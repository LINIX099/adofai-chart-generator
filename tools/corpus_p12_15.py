# -*- coding: utf-8 -*-
"""P12~P15 语料 · **逐张**指标（看分布，不是只看均值）。一次性脚本。"""
import os, sys, json, math, statistics as st
from collections import Counter
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from corpus_report import one_chart, load_any, MP_MS     # noqa: E402

rows = []
for lv in ("P12", "P13", "P14", "P15"):
    d0 = os.path.join(ROOT, "corpus_tuf", lv)
    for f in sorted(os.listdir(d0)):
        if not f.lower().endswith(".adofai"):
            continue
        try:
            d, _k = load_any(os.path.join(d0, f))
            r = one_chart(d)
        except Exception as e:                                # noqa: BLE001
            print("fail", f, e); continue
        if r is None or r["n"] < 20:
            continue
        n = r["n"]
        rows.append({
            "lv": lv, "f": f, "n": n, "bpm": r["bpm"],
            "直线": r["straight"] / n, "多押": r["multipress"] / n,
            "Twirl": r["twirl"] / n * 100, "SS": r["setspeed"] / n * 100,
            "mid": r["midspin"] / n * 100,
            "2幂": r["pow2"] / n, "1/12": r["on12"] / n,
            "dt": r["median_dt"], "pause": r["pause"],
        })

keys = ("直线", "多押", "Twirl", "SS", "mid", "2幂", "1/12", "dt")
print(f"{'level':6s}{'file':46s}{'格':>6s}{'bpm':>7s}" +
      "".join(f"{k:>8s}" for k in keys))
print("-" * 120)
for r in sorted(rows, key=lambda x: (x["lv"], -x["n"])):
    print(f"{r['lv']:6s}{r['f'][:44]:46s}{r['n']:6d}{r['bpm']:7.0f}" +
          "".join(f"{r[k]:8.2f}" if k != "dt" else f"{r[k]:8.1f}" for k in keys))

print()
print("=== 分档位统计（中位 / 最小 / 最大）===")
for lv in ("P12", "P13", "P14", "P15", "ALL"):
    sub = [r for r in rows if lv == "ALL" or r["lv"] == lv]
    if not sub:
        continue
    print(f"[{lv}] {len(sub)} 张 " + "  ".join(
        f"{k}={st.median([x[k] for x in sub]):.2f}"
        f"({min(x[k] for x in sub):.2f}~{max(x[k] for x in sub):.2f})" for k in keys))


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    i = (len(xs) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


print()
print("=== P12~P15 合体 · 分位（判定「在不在语料范围内」用 P10~P90）===")
print("KP = {" + ", ".join(
    f'"{k}": ({pct([x[k] for x in rows], 0.10):.4f}, {pct([x[k] for x in rows], 0.90):.4f})'
    for k in keys) + "}")
print("   中位：" + "  ".join(f"{k}={pct([x[k] for x in rows], 0.5):.2f}" for k in keys))
print("   P10 ：" + "  ".join(f"{k}={pct([x[k] for x in rows], 0.10):.2f}" for k in keys))
print("   P90 ：" + "  ".join(f"{k}={pct([x[k] for x in rows], 0.90):.2f}" for k in keys))
print("   P05 ：" + "  ".join(f"{k}={pct([x[k] for x in rows], 0.05):.2f}" for k in keys))
print("   P95 ：" + "  ".join(f"{k}={pct([x[k] for x in rows], 0.95):.2f}" for k in keys))

