"""对比「有模板 / 无模板」的生成结果，并列出**没被模板覆盖**的节奏型。

用法:  python tools/compare_templates.py
"""
from __future__ import annotations
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import midi, onsets as onsets_mod, solve as solve_mod, rhythm  # noqa: E402

NOTE_CN = {0.25: "十六", 1 / 3: "八分三连", 0.5: "八分", 2 / 3: "八分三连2",
           0.75: "附点八分", 1.0: "四分", 4 / 3: "四分三连", 1.5: "附点四分",
           2.0: "二分", 1 / 6: "十六三连", 3.0: "附点二分"}


def label(v: float) -> str:
    for k, s in NOTE_CN.items():
        if abs(v - k) < 1e-6:
            return s
    return f"{v:.3g}拍"


def run(path, track=-1, use_tpl=True):
    m = midi.load(path)
    cand = [t for t in m.tracks if t.notes and not t.is_drum_only()] or m.tracks
    ti = cand[0].index if track < 0 else track
    trk = m.tracks[ti]
    ons = onsets_mod.build_onsets(trk.notes, onsets_mod.OnsetParams(merge_ms=30.0))
    p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0, use_templates=use_tpl)
    ch = solve_mod.solve(ons, p)
    return ch, ons, m


def main():
    for fn in ("Automaton_Waltz.mid", "FallenEra.mid", "MemoryLocked.mid"):
        path = os.path.join(ROOT, "samples", "_external", fn)
        print("=" * 88)
        print(fn)
        for use in (False, True):
            ch, ons, m = run(path, use_tpl=use)
            n = max(1, len(ch.floors))
            sp = solve_mod.speed_profile(ch)
            tag = "有模板" if use else "无模板"
            print(f"  {tag}  层={len(ch.floors):>5} 直线={sp['straight_frac']*100:>5.1f}% "
                  f"Twirl={ch.n_twirl:>4}({ch.n_twirl/n*100:>4.1f}%) "
                  f"SetSpeed={ch.n_speed_events:>4} 速度={sp['min']:.2f}~{sp['max']:.2f}x "
                  f"模板={len(ch.meta.get('tpl_names',[]))}段/{ch.meta.get('tpl_covered',0)}格")
            if use:
                c = collections.Counter(ch.meta.get("tpl_names", []))
                if c:
                    print("         " + "  ".join(f"{k}×{v}" for k, v in c.most_common(6)))

        # 没被覆盖的节奏型
        ch, ons, m = run(path, use_tpl=True)
        beats, _ = solve_mod.beats_of(ons, m.ppqn, m.bpm0)
        qb = [rhythm.quantize(b) for b in beats] if beats else []
        scale = ch.base_bpm / (m.bpm0 or 120.0)
        rq = [b * scale for b in qb] if qb else []
        # 「直线」按**实际生成的 travel** 判，不按音值
        is_str = [solve_mod._is_straight(ch.floors[i + 1].travel)
                  for i in range(len(rq))]
        mask = [False] * len(rq)
        for s, L in ch.meta.get("tpl_spans", []):
            for k in range(s, min(len(mask), s + L)):
                mask[k] = True
        cnt = {k: collections.Counter() for k in (2, 3, 4)}
        for k in (2, 3, 4):
            for i in range(len(rq) - k + 1):
                if any(mask[i:i + k]) or any(is_str[i:i + k]):
                    continue
                cnt[k][tuple(round(v, 6) for v in rq[i:i + k])] += 1
        tot_un = sum(1 for i in range(len(rq)) if not mask[i] and not is_str[i])
        n_nonstr = sum(1 for x in is_str if not x)
        print(f"  非直线格 {n_nonstr} / {len(rq)}；其中模板覆盖 "
              f"{n_nonstr - tot_un} 格（{(n_nonstr - tot_un)/max(1,n_nonstr)*100:.0f}%），"
              f"未覆盖 {tot_un} 格。最常出现的没模板节奏：")
        shown = 0
        for k in (3, 4, 2):
            for g, c in cnt[k].most_common(4):
                if c < 2:
                    continue
                s = " · ".join(label(v) for v in g)
                print(f"     n={k}  {s:<40} ×{c}")
                shown += 1
                if shown >= 9:
                    break
            if shown >= 9:
                break
        print()


if __name__ == "__main__":
    main()
