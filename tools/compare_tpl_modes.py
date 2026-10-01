"""三种模式对比：DP 兜底 / 模板全用 / 模板只修非直线。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import midi as midi_mod, onsets as onsets_mod, solve as solve_mod  # noqa: E402

S = os.path.join(ROOT, "samples", "_external")
MODES = (("DP    ", False, False), ("模板-全", True, False), ("模板-修", True, True))

for fn in ("Automaton_Waltz.mid", "FallenEra.mid", "MemoryLocked.mid"):
    m = midi_mod.load(os.path.join(S, fn))
    ons = onsets_mod.build_onsets(m.tracks[0].notes, onsets_mod.OnsetParams(merge_ms=30.0))
    for preset in ("少", "平衡", "多"):
        print(f"{fn:<22}{preset}")
        for name, use, only in MODES:
            p = solve_mod.SolveParams(straight_weight=solve_mod.STRAIGHT_PRESETS[preset],
                                      ppqn=m.ppqn, midi_bpm=m.bpm0,
                                      use_templates=use, template_only_nonstraight=only)
            ch = solve_mod.solve(ons, p)
            ot = [o.t_ms for o in ons]
            lead = solve_mod.total_lead_ms(ch, 4)
            e = solve_mod.check_offset(ch, ot[0], 4, ot, m.length_ms + lead, lead)["max_err_ms"] * 1000
            print(f"    {name}  直线={ch.straight_frac*100:5.1f}%  "
                  f"模板={ch.meta.get('tpl_covered', 0):>4}格/{ch.meta.get('tpl_hits', 0):>3}段  "
                  f"Twirl={ch.n_twirl:>4}  SetSpeed={ch.n_speed_events:>4}  "
                  f"速度={solve_mod.speed_profile(ch)['min']:.2f}~{solve_mod.speed_profile(ch)['max']:.2f}x  "
                  f"误差={e:7.0f}us")
    print()
