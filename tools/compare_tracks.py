"""多音轨采音 vs 单音轨 —— 看「空白音」少了多少，以及生成结果的变化。

用法:  python tools/compare_tracks.py [--merge 30]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import midi as midi_mod, onsets as onsets_mod, solve as solve_mod  # noqa: E402

S = os.path.join(ROOT, "samples")
LONG_MS = 1000.0


def gap_stats(ons):
    dts = [ons[i + 1].t_ms - ons[i].t_ms for i in range(len(ons) - 1)]
    if not dts:
        return 0, 0.0, 0.0
    dts_s = sorted(dts)
    long_n = sum(1 for d in dts if d > LONG_MS)
    return (long_n,
            sum(d for d in dts if d > LONG_MS) / 1000.0,
            dts_s[len(dts_s) // 2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", type=float, default=30.0)
    args = ap.parse_args()

    for fn in ("Automaton_Waltz.mid", "FallenEra.mid", "MemoryLocked.mid"):
        m = midi_mod.load(os.path.join(S, fn))
        print("=" * 96)
        print(f"{fn}   tracks={len(m.tracks)}   bpm0={m.bpm0:g}")
        for t in m.tracks:
            print("      " + onsets_mod.track_summary(t))
        print(f"   {'采音':<16}{'onset':>7}{'>1s空白':>9}{'空白总秒':>10}"
              f"{'中位间隔':>10}   {'SetSpeed':>8}{'Pause':>7}{'直线':>8}{'误差us':>9}")
        for label, spec, idx in (("单轨 trk0", "auto", -1),
                                 ("单轨 trk1", "auto", 1),
                                 ("多轨 all", "all", -1),
                                 ("补空白 600ms", "fill", -1),
                                 ("补空白 1200ms", "fill1200", -1),
                                 ("多轨 all+drums", "all+drums", -1)):
            if idx >= 0 and idx >= len(m.tracks):
                continue
            if spec == "fill" or spec == "fill1200":
                gap = 600.0 if spec == "fill" else 1200.0
                prim = onsets_mod.select_tracks(m, "auto", -1)[0]
                others = [t for t in onsets_mod.select_tracks(m, "all", -1)
                          if t.index != prim.index]
                ons = onsets_mod.build_onsets_fill(
                    prim, others, onsets_mod.OnsetParams(merge_ms=args.merge), gap)
                names = f"主trk{prim.index}+补{len(others)}轨"
            else:
                trks = onsets_mod.select_tracks(m, spec, idx)
                if not trks:
                    continue
                ons = onsets_mod.build_onsets_multi(
                    trks, onsets_mod.OnsetParams(merge_ms=args.merge))
                names = "+".join(f"trk{t.index}" for t in trks)
            if len(ons) < 2:
                print(f"   {label:<16} onset 太少")
                continue
            nl, ls, med = gap_stats(ons)
            p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0)
            ch = solve_mod.solve(ons, p)
            ot = [o.t_ms for o in ons]
            lead = solve_mod.total_lead_ms(ch, 4)
            e = solve_mod.check_offset(ch, ot[0], 4, ot, m.length_ms + lead, lead)["max_err_ms"] * 1000
            npa = sum(1 for f in ch.floors if f.pause_beats > 1e-9)
            print(f"   {label:<16}{len(ons):>7}{nl:>9}{ls:>10.1f}{med:>10.0f}   "
                  f"{ch.n_speed_events:>8}{npa:>7}{ch.straight_frac*100:>7.1f}%{e:>9.0f}")
            print(f"        （{names}）")
        print()


if __name__ == "__main__":
    main()
