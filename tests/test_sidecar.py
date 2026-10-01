# -*- coding: utf-8 -*-
"""sidecar 端到端：起服务 → 加载 → 求解 → 视图数据 → 音频 Range → 导出。

用法:
    python tests/test_sidecar.py [--ogg]

`--ogg` 会额外跑一次 OGG 加载（约 1 分钟，验进度/取消通道）。

★ 2026-10 说明：这个文件曾被一条 PowerShell 文本替换命令按 GBK 读坏
（教训：**别用 PowerShell 文本 cmdlet 改非 ASCII 源码**）。
本版是照 `__pycache__` 里那份 .pyc 的字符串常量（= 损坏前的真值）
**逐条重建**的，断言清单与损坏前一致，并补上了本轮新增的
主次级轨 / 轨道位置偏移 / 激进采音 / 等待拍阈值默认 4 四条。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sidecar import server as SV                            # noqa: E402
from sidecar import schema as SC                            # noqa: E402
from core import onsets as onsets_mod                       # noqa: E402

ok = 0
bad = 0


def chk(name: str, cond, extra: str = "") -> None:
    global ok, bad
    if cond:
        ok += 1
        print(f"  ok   {name}")
    else:
        bad += 1
        print(f"  FAIL {name}  {extra}")


def post(url: str, obj: dict, timeout: float = 300.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 前端也是这么做的：读 body 里的 error，而不是只看状态码
        try:
            d = json.loads(e.read().decode("utf-8"))
        except Exception:                                     # noqa: BLE001
            d = {"ok": False, "error": f"HTTP {e.code}"}
        d["status"] = e.code
        return d


def get(url: str, headers: dict | None = None, timeout: float = 60.0):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


def main() -> int:                                            # noqa: C901
    ogg = "--ogg" in sys.argv
    SV.APP = SV.App(ROOT)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SV.Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1},
                          daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    print(f"[sidecar] {base}")

    out_root = os.path.join(ROOT, "out", "_sidecar_export")

    try:
        # ============================================================ [1]
        print("\n[1] 健康 / schema")
        st, _h, body = get(base + "/api/health")
        d = json.loads(body)
        chk("health ok", st == 200 and d.get("ok"), str(d)[:120])

        d = json.loads(get(base + "/api/schema")[2])
        keys = {f["key"] for f in d["fields"]}
        chk("schema 字段数 ≥ 30", len(d["fields"]) >= 30, str(len(d["fields"])))
        chk("schema 有默认值", set(d["defaults"]) >= keys)
        chk("schema 覆盖 OnsetParams 全部 7 项",
            {"merge_ms", "merge_anchor", "min_velocity", "min_interval_ms",
             "pitch_lo", "pitch_hi", "max_onsets"} <= keys)
        chk("schema 覆盖 SolveParams 的 UI 项",
            {"auto_bpm", "quantize_rhythm", "base_bpm", "ref_index", "bpm_max",
             "straight_preset", "allow_set_speed", "twirl_index",
             "twirl_limit_deg", "use_templates", "template_only_nonstraight",
             "use_pause", "pause_min_beats", "use_snowflake",
             "snowflake_min_tiles", "snowflake_full_tiles", "snown_index",
             "travel_min", "travel_max", "aggressive_pick", "ladder_outer_mode",
             "ladder_outer_cbpm", "ladder_tier_order",
             "use_position_track", "pos_track_step", "pos_track_min_beats",
             "closed_bias_index", "straighten", "straighten_min_run",
             "straighten_theta"} <= keys)
        # ★ schema.py 的既定口径：「UI 默认值一律从 core dataclass 取」。
        #   所以这里不该钉死某个历史数值，而应该断言**真的和 core 一致**。
        from core.solve import SolveParams as _SP
        chk("默认值与 core dataclass 一致",
            d["defaults"]["merge_ms"] == 30.0
            and d["defaults"]["pause_min_beats"] == _SP().pause_min_beats
            and d["defaults"]["travel_min"] == _SP().travel_min
            and d["defaults"]["base_bpm"] == 180.0)
        chk("轨道位置偏移有 UI 开关且默认与 core 一致（2026-10 起默认关）",
            d["defaults"]["use_position_track"] == _SP().use_position_track
            and d["defaults"]["use_position_track"] is False
            and d["defaults"]["pos_track_step"] == _SP().pos_track_step
            and d["defaults"]["pos_track_min_beats"] == _SP().pos_track_min_beats)
        chk("激进采音默认关（原逻辑保留）",
            d["defaults"]["aggressive_pick"] is False
            and d["defaults"]["aggressive_pick"] == _SP().aggressive_pick
            and d["defaults"]["ladder_outer_mode"] == "auto"
            and d["defaults"]["ladder_outer_cbpm"] == 400.0
            and d["defaults"]["ladder_tier_order"] == "straight")
        chk("等待拍阈值默认 = 4（用户 2026-10 改）",
            d["defaults"]["pause_min_beats"] == 4.0
            and d["defaults"]["pause_min_beats"] == _SP().pause_min_beats,
            str(d["defaults"]["pause_min_beats"]))

        # ============================================================ [2]
        print("\n[2] 加载 MIDI")
        mid = os.path.join(ROOT, "samples", "audio", "doublepress_demo_120.mid")
        if not os.path.exists(mid):
            cand = [os.path.join(ROOT, "samples", f)
                    for f in os.listdir(os.path.join(ROOT, "samples"))
                    if f.lower().endswith((".mid", ".midi"))]
            mid = cand[0] if cand else ""
        chk("找到 MIDI 样本", bool(mid), mid)
        info = post(base + "/api/load", {"path": mid})
        chk("load ok", info.get("ok"), str(info.get("error"))[:200])
        chk("load 返回音轨列表", len(info.get("tracks", [])) >= 1)
        chk("load 给出默认勾选/光标", "default_tracks_checked" in info
            and "default_current_track" in info)
        chk("load 给出三条轨列表（主 / 次级 / 双押）",
            isinstance(info.get("sub"), list) and isinstance(info.get("dp"), list)
            and len(info.get("sub", [])) == len(info.get("tracks", [])),
            f"tracks={len(info.get('tracks', []))} sub={len(info.get('sub', []))}")

        state = dict(SC.defaults())
        state["tracks_checked"] = info["default_tracks_checked"]
        state["sub_checked"] = info.get("default_sub_checked") or []
        state["dp_checked"] = info["default_dp_checked"]
        state["current_track"] = info["default_current_track"]
        state["song"] = info["name"]

        # ============================================================ [3]
        print("\n[3] derive（主轨/采音集合/音高）")
        dv = post(base + "/api/derive", {"state": state})
        chk("derive ok", dv.get("ok"), str(dv)[:160])
        chk("主轨在采音集合里或至少合法",
            0 <= dv["primary"] < len(info["tracks"]))
        chk("pitch 建议非空", dv["pitch_lo"] is not None and dv["pitch_hi"] is not None,
            f"{dv['pitch_lo']}..{dv['pitch_hi']}")
        if dv["pitch_lo"] is not None:
            state["pitch_lo"], state["pitch_hi"] = dv["pitch_lo"], dv["pitch_hi"]

        # ============================================================ [4]
        print("\n[4] rebuild（求解 + 视图数据）")
        t0 = time.perf_counter()
        rb = post(base + "/api/rebuild", {"state": state})
        dt = (time.perf_counter() - t0) * 1000
        chk("rebuild ok", rb.get("ok"), str(rb.get("msg") or rb.get("error"))[:200])
        chk("层数 > 0", rb.get("n_floors", 0) > 0, str(rb.get("n_floors")))
        chk("基准 BPM 合理", 10 < rb.get("base_bpm", 0) < 4000, str(rb.get("base_bpm")))
        chk("有状态文案", bool(rb.get("status")))
        chk("有 timing 文案", bool(rb.get("timing")))
        pl = rb.get("payload") or {}
        chk("payload.floors 与 n_floors 一致",
            len(pl.get("floors", [])) == rb.get("n_floors"),
            f"{len(pl.get('floors', []))} vs {rb.get('n_floors')}")
        chk("payload.entry 与 floors 等长",
            len(pl.get("entry", [])) == len(pl.get("floors", [])))
        chk("payload 有 hit/notes/falls",
            "hit" in pl and "notes" in pl and "falls" in pl)
        chk("floors 带坐标 x/y（ChartView 要用）",
            abs(pl["floors"][0]["x"]) < 1e-9 and abs(pl["floors"][0]["y"]) < 1e-9)
        chk("层号严格递增（entry 单调）",
            all(b > a - 1e-9 for a, b in zip(pl["entry"], pl["entry"][1:])))
        chk("求解够快（<2s）", dt < 2000, f"{dt:.0f}ms")
        chk("payload 暴露 pos_track_n（轨道位置偏移开关要用）",
            "pos_track_n" in pl, str(list(pl)[:12]))
        # ★★ 算法轨道调度（`docs/60`）：session 的**步骤 8c 真的跑了**，
        #   而且皮肤真的进了导出用的 `settings`（不是只回了 payload）。
        #   ⚠ 判据语义在 `tests/test_appearance.py`；这里只证「开关一路通到导出面」。
        _ap = pl.get("appearance") or {}
        chk("payload 带 appearance 报告（步骤 8c 跑了）",
            bool(_ap) and _ap.get("enabled") is True and isinstance(_ap.get("text"), str),
            f"enabled={_ap.get('enabled')} keys={sorted(_ap)[:8]}")
        chk("appearance 皮肤 = Neon 且写进 settings",
            (_ap.get("settings") or {}).get("trackStyle") == "Neon",
            str((_ap.get("settings") or {}).get("trackStyle")))
        chk("appearance 有 floors/ripples/radius_spans 三个账目",
            all(k in _ap for k in ("floors", "ripples", "radius_spans")),
            str(sorted(_ap)[:12]))

        # ★★ 演出（`docs/62`）：session 的**步骤 8d 真的跑了**，事件真的进了导出面。
        #   ⚠ 判据语义在 `tests/test_show.py`；这里只证「开关一路通到 actions + settings」。
        _sh = pl.get("show") or {}
        chk("payload 带 show 报告（步骤 8d 跑了）",
            bool(_sh) and _sh.get("enabled") is True and isinstance(_sh.get("text"), str),
            f"enabled={_sh.get('enabled')} keys={sorted(_sh)[:8]}")
        chk("show 离场/入场都有条数",
            _sh.get("n_out", 0) > 0 and _sh.get("n_in", 0) > 0,
            f"out={_sh.get('n_out')} in={_sh.get('n_in')}")
        chk("show 报出 beatsAhead 需求 = 提前量 + 余量",
            float(_sh.get("required_beats_ahead") or 0)
            == float(_sh.get("lead", 0)) + float(_sh.get("margin", 0)),
            f"{_sh.get('required_beats_ahead')} vs lead {_sh.get('lead')}")
        # 导出面：`settings.beatsAhead` 必须被抬起来（否则入场动画播在方块出现之前）
        _lj = post(base + "/api/leveljson", {"state": state})
        _lv = (_lj.get("level") or {}) if _lj.get("ok") else {}
        if _lv:
            _ba = float(((_lv.get("settings") or {}).get("beatsAhead")) or 0)
            chk("导出的 settings.beatsAhead ≥ 演出需求",
                _ba >= float(_sh.get("required_beats_ahead") or 0) - 1e-9,
                f"beatsAhead={_ba}")
            _mvs = [a for a in (_lv.get("actions") or [])
                    if a.get("eventType") == "MoveTrack"]
            chk("导出的 actions 里有演出的 MoveTrack",
                len(_mvs) >= int(_sh.get("n_out") or 0), f"MoveTrack={len(_mvs)}")
            _fl = [int(a.get("floor") or 0) for a in (_lv.get("actions") or [])]
            chk("导出 actions 仍按 floor 有序", _fl == sorted(_fl))

        # ------------------------------------------------------------ [4b]
        print("\n[4b] ★ 主次级（权重最高的全采，权重低的只插空）")
        _sv = SV.APP.session
        _prim = info["default_tracks_checked"][0]
        _dp = set(info.get("default_dp_checked") or [])
        _others = [t["index"] for t in info["tracks"]
                   if t["has_notes"] and t["index"] != _prim
                   and t["index"] not in _dp]      # 双押轨不当次级轨
        if _others:
            _sec = _others[0]
            st_base = dict(state)
            st_base["tracks_checked"] = [_prim]
            st_base["sub_checked"] = []
            _sv.rebuild(st_base)
            n_prim = len(_sv.onsets)
            dv_b = _sv.derive(st_base)
            chk("只勾主轨时 fill_mode = False",
                dv_b["fill_mode"] is False and dv_b["sub_tracks"] == [])

            st_sub = dict(state)
            st_sub["tracks_checked"] = [_prim]
            st_sub["sub_checked"] = [_sec]
            st_sub["pitch_lo"], st_sub["pitch_hi"] = 0, 127
            _sv.rebuild(st_sub)
            n_fill = len(_sv.onsets)
            dv_s = _sv.derive(st_sub)
            chk("勾了次级轨 → derive 报出 fill_mode / sub_tracks",
                dv_s["fill_mode"] is True and dv_s["sub_tracks"] == [_sec],
                f"{dv_s['fill_mode']} {dv_s['sub_tracks']}")
            chk("次级轨只插空：onset 数 ≥ 只主轨、且 < 并集",
                n_prim <= n_fill < n_prim + len(_sv.midi.tracks[_sec].notes),
                f"主轨 {n_prim} → 插空 {n_fill}")
            chk("状态文案写明「只插空」", "只插空" in str(dv_s["hint"]),
                str(dv_s["hint"]))
            # ⚠ `core.onsets.notes_fill_gaps` 的既定语义：`gap_ms <= 0`
            #   是「不做缝隙判断」⇒ 等价于并集，**不是**「不插空」。
            st_union = dict(st_sub)
            st_union["sub_gap_ms"] = 0.0
            _sv.rebuild(st_union)
            n_union = len(_sv.onsets)
            chk("插空阈值 0 → 不做缝隙判断（等价并集，≥ 插空模式）",
                n_union >= n_fill, f"插空 {n_fill} vs 阈值0 {n_union}")
            # 阈值调到巨大 ⇒ 主轨的缝隙全都不够大 ⇒ 次级轨一个也插不进来
            st_huge = dict(st_sub)
            st_huge["sub_gap_ms"] = 9_000_000.0
            _sv.rebuild(st_huge)
            chk("插空阈值极大 → 次级轨一个都插不进来（等于只采主轨）",
                len(_sv.onsets) == n_prim, f"{len(_sv.onsets)} vs {n_prim}")
            _sv.rebuild(state)
        else:
            chk("样本有第二条可当次级轨的轨（跳过）", True, "单轨样本")

        # ============================================================ [5]
        print("\n[5] cap_times / beat_grid")
        ct = post(base + "/api/cap_times", {"state": state})
        chk("cap_times 非空且升序",
            len(ct["cap"]) > 1 and all(b >= a for a, b in zip(ct["cap"], ct["cap"][1:])))
        bg = post(base + "/api/beat_grid", {"division": 4})
        chk("beat_grid 非空", len(bg.get("grid") or []) > 0,
            str(bg.get("grid"))[:80])

        # ============================================================ [6]
        print("\n[6] 音频 + Range")
        au = post(base + "/api/audio", {"state": state})
        chk("audio ok", au.get("ok"), str(au.get("error"))[:120])
        st2, hd, blob = get(base + au["url"])
        chk("整段可读", st2 == 200 and len(blob) > 1000, f"{st2} {len(blob)}")
        st3, hd3, part = get(base + au["url"], {"Range": "bytes=0-1023"})
        chk("Range 206 + 1024 字节",
            st3 == 206 and len(part) == 1024, f"{st3} {len(part)}")

        # ============================================================ [7]
        print("\n[7] 导出 + 第三方反解校验（带上建议 offset）")
        from core import verify as V
        chk_sug = (rb.get("check") or {}).get("suggest_ms")
        chk("回传了建议 offset", chk_sug is not None, str(rb.get("check"))[:120])
        print(f"       建议 offset = {chk_sug}")
        st_exp = dict(state)
        st_exp["offset"] = float(chk_sug or 0.0)
        # ★ 先把上次的导出清掉 —— 否则 `_find_chart` 会捞到旧文件，
        #   反解校验就会拿「上一首的谱」去比「这一首的音」，实测差 12 秒。
        import shutil
        shutil.rmtree(out_root, ignore_errors=True)
        ex = post(base + "/api/export", {"state": st_exp, "dir": out_root})
        chk("export ok", ex.get("ok"), str(ex.get("error") or ex.get("msg"))[:160])
        chart_file = os.path.join(ex.get("dir") or out_root, "main.adofai")
        if not os.path.exists(chart_file):
            chart_file = _find_chart(ex.get("dir") or out_root)
        chk("落盘 main.adofai", os.path.exists(chart_file), chart_file)
        print(f"       导出到 {chart_file}")
        ons_ms = [o.t_ms for o in SV.APP.session.onsets]
        # ★ 这份谱带**中旋双押层**（插进去的 `999`/薄格层），层 ↔ onset 不再 1:1，
        #   `verify_file` 的逐层对照会把正确的谱报成假失败（实测 11999ms）。
        #   插了双押层时改用**按键集合**校验（`docs/18` 风险 7）。
        n_dp = int((rb.get("dp") or {}).get("n", 0) or 0)
        has_dp = n_dp > 0 or (rb.get("n_floors", 0) != len(ons_ms) + 1)
        if has_dp:
            vr = V.verify_press_subset(chart_file, ons_ms, tol_ms=2.0)
            chk("这份谱带双押层（层数 ≠ onset 数+1 ⇒ 必须按键盘校验）", has_dp,
                f"floors={rb.get('n_floors')} onsets={len(ons_ms)}")
        else:
            vr = V.verify_file(chart_file, ons_ms, tol_ms=2.0, lead_floors=1)
        chk("第三方反解校验通过", vr.ok, vr.summary())
        chk("建议 offset 下命中误差 ≈ 0（≤2ms）", vr.max_err_ms <= 2.0,
            f"{vr.max_err_ms:.2f}ms")

        # ============================================================ [7b]
        print("\n[7b] 不带双押轨的导出（走逐层 1:1 校验分支）")
        st_ndp = dict(state)
        st_ndp["dp_checked"] = []
        rb2 = post(base + "/api/rebuild", {"state": st_ndp})
        chk("重建 ok", rb2.get("ok"), str(rb2.get("msg"))[:160])
        chk("无双押时层数更少", rb2.get("n_floors", 0) < rb.get("n_floors", 0),
            f"{rb2.get('n_floors')} vs {rb.get('n_floors')}")
        ex2 = post(base + "/api/export", {"state": st_ndp, "dir": out_root})
        chk("导出 ok", ex2.get("ok"), str(ex2.get("error"))[:160])
        cf2 = _find_chart(ex2.get("dir") or out_root)
        ons2 = [o.t_ms for o in SV.APP.session.onsets]
        vr2 = V.verify_file(cf2, ons2, tol_ms=2.0, lead_floors=1)
        chk("逐层 1:1 校验通过且无「按键盘」字样",
            vr2.ok and "按键盘" not in vr2.summary(), vr2.summary()[:140])
        chk("模型侧命中误差 ≈ 0（≤2ms）", vr2.max_err_ms <= 2.0,
            f"{vr2.max_err_ms:.2f}ms")

        # ============================================================ [7c]
        print("\n[7c] 参数映射对等：每个 UI 字段 → core 字段")
        from core.solve import STRAIGHT_PRESETS
        sv = SV.APP.session
        st_p, _ = sv.params_solve(state, sv.onsets)
        ons_p = sv.params_onset(state)
        chk("改值确实进了 OnsetParams", ons_p.merge_ms == state["merge_ms"],
            str(ons_p.merge_ms))
        st_auto = dict(state)
        st_auto["auto_bpm"] = True
        p_auto, info_auto = sv.params_solve(st_auto, sv.onsets)
        chk("自动 BPM：base_bpm 保持 0（显示值不算输入）", p_auto.base_bpm == 0.0,
            str(p_auto.base_bpm))
        chk("自动 BPM：回填了显示值", info_auto["display_bpm"] is not None,
            str(info_auto["display_bpm"]))
        st_man = dict(state)
        st_man["auto_bpm"] = False
        st_man["base_bpm"] = 233.0
        p_man, _ = sv.params_solve(st_man, sv.onsets)
        chk("手动 BPM：base_bpm 用框里的值", p_man.base_bpm == 233.0,
            str(p_man.base_bpm))

        st3d = dict(state)
        st3d.update({"ref_index": 3, "straight_preset": 0, "twirl_index": 1,
                     "snown_index": 2, "bpm_max": 321.0, "twirl_limit_deg": 111.0,
                     "pause_min_beats": 2.5, "snowflake_min_tiles": 7,
                     "snowflake_full_tiles": 33, "quantize_rhythm": False,
                     "use_templates": False, "template_only_nonstraight": False,
                     "use_pause": False, "use_snowflake": True,
                     "travel_min": 40.0, "travel_max": 270.0,
                     "snowflake_shape": "zigzag",
                     "snowflake_min_arms": 3, "snowflake_compact": False,
                     "snowflake_uniform_tol_ms": 9.5, "snowflake_random": True,
                     "snowflake_seed": 4242,
                     "use_position_track": False, "pos_track_step": 0.35,
                     "pos_track_min_beats": 16.0,
                     "aggressive_pick": True, "ladder_outer_mode": "always",
                     "ladder_outer_cbpm": 555.0,
                     "ladder_tier_order": "switch",
                     "closed_bias_index": 2, "straighten": False,
                     "straighten_min_run": 4, "straighten_theta": 33.0,
                     "allow_set_speed": False})
        p3, _ = sv.params_solve(st3d, sv.onsets)
        chk("ref_index → beat_beats", p3.beat_beats == 0.75, str(p3.beat_beats))
        chk("straight_preset → straight_weight（『少』λ 最大）",
            p3.straight_weight == STRAIGHT_PRESETS[SC.STRAIGHT_VALUES[0]],
            str(p3.straight_weight))
        chk("twirl_index → twirl_mode（UI 顺序 ≠ 常量顺序）",
            p3.twirl_mode == "accum", str(p3.twirl_mode))
        chk("snown_index → snowflake_n_rot", tuple(p3.snowflake_n_rot) == (8,),
            str(p3.snowflake_n_rot))
        chk("bpm_max / twirl_limit / pause_beats",
            p3.bpm_max == 321.0 and p3.twirl_limit_deg == 111.0
            and p3.pause_min_beats == 2.5)
        chk("最小角度 → SolveParams.travel_min", p3.travel_min == 40.0,
            str(p3.travel_min))
        chk("★ 最大夹角 → SolveParams.travel_max（用户口径：不许超过 270°）",
            p3.travel_max == 270.0, str(p3.travel_max))
        chk("雪花三参",
            p3.use_snowflake is True and p3.snowflake_min_tiles == 7
            and p3.snowflake_full_tiles == 33.0)
        chk("雪花新参数全部接通（docs/24 §4）",
            p3.snowflake_shape == "zigzag" and p3.snowflake_min_arms == 3
            and p3.snowflake_compact is False
            and p3.snowflake_uniform_tol_ms == 9.5
            and p3.snowflake_random is True and p3.snowflake_seed == 4242)
        chk("轨道位置偏移 → SolveParams（含 step / min_beats）",
            p3.use_position_track is False and p3.pos_track_step == 0.35
            and p3.pos_track_min_beats == 16.0)
        chk("激进采音 → SolveParams（含 绕圈偏好 / 档位序）",
            p3.aggressive_pick is True and p3.ladder_outer_mode == "always"
            and p3.ladder_outer_cbpm == 555.0
            and p3.ladder_tier_order == "switch")
        # ★ 闭合图形使用策略：UI 存 index，映射成 -1/0/+1
        chk("闭合图形 → SolveParams.closed_figure_bias（index → −1/0/+1）",
            p3.closed_figure_bias == 1
            and SC.CLOSED_VALUES[2] == 1 and SC.CLOSED_VALUES[0] == -1,
            str(p3.closed_figure_bias))
        # ★★ 2026-10 回归：用户报「闭合图形限制完全没生效」。
        #   根因是 `closed_bias_index` 的 combo **把真值 (-1/0/1) 当 value**，
        #   而 sidecar 按下标解 ⇒ 界面三档实际只产生 {-1, -1, 0}。
        #   这条守着「选项 value 必须是下标」这条全仓约定（同组 `*_index` 都是）。
        _bad_idx = []
        for _f in SC.FIELDS:
            if _f.get("type") != "combo" or not str(_f.get("key", "")).endswith("_index"):
                continue
            _vals = [o["value"] for o in _f.get("options") or []]
            if _vals != list(range(len(_vals))):
                _bad_idx.append((_f["key"], _vals))
        chk("所有 `*_index` combo 的 value 都是下标（不是真值）",
            not _bad_idx, str(_bad_idx))
        _cb = next(_f for _f in SC.FIELDS if _f["key"] == "closed_bias_index")
        _mapped = [SC.CLOSED_VALUES[min(max(int(o["value"]), 0),
                                        len(SC.CLOSED_VALUES) - 1)]
                   for o in _cb["options"]]
        chk("闭合图形三档 UI 标签 → 三个**互不相同**的 bias",
            _mapped == [-1, 0, 1], str(_mapped))
        # ★ 回正：2026-10 之前**一个参数都没接 UI**，这条守着别再退回去
        chk("回正 → SolveParams（开关 + 斜轨长 + 斜轨判定）",
            p3.straighten is False and p3.straighten_min_run == 4
            and p3.straighten_theta == 33.0)
        chk("勾选类开关", p3.quantize_rhythm is False and p3.use_templates is False
            and p3.template_only_nonstraight is False and p3.use_pause is False)
        chk("allow_set_speed=False → speed_tiers 只留 1",
            tuple(p3.speed_tiers) == (1,), str(p3.speed_tiers))
        chk("ppqn / midi_bpm 来自 MIDI",
            p3.ppqn == SV.APP.session.midi.ppqn
            and p3.midi_bpm == SV.APP.session.midi.bpm0)

        # ============================================================ [7d]
        print("\n[7d] 中断语义：失败了不清旧谱面")
        post(base + "/api/rebuild", {"state": state})
        n_before = len(SV.APP.session.chart.floors)
        chk("先做一次干净重建", n_before > 0, str(n_before))
        st_bad = dict(state)
        st_bad["tracks_checked"] = []
        st_bad["regions"] = []
        rbad = post(base + "/api/rebuild", {"state": st_bad})
        chk("没轨时报错而不是崩", (not rbad.get("ok")) and rbad.get("msg"),
            str(rbad.get("msg"))[:120])
        chk("旧谱面仍在（层数不变）",
            SV.APP.session.chart is not None
            and len(SV.APP.session.chart.floors) == n_before,
            f"{len(SV.APP.session.chart.floors) if SV.APP.session.chart else 0} vs {n_before}")

        # ============================================================ [7e]
        print("\n[7e] 区间采音：某一段改用别的音轨")
        rb0 = post(base + "/api/rebuild", {"state": state})
        chk("无区间先出一次谱", rb0.get("ok"))
        n0 = rb0["n_onsets"]
        all_tr = [t["index"] for t in info["tracks"] if t["has_notes"]]
        chk("样本至少 2 条有音的轨", len(all_tr) >= 2, str(all_tr))
        other = [i for i in all_tr if i != state["tracks_checked"][0]][0]
        ons_all = [o.t_ms for o in SV.APP.session.onsets]
        t0d, t1d = ons_all[len(ons_all) // 3], ons_all[2 * len(ons_all) // 3]
        st_rg = dict(state)
        st_rg["regions"] = [{"start_ms": t0d, "end_ms": t1d, "tracks": [other],
                             "mode": "replace", "label": "B段", "fill_gap_ms": 0}]
        rbr = post(base + "/api/rebuild", {"state": st_rg})
        chk("带区间重建 ok", rbr.get("ok"), str(rbr.get("msg"))[:160])
        chk("回传了区间元信息（预览条画色带要用）",
            len(rbr.get("regions") or []) == 1, str(rbr.get("regions"))[:120])
        chk("区间标了实际采到的点数",
            (rbr.get("regions") or [{}])[0].get("n", 0) > 0,
            str((rbr.get("regions") or [{}])[0]))
        sv2 = SV.APP.session
        chk("区间用的是指定轨",
            (sv2.region_meta or [{}])[0].get("tracks") == [other],
            str(sv2.region_meta))
        only = onsets_mod.build_onsets(sv2.midi.tracks[other].notes,
                                       sv2.params_onset(st_rg))
        inside = [o for o in sv2.onsets if t0d <= o.t_ms < t1d]
        expect = [o for o in only if t0d <= o.t_ms < t1d]
        chk("区间内的 onset 恰好等于「该轨单独采」的结果",
            len(inside) == len(expect), f"{len(inside)} vs {len(expect)}")
        chk("区间外仍是全局采音（点数没被清空）",
            len([o for o in sv2.onsets if o.t_ms < t0d - 1]) > 0)
        chk("payload 也带上区间（前端画色带）",
            len((rbr.get("payload") or {}).get("regions") or []) == 1)
        chk("状态栏报告区间", "区间" in str(rbr.get("status")),
            str(rbr.get("status"))[:160])

        # ============================================================ [7f]
        print("\n[7f] 区间把全局关掉：只从区间采")
        st_only = dict(state)
        st_only["tracks_checked"] = []
        st_only["regions"] = st_rg["regions"]
        rbo = post(base + "/api/rebuild", {"state": st_only})
        chk("全局不勾 + 有区间 → 仍能出谱", rbo.get("ok"), str(rbo.get("msg"))[:120])
        ss = SV.APP.session
        out_of = [o for o in ss.onsets if not (t0d <= o.t_ms < t1d)]
        chk("区间外一个 onset 都没有", len(out_of) == 0, f"{len(out_of)} 个在区间外")
        chk("区间内还有 onset",
            len([o for o in ss.onsets if t0d <= o.t_ms < t1d]) > 0)

        # ============================================================ [7g]
        print("\n[7g] ★ 分段采音（docs/34 方案 C）：角色随时间")
        base_rg = dict(state)                     # 干净一份（无区间无分段）
        base_rg.pop("segments", None)
        rb_base = post(base + "/api/rebuild", {"state": base_rg})
        chk("基线出谱", rb_base.get("ok"), str(rb_base.get("msg"))[:120])
        n_base = rb_base["n_onsets"]
        chk("没分段时报 0 段", rb_base.get("n_segments") == 0)

        # 一条「从 t0d 起改用 other 轨」的分段 = 旧区间第一段的等价物
        st_sg = dict(base_rg)
        st_sg["segments"] = [{"at_ms": t0d, "label": "B段", "main": [other],
                             "sub": [], "dp": []}]
        st_sg["segment_mode"] = "from"
        rbs = post(base + "/api/rebuild", {"state": st_sg})
        chk("带分段重建 ok", rbs.get("ok"), str(rbs.get("msg"))[:160])
        segs = rbs.get("segments") or []
        total_ms_rbs = float((rbs.get("payload") or {}).get("total_ms") or 0.0)
        chk("回传分段元信息（预览条画泳道要用）", len(segs) == 2,
            str(segs)[:160])
        chk("分段标了 src / 实际采到的点数",
            segs[0].get("src") == "global" and segs[1].get("src") == "segment"
            and segs[1].get("n", 0) > 0, str(segs)[:200])
        chk("分段「从这点起」：第一片吃全局、第二片吃规则",
            segs[0]["start_ms"] == 0.0 and segs[0]["end_ms"] == t0d
            and segs[1]["start_ms"] == t0d
            and segs[1]["end_ms"] == round(total_ms_rbs, 6),
            f"{segs[0]['start_ms']}~{segs[1]['end_ms']} / 曲长 {total_ms_rbs}")
        chk("第二片用的是指定轨", segs[1]["main"] == [other], str(segs[1]["main"]))
        chk("payload 也带上分段（前端画泳道）",
            len((rbs.get("payload") or {}).get("segments") or []) == 2)
        chk("payload 带上了语义模式",
            (rbs.get("payload") or {}).get("segment_mode") == "from")
        chk("状态栏报告分段", "分段" in str(rbs.get("status")), str(rbs.get("status"))[:120])

        # ★ 「到这点为止」是镜像：管的段落反过来
        st_un = dict(st_sg)
        st_un["segment_mode"] = "until"
        rbu = post(base + "/api/rebuild", {"state": st_un})
        su = rbu.get("segments") or []
        chk("until 模式片数相同", len(su) == len(segs), f"{len(su)} vs {len(segs)}")
        chk("★ until：第一片吃规则、最后一片吃全局",
            su[0].get("src") == "segment" and su[-1].get("src") == "global",
            str([x.get("src") for x in su]))
        chk("★ 两种模式对同一组分段的 onset 总数可以不同（管的段落反了）",
            isinstance(rbu.get("n_onsets"), int))

        # 区间与分段同时存在 ⇒ 分段优先，且**必须报出来**（不许静默）
        st_both = dict(st_sg)
        st_both["regions"] = [{"start_ms": t0d, "end_ms": t1d,
                              "tracks": [other], "label": "旧区间"}]
        rbb = post(base + "/api/rebuild", {"state": st_both})
        wl = " ".join(rbb.get("warning_list") or [])
        chk("★ 区间+分段同时存在 ⇒ 报警告且分段优先",
            "分段优先" in wl, wl[:200] or "(没有警告)")
        chk("区间确实被忽略了（没有区间元信息）",
            not (rbb.get("regions") or []), str(rbb.get("regions"))[:120])
        chk("结果等于纯分段的结果（区间没掺进来）",
            rbb.get("n_onsets") == rbs.get("n_onsets"),
            f"{rbb.get('n_onsets')} vs {rbs.get('n_onsets')}")

        # 「全关」与「继承」是两件事：显式 main=[] 的段一个点都不采 ⇒ 要报
        st_off = dict(base_rg)
        st_off["segments"] = [{"at_ms": 0.0, "label": "静音段",
                              "main": [], "sub": [], "dp": []}]
        rbf = post(base + "/api/rebuild", {"state": st_off})
        chk("整段全关 ⇒ 采音点不足、明确失败（不静默出空谱）",
            not rbf.get("ok"), str(rbf.get("msg"))[:120])

        # 分段里的轨必须被 pitch 过滤覆盖（否则会被自动改写的 pitch_lo/hi 滤没）
        st_pf = dict(base_rg)
        st_pf["segments"] = [{"at_ms": 0.0, "label": "只要 other",
                              "main": [other], "sub": [], "dp": []}]
        rbp = post(base + "/api/rebuild", {"state": st_pf})
        chk("★ 分段指定的轨被纳入音高范围（不是 0 个点）",
            rbp.get("ok") and (rbp.get("segments") or [{}])[0].get("n", 0) > 0,
            str((rbp.get("segments") or [{}])[0])[:160])

        # 清空分段 ⇒ 回到基线
        st_cl = dict(base_rg)
        st_cl["segments"] = []
        rbc = post(base + "/api/rebuild", {"state": st_cl})
        chk("清空分段回到基线（逐点一致）",
            rbc.get("n_onsets") == n_base and not (rbc.get("segments") or []),
            f"{rbc.get('n_onsets')} vs {n_base}")

        # ============================================================ [7h]
        print("\n[7h] ★ 启动并桥接（/api/host*，docs/40）—— 用替身，不真起 Electron")
        real_ctl = SV.APP.hostctl

        class FakeCtl:
            def __init__(self):
                self.started = []
                self.stopped = 0
                self.injected = []

            def state(self):
                return {"present": True, "deps": True, "pid": 0, "pid_alive": False,
                        "cdp_up": False, "port": 9222, "log": "L", "pidfile": "P"}

            def start_and_bridge(self, url, progress=None, should_cancel=None):
                self.started.append(url)
                if progress:
                    progress(0.3, "替身：正在起")
                    progress(1.0, "替身：好了")
                return {"ok": True, "pid": 4242, "already": False}

            def stop_and_unbridge(self):
                self.stopped += 1
                return {"ok": True, "stopped": True, "pid": 4242, "note": ""}

            def inject_url(self, url):
                self.injected.append(url)
                return {"ok": True, "already": False}

        fake = FakeCtl()
        SV.APP.hostctl = fake
        try:
            h0 = get(base + "/api/host")[2]
            h0 = json.loads(h0)
            chk("GET /api/host 通", h0.get("ok"))
            chk("报出宿主在不在装没装", h0.get("present") is True and h0.get("deps") is True)
            chk("带上连接串（UI 面板上的复制按钮用）",
                "/ws?token=" in str(h0.get("url")), str(h0.get("url"))[:60])
            chk("带上 starting 标志", h0.get("starting") is False)

            st0 = post(base + "/api/host/start", {})
            chk("POST /api/host/start 立刻返回（不阻塞）",
                st0.get("ok") is True and st0.get("started") is True, str(st0)[:120])
            for _ in range(40):                       # 后台线程跑完
                if fake.started:
                    break
                time.sleep(0.05)
            chk("★ 后台真的去起了，并且拿到的是**我们的**连接串",
                len(fake.started) == 1 and "/ws?token=" in fake.started[0],
                str(fake.started)[:80])

            time.sleep(0.3)
            h1 = json.loads(get(base + "/api/host")[2])
            chk("★ 起完了 starting 回到 False（UI 不会一直转圈）",
                h1.get("starting") is False, str(h1.get("starting")))

            inj = post(base + "/api/host/inject", {})
            chk("POST /api/host/inject 能手动重推连接串",
                inj.get("ok") is True and len(fake.injected) == 1)

            sp = post(base + "/api/host/stop", {})
            chk("POST /api/host/stop 通", sp.get("ok") is True and fake.stopped == 1)

            # 失败也要如实回（不假装成功）
            def boom(url, progress=None, should_cancel=None):
                return {"ok": False, "stage": "cdp", "error": "调试端口不通"}
            fake.start_and_bridge = boom
            post(base + "/api/host/start", {})
            time.sleep(0.4)
            h2 = json.loads(get(base + "/api/host")[2])
            chk("失败后 starting 也会回到 False（不留死锁）", h2.get("starting") is False)

            # ★ 起两次要挡住（不许并发起两个宿主）
            spare = SV.APP.host_starting
            SV.APP.host_starting = True
            dup = post(base + "/api/host/start", {})
            chk("并发重复 start 被 409 挡住", dup.get("status") == 409, str(dup)[:100])
            SV.APP.host_starting = spare
        finally:
            SV.APP.hostctl = real_ctl
            SV.APP.host_starting = False

        # ============================================================ [8]
        print("\n[8] 错误处理")
        e1 = post(base + "/api/load", {"path": os.path.join(ROOT, "no_such.mid")})
        chk("不存在的文件报错", not e1.get("ok"), str(e1.get("error"))[:160])
        chk("错误是 4xx", e1.get("status") == 400, str(e1.get("status")))
        e2 = post(base + "/api/nope", {})
        chk("未知接口 404", e2.get("status") == 404, str(e2.get("status")))
        e3 = post(base + "/api/load", {"path": os.path.join(ROOT, "..", "x.mid")})
        chk("越界路径被拒", not e3.get("ok"), str(e3.get("error"))[:160])

        # ============================================================ [9]
        if ogg:
            print("\n[9] OGG 采样音源（--ogg，慢）")
            ogg_path = os.path.join(ROOT, "samples", "audio",
                                    "doublepress_demo_120.ogg")
            if not os.path.exists(ogg_path):
                print("       （没有 OGG 样本，跳过）")
            else:
                info2 = post(base + "/api/load", {"path": ogg_path}, timeout=600)
                chk("OGG 加载成功", info2.get("ok"), str(info2.get("error"))[:150])
                chk("OGG 用音源当预览音频",
                    bool(SV.APP.session.source_audio))
                chk("OGG 报告了自洽网格（v0.2 修复进到 UI）",
                    bool(info2.get("grid_fit")), str(info2.get("grid_fit"))[:110])
                chk("OGG 报告了检波偏置",
                    info2.get("detector_bias") is not None,
                    str(info2.get("detector_bias")))
                st_ogg = dict(SC.defaults())
                st_ogg["tracks_checked"] = info2["default_tracks_checked"]
                st_ogg["sub_checked"] = []
                st_ogg["dp_checked"] = info2["default_dp_checked"]
                st_ogg["current_track"] = info2["default_current_track"]
                st_ogg["song"] = info2["name"]
                dvo = post(base + "/api/derive", {"state": st_ogg})
                st_ogg["pitch_lo"], st_ogg["pitch_hi"] = dvo["pitch_lo"], dvo["pitch_hi"]
                rbo2 = post(base + "/api/rebuild", {"state": st_ogg})
                chk("OGG 出谱", rbo2.get("ok") and rbo2["n_floors"] > 0,
                    str(rbo2.get("n_floors")))
                auo = post(base + "/api/audio", {"state": st_ogg})
                chk("OGG 直接用原曲当预览音源",
                    auo.get("ok") and auo["path"].endswith(".ogg"),
                    str(auo.get("path"))[:120])
    # ============================================================ BDG（docs/38）
        print("\n[15] ★ BDG 工程当来源 + 桥端点 + 收回后重建")
        bdg = os.path.join(ROOT, "tests", "fixtures", "bdg", "v2_real_electric_hornet.bdg")
        bj = json.loads(get(base + "/api/bridge")[2].decode("utf-8"))
        chk("GET /api/bridge 有连接串", bool(bj.get("url", "").startswith("ws://127.0.0.1:")),
            str(bj.get("url"))[:60])
        chk("连接串带一次性 token", "token=" in str(bj.get("url")), "")
        chk("桥状态含统计", isinstance(bj.get("state", {}).get("stats"), dict),
            str(bj.get("state", {}).get("stats"))[:60])

        imp0 = post(base + "/api/bridge/import", {})
        chk("未连 BDG 时投射明确失败（不静默）",
            imp0.get("ok") is False and imp0.get("error"), str(imp0.get("error"))[:50])
        ad0 = post(base + "/api/bridge/adopt", {})
        chk("没投送过时收回明确失败", ad0.get("ok") is False, str(ad0.get("error"))[:50])

        if os.path.exists(bdg):
            bd = post(base + "/api/load", {"path": bdg})
            chk("BDG 工程能加载", bd.get("ok") is True, str(bd.get("error"))[:80])
            chk("标明来源是 BDG", bd.get("is_bdg") is True, "")
            chk("每条 BDG 轨 = 一条音轨", len(bd.get("tracks", [])) == 6,
                str(len(bd.get("tracks", []))))
            chk("点数合计 866",
                sum(t["notes"] for t in bd.get("tracks", [])) == 866,
                str(sum(t["notes"] for t in bd.get("tracks", []))))
            chk("带「建议角色」（控制轨 → 关）",
                [t.get("suggest") for t in bd["tracks"]] == ["", "", "", "", "off", "off"],
                str([t.get("suggest") for t in bd["tracks"]]))
            chk("默认勾主轨（建议为空时按启发式挑一条）",
                len(bd.get("default_tracks_checked", [])) >= 1,
                str(bd.get("default_tracks_checked")))
            chk("带上他的变速 + 合法档比对",
                bd.get("bdg", {}).get("fit", {}).get("n_exact") == 3,
                str(bd.get("bdg", {}).get("fit", {}))[:80])

            st_bdg = dict(state)
            st_bdg["tracks_checked"] = bd["default_tracks_checked"]
            st_bdg["sub_checked"] = bd["default_sub_checked"]
            st_bdg["dp_checked"] = bd["default_dp_checked"]
            st_bdg["current_track"] = bd["default_current_track"]
            st_bdg["song"] = bd["name"]
            dvb = post(base + "/api/derive", {"state": st_bdg})
            st_bdg["pitch_lo"], st_bdg["pitch_hi"] = dvb["pitch_lo"], dvb["pitch_hi"]
            rbb = post(base + "/api/rebuild", {"state": st_bdg})
            chk("BDG 源能出谱", rbb.get("ok") and rbb.get("n_floors", 0) > 0,
                str(rbb.get("n_floors")))
            n_before = rbb.get("n_floors", 0)

            # ★ 收回：把「编辑器里的进度」钉进采音结果，重建应当用它（层数随之变）
            fake = [{"ms": 1000.0 + i * 500.0} for i in range(6)]
            s_ad = SV.APP.session.adopt_onsets(fake)
            chk("adopt_onsets 钉住 6 个音", s_ad.get("n") == 6, str(s_ad))
            rbb2 = post(base + "/api/rebuild", {"state": st_bdg})
            chk("★ 重建改用收回来的进度（层数变了）",
                rbb2.get("ok") and rbb2.get("n_floors", 0) != n_before,
                f"{n_before} → {rbb2.get('n_floors')}")
            post(base + "/api/bridge/clear", {})
            chk("clear 之后 override 清掉", SV.APP.session.onsets_override is None, "")
            rbb3 = post(base + "/api/rebuild", {"state": st_bdg})
            chk("清掉后回到选轨采音", rbb3.get("n_floors") == n_before,
                f"{rbb3.get('n_floors')} vs {n_before}")
        else:
            chk("BDG fixture 存在", False, bdg)

        # ============================================================ [16]
        print("\n[16] ★ 收回轨道项目 + 去噪/直拟合（docs/44-45）")
        # 先加载一个 MIDI（重建要有源文件）
        _mid = os.path.join(ROOT, "samples", "audio", "doublepress_demo_120.mid")
        if not os.path.exists(_mid):
            _cs = [os.path.join(ROOT, "samples", f)
                   for f in os.listdir(os.path.join(ROOT, "samples"))
                   if f.lower().endswith((".mid", ".midi"))]
            _mid = _cs[0] if _cs else ""
        _i16 = post(base + "/api/load", {"path": _mid})
        chk("加载 MIDI（收回模式的载体）", _i16.get("ok"), str(_i16.get("error"))[:80])
        st16 = dict(SC.defaults())
        st16["tracks_checked"] = _i16["default_tracks_checked"]
        st16["sub_checked"] = _i16.get("default_sub_checked") or []
        st16["dp_checked"] = _i16["default_dp_checked"]
        st16["current_track"] = _i16["default_current_track"]
        st16["song"] = _i16["name"]

        # 伪造一份「BDG 面板按了『返回数据到谱面生成器』」的载荷
        pay16 = {
            "run": "R16",
            "anchor": {"baseBpm": 400.0, "offsetMs": 0.0},
            "n_points": 5, "n_added": 0,
            "tracks": [
                {"name": "ADO·主轨 trk0", "role": "main", "lane": "main:0",
                 "src_track": 0,
                 "points": [{"idx": 0, "beat": 0.0, "ms": 1000.0,
                             "src_tracks": [0]},
                            {"idx": 1, "beat": 4.0, "ms": 1150.0,
                             "src_tracks": [0]},
                            {"idx": 2, "beat": 8.0, "ms": 1300.0,
                             "src_tracks": [0, 2]}]},     # 跨轨簇
                {"name": "ADO·双押轨", "role": "dp", "lane": "dp:",
                 "src_track": None,
                 "points": [{"idx": 3, "beat": 12.0, "ms": 1450.0,
                             "src_tracks": []}]},
                {"name": "ADO·主轨 trk3", "role": "main", "lane": "main:3",
                 "src_track": 3,
                 "points": [{"idx": 4, "beat": 16.0, "ms": 1600.0,
                             "src_tracks": [3]}]},
            ],
        }
        r16 = post(base + "/api/bridge/back/apply", {"payload": pay16})
        chk("收回落地 ok", r16.get("ok"), str(r16.get("error"))[:120])
        chk("★ 我们的音轨 = 收回的那些轨（3 条）",
            len((r16.get("info") or {}).get("tracks", [])) == 3,
            str([t.get("name") for t in (r16.get("info") or {}).get("tracks", [])]))
        chk("音轨列表带 BDG 收回标记",
            all(t.get("bdg") for t in (r16.get("info") or {}).get("tracks", [])))
        g16 = json.loads(get(base + "/api/bridge/back")[2].decode("utf-8"))
        chk("GET /api/bridge/back 能查", g16.get("ok"), str(g16.get("error"))[:80])
        chk("收回 4 个 onset + 1 个双押",
            g16.get("meta", {}).get("n_onsets") == 4
            and g16.get("meta", {}).get("n_dp") == 1, str(g16.get("meta"))[:120])
        chk("跨轨簇的源轨号原样带过来",
            sorted((SV.APP.session.onsets[2].src_tracks or ())) == [0, 2],
            str(SV.APP.session.onsets[2].src_tracks))

        dv16 = post(base + "/api/derive", {"state": st16})
        chk("derive 走「轨道项目模式」", dv16.get("lanes_back") is True,
            str(dv16.get("hint"))[:60])
        rb16 = post(base + "/api/rebuild", {"state": st16})
        chk("★ 轨道项目模式能重建（不再从 MIDI 采音）", rb16.get("ok"),
            str(rb16.get("msg") or rb16.get("error"))[:120])
        chk("onset 数 = 收回来的 4 个", rb16.get("n_onsets") == 4,
            str(rb16.get("n_onsets")))
        chk("双押轨的点也能投回去（dp 泳道不丢）",
            len(SV.APP.session.dp_lane_onsets()) == 1,
            str(SV.APP.session.dp_lane_onsets())[:80])

        # 直拟合 + 去噪（state 里那 6 个字段）
        st16b = dict(st16)
        st16b["fit_mode"] = "direct"
        st16b["denoise_on"] = True
        rb16b = post(base + "/api/rebuild", {"state": st16b})
        chk("★ 直拟合能出谱", rb16b.get("ok"),
            str(rb16b.get("msg") or rb16b.get("error"))[:120])
        chk("直拟合自检：逐点精确",
            (rb16b.get("fit") or {}).get("err_max_ms") == 0.0,
            str(rb16b.get("fit"))[:100])
        chk("去噪报告上屏（warning_list 里有去噪那条）",
            any("去噪" in w for w in (rb16b.get("warning_list") or [])),
            str(rb16b.get("warning_list"))[:160])
        chk("直拟合的报告也上屏",
            any("直拟合" in w for w in (rb16b.get("warning_list") or [])),
            "")
        st16c = dict(st16b)
        st16c["fit_mode"] = "solve"
        rb16c = post(base + "/api/rebuild", {"state": st16c})
        chk("切回最优化照常", rb16c.get("ok") and rb16c.get("n_floors", 0) > 0, "")

        cl16 = post(base + "/api/bridge/back/clear", {})
        chk("清掉收回", cl16.get("ok"), "")
        rb16d = post(base + "/api/rebuild", {"state": st16})
        chk("清掉后回到从选轨采音", rb16d.get("ok")
            and rb16d.get("n_onsets") != 4, str(rb16d.get("n_onsets")))

        # ============================================================ [17]
        print("\n[17] ★ 毫秒时间戳当来源（docs/45 §7）—— 用户那条箭头的前半段")
        _tsd = os.path.join(ROOT, "out")
        os.makedirs(_tsd, exist_ok=True)
        _tsp = os.path.join(_tsd, "_sidecar_ts.txt")
        with open(_tsp, "w", encoding="utf-8") as fh:
            fh.write("\n".join("%.3f" % (2.131 + k * 150.0) for k in range(120)) + "\n")
        i17 = post(base + "/api/load", {"path": _tsp})
        chk("时间戳文件能当来源加载", i17.get("ok") is True, str(i17.get("error"))[:80])
        chk("标明来源是时间戳", i17.get("is_ts") is True, "")
        chk("★ 默认 merge_ms = 0（30ms 会把密集处的点悄悄并掉）",
            i17.get("default_merge_ms") == 0.0, str(i17.get("default_merge_ms")))
        chk("★ 默认直拟合 + 去噪开",
            i17.get("default_fit_mode") == "direct"
            and i17.get("default_denoise_on") is True,
            f"{i17.get('default_fit_mode')}/{i17.get('default_denoise_on')}")
        chk("读回 120 个点", (i17.get("ts") or {}).get("n_kept") == 120,
            str(i17.get("ts"))[:100])
        chk("网格自动算出来（bpm≈400，格 = 砖长/分母）",
            abs((i17.get("ts_grid") or {}).get("bpm", 0) - 400.0) < 1.0
            and abs((i17.get("ts_grid") or {}).get("step_ms", 0)
                    - (i17.get("ts_grid") or {}).get("period_ms", 0)
                    / max(1, (i17.get("ts_grid") or {}).get("div", 1))) < 1e-6,
            str(i17.get("ts_grid"))[:120])
        chk("文件信息带网格行（界面上看得见）",
            bool(i17.get("grid_fit")), str(i17.get("grid_fit"))[:70])
        st17 = dict(SC.defaults())
        st17["tracks_checked"] = [0]
        st17["merge_ms"] = 0.0
        st17["fit_mode"] = "direct"
        st17["dp_checked"] = []
        r17 = post(base + "/api/rebuild", {"state": st17})
        chk("直拟合能出谱", r17.get("ok"), str(r17.get("msg") or r17.get("error"))[:100])
        chk("onset 数 = 120", r17.get("n_onsets") == 120, str(r17.get("n_onsets")))
        chk("★★ 时序误差 = 0（直拟合的立身之本）",
            (r17.get("fit") or {}).get("err_max_ms") == 0.0,
            str(r17.get("fit"))[:100])
        chk("去噪报告里有格（分母/相位都在）",
            (r17.get("denoise") or {}).get("div") in (1, 2, 4, 8, 16, 32)
            and (r17.get("denoise") or {}).get("phase_ms") is not None,
            str((r17.get("denoise") or {}).get("grid"))[:110])
        # ★ 选档策略 / 最小角度这两件「用户参数有没有生效」的事（docs/46）
        st17b = dict(st17)
        st17b["tier_mode"] = "sticky"
        st17b["travel_min"] = 90.0
        r17b = post(base + "/api/rebuild", {"state": st17b})
        chk("选档策略能切到「粘住上一档」",
            (r17b.get("fit") or {}).get("tier_mode") == "sticky",
            str((r17b.get("fit") or {}).get("tier_mode")))
        chk("★ 最小角度 90° 真的被用上（不再有 <90° 的格子）",
            float((r17b.get("fit") or {}).get("travel_min", 0)) >= 90.0 - 1e-9,
            str((r17b.get("fit") or {}).get("travel_min")))
        chk("直拟合那条警告里报出换档/发卡弯",
            any("发卡弯" in w for w in (r17b.get("warning_list") or [])),
            str(r17b.get("warning_list"))[:140])

        # ============================================================ [17b]
        print("\n[17b] ★★ 时间戳 JSON（DEMUCS 分轨）当来源 —— docs/56")
        _sjd = os.path.join(ROOT, "tests", "fixtures", "stemjson")
        _sj = os.path.join(_sjd, "full_6stems.json")
        i17c = post(base + "/api/load", {"path": _sj})
        chk("时间戳 JSON 能当来源加载", i17c.get("ok") is True,
            str(i17c.get("error"))[:90])
        chk("★ 标明 is_stem_json（与纯时间戳区分开）",
            i17c.get("is_stem_json") is True and i17c.get("is_ts") is True, "")
        chk("★ 一路一条音轨（6 路 ⇒ 6 条轨）",
            len(i17c.get("tracks") or []) == 6,
            str([t.get("name") for t in (i17c.get("tracks") or [])]))
        chk("音轨名带中文路名", (i17c.get("tracks") or [{}])[0].get("name") == "旋律·melody",
            str((i17c.get("tracks") or [{}])[0].get("name")))
        chk("★ 默认只勾主旋律（其余只标注，自己勾）",
            i17c.get("default_tracks_checked") == [0]
            and i17c.get("default_sub_checked") == []
            and i17c.get("default_dp_checked") == [],
            str(i17c.get("default_tracks_checked")))
        chk("★ 默认 merge_ms=0 / 直拟合 / 去噪开",
            i17c.get("default_merge_ms") == 0.0
            and i17c.get("default_fit_mode") == "direct"
            and i17c.get("default_denoise_on") is True, "")
        chk("建议角色带进 info（鼓 = 双押）",
            (i17c.get("stem_roles") or {}).get("2") == "dp",
            str(i17c.get("stem_roles")))
        chk("轨道行带人话注释", bool((i17c.get("tracks") or [{}])[0].get("note")), "")
        chk("文件信息带每一路摘要（6 行 / 83 点）",
            len((i17c.get("stem") or {}).get("stems") or []) == 6
            and (i17c.get("stem") or {}).get("n_points") == 83,
            str((i17c.get("stem") or {}).get("n_points")))
        chk("尾部长度 = duration_sec", abs(i17c.get("length_ms", 0) - 202378.0) < 1e-6,
            str(i17c.get("length_ms")))
        chk("原曲不在 ⇒ 不绑但上屏说明",
            i17c.get("source_audio") == ""
            and any("原曲找不到" in w for w in (i17c.get("warning_list") or [])),
            str(i17c.get("warning_list"))[:120])
        chk("载入的取舍账也交给前端（warning_list）",
            isinstance(i17c.get("warning_list"), list)
            and any("时间戳 JSON" in w for w in i17c["warning_list"]),
            str(i17c.get("warning_list"))[:120])
        st17c = dict(SC.defaults())
        st17c["tracks_checked"] = [0]
        st17c["merge_ms"] = 0.0
        st17c["fit_mode"] = "direct"
        st17c["dp_checked"] = []
        r17c = post(base + "/api/rebuild", {"state": st17c})
        chk("主旋律 32 点直拟合出谱", r17c.get("ok") and r17c.get("n_onsets") == 32,
            str(r17c.get("n_onsets")))
        chk("★★ 时序误差 = 0", (r17c.get("fit") or {}).get("err_max_ms") == 0.0,
            str(r17c.get("fit"))[:90])
        st17d = dict(st17c)
        st17d["tracks_checked"] = [0, 2]
        r17d = post(base + "/api/rebuild", {"state": st17d})
        chk("★ 再勾鼓轨 ⇒ 主轨取并集（32 → 48）",
            r17d.get("n_onsets") == 48, str(r17d.get("n_onsets")))
        # ★ 结构化 JSON 必须**明确拒绝**，绝不出「顶层数字」那张垃圾谱（docs/56 §3）
        i17e = post(base + "/api/load", {"path": os.path.join(_sjd, "not_stem.json")})
        chk("★★ 结构化 JSON（BDG 味）明确拒绝",
            i17e.get("ok") is not True
            and "读不出时间戳" in str(i17e.get("error")), str(i17e.get("error"))[:90])
        _sc, _sh, _sb = get(base + "/api/samples")
        chk("samples 菜单里有时间戳 JSON 示例",
            any(s.endswith(".json") for s in
                json.loads(_sb.decode("utf-8")).get("samples", [])),
            str(json.loads(_sb.decode("utf-8")).get("samples", []))[:110])
        # ★★ 切回 [17] 那份纯时间戳 —— 后面的小节（[18] 采bpm…）全都建立在
        #    它的「120 点 / 400bpm / 砖长 150ms」上，不切回去它们会读到 32 点。
        i17f = post(base + "/api/load", {"path": _tsp})
        chk("切回纯时间戳（后续小节依赖它的 120 点）",
            i17f.get("ok") is True and i17f.get("is_stem_json") is not True
            and (i17f.get("ts") or {}).get("n_kept") == 120,
            f"{i17f.get('is_stem_json')}/{(i17f.get('ts') or {}).get('n_kept')}")

        # ============================================================ [18]
        print("\n[18] ★ ③b 采bpm（xk base / 大直线）—— docs/47")
        chk("schema 里有 xk 组（界面自动出现一区）",
            any(g.get("id") == "xk" for g in SC.schema()["groups"]), "")
        chk("有「采bpm（xk base）」字段且落在 xk 组里",
            any(f.get("key") == "xk_base" and f.get("group") == "xk"
                for f in SC.schema()["fields"]), "")
        _d18 = SC.defaults()
        chk("默认：关（走原路径）+ tbpm 没填 + 没区间",
            _d18.get("xk_base") == 0 and _d18.get("xk_tbpm") == 0.0
            and _d18.get("xk_ranges") == [], "")
        st18 = dict(st17)                       # 同一份 120 点 / 400bpm / 砖长 150ms
        st18["xk_base"] = 4
        st18["xk_tbpm"] = 100.0                 # ×4 ⇒ cbpm 400 ⇒ 砖长 150（同一个格子）
        st18["xk_ranges"] = [{"start_ms": 3000.0, "end_ms": 6000.0, "xk_base": 4,
                              "tracks": [], "label": "测"}]
        r18 = post(base + "/api/rebuild", {"state": st18})
        chk("采bpm 开着能出谱", r18.get("ok"),
            str(r18.get("msg") or r18.get("error"))[:100])
        _x18 = r18.get("xk") or {}
        chk("★ 报告里有区间行 + 注入砖数",
            bool(_x18.get("rows")) and _x18.get("n_synth", 0) > 0, str(_x18)[:130])
        chk("★ 区间内被取代的 onset **报了数**（不静默）",
            _x18.get("n_dropped", 0) > 0, str(_x18.get("n_dropped")))
        chk("★ 区间外**原样保留**",
            _x18.get("n_outside", 0) > 0, str(_x18.get("n_outside")))
        chk("★ 砖长 = 150ms（tbpm100 × 4k）",
            abs(_x18["rows"][0]["period_ms"] - 150.0) < 1e-6,
            str(_x18["rows"][0])[:130])
        chk("★★ 基准 BPM 被**钉死到 cbpm 400**（并报出来）",
            any("钉死到 cbpm 400" in w for w in (r18.get("warning_list") or [])),
            str(r18.get("warning_list"))[:150])
        chk("★★ 时序误差 = 0（骨架是**构造**出来的，不是拟合）",
            (r18.get("fit") or {}).get("err_max_ms") == 0.0,
            str(r18.get("fit"))[:100])
        chk("报告里写明「区间外走原路径」",
            "原路径" in (_x18.get("text") or ""), str(_x18.get("text"))[:120])
        chk("onset 数 = 区间外 + 骨架砖（账对得上）",
            r18.get("n_onsets") == _x18.get("n_outside", 0) + _x18.get("n_synth", 0),
            f"{r18.get('n_onsets')} vs {_x18.get('n_outside')}+{_x18.get('n_synth')}")
        # ★ 起止写**格子号**（1 起算）也能跑
        st18f = dict(st18)
        st18f["xk_ranges"] = [{"start_tile": 21, "end_tile": 41, "xk_base": 4}]
        r18f = post(base + "/api/rebuild", {"state": st18f})
        chk("★ 起止写**格子号**也能出谱", r18f.get("ok"),
            str(r18f.get("msg") or r18f.get("error"))[:100])
        chk("格子 21~41 ⇒ 21 块砖（**两端都算**）",
            (r18f.get("xk") or {}).get("n_synth") == 21,
            str((r18f.get("xk") or {}).get("n_synth")))
        # ★ 没框区间 ⇒ 全曲采bpm（并报出来）
        st18g = dict(st18)
        st18g["xk_ranges"] = []
        r18g = post(base + "/api/rebuild", {"state": st18g})
        chk("★ 没框区间 ⇒ **全曲采bpm**，并报出来",
            any("全曲" in w for w in (r18g.get("warning_list") or [])),
            str(r18g.get("warning_list"))[:150])
        chk("全曲采bpm 时区间外一个都不剩（n_outside=0）",
            (r18g.get("xk") or {}).get("n_outside") == 0,
            str((r18g.get("xk") or {}).get("n_outside")))
        # ★ 八度校验：tbpm 50 × 4 = cbpm 200 ⇒ 砖长 300，而真音是 150 ⇒ 差 ÷2
        st18b = dict(st18)
        st18b["xk_tbpm"] = 50.0
        r18b = post(base + "/api/rebuild", {"state": st18b})
        chk("★ 八度校验：砖长与去噪解出的差 ÷2 ⇒ **报出来**",
            any("八度" in w for w in (r18b.get("warning_list") or [])),
            str(r18b.get("warning_list"))[:170])
        # ★ 关掉 ⇒ 老路径逐字节不变
        st18c = dict(st18)
        st18c.update({"xk_base": 0, "xk_tbpm": 0.0, "xk_ranges": []})
        r18c = post(base + "/api/rebuild", {"state": st18c})
        chk("★★ 关掉采bpm ⇒ onset 数回到 120（老路径逐字节不变）",
            r18c.get("n_onsets") == 120, str(r18c.get("n_onsets")))
        chk("关掉时 xk 报告是空的", not (r18c.get("xk") or {}).get("rows"), "")
        # ★ tbpm 没填 ⇒ 整组不生效（不静默）
        st18d = dict(st18)
        st18d["xk_tbpm"] = 0.0
        r18d = post(base + "/api/rebuild", {"state": st18d})
        chk("★ tbpm 没填 ⇒ 整组不生效并报出来",
            any("不生效" in w for w in (r18d.get("warning_list") or [])),
            str(r18d.get("warning_list"))[:150])
        chk("没填 tbpm 时没有注入（onset 数还是 120）",
            r18d.get("n_onsets") == 120, str(r18d.get("n_onsets")))
        # ★ 区间重叠 ⇒ 整组不生效（猜哪个赢都是错）
        st18e = dict(st18)
        st18e["xk_ranges"] = [{"start_ms": 3000.0, "end_ms": 6000.0, "xk_base": 4},
                              {"start_ms": 5000.0, "end_ms": 8000.0, "xk_base": 4}]
        r18e = post(base + "/api/rebuild", {"state": st18e})
        chk("★ 区间**重叠** ⇒ 整组不生效并报出来",
            any("重叠" in w for w in (r18e.get("warning_list") or [])),
            str(r18e.get("warning_list"))[:150])
        # ★★ 砖数硬上限：离谱区间必须**很快报错**，不许把 sidecar 卡几十秒
        #    （实测没有上限时 0~1e8ms = 66 万块砖 ⇒ 53 秒，界面就是「进度条冻死」）
        st18h = dict(st18)
        st18h["xk_ranges"] = [{"start_ms": 0.0, "end_ms": 1e8}]
        _t0 = time.time()
        r18h = post(base + "/api/rebuild", {"state": st18h})
        _dt = time.time() - _t0
        chk("★ 离谱区间 ⇒ **整组不生效**并报出「上限」",
            any("上限" in w for w in (r18h.get("warning_list") or [])),
            str(r18h.get("warning_list"))[:160])
        chk("★★ 而且**很快**（不许卡几十秒）", _dt < 10.0, f"{_dt:.2f}s")
        # ★★ 采bpm 开着时 **② 主轨一条都不勾也是合法的**（主轨本来就该失效，
        #    `docs/47` §1 第 5 条）。用户真机踩过：不勾主轨 + 开采bpm ⇒
        #    每次重建都被「没有可采音的音轨」拒掉、只保留上一张谱面 ⇒
        #    看起来就是「重新生成 / 进度条死了」，而且双押永远走不到。
        st18i = dict(st18)
        st18i["tracks_checked"] = []
        r18i = post(base + "/api/rebuild", {"state": st18i})
        chk("★★ 采bpm 开 + 主轨一条不勾 ⇒ **不再拒算**",
            r18i.get("ok") is True,
            str(r18i.get("msg") or r18i.get("error"))[:110])
        chk("★ 而且照样注入骨架",
            ((r18i.get("xk") or {}).get("n_synth") or 0) > 0,
            str((r18i.get("xk") or {}).get("n_synth")))
        chk("★ 并说明「② 主轨不参与采音」",
            any("主轨" in w and "不参与" in w
                for w in (r18i.get("warning_list") or [])),
            str(r18i.get("warning_list"))[:150])
        st18j = dict(st18i)
        st18j.update({"xk_base": 0, "xk_tbpm": 0.0, "xk_ranges": []})
        r18j = post(base + "/api/rebuild", {"state": st18j})
        chk("★ 关掉采bpm 后，没勾主轨**仍然拒绝**（老行为不变）",
            r18j.get("ok") is False
            and "没有可采音的音轨" in str(r18j.get("msg")),
            str(r18j.get("msg"))[:110])
        chk("★ 重建失败时 xk 报告**不留上一轮的**（不许静默的陈报告）",
            not (r18j.get("xk") or {}).get("rows"), str(r18j.get("xk"))[:110])
        # ★★ 全曲采bpm + 主轨一条不勾：**最容易踩的一格**（全曲范围要取「曲子长度」，
        #    不能取「现有 onset 的范围」—— 主轨不勾时 onset 是空的，会算成空区间）
        st18k = dict(st18)
        st18k["tracks_checked"] = []
        st18k["xk_ranges"] = []
        r18k = post(base + "/api/rebuild", {"state": st18k})
        chk("★★ 全曲采bpm + 主轨不勾 ⇒ 也能出谱（不再报「采音点少于 2 个」）",
            r18k.get("ok") is True,
            str(r18k.get("msg") or r18k.get("error"))[:110])
        chk("★ 全曲的砖数 = 整首曲子 ÷ 砖长（>0）",
            ((r18k.get("xk") or {}).get("n_synth") or 0) > 100,
            str((r18k.get("xk") or {}).get("n_synth")))
        chk("★ 全曲报告写明是「整首曲子」",
            any("整首曲子" in w for w in (r18k.get("warning_list") or [])),
            str(r18k.get("warning_list"))[:150])
        chk("★ 失败时 warning_list 也带回来了（真因不被吃掉）",
            isinstance(r18j.get("warning_list"), list),
            str(type(r18j.get("warning_list"))))

        # ============================================================ [18b]
        print("\n[18b] ★★ 拟合容差 + 使用激进的拟合策略（15° 阶梯）—— docs/57")
        _fs = {f.get("key"): f for f in SC.schema()["fields"]}
        chk("schema 有「拟合容差」且默认 100ms（用户口径 0~100）",
            _fs.get("fit_tol_ms", {}).get("default") == 100.0
            and _fs.get("fit_tol_ms", {}).get("min") == 0.0
            and _fs.get("fit_tol_ms", {}).get("max") == 100.0,
            str(_fs.get("fit_tol_ms")))
        chk("schema 有「使用激进的拟合策略」且**默认关**",
            _fs.get("aggressive_fit", {}).get("default") is False, "")
        chk("★ 旧字段 `denoise_radius_ms` 已撤（0 = 全吸 与「容差」直觉相反）",
            "denoise_radius_ms" not in _fs, "")
        _told = os.path.join(ROOT, "out", "_sidecar_jitter.txt")
        os.makedirs(os.path.dirname(_told), exist_ok=True)
        import random as _rnd
        _r = _rnd.Random(11)
        _t, _ts2 = 1000.0, []
        for _i in range(60):
            _ts2.append(_t + _r.uniform(-25.0, 25.0))
            _t += (4 if _i % 6 else 2) * 150.0 / 4
        with open(_told, "w", encoding="utf-8") as fh:
            fh.write("\n".join("%.3f" % x for x in sorted(_ts2)) + "\n")
        i18b = post(base + "/api/load", {"path": _told})
        chk("抖动时间戳能当来源", i18b.get("ok") is True, str(i18b.get("error"))[:80])
        st18b = dict(SC.defaults())
        st18b.update({"tracks_checked": [0], "dp_checked": [], "merge_ms": 0.0,
                      "fit_mode": "direct", "denoise_on": True, "tier_mode": "dp"})
        st18b["aggressive_fit"] = False
        st18b["fit_tol_ms"] = 100.0
        r18b0 = post(base + "/api/rebuild", {"state": st18b})
        F0 = r18b0.get("fit") or {}
        chk("关着激进拟合 ⇒ 报告里没有阶梯那一栏",
            not F0.get("ladder_on") and F0.get("n_floors") == 61,
            f"ladder_on={F0.get('ladder_on')} 层={F0.get('n_floors')}")
        st18b["aggressive_fit"] = True
        r18b1 = post(base + "/api/rebuild", {"state": st18b})
        F1 = r18b1.get("fit") or {}
        chk("★★ 开着 ⇒ 非双押格角度**全部**落在 15° 的整数倍上",
            F1.get("ladder_on") is True and F1.get("n_ladder_bad") == 0,
            f"ladder_on={F1.get('ladder_on')} 非阶梯格={F1.get('n_ladder_bad')}")
        chk("★ 真挪了，且每个音 ≤ 容差（100ms）",
            (F1.get("n_ladder_moved") or 0) > 20
            and (F1.get("ladder_move_max_ms") or 0) <= 100.0 + 1e-9,
            f"修正={F1.get('n_ladder_moved')} max={F1.get('ladder_move_max_ms')}")
        # ★★ 2026-10 第二版口径：用户「最小夹角不可以在 30° 以下」⇒ 激进模式**不再**
        #   把最小角度钉死成阶梯步长 15°，而是 `max(15, 框里的值)`（后端照样不信前端）。
        chk("★ 激进模式下最小角度 = max(15, 框里的值)（不再被钉死成 15）",
            F1.get("travel_min_setting") == 20.0, str(F1.get("travel_min_setting")))
        st18b2 = dict(st18b)
        st18b2["travel_min"] = 90.0
        r18b2 = post(base + "/api/rebuild", {"state": st18b2})
        chk("★ 激进模式下 `travel_min=90` **照用 90**（阶梯仍只走 15° 的整数倍）",
            ((r18b2.get("fit") or {}).get("travel_min_setting")) == 90.0,
            str((r18b2.get("fit") or {}).get("travel_min_setting")))
        st18b["fit_tol_ms"] = 5.0
        r18b3 = post(base + "/api/rebuild", {"state": st18b})
        F3 = r18b3.get("fit") or {}
        chk("★ 容差 5ms ⇒ 一部分挪不动：**原样保留 + 计数 + 上屏**",
            (F3.get("n_ladder_raw") or 0) > 0
            and (F3.get("n_ladder_bad") or 0) > 0
            and any("挪不动" in w for w in (r18b3.get("warning_list") or [])),
            f"挪不动={F3.get('n_ladder_raw')} 非阶梯={F3.get('n_ladder_bad')}")
        chk("★ 挪动量仍然 ≤ 容差（不硬掰）",
            (F3.get("ladder_move_max_ms") or 0) <= 5.0 + 1e-9,
            str(F3.get("ladder_move_max_ms")))
        st18b["fit_tol_ms"] = 0.0
        r18b4 = post(base + "/api/rebuild", {"state": st18b})
        F4 = r18b4.get("fit") or {}
        chk("★★ 容差 0 ⇒ 一个点都不挪（用户口径：0 = 保真）",
            (F4.get("n_ladder_moved") or 0) == 0
            and (F4.get("ladder_move_max_ms") or 0) == 0.0,
            f"修正={F4.get('n_ladder_moved')} max={F4.get('ladder_move_max_ms')}")
        # 去噪那一侧：容差 = 吸附半径，0 = 一个点都不吸（★ 这条要用**格能成立**的数据：
        # 我们那份 ±25ms 的人工抖动连网格都凑不出来（`格级 R < 0.30`），
        # 拿它验「吸不吸」是空过。MemoryLocked 的网格成立且有点离格。）
        st18m = dict(st18b)
        st18m["aggressive_fit"] = False
        st18m["fit_tol_ms"] = 0.0
        i18m = post(base + "/api/load",
                    {"path": os.path.join(ROOT, "samples", "_external", "MemoryLocked.mid")})
        st18m["tracks_checked"] = list(i18m.get("default_tracks_checked") or [0])
        r18b5 = post(base + "/api/rebuild", {"state": st18m})
        _d5 = r18b5.get("denoise") or {}
        chk("★★ 容差 0 ⇒ 去噪也不吸（旧语义「0 = 全吸」已改正）",
            _d5.get("on") is True
            and ((_d5.get("report") or {}).get("n_moved") or 0) == 0
            and ((_d5.get("report") or {}).get("move_max_ms") or 0) == 0.0
            and (_d5.get("n_out_of_radius") or 0) > 0,
            str({"moved": (_d5.get("report") or {}).get("n_moved"),
                 "max": (_d5.get("report") or {}).get("move_max_ms"),
                 "out": _d5.get("n_out_of_radius")}))
        _t18b6 = dict(st18m)
        _t18b6["fit_tol_ms"] = 20.0
        r18b6 = post(base + "/api/rebuild", {"state": _t18b6})
        _d6 = r18b6.get("denoise") or {}
        chk("★ 容差 20ms ⇒ 吸 20ms 内的点、其余原样保留并上屏",
            (r18b6.get("ok") is True
             and ((_d6.get("report") or {}).get("n_moved") or 0) > 0
             and ((_d6.get("report") or {}).get("move_max_ms") or 0) <= 20.0 + 1e-9
             and any("容差" in w for w in (r18b6.get("warning_list") or []))),
            f"吸了={(_d6.get('report') or {}).get('n_moved')} "
            f"max={(_d6.get('report') or {}).get('move_max_ms')}")
        # ============================================================ [18b2]
        print("\n[18b2] ★★ 激进策略 × 求解方式：**静默失效必须明说**"
              "（用户 2026-10 报「AI 的 MIDI 用激进策略跑不通」）")
        # ① 「使用激进的采音策略」`aggressive_pick` 是 `core.ladder` 那条路，
        #    只有最优化会走；直拟合下勾了它以前**一个字都不说** ⇒ 看起来像「坏了」。
        _st18p = dict(SC.defaults())
        _st18p.update({"tracks_checked": [0], "dp_checked": [], "merge_ms": 0.0,
                       "fit_mode": "direct", "denoise_on": True,
                       "aggressive_fit": False, "aggressive_pick": True})
        _r18p = post(base + "/api/rebuild", {"state": _st18p})
        _w18p = _r18p.get("warning_list") or []
        chk("★ 直拟合 + 「激进采音」⇒ 明确上屏「这一次没用上」（不再静默）",
            _r18p.get("ok") is True
            and any("激进的采音策略" in w and "没用上" in w for w in _w18p),
            str([w for w in _w18p if "激进" in w])[:150])
        _st18q = dict(_st18p)
        _st18q["fit_mode"] = "solve"           # 换最优化 ⇒ 这条警告必须消失
        _r18q = post(base + "/api/rebuild", {"state": _st18q})
        chk("★ 换成最优化 ⇒ 那句警告消失（它真的在描述「这条路走不到」）",
            _r18q.get("ok") is True
            and not any("没用上" in w for w in (_r18q.get("warning_list") or [])),
            str([w for w in (_r18q.get("warning_list") or []) if "激进" in w])[:150])
        # ② 最大夹角 < 180° 与「直线格 / Pause 格 = 180°」是**定义冲突** ⇒ 必须说
        _st18r = dict(_st18q)
        _st18r["travel_max"] = 90.0
        _r18r = post(base + "/api/rebuild", {"state": _st18r})
        chk("★ 最大夹角 90°（< 180）⇒ 上屏说明「直线格必然是 180°，这一档满足不了」",
            _r18r.get("ok") is True
            and any("最大夹角" in w and "180" in w
                    for w in (_r18r.get("warning_list") or [])),
            str([w for w in (_r18r.get("warning_list") or [])
                 if "最大夹角" in w])[:150])
        _st18r["travel_max"] = 270.0
        _r18s = post(base + "/api/rebuild", {"state": _st18r})
        chk("★ 最大夹角 270° ⇒ 没有那句抱怨，且违规 0（阶梯/DP 都认上界）",
            _r18s.get("ok") is True and (_r18s.get("n_violations") or 0) == 0
            and not any("最大夹角" in w
                        for w in (_r18s.get("warning_list") or [])),
            f"违规={_r18s.get('n_violations')} "
            f"{[v.get('code') for v in (_r18s.get('violations') or [])][:3]}")
        post(base + "/api/load", {"path": _tsp})       # 回到 120 点时间戳（后续小节用）

        # ============================================================ [18c]
        print("\n[18c] ★★ 自动贴合（时值体检 /api/tempo_diag）—— docs/58")
        # ★ 用**倍频陷阱**夹具当输入：它是「真砖长 90.909、但有一路会被认成 181.8」的
        #   最小复现（`docs/58` §2），拿它断言砖长才有意义。
        _trap = os.path.join(ROOT, "tests", "fixtures", "stemjson", "octave_trap.json")
        i18c = post(base + "/api/load", {"path": _trap})
        chk("载入倍频陷阱夹具（体检的输入）", i18c.get("ok") is True,
            str(i18c.get("error"))[:70])
        td1 = post(base + "/api/tempo_diag", {})
        chk("★ /api/tempo_diag 通", td1.get("ok") is True, str(td1)[:110])
        chk("★★ 认出真砖长 90.909ms（没被那一路的 181.8 骗走）",
            abs((td1.get("brick_ms") or 0) - 90.9091) < 0.1,
            "brick=%.4f bpm=%.1f src=%s" % (td1.get("brick_ms") or 0,
                                            td1.get("bpm") or 0,
                                            td1.get("brick_source")))
        chk("★ 给出建议参数（砖长提示 / 容差 / 去密 / 激进 / 主轨 / 双押清空）",
            isinstance((td1.get("suggest") or {}).get("denoise_hint_ms"), (int, float))
            and isinstance((td1.get("suggest") or {}).get("fit_tol_ms"), (int, float))
            and isinstance((td1.get("suggest") or {}).get("merge_ms"), (int, float))
            and isinstance((td1.get("suggest") or {}).get("aggressive_fit"), bool)
            and (td1.get("suggest") or {}).get("tracks_checked")
            and (td1.get("suggest") or {}).get("dp_checked") == [],
            str(td1.get("suggest"))[:130])
        chk("★ 主轨挑的是点最多的那条（旋律）",
            "旋律" in str((td1.get("suggest") or {}).get("main_label")),
            str((td1.get("suggest") or {}).get("main_label")))
        chk("★ 每路都有「残差 中位/p90/max + 覆盖率」",
            bool(td1.get("streams"))
            and all(("median_ms" in r and "cover" in r) for r in td1["streams"]),
            str(td1["streams"])[:120])
        chk("★ 人话说明非空（不许只回一堆数字）",
            len(td1.get("why") or []) >= 3, str(td1.get("why"))[:110])
        chk("★ 试算两种模式都带回来了（用于比「像不像人」）",
            ((td1.get("probe") or {}).get("off") or {}).get("ok") is True
            and ((td1.get("probe") or {}).get("on") or {}).get("ok") is True,
            str(td1.get("probe"))[:110])
        td2 = post(base + "/api/tempo_diag", {})
        chk("★★ 体检是**只读**的：连着跑两次结果一致（不改任何状态）",
            td1.get("brick_ms") == td2.get("brick_ms")
            and td1.get("suggest") == td2.get("suggest"), "")
        # 按建议套用 ⇒ 真出谱
        _sg = td1.get("suggest") or {}
        st18c = dict(SC.defaults())
        st18c.update({"tracks_checked": _sg.get("tracks_checked") or [0],
                      "dp_checked": [], "sub_checked": [],
                      "fit_mode": _sg.get("fit_mode") or "direct",
                      "denoise_on": True,
                      "denoise_hint_ms": _sg.get("denoise_hint_ms") or 0.0,
                      "fit_tol_ms": _sg.get("fit_tol_ms") or 0.0,
                      "merge_ms": _sg.get("merge_ms") or 0.0,
                      "aggressive_fit": bool(_sg.get("aggressive_fit"))})
        r18c = post(base + "/api/rebuild", {"state": st18c})
        F = r18c.get("fit") or {}
        chk("★ 按建议套用能出谱", r18c.get("ok") is True,
            str(r18c.get("msg") or r18c.get("error"))[:100])
        chk("★★ 套用后非双押格角度全在 15° 整数倍上（若建议开了激进）",
            (F.get("n_ladder_bad") == 0) if _sg.get("aggressive_fit") else True,
            "非阶梯格=%s 直线=%.1f%%" % (F.get("n_ladder_bad"),
                                         (F.get("straight_frac") or 0) * 100))
        # 异构示例（6 路砖长互不相容）⇒ 也要能跑，但必须**明说不可靠**
        _sample = os.path.join(ROOT, "samples", "示例·分轨时间戳.json")
        post(base + "/api/load", {"path": _sample})
        td3 = post(base + "/api/tempo_diag", {})
        chk("★ 各路节奏互不相容时：仍然给答案，但**标记不可靠并说明**",
            td3.get("ok") is True and (td3.get("brick_ms") or 0) > 0
            and (td3.get("brick_reliable") is False
                 or any("不可靠" in w for w in (td3.get("why") or []))),
            "reliable=%s cover=%.2f" % (td3.get("brick_reliable"),
                                        td3.get("brick_cover") or 0))
        post(base + "/api/load", {"path": _tsp})       # 回到 120 点时间戳（后续小节用）



        # ============================================================ [19]
        print("\n[19] ★★ 固定双押角度（用户 2026-10 定死：不按毫秒、不能自定义）")
        from core import dp_angle as _DA
        from core import solve as _sv
        chk("schema 有「使用固定双押角度」且**默认开**",
            any(f.get("key") == "use_fixed_dp_angle" and f.get("default") is True
                for f in SC.schema()["fields"]), "")
        chk("SolveParams 默认 use_fixed_dp_angle = True",
            getattr(_sv.SolveParams(), "use_fixed_dp_angle", None) is True, "")
        chk("表：<300 ⇒ 15° / 300~839 ⇒ 30° / ≥840 ⇒ 90°",
            tuple(_DA.fixed_theta(b, 1) for b in (100, 300, 839, 840))
            == (15.0, 30.0, 30.0, 90.0), "")
        chk("表：≥840 且**连续双押 ≥4** ⇒ 回 30°",
            _DA.fixed_theta(1400.0, 4) == 30.0
            and _DA.fixed_theta(1400.0, 3) == 90.0, "")
        _mid19 = os.path.join(ROOT, "samples", "audio", "doublepress_demo_120.mid")
        if os.path.isfile(_mid19):
            i19 = post(base + "/api/load", {"path": _mid19})
            chk("加载双押样例 MIDI", i19.get("ok") is True,
                str(i19.get("error"))[:80])
            st19 = dict(SC.defaults())
            st19["tracks_checked"] = [2]      # ★ trk0 一个音都没有（样例 MIDI 的坑）
            st19["dp_checked"] = [1]
            st19["dp_mode"] = 1
            st19["merge_ms"] = 0.0
            r19 = post(base + "/api/rebuild", {"state": st19})
            chk("角度双押仍能出谱", r19.get("ok") is True,
                str(r19.get("msg"))[:100])
            _info19 = str(r19.get("dp_info") or "") or str(r19.get("status") or "")
            chk("★ 报告写明角度来自**固定写法表**", "固定写法" in _info19,
                _info19[:150])
            chk("★ 按窗口报出各 θ 的处数（15/30/90）",
                ("90°×" in _info19) or ("30°×" in _info19) or ("15°×" in _info19),
                _info19[:150])
            chk("★ 关掉开关时不许静默：开着就说明「薄角θ/偏移预算已忽略」",
                ("已忽略" in _info19)
                or abs(float(st19.get("dp_skew_max_ms", 25.0)) - 25.0) < 1e-9,
                _info19[:150])
            st19b = dict(st19)
            st19b["use_fixed_dp_angle"] = False
            r19b = post(base + "/api/rebuild", {"state": st19b})
            _info19b = str(r19b.get("dp_info") or "") or str(r19b.get("status") or "")
            chk("★ 关掉开关 ⇒ 回 Δ 预算反解（老口径**保留不删**）",
                "固定写法" not in _info19b and "Δ" in _info19b, _info19b[:150])
            # ★ 自定义角度只在不固定时才生效
            st19c = dict(st19b)
            st19c["dp_theta"] = 45.0
            r19c = post(base + "/api/rebuild", {"state": st19c})
            _info19c = str(r19c.get("dp_info") or "") or str(r19c.get("status") or "")
            chk("★ 关掉开关后「薄角 θ」才真的生效（θ 45°）",
                "45" in _info19c, _info19c[:150])
            st19d = dict(st19)
            st19d["dp_theta"] = 45.0          # 开着固定表 ⇒ 这个值必须被忽略
            r19d = post(base + "/api/rebuild", {"state": st19d})
            _info19d = str(r19d.get("dp_info") or "") or str(r19d.get("status") or "")
            chk("★★ 开着固定表时「薄角 θ」被**忽略**（并报出来，不静默）",
                "固定写法" in _info19d and "45°×" not in _info19d
                and any("不参与选角" in w for w in (r19d.get("warning_list") or [])),
                _info19d[:130] + " || " + str(r19d.get("warning_list"))[:110])

        # ============================================================ [20]
        print("\n[20] ★★ 三押（docs/48）：两条多押轨同一时间都有音 ⇒ 拆 3 块")
        _mid20 = os.path.join(ROOT, "samples", "audio", "doublepress_demo_120.mid")
        if os.path.isfile(_mid20):
            i20 = post(base + "/api/load", {"path": _mid20})
            chk("加载双押样例 MIDI", i20.get("ok") is True,
                str(i20.get("error"))[:80])
            # ★ 走**采bpm 骨架**：主轨可以不勾 ⇒ 不存在「主轨与多押轨撞车」的坑，
            #   而且多押音一对一吸附到**砖**上（正好是判据要的「同一时间」）。
            base20 = dict(SC.defaults())
            base20["tracks_checked"] = []
            base20["xk_base"] = 4
            base20["xk_tbpm"] = 250          # ⇒ cbpm 1000，砖长 60ms
            base20["dp_mode"] = 1
            base20["merge_ms"] = 0.0
            # ---- (a) 一条多押轨 ⇒ 只有双押（押数全 2）--------------------
            st20a = dict(base20)
            st20a["dp_checked"] = [1]
            r20a = post(base + "/api/rebuild", {"state": st20a})
            chk("一条多押轨仍能出谱（采bpm 骨架）", r20a.get("ok") is True,
                str(r20a.get("msg"))[:100])
            _i20a = str(r20a.get("dp_info") or "")
            _d20a = r20a.get("dp") or {}
            chk("★ 一条轨 ⇒ **没有**三押（押数全 2）",
                "三押" not in _i20a and not _d20a.get("dp_three"),
                _i20a[:150])
            # ---- (b) 两条多押轨同时有音 ⇒ 三押 ---------------------------
            st20b = dict(base20)
            st20b["dp_checked"] = [1, 2]
            r20b = post(base + "/api/rebuild", {"state": st20b})
            chk("两条多押轨能出谱", r20b.get("ok") is True,
                str(r20b.get("msg"))[:100])
            _i20b = str(r20b.get("dp_info") or "")
            _d20b = r20b.get("dp") or {}
            chk("★★ 报告写明**三押 N 处**", ("三押" in _i20b)
                and _d20b.get("dp_three", 0) > 0,
                _i20b[:170])
            chk("★ 三押组合按表报出（cbpm 1000 ⇒ 30 · 60）",
                ("30°" in _i20b) and ("60°" in _i20b), _i20b[:170])
            chk("★ 三押处数 == 两条轨**同时**有音的个数（128 个 500ms 网格点）",
                _d20b.get("dp_three", 0) == 128, str(_d20b)[:170])
            chk("三押产物规则全过（0 违规）",
                int(r20b.get("n_violations") or 0) == 0,
                str(r20b.get("violations"))[:150])
            # ---- (c) 三条多押轨同时 ⇒ 四押：**跳过**但必须报 --------------
            st20c = dict(base20)
            st20c["dp_checked"] = [1, 2, 3]
            r20c = post(base + "/api/rebuild", {"state": st20c})
            _i20c = str(r20c.get("dp_info") or "")
            _d20c = r20c.get("dp") or {}
            _w20c = " || ".join(str(w) for w in (r20c.get("warning_list") or []))
            chk("★ 三条轨同时 ⇒ **跳过四押**并上屏", "四押" in _i20c,
                _i20c[:170])
            chk("★ 四押处数进 warnings（不许静默）",
                "四押" in _w20c and int(_d20c.get("dp_extra_press") or 0) > 0,
                _w20c[:170])
            chk("★ 四押那些落点**降级成双押**插进去（不是整段丢掉）",
                int(r20c.get("ok") is True) == 1
                and int(r20c.get("n_violations") or 0) == 0,
                str(r20c.get("msg"))[:120])
            # ---- (d) 关掉固定表 ⇒ 老口径没有押数概念：三押**不拆**并报 ------
            st20d = dict(base20)
            st20d["dp_checked"] = [1, 2]
            st20d["use_fixed_dp_angle"] = False
            r20d = post(base + "/api/rebuild", {"state": st20d})
            _i20d = str(r20d.get("dp_info") or "")
            _w20d = " || ".join(str(w) for w in (r20d.get("warning_list") or []))
            chk("★ 老口径（关固定表）⇒ 三押**未拆**且报出来",
                "未拆" in _i20d and ("押数概念" in _w20d), _i20d[:170])
            # ---- (e) 老路径（不采bpm）也要能数押数：主轨故意避开多押轨 ----
            st20e = dict(SC.defaults())
            st20e["tracks_checked"] = [3]    # ★ 主轨 ≠ 任何多押轨（_selected 会剔除重叠）
            st20e["dp_checked"] = [1, 2]
            st20e["dp_mode"] = 1
            st20e["merge_ms"] = 0.0
            r20e = post(base + "/api/rebuild", {"state": st20e})
            _d20e = r20e.get("dp") or {}
            chk("★★ 非采bpm 路径同样数得出三押（同一判据，不是骨架专属）",
                int(_d20e.get("dp_three") or 0) > 0,
                str(r20e.get("dp_info"))[:170])
            chk("非采bpm 路径产物规则全过",
                int(r20e.get("n_violations") or 0) == 0,
                str(r20e.get("violations"))[:150])
            # ---- (f) ★★ 用户 2026-10：三押开关第 1 档（不拆 ⇒ 只按双押插）------
            st20f = dict(base20)
            st20f["dp_checked"] = [1, 2]
            st20f["three_press_mode"] = 1
            r20f = post(base + "/api/rebuild", {"state": st20f})
            _i20f = str(r20f.get("dp_info") or "")
            _d20f = r20f.get("dp") or {}
            _w20f = " || ".join(str(w) for w in (r20f.get("warning_list") or []))
            chk("★ 三押开关=不拆 ⇒ 不产生三押", not _d20f.get("dp_three"),
                _i20f[:170])
            chk("★ 不拆要**单独记账 + 上屏**（three_off，不许静默）",
                int(_d20f.get("dp_three_off") or 0) > 0 and "三押**已关**" in _i20f
                and "不拆" in _w20f, _i20f[:170])
            chk("★ 不拆仍插双押（不是整组丢）",
                int(r20f.get("ok") is True) == 1
                and int(r20f.get("n_violations") or 0) == 0
                and int((_d20f or {}).get("dp_hits") or 0) > 0,
                str(r20f.get("msg"))[:120])
            # ---- (g) ★★ 三押开关第 2 档（跳过 ⇒ 连双押也不插）--------------
            st20g = dict(base20)
            st20g["dp_checked"] = [1, 2]
            st20g["three_press_mode"] = 2
            r20g = post(base + "/api/rebuild", {"state": st20g})
            _i20g = str(r20g.get("dp_info") or "")
            _d20g = r20g.get("dp") or {}
            _w20g = " || ".join(str(w) for w in (r20g.get("warning_list") or []))
            chk("★ 三押开关=跳过 ⇒ 押数 3 的那一组**连双押也不插**",
                int(_d20g.get("dp_press_skipped") or 0) > 0
                and not _d20g.get("dp_three"), _i20g[:170])
            chk("★ 跳过要上屏 + 进 warnings（不许静默）",
                "跳过三押" in _i20g and "一格都没插" in _w20g, _i20g[:170])
            chk("★ 跳过时按下的层数**少**于不拆那一档（真的没插）",
                int((r20g.get("n_floors") or 0)) < int((r20f.get("n_floors") or 0)),
                f"{r20g.get('n_floors')} vs {r20f.get('n_floors')}")
            chk("跳过那一档产物规则仍全过",
                int(r20g.get("n_violations") or 0) == 0,
                str(r20g.get("violations"))[:150])

        # ============================================================ [21]
        print("\n[21] ★★ 预览音源（用户 2026-10：「建议允许（不强制）使用 ogg，"
              "并允许调节 ogg 偏移来做音频混合预览」）")
        _mid21 = os.path.join(ROOT, "samples", "audio", "doublepress_demo_120.mid")
        _ogg21 = os.path.join(ROOT, "samples", "audio", "doublepress_demo_120.ogg")
        if os.path.exists(_mid21) and os.path.exists(_ogg21):
            i21 = post(base + "/api/load", {"path": _mid21})
            chk("加载样例 MIDI（用来配一个外面的 ogg）", i21.get("ok") is True,
                str(i21.get("error"))[:80])
            st21 = dict(SC.defaults())
            # ★ 与 [20] 同一套路：走**采bpm 骨架**（这份样例 MIDI 的 trk0 一个音都没有，
            #   勾主轨会「没有可采音的音轨」）
            st21["tracks_checked"] = []
            st21["xk_base"] = 4
            st21["xk_tbpm"] = 250
            # ---- (a) 默认（自动）⇒ 与今天一样：MIDI 源没有原曲 ⇒ 合成音 ----
            r21a = post(base + "/api/rebuild", {"state": st21})
            _p21a = r21a.get("payload") or {}
            chk("★ 默认「自动」⇒ 没有原曲就用**合成音**（= 今天的行为）",
                r21a.get("ok") is True and not _p21a.get("preview_audio")
                and float(_p21a.get("audio_lead_ms") or 0) > 0,
                f"preview_audio={_p21a.get('preview_audio')!r} "
                f"lead={_p21a.get('audio_lead_ms')}")
            _a21a = post(base + "/api/audio", {"state": st21})
            chk("合成音那一路：/api/audio 交出去的是**生成的 wav**",
                bool(_a21a.get("ok")) and str(_a21a.get("path", "")).endswith(".wav"),
                str(_a21a.get("path"))[:120])
            # ---- (b) 指定文件 ⇒ 预览放原曲（音频混合预览）------------------
            st21b = dict(st21)
            st21b["preview_audio_mode"] = 2
            st21b["preview_audio_path"] = _ogg21
            r21b = post(base + "/api/rebuild", {"state": st21b})
            _p21b = r21b.get("payload") or {}
            chk("★★ 「指定文件」⇒ 预览交出去的就是那份 ogg",
                r21b.get("ok") is True
                and os.path.abspath(str(_p21b.get("preview_audio") or ""))
                == os.path.abspath(_ogg21), str(_p21b.get("preview_audio"))[:140])
            chk("★ 交出去的是**文件** ⇒ 前置静音 S = 0（老口径：原曲原样）",
                abs(float(_p21b.get("audio_lead_ms") or 0)) < 1e-9,
                str(_p21b.get("audio_lead_ms")))
            chk("★ 预览音源要**上屏**（不许静默）",
                "预览音源" in str(r21b.get("status") or ""),
                str(r21b.get("status"))[:150])
            _a21b = post(base + "/api/audio", {"state": st21b})
            chk("★ /api/audio 跟着换成原曲（前端 `<audio>` 才是音频混合预览）",
                bool(_a21b.get("ok")) and os.path.abspath(str(_a21b.get("path")))
                == os.path.abspath(_ogg21), str(_a21b.get("path"))[:140])
            # ---- (c) 合成音档 ⇒ 就算有原曲也不用它 --------------------------
            st21c = dict(st21b)
            st21c["preview_audio_mode"] = 1
            r21c = post(base + "/api/rebuild", {"state": st21c})
            _p21c = r21c.get("payload") or {}
            chk("★ 「合成音」档 ⇒ 即使指定了原曲也**不用**（不强制用 ogg）",
                r21c.get("ok") is True and not _p21c.get("preview_audio")
                and float(_p21c.get("audio_lead_ms") or 0) > 0,
                f"preview_audio={_p21c.get('preview_audio')!r}")
            # ---- (d) 指定的文件不存在 ⇒ 退回合成音 + **报出来** --------------
            st21d = dict(st21b)
            st21d["preview_audio_path"] = os.path.join(ROOT, "samples", "没有这个.ogg")
            r21d = post(base + "/api/rebuild", {"state": st21d})
            _p21d = r21d.get("payload") or {}
            _w21d = " || ".join(str(w) for w in (r21d.get("warning_list") or []))
            chk("★★ 指定文件不存在 ⇒ 退回合成音**并上屏**（不许静默）",
                r21d.get("ok") is True and not _p21d.get("preview_audio")
                and "预览音源指定的文件不存在" in _w21d
                and _w21d.count("预览音源指定的文件不存在") == 1,
                _w21d[:170])
            # ---- (e) 用户切的 ogg 当**生成源**时仍是「自动 = 原曲」 ----------
            i21e = post(base + "/api/load", {"path": _ogg21})
            st21e = dict(SC.defaults())
            st21e["tracks_checked"] = [0]      # ★ 音频源只有 1 条「音头轨」
            r21e = post(base + "/api/rebuild", {"state": st21e})
            _p21e = r21e.get("payload") or {}
            chk("★ 载入的就是 ogg（生成源）⇒ 「自动」照样用原曲（老行为不变）",
                i21e.get("ok") is True
                and os.path.abspath(str(_p21e.get("preview_audio") or ""))
                == os.path.abspath(_ogg21),
                str(_p21e.get("preview_audio"))[:140])

        # ============================================================ [22]
        print("\n[22] ★★ 双押写法默认值：**角度双押**（时序最准）vs 中旋（密集音有量化误差）")
        from core import verify as _V22
        _mid22 = os.path.join(ROOT, "samples", "audio", "doublepress_demo_120.mid")
        if os.path.exists(_mid22):
            post(base + "/api/load", {"path": _mid22})
            chk("★ schema 默认写法 = 角度双押（= 用户「固定写法表」口径）",
                int(SC.defaults()["dp_mode"]) == 1, str(SC.defaults()["dp_mode"]))
            _err22 = {}
            for _mode in (1, 0):
                st22 = dict(SC.defaults())
                st22.update({"tracks_checked": [2], "dp_checked": [1], "dp_mode": _mode})
                r22 = post(base + "/api/rebuild", {"state": st22})
                _ons22 = [o.t_ms for o in SV.APP.session.onsets]
                _d22 = os.path.join(out_root, "_mode%d" % _mode)
                shutil.rmtree(_d22, ignore_errors=True)
                ex22 = post(base + "/api/export", {"state": st22, "dir": _d22})
                _f22 = os.path.join(ex22.get("dir") or _d22, "main.adofai")
                if not os.path.exists(_f22):
                    _f22 = _find_chart(ex22.get("dir") or _d22)
                vr22 = _V22.verify_press_subset(_f22, _ons22, tol_ms=2.0)
                _err22[_mode] = float(vr22.max_err_ms)
                print("       写法 %d（%s）层数 %s · 按键时刻误差 max %.3fms"
                      % (_mode, "角度" if _mode else "中旋", r22.get("n_floors"),
                         _err22[_mode]))
            chk("★★ 默认写法（角度双押）在**密集主轨**上按键时刻误差 ≤ 2ms",
                _err22[1] <= 2.0, "%.3fms" % _err22[1])
            chk("★ 角度 ≤ 中旋（防将来退化；中旋在密集音上有固有量化误差）",
                _err22[1] <= _err22[0] + 1e-9,
                "角度 %.3fms / 中旋 %.3fms" % (_err22[1], _err22[0]))

    finally:
        srv.shutdown()

    print(f"\n{'OK' if bad == 0 else 'FAILED'}  {ok} passed, {bad} failed")
    return 1 if bad else 0


def _find_chart(root: str) -> str:
    """在导出目录里找 main.adofai（导出的子目录名取决于曲名）。"""
    if not os.path.isdir(root):
        return os.path.join(root, "main.adofai")
    for dirpath, _dirs, files in os.walk(root):
        if "main.adofai" in files:
            return os.path.join(dirpath, "main.adofai")
    return os.path.join(root, "main.adofai")


if __name__ == "__main__":
    raise SystemExit(main())
