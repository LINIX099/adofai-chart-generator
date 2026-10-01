# -*- coding: utf-8 -*-
"""交付验收：把产物与 P12~P15 语料、同曲参照并排体检。

    python tools/verify_osn1.py <产物目录或 main.adofai>
"""
from __future__ import annotations

import json
import os
import sys
import statistics as st

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                     # noqa: BLE001
    pass

from corpus_report import one_chart, load_any, GRID   # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

#: P12~P15 合体 · P10~P90（`tools/_p12_15_per_chart.py` 实测 45 张）
BAND = {
    "直线": (0.2191, 0.4869, "%.1f%%"),
    "多押": (0.0055, 0.2685, "%.1f%%"),
    "Twirl": (9.5287, 31.0520, "%.2f"),
    "SetSpeed": (0.8134, 22.2624, "%.2f"),
    "midspin": (0.0000, 0.0422, "%.2f%%"),
    "2幂": (0.7140, 1.0000, "%.1f%%"),
    "1/12格": (0.5663, 1.0000, "%.1f%%"),
    "中位dt": (83.7079, 184.5123, "%.1f"),
}
REF_MPP = [
    ("同曲参照·Renewed", os.path.join(_ROOT, "corpus_tuf", "P14",
                                  "3080_Mad Piano Party (Renewed).adofai")),
    ("同曲参照·Featured", os.path.join(_ROOT, "corpus_tuf", "P14",
                                   "9851_Mad Piano Party [Featured ver.].adofai")),
]
BAND_ORDER = ["直线", "多押", "Twirl", "SetSpeed", "midspin", "2幂", "1/12格", "中位dt"]


def m_of(path):
    d, _k = load_any(path)
    r = one_chart(d)
    if r is None:
        return None
    n = r["n"]
    return {
        "n": n, "bpm": r["bpm"],
        "直线": r["straight"] / n, "多押": r["multipress"] / n,
        "Twirl": r["twirl"] / n * 100, "SetSpeed": r["setspeed"] / n * 100,
        "midspin": r["midspin"] / n * 100,
        "2幂": r["pow2"] / n, "1/12格": r["on12"] / n,
        "中位dt": r["median_dt"], "pause": r["pause"],
        "ang": None,
    }


#: 哪些指标存的是**分数**（显示要 ×100）
PCT = {"直线", "多押", "midspin", "2幂", "1/12格"}


def _disp(key, v):
    fmt = BAND[key][2]
    return fmt % (v * 100.0 if key in PCT else v)


def fmt(m, key):
    return _disp(key, m[key])


def main(argv):
    if not argv:
        print(__doc__); return 2
    target = argv[0]
    if os.path.isdir(target):
        cand = [os.path.join(target, f) for f in os.listdir(target)
                if f.endswith(".adofai")]
        if not cand:
            cand = [os.path.join(dp, f) for dp, _d, fs in os.walk(target)
                    for f in fs if f.endswith(".adofai")]
        target = cand[0]
    print(f"产物：{target}")
    mine = m_of(target)
    if mine is None:
        print("读不出谱面"); return 1

    print()
    print("=" * 92)
    print("① 指标 vs P12~P15 语料（P10~P90 判据）")
    print("-" * 92)
    print(f"{'指标':10s}{'产物':>12s}{'语料 P10':>12s}{'语料 P90':>12s}{'判定':>8s}")
    ok = 0
    for k in BAND_ORDER:
        lo, hi = BAND[k][0], BAND[k][1]
        v = mine[k]
        good = lo <= v <= hi
        ok += good
        print(f"{k:10s}{fmt(mine,k):>12s}{_disp(k,lo):>12s}{_disp(k,hi):>12s}"
              f"{'  ✔' if good else '  ✗':>8s}")
    print(f"\n   在带内：{ok}/{len(BAND_ORDER)}")

    print()
    print("=" * 92)
    print("② 与同曲真人参照并排（P14 · Mad Piano Party）")
    print("-" * 92)
    cols = [("产物", mine)]
    for tag, p in REF_MPP:
        if os.path.isfile(p):
            cols.append((tag, m_of(p)))
    keys = ["n", "bpm", "直线", "多押", "Twirl", "SetSpeed", "2幂", "1/12格", "中位dt"]
    print(f"{'':10s}" + "".join(f"{t:>18s}" for t, _ in cols))
    for k in keys:
        def cell(m):
            if k == "n":
                return f"{m['n']:d}"
            if k == "bpm":
                return f"{m['bpm']:.0f}"
            return _disp(k, m[k]) if k in BAND else f"{m[k]}"
        print(f"{k:10s}" + "".join(f"{cell(m):>18s}" for _t, m in cols))

    print()
    print("=" * 92)
    print("③ 角度 / 速度 / 音值")
    print("-" * 92)
    from _speeds import speeds_for, travel_into
    from _pathdata import angle_data_of
    from collections import Counter
    d, _k = load_any(target)
    a, _s = angle_data_of(d)
    n = len(a)
    acts = [e for e in (d.get("actions") or []) if e.get("active") is not False]
    tw = {int(e.get("floor", 0)) for e in acts if e.get("eventType") == "Twirl"}
    tv = travel_into(a, tw)
    sp = speeds_for(d, n)
    print("   角度: " + "  ".join(
        f"{x:g}°({c*100.0/n:.1f}%)" for x, c in Counter(round(t, 2) for t in tv).most_common(10)))
    print("   速度: " + "  ".join(
        f"{x:g}x({c*100.0/n:.1f}%)" for x, c in Counter(round(s, 4) for s in sp).most_common(8)))
    vals = Counter(round((tv[i] / 180.0) / (sp[i] or 1.0), 4) for i in range(min(n, len(tv))))
    print("   音值: " + "  ".join(
        f"{x:g}({c*100.0/n:.1f}%)" for x, c in vals.most_common(8)))

    # ---------------- ④ 规则 + 几何（走界面同一条路：sidecar session）
    print()
    print("=" * 92)
    print("④ 规则体检 / 几何体检（sidecar session 重跑一遍同一套设置）")
    print("-" * 92)
    try:
        import threading
        from http.server import ThreadingHTTPServer
        import urllib.request
        from sidecar import schema as SC
        from sidecar import server as SV
        from core import rules as R, geomcheck as GC, verify as V

        SRC = _HOME + r"\Downloads\osn1_timestamps.json"
        AUDIO = _HOME + r"\Downloads\mad_piano_party.ogg"
        SET = {"denoise_hint_ms": 181.818182, "slow_speed_penalty": 0.55,
               "straighten": False, "song": "Mad Piano Party", "artist": "Plum",
               "preview_audio_mode": 2, "preview_audio_path": AUDIO}

        SV.APP = SV.App(_ROOT)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), SV.Handler)
        srv.daemon_threads = True
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1},
                         daemon=True).start()

        def post(path, obj):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(obj).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1800) as r:
                return json.loads(r.read().decode("utf-8"))

        r0 = post("/api/load", {"path": SRC})
        st = SC.defaults()
        st.update(SET)
        st["tracks_checked"] = r0.get("default_tracks_checked") or [0]
        if "default_merge_ms" in r0:
            st["merge_ms"] = r0["default_merge_ms"]
        if "default_fit_mode" in r0:
            st["fit_mode"] = r0["default_fit_mode"]
        rb = post("/api/rebuild", {"state": st})
        ch = SV.APP.session.chart
        viol = R.check_chart(ch)
        errs = [v for v in viol if v.get("level") != "info"]
        print(f"   规则：违规(非 info) {len(errs)} 条 · info {len(viol)-len(errs)} 条")
        for v in errs[:12]:
            print(f"      ✗ {v.get('code')}: {v.get('msg') or v}")
        for v in viol:
            if v.get("level") == "info":
                print(f"      · info {v.get('code')}: {v.get('msg') or v}")
        m = GC.metrics(ch)
        for ln in GC.report_lines(m):
            print("   " + ln)
        # 逐按键反解
        ons = [o.t_ms for o in SV.APP.session.onsets]
        cf = target
        vr = V.verify_press_subset(cf, ons, tol_ms=2.0)
        print(f"   反解校验：{'✓' if vr.ok else '✗'} {vr.summary()}")
    except Exception as exc:                                  # noqa: BLE001
        import traceback
        print("   （跳过：{}）".format(exc))
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
