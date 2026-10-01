# -*- coding: utf-8 -*-
"""验证 docs/25 §1.2 的三个恒等式（别让文档里写的是我口算的东西）。

用法:  python tools/_ladder_verify.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.path import Path, turn_of, angle_of, norm180                   # noqa: E402
from vendor.adofai_timemodel.angle import ADOAngle                       # noqa: E402

# 我们模型的 travel → angleData 差（同一 parity）
def our_delta(T: float, ccw: bool, a_prev: float) -> float:
    h_prev = 90.0 - a_prev
    turn = turn_of(T, ccw)
    a = angle_of(h_prev + turn)
    d = norm180(a - a_prev)
    return 0.0 if abs(d) < 1e-9 else d


# 用 vendored parser 的公式反解 travel（docs/16 §1 的两处来源之一）
def parser_travel(da: float, ccw: bool) -> float:
    # travel = movedDegrees(start, end, not ccw)，start=270−a_prev, end=90−a
    # ⇒ end−start = −180 − Δa
    delta = -180.0 - da
    travel = delta * (1.0 if not ccw else -1.0)
    return travel % 360.0


ok = True
print("=" * 78)
print("恒等式 A：travel 只由 (r, k) 决定 —— 由 solve 的公式直接给出（不在这里重复验）")
print("=" * 78)
print()
print("=" * 78)
print("恒等式 B：同一 travel，两种 parity 的写法 Δa 相差 180°，且都反解回同一个 travel")
print("=" * 78)
print(f"{'T':>8}{'Δa(无Tw)':>12}{'Δa(有Tw)':>12}{'和':>8}"
      f"{'parser←无Tw':>14}{'parser←有Tw':>14}")
for T in (15.0, 45.0, 60.0, 90.0, 120.0, 135.0, 165.0, 180.0,
          195.0, 225.0, 270.0, 315.0, 345.0):
    d0 = our_delta(T, False, 0.0)
    d1 = our_delta(T, True, 0.0)
    p0 = parser_travel(d0, False)
    p1 = parser_travel(d1, True)
    s = norm180(d0 + d1)
    good = abs(abs(s) - 180.0) < 1e-6 or abs(s) < 1e-6
    good = good and abs(p0 - T) < 1e-6 and abs(p1 - T) < 1e-6
    ok &= good
    print(f"{T:>8.1f}{d0:>12.2f}{d1:>12.2f}{s:>8.2f}"
          f"{p0:>14.2f}{p1:>14.2f}   {'OK' if good else '✘'}")
print()
print("  结论：Δa(无Tw) = 180 − T，Δa(有Tw) = T − 180，两者互为相反数（相差 180°），")
print("        且反解出的**有效 travel 完全相同** ⇒ parity 不改变时长，只改几何。")
print()
print("=" * 78)
print("恒等式 C：半圈由 T 自己决定（内圈 T≤180 ⇔ turn≤0 / 外圈 T>180 ⇔ turn>0）")
print("=" * 78)
print(f"{'T':>8}{'turn(无Tw)':>12}{'turn(有Tw)':>12}{'|turn|':>9}  半圈")
for T in (15.0, 90.0, 120.0, 179.0, 180.0, 181.0, 240.0, 270.0, 345.0):
    t0 = turn_of(T, False)
    t1 = turn_of(T, True)
    half = "内圈" if T <= 180.0 + 1e-9 else "外圈"
    good = t0 * t1 <= 0                      # 两种 parity 的 turn 符号相反
    good = good and abs(abs(t0) - abs(T - 180.0)) < 1e-9
    good = good and ((t0 < 0) == (T < 180.0))   # 无 Twirl 时 travel<180 ⇒ turn<0
    ok &= good
    print(f"{T:>8.1f}{t0:>12.2f}{t1:>12.2f}{abs(t0):>9.2f}  {half}"
          f"   {'OK' if good else '✘'}")
print()
print("=" * 78)
print("恒等式 D（顺带）：|turn| = |T − 180|，两种 parity 的 turn 关于 0 对称 ⇒ ")
print("            出射朝向关于「当前朝向」镜像（这正是第 3 级「新的 180°」的几何含义）")
print("=" * 78)
for T in (60.0, 120.0, 240.0):
    h = 90.0
    h0 = h + turn_of(T, False)
    h1 = h + turn_of(T, True)
    mirror = abs(norm180((h0 - h) + (h1 - h))) < 1e-9
    ok &= mirror
    print(f"  T={T:>6.1f}  h'={h0 % 360:7.2f} / {h1 % 360:7.2f}  "
          f"关于 h={h:g} 镜像：{'OK' if mirror else '✘'}")
print()
print("=> 全部通过" if ok else "=> 有断言不成立，文档 §1.2 需要改")
raise SystemExit(0 if ok else 1)
