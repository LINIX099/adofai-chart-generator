"""core/dp_offset.py 单测：双押偏移累计与回正。

关键验证：**把公式与 `vendor/adofai_timemodel`（第三方权威反解器）对齐** ——
写两份只差 `angleOffset` 的 .adofai，用 parser 反解，比较总时长差是否等于
我们预测的 `delta_ms`。这一步把「口径」钉死，不靠猜。

跑法:  python tests/test_dp_offset.py
"""
import json
import os
import sys
import tempfile

_ROUTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTE)

from core import dp_offset as D                        # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


class F:
    __slots__ = ("travel", "bpm", "angle_offset", "pause_beats", "speed_k")

    def __init__(self, travel, bpm, angle_offset=0.0):
        self.travel = float(travel)
        self.bpm = float(bpm)
        self.angle_offset = float(angle_offset)
        self.pause_beats = 0.0
        self.speed_k = 1.0


def formulas():
    print("=" * 78)
    print("A. 公式自洽（与游戏口径一致）")
    print("=" * 78)
    check(abs(D.flat_duration_ms(180, 120) - 500.0) < 1e-9,
          "整格直线 @120bpm = 500ms")
    check(abs(D.split_duration_ms(180, 90, 120, 240) - 375.0) < 1e-9,
          "半格变速 90°@120 + 90°@240 = 250 + 125 = 375ms")
    # 反解 φ 后必须精确重现目标 Δ（注意 defer 有符号/范围约束，取可行组合）
    ok = True
    for A, bp, bn, want in ((180, 120, 240, 190.0),     # 提速 → 只能加长
                            (180, 240, 120, -100.0),    # 减速 → 只能缩短
                            (90, 240, 480, 20.0),
                            (360, 180, 60, -300.0)):
        phi = D.solve_angle_offset(A, bp, bn, want)
        if not (0.0 <= phi <= A + 1e-9):
            ok = False
            break
        got = D.delta_ms(A, phi, bp, bn)
        ok &= abs(got - want) < 1e-9
    check(ok, "solve_angle_offset ↔ delta_ms 往返一致（4 组，含正负）")
    # 符号约束：提速格永远修不了「缩短」
    cap_up = D.defer_capacity_ms(180, 120, 240)
    cap_dn = D.defer_capacity_ms(180, 240, 120)
    check(cap_up > 0 and abs(cap_up - 250.0) < 1e-9,
          f"提速格容量 = +{cap_up:.1f}ms（只能加长）")
    check(cap_dn < 0 and abs(cap_dn + 250.0) < 1e-9,
          f"减速格容量 = {cap_dn:.1f}ms（只能缩短）")
    check(D.solve_angle_offset(180, 120, 240, -60.0) < 0,
          "提速格要「缩短」→ 反解出负 φ（不可行，由调用方拒掉）")
    # Pause 往返
    ok2 = True
    for want, bpm in ((-30.0, 240.0), (17.5, 120.0), (0.0, 180.0)):
        d = D.pause_beats_for(want, bpm)
        ok2 &= abs(d * 60000.0 / bpm - want) < 1e-9
    check(ok2, "pause_beats_for ↔ 额外时长 往返一致（3 组）")


def parser_alignment():
    print("=" * 78)
    print("B. 与 vendor parser 对齐（权威口径：angleOffset = 推迟已有 SetSpeed）")
    print("=" * 78)
    from core.solve import Chart, Floor
    from core import writer
    from core import verify

    # 6 格：第 3 格变速 120 -> 240（SetSpeed 落在第 3 格，默认 angleOffset=0）
    floors = []
    for i in range(6):
        floors.append(Floor(travel=180.0, bpm=120.0 if i < 3 else 240.0,
                            twirl=False, turn=0.0, heading=90.0, angle=0.0,
                            speed_k=1.0 if i < 3 else 0.5))
    floors.append(Floor(travel=180.0, bpm=240.0, twirl=False, turn=0.0,
                        heading=90.0, angle=0.0, speed_k=0.5))
    ch = Chart(base_bpm=120.0, floors=floors)

    A, bp, bn = 180.0, 120.0, 240.0
    want = 190.0
    phi = D.solve_angle_offset(A, bp, bn, want)
    model = D.delta_ms(A, phi, bp, bn)
    check(abs(model - want) < 1e-9, f"反解 φ={phi:.3f}° 后 Δ={model:.3f}ms == 目标")

    tmp = tempfile.mkdtemp(prefix="dp_offset_")
    p0 = os.path.join(tmp, "base.adofai")
    p1 = os.path.join(tmp, "off.adofai")
    writer.write(ch, p0)
    writer.write(ch, p1)
    d = json.load(open(p1, encoding="utf-8"))
    hit = 0
    for act in d["actions"]:
        if act.get("eventType") == "SetSpeed" and int(act.get("floor", -1)) == 3:
            act["angleOffset"] = phi
            hit += 1
    json.dump(d, open(p1, "w", encoding="utf-8"), ensure_ascii=False)
    check(hit == 1, f"定位并改写 SetSpeed@floor3 的 angleOffset （命中 {hit}）")

    try:
        c0, _ = verify.parse_times(p0)
        c1, _ = verify.parse_times(p1)
        got = float(c1[-1]) - float(c0[-1])
        check(abs(got - model) < 0.05,
              f"parser 总时长差 {got:.3f}ms == 预测 {model:.3f}ms（φ={phi:.3f}°）")
        # 局部性：只有第 3 格自己的时长变了
        d0 = [c0[i + 1] - c0[i] for i in range(len(c0) - 1)]
        d1 = [c1[i + 1] - c1[i] for i in range(len(c1) - 1)]
        others = max(abs(d1[j] - d0[j]) for j in range(len(d0)) if j != 2)
        check(others < 1e-6,
              f"只有被改那格变化，其它格最大差 {others*1000:.4f} us（局部性）")
    except Exception as e:                                   # noqa: BLE001
        check(False, f"parser 反解失败: {type(e).__name__}: {e}")


def accumulator():
    print("=" * 78)
    print("C. 累计与回正（20ms 阈值）")
    print("=" * 78)
    base = 300.0
    beat_ms = 60000.0 / base
    per = beat_ms / 12.0                    # 每次双押 +1/12 拍
    n = 40
    # 无 SetSpeed 的谱：只能靠 Pause 回正（AUTO 自动退到 pause）
    flat = [F(180.0, base) for _ in range(n)]
    deltas = [per] * n
    rep = {}
    pl = D.plan_corrections(flat, deltas, base_bpm=base, tol_ms=20.0,
                            mode=D.MODE_AUTO, report=rep)
    check(len(pl.corrections) > 0, f"产生了回正 （{len(pl.corrections)} 处）")
    check(abs(pl.residual_ms) < 0.05,
          f"末尾残余偏移 {pl.residual_ms:.4f}ms ≈ 0")
    check(abs(pl.peak_ms) >= 20.0,
          f"峰值累计 {pl.peak_ms:.2f}ms ≥ 阈值 20ms")
    check(all(c.kind == D.MODE_PAUSE for c in pl.corrections),
          "无 SetSpeed 时退化为 Pause 回正")
    check(all(abs(c.offset_after_ms) < 1e-6 for c in pl.corrections),
          "每次回正后 offset_after ≈ 0")
    print("      " + pl.describe())

    # 有 SetSpeed 的谱：优先用 angleOffset 回正（零额外事件）
    alt = []
    for i in range(n):
        alt.append(F(180.0, base if (i // 2) % 2 == 0 else base * 2))
    pl2 = D.plan_corrections(alt, deltas, base_bpm=base, tol_ms=20.0,
                             mode=D.MODE_SET_SPEED)
    check(len(pl2.corrections) > 0, f"有 SetSpeed 时用 angleOffset 回正（{len(pl2.corrections)} 处）")
    check(all(c.kind == D.MODE_SET_SPEED for c in pl2.corrections),
          f"mode=set_speed 只产出 angleOffset 回正")
    check(all(0.0 <= c.angle_offset <= 180.0 + 1e-9 for c in pl2.corrections),
          "φ 全部落在 [0, travel]")
    print("      " + pl2.describe())

    # pause 模式：任意符号都能修
    pl3 = D.plan_corrections(flat, deltas, base_bpm=base, tol_ms=20.0,
                             mode=D.MODE_PAUSE)
    check(all(c.kind == D.MODE_PAUSE for c in pl3.corrections),
          "pause 模式只产出 Pause 回正")
    check(abs(pl3.residual_ms) < 0.05, f"pause 模式残余 {pl3.residual_ms:.4f}ms ≈ 0")

    # 偏移不够大 → 不动手
    pl4 = D.plan_corrections(flat, [per / 100.0] * n, base_bpm=base, tol_ms=20.0)
    check(not pl4.corrections, "累计不过阈值 → 不回正")

    # set_speed 模式在无事件的谱上应全部 dropped，而不是崩
    pl5 = D.plan_corrections(flat, deltas, base_bpm=base, tol_ms=20.0,
                             mode=D.MODE_SET_SPEED)
    check(pl5.dropped > 0 and not pl5.corrections,
          f"无 SetSpeed + set_speed 模式 → 全部 dropped={pl5.dropped}")


def main():
    formulas()
    parser_alignment()
    accumulator()
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
