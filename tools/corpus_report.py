"""任意语料目录的体检报告 —— 统一口径，用来对比「真人谱」和「我们生成的谱」。

用法：
    python tools/corpus_report.py <目录> [目录2 ...]
    python tools/corpus_report.py <目录> --tag 标签

口径全部和 `tools/_speeds.py` 一致（SetSpeed 用 `bpmMultiplier` 且**累乘**）。
"""
from __future__ import annotations

import collections
import json
import math
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jsonrepair import loads_lenient, _read_text  # noqa: E402
from _pathdata import angle_data_of  # noqa: E402
from _speeds import is_pow2, speeds_for, travel_into  # noqa: E402

MP_MS = 35.0          # 多押判定窗口
GRID = 12.0           # 音值量化网格


# ---------------------------------------------------------------- 解析
def load_any(path):
    """返回 (dict, kind)。kind 标明用了哪种解析。"""
    return loads_lenient(_read_text(path))


def travels(a, twirl=frozenset()):
    """floor f 自己的转角（口径见 `_speeds.travel_into`）。"""
    return travel_into(a, twirl)


# ---------------------------------------------------------------- 单张
def one_chart(d):
    """一张谱的指标。`angleData` 和旧格式 `pathData` 都吃。"""
    a, src = angle_data_of(d)
    if len(a) < 2:
        return None
    d = dict(d)
    d["_src"] = src
    bpm = float(d.get("settings", {}).get("bpm") or 0)
    n = len(a)
    acts = [e for e in (d.get("actions") or []) if e.get("active") is not False]
    twirl = {(int(e.get("floor", 0))) for e in acts if e.get("eventType") == "Twirl"}
    setspeed = [e for e in acts if e.get("eventType") == "SetSpeed"]
    pause = [e for e in acts if e.get("eventType") == "Pause"]

    tv = travels(a, twirl)
    sp = speeds_for(d, n)
    if len(sp) != len(tv):
        sp = (sp + [1.0] * n)[:len(tv)]

    vals, dts = [], []
    for i, t in enumerate(tv):
        v = (t / 180.0) / (sp[i] or 1.0)
        vals.append(v)
        if bpm > 0:
            dts.append(v * 60000.0 / bpm)

    n_str = sum(1 for t in tv if abs(t - 180.0) <= 0.5)
    n_mp = sum(1 for i, t in enumerate(tv)
               if abs(t - 180.0) > 0.5 and i < len(dts) and dts[i] <= MP_MS)
    n_mid = sum(1 for i in range(1, len(a)) if a[i] == 999)
    on12 = sum(1 for v in vals if abs(v * GRID - round(v * GRID)) < 1e-6)

    return {
        "n": len(tv), "bpm": bpm, "src": d.get("_src", "angleData"),
        "travels": tv, "speeds": sp, "vals": vals, "dts": dts,
        "straight": n_str, "multipress": n_mp, "midspin": n_mid,
        "twirl": len(twirl), "setspeed": len(setspeed), "pause": len(pause),
        "turnspeed": len({int(e.get("floor", 0)) for e in setspeed}),
        "on12": on12,
        "median_dt": st.median(dts) if dts else 0.0,
        "pow2": sum(1 for s in sp if is_pow2(s)),
    }


# ---------------------------------------------------------------- 汇总
def report(root, tag=None, *, verbose=True, min_tiles=20):
    """体检一个目录（也可以传 glob 通配符，如 `ex/*/level.adofai`）。"""
    tag = tag or os.path.basename(os.path.normpath(root))
    charts, kinds, fails = [], collections.Counter(), []

    if any(ch in root for ch in "*?["):
        import glob
        paths = sorted(glob.glob(root))
    else:
        paths = [os.path.join(dp, f)
                 for dp, _d, fs in os.walk(root) for f in fs
                 if f.lower().endswith(".adofai") and not f.lower().startswith("backup")]

    for p in paths:
        fn = os.path.basename(p)
        try:
            d, kind = load_any(p)
        except Exception:                                        # noqa: BLE001
            kinds["fail"] += 1
            fails.append(p)
            continue
        kinds[kind] += 1
        rec = one_chart(d)
        if rec is None:
            kinds["weird"] += 1
            continue
        if rec["n"] < min_tiles:
            kinds["tiny"] += 1
            continue
        rec["file"] = fn
        charts.append(rec)

    if not charts:
        print(f"\n### {tag}\n   没有可用谱面")
        return {}

    T = sum(c["n"] for c in charts)
    agg = {
        "tag": tag, "charts": len(charts), "tiles": T,
        "strict": kinds["strict"], "lenient": kinds["lenient"], "fail": kinds["fail"],
        "repaired": kinds["repaired"], "weird": kinds["weird"],
        "straight": sum(c["straight"] for c in charts) / T,
        "multipress": sum(c["multipress"] for c in charts) / T,
        "midspin": sum(c["midspin"] for c in charts) / T,
        "twirl_per100": sum(c["twirl"] for c in charts) / T * 100,
        "setspeed_per100": sum(c["setspeed"] for c in charts) / T * 100,
        "pause_per_chart": sum(c["pause"] for c in charts) / len(charts),
        "pow2": sum(c["pow2"] for c in charts) / T,
        "on12": sum(c["on12"] for c in charts) / T,
        "median_dt": st.median([c["median_dt"] for c in charts if c["median_dt"] > 0]),
        "setspeed_charts0": sum(1 for c in charts if c["setspeed"] == 0),
    }

    sp_all = collections.Counter()
    v_all = collections.Counter()
    dt_all = []
    for c in charts:
        for s in c["speeds"]:
            sp_all[round(s, 4)] += 1
        for v in c["vals"]:
            v_all[round(v * GRID) / GRID] += 1
        dt_all += c["dts"]
    on15 = sum(cnt for s, cnt in sp_all.items() if _on15(s))
    agg["pow15"] = on15 / T
    agg["median_dt_all"] = st.median(dt_all) if dt_all else 0.0

    if verbose:
        print(f"\n{'='*78}\n### {tag}")
        print(f"   谱 {len(charts)} 张 / {T} 格   "
              f"解析：strict {kinds['strict']} / lenient {kinds['lenient']} / "
              f"修补 {kinds['repaired']} / 失败 {kinds['fail']} / "
              f"脏数据 {kinds['weird']} / 太小 {kinds['tiny']}")
        print(f"   直线 {agg['straight']*100:5.1f}%   "
              f"多押(Δt≤35ms) {agg['multipress']*100:5.1f}%   "
              f"其余 {(1-agg['straight']-agg['multipress'])*100:5.1f}%")
        print(f"   midspin {agg['midspin']*100:5.2f}%")
        print(f"   SetSpeed {agg['setspeed_per100']:5.2f} /100格   "
              f"（完全没用的谱 {agg['setspeed_charts0']}/{len(charts)}）")
        print(f"   Pause    {agg['pause_per_chart']:5.2f} /张")
        print(f"   Twirl    {agg['twirl_per100']:5.2f} /100格")
        print(f"   速度档：2 的幂 {agg['pow2']*100:5.1f}%   "
              f"2^a×1.5^b {agg['pow15']*100:5.1f}%")
        print(f"   音值 v 落在 1/12 网格 {agg['on12']*100:5.1f}%")
        print(f"   单格时长 中位 {agg['median_dt_all']:.1f} ms")
        print(f"   最常用的速度档："
              + "  ".join(f"{s:g}x({c/T*100:.1f}%)" for s, c in sp_all.most_common(6)))
        print(f"   最常用的音值 v ："
              + "  ".join(f"{v:g}({c/T*100:.1f}%)" for v, c in v_all.most_common(8)))
        if fails and len(fails) <= 8:
            print("   解析失败：")
            for f in fails:
                print(f"      {f}")
        elif fails:
            print(f"   解析失败 {len(fails)} 张（前 3：{[os.path.basename(f) for f in fails[:3]]}）")
    return agg


def _on15(s):
    if s <= 0 or not math.isfinite(s):
        return False
    for b in range(-12, 13):
        t = s / (1.5 ** b)
        if t <= 0 or not math.isfinite(t):
            continue
        e = math.log2(t)
        if math.isfinite(e) and abs(e - round(e)) < 1e-6:
            return True
    return False


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        # ★ 以前这里写死了一个语料目录（别人的机器上不存在）。语料不入库，
        #   所以改成**必须显式给路径**（见 EXTERNAL_ASSETS.md 怎么拿语料）。
        print(__doc__)
        print("用法：python tools/corpus_report.py <谱面目录> [<目录2> ...]")
        raise SystemExit(2)
    for a in args:
        report(a)
