# -*- coding: utf-8 -*-
"""**节奏型验收谱**（BPM 250）—— 从 Flower Rocket 参考谱里挖出来的「人类的排版写法」。

    python tools\\make_rhythm_demo.py

产物：`out/节奏型验收谱/main.adofai`

## 为什么做这个

用户 2026-10 看了补格产物（`out/flower_fill`，一对一 76.2%）之后：

> 「**采音很不错**，但是我觉得**排版过于灾难性了**。你可以看到它**几乎完全糊成一团**，
>   我建议你去看参考谱找找**相同的节奏型人类会怎么写**，然后挑几个（4~7）你觉得典型的
>   出来，**根据时值推测其乐理对应的节奏型**并写出**检验谱面**供我确认（**bpm250**）。
>   我们把他们作为**新的一批模板**」

## 挖出来的病根（实测，参考谱 2543 格 vs 我们 2504 格）

| | 参考谱（人类） | 我们（补格后） |
|---|---|---|
| 段 bpm | **920(×4) 52.6%** · 460(×2) 20.7% · 230(×1) 14.8% | **230(×1) 91.1%** |
| 最常见的格 | **×4 + travel 180**（594 次） | **×1 + travel 22.5**（745 次） |
| travel 取值种类 | **19 种，全是 15° 的整数倍** | 150 种，含 22.5 / 67.5 / 157.5 |

★ **`travel ∈ {22.5, 67.5, 112.5, 157.5}` 在参考谱里出现 0 次** —— 人类只用 15° 网格。

## ★★ 一条公式（全部 19 种取值都符合）

```
travel = 180 × 速度倍数 × 音值          （音值 = 这一格占几拍；1 拍 = 60000/base_bpm）
```

⇒ **想变快就抬 SetSpeed 档，而不是在原档位缩小 travel。**
同一个 1/8 拍（三十二分音符）：

* `倍数=1` ⇒ travel **22.5°** ← ✗ 不在 15° 网格上，人类**从不写**（这就是我们糊掉的形状）
* `倍数=4` ⇒ travel **90°** ← ✓ 参考谱 166 次
* `倍数=8` ⇒ travel **180°** ← ✓ 参考谱 84 次（而且**是直线**）

## 验的这 6 段

每段一个 `EditorComment` 写清编号 / 乐理名 / travel / 记谱 / 结论，段间用 `PositionTrack` 错开。
**Twirl 一律不摆**（照抄 `patterns/README.md` 的约定）。
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core.writer import SETTINGS_TEMPLATE, _num                # noqa: E402

BPM = 250.0                       # ★ 用户指定
OUT = os.path.join(_ROOT, "out", "节奏型验收谱")
SEP = 180.0                       # 段间：一格直线
SHIFT = (0.0, 3.0)                # 每段用 PositionTrack 往下错开（`patterns/README.md` 的约定）

#: 参考谱实测的「同款频次」——注释里带上，方便对照
EVIDENCE = {
    "x4_180": "参考谱 ×4/180 = 594 次（**第一主力**）",
    "x2_90": "参考谱 ×2/90 = 56 次 · ×1/90 = 132 次",
    "x4_30_150": "参考谱 30·150 = 182 次 · 150·30 = 108 次",
    "x4_90": "参考谱 ×4/90 = 166 次（三十二分直角）",
    "x8_180": "参考谱 ×8/180 = 84 次（三十二分**直线**）",
    "x1_30": "参考谱 ×2/30 = 187 次 · ×1/60 = 38 次 · ×1/15 = 62 次",
}


def build_angles(T: list[float]) -> list[float]:
    """travel → angleData（与 `core/path.py::turn_of` 同一套：转角 = 180 − travel，逆时针）。"""
    a = [0.0]
    for t in T:
        v = (a[-1] + 180.0 - t) % 360.0
        if abs(v - 360.0) < 1e-9:
            v = 0.0
        a.append(v)
    return a


def notation(travels: list[float], unit_deg: float = 15.0) -> str:
    """`1 字符 = 15°` 的记谱（`patterns/README.md` 的约定）。"""
    out = []
    for t in travels:
        k = int(round(t / unit_deg))
        out.append("X" + "·" * (k - 1))
    return "".join(out)


def frac_name(v: float) -> str:
    """音值 → 人看得懂的名字（`v` = 占几拍）。"""
    for den, name in ((1.0, "四分"), (0.5, "八分"), (0.25, "十六分"),
                      (0.125, "三十二分"), (1 / 6, "十六分三连"),
                      (1 / 12, "三十二分三连"), (1 / 3, "八分三连"),
                      (5 / 24, "5/24 拍"), (1 / 24, "1/24 拍")):
        if abs(v - den) < 1e-6:
            return name
    if abs(v - round(v)) < 1e-9 and v >= 1:
        return "%g 拍" % v
    return "%.5g 拍" % v


# ============================================================ 六段
#: `(编号, 乐理名, [(速度倍数, travel), ...], 备注, 参考谱证据键)`
CELLS = [
    ("1", "匀速十六分 · 直线",
     [(4.0, 180.0)] * 8,
     "一串**十六分音符**连打（×4 档下 travel 180 = 1/4 拍 = 一个十六分）。\n"
     "形状：一条直线（转角全 0）。参考谱的第一主力写法。",
     "x4_180"),

    ("2", "匀速十六分 · 直角阶梯",
     [(2.0, 90.0)] * 8,
     "同样是一串**十六分音符**（×2 档下 travel 90 = 1/4 拍），\n"
     "但每格转 +90° ⇒ 走成阶梯 / 方波。参考谱 `90·90` 连写 101 次。",
     "x2_90"),

    ("3", "十六分「一摆」",
     [(4.0, 30.0), (4.0, 150.0)] * 4,
     "把一个**十六分音符**（60ms）切成 `1/24 + 5/24 = 1/4 拍`：\n"
     "  第 1 格 travel 30 ⇒ 转角 +150°（几乎回头）\n"
     "  第 2 格 travel 150 ⇒ 转角 +30°（收回来）\n"
     "两格转角之和 = **180°** ⇒ 第 2 格的落点**正好回到第 1 格的出发点** —— 一个来回。\n"
     "位置不动、时值照吃 ⇒ 这就是人类「密集但不铺开」的手法。",
     "x4_30_150"),

    ("4", "十六分「双摆」（对摆）",
     [(4.0, 30.0), (4.0, 150.0), (4.0, 150.0), (4.0, 30.0)] * 2,
     "两个摆**反向相接**：`+150/+30` 然后 `+30/+150`。\n"
     "参考谱 `30·150·30` / `150·30·150` 各 95 次 —— 它的摆动手法。",
     "x4_30_150"),

    ("5", "三十二分：直角 vs 直线（★ 本谱重点）",
     [(4.0, 90.0)] * 4 + [(8.0, 180.0)] * 4,
     "同一个**三十二分音符**（30ms），两种写法：\n"
     "  前 4 格 ×4 档 + travel 90（直角）  ← 参考谱 166 次\n"
     "  后 4 格 ×8 档 + travel 180（**直线**）← 参考谱 84 次\n"
     "两者墙钟**完全一样**。人类**从不**用 ×1 档 + travel 22.5 写这一档 ——\n"
     "那正是我们补格糊掉的原因（22.5° 不在 15° 网格上）。",
     "x4_90"),

    ("6", "三连家族（同一个 travel，抬档就变快）",
     [(1.0, 30.0)] * 3 + [(1.0, 60.0)] * 3 + [(2.0, 30.0)] * 3,
     "· ×1 + travel 30 = **1/6 拍** = 十六分三连（40ms）\n"
     "· ×1 + travel 60 = **1/3 拍** = 八分三连（80ms）\n"
     "· ×2 + travel 30 = **1/12 拍** = 三十二分三连（20ms）\n"
     "★ 注意后两行：**travel 从 60 变成 30、同时抬一档 ⇒ 时长减半、形状不变**。\n"
     "参考谱 travel 30 出现 460 次 —— 它的三连全靠这一档。",
     "x1_30"),
]


def main() -> int:
    T: list[float] = [180.0]                  # 第 0 层：开局站位
    actions: list[dict] = []
    rows: list[tuple] = []
    beat = 60000.0 / BPM

    for cid, mus, cells, note, ev in CELLS:
        start = len(T)
        travels = [t for _m, t in cells]
        T.extend(travels)
        T.append(SEP)
        floor = start + 1                     # onset 下标 → floor（第 0 层是站位）

        # 段速：**只在倍数变化处**发 SetSpeed（人类谱都这样）
        prev = None
        for i, (m, _t) in enumerate(cells):
            if m != prev:
                actions.append({"floor": floor + i, "eventType": "SetSpeed",
                                "speedType": "Bpm",
                                "beatsPerMinute": _num(BPM * m),
                                "bpmMultiplier": 1, "angleOffset": 0})
                prev = m

        lines = []
        for i, (m, t) in enumerate(cells):
            v = (t / 180.0) / m
            ms = v * beat
            lines.append("      ×%-2g travel %5.1f°  转角 %+6.1f°  ⇒ %6.2fms"
                         "（%g 拍/拍 = %s）" % (m, t, 180.0 - t, ms, v, frac_name(v)))
            rows.append((cid, t, m, ms, v))

        comment = ("【%s】%s\n"
                   "travel：%s\n"
                   "记谱（1 字符 = 15°）：%s\n"
                   "%s\n"
                   "参考谱同款：%s\n"
                   "形状：\n%s\n"
                   "（Twirl 待摆）"
                   % (cid, mus,
                      " · ".join("%g°@×%g" % (t, m) for m, t in cells),
                      notation(travels), note, EVIDENCE[ev], "\n".join(lines)))
        actions.append({"floor": floor, "eventType": "EditorComment",
                        "comment": comment})
        actions.append({"floor": floor, "eventType": "PositionTrack",
                        "positionOffset": list(SHIFT),
                        "relativeTo": [0, "ThisTile"],
                        "justThisTile": False, "editorOnly": False})

    T.append(SEP)                              # 收尾
    a = build_angles(T)

    s = dict(SETTINGS_TEMPLATE)
    s.update({
        "bpm": BPM, "offset": 0, "songFilename": "main.ogg",
        "beatsAhead": 3, "beatsBehind": 4,
        "trackDisappearAnimation": "None",
        "countdownTicks": 4, "separateCountdownTime": False,
        "zoom": 200, "hitsoundVolume": 25,
    })
    data = {"angleData": [_num(v) for v in a], "settings": s,
            "actions": actions, "decorations": []}

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "main.adofai")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

    # ---------------------------------------------------------- 自检
    print("=" * 96)
    print("节奏型验收谱 · BPM %g ⇒ 一拍 %.2fms" % (BPM, beat))
    print("=" * 96)
    print("层数 %d（%d 段 + 站位 + 分隔 + 收尾）" % (len(a), len(CELLS)))
    print()
    cur = None
    for cid, t, m, ms, v in rows:
        if cid != cur:
            cur = cid
            name = next(c[1] for c in CELLS if c[0] == cid)
            print("  ── 段 %s · %s" % (cid, name))
        print("     ×%-2g travel %6.1f°  转角 %+7.1f°  %7.2fms  = %-12s  %s"
              % (m, t, 180.0 - t, ms, frac_name(v), notation([t])))
    print()
    bad = [r for r in rows if abs((r[1] / 15.0) - round(r[1] / 15.0)) > 1e-9]
    print("  ★ travel 全部落在 15° 网格上：%s"
          % ("**是 ✓**" if not bad else "**否** —— 违规 %d 个：%s"
             % (len(bad), [r[1] for r in bad])))
    print("  ★ 用到的音值（拍）：%s"
          % " · ".join(sorted({frac_name(r[4]) for r in rows})))
    print("  ★ 段速：%s" % " · ".join(sorted({("×%g" % r[2]) for r in rows})))
    print()
    print("产物：%s" % path)
    print("对照：参考谱 travel 只有 19 种取值、全是 15° 整数倍；"
          "22.5 / 67.5 / 157.5 **一次都没出现**。")

    # ---------------------------------------------------------- 反解校验
    try:
        from core import verify as V
        cum, _ang = V.parse_times(path)
        print("\n反解（第三方 parser）：%d 层可读 ✓" % len(cum))
    except Exception as exc:                                  # noqa: BLE001
        print("\n✗ 反解失败：%s: %s" % (type(exc).__name__, exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
