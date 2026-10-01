"""BDG 桥（`sidecar/ws.py` + `sidecar/bridge.py`）单测。

三组：

    A 帧层   —— 握手 Accept 向量 / 长度三档 / 客户端掩码 / 分片 / 控制帧 / 上限
    B 协议层 —— 无 socket：hello → project → ack，未知 type 不静默
    C 环回   —— 真 socket 打真 sidecar：握手、114KB 快照（走 64 位长度）、
                token 三态、状态回落

跑法:  python tests/test_bridge.py
"""
import io
import json
import os
import socket
import struct
import sys
import threading
import time
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from sidecar import bridge as BR                            # noqa: E402
from sidecar import server as SV                            # noqa: E402
from sidecar import ws as WS                                # noqa: E402
from core.bdg import roundtrip as RT                        # noqa: E402

FAIL = []
_ROUTE = _ROOT
REAL = os.path.join(_HERE, "fixtures", "bdg", "v2_real_electric_hornet.bdg")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


# ---------------------------------------------------------------- 客户端侧工具
def client_frame(payload: bytes, opcode: int = WS.OP_TEXT, mask: bool = True) -> bytes:
    """客户端帧（**必须加掩码**）。"""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    b0 = 0x80 | opcode
    n = len(payload)
    mbit = 0x80 if mask else 0x00
    if n < 126:
        head = struct.pack("!BB", b0, mbit | n)
    elif n < (1 << 16):
        head = struct.pack("!BBH", b0, mbit | 126, n)
    else:
        head = struct.pack("!BBQ", b0, mbit | 127, n)
    if not mask:
        return head + payload
    key = b"\x37\xfa\x21\x3d"
    body = bytes(c ^ key[i & 3] for i, c in enumerate(payload))
    return head + key + body


def drain(sock, rfile, n=1, timeout=5.0):
    out = []
    for _ in range(n):
        fin, op, data = WS.recv_frame(rfile)
        if op == WS.OP_CLOSE:
            break
        out.append(data.decode("utf-8"))
    return out


# =====================================================================
def A_frames():
    print("=" * 78)
    print("A. 帧层（RFC6455 最小实现）")
    # 规范里的标准向量
    check(WS.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
          "Sec-WebSocket-Accept 标准向量")

    for n in (0, 5, 125, 126, 300, 70000):
        payload = ("x" * n).encode()
        raw = WS.encode(payload, WS.OP_TEXT)
        fin, op, data = WS.recv_frame(io.BytesIO(raw))
        check(fin and op == WS.OP_TEXT and data == payload, f"长度 {n} 字节往返（{len(raw)}B 帧）")

    # 掩码（客户端发的必须解）
    raw = client_frame("你好，BDG", WS.OP_TEXT, mask=True)
    fin, op, data = WS.recv_frame(io.BytesIO(raw))
    check(data.decode("utf-8") == "你好，BDG", "客户端掩码被正确解开")

    # 分片
    frag = WS.encode("前半", WS.OP_TEXT, fin=False) + WS.encode("后半", WS.OP_CONT, fin=True)
    c = WS.Conn(io.BytesIO(frag), io.BytesIO())
    check(c.recv_text() == "前半后半", "分片被拼起来")

    # ping 自动回 pong；close 收场
    out = io.BytesIO()
    c = WS.Conn(io.BytesIO(WS.encode(b"", WS.OP_PING) + WS.encode("hi", WS.OP_TEXT)),
                out)
    msg = c.recv_text()
    fin, op, data = WS.recv_frame(io.BytesIO(out.getvalue()))
    check(msg == "hi" and op == WS.OP_PONG, "ping 自动回 pong，然后继续收文本")

    c = WS.Conn(io.BytesIO(WS.encode(struct.pack("!H", 1000), WS.OP_CLOSE)), io.BytesIO())
    check(c.recv_text() is None and c.closed, "收到 close ⇒ 返回 None 并置关闭位")

    # 上限 / 非法
    try:
        WS.recv_frame(io.BytesIO(bytes([0x81, 0x7A]) + b"short"))
        check(False, "半截帧被拒")
    except WS.WsError as exc:
        check("提前结束" in str(exc), f"半截帧被拒：{exc}")
    big = (WS.MAX_FRAME + 10).to_bytes(8, "big")
    try:
        WS.recv_frame(io.BytesIO(bytes([0x81, 127]) + big))
        check(False, "超大帧被拒")
    except WS.WsError as exc:
        check("过大" in str(exc), f"超大帧被拒：{exc}")
    try:
        WS.recv_frame(io.BytesIO(bytes([0xC1, 0x00])))
        check(False, "RSV 位被拒")
    except WS.WsError as exc:
        check("RSV" in str(exc), f"RSV 位被拒：{exc}")

    check(WS.token_ok("abc", "abc") and not WS.token_ok("abc", "abd")
          and not WS.token_ok("", ""), "token 比较：相等才过，空值必拒")
    check(len(WS.new_token()) >= 20, f"一次性 token 长度 {len(WS.new_token())}")


def B_protocol():
    print("=" * 78)
    print("B. 协议层（无 socket）")
    br = BR.Bridge(app=None, token="T")

    # 没握手就说话
    r = json.loads(br.handle_text(json.dumps({"v": 1, "type": "project",
                                              "project": {}}))[0])
    check(r["type"] == BR.OUT_FAILED and "hello" in r["error"],
          "未握手 ⇒ failed（并让对端先 hello）")
    check(br.should_close, "未握手说话 ⇒ 标记收场")

    # 握手
    br = BR.Bridge(app=None, token="T")
    r = json.loads(br.handle_text(json.dumps(
        {"v": 1, "type": "hello", "plugin": "0.1.0", "bdg": "2",
         "caps": {"loop": True, "typedTracks": True}}))[0])
    check(r["type"] == BR.OUT_ACCEPTED and r["accepted"] == [1],
          f"hello ⇒ accepted{ r['accepted'] }")
    check(br.authed and br.peer["plugin"] == "0.1.0", "对端信息记下来了")

    # ping 不需要握手
    r = json.loads(br.handle_text(json.dumps({"type": "ping"}))[0])
    check(r["type"] == BR.OUT_PONG, "ping ⇒ pong")

    # project（真工程）
    with open(REAL, "rb") as f:
        raw = json.loads(f.read().decode("utf-8"))
    a = json.loads(br.handle_text(json.dumps({"type": "project", "project": raw}))[0])
    check(a["type"] == BR.OUT_ACK and a["ok"] is True, f"project ⇒ ack ok（{a.get('parse')}）")
    check(a["n_tracks"] == 6 and a["n_points"] == 866, "回执给出 6 轨 / 866 点")
    check(a["n_bpm_events"] == 2 and a["dup_beats"] == 232, "回执给出真变速 2 / 重复拍 232")
    check(a["can_emit"] is True and a["parser"] == "standard", "回执说明可写回")
    check(br.last_project is not None and br.state()["n_points"] == 866, "状态已更新")

    # 空快照 ⇒ 不 ok（不许静默当成功）
    a2 = json.loads(br.handle_text(json.dumps({"type": "project", "project": {}}))[0])
    check(a2["ok"] is False and a2["error"], f"空快照 ⇒ ack ok=False（{a2.get('error')}）")

    # 未知 type 不静默
    a3 = json.loads(br.handle_text(json.dumps({"type": "啥东西"}))[0])
    check(a3["ok"] is False and "未知" in a3["error"], "未知 type ⇒ ack ok=False + 记账")
    check(any("啥东西" in w for w in br.warns), "未知 type 写进 warns")

    # 坏 JSON
    a4 = json.loads(br.handle_text("{oops")[0])
    check(a4["ok"] is False, "坏 JSON ⇒ ack ok=False")

    # 其他入站
    check(json.loads(br.handle_text(json.dumps(
        {"type": "selection", "kind": "markers", "markerIds": ["a", "b"]}))[0])["n"] == 2,
        "selection ⇒ ack n=2")
    check(json.loads(br.handle_text(json.dumps({"type": "playhead", "beat": 12.5}))[0])["ok"]
          and br.playhead == 12.5, "playhead 被记住")
    bad_audio = json.loads(br.handle_text(json.dumps({"type": "audio", "name": "x"}))[0])
    check(bad_audio["ok"] is False, "audio 没有 path ⇒ ok=False")
    ok_audio = json.loads(br.handle_text(json.dumps(
        {"type": "audio", "path": "/tmp/x.ogg", "md5": "abc"}))[0])
    check(ok_audio["ok"] and br.audio["md5"] == "abc", "audio ⇒ 记住 path/md5")

    # 出站消息形状
    for text, kind in ((br.pull_msg(), "pull"), (br.import_msg(tracks=[{"a": 1}]), "import")):
        m = json.loads(text)
        check(m["v"] == 1 and m["type"] == kind and isinstance(m["seq"], int)
              and "ts" in m, f"出站 {kind} 信封完整（v/type/seq/ts）")

    st = br.state()
    check(st["authed"] and st["peer"]["bdg"] == "2" and st["projects"] == 2,
          f"state() 可读：{st['n_points']} 点 / {st['stats']['msgs_in']} 条入站")
    check(br.token == "T" and br.url("127.0.0.1", 8765).endswith("token=T"),
          f"连接串：{br.url('127.0.0.1', 8765)}")


class QuietServer(ThreadingHTTPServer):
    """关连接时 socketserver 会往 stderr 喷栈，测试里不需要。"""

    def handle_error(self, request, client_address):        # noqa: D102
        pass


def C_loopback():
    print("=" * 78)
    print("C. 环回：真 socket 打真 sidecar")
    SV.APP = SV.App(_ROUTE)
    srv = QuietServer(("127.0.0.1", 0), SV.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1},
                     daemon=True).start()
    host, port = srv.server_address[:2]
    time.sleep(0.15)

    def connect(token):
        s = socket.create_connection((host, port), timeout=15)
        rf = s.makefile("rb")
        return s, rf

    # (1) 非升级请求
    s, rf = connect("x")
    s.sendall(f"GET /ws HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    head = rf.readline().decode()
    check("400" in head, f"普通 GET /ws ⇒ {head.strip()}")

    # (2) token 错
    s, rf = connect("x")
    s.sendall(("GET /ws?token=WRONG HTTP/1.1\r\nHost: x\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n").encode())
    head = rf.readline().decode()
    check("403" in head, f"token 不匹配 ⇒ {head.strip()}")
    s.close()

    # (3) 正常握手
    tok = SV.APP.bridge.token
    s, rf = connect(tok)
    s.sendall((f"GET /ws?token={tok} HTTP/1.1\r\nHost: x\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n").encode())
    head = rf.readline().decode()
    hdr = {}
    while True:
        line = rf.readline().decode()
        if line in ("\r\n", "\n", ""):
            break
        k, _, v = line.partition(":")
        hdr[k.strip().lower()] = v.strip()
    check("101" in head, f"握手成功 ⇒ {head.strip()}")
    check(hdr.get("sec-websocket-accept") == WS.accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
          "Accept 头正确")

    # hello
    s.sendall(client_frame(json.dumps({"v": 1, "type": "hello", "plugin": "0.1.0",
                                       "bdg": "2"})))
    m = json.loads(drain(s, rf)[0])
    check(m["type"] == "accepted" and m["accepted"] == [1], "hello ⇒ accepted")

    # project：真实 114KB 工程（>65536 ⇒ 服务端要写 64 位长度的帧）
    with open(REAL, "rb") as f:
        raw = json.loads(f.read().decode("utf-8"))
    body = json.dumps({"v": 1, "type": "project", "project": raw}, ensure_ascii=False)
    check(len(body) > 70000, f"快照消息 {len(body)} 字节（走 64 位长度档）")
    s.sendall(client_frame(body))
    a = json.loads(drain(s, rf)[0])
    check(a["type"] == "ack" and a["ok"] and a["n_points"] == 866,
          f"真 socket 收到回执：{a['n_tracks']} 轨 / {a['n_points']} 点")

    # ping 往返
    s.sendall(client_frame("", WS.OP_PING))
    fin, op, data = WS.recv_frame(rf)
    check(op == WS.OP_PONG, "真 socket ping ⇒ pong")

    # 未知 type 也不静默
    s.sendall(client_frame(json.dumps({"type": "nope"})))
    a2 = json.loads(drain(s, rf)[0])
    check(a2["ok"] is False, "真 socket：未知 type ⇒ ok=False")

    # 关掉 ⇒ 服务端状态回落
    s.sendall(client_frame(struct.pack("!H", 1000), WS.OP_CLOSE))
    time.sleep(0.4)
    check(SV.APP.bridge.state()["connected"] is False, "断开后 connected 回落 False")
    check(SV.APP.bridge.stats["rejected"] == 1, f"被拒计数 = {SV.APP.bridge.stats['rejected']}")
    s.close()

    # /api/bridge 暴露连接串（GUI 用它显示）
    import urllib.request
    with urllib.request.urlopen(f"http://{host}:{port}/api/bridge", timeout=10) as r:
        j = json.loads(r.read().decode("utf-8"))
    check(j["ok"] and j["token"] == tok and j["url"].startswith("ws://127.0.0.1:"),
          f"GET /api/bridge ⇒ {j['url']}")

    srv.shutdown()
    srv.server_close()


def K_plugin_capture():
    print("=" * 78)
    print("K. 插件真发出来的消息 ⇄ 我们真服务端（跨语言线格式复验）")
    cap_path = os.path.join(_HERE, "fixtures", "bdg", "_bridge_capture.json")
    if not os.path.exists(cap_path):
        check(False, "缺 line-format 抓取：先跑 `node tools/_bdg_plugin_test.js`")
        return
    with open(cap_path, "r", encoding="utf-8") as f:
        cap = json.load(f)

    br = BR.Bridge(app=None, token="T")
    r = json.loads(br.handle_text(json.dumps(cap["hello"]))[0])
    check(r["type"] == BR.OUT_ACCEPTED, f"插件的 hello ⇒ {r['type']}")

    a = json.loads(br.handle_text(json.dumps(cap["project"]))[0])
    check(a["type"] == "ack" and a["ok"] is True,
          f"插件的 project ⇒ ack ok（{a.get('parse')}）")
    check(a["n_tracks"] == 6 and a["n_points"] == 866,
          f"服务端解出 {a['n_tracks']} 轨 / {a['n_points']} 点")
    check(a["parser"] == "snapshot",
          f"★ 认出这是插件快照（无版本号）：parser={a['parser']}")
    check(a["dup_beats"] == 232 and a["n_bpm_events"] == 2,
          f"重复拍 {a['dup_beats']} / 插件轨变速 {a['n_bpm_events']}")
    check(a["can_emit"] is False, "快照本来就不写回（can_emit=False 是正常的）")
    check(not any("未知格式版本" in w for w in a.get("warn_list", [])),
          f"没有「未知版本」误报：{a.get('warn_list')}")

    p = br.last_project
    check(p is not None and abs(p.tempo.time_of_beat(0.0) - p.offset_ms) < 1e-9,
          "服务端用宿主锚点建表（time_of_beat(0)=offsetMs）")
    check(all(not x.synth for x in p.points), "插件快照里循环子点已存在 ⇒ 不用补")

    for k in ("audio", "selection", "playhead"):
        msg = cap.get(k)
        if not msg:
            check(False, f"抓取里缺 {k}")
            continue
        rr = json.loads(br.handle_text(json.dumps(msg))[0])
        check(rr.get("ok") is True, f"插件发的 {k} 被真服务端接受")
    check(br.audio and br.audio["path"].endswith(".ogg"),
          f"音频路径记下来了：{br.audio and br.audio['path']}")
    check(br.playhead is not None and br.selection is not None, "播放头 / 选区都记下来了")


def L_import_adopt():
    print("=" * 78)
    print("L. 投射 / 收回（docs/38）：import → 对账 → adopt 回毫秒")
    from core.bdg import aliases as al

    class FakeConn:
        """假连接：把服务端发出去的东西收下来。"""
        def __init__(self):
            self.out = []
            self.closed = False

        def send_text(self, t):
            self.out.append(json.loads(t))

    br = BR.Bridge(app=None, token="T")
    br.conn = FakeConn()
    br.authed = True
    br.handle_text(json.dumps({"type": "hello", "v": 1, "plugin": "0.1.0"}))

    # 先喂一份真快照当「他的时间锚」（120bpm、offset 0）
    snap = {
        "name": "rt", "baseBpm": 120.0, "offsetMs": 0.0, "audioName": None,
        "audioMd5": None, "bpmLocked": False, "bpmPoints": [],
        "tracks": [{"id": "t1", "name": "n", "color": "#fff", "locked": False,
                    "hidden": False, "type": "beat"}],
        "markers": [],
    }
    br.handle_text(json.dumps({"type": "project", "project": snap}))
    check(br.tempo() is not None, "拿到他的 tempo 当换算器")

    # 投射：给毫秒，用它反解 beat
    out = br.push_import([{"ms": 0.0, "role": "main"}, {"ms": 250.0, "role": "main"},
                          {"ms": 500.0, "role": "dp"}], src="test")
    check(out["ok"] and out["n"] == 3, f"投射 3 点：{out.get('n')}")
    check(out["beats"] == [0.0, 0.5, 1.0], f"毫秒→拍位 = {out['beats']}（120bpm：250ms = 0.5 拍）")
    imp = br.conn.out[-1]
    check(imp["type"] == "import" and imp["n_onsets"] == 3, "发出去的是 import 载荷")
    check([t["role"] for t in imp["tracks"]] == ["main", "dp"], "按角色分了轨")
    check(all("bpmPoints" not in imp and "baseBpm" not in imp for _ in [0]),
          "★ 不动他的 BPM 锚")

    # 收回：伪造「用户删了一个、移了一个、加了一个」的快照
    tags = {t["role"]: t for t in imp["tracks"]}
    A = tags["main"]["onsets"][0]["attrs"]
    B = tags["main"]["onsets"][1]["attrs"]
    C = tags["dp"]["onsets"][0]["attrs"]
    back = {
        "name": "rt", "baseBpm": 120.0, "offsetMs": 0.0, "bpmPoints": [],
        "tracks": [{"id": "t1", "name": "n", "color": "#fff", "locked": False,
                    "hidden": False, "type": "beat"},
                   {"id": "tm", "name": "main", "color": "#fff", "locked": False,
                    "hidden": False, "type": "dev.adocharter.bdg-bridge:main"},
                   {"id": "td", "name": "dp", "color": "#fff", "locked": False,
                    "hidden": False, "type": "dev.adocharter.bdg-bridge:dp"}],
        "markers": [
            {"id": "m1", "trackId": "tm", "beat": 0.0, "timeMs": 0.0, "attrs": A},
            {"id": "m2", "trackId": "tm", "beat": 0.5, "timeMs": 250.0, "attrs": B},
            # C（dp 那个 1.0）被删了
            {"id": "m3", "trackId": "tm", "beat": 2.0, "timeMs": 1000.0},   # 用户新加
        ],
    }
    br.handle_text(json.dumps({"type": "project", "project": back}))
    d = br.diff()
    check(d is not None, "拿到对账")
    check(d["counts"][al.EDIT_KEPT] == 2, f"留下 2：{d['counts']}")
    check(d["counts"][al.EDIT_DELETED] == 1, f"删除 1：{d['counts']}")
    check(d["n_added"] == 1, f"新增 1：{d['n_added']}")

    ad = br.adopt()
    check(ad["ok"] and len(ad["onsets"]) == 3, f"收回 {len(ad.get('onsets', []))} 个音")
    ms = [round(o["ms"], 3) for o in ad["onsets"]]
    check(ms == [0.0, 250.0, 1000.0], f"★ 收回来的毫秒（含用户新增的 2 拍=1000ms）：{ms}")
    check(all("role" in o for o in ad["onsets"]), "每个音带角色")
    check("对账" in ad["report"], f"报告可读：{ad['report'].splitlines()[0]}")

    # 吸附形态：偏移都落在 1/4 网格上就该被判出来
    br2 = BR.Bridge(app=None, token="T")
    br2.conn = FakeConn()
    br2.authed = True
    br2.handle_text(json.dumps({"type": "hello", "v": 1, "plugin": "0.1.0"}))
    br2.handle_text(json.dumps({"type": "project", "project": snap}))
    br2.push_import([{"ms": 0.0, "role": "main"}, {"ms": 310.0, "role": "main"}])
    imp2 = br2.conn.out[-1]
    ons2 = imp2["tracks"][0]["onsets"]
    snapped = {
        "name": "rt", "baseBpm": 120.0, "offsetMs": 0.0, "bpmPoints": [],
        "tracks": [{"id": "tm", "name": "m", "color": "#fff", "locked": False,
                    "hidden": False, "type": "dev.adocharter.bdg-bridge:main"}],
        "markers": [
            {"id": "s1", "trackId": "tm", "beat": 0.0, "timeMs": 0.0,
             "attrs": ons2[0]["attrs"]},
            {"id": "s2", "trackId": "tm", "beat": 0.75, "timeMs": 375.0,
             "attrs": ons2[1]["attrs"]},        # 0.62 → 0.75（吸到 1/4 网格）
        ],
    }
    br2.handle_text(json.dumps({"type": "project", "project": snapped}))
    d2 = br2.diff()
    check(d2["snap_suspect"] and d2["snap_div"] == 4,
          f"★ 吸附被抓出来：div=1/{d2['snap_div']}，最大 {d2['drift_max_ms']}ms")
    check(d2["drift_over"] == 1, f"超 25ms 预算 {d2['drift_over']} 个")

    # 没连桥时不许假装成功
    br3 = BR.Bridge(app=None, token="T")
    check(br3.push_import([{"ms": 0.0}])["ok"] is False, "没连桥 ⇒ 明确失败（不静默）")
    check(br3.adopt()["ok"] is False, "没投送过 ⇒ 收回明确失败")


def M_role_points():
    """★ 分段采音的自动填充：BDG 角色轨上的点 → `core.segments`（`docs/38` §10）。"""
    print("=" * 78)
    print("M. 角色轨上的点 → 分段（docs/34 方案 C 的自动填充）")
    from core import segments as SG

    class FakeConn2:
        def __init__(self):
            self.out = []
            self.closed = False

        def send_text(self, t):
            self.out.append(json.loads(t))

    br = BR.Bridge(app=None, token="T")
    br.conn = FakeConn2()
    br.authed = True
    br.handle_text(json.dumps({"type": "hello", "v": 1, "plugin": "0.1.0"}))
    # 120bpm、offset 0 ⇒ 1 拍 = 500ms
    snap = {
        "name": "rp", "baseBpm": 120.0, "offsetMs": 0.0,
        "bpmPoints": [], "audioMd5": None, "bpmLocked": False, "audioName": None,
        "tracks": [
            {"id": "t0", "name": "beat", "color": "#fff", "locked": False,
             "hidden": False, "type": "beat"},
            {"id": "tm", "name": "main", "color": "#fff", "locked": False,
             "hidden": False, "type": "dev.adocharter.bdg-bridge:main"},
            {"id": "ts", "name": "sub", "color": "#fff", "locked": False,
             "hidden": False, "type": "dev.adocharter.bdg-bridge:sub"},
            {"id": "tx", "name": "bpm", "color": "#fff", "locked": False,
             "hidden": False, "type": "dev.bdg.adofai-export:bpm"},
        ],
        "markers": [
            {"id": "a", "trackId": "tm", "beat": 2.0, "timeMs": 1000.0},
            {"id": "b", "trackId": "tm", "beat": 6.0, "timeMs": 3000.0},
            {"id": "c", "trackId": "ts", "beat": 4.0, "timeMs": 2000.0},
            {"id": "d", "trackId": "t0", "beat": 1.0, "timeMs": 500.0},   # 普通踩点轨
            {"id": "e", "trackId": "tx", "beat": 5.0, "timeMs": 2500.0},  # bpm 轨 = 关
        ],
    }
    br.handle_text(json.dumps({"type": "project", "project": snap}))

    pts = br.role_points()
    check(len(pts) == 3,
          f"★ 只认**我们插件**的角色轨：内置踩点轨（beat）与宿主 bpm 控制轨都不算"
          f"（实得 {len(pts)} 个）")
    check([p["track"] for p in pts] == [1, 2, 1],
          f"带 BDG 侧轨下标（与 to_midi_like 的 enumerate 一一对应）{[p['track'] for p in pts]}")
    check([round(p["at_ms"], 1) for p in pts] == [1000.0, 2000.0, 3000.0],
          f"拍位用它自己的锚换成了毫秒、并按时刻排好 {[round(p['at_ms'], 1) for p in pts]}")
    check(all(p["role"] in SG.ROLES for p in pts), "角色全在合法词表里")
    check([p["role"] for p in pts] == ["main", "sub", "main"],
          "★ 内置轨（role=main）没混进来 —— 否则每条普通轨都会凭空生成分段")

    pay = br.segments_payload()
    check(pay["ok"] and pay["n"] == 2 and pay["n_points"] == 3,
          f"★ 3 个点 → 2 条分段：3000ms 那个（trk1 又是 main，净效果没变）被省掉"
          f"（实得 {pay.get('n')} 条 / {pay.get('n_points')} 点）")
    check(pay["mode"] == SG.MODE_FROM, "默认「从这点起」口径")
    j = pay["segments"]
    check([x["at_ms"] for x in j] == [1000.0, 2000.0],
          f"按时刻排序 {[x['at_ms'] for x in j]}")
    check(j[0]["main"] == [1] and j[0]["sub"] is None and j[0]["dp"] is None,
          f"★ 1000ms（只有主轨点）：次/双押留 None 继承全局 —— 实得 {j[0]}")
    check(j[1]["main"] == [1] and j[1]["sub"] == [2] and j[1]["dp"] is None,
          f"★ 累计快照（2000ms 才第一次出现 sub）：{j[1]}")
    check(all(x["dp"] is None for x in j),
          "dp 从没出现过 ⇒ 每条里都是 None（不静默清空）")
    check("从这点起" in pay["report"] and "分段：2 段" in pay["report"],
          f"报告可读：{pay['report'].splitlines()[0]}")

    # 没有角色轨 ⇒ 明确说不行（不静默）
    br4 = BR.Bridge(app=None, token="T")
    br4.conn = FakeConn2()
    br4.authed = True
    br4.handle_text(json.dumps({"type": "hello", "v": 1, "plugin": "0.1.0"}))
    br4.handle_text(json.dumps({"type": "project", "project": snap}))
    br4.handle_text(json.dumps({"type": "project", "project": {
        "name": "x", "baseBpm": 120.0, "offsetMs": 0.0, "bpmPoints": [],
        "tracks": [{"id": "t0", "name": "b", "color": "#f", "locked": False,
                    "hidden": False, "type": "beat"}],
        "markers": [{"id": "z", "trackId": "t0", "beat": 1.0, "timeMs": 500.0}],
    }}))
    p4 = br4.segments_payload()
    check(p4["ok"] is False and "角色轨" in p4["error"], f"没有角色轨 ⇒ 明确失败：{p4.get('error')}")
    br5 = BR.Bridge(app=None, token="T")
    check(br5.segments_payload()["ok"] is False, "没拿到快照 ⇒ 明确失败")


def N_tracks_back():
    """★ 收回（`type:"tracks"`，`docs/45`）：插件那个按钮发来的东西我们认不认。"""
    print("=" * 78)
    print("N. 收回：带时值数据的轨道 → 我们的音轨项目")

    class FakeSess:
        def __init__(self):
            self.pay = None

        def restore_tracks(self, payload):
            self.pay = payload
            lanes = RT.back_lanes(payload)
            return {"ok": True,
                    "meta": {"n_lanes": len(lanes), "n_onsets": 3, "n_dup": 1},
                    "text": "[收回] {} 轨".format(len(lanes)),
                    "info": {"tracks": [{"index": 0}], "lanes_back": True}}

    class FakeApp:
        def __init__(self):
            self.session = FakeSess()
            self.broker = None
            self.root = "X"

    app = FakeApp()
    br = BR.Bridge(app=app, token="T")
    br.handle_text(json.dumps({"type": "hello", "v": 1, "plugin": "0.1.0"}))
    msg = {"type": "tracks", "run": "R1",
           "anchor": {"baseBpm": 400.0, "offsetMs": 0.0},
           "n_points": 2, "n_added": 0,
           "tracks": [{"name": "ADO·主轨 trk0", "role": "main", "lane": "main:0",
                       "src_track": 0,
                       "points": [{"idx": 0, "beat": 0.0, "ms": 100.0,
                                   "src_tracks": [0]},
                                  {"idx": 1, "beat": 4.0, "ms": 250.0,
                                   "src_tracks": [0]}]}]}
    a = json.loads(br.handle_text(json.dumps(msg))[0])
    check(a.get("ok") and a.get("n_tracks") == 1, f"回执认这条消息：{a}")
    check(app.session.pay is not None and app.session.pay["run"] == "R1",
          "载荷原样交给了 session（它负责落地）")
    check(a.get("n_onsets") == 3 and a.get("n_dup") == 1,
          "回执里带上落地结果（点数/合并数）")
    check(len(br.back_lanes) == 1 and br.state()["back"]["n_lanes"] == 1,
          "桥自己也留一份（面板/状态栏要看得到）")
    check(br.stats["backs"] == 1, "计数 +1")

    a2 = json.loads(br.handle_text(json.dumps({"type": "tracks", "tracks": []}))[0])
    check(a2.get("ok") is False and a2.get("error"), "空载荷明确失败（不静默）")

    br2 = BR.Bridge(app=None, token="T")
    br2.handle_text(json.dumps({"type": "hello", "v": 1}))
    a3 = json.loads(br2.handle_text(json.dumps(msg))[0])
    check(a3.get("ok") and a3.get("n_tracks") == 1,
          "没有 session 时也回执（不因为落地不了就丢消息）")
    check(any("session" in w for w in br2.warns), "warns 里说明了原因")

    # ★ 插件**真正发出去的那条**（tools/_bdg_plugin_test.js 抓的）也要能吃掉
    cap_path = os.path.join(_HERE, "fixtures", "bdg", "_bridge_capture.json")
    if os.path.exists(cap_path):
        cap = json.load(open(cap_path, encoding="utf-8"))
        if cap.get("back"):
            br3 = BR.Bridge(app=FakeApp(), token="T")
            br3.handle_text(json.dumps({"type": "hello", "v": 1, "plugin": "0.1.0"}))
            a4 = json.loads(br3.handle_text(json.dumps(cap["back"]))[0])
            check(a4.get("ok") and a4.get("n_tracks") >= 1,
                  f"★ 插件抓包那条 tracks 服务端能吃（{a4.get('n_tracks')} 轨）")
        else:
            check(False, "抓包里没有 back（先跑 node tools/_bdg_plugin_test.js）")
    else:
        check(False, "没有抓包文件（先跑 node tools/_bdg_plugin_test.js）")


def O_grid_probe():
    """★ 网格探测（`type:"grid"`，`docs/45` §7）：插件拿到裸时间戳时问我们要格子。"""
    print("=" * 78)
    print("O. 网格探测：插件拿裸时间戳来问 bpm/相位/分母")

    br = BR.Bridge(app=None, token="T")
    br.handle_text(json.dumps({"type": "hello", "v": 1}))
    ts = [round(2.131 + k * 150.0, 3) for k in range(48)]
    a = json.loads(br.handle_text(json.dumps({"type": "grid", "times": ts}))[0])
    check(a.get("ok") and a.get("kind") == "grid", f"回执认得这条消息：{str(a)[:90]}")
    check(abs(float(a.get("bpm", 0)) - 400.0) < 0.5,
          f"砖长 150ms ⇒ bpm≈400（实得 {a.get('bpm')}）")
    check(int(a.get("div", 0)) in (1, 2, 4, 8, 16, 32),
          f"分母落在宿主档位上：1/{a.get('div')}")
    step = float(a.get("step", 0))
    off = float(a.get("offsetMs", 0))
    bad = [t for t in ts if abs(t - (off + round((t - off) / step) * step)) > 1e-6]
    check(not bad, f"★ 回给插件的相位/格，能让**所有点**落在 k/div 上（{len(bad)} 个不落）")
    check(br.stats.get("grids") == 1, "计数 +1")
    check(any("置信度" in str(n) for n in (a.get("grid") or {}).get("notes", [])),
          "报告里带置信度（格级 + 拍级）")

    b = json.loads(br.handle_text(json.dumps({"type": "grid", "times": [1.0]}))[0])
    check(b.get("ok") is False and b.get("kind") == "grid",
          "点太少 ⇒ 明确失败：" + str(b.get("error"))[:40])
    c = json.loads(br.handle_text(json.dumps({"type": "grid"}))[0])
    check(c.get("ok") is False, "没带 times ⇒ 明确失败（不静默）")
    d = json.loads(br.handle_text(json.dumps({"type": "grid",
                                              "times": ["a", "b"]}))[0])
    check(d.get("ok") is False, "非数字 ⇒ 明确失败")
    # 信封占用了 ts（发送时刻）⇒ 我们的数组键名必须是 times（插件单测抓过一次）
    e = json.loads(br.handle_text(json.dumps({"type": "grid", "ts": 1789.0,
                                              "times": ts[:12]}))[0])
    check(e.get("ok") is True, "信封的 ts 在也不会干扰（我们读 times）")


def main():
    A_frames()
    B_protocol()
    C_loopback()
    K_plugin_capture()
    L_import_adopt()
    M_role_points()
    N_tracks_back()
    O_grid_probe()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ BDG 桥全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
