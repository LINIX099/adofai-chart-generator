# -*- coding: utf-8 -*-
"""审计：**双押插入后，主音是否还压在原来的时刻上**（`docs/16` 的「偏移」口径）。

用法:  python tools/_dp_offset_audit.py

为什么要有这个工具
------------------
`core/dp_offset.py`（`docs/16` 的偏移回正公式）目前是**死代码**——
`docs/24` §8 的结论是「两条双押路径都天然零净偏移」。
用户 2026-10 怀疑「**双押偏移没有被按照公式修复回去**」，所以要拿出**数字**：
不是「净偏移为零」，而是**每一个主音**在插入双押前后差了多少毫秒。

口径
----
    err[i] = 插入后第 i 个 onset 的按键时刻 − 插入前第 i 个 onset 的按键时刻
    （用 `dp_old2new` 重映射，和导出的 `hit_times` 完全同一套）

判定：`dp_angle` 的拆法 Σtravel 守恒 ⇒ 应该恒为 0；
      `dp_midspin` 的 `[X, 999]` + 原格 −Σs —— `old2new` 指向的是**被吃掉 s 的原格**，
      它的 entry 比原来晚 Σs·mpd ⇒ 会有个**不累积但非零**的常数偏移。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import dp_angle as DA                               # noqa: E402
from core import dp_midspin as DM                             # noqa: E402
from core import midi as M, onsets as O, solve as S           # noqa: E402

CASES = ("FallenEra.mid", "Automaton_Waltz.mid", "MemoryLocked.mid")


def baseline(smp: str):
    m = M.load(os.path.join(ROOT, "samples", "_external", smp))
    ons = O.build_onsets(m.tracks[0].notes, O.OnsetParams(merge_ms=30.0))
    p = S.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0)
    ch = S.solve(ons, p)
    t = S.times_from_chart(ch)
    lead = 1 if ch.meta.get("n_lead") else 0
    n = len(ch.floors)
    return (m, ons, p, ch, [t[min(i + lead, n - 1)] for i in range(len(ons))])


def press_after(ch, n_on: int, lead: int) -> list:
    t = S.times_from_chart(ch)
    nf = len(ch.floors)
    o2n = ch.meta.get("dp_old2new") or {}
    out = []
    for i in range(n_on):
        j = min(i + lead, nf - 1)
        out.append(t[o2n.get(j, j)])
    return out


def audit(smp: str, mode: str) -> dict:
    m, ons, p, ch, base = baseline(smp)
    n0 = len(ch.floors)
    t0 = S.times_from_chart(ch)
    tg = [t0[i] for i in range(5, n0 - 5, 7)]
    rep = {}
    if mode == "angle":
        DA.apply(ch, DA.plan(ch, tg, report=rep))
    else:
        DM.apply(ch, DM.plan(ch, tg, report=rep))
    after = press_after(ch, len(ons), 1)
    err = [a - b for a, b in zip(after, base)]
    nz = [e for e in err if abs(e) > 1e-6]
    return {
        "smp": smp, "mode": mode, "pairs": len(tg),
        "max": max(err), "min": min(err),
        "n_nonzero": len(nz),
        "n_gt1ms": sum(1 for e in err if abs(e) > 1.0),
        "n_gt20ms": sum(1 for e in err if abs(e) > 20.0),
        "acc_end": err[-1],
    }


def midspin_fix_preview(smp: str) -> dict:
    """预览：把 `old2new` 指到折返格 X（而不是被吃掉 s 的原格）会怎样。"""
    m, ons, p, ch, base = baseline(smp)
    n0 = len(ch.floors)
    t0 = S.times_from_chart(ch)
    tg = [t0[i] for i in range(5, n0 - 5, 7)]
    DM.apply(ch, DM.plan(ch, tg))
    t = S.times_from_chart(ch)
    nf = len(ch.floors)
    o2n = ch.meta["dp_old2new"]
    o2x = dict(o2n)
    for (ix, _iy, ib) in ch.meta["dp_pairs"]:
        for k, v in o2n.items():
            if v == ib:
                o2x[k] = ix
                break
    err = [t[o2x.get(min(i + 1, nf - 1), min(i + 1, nf - 1))] - base[i]
           for i in range(len(ons))]
    return {"smp": smp, "max": max(abs(e) for e in err),
            "n_gt1ms": sum(1 for e in err if abs(e) > 1.0)}


def closure(smp: str) -> dict:
    """闭合体检：每个图形段（自然 / 引擎 / 模板）的路径是否回到起点朝向。"""
    m, ons, p, ch, base = baseline(smp)
    from core.path import Path
    fl = ch.floors
    path = Path.from_floors(fl, [bool(f.twirl) for f in fl])
    # 全局：终点 heading 与起点 heading 差（mod 360）
    h0 = path.headings[0] if path.headings else 0.0
    hN = path.headings[-1] if path.headings else 0.0
    segs = []
    spans = (getattr(p, "natural_spans", None) or [])
    for s0, L in spans:
        lo, hi = s0 + 1, s0 + 1 + L
        if hi <= len(fl) and lo >= 1:
            s = sum(fl[i].travel for i in range(lo, hi))
            segs.append((lo, L, s, (s - 180.0 * L) % 360.0))
    bad = [x for x in segs if abs(min(x[3], 360 - x[3])) > 1e-6]
    return {"smp": smp, "n_seg": len(segs), "n_bad": len(bad),
            "end_heading_err": abs(((hN - h0 + 180) % 360) - 180),
            "bad_examples": bad[:3]}


def main() -> int:
    print("=" * 100)
    print("A. 双押插入前后，**每个主音**的时刻差（ms）")
    print("=" * 100)
    print(f"{'曲目':<22}{'写法':<8}{'对数':>5}{'最大':>10}{'最小':>10}"
          f"{'非零个数':>9}{'>1ms':>7}{'>20ms':>7}{'累计末':>10}")
    rows = []
    for smp in CASES:
        if not os.path.exists(os.path.join(ROOT, "samples", "_external", smp)):
            continue
        for mode in ("angle", "midspin"):
            r = audit(smp, mode)
            rows.append(r)
            print(f"{r['smp']:<22}{r['mode']:<8}{r['pairs']:>5}"
                  f"{r['max']:>+10.3f}{r['min']:>+10.3f}{r['n_nonzero']:>9}"
                  f"{r['n_gt1ms']:>7}{r['n_gt20ms']:>7}{r['acc_end']:>+10.3f}")
    print()
    print("=" * 100)
    print("B. 预览：中旋把 `old2new` 指到折返格 X（而不是被吃掉 s 的原格）")
    print("=" * 100)
    for smp in CASES:
        if not os.path.exists(os.path.join(ROOT, "samples", "_external", smp)):
            continue
        f = midspin_fix_preview(smp)
        print(f"  {smp:<22} 最大 |误差| = {f['max']:.3f} ms   >1ms 的个数 = {f['n_gt1ms']}")
    print()
    print("=" * 100)
    print("C. 闭合体检：自然段 `Σtravel − 180n ≡ 0 (mod 360)`")
    print("=" * 100)
    tot_bad = 0
    for smp in CASES:
        if not os.path.exists(os.path.join(ROOT, "samples", "_external", smp)):
            continue
        c = closure(smp)
        tot_bad += c["n_bad"]
        print(f"  {smp:<22} 自然段 {c['n_seg']:>4} 个，不闭合 {c['n_bad']:>3} 个"
              f"   终点朝向误差 {c['end_heading_err']:.6f}°   {c['bad_examples']}")
    print("=" * 100)
    print("=> 完毕")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
