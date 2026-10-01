"""雪花解剖：把一个雪花拆成 (N 重对称, motif 长度, motif 转角序列, Twirl 位置, 闭合情况)。

    python tools/snowflake_anatomy.py "<main.adofai>" <lo> <hi> [...]

判据：
  ① 绕**包围盒中心**转 360/N，点集是否重合（容差按包围盒尺度给，否则 768 格累计误差会误判）
  ② 转角序列 T[f] 的周期 m 是否等于 (hi-lo+1)/N
  ③ motif 内 Twirl 落在第几格
  ④ 一个 motif 的朝向变化 / 位移，以及整朵的闭合情况
"""
from __future__ import annotations

import collections
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jsonrepair import load  # noqa: E402
from _pathdata import angle_data_of  # noqa: E402
from _speeds import speeds_for, travel_into  # noqa: E402


def positions(a):
    """按游戏口径摆格子位置。

    朝向 `h[f] = 90 - a[f]`（`exitangle = 90 - a`，decomp 里写死的），
    于是 `p[f+1] = p[f] + unit(h[f])`。

    ★ Twirl 不影响位置：它只改「绕这一格往哪边走」（方向 + 计时），
      终点仍然是下一格的坐标，位置完全由 `a` 决定。
    """
    pts = [(0.0, 0.0)]
    x = y = 0.0
    for f in range(len(a) - 1):
        h = math.radians(90.0 - a[f])
        x += math.cos(h)
        y += math.sin(h)
        pts.append((x, y))
    return pts


def anatomy(path, lo, hi):
    o, _ = load(path)
    a, src = angle_data_of(o)
    n = len(a)
    bpm = float(o.get("settings", {}).get("bpm") or 120)
    beat = 60000.0 / bpm
    acts = [e for e in (o.get("actions") or []) if e.get("active") is not False]
    tw = {int(e["floor"]) for e in acts if e.get("eventType") == "Twirl"}
    T = travel_into(a, tw)
    sp = speeds_for(o, n)

    hi = min(hi, n - 1)
    P = positions(a)
    seg = P[lo:hi + 1]
    L = hi - lo + 1
    xs = [p[0] for p in seg]
    ys = [p[1] for p in seg]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    scale = max(max(xs) - min(xs), max(ys) - min(ys))
    tol = max(0.05, scale * 0.004)

    print("=" * 94)
    print(f"{os.path.basename(os.path.dirname(path)) or os.path.basename(path)}  "
          f"{lo}~{hi}   {L} 格   bpm={bpm:g}(1拍={beat:.2f}ms)   {src}")
    print(f"  包围盒 {max(xs)-min(xs):.4f} × {max(ys)-min(ys):.4f}   "
          f"中心 ({cx:.3f}, {cy:.3f})   容差 {tol:.4f}")
    print(f"  起点→终点 距离 {math.dist(seg[0], seg[-1]):.4f}")

    # ① 旋转对称阶数
    uniq = sorted({(round(x, 5), round(y, 5)) for x, y in zip(xs, ys)})
    hits = []
    for k in (2, 3, 4, 5, 6, 8, 12, 16):
        ang = math.radians(360.0 / k)
        ca, sa = math.cos(ang), math.sin(ang)
        rot = [((x - cx) * ca - (y - cy) * sa + cx,
                (x - cx) * sa + (y - cy) * ca + cy) for x, y in uniq]
        miss = 0
        for x, y in uniq:
            d = min(math.hypot(x - rx, y - ry) for rx, ry in rot)
            if d > tol:
                miss += 1
        ok = "✔" if miss == 0 else f"缺{miss}" + ("（近似）" if miss <= 2 else "")
        print(f"    k={k:>2} 重：{ok}")
        if miss <= 2:
            hits.append(k)
    print(f"  → 对称阶数 {hits if hits else '无'}")

    # ② 转角周期
    Tseg = T[lo:hi + 1]
    per = None
    for m in range(1, L // 2 + 1):
        if L % m:
            continue
        if all(abs(Tseg[i] - Tseg[i % m]) < 1e-9 for i in range(L)):
            per = m
            break
    print(f"  转角序列周期：{per if per else '（区间内没找到整除周期）'}")
    if per:
        print(f"     motif 转角：{', '.join(f'{t:g}' for t in Tseg[:per])}")
        twm = sorted(f - lo for f in tw if lo <= f < lo + per)
        print(f"     motif 内 Twirl 位置（相对 lo）：{twm}")
        dh = sum(t - 180.0 for t in Tseg[:per]) % 360.0
        print(f"     一个 motif 的朝向变化：{dh:g}°  → "
              f"{'N=' + str(round(360/dh)) if dh and abs(360/dh - round(360/dh)) < 1e-6 else '不是整分'}")
        p0, p1 = P[lo], P[lo + per] if lo + per < len(P) else None
        if p1:
            print(f"     一个 motif 的位移：({p1[0]-p0[0]:.4f}, {p1[1]-p0[1]:.4f})  "
                  f"|Δ|={math.dist(p0, p1):.4f}")
    # ③ 时长
    dts = [(T[f] / 180.0) / sp[f] * beat for f in range(lo, hi + 1) if sp[f] > 0]
    if dts:
        c = collections.Counter(round(d / beat, 6) for d in dts)
        print(f"  每格时长（拍）分布："
              + "  ".join(f"{k:g}×{v}" for k, v in c.most_common(6)))
    print()


if __name__ == "__main__":
    f = sys.argv[1]
    rest = [int(x) for x in sys.argv[2:]]
    for i in range(0, len(rest), 2):
        anatomy(f, rest[i], rest[i + 1])
