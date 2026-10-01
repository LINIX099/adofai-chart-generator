# -*- coding: utf-8 -*-
"""临时：恒定 BPM + 细分网格，到底能不能**精确**表示我们的谱？

    python tools/_subdiv_check.py

★ 判据要分成两件事（第一版把它们混了）：
  · **精确落格**：误差 < 1e-6 ms —— 这个点就在网格线上（说明结构真的是有理的）
  · **分辨率够**：网格间距 ≤ 2ms —— 任何时间都能怼上去，但那是「逼近」不是「落格」

一个 1/128 的网格（间距 1.3ms）当然能「表示」任何时间 —— 那不能证明什么。
要问的是：**我们的 BPM 档位之间是不是有理数比**（是 ⇒ 能精确；不是 ⇒ 只能逼近）。
"""
import glob
import json
import os
from math import gcd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "out", "FallenEra")


def floor_times(d):
    s = d.get("settings") or {}
    bpm = float(s.get("bpm") or 120.0)
    off = float(s.get("offset") or 0.0)
    n = len(d.get("angleData") or [])
    per = {}
    for a in d.get("actions") or []:
        if a.get("eventType") == "SetSpeed":
            f = int(a.get("floor") or 0)
            if a.get("speedType") == "Bpm":
                per[f] = float(a.get("beatsPerMinute") or bpm)
            else:
                per[f] = per.get(f, bpm) * float(a.get("bpmMultiplier") or 1.0)
    t, out = off, []
    for f in range(n):
        out.append(t)
        cur = bpm
        for k in sorted(x for x in per if x <= f):
            cur = per[k]
        t += 60000.0 / cur
    return out, bpm, off, per, n


def err_at(ts, off, base, div):
    """最大误差（ms）。返回 (最大误差, 精确落格率)。"""
    worst, exact = 0.0, 0
    for t in ts:
        beat = (t - off) * base / 60000.0
        frac = abs(beat * div - round(beat * div))
        worst = max(worst, frac / div * 60000.0 / base)
        if frac * 60000.0 / base / div < 1e-6:
            exact += 1
    return worst, exact / max(1, len(ts))


def ratio_denoms(bpms):
    """档位相对最低档的比值 → 需要的分母（把每个比值写成最简分数取 lcm）。"""
    v = sorted(set(bpms))
    lo = v[0]
    dens = [1]
    for x in v[1:]:
        # lo/x = p/q
        from fractions import Fraction
        fr = Fraction(lo / x).limit_denominator(512)
        dens.append(fr.denominator)
    l = 1
    for d in dens:
        l = l * d // gcd(l, d)
    return l, [Fraction(lo / x).limit_denominator(512) for x in v]


for f in sorted(glob.glob(os.path.join(D, "**", "*.adofai"), recursive=True)):
    with open(f, encoding="utf-8-sig") as fh:
        d = json.load(fh)
    ts, bpm, off, per, n = floor_times(d)
    if n == 0:
        continue
    bpms = sorted(set(round(v, 6) for v in per.values()))
    print("=" * 78)
    print(os.path.relpath(f, ROOT))
    print("  bpm=%-7s offset=%-8s 砖=%-5d 档位 %d 个: %s"
          % (bpm, off, n, len(bpms), bpms if len(bpms) <= 5
             else bpms[:3] + ["…"] + bpms[-2:]))
    if len(bpms) <= 8:
        need, frs = ratio_denoms(bpms)
        print("  档位/最低档 的最简比：%s   ⇒ 理论上需要分母 = %d"
              % (", ".join(str(x) for x in frs), need))
    else:
        need = None
        print("  （档位太多，不逐项列比值）")

    for tag, base in (("最低档", min(bpms)), ("最高档", max(bpms)), ("谱面 bpm", bpm)):
        line = []
        for div in (1, 2, 4, 8, 16, 32, 64, 128, 256):
            w, ex = err_at(ts, off, base, div)
            if ex >= 0.999999:
                line.append("1/%d:★精确" % div)
                break
            if div >= 32:
                line.append("1/%d:%.2fms/%.0f%%" % (div, w, ex * 100))
        print("  baseBpm=%-8g  %s" % (base, "  ".join(line) if line else "（连 1/256 都不精确）"))
