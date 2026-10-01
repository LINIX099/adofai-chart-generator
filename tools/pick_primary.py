"""主轨选择：把每条轨分别当主轨（其余轨补空白），看生成结果。

用法: python tools/pick_primary.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import midi as midi_mod, onsets as onsets_mod, solve as solve_mod  # noqa: E402

S = os.path.join(ROOT, "samples")
FILL_MS = 600.0
LONG_MS = 1000.0


def stats(ons, m):
    dts = [ons[i + 1].t_ms - ons[i].t_ms for i in range(len(ons) - 1)]
    blanks = sum(1 for d in dts if d > LONG_MS)
    p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0)
    ch = solve_mod.solve(ons, p)
    ot = [o.t_ms for o in ons]
    lead = solve_mod.total_lead_ms(ch, 4)
    e = solve_mod.check_offset(ch, ot[0], 4, ot, m.length_ms + lead, lead)["max_err_ms"] * 1000
    n = max(1, len(ch.floors))
    npa = sum(1 for f in ch.floors if f.pause_beats > 1e-9)
    return dict(onset=len(ons), blanks=blanks, straight=ch.straight_frac * 100,
                ss=ch.n_speed_events, ss100=ch.n_speed_events / n * 100,
                twirl=ch.n_twirl / n * 100, pause=npa, err=e,
                tpl=ch.meta.get("tpl_covered", 0), bpm=ch.base_bpm)


for fn in ("Automaton_Waltz.mid", "FallenEra.mid", "MemoryLocked.mid"):
    m = midi_mod.load(os.path.join(S, fn))
    print("=" * 104)
    print(f"{fn}   {len(m.tracks)} 轨   bpm0={m.bpm0:g}   （每 100 格 SetSpeed：EX=1.35）")
    mel = [t for t in m.tracks if t.notes and not t.is_drum_only()]
    others_all = mel
    print(f"   {'轨':<5}{'名字':<10}{'音数':>6}{'音高':>10}{'均高':>7}{'均力度':>7} | "
          f"{'onset':>6}{'空白':>5}{'SetSpeed':>9}{'每100':>7}{'直线':>7}{'Twirl':>7}"
          f"{'Pause':>7}{'模板':>6}")
    rows = []
    for t in m.tracks:
        if not t.notes:
            continue
        lo = min(n.pitch for n in t.notes)
        hi = max(n.pitch for n in t.notes)
        avgp = sum(n.pitch for n in t.notes) / len(t.notes)
        avgv = sum(n.velocity for n in t.notes) / len(t.notes)
        if t.is_drum_only():
            print(f"   {t.index:<5}{t.name[:9]:<10}{len(t.notes):>6}{f'{lo}-{hi}':>10}"
                  f"{avgp:>7.1f}{avgv:>7.1f} |  （鼓轨，不做主轨）")
            continue
        fill = [o for o in others_all if o.index != t.index]
        ons = onsets_mod.build_onsets_fill(
            t, fill, onsets_mod.OnsetParams(merge_ms=30.0), FILL_MS)
        st = stats(ons, m)
        rows.append((t, avgp, avgv, st))
        print(f"   {t.index:<5}{t.name[:9]:<10}{len(t.notes):>6}{f'{lo}-{hi}':>10}"
              f"{avgp:>7.1f}{avgv:>7.1f} | "
              f"{st['onset']:>6}{st['blanks']:>5}{st['ss']:>9}{st['ss100']:>7.2f}"
              f"{st['straight']:>6.1f}%{st['twirl']:>6.1f}%{st['pause']:>7}{st['tpl']:>6}")
    if rows:
        print("   各启发式会选：")
        by_note = max(rows, key=lambda r: len(r[0].notes))
        by_pitch = max(rows, key=lambda r: r[1])
        by_vel = max(rows, key=lambda r: r[2])
        by_fit = min(rows, key=lambda r: abs(r[3]["ss100"] - 1.35)
                     + abs(r[3]["straight"] - 45.0) / 20)
        print(f"      音符最多   → trk{by_note[0].index} {by_note[0].name}")
        print(f"      平均音高最高→ trk{by_pitch[0].index} {by_pitch[0].name}")
        print(f"      力度最大   → trk{by_vel[0].index} {by_vel[0].name}")
        print(f"      最贴 EX 标尺 → trk{by_fit[0].index} {by_fit[0].name}")
    print()
