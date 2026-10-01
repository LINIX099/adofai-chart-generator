"""v3 红线回归：直线优先 / 第一格 / 滚轮。

跑法:  python tests/test_v3_rules.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import midi as midi_mod                     # noqa: E402
from core import onsets as onsets_mod                 # noqa: E402
from core import solve as solve_mod                   # noqa: E402

SAMPLES = os.path.join(_ROOT, "samples", "_external")   # 第三方，不随包
FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def core_checks():
    print("=" * 78)
    print("A. 核心红线（三个样本 × 三档直线优先）")
    print("=" * 78)
    # 样本是第三方音乐，源码包里不带；缺了就跳过这一节（其余检查照跑）
    missing = [fn for fn, _ in (("FallenEra.mid", 0), ("Automaton_Waltz.mid", 0),
                                ("MemoryLocked.mid", 0))
               if not os.path.exists(os.path.join(SAMPLES, fn))]
    if missing:
        print(f"  [跳过] samples/ 里缺 {', '.join(missing)}"
              f" —— 这三首是第三方作品，未随源码包分发。")
        return
    for fn, ti in (("FallenEra.mid", 0), ("Automaton_Waltz.mid", 0), ("MemoryLocked.mid", 0)):
        m = midi_mod.load(os.path.join(SAMPLES, fn))
        ons = onsets_mod.build_onsets(m.tracks[ti].notes, onsets_mod.OnsetParams(merge_ms=30.0))
        for preset in ("少", "平衡", "多"):
            p = solve_mod.SolveParams(straight_weight=solve_mod.STRAIGHT_PRESETS[preset],
                                      ppqn=m.ppqn, midi_bpm=m.bpm0)
            ch = solve_mod.solve(ons, p)
            tag = f"{fn}/trk{ti}/{preset}"
            # ① 第一格 = 直线
            check(abs(ch.floors[0].travel - 180.0) < 1e-9,
                  f"{tag}: 第0层 travel == 180 （实际 {ch.floors[0].travel}）")
            check(abs(ch.floors[0].angle) < 1e-9 or abs(ch.floors[0].angle - 360.0) < 1e-9,
                  f"{tag}: angleData[0] == 0 （实际 {ch.floors[0].angle}）")
            # ② 不出现回头方块（travel<15 或 >345）
            bad = [f for f in ch.floors[1:] if f.travel < 15.0 or f.travel > 345.0]
            check(not bad, f"{tag}: 无回头方块 （{len(bad)} 个越界）")
            # ②b 「直线」必须是精确的 180，不能是 179.9982 这种浮点噪声
            off = [f.travel for f in ch.floors[1:]
                   if 179.0 < f.travel < 181.0 and f.travel != 180.0]
            check(not off, f"{tag}: 直线层 travel 精确 == 180 （{len(off)} 个不精确）")
            # ③ travel 全部 <360（游戏 angleMoved >= 2π 会被强制 2 拍）
            check(all(f.travel < 360.0 for f in ch.floors),
                  f"{tag}: 所有 travel < 360°")
            # ④ 直线为主
            check(ch.straight_frac > 0.45,
                  f"{tag}: 直线 {ch.straight_frac*100:.1f}% > 45%")
            # ⑤ 规则层自检（Twirl/SetSpeed 同格、速度档 2 的幂、回头、第0层）
            from core import rules as rules_mod
            viol = [v for v in rules_mod.check_chart(ch) if v.get("level") != "info"]
            check(not viol, f"{tag}: 规则检查全过 （{len(viol)} 条："
                            + (viol[0]["code"] if viol else "") + "）")
            # ⑥ 时序精度。
            #    注意口径：谱面自身（网格）误差是 0，这里的 0.1ms 来自 MIDI 导出的
            #    tempo 被截断（333333us 而不是 333333.33us = 180BPM）。
            #    我们把基准 BPM 吸附成人写得出来的整数（360/370/400），所以留有这点差。
            ot = [o.t_ms for o in ons]
            lead = solve_mod.total_lead_ms(ch, 4)
            chk = solve_mod.check_offset(ch, ot[0], 4, ot, m.length_ms + lead, lead)
            check(chk["max_err_ms"] < 2.0,
                  f"{tag}: 命中时刻误差 {chk['max_err_ms']*1000:.0f}us < 2000us")


def wheel_checks():
    print("=" * 78)
    print("B. 滚轮不该改数值（模拟滚轮事件）")
    print("=" * 78)
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    w.show()
    app.processEvents()

    def wheel(angle: int) -> QWheelEvent:
        p = QPointF(10.0, 10.0)
        return QWheelEvent(p, QPointF(10.0, 10.0), QPoint(0, 0), QPoint(0, angle),
                           Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)

    for name in ("sp_bpm", "sp_merge", "sp_bpmmax", "sp_offset", "sp_plo"):
        sb = getattr(w, name)
        sb.setValue(sb.value())                       # 确保有确定值
        base = sb.value()
        w.ed_song.setFocus()                          # 焦点在别处
        app.processEvents()
        QApplication.sendEvent(sb, wheel(120))
        app.processEvents()
        check(sb.value() == base,
              f"{name}: 未获得焦点时滚轮不改值 （{base} -> {sb.value()}）")

    sb = w.sp_bpm
    sb.setValue(200.0)
    sb.setFocus()
    app.processEvents()
    QApplication.sendEvent(sb, wheel(120))
    app.processEvents()
    check(sb.value() != 200.0,
          f"sp_bpm: 获得焦点后滚轮**应当**改值 （200 -> {sb.value()}）")

    w.close()


if __name__ == "__main__":
    core_checks()
    wheel_checks()
    print("=" * 78)
    if FAIL:
        print(f"=> FAIL ({len(FAIL)} 项)")
        for m in FAIL:
            print("   - " + m)
        raise SystemExit(1)
    print("=> PASS")
