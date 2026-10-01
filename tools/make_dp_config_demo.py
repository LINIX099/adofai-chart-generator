# -*- coding: utf-8 -*-
"""**双押配置验收谱**（base 250bpm · ×4 档）—— 用 X/O 记谱写出来的几套常见双押落点。

    python tools\\make_dp_config_demo.py

产物：`out/双押配置验收谱/main.adofai`（每套一个 `EditorComment`）

## 记谱约定（用户 2026-10 定）

```
每一个字符 = 1 格 = 一个 travel-180 平格的时长（×4/base250 下 = 60ms）
  O = 普通格子   → 1 格，travel 180
  X = 双押       → 1 格，两格 [30, 150]      （Σtravel = 180 = 一格，**时值完全一样**）
空格 = 分组，不占时间
```

★ 为什么 1 格 = 60ms：主人的 `out/双押交互.adofai` 解出来是

```
有效单元（5 格）: 30, 150, 180, 180, 180
dt（ms）        : 10,  50,  60,  60,  60       ⇒ 一格 = 60ms
记谱            : X    O    O    O        （4 字符 = 4 格 = 240ms）
```

## ★★ 一条不变量（人类写法之所以"排版不奇怪"，全靠它）

```
一个双押 = 两格 [θ, 180·W − θ]，Σtravel = 180·W
```

⇒ **双押吃掉的时间 = W 个平格的时间，一分不多一分不少**（`docs/31` §2.2.2）。
⇒ 所以**它不会把后面的音推走** —— 这是"塞双押不破坏排版"的全部秘密。
⇒ 但**多出来一格**（2 格 vs 1 格）⇒ 路径会多一个"侧跳"，所以必须

| 求解器规则 | 为什么 |
|---|---|
| ① 双押只能落在**平格**（本来 travel = 180）上 | 落在拐角上会让 Σtravel ≠ 180W，时序就崩 |
| ② **相邻双押必须用相反手性**（Twirl 翻奇偶） | 否则侧跳同向累积 ⇒ 路径一边倒 |
| ③ `θ` 取 15/30/60（薄角），`W` = 双押占几格 | `docs/31` §2.2.2 的统一公式 |

## 这几套配置

用户 2026-10：「你可以按照你的想法先写几个**常见的双押配置**，我去改它们」。
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

BPM = 250.0
MULT = 4.0                        # 段速倍率 ⇒ cbpm = 1000
OUT = os.path.join(_ROOT, "out", "双押配置验收谱")
SEP = "OO"                        # 段间：两格平格
THETA = 30.0                      # 薄角

#: `(编号, 名字, 记谱, 说明)`
CONFIGS = [
    ("1", "每 4 格一个（正拍双押）", "XOOO XOOO XOOO",
     "★ 最常见的那个 —— 也是主人给的例子、`out/双押交互.adofai` 的写法。\n"
     "落在每 4 格的**第一格**上（4/4 的强拍）。"),
    ("2", "每 3 格一个", "OOX OOX OOX",
     "★ 主人给的第二个例子。三格一循环，双押落在**第 3 格**。\n"
     "听感上是 3:4 的交叉（hemiola）。"),
    ("3", "每 2 格一个", "XO XO XO XO XO XO",
     "半小节一个。密度翻倍，是最「老实」的加密方式。"),
    ("4", "4 格两头（对称）", "XOOX XOOX XOOX",
     "4 格一循环、**两头**都是双押 ⇒ 强拍 + 次强拍。\n"
     "比 ① 对称，落点成镜像。"),
    ("5", "正反交错（8 格循环）", "XOOO OOOX XOOO OOOX",
     "一小节正拍、下一小节反拍 ⇒ 8 格一循环。\n"
     "★ 现场效果是「一强一弱」交替，比 ① 有推进感。"),
    ("6", "前两格（4 格循环）", "XXOO XXOO XXOO",
     "双押**背靠背**贴在循环头上。\n"
     "★ 注意：两个 X 相邻 ⇒ 第二对要走**相反手性**（见 §规则②）。"),
    ("7", "后两格（4 格循环）", "OOXX OOXX OOXX",
     "和 ⑥ 镜像：双押贴在循环尾，接下一循环的头 ⇒ 实际是「2 格空 + 2 格密」。"),
    ("8", "全双押（连续）", "XXXX XXXX",
     "★ `docs/31` 的**斜向单元**：两对 `[30,150]` 背靠背 = 每 1 格一个双押。\n"
     "「非常好用的**连续双押**手段」（用户原话）。"),
]


def parse_notation(s: str):
    """X/O 记谱 → `(tiles, twirls, n_ge)`。`tiles[i] = (travel, is_double)`。"""
    chars = [c for c in s if c in "XO"]
    tiles: list[tuple[float, bool]] = []
    twirls: list[bool] = []
    seen_double = False
    for c in chars:
        if c == "O":
            tiles.append((180.0, False))
            twirls.append(False)
        else:
            # ★ 规则②：相邻双押用**相反手性** ⇒ 每个新双押的第一格翻一次奇偶
            #   （第一个不翻 —— 与 `双押交互.adofai` 的 Twirl 落点一致）
            twirls.append(seen_double)
            seen_double = True
            tiles.append((THETA, True))
            tiles.append((180.0 - THETA, True))
            twirls.append(False)
    return tiles, twirls, len(chars)


def build_angles(travels: list[float], twirls: list[bool]) -> list[float]:
    """travel + Twirl → angleData（口径与 `core/path.py` 一致：累积奇偶先翻再算）。"""
    a, ccw = [0.0], False
    for t, tw in zip(travels, twirls):
        if tw:
            ccw = not ccw
        turn = (180.0 - t) if ccw else (t - 180.0)
        v = (a[-1] - turn) % 360.0
        if abs(v - 360.0) < 1e-9:
            v = 0.0
        a.append(v)
    return a


def main() -> int:
    travels: list[float] = [180.0]             # 第 0 层：开局站位
    twirls: list[bool] = [False]
    actions: list[dict] = []
    plan: list[tuple] = []                     # (段号, 名字, 记谱, 格数, 格起, 双押格)
    beat = 60000.0 / BPM
    ge_ms = beat / 4.0                         # ★ 一格 = 60ms（×4 档）

    for cid, name, nota, note in CONFIGS:
        tiles, tws, n_ge = parse_notation(nota)
        start = len(travels)
        travels.extend(t for t, _d in tiles)
        twirls.extend(tws)
        floor = start                        # 这一段的第 1 格（T 里已有站位，故不 +1）
        plan.append((cid, name, nota, n_ge, floor,
                     [i for i, c in enumerate([c for c in nota if c in "XO"]) if c == "X"]))

        # 段速（只发一次）
        if cid == "1":
            actions.append({"floor": floor, "eventType": "SetSpeed",
                            "speedType": "Bpm", "beatsPerMinute": _num(BPM * MULT),
                            "bpmMultiplier": 1, "angleOffset": 0})

        # 分隔（两格平格，顺便把段分开）
        travels.extend([180.0, 180.0])
        twirls.extend([False, False])

        comment = ("【%s】%s\n"
                   "记谱：%s\n"
                   "     （1 字符 = 1 格 = %.1fms；X = 双押 [%g, %g]，O = 平格 [180]）\n"
                   "%s\n"
                   "段长：%d 格 = %.0fms\n"
                   "不变量：Σtravel = 180 × 格数（双押吃掉的时间 = 一个平格）"
                   % (cid, name, nota, ge_ms, THETA, 180.0 - THETA, note,
                      n_ge, n_ge * ge_ms))
        actions.append({"floor": floor, "eventType": "EditorComment",
                        "comment": comment})

    # 收尾
    travels.extend([180.0, 180.0])
    twirls.extend([False, False])
    a = build_angles(travels, twirls)

    s = dict(SETTINGS_TEMPLATE)
    s.update({"bpm": BPM, "offset": 0, "songFilename": "main.ogg",
              "beatsAhead": 3, "beatsBehind": 4,
              "trackDisappearAnimation": "None",
              "countdownTicks": 4, "separateCountdownTime": False,
              "zoom": 200, "hitsoundVolume": 25})
    data = {"angleData": [_num(v) for v in a], "settings": s,
            "actions": actions, "decorations": []}

    # ---------------------------------------------------------- 自检（不许静默）
    errs: list[str] = []
    cbpm = BPM * MULT
    dts = [(t / 180.0) * (60000.0 / cbpm) for t in travels[1:]]
    print("=" * 96)
    print("双押配置验收谱 · base %g bpm · 段速 ×%g（cbpm %g）⇒ **一格 %.2fms**"
          % (BPM, MULT, cbpm, ge_ms))
    print("=" * 96)
    print("记谱约定：1 字符 = 1 格；X = 双押 [%g, %g]（Σ=180）；O = 平格 [180]"
          % (THETA, 180.0 - THETA))
    print()
    ti = 0                                     # dts[0] = travels[1] = 第 1 段的第 1 格
    for (cid, name, nota, n_ge, floor, xs) in plan:
        chars = [c for c in nota if c in "XO"]
        acc, marks = 0.0, []
        for i, c in enumerate(chars):
            if c == "X":
                marks.append(i + 1)
                acc += dts[ti] + dts[ti + 1]
                ti += 2
            else:
                acc += dts[ti]
                ti += 1
        ti += 2                                # 分隔两格
        exp = n_ge * ge_ms
        ok = abs(acc - exp) < 1e-6
        if not ok:
            errs.append("段%s 时长 %0.2f ≠ %0.2f" % (cid, acc, exp))
        print("  【%s】%-22s %s" % (cid, name, nota))
        print("        格数 %-3d 双押落在第 %-16s 段长 %.0fms  %s"
              % (n_ge, "、".join(str(x) for x in marks) + " 格", acc,
                 "✓" if ok else "✗ **对不上**"))
    print()
    bad = [r for r in travels if abs((r / 15.0) - round(r / 15.0)) > 1e-9]
    print("  ★ travel 全部落在 15° 网格上：%s"
          % ("**是 ✓**" if not bad else "**否** —— %s" % sorted(set(bad))))
    print("  ★ 每个双押 Σtravel = %.1f = 180 ⇒ 吃掉的时间与一个平格完全相同 ✓"
          % (THETA + 180.0 - THETA))
    print("  ★ 双押处的 Twirl（相邻双押相反手性）：%d 个"
          % sum(1 for x in twirls if x))
    if errs:
        print("\n✗ 自检失败：")
        for e in errs:
            print("   · " + e)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "main.adofai")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print("\n产物：%s（%d 层）" % (path, len(a)))

    try:
        from core import verify as V
        cum, _ang = V.parse_times(path)
        print("反解（第三方 parser）：%d 层可读 ✓" % len(cum))
    except Exception as exc:                                  # noqa: BLE001
        print("✗ 反解失败：%s: %s" % (type(exc).__name__, exc))
        return 1
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
