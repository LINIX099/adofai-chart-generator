"""`core/templates.py::match_dp` 单测：时间戳窗口 DP 对位（v0.2 项5）。

要点：DP 是**全局最优**，所以在同样约束下**从不劣于**贪心最长优先，
并且在「贪心先吃掉长模板会挡住更优排布」的场景里严格更好。

跑法:  python tests/test_templates_dp.py
"""
import os
import random
import sys

_ROUTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTE)

from core.templates import Template, match, match_dp     # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def T(i: str, notes: list[float]) -> Template:
    return Template(id=i, name=i, notes=list(notes),
                    travel=[n * 180.0 for n in notes])


def covered(hits) -> int:
    return sum(r * t.n for _i, t, r in hits)


def separating_case():
    print("=" * 78)
    print("A. 贪心次优、DP 最优的构造用例")
    print("=" * 78)
    # A 在 0 处能匹配 5 格，贪心先吃掉它 → 3 号位的 C（4 格）永远用不上
    rs = [1, 1, 1, 0.5, 0.5, 0.5, 0.5, 9]
    tpls = [T("A", [1, 1, 1, 0.5, 0.5]), T("B", [1, 1, 1]),
            T("C", [0.5, 0.5, 0.5, 0.5])]
    g = match(rs, tpls, 0.006)
    d = match_dp(rs, tpls, 0.006)
    check(covered(g) == 5, f"贪心只覆盖 5 格（实际 {covered(g)}）")
    check(covered(d) == 7, f"DP 覆盖 7 格（实际 {covered(d)}）")
    check(covered(d) > covered(g), "DP 严格优于贪心")
    check([(i, t.id) for i, t, _r in d] == [(0, "B"), (3, "C")],
          f"DP 选的是 B@0 + C@3（实际 {[(i,t.id) for i,t,_ in d]}）")


def never_worse():
    print("=" * 78)
    print("B. 随机压力：DP 从不劣于贪心")
    print("=" * 78)
    from core.templates import load
    tpls = load()
    rng = random.Random(20240915)
    worse = better = 0
    trials = 400
    for _ in range(trials):
        n = rng.randint(4, 70)
        rs = [rng.choice([0.25, 0.5, 0.75, 1.0, 1/3, 2/3, 2.0]) for _ in range(n)]
        ca = covered(match(rs, tpls, 0.006))
        cb = covered(match_dp(rs, tpls, 0.006))
        if cb < ca:
            worse += 1
        elif cb > ca:
            better += 1
    check(worse == 0, f"DP 更差 {worse} / {trials} 次（必须 0）")
    check(better >= 1, f"DP 更好 {better} / {trials} 次（证明确实更优）")


def invariants():
    print("=" * 78)
    print("C. 不变量：不重叠 / 有序 / 越界 / 确实匹配")
    print("=" * 78)
    from core.templates import load
    tpls = load()
    rng = random.Random(7)
    bad_overlap = bad_order = bad_fit = bad_reps = 0
    for _ in range(200):
        n = rng.randint(4, 60)
        rs = [rng.choice([0.25, 0.5, 0.75, 1.0, 1/3, 2/3]) for _ in range(n)]
        hits = match_dp(rs, tpls, 0.006)
        cur = 0
        for i, t, r in hits:
            if i < cur:
                bad_overlap += 1
            if i + r * t.n > n:
                bad_order += 1
            if r < 1:
                bad_reps += 1
            for k in range(r):
                for j in range(t.n):
                    if abs(rs[i + k * t.n + j] - t.notes[j]) > 0.006:
                        bad_fit += 1
            cur = i + r * t.n
    check(bad_overlap == 0, f"区间不重叠（违规 {bad_overlap}）")
    check(bad_order == 0, f"全部落在序列内（越界 {bad_order}）")
    check(bad_reps == 0, f"reps ≥ 1（违规 {bad_reps}）")
    check(bad_fit == 0, f"每一格都真的匹配（违约 {bad_fit}）")
    check(match_dp([], tpls) == [] and match_dp([1.0], []) == [],
          "空输入 → 空结果")


def accept_and_timing():
    print("=" * 78)
    print("D. accept 屏障与时序闸仍然生效")
    print("=" * 78)
    rs = [1.0] * 12
    tpls = [T("S", [1.0, 1.0])]
    full = match_dp(rs, tpls, 0.006)
    check(covered(full) == 12, f"无屏障时全覆盖（{covered(full)}）")

    # 屏蔽前 6 格
    def accept(i, t, reps):
        return i >= 6
    blocked = match_dp(rs, tpls, 0.006, accept=accept)
    check(all(i >= 6 for i, _t, _r in blocked), f"accept 屏障生效（{[(i) for i,_,_ in blocked]}）")
    check(covered(blocked) == 6, f"屏障后只剩 6 格（{covered(blocked)}）")

    # 时序闸：音值一致但原始 Δt 偏离 → 必须拒绝
    ok = match_dp(rs, tpls, 0.006, timing=[1.0] * 12, beat_ms=500.0,
                  timing_tol_ms=0.5)
    check(covered(ok) == 12, "时序完全吻合 → 接受")
    bad = match_dp(rs, tpls, 0.006, timing=[1.5] * 12, beat_ms=500.0,
                   timing_tol_ms=0.5)
    check(covered(bad) == 0, "时序偏离 0.5 拍 > 容差 → 全部拒绝")


def main():
    separating_case()
    never_worse()
    invariants()
    accept_and_timing()
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
