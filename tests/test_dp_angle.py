"""core/dp_angle.py 单测：角度双押插入（v0.2 项3 定稿）。

关键：插入双押层后「层 ↔ onset」不再 1:1，所以**不能**用 `verify.verify_file`
（它假设 floor j ↔ onset j−1）。正确口径是：

    ① 原格时刻不变（用 `dp_old2new` 重映射）
    ② 逐层「模型 ↔ 第三方 parser」双射（cum[j] ↔ times[j+1] − times[1]）

跑法:  python tests/test_dp_angle.py
"""
import json
import math
import os
import sys
import tempfile

_ROUTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTE)

from core import dp_angle as DA                        # noqa: E402
from core import rules as R                            # noqa: E402
from core import verify as V                           # noqa: E402
from core import writer as W                           # noqa: E402

FAIL = []
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _solve(sample="FallenEra.mid", n_targets=1, **kw):
    from core import midi as M, onsets as O, solve as S
    m = M.load(os.path.join(_ROOT, "samples", sample))
    ons = O.build_onsets(m.tracks[0].notes, O.OnsetParams(merge_ms=30.0))
    p = S.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0, **kw)
    return S.solve(ons, p), S, ons


def theta_rule():
    print("=" * 78)
    print("A. θ 按 **Δ 预算**反解：Δ = (θ/180)×(60000/bpm) ≤ 25ms")
    print("=" * 78)
    # 关掉预算（skew_max_ms=0）⇒ 退回老的固定两档，老基线可比对
    check(DA.choose_thin(120, 0) == 15.0, "关预算：cbpm=120 → 15°")
    check(DA.choose_thin(299.9, 0) == 15.0, "关预算：cbpm=299.9 → 15°")
    check(DA.choose_thin(300, 0) == 30.0, "关预算：cbpm=300 → 30°")
    check(DA.choose_thin(370, 0) == 30.0, "关预算：cbpm=370 → 30°")

    # ★ 默认（预算 25ms）：**所有 bpm** 下 Δ 都必须 ≤ 25ms
    worst = []
    for bpm in [5, 10, 15, 20, 30, 50, 75, 100, 125, 150, 180, 200, 240, 250,
                300, 360, 400, 500, 750, 1000, 1500, 2000]:
        th = DA.choose_thin(bpm)
        d = DA.skew_ms(th, bpm)
        if d > DA.SKEW_MAX_MS + 1e-9:
            worst.append((bpm, th, d))
    # bpm < 6.7 连阶梯最小档也压不住 —— 那种局部速度现实中不会出现
    # （`bpm_min=80` + 最大 `k=8` ⇒ 局部 bpm ≥ 10），只允许它们超
    real_bad = [x for x in worst if x[0] >= 10]
    check(not real_bad, f"所有现实 bpm 下 Δ ≤ {DA.SKEW_MAX_MS:g}ms（超的：{real_bad}）")
    check(DA.choose_thin(10) == 0.75, "bpm=10 → θ=0.75°（阶梯里挑最大可行档）")
    check(DA.choose_thin(1000) == 60.0, "bpm=1000 → θ=60°（触上限）")

    # ★ 棘轮：θ 必须随 bpm **单调不减**（旧口径在 300 处反向跳变，Δ 反而恶化）
    seq = [DA.choose_thin(b) for b in range(10, 1201, 5)]
    check(all(x <= y + 1e-9 for x, y in zip(seq, seq[1:])),
          "θ(bpm) 单调不减（不再有 300cbpm 处的反向跳变）")
    ds = [DA.skew_ms(DA.choose_thin(b), b) for b in range(10, 1201, 5)]
    check(max(ds) <= DA.SKEW_MAX_MS + 1e-9,
          f"扫描 10~1200bpm：Δ 最大 {max(ds):.2f}ms")

    # ★ θ 必须按**该格自己的 bpm** 算：慢速档 k 会把 Δ 放大 k 倍
    check(abs(DA.skew_ms(15.0, 60.0) - 83.3) < 0.1,
          "Δ 反比于本地 bpm：15° @60bpm = 83.3ms（所以不能用整谱 base_bpm）")


def fixed_table():
    print("=" * 78)
    print("A2. ★★ 固定双押角度表（用户 2026-10 定死：不按毫秒、不能自定义）")
    print("=" * 78)
    from core import midi as M, onsets as O, solve as S
    check(DA.FIXED_THETA_TABLE[0] == (840.0, 90.0), "表的第一档 = ≥840 ⇒ 90°")
    check([DA.fixed_theta(b) for b in (0.1, 100, 299.9, 300, 839.9, 840, 5000)]
          == [15.0, 15.0, 15.0, 30.0, 30.0, 90.0, 90.0],
          "窗口：<300 ⇒ 15° / 300~839 ⇒ 30° / ≥840 ⇒ 90°")
    check(DA.fixed_theta(1400, 1) == 90.0 and DA.fixed_theta(1400, 3) == 90.0,
          "≥840 且**连续双押 <4** ⇒ 90°")
    check(DA.fixed_theta(1400, 4) == 30.0 and DA.fixed_theta(1400, 9) == 30.0,
          "≥840 且**连续双押 ≥4** ⇒ 回 30°（用户口径的例外）")
    check(DA.fixed_theta(100, 9) == 15.0,
          "低 bpm 段连续再长也还是 15°（例外只作用于 90° 档）")
    check(DA.skew_ms(90.0, 840) > DA.SKEW_MAX_MS,
          "固定表的 90° @840 ⇒ Δ {:.2f}ms **超** 25ms 预算 ⇒ 固定表下预算不当判据"
          .format(DA.skew_ms(90.0, 840)))

    m = M.load(os.path.join(_ROOT, "samples", "FallenEra.mid"))
    ons = O.build_onsets(m.tracks[0].notes, O.OnsetParams(merge_ms=30.0))
    ch = S.solve(ons, S.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0))
    tc = S.times_from_chart(ch)
    tg = [tc[i + 1] for i in range(4, min(len(tc) - 2, 260), 7)]
    rf: dict = {}
    pf = DA.plan(ch, tg, report=rf, use_fixed=True)
    check(len(pf) > 0, f"固定表下仍插得进（{len(pf)} 处）")
    check(rf.get("theta_src") == "fixed", "plan(use_fixed=True) ⇒ theta_src = fixed")
    bad = [(k, v[0], DA.fixed_theta(ch.floors[k].bpm, 1))
           for k, v in pf.items()
           if v[0] != (DA.fixed_theta(ch.floors[k].bpm, 1),)]
    check(not bad, f"每个 θ 都等于**表值**（反例 {bad[:3]}）")
    check(set(rf.get("theta_counts", {})) <= {15.0, 30.0, 90.0},
          f"用到的 θ 只可能是 15/30/90：{rf.get('theta_counts')}")
    check(rf.get("skew_max_ms", 0) > 0,
          f"Δ 仍然被记成**情报**（≤{rf.get('skew_max_ms', 0):.2f}ms）")

    rb: dict = {}
    pb = DA.plan(ch, tg, report=rb, use_fixed=False)
    check(rb.get("theta_src") == "budget",
          "plan(use_fixed=False) ⇒ theta_src = budget（老口径**保留不删**）")
    check(len(pb) > 0, f"老口径也插得进（{len(pb)} 处）")


def timing_neutral():
    print("=" * 78)
    print("B. 零时长偏移 + 模型↔parser 双射")
    print("=" * 78)
    for sample in ("FallenEra.mid", "Automaton_Waltz.mid"):
        ch, S, ons = _solve(sample)
        t0 = S.times_from_chart(ch)
        n0 = len(ch.floors)
        tg = [t0[i] for i in range(3, n0 - 3, 6)]
        rep = {}
        n = DA.apply(ch, DA.plan(ch, tg, report=rep))
        t1 = S.times_from_chart(ch)
        o2n = ch.meta["dp_old2new"]

        off = max(abs(t1[o2n[i]] - t0[i]) for i in range(n0))
        check(off < 1e-6, f"{sample}: 原格时刻偏差 {off:.9f} ms（{n} 处双押）")
        check(abs(t1[-1] - t0[-1]) < 1e-6,
              f"{sample}: 总时长不变（差 {t1[-1]-t0[-1]:.9f} ms）")

        path = os.path.join(tempfile.mkdtemp(), "t.adofai")
        W.write(ch, path)
        cum, _a = V.parse_times(path)
        errs = [abs(float(cum[j]) - (t1[j + 1] - t1[1]))
                for j in range(min(len(cum), len(t1) - 1))]
        check(errs and max(errs) < 0.05,
              f"{sample}: 逐层 模型↔parser 最大误差 {max(errs)*1000:.1f} us"
              f"（{len(errs)} 层）")


def encoding():
    print("=" * 78)
    print("C. 编码自洽：反向=薄格带 Twirl；有效 travel 恒为 [θ, T−θ]")
    print("=" * 78)
    ch, S, ons = _solve("FallenEra.mid")
    t0 = S.times_from_chart(ch)
    n0 = len(ch.floors)
    tg = [t0[i] for i in range(3, n0 - 3, 6)]
    DA.apply(ch, DA.plan(ch, tg, mode=DA.MODE_REVERSE))
    enc = ch.meta["dp_enc"]
    bad = 0
    for (ix, _iy, ib) in ch.meta["dp_pairs"]:
        e = enc[ix]
        want_tw = (e == DA.MODE_REVERSE)
        if bool(ch.floors[ix].twirl) != want_tw:
            bad += 1
        if abs(ch.floors[ix].travel - ch.meta["dp_theta"][ix]) > 1e-9:
            bad += 1
        if abs(ch.floors[ib].travel + ch.floors[ix].travel
               - ch.meta["dp_base_travel"][ib]) > 1e-9:
            bad += 1
    check(bad == 0, f"薄格 Twirl / travel / 总和 自洽（违规 {bad}）")
    st = DA.stats(ch)
    check(st["pairs"] == st["thin"] == st["reverse"] + st["normal"],
          f"stats 自洽 {st}")
    check(st["bad_travel"] == 0, "薄格与剩余格 travel 都不低于下限")

    viol = [v for v in R.check_chart(ch) if v.get("level") != "info"]
    check(not viol, f"规则全过（{len(viol)} 条：{[v['code'] for v in viol][:3]}）")


def guards():
    print("=" * 78)
    print("D. 护栏分层（docs/31 §5.1「b」）：硬保护不拆、软保护可拆、SetSpeed 不拆")
    print("=" * 78)
    ch, S, ons = _solve("FallenEra.mid")
    t0 = S.times_from_chart(ch)
    n0 = len(ch.floors)
    # 目标覆盖全部格，看各类护栏是否触发
    rep = {}
    plan = DA.plan(ch, t0, report=rep)
    need = ("hits", "lost", "owned", "twirl_busy", "setspeed", "moved",
            "moved_ms_max", "soft_used", "dropped", "out_of_range", "dup",
            "theta_min", "theta_max", "skew_max_ms", "skew_avg_ms", "skew_over",
            "fallback_normal")
    check(all(k in rep for k in need), f"report 含全部账目 {sorted(rep)}")

    hard = {i for i, f in enumerate(ch.floors)
            if f.template or f.engine or f.snowflake}
    check(not (set(plan) & hard), "硬保护格（模板/引擎/雪花）一律没被拆")
    check(not any(i == 0 or i >= n0 - 1 for i in plan),
          "开局站位 / 尾层没被拆")
    # ★★ 2026-10 用户完整规则：「（当双押使用变速）调速必须**不和旋转重叠**，
    #   必须位于**双押的第一格**」⇒ 带 SetSpeed 的格**可以拆**，但**不许叠 Twirl**。
    ss_hit = {i for i in plan if DA._setspeed_here(ch.floors, i)}
    check(all(plan[i][1] == DA.MODE_NORMAL for i in ss_hit),
          f"★ 带 SetSpeed 的格被拆时一律**正常写法**（不叠 Twirl）：{len(ss_hit)} 处")
    check(not any(DA._setspeed_here(ch.floors, i) and ch.floors[i].twirl
                  for i in plan),
          "★ 只有「SetSpeed + 自带 Twirl」才让位（实测 0 处）")
    # 软保护（自然填充格）**应当**被用上 —— 这是 b 的关键
    soft = {i for i, f in enumerate(ch.floors) if f.natural}
    check(len(set(plan) & soft) > 0,
          f"软保护格被复用（{len(set(plan) & soft)}/{len(soft)} 格）")
    # 自带 Twirl 的格：允许拆，但 Twirl 必须被搬到薄格上（= 走反向写法）
    busy = {i for i, f in enumerate(ch.floors) if f.twirl}
    hit_busy = set(plan) & busy
    check(all(plan[i][1] == DA.MODE_REVERSE for i in hit_busy),
          f"自带 Twirl 的格被拆时一律改反向写法（{len(hit_busy)} 处）")
    check(rep["twirl_busy"] == len(hit_busy),
          f"twirl_busy 计数与实拆数一致（{rep['twirl_busy']}）")

    # 换位：snap_ms=0 时一步都不许挪
    ch2, _S2, _o2 = _solve("FallenEra.mid")
    rep2 = {}
    DA.plan(ch2, S.times_from_chart(ch2), report=rep2, snap_ms=0.0)
    check(rep2["moved"] == 0, "snap_ms=0 时 moved == 0（绝不挪时间）")


def no_silent_drop():
    print("=" * 78)
    print("F. ★ 满直线谱：角度双押不许静默丢（docs/31 §5.1 的验收）")
    print("=" * 78)
    ch, S, ons = _solve("FallenEra.mid")
    # 把整条谱**强制成满直线**：所有非首层的 travel 归 180、清掉图形标记。
    # 这样剩下的全是「自然填充格」= 以前 `owned` 全挡、双押恒为 0 的那种谱。
    for i, f in enumerate(ch.floors):
        if i == 0:
            continue
        f.travel = 180.0
        f.snowflake = False
        f.template = False
        f.engine = False
        f.natural = True
        f.twirl = False
        f.bpm = ch.base_bpm
        f.speed_k = 1.0
        f.pause_beats = 0.0
    n0 = len(ch.floors)
    t0 = S.times_from_chart(ch)
    tg = [t0[i] for i in range(3, n0 - 3, 5)]
    rep = {}
    p = DA.plan(ch, tg, report=rep)
    check(len(p) > 0, f"满直线谱上仍能插进双押：{len(p)}/{len(tg)}")
    check(rep["owned"] == 0, f"owned == 0（软保护不再当硬保护挡人）：{rep['owned']}")
    check(rep["lost"] == 0, f"lost == 0（一个都不丢）：{rep['lost']}")
    n = DA.apply(ch, p)
    t1 = S.times_from_chart(ch)
    o2n = ch.meta["dp_old2new"]
    off = max(abs(t1[o2n[i]] - t0[i]) for i in range(n0))
    check(off < 1e-6, f"插入后原格时刻零偏移（{off:.9f} ms，{n} 处双押）")
    viol = [v for v in R.check_chart(ch) if v.get("level") != "info"]
    check(not viol, f"规则全过（{[v['code'] for v in viol][:3]}）")


def reverse_vs_normal():
    print("=" * 78)
    print("E. 反向 vs 正常：有效 travel 相同；高密度反向重叠率低")
    print("=" * 78)
    ch, S, ons = _solve("FallenEra.mid")
    t0 = S.times_from_chart(ch)
    n0 = len(ch.floors)
    tg = [t0[i] for i in range(3, n0 - 3, 8)]

    outs = {}
    for mode in (DA.MODE_NORMAL, DA.MODE_REVERSE):
        c, _S, _o = _solve("FallenEra.mid")
        DA.apply(c, DA.plan(c, tg, mode=mode))
        tv = [round(f.travel, 3) for f in c.floors]
        outs[mode] = (tv, c)
    # 有效 travel 序列必须一致（时序口径相同）
    check(outs[DA.MODE_NORMAL][0] == outs[DA.MODE_REVERSE][0],
          "两种写法的有效 travel 序列完全一致")

    # 高密度合成对照：同一个缺口反复用
    from core.path import Path
    def dense(mode, T=180.0, th=30.0, gap=2, reps=20):
        tv = [180.0]
        fl = [False]
        for _ in range(reps):
            for _ in range(gap - 1):
                tv.append(180.0)
                fl.append(False)
            tv += [th, T - th]
            fl += [mode == DA.MODE_REVERSE, False]
        tv.append(180.0)
        fl.append(False)
        return Path.from_travels(tv, flips=fl)

    def ov(P, thr=1.75):
        pts = P.points
        c = 0
        for i in range(1, len(pts)):
            for j in range(0, i - 1):
                if math.hypot(pts[i][0]-pts[j][0], pts[i][1]-pts[j][1]) < thr:
                    c += 1
        return c

    cn = ov(dense(DA.MODE_NORMAL))
    cr = ov(dense(DA.MODE_REVERSE))
    check(cr < cn * 0.2,
          f"反向重叠对数 {cr} 远小于正常 {cn}（比值 {cr/max(1,cn):.3f}）")


def reserve_slots():
    print("=" * 78)
    print("G. ★ a：预留槽位（docs/31 §5.2）—— 钉死速度档 + 图形让路")
    print("=" * 78)
    from core import midi as M, onsets as O, solve as S
    m = M.load(os.path.join(_ROOT, "samples", "FallenEra.mid"))
    ons = O.build_onsets(m.tracks[0].notes, O.OnsetParams(merge_ms=30.0))

    def build(**kw):
        p = S.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0, **kw)
        return S.solve(ons, p), p

    base, _p0 = build()
    # 挑一批「不是模板/天然/引擎格」的 onset 来预留
    want = [i for i in range(4, len(ons) - 4, 11)]
    out, p1 = build(dp_reserve=tuple(want))
    rm = p1.dp_reserve_meta
    check(rm.get("n", 0) > 0, f"预留生效 {rm}")

    fl = out.floors
    resv = [i for i, f in enumerate(fl) if f.dp_reserved]
    check(len(resv) > 0, f"谱面上有 {len(resv)} 格被标记 dp_reserved")
    ss = {i for i in range(1, len(fl)) if abs(fl[i].bpm - fl[i - 1].bpm) > 1e-9}
    check(not (set(resv) & ss),
          f"预留格自己**不带 SetSpeed**（撞上 {len(set(resv) & ss)} 格）")

    # 时序：预留只换档、不改时长。允许 20µs —— 因为 `_is_straight` 会把
    # 「差 0.05° 以内」的 travel 吸附成正好 180°，那点吸附会带来亚毫秒级偏差。
    t0 = S.times_from_chart(base)
    t1 = S.times_from_chart(out)
    off = max(abs(t1[i] - t0[i]) for i in range(min(len(t0), len(t1))))
    check(off < 0.02, f"预留后逐层时刻仍贴合原 onset（最大差 {off*1000:.1f} µs）")

    # 预留槽位必须被角度双押**全部认领**（除预留自己放弃的以外）
    tg = [t1[i + 1] for i in want if i + 1 < len(t1)]
    rep = {}
    DA.apply(out, DA.plan(out, tg, report=rep))
    check(rep.get("reserved_used", 0) > 0,
          f"双押落在预留槽位上 {rep.get('reserved_used')} 处")
    check(rep.get("lost", 0) <= rm.get("lost", 0),
          f"非预留原因丢音为 0（lost={rep.get('lost')} ≤ 预留放弃 {rm.get('lost')}）")

    # 空 dp_reserve ⇒ 老路径逐字节不变
    out2, _p2 = build(dp_reserve=())
    h0 = hash(tuple((round(f.travel, 9), round(f.bpm, 9), bool(f.twirl))
                    for f in base.floors))
    h2 = hash(tuple((round(f.travel, 9), round(f.bpm, 9), bool(f.twirl))
                    for f in out2.floors))
    check(h0 == h2, "dp_reserve 为空时产物与不传完全一致（老路径不受影响）")


def _plain_chart(n=6, travel=180.0, bpm=1000.0, soft=True):
    """造一张干净谱：`n` 格等长，中间那些标记成**软保护**（可拆）。

    用来把「三押 = 替掉 1 个普通格」钉在**同一 bpm 窗口**上，不受真实谱的
    模板 / 雪花 / SetSpeed 干扰。
    """
    from core.solve import Chart, Floor
    fl = []
    for i in range(n):
        fl.append(Floor(travel=travel, bpm=bpm, twirl=False, turn=0.0,
                        heading=0.0, angle=0.0, natural=bool(soft and 0 < i < n - 1)))
    return Chart(base_bpm=bpm, floors=fl, meta={"travel_min": 15.0})


def three_press():
    print("=" * 78)
    print("H. ★★ 三押（docs/48）：押数 = 1 + 同时有音的 dp 轨数 ⇒ [θ₁, θ₂, 余量]")
    print("=" * 78)
    from core import solve as S

    # ---- H1 押数聚类（判据本身）-----------------------------------------
    marks = [(0.0, 0), (5.0, 1), (12.0, 0),          # 0ms: 轨 0+1 同时 ⇒ 押数 3
             (500.0, 1),                             # 单轨 ⇒ 押数 2（双押）
             (1000.0, 3), (1010.0, 3),               # ★ 同一轨连响两下 ⇒ **不是**三押
             (2000.0, 0), (2005.0, 1), (2010.0, 2)]  # 三条轨 ⇒ 押数 4（四押）
    grp = DA.group_marks(marks, 45.0)
    check([g[1] for g in grp] == [2, 1, 1, 3],
          f"分组：轨数 = {[g[1] for g in grp]}（期望 [2, 1, 1, 3]；★ 同轨两下只算 1）")
    pr, un = DA.press_of([0.0, 500.0, 1000.0, 2000.0], grp, 45.0)
    check(pr == [3, 2, 2, 4], f"押数 = {pr}（期望 [3, 2, 2, 4]）")
    check(un == 0, "全部分组都落到落点上")
    pr2, un2 = DA.press_of([0.0], grp, 45.0)
    check(un2 == 3, f"落不上的分组要记账（unmatched={un2}）")

    # ---- H2 角度表 ------------------------------------------------------
    check(DA.fixed_theta_list(1200, 1) == (90.0,) and DA.fixed_theta_list(1200, 2)
          == DA.FIXED_TRIPLE_HI,
          "cbpm 1200：双押 (90,)（≥840 档）/ 三押 **(30,60)**（三押表**不看** 90° 档）")
    check(DA.fixed_theta_list(200, 2) == DA.FIXED_TRIPLE_LOW,
          "低位：三押 (15,15)（第三块 150）")
    check(sum(DA.FIXED_TRIPLE_HI) == 90 and sum(DA.FIXED_TRIPLE_LOW) == 30,
          "★ 30+60 = 90（参考谱实测）· 15+15 = 30 ⇐ 都 < 180 ⇒ 闭合")
    check(90.0 * 2 == 180.0 and not (180.0 - 180.0 >= DA.MIN_TRAVEL),
          "★ `90·90` 不入表：第三块 = 180−180 = 0 ⇒ 不闭合")

    # ---- H3 三押几何：闭合 + 时序零偏移 + 按下的间隔 ---------------------
    ch = _plain_chart(n=6, bpm=1000.0)
    t0 = S.times_from_chart(ch)
    n0 = len(ch.floors)
    T = t0[2]
    rep: dict = {}
    plan = DA.plan(ch, [T], report=rep, presses=[3])
    check(len(plan) == 1 and len(next(iter(plan.values()))[0]) == 2,
          f"三押 ⇒ 2 块薄格（plan={plan}）")
    check(rep.get("triple_used") == 1 and rep.get("extra_press", 0) == 0,
          f"记账 triple_used==1：{rep.get('triple_used')}/{rep.get('extra_press')}")
    n_thin = DA.apply(ch, plan)
    check(n_thin == 2, f"插了 2 块薄格（不是 1 块）：{n_thin}")
    t1 = S.times_from_chart(ch)
    o2n = ch.meta["dp_old2new"]
    off = max(abs(t1[o2n[i]] - t0[i]) for i in range(n0))
    check(off < 1e-6, f"原格时刻零偏移（{off:.9f} ms）")
    check(abs(t1[-1] - t0[-1]) < 1e-6,
          f"总时长不变（差 {t1[-1]-t0[-1]:.9f} ms）")
    th = ch.meta["dp_theta"]
    check([th[k] for k in sorted(th)] == [30.0, 60.0],
          f"薄角序列 {[th[k] for k in sorted(th)]}（cbpm 1000 ⇒ 30/60）")
    tv = [round(f.travel, 6) for f in ch.floors]
    check(tv[2:5] == [30.0, 60.0, 90.0],
          f"★ 拆成 [30,60,90]（余量 90）⇒ {tv[2:5]}")
    # ★ 三块砖的**按下间隔** = 相邻块时长（cbpm 1000 ⇒ 0 / 10 / 30 ms）
    i1, i2, ir = 2, 3, 4
    _p = [t1[i2] - t1[i1], t1[ir] - t1[i1]]
    check([round(x, 4) for x in _p] == [10.0, 30.0],
          f"★ 第三押的按下时刻：0 / 10 / 30 ms（实测 {_p[0]:.3f} / {_p[1]:.3f}）"
          f"—— 每块自己的时长 {t1[i2]-t1[i1]:.1f} / {t1[ir]-t1[i2]:.1f} / "
          f"{t1[ir+1]-t1[ir]:.1f}")
    st = DA.stats(ch)
    check(st["triple"] == 1 and st["press_hist"] == {3: 1},
          f"stats 押数分布 {st['press_hist']}（triple={st['triple']}）")
    check(st["bad_travel"] == 0, "剩余格 travel 仍不低于下限（90 ≥ 15）")

    # ---- H4 记账：dp_pairs 每块薄格一条，剩余格下标相同 -------------------
    pr3 = [x for x in ch.meta["dp_pairs"]]
    check(len(pr3) == 2 and len({x[2] for x in pr3}) == 1,
          f"dp_pairs 两个薄格共用一个剩余格：{pr3}")
    check(pr3[0][0] == 2 and pr3[1][0] == 3, "薄格下标连着（[2,3] + 余量 4）")
    check(ch.meta["dp_old2new"][2 - 1] != ch.meta["dp_old2new"].get(2, -1),
          "原 onset 压在**第一块**薄格上（第三押不是 onset 层）")

    # ---- H5 模型 ↔ 第三方 parser 双射（两种编码都要） ---------------------
    for mode in (DA.MODE_NORMAL, DA.MODE_REVERSE):
        c = _plain_chart(n=6, bpm=1000.0)
        tt = S.times_from_chart(c)
        DA.apply(c, DA.plan(c, [tt[2], tt[4]], mode=mode, presses=[3, 3]))
        tf = S.times_from_chart(c)
        path = os.path.join(tempfile.mkdtemp(), "t3.adofai")
        W.write(c, path)
        cum, _a = V.parse_times(path)
        errs = [abs(float(cum[j]) - (tf[j + 1] - tf[1]))
                for j in range(min(len(cum), len(tf) - 1))]
        check(errs and max(errs) < 0.05,
              f"{mode}: 三押逐层 模型↔parser 最大误差 {max(errs)*1000:.1f} us"
              f"（{len(errs)} 层）")
        tvn = [round(f.travel, 6) for f in c.floors]
        if mode == DA.MODE_NORMAL:
            ref = tvn
        else:
            check(tvn == ref, "★ 反向写法的有效 travel 序列与正常**完全一致**")
    viol = [v for v in R.check_chart(c) if v.get("level") != "info"]
    check(not viol, f"规则全过（{[v['code'] for v in viol][:3]}）")

    # ---- H6 四押：**不做**但必须报（降级成双押） --------------------------
    ch4 = _plain_chart(n=6, bpm=1000.0)
    t4 = S.times_from_chart(ch4)
    r4: dict = {}
    p4 = DA.plan(ch4, [t4[2]], report=r4, presses=[4])
    check(len(p4) == 1 and len(next(iter(p4.values()))[0]) == 1,
          "四押押数 ⇒ **只拆 1 块**（降级双押）")
    check(r4.get("extra_press") == 1 and r4.get("triple_used") == 0,
          f"extra_press == 1（不许静默）：{r4.get('extra_press')}")

    # ---- H7 老口径 / 关掉三押 ⇒ 退回两格 + 记账 --------------------------
    chb = _plain_chart(n=6, bpm=1000.0)
    tb = S.times_from_chart(chb)
    rb: dict = {}
    pb = DA.plan(chb, [tb[2]], report=rb, presses=[3], use_fixed=False)
    check(len(next(iter(pb.values()))[0]) == 1,
          "use_fixed=False（老口径）⇒ 三押**不做**，退回两格")
    check(rb.get("three_legacy") == 1,
          f"three_legacy 记账 {rb.get('three_legacy')}")
    check(DA.apply(chb, pb) == 1, "老口径只插 1 块薄格")
    chc = _plain_chart(n=6, bpm=1000.0)
    tc = S.times_from_chart(chc)
    pc = DA.plan(chc, [tc[2]], presses=[3], three_press=False)
    check(len(next(iter(pc.values()))[0]) == 1,
          "three_press=False ⇒ 与今天逐字节相同（退回两格）")

    # ---- H7b ★★ 用户 2026-10：「为三押添加开关，可以不一定生成双押」-------
    #   三档：0 拆（默认）/ 1 不拆（按双押插一格）/ 2 跳过（连双押也不插）
    c1 = _plain_chart(n=6, bpm=1000.0)
    _t1 = S.times_from_chart(c1)
    r1: dict = {}
    _p1 = DA.plan(c1, [_t1[2]], report=r1, presses=[3], three_press=False)
    check(len(_p1) == 1 and len(next(iter(_p1.values()))[0]) == 1,
          "第 1 档（不拆）：押数 3 的那一组仍**插一格双押**")
    check(r1.get("three_off") == 1 and r1.get("three_legacy", 0) == 0,
          f"第 1 档单独记账 three_off（=1，且**不算**老口径）：{r1.get('three_off')}"
          f"/{r1.get('three_legacy')}")
    check(r1.get("triple_used", 0) == 0, "第 1 档不产生三押")
    c2 = _plain_chart(n=6, bpm=1000.0)
    _t2 = S.times_from_chart(c2)
    r2: dict = {}
    _p2 = DA.plan(c2, [_t2[2]], report=r2, presses=[3], skip_press=True)
    check(_p2 == {}, "★★ 第 2 档（跳过）：**连双押也不插**（plan 为空）")
    check(r2.get("press_skipped") == 1 and r2.get("hits") == 0,
          f"第 2 档记账 press_skipped（不许静默）：{r2.get('press_skipped')}")
    check(DA.apply(c2, _p2) == 0 and not c2.meta["dp_pairs"],
          "第 2 档 apply 不插任何薄格")
    # ★ 第 2 档只吃「押数 ≥3」：正常双押（押数 2）必须照旧插进去
    c3 = _plain_chart(n=6, bpm=1000.0)
    _t3 = S.times_from_chart(c3)
    r3: dict = {}
    _p3 = DA.plan(c3, [_t3[2], _t3[4]], report=r3, presses=[3, 2],
                  skip_press=True)
    check(len(_p3) == 1 and len(next(iter(_p3.values()))[0]) == 1,
          "第 2 档**只跳过押数 ≥3**的那一组，普通双押照插")
    check(r3.get("press_skipped") == 1 and r3.get("hits") == 1,
          f"第 2 档记账（跳过 1 / 落 1）：{r3.get('press_skipped')}/{r3.get('hits')}")
    # ★ 四押（押数 4）在第 2 档也要一起跳过（否则又变成「降级双押」）
    c4b = _plain_chart(n=6, bpm=1000.0)
    _t4b = S.times_from_chart(c4b)
    r4b: dict = {}
    _p4b = DA.plan(c4b, [_t4b[2]], report=r4b, presses=[4], skip_press=True)
    check(_p4b == {} and r4b.get("press_skipped") == 1
          and r4b.get("extra_press", 0) == 0,
          "★ 第 2 档把四押也一起跳过（不再走「降级成双押」那条）")

    # ---- H8 ★ 带 SetSpeed 的格：**照拆**，但调速必须落在双押第一格、不叠 Twirl -----
    from core.solve import Floor
    chs = _plain_chart(n=6, bpm=1000.0)
    chs.floors[2].bpm = 2000.0            # 第 2 格自己带 SetSpeed
    ts = S.times_from_chart(chs)
    rs: dict = {}
    ps = DA.plan(chs, [ts[2]], report=rs, presses=[3], snap_ms=0.0)
    check(2 in ps, f"★ 带 SetSpeed 的格**照拆**（不再白丢点；plan={sorted(ps)}）")
    check(ps[2][1] == DA.MODE_NORMAL, "★ 且用**正常写法**（调速不许与旋转重叠）")
    check(rs.get("setspeed_used") == 1 and rs.get("setspeed", 0) == 0,
          f"记账：setspeed_used={rs.get('setspeed_used')} / 让位 {rs.get('setspeed')}")
    DA.apply(chs, ps)
    ssfl = {i for (i, _b) in chs.set_speed_floors}
    _prs = chs.meta["dp_pairs"]
    _first, _rest = _prs[0][0], _prs[-1][2]
    check(_first in ssfl and _rest not in ssfl,
          f"★ 调速事件落在**第一块薄格**上（不在第二块 / 余量格）："
          f"SetSpeed {sorted(ssfl)} · 第一块 {_first} · 余量 {_rest}")
    _v = [v for v in R.check_chart(chs) if v.get("level") != "info"]
    check(not _v, f"规则全过（无「Twirl 与 SetSpeed 同格」）：{[v['code'] for v in _v][:3]}")

    # ---- H8b 只有「SetSpeed **且** 自带 Twirl」才让位（不静默）------------
    cht = _plain_chart(n=6, bpm=1000.0)
    cht.floors[2].bpm = 2000.0
    cht.floors[2].twirl = True
    tt = S.times_from_chart(cht)
    rt: dict = {}
    pt = DA.plan(cht, [tt[2]], report=rt, presses=[3], snap_ms=0.0)
    check(2 not in pt and rt.get("setspeed") == 1,
          f"★ 「调速 + 自带 Twirl」无处安放 ⇒ 让位并记账（setspeed={rt.get('setspeed')}）")

    # ---- H9 满直线谱：三押也不许静默丢 ------------------------------------
    chl = _plain_chart(n=13, bpm=1000.0)
    tl = S.times_from_chart(chl)
    rl: dict = {}
    pl = DA.plan(chl, [tl[i] for i in range(2, 11)], report=rl,
                 presses=[3] * 9)
    check(len(pl) == 9 and rl.get("lost") == 0,
          f"满直线谱 9 个三押全插进去（hits={len(pl)} lost={rl.get('lost')}）")
    check(rl.get("triple_used") == 9, f"triple_used == 9：{rl.get('triple_used')}")

    # ---- H10 ★ 钉住参考谱（fixture 复算） --------------------------------
    p = os.path.join(_ROOT, "tests", "fixtures", "adofai",
                     "three_press_interact.adofai")
    with open(p, encoding="utf-8-sig") as fp:
        d = json.load(fp)
    a = d["angleData"]
    head = [90.0 - x for x in a]
    tr = [0.0] + [((head[i] - head[i - 1] + 180.0) % 360.0)
                  for i in range(1, len(a))]
    bpm = float(d["settings"]["bpm"]) * 4.0     # SetSpeed ×4
    check(bpm == 1000.0, f"参考谱 cbpm = {bpm:g}（250 × 4）")
    check([round(x, 6) for x in tr[:6]] == [0.0, 30.0, 60.0, 90.0, 180.0, 180.0],
          f"★ 单元 = [30, 60, 90, 180, 180, 180]（实测 {tr[:6]}）")
    dt = [round(tr[i] / 180.0 * 60000.0 / bpm, 4) for i in range(6)]
    check(dt == [0.0, 10.0, 20.0, 30.0, 60.0, 60.0],
          f"★ 按下时刻 0 / 10 / 30 / 60 ms（实测 {dt}）")
    check(abs(sum(tr[1:4]) - 180.0) < 1e-9,
          "★ 30+60+90 = 180 = 正好 1 拍 ⇒ 替掉一个普通格")
    check(DA.fixed_theta_list(bpm, 2) == (tr[1], tr[2]),
          f"★ 表值 == 参考谱写法 {(tr[1], tr[2])}")
    check(not any(bool(f.get("twirl")) for f in d.get("actions", [])),
          "参考谱无 Twirl（是「正常写法」；反向写法是本站默认，见 docs/48 §6.3）")


def setspeed_first_tile():
    print("=" * 78)
    print("I. ★ 调速落在双押第一格（2026-10 用户完整规则）—— 把白丢的点捞回来")
    print("=" * 78)
    from core import midi as M, onsets as O, solve as S
    tot_used = 0
    for sample, main in (("FallenEra.mid", 0), ("Automaton_Waltz.mid", 0),
                         ("MemoryLocked.mid", 0)):
        m = M.load(os.path.join(_ROOT, "samples", sample))
        ons = O.build_onsets(m.tracks[main].notes, O.OnsetParams(merge_ms=30.0))
        ch = S.solve(ons, S.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0))
        t0 = S.times_from_chart(ch)
        n0 = len(ch.floors)
        n_ss = sum(1 for i in range(1, n0) if DA._setspeed_here(ch.floors, i))
        tw_ss = sum(1 for i in range(1, n0)
                    if DA._setspeed_here(ch.floors, i) and ch.floors[i].twirl)
        tg = [t0[i + 1] for i in range(2, min(len(t0) - 2, len(ons)))]
        rep: dict = {}
        DA.apply(ch, DA.plan(ch, tg, report=rep, use_fixed=True))
        t1 = S.times_from_chart(ch)
        o2n = ch.meta["dp_old2new"]
        off = max(abs(t1[o2n[i]] - t0[i]) for i in range(n0))
        viol = [v for v in R.check_chart(ch) if v.get("level") != "info"]
        print("  · %-20s SetSpeed 格 %2d（带 Twirl %d）⇒ **落双押第一格 %2d 处**、"
              "让位 %d、时长偏移 %.2e ms、违规 %d"
              % (sample, n_ss, tw_ss, rep.get("setspeed_used", 0),
                 rep.get("setspeed", 0), off, len(viol)))
        check(off < 1e-6, f"{sample}: 捞回来后原格时刻**零偏移**（{off:.2e} ms）")
        check(not viol, f"{sample}: 规则全过（{[v['code'] for v in viol][:3]}）")
        check(int(rep.get("setspeed", 0)) == 0 or tw_ss > 0,
              f"{sample}: 让位只可能发生在「调速+Twirl」上（带 Twirl {tw_ss} 处）")
        tot_used += int(rep.get("setspeed_used", 0))
    check(tot_used > 0,
          f"★ 三个样本合计「调速落双押第一格」**{tot_used} 处** —— 这些以前全被白丢")


def main():
    theta_rule()
    fixed_table()
    timing_neutral()
    encoding()
    guards()
    reverse_vs_normal()
    no_silent_drop()
    reserve_slots()
    three_press()
    setspeed_first_tile()
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
