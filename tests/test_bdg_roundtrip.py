"""往返对账单测（`docs/38` 验收线 1-8）。

    python tests/test_bdg_roundtrip.py

不碰网络、不碰宿主：喂「我们投送的 onsets」+「伪造的收回快照」，验四类编辑能不能判对。
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import bdg                                     # noqa: E402
from core.bdg import aliases as al                        # noqa: E402
from core.bdg import roundtrip as RT                      # noqa: E402

FAIL = []
P = "dev.adocharter.bdg-bridge"


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _mk_snapshot(pts, roles=(al.ROLE_MAIN, al.ROLE_SUB, al.ROLE_DP, al.ROLE_OFF)):
    """伪造一份 BDG 快照：`pts` = [(role, beat, attrs or None)]。"""
    tracks = [{"id": "t_" + r, "name": "T_" + r, "color": "#fff", "locked": False,
               "hidden": False, "type": P + ":" + r} for r in roles]
    markers = []
    for i, (role, beat, attrs) in enumerate(pts):
        m = {"id": "m%d" % i, "trackId": "t_" + role, "beat": beat,
             "timeMs": round(beat * 500.0, 6)}      # 120bpm ⇒ 1 拍 = 500ms（跟真的快照一样自带）
        if attrs:
            m["attrs"] = attrs
        markers.append(m)
    return {"name": "rt", "baseBpm": 120.0, "offsetMs": 0.0, "audioName": None,
            "audioMd5": None, "bpmLocked": False, "tracks": tracks,
            "markers": markers, "bpmPoints": []}


def A_build_import():
    print("=" * 78)
    print("A. 投射载荷（docs/38 §3.1）")
    sent = [RT.Sent(0, 0.0, al.ROLE_MAIN), RT.Sent(1, 1.0064, al.ROLE_MAIN),
            RT.Sent(2, 2.01, al.ROLE_DP)]
    payload = RT.build_import(sent, "RUN1")
    check(payload["run"] == "RUN1" and payload["n_onsets"] == 3, "批次号 + 点数")
    check([t["role"] for t in payload["tracks"]] == [al.ROLE_MAIN, al.ROLE_DP],
          "只带用到的角色轨")
    a = payload["tracks"][0]["onsets"][1]["attrs"]
    check(a[al.SYNC_IDX[0]] == 1 and a[al.SYNC_RUN[0]] == "RUN1"
          and a[al.SYNC_ROLE[0]] == al.ROLE_MAIN, f"对账标记写进了 attrs：{a}")
    check("bpmPoints" not in payload,
          "★ 载荷里**没有** bpmPoints（变速仍然是他的地盘，`docs/41` #3 暂不修）")
    check(al.K_BASE_BPM not in payload,
          "★ 不传锚时**一个锚字段都不加**（老载荷逐字节不变）")
    check(payload["tracks"][0]["name"] == al.ROLE_NAME[al.ROLE_MAIN],
          f"轨名 = {payload['tracks'][0]['name']}")
    check(all(al.K_MS not in o for o in payload["tracks"][0]["onsets"]),
          "★ 没给 ms 就不发 ms（旧路径不变）")

    # ★★ 把**我们的时序锚**和每个点的**毫秒**一起发（docs/41 #2）
    sent2 = [RT.Sent(0, 0.0, al.ROLE_MAIN, "app", 1000.0),
             RT.Sent(1, 1.0, al.ROLE_MAIN, "app", 1333.333333)]
    p2 = RT.build_import(sent2, "RUN2", base_bpm=180.0, offset_ms=1000.0)
    check(p2[al.K_BASE_BPM] == 180.0 and p2[al.K_OFFSET_MS] == 1000.0,
          f"★ 载荷带上我们的锚：baseBpm={p2.get(al.K_BASE_BPM)} "
          f"offsetMs={p2.get(al.K_OFFSET_MS)}")
    o0 = p2["tracks"][0]["onsets"][0]
    check(o0[al.K_MS] == 1000.0 and o0[al.K_BEAT] == 0.0,
          f"★ 每个点既带 ms 也带 beat（新插件用 ms 换算、老插件回退用 beat）：{o0}")
    check(p2["tracks"][0]["onsets"][1][al.K_MS] == 1333.333333,
          "ms 保留 6 位小数（不在这里丢精度）")
    # 只传 bpm 不传 offset ⇒ offsetMs 也要在（0 是有效值）
    p3 = RT.build_import(sent2, "RUN3", base_bpm=180.0)
    check(p3[al.K_OFFSET_MS] == 0.0, "只给 bpm 时 offsetMs 也发（0 是有效值，不能缺）")
    # dict 形式的 onset 也认
    p4 = RT.build_import([{"idx": 7, "beat": 1.5, "role": al.ROLE_MAIN,
                           "ms": 2500.0}], "RUN4")
    check(p4["tracks"][0]["onsets"][0][al.K_MS] == 2500.0, "dict 形式的 ms 也带上")


def A2_lanes():
    print("=" * 78)
    print("A2. ★ 分泳道（docs/42）：按**源轨**分轨 + 双押单开一条")
    # ① 单源轨 ⇒ **不加后缀**（单轨工程的布局与老版本逐字节一致）
    one = [RT.Sent(0, 0.0, al.ROLE_MAIN, "app", 0.0, (3,)),
           RT.Sent(1, 1.0, al.ROLE_MAIN, "app", 500.0, (3,))]
    p1 = RT.build_import(one, "L1")
    check(p1[al.K_N_LANES] == 1 and len(p1[al.K_TRACKS]) == 1, "单源轨 ⇒ 1 条泳道")
    check(p1[al.K_TRACKS][0][al.K_NAME] == al.ROLE_NAME[al.ROLE_MAIN],
          f"★ 单源轨不加后缀（保持老名字）：{p1[al.K_TRACKS][0][al.K_NAME]}")
    check(p1[al.K_TRACKS][0][al.K_LANE] == f"{al.ROLE_MAIN}:3",
          f"泳道键是 <role>:<源轨>：{p1[al.K_TRACKS][0][al.K_LANE]}")
    a0 = p1[al.K_TRACKS][0][al.K_ONSETS][0][al.K_ATTRS]
    check(a0[al.SYNC_TRACK[0]] == 3, f"★ attrs 里备注了源轨：{a0.get(al.SYNC_TRACK[0])}")
    check(al.SYNC_TRACKS[0] not in a0, "单轨簇不写 adbTracks（只有跨轨才写）")

    # ② 多源轨 ⇒ 一个源轨一条泳道，名字带 trk 后缀
    many = [RT.Sent(0, 0.0, al.ROLE_MAIN, "app", 0.0, (0,)),
            RT.Sent(1, 1.0, al.ROLE_MAIN, "app", 500.0, (1,)),
            RT.Sent(2, 2.0, al.ROLE_MAIN, "app", 1000.0, (0,)),
            RT.Sent(3, 3.0, al.ROLE_MAIN, "app", 1500.0, (2,))]
    p2 = RT.build_import(many, "L2")
    names = [t[al.K_NAME] for t in p2[al.K_TRACKS]]
    check(p2[al.K_N_LANES] == 3, f"3 条源轨 ⇒ 3 条泳道（实得 {p2[al.K_N_LANES]}）")
    check(names == [f"{al.ROLE_NAME[al.ROLE_MAIN]} trk0",
                    f"{al.ROLE_NAME[al.ROLE_MAIN]} trk1",
                    f"{al.ROLE_NAME[al.ROLE_MAIN]} trk2"],
          f"★ 多源轨才加 trk 后缀：{names}")
    cnt = [len(t[al.K_ONSETS]) for t in p2[al.K_TRACKS]]
    check(cnt == [2, 1, 1], f"每个音进了**自己那条**源轨的泳道：{cnt}")
    check(sum(cnt) == p2["n_onsets"] == 4, "一个音不丢")

    # ③ 双押 ⇒ **单开一条**，不管它来自几条源轨
    dp = [RT.Sent(0, 0.0, al.ROLE_MAIN, "app", 0.0, (0,)),
          RT.Sent(1, 1.0, al.ROLE_DP, "app", 500.0, (0,)),
          RT.Sent(2, 2.0, al.ROLE_DP, "app", 1000.0, (1,)),
          RT.Sent(3, 3.0, al.ROLE_DP, "app", 1500.0, (5,))]
    p3 = RT.build_import(dp, "L3")
    lanes = {t[al.K_LANE]: t for t in p3[al.K_TRACKS]}
    check(len(lanes) == 2, f"main 1 条 + dp 1 条 = 2（实得 {len(lanes)}）")
    dplane = lanes[al.ROLE_DP + ":"]
    check(dplane is not None, f"★ 双押泳道键不带源轨维：{list(lanes)}")
    check(dplane[al.K_NAME] == al.ROLE_NAME[al.ROLE_DP],
          f"★ 双押单开一条、不带 trk 后缀：{dplane[al.K_NAME]}")
    check(len(dplane[al.K_ONSETS]) == 3,
          f"★ 来自 3 条不同源轨的双押**合并进同一条**：{len(dplane[al.K_ONSETS])}")
    check(all(o[al.K_ATTRS][al.SYNC_ROLE[0]] == al.ROLE_DP
              for o in dplane[al.K_ONSETS]), "双押点的角色标记是 dp（收回时认得出）")

    # ④ 跨轨簇 ⇒ 归到最早那条，但**全部源轨都记下来**，并报 n_cross_track
    cross = [RT.Sent(0, 0.0, al.ROLE_MAIN, "app", 0.0, (2, 5)),
             RT.Sent(1, 1.0, al.ROLE_MAIN, "app", 500.0, (5,))]
    p4 = RT.build_import(cross, "L4")
    lanes4 = {t[al.K_LANE]: t for t in p4[al.K_TRACKS]}
    check(f"{al.ROLE_MAIN}:2" in lanes4 and f"{al.ROLE_MAIN}:5" in lanes4,
          f"跨轨簇归到**最早**那条（trk2）：{list(lanes4)}")
    ax = lanes4[f"{al.ROLE_MAIN}:2"][al.K_ONSETS][0][al.K_ATTRS]
    check(ax[al.SYNC_TRACK[0]] == 2 and ax[al.SYNC_TRACKS[0]] == [2, 5],
          f"★ 跨轨簇把**全部**源轨都记上：{ax}")
    check(p4[al.K_N_CROSS_TRACK] == 1,
          f"★ 跨轨簇**报出来**（不许静默）：n_cross_track={p4.get(al.K_N_CROSS_TRACK)}")

    # ⑤ lane_of / lane_names 是纯函数，直接测
    check(RT.lane_of(al.ROLE_MAIN, (7, 9)) == f"{al.ROLE_MAIN}:7", "lane_of 取最早源轨")
    check(RT.lane_of(al.ROLE_DP, (7, 9)) == f"{al.ROLE_DP}:", "lane_of 对 dp 抹掉源轨维")
    check(RT.lane_of(al.ROLE_MAIN, ()) == f"{al.ROLE_MAIN}:", "没有源轨时也不炸")
    p5 = RT.build_import(many, "L5", names={f"{al.ROLE_MAIN}:1": "贝斯"})
    check(any(t[al.K_NAME] == "贝斯" for t in p5[al.K_TRACKS]), "names 可以按泳道覆盖轨名")

    # ⑥ ★★ 三押单开一条泳道（2026-10 · 用户「三押轨道不出现」）
    #   三押点在双押泳道里再分一条 `dp:3`（**角色仍是 dp**）⇒ BDG 里终于看得见。
    tri = [RT.Sent(0, 0.0, al.ROLE_MAIN, "app", 0.0, (0,)),
           RT.Sent(1, 1.0, al.ROLE_DP, "app", 500.0, (), f"{al.ROLE_DP}:"),
           RT.Sent(2, 2.0, al.ROLE_DP, "app", 1000.0, (), al.LANE_DP3),
           RT.Sent(3, 3.0, al.ROLE_DP, "app", 1500.0, (), al.LANE_DP3)]
    p6 = RT.build_import(tri, "L6")
    l6 = {t[al.K_LANE]: t for t in p6[al.K_TRACKS]}
    check(set(l6) == {f"{al.ROLE_MAIN}:0", f"{al.ROLE_DP}:", al.LANE_DP3},
          f"★ 三押另开一条泳道：{sorted(l6)}")
    check(l6[al.LANE_DP3][al.K_NAME] == al.LANE_NAME[al.LANE_DP3],
          f"★ 轨名 = {al.LANE_NAME[al.LANE_DP3]}（用户在 BDG 里看得见的那个）："
          f"{l6[al.LANE_DP3][al.K_NAME]}")
    check(len(l6[al.LANE_DP3][al.K_ONSETS]) == 2
          and len(l6[f"{al.ROLE_DP}:"][al.K_ONSETS]) == 1,
          "★ 押数 2 与 ≥3 各进各的泳道、一个不丢")
    check(all(o[al.K_ATTRS][al.SYNC_ROLE[0]] == al.ROLE_DP
              for o in l6[al.LANE_DP3][al.K_ONSETS]),
          "★ 三押点的角色仍是 dp（收回/对账那边一字节都不用改）")
    check(RT.lane_of(al.ROLE_DP, (), al.LANE_DP3) == al.LANE_DP3,
          "lane_of 认显式泳道")
    check(RT.lane_of(al.ROLE_DP, (7,)) == f"{al.ROLE_DP}:",
          "★ 不给显式泳道时逐字节还是老行为")


def A3_lane_roles():
    """★ 我们投过去的是**内置轨**（type="beat"），靠**轨名**才能认回角色（`docs/42`）。

    不这么做的话 `role_for_type("beat")` 一律给 `main` ⇒ 所有泳道都成了主轨，
    双押的点会被对账判成「换角色」，用户把点拖到别的泳道也看不出来。
    """
    print("=" * 78)
    print("A3. ★ 泳道角色的认回：内置轨按**轨名**认（否则全是 main）")
    snap = {
        "name": "lanes", "baseBpm": 120.0, "offsetMs": 0.0, "audioName": None,
        "audioMd5": None, "bpmLocked": False, "bpmPoints": [],
        "tracks": [
            {"id": "L0", "name": "ADO·主轨 trk0", "color": "#fff",
             "locked": False, "hidden": False, "type": "beat"},
            {"id": "L1", "name": "ADO·主轨 trk1", "color": "#fff",
             "locked": False, "hidden": False, "type": "beat"},
            {"id": "LD", "name": "ADO·双押轨", "color": "#fff",
             "locked": False, "hidden": False, "type": "beat"},
            {"id": "LB", "name": "Marker 1", "color": "#fff",
             "locked": False, "hidden": False, "type": "beat"},
        ],
        "markers": [],
    }
    p, _ = bdg.parse(snap)
    roles = {t.name: t.role for t in p.tracks}
    check(roles.get("ADO·主轨 trk0") == al.ROLE_MAIN,
          f"`ADO·主轨 trk0` → main（实得 {roles.get('ADO·主轨 trk0')}）")
    check(roles.get("ADO·主轨 trk1") == al.ROLE_MAIN, "trk1 也是 main")
    check(roles.get("ADO·双押轨") == al.ROLE_DP,
          f"★ `ADO·双押轨` → **dp**（不是 main！实得 {roles.get('ADO·双押轨')}）")
    check(roles.get("Marker 1") == al.ROLE_MAIN,
          "认不出名字的普通轨退回按 type 认（beat ⇒ main）")

    # 对账：双押泳道上的点必须**认得出还是双押**，不能被判成「换角色」
    snap2 = dict(snap)
    snap2["markers"] = [
        {"id": "m0", "trackId": "L0", "beat": 0.0, "timeMs": 0.0,
         "attrs": RT.tag_attrs(0, "R", al.ROLE_MAIN, extra={al.SYNC_TRACK[0]: 0})},
        {"id": "m1", "trackId": "LD", "beat": 1.0, "timeMs": 500.0,
         "attrs": RT.tag_attrs(1, "R", al.ROLE_DP)},
    ]
    p2, _ = bdg.parse(snap2)
    sent = [RT.Sent(0, 0.0, al.ROLE_MAIN, "app", 0.0, (0,)),
            RT.Sent(1, 1.0, al.ROLE_DP, "app", 500.0, (0,))]
    d = RT.compare(sent, p2, "R", p2.tempo)
    check(d["counts"][al.EDIT_ROLE] == 0,
          f"★ 双押点没被误判成换角色（role_changed={d['counts'][al.EDIT_ROLE]}）")
    check(d["counts"][al.EDIT_KEPT] == 2,
          f"两个都算「原样」：{d['counts']}")

    # 反过来：把主轨的点拖到双押泳道 ⇒ **必须**判成换角色
    snap3 = dict(snap)
    snap3["markers"] = [
        {"id": "m0", "trackId": "LD", "beat": 0.0, "timeMs": 0.0,
         "attrs": RT.tag_attrs(0, "R", al.ROLE_MAIN)},
    ]
    p3, _ = bdg.parse(snap3)
    d3 = RT.compare([RT.Sent(0, 0.0, al.ROLE_MAIN)], p3, "R", p3.tempo)
    check(d3["counts"][al.EDIT_ROLE] == 1,
          "★ 用户把点拖到另一条泳道 = 改角色（这个信号保住了）")

    # 纯函数也直接测
    from core.bdg.parse import role_from_lane_name as f
    check(f("ADO·主轨 trk12") == al.ROLE_MAIN and f("ADO·双押轨") == al.ROLE_DP,
          "role_from_lane_name 认前缀（trk 后缀不影响）")
    check(f("Marker 1") == "" and f("") == "", "认不出的名字返回空（调用方退回按 type）")


def B_compare_clean():
    print("=" * 78)
    print("B. 原封不动 ⇒ 全 kept，零偏移")
    sent = [RT.Sent(i, i * 1.0, al.ROLE_MAIN) for i in range(5)]
    pts = [(al.ROLE_MAIN, i * 1.0, RT.tag_attrs(i, "R", al.ROLE_MAIN)) for i in range(5)]
    p, _ = bdg.parse(_mk_snapshot(pts))
    d = RT.compare(sent, p, "R", p.tempo)
    check(d["counts"][al.EDIT_KEPT] == 5 and d["n_added"] == 0 and d["n_stale"] == 0,
          f"留下 5：{d['counts']}")
    check(d["drift_max_ms"] == 0.0 and not d["snap_suspect"], "零偏移、非吸附")
    check(len(d["onsets"]) == 5 and all(o["status"] == al.EDIT_KEPT for o in d["onsets"]),
          "新进度 = 5 个原始点")


def C_compare_edits():
    print("=" * 78)
    print("C. 四类编辑（移动 / 删除 / 新增 / 换角色）一次判清")
    sent = [RT.Sent(0, 0.0, al.ROLE_MAIN), RT.Sent(1, 1.0, al.ROLE_MAIN),
            RT.Sent(2, 2.0, al.ROLE_MAIN), RT.Sent(3, 3.0, al.ROLE_SUB)]
    pts = [
        (al.ROLE_MAIN, 0.0, RT.tag_attrs(0, "R", al.ROLE_MAIN)),                  # kept
        (al.ROLE_MAIN, 1.125, RT.tag_attrs(1, "R", al.ROLE_MAIN)),                # moved +0.125
        # idx=2 被删掉
        (al.ROLE_DP, 3.0, RT.tag_attrs(3, "R", al.ROLE_SUB)),                     # role_changed
        (al.ROLE_MAIN, 9.0, None),                                               # added（用户手加）
    ]
    p, _ = bdg.parse(_mk_snapshot(pts))
    d = RT.compare(sent, p, "R", p.tempo)
    c = d["counts"]
    check(c[al.EDIT_KEPT] == 1, f"留下 1（实得 {c[al.EDIT_KEPT]}）")
    check(c[al.EDIT_MOVED] == 1, f"移动 1（实得 {c[al.EDIT_MOVED]}）")
    check(c[al.EDIT_DELETED] == 1, f"删除 1（实得 {c[al.EDIT_DELETED]}）")
    check(c[al.EDIT_ROLE] == 1, f"换角色 1（实得 {c[al.EDIT_ROLE]}）")
    check(d["n_added"] == 1, f"新增 1（实得 {d['n_added']}）")
    mv = [e for e in d["edits"] if e["status"] == al.EDIT_MOVED][0]
    check(abs(mv["beat_out"] - 1.125) < 1e-9 and mv["beat_in"] == 1.0,
          f"移动的拍位：{mv['beat_in']} → {mv['beat_out']}")
    check(abs(mv["drift_ms"] - 62.5) < 0.01, f"偏移 = {mv['drift_ms']} ms（1/8 拍 @120bpm）")
    check(d["drift_over"] == 1, "超 25ms 预算计数 = 1")
    check(d["snap_suspect"] and d["snap_div"] == 8,
          f"★ 偏移对齐 1/8 网格 ⇒ 判定是吸附干的（div={d['snap_div']}）")

    ids = [o["idx"] for o in d["onsets"]]
    check(2 not in ids, "删除的那个不在新进度里")
    check(None in ids, "新增的在新进度里（idx=None）")
    check(len(d["onsets"]) == 4, f"新进度 = 4 个（3 留下/移动/换角色 + 1 新增）：{ids}")
    check(d["onsets"][0]["beat"] <= d["onsets"][-1]["beat"], "新进度按拍位排好序")
    a = [o for o in d["onsets"] if o["idx"] is None][0]
    check(a["role"] == al.ROLE_MAIN, f"新增点取它所在轨的角色：{a['role']}")


def D_stale():
    print("=" * 78)
    print("D. 上一批残留：带标记但批次号不对 ⇒ 不算删/增，单独报")
    sent = [RT.Sent(0, 0.0, al.ROLE_MAIN)]
    pts = [(al.ROLE_MAIN, 0.0, RT.tag_attrs(0, "NEW", al.ROLE_MAIN)),
           (al.ROLE_MAIN, 5.0, RT.tag_attrs(7, "OLD", al.ROLE_MAIN))]
    p, _ = bdg.parse(_mk_snapshot(pts))
    d = RT.compare(sent, p, "NEW", p.tempo)
    check(d["counts"][al.EDIT_DELETED] == 0 and d["n_added"] == 0,
          "残留既不算删除也不算新增")
    check(d["n_stale"] == 1, f"残留 1（实得 {d['n_stale']}）")
    check(len(d["onsets"]) == 1, "新进度只含我们这批发出去的")


def E_lossless():
    print("=" * 78)
    print("E. 吸附关掉时应当逐点无损（1e-6 拍 ≈ 0.3µs）")
    beats = [0.0064, 1.91265, 3.97515, 17.253333]
    sent = [RT.Sent(i, b, al.ROLE_MAIN) for i, b in enumerate(beats)]
    pts = [(al.ROLE_MAIN, bdg.snap.round_prec(b), RT.tag_attrs(i, "R", al.ROLE_MAIN))
           for i, b in enumerate(beats)]
    p, _ = bdg.parse(_mk_snapshot(pts))
    d = RT.compare(sent, p, "R", p.tempo)
    check(d["drift_max_ms"] < 0.001, f"最大偏移 {d['drift_max_ms']} ms < 0.001")
    check(d["counts"][al.EDIT_MOVED] == 0 and d["counts"][al.EDIT_KEPT] == 4,
          f"round() 之后视为没动：{d['counts']}")

    # 吸附开着（1/4 档）就该被抓出来
    pts2 = [(al.ROLE_MAIN, bdg.snap.snap_beat(b, 4), RT.tag_attrs(i, "R", al.ROLE_MAIN))
            for i, b in enumerate(beats)]
    p2, _ = bdg.parse(_mk_snapshot(pts2))
    d2 = RT.compare(sent, p2, "R", p2.tempo)
    check(d2["snap_suspect"] and d2["snap_div"] == 4,
          f"1/4 吸附被抓出来（div={d2['snap_div']}，最大 {d2['drift_max_ms']}ms）")


def F_report():
    print("=" * 78)
    print("F. 报告文本（面板/状态栏直接显示）")
    sent = [RT.Sent(0, 0.0, al.ROLE_MAIN), RT.Sent(1, 1.0, al.ROLE_MAIN)]
    pts = [(al.ROLE_MAIN, 0.0, RT.tag_attrs(0, "R", al.ROLE_MAIN)),
           (al.ROLE_MAIN, 1.25, RT.tag_attrs(1, "R", al.ROLE_MAIN))]
    p, _ = bdg.parse(_mk_snapshot(pts))
    d = RT.compare(sent, p, "R", p.tempo)
    txt = RT.report_text(d)
    print("      " + txt.replace("\n", "\n      "))
    check("对账" in txt and "吸附" in txt, "报告里点了「是吸附干的」")
    check(json.dumps(d, ensure_ascii=False), "结果可 JSON 化（给面板/接口）")


def G_collect_back():
    """★ 收回（BDG → 我们，`docs/45`）：把带时值数据的轨道整条搬回来。"""
    print("=" * 78)
    print("G. 收回：带时值数据的轨道 → 我们的音轨项目")

    def attrs(idx, role, track=None, run="R1", tracks=None):
        a = {al.SYNC_IDX[0]: idx, al.SYNC_RUN[0]: run, al.SYNC_ROLE[0]: role}
        if track is not None:
            a[al.SYNC_TRACK[0]] = track
        if tracks is not None:
            a[al.SYNC_TRACKS[0]] = tracks
        return a

    pts = [
        (al.ROLE_MAIN, 0.0, attrs(0, al.ROLE_MAIN, 0)),
        (al.ROLE_MAIN, 1.0, attrs(1, al.ROLE_MAIN, 0)),
        (al.ROLE_MAIN, 2.0, attrs(2, al.ROLE_MAIN, tracks=[0, 2])),   # 跨轨簇
        (al.ROLE_MAIN, 3.0, None),                                    # 用户新加的点
        (al.ROLE_MAIN, 4.0, attrs(4, al.ROLE_MAIN, 0, run="OLD")),    # 上一批残留
        (al.ROLE_DP, 5.0, attrs(5, al.ROLE_DP)),
    ]
    raw = _mk_snapshot(pts)
    raw["tracks"].append({"id": "t_mine", "name": "我的素材", "color": "#000",
                          "locked": False, "hidden": False, "type": ""})
    raw["markers"].append({"id": "x1", "trackId": "t_mine", "beat": 6.0,
                           "timeMs": 3000.0})
    p, rep = bdg.parse(raw)
    check(rep.ok, "伪造快照解得动")

    pay = RT.collect_back(p, run="R1", tempo=p.tempo)
    lanes = RT.back_lanes(pay)
    names = [l[al.K_LANE] for l in lanes]
    check(len(lanes) == 2, f"按 (角色, 源轨) 分条：{names}")
    check(not any("我的素材" in l[al.K_NAME] for l in lanes),
          f"用户自己的轨不搬（收了 {names}）")
    n_all = sum(l[al.K_N_POINTS] for l in lanes)
    check(n_all == 6, f"6 个点全收（实得 {n_all}）")
    check(pay[al.K_N_ADDED] == 1, f"新加的点单独计数：{pay[al.K_N_ADDED]}")
    dp = [l for l in lanes if l[al.K_ROLE] == al.ROLE_DP]
    check(len(dp) == 1 and dp[0][al.K_N_POINTS] == 1, "双押单独一条")
    main0 = [l for l in lanes if l[al.K_LANE] == "main:0"][0]
    check(main0[al.K_N_POINTS] == 5,
          f"★ **一条 BDG 轨 = 我们的一条音轨**：main:0 收全 5 点"
          f"（实得 {main0[al.K_N_POINTS]}）")
    check(all(q[al.K_MS] >= 0 for l in lanes for q in l[al.K_POINTS])
          and any(abs(q[al.K_MS] - 500.0) < 1e-6
                  for l in lanes for q in l[al.K_POINTS]),
          "每个点都带毫秒（宿主算好的时值：beat 1.0 → 500ms）")
    m0 = [l for l in lanes if l[al.K_LANE] == "main:0"][0]
    check(len([l for l in lanes if l[al.K_LANE] == "main:2"]) == 0,
          "跨轨簇仍归到**最早那条源轨**的泳道（main:0）")
    check(m0[al.K_POINTS][2][al.K_SRC_TRACKS] == [0, 2],
          "★ 跨轨簇的两个源轨号都记在点里（不许静默丢信息）")
    check(al.K_ANCHOR in pay and pay[al.K_ANCHOR][al.K_BASE_BPM] == 120.0,
          "带上对端的时序锚（收回后要比对我们自己的）")

    txt = RT.back_text(pay, lanes)
    check(txt.startswith("[收回]") and "6 点" in txt,
          "人话报告：" + txt.splitlines()[0])


def H_idx_collision():
    """★★ 双押点与主轨点**共用 onset 下标** ⇒ 对账不许把撞车的判成删除。

    2026-10 真机踩到：544 点里 216 个多押点被报「删除」，而谱面一个都没丢。
    真因是 `compare` 的 `by_idx` 原本**一对一**（`setdefault`），同一个 onset
    下标上主轨点 + 双押点有两条 ⇒ 后写的被挤掉。双押的定义就是「同一下同时按下」，
    所以这个撞车是**常态**，不是边界情况。
    """
    print("=" * 78)
    print("H. ★★ 主轨/双押共用 onset 下标：撞车的不许判「删除」")
    sent = [RT.Sent(0, 0.0, al.ROLE_MAIN),
            RT.Sent(1, 1.0, al.ROLE_MAIN), RT.Sent(1, 1.0, al.ROLE_DP),
            RT.Sent(2, 2.0, al.ROLE_DP)]
    pts = [(al.ROLE_MAIN, 0.0, RT.tag_attrs(0, "R", al.ROLE_MAIN)),
           (al.ROLE_MAIN, 1.0, RT.tag_attrs(1, "R", al.ROLE_MAIN)),
           (al.ROLE_DP, 1.0, RT.tag_attrs(1, "R", al.ROLE_DP)),
           (al.ROLE_DP, 2.0, RT.tag_attrs(2, "R", al.ROLE_DP))]
    p, rep = bdg.parse(_mk_snapshot(pts))
    check(rep.ok, "伪造快照解得动")
    d = RT.compare(sent, p, "R", p.tempo)
    c = d[al.K_COUNTS]
    check(c[al.EDIT_DELETED] == 0, f"★ 撞车的双押点不许判「删除」：{c}")
    check(c[al.EDIT_KEPT] == 4, f"★ 4 个点全留下（含撞车那一对）：{c}")
    check(d["n_stale"] == 0, f"撞车不许变成「残留」：n_stale={d['n_stale']}")
    # 撞车 + 用户把它拖到主轨 ⇒ 仍然认得出**换角色**（不是删+增）
    sent2 = [RT.Sent(1, 1.0, al.ROLE_DP)]
    d2 = RT.compare(sent2, p, "R", p.tempo)
    check(d2[al.K_COUNTS][al.EDIT_ROLE] == 1 or d2[al.K_COUNTS][al.EDIT_KEPT] == 1,
          f"★ 撞车时按角色挑，不误报：{d2[al.K_COUNTS]}")
    # ★★ 收回的「新进度」也不许被撞车合并掉（`onsets_out` 以前只按 idx 存）
    o = d[al.K_ONSETS]
    check(len(o) == 4, f"★ 收回明细 4 条（撞车的一对都要在）：实得 {len(o)}")
    roles = sorted(str(x[al.K_ROLE]) for x in o)
    check(roles == [al.ROLE_DP, al.ROLE_DP, al.ROLE_MAIN, al.ROLE_MAIN],
          f"★ 角色不许串（主轨行拿双押的拍位就是这里串的）：{roles}")
    beats = sorted(round(float(x[al.K_BEAT]), 6) for x in o)
    check(beats == [0.0, 1.0, 1.0, 2.0],
          f"★ 拍位不许串/不许合并：{beats}")


def main():
    A_build_import()
    A2_lanes()
    A3_lane_roles()
    B_compare_clean()
    C_compare_edits()
    D_stale()
    E_lossless()
    F_report()
    G_collect_back()
    H_idx_collision()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 往返对账全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
