# -*- coding: utf-8 -*-
"""原地惩罚（2026-10 用户：「算法会贪心地倾向于原地打转，建议增加原地惩罚，
让算法可以更倾向于**向规划的方向**铺设轨道而不是原地打转」）。

跑法:  python tests/test_inplace.py

分三块：
  [1] 评分器 `core/figures.score` —— 「原地转圈」必须**打不过**「同样省速度但往前走」
  [2] `choose` 的 dp 对照项 —— DP 自己更前进时，图形要让路（老路径）
  [3] 端到端三样本 —— 原地打转窗口占比下降、直线率不降、时序/规则全绿
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import figures as F                                   # noqa: E402
from core.midi import load                                      # noqa: E402
from core.onsets import build_onsets, OnsetParams               # noqa: E402
from core import solve as S, rules as R                          # noqa: E402

FAIL: list = []


def chk(name, ok, extra=""):
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (f"   {extra}" if extra else ""))
    if not ok:
        FAIL.append(name)


def _prog(ch):
    """原地打转窗口占比：每 4 格看一次净位移 / 4 格长度（1 = 一直往前）。"""
    pts = [(f.x, f.y) for f in ch.floors]
    n = len(pts)
    W = 4
    small = tiles = 0
    for i in range(1, n - W):
        d = math.hypot(pts[i + W][0] - pts[i][0], pts[i + W][1] - pts[i][1])
        tiles += 1
        if d / (W * 2.0) < 0.25:
            small += 1
    return 100.0 * small / max(1, tiles)


def _straight(ch):
    return 100.0 * sum(1 for f in ch.floors[1:-1]
                       if abs(f.travel - 180.0) < 1e-6) / max(1, len(ch.floors) - 2)


def scorer():
    print("=" * 78)
    print("[1] 评分器：原地转圈 vs 向前推进（同一个 SetSpeed 代价）")
    w = F.Walk(R2=2.0, allow_twirl=True)
    # 两段都是「零 SetSpeed 变化」的 4 格候选（k 全是 1）
    #   · 原地圈：travel 全 90 ⇒ 每格转 −90°，4 格正好绕回原点
    #   · 直线  ：travel 全 180 ⇒ 一路往上
    loop = F.Figure(0, 4, (90.0,) * 4, (1.0,) * 4, (False,) * 4, "nat")
    fwd = F.Figure(0, 4, (180.0,) * 4, (1.0,) * 4, (False,) * 4, "nat")
    s_loop = F.score(loop, w, prev_k=1.0, next_k=1.0, prefer_travel=120.0)
    s_fwd = F.score(fwd, w, prev_k=1.0, next_k=1.0, prefer_travel=120.0)
    chk("★ 新口径：一路往上**赢**原地绕圈", s_fwd < s_loop,
        f"直线 {s_fwd[0]} vs 原地 {s_loop[0]}")
    chk("★ 关掉原地惩罚（老口径）时两者在 SetSpeed 项上打平（旧行为被保住）",
        F.score(loop, w, prev_k=1.0, next_k=1.0, prefer_travel=120.0,
                inplace_waste=False)[0]
        == F.score(fwd, w, prev_k=1.0, next_k=1.0, prefer_travel=120.0,
                   inplace_waste=False)[0],
        "两边都是 changes=0")
    # 「每 3 格白转 ≈ 一个 SetSpeed」的标定：4 格原地 ⇒ waste = 1
    chk("处罚标定：4 格原地打转 = 1 个 SetSpeed 的代价（(1−0)×4÷3 四舍五入）",
        s_loop[0] == 1 and s_fwd[0] == 0, f"{s_loop[0]} / {s_fwd[0]}")
    # 一长段原地打转（12 格）必须输给「花 2 次 SetSpeed 一路直线」
    loop12 = F.Figure(0, 12, (90.0,) * 12, (1.0,) * 12, (False,) * 12, "nat")
    fwd12 = F.Figure(0, 12, (180.0,) * 12, (1.0,) * 12, (False,) * 12, "nat")
    s_l12 = F.score(loop12, w, prev_k=2.0, next_k=2.0, prefer_travel=120.0)
    # 直线那条要进出各换一次档（prev=2 → 1 → 2）⇒ changes = 2
    s_f12 = F.score(fwd12, w, prev_k=2.0, next_k=2.0, prefer_travel=120.0)
    chk("★ 12 格原地（0 次换档）**输给** 2 次换档的一路直线",
        s_l12 > s_f12, f"原地 {s_l12[0]} vs 直线 {s_f12[0]}")
    # 引擎候选（三连音）不吃这一项：形状没得挑，不许被罚到打不过自然段
    eng = F.Figure(0, 4, (120.0,) * 4, (1.0,) * 4, (False,) * 4, "eng")
    chk("引擎（三连音）不吃原地惩罚（结构性写法）",
        F.score(eng, w, prev_k=1.0, next_k=1.0, prefer_travel=120.0)[0] == 0,
        "waste=0")


def chooser():
    print("=" * 78)
    print("[2] choose / dp_candidate：DP 逐格铺法 vs 闭合图形（uniform-k）")
    p = S.SolveParams(use_triplet_engine=False)
    # 混排窗口：r = 1,2,1,2,…，而 DP 给的档是**逐格**的（1,2,1,2,…）
    #   ⇒ dp 候选：travel 全是 180（一路直线）
    #   ⇒ 闭合段只能 uniform-k：k=2 ⇒ travel 90/180 混排（而且这一段压根不闭合）
    rs = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    ks = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    dc = F.dp_candidate(0, len(rs), rs, ks, p, 1.0)
    chk("★ dp 候选 = DP 自己的逐格写法（这一窗全是直线 180）",
        all(abs(t - 180.0) < 1e-9 for t in dc.travels), str(dc.travels))
    w = F.Walk(R2=2.0, allow_twirl=True)
    fig = F.choose(0, rs, ks, p, w, blocked=set(), tail_k=1.0,
                   prefer_travel=120.0, prev_k=1.0)
    chk("★★ DP 逐格更前进 ⇒ 老路径 `choose` 返回 None（交回 DP，不画原地图形）",
        fig is None, f"fig={fig}")
    fig2 = F.choose(0, rs, ks, p, w, blocked=set(), tail_k=1.0,
                    prefer_travel=120.0, prev_k=1.0, dp_mode="figure")
    # ⚠ 返回的可能不是**最长**那一条（评分第一位是「SetSpeed 数」，窗口越长
    #   交替换档越多）—— 所以只验「它是 dp 候选、而且逐格都是 DP 的直线写法」。
    chk("★ 阶梯口径（dp_mode='figure'）⇒ 把 dp 候选当图形返回（照抄逐格 travel/k）",
        fig2 is not None and fig2.kind == "dp" and len(fig2.travels) >= 2
        and all(abs(t - 180.0) < 1e-9 for t in fig2.travels)
        and tuple(fig2.travels) == tuple(dc.travels[:len(fig2.travels)]),
        f"kind={getattr(fig2, 'kind', None)} n={getattr(fig2, 'n', 0)} "
        f"travels={getattr(fig2, 'travels', None)}")


def samples():
    print("=" * 78)
    print("[3] 端到端：三样本 —— 原地打转↓ · 直线率↑ · 时序/规则全绿")
    tot_old = tot_new = 0.0
    for name in ("FallenEra", "Automaton_Waltz", "MemoryLocked"):
        mf = load(os.path.join(ROOT, "samples", name + ".mid"))
        ons = build_onsets(mf.tracks[0].notes, OnsetParams(merge_ms=30.0))
        base = dict(ppqn=mf.ppqn, midi_bpm=mf.bpm0)
        ch_old = S.solve(ons, S.SolveParams(**base, inplace_waste=False))
        ch_new = S.solve(ons, S.SolveParams(**base))
        ip_old, ip_new = _prog(ch_old), _prog(ch_new)
        st_old, st_new = _straight(ch_old), _straight(ch_new)
        tot_old += ip_old
        tot_new += ip_new
        print(f"  · %-18s 原地 %5.1f%% → %5.1f%%　直线 %5.1f%% → %5.1f%%　"
              f"SetSpeed %d → %d"
              % (name, ip_old, ip_new, st_old, st_new,
                 len(ch_old.set_speed_floors), len(ch_new.set_speed_floors)))
        chk(f"{name}: 原地打转**下降**（{ip_old:.1f}% → {ip_new:.1f}%）",
            ip_new <= ip_old + 1e-9, f"{ip_new:.2f} ≤ {ip_old:.2f}")
        chk(f"{name}: 直线率**不下降**（{st_old:.1f}% → {st_new:.1f}%）",
            st_new >= st_old - 1e-9, f"{st_new:.2f} ≥ {st_old:.2f}")
        errs = [v for v in R.check_chart(ch_new) if v.get("level") != "info"]
        chk(f"{name}: 规则 0 违规", not errs, str(errs[:2]))
        t_new = S.times_from_chart(ch_new)
        t_old = S.times_from_chart(ch_old)
        # ⚠ 容差 0.05ms：`times_from_chart` 是 ~850 项浮点累加，换档会改变
        #   累加顺序 ⇒ 只有最后几位浮点噪声（实测最大 0.026ms），**不是时长漂移**。
        chk(f"{name}: 层数不变、总时长不漂（浮点噪声内）",
            len(ch_new.floors) == len(ch_old.floors)
            and abs(t_new[-1] - t_old[-1]) < 0.05,
            f"{len(ch_new.floors)}/{len(ch_old.floors)} 层 · "
            f"{t_new[-1]:.3f} vs {t_old[-1]:.3f}ms（差 {t_new[-1]-t_old[-1]:.4f}）")
    chk("★ 三样本合计：原地打转窗口占比**明显下降**",
        tot_new < tot_old - 5.0, f"{tot_old/3:.1f}% → {tot_new/3:.1f}%（均值）")


def main():
    scorer()
    chooser()
    samples()
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
