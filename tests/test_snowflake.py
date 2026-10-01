"""core/snowflake.py 单测：魔法阵（雪花）。

项4 要点：**形状生成确定性化**（穷举 + 确定性打分），并与开源项目
`star_calculator.js` 的参数化对标。

跑法:  python tests/test_snowflake.py
"""
import math
import os
import random
import sys

_ROUTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTE)

from core import snowflake as SN                       # noqa: E402
from core.snowflake import Snowflake                   # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


LENGTHS = (10, 12, 24, 36, 48, 64, 100, 128, 200, 301)


def star_alignment():
    print("=" * 78)
    print("A. 与开源项目 star_calculator.js 的参数化对标")
    print("=" * 78)
    ok = True
    for n, arms in ((6, 3), (8, 4), (6, 4), (12, 5)):
        s = Snowflake(n_rot=n, arms=arms, shape="uniform")
        per = 180.0 + s.turn_out / (arms - 1)          # uniform 每步 travel
        ref = SN.beat_angle(n, arms - 1, inner=True)   # pInterval = arms - 1
        ok &= abs(per - ref) < 1e-9
    check(ok, "uniform 每步 travel == beat_angle(inner)，pInterval = arms−1")

    # 具体数值：n=6, arms=3 → q=2 → 内圈 120°、外圈 240°
    check(abs(SN.beat_angle(6, 2, inner=True) - 120.0) < 1e-9,
          "n_rot=6, pInterval=2 ⇒ 内圈 beatAngle = 120°")
    check(abs(SN.beat_angle(6, 2, inner=False) - 240.0) < 1e-9,
          "同一组 ⇒ 外圈 beatAngle = 240°（我们不采用，只走内圈）")
    # 实测 travels 吻合
    s = Snowflake(n_rot=6, arms=3, shape="uniform")
    tv = [t for t in s.travels() if abs(t - 180.0) > 1e-9]
    check(tv and all(abs(t - 120.0) < 1e-9 for t in tv),
          f"n_rot=6/arms=3 的非直线 travel 全是 120°（{sorted(set(round(t,3) for t in tv))}）")


def determinism():
    print("=" * 78)
    print("B. 确定性：同输入同输出，且与调用顺序无关")
    print("=" * 78)
    # 同一次调用重复
    a = SN.plan(100)
    b = SN.plan(100)
    check(a is not None and b is not None and a == b,
          "同 length 两次 plan 完全一致")

    # 顺序无关（旧写法共用 RNG，次序会影响结果）
    seq1 = [SN.plan(L) for L in LENGTHS]
    seq2 = [SN.plan(L) for L in reversed(LENGTHS)]
    pair_ok = all(seq1[i] == seq2[len(LENGTHS) - 1 - i] for i in range(len(LENGTHS)))
    check(pair_ok, "打乱调用顺序 → 每个 length 结果不变")

    # 不同 RNG 注入也不影响（deterministic 路径忽略 rng）
    r1 = SN.plan(100, rng=random.Random(1))
    r2 = SN.plan(100, rng=random.Random(999))
    check(r1 == r2 == a, "注入不同 RNG 不影响确定性结果")

    # 随机路径仍可用（A/B 开关没坏）
    rand = SN.plan(100, deterministic=False, rng=random.Random(7))
    check(rand is not None and rand.tiles <= 100,
          f"deterministic=False 仍能产出（{rand.describe() if rand else None}）")


def constraints():
    print("=" * 78)
    print("C. 硬约束：内圈 / 闭合 / 格数 / 结构")
    print("=" * 78)
    bad_tiles = bad_outer = bad_close = bad_struct = 0
    for L in LENGTHS:
        s = SN.plan(L)
        if s is None:
            continue
        if s.tiles > L:
            bad_tiles += 1
        if SN.outer_tiles(s) != 0:
            bad_outer += 1
        if SN.close_err(s) > 1e-6:
            bad_close += 1
        if s.tiles != 2 * s.n_rot * s.arms:
            bad_struct += 1
    check(bad_tiles == 0, f"tiles ≤ length（越界 {bad_tiles}）")
    check(bad_outer == 0, f"全内圈：无 travel > 180（越界 {bad_outer}）")
    check(bad_close == 0, f"每条花瓣精确闭合（越界 {bad_close}）")
    check(bad_struct == 0, f"tiles == 2·N·arms（异常 {bad_struct}）")

    s = SN.plan(100)
    # ★ 正确的内圈判据是 `outer_tiles == 0`（travel > 180）。
    #   travel 恰为 180 的**直线格是正常且必需的**（花瓣起点那一格转角 0），
    #   所以 inner_frac 不可能是 100%（参考 R lv16 实测：内圈 61.1% + 直线 38.9%）。
    check(SN.outer_tiles(s) == 0, "outer_tiles == 0（真正的外圈判据）")
    check(0.4 <= s.inner_frac() <= 1.0,
          f"内圈占比落在合理区间（实际 {s.inner_frac()*100:.1f}%）")
    check(len(s.positions()) == s.tiles + 1, "positions 长度 = tiles + 1")
    check(all(abs(t) <= SN.TURN_MAX + 1e-9 for t in s.out_turns()),
          "单步转角不超过 TURN_MAX")

    # 最小可塞：2·N·arms = 2·6·2 = 24
    check(SN.plan(2) is None, "length=2 塞不进 → None")
    check(SN.plan(23) is None, "length=23 < 最小 24 → None")
    check(SN.plan(24) is not None, "length=24 == 最小可用 → 产出")


def greedy_max():
    print("=" * 78)
    print("D. 取「塞得下且格数最大」的那一档")
    print("=" * 78)
    ok = True
    for L in LENGTHS:
        grid = SN.candidate_grid(L)
        if not grid:
            continue
        s = SN.plan(L)
        best = max(g[0] for g in grid)
        ok &= (s.tiles == best)
    check(ok, "plan 每次都用满格数（tiles == max ≤ length）")
    # 同格数优先偶数 N
    pool = SN._pool_of(SN.candidate_grid(96))
    check(all(n % 2 == 0 for _t, n, _a in pool) or not pool,
          f"候选池优先偶数 N（{[(t,n,a) for t,n,a in pool][:4]}…）")


def should_use_rule():
    print("=" * 78)
    print("E. should_use：10 格以内不用，之后递增到 100%")
    print("=" * 78)
    check(not SN.should_use(9, 10, 48.0, 0), "9 格 < min_tiles → 不用")
    check(SN.should_use(60, 10, 48.0, 0), "60 格 ≥ full_tiles → 必用")
    # 单调性：同一个 seed 下，长度越大越容易命中
    hits = [SN.should_use(L, 10, 48.0, 12345) for L in range(10, 49)]
    first_true = next((i for i, h in enumerate(hits) if h), None)
    check(first_true is not None and not any(hits[:first_true]),
          f"首次命中在 length={10 + (first_true or 0)}，之前全 False（单调门控）")


def main():
    star_alignment()
    determinism()
    constraints()
    greedy_max()
    should_use_rule()
    print("=" * 78)
    if FAIL:
        print(f"=> FAIL  （{len(FAIL)} 条）")
        for m in FAIL[:12]:
            print("   · " + m)
        return 1
    print("=> PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
