# -*- coding: utf-8 -*-
"""**迭代 2**：把 `Sinkhole` 的运镜重写成两段不同写法，产出 `level2.adofai`。

    python tools\\apply_camera_gs2.py [--report] [--tail-mode progress|truncate]

用户 2026-10 的两条要求（原话）：

> 1 **少用甩尾运镜，尽可能用柔和的运镜**
> 2 **1777 格子后面的段落，全部使用国士无双中 3080 格子之后的写法。
>    具体怎么写你要联系两个谱面里面相似的配置**

---

## ★ 两个谱面里「相似的配置」在哪（这是本轮的核心发现）

| | 国士無双 | Sinkhole 非特效版 |
|---|---|---|
| `settings.bpm` | **340** | **900**（乐句 bpm 见特效版 = 225） |
| `settings.position` | `[0, 2]` | **`[0, 1]`** |
| `settings.zoom` | **300** | **250** |
| 被抄的那一段 | **`3080..4084`**（1005 格 / **38.8 s**） | **`1777..2664`**（888 格 / **37.2 s**） |
| 那一段的 `cur` | **恒定 `1360`**（= 4 × base） | **恒定 `900`**（= 1 × base） |
| 那一段的 travel | 180/90/30/60 为主 | 180/90/30/60 为主 |
| 两段在整谱里的位置 | 最后一个变速点之后，直到结束 | **最后一个变速点之后，直到结束** |

**对应关系（本工具用的）**：

1. **静止位同一个值**：国士 3080+ 的回归位是 **`pos=[0,1]`**（它自己的 base 是 `[0,2]`），
   而 Sinkhole 的 `settings.position` **正好也是 `[0,1]`** ⇒ **位置可以原样搬**（单位都是格）。
2. **缩放按基准位比例搬**：`250 / 300 = 0.8333`。
   （国士那一套是在 base 300 上写的；不换算就会整体偏远。）
3. **时值按 `base` 比例搬**：`900 / 340 = 2.647`。
   `MoveCamera.duration` 的单位是**拍**、拍长只由 base 决定 ⇒ 乘这个比例**墙上时长不变**，
   动作的快慢观感才和国士一致。
4. **落点**：两段都是「最后一个变速点之后的收尾长段」，而且**墙上时长几乎一样**
   （**38.8 s vs 37.2 s**）⇒ 按**段内进度**对齐基本就是 1:1 对齐。

---

## 两段写法

### 前段 `0..1776` —— 国士两层，但**换成柔和档**（要求 1）

配方与 `tools/apply_camera_gs.py`（v3）**逐字相同**，只把 ease 换掉：

| | v3（照抄国士） | **迭代 2（柔和档）** |
|---|---|---|
| 宏观 · 长锚 | `OutExpo`（起手极快） | **`OutCubic`** |
| 宏观 · 弹回 | `OutCirc`（起手猛） | **`OutSine`** |
| 微观 | `OutElastic`（**末尾过冲 = 甩尾**） | **`OutSine`** |

### 后段 `1777..2664` —— 国士 `3080..4084` 的写法（要求 2）

国士 3080+ 换了**完全不同**的一套（实测 465 条里）：

* `relativeTo`：**`Player` 348 条**（前段那种 `Tile` 微观**没了**），`Tile` 74、`LastPositionNoRotation` 16；
* `ease`：**`OutSine` 137 · `Linear` 125 · `InSine` 53 · `InCubic` 48 · `OutCubic` 40 ·
  `OutCirc` 31 · `OutQuad` 26** —— ★ **一条 `OutElastic` 都没有**，也没有 `OutExpo` / `InBack`；
* `duration`：`0`（148）/ **`2`（163）** / `1`（69）/ `4`（26）/ `8`…
* 反复出现的四个动机：
  * **呼吸对**：`[-1,2] zoom 180 rot −3 OutSine` → `[0,1] zoom 160 rot 4 InSine`（各 2 拍）；
  * **大摆**：`[-4,4] zoom 270 rot −3 OutCubic` → `[0,0] zoom 200 rot 4 InCubic`（各 4 拍）；
  * **硬切点拨**：`dur=0 zoom 140 Linear` → `zoom 235 OutSine`（1 拍）→ `zoom 160 InSine`（1 拍）；
  * **正弦呼吸链**：`dur=0 zoom 140` → `1 拍 zoom 180/212 OutSine` → `1 拍 pos=[±1,1] zoom 160 InSine`；
* 回归位永远是 **`pos=[0,1]`**。

本工具**逐条搬**这 465 条，只做上面那三处换算（位置原样 / 缩放 ×0.8333 / 时值 ×2.647）。

★ **不许静默**：国士那一套里有 `relativeTo: null`、`position: [null,null]`、`zoom: 0` 这些
「不改」写法 —— 本项目不许留空（`docs/64` §8.6.5 的 v1 黑屏就是 `zoom: null` 造成的），
所以这里**模拟运行状态把空位补实**，并把补了多少、`zoom ≤ 0` 遇到几条全部打出来。
"""
import argparse
import bisect
import json
import math
import os
import shutil
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

import analyze_camera_cur as ACC                              # noqa: E402
import apply_camera_gs as A1                                  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

GUKSU = CORPUS + r"\Laur_-_国士無双\Done.adofai"
SINKHOLE = CORPUS + r"\Sinkhole - Plum\level.adofai"

#: Sinkhole 从这一格起换成「国士 3080+ 的写法」（用户点名的格号）。
TAIL_FROM = 1777
#: 国士从这一格起是被抄的那一段（用户点名的格号）。
GS_TAIL_FROM = 3080
#: 缩放下限 —— 国士那一套里有 `zoom 0 / 1 / 12 / 25` 这种「怼到脸上」的值，
#: 既是**甩尾**又贴着本项目「`zoom` 永不为 0」的红线，所以**抬到 100**并计数报告。
ZOOM_LO = 100.0
#: 贴 tag 用（可追溯；国士原文没有 tag）。
TAG = "gs2_"

# ============================================================ ★ 「呼吸 + 漂移」
#: 用户 2026-10（迭代 2.1 的口径，原话）：
#:
#: > 「我原始的想法是，从 1777 到加速段结束，**完整使用优秀的、呼吸+漂移的镜头调度**。
#: >   目前的镜头使用中有些地方的**位移明显用力过猛**了，而**并不需要如此频繁**
#: >   （国士无双里面也没有如此频繁且僵硬的使用）」
#:
#: 实测对照（国士 `3080..4084` vs 迭代 2 的后段）—— **1:1 搬过来，密度一模一样**：
#:
#: | | 国士 3080+ | 迭代 2 后段 |
#: |---|---|---|
#: | 改变位置的条数 | 5.39 条/秒 | 5.65 条/秒 |
#: | 平均位移 | 1.68 格 | 1.67 格 |
#: | 位移总量 | 9.04 格/秒 | 9.45 格/秒 |
#: | 硬切（`dur=0`） | 3.71 条/秒 | 3.87 条/秒 |
#: | 位置**完全静止**最长 | 4.59 s | 4.41 s |
#:
#: ⇒ 所以「太频繁 / 用力过猛」不是搬歪了，是**国士那一段本身就是离散的密集位移**
#:   （平均一跳 1.67 格、每秒 5.65 次），而且还夹着每秒 3.87 次硬切。
#:   要的是**连续的慢漂**，不是离散的跳。
#:
#: ⇒ `drift_tail()` 用三层合成，**每条事件同时带三层的结果**（ADOFAI 的一条
#:   `MoveCamera` 会把**所有**维度补间到它自己的目标值，所以"一层一条"是行不通的）：
#:
#: 1. **漂移层**（慢 · 连续 · **永不停**）—— 两个不同周期的正弦叠加，x / y / 旋转各一组；
#: 2. **呼吸层**（缩放）—— 慢基线 ± 每拍交替的呼吸，照抄国士「一涨一落」的动机；
#: 3. **网格**：每 `STEP_BEATS` 拍一条、每条 `DUR_BEATS` 拍 ⇒ **2× 重叠，永不静止**。
#:
#: 期望效果：**画面一直在慢慢动，但一次都不猛**（ease 全部 `InOutSine`，零过冲、零硬切）。
DRIFT_NOTE = "呼吸 + 漂移"
#: ★★ **这套调度已定稿为公式** —— 用户 2026-10：
#: 「level2.2 的长镜头**非常好**，可以把**公式梳理出来了**。以后这个就是
#:  **轮指、采bpm** 这种场景主要使用的镜头调度方案」
#: ⇒ 公式全文（记法 / 常数 / 不变量 / 场景映射 / 跨谱面换算）见
#:   **`docs/70-镜头调度公式（呼吸+漂移+聚焦）.md`**。
#:   改这里的常数**必须同步改 `docs/70`**（那边是规格，这边是参考实现）。
#: 漂移层：`(周期秒, 幅度, 相位)` 列表，**叠加**。
DRIFT_X = ((13.0, 1.00, 0.00), (7.3, 0.50, 1.70))
DRIFT_Y = ((11.0, 0.80, 0.90), (6.1, 0.40, 2.40))
DRIFT_ROT = ((17.0, 4.0, 0.40), (9.0, 2.0, 2.10))
#: 缩放：慢基线（`ZOOM_MID ± ZOOM_SLOW_A`，周期 `ZOOM_SLOW_P` 秒）叠呼吸（`±BREATH_AMP`）。
ZOOM_MID = 220.0
ZOOM_SLOW_P = 15.0
ZOOM_SLOW_A = 45.0
ZOOM_BREATH_AMP = 0.11
#: 网格：每 `STEP_BEATS` 拍一条、每条 `DUR_BEATS` 拍。
#: ★ `DUR = 2 × STEP` ⇒ 任意时刻都有两条补间在跑 ⇒ **镜头永远在动、永不静止**。
STEP_BEATS = 8.0
DUR_BEATS = 16.0
DRIFT_EASE = "InOutSine"

# ============================================================ ★★ 2.2：折弯段聚焦 + 结尾聚焦球
#: 用户 2026-10（迭代 2.2，配一张编辑器截图）：
#:
#: > 「对于这样**连续 90° 折弯循环**的结构，可以适当**聚焦镜头**」
#: > 「迭代 2.2，**结尾速度完全降下来之后，聚焦到球本身**」
#:
#: 截图认出来是 **Sinkhole 结尾那一段**（实测）：
#:
#: ```
#: 格 2560..2647（4 个循环，137.6 ~ 140.8 s）
#:   travel: 30, 60, 90, 90, 90, 90, 90, 90, 90   ← 一个循环 9 格
#:   Twirl : .   .   .   T   .   T   .   T   .     ← 7 个 90 里隔一个一个
#: ```
#: （1075..1080 还有一小段。）之后 2650 速度掉到 450、2664 掉到 112.5。
#:
#: ★ 用户选的口径是「**温柔一点，只拉近到 190~210 并轻摆**」—— **不换帧**
#:   （仍然是 `Player`），只把缩放收窄 + 加一点旋转轻摆。
#:   （本谱基准位是 `zoom 250`，所以 190~210 就是「拉近一点」。）
STAIR_MIN_TURNS = 4            #: 连续折点数 ≥ 这个才算「折弯循环」
STAIR_GAP_MERGE = 40           #: 两串之间 ≤ 这么多格就并成一个「聚焦区」
STAIR_RAMP_TILES = 6           #: 聚焦区的边缘渐变宽度（格）
FOCUS_ZOOM_MID = 200.0         #: 聚焦时的缩放中位（用户在 190~210 之间点的）
FOCUS_ZOOM_AMP = 9.0           #: 聚焦时残留的轻微呼吸
FOCUS_ROT_DEG = 4.0            #: 聚焦时的旋转轻摆幅度（度）
FOCUS_ROT_PERIOD = 3.2         #: 轻摆周期（秒）
FOCUS_DRIFT_GAIN = 0.35        #: 聚焦时漂移幅度压到这么多（不然「聚焦」会晃）
END_ZOOM = 150.0               #: 结尾「聚焦到球本身」的缩放
END_BREATH = 4.0               #: 结尾焦点上残留的一点点呼吸（不然是死画面）
END_RAMP_TILES = 4             #: 结尾聚焦的边缘渐变宽度（格）


def stair_zones(ang: list[float]) -> list[tuple[int, int]]:
    """找出**连续 90° 折弯**的「聚焦区」（把邻近的串并起来）。

    判据（照抄 Sinkhole 实测的形状）：连续若干格 `travel ∈ {90, 270}`，
    中间**最多夹一个 180**；折点数 ≥ `STAIR_MIN_TURNS` 才算一串。
    相邻两串之间 ≤ `STAIR_GAP_MERGE` 格就并成一个区。
    """
    def _turn(x) -> bool:
        return round(float(x)) in (90, 270)

    runs: list[tuple[int, int]] = []
    i = 0
    n = len(ang)
    while i < n:
        if not _turn(ang[i]):
            i += 1
            continue
        j, k = i, i
        while k < n:
            if _turn(ang[k]):
                j = k
                k += 1
            elif round(float(ang[k])) == 180 and k + 1 < n and _turn(ang[k + 1]):
                k += 1
            else:
                break
        n_turn = sum(1 for x in range(i, j + 1) if _turn(ang[x]))
        if n_turn >= STAIR_MIN_TURNS:
            runs.append((i, j))
        i = j + 1
    zones: list[tuple[int, int]] = []
    for lo, hi in runs:
        if zones and lo - zones[-1][1] <= STAIR_GAP_MERGE:
            zones[-1] = (zones[-1][0], hi)
        else:
            zones.append((lo, hi))
    return zones


def _zone_weight(f: int, zones: list[tuple[int, int]]) -> float:
    """这一格落在聚焦区里多少（0~1，边缘 `STAIR_RAMP_TILES` 格线性渐变）。"""
    w = 0.0
    for lo, hi in zones:
        if f < lo - STAIR_RAMP_TILES or f > hi + STAIR_RAMP_TILES:
            continue
        if lo <= f <= hi:
            w = max(w, 1.0)
        elif f < lo:
            w = max(w, 1.0 - (lo - f) / float(STAIR_RAMP_TILES))
        else:
            w = max(w, 1.0 - (f - hi) / float(STAIR_RAMP_TILES))
    return max(0.0, min(1.0, w))

#: 甩尾判定用的 ease 名单（过冲类 + 极速起手类）。
WHIP_OVERSHOOT = ("OutElastic", "InElastic", "OutBack", "InBack", "OutBounce")
WHIP_FAST = ("OutExpo", "InExpo", "OutCirc", "InCirc", "OutQuint", "InQuint",
             "OutFlash", "InFlash")


def cum_times(msv: list[float]) -> list[float]:
    """`T[f]` = **到达第 f 格**的时刻（ms）。`T` 比 `msv` 长 1。"""
    out = [0.0]
    for m in msv:
        out.append(out[-1] + float(m))
    return out


def resolve_state(actions: list[dict], settings: dict):
    """把国士的 `MoveCamera` 序列**跑一遍状态机**，给每条补全 `relativeTo/position/rotation/zoom`。

    ADOFAI 的语义：字段是 `null` 就是「**不改这一维**」，`position: [null, 1]` 是
    「x 不动、y 设成 1」。本项目不许留空（读了会被当 0），所以这里把每一步的实际值算出来。

    返回 `(补全后的事件列表, 统计)`。**`zoom <= 0` 一律当「不改」并计数** ——
    那是国士原文里的危险值，不能原样搬过来。
    """
    st = {"relativeTo": str(settings.get("relativeTo") or "Player"),
          "position": [float(v) for v in (settings.get("position") or [0, 0])],
          "rotation": float(settings.get("rotation") or 0.0),
          "zoom": float(settings.get("zoom") or 100.0)}
    n_rt = n_pos = n_rot = n_z = n_z0 = 0
    out = []
    for e in actions:
        rt = e.get("relativeTo")
        if rt:
            st["relativeTo"] = str(rt)
        else:
            n_rt += 1
        pos = e.get("position")
        if pos and any(v is not None for v in pos):
            if pos[0] is None or pos[1] is None:
                n_pos += 1
            st["position"] = [
                float(pos[0]) if pos[0] is not None else st["position"][0],
                float(pos[1]) if pos[1] is not None else st["position"][1]]
        else:
            n_pos += 1
        rot = e.get("rotation")
        if rot is None:
            n_rot += 1
        else:
            st["rotation"] = float(rot)
        z = e.get("zoom")
        if z is None:
            n_z += 1
        elif float(z) <= 0.0:
            n_z0 += 1
        else:
            st["zoom"] = float(z)
        out.append({
            "floor": int(e["floor"]),
            "duration": float(e.get("duration") or 0.0),
            "relativeTo": st["relativeTo"],
            "position": list(st["position"]),
            "rotation": st["rotation"],
            "zoom": st["zoom"],
            "angleOffset": float(e.get("angleOffset") or 0.0),
            "ease": str(e.get("ease") or "Linear"),
            "_src": e,
        })
    return out, {"rt_null": n_rt, "pos_null": n_pos, "rot_null": n_rot,
                 "zoom_null": n_z, "zoom_le0": n_z0}


def transplant(gs_ev, gs_T, sn_T, ns, sn_from, gs_from, zoom_scale, dur_scale,
               mode="progress"):
    """把国士 `gs_from..` 的镜头搬到 Sinkhole `sn_from..` 上。

    * `mode="progress"`：按**段内进度**对齐（两段都是「变速点之后的收尾长段」）
      ⇒ 国士那一段**全部**用上；时值仍是**墙上时长**（乘 `dur_scale`），不压缩快慢；
    * `mode="truncate"`：按**墙上时间 1:1** 对齐，Sinkhole 段短，所以只用到国士前一部分。
    """
    sn_last = len(sn_T) - 2
    gs_last = int(gs_ev[-1]["floor"]) if gs_ev else gs_from
    t_g0, t_g1 = gs_T[gs_from], gs_T[gs_last]
    t_s0, t_s1 = sn_T[sn_from], sn_T[sn_last]
    span_g = max(1e-9, t_g1 - t_g0)

    out = []
    n_skip = n_clamp = 0
    for e in gs_ev:
        f = int(e["floor"])
        if f < gs_from:
            continue
        if mode == "progress":
            p = (gs_T[f] - t_g0) / span_g
            t = t_s0 + p * (t_s1 - t_s0)
        else:
            t = t_s0 + (gs_T[f] - t_g0)
            if t > t_s1:
                n_skip += 1
                continue
        fs = bisect.bisect_right(sn_T, t) - 1
        fs = max(sn_from, min(sn_last, fs))
        z = float(e["zoom"]) * zoom_scale
        if z < ZOOM_LO:
            z = ZOOM_LO
            n_clamp += 1
        out.append({
            "floor": int(fs),
            "eventType": "MoveCamera",
            "duration": float(e["duration"]) * dur_scale,
            "relativeTo": e["relativeTo"],
            "position": [float(e["position"][0]), float(e["position"][1])],
            "rotation": float(e["rotation"]),
            "zoom": float(z),
            "angleOffset": float(e["angleOffset"]),
            "ease": e["ease"],
            "eventTag": TAG + "tail",
            "_src_floor": f,
        })
    out.sort(key=lambda x: x["floor"])
    return out, {"used": len(out), "skipped": n_skip, "zoom_clamped": n_clamp,
                 "src_span_s": span_g / 1000.0,
                 "dst_span_s": (t_s1 - t_s0) / 1000.0}


def drift_tail(curs, ms, bp, base, sn_from, sn_to, ang=None, focus=False,
               end_focus=False):
    """★ **呼吸 + 漂移** 的后段调度（迭代 2.1；`focus=True` 时加 2.2 的两处聚焦）。

    一条事件同时给出三层的结果 —— 因为 ADOFAI 的 `MoveCamera` 会把**所有**维度
    补间到它自己的目标值，所以「一条只管缩放、另一条只管位置」是行不通的。

    | 层 | 怎么算 |
    |---|---|
    | **漂移 · 位置** | 基准位 + `DRIFT_X` / `DRIFT_Y` 两组正弦叠加 |
    | **漂移 · 旋转** | `DRIFT_ROT` 两组正弦叠加（±6° 量级，周期 9~17 秒） |
    | **呼吸 · 缩放** | `ZOOM_MID ± ZOOM_SLOW_A`（周期 15 秒）再乘 `1 ± ZOOM_BREATH_AMP`，逐条交替 |

    ★ **2.2 的两处聚焦**（都是**平滑加权**，不是硬切）：

    * **折弯段聚焦**（`focus=True`）：在 `stair_zones()` 找出的「连续 90° 折弯」区里，
      按 `focus_w` 把缩放收窄到 `FOCUS_ZOOM_MID`（190~210）、加一点旋转轻摆、
      漂移幅度压到 `FOCUS_DRIFT_GAIN`；
    * **结尾聚焦球**（`end_focus=True`）：从**最后一个聚焦区结束的下一格**起，
      位置收到 `[0,0]`（球本身）、缩放收到 `END_ZOOM`、旋转归 0。

    落点用**墙上时间**（每 `STEP_BEATS` 拍一条）而不是格号 —— 这样跨 `SetSpeed`
    变速段也稳。补间的目标取**它自己中点时刻**的漂移值 ⇒ 整条链子连起来是
    一条平滑的轨迹，而不是"一段段停下来"。
    """
    beat = 60000.0 / float(base)
    T = cum_times(ms)
    t0 = T[sn_from]
    t_end = T[sn_to]
    n = len(curs) - 1

    zones = stair_zones(ang) if (focus and ang) else []
    zones = [z for z in zones if z[1] >= sn_from]
    end_from = (zones[-1][1] + 1) if (end_focus and zones) else None

    def _osc(u, spec):
        return sum(a * math.sin(2.0 * math.pi * u / p + ph) for (p, a, ph) in spec)

    def _lerp(a, b, w):
        return a + (b - a) * w

    ev = []
    i = 0
    t = t0
    while t <= t_end:
        fs = bisect.bisect_right(T, t) - 1
        fs = max(sn_from, min(n, fs))
        u = (t - t0) / 1000.0
        um = u + DUR_BEATS * beat / 2000.0          # 补间中点（只给漂移采样用）
        # ★ 聚焦权重用**事件自己的格号** `fs`，不用中点 `fm` ——
        #   在 90° 折弯段里 `travel=90` ⇒ 1 格只要 0.5 拍，一条 16 拍的补间跨 32 格，
        #   用中点会让权重提前 32 格生效，把折弯聚焦区截掉一大半（实测踩过）。
        fm = int(fs)
        # ---- 漂移层
        px = float(bp["position"][0]) + _osc(um, DRIFT_X)
        py = float(bp["position"][1]) + _osc(um, DRIFT_Y)
        rot = _osc(um, DRIFT_ROT)
        z0 = ZOOM_MID + ZOOM_SLOW_A * math.sin(2.0 * math.pi * um / ZOOM_SLOW_P + 0.7)
        z = z0 * (1.0 + ZOOM_BREATH_AMP * (1.0 if i % 2 == 0 else -1.0))
        # ---- 2.2 折弯段聚焦
        fw = _zone_weight(fm, zones)
        if fw > 0.0:
            zf = FOCUS_ZOOM_MID + FOCUS_ZOOM_AMP * math.sin(
                2.0 * math.pi * um / 2.4 + 0.3)
            rotf = FOCUS_ROT_DEG * math.sin(2.0 * math.pi * um / FOCUS_ROT_PERIOD)
            z = _lerp(z, zf, fw)
            rot = _lerp(rot, rotf, fw)
            px = _lerp(px, float(bp["position"][0]) + (px - bp["position"][0])
                       * FOCUS_DRIFT_GAIN, fw)
            py = _lerp(py, float(bp["position"][1]) + (py - bp["position"][1])
                       * FOCUS_DRIFT_GAIN, fw)
        # ---- 2.2 结尾聚焦球
        if end_from is not None and fm >= end_from - END_RAMP_TILES:
            ew = min(1.0, (fm - (end_from - END_RAMP_TILES)) / float(END_RAMP_TILES))
            z = _lerp(z, END_ZOOM + END_BREATH * math.sin(
                2.0 * math.pi * um / 2.8 + 0.9), ew)
            rot = _lerp(rot, 0.0, ew)
            px = _lerp(px, 0.0, ew)
            py = _lerp(py, 0.0, ew)
        ev.append({
            "floor": int(fs), "eventType": "MoveCamera",
            "duration": DUR_BEATS, "relativeTo": "Player",
            "position": [px, py], "rotation": rot,
            "zoom": float(z), "angleOffset": 0.0,
            "ease": DRIFT_EASE, "eventTag": TAG + "drift",
        })
        i += 1
        t += STEP_BEATS * beat
    return ev


def whip_stats(mv: list[dict]) -> dict:
    c = Counter(a["ease"] for a in mv)
    over = sum(v for k, v in c.items() if k in WHIP_OVERSHOOT)
    fast = sum(v for k, v in c.items() if k in WHIP_FAST)
    cuts = sum(1 for a in mv if float(a.get("duration") or 0.0) <= 0.0)
    return {"n": len(mv), "overshoot": over, "fast": fast, "cuts": cuts,
            "eases": c}


# ============================================================ 验收清单
def write_checklist(path: str, meta: dict, ev: list[dict], ws: dict,
                    w3: dict | None) -> None:
    L: list[str] = []
    add = L.append
    add("=" * 78)
    add("运镜验收清单 · 迭代 2（两段不同写法）→ level2.adofai")
    add("=" * 78)
    add("")
    add("源谱    : %s" % meta["src"])
    add("谱面    : %d 格 · base %g · %.1f s" % (meta["tiles"], meta["base"],
                                                meta["seconds"]))
    add("基准位  : relativeTo=%s position=%s rotation=%g zoom=%g"
        % (meta["bp"]["relativeTo"], meta["bp"]["position"],
           meta["bp"]["rotation"], meta["bp"]["zoom"]))
    add("抄的源  : %s" % meta["gs_path"])
    add("          抄国士 `%d..%d`（%.1f s）"
        % (meta["gs_from"], meta["gs_last"], meta["gs_span"]))
    add("")
    add("── 用户的两条要求 ─────────────────────────────────────────")
    add("")
    add("① **少用甩尾运镜，尽可能用柔和的运镜**")
    add("② **%d 格子后面的段落，全部使用国士无双中 %d 格子之后的写法**"
        % (TAIL_FROM, GS_TAIL_FROM))
    add("")
    add("── 两个谱面里「相似的配置」（要求 ② 的落点依据）────────────")
    add("")
    add("  · 国士 `%d+` 是一整段 `cur` **恒定 %g** 的收尾长段；"
        % (GS_TAIL_FROM, meta["gs_cur"]))
    add("    本谱 `%d+` 同样是一整段 `cur` **恒定 %g** 的收尾长段。" % (TAIL_FROM, meta["sn_cur"]))
    add("  · 两段的 **travel 形状同族**（180 / 90 / 30 / 60 为主）。")
    add("  · **墙上时长几乎相同**：国士段 %.1f s，本谱段 %.1f s。"
        % (meta["gs_span"], meta["sn_span"]))
    add("  · ★ **静止位是同一个值**：国士 %d+ 反复回到 `pos=[0,1]`"
        % GS_TAIL_FROM)
    add("    （国士自己的 base 是 `[0,2]`），而本谱 `settings.position` **正好也是 `[0,1]`**"
        " ⇒ **位置原样搬**。")
    add("  · **缩放按基准位比例搬**：本谱 %g / 国士 %g = **×%.4f**。"
        % (meta["bp"]["zoom"], meta["gs_zoom"], meta["zoom_scale"]))
    add("  · **时值按 base 比例搬**：%g / %g = **×%.4f**。"
        % (meta["base"], meta["gs_base"], meta["dur_scale"]))
    add("    （`duration` 单位是**拍**、拍长只由 base 决定 ⇒ 乘这个比例**墙上时长不变**，")
    add("      动作快慢的观感才和国士一致。）")
    add("")
    add("── 前段 `0..%d`：国士两层 · **柔和档**（要求 ①）──────────" % (TAIL_FROM - 1))
    add("")
    add("  配方和迭代 1（`out/运镜验收谱v3-Sinkhole - Plum/`）**逐字相同**，只换 ease：")
    add("")
    add("  %-12s %-22s %s" % ("", "迭代 1（照抄国士）", "迭代 2（柔和档）"))
    add("  %-12s %-22s %s" % ("宏观 · 长锚", "OutExpo（起手极快）", "OutCubic"))
    add("  %-12s %-22s %s" % ("宏观 · 弹回", "OutCirc（起手猛）", "OutSine"))
    add("  %-12s %-22s %s" % ("微观", "OutElastic（**过冲 = 甩尾**）", "OutSine"))
    add("")
    add("  长锚 %d · 弹回 %d · 微观 %d · 一拍一振 定基 %d / 硬切 %d"
        % (meta["h_macro"], meta["h_snap"], meta["h_micro"],
           meta["h_lock"], meta["h_cut"]))
    add("")
    add("── 后段 `%d..%d`：国士 `%d+` 的写法（要求 ②）──────────────"
        % (TAIL_FROM, meta["tiles"] - 1, GS_TAIL_FROM))
    add("")
    add("  国士那一套换了完全不同的写法（实测 465 条）：")
    add("    · `relativeTo`：**`Player` 348 条**（迭代 1 那种 `Tile` 微观**没了**）")
    add("    · `ease`：`OutSine` 137 · `Linear` 125 · `InSine` 53 · `InCubic` 48 ·")
    add("      `OutCubic` 40 · `OutCirc` 31 · `OutQuad` 26 —— ★ **一条 `OutElastic` 都没有**")
    add("    · 四个反复出现的动机：**呼吸对** / **大摆** / **硬切点拨** / **正弦呼吸链**")
    add("    · 回归位永远是 **`pos=[0,1]`**")
    add("")
    add("  逐条搬过来 %d 条，只做了三处换算：位置原样 / 缩放 ×%.4f / 时值 ×%.4f"
        % (meta["t_used"], meta["zoom_scale"], meta["dur_scale"]))
    add("  搬过来的 ease 分布：%s" % meta["t_eases"])
    add("")
    add("── 甩尾指标（要求 ① 的量化）──────────────────────────────")
    add("")
    add("  %-10s %8s %10s %12s %8s" % ("", "总条数", "过冲类", "极速起手", "硬切"))
    if w3:
        add("  %-10s %8d %10d %12d %8d   ← 迭代 1（v3 照抄国士）"
            % ("v3", w3["n"], w3["overshoot"], w3["fast"], w3["cuts"]))
    add("  %-10s %8d %10d %12d %8d   ← **迭代 2（本产物）**"
        % ("level2", ws["n"], ws["overshoot"], ws["fast"], ws["cuts"]))
    add("")
    add("  「过冲类」= `OutElastic` / `InBack` / `OutBack` / `OutBounce` —— 这就是**甩尾**")
    add("  （末尾甩出去再弹回来）。「极速起手」= `OutExpo` / `OutCirc` / `OutQuint` / `OutFlash`。")
    add("")
    add("  ★ 前段的过冲类已经**清零**（微观 `OutElastic` 全部换 `OutSine`）。")
    add("  ★★ 后段的**硬切 %d 条是国士 %d+ 原文就有的**（作者用它「点拨」：`dur=0` 瞬切到"
        % (meta["t_cuts"], GS_TAIL_FROM))
    add("     小 zoom，紧接一条 `OutSine` 涨上去）。要求 ② 说「全部使用那个写法」，")
    add("     所以**照搬没改** —— 如果你觉得闪，说一声，把 `dur=0` 那批软化掉就行。")
    add("")
    add("── 不许静默（本轮的所有补位 / 抬升 / 跳过）────────────────")
    add("")
    add("  · **空位补实**：国士原文用 `null` / `[null,null]` 表示「这一维不改」，")
    add("    本项目不许留空（`docs/64` §8.6.5：`zoom: null` 会被读成 0 ⇒ 黑屏），")
    add("    所以模拟运行状态把它们补成实际值：")
    add("      relativeTo %d · position %d · rotation %d · zoom %d"
        % (meta["null"]["rt_null"], meta["null"]["pos_null"],
           meta["null"]["rot_null"], meta["null"]["zoom_null"]))
    add("  · **`zoom ≤ 0` 的 %d 条**（国士原文有 `zoom 0 / 1 / 12 / 25` 这种怼脸值）")
    add("    按「不改」处理；另有 **%d 条**缩放结果 < %g，**抬到 %g**。"
        % (meta["null"]["zoom_le0"], ZOOM_LO, meta["t_clamped"]))
    add("  · **原有 action 一条没改**：`MoveCamera` 是**插**进去的，原事件相对顺序不动。")
    add("")
    add("── 听的时候看什么 ─────────────────────────────────────────")
    add("")
    add("  **前段（0 ~ %d 格 / 0 ~ %.0f s）**" % (TAIL_FROM - 1, meta["sn_span_start"]))
    add("    ① 微观层还在不在（每 2 格一个小步跳），但**不再有尾巴甩出去**了；")
    add("    ② 每串末尾的「弹回」应当是**平滑收住**，不是「啪」一下；")
    add("    ③ 长锚那 5 秒应当是**匀速慢漂**，不是起手猛地一冲。")
    add("")
    add("  **后段（%d ~ %d 格 / %.0f ~ 143 s）**" % (TAIL_FROM, meta["tiles"] - 1,
                                                    meta["sn_span_start"]))
    add("    ④ 画面**几乎全程挂在玩家身上**（`Player` 帧），不再有钉在格上的微观抖动；")
    add("    ⑤ 主基调是「**一涨一落**」的呼吸（`OutSine` 涨 → `InSine` 落），很软；")
    add("    ⑥ 偶尔会**瞬切**一下再涨（`dur=0`）—— 那是国士原文的点拨，看接不接受；")
    add("    ⑦ 位置应当在 `[0,1]` / `[0,0]` / `[-1,2]` 这几个点附近来回，不会跑远。")
    add("")
    add("── 产物怎么用 ─────────────────────────────────────────────")
    add("")
    add("  把整个目录拷进：")
    add(r"    C:\Users\<你>\Documents\A Dance of Fire and Ice\Worlds\ ")
    add("  （目录里只有 `level2.adofai` + 音频；源谱没有任何图片依赖）")
    add("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


# ============================================================ 验收清单（漂移版）
def write_checklist_drift(path: str, meta: dict, ev: list[dict], ws: dict,
                          w3: dict | None) -> None:
    L: list[str] = []
    add = L.append
    add("=" * 78)
    add("运镜验收清单 · 迭代 2.1 → level2.1.adofai")
    add("=" * 78)
    add("")
    add("源谱    : %s" % meta["src"])
    add("谱面    : %d 格 · base %g · %.1f s" % (meta["tiles"], meta["base"],
                                                meta["seconds"]))
    add("基准位  : relativeTo=%s position=%s rotation=%g zoom=%g"
        % (meta["bp"]["relativeTo"], meta["bp"]["position"],
           meta["bp"]["rotation"], meta["bp"]["zoom"]))
    add("")
    add("── 这一轮改了什么 ─────────────────────────────────────────")
    add("")
    add("主人 2026-10 的口径（原话）：")
    add("  「我原始的想法是，从 1777 到加速段结束，**完整使用优秀的、呼吸+漂移的镜头")
    add("    调度**。目前的镜头使用中有些地方的**位移明显用力过猛**了，而**并不需要")
    add("    如此频繁**（国士无双里面也没有如此频繁且僵硬的使用）」")
    add("  「（静止处）**加上慢速漂移**」")
    add("")
    add("前段 `0..%d` **不动**（国士两层 · 柔和档，与 `level2.adofai` 逐字相同）。"
        % (TAIL_FROM - 1))
    add("")
    add("后段 `%d..%d` **重写成「呼吸 + 漂移」调度**，替换掉原来逐条搬的国士 %d+。"
        % (TAIL_FROM, meta["tiles"] - 1, GS_TAIL_FROM))
    add("")
    add("── 为什么要重写（实测对照）────────────────────────────────")
    add("")
    add("  %-22s %14s %14s" % ("", "国士 3080+", "level2 后段"))
    for k, a, b in meta["cmp"]:
        add("  %-22s %14s %14s" % (k, a, b))
    add("")
    add("  ⇒ 搬过来是 **1:1** 的，密度一模一样。所以「太频繁 / 用力过猛」不是搬歪了，")
    add("    是**国士那一段本身就是离散的密集位移**（平均一跳 1.67 格、每秒 5.65 次），")
    add("    而且夹着每秒 3.87 次硬切。要的是**连续慢漂**，不是离散跳。")
    add("")
    add("── 新的调度 ───────────────────────────────────────────────")
    add("")
    add("  一条 `MoveCamera` 会把**所有**维度补间到它自己的目标值，所以")
    add("  「一条只管缩放、另一条只管位置」是行不通的 ⇒ **每条事件同时带三层的结果**：")
    add("")
    add("  ┌ **漂移 · 位置**（慢 · 连续 · **永不停**）")
    add("  │   x = 基准x + %s" % (" + ".join("%g·sin(2πt/%g s)" % (a, p)
                                          for p, a, _ in DRIFT_X),))
    add("  │   y = 基准y + %s" % (" + ".join("%g·sin(2πt/%g s)" % (a, p)
                                          for p, a, _ in DRIFT_Y),))
    add("  │   ⇒ x 峰峰 %g 格 / y 峰峰 %g 格，**13 / 11 秒一个来回**"
        % (2 * sum(a for _, a, _ in DRIFT_X), 2 * sum(a for _, a, _ in DRIFT_Y)))
    add("  ├ **漂移 · 旋转**")
    add("  │   %s ⇒ ±%g° 量级，17 / 9 秒一个来回"
        % (" + ".join("%g·sin(2πt/%g s)" % (a, p) for p, a, _ in DRIFT_ROT),
           sum(a for _, a, _ in DRIFT_ROT)))
    add("  └ **呼吸 · 缩放**")
    add("      %g ± %g（15 秒慢基线）再 ×(1 ± %g)，**逐条交替**"
        % (ZOOM_MID, ZOOM_SLOW_A, ZOOM_BREATH_AMP))
    add("      实得 zoom %.0f ~ %.0f" % (meta["zr"][0], meta["zr"][1]))
    add("")
    add("  **网格**：每 %g 拍一条、每条 %g 拍 ⇒ **2× 重叠，任意时刻都有两条在跑** ⇒"
        % (STEP_BEATS, DUR_BEATS))
    add("  镜头永远在动、**永不静止**；ease 全部 `%s`（零过冲、零硬切）。" % DRIFT_EASE)
    add("  后段共 **%d 条**（原来 %d 条）⇒ 每秒 %.2f 条，位置变化**降频 %.1f 倍**"
        % (meta["t_n"], meta["t_n0"], meta["t_n"] / meta["dst_span"],
           meta["t_n0"] / max(1e-9, meta["t_n"])))
    add("")
    if meta.get("zones") or meta.get("end_focus"):
        add("── ★ 迭代 2.2 的两处聚焦（用户配编辑器截图点的）──────────────")
        add("")
        add("  用户口径：「对于这样**连续 90° 折弯循环**的结构，可以适当**聚焦镜头**」+")
        add("            「迭代 2.2，**结尾速度完全降下来之后，聚焦到球本身**」")
        add("  ★ 力度按用户选的「温柔一点」：**不换帧**，只把缩放收窄 + 旋转轻摆。")
        add("")
        for (lo, hi) in meta.get("zones") or []:
            add("  · **折弯聚焦区**：格 %d..%d（%.1f ~ %.1f s，%d 格）"
                % (lo, hi, meta["tz"][lo], meta["tz"][hi], hi - lo + 1))
        if meta.get("zones"):
            add("    缩放收到 **%g ± %g**（本谱基准 %g ⇒ **拉近**）· 旋转轻摆 **±%g°**"
                % (FOCUS_ZOOM_MID, FOCUS_ZOOM_AMP, meta["bp"]["zoom"], FOCUS_ROT_DEG))
            add("    漂移幅度压到 **%g 倍**（不然「聚焦」会晃）· 边缘 %d 格线性渐变"
                % (FOCUS_DRIFT_GAIN, STAIR_RAMP_TILES))
        if meta.get("end_focus") and meta.get("zones"):
            ef = meta["zones"][-1][1] + 1
            add("  · **结尾聚焦球**：格 %d..%d（%.1f ~ %.1f s）位置收到 **`[0,0]`**、"
                % (ef, meta["tiles"] - 1, meta["tz"][ef], meta["seconds"]))
            add("    缩放收到 **%g ± %g**（留一点呼吸，不然是死画面）、旋转归 0。"
                % (END_ZOOM, END_BREATH))
            add("    ★ 这一档**不发**出场归位事件 —— 归位会把镜头从球上拉回基准位，")
            add("      正好毁掉这个收尾。")
        add("")
    add("── 甩尾 / 僵硬指标 ───────────────────────────────────────")
    add("")
    add("  %-10s %8s %10s %12s %8s" % ("", "总条数", "过冲类", "极速起手", "硬切"))
    if w3:
        add("  %-10s %8d %10d %12d %8d   ← 迭代 1（v3 照抄国士）"
            % ("v3", w3["n"], w3["overshoot"], w3["fast"], w3["cuts"]))
    if meta.get("w2"):
        w2 = meta["w2"]
        add("  %-10s %8d %10d %12d %8d   ← 迭代 2（搬国士 3080+）"
            % ("level2", w2["n"], w2["overshoot"], w2["fast"], w2["cuts"]))
    add("  %-10s %8d %10d %12d %8d   ← **迭代 2.1（本产物）**"
        % ("level2.1", ws["n"], ws["overshoot"], ws["fast"], ws["cuts"]))
    add("")
    add("  ★ 后段的**硬切从 %d 条降到 0**（国士原文那批 `dur=0` 点拨全部去掉了）。"
        % (meta.get("t_cuts0") or 0))
    add("  ★ 位置**完全静止**的最长一段：从 %.2f s 降到 **0 s**（永远在漂）。"
        % meta.get("static0", 0.0))
    add("")
    add("── 听的时候看什么 ─────────────────────────────────────────")
    add("")
    add("  **后段（%d ~ %d 格 / %.0f ~ %.0f s）**"
        % (TAIL_FROM, meta["tiles"] - 1, meta["sn_span_start"], meta["seconds"]))
    add("    ① 画面应当**一直在慢慢动**，从头到尾**没有一秒是停住的**；")
    add("    ② 但**没有一下是猛的** —— 没有瞬切、没有过冲、没有甩尾；")
    add("    ③ 位置像**呼吸一样慢慢飘**（十几秒一个来回），不是一格一格跳；")
    add("    ④ 缩放是软的**一涨一落**（每秒大约一次），幅度不吓人；")
    add("    ⑤ 整体观感应当是「**镜头在带着你慢慢摇**」，而不是「镜头在追着点跳」。")
    add("")
    add("  **前段（0 ~ %d 格）**：与 `level2.adofai` 完全一样，不用重听。"
        % (TAIL_FROM - 1))
    add("")
    add("── 产物怎么用 ─────────────────────────────────────────────")
    add("")
    add("  ★ **注意**：`%s` 里现在有**两个** `.adofai`（`level2.adofai` 和"
        % meta["out"])
    add("    `level2.1.adofai`）。游戏可能只认其中一个 —— 要听 2.1 的话，")
    add("    把 `level2.adofai` 先挪出目录，或者只把 `level2.1.adofai` + 音频拷进")
    add("    `Worlds\\` 下的一个**新目录**。")
    add("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


# ============================================================ 主
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sinkhole 运镜迭代 2 → level2.adofai")
    ap.add_argument("--sink", default=SINKHOLE)
    ap.add_argument("--guksu", default=GUKSU)
    ap.add_argument("--out", default=None)
    ap.add_argument("--tail-mode", choices=("progress", "truncate"), default="progress",
                    help="transplant 模式的落点方式")
    ap.add_argument("--tail", choices=("transplant", "drift"), default="transplant",
                    help="后段写法：transplant=逐条搬国士 3080+（迭代 2）/"
                         "drift=呼吸+漂移调度（迭代 2.1）")
    ap.add_argument("--name", default="level2", help="产物文件名（不带扩展名）")
    ap.add_argument("--focus", action="store_true",
                    help="★ 2.2：连续 90° 折弯段 → 温柔聚焦（zoom 190~210 + 旋转轻摆）")
    ap.add_argument("--end-focus", action="store_true",
                    help="★ 2.2：结尾（最后一个折弯区之后）→ 聚焦到球本身")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--macro", default=ACC.MACRO_DIR)
    args = ap.parse_args(argv)

    sink_path = os.path.abspath(args.sink)
    gs_path = os.path.abspath(args.guksu)
    out_dir = os.path.abspath(args.out or os.path.join(
        _ROOT, "out", "运镜验收谱v4-Sinkhole2"))

    # ---------------- 两张谱
    src = A1.load_json(sink_path)
    bp = A1.base_pose(src["settings"])
    base_sn = float(src["settings"]["bpm"])
    sn_a = ACC.load_angle(sink_path, args.macro)
    curs = ACC.floor_bpm(sn_a)
    ms_sn = ACC.floor_ms(sn_a)
    T_sn = cum_times(ms_sn)

    gs = A1.load_json(gs_path)
    base_gs = float(gs["settings"]["bpm"])
    gs_a = ACC.load_angle(gs_path, args.macro)
    ms_gs = ACC.floor_ms(gs_a)
    T_gs = cum_times(ms_gs)
    gs_mv = [e for e in (gs_a.actions or []) if e.get("eventType") == "MoveCamera"]
    gs_res, gs_null = resolve_state(
        [{"floor": e["floor"], "duration": e.get("duration"),
          "relativeTo": e.get("relativeTo"), "position": e.get("position"),
          "rotation": e.get("rotation"), "zoom": e.get("zoom"),
          "angleOffset": e.get("angleOffset"), "ease": e.get("ease")}
         for e in gs_mv], gs["settings"])

    zoom_scale = float(bp["zoom"]) / float(gs["settings"]["zoom"] or 100.0)
    dur_scale = base_sn / base_gs

    print("=" * 92)
    print("Sinkhole 运镜 · 迭代 2 → level2.adofai")
    print("=" * 92)
    print("源谱    : %s" % sink_path)
    print("          %d 格 · base %g · %.1f s · 基准位 rel=%s pos=%s zoom=%g"
          % (len(curs), base_sn, T_sn[-1] / 1000.0, bp["relativeTo"],
             bp["position"], bp["zoom"]))
    print("抄的源  : %s" % gs_path)
    print("          国士 %g 格 · base %g · 抄 `%d..%d`（%.1f s / cur 恒定 %g）"
          % (len(ms_gs), base_gs, GS_TAIL_FROM, len(ms_gs) - 1,
             (T_gs[-1] - T_gs[GS_TAIL_FROM]) / 1000.0,
             ACC.floor_bpm(gs_a)[GS_TAIL_FROM]))
    print()
    print("── 两谱的「相似配置」换算 ──────────────────────────────────────────")
    print("  静止位：国士 3080+ 的回归位 = pos=[0,1]；本谱 settings.position = %s"
          % bp["position"])
    print("          ⇒ 位置**原样搬**（单位都是格）")
    print("  缩放  ：本谱 %g / 国士 %g = **×%.4f**"
          % (bp["zoom"], gs["settings"]["zoom"], zoom_scale))
    print("  时值  ：本谱 base %g / 国士 base %g = **×%.4f**（墙上时长不变）"
          % (base_sn, base_gs, dur_scale))
    print("  落点  ：按段内进度对齐（`--tail-mode progress`）"
          if args.tail_mode == "progress" else "  落点  ：按墙上时间 1:1 对齐（truncate）")

    # ---------------- 前段：两层，柔和档
    head_curs = curs[:TAIL_FROM]
    ev_head, st_head = A1.plan(head_curs, bp, base_sn, profile="soft")

    # ---------------- 后段
    if args.tail == "drift":
        ang = None
        zones: list[tuple[int, int]] = []
        if args.focus or args.end_focus:
            sn_a.getRotateAngle()
            ang = [float(x) for x in sn_a.originRotateAngleList]
            zones = [z for z in stair_zones(ang) if z[1] >= TAIL_FROM]
        tail = drift_tail(curs, ms_sn, bp, base_sn, TAIL_FROM, len(curs) - 1,
                          ang=ang, focus=bool(args.focus),
                          end_focus=bool(args.end_focus))
        tinfo = {"used": len(tail), "skipped": 0, "zoom_clamped": 0,
                 "src_span_s": 0.0,
                 "dst_span_s": (T_sn[-1] - T_sn[TAIL_FROM]) / 1000.0,
                 "mode": "drift"}
    else:
        tail, tinfo = transplant(gs_res, T_gs, T_sn, len(curs), TAIL_FROM,
                                 GS_TAIL_FROM, zoom_scale, dur_scale,
                                 mode=args.tail_mode)
        tinfo["mode"] = "transplant"

    # ---------------- 出场归位
    # ★ 结尾聚焦球时**不发**归位（归位会把镜头从球上拉回基准位，正好毁掉那个收尾）。
    back = None if args.end_focus else A1.cam(
        len(curs) - 1, dur=A1.SNAP_BEATS, ease="OutSine",
        rel=bp["relativeTo"], position=bp["position"], zoom=bp["zoom"],
        rotation=bp["rotation"], tag=TAG + "back")

    ev = ev_head + tail + ([back] if back else [])
    ev.sort(key=lambda a: int(a["floor"]))
    # ★ 调试用的 `_src_floor` 不许落盘（`MoveCamera` 只许有那 10 个字段）。
    for a in ev:
        a.pop("_src_floor", None)

    print()
    print("── 前段 0..%d：国士两层 · **柔和档**（要求 1）────────────────────"
          % (TAIL_FROM - 1))
    print("  ease 换法：长锚 OutExpo→%s · 弹回 OutCirc→%s · 微观 OutElastic→%s"
          % (A1.PROFILES["soft"]["long"], A1.PROFILES["soft"]["snap"],
             A1.PROFILES["soft"]["micro"]))
    print("  长锚 %d · 弹回 %d · 微观 %d · 一拍一振 %d/%d"
          % (st_head["macro"], st_head["snap"], st_head["micro"],
             st_head["shake_lock"], st_head["shake_cut"]))
    print()
    if args.tail == "drift":
        print("── 后段 %d..%d：**%s** 调度（要求 ② 重写，迭代 2.1）────────────"
              % (TAIL_FROM, len(curs) - 1, DRIFT_NOTE))
        print("  网格：每 %g 拍一条、每条 %g 拍（`%s`）⇒ **2× 重叠，永不静止**"
              % (STEP_BEATS, DUR_BEATS, DRIFT_EASE))
        print("  漂移 · 位置：x 周期 %s 幅度 %s 格；y 周期 %s 幅度 %s 格"
              % ([p for p, _, _ in DRIFT_X], [a for _, a, _ in DRIFT_X],
                 [p for p, _, _ in DRIFT_Y], [a for _, a, _ in DRIFT_Y]))
        print("  漂移 · 旋转：%s ⇒ ±%g° 量级"
              % ([p for p, _, _ in DRIFT_ROT],
                 sum(a for _, a, _ in DRIFT_ROT)))
        print("  呼吸 · 缩放：%g ± %g（周期 %g s）再 ×(1 ± %g)"
              % (ZOOM_MID, ZOOM_SLOW_A, ZOOM_SLOW_P, ZOOM_BREATH_AMP))
        zs = [e["zoom"] for e in tail]
        ps = [e["position"] for e in tail]
        print("  实得：%d 条 · zoom %.0f~%.0f · x %.2f~%.2f · y %.2f~%.2f"
              % (len(tail), min(zs), max(zs),
                 min(p[0] for p in ps), max(p[0] for p in ps),
                 min(p[1] for p in ps), max(p[1] for p in ps)))
        if args.focus or args.end_focus:
            print()
            print("── ★ 迭代 2.2 的聚焦 ──────────────────────────────────────")
            if zones:
                for (lo, hi) in zones:
                    t_a = T_sn[lo] / 1000.0
                    t_b = T_sn[hi] / 1000.0
                    tv = [round(ang[x]) for x in range(lo, min(hi + 1, lo + 12))]
                    print("  折弯聚焦区：格 %d..%d（%.1f~%.1f s，%d 格） travel=%s…"
                          % (lo, hi, t_a, t_b, hi - lo + 1, tv))
                print("  缩放收到 %g±%g（本谱基准 %g ⇒ 拉近）· 旋转轻摆 ±%g°（周期 %g s）"
                      " · 漂移压到 %g 倍"
                      % (FOCUS_ZOOM_MID, FOCUS_ZOOM_AMP, bp["zoom"],
                         FOCUS_ROT_DEG, FOCUS_ROT_PERIOD, FOCUS_DRIFT_GAIN))
            if args.end_focus and zones:
                ef = zones[-1][1] + 1
                print("  结尾聚焦球：格 %d..%d（%.1f~%.1f s）位置收到 [0,0]、缩放收到 %g"
                      % (ef, len(curs) - 1, T_sn[ef] / 1000.0, T_sn[-1] / 1000.0,
                         END_ZOOM))
    else:
        print("── 后段 %d..%d：国士 %d+ 的写法（要求 ②，迭代 2）──────────────"
              % (TAIL_FROM, len(curs) - 1, GS_TAIL_FROM))
        print("  搬过来 %d 条（国士源段 %.1f s → 本谱段 %.1f s）"
              % (tinfo["used"], tinfo["src_span_s"], tinfo["dst_span_s"]))
        if tinfo["skipped"]:
            print("  ⚠ 因段短而**没用上**的国士事件：%d 条 —— **不静默**" % tinfo["skipped"])
        print("  `zoom` 抬到 ≥%g 的：%d 条（国士原文有 zoom 0/1/12/25 这种怼脸值）"
              % (ZOOM_LO, tinfo["zoom_clamped"]))
        print("  空位补实（国士原文用 null 表示「不改」）：relativeTo %d · position %d · "
              "rotation %d · zoom %d（其中 zoom≤0 的 %d 条按「不改」处理）"
              % (gs_null["rt_null"], gs_null["pos_null"], gs_null["rot_null"],
                 gs_null["zoom_null"], gs_null["zoom_le0"]))
        print("  搬过来的 ease 分布：%s" % dict(Counter(e["ease"] for e in tail)))

    # ---------------- 甩尾指标
    ws = whip_stats([a for a in ev if a["eventType"] == "MoveCamera"])
    v3_path = os.path.join(_ROOT, "out", "运镜验收谱v3-Sinkhole - Plum", "level.adofai")
    w3 = None
    print()
    print("── 甩尾指标（用户要求 1 的量化）────────────────────────────────")
    if os.path.isfile(v3_path):
        try:
            v3 = json.load(open(v3_path, encoding="utf-8"))
            w3 = whip_stats([a for a in v3["actions"]
                             if a.get("eventType") == "MoveCamera"])
            print("  %-14s %6s %8s %8s %8s" % ("", "总条数", "过冲类", "极速起手", "硬切"))
            print("  %-14s %6d %8d %8d %8d   ← 迭代 1（v3 照抄国士）"
                  % ("v3", w3["n"], w3["overshoot"], w3["fast"], w3["cuts"]))
            print("  %-14s %6d %8d %8d %8d   ← **%s**（本产物）"
                  % (args.name, ws["n"], ws["overshoot"], ws["fast"], ws["cuts"],
                     args.name))
            if args.tail == "drift":
                tcuts = sum(1 for e in tail if float(e["duration"]) <= 0.0)
                print("  后段单独看：%d 条 · 硬切 %d 条 · 位置静止最长 **0 s**"
                      % (len(tail), tcuts))
            print("  ⇒ 过冲类 %d → %d（-%d，**%d%%**）"
                  % (w3["overshoot"], ws["overshoot"],
                     w3["overshoot"] - ws["overshoot"],
                     round(100.0 * (w3["overshoot"] - ws["overshoot"])
                           / max(1, w3["overshoot"]))))
        except Exception as exc:                              # noqa: BLE001
            print("  （读不到 v3 产物做对照：%s）" % exc)
    print("  本产物 ease：%s" % dict(ws["eases"]))

    # ---------------- 落盘
    out_level = os.path.join(out_dir, args.name + ".adofai")
    A1.write_level(src, ev, out_level)
    song = str(src["settings"].get("songFilename") or "")
    copied = None
    if song:
        s_song = os.path.join(os.path.dirname(sink_path), song)
        if os.path.isfile(s_song):
            copied = os.path.join(out_dir, song)
            shutil.copyfile(s_song, copied)

    bad = A1.verify_output(out_level, src, ev)
    print()
    if bad:
        print("✗ 产物自检失败：")
        for x in bad:
            print("   · " + x)
    else:
        print("✓ 产物自检通过：原 action 一条没改 / 字段集标准 10 个 / zoom 全部 > 0 / "
              "宏解析器能解")
    if copied:
        print("✓ 音频已放好：%s" % os.path.basename(copied))

    cl = os.path.join(out_dir, "验收清单-%s.txt" % args.name)
    if args.tail == "drift":
        # 与迭代 2 的后段做对照（读现成的 level2.adofai）
        w2 = None
        l2 = os.path.join(out_dir, "level2.adofai")
        if os.path.isfile(l2):
            try:
                j2 = json.load(open(l2, encoding="utf-8"))
                w2 = whip_stats([a for a in j2["actions"]
                                 if a.get("eventType") == "MoveCamera"])
            except Exception:                                 # noqa: BLE001
                w2 = None
        zr = (min(e["zoom"] for e in tail), max(e["zoom"] for e in tail))
        write_checklist_drift(cl, {
            "src": sink_path, "out": out_dir, "tiles": len(curs),
            "base": base_sn, "seconds": T_sn[-1] / 1000.0, "bp": bp,
            "sn_span_start": T_sn[TAIL_FROM] / 1000.0,
            "dst_span": (T_sn[-1] - T_sn[TAIL_FROM]) / 1000.0,
            "zr": zr, "t_n": len(tail), "t_n0": 453,
            "t_cuts0": (w2["cuts"] if w2 else 153),
            "static0": 4.41, "w2": w2,
            "zones": zones, "tz": [x / 1000.0 for x in T_sn],
            "end_focus": bool(args.end_focus),
            "cmp": [("条数 / 秒", "11.63", "12.18"),
                    ("改变位置 条/秒", "5.39", "**5.65**"),
                    ("平均位移", "1.68 格", "1.67 格"),
                    ("位移总量 格/秒", "9.04", "**9.45**"),
                    ("硬切 条/秒", "3.71", "**3.87**"),
                    ("位置静止最长", "4.59 s", "**4.41 s**")],
        }, ev, ws, w3)
    else:
        write_checklist(cl, {
        "src": sink_path, "tiles": len(curs), "base": base_sn,
        "seconds": T_sn[-1] / 1000.0, "bp": bp,
        "gs_path": gs_path, "gs_from": GS_TAIL_FROM, "gs_last": len(ms_gs) - 1,
        "gs_span": (T_gs[-1] - T_gs[GS_TAIL_FROM]) / 1000.0,
        "sn_span": (T_sn[-1] - T_sn[TAIL_FROM]) / 1000.0,
        "sn_span_start": T_sn[TAIL_FROM] / 1000.0,
        "gs_base": base_gs, "gs_zoom": float(gs["settings"]["zoom"]),
        "zoom_scale": zoom_scale, "dur_scale": dur_scale,
        "gs_cur": ACC.floor_bpm(gs_a)[GS_TAIL_FROM],
        "sn_cur": curs[TAIL_FROM],
        "h_macro": st_head["macro"], "h_snap": st_head["snap"],
        "h_micro": st_head["micro"], "h_lock": st_head["shake_lock"],
        "h_cut": st_head["shake_cut"],
        "t_used": tinfo["used"], "t_clamped": tinfo["zoom_clamped"],
        "t_cuts": sum(1 for e in tail if float(e["duration"]) <= 0.0),
        "t_eases": dict(Counter(e["ease"] for e in tail)),
        "null": gs_null,
    }, ev, ws, w3)
    print("✓ 验收清单 → %s" % cl)
    print()
    print("产物 → %s" % out_dir)
    print("进游戏：把整个目录拷进")
    print(r"  C:\Users\<你>\Documents\A Dance of Fire and Ice\Worlds\ ")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
