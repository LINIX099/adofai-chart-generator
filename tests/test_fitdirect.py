"""直拟合单测（`docs/43` 代价表 / `docs/44`）。

    python tests/test_fitdirect.py

验收线（用户口径「时序优先」）：

  1. **逐点精确**：`times_from_chart()` 反算的 entryTime 与输入毫秒**零误差**
     （这是直拟合存在的理由 —— 最优化那条路会漂 155ms）；
  2. 速度档只用 2 的幂、travel 落在合法区间；
  3. 长间隔拆层不改变总时长；
  4. 去噪后直线率高（格距是 2 的幂的比例 ≈ 直线率）。
"""
import os
import random
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import denoise as DN                            # noqa: E402
from core import fitdirect as FD                          # noqa: E402
from core import rules as rules_mod                       # noqa: E402
from core import solve as solve_mod                       # noqa: E402
from core import writer                                   # noqa: E402
from core.onsets import Onset                             # noqa: E402
from core.solve import SPEED_TIERS, SolveParams, times_from_chart      # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _onsets(ts):
    return [Onset(t_ms=float(t), velocity=100, pitch=60, n_merged=1, pitches=(60,),
                  tick=int(round(float(t) * 960 * 120.0 / 60000.0))) for t in ts]


def _timing_err(ch, ons, entry):
    tt = times_from_chart(ch)
    base = tt[entry[0]]
    return [abs((tt[entry[j]] - base) - (ons[j].t_ms - ons[0].t_ms))
            for j in range(len(ons))]


def A_exact():
    print("=" * 78)
    print("A. 逐点精确（直拟合的立身之本）")
    rnd = random.Random(11)
    ks = [0, 4, 8, 10, 14, 18, 22, 30, 34, 38, 46, 50, 54, 58, 62, 70]
    ts = [76.871 + k * 37.5 + rnd.uniform(-5, 5) for k in ks]
    g = DN.plan(ts)
    dr = DN.denoise(ts, g)
    ons = _onsets(dr["ts"])
    ch, rep = FD.build(ons, base_bpm=g.bpm)
    print("    " + rep.describe())
    check(rep.err_max_ms < 1e-6,
          f"★ 时序误差 max {rep.err_max_ms:.6f}ms（必须是 0）")
    check(rep.base_bpm == g.bpm, f"bpm 用去噪网格的（{rep.base_bpm:.4f}）")
    check(all(k in SPEED_TIERS for k in rep.k_used),
          f"速度档只用 2 的幂：{rep.k_used}")
    check(rep.travel_min >= 2.0 and rep.travel_max <= 358.0,
          f"travel 全部合法：{rep.travel_min:.2f}~{rep.travel_max:.2f}°")
    check(rep.n_onsets == len(ons) and rep.n_floors == len(ons) + 1,
          f"一砖一个音：{rep.n_onsets} onset → {rep.n_floors} 层（含开局站位）")
    check(ch.meta.get("fit_mode") == FD.MODE, "meta 里标了 fit_mode=direct")
    check(len(ch.meta.get("onset_floors") or []) == len(ons),
          "onset_floors 表齐（长间隔拆层后下游靠它定位）")
    check(rep.straight_frac > 0.5,
          f"去噪后直线率 {rep.straight_frac:.1%}（格距是 2 的幂）")


def B_fill():
    print("=" * 78)
    print("B. 长间隔：休止格（默认）与拆层（关掉休止时）都不改变总时长")
    # 前两个音很近、第三个隔了 40 拍（6000ms）⇒ 一个格子转不完 ⇒ 要么休止、要么拆层
    ts = [1000.0, 1037.5, 7037.5, 7100.0]
    ons = _onsets(ts)
    ch, rep = FD.build(ons, base_bpm=400.0)
    check(rep.n_pause >= 1,
          f"★ 默认用「1 直线格 + Pause」处理长休止（{rep.n_pause} 处，"
          f"填充层 {rep.n_fill}）")
    errs = _timing_err(ch, ons, ch.meta["onset_floors"])
    check(max(errs) < 1e-6, f"★ 休止格也逐点精确（max {max(errs):.6f}ms）")
    check(all(f.travel <= 340.0 + 1e-9 for f in ch.floors[1:-1]),
          "每层 travel 都在合法区间内")

    ch2, rep2 = FD.build(ons, base_bpm=400.0, use_pause=False, tier_mode="sticky")
    check(rep2.n_fill >= 1,
          f"关掉休止 + 粘住档位 ⇒ 退回拆层（{rep2.n_fill} 个填充层，休止 {rep2.n_pause}）")
    errs2 = _timing_err(ch2, ons, ch2.meta["onset_floors"])
    check(max(errs2) < 1e-6, f"拆层后仍然逐点精确（max {max(errs2):.6f}ms）")
    check(ch2.meta["onset_floors"][-1] == len(ch2.floors) - 1,
          "最后一个 onset 落在尾层")

    # DP 那条路**不需要**拆层：它可以用更大的档把 travel 压回合法区间
    _c3, rep3 = FD.build(ons, base_bpm=400.0, use_pause=False, tier_mode="dp")
    check(rep3.n_fill == 0 and rep3.n_floors == len(ons) + 1,
          f"DP 不拆层（{rep3.n_floors} 层 = {len(ons)} 点 + 尾层）")


def C_faithful():
    print("=" * 78)
    print("C. 不去噪也精确（只是几何不整齐）")
    ts = [1000.0, 1137.3, 1211.9, 1500.0, 1712.4, 2100.0, 2400.0, 2754.2]
    ons = _onsets(ts)
    ch, rep = FD.build(ons, base_bpm=400.0)
    errs = _timing_err(ch, ons, ch.meta["onset_floors"])
    check(max(errs) < 1e-6, f"未去噪也逐点精确（max {max(errs):.6f}ms）")
    print(f"    未去噪直线率 {rep.straight_frac:.1%}（比去噪后低，符合预期）")


def D_write():
    print("=" * 78)
    print("D. 真能写出 .adofai")
    ks = [0, 4, 8, 12, 16, 20, 24, 28]
    ts = [500.0 + k * 37.5 for k in ks]
    ons = _onsets(ts)
    ch, rep = FD.build(ons, base_bpm=400.0)
    d = tempfile.mkdtemp(prefix="adoc_fit_")
    p = writer.write(ch, os.path.join(d, "main.adofai"))
    check(os.path.exists(p), "写出 " + os.path.basename(p))
    import json
    lv = json.load(open(p, encoding="utf-8"))
    check(lv["settings"]["bpm"] == 400.0, f"settings.bpm = {lv['settings']['bpm']}")
    check(len(lv["angleData"]) == len(ch.floors),
          f"angleData {len(lv['angleData'])} 条 = 层数 {len(ch.floors)}")


def E_meta():
    print("=" * 78)
    print("E. meta 齐全（下游 payload / 状态栏要用）")
    ts = [1000.0 + k * 37.5 for k in range(12)]
    ons = _onsets(ts)
    ch, rep = FD.build(ons, base_bpm=400.0)
    need = ("n_onsets", "n_floors", "n_lead", "lead_ms", "duration_ms",
            "fit_mode", "fit", "straight_frac", "event_frac", "quant_err_ms")
    missing = [k for k in need if k not in ch.meta]
    check(not missing, f"meta 必需键齐（缺 {missing or '无'}）")
    check(ch.meta["n_lead"] == 1, "开局站位层算进去了（n_lead=1）")
    check(abs(ch.meta["duration_ms"] - (ts[-1] - ts[0])) < 1e-9,
          "duration 与输入一致")
    # Chart 的统计属性要能跑（rebuild 里直接用）
    ok = (ch.straight_frac >= 0.0, ch.n_twirl >= 0, ch.n_speed_events >= 0,
          len(ch.travel_hist(3)) > 0, len(ch.set_speed_floors) >= 0)
    check(all(ok), "straight_frac / n_twirl / n_speed_events / travel_hist 都能算")


def F_sticky():
    print("=" * 78)
    print("F. 速度档策略：粘住上一档 vs 一味求直")
    ks = [0, 4, 8, 12, 16, 20]
    ts = [1000.0 + k * 37.5 for k in ks]
    ons = _onsets(ts)
    _c1, r1 = FD.build(ons, base_bpm=400.0, keep=(20.0, 340.0), tier_mode="sticky")
    _c2, r2 = FD.build(ons, base_bpm=400.0, keep=(-1.0, -1.0), tier_mode="sticky")
    check(r1.n_switched <= r2.n_switched,
          f"粘住策略换档更少（{r1.n_switched} ≤ {r2.n_switched}）")
    check(r2.straight_frac >= r1.straight_frac,
          f"求直策略直线率不低（{r2.straight_frac:.1%} ≥ {r1.straight_frac:.1%}）")
    check(r1.err_max_ms < 1e-6 and r2.err_max_ms < 1e-6, "两种策略都逐点精确")


def H_params():
    """★ 用户参数真的起作用（`docs/46`）—— 这一组就是「奇怪轨道」那个问题的验收线。"""
    print("=" * 78)
    print("H. 参数接管：最小角度 / 直线优先 / 一档最少层数 / 选档策略 / 位置偏移")

    def travel_min_of(rep):
        return rep.travel_min

    # 造一段「有 16 分小格子 + 正常砖」的序列：37.5ms 的间隔会逼出小角度
    ks = [0, 1, 2, 4, 8, 9, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48]
    ts = [1000.0 + k * 37.5 for k in ks]
    ons = _onsets(ts)

    ch20, r20 = FD.build(ons, SolveParams(travel_min=20.0), base_bpm=400.0,
                         tier_mode="dp")
    ch90, r90 = FD.build(ons, SolveParams(travel_min=90.0), base_bpm=400.0,
                         tier_mode="dp")
    check(r20.travel_min_setting == 20.0 and r90.travel_min_setting == 90.0,
          f"报告里记下用的是哪个最小角度（{r20.travel_min_setting:g} / "
          f"{r90.travel_min_setting:g}）")
    check(travel_min_of(r90) >= 90.0 - 1e-9,
          f"★ 最小角度 90° ⇒ 不再出现小于 90° 的格子（实得最小 "
          f"{travel_min_of(r90):.2f}°）")
    check(r90.n_hairpin <= r20.n_hairpin,
          f"发卡弯不增：{r20.n_hairpin} → {r90.n_hairpin}")
    check(r20.err_max_ms < 1e-6 and r90.err_max_ms < 1e-6,
          "两种最小角度下都逐点精确")

    # 一档最少层数：调大 ⇒ 换档数不增（把碎档并给邻居）
    _c1, r1 = FD.build(ons, SolveParams(speed_min_run=1), base_bpm=400.0,
                       tier_mode="dp")
    _c8, r8 = FD.build(ons, SolveParams(speed_min_run=8), base_bpm=400.0,
                       tier_mode="dp")
    check(r8.n_switched <= r1.n_switched,
          f"一档≥8 层 ⇒ 换档更少（{r1.n_switched} → {r8.n_switched}）")
    check(r8.err_max_ms < 1e-6, "并档后时序仍然精确")

    # 选档策略：两条路都能出谱，但形状不同
    _cd, rd = FD.build(ons, SolveParams(), base_bpm=400.0, tier_mode="dp")
    _cs, rs = FD.build(ons, SolveParams(), base_bpm=400.0, tier_mode="sticky")
    check(rd.tier_mode == "dp" and rs.tier_mode == "sticky",
          "报告里标明走的是哪条选档策略")
    check(rd.err_max_ms < 1e-6 and rs.err_max_ms < 1e-6, "两条策略都逐点精确")

    # 轨道位置偏移（PositionTrack）：以前直拟合完全没接
    _c0, _r0 = FD.build(ons, SolveParams(use_position_track=False),
                        base_bpm=400.0)
    c1, _r1 = FD.build(ons, SolveParams(use_position_track=True,
                                        pos_track_min_beats=1.0),
                       base_bpm=400.0)
    check(not (_c0.meta.get("pos_tracks") or []), "关掉位置偏移 ⇒ meta 里是确定的空表")
    check("pos_tracks" in c1.meta, "开着位置偏移 ⇒ 直拟合也落 meta（与 solve 一致）")

    # 报告要把「用了哪些 / 不用哪些」说清楚（不许静默）
    txt = FD.report_text(r90)
    check("选档" in txt and "最小角度" in txt, "报告里写了选档依据与最小角度")
    check("不用" in txt and "模板" in txt,
          "报告里写明直拟合**不用**哪些参数（模板/三连音/雪花/量化）")


def G_real():
    print("=" * 78)
    print("G. 真数据（去噪 → 直拟合，端到端）")
    path = os.path.join(
        _HOME + r"\.dsh\attachments\v1\files\0a",
        "0aed72d9d890d040d5c6834bb8dc527618f8b0b8ec21d0bdaa1d1ef34f912149",
        "Flower_Dance-DJ_OKAWARI-1974307.txt")
    if not os.path.exists(path):
        print("  [SKIP] 找不到那份外部时间戳")
        return
    ts = sorted(float(l) for l in open(path, encoding="utf-8") if l.strip())
    g = DN.plan(ts)
    dr = DN.denoise(ts, g)
    ons = _onsets(dr["ts"])
    ch, rep = FD.build(ons, base_bpm=g.bpm)
    check(abs(rep.base_bpm - 400.0) < 1e-6, f"bpm 恰好 400（{rep.base_bpm:.6f}）")
    check(rep.err_max_ms < 1e-6, f"★ 逐点精确 max {rep.err_max_ms:.6f}ms")
    check(rep.n_setspeed < len(ons) * 0.2,
          f"SetSpeed {rep.n_setspeed} 条（< 20% 层数，不会满屏变速）")
    check(rep.straight_frac > 0.8, f"直线率 {rep.straight_frac:.1%} > 80%")


def I_ladder():
    """★★ 15° 阶梯（`docs/57`）：用户 2026-10「使用激进的拟合策略，最小角度 15°，
    只允许 15 30 45 60 75 90……往后」+「拟合容差把 ±0~100ms 的抖动修正至常规线」。

    这一组守四件事：
      1. 关着时**逐字节是老口径**（角度任意、时序误差 0）；
      2. 开着 + 容差够 ⇒ **非双押格的角度全都落在 15° 的整数倍上**；
      3. 每个音的挪动量 **≤ 容差**（不许为了对齐硬掰时间），且**不累积**；
      4. 容差太小时：**原样保留 + 计数 + 上屏**（不许静默、不许偷偷掰）。
    """
    print("=" * 78)
    print("I. ★ 15° 阶梯（激进拟合）+ 拟合容差")
    rnd = random.Random(11)
    ts = []
    t = 1000.0
    for i in range(60):
        ts.append(t + rnd.uniform(-25.0, 25.0))     # ±25ms 抖动
        t += (4 if i % 6 else 2) * 150.0 / 4
    ts.sort()
    ons = _onsets(ts)

    def bad15(ch):
        return [f.travel for f in ch.floors[1:-1]
                if abs(f.travel / 15.0 - round(f.travel / 15.0)) > 1e-6]

    p = SolveParams(travel_min=15.0, use_pause=False)

    ch0, r0 = FD.build(ons, p, base_bpm=400.0)
    check(not r0.ladder_on and r0.n_ladder_moved == 0,
          "关着「激进拟合」⇒ 报告里没有阶梯这一栏（老口径）")
    check(len(bad15(ch0)) > 20,
          f"★ 关着时角度**本来就五花八门**（{len(bad15(ch0))} 层不在 15° 整数倍上）"
          f"—— 这就是要解决的问题")
    check(r0.err_max_ms == 0.0, "关着时逐点精确（时序误差 0）")

    ch1, r1 = FD.build(ons, p, base_bpm=400.0, angle_ladder=True, angle_tol_ms=100.0)
    check(r1.ladder_on and r1.ladder_tol_ms == 100.0, "开着时报告里记下容差")
    check(bad15(ch1) == [],
          f"★★ 非双押格的角度**全部**在 15 30 45 60 75 90… 上（实得 {len(bad15(ch1))} 个例外）")
    check(r1.n_ladder_bad == 0, "★ 报告里也这么记（非阶梯格 0）")
    check(r1.n_ladder_moved > 20,
          f"★ 真挪了（修正 {r1.n_ladder_moved} 音，中位 {r1.ladder_move_median_ms:.2f}ms）")
    check(r1.ladder_move_max_ms <= 100.0 + 1e-9,
          f"★ 每个音的挪动量 ≤ 容差（max {r1.ladder_move_max_ms:.2f}ms）")
    check(abs(r1.ladder_move_sum_ms) < 25.0 * len(ts),
          f"★ 挪动**不累积**（合计 {r1.ladder_move_sum_ms:+.1f}ms，60 个音各挪 ≤25ms 也不可能滚雪球）")
    check(r1.err_max_ms == 0.0, "拟合本身仍然逐点精确（误差是「相对原谱」的挪动，另记）")

    # ★★ 独立复核（不信报告）：用 `times_from_chart` 反算**相对原输入**的偏差
    #   —— 它必须 ≤ 容差，而且要和报告里的挪动量对得上（不许是两套账）。
    _tt = times_from_chart(ch1)
    _e1 = ch1.meta["onset_floors"]
    _dev = max(abs((_tt[_e1[j]] - _tt[_e1[0]]) - (ons[j].t_ms - ons[0].t_ms))
               for j in range(len(ons)))
    check(_dev <= 100.0 + 1e-6,
          f"★★ 反算复核：相对**原输入**的最大偏差 {_dev:.3f}ms ≤ 容差 100ms")
    check(abs(_dev - r1.ladder_move_max_ms) < 0.5,
          f"★ 与报告里的挪动量对得上（{_dev:.3f} vs {r1.ladder_move_max_ms:.3f}）")

    # 容差不够 ⇒ 原样保留 + 计数（不许硬掰）
    ch2, r2 = FD.build(ons, p, base_bpm=400.0, angle_ladder=True, angle_tol_ms=5.0)
    check(r2.n_ladder_raw > 0 and r2.n_ladder_bad == len(bad15(ch2)),
          f"★ 容差 5ms ⇒ {r2.n_ladder_raw} 个音挪不动：**原样保留**且计数"
          f"（产物里非阶梯格 {r2.n_ladder_bad}）")
    check(r2.ladder_move_max_ms <= 5.0 + 1e-9,
          f"★ 挪动量仍然 ≤ 5ms（max {r2.ladder_move_max_ms:.2f}ms）—— 不硬掰")
    check(len(bad15(ch2)) > 0 and len(bad15(ch2)) < len(bad15(ch0)),
          f"修了一部分：{len(bad15(ch0))} → {len(bad15(ch2))} 层不在阶梯上")

    # 容差 0 ⇒ 一个点都不挪（= 保真；用户口径）
    ch3, r3 = FD.build(ons, p, base_bpm=400.0, angle_ladder=True, angle_tol_ms=0.0)
    check(r3.n_ladder_moved == 0 and r3.ladder_move_max_ms == 0.0,
          "★ 容差 0 ⇒ 一个点都不挪（保真）")
    check(len(ch3.floors) == len(ch0.floors), "层数不变")

    # 拆层也留在阶梯上（351° 这种长间隔会拆成两片，旧口径拆出 175.5°+175.5°）
    long_ts = [0.0, 150.0, 442.5]
    _p = SolveParams(travel_min=15.0, use_pause=False)
    chL0, _rL0 = FD.build(_onsets(long_ts), _p, base_bpm=400.0, tiers=(1.0,))
    chL, rL = FD.build(_onsets(long_ts), _p, base_bpm=400.0, tiers=(1.0,),
                       angle_ladder=True, angle_tol_ms=100.0)
    check(len(bad15(chL0)) == 2 and rL.n_fill >= 1,
          f"（对照）旧口径拆出 {[round(f.travel, 1) for f in chL0.floors[1:-1]]}"
          f"—— 有 {len(bad15(chL0))} 片不在阶梯上")
    check(bad15(chL) == [] and rL.n_fill >= 1,
          f"★ 长间隔拆层后每片仍在阶梯上（填充 {rL.n_fill} 层 "
          f"{[round(f.travel, 1) for f in chL.floors[1:-1]]}）")
    check(FD._split_units(23, 2) == [12, 11]
          and FD._split_units(46, 3) == [16, 15, 15]
          and sum(FD._split_units(46, 3)) == 46,
          "拆层按**整数个 15°** 分（23 单位 → 12+11；46 → 16+15+15）")

    # `snap_to_ladder` 是纯函数：直接喂「想要多少毫秒」也能验
    units = FD.ladder_unit_ms(150.0, 1.0)
    check(abs(units - 12.5) < 1e-9, f"一个 15° 单位 = 砖长·k/12（实得 {units}）")
    got = FD._ladder_fit(30.0, 12.5)
    check(got is not None and got[1] == 2 and abs(got[0] - 25.0) < 1e-9,
          f"30ms 吸到最近的 15° 格子 = 25ms（实得 {got}）")


def J_angle_window():
    """★ 用户口径（2026-10 第二版）：「**最小夹角不低于 30°、最大夹角不超过 270°**」。

    实现：`SolveParams.travel_max`（`0` = 老口径）+ 阶梯单位数区间
    `j ∈ [ceil(min/15), floor(max/15)]`。这一组验三件事：
      ① 选档候选里不再出现越界角（窗口有解时）；
      ② 阶梯吸附本身不会把角度**推出**窗口；
      ③ `rules` 会在真的越界时报 `travel_above_max`（不许静默）。
    """
    print("=" * 78)
    print("J. 角度窗口 [30°, 270°]（用户口径）")

    # ① 候选生成：每个 r 都给不出越界角（窗口比值 9 > 2 ⇒ 必含一个 2 的幂档）
    bad = []
    for r in (0.26, 0.5, 0.75, 1.0, 1.3, 1.5, 2.0, 3.0, 4.0):
        for t, _k in solve_mod._tier_options(r, solve_mod.SPEED_TIERS, 30.0, 270.0):
            if not (30.0 - 1e-9 <= t <= 270.0 + 1e-9):
                bad.append((r, round(t, 3)))
    check(not bad, f"① 候选角全部落在 [30,270]（越界 {bad[:4]}）")

    # ② 真拟合：一音一格 + 15° 阶梯 + 窗口
    ks = [0, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32, 40, 48]
    ts = [1000.0 + k * 37.5 for k in ks]
    ons = _onsets(ts)
    p = SolveParams(travel_min=30.0, travel_max=270.0)
    ch, rep = FD.build(ons, p, base_bpm=400.0, tier_mode="dp",
                       angle_ladder=True, angle_tol_ms=100.0)
    check(rep.travel_min >= 30.0 - 1e-9 and rep.travel_max <= 270.0 + 1e-9,
          f"② 打开窗口后实测 travel {rep.travel_min:.2f}~{rep.travel_max:.2f}°")
    check(rep.n_ladder_bad == 0,
          f"② 非双押格仍在 15° 阶梯上（非阶梯格 {rep.n_ladder_bad}）")
    _j = FD._ladder_j_range(30.0, 270.0)
    _got = FD._ladder_fit(150.0, 12.5, j_min=_j[0], j_max=_j[1])
    _over = FD._ladder_fit(1000.0, 12.5, j_min=_j[0], j_max=_j[1])
    check(_j == (2, 18) and _got is not None and _got[1] == 12 and _over is None,
          f"② 阶梯单位数窗口 j={_j}（2 → 30°，18 → 270°）；超出窗口 ⇒ 原样保留"
          f"（1000ms 落到 None = 不硬掰）")
    # 对照：**同一个 r**，不设上界时候选里**有** >270° 的档，设了就没有
    _no = [t for t, _k in solve_mod._tier_options(1.75, SPEED_TIERS, 30.0, 0.0)
           if t > 270.0 + 1e-9]
    _yes = [t for t, _k in solve_mod._tier_options(1.75, SPEED_TIERS, 30.0, 270.0)
            if t > 270.0 + 1e-9]
    check(_no and not _yes,
          f"② 对照 r=1.75：不设上界有 {_no}（>270），设 270 后一个都没有 —— 闸真在干活")

    # ③ rules 报越界（把一格改成 315°）
    ch0, _ = FD.build(ons, SolveParams(travel_min=30.0), base_bpm=400.0,
                      tier_mode="dp", angle_ladder=True, angle_tol_ms=100.0)
    ch0.meta["travel_max"] = 270.0
    ch0.floors[1].travel = 315.0
    codes = [v["code"] for v in rules_mod.check_chart(ch0)
             if v.get("level") != "info"]
    check("travel_above_max" in codes,
          f"③ 真的越界时报 travel_above_max（实得 {sorted(set(codes))}）")
    ch.meta["travel_max"] = 270.0
    codes2 = [v["code"] for v in rules_mod.check_chart(ch)
              if v.get("level") != "info"]
    check("travel_above_max" not in codes2 and "travel_below_min" not in codes2,
          f"③ 合规的谱面两条都不报（实得 {sorted(set(codes2))}）")


def main():
    A_exact()
    B_fill()
    C_faithful()
    D_write()
    E_meta()
    F_sticky()
    H_params()
    G_real()
    I_ladder()
    J_angle_window()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 直拟合全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
