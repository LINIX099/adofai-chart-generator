# -*- coding: utf-8 -*-
"""读**一份**重型特效谱的演出时间轴：AnimateTrack 变迁 + MoveTrack 配方 + 逐格窗口。

    python tools/show_timeline.py <chart.adofai> [--window 起点 终点] [--top 12]

为什么需要它：`analyze_show_events.py` 给的是**全语料统计**，看得出"用了多少"，
看不出"**他们到底怎么写的**"。这个工具是逐谱取证用的：

  §1 `AnimateTrack` 变迁表 —— 每一次"轨道出现/消失风格"的切换点（= 入场离场风格切换）
  §2 `MoveTrack` 配方聚类 —— 相同写法的归成一类，看哪几种是套路
  §3 **按作用范围分类**：动"未来的格"（入场）/ 动"踩过的格"（离场）/ 只动脚下
  §4 逐格时间轴（给了 `--window` 才打）

★ 范围一律换算成**绝对格号**再分类，避免 `ThisTile` 相对偏移看花眼。
"""
from __future__ import annotations

import collections
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.analyze_show_events import load, travel_series, shape_of   # noqa: E402

WATCH = ("MoveTrack", "AnimateTrack", "PositionTrack", "MoveDecorations",
         "MoveCamera", "Flash", "RepeatEvents")


def span_of(a: dict, floor: int) -> tuple[int, int]:
    """作用范围的**绝对格号**。

    ★ `startTile`/`endTile` 的第二个值是锚点：`"ThisTile"` = 相对触发格，
      `"Start"` = **绝对格号**（游戏里走 `IDFromTile`）。两者可混用。
      （2026-09-18 修正：原先把 `"Start"` 也按相对算，把 Hello 2024 floor 774 的
       `[892,"Start"]` 算成了 774+892。）
    """
    def _i(key, dflt):
        v = a.get(key)
        if isinstance(v, list) and v:
            try:
                n = int(v[0])
            except Exception:                                  # noqa: BLE001
                return dflt
            anchor = v[1] if len(v) > 1 else "ThisTile"
            return n if anchor == "Start" else floor + n
        return dflt
    return _i("startTile", -1), _i("endTile", 0)


def kind_of(a: dict, floor: int) -> str:
    lo, hi = span_of(a, floor)
    if lo > hi:
        lo, hi = hi, lo
    if hi < floor:
        return "离场(踩过的)"
    if lo > floor:
        return "入场(未来的)"
    if lo == hi == floor:
        return "只动脚下"
    return "跨过脚下"


def recipe_sig(a: dict, floor: int) -> str:
    lo, hi = span_of(a, floor)
    if lo > hi:
        lo, hi = hi, lo
    fields = "+".join(k for k in ("positionOffset", "rotationOffset", "scale", "opacity")
                      if k in a) or "-"
    span = f"{lo - floor}..{hi - floor}"
    cover = ""
    if hi < floor:
        cover = f"回看{floor - hi}"
    elif lo > floor:
        cover = f"前瞻{lo - floor}"
    return (f"{cover:<8} span={span:<10} fields={fields:<46} "
            f"dur={a.get('duration')} ease={a.get('ease')} gap={a.get('gapLength', 0)}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    path = argv[0]
    win = None
    top = 12
    rest = argv[1:]
    for i, x in enumerate(rest):
        if x == "--window" and i + 2 < len(rest):
            win = (int(rest[i + 1]), int(rest[i + 2]))
        elif x == "--top" and i + 1 < len(rest):
            top = int(rest[i + 1])

    j = load(path)
    st = j.get("settings", {}) or {}
    acts = [a for a in (j.get("actions") or []) if isinstance(a, dict)]
    tv = travel_series(j.get("angleData") or st.get("angleData") or [])
    print("=" * 100)
    print(f"{path}")
    print(f"  version={st.get('version')} bpm={st.get('bpm')} 格数={len(tv)} 事件={len(acts)}")

    # ---------- §1 AnimateTrack 变迁 ----------
    print("\n" + "-" * 100)
    print("§1 AnimateTrack 变迁（轨道出现/消失风格的切换点）")
    print("-" * 100)
    anim = sorted([a for a in acts if a.get("eventType") == "AnimateTrack"],
                  key=lambda a: int(a["floor"]))
    c = collections.Counter()
    last = None
    for a in anim:
        c[(a.get("trackAnimation"), a.get("trackDisappearAnimation"))] += 1
    print(f"  全谱 {len(anim)} 条；风格组合分布：")
    for k, v in c.most_common(10):
        print(f"    出现={k[0]!r} 消失={k[1]!r}  ×{v}")
    print(f"  前 25 个切换点：")
    for a in anim[:25]:
        sig = (a.get("trackAnimation"), a.get("beatsAhead"),
               a.get("trackDisappearAnimation"), a.get("beatsBehind"))
        mark = "" if sig != last else "   (同前)"
        last = sig
        print(f"    floor {int(a['floor']):>6}  出现={sig[0]!r}/{sig[1]}拍  "
              f"消失={sig[2]!r}/{sig[3]}拍{mark}")

    # ---------- §2/§3 MoveTrack ----------
    mv = sorted([a for a in acts if a.get("eventType") == "MoveTrack"],
                key=lambda a: int(a["floor"]))
    rec: collections.Counter = collections.Counter()
    sample: dict[str, dict] = {}
    bykind: collections.Counter = collections.Counter()
    kindsamples: dict[str, dict] = {}
    for a in mv:
        f = int(a["floor"])
        sig = recipe_sig(a, f)
        rec[sig] += 1
        sample.setdefault(sig, a)
        k = kind_of(a, f)
        bykind[k] += 1
        kindsamples.setdefault(k, a)
    print("\n" + "-" * 100)
    print(f"§2 MoveTrack 配方（共 {len(mv)} 条，top {top}）")
    print("-" * 100)
    for sig, n in rec.most_common(top):
        print(f"  ×{n:<6} {sig}")
        print(f"          {json.dumps(sample[sig], ensure_ascii=False)}")
    print("\n" + "-" * 100)
    print("§3 按作用范围分类")
    print("-" * 100)
    for k, n in bykind.most_common():
        print(f"  {k:<14} ×{n:<7} 例：{json.dumps(kindsamples[k], ensure_ascii=False)}")

    # 入场事件：动的是**未来**的格
    enter = [a for a in mv if kind_of(a, int(a["floor"])) == "入场(未来的)"][:12]
    if enter:
        print("\n  ★ 动「未来的格」的前 12 条（= 入场动作的写法）：")
        for a in enter:
            f = int(a["floor"])
            lo, hi = span_of(a, f)
            print(f"    floor {f:>6} 作用 {lo}..{hi}  {json.dumps(a, ensure_ascii=False)}")
    exit_ = [a for a in mv if kind_of(a, int(a["floor"])) == "离场(踩过的)"][:12]
    if exit_:
        print("\n  ★ 动「踩过的格」的前 12 条（= 离场动作的写法）：")
        for a in exit_:
            f = int(a["floor"])
            lo, hi = span_of(a, f)
            print(f"    floor {f:>6} 作用 {lo}..{hi}  {json.dumps(a, ensure_ascii=False)}")

    # ---------- §4 逐格窗口 ----------
    if win:
        a0, b0 = win
        print("\n" + "-" * 100)
        print(f"§4 逐格时间轴  格 {a0} .. {b0}")
        print("-" * 100)
        byfloor: dict[int, list[dict]] = collections.defaultdict(list)
        for a in acts:
            byfloor[int(a.get("floor", -1))].append(a)
        for f in range(a0, b0 + 1):
            tl = tv[f] if 0 <= f < len(tv) else float("nan")
            head = f"  {f:>6} [{shape_of(tl):<4}]"
            evs = [a for a in byfloor.get(f, []) if a.get("eventType") in WATCH]
            if not evs:
                print(head)
                continue
            for a in evs:
                et = a["eventType"]
                if et == "MoveTrack":
                    lo, hi = span_of(a, f)
                    body = (f"作用{lo}..{hi} dur={a.get('duration')} "
                            f"ease={a.get('ease')} "
                            + " ".join(f"{k}={a[k]}" for k in
                                       ("positionOffset", "rotationOffset", "scale",
                                        "opacity", "angleOffset") if k in a))
                elif et == "MoveDecorations":
                    body = (f"tag={a.get('tag')!r} dur={a.get('duration')} "
                            f"{' '.join(f'{k}={a[k]}' for k in ('positionOffset', 'scale', 'opacity', 'visible') if k in a)}")
                elif et == "AnimateTrack":
                    body = (f"出现={a.get('trackAnimation')!r}/{a.get('beatsAhead')}拍 "
                            f"消失={a.get('trackDisappearAnimation')!r}/{a.get('beatsBehind')}拍")
                elif et == "PositionTrack":
                    body = f"offset={a.get('positionOffset')} justThisTile={a.get('justThisTile')}"
                elif et == "MoveCamera":
                    body = (f"rel={a.get('relativeTo')} pos={a.get('position')} "
                            f"rot={a.get('rotation')} zoom={a.get('zoom')} "
                            f"dur={a.get('duration')} ease={a.get('ease')}")
                elif et == "RepeatEvents":
                    body = (f"{a.get('repeatType')} interval={a.get('interval')} "
                            f"rep={a.get('repetitions')} tag={a.get('tag')!r}")
                else:
                    body = json.dumps({k: v for k, v in a.items()
                                       if k not in ("floor", "eventType")},
                                      ensure_ascii=False)
                print(f"{head} {et:<16} {body}")
                head = " " * 9
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
