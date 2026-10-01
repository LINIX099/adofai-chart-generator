# -*- coding: utf-8 -*-
"""**运镜验收谱 v2**：一拍一振 / 缓慢运镜 / 回正 / 雪花 A·B。

    python tools/make_camera_demo.py [输出目录]

## v1 → v2：砍掉什么、为什么

v1（18 段）里 **段 9~15 是废的** —— 用户 2026-10 实测：「9 之后的把镜头弄没了 看不见」，
但 **段 18（复位诊断）没错** ⇒ 相机状态**救得回来**，是那几条动作自己把相机搞飞的。
用户口径：**「下一迭代准备重写一个测试谱面」**，而且

> **预期应该只有缓慢匀速运镜和 7+8 的组合了，还有回正运镜**

⇒ v2 只留那三类内容（**不做**：摆头 / OutElastic 旋转 / 半六边形 Bounce / 追球 /
长拍位移 / 短拉链 —— 那些是 v1 段 9~15，全部删除）。

## 第四 / 第五轮回执（**本文件现在的样子**）

第四轮定了 **按 `cur` 分流**；第五轮把两个分支都换成了**抄 Tempest 加强版**的写法：

> 「**雪花的镜头写法……你去抄一下 Tempest 加强版**」
> 「**慢速直接一拍一振好了，高速完全不用这个写法**」
> 「**物量大的用 B，小的用 A**」

⇒

| 分支 | 判据 | 写法 | 段 |
|---|---|---|---|
| 低 `cur` | `cbpm < 400` | **一拍一振**：每拍一条 `duration=0` 硬切 | 3 / 4 |
| 高 `cur` | `cbpm ≥ 400` | 位置 + 呼吸 + 缓慢移动（并行补间，**零硬切**） | 2 / 5 |
| 雪花（小） | 格数 `<= 48` | Tempest **A**：居中近景 + 缓速整圈 | 8 |
| 雪花（大） | 格数 `> 48` | Tempest **B**：远景 + 长缓移 + 多圈 | 9 |

雪花的两套**逐条抄** Tempest 的 `f402`（A）与 `f1077`（B），
推导与出处见 `docs/64` §9.2b。

## 段落表（v2 · 10 段）

    段 1  基准·不动镜头          对照
    段 2  缓慢运镜 · 绑定         zoom 200↔120（InOutSine）+ 上偏 4 格（OutQuad）并行
    段 3  低 cur · 一拍一振       每拍硬切：偶拍定基、奇拍抖出去
    段 4  低 cur · 一拍一振 2     再来一轮，看频闪连不连
    段 5  高 cur · 缓慢           `SetSpeed ×4` ⇒ cbpm 480；★ **零硬切**
    段 6  回正 · +90              直角弯 → 出弯后 rotation=90 把新方向转回水平
    段 7  回正 · −90              同结构换一档（对比哪一档对）
    段 8  雪花 · 近景（A）        32 格 ⇒ Tempest A
    段 9  雪花 · 远景（B）        64 格 ⇒ Tempest B
    段 10 复位诊断                只发定基、正文不动（v1 用户验过：没错）

## 口径（与 `tests/test_camera.py` 同一套）

`MoveCamera` 分三类（`_kind()`）：

* **定基事件** `lock`：`duration=0` + `rel=Player + pos=[0,0] + zoom=200 +
  rotation ≡ 0 (mod 360)` + **无 tag** —— 完整复位的唯一写法；
* **硬切事件** `cut`：`duration=0` + 任意姿态，**四样必须给齐**、**必须挂 tag**，
  且只许出现在「一拍一振段」与「雪花段进场」；
* **表演事件** `perf`：`duration ≥ 0.25`，一次只动**一个非归零维度**
  （雪花段放宽到 2，因为那边的 `zoom` 天生不在基准位）。

其余：`ease` ∈ `EASES`；`zoom ∈ [50,300]`（雪花 B 放到 600）；
`rotation ∈ [−30,30]`（回正段 ±90，360 的整数倍视为视觉归零、不设限）；
`position` 在 `Player` 帧**绝不许**留 `[null,null]`；`zoom` **绝不许** `null` / ≤0；
`RepeatEvents` 的 `tag` 带 `cam` 前缀（`docs/64` §6 尾）；
**只写 `actions`**，只在「回正段」给轨道加直角弯。
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import wave

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import path as path_mod                             # noqa: E402
from core import solve as solve_mod                           # noqa: E402
from core import writer as W                                  # noqa: E402

# ============================================================ 常量
BPM = 120.0
CD = 4
SR = 44100
OPEN = 12                 # 开局跑道
RUNWAY = 12               # 每段正文之前的跑道
SEP = 2                   # 段间分隔
BASE_ZOOM = 200.0         # ★ 基准位
LOCK_ROT = 0.0            # ★ 2026-10 **用户实测标定**：0 = 屏幕上直线水平
TAG = "cam_"              # ★ tag 命名空间（不与 core/show.py 的 出A/in_init/qe_pull 撞车）

MV_CAM_KEYS = frozenset((
    "floor", "eventType", "duration", "relativeTo", "position",
    "rotation", "zoom", "angleOffset", "ease", "eventTag",
))
REPEAT_KEYS = frozenset((
    "floor", "eventType", "repeatType", "repetitions", "interval",
    "floorCount", "executeOnCurrentFloor", "tag",
))
EASES = frozenset((
    "OutCubic", "InCubic", "OutQuad", "InQuad", "InOutQuad", "InOutCubic",
    "OutCirc", "InCirc", "InOutCirc", "OutQuart", "InQuart", "OutExpo",
    "InExpo", "OutBack", "InBack", "InOutBack", "OutElastic", "OutBounce",
    "OutFlash", "InFlash", "OutSine", "InOutSine", "Linear",
))
RESERVED_TAGS = frozenset((
    "出A", "出B", "出C", "出D", "入A", "入B", "入C",
    "in_init", "in_ret", "qe_hide", "qe_pull",
))

#: 每个**定基事件**用的 rotation（回正段由招式函数自己改，这里只是段首基准）
CAL_ROT = {}


# ============================================================ 事件构造
def cam(floor: int, *, dur: float, ease: str, zoom=None, rotation=0.0,
        position="auto", rel: str = "Player", ang: float = 0.0,
        tag: str = "") -> dict:
    """一条 `MoveCamera`。

    ★★★ **`zoom` 永远不许是 `null`（也永远不许是 0）** —— 2026-10 用户定位到的根因：

    > 「**缩放 无论如何 都不要设置为 0**」

    v1 的实测证据（`out/运镜验收谱/main.adofai`）：

    | 区间 | `"zoom": null` 条数 | 用户看到的现象 |
    |---|---|---|
    | 段 1~8（纯缩放） | **0** | ✅ 正常 |
    | 段 9~15（纯旋转） | **17 = 全部** | ❌ 看不见 |
    | 段 18（只发定基） | 0 | ✅ 「没错」 |

    ⇒ 纯旋转的那些事件以前写 `"zoom": null`（"不改缩放"），游戏把它读成了 0/失效，
    画面直接没了。**教学谱的写法是「整个 `zoom` 键都不写」**（`f504` 等），
    不是写 `null` —— 所以最稳的是**每条都给显式数值**。

    其余字段同理「能钉就钉」：`rotation` 默认 `0.0`、`position` 默认 `[0,0]`（Player 帧）。
    """
    if position == "auto":
        pos = [0, 0] if rel == "Player" else [None, None]
    else:
        pos = list(position) if position is not None else [None, None]
    z = float(BASE_ZOOM) if zoom is None else float(zoom)
    return {
        "floor": int(floor), "eventType": "MoveCamera",
        "duration": float(dur),
        "relativeTo": rel,
        "position": pos,
        "rotation": None if rotation is None else float(rotation),
        "zoom": z,
        "angleOffset": float(ang),
        "ease": ease,
        "eventTag": tag,
    }


def lock(floor: int, rot: float = LOCK_ROT) -> dict:
    """**定基事件**：`duration=0` + 完整复位（四样都给）。"""
    return cam(floor, dur=0.0, ease="Linear", zoom=BASE_ZOOM, rotation=float(rot),
               position=[0, 0], rel="Player", tag="")


def rep(floor: int, *, tag: str, reps: int, interval: int, rtype: str = "Beat",
        on_cur: bool = False, floor_count: int = 1) -> dict:
    return {
        "floor": int(floor), "eventType": "RepeatEvents",
        "repeatType": rtype, "repetitions": int(reps),
        "interval": int(interval), "floorCount": int(floor_count),
        "executeOnCurrentFloor": bool(on_cur),
        "tag": tag,
    }


def set_text(floor: int, tag: str, text: str) -> dict:
    return {"floor": int(floor), "eventType": "SetText", "decText": str(text),
            "tag": str(tag), "angleOffset": 0, "eventTag": ""}


def move_deco(floor: int, tag: str, *, opacity=None, dpos=None,
              dur: float = 0.0, ease: str = "Linear") -> dict:
    return {"floor": int(floor), "eventType": "MoveDecorations",
            "duration": float(dur), "tag": str(tag),
            "positionOffset": list(dpos) if dpos is not None else [None, None],
            "opacity": opacity, "parallaxOffset": [None, None],
            "angleOffset": 0, "ease": ease, "eventTag": ""}


def add_text(tag: str, pos, scale, *, text: str = "", opacity: int = 0,
             depth: int = -1) -> dict:
    return {
        "floor": 0, "eventType": "AddText", "locked": True, "decText": str(text),
        "tag": str(tag), "font": "Default", "position": list(pos),
        "relativeTo": "Camera", "pivotOffset": [0, 0], "rotation": 0,
        "lockRotation": True, "scale": list(scale), "lockScale": True,
        "color": "ffffff", "opacity": int(opacity), "depth": int(depth),
        "parallax": [0, 0], "parallaxOffset": [0, 0],
    }


# ============================================================ 招式（v2 只有三类）
# ---------------------------------------------------------------- ① 缓慢运镜
#: 「缓慢」段的幅度：用户 2026-10 第二轮回执「**2 3，数值浮动过小，看不出变化**」
#: ⇒ 从 175（只差 25）拉到 **120**（差 80）—— 仍然是"缓慢"，但一眼看得出在动。
SLOW_ZOOM_LO = 120.0
#: 缓慢位移的偏移量（格）：用户「段 4 的匀速过于呆板，**考虑使用缓速**」⇒ 缓速换 `OutQuad`，
#: 幅度 3 格 → **4 格**。
SLOW_PAN_TILES = 4.0
#: 「缓慢」这一段跨多少**格**（不是拍！）—— 去 8 格、回 8 格。
SLOW_SPAN_TILES = 8.0

# ---------------------------------------------------------------- 一拍一振
#: ★★ 2026-10 用户口径：「**慢速直接一拍一振好了，高速完全不用这个写法**」。
#:
#: `cur`（= cbpm）低于 `_CUR_SPLIT` 的段落，把原来的「跳跃」具体成
#: **每拍一条 `duration=0` 的硬切**（用户自己选的那档：「把原来的『跳跃』具体成每拍硬切一次」）。
#: 高 `cur` 段**一条硬切都不许有**（自检会拦）。
#:
#: 硬切的两个姿态（数值抄 Tempest 加强版 `f894..f914` 的抖动段，见 `docs/64` §9.2b）：
#:
#: | 拍 | 姿态 | `position` | `zoom` | `rotation` |
#: |---|---|---|---|---|
#: | 偶 | **定基**（复位） | `[0,0]` | 基准 200 | 0 |
#: | 奇 | **振** | `[JIT_TILES, 0]` | `JIT_ZOOM` | `JIT_ROT × 步进` |
JIT_TILES = 1.0           #: 振的横向位移（格）—— Tempest 用 `[-1,0]`
JIT_ZOOM = 170.0          #: 振的缩放 —— Tempest 用 160↔180
JIT_ROT = 5.0             #: 振的旋转步进（度）—— Tempest 每拍 +1°
JIT_ROT_STEPS = 4         #: 步进循环长度（`rotation` 走 5/10/15/20 再回头）

#: `cur` 分界：≥ 这个值算「高 cur」⇒ 用位置+呼吸+缓慢移动，**不许**一拍一振。
#: 与 `SolveParams.ladder_outer_cbpm` 同口径（`docs/64` §9.2）。
CUR_SPLIT = 400.0

# ---------------------------------------------------------------- 时值按「格」算
#: `build()` 填：`{段起始格: 该段的 cur（cbpm）}`
_CUR: dict = {}


def cur_at(s: int) -> float:
    """取该段的 `cur`（cbpm）。没登记过就按基准速度算（1 格 = 1 拍）。"""
    return float(_CUR.get(s) or BPM)


def beats_for_tiles(n: float, cur: float) -> float:
    """把「跨 `n` 格」换算成 `MoveCamera` 要写的**拍数**。

    ★★ 2026-10 用宏解析器（`tools/analyze_camera_cur.py`）实测出来的口径：

    `MoveCamera.duration` 的单位是**拍**，而**拍长只由 base bpm 决定、与 `SetSpeed` 无关**；
    该段的 1 格 = `60000/cur` 毫秒 = `base_bpm/cur` 拍。所以

        拍数 = 覆盖格数 × base_bpm / cur

    教学谱（`out/_camera/tut.adofai`）实测：`0~200 / 200~400 / 400~800 / ≥800`
    四档的「覆盖格数」**众数都是 1.0 格** —— 作者的真实规则是「**一条补间 ≈ 1 格**」，
    时值随 `cur` 变短只是被除出来的。

    ⇒ 所以本文件所有时值都**按格写**再换算成拍。v2 早先直接写「8 拍」，
      在高 cur 段（`SetSpeed ×4`）会变成 **32 格** —— 那段只有 16 格，**溢出 2 倍**，
      相机到段尾还在动、被下一段的定基硬切掉。这个 bug 就是上面那个工具抓出来的。
    """
    return float(n) * BPM / float(cur or BPM)

# ---------------------------------------------------------------- 雪花
#: ★★ 2026-10 用户口径：「**雪花的镜头写法……你去抄一下 Tempest 加强版**」，
#: 以及「**物量大的用 B，小的用 A**」。
#:
#: Tempest 加强版（`Plum-Tempest（加强版）`）里有两处密集 `SetSpeed` 段
#: （`401..684` 与 `1076..1361`，SetSpeed 序列逐字相同）—— 那就是雪花。作者给它们
#: 写了**两套**镜头：
#:
#: * **A（物量小）**`f402` 起：硬切 `rel=Tile pos=[0,0] zoom=100` → 16 格拉远到 `250`
#:   → 64 格转 `720°`（`InOutCirc`）；`f576` 横移 + `2880°`；`f669` 回 `Player`。
#: * **B（物量大）**`f1077` 起：硬切 `rel=Tile pos=[·,-14] zoom=600` → 长缓移
#:   （`InOutSine`）+ `5760°` 共 16 圈；`f1344` 回到 `Player`。
#:
#: ⇒ 本工具按**雪花格数**分流：`tiles <= SNOW_BIG_TILES` 走 A（近景居中），
#: 否则走 B（远景 + 长缓移 + 多圈）。两套的旋转角速度都从 Tempest 抄：
SNOW_BIG_TILES = 48.0
#: A 的角速度：Tempest 是 720°/64 拍 = **11.25°/拍** ⇒ 我们写「每 32 拍一圈」。
SNOW_A_DEG_PER_BEAT = 360.0 / 32.0
#: B 的角速度：Tempest 是 5760°/54 拍 ≈ 106.7°/拍 ⇒ 取整成「每 4 拍一圈」。
SNOW_B_DEG_PER_BEAT = 360.0 / 4.0
#: B 的远景参数（照抄 Tempest）
SNOW_B_ZOOM = 600.0
SNOW_B_DY = -14.0
SNOW_B_DX1 = -8.0
SNOW_B_DX2 = 12.0
#: A 的近景参数（照抄 Tempest）
SNOW_A_ZOOM_IN = 100.0
SNOW_A_ZOOM = 250.0
SNOW_A_PUSH_ZOOM = 210.0


def snow_spin_deg(L: int) -> float:
    """雪花段整体要转多少度 —— **永远是 360 的整数倍**（转完视觉上等于回正）。"""
    if L <= SNOW_BIG_TILES:
        n = max(1, int(round(L * SNOW_A_DEG_PER_BEAT / 360.0)))
    else:
        n = max(1, int(round(L * SNOW_B_DEG_PER_BEAT / 360.0)))
    return 360.0 * n


def m_slow_bind(s, e, ev):
    """① **缓慢运镜（缩放 + 位移 · 绑定）**：**同时**缓慢拉远 + 缓慢上偏，8 格去、8 格回。

    ★ 用户 2026-10 第三轮回执：**「2 不要了，3 留下，并且与 4 绑定使用」**
    ⇒ 原来的「段 2 纯 Linear」「段 3 只缩放」「段 4 只位移」三合一成**这一段**：

    * **缩放**用 `InOutSine`（原来段 3 的缓速，柔）；
    * **位移**用 `OutQuad`（原来段 4 换过的缓速，快起慢停不呆板）；
    * 两者**各发一条、同格并行** —— 仍然守住「每条只动一个维度」，
      "配合"靠**并排发**做到（教学谱 §2.4 的口径），而不是一条里塞两个字段。

    ★★ 时值**按格写**（`beats_for_tiles`）：这一段是「缓慢」的样板，所以让它跨
      **8 格**，而不是写死「8 拍」—— 在高 cur 段（`SetSpeed ×4`）"8 拍"会变成
      **32 格**，段只有 16 格，直接溢出（`tools/analyze_camera_cur.py` 抓到）。
    """
    cur = cur_at(s)
    d = beats_for_tiles(SLOW_SPAN_TILES, cur)
    ev.append(cam(s, dur=d, ease="InOutSine", zoom=SLOW_ZOOM_LO,
                  tag=TAG + "slow_zoom"))
    ev.append(cam(s, dur=d, ease="OutQuad", position=[0, SLOW_PAN_TILES],
                  tag=TAG + "slow_pan"))
    ev.append(cam(s + int(SLOW_SPAN_TILES), dur=d, ease="InOutSine",
                  zoom=BASE_ZOOM, tag=TAG + "slow_zoom"))
    ev.append(cam(s + int(SLOW_SPAN_TILES), dur=d, ease="OutQuad",
                  position=[0, 0], tag=TAG + "slow_pan"))


# ---------------------------------------------------------------- ② 低 cur：一拍一振
def m_beat_shake(s, e, ev):
    """②' **一拍一振**（低 `cur` 段专用）—— 每拍一条 `duration=0` 的硬切。

    ★★ 2026-10 用户口径（原话）：

    > 「慢速直接**一拍一振**好了，**高速完全不用这个写法**」

    它取代了旧版的「7+8 组合」（每 2 拍一对 `OutCirc` 弹出 → `InQuart` 拉回）：
    同样的「出+回」，但**压缩到一拍之内**，靠**硬切**而不是缓动 —— 慢速段落里
    缓动看不出变化，硬切才看得出「振」。

    姿态序列（**偶拍回定基、奇拍抖出去**）：

        k=0  定基   pos=[0,0]      zoom=200  rot=0
        k=1  振     pos=[1,0]      zoom=170  rot=5
        k=2  定基   pos=[0,0]      zoom=200  rot=0
        k=3  振     pos=[1,0]      zoom=170  rot=10
        …

    `rotation` 每振 +5°、走 4 档回头（`JIT_ROT_STEPS`）—— 「步进」这一点也是抄
    Tempest `f894..f914` 的（那边每拍 +1°，走 0…7）。

    ★ 这里**故意**在中途发 `duration=0`：`docs/64` §9.3 的「段中不许瞬跳」是给
    **雪花段 / 组合段**定的；一拍一振整段本来就是瞬跳，那一条对它不适用。

    ★★ **这个写法只在「1 格 = 1 拍」时成立**（`cur == base_bpm`）—— 因为「一拍一振」
      的节拍网格必须落在格子上。所以这里直接**硬拦**：不是 1 格 1 拍就不许用。
      （要支持变速段得把事件放到"拍"的网格上，那是接线那一轮的事。）
    """
    cur = cur_at(s)
    if abs(cur - BPM) > 1e-6:
        raise SystemExit(
            "一拍一振段（格 %d）的 cur=%g ≠ base bpm %g ⇒ 1 格不是 1 拍，"
            "节拍网格对不上格子。要么把这段设回基准速度，要么等接线那一轮"
            "实现「按拍网格放事件」。" % (s, cur, BPM))
    n = e - s + 1
    for k in range(n):
        f = s + k
        # ★ **奇拍回定基、偶拍抖出去**，且**末拍必须回定基** —— 否则段尾停在
        #   一个抖动姿态上，要等下一段的定基才复位，那中间就是「卡顿」。
        #   （段长取偶数的好处：最后一拍天然就是奇拍 = 定基，不会出现连续两条定基。）
        if k % 2 == 1 or k == n - 1:
            ev.append(lock(f))                       # 定基：无 tag、四样都给全
            continue
        step = (k // 2) % JIT_ROT_STEPS
        ev.append(cam(f, dur=0.0, ease="Linear", rel="Player",
                      position=[JIT_TILES, 0.0], zoom=JIT_ZOOM,
                      rotation=JIT_ROT * (step + 1), tag=TAG + "shake"))


# ---------------------------------------------------------------- ③ 回正
def _corner_body(travels, s, e, offset):
    """在正文的第 `offset` 格放一个 90° 直角弯（其余全直）。"""
    travels[s + offset] = 90.0


def m_rectify_pos(s, e, ev):
    """③ **回正 · 右转用 `rotation = +90`**：拐角那一格**镜头不动**，
    出拐角后短缓动把**新方向**转回水平（`docs/59` §3.1「拐角不动、出拐角后回正」）。

    一段里放**一右一左**两个拐角（`travel 90` / `270`）⇒ 轨道朝向走完又回到 0，
    所以这一段是**自足的**：段尾 `rotation` 也回到 0，不会把偏掉的朝向漏给下一段。
    """
    ev.append(cam(s + 7, dur=beats_for_tiles(4, cur_at(s)), ease="OutCubic",
                  rotation=90.0, tag=TAG + "rect_p90"))
    ev.append(cam(s + 15, dur=beats_for_tiles(4, cur_at(s)), ease="OutCubic",
                  rotation=0.0, tag=TAG + "rect_p90"))


def m_rectify_neg(s, e, ev):
    """③' **回正 · 右转用 `rotation = −90`**：同结构换一档 —— 两段只有这一个变量。"""
    ev.append(cam(s + 7, dur=beats_for_tiles(4, cur_at(s)), ease="OutCubic",
                  rotation=-90.0, tag=TAG + "rect_n90"))
    ev.append(cam(s + 15, dur=beats_for_tiles(4, cur_at(s)), ease="OutCubic",
                  rotation=0.0, tag=TAG + "rect_n90"))


def m_reset(s, e, ev):
    """④ **复位诊断**（v1 用户验过：没错）—— 只发段首定基，正文一个动作都不做。"""
    return None


# ---------------------------------------------------------------- ④ 雪花
#: `build()` 填：`{段起始格: (中心偏移 dx, 中心偏移 dy, 雪花格数)}`
_SNOW: dict = {}


def _snow_ctx(s: int):
    dx, dy, L = _SNOW.get(s, (0.0, 0.0, 0))
    if L <= 0:
        raise SystemExit("雪花段没有登记中心：s=%d" % s)
    return float(dx), float(dy), int(L)


def m_snow_near(s, e, ev):
    """④-A **雪花 · 物量小（`tiles <= SNOW_BIG_TILES`）· 近景居中**。

    逐条抄 Tempest 加强版 **A 段**（`f402` 起），只把拍数按我们的段长重排：

    | 格 | 跨 | rel | position | zoom | rotation | ease | tag |
    |---|---|---|---|---|---|---|---|
    | `s` | `0` | `Tile` | 中心 | `100` | 0 | `OutCubic` | `snowA_in` |
    | `s` | `L/4` 格 | `Tile` | 中心 | `250` | 0 | `InOutCirc` | `snowA_zoom` |
    | `s` | `3L/4` 格 | `Tile` | 中心 | `250` | `snow_spin_deg(L)` | `InOutCirc` | `snowA_spin` |
    | `s+3L/4` | `L/4` 格 | `Player` | `[0,0]` | `200` | 同上（**显式**，不回落） | `InOutCirc` | `snowA_back` |

    Tempest 的原文是 `f402` **三连发**（`d0 zoom=100` / `d16 zoom=250` /
    `d64 rotation=720`）—— **三条同格并行、各管一个维度**，正是本项目
    「表演事件只动一维」的写法（`docs/64` §9.3 ③）。

    ★ 旋转总角永远是 **360 的整数倍** ⇒ 转完视觉上等于回正，所以出场事件可以把
      `rotation` 原样带下去（不算回落），下一段的定基接管时不会看到角度突跳。
    ★ 表里的「跨」是**格**，写进 `duration` 前要过 `beats_for_tiles()`。
    """
    dx, dy, L = _snow_ctx(s)
    cur = cur_at(s)
    spin = snow_spin_deg(L)
    q = max(1, L // 4)
    ev.append(cam(s, dur=0.0, ease="OutCubic", rel="Tile", position=[dx, dy],
                  zoom=SNOW_A_ZOOM_IN, rotation=0.0, tag=TAG + "snowA_in"))
    ev.append(cam(s, dur=beats_for_tiles(q, cur), ease="InOutCirc", rel="Tile",
                  position=[dx, dy], zoom=SNOW_A_ZOOM, rotation=0.0,
                  tag=TAG + "snowA_zoom"))
    ev.append(cam(s, dur=beats_for_tiles(L - q, cur), ease="InOutCirc",
                  rel="Tile", position=[dx, dy], zoom=SNOW_A_ZOOM,
                  rotation=spin, tag=TAG + "snowA_spin"))
    ev.append(cam(s + (L - q), dur=beats_for_tiles(q, cur), ease="InOutCirc",
                  rel="Player", position=[0, 0], zoom=BASE_ZOOM,
                  rotation=spin, tag=TAG + "snowA_back"))


def m_snow_far(s, e, ev):
    """④-B **雪花 · 物量大（`tiles > SNOW_BIG_TILES`）· 远景 + 长缓移 + 多圈**。

    逐条抄 Tempest 加强版 **B 段**（`f1077` 起）：

    | 格 | 跨 | rel | position | zoom | rotation | angleOffset | ease | tag |
    |---|---|---|---|---|---|---|---|---|
    | `s` | `0` | `Tile` | 中心 + `(0,-14)` | `600` | 0 | 0 | `Linear` | `snowB_in` |
    | `s` | `L/2` 格 | `Tile` | 中心 + `(-8,-14)` | `600` | 0 | 0 | `InOutSine` | `snowB_drift` |
    | `s+L/2` | `L/2` 格 | `Tile` | 中心 + `(12,-14)` | `600` | 0 | 0 | `InOutSine` | `snowB_spin` |
    | `e` | `L/4` 格 | `Player` | `[0,0]` | `200` | 0 | 0 | `InCirc` | `snowB_back` |

    ★ 「多圈」这里走 `angleOffset`（Tempest B 也是 `angleOffset=5760`），
      而 A 段走 `rotation`（Tempest A 是 `rotation=720`）—— **两套照抄，不统一**，
      因为它们本来就是作者写的两种不同旋法。
    ★ 表里的「跨」是**格**，写进 `duration` 前要过 `beats_for_tiles()`。
    """
    dx, dy, L = _snow_ctx(s)
    cur = cur_at(s)
    spin = snow_spin_deg(L)
    half = max(1, L // 2)
    tail = max(1, L // 4)
    top = dy + SNOW_B_DY
    ev.append(cam(s, dur=0.0, ease="Linear", rel="Tile", position=[dx, top],
                  zoom=SNOW_B_ZOOM, rotation=0.0, tag=TAG + "snowB_in"))
    ev.append(cam(s, dur=beats_for_tiles(half, cur), ease="InOutSine", rel="Tile",
                  position=[dx + SNOW_B_DX1, top], zoom=SNOW_B_ZOOM,
                  rotation=0.0, tag=TAG + "snowB_drift"))
    ev.append(cam(s + half, dur=beats_for_tiles(half, cur), ease="InOutSine",
                  rel="Tile", position=[dx + SNOW_B_DX2, top], zoom=SNOW_B_ZOOM,
                  rotation=0.0, ang=spin, tag=TAG + "snowB_spin"))
    ev.append(cam(e, dur=beats_for_tiles(tail, cur), ease="InCirc", rel="Player",
                  position=[0, 0], zoom=BASE_ZOOM, rotation=0.0,
                  tag=TAG + "snowB_back"))


# ---------------------------------------------------------------- ⑤ 国士無双 · 两层
#: ★★ 2026-10 用户口径：「**准备开抄国士无双**」（`docs/67` 交接单）。
#:
#: 源文件 `Laur_-_国士無双\Done.adofai`，取样段 `1521..1778`（258 格，`cur` 恒定
#: **45.3 格/s** ≈ cbpm 2718，镜头 54 条）。实测出来的是**两层并行**，靠 `relativeTo`
#: 分工 —— 一层跟人、一层不跟人，所以两层**互不打架**：
#:
#: | 层 | `relativeTo` | 干什么 | 时值 | 节奏 |
#: |---|---|---|---|---|
#: | **宏观 · 长锚** | `Player` | 大偏移（`pos=[-4,3]` / `zoom=300`），**慢慢漂** | **按拍写死** | 走完才重发 |
#: | **宏观 · 弹回** | `Player` | 同一姿态，把画面**拉回宏观位** | **按拍写死** | **每一串微观的串尾** |
#: | **微观** | `Tile` | 小步跳（`pos` 在 6 个值间轮换 / `zoom=210`） | **按拍写死** | **每 2 格一条，一串 3~6 条** |
#:
#: ★★ **2026-10 复测修正**：初版写的是「宏观层每 44~78 格重发一次」+「微观连续每 2 格」
#:   —— **两个都不对**。把 `1500..1800` 逐条摊开重数之后，真实结构是
#:   「**微观成串 + 串尾弹回 + 长锚静默**」：
#:
#:   ```
#:   1569,1571,1573  微观 Tile（每 2 格一条）      ← 一串 3 条
#:   1575            宏观 Player dur=4  OutCirc    ← 「弹回」，串尾一定有
#:   1579,1581,1583  微观（下一串）
#:   1585            宏观 Player dur=32 OutCirc    ← 长锚（跨 256 格）
#:           …1585..1629 共 44 格**一条微观都没有**（长锚自己在走）
#:   ```
#:
#:   ⇒ 弹回间隔是 **10~16 格**（不是 44~78）；微观串长 **3~6 条**（不是整段连续）。
#:
#: ★ 这一套解掉了 `docs/64` §9.2 的「**高 cur 二选一**」：高 cur 不必只做"缓慢"，
#:   两层叠起来既有跟人的稳、又有不跟人的抖。
#:
#: ★ 拍数**不能照搬**：国士 `cur/base = 8`，一条 `64` 拍补间覆盖 **512 格**。
#:   换算要按**秒**过（见 `tools/apply_camera_gs.py` 的换算表：国士 base 340 的
#:   `1.66667` 拍 = 294 ms）。demo 的 base 是 120，所以「1 乐句拍 = 1 拍」：
#:   微观 `1` 拍（0.5 s）、弹回 `2` 拍（1 s）、长锚 `20` 拍（10 s）。
#:   **都是"拍"值**，不是被格数除出来的（这正是「按拍」）。
GS_MACRO_REL = "Player"
GS_MACRO_POS = [-4.0, 3.0]          #: 跟人层的大偏移（国士無双全体一致）
GS_MACRO_ZOOM = 300.0               #: 跟人层的缩放（正好压在表演事件的上限）
#: 长锚时值（国士 `32` 拍 @340 = 5.65 s ⇒ demo 取 `20` 拍 = 10 s）
GS_LONG_BEATS = 20.0
#: 串尾「弹回」时值（国士 `4` 拍 @340 = 0.706 s ⇒ demo 取 `2` 拍 = 1 s）
GS_SNAP_BEATS = 2.0
#: ★ 两个宏观时值都**按拍写死**，**不走 `beats_for_tiles()`**。
GS_MACRO_BEATS_SET = (GS_LONG_BEATS, GS_SNAP_BEATS)
GS_MACRO_EASE_LONG = "OutExpo"      #: 长锚（国士無双 `f1521` / `f1585`）
GS_MACRO_EASE_SNAP = "OutCirc"      #: 弹回（国士無双 `f1575` 起）
GS_MICRO_REL = "Tile"
GS_MICRO_ZOOM = 210.0               #: 国士無双 用 210（偶有 220 / 230）
#: 微观时值（国士 `1.66667` 拍 @340 = 294 ms ⇒ demo 取 `1` 拍 = 0.5 s）
GS_MICRO_BEATS = 1.0
GS_MICRO_BEATS_SLOW = 1.0           #: 太慢那一档（网格退回每格，时值不变）
GS_MICRO_POS = ((-2.5, 2.0), (-1.5, 1.0), (-1.5, 2.0),
                (-2.0, 2.0), (-2.0, 1.0), (-2.5, 1.0))
GS_MICRO_TILES_FAST = 2             #: 不慢时：**每 2 格一条**（照抄国士無双）
GS_MICRO_TILES_SLOW = 1             #: 太慢时：每 1 格一条（= 现有「一拍一振」的网格）
#: ★ 微观**串长**的循环表 —— 国士实测是 **3/3/3/4/6/3/3/5/3/5** 条。
GS_BURST_PATTERN = (3, 4, 6, 5)
#: 「弹回」之后的空隙（格）—— 国士是「串尾弹回，4 格后下一串」。
GS_SNAP_GAP_TILES = 4
#: 长锚之后的**静默期**（格）—— 国士是 44 格一条微观都不发。
GS_LULL_TILES = 32
GS_BACK_BEATS = 2.0                 #: 出场归位：按拍写死的补间
#: ★ 进场招牌（国士無双 `f1517..f1519`）—— 用户 2026-10：
#: 「**开局无所谓喵 可以抄为可选项目**」⇒ 做成**可选开关**（段选项 `gs_entry`），
#: **默认关**。理由：`zoom=1` 贴着下限，而本项目的红线是「`zoom` 永不为 0」，
#: `1` 离它只有一步；`zoom=320` 也超出了普通表演事件的 300 上限。
GS_ENTRY_ZOOM_IN = 120.0
GS_ENTRY_ZOOM_MID = 320.0
GS_ENTRY_ZOOM_LO = 1.0
GS_ENTRY_POS = [2.0, 0.0]
GS_ENTRY_ANG = 720.0
GS_ENTRY_BEATS = 4.0

#: `build()` 填：`{段起始格: 是否发进场招牌}`（段选项 `gs_entry=True` 时登记）
_GS_ENTRY: dict = {}


def gs_micro_step(cur: float) -> int:
    """微观层的**节奏**（每几格一条）。

    ★ 用户 2026-10 口径：「**太慢的用现有，别的用国士无双**」

    ⇒ `cur < CUR_SPLIT`（慢段）退回**每 1 格一条**（与现有「一拍一振」同一个网格），
      其余情况照抄国士無双的「**每 2 格一条**」。

    ★ **不许静默**：调用方（`verify()` / 清单 / 汇报）都要把选中的那一档写出来。
    """
    return GS_MICRO_TILES_SLOW if float(cur) < CUR_SPLIT else GS_MICRO_TILES_FAST


def _gs_entry(s: int) -> bool:
    return bool(_GS_ENTRY.get(int(s)))


def m_gs_double_layer(s, e, ev):
    """⑤ **国士無双 · 两层**（宏观跟人 + 微观不跟人，**并行**）。

    逐条抄 `Laur_-_国士無双` 的 `Done.adofai` `1521..1778`：

    | 层 | 格 | `dur`（拍） | `rel` | `position` | `zoom` | `rotation` | `ease` | tag |
    |---|---|---|---|---|---|---|---|---|
    | 宏观 · 长锚 | 每 `GS_LONG_BEATS × cur/BPM` 格 | **`GS_LONG_BEATS`** | `Player` | `[-4,3]` | `300` | 0 | `OutExpo` | `gs_long` |
    | 宏观 · 弹回 | 每一串微观的串尾 | **`GS_SNAP_BEATS`** | `Player` | `[-4,3]` | `300` | 0 | `OutCirc` | `gs_snap` |
    | 微观 | 串内每 `step` 格 | **`GS_MICRO_BEATS`** | `Tile` | 6 个值轮换 | `210` | 0 | `OutElastic` | `gs_micro` |
    | 出场 | `e` | `GS_BACK_BEATS` | `Player` | `[0,0]` | 基准 | 0 | `OutCubic` | `gs_back` |

    国士無双的原文结构（`docs/67` §1，**2026-10 复测修正版**）：

        f1569,1571,1573 微观 Tile 每 2 格一条            ← 一串 3 条
        f1575           宏观 Player dur=4  OutCirc       ← 「弹回」，串尾一定有
        f1579,1581,1583 微观（下一串）
        f1585           宏观 Player dur=32 OutCirc       ← 长锚（跨 256 格）
                …1585..1629 共 44 格**一条微观都没有**（长锚自己在走）

    ★★ 所以本函数按**三段循环**铺，不是"连续微观"：

    1. **长锚**（`OutExpo`）：上一条的 `GS_LONG_BEATS` 拍走完（按格折算）才发下一条
       —— 国士那发 `32` 拍自己就跨 256 格，不会每 10 格来一发；
    2. **静默期** `GS_LULL_TILES` 格：一条微观都不发（照抄国士那 44 格）；
    3. **微观串**：`GS_BURST_PATTERN` 里取一个串长，串内每 `step` 格一条；
       串尾发一条**弹回**，然后空 `GS_SNAP_GAP_TILES` 格再开下一串。

    ★ **微观层的时值也是"拍"**（照抄国士），只有**节奏**是按格
      （`gs_micro_step()`）。慢段退回每格一条 —— 用户 2026-10：
      「**太慢的用现有，别的用国士无双**」。

    ★ 出场归位（`gs_back`）是**本工具加的**，国士無双那段本来在整首谱中间、不需要收尾；
      我们每段自成一体，收尾不回基准的话下一段的定基会瞬跳（`docs/64` §9.3 ①）。
      **这一条是偏离素材的，已在此写明。**
    """
    cur = cur_at(s)
    step = gs_micro_step(cur)
    mbeats = GS_MICRO_BEATS if step == GS_MICRO_TILES_FAST else GS_MICRO_BEATS_SLOW

    # ---- 可选进场招牌（`gs_entry=True`）—— 照抄国士無双 `f1517..f1519`
    if _gs_entry(s):
        ev.append(cam(s, dur=GS_ENTRY_BEATS, ease="OutElastic", rel="Tile",
                      position=[0.0, 0.0], zoom=GS_ENTRY_ZOOM_IN, rotation=0.0,
                      tag=TAG + "gs_entry"))
        ev.append(cam(s, dur=GS_ENTRY_BEATS, ease="OutCubic", rel="Tile",
                      position=[0.0, 0.0], zoom=GS_ENTRY_ZOOM_MID, rotation=0.0,
                      tag=TAG + "gs_entry_zoom"))
        ev.append(cam(s, dur=GS_ENTRY_BEATS, ease="InBack", rel="Tile",
                      position=list(GS_ENTRY_POS), zoom=GS_ENTRY_ZOOM_LO,
                      rotation=0.0, ang=GS_ENTRY_ANG, tag=TAG + "gs_entry_spin"))

    long_cover = max(1.0, GS_LONG_BEATS * cur / BPM)   # 长锚覆盖多少格
    long_until = float(s)
    blocked_until = float(s)
    bi = 0
    j = 0
    f = float(s)
    while f <= e:
        if f < blocked_until:                          # 静默期
            f += 1
            continue
        if f >= long_until:                            # 长锚（走完才重发）
            ev.append(cam(int(f), dur=GS_LONG_BEATS, ease=GS_MACRO_EASE_LONG,
                          rel=GS_MACRO_REL, position=list(GS_MACRO_POS),
                          zoom=GS_MACRO_ZOOM, rotation=0.0, tag=TAG + "gs_long"))
            long_until = f + long_cover
            blocked_until = f + GS_LULL_TILES
            continue
        b = GS_BURST_PATTERN[bi % len(GS_BURST_PATTERN)]   # 一串微观
        bi += 1
        made = 0
        for _k in range(b):
            if f > e - step:
                break
            px, py = GS_MICRO_POS[j % len(GS_MICRO_POS)]
            ev.append(cam(int(f), dur=mbeats, ease="OutElastic", rel=GS_MICRO_REL,
                          position=[px, py], zoom=GS_MICRO_ZOOM, rotation=0.0,
                          tag=TAG + "gs_micro"))
            j += 1
            made += 1
            f += step
        if not made:
            break
        if f <= e - step:                              # 串尾「弹回」
            ev.append(cam(int(f), dur=GS_SNAP_BEATS, ease=GS_MACRO_EASE_SNAP,
                          rel=GS_MACRO_REL, position=list(GS_MACRO_POS),
                          zoom=GS_MACRO_ZOOM, rotation=0.0, tag=TAG + "gs_snap"))
            f += GS_SNAP_GAP_TILES

    # ---- 出场归位（按拍）
    ev.append(cam(e, dur=GS_BACK_BEATS, ease="OutCubic", rel="Player",
                  position=[0.0, 0.0], zoom=BASE_ZOOM, rotation=0.0,
                  tag=TAG + "gs_back"))


# ============================================================ 段落表
#: (键, 正文格数, 标题, 看什么, 招式, 选项)
#: 选项：`corners=[(偏移, travel)]` 放拐角；`nolock=True` 不发段首定基；`glue=True` 紧接上一段
#: ★ 标题里**不要写段号** —— 段号由清单/EditorComment 按序号生成，写死会随增删漂掉。
SECTIONS: list[tuple] = [
    ("基准", 8, "基准（完全不动镜头）",
     "看什么：这一段一个镜头事件都没有 —— 记住「正常」是什么样", None, {}),
    ("缓慢·绑定", 16, "缓慢运镜（拉远 + 上偏 · 绑定）—— 高 cur 档的样板",
     "看什么：★ 镜头**同时**缓慢拉远（InOutSine，200↔120）与缓慢上偏"
     "（OutQuad，4 格）—— 两个维度**并行**，8 拍去 8 拍回。"
     "这就是你说的「3 与 4 绑定使用」，也是**高 cur 段**的标准写法。", m_slow_bind, {}),
    ("低cur·一拍一振", 16, "低 cur · 一拍一振（cbpm 120 < 400）",
     "看什么：★★ 每**一拍**（= 每格 = 500ms）一次**硬切**：偶拍回基准、"
     "奇拍抖出去（位置 +1 格、zoom 170、rotation 5/10/15/20 循环）。"
     "这就是「慢速直接一拍一振」—— 该看到**一格一抖**的频闪感，不是平滑滑动。",
     m_beat_shake, {}),
    ("低cur·一拍一振2", 16, "低 cur · 一拍一振（第二轮 · 看重复是否自然）",
     "看什么：★ 与上一段逐拍同构地再来一轮 —— 盯**两轮之间的接缝**，"
     "频闪应当连贯，不该有半拍的空档或多余的一抖。", m_beat_shake, {}),
    ("高cur·缓慢", 16, "高 cur · 位置 + 呼吸 + 缓慢移动（cbpm 480 ≥ 400）",
     "看什么：★★ 这一段被 `SetSpeed ×4` 提速到 cbpm 480 ⇒ 按你的口径用"
     "**位置 + 呼吸 + 缓慢移动**：`InOutSine` 缩放（200↔120）与 `OutQuad` 位移"
     "（4 格）**并行**、8 拍去 8 拍回。★ **这一段一条硬切都没有** —— "
     "「高速完全不用一拍一振那个写法」就是这条。",
     m_slow_bind, {"speed_x": 4.0}),
    ("国士無双·两层", 128, "★★ 国士無双 · 两层（宏观跟人 + 微观不跟人，cbpm 480）",
     "看什么：★★ 抄自 `Laur_-_国士無双`。这一段**同时**有两层镜头 —— "
     "① **宏观层**（`relativeTo=Player`，跟人）：`pos=[-4,3]` / `zoom=300`，"
     "**按拍写死 20 拍**一条长锚（`OutExpo`，走完才重发），每串微观末尾还有一条 "
     "**弹回**（`OutCirc`，2 拍）；"
     "② **微观层**（`relativeTo=Tile`，不跟人）：`zoom=210`、`pos` 在 6 个小值间轮换、"
     "`OutElastic`、**每 2 格一条，一串 3~6 条**。"
     "★ 两层一个跟人一个不跟人，所以**互不打架** —— "
     "这就是「高 cur 只能缓慢」那个二选一的解法。"
     "★ 长锚之后有 **32 格静默期**（照抄国士那 44 格）：那几秒画面应当**慢慢漂**，"
     "一条微观都不该有。**和上一段比一比**：同样的 cbpm 480，"
     "一个只有缓慢、一个有跟人 + 不跟人两层。",
     m_gs_double_layer, {"speed_x": 4.0}),
    ("回正·+90", 24, "回正（右转用 rotation = +90）",
     "看什么：★ 前 7 格直线水平 → 第 8 格（正文第 7 格）**拐直角、镜头不动** → "
     "出拐角后用 4 拍转到 `rotation=90`。**新方向回到水平了吗？**"
     "　然后还有**第二组**：再遇一个**反向**（左转）拐角，镜头用 4 拍转回 `rotation=0`。",
     m_rectify_pos, {"corners": [(6, 90.0), (14, 270.0)]}),
    ("回正·-90", 24, "回正（右转用 rotation = −90）",
     "看什么：★ 与上一段同结构，只把**右转那一档**换成 `−90` —— "
     "两段只有这一个变量",
     m_rectify_neg, {"corners": [(6, 90.0), (14, 270.0)]}),
    ("雪花·近景", 32, "★ 雪花 A（物量小 ≤48 格）：镜头钉在正中央 · 近景",
     "看什么：★★ 玩家绕着雪花转，**镜头钉在雪花正中央不动**（`relativeTo=Tile`），"
     "进场硬切怼近到 zoom 100 → 4 拍拉远到 250 → 整段**缓速转一圈** → "
     "出雪花缓速回玩家。抄的是 Tempest 加强版 `f402` 那一套（`docs/64` §9.2b A）。",
     m_snow_near, {"snow": 32}),
    ("雪花·远景", 64, "★ 雪花 B（物量大 >48 格）：远景 + 长缓移 + 多圈",
     "看什么：★★ 同一朵雪花的**大物量**写法：进场硬切拉到 `zoom=600`、"
     "镜头退到下方 14 格（远景俯视），整段缓慢横移（−8 → +12 格）同时"
     "**转 16 圈**，收尾回玩家。抄的是 Tempest 加强版 `f1077` 那一套"
     "（`docs/64` §9.2b B）。和上一段比一比：**哪种更适合大雪花？**",
     m_snow_far, {"snow": 64}),
    ("复位诊断", 8, "复位诊断（只发段首定基，正文不动）",
     "看什么：这一段什么都不做 —— 画面应当恢复正常（v1 已验过）", m_reset, {}),
]


# ============================================================ 组装
def build():
    secs: list[dict] = []
    cursor = OPEN
    for key, body, title, watch, fn, opt in SECTIONS:
        glue = bool(opt.get("glue"))
        # `glue=True` ⇒ **紧接上一段**：不收跑道、不加段间分隔 ——
        # 这才是"无缝衔接"的字面意思（留着跑道就等于中间空一段没人管相机）。
        if secs and not glue:
            cursor += SEP
        s = cursor + (0 if glue else RUNWAY)
        e = s + body - 1
        secs.append(dict(key=key, body=body, title=title, watch=watch, fn=fn,
                         s=s, e=e, runway0=cursor,
                         corners=list(opt.get("corners") or ()),
                         nolock=bool(opt.get("nolock")), glue=glue,
                         speed_x=float(opt.get("speed_x") or 1.0),
                         gs_entry=bool(opt.get("gs_entry")),
                         snow=int(opt.get("snow") or 0)))
        cursor = e + 1
    n_tiles = cursor + 8

    # ★ 国士無双 的**可选进场招牌**（`zoom=1` + 两整圈，用户 2026-10：
    #   「开局无所谓喵 可以抄为可选项目」）—— 必须在招式函数跑之前登记。
    for sec in secs:
        _GS_ENTRY[sec["s"]] = bool(sec["gs_entry"])

    # ---- ① 轨道：直角弯 + 雪花几何
    travels = [180.0] * n_tiles
    for sec in secs:
        for off, tv in sec["corners"]:
            if 0 <= off < sec["body"]:
                travels[sec["s"] + off] = float(tv)
    for sec in secs:
        if not sec["snow"]:
            continue
        from core import snowflake as SN
        sp = SN.plan(int(sec["snow"]))
        if sp is None or sp.tiles != sec["snow"]:
            raise SystemExit("雪花排不出来：L=%d ⇒ %s" % (sec["snow"], sp))
        tv = sp.travels()
        travels[sec["s"]:sec["s"] + len(tv)] = tv
        sec["snow_spec"] = sp

    # ---- ② 每格的当前速度（`cur` = `Floor.bpm` = cbpm）
    bpms = [BPM] * n_tiles
    set_speeds: list[tuple[int, float]] = []
    for sec in secs:
        if sec["speed_x"] == 1.0:
            continue
        b = BPM * sec["speed_x"]
        for i in range(sec["s"], sec["e"] + 1):
            bpms[i] = b
        set_speeds.append((sec["s"], b))                 # 提速
        if sec["e"] + 1 < n_tiles:
            set_speeds.append((sec["e"] + 1, BPM))       # 下一段恢复
    # ★ 登记每段的 `cur`（cbpm）—— 招式算时值要用（`beats_for_tiles`）。
    for sec in secs:
        _CUR[sec["s"]] = BPM * sec["speed_x"]

    floors = [solve_mod.Floor(travel=travels[i], bpm=bpms[i], twirl=False, turn=0.0,
                              heading=0.0, angle=0.0, speed_k=1.0, pause_beats=0.0)
              for i in range(n_tiles)]
    p = path_mod.Path.from_floors(floors, [False] * n_tiles, allow_twirl=True)
    p.commit_to(floors, write_twirl=False)
    ch = solve_mod.Chart(base_bpm=BPM, floors=floors, meta={})
    # ★ `Chart.set_speed_floors` 是**派生属性**（`f.bpm` 与上一个有效值不同处自动出
    #   SetSpeed）⇒ 只要把 `floors[i].bpm` 设对，事件自己就出来了，不用手动登记。

    # ---- ③ 雪花中心（用**真实路径坐标**算，不另起一套几何）
    for sec in secs:
        if not sec["snow"]:
            continue
        pts = p.points[sec["s"]:sec["s"] + sec["snow"] + 1]
        cx = (min(q[0] for q in pts) + max(q[0] for q in pts)) / 2.0
        cy = (min(q[1] for q in pts) + max(q[1] for q in pts)) / 2.0
        x0, y0 = p.points[sec["s"]]
        # ★ `-0.0` 归成 `0.0`：落盘后 JSON 里写 `-0.0` 很脏，游戏读起来虽然一样，
        #   但清单/对比时会看不出差异。
        _SNOW[sec["s"]] = (round(cx - x0, 4) + 0.0 or 0.0,
                           round(cy - y0, 4) + 0.0 or 0.0,
                           sec["snow"])

    ev: list[dict] = []
    for sec in secs:
        s, e, fn = sec["s"], sec["e"], sec["fn"]
        if fn is None:
            continue                                   # 段 1「基准」：一个镜头事件都不发
        # ★★ 用户口径「**物量大的用 B，小的用 A**」—— 唯一的判据是雪花格数，
        #    `SNOW_BIG_TILES` 以上走 Tempest 的远景写法，以下走近景写法。
        if sec["snow"]:
            fn = m_snow_far if sec["snow"] > SNOW_BIG_TILES else m_snow_near
            sec["snow_recipe"] = "B" if sec["snow"] > SNOW_BIG_TILES else "A"
        if not sec["nolock"]:
            ev.append(lock(s - 1))
        fn(s, e, ev)

    for i, sec in enumerate(secs, start=1):
        s, e = sec["s"], sec["e"]
        ev.append(set_text(s, "1", sec["title"]))
        ev.append(set_text(s, "2", sec["watch"]))
        ev.append(move_deco(s, "1 2", opacity=100))
        ev.append(move_deco(e + 1, "1 2", opacity=0))

    ev.sort(key=lambda a: (int(a["floor"]), _order(a["eventType"]),
                           a.get("angleOffset") or 0))
    return ch, ev, secs, set_speeds


def _order(et: str) -> int:
    return {"SetSpeed": 0, "Twirl": 0, "Pause": 0, "MoveCamera": 1,
            "RepeatEvents": 2, "SetText": 3, "MoveDecorations": 4,
            "MoveTrack": 5, "EditorComment": 6}.get(et, 7)


# ============================================================ 自检
def _is_visually_zero_rot(r) -> bool:
    """`rotation` 算不算「视觉上的归零」—— **360 的整数倍**都算。

    Tempest 加强版就是这么写的：A 段 `rotation=720`、B 段 `angleOffset=5760`。
    转完整圈在画面上与 0 无异 ⇒ 出场事件可以把这个值**原样带下去**，不算回落，
    下一段的定基接管时也不会看到角度突跳。
    """
    if r is None:
        return True
    return abs(float(r) % 360.0) < 1e-9


def _dims(a) -> list:
    """这条 `MoveCamera` 离**基准位**有多远的维度。

    ★ 归零量（不算"动"）：`zoom == 基准`、`position == [0,0]`、`rotation ≡ 0 (mod 360)`
    —— 它们是"把这一维钉回基准"，正是"不要有卡顿或原始运镜"要的写法
    （`docs/64` §8.5.2）。只有**非归零**量才与别的维度互斥。
    """
    out = []
    if a.get("zoom") is not None and abs(float(a["zoom"]) - BASE_ZOOM) > 1e-9:
        out.append("zoom")
    if not _is_visually_zero_rot(a.get("rotation")):
        out.append("rotation")
    pos = a.get("position")
    if pos not in (None, [None, None]):
        if pos != [0, 0] or not out:
            out.append("position")
    return out


#: `MoveCamera` 的三种角色（`duration` + 形状合起来判）
#:
#: * `lock` —— **定基事件**：`duration=0` + 完整复位（`Player` + `[0,0]` + 基准 zoom
#:   + 视觉归零的 rotation + 无 tag）。「复位」的唯一正确写法。
#: * `cut`  —— **硬切事件**：`duration=0` + 任意姿态。**一拍一振**专用
#:   （`docs/64` §9.2b）。硬切是"换一个姿态"，所以**必须一次把四样给齐**，
#:   「表演事件只动一维」对它是无意义的（它压根不是补间）。
#: * `perf` —— **表演事件**：`duration>0`，走补间，受「一条一维」约束。
def _kind(a) -> str:
    if float(a.get("duration") or 0.0) > 0.0:
        return "perf"
    if (a.get("relativeTo") == "Player" and a.get("position") == [0, 0]
            and not a.get("eventTag")
            and a.get("zoom") is not None
            and abs(float(a["zoom"]) - BASE_ZOOM) < 1e-9
            and _is_visually_zero_rot(a.get("rotation"))):
        return "lock"
    return "cut"


def _is_lock(a) -> bool:
    """兼容旧名：`duration=0` 的都算「瞬跳类」（定基 / 硬切）。"""
    return _kind(a) != "perf"


def verify(ev, ch, secs) -> list[str]:
    bad: list[str] = []
    mv = [a for a in ev if a["eventType"] == "MoveCamera"]
    rp = [a for a in ev if a["eventType"] == "RepeatEvents"]

    shake_secs = [sec for sec in secs if sec["fn"] is m_beat_shake]
    snow_secs = [sec for sec in secs if sec["snow"]]
    gs_secs = [sec for sec in secs if sec["fn"] is m_gs_double_layer]
    high_secs = [sec for sec in secs if sec["speed_x"] > 1.0]

    def _in(sec_list, f) -> bool:
        return any(sec["s"] <= f <= sec["e"] for sec in sec_list)

    for a in mv:
        if not set(a) <= set(MV_CAM_KEYS):
            bad.append(f"MoveCamera 出现白名单外的字段：{sorted(set(a) - MV_CAM_KEYS)}")
            break
    for a in rp:
        if not set(a) <= set(REPEAT_KEYS):
            bad.append(f"RepeatEvents 出现白名单外的字段：{sorted(set(a) - REPEAT_KEYS)}")
            break

    fl = [int(a["floor"]) for a in ev]
    if fl != sorted(fl):
        bad.append("事件没有按 floor 有序")

    for a in mv:
        if not a.get("relativeTo"):
            bad.append(f"floor {a['floor']} 没写 relativeTo")
            break
        if a["relativeTo"] not in ("Player", "Tile", "Global", "LastPosition",
                                   "LastPositionNoRotation"):
            bad.append(f"floor {a['floor']}：relativeTo {a['relativeTo']!r} 非法")
            break

    # ---- 定基 / 硬切 / 表演：三类各自的形状约束
    for a in mv:
        if _kind(a) != "lock":
            continue
        miss = [k for k in ("zoom", "rotation", "position", "relativeTo")
                if a.get(k) in (None, [None, None])]
        if miss:
            bad.append(f"floor {a['floor']}：定基事件没给 {miss}（状态会漏段）")
            break
        if abs(float(a["zoom"]) - BASE_ZOOM) > 1e-9:
            bad.append(f"floor {a['floor']}：定基 zoom != 基准")
            break
    cuts = [a for a in mv if _kind(a) == "cut"]
    for a in cuts:
        miss = [k for k in ("zoom", "rotation", "position", "relativeTo")
                if a.get(k) in (None, [None, None])]
        if miss:
            bad.append(f"floor {a['floor']}：硬切事件没给 {miss}"
                       f"（硬切要一次换完整姿态）")
            break
        if not a.get("eventTag"):
            bad.append(f"floor {a['floor']}：硬切事件没挂 tag")
            break
    # ★ 硬切只许出现在**一拍一振段**和**雪花段的进场** —— 别的地方发 `duration=0`
    #   就是「卡顿」。雪花段的进场硬切是抄 Tempest 的（A `f402` / B `f1077` 都是
    #   `duration=0` + `relativeTo=Tile`），属于设计，不算瞬跳。
    stray = [a for a in cuts
             if not _in(shake_secs, int(a["floor"]))
             and not _in(snow_secs, int(a["floor"]))]
    if stray:
        bad.append(f"floor {stray[0]['floor']}：一拍一振 / 雪花进场以外的位置出现硬切"
                   f"（`docs/64` §9.3 ①：段中不许瞬跳）")
    perf = [a for a in mv if _kind(a) == "perf"]
    for a in perf:
        if float(a["duration"]) < 0.25:
            bad.append(f"floor {a['floor']}：表演事件 duration < 0.25")
            break
        d = _dims(a)
        # 0 个 = **归位事件**（把所有维度都送回基准，用于平滑收尾）；1 个 = 表演动作。
        # ★ 雪花段放宽到 2：那边 `zoom` 天生不在基准位（A=250 / B=600），
        #   所以哪怕只动位置，按「离基准多远」算也会带上 zoom 这一维。
        # ★★ 国士無双·两层段也放宽到 2：那一套**本来就同时给 position 与 zoom**
        #   （宏观 `[-4,3]`+`300`、微观 小步跳+`210`），是作者的**分层**写法 ——
        #   它靠 `relativeTo` 分工（一层跟人、一层不跟人）而不是靠"只动一维"。
        #   「一条一维」是教学谱那一套的规矩（93%），**不是国士無双的**。
        lim = 2 if (_in(snow_secs, int(a["floor"]))
                    or _in(gs_secs, int(a["floor"]))) else 1
        if len(d) > lim:
            bad.append(f"floor {a['floor']}：表演事件动了 {d} —— 教学谱 93% 是一条一维")
            break
    # ★ 每条 Player 帧事件都要**显式给 position**（v1 的坑：`[null,null]` = 不改位置
    #   ⇒ 纯旋转段里没人去重算位置，相机跟不住玩家就"看不见"了）。
    #   `[0,0]` = 钉在玩家身上；`[0,3]` = 显式偏移（段 4 的匀速位移就是这么写的）——
    #   两种都行，**只禁 `[null,null]`**。
    loose = [a for a in mv
             if a.get("relativeTo") == "Player"
             and a.get("position") in (None, [None, None])]
    if loose:
        bad.append(f"floor {loose[0]['floor']}：Player 帧却把 position 留着 [null,null]"
                   f"（v1 就是这里把相机弄没的）")

    # ★★★ 2026-10 用户定位的根因：**`zoom` 永远不许是 null / 0**。
    #   v1 的段 9~15（纯旋转）全部写了 `"zoom": null` ⇒ 画面直接没了；
    #   段 1~8 / 段 18 有显式 zoom ⇒ 正常。**这条是本工具最重要的一条断言。**
    zn = [a for a in mv if a.get("zoom") is None]
    z0 = [a for a in mv if a.get("zoom") is not None and float(a["zoom"]) <= 0.0]
    if zn:
        bad.append(f"floor {zn[0]['floor']}：zoom 是 null（用户实测：画面会直接消失）")
    if z0:
        bad.append(f"floor {z0[0]['floor']}：zoom = {z0[0]['zoom']} ≤ 0（绝不许）")
    for a in perf:
        z = float(a["zoom"])
        # 雪花 B 段照抄 Tempest 的 `zoom=600`（远景俯视），所以上限分段放宽。
        zlo, zhi = 50.0, 300.0
        if _in(snow_secs, int(a["floor"])):
            zhi = SNOW_B_ZOOM
        elif _in(gs_secs, int(a["floor"])):
            # ★ 国士無双的**可选进场招牌**（`gs_entry=True`）要 `zoom=320` 与 `zoom=1`
            #   —— 那是语料里的原值，开了这个开关就按它的值域放行（`zoom>0` 仍然是红线）。
            gs_hit = [x for x in gs_secs
                      if x["s"] - 1 <= int(a["floor"]) <= x["e"] and _gs_entry(x["s"])]
            if gs_hit:
                zlo = min(zlo, GS_ENTRY_ZOOM_LO)
                zhi = max(zhi, GS_ENTRY_ZOOM_MID)
        if not (zlo <= z <= zhi + 1e-9):
            bad.append(f"floor {a['floor']}：表演事件 zoom {z} 越界 [{zlo:g},{zhi:g}]")
            break

    # 值域
    for a in mv:
        f = int(a["floor"])
        r = a.get("rotation")
        in_rect = any(sec["key"].startswith("回正") and sec["s"] - 1 <= f
                      <= sec["e"] for sec in secs)
        if _is_visually_zero_rot(r):
            lim = None                     # 360 的整数倍 = 视觉归零，不再限
        elif in_rect:
            lim = 90.0
        else:
            lim = 30.0
        if lim is not None and r is not None and abs(float(r)) > lim + 1e-9:
            bad.append(f"floor {f}：rotation {r} 越界（限 ±{lim:g}）")
            break
        v = float(a.get("angleOffset") or 0.0)
        if abs(v % 45.0) > 1e-9 or abs(v) > 7200.0 + 1e-9:
            bad.append(f"floor {f}：angleOffset {v} 不合法")
            break
    for a in perf:
        if a["ease"] not in EASES:
            bad.append(f"floor {a['floor']}：ease {a['ease']!r} 不在白名单")
            break

    # ★★ 无缝衔接的三条硬指标
    print("    ★ 无缝衔接检查：")
    for sec in secs:
        if sec["nolock"]:
            # ① 这一段**不许**有 duration=0 的瞬跳
            jumps = [a for a in mv if sec["s"] - 1 <= int(a["floor"]) <= sec["e"]
                     and _is_lock(a)]
            if jumps:
                bad.append(f"段「{sec['key']}」标了 nolock 却还有 "
                           f"{len(jumps)} 条 duration=0 的瞬跳")
            print("      · 段「%s」无瞬跳 ✓" % sec["key"])
    # ② 相邻两段之间「上一段末条 == 下一段首条的目标状态」⇒ 不需要重定位
    for i in range(len(secs) - 1):
        a, b = secs[i], secs[i + 1]
        if not b["nolock"]:
            continue
        tail = [x for x in mv if x.get("eventTag") and int(x["floor"]) <= a["e"]]
        if not tail:
            continue
        last = max(tail, key=lambda x: int(x["floor"]))
        if last.get("zoom") is not None and abs(float(last["zoom"]) - BASE_ZOOM) > 1e-9:
            bad.append(f"段「{a['key']}」末条 zoom={last['zoom']} 不是基准位 ⇒ "
                       f"段「{b['key']}」接不上（会跳）")
        if last.get("rotation") not in (None, 0, 0.0):
            bad.append(f"段「{a['key']}」末条 rotation={last['rotation']} 不是 0 ⇒ "
                       f"段「{b['key']}」接不上")
        print("      · 段「%s」末条已回基准 ⇒ 段「%s」可直接接手 ✓" % (a["key"], b["key"]))
    # ③ 每一对的末条都回基准（不需要末条之后再来一次定位）
    pairs_bad = []
    for a in sorted(perf, key=lambda x: int(x["floor"])):
        if a.get("zoom") is not None and abs(float(a["zoom"]) - BASE_ZOOM) > 1e-9:
            continue
        pairs_bad.append(a)
    if not pairs_bad:
        bad.append("一条回到基准位的表演事件都没有 ⇒ 组合的『成对』不成立")
    print("      · 回基准的表演事件 %d 条" % len(pairs_bad))

    # ★★ 2026-10 用宏解析器实测出来的硬指标：**补间不许溢出它所在的段**。
    #   教学谱（`out/_camera/tut.adofai`）四档 cur 的「覆盖格数」众数都是 **1.0 格**；
    #   我们自己写死「8 拍」时，在高 cur 段（`cur = base × 4`）会变成 **32 格**，
    #   而那段只有 16 格 ⇒ 相机到段尾还在动，被下一段的定基硬切掉。
    #      覆盖格数 = duration(拍) × cur / base_bpm
    #   （段尾的归位事件允许往跑道里多溢 1~2 格，那是"缓速出场"要的。）
    over = []
    for sec in secs:
        cur = cur_at(sec["s"])
        for a in perf:
            f = int(a["floor"])
            if not (sec["s"] - 1 <= f <= sec["e"]):
                continue
            cover = float(a["duration"]) * cur / BPM
            if cover > sec["body"] + 3.0 + 1e-6:
                over.append((sec["key"], f, cover, sec["body"], cur))
    if over:
        k, f, cover, body, cur = over[0]
        bad.append(f"段「{k}」floor {f}：补间覆盖 {cover:.1f} 格 > 段长 {body} 格 + 3"
                   f"（cur={cur:g}）⇒ 段尾还在动")
    else:
        print("    ★ 时值不溢出：每段的补间覆盖格数都 ≤ 段长 + 3 格 ✓")

    # ★★ 2026-10 **一拍一振**（`docs/64` §9.2「低 cur」）：逐拍核对「偶定基 / 奇硬切」。
    for sec in shake_secs:
        n = sec["e"] - sec["s"] + 1
        get = {int(a["floor"]): _kind(a) for a in mv
               if sec["s"] <= int(a["floor"]) <= sec["e"]}
        for k in range(n):
            f = sec["s"] + k
            want = "lock" if (k % 2 == 1 or k == n - 1) else "cut"
            if get.get(f) != want:
                bad.append(f"段「{sec['key']}」第 {k} 拍（格 {f}）应为 {want}，"
                           f"实际 {get.get(f)}")
                break
        print(f"    ★ 一拍一振「{sec['key']}」{n} 拍：定基 "
              f"{sum(1 for v in get.values() if v == 'lock')} / 硬切 "
              f"{sum(1 for v in get.values() if v == 'cut')}")
    # ★★ 高 cur 段**一条硬切都不许有**（用户：「高速完全不用这个写法」）。
    for sec in high_secs:
        if sec["fn"] is m_beat_shake:
            continue
        c = [a for a in mv if sec["s"] <= int(a["floor"]) <= sec["e"]
             and _kind(a) == "cut"]
        if c:
            bad.append(f"段「{sec['key']}」是高 cur 段，却有 {len(c)} 条硬切"
                       f"（用户：高速完全不用一拍一振那个写法）")
        else:
            print(f"    ★ 高 cur「{sec['key']}」硬切 0 条 ✓")

    # ★★ 2026-10 雪花（`docs/64` §9.2b，抄 Tempest 加强版 A/B 两套）：
    #   ① 进场必须是 `Tile` 帧**硬切**；② 段内不许逐格跟随玩家；
    #   ③ 旋转总角 = 360 的整数倍且 ≥ 360；④ 按格数分流 A/B，各档的 zoom/位移要在。
    for sec in snow_secs:
        L = int(sec["snow"])
        want = "B" if L > SNOW_BIG_TILES else "A"
        if sec.get("snow_recipe") != want:
            bad.append(f"段「{sec['key']}」雪花 {L} 格应走 {want}，"
                       f"实际 {sec.get('snow_recipe')}")
        sn = [a for a in mv if sec["s"] - 1 <= int(a["floor"]) <= sec["e"]]
        if not [a for a in sn if a.get("relativeTo") in ("Tile", "Global")]:
            bad.append(f"段「{sec['key']}」雪花段没有**世界锚定**的居中事件")
        ins = [a for a in sn if int(a["floor"]) == sec["s"]]
        if not ins or _kind(ins[0]) != "cut" or ins[0].get("relativeTo") != "Tile":
            bad.append(f"段「{sec['key']}」雪花进场不是「`Tile` 帧硬切」")
        fol = [a for a in sn if a.get("relativeTo") == "Player"
               and _kind(a) == "perf" and int(a["floor"]) > sec["s"]]
        # ★ 例外：**段尾**允许**恰好一条**归位事件（缓速回玩家）——
        #   否则下一段的 `duration=0` 定基会从"雪花中心"瞬跳回玩家（卡顿）。
        back = [a for a in fol if int(a["floor"]) >= sec["e"] - max(1, L // 4)]
        if len(back) > 1:
            bad.append(f"段「{sec['key']}」雪花段的归位事件多于 1 条：{len(back)}")
        fol = [a for a in fol if a not in back]
        if fol:
            bad.append(f"段「{sec['key']}」雪花段里还有 {len(fol)} 条逐格跟随玩家的事件")
        spin = snow_spin_deg(L)
        got = [a for a in sn
               if abs(float(a.get("rotation") or 0.0) - spin) < 1e-9
               or abs(float(a.get("angleOffset") or 0.0) - spin) < 1e-9]
        if not got:
            bad.append(f"段「{sec['key']}」雪花段没找到 {spin:g}° 的整圈旋转")
        if abs(spin % 360.0) > 1e-9 or spin < 360.0:
            bad.append(f"段「{sec['key']}」雪花旋转 {spin} 不是 360 的正整数倍")
        dx, dy, _L = _snow_ctx(sec["s"])
        zs = {a.get("zoom") for a in sn if a.get("zoom") is not None}
        if want == "A":
            if SNOW_A_ZOOM_IN not in zs or SNOW_A_ZOOM not in zs:
                bad.append(f"段「{sec['key']}」雪花 A 缺 {SNOW_A_ZOOM_IN:g} / "
                           f"{SNOW_A_ZOOM:g} 的缩放（抄 Tempest `f402`）")
            ctr = [a for a in ins if a.get("position") == [dx, dy]]
            if not ctr:
                bad.append(f"段「{sec['key']}」雪花 A 进场没有钉在中心 "
                           f"[{dx:g},{dy:g}]")
        else:
            if SNOW_B_ZOOM not in zs:
                bad.append(f"段「{sec['key']}」雪花 B 缺 zoom={SNOW_B_ZOOM:g}"
                           f"（抄 Tempest `f1077`）")
            top = dy + SNOW_B_DY
            ys = [a["position"][1] for a in sn
                  if a.get("position") and a["position"][1] is not None]
            if not ys or min(abs(float(v) - top) for v in ys) > 1e-6:
                bad.append(f"段「{sec['key']}」雪花 B 没有退到下方 "
                           f"{SNOW_B_DY:g} 格（y={top:g}）")
            xs = [abs(float(a["position"][0]) - dx) for a in sn
                  if a.get("position") and a["position"][0] is not None]
            if not xs or max(xs) < max(abs(SNOW_B_DX1), abs(SNOW_B_DX2)) - 1e-6:
                bad.append(f"段「{sec['key']}」雪花 B 的长缓移幅度不够"
                           f"（应到 ±{max(abs(SNOW_B_DX1), abs(SNOW_B_DX2)):g} 格）")
        for a in sn:
            if a.get("relativeTo") not in ("Tile", "Global"):
                continue
            pos = a.get("position")
            if pos in (None, [None, None]):
                continue
            if max(abs(float(v)) for v in pos if v is not None) > 24.0:
                bad.append(f"段「{sec['key']}」居中偏移 {pos} 太远（>24 格）")
                break
        print(f"    ★ 雪花 {want}「{sec['key']}」{L} 格 · 转 {spin:g}° "
              f"· zoom {sorted(z for z in zs)}")

    # ★★ 2026-10 国士無双（`docs/67`）：**两层并行** —— 宏观 `Player` 跟人、
    #   微观 `Tile` 不跟人；两层时值都是**按拍写死**，只有节奏按格。
    for sec in gs_secs:
        cur = cur_at(sec["s"])
        step = gs_micro_step(cur)
        mbeats = GS_MICRO_BEATS if step == GS_MICRO_TILES_FAST else GS_MICRO_BEATS_SLOW
        sn = [a for a in mv if sec["s"] - 1 <= int(a["floor"]) <= sec["e"]]
        macro = [a for a in sn if a.get("relativeTo") == GS_MACRO_REL
                 and a.get("position") == GS_MACRO_POS]
        micro = [a for a in sn if a.get("relativeTo") == GS_MICRO_REL
                 and a.get("eventTag") == TAG + "gs_micro"]
        # ① 宏观层：跟人 + 大偏移 + **按拍写死**（长锚 / 弹回两个拍值）
        if not macro:
            bad.append(f"段「{sec['key']}」没有宏观层（`{GS_MACRO_REL}` + "
                       f"{GS_MACRO_POS}）")
        else:
            zz = {float(a["zoom"]) for a in macro}
            if zz != {GS_MACRO_ZOOM}:
                bad.append(f"段「{sec['key']}」宏观层 zoom 应为 {GS_MACRO_ZOOM:g}：{sorted(zz)}")
            dd = {float(a["duration"]) for a in macro}
            if dd != set(GS_MACRO_BEATS_SET):
                bad.append(f"段「{sec['key']}」宏观层时值应**按拍写死**为 "
                           f"{sorted(GS_MACRO_BEATS_SET)} 拍：{sorted(dd)}")
            longs = [a for a in sn if a.get("eventTag") == TAG + "gs_long"]
            snaps = [a for a in sn if a.get("eventTag") == TAG + "gs_snap"]
            if not longs:
                bad.append(f"段「{sec['key']}」没有长锚（`gs_long`）")
            elif abs(int(longs[0]["floor"]) - sec["s"]) > 1e-9:
                bad.append(f"段「{sec['key']}」长锚第一条不在段首（floor {longs[0]['floor']}）")
            if not snaps:
                bad.append(f"段「{sec['key']}」没有串尾「弹回」（`gs_snap`）—— "
                           f"光有连续微观不是国士那一套")
            # 长锚必须**走完才重发**（按格折算）
            cover = GS_LONG_BEATS * cur / BPM
            lfs = sorted(int(a["floor"]) for a in longs)
            for a, b in zip(lfs, lfs[1:]):
                if b - a < cover - 1.5:
                    bad.append(f"段「{sec['key']}」长锚重发太密：{a}→{b} 格差 "
                               f"{b - a} < 覆盖 {cover:.1f}")
                    break
        # ② 微观层：不跟人 + **串内**每 step 格一条 + `OutElastic`
        if not micro:
            bad.append(f"段「{sec['key']}」没有微观层（`{GS_MICRO_REL}` 小步跳）")
        else:
            zz = {float(a["zoom"]) for a in micro}
            if zz != {GS_MICRO_ZOOM}:
                bad.append(f"段「{sec['key']}」微观层 zoom 应为 {GS_MICRO_ZOOM:g}：{sorted(zz)}")
            dd = {float(a["duration"]) for a in micro}
            if dd != {mbeats}:
                bad.append(f"段「{sec['key']}」微观层时值应为 {mbeats:g} 拍：{sorted(dd)}")
            ee = {a["ease"] for a in micro}
            if ee != {"OutElastic"}:
                bad.append(f"段「{sec['key']}」微观层 ease 应照抄国士無双的 `OutElastic`：{sorted(ee)}")
            fs = sorted(int(a["floor"]) for a in micro)
            gaps = sorted({b - a for a, b in zip(fs, fs[1:])})
            # ★ 串**内**是每 `step` 格；串**间**是「串尾弹回（占 1 个 step）+ 空
            #   `GS_SNAP_GAP_TILES` 格」；长锚之后还要多一个 `GS_LULL_TILES` 静默期。
            allowed = {step,
                       step + GS_SNAP_GAP_TILES,
                       step + GS_SNAP_GAP_TILES + GS_LULL_TILES}
            if gaps and not set(gaps) <= allowed:
                bad.append(f"段「{sec['key']}」微观层出现意外间隔：{gaps}"
                           f"（只允许 {sorted(allowed)}）")
            # 串长必须落在国士的 3~6 条区间里
            runs: list[int] = []
            cur_run = 1
            for a, b in zip(fs, fs[1:]):
                if b - a == step:
                    cur_run += 1
                else:
                    runs.append(cur_run)
                    cur_run = 1
            runs.append(cur_run)
            if runs and not all(1 <= r <= max(GS_BURST_PATTERN) for r in runs):
                bad.append(f"段「{sec['key']}」微观串长异常：{sorted(set(runs))}"
                           f"（国士实测 3~6）")
            # ★ 长锚后必须有静默期（一条微观都不发）
            longs = [int(a["floor"]) for a in sn if a.get("eventTag") == TAG + "gs_long"]
            for lf in longs:
                win = [f for f in fs if lf + 4 <= f <= lf + GS_LULL_TILES - 4]
                if win:
                    bad.append(f"段「{sec['key']}」长锚 floor {lf} 后的静默期里还有 "
                               f"{len(win)} 条微观（国士是 44 格一条不发）")
                    break
        # ③ 分工：段内**不许**出现"跟人的微观事件"（那就是两条跟人层打架）
        extra = [a for a in sn if a.get("relativeTo") == GS_MACRO_REL
                 and a.get("eventTag") == TAG + "gs_micro"]
        if extra:
            bad.append(f"段「{sec['key']}」微观层挂到了 `{GS_MACRO_REL}` 上"
                       f"（{len(extra)} 条）—— 两层必须一个跟人、一个不跟人")
        # ④ 两层必须**真的并行** —— 判据是**时间上交错**，不是同格重叠。
        #   ★ 国士無双 里宏观（1575 弹回）和微观（1569/1571/1573）**从来不在同一格**
        #     —— 它们是「微观一串 → 宏观一条」交替着走的。所以这里查交错。
        if macro and micro:
            mfs = sorted(int(a["floor"]) for a in macro)
            mifs = sorted(int(a["floor"]) for a in micro)
            mac_in = [f for f in mfs if mifs[0] < f < mifs[-1]]
            mic_in = [f for f in mifs if mfs[0] < f < mfs[-1]]
            if not mac_in or not mic_in:
                bad.append(f"段「{sec['key']}」两层没有**交错**：宏观 {len(mfs)} 条 / "
                           f"微观 {len(mifs)} 条，看起来是先做完一层再做另一层")
        else:
            mac_in = mic_in = []
        # ⑤ 出场必须回基准（本工具加的收尾；国士無双那段在整首谱中间，没有这一条）
        back = [a for a in sn if a.get("eventTag") == TAG + "gs_back"]
        if not back:
            bad.append(f"段「{sec['key']}」没有出场归位事件（下一段定基会瞬跳）")
        elif float(back[0]["zoom"]) != float(BASE_ZOOM) or back[0].get("position") != [0.0, 0.0]:
            bad.append(f"段「{sec['key']}」出场归位没回基准：zoom="
                       f"{back[0]['zoom']} pos={back[0].get('position')}")
        n_long = len([a for a in macro if a.get("eventTag") == TAG + "gs_long"])
        n_snap = len([a for a in macro if a.get("eventTag") == TAG + "gs_snap"])
        print(f"    ★ 国士無双两层「{sec['key']}」cur={cur:g} · 宏观 长锚 {n_long} / "
              f"弹回 {n_snap}（{GS_LONG_BEATS:g}/{GS_SNAP_BEATS:g} 拍）· 微观 "
              f"{len(micro)} 条（串内每 {step} 格 / {mbeats:.5f} 拍 · 串长 "
              f"{list(GS_BURST_PATTERN)}）· 两层交错 {len(mac_in)}/{len(mic_in)} · "
              f"长锚静默 {GS_LULL_TILES} 格 · 出场 "
              f"{'有' if back else '无'} · 进场招牌 "
              f"{'开' if _gs_entry(sec['s']) else '关'}")

    for r in rp:
        t = r["tag"]
        if t in RESERVED_TAGS or not str(t).startswith(TAG):
            bad.append(f"RepeatEvents.tag {t!r} 撞词表/没前缀")
            break
        if r["repeatType"] not in ("Beat", "Floor"):
            bad.append(f"repeatType {r['repeatType']!r} 不合法")
            break
        same = [a for a in mv if a.get("eventTag") == t]
        if not same or min(int(x["floor"]) for x in same) != int(r["floor"]):
            bad.append(f"RepeatEvents.tag {t!r} 复制不到")
            break
    return bad


def verify_file(path: str) -> list[str]:
    bad: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        j = json.load(f)
    acts = j.get("actions") or []
    fl = [int(a.get("floor") or 0) for a in acts]
    if fl != sorted(fl):
        bad.append("落盘后 actions 没按 floor 有序")
    mv = [a for a in acts if a.get("eventType") == "MoveCamera"]
    if not mv:
        bad.append("落盘后一条 MoveCamera 都没有")
    for a in mv:
        if not set(a) <= set(MV_CAM_KEYS):
            bad.append("落盘后有字段超白名单")
            break
    if len(j.get("decorations") or []) != 2:
        bad.append("decorations 应为 2 条")
    if not any(a.get("eventType") == "SetText" for a in acts):
        bad.append("没有 SetText")
    return bad


# ============================================================ 音频
def write_click_track(path: str, ch, accents: set[int]):
    lead_ms = solve_mod.total_lead_ms(ch, CD)
    times = solve_mod.times_from_chart(ch)
    n = int((lead_ms + (times[-1] if times else 0.0) + 1200.0) / 1000.0 * SR)
    buf = [0.0] * max(1, n)

    def click(at_ms: float, freq: float, amp: float) -> None:
        i0 = int(at_ms / 1000.0 * SR)
        for k in range(int(0.035 * SR)):
            j = i0 + k
            if j < 0 or j >= n:
                continue
            env = math.exp(-k / (0.006 * SR))
            if k < 0.002 * SR:
                env *= k / (0.002 * SR)
            buf[j] += amp * env * math.sin(2 * math.pi * freq * k / SR)

    for i in range(1, len(times)):
        click(lead_ms + times[i], 1320.0 if i in accents else 660.0,
              0.30 if i in accents else 0.20)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(v * 32767)))) for v in buf))
    return lead_ms, n


# ============================================================ 输出
def write_checklist(path: str, secs: list[dict], ev) -> None:
    byfloor = {}
    for a in ev:
        if a["eventType"] == "MoveCamera":
            byfloor.setdefault(int(a["floor"]), []).append(a)
    L = ["运镜验收谱 v2 · 逐段清单", "=" * 70,
         "每段：屏幕右上角有字幕（标题 + 看什么），段首有节拍重音 + 游戏内标签。", "",
         "★ v2 相对 v1 砍掉了 段 9~15（纯旋转摆头 / 弹性 / Bounce / 追球 / 位移 / 短拉链）",
         "  —— 用户实测那几段「把镜头弄没了 看不见」，而段 18（复位诊断）没错",
         "   ⇒ 是那几条动作自己的问题，v2 直接从谱面里去掉。",
         "★ 根因（用户 2026-10 定位）：**`zoom` 绝不许 `null` / 0** —— 已写进自检与契约测试。", "",
         "★★ 本迭代（第五轮回执）改了三件事：",
         "   1. 「**慢速直接一拍一振好了，高速完全不用这个写法**」",
         "      ⇒ 低 cur 段 = 每拍一条 `duration=0` 硬切（偶拍回基准、奇拍抖出去）；",
         "        高 cur 段**一条硬切都没有**（自检会拦）。",
         "   2. 「**雪花的镜头写法……你去抄一下 Tempest 加强版**」",
         "      ⇒ 新增「雪花 A / 雪花 B」两段，逐条抄 Tempest 的 `f402` / `f1077`。",
         "   3. 「**物量大的用 B，小的用 A**」",
         f"      ⇒ 判据 = 雪花格数：`> {SNOW_BIG_TILES:g}` 走 B（远景 + 长缓移 + 多圈），"
         f"`<= {SNOW_BIG_TILES:g}` 走 A（近景居中 + 缓速整圈）。", "",
         "★ **回正两段**只有**一个变量**（右转档 ±90）：哪一档真能把新方向转回水平？", ""]
    for i, s in enumerate(secs, start=1):
        L.append(f"[ ] 段{i:>2} 「{s['key']}」 格 {s['s']}~{s['e']}"
                 f"（正文 {s['body']} 格）")
        L.append("        " + s["title"])
        for ln in s["watch"].split("\n"):
            L.append("        " + ln)
        if s["nolock"]:
            L.append(f"        ★ **无跑道、无定基**：接缝就在格 {s['s'] - 1} → {s['s']}，"
                     f"两轮应当完全连着")
        if s["corners"]:
            L.append("        ★ 直角弯在格 " + "、".join(
                f"{s['s'] + o}（travel {int(t)}）" for o, t in s["corners"]))
        L.append("")
    L += ["—" * 70,
          "验收要点：",
          "  1. **低 cur**（段 3/4，cbpm 120 < 400）：**一拍一振** —— 每格一次硬切，",
          "     偶拍回基准、奇拍抖到 [1,0]/zoom170/rotation 5·10·15·20；",
          "     该看到「一格一抖」的频闪感；**段尾必须收在基准**（自检已核）；",
          "  2. **高 cur**（段 5，`SetSpeed ×4` ⇒ cbpm 480 ≥ 400）："
          "**位置 + 呼吸 + 缓慢移动**（并行、8+8 拍），"
          "★ **一条硬切都没有** —— 「高速完全不用一拍一振那个写法」；",
          "  3. **回正**（段 6/7）：拐角那格镜头不动，出拐角后把新方向转回水平；",
          f"  4. **雪花 A**（段 8，{32} 格 ≤ {SNOW_BIG_TILES:g}）：镜头钉在雪花正中央，"
          "进场硬切怼近 zoom 100 → 拉远 250 → 整段缓速转一圈；",
          f"  5. **雪花 B**（段 9，64 格 > {SNOW_BIG_TILES:g}）：同一朵花换远景写法 ——"
          " zoom 600、镜头退到下方 14 格、长缓移（−8→+12 格）同时转 16 圈。",
          "     ★ 请对比 A / B：**大雪花到底该用哪一套？**",
          "",
          "历轮回执（用户 2026-10）：",
          "  · 一轮：段 9~15「把镜头弄没了」⇒ 整段删除；段 18 没错 ⇒ 保留成复位诊断；",
          "  · 二轮：幅度太小 ⇒ 200↔120；匀速呆板 ⇒ 换 `OutQuad`；",
          "  · 三轮：「2 不要了，3 留下，并且与 4 绑定使用」⇒ 三合一；",
          "  · 四轮：「**检测 cur**：高 cur 用位置+呼吸+缓慢移动，低 cur 用跳跃」；",
          "    「**雪花镜头永远位于正中央**，允许缓速 ±30° 旋转和位移」；",
          "  · 五轮（本轮）：「**雪花的镜头写法……你去抄一下 Tempest 加强版**」；",
          "    「**慢速直接一拍一振好了，高速完全不用这个写法**」；",
          "    「**物量大的用 B，小的用 A**」（⇒ A/B 两段，见上）；",
          "  · 根因：`zoom` 绝不许 `null` / 0（用户定位）—— 已写进自检与契约测试。",
          "",
          "★ 雪花段的「中心」是用**真实路径坐标**算的（`Path.points` 的包围盒中心）："
          "这种花瓣都从中心出发的形状，包围盒中心**正好就是入口那一格**，所以 A 段的"
          "中心偏移是 (0,0)、B 段在此基础上再退到下方 14 格。",
          "★ 本轮的 A/B 数值是**从 Tempest 的拍数换算过来的**（Tempest 段长 283/285 格，"
          "我们的雪花只有 32/64 格）：",
          "  · A 的旋速 = Tempest 的 720°/64 拍 = 11.25°/拍 ⇒ 我们写「每 32 拍一圈」；",
          "  · B 的旋速 = Tempest 的 5760°/54 拍 ≈ 106.7°/拍 ⇒ 取整成「每 4 拍一圈」。",
          "  这两条换算**是本喵定的**，主人若觉得转速不对请直接说。",
          "已知未覆盖：Flash / ShakeScreen / 高滤梦境2 —— 教学谱里有，本轮不做。"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def make_one(out_dir: str) -> int:
    ch, ev, secs, set_speeds = build()
    wav = os.path.join(out_dir, "main.wav")
    write_click_track(wav, ch, {s["s"] for s in secs})

    W.write_dir(ch, out_dir, name="main", audio_src=wav,
                song="运镜验收谱 v2（一拍一振 / 缓慢 / 回正 / 雪花 A·B / 国士無双·两层）",
                artist="(合成节拍点击)", author="ADOFAI Chart Generator",
                offset_ms=0.0, difficulty=1, countdown_ticks=CD)

    p = os.path.join(out_dir, "main.adofai")
    with open(p, "r", encoding="utf-8") as f:
        j = json.load(f)
    j["decorations"] = [
        add_text("1", [0, 6], [150, 150], text="", opacity=0, depth=-1),
        add_text("2", [0, 4.2], [95, 95], text="", opacity=0, depth=-1),
    ]
    for i, s in enumerate(secs, start=1):
        j["actions"].append({"floor": s["s"], "eventType": "EditorComment",
                             "comment": f"★ 段{i}/{len(secs)} · {s['title']}\n"
                                        f"{s['watch']}\n"})
    j["actions"].extend(ev)
    j["actions"].sort(key=lambda a: (int(a.get("floor") or 0),
                                     _order(a.get("eventType", "")),
                                     a.get("angleOffset") or 0))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent="\t")

    ms = 60000.0 / BPM
    print("=" * 96)
    print("运镜验收谱 v2（一拍一振 / 缓慢 / 回正 / 雪花 A·B / 国士無双·两层）")
    print("=" * 96)
    print(f"输出目录 : {out_dir}")
    print(f"谱面     : {len(ch.floors)} 格 · bpm {BPM:g} · 每格 {ms:.0f} ms（1 格 = 1 拍）· "
          f"全长 {len(ch.floors) * ms / 1000:.0f} s")
    print()
    print(f"{'段':<4}{'键':<14}{'正文格':<11}看什么")
    for i, s in enumerate(secs, start=1):
        w = s["watch"].split("\n")[0].replace("看什么：", "").replace("看什么: ", "")
        print(f"{i:<4}{s['key']:<14}{str(s['s']) + '~' + str(s['e']):<11}{w[:70]}")
    print()
    mvv = [a for a in ev if a["eventType"] == "MoveCamera"]
    n_lock = len([a for a in mvv if _kind(a) == "lock"])
    n_cut = len([a for a in mvv if _kind(a) == "cut"])
    n_perf = len([a for a in mvv if _kind(a) == "perf"])
    print("事件总量 : %d = MoveCamera %d（定基 %d / 硬切 %d / 表演 %d） + RepeatEvents %d"
          " + SetText %d + MoveDecorations %d + EditorComment %d"
          % (len(ev), len(mvv), n_lock, n_cut, n_perf,
             len([a for a in ev if a["eventType"] == "RepeatEvents"]),
             len([a for a in ev if a["eventType"] == "SetText"]),
             len([a for a in ev if a["eventType"] == "MoveDecorations"]),
             len(secs)))

    ok = True
    bad = verify(ev, ch, secs)
    if bad:
        ok = False
        print("✗ 契约自检失败：")
        for x in bad:
            print("   - " + x)
    else:
        print("✓ 契约自检通过：字段白名单 / 显式 relativeTo / 定基完整复位 / 硬切四样给齐 / "
              "单维度 / 值域 / tag 命名空间 / 一拍一振逐拍 / 高 cur 无硬切 / 雪花 A·B")
    bad = verify_file(p)
    if bad:
        ok = False
        print("✗ 回读落盘失败：")
        for x in bad:
            print("   - " + x)
    else:
        print("✓ 回读落盘通过：actions 按 floor 有序 / 字段集一致 / 装饰 + SetText 都在")
    try:
        from core import verify as verify_mod
        ons_ms = solve_mod.times_from_chart(ch)[1:]      # ★ 去掉第 0 层引导层
        vr = verify_mod.verify_file(p, ons_ms, tol_ms=1.0, lead_floors=1)
        if not vr.ok:
            ok = False
            print(f"✗ 第三方反解失败：{vr.summary()}")
        else:
            print(f"✓ 第三方反解通过：{vr.summary()}")
    except Exception as exc:                                  # noqa: BLE001
        print(f"（第三方反解跳过：{type(exc).__name__}: {exc}）")
    try:
        from core import rules as rules_mod

        def _lv(v):
            return v.get("level") if isinstance(v, dict) else getattr(v, "level", "")

        def _msg(v):
            return v.get("msg") if isinstance(v, dict) else getattr(v, "msg", v)

        viol = [v for v in rules_mod.check_chart(ch) if _lv(v) != "info"]
        if viol:
            ok = False
            print(f"⚠ 规则检查 {len(viol)} 条违规：")
            for v in viol[:6]:
                print("   - " + str(_msg(v)))
        else:
            print("✓ 规则检查通过")
    except Exception as exc:                                  # noqa: BLE001
        print(f"（规则检查跳过：{exc}）")

    write_checklist(os.path.join(out_dir, "验收清单.txt"), secs, ev)
    print(f"\n验收清单 → {os.path.join(out_dir, '验收清单.txt')}")
    return 0 if ok else 1


def main() -> int:
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else os.path.join(_ROOT, "out", "运镜验收谱v2"))
    rc = make_one(out_dir)
    print("\n进游戏：整个输出目录拷进")
    print(r"  C:\Users\<你>\Documents\A Dance of Fire and Ice\Worlds\ ")
    print("\n★ 本迭代只看四件事：① 低 cur 的**一拍一振**频闪对不对（段 3/4）；"
          "② **雪花 A / B 哪套更适合大雪花**（段 9/10）；")
    print("  ③ 高 cur 段里**不该出现任何硬切**（段 5）；")
    print("  ④ ★ **国士無双·两层**（段 6）：对着**同速的段 5** 比 ——")
    print("     一层跟人（`Player`，大偏移）、一层不跟人（`Tile`，小步跳），"
          "两层叠在一起会不会太晕。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
