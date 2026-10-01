"""xk base 区间接线单测（定稿 = `docs/47` §3）。

    python tests/test_xkbase.py

只测**纯逻辑**（注入前后都在内存里，不碰 sidecar / UI）：

  A 区间规范化：排先后 / 重叠抛 / 空区间抛 / N 非法抛
  B 骨架砖：每砖一个、间隔**逐位等于砖长**、全部 `synth=True`
  C 注入：区间内真实 onset **被取代**、区间外**原样**、排序、计数
  D 多 N：不同区间不同 N 各成一条骨架；缺骨架 ⇒ 抛
  E 报告不静默：丢了多少 / 插了多少 / 区间外多少 / 八度话原文带上
  F `strip_synth` / `synth_flags`
  G 多押落点吸附到砖上（`dp_marks`）+ 没落上的数
  H 真数据：`Flower_Dance` 框一段 ⇒ 注入后 `Δt/砖长 ≡ 1.0`（**绝对对拍**是构造出来的）
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import bigline as BL                             # noqa: E402
from core import xkbase as XK                              # noqa: E402
from core.onsets import Onset                              # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

FAIL = []
REAL_TS = os.path.join(
    _HOME + r"\.dsh\attachments\v1\files\0a",
    "0aed72d9d890d040d5c6834bb8dc527618f8b0b8ec21d0bdaa1d1ef34f912149",
    "Flower_Dance-DJ_OKAWARI-1974307.txt")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def near(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except XK.XkError:
        return True
    except Exception:
        return False
    return False


def ons(ts, **kw):
    return [Onset(t_ms=float(t), velocity=100, pitch=60, **kw) for t in ts]


# ---------------------------------------------------------------- A 区间
def A_ranges():
    print("\nA. 区间规范化（显式 start/end，`docs/47` §1 第 12 条）")
    rs = XK.normalize_ranges([
        {"start_ms": 900.0, "end_ms": 300.0, "xk_base": 4},          # 倒了
        {"start_ms": 0.0, "end_ms": 100.0, "xk_base": 2},
    ])
    check(len(rs) == 2, "两段都收下")
    check(near(rs[0].start_ms, 0.0) and near(rs[1].start_ms, 300.0),
          "按 start 排序（还没查重叠）")
    r0 = XK.XkRange(900.0, 300.0, 4)
    check(near(r0.start_ms, 300.0) and near(r0.end_ms, 900.0),
          "起止倒了 ⇒ **自动排先后**（倒着填是常见手滑）")
    check(near(r0.span_ms, 600.0), "区间长度 = 600ms")
    check(raises(XK.XkRange, 500.0, 500.0, 4), "起止相同 ⇒ 抛（空区间没意义）")
    check(raises(XK.XkRange, 0.0, 100.0, 0), "区间内 N=0 ⇒ 抛（区间=采bpm，N 必须是 2/4/8）")
    check(raises(XK.XkRange, 0.0, 100.0, 3), "区间内 N=3 ⇒ 抛")
    check(raises(XK.normalize_ranges, [{"start_ms": 0.0, "end_ms": 100.0, "xk_base": 4},
                                       {"start_ms": 50.0, "end_ms": 200.0, "xk_base": 4}]),
          "**重叠 ⇒ 抛**（猜哪个赢都是错）")
    check(not raises(XK.normalize_ranges, [{"start_ms": 0.0, "end_ms": 100.0, "xk_base": 4},
                                           {"start_ms": 100.0, "end_ms": 200.0, "xk_base": 4}]),
          "首尾相接（不重叠）—— 这个**不该**抛")
    check(raises(XK.normalize_ranges, "nope"), "不是一个列表 ⇒ 抛")
    check(raises(XK.normalize_ranges, [{"start_ms": "x", "end_ms": 1.0, "xk_base": 4}]),
          "起止非数 ⇒ 抛")
    check(XK.normalize_ranges(None) == [], "None ⇒ 空列表（= 没框区间）")
    check(XK.normalize_ranges([]) == [], "空列表 ⇒ 空列表")
    d = XK.XkRange(100.0, 300.0, 8, tracks=(1, 2), label="副歌").to_dict()
    check(json.loads(json.dumps(d))["xk_base"] == 8, "to_dict 可 JSON 序列化（要给前端）")
    check(near(d["start_ms"], 100.0) and d["tracks"] == [1, 2], "to_dict 内容对")
    check(XK.XkRange(0.0, 300.0, 4).contains(150.0), "contains 判在区间内")
    check(not XK.XkRange(0.0, 300.0, 4).contains(301.0), "contains 判在区间外")


# ---------------------------------------------------------------- B 骨架砖
def B_synth():
    print("\nB. 骨架砖：每砖一个、间隔**逐位等于砖长**、`synth=True`")
    ln = BL.BigLine(100, 4, phase_ms=0.0)                 # 砖长 150ms
    r = XK.XkRange(0.0, 600.0, 4)
    got = XK.synth_onsets(ln, r)
    check(len(got) == 5, "0~600ms ⇒ 5 块砖（两端都算）")
    check(all(o.synth for o in got), "全部带 `synth=True`（下游靠它区分骨架与真音）")
    check([o.t_ms for o in got] == [0.0, 150.0, 300.0, 450.0, 600.0],
          "时刻 = φ + k·砖长：0/150/300/450/600")
    gaps = [round(got[i + 1].t_ms - got[i].t_ms, 9) for i in range(len(got) - 1)]
    check(set(gaps) == {150.0}, "相邻间隔**全是** 150.0ms（等间隔 ⇒ 绝对对拍）")
    check(all(o.velocity == XK.SYNTH_VELOCITY and o.pitch == XK.SYNTH_PITCH for o in got),
          "合成砖的力度/音高只是占位（别当音乐信息看）")
    check(raises(XK.synth_onsets, BL.BigLine.maybe(100, 0), r),
          "骨架是关的却要注入 ⇒ 抛")
    check(raises(XK.synth_onsets, ln, XK.XkRange(0.0, 600.0, 2)),
          "骨架 4k 而区间要 2k ⇒ 抛（每段 N 各自成一条骨架）")


# ---------------------------------------------------------------- C 注入
def C_inject():
    print("\nC. 注入：区间内被取代、区间外原样")
    ln4 = BL.BigLine(100, 4, phase_ms=0.0)
    real = ons([0.0, 100.0, 150.0, 420.0, 600.0, 700.0, 1000.0])
    new, meta = XK.inject(real, {4: ln4}, [{"start_ms": 300.0, "end_ms": 600.0, "xk_base": 4}])
    tin = [o.t_ms for o in new]
    check(tin == sorted(tin), "结果是按时间排序的")
    check(meta.n_dropped == 2, "区间 [300,600] 内被取代的真实 onset = 2（420 / 600）")
    check(meta.n_outside == 5, "区间外原样保留 5 个（0/100/150/700/1000）")
    check(meta.n_synth == 3, "注入 3 块砖（300/450/600）")
    check(len(new) == meta.n_outside + meta.n_synth, "总数 = 区间外 + 骨架砖")
    kept = [o.t_ms for o in new if not o.synth]
    check(kept == [0.0, 100.0, 150.0, 700.0, 1000.0], "留下的就是区间外那 5 个，顺序不变")
    check(any(o.synth and near(o.t_ms, 300.0) for o in new), "骨架吞掉 300ms 那一块")

    # 区间外「原路径」：真实 onset 一个不丢
    new2, meta2 = XK.inject(real, {4: ln4}, [])
    check(new2 == real and meta2.n_synth == 0,
          "**没有框区间 ⇒ 原样返回**（全部走原路径）")
    check("全部走原路径" in meta2.report_text(), "报告里写明走原路径")
    new3, meta3 = XK.inject(real, {}, [])
    check(meta3.ok is False and new3 == real, "没有骨架 ⇒ ok=False 且原样返回")

    # 两端都算：区间端点上的 onset 也算「被取代」
    new4, meta4 = XK.inject(ons([0.0, 300.0, 600.0]), {4: ln4},
                            [{"start_ms": 300.0, "end_ms": 600.0, "xk_base": 4}])
    check(meta4.n_dropped == 2, "端点 300 / 600 都算区间内 ⇒ 都被取代（两端都算）")


# ---------------------------------------------------------------- D 多 N
def D_multi_n():
    print("\nD. 多 N：不同区间不同 N 各成一条骨架")
    ln2 = BL.BigLine(100, 2, phase_ms=0.0)                 # 砖长 300ms
    ln4 = BL.BigLine(100, 4, phase_ms=0.0)                 # 砖长 150ms
    rs = [{"start_ms": 0.0, "end_ms": 600.0, "xk_base": 2},
          {"start_ms": 600.0, "end_ms": 1200.0, "xk_base": 4}]
    real = ons([0.0, 500.0, 700.0, 1100.0, 2000.0])
    new, meta = XK.inject(real, {2: ln2, 4: ln4}, rs)
    a = [o.t_ms for o in new if o.synth and o.t_ms <= 600.0]
    b = [o.t_ms for o in new if o.synth and o.t_ms > 600.0]
    check(a == [0.0, 300.0, 600.0], "2k 段：砖长 300ms ⇒ 0/300/600")
    check(b == [750.0, 900.0, 1050.0, 1200.0],
          "4k 段：砖长 150ms ⇒ 750/900/1050/1200（**交界处的 600 去了重**）")
    check([o.t_ms for o in new if o.synth] ==
          [0.0, 300.0, 600.0, 750.0, 900.0, 1050.0, 1200.0],
          "合并后骨架是一条**不重复、不跳号**的砖列")
    check(meta.n_dup == 1, "交界处重合的 1 块砖**报了数**（不许静默）")
    check("重合" in meta.report_text(), "报告里写明「边界重合已去重」")
    check(len(meta.rows) == 2 and [r["n"] for r in meta.rows] == [2, 4],
          "报告里两段各自的 N 都在")
    check([r["dropped"] for r in meta.rows] == [2, 2],
          "两段各自丢掉的真实 onset 数（2 / 2，**首尾相接不重复计**）")
    check(near(meta.rows[0]["period_ms"], 300.0) and near(meta.rows[1]["period_ms"], 150.0),
          "报告里两段的砖长不一样")
    check(raises(XK.inject, real, {2: ln2}, rs),
          "第二段要 4k 但没有 4k 骨架 ⇒ 抛（不静默降级）")


# ---------------------------------------------------------------- E 报告
def E_report():
    print("\nE. 报告不静默")
    ln = BL.BigLine(100, 4, phase_ms=0.0)
    real = ons([0.0, 100.0, 200.0, 400.0, 900.0])
    _, meta = XK.inject(real, {4: ln}, [{"start_ms": 100.0, "end_ms": 500.0, "xk_base": 4}],
                        octave="⚠ 八度嫌疑：测试")
    txt = meta.report_text()
    check("注入骨架" in txt and "块砖" in txt, "报告里有砖数")
    check("被取代" in txt, "报告里写明区间内被取代的 onset 数")
    check("原样保留" in txt and "原路径" in txt, "报告里写明区间外走原路径")
    check("⚠ 八度嫌疑：测试" in txt, "八度校验的话**原文带上去**（不吞）")
    check("格子" in txt and "块砖" in txt, "每段那行里有格子号范围")
    check(isinstance(json.dumps(meta.to_dict()), str), "to_dict 可 JSON 序列化")
    c = XK.XkRange(0.0, 600.0, 4)
    check("4k" in c.describe(ln) and "150" not in c.describe(ln),
          "describe 给的是「4k + 格子范围」（不带砖长数值）")
    check("格子 1~5" in c.describe(ln), "describe 用的是 **1 起算的物量号**")
    m0 = XK.XkMeta(ok=False, why="xk base 关")
    check("全部走原路径" in m0.report_text(), "关掉时的报告是一句人话")


# ---------------------------------------------------------------- F 辅助
def F_helpers():
    print("\nF. strip_synth / synth_flags")
    ln = BL.BigLine(100, 4, phase_ms=0.0)
    real = ons([0.0, 250.0, 500.0])
    new, _ = XK.inject(real, {4: ln}, [{"start_ms": 0.0, "end_ms": 300.0, "xk_base": 4}])
    fl = XK.synth_flags(new)
    check(sum(fl) == 3 and len(fl) == len(new), "synth_flags 与 onsets 等长且计数对得上")
    check([o.t_ms for o in XK.strip_synth(new)] == [500.0],
          "strip_synth 只留真实 onset（0/250 在区间内、已被取代）")
    check(XK.strip_synth(real) == real, "本来就没有骨架砖时原样返回")


# ---------------------------------------------------------------- G 多押
def G_dp():
    print("\nG. 多押落点吸附到**砖**上（`dp_marks`）")
    ln = BL.BigLine(100, 4, phase_ms=0.0)
    bones = XK.synth_onsets(ln, XK.XkRange(0.0, 900.0, 4))     # 0/150/…/900
    hit, miss = XK.dp_marks(bones, [152.0, 445.0, 902.0], tol_ms=45.0)
    check(hit == [1, 3, 6], "多押时刻 152/445/902 ⇒ 吸附到砖 1/3/6（150/450/900）")
    check(miss == 0, "全部落上了 ⇒ miss = 0")
    hit2, miss2 = XK.dp_marks(bones, [152.0, 5000.0], tol_ms=45.0)
    check(hit2 == [1] and miss2 == 1, "落不上的那一拍**报数**（miss = 1，不静默）")
    hit3, _ = XK.dp_marks(bones, [160.0, 165.0], tol_ms=45.0)
    check(len(hit3) == 1, "同一块砖上多个多押标记 ⇒ 只算一次（砖是唯一的）")
    hit4, _ = XK.dp_marks(bones, [0.0], tol_ms=45.0)
    check(hit4 == [0], "第一块砖也能命中")


# ---------------------------------------------------------------- H 真数据
def H_real():
    print("\nH. 真数据：框一段 ⇒ 注入后 `Δt/砖长 ≡ 1.0`（绝对对拍是构造出来的）")
    if not os.path.isfile(REAL_TS):
        print("  [skip] 没有真数据文件")
        return
    from core import ts_source as TS
    from core import denoise as DN
    ts, _ = TS.read_ts(REAL_TS)
    g = DN.plan(ts)
    tbpm, n = 100, 4
    ln = BL.BigLine(tbpm, n, phase_ms=g.phase_ms)
    check(near(ln.period_ms, g.period_ms, 1e-6), "骨架砖长与去噪解出的逐位相同")
    check(BL.octave_note(tbpm, n, g.period_ms) == "", "八度校验通过（没有 ×2 / ÷2 的嫌疑）")
    real = ons(ts)
    t0, t1 = 60_000.0, 90_000.0
    new, meta = XK.inject(real, {n: ln}, [{"start_ms": t0, "end_ms": t1, "xk_base": n}])
    want = len(ln.tiles_within(t0, t1))
    check(meta.n_synth == want, "区间 [60000,90000] ⇒ 注入 {} 块砖（= 落在区间里的格子数）".format(want))
    check(meta.rows[0]["tiles"] == want,
          "**报告里的砖数与实际注入的一致**（{}）—— 报少了/报多了都是静默".format(want))
    check(meta.n_outside == len(real) - meta.n_dropped, "区间外 = 总数 − 被取代（账对得上）")
    check(meta.n_dropped > 0, "这段里确实有 {} 个真实 onset 被取代".format(meta.n_dropped))
    inside = [o.t_ms for o in new if o.synth]
    gaps = [round(inside[i + 1] - inside[i], 9) for i in range(len(inside) - 1)]
    check(set(gaps) == {round(ln.period_ms, 9)},
          "{} 块砖的间隔**全是** {:.3f}ms ⇒ r = Δt/砖长 ≡ 1.0".format(len(inside), ln.period_ms))
    check(sorted(inside) == inside and len(set(inside)) == len(inside),
          "砖号连续且不重复（等间隔、无跳号、无叠砖）")
    check(ln.tile_of(inside[0]) == ln.tiles_within(t0, t1)[0], "第一块砖就是区间里第一块格子")
    print("  ---- 报告 ----")
    for row in meta.report_text().splitlines():
        print("  " + row)


def main():
    A_ranges()
    B_synth()
    C_inject()
    D_multi_n()
    E_report()
    F_helpers()
    G_dp()
    H_real()
    print("\n" + "=" * 78)
    if FAIL:
        print("✗ {} 项失败:".format(len(FAIL)))
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ xk base 区间接线全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
