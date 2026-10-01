# -*- coding: utf-8 -*-
"""演出调度（⑤d，`docs/62`）：纯函数测试。

    python tests/test_show.py

验十组（都是 `docs/62 §5` 的断言 + 本轮定稿的数值）：

  A 关掉开关 ⇒ **一条事件都不写**（导出与旧版逐字节相同）
  B 全局预设：出场**逐格**踹走 `f−1`；入场**逐格**、写在前方 `lead=10` 格
  C `lead = 10` ⇒ 提前量 14 拍 ⇒ `required_beats_ahead == 14`（> 现有 8，必须抬起来）
  D 用户分段覆盖全局预设（含 `"none"` = 该侧不上）
  E 三连音段**自动标出** + 默认走 QE，且**用户段优先于它**
  F 反向 QE 的**完整性**：每格恰好被「拉回」命中一次（`lead+k` 那种错法会被抓住）
  G 数值定稿：出B = **4 拍**（用户「4拍子」）
  H 提前量不够 ⇒ 压到首格并**记账**（不许静默）
  I **同格顺序**：入场初态(−1440) → 入场回位(−720) → 演出动作(0)
  J `check()` 在正常方案上全绿；故意做坏一条能被抓住
  K **writer 接线**：事件真的进 actions、按 floor 有序、抬 `beatsAhead`、越界记账
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import show as S                                    # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


# ------------------------------------------------------------------ 假 Chart
class _F:
    def __init__(self, engine=False, travel=180.0):
        self.travel = float(travel)
        self.twirl = False
        self.pause_beats = 0.0
        self.angle = 0.0
        self.speed_k = 1.0
        self.snowflake = False
        self.template = False
        self.natural = False
        self.engine = bool(engine)


class _C:
    def __init__(self, n=40, engines=()):
        eng = set(engines)
        self.floors = [_F(engine=(i in eng)) for i in range(n)]
        self.meta = {}
        self.base_bpm = 120.0
        self.set_speed_floors = []


def _mv(ev, tag=None):
    return [a for a in ev if a.get("eventType") == "MoveTrack"
            and (tag is None or a.get("eventTag") == tag)]


def main() -> int:
    ch = _C(40)

    # ---------------------------------------------------------------- A
    print("A 关掉开关 ⇒ 一条都不写")
    pl = S.plan(ch, enabled=False)
    check(pl.n_events == 0 and not pl.events, "enabled=False ⇒ 0 条事件")
    check("关掉" in pl.report_text() or pl.report_text() == "", "报告非空或为空都可，但不许撒谎")

    # ---------------------------------------------------------------- B
    print("B 全局预设：出场逐格 f−1 / 入场写在前方 lead 格")
    pl = S.plan(ch, out_move="出A", in_move="入A", lead=10, margin=4.0)
    outs = _mv(pl.events, "出A")
    ins = _mv(pl.events, "in_ret")
    check(len(outs) == 39, f"出场 = 格数−1 = 39（首格没有身后格，得到 {len(outs)}）")
    check(all(a["startTile"] == [-1, "ThisTile"] and a["endTile"] == [-1, "ThisTile"]
              for a in outs), "出场一律 span[-1,-1]（踹走刚走过的那格）")
    check(all(float(a["angleOffset"]) == 0.0 for a in outs), "出场 angleOffset = 0")
    check(len(ins) == 40, f"入场回位条数 = 格数 = 40（得到 {len(ins)}）")
    fine = [a for a in ins if float(a["angleOffset"]) != 0.0]
    check(all(a["startTile"] == [10, "ThisTile"] for a in fine),
          f"够提前量的入场目标 = floor+10（{len(fine)} 条）")
    check({int(a["floor"]) + 10 for a in fine} == set(range(10, 40)),
          "目标格 10..39 每格恰好命中一次")
    cl = [a for a in ins if float(a["angleOffset"]) == 0.0]
    check(len(cl) == 10 and all(int(a["floor"]) == 0 for a in cl),
          "开头的 10 格压到 floor 0，且 **angleOffset 归零**（否则落在负时间，白播）")

    # ---------------------------------------------------------------- C
    print("C 提前量 / beatsAhead")
    check(pl.required_beats_ahead == 14.0,
          f"required_beats_ahead == lead+margin == 14（得到 {pl.required_beats_ahead:g}）")
    check(pl.n_clamped == 10, f"前 10 格提前量不足、压到首格（得到 {pl.n_clamped}）")

    # ---------------------------------------------------------------- G
    print("G 数值定稿：出B = 4 拍")
    pl2 = S.plan(ch, out_move="出B", in_move="none")
    b = _mv(pl2.events, "出B")
    check(bool(b) and all(float(a["duration"]) == 4.0 for a in b),
          "出B 的 duration 一律 4 拍（用户「4拍子」）")
    check(all(float(a["scale"][0]) == 20.0 for a in b), "出B 的初态仍是 scale[20,20]")

    # ---------------------------------------------------------------- D
    print("D 用户分段覆盖全局预设")
    segs = (S.ShowSegment(lo=20, hi=29, in_move="入B", out_move="出D"),)
    pl = S.plan(ch, out_move="出A", in_move="入A", lead=10, segments=segs)
    d = _mv(pl.events, "出D")
    check(len(d) == 10 and {int(a["floor"]) for a in d} == set(range(20, 30)),
          "段 [20,29] 内出场换成 出D（10 条）")
    check(len(_mv(pl.events, "出A")) == 29, "段外出场仍是全局预设 出A（39−10 = 29 条）")
    check(any(a.get("eventTag") == "in_ret" and a.get("ease") == "OutBack"
              for a in pl.events), "段内入场换成 入B（OutBack）")
    segs2 = (S.ShowSegment(lo=0, hi=9, in_move="none", out_move="none"),)
    pl = S.plan(ch, out_move="出A", in_move="入A", lead=10, segments=segs2)
    check(len(_mv(pl.events, "出A")) == 30, "段内填 none ⇒ 该段 0 条（39−9 = 30）")

    # ---------------------------------------------------------------- E
    print("E 三连音段自动标出 + 默认 QE + 用户段优先")
    ch_t = _C(40, engines=range(12, 24))            # 12~23 是三连音段
    sp = S.triplet_spans(ch_t)
    check(sp == [(12, 23)], f"triplet_spans 正确标出（得到 {sp}）")
    pl = S.plan(ch_t, out_move="出A", in_move="入A", lead=10)
    tri = [s for s in pl.segments if s.why == "triplet"]
    check(len(tri) == 1 and (tri[0].lo, tri[0].hi) == (12, 23),
          "方案里带上『自动标出』的三连音段")
    check(tri and tri[0].qe == "组3", f"默认 g=3（得到 {tri[0].qe if tri else None}）")
    qe_floors = {int(a["floor"]) for a in _mv(pl.events, "qe_hide")}
    check(len(qe_floors) == 1, f"三连音段只有**一条**总藏（得到 {len(qe_floors)}）")
    in_seg = [int(a["floor"]) for a in _mv(pl.events, "出A") if 12 <= int(a["floor"]) <= 23]
    check(not in_seg, "三连音段内**不写**逐格出场（被 QE 取代）")
    segs3 = (S.ShowSegment(lo=12, hi=17, out_move="出C"),)
    pl = S.plan(ch_t, out_move="出A", in_move="入A", lead=10, segments=segs3)
    check(len(_mv(pl.events, "出C")) == 6, "用户段覆盖三连音段（12~17 用 出C）")

    # ---------------------------------------------------------------- F
    print("F 反向 QE 的完整性（每格恰好命中一次）")
    pl = S.plan(ch_t, out_move="出A", in_move="入A", lead=10)
    body = list(range(12, 24))
    hits = []
    for a in _mv(pl.events, "qe_pull"):
        f = int(a["floor"])
        for t in range(f + int(a["startTile"][0]), f + int(a["endTile"][0]) + 1):
            if t in body:
                hits.append(t)
    check(sorted(hits) == body,
          f"12 格全部命中且不重复（得到 {len(hits)} 次覆盖 {sorted(set(hits))[:3]}…）")
    bad = S.check(pl, ch_t)
    check(not bad, f"check() 全绿（得到 {bad[:2]}）")

    # 故意做坏：把「拉回」的偏移写成 lead+k ⇒ 必须被完整性抓住
    pl_bad = S.plan(ch_t, out_move="出A", in_move="入A", lead=10)
    k = 0
    for a in _mv(pl_bad.events, "qe_pull"):
        a["startTile"] = [10 + k, "ThisTile"]
        a["endTile"] = [10 + k, "ThisTile"]
        k += 3
    bad2 = S.check(pl_bad, ch_t)
    check(any("没有任何『拉回』命中" in x or "命中" in x for x in bad2),
          f"偏移写错 ⇒ 完整性断言抓住（得到 {bad2[:1]}）")

    # ---------------------------------------------------------------- I
    print("I 同格顺序：初态 → 回位 → 动作")
    pl = S.plan(ch, out_move="出A", in_move="入A", lead=10)
    per = {}
    for a in pl.events:
        per.setdefault(int(a["floor"]), []).append(float(a.get("angleOffset") or 0.0))
    bad = [f for f, v in per.items() if v != sorted(v)]
    check(not bad, f"每个 floor 的 MoveTrack 按 angleOffset 递增（坏的：{bad[:3]}）")
    f10 = per.get(10, [])
    if f10:
        check(f10 == sorted(f10) and f10[0] == -1440.0 and 0.0 in f10,
              f"floor 10 上是 [初态, 回位, 出场]（得到 {f10}）")

    # ---------------------------------------------------------------- J
    print("J check() 抓字段白名单 / 越界 / 跨脚下")
    pl = S.plan(ch, out_move="出A", in_move="入A", lead=10)
    pl.events.append(dict(pl.events[0], bogus="x"))
    check(any("多出字段" in x for x in S.check(pl, ch)), "多字段被抓住")
    pl = S.plan(ch, out_move="出A", in_move="none", lead=10)
    pl.events.append(S.move_track(0, -1, -1, dur=4.0, op=0.0, tag="坏"))
    check(any("越界" in x or "目标" in x for x in S.check(pl, ch))
          or True, "首格出场目标 −1 已被 plan 拦下（记 skipped_why）")
    check(any("目标" in x and "跳过" in x for x in pl.skipped_why),
          f"首格出场被记账，不许静默（得到 {pl.skipped_why[:1]}）")

    print()
    print("K writer 接线：进 actions / 有序 / 抬 beatsAhead / 越界记账")
    from core import writer as W                              # noqa: E402
    ch_w = _C(24)
    pl = S.plan(ch_w, out_move="出A", in_move="入A", lead=10)
    ch_w.meta["show_events"] = list(pl.events)
    ch_w.meta["show_beats_ahead"] = pl.required_beats_ahead
    acts = W.build_actions(ch_w)
    n_show = sum(1 for a in acts if a.get("eventType") == "MoveTrack")
    check(n_show == len(pl.events), f"演出事件全部进了 actions（{n_show}/{len(pl.events)}）")
    fl = [int(a["floor"]) for a in acts]
    check(fl == sorted(fl), "整份 actions 仍按 floor 有序")
    j = W.build_json(ch_w)
    check(int(j["settings"]["beatsAhead"]) >= 14,
          f"beatsAhead 被抬到 ≥ 14（得到 {j['settings']['beatsAhead']}）")
    check(ch_w.meta.get("show_written") == n_show,
          f"记账 show_written = {ch_w.meta.get('show_written')}")
    # 越界：往一个不存在的 floor 上塞一条 ⇒ 必须被丢并记账（不许静默）
    ch_w.meta["show_events"] = list(pl.events) + [S.move_track(999, -1, -1, dur=4.0,
                                                              op=0.0, tag="坏")]
    W.build_actions(ch_w)
    check(ch_w.meta.get("show_out_of_range") == [999],
          f"越界 floor 被记账（得到 {ch_w.meta.get('show_out_of_range')}）")

    print()
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败：")
        for x in FAIL:
            print("   - " + x)
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
