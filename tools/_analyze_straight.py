"""Recon v2: straight-line statistics of real ADOFAI charts.

Fixes v1's inverted metric: travel == 180 is a straight line (not turn == 180).
"""
import os
import json, os, math
from collections import Counter

CORPUS = CORPUS
EPS = 1e-3


def load(p):
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def angles(d):
    a = d.get("angleData")
    if a:
        return [float(x) for x in a], "angleData"
    pd = d.get("pathData") or []
    out = []
    for x in pd:
        if isinstance(x, (int, float)):
            out.append(float(x) * 15.0)
        elif isinstance(x, str):
            out.append(None)          # 'R' / '!' markers
    return out, "pathData"


def travels(a):
    """travel[i] = angle the planet rotates going from floor i to floor i+1."""
    t = []
    for i in range(len(a) - 1):
        if a[i] is None or a[i + 1] is None:
            t.append(None)
            continue
        # heading_i = 90 - a[i];  turn_i = heading_{i+1} - heading_i = a[i]-a[i+1]
        # travel_i = 180 + turn_i
        t.append((180.0 + a[i] - a[i + 1]) % 360.0)
    return t


def analyse(path, label=None):
    try:
        d = load(path)
    except Exception as e:
        print(f"  !! {path}: {e}")
        return None
    a, fmt = angles(d)
    if len(a) < 4:
        return None
    t = [x for x in travels(a) if x is not None]
    if not t:
        return None
    st = d.get("settings", {})
    acts = d.get("actions") or []
    et = Counter(x.get("eventType") for x in acts)
    n = len(t)
    c = Counter(round(x, 2) for x in t)
    straight = sum(k for v, k in c.items() if abs(v - 180.0) < EPS)
    uturn = sum(k for v, k in c.items() if v < 15.0 or v > 345.0)
    print(f"\n=== {label or os.path.basename(path)}")
    print(f"    {path}")
    print(f"    floors={len(a)}  v={st.get('version')}  bpm={st.get('bpm')}  "
          f"offset={st.get('offset')}  format={fmt}")
    print(f"    a[0]={a[0]}   travel[0]={t[0]:.2f}   (first press)")
    print(f"    first 10 travel: {[round(x,2) for x in t[:10]]}")
    print(f"    >>> 直线(travel==180): {straight}/{n} = {straight/n*100:.1f}%")
    print(f"    >>> 回头(travel<15 或 >345): {uturn}/{n} = {uturn/n*100:.1f}%")
    print(f"    >>> travel 种类: {len(c)}")
    print(f"    top10: " + "  ".join(f"{v:g}°x{k}({k/n*100:.1f}%)"
                                    for v, k in c.most_common(10)))
    print(f"    events: {dict(et)}")
    return dict(label=label or path, n=n, straight=straight / n, uturn=uturn / n,
                kinds=len(c), a0=a[0], t0=t[0], c=c, events=dict(et),
                version=st.get("version"), bpm=st.get("bpm"), fmt=fmt)


# ---------------------------------------------------------------- targets
import glob

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

_HOME = os.path.expanduser("~")                                #: 用户目录

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  #: 仓库根（不写死盘符）
print("#" * 78)
print("# 所有 FallenEra 相关谱面")
print("#" * 78)
hits = []
for root, dirs, files in os.walk(CORPUS):
    for fn in files:
        if fn.lower().endswith(".adofai") and "fallen" in root.lower():
            hits.append(os.path.join(root, fn))
for p in hits:
    analyse(p, os.path.relpath(p, CORPUS))

print("\n" + "#" * 78)
print("# 其他参照物")
print("#" * 78)
for p, lab in [
    (ROOT + r"\out\FallenEra\main.adofai", "我们的输出 out/FallenEra"),
    (_HOME + r"\Documents\A Dance of Fire and Ice\Worlds\CLionSister Like Triangle -1\main.adofai", "CLionSister (用户自制)"),
]:
    analyse(p, lab)

# ---------------------------------------------------------------- corpus
print("\n" + "#" * 78)
print("# 全语料统计")
print("#" * 78)
firsts = Counter()
first_travels = Counter()
straights, uturns, kinds_l = [], [], []
vocab = Counter()
tot_layers = 0
nfiles = 0
bad = 0
for root, dirs, files in os.walk(CORPUS):
    for fn in files:
        if not fn.lower().endswith(".adofai"):
            continue
        try:
            d = load(os.path.join(root, fn))
        except Exception:
            bad += 1
            continue
        a, fmt = angles(d)
        if len(a) < 10:
            continue
        t = [x for x in travels(a) if x is not None]
        if len(t) < 10:
            continue
        nfiles += 1
        tot_layers += len(t)
        firsts[round(a[0], 2)] += 1
        first_travels[round(t[0], 2)] += 1
        c = Counter(round(x, 2) for x in t)
        straights.append(sum(k for v, k in c.items() if abs(v - 180.0) < EPS) / len(t))
        uturns.append(sum(k for v, k in c.items() if v < 15.0 or v > 345.0) / len(t))
        kinds_l.append(len(c))
        vocab.update(c)

print(f"文件数 = {nfiles}  (解析失败 {bad})   总层数 = {tot_layers}")
q = lambda L, p: sorted(L)[min(len(L) - 1, int(len(L) * p))]
print("\n第一格 a[0] 分布 (top 12):")
for v, k in firsts.most_common(12):
    print(f"    {v:>8g}° : {k:4d}  ({k/nfiles*100:.1f}%)")
print("\n第一格 travel[0] 分布 (top 12):")
for v, k in first_travels.most_common(12):
    print(f"    {v:>8g}° : {k:4d}  ({k/nfiles*100:.1f}%)")
print("\n直线率 (travel==180):")
print(f"    p10={q(straights,.1)*100:.1f}%  p25={q(straights,.25)*100:.1f}%  "
      f"中位={q(straights,.5)*100:.1f}%  p75={q(straights,.75)*100:.1f}%  "
      f"p90={q(straights,.9)*100:.1f}%  平均={sum(straights)/len(straights)*100:.1f}%")
print("回头率 (travel<15 或 >345):")
print(f"    p10={q(uturns,.1)*100:.1f}%  中位={q(uturns,.5)*100:.1f}%  "
      f"p90={q(uturns,.9)*100:.1f}%  平均={sum(uturns)/len(uturns)*100:.1f}%")
print(f"\ntravel 种类数: 中位={q(kinds_l,.5)}  p25={q(kinds_l,.25)}  p75={q(kinds_l,.75)}")
print("\ntravel 全局词表 (top 30):")
for v, k in vocab.most_common(30):
    print(f"    {v:>8g}° : {k:8d}  ({k/tot_layers*100:5.2f}%)")

# -------- how many charts are "straight dominant" among the common ones
print("\n" + "#" * 78)
print("# 直线率 vs 谱面大小（只看 200 层以上的谱）")
print("#" * 78)
rows = []
for root, dirs, files in os.walk(CORPUS):
    for fn in files:
        if not fn.lower().endswith(".adofai"):
            continue
        try:
            d = load(os.path.join(root, fn))
        except Exception:
            continue
        a, fmt = angles(d)
        if len(a) < 200:
            continue
        t = [x for x in travels(a) if x is not None]
        if len(t) < 200:
            continue
        c = Counter(round(x, 2) for x in t)
        s = sum(k for v, k in c.items() if abs(v - 180.0) < EPS) / len(t)
        dom = c.most_common(1)[0]
        rows.append((s, len(t), dom[0], dom[1] / len(t), os.path.relpath(os.path.join(root, fn), CORPUS)))
rows.sort(reverse=True)
print(f"{'直线率':>7} {'层数':>7} {'最常见travel':>12} {'占比':>6}  文件")
for s, n, dv, dk, p in rows:
    print(f"{s*100:6.1f}% {n:7d} {dv:11g}° {dk*100:5.1f}%  {p}")
