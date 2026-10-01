"""core/straighten.py 单测：角度回正（项1）。

要点：
- **零时序影响**：只改 Twirl 符号，`travel` 一个都不动
- 有长斜轨才动手；干净谱面原样返回
- `pinned`（模板/引擎/自然/雪花段）与 `forbidden`（SetSpeed 格）必须被尊重

跑法:  python tests/test_straighten.py
"""
import os
import sys

_ROUTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTE)

from core import straighten as st                     # noqa: E402
from core.path import Path                            # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


class F:
    """最小 Floor 存根：straighten 只读 `.travel`。"""

    __slots__ = ("travel",)

    def __init__(self, tv):
        self.travel = float(tv)


def offaxis(floors, flips):
    p = Path.from_floors(floors, flips)
    return sum(p.deviation(i) for i in range(p.n))


def runs(floors, flips):
    p = Path.from_floors(floors, flips)
    return p.diagonal_runs(theta=20.0, min_run=8, start=1)


# 两格 travel=120（|turn|=60，符号不对称 mod 90）→ 同号会停在斜向，异号回正交。
TV_DIAG = [180.0] + [120.0, 120.0] + [180.0] * 20


def main():
    print("=" * 78)
    print("A. 基础：长斜轨被拉回正交，且 travel 完全不变")
    print("=" * 78)
    floors = [F(t) for t in TV_DIAG]
    base = [False] * len(floors)
    r0 = runs(floors, base)
    check(len(r0) >= 1, f"基线下确实存在长斜轨 （{r0}）")
    o0 = offaxis(floors, base)

    plan = st.plan_straighten(floors, base, theta=20.0, min_run=8)
    check(plan.skipped == "", f"应当执行回正 （skipped={plan.skipped!r}）")
    check(plan.offaxis_after < plan.offaxis_before - 1.0,
          f"偏轴下降 {plan.offaxis_before:.1f} → {plan.offaxis_after:.1f}")
    check(offaxis(floors, plan.flips) < o0 - 1.0, "复算偏轴确实下降")
    r1 = runs(floors, plan.flips)
    check(sum(l for _, l in r1) < sum(l for _, l in r0),
          f"斜轨覆盖下降 （{sum(l for _,l in r0)} → {sum(l for _,l in r1)}）")
    check(all(abs(floors[i].travel - TV_DIAG[i]) < 1e-12 for i in range(len(floors))),
          "travel 一个都没改（零时序影响）")
    check(plan.twirls_after <= plan.twirls_before * 2 + 2,
          f"Twirl 数受控 （{plan.twirls_before} → {plan.twirls_after}）")

    print("=" * 78)
    print("B. 干净谱面：不做任何改动")
    print("=" * 78)
    clean = [F(180.0)] * 30
    plan_c = st.plan_straighten(clean, [False] * 30)
    check(plan_c.skipped == "no-diagonal-run",
          f"全直线 → 跳过 （skipped={plan_c.skipped!r}）")
    check(plan_c.flips == [False] * 30, "flips 原样返回")
    check(plan_c.changed == 0, "changed == 0")

    # 无长斜轨（斜格太少）
    short = [F(180.0), F(120.0), F(120.0)] + [F(180.0)] * 3
    plan_s = st.plan_straighten(short, [False] * len(short), min_run=8)
    check(plan_s.skipped == "no-diagonal-run",
          "斜轨不够长 → 不处理")

    print("=" * 78)
    print("C. 尊重 pinned / forbidden")
    print("=" * 78)
    # pinned = {2}：不许改第 2 格 → 失去「异号回正」的机会
    plan_p = st.plan_straighten(floors, base, pinned={2}, theta=20.0, min_run=8)
    check(plan_p.flips[2] is False, "pinned 格保持原 flip")

    # forbidden = 全部可翻点 → 不能加 Twirl
    plan_f = st.plan_straighten(floors, base,
                                forbidden=set(range(len(floors))),
                                theta=20.0, min_run=8)
    check(all(v is False for v in plan_f.flips), "forbidden 格不加 Twirl")
    check(plan_f.offaxis_after == plan_f.offaxis_before,
          "全被禁止 → 无法回正，原样返回")

    print("=" * 78)
    print("D. 开关与边界")
    print("=" * 78)
    plan_off = st.plan_straighten(floors, base, allow_twirl=False)
    check(plan_off.skipped == "disabled", "allow_twirl=False → disabled")
    check(plan_off.flips == base, "disabled 时 flips 不变")

    plan_empty = st.plan_straighten([], [])
    check(plan_empty.skipped == "disabled", "空输入 → disabled（不崩）")

    # flip_penalty 很大 → 省 Twirl（可能不动）
    plan_cost = st.plan_straighten(floors, base, flip_penalty=1e9, theta=20.0, min_run=8)
    check(plan_cost.twirls_after <= plan.twirls_before,
          f"高 Twirl 代价 → 不加图标 （{plan_cost.twirls_before} → {plan_cost.twirls_after}）")

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
