"""算法轨道调度（`docs/60`）：纯函数测试。

    python tests/test_appearance.py

验十组（都是这一轮实测/踩过的坑）：

  A 皮肤：`settings` 只覆盖该覆盖的那几个键；**关掉开关 ⇒ settings 一个字节不动**
  B 图形段识别：`snowflake`/`template`/`natural`/`engine` 四个标记的连续 run ⇒ 段起点
  C 涟漪环配方：`startTile=-n / endTile=+n / gapLength=max(0,2n-1) / angleOffset=step·n`
    ★ n=0 时 `gapLength` **必须是 0**（写 −1 会让游戏 `i += 1+gapLength` 步长 0 ⇒ 死循环）
  D 环数上限：不越过谱首/谱尾（负下标会被游戏忽略，`TimelineManager.ts:178`）
  E ⑤b 优先：触发点与换手押**同格** ⇒ 跳过并记账；扫描过换手押格 ⇒ 只记账不跳过
  F 密度：格/拍口径（与 BPM 无关）；窗口内计数正确
  G 半径状态机：迟滞 + 最短驻留 ⇒ 密集切 125（**行星距离上限**）、回落切 100，防抖
  H 事件字段集：`RecolorTrack` 17 字段（逐字对齐语料）/ `ScaleRadius` 只有 3 个键
  I `writer` 接线：事件真的进 actions、整份仍按 floor 有序、skin 进 settings、越界记账
  J 同格并行度上限：超上限 ⇒ 截断并记账（不许静默）
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import appearance as AP                             # noqa: E402
from core import writer as W                                  # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


# ------------------------------------------------------------------ 小工具
class _F:
    """假的 Floor：`appearance` / `track_fx` / `writer` 会读的字段。"""
    def __init__(self, travel=180.0, *, snowflake=False, template=False,
                 natural=False, engine=False, speed_k=1.0, pause_beats=0.0):
        self.travel = float(travel)
        self.twirl = False
        self.pause_beats = float(pause_beats)
        self.angle = 0.0
        self.speed_k = float(speed_k)
        self.snowflake = bool(snowflake)
        self.template = bool(template)
        self.natural = bool(natural)
        self.engine = bool(engine)


class _C:
    """假的 Chart：只要 `floors` / `meta` / `set_speed_floors` / `base_bpm`。"""
    def __init__(self, travels=None, *, meta=None, base_bpm=180.0, floors=None):
        self.floors = list(floors) if floors is not None else [_F(t) for t in (travels or [])]
        self.meta = dict(meta or {})
        self.set_speed_floors = []
        self.base_bpm = float(base_bpm)


def flat(n, travel=180.0):
    return _C(floors=[_F(travel) for _ in range(n)])


# ================================================================== A 皮肤
def group_a():
    print("\n=== A 皮肤（settings 层）===")
    ch = flat(8)
    pl = AP.plan(ch, skin_style="Neon")
    st = pl.settings
    check(st.get("trackStyle") == "Neon", "皮肤写进 settings.trackStyle=Neon")
    check(set(st) == {"trackStyle", "trackColorType", "trackColor", "secondaryTrackColor",
                      "trackColorPulse", "trackPulseLength", "trackGlowIntensity",
                      "trackColorAnimDuration"},
          f"皮肤**只**覆盖这 8 个外观键，实际 {sorted(st)}")

    off = AP.plan(ch, enabled=False)
    check(off.settings == {}, "关掉开关 ⇒ settings 空 dict（导出与旧版逐字节相同）")
    check(off.events == [] and off.n_events == 0, "关掉开关 ⇒ 一条事件都不写")
    check(off.report_text() == "", "关掉开关 ⇒ 报告为空（不上屏）")


# =========================================================== B 图形段识别
def group_b():
    print("\n=== B 图形段识别 ===")
    fl = [_F() for _ in range(4)] + [_F(snowflake=True) for _ in range(3)] + \
         [_F() for _ in range(2)] + [_F(template=True) for _ in range(2)] + [_F() for _ in range(2)]
    ch = _C(floors=fl)
    sp = AP.figure_spans(ch)
    check(sp == [(4, 6), (9, 10)], f"两段图形 ⇒ [(4,6),(9,10)]，实际 {sp}")
    check(AP.figure_kind(ch, 4) == "雪花", f"第 4 格是雪花，实际 {AP.figure_kind(ch, 4)!r}")
    check(AP.figure_kind(ch, 9) == "模板", f"第 9 格是模板，实际 {AP.figure_kind(ch, 9)!r}")
    only = AP.figure_spans(ch, sources=("snowflake",))
    check(only == [(4, 6)], f"只挑雪花 ⇒ [(4,6)]，实际 {only}")
    single = _C(floors=[_F(snowflake=True)] + [_F() for _ in range(3)])
    check(AP.figure_spans(single) == [], "只有 1 格的图形段被 min_tiles=2 丢掉")


# ============================================================ C 涟漪环配方
def group_c():
    print("\n=== C 涟漪环配方 ===")
    fl = [_F() for _ in range(6)] + [_F(snowflake=True) for _ in range(4)] + [_F() for _ in range(30)]
    ch = _C(floors=fl)
    pl = AP.plan(ch, ripple=True, ripple_rings=3, ripple_step=30.0, radius=False)
    rec = [e for e in pl.events if e["eventType"] == "RecolorTrack"]
    check(len(pl.ripples) == 1 and pl.ripples[0].floor == 6,
          f"触发点是图形段起点 6，实际 {[(r.floor, r.rings) for r in pl.ripples]}")
    check(pl.ripples[0].rings == 3, f"环数 = 3（设置值），实际 {pl.ripples[0].rings}")
    check(len(rec) == 2 * 4, f"每环 2 条（闪 + 回色）⇒ 3 环共 8 条，实际 {len(rec)}")

    def one(k, back):
        for e in rec:
            if e["gapLength"] == (0 if k == 0 else 2 * k - 1) and \
               (e["duration"] == 2.0) == back:
                return e
        return None

    for k in (0, 1, 2, 3):
        e = one(k, False)
        check(e is not None, f"第 {k} 环的闪光事件存在")
        if e is None:
            continue
        check(e["startTile"] == [-k, "ThisTile"] and e["endTile"] == [k, "ThisTile"],
              f"第 {k} 环 startTile/endTile = ±{k}")
        gap_exp = max(0, 2 * k - 1)
        check(e["gapLength"] == gap_exp, f"第 {k} 环 gapLength = {gap_exp}（步长 2k）")
        check(abs(e["angleOffset"] - 30.0 * k) < 1e-9, f"第 {k} 环 angleOffset = 30k")
    zero = one(0, False)
    check(zero is not None and zero["gapLength"] == 0,
          "★ n=0 的 gapLength **必须是 0**（−1 ⇒ 步长 0 ⇒ 游戏死循环）")
    back = one(1, True)
    check(back is not None and back["duration"] == 2.0 and back["ease"] == "OutCubic",
          "回色事件 duration=2 / ease=OutCubic（语料的成对写法）")


# ============================================================ D 环数上限
def group_d():
    print("\n=== D 环数上限（不许越过谱首/谱尾）===")
    ch = _C(floors=[_F(snowflake=True) for _ in range(2)] + [_F() for _ in range(3)])
    pl = AP.plan(ch, ripple=True, ripple_rings=16, radius=False)
    check(pl.ripples and pl.ripples[0].rings == 0,
          f"触发格 0 ⇒ 左边没地方 ⇒ 0 环，实际 {pl.ripples[0].rings if pl.ripples else None}")
    check("谱面边界" in pl.ripples[0].why, f"被边界砍掉要写原因：{pl.ripples[0].why!r}")
    ch2 = _C(floors=[_F() for _ in range(5)] + [_F(snowflake=True) for _ in range(2)] +
             [_F() for _ in range(2)])
    pl2 = AP.plan(ch2, ripple=True, ripple_rings=16, radius=False)
    check(pl2.ripples[0].rings == 3,
          f"距谱尾只剩 3 格 ⇒ 3 环，实际 {pl2.ripples[0].rings}")
    check("谱面边界" in pl2.ripples[0].why, f"受限原因写清楚了：{pl2.ripples[0].why!r}")
    ch3 = _C(floors=[_F() for _ in range(10)] + [_F(snowflake=True) for _ in range(2)] +
             [_F() for _ in range(40)])
    pl3 = AP.plan(ch3, ripple=True, ripple_rings=4, radius=False)
    check(pl3.ripples[0].rings == 4 and pl3.ripples[0].why == "",
          "空间充足 ⇒ 给满 4 环，且**不写**受限原因")


# =========================================================== E ⑤b 优先
def group_e():
    print("\n=== E ⑤b（换手押上色）优先 ===")
    fl = [_F() for _ in range(6)] + [_F(snowflake=True) for _ in range(3)] + [_F() for _ in range(20)]
    ch = _C(floors=fl)
    pl = AP.plan(ch, ripple=True, ripple_rings=2, radius=False, occupied={6})
    check(pl.ripples == [] and pl.n_collide == 1,
          f"触发点与换手押同格 ⇒ 跳过并记 n_collide=1，实际 {pl.n_collide}")
    check(any("避让" in w for w in pl.skipped_why), "跳过原因写进 skipped_why")
    pl2 = AP.plan(ch, ripple=True, ripple_rings=2, radius=False, occupied={5, 7})
    check(pl2.ripples and pl2.n_collide == 0, "只在'扫描到'的换手押格上不跳过")
    check(pl2.n_overlap_occ == 2, f"扫描过的换手押格要记数，实际 {pl2.n_overlap_occ}")
    check("扫过" in pl2.report_text(), "报告里要说'涟漪会短暂扫过 N 个换手押格'")


# ============================================================== F 密度
def group_f():
    print("\n=== F 密度（**音/秒**，纯实时）===")
    # 180 BPM、全 180° 直格 ⇒ 1 拍 1 音 ⇒ 3 音/秒
    ch = _C(floors=[_F(180.0) for _ in range(40)], base_bpm=180.0)
    d = AP.density_fps(ch, window_s=2.0)
    check(abs(d[20] - 3.0) < 1e-6,
          f"180° 直格 @180BPM ⇒ 3 音/秒，实际 {d[20]:.4f}")
    # 45° 格 ⇒ 4 音/拍 ⇒ 12 音/秒
    ch2 = _C(floors=[_F(45.0) for _ in range(60)], base_bpm=180.0)
    d2 = AP.density_fps(ch2, window_s=2.0)
    check(abs(d2[30] - 12.0) < 0.05,
          f"45° 格 @180BPM ⇒ 12 音/秒，实际 {d2[30]:.4f}")
    # ★ 口径一致性：`音/秒 == 格/拍 × base_bpm/60`。
    #   第一版直接用「格/拍」当阈值 ⇒ 同一个 **音/秒** 阈值，标成 122.5 与 980 BPM
    #   时对应的「格/拍」差了 8 倍 ⇒ 阈值在音乐上根本没有意义（这才是 ASGORE 闪 4 格的根因）。
    ch5 = _C(floors=[_F(90.0) for _ in range(60)], base_bpm=180.0)   # 2 格/拍
    d5 = AP.density_fps(ch5, window_s=2.0)
    check(abs(d5[30] - 6.0) < 0.05,
          f"90° 格 @180BPM ⇒ 2 格/拍 × 3 = 6 音/秒，实际 {d5[30]:.4f}")
    # 速度档 2（半速）⇒ 每秒音数减半
    ch4 = _C(floors=[_F(180.0, speed_k=2.0) for _ in range(60)], base_bpm=180.0)
    d4 = AP.density_fps(ch4, window_s=2.0)
    check(abs(d4[30] - 1.5) < 0.05,
          f"速度档 2（半速）⇒ 1.5 音/秒，实际 {d4[30]:.4f}")


# ============================================================ G 半径状态机
def group_g():
    print("\n=== G 半径状态机（迟滞 + 双最短驻留）===")
    # 直格 @180BPM = 3 音/秒（疏）；30° 格 = 6 音/拍 = 18 音/秒（密）
    quiet = [_F(180.0) for _ in range(40)]
    dense = [_F(30.0) for _ in range(80)]
    fl = quiet + dense + quiet
    ch = _C(floors=fl, base_bpm=180.0)
    sw = AP.radius_switch_points(ch, quiet=100, dense=125)
    check(len(sw) == 2, f"疏→密→疏 ⇒ 2 个切换点，实际 {len(sw)}: "
                        f"{[(s.floor, s.scale) for s in sw]}")
    if len(sw) == 2:
        check(sw[0].scale == 125, f"进密集 ⇒ 125，实际 {sw[0].scale}")
        check(sw[1].scale == 100, f"回稀疏 ⇒ 100，实际 {sw[1].scale}")
        check(sw[1].floor > sw[0].floor, "回落的格在切换之后")
        check(sw[1].floor - sw[0].floor >= AP.RADIUS_MIN_TILES,
              f"回落至少隔 {AP.RADIUS_MIN_TILES} 格，实际 {sw[1].floor - sw[0].floor}")
    # ★★ 用户 2026-10：「行星距离（`ScaleRadius`）**最高的阈值应该为 125**」
    #   ⇒ 给 250 / 400 也必须夹到 125，而且**要记账**（不许静默）。
    check(AP.RADIUS_MAX == 125, f"`RADIUS_MAX` 是 125，实际 {AP.RADIUS_MAX}")
    check(AP.RADIUS_DENSE <= AP.RADIUS_MAX,
          f"密集档默认 {AP.RADIUS_DENSE} ≤ 上限 {AP.RADIUS_MAX}")
    sw_hi = AP.radius_switch_points(ch, quiet=100, dense=250)
    check(all(s.scale <= 125 for s in sw_hi),
          f"要 250 也夹到 ≤125：{[s.scale for s in sw_hi]}")
    pl_hi = AP.plan(ch, radius=True, radius_dense=400, radius_quiet=100)
    why = " ".join(pl_hi.skipped_why or [])
    check("夹" in why and "125" in why,
          f"超上限时**记账**（不许静默）：{why[:120]!r}")
    flat_ch = _C(floors=[_F(180.0) for _ in range(30)], base_bpm=180.0)
    check(AP.radius_switch_points(flat_ch) == [],
          "全谱一个密度 ⇒ 0 个切换点（**初始状态默认就是 quiet，不写事件**）")
    # ★★ 实测踩到的坑（ASGORE 60s）：高 BPM 下"4 拍"只有 4 格 ⇒ 只按拍数防抖会**闪一下**。
    #   这里构造一段**只有 3 格**的密集尖峰，必须一次都不切。
    spike = ([_F(180.0) for _ in range(40)] + [_F(30.0) for _ in range(3)]
             + [_F(180.0) for _ in range(40)])
    sw2 = AP.radius_switch_points(_C(floors=spike, base_bpm=180.0))
    check(len(sw2) <= 1,
          f"密集尖峰只有 3 格（< 最短 {AP.RADIUS_MIN_TILES} 格）⇒ 不许回落/闪断，"
          f"实际 {len(sw2)} 个切换")
    # 长密集段必须给满：50 格密集 ⇒ 一定切过去
    sw3 = AP.radius_switch_points(
        _C(floors=[_F(180.0) for _ in range(30)] + [_F(30.0) for _ in range(50)]
           + [_F(180.0) for _ in range(30)], base_bpm=180.0))
    check(len(sw3) == 2 and sw3[0].scale == 125,
          f"50 格密集段 ⇒ 切过去并回来，实际 {[(s.floor, s.scale) for s in sw3]}")


# ========================================================= H 事件字段集
def group_h():
    print("\n=== H 事件字段集（逐字对齐语料）===")
    ch = _C(floors=[_F() for _ in range(4)] + [_F(snowflake=True) for _ in range(3)] +
            [_F(30.0) for _ in range(40)])
    pl = AP.plan(ch, ripple=True, ripple_rings=1, radius=True)
    rec = [e for e in pl.events if e["eventType"] == "RecolorTrack"]
    want_r = {"floor", "eventType", "startTile", "endTile", "gapLength", "duration",
              "trackColorType", "trackColor", "secondaryTrackColor",
              "trackColorAnimDuration", "trackColorPulse", "trackPulseLength",
              "trackStyle", "trackGlowIntensity", "angleOffset", "ease", "eventTag"}
    check(set(rec[0]) == want_r,
          f"RecolorTrack 字段集与语料一致，多了/少了 {sorted(set(rec[0]) ^ want_r)}")
    check("justThisTile" not in rec[0] and "startTile" in rec[0],
          "RecolorTrack **不带** justThisTile（那是 ColorTrack 的字段）")
    sr = [e for e in pl.events if e["eventType"] == "ScaleRadius"]
    check(sr and set(sr[0]) == {"floor", "eventType", "scale"},
          f"ScaleRadius 只有 3 个键（语料实测 keys(3)），实际 {sorted(sr[0]) if sr else None}")
    check(isinstance(sr[0]["scale"], int), "scale 是整数（语料全是整数）")
    check(all(e["ease"] in ("Linear", "OutCubic") for e in rec),
          "ease 只用语料里出现过的 Linear/OutCubic")


# ============================================================ I writer 接线
def group_i():
    print("\n=== I writer 接线 ===")
    ch = _C(floors=[_F() for _ in range(4)] + [_F(snowflake=True) for _ in range(3)] +
            [_F(30.0) for _ in range(40)], meta={"appearance_events": []})
    pl = AP.plan(ch, ripple=True, ripple_rings=2, radius=True)
    ch.meta["appearance_events"] = list(pl.events)
    ch.meta["appearance_settings"] = dict(pl.settings)
    acts = W.build_actions(ch)
    got = [a for a in acts if a.get("eventType") in ("RecolorTrack", "ScaleRadius")]
    check(len(got) == pl.n_events, f"事件全进 actions：{len(got)} vs {pl.n_events}")
    fl = [int(a.get("floor", -1)) for a in acts if "floor" in a]
    check(fl == sorted(fl), "整份 actions 仍按 floor 有序")
    check(ch.meta.get("appearance_written") == pl.n_events,
          f"写了几条要记账，实际 {ch.meta.get('appearance_written')}")
    check(ch.meta.get("appearance_out_of_range") == [], "没有越界事件")
    # 越界 ⇒ 丢弃并报出来
    ch.meta["appearance_events"] = [{"floor": 99999, "eventType": "ScaleRadius", "scale": 125}]
    W.build_actions(ch)
    check(ch.meta.get("appearance_out_of_range") == [99999]
          and ch.meta.get("appearance_written") == 0,
          f"越界事件被丢弃并记账，实际 {ch.meta.get('appearance_out_of_range')}")
    # settings 皮肤
    ch.meta["appearance_settings"] = AP.Skin(style="Neon").to_settings()
    j = W.build_json(ch, song="s", artist="a")
    check(j["settings"]["trackStyle"] == "Neon", "皮肤进 settings.trackStyle")
    ch.meta["appearance_settings"] = {}
    j2 = W.build_json(ch, song="s", artist="a")
    check(j2["settings"]["trackStyle"] == "Standard",
          "不带皮肤 ⇒ 保持模板默认 Standard（不偷偷改）")


# ====================================================== J 同格并行度上限
def group_j():
    print("\n=== J 同格并行度上限（防护）===")
    fl = [_F() for _ in range(6)] + [_F(snowflake=True) for _ in range(3)] + [_F() for _ in range(60)]
    ch = _C(floors=fl)
    pl = AP.plan(ch, ripple=True, ripple_rings=40, radius=False, max_per_floor=10)
    check(pl.n_capped > 0, f"超上限要记截断数，实际 {pl.n_capped}")
    check(pl.max_per_floor <= 10, f"同格最多 10 条，实际 {pl.max_per_floor}")
    check(pl.ripples and pl.ripples[0].rings < 40, "环数被上限截断（报告里也说）")
    check("截断" in pl.report_text(), "报告里要说截断了几环")


def main():
    print("=" * 66)
    print("算法轨道调度（docs/60）单测")
    print("=" * 66)
    for fn in (group_a, group_b, group_c, group_d, group_e,
               group_f, group_g, group_h, group_i, group_j):
        fn()
    print("\n" + "=" * 66)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败：")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 算法轨道调度全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
