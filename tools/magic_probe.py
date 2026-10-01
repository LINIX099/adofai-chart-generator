"""魔法阵探针 —— 只读，不生成。

几何模型（`scrLevelMaker` + README 验证过）：

    p[0] = (0,0),  h[0] = 90°            # 先按当前朝向走一格，再转
    p[i+1] = p[i] + (cos h[i], sin h[i])
    h[i+1] = h[i] + travel[i] - 180
    travel[i] = (180 + angleData[i] - angleData[i+1]) % 360

用法：
    python tools/magic_probe.py "<main.adofai 路径>" 84 263 [更多区间...]
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jsonrepair import load  # noqa: E402
from _pathdata import angle_data_of  # noqa: E402
from _speeds import speeds_for  # noqa: E402

TOL = 1e-9


def travels(a):
    return [0.0 if (a[i] == 999 or a[i + 1] == 999)
            else (180.0 + a[i] - a[i + 1]) % 360.0
            for i in range(len(a) - 1)]


def path(a):
    """返回 [(x, y, heading, travel), ...]，长度 = len(a)。"""
    tv = travels(a)
    pts = [(0.0, 0.0, 90.0, 180.0)]
    x = y = 0.0
    h = 90.0
    for t in tv:
        x += math.cos(math.radians(h))
        y += math.sin(math.radians(h))
        h = (h + t - 180.0) % 360.0
        pts.append((x, y, h, t))
    return pts


def fmt(v, nd=3):
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def probe(path_file, lo, hi):
    o, kind = load(path_file)
    a, src = angle_data_of(o)
    pts = path(a)
    n = len(a)
    if hi > n - 1:
        print(f"   ⚠ 区间 {lo}~{hi} 超出（谱面只有 {n} 格）")
        hi = n - 1
    sub = pts[lo:hi + 1]

    print(f"\n{'='*74}")
    print(f"区间 {lo}~{hi}   （{hi-lo+1} 格）   文件 {os.path.basename(path_file)}")
    print(f"解析方式 {kind} / 角度来源 {src}   谱面总长 {n} 格")

    # ---- 全局几何
    xs = [p[0] for p in sub]
    ys = [p[1] for p in sub]
    start, end = (xs[0], ys[0]), (xs[-1], ys[-1])
    d = math.dist(start, end)
    print(f"   起点 ({fmt(start[0])}, {fmt(start[1])})   "
          f"终点 ({fmt(end[0])}, {fmt(end[1])})   回程距离 {d:.4f}")
    print(f"   包围盒 {fmt(max(xs)-min(xs))} × {fmt(max(ys)-min(ys))}   "
          f"（{max(xs)-min(xs):.2f} × {max(ys)-min(ys):.2f} 格）")

    # 非相邻最近距离
    mind, pair = 1e9, None
    for i in range(len(sub)):
        for j in range(i + 2, len(sub)):
            dd = math.dist(sub[i][:2], sub[j][:2])
            if dd < mind:
                mind, pair = dd, (lo + i, lo + j)
    print(f"   非相邻最近 {mind:.4f} 格 @ {pair}")

    # ---- 朝向
    h0, hN = sub[0][2], sub[-1][2]
    print(f"   起始朝向 {fmt(h0)}°   结束朝向 {fmt(hN)}°"
          f"   {'★朝向回正' if abs((hN-h0) % 360) < 1e-6 else ''}")

    # ---- 速度（要提前算，周期那块要用）
    acts = [e for e in (o.get("actions") or []) if e.get("active") is not False]
    sp = speeds_for(o, n - 1)
    sp0 = sp[max(0, lo - 1):hi] if sp else []

    # ---- travel
    tvs = [p[3] for p in sub[1:]]
    import collections
    c = collections.Counter(round(t, 4) for t in tvs)
    print(f"   travel 取值："
          + "  ".join(f"{t:g}°×{k}" for t, k in c.most_common(8)))
    print(f"   前 40 个 travel：{', '.join(fmt(t,1) for t in tvs[:40])}")

    # ---- 周期
    per_found = None
    for per in range(1, min(73, len(tvs) // 2 + 1)):
        if all(abs(tvs[i] - tvs[i % per]) < 1e-6 for i in range(len(tvs))):
            print(f"   ★ travel 周期 = {per}  （重复 {len(tvs)/per:.2f} 次）")
            per_found = per
            break
    if per_found:
        m = per_found
        dh = (sub[m][2] - sub[0][2]) % 360 if m < len(sub) else 0.0
        dx = sub[m][0] - sub[0][0] if m < len(sub) else 0.0
        dy = sub[m][1] - sub[0][1] if m < len(sub) else 0.0
        rot = dh if 1 <= dh <= 359 else 0.0
        print(f"   一个周期里：朝向转 {fmt(dh,2)}°   位移 ({fmt(dx,3)}, {fmt(dy,3)})"
              f"  |位移| {math.hypot(dx, dy):.3f}")
        if rot and abs(360 / rot - round(360 / rot)) < 1e-6:
            print(f"   ★★ {round(360/rot)} 次旋转对称（每次 {fmt(rot)}°）")
        print(f"   周期内 travel：{', '.join(fmt(t,1) for t in tvs[:m])}")
        if sp0:
            print(f"   周期内速度：  {', '.join(fmt(s,3) for s in sp0[:m])}")

    # ---- 位置周期
    for per in range(1, min(73, len(sub) // 2 + 1)):
        ok = True
        for i in range(per, len(sub)):
            if math.dist(sub[i][:2], sub[i - per][:2]) > 1e-6:
                ok = False
                break
        if ok:
            print(f"   ★ 位置也在周期 {per} 上（严格平移）")
            break

    # ---- 旋转对称：绕重心转 360/k 后点集是否不变
    cxm = sum(xs) / len(xs)
    cym = sum(ys) / len(ys)
    uniq = sorted({(round(x, 6), round(y, 6)) for x, y in zip(xs, ys)})
    hits = []
    for k in (2, 3, 4, 5, 6, 8, 12):
        ang = math.radians(360.0 / k)
        ca, sa = math.cos(ang), math.sin(ang)
        rot = set()
        for x, y in uniq:
            dx, dy = x - cxm, y - cym
            rot.add((round(cxm + dx * ca - dy * sa, 6),
                     round(cym + dx * sa + dy * ca, 6)))
        miss = sum(1 for p in uniq
                   if min((abs(p[0] - q[0]) + abs(p[1] - q[1])) for q in rot) > 0.02)
        if miss == 0:
            hits.append(k)
    print(f"   重心 ({fmt(cxm,2)}, {fmt(cym,2)})   不重复点 {len(uniq)}/{len(sub)}")
    if hits:
        print(f"   ★★ 绕重心旋转对称阶数：{hits}"
              f"（最大 {max(hits)} 重）")
    else:
        print("   ★★ 绕重心没有整数阶旋转对称")

    # ---- 事件
    tw = sorted(int(e["floor"]) for e in acts if e.get("eventType") == "Twirl")
    tw_in = [f for f in tw if lo <= f <= hi]
    ss_in = sorted(int(e["floor"]) for e in acts if e.get("eventType") == "SetSpeed"
                   and lo <= int(e["floor"]) <= hi)
    pa_in = [f for f in (int(e["floor"]) for e in acts if e.get("eventType") == "Pause")
             if lo <= f <= hi]
    print(f"   区间内 Twirl {len(tw_in)} 个：{tw_in[:20]}")
    print(f"   区间内 SetSpeed {len(ss_in)} 个：{ss_in[:20]}")
    print(f"   区间内 Pause {len(pa_in)} 个：{pa_in[:10]}")
    sp = speeds_for(o, n - 1)
    sp0 = sp[max(0, lo - 1):hi] if sp else []
    if sp0:
        print(f"   区间内速度档："
              + "  ".join(f"{s:g}x×{k}" for s, k in
                          collections.Counter(round(x, 4) for x in sp0).most_common(6)))
        vals = [(tvs[i] / 180.0) / (sp0[i] or 1.0) for i in range(len(tvs))]
        print(f"   区间内音值 v ："
              + "  ".join(f"{round(v,4):g}×{k}" for v, k in
                          collections.Counter(round(v, 4) for v in vals).most_common(8)))
    bpm = float(o.get("settings", {}).get("bpm") or 0)
    print(f"   settings.bpm = {bpm:g}")


if __name__ == "__main__":
    f = sys.argv[1]
    rest = [int(x) for x in sys.argv[2:]]
    for i in range(0, len(rest), 2):
        probe(f, rest[i], rest[i + 1])
