"""段落时长 vs 模板命中 —— 验证「短段落用 90°，长段落用速度×2」。

对每个样本：
  - 按 Δt > 1s 切「段落」，给出段落时长分布
  - 「模板只修非直线」模式下，扫不同的 template_max_span_s，看命中格数与直线占比
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import midi as midi_mod, onsets as onsets_mod, solve as solve_mod  # noqa: E402

S = os.path.join(ROOT, "samples", "_external")
REST_MS = float(os.environ.get("REST_MS", "1000"))

for fn in ("Automaton_Waltz.mid", "FallenEra.mid", "MemoryLocked.mid"):
    m = midi_mod.load(os.path.join(S, fn))
    ons = onsets_mod.build_onsets(m.tracks[0].notes, onsets_mod.OnsetParams(merge_ms=30.0))
    dts = [ons[i + 1].t_ms - ons[i].t_ms for i in range(len(ons) - 1)]

    # 段落切分
    print("=" * 88)
    print(f"{fn}   总时长 {sum(dts)/1000:.0f}s   音符 {len(dts)}")
    print(f"   {'休止阈值':<10}{'段落数':>7}{'>10s段数':>10}{'>10s占时长':>11}"
          f"{'<10s的段总时长':>15}")
    for rms in (200, 300, 500, 800, 1000, 2000, 4000):
        sgs, i = [], 0
        while i < len(dts):
            j = i
            while j + 1 < len(dts) and dts[j] <= rms:
                j += 1
            sgs.append((i, j + 1))
            i = j + 1
        L = [sum(dts[a:b]) for a, b in sgs]
        tot = sum(L)
        over = [x for x in L if x > 10_000]
        short_t = sum(x for x in L if x <= 10_000)
        print(f"   {rms:>5}ms   {len(sgs):>7}{len(over):>10}"
              f"{sum(over)/tot*100:>10.0f}%{short_t/1000:>13.1f}s")

    segs, i = [], 0
    while i < len(dts):
        j = i
        while j + 1 < len(dts) and dts[j] <= REST_MS:
            j += 1
        segs.append((i, j + 1))
        i = j + 1
    lens = sorted((sum(dts[a:b]) for a, b in segs), reverse=True)
    print(f"   （下面用休止>{REST_MS/1000:.0f}s；最长 8 段: "
          + " ".join(f"{x/1000:.1f}" for x in lens[:8]) + "）")

    print(f"   {'时长闸':<10}{'命中格':>8}{'段数':>6}{'直线':>8}{'Twirl':>7}{'SetSpeed':>10}{'误差us':>9}")
    only = os.environ.get("ONLY", "1") == "1"
    print(f"   （模式：{'模板只修非直线' if only else '模板全用'}）")
    for lim in (0.0, 2.0, 5.0, 10.0, 20.0, 1e9):
        p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0,
                                  template_max_span_s=lim,
                                  template_rest_ms=REST_MS,
                                  template_only_nonstraight=only)
        ch = solve_mod.solve(ons, p)
        ot = [o.t_ms for o in ons]
        lead = solve_mod.total_lead_ms(ch, 4)
        e = solve_mod.check_offset(ch, ot[0], 4, ot, m.length_ms + lead, lead)["max_err_ms"] * 1000
        lab = "不限" if lim > 1e8 else f"<{lim:g}s"
        print(f"   {lab:<10}{ch.meta.get('tpl_covered', 0):>8}"
              f"{ch.meta.get('tpl_rounds', 0):>6}"
              f"{ch.straight_frac*100:>7.1f}%{ch.n_twirl:>7}{ch.n_speed_events:>10}{e:>9.0f}")
    print()
