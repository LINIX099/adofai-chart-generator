# -*- coding: utf-8 -*-
"""中旋双押插入的自检：拿真实 MIDI 求一张谱，再按外部音头插双押。

验证四件事：
  1. 总时长不变（零净偏移）
  2. 原有每一层的时刻都被保留
  3. 每个双押点：999 与下一格同一瞬间、折返格与下一格坐标重合
  4. 没被插到的层，x/y 一个都没动
用法：python tools/test_dp_midspin.py [midi] [--dp-ratio 0.37]
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dp_midspin as dp                      # noqa: E402
from core import midi as midi_mod                      # noqa: E402
from core import onsets as onsets_mod                  # noqa: E402
from core import solve as solve_mod                    # noqa: E402


def build_chart(path: str):
    m = midi_mod.load(path)
    cand = [t for t in m.tracks if t.notes and not t.is_drum_only()]
    cand = cand or [t for t in m.tracks if t.notes]
    prim = max(cand, key=lambda t: sum(n.pitch for n in t.notes) / len(t.notes))
    others = [t for t in cand if t is not prim]
    p_on = onsets_mod.OnsetParams()
    ons = onsets_mod.build_onsets_fill(prim, others, p_on, 2000.0)
    p_sv = solve_mod.SolveParams(
        straight_weight=solve_mod.STRAIGHT_PRESETS["平衡"],
        ppqn=m.ppqn, midi_bpm=m.bpm0,
    )
    return solve_mod.solve(ons, p_sv)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("midi", nargs="?",
                    default=os.path.join(os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))),
                        "samples", "FallenEra.mid"))
    ap.add_argument("--dp-ratio", type=float, default=0.37,
                    help="把双押目标放在每个底座音之后这个比例处（离网格）")
    ap.add_argument("--count", type=int, default=60)
    args = ap.parse_args(argv)

    ch = build_chart(args.midi)
    n0 = len(ch.floors)
    t0 = solve_mod.times_from_chart(ch)
    before = [(f.x, f.y, f.angle) for f in ch.floors]
    rep: dict = {}
    print(f"[底座] {os.path.basename(args.midi)}  层 {n0}  "
          f"总时长 {t0[-1]:.1f}ms  直线 {ch.straight_frac*100:.0f}%  "
          f"Twirl {ch.n_twirl}")

    # 另一条轨：在每层之后 --dp-ratio 处放一个「音头」（刻意离网格）
    tg = []
    for i in range(1, min(n0 - 1, args.count + 1)):
        tg.append(t0[i] + args.dp_ratio * (t0[i + 1] - t0[i]))
    plan = dp.plan(ch, tg, report=rep)
    n_pairs = dp.apply(ch, plan)
    t1 = solve_mod.times_from_chart(ch)
    st = dp.stats(ch)
    print(f"[插入] 计划 {len(tg)} 个 → 实际 {n_pairs} 对  "
          f"层 {n0} → {len(ch.floors)}   丢弃 {rep['dropped']}  "
          f"落进 Pause 被迫偏移 {rep['pause']}（最大 {rep['pause_ms']:.1f}ms）")

    bad = 0
    d = t1[-1] - t0[-1]
    print(f"\n1) 总时长   {t1[-1]:.4f} vs {t0[-1]:.4f}  差 {d:.6f}ms")
    bad += 0 if abs(d) < 0.5 else 1

    worst = max(min(abs(x - w) for x in t1) for w in t0)
    print(f"2) 原有各层时刻的最大还原误差 {worst:.6f}ms")
    bad += 0 if worst < 0.5 else 1

    print(f"3) 双押结构  999×{st['n999']}  同时按下 {st['ok_sim']}/{st['pairs']}  "
          f"坐标重合 {st['ok_pos']}/{st['pairs']}")
    bad += 0 if (st['pairs'] == n_pairs and st['ok_sim'] == n_pairs
                 and st['ok_pos'] == n_pairs and st['n999'] == n_pairs) else 1

    # 4) 没被插到的层：坐标与角度必须原样（用 old2new 精确对齐）
    o2n = ch.meta["dp_old2new"]
    moved = []
    for i in range(n0):
        if i in plan:
            continue
        f = ch.floors[o2n[i]]
        ox, oy, oa = before[i]
        if (abs(f.x - ox) > 1e-9 or abs(f.y - oy) > 1e-9
                or abs(f.angle - oa) > 1e-6):
            moved.append(i)
    print(f"4) 未插入层里坐标/角度被改动的: {len(moved)} 个（应为 0）"
          + (f"  例: {moved[:5]}" if moved else ""))
    bad += 0 if not moved else 1

    # 5) 双押落点精度（目标 → 实际）。落在 Pause 区间的会被压回上限，允许偏差
    got = sorted(t1[iy] for (_ix, iy, _ib) in ch.meta["dp_pairs"])
    err = [abs(a - b) for a, b in zip(got, sorted(tg)[:len(got)])]
    if err:
        srt = sorted(err)
        n_bad = sum(1 for e in err if e > 0.5)
        print(f"5) 双押落点误差  最大 {max(err):.4f}ms  中位 {srt[len(srt)//2]:.6f}ms  "
              f"偏差>0.5ms 的 {n_bad} 个（含 Pause 偏移 {rep['pause']} 个）")
        bad += 0 if n_bad <= rep["pause"] else 1
        if n_bad:
            worst = sorted(zip(err, got, sorted(tg)), reverse=True)[:3]
            for e, g, w in worst:
                print(f"      差 {e:8.3f}ms   落点 {g:11.3f}  目标 {w:11.3f}")

    print(f"\n结论: {'全部通过' if bad == 0 else f'{bad} 项问题'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
