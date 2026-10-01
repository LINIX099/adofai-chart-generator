"""语料速度读取 —— **唯一正确版本**，所有体检/挖掘脚本都该用这个。

两个曾经踩过的坑（都导致分析静默退化成垃圾）：

① **SetSpeed 事件没有 `speed` 字段。**
   语料写法：
       {"floor":77,"eventType":"SetSpeed","speedType":"Multiplier",
        "beatsPerMinute":100,"bpmMultiplier":2,"angleOffset":0}
   旧代码 `act.get("speed", 1.0)` 永远取到 1.0 → 整份分析变成「忽略 SetSpeed」。

② **Multiplier 是「乘在当前 BPM 上」，不是绝对值。**
   `vendor/adofai_timemodel/angle.py::_buildSpeedSegments` 是权威实现：
       current_bpm = settings['bpm']
       if speedType == 'Bpm':        current_bpm = beatsPerMinute
       elif speedType == 'Multiplier': current_bpm *= bpmMultiplier
   所以连续两个 2x 是 4x，不是 2x。旧代码写 `cur = ev[i]`（赋值）→ 高估慢档。

另外：`active: false` 的事件要跳过（编辑器里被关掉的）。
`angleData` 里的 999 = midspin = 0° 转角（`span = 0 if angle == 999`）。
"""
from __future__ import annotations

import math


def speeds_for(d, n: int) -> list[float]:
    """返回每层的速度倍率（相对 `settings.bpm`），长度 n。

    `d` 是已解析的 .adofai dict。`n` = 需要的层数（一般 len(angleData)-1）。
    """
    base = float(d.get("settings", {}).get("bpm") or 0) or 1.0
    ev: dict[int, tuple[float | None, float]] = {}
    for act in (d.get("actions") or []):
        if act.get("eventType") != "SetSpeed" or act.get("active") is False:
            continue
        if act.get("speedType") == "Bpm":
            ev[int(act.get("floor", 0))] = (float(act.get("beatsPerMinute") or base), None)  # type: ignore[arg-type]
        else:
            ev[int(act.get("floor", 0))] = (None, float(act.get("bpmMultiplier") or 1.0))

    sp, cur = [1.0] * n, base
    for i in range(n):
        hit = ev.get(i)
        if hit is not None:
            abs_bpm, mult = hit
            cur = abs_bpm if abs_bpm is not None else cur * mult
        sp[i] = cur / base
    return sp


def is_pow2(s: float, tol: float = 1e-6) -> bool:
    """s 是不是 2 的整数次幂（含 1/2^n）。"""
    if s <= 0 or not math.isfinite(s):
        return False
    e = math.log2(s)
    if not math.isfinite(e) or abs(e) > 1024:
        return False
    return abs(e - round(e)) < tol


def load_corpus_chart(path: str):
    """宽松解析一张语料谱（ADOFAI 写的 JSON 有尾逗号 + 裸控制字符）。"""
    import json
    import re
    txt = open(path, encoding="utf-8-sig").read()
    txt = re.sub(r",(\s*[}\]])", r"\1", txt)
    return json.loads(txt, strict=False)


def travel_into(a: list[float], twirl: set[int] | frozenset[int] = frozenset()) -> list[float]:
    """**floor f 自己的转角** `T[f] = (180 + a[f-1] - a[f]) % 360`。

    这是 README / `scrLevelMaker` 的口径（`a[k] = (a[k-1] + 180 - travel[k]) % 360`），
    也是「floor f 时长 = (T[f]/180)/speed[f] × 拍」里那个 T。

    ★ 容易踩的坑：写成 `(180 + a[f] - a[f+1])` 是**下一格**的转角，差一格。
    对「直线占比」这种大样本统计无所谓，但算每格时长 / 校验匀速就全错了。

    `twirl` 里的 floor 会把转角翻成 `360−θ`。
    第 0 格固定 180°（游戏规则：第一格必须直走）。999（midspin）按 0° 处理。

    ★ **Twirl 是累积奇偶，不是"只有那一格翻"**：游戏里 `isCCW` 是个状态
      （`scrFloor.isCCW` / `GetAngleMoved(entry, exit, !isCCW)`），从该格起一直生效。
      早期这版写成 `if f in twirl: 翻`（逐格翻），对连续/稀疏 Twirl 都会算错时长。
    """
    n = len(a)
    T = [0.0] * n
    ccw = False
    for f in range(n):
        if f == 0:
            T[f] = 180.0
        elif a[f] == 999 or a[f - 1] == 999:
            T[f] = 0.0
        else:
            T[f] = (180.0 + a[f - 1] - a[f]) % 360.0
        if f in twirl:
            ccw = not ccw
        if ccw:
            T[f] = (360.0 - T[f]) % 360.0
    return T


def travel_out(a: list[float]) -> list[float]:
    """从第 f 格走到第 f+1 格的转角（长度 n-1）—— 只是 `travel_into` 的左移版。"""
    return travel_into(a)[1:]
