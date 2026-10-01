# -*- coding: utf-8 -*-
"""临时探针：老 `apply_regions` vs「单趟并集」到底差在哪。（跑完可删）"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import segments as SG                            # noqa: E402
from core.onsets import OnsetParams, build_onsets          # noqa: E402
from core.midi import Note, Track                          # noqa: E402


def mk(idx, ms):
    t = Track(index=idx)
    for m in sorted(ms):
        t.notes.append(Note(track=idx, channel=0, pitch=60, velocity=100,
                            t_on_ms=float(m), t_off_ms=float(m),
                            t_on_tick=0, t_off_tick=0))
    return t


def old(tracks, t0, t1, gmain, rtis, p_on):
    base = build_onsets([n for i in gmain for n in tracks[i].notes], p_on)
    r_on = build_onsets([n for i in rtis for n in tracks[i].notes], p_on)
    r_on = [o for o in r_on if t0 <= o.t_ms < t1]
    out = [o for o in base if not (t0 <= o.t_ms < t1)] + r_on
    out.sort(key=lambda o: o.t_ms)
    d = []
    for o in out:
        if d and (o.t_ms - d[-1].t_ms) < p_on.merge_ms:
            continue
        d.append(o)
    return d


def truth(tracks, t0, t1, gmain, rtis, p_on):
    """「区间内改用 rtis」的单趟并集：这就是分段采音每片干的事。"""
    notes = [n for i in gmain for n in tracks[i].notes if not (t0 <= n.t_on_ms < t1)]
    notes += [n for i in rtis for n in tracks[i].notes if t0 <= n.t_on_ms < t1]
    return build_onsets(notes, p_on)


def times(ons):
    return [round(o.t_ms, 6) for o in ons]


random.seed(7)
p_on = OnsetParams(merge_ms=30.0, merge_anchor="first", min_velocity=1,
                   min_interval_ms=0.0, pitch_lo=0, pitch_hi=127, max_onsets=0)
diff = 0
n = 0
examples = []
for trial in range(20000):
    ms = [[random.randrange(0, 60) * 10.0 for _ in range(random.randrange(1, 5))]
          for _ in range(3)]
    tracks = [mk(i, ms[i]) for i in range(3)]
    gmain = [0, 1]
    rtis = random.choice([[2], [0, 2], [1], [2, 0]])
    t0 = random.randrange(0, 6) * 10.0
    t1 = t0 + random.choice([10.0, 20.0, 30.0, 50.0, 200.0])
    a = times(old(tracks, t0, t1, gmain, rtis, p_on))
    b = times(truth(tracks, t0, t1, gmain, rtis, p_on))
    n += 1
    if a != b:
        diff += 1
        if len(examples) < 6:
            examples.append((ms, gmain, rtis, t0, t1, a, b))

print(f"比对 {n} 例，不同 {diff} 例")
for (ms, gm, rt, t0, t1, a, b) in examples:
    print("-" * 70)
    print(f"  轨音={ms}  全局主={gm}  区间轨={rt}  区间=[{t0},{t1})")
    print(f"  老 : {a}")
    print(f"  单趟: {b}")

# 精确定位：`<=`（聚类）vs `<`（尾巴去重）在「恰好 = merge_ms」处的差
print("=" * 70)
print("跨边界恰好相隔 merge_ms 的一对：")
tracks = [mk(0, [1000.0]), mk(1, [1030.0])]
for t0 in (1020.0, 1025.0, 1030.0, 1031.0):
    a = times(old(tracks, t0, 2000.0, [0], [1], p_on))
    b = times(truth(tracks, t0, 2000.0, [0], [1], p_on))
    print(f"  t0={t0:7.1f}  老={a}  单趟={b}  {'★差' if a != b else ''}")
print("=" * 70)
print("跨边界一对 < merge_ms：")
tracks = [mk(0, [1000.0]), mk(1, [1010.0])]
for t0 in (1005.0,):
    a = times(old(tracks, t0, 2000.0, [0], [1], p_on))
    b = times(truth(tracks, t0, 2000.0, [0], [1], p_on))
    print(f"  t0={t0:7.1f}  老={a}  单趟={b}  {'★差' if a != b else ''}")
