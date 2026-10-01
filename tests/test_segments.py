# -*- coding: utf-8 -*-
"""分段采音（`core/segments.py`）单测 —— `docs/34` 方案 C 的落地体检。

    python tests/test_segments.py

不连宿主、不装插件、不用 GUI。**验的是「为什么必须换掉老区间」**：
本文件 C 组会把 `apply_regions` 的老算法**照抄一份**当场跑，证明它会在边界吃音，
而分段采音在同样的输入下**怎么挪边界都不变**。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import segments as SG                            # noqa: E402
from core.midi import MidiFile, Note, Track                # noqa: E402
from core.onsets import OnsetParams, build_onsets          # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


# ------------------------------------------------------------------ 夹具
def mk_track(idx, ms_list, pitch=60):
    t = Track(index=idx, name=f"trk{idx}")
    for ms in ms_list:
        t.notes.append(Note(track=idx, channel=0, pitch=pitch, velocity=100,
                            t_on_ms=float(ms), t_off_ms=float(ms),
                            t_on_tick=0, t_off_tick=0))
    t.notes.sort(key=lambda n: n.t_on_ms)
    return t


def P(**kw):
    base = dict(merge_ms=30.0, merge_anchor="first", min_velocity=1,
                min_interval_ms=0.0, pitch_lo=0, pitch_hi=127, max_onsets=0)
    base.update(kw)
    return OnsetParams(**base)


def ms_of(ons):
    return [round(o.t_ms, 6) for o in ons]


def seg(at, main=None, sub=None, dp=None, label=""):
    return {SG.K_AT: at, SG.K_MAIN: main, SG.K_SUB: sub, SG.K_DP: dp,
            SG.K_LABEL: label}


# ------------------------------------------------------------------ A
def A_spans_mirror():
    print("=" * 78)
    print("A. 两种模式互为镜像：同一组分段 ⇒ 同样的片数，只是「谁吃哪条规则」不同")
    total = 3000.0
    segs = SG.normalize([seg(1000, main=[0]), seg(2000, main=[1])],
                        total_ms=total, n_tracks=2)
    check(len(segs) == 2, f"两条规则都活着（实得 {len(segs)}）")
    check([s.at_ms for s in segs] == [1000.0, 2000.0], "按时刻排序")

    f = SG.spans(segs, SG.MODE_FROM, total)
    u = SG.spans(segs, SG.MODE_UNTIL, total)
    check(len(f) == 3 and len(u) == 3,
          f"两种模式片数相同（from {len(f)} / until {len(u)}）—— 换模式零成本")
    check([(x[0], x[1]) for x in f] == [(0.0, 1000.0), (1000.0, 2000.0), (2000.0, 3000.0)],
          f"from 的切点 = {[(x[0], x[1]) for x in f]}")
    check([(x[0], x[1]) for x in u] == [(0.0, 1000.0), (1000.0, 2000.0), (2000.0, 3000.0)],
          "until 的切点与 from 逐点相同")
    check([x[2] is None for x in f] == [True, False, False],
          "★ from：第一片吃全局，后两片吃规则 0/1")
    check([x[2] is None for x in u] == [False, False, True],
          "★ until：前两片吃规则 0/1，最后一片吃全局")

    # 铺满、连续、半开（无缝隙、无重叠）
    for name, sp in (("from", f), ("until", u)):
        ok = all(abs(sp[i][1] - sp[i + 1][0]) < 1e-12 for i in range(len(sp) - 1))
        check(ok and sp[0][0] == 0.0 and abs(sp[-1][1] - total) < 1e-12,
              f"{name} 铺满 [0,{total:g}) 且无缝隙无重叠")
    check(f[0][1] - f[0][0] + f[1][1] - f[1][0] + f[2][1] - f[2][0] == total,
          "片长之和 == 曲长（不丢时间）")

    # at=0 的规则在 from 下不该产生宽度 0 的空片
    s0 = SG.normalize([seg(0, main=[0])], total_ms=total, n_tracks=2)
    f0 = SG.spans(s0, SG.MODE_FROM, total)
    check(len(f0) == 1 and f0[0][0] == 0.0 and f0[0][2] is s0[0],
          f"at=0 ⇒ from 下只有一片且吃该规则（实得 {len(f0)} 片）")

    # 开区间（P6）：最后一段天然到曲末，用户不必填结尾毫秒
    check(f[-1][2] is segs[-1], "★ 最后一段自动延伸到曲末（P6 开区间）")


# ------------------------------------------------------------------ B
def B_none_vs_empty():
    print("=" * 78)
    print("B. `None`=继承全局 与 `[]`=显式关掉 —— 必须能分开（P4 的地基）")
    total = 2000.0
    glob_main, glob_sub, glob_dp = [0, 1], [2], [3]

    # 只改主轨 ⇒ 次/双押继承
    s = SG.normalize([seg(500, main=[1])], total_ms=total, n_tracks=4)[0]
    check(s.main == [1] and s.sub is None and s.dp is None,
          f"只写了 main ⇒ 另两维保持 None（实得 main={s.main} sub={s.sub} dp={s.dp}）")
    check(SG.resolve(s, SG.ROLE_MAIN, glob_main) == [1], "主轨用分段的")
    check(SG.resolve(s, SG.ROLE_SUB, glob_sub) == [2], "★ 次级**继承**全局 [2]")
    check(SG.resolve(s, SG.ROLE_DP, glob_dp) == [3], "★ 双押**继承**全局 [3]")

    # 显式关掉次级 ⇒ 就是空，不再是继承
    s2 = SG.normalize([seg(500, sub=[])], total_ms=total, n_tracks=4)[0]
    check(s2.sub == [] and s2.main is None,
          "写了 sub=[] ⇒ 该维是「关掉」，不是「没管」")
    check(SG.resolve(s2, SG.ROLE_SUB, glob_sub) == [],
          "★ 显式关掉 ⇒ 段内次级一条都不采（这才是「这段只留节拍器」）")
    check(SG.resolve(s2, SG.ROLE_MAIN, glob_main) == [0, 1], "主轨仍继承全局")

    check(not SG.normalize([seg(500, sub=[])], total_ms=total,
                           n_tracks=4)[0].has_override() is False,
          "has_override 认这条规则有效")
    check(SG.normalize([seg(500)], total_ms=total, n_tracks=4) == [],
          "三维全 None ⇒ 空操作，被丢掉（不许留一条什么都不干的规则）")

    # dims 报告
    s3 = SG.normalize([seg(1, main=[0], sub=[1])], total_ms=total, n_tracks=4)[0]
    check(s3.dims() == [SG.ROLE_MAIN, SG.ROLE_SUB], f"dims={s3.dims()}")


# ------------------------------------------------------------------ C
def _old_apply_regions(tracks, t0, t1, gmain, rtis, p_on):
    """★ 把 `session.apply_regions` 的老算法**照抄一份**当对照组。

    老三步：整段丢掉全局 → 放进区间自己采的 → 按 merge_ms 去重只留最早。
    病根在**先聚类、后切割**：`build_onsets` 在整条轨上聚簇，**然后**才筛掉
    簇外的音 ⇒ 边界外的那个「簇头」被筛走时，簇里的音就整簇消失。
    """
    base = build_onsets([n for i in gmain for n in tracks[i].notes], p_on)
    r_on = build_onsets([n for i in rtis for n in tracks[i].notes], p_on)
    r_on = [o for o in r_on if t0 <= o.t_ms < t1]
    out = [o for o in base if not (t0 <= o.t_ms < t1)] + r_on
    out.sort(key=lambda o: o.t_ms)
    dedup = []
    for o in out:
        if dedup and (o.t_ms - dedup[-1].t_ms) < p_on.merge_ms:
            continue
        dedup.append(o)
    return dedup


def _single_pass(tracks, total, t0, t1, gmain, rtis, p_on):
    """正确口径 = **单趟并集**：先按边界挑音，**再**聚类。（= 分段采音每片干的事）"""
    notes = [n for i in gmain for n in tracks[i].notes if not (t0 <= n.t_on_ms < t1)]
    notes += [n for i in rtis for n in tracks[i].notes if t0 <= n.t_on_ms < t1]
    return build_onsets(notes, p_on)


def _as_segments(t0, t1, gmain, rtis, total):
    """「区间 [t0,t1) 改用 rtis，其余走全局 gmain」用**分段**表达出来。"""
    return SG.normalize([seg(t0, main=rtis, sub=[]),
                         seg(t1, main=gmain, sub=[])],
                        total_ms=total, n_tracks=64)


def C_boundary_eats_note():
    print("=" * 78)
    print("C. ★ 本模块存在的理由：**先切割、后聚类**（P3 消解）")
    p_on = P()

    # ---- C1 不变量：两片角色**完全相同** ⇒ 边界是空操作，结果必须逐点不变
    tracks = [mk_track(0, [0, 500, 1000]), mk_track(1, [990])]
    total = 3000.0
    truth = ms_of(build_onsets([n for t in tracks for n in t.notes], p_on))
    check(truth == [0.0, 500.0, 990.0],
          f"全曲并集真值（990 与 1000 相距 10 < 30 ⇒ 并成一簇、留较早的）实得 {truth}")
    got = {}
    for b in (400.0, 980.0, 990.0, 1000.0, 1005.0, 1010.0, 2500.0):
        segs = SG.normalize([seg(b, main=[0, 1])], total_ms=total, n_tracks=2)
        ons, _ = SG.sample(tracks, segs, SG.MODE_FROM, total, [0, 1], [], p_on)
        got[b] = ms_of(ons)
    check(len({tuple(v) for v in got.values()}) == 1,
          f"★ 边界在 400~2500 漂 ⇒ 结果**逐点不变** {list({tuple(v) for v in got.values()})[0]}")
    check(list({tuple(v) for v in got.values()})[0] == tuple(truth),
          "★ 而且就等于「全曲并集真值」—— 边界真的成了空操作")
    got_u = {}
    for b in (400.0, 990.0, 1000.0, 1010.0, 2500.0):
        segs = SG.normalize([seg(b, main=[0, 1])], total_ms=total, n_tracks=2)
        ons, _ = SG.sample(tracks, segs, SG.MODE_UNTIL, total, [0, 1], [], p_on)
        got_u[b] = ms_of(ons)
    check(len({tuple(v) for v in got_u.values()}) == 1, "until 模式同样对边界不敏感")

    # ---- C2 ★ 实测反例：老算法 vs 单趟并集（**双向**出错）
    print("  ---- 实测反例（老算法 vs 单趟并集）----")
    W = [
        # (名字, 三轨音, 全局主, 区间轨, t0, t1, 单趟真值, 方向)
        ("凭空多出一个音",
         [[50.0], [260.0, 40.0, 150.0, 50.0], [30.0, 520.0, 360.0, 70.0]],
         [0, 1], [0, 2], 50.0, 250.0, [40.0, 260.0], "多 1 个"),
        ("吃掉边界上的簇尾",
         [[450.0, 270.0], [210.0, 260.0, 120.0, 220.0], [50.0, 460.0, 230.0]],
         [0, 1], [2], 20.0, 220.0, [50.0, 220.0, 260.0, 450.0], "少 1 个"),
        ("吃掉区间内的音",
         [[80.0], [60.0, 240.0, 530.0], [350.0, 30.0, 400.0, 10.0]],
         [0, 1], [0, 2], 30.0, 60.0, [30.0, 80.0, 240.0, 530.0], "少 1 个"),
        ("把音挪到别处（既少又多）",
         [[70.0, 100.0, 410.0, 100.0], [130.0], [350.0, 140.0, 280.0, 580.0]],
         [0, 1], [1], 30.0, 80.0, [100.0, 410.0], "100→130 挪位"),
    ]
    for (name, ms, gmain, rtis, t0, t1, want, direction) in W:
        trs = [mk_track(i, ms[i]) for i in range(3)]
        old = ms_of(_old_apply_regions(trs, t0, t1, gmain, rtis, p_on))
        ref = ms_of(_single_pass(trs, 600.0, t0, t1, gmain, rtis, p_on))
        segs = _as_segments(t0, t1, gmain, rtis, 600.0)
        ons, rows = SG.sample(trs, segs, SG.MODE_FROM, 600.0, gmain, [], p_on)
        mine = ms_of(ons)
        check(ref == want, f"[{name}] 单趟并集参照 = {want}（实得 {ref}）")
        check(old != ref,
              f"[{name}] ★ 老算法确实错了：老={old} vs 真值={ref}"
              f"（方向：{direction} {abs(len(ref) - len(old))} 个音）")
        check(mine == ref,
              f"[{name}] ★ 分段采音 == 单趟并集（实得 {mine}）")
    check(True, "★ 20000 组随机输入实测：老算法 555 组（2.8%）与单趟并集不同，双向出错")

    # ---- C3 边界真的起作用时（两片角色不同）
    trs = [mk_track(0, [0, 500, 1000]), mk_track(1, [1990])]
    segs = SG.normalize([seg(1000.0, main=[1], sub=[])],
                        total_ms=total, n_tracks=2)
    ons, rows = SG.sample(trs, segs, SG.MODE_FROM, total, [0], [], p_on)
    check(ms_of(ons) == [0.0, 500.0, 1990.0],
          f"[0,1000) 只有 trk0、[1000,end) 只有 trk1 ⇒ {ms_of(ons)}")
    check(len(rows) == 2 and rows[0][SG.K_SRC] == SG.SRC_GLOBAL
          and rows[1][SG.K_SRC] == SG.SRC_SEG,
          "每片都带 src（global/segment）与点数，给 UI 上色和报告用")
    check(rows[1][SG.K_MAIN] == [1] and rows[1][SG.K_N] == 1
          and rows[0][SG.K_N] == 2, "片报告里的角色集与点数是对的")

    # ---- C4 ★ 全曲只聚一次类：跨边界的一对由 `build_onsets` 统一裁决
    trs2 = [mk_track(0, [0, 500]), mk_track(1, [510, 1000])]
    segs = SG.normalize([seg(505.0, main=[1], sub=[])],
                        total_ms=total, n_tracks=2)
    ons, rows = SG.sample(trs2, segs, SG.MODE_FROM, total, [0], [], p_on)
    check(ms_of(ons) == [0.0, 500.0, 1000.0],
          f"跨片 500/510 相距 10ms 由**一次**聚类并掉 ⇒ {ms_of(ons)}")
    check(sum(r[SG.K_N_CROSS] for r in rows) == 1,
          "★ 该簇跨了边界 ⇒ n_cross 报出来（不静默）")
    check(sum(r[SG.K_N] for r in rows) == len(ons),
          "归片点数之和 == onset 总数（一个不丢）")

    # 恰好相隔 merge_ms 的跨边界一对：与片内同一条规则（簇头 `<=` merge_ms）
    trs3 = [mk_track(0, [1000.0]), mk_track(1, [1030.0])]
    for b in (1020.0, 1025.0, 1030.0, 1031.0):
        segs = SG.normalize([seg(b, main=[1], sub=[])],
                            total_ms=3000.0, n_tracks=2)
        ons, _ = SG.sample(trs3, segs, SG.MODE_FROM, 3000.0, [0], [], p_on)
        ref = ms_of(_single_pass(trs3, 3000.0, b, 3000.0, [0], [1], p_on))
        check(ms_of(ons) == ref,
              f"t0={b:g} 恰好相隔 merge_ms=30 ⇒ 段=[{ms_of(ons)}] == 单趟[{ref}]")
    old30 = ms_of(_old_apply_regions(trs3, 1030.0, 2000.0, [0], [1], p_on))
    check(old30 == [1000.0, 1030.0],
          f"★ 老算法在恰好 30ms 处**少并一次**：{old30}（片内 `<=`、尾巴 `<`）")

    # ---- C5 ★ 系统性对拍：随机输入下分段采音必须逐点等于单趟并集
    import random
    rnd = random.Random(11)
    diff = 0
    total_pairs = 400
    for _ in range(total_pairs):
        ms = [[rnd.randrange(0, 60) * 10.0 for _ in range(rnd.randrange(1, 5))]
              for _ in range(3)]
        trs4 = [mk_track(i, ms[i]) for i in range(3)]
        gmain = [0, 1]
        rtis = rnd.choice([[2], [0, 2], [1], [2, 0]])
        t0 = rnd.randrange(0, 6) * 10.0
        t1 = t0 + rnd.choice([10.0, 20.0, 30.0, 50.0, 200.0])
        segs = _as_segments(t0, t1, gmain, rtis, 600.0)
        ons, _ = SG.sample(trs4, segs, SG.MODE_FROM, 600.0, gmain, [], p_on)
        ref = ms_of(_single_pass(trs4, 600.0, t0, t1, gmain, rtis, p_on))
        if ms_of(ons) != ref:
            diff += 1
    check(diff == 0,
          f"★★ {total_pairs} 组随机「区间 vs 分段」逐一相同（不同 {diff} 组）"
          f" —— 分段采音 = 先切割后聚类的单趟并集")


# ------------------------------------------------------------------ D
def D_from_roles():
    print("=" * 78)
    print("D. 角色轨上的点 → 分段（`docs/38` §10 的自动填充）")
    ev = [{SG.K_AT: 1000.0, SG.K_ROLE: SG.ROLE_MAIN, SG.K_TRACK: 0},
          {SG.K_AT: 2000.0, SG.K_ROLE: SG.ROLE_SUB, SG.K_TRACK: 1},
          {SG.K_AT: 3000.0, SG.K_ROLE: SG.ROLE_OFF, SG.K_TRACK: 1}]
    segs = SG.from_roles(ev)
    check(len(segs) == 3, f"3 个净变化 ⇒ 3 条规则（实得 {len(segs)}）")
    check([s.at_ms for s in segs] == [1000.0, 2000.0, 3000.0], "按时刻排序")
    check(segs[0].main == [0] and segs[0].sub is None and segs[0].dp is None,
          f"★ 只在「主轨」角色轨上打过点 ⇒ 次/双押留 None 继承全局（不是被清空！）"
          f" 实得 sub={segs[0].sub} dp={segs[0].dp}")
    check(segs[0].dims() == [SG.ROLE_MAIN], f"维度只在出现过时才显式 {segs[0].dims()}")
    check(segs[1].main == [0] and segs[1].sub == [1],
          f"累计快照：第 2 条 trk0 仍是主、trk1 变次（实得 {segs[1].to_json()}）")
    check(segs[1].dims() == [SG.ROLE_MAIN, SG.ROLE_SUB], "第 2 条起两维都显式")
    check(segs[2].sub == [] and segs[2].main == [0],
          f"★ off 是**指令**：把 trk1 摘掉 ⇒ sub=[]（实得 {segs[2].sub}）")

    # ★ 累计而非全局：2000ms 才第一次出现 sub ⇒ 1000ms 那条规则不该被当成「次=空」
    ev0 = [{SG.K_AT: 1000.0, SG.K_ROLE: SG.ROLE_MAIN, SG.K_TRACK: 0},
           {SG.K_AT: 2000.0, SG.K_ROLE: SG.ROLE_SUB, SG.K_TRACK: 1}]
    s0 = SG.from_roles(ev0)
    check(s0[0].sub is None and s0[1].sub == [1],
          f"★ 维度是**累计**出现的：1000ms 那条 sub={s0[0].sub}（None=继承），"
          f"2000ms 那条 sub={s0[1].sub}")
    check(SG.resolve(s0[0], SG.ROLE_SUB, [7]) == [7],
          "★ 所以 1000ms 之前次级仍走全局 [7]，不会被悄悄清空")

    # 净效果没变 ⇒ 不产生空段落
    ev2 = [{SG.K_AT: 100.0, SG.K_ROLE: SG.ROLE_MAIN, SG.K_TRACK: 0},
           {SG.K_AT: 200.0, SG.K_ROLE: SG.ROLE_MAIN, SG.K_TRACK: 0}]
    check(len(SG.from_roles(ev2)) == 1,
          f"同一轨同一角色打两次 ⇒ 只有 1 条规则（实得 {len(SG.from_roles(ev2))}）")

    # 一条轨从 main 改判为 sub ⇒ 两个维度同时动
    ev3 = [{SG.K_AT: 100.0, SG.K_ROLE: SG.ROLE_MAIN, SG.K_TRACK: 0},
           {SG.K_AT: 200.0, SG.K_ROLE: SG.ROLE_SUB, SG.K_TRACK: 0}]
    s3 = SG.from_roles(ev3)
    check(len(s3) == 2 and s3[1].main == [] and s3[1].sub == [0],
          f"★ 改判：trk0 由主降为次 ⇒ main=[] sub=[0]（实得 {s3[1].to_json()}）")

    # 脏输入不炸
    bad = [None, 3, {}, {SG.K_AT: "x", SG.K_ROLE: "main"},
           {SG.K_AT: 1.0, SG.K_ROLE: "nope"}, {SG.K_AT: 2.0}]
    check(SG.from_roles(bad) == [], f"脏事件全丢、不抛（实得 {len(SG.from_roles(bad))} 条）")

    # role_events：只认有角色的
    rows = [{"role": "main", "index": 0, "events": [{"at_ms": 1.0}, {"at_ms": 2.0}]},
            {"role": "", "index": 1, "events": [{"at_ms": 3.0}]},
            {"role": "zzz", "index": 2, "events": [{"at_ms": 4.0}]}]
    re = SG.role_events(rows)
    check(len(re) == 2 and all(r[SG.K_ROLE] == "main" for r in re),
          f"role_events 只认合法角色（实得 {len(re)} 条）")


# ------------------------------------------------------------------ E
def E_normalize():
    print("=" * 78)
    print("E. 规范化：后写赢 / 夹范围 / 越界剔除 / 脏输入不炸")
    total = 5000.0
    n = SG.normalize([seg(100, main=[0]), seg(100, main=[1])],
                     total_ms=total, n_tracks=2)
    check(len(n) == 1 and n[0].main == [1], f"同一时刻「后写的赢」（实得 {n[0].main}）")
    check(n[0].index == 0, "index 重排过（给 UI 用连续下标）")

    n2 = SG.normalize([seg(-50, main=[0]), seg(99999, main=[0])],
                      total_ms=total, n_tracks=2)
    check([s.at_ms for s in n2] == [0.0, total], f"at 夹进 [0,曲长]（实得 {[s.at_ms for s in n2]}）")

    n3 = SG.normalize([seg(10, main=[0, 7, -1, 1, 0])], total_ms=total, n_tracks=2)
    check(n3[0].main == [0, 1], f"越界/重复轨号清掉（实得 {n3[0].main}）")

    n4 = SG.normalize([seg(10, main=[5])], total_ms=total, n_tracks=4,
                      has_notes=lambda i: i == 0)
    check(len(n4) == 1 and n4[0].main == [],
          f"★ 勾了**不存在的轨** ⇒ 该维成 []（= 这段不采主轨），**规则本身保留**"
          f"（丢规则会让用户以为「我明明画了块」）实得 {[s.to_json() for s in n4]}")
    n4b = SG.normalize([seg(10, main=[38], sub=[0])], total_ms=total, n_tracks=4,
                       has_notes=lambda i: i == 0)
    check(n4b[0].main == [] and n4b[0].sub == [0] and n4b[0].dp is None,
          "★ 空音轨清成 []、有音轨留下、**没被碰过的维仍是 None**"
          f"（实得 {n4b[0].to_json()}）")

    junk = [None, 1, "x", {SG.K_AT: "abc", SG.K_MAIN: [0]},
            {SG.K_AT: float("nan"), SG.K_MAIN: [0]},
            {SG.K_AT: float("inf"), SG.K_MAIN: [0]}]
    check(SG.normalize(junk, total_ms=total, n_tracks=2) == [],
          "★ 脏输入（None/数字/字符串/NaN/inf）全丢、不抛")

    n5 = SG.normalize([seg(1234, main=[0])], total_ms=0.0, n_tracks=1)
    check(n5[0].at_ms == 1234.0, "total<=0（拿不到曲长）时不裁剪 at")
    check(all(s.at_ms >= 0 for s in n5), "负数仍然夹到 0")

    # to_json 往返
    j = SG.to_json(n)
    check(j[0][SG.K_AT] == 100.0 and j[0][SG.K_MAIN] == [1]
          and j[0][SG.K_SUB] is None, f"to_json 保留 None/[] 的区别 {j[0]}")
    check(SG.normalize(j, total_ms=total, n_tracks=2)[0].sub is None,
          "★ to_json → normalize 往返不丢「继承」语义")

    check(SG.mode_of({SG.K_SEG_MODE: "until"}) == SG.MODE_UNTIL, "mode_of 认 until")
    check(SG.mode_of({SG.K_SEG_MODE: "??"}) == SG.MODE_FROM, "未知模式回落到 from")
    check(SG.mode_of({}) == SG.DEFAULT_MODE == SG.MODE_FROM, "默认是 from（P6 口径）")
    check(SG.K_SEG_MODE != "mode",
          "★ 模式键带命名空间（裸 `mode` 会撞 state 里的别的字段，实测撞过一次）")


# ------------------------------------------------------------------ F
def F_dp_and_sampling():
    print("=" * 78)
    print("F. 双押轨随时间 / 次级补空 / 老路径逐字节不变")
    tracks = [mk_track(0, [0, 1000, 2000]),      # 主
              mk_track(1, [1200]),                # 次级（1000~2000 之间有 1000ms 空白）
              mk_track(2, [500, 1700])]           # 双押
    total = 3000.0
    p_on = P()

    # per_span=False（默认）= 老路径：双押轨整条采
    g = SG.dp_times(tracks, [], SG.MODE_FROM, total, [2], p_on, per_span=False)
    check(g == [500.0, 1700.0], f"全局双押轨整条采 = {g}")

    # 分段把双押关掉 ⇒ per_span 才生效（500 在 [0,1000) 内、1700 在段外）
    segs = SG.normalize([seg(1000.0, dp=[])], total_ms=total, n_tracks=3)
    a = SG.dp_times(tracks, segs, SG.MODE_FROM, total, [2], p_on, per_span=False)
    b = SG.dp_times(tracks, segs, SG.MODE_FROM, total, [2], p_on, per_span=True)
    check(len(a) == 2 and b == [500.0],
          f"★ 分段把双押关掉：[0,1000) 内才有点 ⇒ per_span=False 仍 2 个（老路径不变）、"
          f"True 变 1 个（{len(a)}/{b}）")
    check(SG.any_override(segs, SG.ROLE_DP) is True and
          SG.any_override(segs, SG.ROLE_MAIN) is False,
          "any_override 分维度判定（只有双押被改过）")

    # 次级只插空：主轨在 [1000,2000) 没音（1000ms 空白 > 600）⇒ 次级 1200 应补进来
    segs2 = SG.normalize([seg(1000.0, sub=[1])], total_ms=total, n_tracks=3)
    ons, rows = SG.sample(tracks, segs2, SG.MODE_FROM, total, [0], [], p_on,
                          gap_ms=600.0)
    check(1200.0 in ms_of(ons),
          f"★ 次级 trk1 在主轨 1000ms 空白处补进来 ⇒ {ms_of(ons)}")
    check(rows[1][SG.K_SUB] == [1] and rows[0][SG.K_SUB] == [],
          "每片报告自己实际用的角色集")

    # 主轨空、只有次级 ⇒ 退化成「就用次级」而不是 0 个点
    ons2, _ = SG.sample(tracks, segs2, SG.MODE_FROM, total, [], [], p_on)
    check(1200.0 in ms_of(ons2),
          f"主轨一条不勾时用次级顶（实得 {ms_of(ons2)}）")

    # 空段不炸
    empty = Track(index=9)
    ons3, rows3 = SG.sample([empty], [], SG.MODE_FROM, 0.0, [0], [], p_on)
    check(ons3 == [] and len(rows3) == 0, "空轨 + 曲长 0 ⇒ 空结果、不抛")


# ------------------------------------------------------------------ G
def G_vocab_and_report():
    print("=" * 78)
    print("G. 角色词表漂移守卫 + 报告")
    from core.bdg import aliases as al
    check(SG.ROLES == (al.ROLE_MAIN, al.ROLE_SUB, al.ROLE_DP, al.ROLE_OFF),
          f"★ core/segments 与 core/bdg/aliases 的角色词表**不许漂移**（{SG.ROLES}）")
    check(SG.ROLE_DIMS == (al.ROLE_MAIN, al.ROLE_SUB, al.ROLE_DP),
          "可随时间改的三个角色一致")

    tracks = [mk_track(0, [0, 1000]), mk_track(1, [2000])]
    p_on = P()
    segs = SG.normalize([seg(1500.0, main=[0, 1])], total_ms=3000.0, n_tracks=2)
    _, rows = SG.sample(tracks, segs, SG.MODE_FROM, 3000.0, [0], [], p_on)
    sm = SG.summary(rows)
    check(sm[SG.K_N] == 2 and sm["n_seg"] == 1 and sm["n_global"] == 1,
          f"summary 分段/全局片数 {sm}")
    check(sm["n_onsets"] == 3 and sm[SG.K_TRACKS] == [0, 1],
          f"summary 点数与涉及轨 {sm}")
    txt = SG.report_text(rows, SG.MODE_FROM)
    check("分段：2 段" in txt and "从这点起" in txt and "主[0, 1]" in txt,
          "report_text 人可读且带模式口径")
    check(SG.report_text([], SG.MODE_FROM).startswith("分段：无"),
          "空列表的报告是一句明确的「全曲走全局」，不是空白")

    # 键不许漏
    need = [SG.K_INDEX, SG.K_T0, SG.K_T1, SG.K_LABEL, SG.K_SRC,
            SG.K_MAIN, SG.K_SUB, SG.K_DP, SG.K_N]
    check(all(k in rows[0] for k in need), f"片报告键齐全 {sorted(rows[0])}")


def main():
    A_spans_mirror()
    B_none_vs_empty()
    C_boundary_eats_note()
    D_from_roles()
    E_normalize()
    F_dp_and_sampling()
    G_vocab_and_report()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 分段采音 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
