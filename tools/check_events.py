"""SetSpeed / Pause / 直线 的体检：看程序是不是还在乱用速度档、长休止有没有硬扭。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import midi as midi_mod, onsets as onsets_mod, solve as solve_mod  # noqa: E402

S = os.path.join(ROOT, "samples")

for fn in ("Automaton_Waltz.mid", "FallenEra.mid", "MemoryLocked.mid"):
    m = midi_mod.load(os.path.join(S, fn))
    ons = onsets_mod.build_onsets(m.tracks[0].notes, onsets_mod.OnsetParams(merge_ms=30.0))
    dts = [ons[i + 1].t_ms - ons[i].t_ms for i in range(len(ons) - 1)]
    print("=" * 92)
    print(f"{fn}   音符 {len(dts)}   总时长 {sum(dts)/1000:.0f}s")
    print(f"   {'配置':<24}{'SetSpeed':>9}{'Pause':>7}{'直线':>8}{'Twirl':>7}"
          f"{'速度范围':>12}{'误差us':>9}")
    for tag, kw in (
        ("默认（罚3 段长6）", {}),
        ("罚 10", {"speed_switch_penalty": 10.0}),
        ("罚 30", {"speed_switch_penalty": 30.0}),
        ("罚 100", {"speed_switch_penalty": 100.0}),
        ("罚 30 段长 16", {"speed_switch_penalty": 30.0, "speed_min_run": 16}),
        ("罚 1e9（全谱一个档）", {"speed_switch_penalty": 1e9}),
    ):
        p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0, **kw)
        ch = solve_mod.solve(ons, p)
        ot = [o.t_ms for o in ons]
        lead = solve_mod.total_lead_ms(ch, 4)
        e = solve_mod.check_offset(ch, ot[0], 4, ot, m.length_ms + lead, lead)["max_err_ms"] * 1000
        sp = solve_mod.speed_profile(ch)
        npa = sum(1 for f in ch.floors if f.pause_beats > 1e-9)
        print(f"   {tag:<24}{ch.n_speed_events:>9}{npa:>7}"
              f"{ch.straight_frac*100:>7.1f}%{ch.n_twirl:>7}"
              f"{sp['min']:>5.2f}~{sp['max']:<6.2f}{e:>9.0f}")
    # 长休止现在长什么样
    p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0)
    ch = solve_mod.solve(ons, p)
    big = [(i, dts[i], ch.floors[i + 1].travel, ch.floors[i + 1].pause_beats)
           for i in range(len(dts)) if dts[i] > 2000]
    big.sort(key=lambda x: -x[1])
    if big:
        print("   最长的 6 处休止：")
        for i, d, tv, pb in big[:6]:
            print(f"      onset {i:<5} 休止 {d:7.0f}ms  →  travel {tv:6.1f}°  "
                  f"Pause {pb:.2f} 拍")
    print()
