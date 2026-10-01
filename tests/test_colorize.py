"""换手押上色（`docs/59`）：纯函数测试。

    python tests/test_colorize.py

验九组（都是这一轮实测/踩过的坑）：

  A 用户样例真文件：20 个双押组 / 19 对全部 gap==2 / 链长 20 ⇒ 整段判为换手押
  B `dp_pairs` 权威路径：来源标注正确；**押数 ≠ 2 的组必须被跳过且记账**（不许静默）
  C 判据边界：孤立双押不算；`gap != 2` 不算；`gap`/`min_cycles` 参数化；空谱面
  D 关闭开关 ⇒ **一条事件都不写**（导出与旧版逐字节相同）
  E 几何歧义：`(90°, 90°)` 与普通直角折角无法区分 ⇒ 不认，**但必须报出来**
  F 事件字段集：**`ColorTrack`** + `justThisTile`（逐字对齐语料，防 `LevelEvent.Decode` 取 null）
  G `writer.build_actions` 接线（事件真的进 actions、整份仍按 floor 有序、越界记账）
  H 事件选型：「**设置**」而不是「**重新设置**」+「**仅作用于当前方块**」+ **一格一条不堆叠**
  I 染色间隔：用户记号串 `XOODOOXOODOO` ⇒ 每 2 个双押染 1 个、两个相位互补
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

from core import colorize as CZ                              # noqa: E402

FAIL = []
SAMPLE = os.path.join(_HERE, "fixtures", "colorize", "handswitch_sample.adofai")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


# ------------------------------------------------------------------ 小工具
class _F:
    """假的 Floor：`travel` + `writer.build_actions` 会读的几个字段。"""
    def __init__(self, travel):
        self.travel = float(travel)
        self.twirl = False
        self.pause_beats = 0.0
        self.angle = 0.0
        self.speed_k = 1.0


class _C:
    """假的 Chart：只要 `floors` / `meta` / `set_speed_floors`。"""
    def __init__(self, travels, meta=None):
        self.floors = [_F(t) for t in travels]
        self.meta = dict(meta or {})
        self.set_speed_floors = []


def travels_from_angle_data(ad):
    """`travel = 180 − |ΔangleData|`（`docs/59` §1.2，两边口径一致）。"""
    out = [180.0]
    for i in range(1, len(ad)):
        turn = (float(ad[i]) - float(ad[i - 1]) + 540.0) % 360.0 - 180.0
        out.append(180.0 - abs(turn))
    return out


def sample_chart():
    with open(SAMPLE, "r", encoding="utf-8-sig") as f:
        j = json.load(f)
    return _C(travels_from_angle_data(j["angleData"]))


def thin_of(ch):
    return [i for i, f in enumerate(ch.floors) if abs(f.travel - 30.0) < 1e-6]


def pairs_chart(n_pairs=2, gap_tiles=2):
    """造一份「每 `gap_tiles` 个普通格夹一个双押」的 travel 序列 + `dp_pairs`。"""
    tv, pairs = [180.0], []
    for _ in range(n_pairs):
        thin, rest = len(tv), len(tv) + 1
        tv += [30.0, 150.0]
        pairs.append((thin, thin, rest))
        tv += [180.0] * gap_tiles
    return _C(tv, meta={"dp_pairs": pairs}), pairs


# ------------------------------------------------------------------ A 用户样例
def A_sample():
    print("\nA 用户样例（真文件 fixture，几何判据）")
    ch = sample_chart()
    rep = CZ.plan(ch)
    check(rep.source == "geometry", f"没有 dp_pairs ⇒ 走几何判据（source={rep.source}）")
    check(len(rep.groups) == 20, f"双押组 = {len(rep.groups)}（期望 20）")
    check(all(g.press == 2 for g in rep.groups), "全部是双押（押数 2）")
    gaps = [rep.groups[k + 1].first - rep.groups[k].last - 1
            for k in range(len(rep.groups) - 1)]
    check(gaps and all(g == 2 for g in gaps),
          f"{len(gaps)}/{len(gaps)} 对相邻组 gap==2（{sorted(set(gaps))}）")
    check(len(rep.chains) == 1 and len(rep.chains[0]) == 20,
          f"链 = {[len(x) for x in rep.chains]}（期望 [20]）")
    # ★ 用户定义：`X O O D O O X O O D O O` ⇒ **每 2 个双押染 1 个，从第 2 个起**
    thin = thin_of(ch)
    want = thin[1::2]
    check(rep.n_events == 10, f"事件数 = {rep.n_events}（期望 10 = 20 组里每 2 个染 1 个）")
    check(rep.floors == want,
          f"染的是第 2/4/6…个双押的薄格（{rep.floors[:4]}… vs {want[:4]}…）")
    check(rep.n_skipped_press == 0 and rep.n_skipped_ambig == 0, "无跳过")
    txt = rep.report_text()
    check("10" in txt and "换手押上色" in txt, f"报告人话：{txt}")
    check("每 2 个双押染 1 个" in txt, f"报告写明染色间隔：{txt[-46:]}")


# ------------------------------------------------------------------ B dp_pairs
def B_meta_path():
    print("\nB `dp_pairs` 权威路径（我们自己生成的谱面）")
    ch, pairs = pairs_chart(4, 2)
    rep = CZ.plan(ch)
    check(rep.source == "dp_pairs", f"来源 = {rep.source}")
    check(len(rep.groups) == 4 and rep.n_events == 2,
          f"4 组 → {rep.n_events} 条事件（每 2 个染 1 个 ⇒ 2 条）")
    check(rep.floors == [pairs[1][0], pairs[3][0]],
          f"落点 = 第 2/4 个双押的薄格 {rep.floors}")

    # 三押（同一剩余格两块薄格）⇒ 本轮跳过，且必须记账
    tv2, pairs2 = [180.0], []
    for _ in range(3):
        t1, t2, rest = len(tv2), len(tv2) + 1, len(tv2) + 2
        tv2 += [30.0, 60.0, 90.0]
        pairs2 += [(t1, t1, rest), (t2, t2, rest)]
        tv2 += [180.0, 180.0]
    rep2 = CZ.plan(_C(tv2, meta={"dp_pairs": pairs2}))
    check(rep2.n_skipped_press == 3 and rep2.n_events == 0,
          f"三押组 3 个被跳过（n_skipped_press={rep2.n_skipped_press}, "
          f"events={rep2.n_events}）")
    check(any("押数" in w for w in rep2.skipped_why), "跳过原因进了报告（不许静默）")
    _t = rep2.report_text()
    check("已跳过" in _t and "3 个" in _t,
          f"**0 处也要把跳过账说出来**（实测抓到的 bug）：{_t}")


# ------------------------------------------------------------------ C 判据边界
def C_bounds():
    print("\nC 判据边界")
    # 孤立单个双押
    ch = _C([180.0, 30.0, 150.0, 180.0, 180.0, 180.0])
    rep = CZ.plan(ch)
    check(rep.n_events == 0 and rep.chains == [], "孤立 1 个双押 ⇒ 不算换手押")
    check(any("OOX" in w for w in rep.skipped_why), "说明了为什么不算")
    # 恰好 2 个周期 ⇒ 算（每 2 个染 1 个 ⇒ 只染第 2 个）
    ch2 = _C([180.0, 30.0, 150.0, 180.0, 180.0, 30.0, 150.0, 180.0, 180.0])
    rep2 = CZ.plan(ch2)
    check(rep2.n_events == 1, f"2 个周期 ⇒ 认，且每 2 个只染 1 个（{rep2.n_events} 条）")
    check(CZ.plan(ch2, color_every=1).n_events == 2, "every=1 ⇒ 两个都染")
    check(CZ.plan(ch2, color_phase=1).n_events == 1,
          "phase=1 ⇒ 换成第 1 个（仍是 1 条，但落点不同）")
    # 间隔 3 格 ⇒ 不算（默认 gap=2）
    ch3 = _C([180.0, 30.0, 150.0, 180.0, 180.0, 180.0, 30.0, 150.0, 180.0, 180.0])
    rep3 = CZ.plan(ch3)
    check(rep3.n_events == 0, "间隔 3 格、默认 gap=2 ⇒ 不算")
    # gap 参数化 ⇒ 能认
    rep4 = CZ.plan(ch3, gap_tiles=3)
    check(rep4.n_events == 1, f"gap=3 ⇒ 认（{rep4.n_events} 条，每 2 个染 1 个）")
    # min_cycles 参数化：孤立那个也算链，但链长 1 < 相位 2 ⇒ 0 条（**并且要报出来**）
    rep5 = CZ.plan(ch, min_cycles=1)
    check(rep5.n_events == 0 and any("相位" in w for w in rep5.skipped_why),
          f"min_cycles=1 + phase=2：链长 1 落不到相位 ⇒ 0 条，且**报出来**："
          f"{rep5.skipped_why[:1]}")
    check(CZ.plan(ch, min_cycles=1, color_phase=1).n_events == 1,
          "min_cycles=1 + phase=1：孤立那个也染")
    # 空谱面
    check(CZ.plan(None).n_events == 0, "没有谱面 ⇒ 0 条，不抛异常")


# ------------------------------------------------------------------ D 关闭
def D_off():
    print("\nD 关闭开关")
    ch = sample_chart()
    rep = CZ.plan(ch, enabled=False)
    check(rep.events == [] and rep.n_events == 0, "关 ⇒ 一条事件都不写")
    check("已关闭" in rep.report_text(), f"报告写明关闭：{rep.report_text()}")


# ------------------------------------------------------------------ E 几何歧义
def E_ambiguous():
    print("\nE 几何歧义 (90,90)")
    # 4 组 (90,90) 连排：几何上跟普通直角折角一模一样 ⇒ 不许认
    tv = [180.0]
    for _ in range(4):
        tv += [90.0, 90.0, 180.0, 180.0]
    ch = _C(tv)
    rep = CZ.plan(ch)
    check(rep.n_events == 0, "不认 (90,90)（否则会把普通直角折角全染了）")
    check(rep.n_skipped_ambig == 4,
          f"4 个 (90,90) 候选全部记账（n_skipped_ambig={rep.n_skipped_ambig}）")
    check("90" in rep.report_text(), f"人话里说清：{rep.report_text()}")
    # 有 dp_pairs ⇒ 90° 双押照认
    tv2, pairs = [180.0], []
    for _ in range(3):
        thin, rest = len(tv2), len(tv2) + 1
        tv2 += [90.0, 90.0, 180.0, 180.0]
        pairs.append((thin, thin, rest))
    rep2 = CZ.plan(_C(tv2, meta={"dp_pairs": pairs}))
    check(rep2.n_events == 1, "有 dp_pairs ⇒ 90° 双押照认（3 组里每 2 个染 1 个 ⇒ 1 条）")


# ------------------------------------------------------------------ F 字段集
def F_event_shape():
    print("\nF 事件字段集与颜色值")
    ch = sample_chart()
    rep = CZ.plan(ch)
    keys = set(rep.events[0].keys())
    check(keys == set(CZ.EVENT_KEYS),
          f"字段集 == 语料真值（多 {sorted(keys - set(CZ.EVENT_KEYS))} / "
          f"少 {sorted(set(CZ.EVENT_KEYS) - keys)}）")
    e = rep.events[0]
    check(e["eventType"] == "ColorTrack",
          "事件名 **ColorTrack**（= 游戏里的「设置轨道颜色」；不是 RecolorTrack「重新设置」）")
    check("startTile" not in e and "endTile" not in e and "duration" not in e,
          "**没有** startTile/endTile/duration/ease —— 那是 RecolorTrack 的字段")
    check(e["justThisTile"] is True,
          f"`justThisTile:true`（仅作用于当前方块）：{e['justThisTile']}")
    check(e["trackColorType"] == "Glow" and e["trackStyle"] == "Neon",
          f"{e['trackColorType']} / {e['trackStyle']}")
    check(e["trackColor"] == "000000" and e["secondaryTrackColor"] == "ffffff",
          f"黑底白边：主 {e['trackColor']} / 副 {e['secondaryTrackColor']}")
    check(e["trackTexture"] == "" and e["trackTextureScale"] == 1,
          "带 trackTexture/trackTextureScale（语料里几乎必带）")
    check(all(isinstance(x["floor"], int) for x in rep.events), "floor 是整数")
    # 范围档：整个双押组 ⇒ 薄格 + 剩余格各一条（仍是 justThisTile、一格一条）
    rep2 = CZ.plan(ch, span=CZ.SPAN_GROUP)
    check(rep2.n_events == 20, f"整组档 ⇒ 10 组 × 2 格 = {rep2.n_events} 条")
    check(rep2.max_per_floor == 1, "整组档仍然**一格一条**（不堆叠）")
    check(all(x["justThisTile"] is True for x in rep2.events), "整组档全是 justThisTile")


# ------------------------------------------------------------------ G writer
def G_writer():
    """`core.writer.build_actions` 的接线：事件真的进 actions、整体仍按 floor 有序。"""
    print("\nG writer 接线（actions 里真有 ColorTrack，且按 floor 有序）")
    from core import writer as W

    ch, _pairs = pairs_chart(2, 2)
    rep = CZ.plan(ch)
    ch.meta["color_events"] = list(rep.events)
    acts = W.build_actions(ch)
    kinds = [a["eventType"] for a in acts]
    check(kinds.count("ColorTrack") == 1,
          f"1 条 ColorTrack 进了 actions（2 个双押里每 2 个染 1 个）：{kinds}")
    fl = [int(a["floor"]) for a in acts]
    check(fl == sorted(fl), f"整份 actions 仍按 floor 有序（{fl}）")
    check(ch.meta.get("color_written") == 1 and ch.meta.get("color_out_of_range") == [],
          f"记账：written={ch.meta.get('color_written')} / "
          f"越界={ch.meta.get('color_out_of_range')}")
    # 越界 floor 必须**丢弃并报出来**（不许静默）
    ch2 = _C([180.0] * 3, meta={"color_events": [CZ.make_event(1), CZ.make_event(99)]})
    a2 = W.build_actions(ch2)
    check([x["eventType"] for x in a2].count("ColorTrack") == 1
          and ch2.meta.get("color_out_of_range") == [99],
          f"越界那条被丢弃且记账（{ch2.meta.get('color_out_of_range')}）")


# ------------------------------------------------------------------ H 事件选型
def H_event_choice():
    """★★ 事件选型：**`ColorTrack` + `justThisTile`**（用户 2026-10 两次进游戏实测后定的）。

    第一次反馈：「我期望他是『**设置**轨道颜色』而不是『**重新设置**轨道颜色』，
    后者必须是走过后才展示，起不到提示作用」
    （真因：`RecolorTrack` 是**运行时**按范围扫，`vendor/Re_ADOJAS/.../TileColorManager.ts:542-569`）
    第二次反馈：「去游戏源码里找找『**仅作用于当前方块**』的事件，别抱着你那个『重设轨道颜色』当宝了」
    ⇒ 换成 `ColorTrack`：`scnGame.cs:379-461` 建关时**逐格预演**（⇒ 一出现就是该色），
      `scnGame.cs:447-461` 的 `justThisTile` 为真时**不写回全局状态**（⇒ 只改这一格）。

    ★ 并守一个**用户拿编辑器截图指出过**的坑：几百条事件**不许堆在同一格**
      （否则编辑器里显示「1/500」，根本没法看）。
    """
    print("\nH 事件选型（ColorTrack + justThisTile；且不许堆叠）")
    ch = sample_chart()
    rep = CZ.plan(ch)
    check(all(e["eventType"] == "ColorTrack" for e in rep.events),
          "全部是 ColorTrack（不写 RecolorTrack）")
    check(all(e["justThisTile"] is True for e in rep.events),
          "全部 justThisTile:true ⇒ 只作用当前方块、下一格自动恢复（不用补恢复事件）")
    check(rep.floors == rep.tiles == thin_of(ch)[1::2],
          f"事件就在**被染的那一格**上（{rep.floors[:4]}…）")
    check(rep.max_per_floor == 1,
          f"★ 一格最多 1 条事件（实测 max_per_floor={rep.max_per_floor}）—— **不堆叠**")
    check(len(set(rep.floors)) == len(rep.floors), "事件格互不重复")
    check("ColorTrack" in rep.report_text() and "justThisTile" in rep.report_text(),
          f"人话里写明事件选型：{rep.report_text()[-46:]}")
    check("一格一条" in rep.report_text(), "人话里写明一格一条")


# ------------------------------------------------------------------ I 染色间隔
def I_every_phase():
    """★★ 「换手的意义在于：**只在换的那个格子**进行染色」—— 用户 2026-10 的记号串
    `XOODOOXOODOO`（X=双押 / O=普通格 / **D=染色的那个双押**）。"""
    print("\nI 染色间隔（只在换的那个格子染）")
    ch = sample_chart()
    thin = thin_of(ch)                       # 20 个双押的薄格，按顺序
    rep = CZ.plan(ch)                        # 默认 every=2 / phase=2
    check(rep.tiles == thin[1::2],
          f"默认 = 链内第 2/4/6…个双押（{rep.tiles[:4]}…）")
    check("每 2 个双押染 1 个" in rep.report_text() and "第 2 个" in rep.report_text(),
          f"报告写明间隔与相位：{rep.report_text()[-52:]}")
    rep_a = CZ.plan(ch, color_phase=1)
    check(rep_a.tiles == thin[0::2],
          f"相位改成 1 ⇒ 换成第 1/3/5…个（{rep_a.tiles[:4]}…）")
    check(not (set(rep.tiles) & set(rep_a.tiles)), "两个相位**不相交**（互补）")
    check(sorted(rep.tiles + rep_a.tiles) == sorted(thin),
          "两个相位合起来 = 全部 20 个双押（不多不少）")
    rep_off = CZ.plan(ch, color_every=1)
    check(rep_off.n_events == 20 and "每个双押都染" in rep_off.report_text(),
          f"every=1 ⇒ 全染（{rep_off.n_events} 条）")
    rep3 = CZ.plan(ch, color_every=3)
    check(rep3.n_events == 7 and rep3.tiles == thin[1::3],
          f"every=3 ⇒ 从第 2 个起每 3 个染 1 个（{rep3.n_events} 条，{rep3.tiles[:3]}…）")


def main():
    A_sample()
    B_meta_path()
    C_bounds()
    D_off()
    E_ambiguous()
    F_event_shape()
    G_writer()
    H_event_choice()
    I_every_phase()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 换手押上色全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
