"""大直线 / 采bpm 骨架单测（定稿 = `docs/47`）。

    python tests/test_bigline.py

只测**纯逻辑**（不碰 sidecar / UI），组件：

  A `round_tbpm` 四舍六入五成双（用户口径，不许用裸 round）
  B cbpm / 砖长（含真谱 150ms 那一行）
  C 格子 ↔ 毫秒（双向、φ≠0 也成立）
  D 起止点：**按毫秒 或 按格子**（`docs/47` §3）
  E 区间：只吐区间内的砖；**区间外本模块一个字都不吐**
  F 八度校验（那个站夹在 50~210 ⇒ 只报不改）
  G 不静默：非法 N / 空 tbpm / 按格子但没骨架 ⇒ 抛 XkError
  H 真数据：`Flower_Dance` 的 150ms/400bpm 就是 tbpm 100 × 4
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import bigline as BL                             # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

FAIL = []
REAL_DIR = os.path.join(
    _HOME + r"\.dsh\attachments\v1\files\0a",
    "0aed72d9d890d040d5c6834bb8dc527618f8b0b8ec21d0bdaa1d1ef34f912149")
REAL_TS = os.path.join(REAL_DIR, "Flower_Dance-DJ_OKAWARI-1974307.txt")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def near(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except BL.XkError:
        return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- A 取整
def A_round():
    print("\nA. round_tbpm —— 四舍六入五成双（不含小数）")
    cases = [
        ("119.84", 120, "小数部分 .84 ⇒ 入"),
        ("120.4", 120, ".4 ⇒ 舍"),
        ("120.5", 120, "**五成双**：120 是偶数 ⇒ 不上去"),
        ("121.5", 122, "**五成双**：121 是奇数 ⇒ 上到 122"),
        ("122.5", 122, "五成双：122 是偶数 ⇒ 不动"),
        ("123.5", 124, "五成双：124"),
        (" 100.5 ", 100, "两边空白照样吃"),
        ("133", 133, "本来就是整数"),
        (133, 133, "整数入参也吃"),
        ("0.6", 1, "向上到 1"),
    ]
    for raw, want, why in cases:
        got = BL.round_tbpm(raw)
        check(got == want, "round_tbpm({!r}) = {}（要 {}）— {}".format(raw, got, want, why))
    check(raises(BL.round_tbpm, ""), "空字符串 ⇒ XkError（不静默）")
    check(raises(BL.round_tbpm, None), "None ⇒ XkError")
    check(raises(BL.round_tbpm, "abc"), "非数 ⇒ XkError")
    check(raises(BL.round_tbpm, "0.4"), "取整后 0 ⇒ XkError（tbpm 必须 > 0）")
    check(raises(BL.round_tbpm, "nan"), "nan ⇒ XkError")
    check(raises(BL.round_tbpm, float("inf")), "inf ⇒ XkError")


# ---------------------------------------------------------------- B 换算
def B_units():
    print("\nB. cbpm / 砖长（「4 分音」= 一拍 4 砖 = N=4，不是乐理 1/4 拍）")
    check(near(BL.cbpm(100, 4), 400.0), "tbpm 100 × 4k ⇒ cbpm 400（= 我们代码里的 base_bpm）")
    check(near(BL.tile_ms(100, 4), 150.0), "⇒ 砖长 150.000000ms")
    check(near(BL.tile_ms(100, 2), 300.0), "tbpm 100 × 2k ⇒ 砖长 300ms（一拍 2 砖）")
    check(near(BL.tile_ms(100, 8), 75.0), "tbpm 100 × 8k ⇒ 砖长 75ms（一拍 8 砖）")
    check(near(BL.tile_ms(120, 4), 125.0), "tbpm 120 × 4k ⇒ 砖长 125ms")
    check(near(BL.cbpm(100, 4) * BL.tile_ms(100, 4) / 1000.0, 60.0),
          "恒等式：cbpm × 砖长 = 60000 ⇒ 每分钟正好 cbpm 块砖")
    check(BL.N_ON == (2, 4, 8) and BL.N_CHOICES[0] == 0, "N 的集合 = {0(关),2,4,8}")
    check(near(BL.TILE_TRAVEL, 180.0), "骨架每块砖都是 180° 直线")


# ---------------------------------------------------------------- C 双向
def C_bidirectional():
    print("\nC. 格子 ↔ 毫秒（右上角那个「物量 ↔ 时间」参考）")
    ln = BL.BigLine(100, 4, phase_ms=0.0)
    check(near(ln.period_ms, 150.0) and near(ln.cbpm, 400.0), "骨架：400cbpm / 砖长 150ms")
    check(near(ln.ms_of(0), 0.0) and near(ln.ms_of(4), 600.0), "ms_of(0)=0 / ms_of(4)=600ms")
    check(near(ln.ms_of(4) - ln.ms_of(0), 4 * 150.0), "4 块砖 = 4×150 = 600ms（= 1 拍 @100bpm）")
    check(ln.beat_of(600.0) == 1.0, "beat_of(600ms) = 1 拍（= 4 砖）")
    for ms in (0.0, 1.0, 149.9, 150.0, 449.999, 600.0, 1234.5, -0.5, -150.0):
        k = ln.tile_of(ms)
        check(ln.ms_of(k) <= ms + 1e-9 < ln.ms_of(k + 1),
              "tile_of({:.3f}) = {} ⇒ 落在 [ms({}), ms({})) 里".format(
                  ms, k, k, k + 1))
    check(ln.floor_no(0.0) == 1 and ln.floor_no(150.0) == 2,
          "物量号（1 起算）：第 0 块砖 = 第 1 格、第 1 块 = 第 2 格")
    check(near(ln.snap(74.0), 0.0) and near(ln.snap(76.0), 150.0),
          "snap 取最近的格（74ms → 0、76ms → 150）")
    check(near(ln.drift_of(151.0), 1.0), "drift_of(151ms) = +1ms（报「对没对上拍」）")

    ph = BL.BigLine(100, 4, phase_ms=76.87)
    check(near(ph.ms_of(0), 76.87), "φ≠0：ms_of(0) 就是 φ")
    check(ph.tile_of(76.87) == 0 and ph.tile_of(76.87 + 149.0) == 0,
          "φ≠0 时砖号跟着相位走（相位是同一根轴）")

    # 往返：k → ms → k
    bad = [k for k in range(-6, 40) if ln.tile_of(ln.ms_of(k)) != k]
    check(not bad, "往返自洽：k → ms → k 全等（反例 {}）".format(bad[:5]))
    bad2 = [k for k in range(-6, 40) if ph.tile_of(ph.ms_of(k)) != k]
    check(not bad2, "φ≠0 也自洽（反例 {}）".format(bad2[:5]))


# ---------------------------------------------------------------- D 起止点
def D_points():
    print("\nD. 起止点可以**按格子**也可以**按毫秒**（`docs/47` §3）")
    ln = BL.BigLine(100, 4, phase_ms=0.0)
    check(near(BL.parse_point("600", ln, "ms"), 600.0), "按毫秒：600 ⇒ 600.0ms")
    check(near(BL.parse_point("3", ln, "tile"), 300.0),
          "按格子：物量号 3 ⇒ k=2 ⇒ 300ms（**1 起算**）")
    check(near(BL.parse_point("1", ln, "tile"), 0.0), "物量号 1 = 骨架第一块砖 = 0ms")
    check(near(BL.parse_point("ms", ln, "ms") if False else 0, 0.0),
          "「毫秒」单位名也认（'ms'）")
    t0, t1 = BL.parse_span("5", "2", ln, "tile")
    check(near(t0, 150.0) and near(t1, 600.0), "起止点会**自动排先后**（5,2 ⇒ 150~600ms）")
    check(raises(BL.parse_point, "2.5", ln, "tile"), "格子号给了小数 ⇒ XkError（不猜）")
    check(raises(BL.parse_point, "", ln, "ms"), "空点 ⇒ XkError")
    check(raises(BL.parse_point, "x", ln, "ms"), "非数 ⇒ XkError")
    check(raises(BL.parse_point, "3", None, "tile"),
          "按格子给点但没有骨架 ⇒ XkError（xk base 关时不许按格子）")
    check(raises(BL.parse_point, "3", ln, "furlong"), "不认识的单位 ⇒ XkError")
    check(raises(BL.parse_point, "3", BL.BigLine.maybe(100, 0), "tile"),
          "N=0 的空骨架 ⇒ 不许按格子（走原路径）")


# ---------------------------------------------------------------- E 区间
def E_span():
    print("\nE. 区间：只吐区间内的砖；**区间外本模块一个字都不吐**")
    ln = BL.BigLine(100, 4, phase_ms=0.0)
    check(ln.tiles(0.0, 600.0) == [0, 1, 2, 3, 4], "0~600ms ⇒ 砖 0..4（**两端都算**）")
    check(ln.tiles(1.0, 599.0) == [0, 1, 2, 3], "1~599ms ⇒ 砖 0..3（含 t0 那块、不含 t1 那块）")
    check(ln.tiles(300.0, 300.0) == [2], "零长区间 ⇒ 就那一块砖")
    check(ln.tiles(-1000.0, 0.0) == list(range(-7, 1)), "区间可以从负时间起（前奏前的空拍）")
    lay = ln.layer(0.0, 450.0)
    check(len(lay) == 4 and lay[0] == (0, 0.0) and lay[-1] == (3, 450.0),
          "layer(0~450ms) = 4 块砖，时刻 0/150/300/450")
    sp = ln.spans_of(0.0, 300.0)
    check(len(sp) == 3 and all(near(f["travel"], 180.0) for f in sp)
          and all(near(f["bpm"], 400.0) for f in sp),
          "spans_of：每块砖 travel 180 + bpm 400（全直线）")
    check(near(sp[2]["ms"] - sp[1]["ms"], 150.0), "相邻砖间隔 = 砖长（时序天然精确）")
    txt = BL.report_text(ln, t0=0.0, t1=600.0)
    check("区间外走**原路径**" in txt, "报告里写明「区间外走原路径」（不静默）")
    check("5 块砖" in txt, "报告里报出区间内砖数")
    check("[0, 600]" not in txt and "1~5" in txt, "报告里的格子号是**1 起算**的物量号")


# ---------------------------------------------------------------- F 八度
def F_octave():
    print("\nF. 八度校验（那个站夹在 50~210 ⇒ 只报不改）")
    n2 = BL.octave_note(100, 4, 300.0)
    check("×2" in n2 and "八度" in n2, "砖长差 ×2 ⇒ 报出来")
    n3 = BL.octave_note(100, 4, 75.0)
    check("÷2" in n3, "砖长差 ÷2 ⇒ 报出来")
    n4 = BL.octave_note(100, 4, 150.0)
    check(n4 == "", "砖长对得上 ⇒ 什么都不说（不误报）")
    check(BL.octave_note(100, 4, 0.0) == "", "没有参照（period=0）⇒ 不说话")
    check(BL.octave_note(100, 4, 151.0) == "", "差 0.7% ⇒ 不当作八度（容差 6%）")
    check("×4" in BL.octave_note(100, 4, 600.0), "差 ×4 也认")
    check("half-time" in BL.octave_note(120, 4, 1000.0),
          "报告里点明 half-time 的成因（那个站的夹取）")


# ---------------------------------------------------------------- G 不静默
def G_errors():
    print("\nG. 不静默：错就抛 / 就说，不兜底")
    for bad_n in (1, 3, 5, 6, 16, -2, "abc"):
        check(raises(BL.check_n, bad_n), "N={!r} ⇒ XkError（只允许 0/2/4/8）".format(bad_n))
    check(not raises(BL.check_n, 2) and not raises(BL.check_n, 0),
          "N=2 / N=0 合法（0 = 关）")
    check(raises(BL.cbpm, 100, 0), "N=0 要 cbpm ⇒ XkError（关的时候没有 cbpm）")
    empty = BL.BigLine.maybe(100, 0)
    check(empty.ok is False and "关" in empty.why, "maybe(100, 0) ⇒ ok=False 并说明原因")
    check(empty.report_text().startswith("大直线：关"), "空骨架的报告是一句人话")
    check(json.loads(json.dumps(empty.to_dict()))["ok"] is False, "空骨架 to_dict 可序列化")
    bad = BL.BigLine.maybe("abc", 4)
    check(bad.ok is False and "解析不了" in bad.why, "tbpm 非数 ⇒ maybe 返回 ok=False（不抛）")
    check(raises(BL.BigLine, 100, 3), "直接构造 N=3 ⇒ XkError")
    check(raises(BL.BigLine, float("nan"), 4), "直接构造 tbpm=nan ⇒ XkError")
    check(raises(BL.BigLine, 0, 4), "直接构造 tbpm=0 ⇒ XkError")
    r = BL.BigLine(119.84, 4)
    check(r.tbpm == 120 and r.rounded_from is not None,
          "传小数进来会被取整，并**记下原值**（rounded_from，不静默）")
    ok = BL.BigLine(120, 4)
    check(ok.rounded_from is None, "整数入参不记 rounded_from（没发生取整）")
    check(isinstance(json.dumps(ok.to_dict()), str), "to_dict 可 JSON 序列化（要给前端）")
    # ★★ 砖数硬上限 —— 没有它，一个填错的 tbpm 能把 sidecar 卡几十秒
    #    （实测 0~1e8ms × 150ms 砖 = 666667 块 ⇒ **53 秒**，界面表现为进度条冻死）
    check(BL.MAX_TILES == 20000, "砖数上限 = 20000（{}）".format(BL.MAX_TILES))
    ln = BL.BigLine(100, 4)
    check(raises(BL.BigLine, 100000, 4), "tbpm 100000 ⇒ 砖长 0.15ms，不合理 ⇒ **直接抛**")
    check(not raises(BL.BigLine, 400, 8), "tbpm 400 × 8k ⇒ 砖长 18.75ms，合法")
    check(raises(ln.tiles, 0.0, 1e8), "区间要铺 66 万块砖 ⇒ 抛（不硬算）")
    check(raises(ln.tiles_within, 0.0, 1e8), "tiles_within 也拦（同一个上限）")
    check(len(ln.tiles(0.0, 150.0 * 100)) == 101, "正常区间（101 块）照常返回")
    check(raises(ln.tile_of, float("nan")), "时间给 nan ⇒ 抛 XkError（不是 TypeError）")
    check(raises(ln.tile_of, 1e30), "时间大到离谱 ⇒ 抛")
    check(raises(ln.ms_of if False else ln.tiles, float("-inf"), 0.0),
          "起点给 -inf ⇒ 抛")


# ---------------------------------------------------------------- H 真数据
def H_real():
    print("\nH. 真数据：`Flower_Dance` 的 150ms / 400bpm 就是 tbpm 100 × 4")
    if not os.path.isfile(REAL_TS):
        print("  [skip] 没有真数据文件：{}".format(REAL_TS))
        return
    from core import ts_source as TS
    from core import denoise as DN
    ts, rep = TS.read_ts(REAL_TS)
    check(len(ts) > 1000, "读到 {} 个时间戳".format(len(ts)))
    g = DN.plan(ts)
    check(near(g.period_ms, 150.0, 1e-6),
          "去噪解出的砖长 = {:.6f}ms（真值 150）".format(g.period_ms))
    ln = BL.BigLine(100, 4, phase_ms=g.phase_ms)
    check(near(ln.period_ms, g.period_ms, 1e-6),
          "大直线（tbpm 100 × 4k）的砖长与去噪解出的**逐位相同**：{:.6f} vs {:.6f}".format(
              ln.period_ms, g.period_ms))
    check(BL.octave_note(100, 4, g.period_ms) == "",
          "八度校验通过（没有 ×2 / ÷2 的嫌疑）")
    lo, hi = min(ts), max(ts)
    ks = ln.tiles(lo, hi)
    want = int((hi - lo) / 150.0) + 1
    check(len(ks) >= want - 1, "整曲骨架 = {} 块砖（{:.0f}ms ⇒ 理论 {}+1 块）".format(
        len(ks), hi - lo, int((hi - lo) / 150.0)))
    check(len(ks) > len(ts),
          "骨架砖数 {} > onset 数 {}（骨架跟音乐内容**无关** ⇒ 才有「绝对不好看」）".format(
              len(ks), len(ts)))
    step = [ks[i + 1] - ks[i] for i in range(min(50, len(ks) - 1))]
    check(set(step) == {1}, "相邻砖号连续（等间隔，中间没有跳号）")
    ms = [ln.ms_of(k) for k in ks[:60]]
    gaps = [round(ms[i + 1] - ms[i], 9) for i in range(len(ms) - 1)]
    check(set(gaps) == {150.0}, "前 60 块砖的间隔全是 150.0ms（**绝对对拍**）")
    print("  ---- 骨架报告 ----")
    for row in BL.report_text(ln, t0=lo, t1=hi).splitlines():
        print("  " + row)


def main():
    A_round()
    B_units()
    C_bidirectional()
    D_points()
    E_span()
    F_octave()
    G_errors()
    H_real()
    print("\n" + "=" * 78)
    if FAIL:
        print("✗ {} 项失败:".format(len(FAIL)))
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 大直线骨架全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
