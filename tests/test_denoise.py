"""去噪 / 吸附单测（`docs/44`）。

    python tests/test_denoise.py

不碰网络、不碰宿廷：全是合成数据 —— 我们自己造一个「格 + 抖动」的序列，
再验它能不能**逐点吸回原来的格**、分母推得对不对、撞格有没有被报出来。

★ 关键等价性：本模块的吸附要用 `core.bdg.snap.js_round`（半数向 +∞），
  否则「正好半格」的点会和 BDG 吸到**不同的**格上（那是真实的错位来源）。
"""
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import denoise as DN                            # noqa: E402
from core.bdg import snap as SN                           # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _lattice(ks, period=150.0, phase=76.871, jitter=0.0, seed=7):
    """`ks` = 格号（单位 = 1/div 拍），加抖动 ⇒ 时间戳列表。"""
    rnd = random.Random(seed)
    step = period / 4.0
    out = [phase + k * step for k in ks]
    if jitter:
        out = [t + rnd.uniform(-jitter, jitter) for t in out]
    return out


def A_grid():
    print("=" * 78)
    print("A. 网格规划：砖长 / 相位 / 分母")
    ts = _lattice([0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44], jitter=4.0)
    g = DN.plan(ts)
    check(abs(g.period_ms - 150.0) < 1.0, f"砖长≈150ms（实得 {g.period_ms:.4f}）")
    check(abs(g.bpm - 400.0) < 3.0, f"bpm≈400（实得 {g.bpm:.3f}）")
    check(g.div in DN.DIVS, f"分母落在宿主档位上：1/{g.div}")
    check(g.ok, "网格通过置信度门槛")

    # ★ 分母自动：格必须**细于最小间隔**（否则两个音撞进同一格 = 丢音）
    gap = DN.min_gap(ts)
    check(g.step_ms < gap, f"格 {g.step_ms:.3f}ms < 最小间隔 {gap:.3f}ms（不撞格）")
    d, why = DN.safe_div(150.0, 40.0)
    check(150.0 / d < 40.0, f"safe_div(150,40) = 1/{d} → 步长 {150.0 / d:.3f} < 40")
    d2, _w = DN.safe_div(150.0, 200.0)
    check(d2 == 1, f"间隔很宽 ⇒ 分母取 1（实得 1/{d2}）")
    d3, w3 = DN.safe_div(150.0, 1.0)
    check(d3 == DN.MAX_DIV and "上限" in w3, f"极密 ⇒ 到上限并**说出来**（1/{d3}）")

    # 相位：给了我们的 offset 就不再拟合，但要报出差多少
    g2 = DN.plan(ts, offset_ms=0.0)
    check(g2.phase_ms == 0.0, "给了 offset ⇒ 相位就用它（相位的唯一真源）")
    g2b = DN.plan(ts, offset_ms=g.phase_ms + 30.0)
    check(any("相位" in n for n in g2b.notes),
          "相位明显对不齐时要在 notes 里说明（不许静默）")
    g2c = DN.plan(ts, offset_ms=g.phase_ms)
    check(not any("相位" in n for n in g2c.notes),
          "相位对齐时就别吵（报告不能变噪音）")

    # hint：用户说了算
    g3 = DN.plan(ts, hint=149.5)
    check(abs(g3.period_ms - 149.5) < 1e-9 and g3.from_hint,
          "给了 hint 就完全按 hint（不精修）")


def _norm(ks):
    """格号归一化：相位只在**模一格**的意义下唯一、分母也只差一个整数倍
    ⇒ 先平移再除以 (k − k0) 的**最大公约数**，只比真正的格结构。"""
    from math import gcd
    d = [k - ks[0] for k in ks]
    g = 0
    for x in d:
        g = gcd(g, abs(int(x)))
    g = max(1, g)
    return [x // g for x in d]


def B_snap():
    print("=" * 78)
    print("B. 吸附：逐点落格 + 落对格")
    ks = [0, 4, 8, 9, 13, 16, 20, 21, 25, 32, 40, 44, 48, 52]
    ts = _lattice(ks, jitter=5.0)
    g = DN.plan(ts)
    check(abs(g.period_ms - 150.0) < 0.05,
          f"★ 抖动存在时周期仍精修到 150（实得 {g.period_ms:.4f}）")
    r = DN.denoise(ts, g)
    check(r["ok"] and r["n_out"] == len(ts), "一个点都没丢")
    check(r["n_dropped"] == 0, "没有撞格")
    bad = [k for k, t, t0 in zip(r["ks"], r["ts"], ts) if abs(t - t0) > g.step_ms / 2 + 1e-9]
    check(not bad, "每个点的挪动都 ≤ 半格（最近格点的定义）")
    # ★ 真正的验收：吸回来的**相对**格号 == 原来的相对格号
    check(_norm(r["ks"]) == _norm(ks),
          f"逐点吸回原格（{sum(1 for a, b in zip(_norm(r['ks']), _norm(ks)) if a != b)} 处不符）")
    check(all(abs(b * g.div - round(b * g.div)) < 1e-9 for b in r["beats"]),
          "beats 全是 k/div（可交给 BDG 当整数格）")
    check(r["report"]["move_median_ms"] < 5.0,
          f"中位挪动 {r['report']['move_median_ms']}ms")

    # 无抖动 ⇒ 一点不动
    ts0 = _lattice(ks, jitter=0.0)
    r0 = DN.denoise(ts0, DN.plan(ts0))
    check(r0["n_moved"] == 0, f"无抖动时一个点都不挪（实得 {r0['n_moved']}）")


def C_half_grid():
    print("=" * 78)
    print("C. 正好半格：必须与 BDG 的 `Math.round` 同结果")
    period, div = 150.0, 4
    step = period / div
    g = DN.GridPlan(ok=True, period_ms=period, phase_ms=0.0, step_ms=step, div=div)
    # 3.5 格 ⇒ JS `Math.round(3.5)` = 4（半数向 +∞）；Python round 会给 4 也对，
    # 但 2.5/4.5 会分道扬镳 ⇒ 用它们当探针。
    ts = [2.5 * step, 4.5 * step, -1.5 * step]
    r = DN.denoise(ts, g)
    ks = [int(SN.js_round(t / step)) for t in ts]
    ks.sort()                     # denoise 的输出**按时间排序**（见 docstring）
    check(r["ks"] == ks, f"半格点按 js_round 走：{r['ks']} == {ks}")
    check(sorted(r["ks"]) == [-1, 3, 5], "−1.5→−1、2.5→3、4.5→5（半数向 +∞）")
    # 对照：Python 内建 round 会给出不同答案（证明这个细节真的要紧）
    diff = [k for k, t in zip(ks, sorted(ts)) if k != round(t / step)]
    check(diff, f"若用 Python 的银行家舍入会差 {len(diff)} 处（所以必须借 js_round）")


def D_collide():
    print("=" * 78)
    print("D. 撞格：宁可不吸，也不能静默丢音")
    # 两个音只差 20ms，而分母 1/32 ⇒ 格 4.69ms 太细：它们会撞进不同格，
    # 但把分母设成 1/1（格 150ms）就会**合并 → 丢音** ⇒ 必须报出来。
    ts = [1000.0, 1020.0, 1300.0]
    g_bad = DN.GridPlan(ok=True, period_ms=150.0, phase_ms=0.0, step_ms=150.0, div=1)
    r = DN.denoise(ts, g_bad)
    check(r["n_dropped"] >= 1, f"粗分母下撞格被丢：{r['n_dropped']} 个")
    check(r["dropped"] and r["dropped"][0]["at_ms"] == 1050.0,
          "丢掉的那个点连**位置**都记下来了（不许静默）")

    # 自动分母不会撞：safe_div 保证 step < gap
    g2 = DN.plan(ts)
    r2 = DN.denoise(ts, g2)
    check(r2["n_dropped"] == 0,
          f"自动分母 1/{g2.div}（格 {g2.step_ms:.2f}ms）不丢音")


def E_radius():
    print("=" * 78)
    print("E. 半径档（BDG 没有的能力）：只吸近的、远的原样保留")
    ks = [0, 4, 8, 12, 16, 20]
    ts = _lattice(ks, jitter=0.0)
    # ★ 叛徒要挪**非整数格**的距离，否则它会优雅地落到隔壁格上（那才是"吸对了"）。
    #   挪 15ms（≈0.4 格）⇒ 离最近格 15ms，半径 10ms 就不该吸它。
    ts[3] += 15.0
    g = DN.GridPlan(ok=True, period_ms=150.0, phase_ms=76.871,
                    step_ms=150.0 / 4, div=4)
    r = DN.denoise(ts, g, radius=10.0)
    check(r["mode"] == DN.MODE_RADIUS and r["n_out_of_radius"] == 1,
          f"半径档生效：{r['n_out_of_radius']} 个点超半径")
    check(abs(r["ts"][3] - ts[3]) < 1e-9, "超半径的点**原样保留**（没被硬吸）")
    check(abs(r["ts"][0] - ts[0]) < 1e-9, "范围内的点照吸")
    check("原样保留" in r["text"], "报告里说了这件事")

    # 全吸（默认）就会把它吸到格上（并且报告挪了多少）
    r2 = DN.denoise(ts, g)
    check(r2["mode"] == DN.MODE_ALL and abs(r2["ts"][3] - ts[3]) > 10.0,
          "默认全吸会把它挪走（与 BDG 行为一致）")


def F_octave():
    print("=" * 78)
    print("F. 倍频：整首都是 16 分时不能把砖长定成 2× 砖")
    # 全是 1/4 砖的间隔（37.5ms）⇒ 众数落在 37.5，但真正的「拍」是 150
    ts = [i * 37.5 for i in range(40)]
    p, why = DN.tile_period(ts)
    check(abs(p - 37.5) < 2.0, f"全 16 分 ⇒ 砖长取 37.5（实得 {p:.3f}；{why}）")
    ts2 = [i * 150.0 for i in range(20)] + [i * 300.0 + 3000 for i in range(10)]
    p2, _ = DN.tile_period(ts2)
    check(abs(p2 - 150.0) < 5.0, f"常规序列 ⇒ 砖长 150（实得 {p2:.3f}）")


def G_real():
    print("=" * 78)
    print("G. 真数据（Flower_Dance 的 1358 个时间戳）")
    path = os.path.join(
        _HOME + r"\.dsh\attachments\v1\files\0a",
        "0aed72d9d890d040d5c6834bb8dc527618f8b0b8ec21d0bdaa1d1ef34f912149",
        "Flower_Dance-DJ_OKAWARI-1974307.txt")
    if not os.path.exists(path):
        print("  [SKIP] 找不到那份外部时间戳（换机器了？）")
        return
    ts = sorted(float(l) for l in open(path, encoding="utf-8") if l.strip())
    g = DN.plan(ts)
    r = DN.denoise(ts, g)
    check(abs(g.bpm - 400.0) < 2.0,
          f"★ 砖长 150ms ⇒ bpm≈400（实得 {g.bpm:.3f}）")
    check(g.div == 4, f"★ 自动分母 1/4（格 {g.step_ms:.3f}ms；实得 1/{g.div}）")
    check(r["n_dropped"] == 0, "一个音都没丢")
    check(r["report"]["move_median_ms"] < 5.0,
          f"中位挪动 {r['report']['move_median_ms']}ms（抖动被吸收）")
    check(all(abs(b * g.div - round(b * g.div)) < 1e-9 for b in r["beats"]),
          "全部落在整数格上")


def main():
    A_grid()
    B_snap()
    C_half_grid()
    D_collide()
    E_radius()
    F_octave()
    G_real()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 去噪/吸附全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
