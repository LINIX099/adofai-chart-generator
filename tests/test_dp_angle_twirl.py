"""「双押成对第 1 格放 Twirl」的验证（纯角度双押的核心机制）。

结论（本文件把它钉成回归）：
  在 `[θ, T−θ]` 的**第 1 格**放 Twirl，parity 从该格起翻转，于是成对 `Δa == T`；
  而原单格 `Δa == 180 − T`。两者相等 ⟺ **T = 90° 或 270°**（与 θ 无关）。
  此时第 2 格**原样继承原格的下游角度**；再在下游第一格补一个 Twirl 把 parity
  拨回，则**整条下游逐格一致**（几何 100% 等价）。

跑法:  python tests/test_dp_angle_twirl.py
"""
import os
import sys

_ROUTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTE)

from core.path import Path                              # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


PREFIX = [180.0, 180.0]
#: 下游故意含**转弯格**（travel≠180），这样 parity 翻转才会暴露出来
TAIL_TURNING = [180.0, 90.0, 45.0, 180.0, 90.0]
TAIL_STRAIGHT = [180.0] * 5
N = len(PREFIX)


def angles(tv, fl):
    return [round(a, 6) for a in Path.from_travels(tv, flips=fl).angles]


def eq(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def base_of(T, tail):
    tv = PREFIX + [T] + tail
    return angles(tv, [False] * len(tv))


def inserted(T, theta, tail, twirls):
    tv = PREFIX + [theta, T - theta] + tail
    fl = [False] * len(tv)
    for k in twirls:
        fl[k] = True
    return angles(tv, fl)


def delta_a(seq, i):
    return (seq[i] - seq[i - 1]) % 360.0


def core_identity():
    print("=" * 78)
    print("A. 成对 Δa == 单格 Δa ⟺ T ∈ {90°, 270°}（与 θ 无关）")
    print("=" * 78)
    bad = []
    for T in (90.0, 270.0):
        for theta in (15.0, 30.0):
            if T - theta < 15:
                continue
            b = base_of(T, TAIL_STRAIGHT)
            ins = inserted(T, theta, TAIL_STRAIGHT, (N,))     # Twirl 在第 1 格
            da_single = delta_a(b, N)
            da_pair = (delta_a(ins, N) + delta_a(ins, N + 1)) % 360.0
            if abs(da_single - da_pair) > 1e-9:
                bad.append((T, theta, da_single, da_pair))
    check(not bad, f"T=90/270 时成对 Δa == 单格（异常 {bad}）")

    # T=180 必须**不相等**（这正是 BUGJI 踩的坑）
    b = base_of(180.0, TAIL_STRAIGHT)
    ins = inserted(180.0, 30.0, TAIL_STRAIGHT, (N,))
    d_s = delta_a(b, N)
    d_p = (delta_a(ins, N) + delta_a(ins, N + 1)) % 360.0
    check(abs((d_p - d_s) % 360.0 - 180.0) < 1e-9,
          f"T=180 时成对与单格恰好差 180°（{d_s} vs {d_p}）")


def second_tile_inherits():
    print("=" * 78)
    print("B. 第 2 格的 angleData == 原格（T=90/270）")
    print("=" * 78)
    for T in (90.0, 270.0):
        for theta in (15.0, 30.0):
            if T - theta < 15:
                continue
            b = base_of(T, TAIL_STRAIGHT)
            ins = inserted(T, theta, TAIL_STRAIGHT, (N,))
            check(abs(ins[N + 1] - b[N]) < 1e-9,
                  f"T={T:.0f} θ={theta:.0f}: 第2格 {ins[N+1]} == 原格 {b[N]}")
    # T=180 反例
    b = base_of(180.0, TAIL_STRAIGHT)
    ins = inserted(180.0, 30.0, TAIL_STRAIGHT, (N,))
    check(abs(ins[N + 1] - b[N] - 180.0) < 1e-9,
          f"T=180: 第2格比原格大 180°（{b[N]} → {ins[N+1]}）")


def one_twirl_vs_two():
    print("=" * 78)
    print("C. 1 个 Twirl 只修好成对；2 个 Twirl 整条下游等价")
    print("=" * 78)
    for T in (90.0, 270.0):
        for theta in (15.0, 30.0):
            if T - theta < 15:
                continue
            b = base_of(T, TAIL_TURNING)
            one = inserted(T, theta, TAIL_TURNING, (N,))
            two = inserted(T, theta, TAIL_TURNING, (N, N + 2))

            # 1 个 Twirl：第2格对了，但下游被 mirror（含转弯格时必须暴露）
            d1 = eq(one[N + 2:], b[N + 1:])
            check(not d1,
                  f"T={T:.0f} θ={theta:.0f}: 1 Twirl 下游**不一致**（parity 翻转暴露）")
            # 2 个 Twirl：整条下游逐格一致
            d2 = eq(two[N + 2:], b[N + 1:])
            check(d2,
                  f"T={T:.0f} θ={theta:.0f}: 2 Twirl 下游**逐格一致** ★")
            # 第 2 格仍然继承
            check(abs(two[N + 1] - b[N]) < 1e-9,
                  f"T={T:.0f} θ={theta:.0f}: 2 Twirl 下第2格仍 == 原格")

    # 全直线下游：1 个 Twirl 就够（直线格 parity 不变）
    b = base_of(90.0, TAIL_STRAIGHT)
    one = inserted(90.0, 30.0, TAIL_STRAIGHT, (N,))
    check(eq(one[N + 2:], b[N + 1:]),
          "下游全直线时，1 个 Twirl 即可保持下游一致（直线是 parity 不变的）")


def notch_shape():
    print("=" * 78)
    print("D. 插入的「薄格」确实是双押缺口，且总 travel 不变")
    print("=" * 78)
    T, theta = 90.0, 30.0
    b = base_of(T, TAIL_STRAIGHT)
    ins = inserted(T, theta, TAIL_STRAIGHT, (N,))
    # 总 travel 不变 ⇒ 总时长不变（用 travel 序列求和验证）
    tv_o = PREFIX + [T] + TAIL_STRAIGHT
    tv_i = PREFIX + [theta, T - theta] + TAIL_STRAIGHT
    check(abs(sum(tv_i) - sum(tv_o)) < 1e-9,
          f"总 travel 不变（{sum(tv_o)} == {sum(tv_i)}）→ 零时长偏移")
    # 薄格的 angleData 相对"不加 Twirl"的变体差 2θ
    ins_no = inserted(T, theta, TAIL_STRAIGHT, ())
    check(abs(ins[N] - ins_no[N] - 2 * theta) < 1e-9,
          f"薄格 angleData 被 Twirl 改变 +2θ（{ins_no[N]} → {ins[N]}）")
    check(abs(ins[N] - (b[N - 1] + theta - 180.0) % 360.0) < 1e-9,
          f"薄格 angleData == a_prev + θ − 180 (mod 360)（{ins[N]}）")


def main():
    core_identity()
    second_tile_inherits()
    one_twirl_vs_two()
    notch_shape()
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
