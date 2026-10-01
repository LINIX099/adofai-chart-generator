# -*- coding: utf-8 -*-
"""把「**国士無双 · 两层运镜**」写到一张**真实谱面**上（离线工具，产出给人验收）。

    python tools\\apply_camera_gs.py <谱面.adofai> [--out 目录] [--report] [--entry]

这是一张**成品谱**的运镜补写器，不是 `core/` 的接线：

* **只加 `MoveCamera`**，其余 action / `angleData` / `settings` 一个字节都不改；
* 产物放到 `out/` 下的独立目录，**不动**主人的铺面库；
* 谱面目录里用到的音频会按 `settings.songFilename` 一起拷过去。

## 依据

`docs/67` 交接单 + `docs/64` §9.2c + `docs/66` §9.5 的 **E 形态**，
素材是 `Laur_-_国士無双/Done.adofai`。

★★ **2026-10 复测修正**：交接单里写的「宏观层每 44~78 格重发一次」是**错的**。
把 `1521..1778` 逐条摊开重数之后，真实结构是：

```
1569,1571,1573  微观 Tile（每 2 格一条）      ← 一串 3 条
1575            宏观 Player dur=4  OutCirc    ← 「弹回」，串尾一定有这一条
1579,1581,1583  微观（下一串）
1585            宏观 Player dur=32 OutCirc    ← 长锚（跨 256 格）
        …1585..1629 共 44 格**一条微观都没有**（长锚自己在走）
1629,1631,1633  微观
1635            宏观 dur=4 OutCubic
```

⇒ 两条修正：

1. **微观是「成串」发的**：每 2 格一条，一串 **3~6** 条，串尾一条「弹回」宏观；
2. **宏观重发间隔是 10~16 格**（不是 44~78），另外偶尔来一发 32/64 拍的**长锚**，
   长锚后面有 **~44 格**完全不发微观的静默期。

## 两条层（时值全部**按拍写死**，不是按格除出来的）

| 层 | `relativeTo` | `position` | `zoom` | 时值 | 节奏 | `ease` |
|---|---|---|---|---|---|---|
| 宏观 · 长锚 | `Player` | 基准 + `[-4,3]` | `300` | `20` 乐句拍 | 段首一发 | `OutExpo` |
| 宏观 · 弹回 | `Player` | 基准 + `[-4,3]` | `300` | `2` 乐句拍 | 每串尾一发 | `OutCirc` |
| 微观 | `Tile` | 6 个小值轮换 | `210` | `1` 乐句拍 | 每 2 格一条 | `OutElastic` |

★ **「乐句拍」的换算**（用户 2026-10：「base bpm 是谱面的设计，这个曲子实际上 bpm
可以看特效版本的」）：这张谱非特效版 `settings.bpm = 900`，特效版（作者 pixelo3o）
`settings.bpm = 225`，而两版同一首歌 ⇒ **1 乐句拍 = 4 个谱面拍**。
国士那一套的时值换成**秒**再落回来：

| | 国士（base 340） | 秒 | 本谱（base 900） |
|---|---|---|---|
| 微观 | `1.66667` 拍 | 294 ms | **`4` 拍** |
| 弹回 | `4` 拍 | 706 ms | **`8` 拍** |
| 长锚 | `32` 拍 | 5.65 s | **`80` 拍** |
| 进场 | `64` 拍 | 11.29 s | **`160` 拍** |

## 分派（`docs/64` §9.2a）

* `cur ≥ CUR_SPLIT`（默认 400 cbpm）⇒ **两层**；
* `cur < CUR_SPLIT` ⇒ **一拍一振**（每格一条 `duration=0`，偶定基 / 奇抖出去）。
  ★ 本工具的「一拍一振」网格落在**格**上，不是**拍**上 —— 因为这张谱
  `cur = 225 ≠ base 900`（1 格 = 4 拍），落在拍上就没法一格一条了。
  **这一条是偏离 `tools/make_camera_demo.py::m_beat_shake` 的硬拦的，写在报告里。**

## 不许静默

`--report` 会把每一段用了哪一档、多少条事件、覆盖多少格全打出来；
`verify_output()` 会把产物**重新用宏解析器读一遍**再核对。
"""
import argparse
import json
import os
import re
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

import analyze_camera_cur as ACC                              # noqa: E402

# ============================================================ 配方常量
#: 分派阈值：`cur ≥ 这个值` 走两层，否则走一拍一振（`docs/64` §9.2）。
CUR_SPLIT = 400.0

#: 乐句拍 → 谱面拍的倍数。本谱非特效版 base 900 / 特效版 base 225。
MUSIC_BEATS = 4.0

#: ★★ **ease 档位** —— 两套配方只差 ease（`docs/69`）：
#:
#: * `gs`   —— **照抄国士無双**（v3 用的）；`OutExpo` / `OutCirc` / `OutElastic`
#:   起手极快、末尾过冲，观感是「**甩尾**」；
#: * `soft` —— **柔和档**（迭代 2 用的）；换成 `OutCubic` / `OutSine` / `OutSine`，
#:   没有过冲、起手也不猛。用户 2026-10 迭代 2 第 1 条：
#:   「**少用甩尾运镜，尽可能用柔和的运镜**」。
PROFILES = {
    "gs": {"long": "OutExpo", "snap": "OutCirc", "micro": "OutElastic"},
    "soft": {"long": "OutCubic", "snap": "OutSine", "micro": "OutSine"},
}

#: 微观层时值 = **1 乐句拍**（国士 `1.66667` 拍 @340 = 294 ms）。
MICRO_BEATS = 1.0 * MUSIC_BEATS
#: 「弹回」宏观时值 = **2 乐句拍**（国士 `4` 拍 @340 = 706 ms）。
SNAP_BEATS = 2.0 * MUSIC_BEATS
#: 「长锚」宏观时值 = **20 乐句拍**（国士 `32` 拍 @340 = 5.65 s）。
LONG_BEATS = 20.0 * MUSIC_BEATS
#: 进场招牌时值 = **40 乐句拍**（国士 `64` 拍 @340 = 11.29 s）。
ENTRY_BEATS = 40.0 * MUSIC_BEATS

#: 微观层节奏：每 2 格一条（照抄国士）。
MICRO_TILES = 2
#: 微观「串长」的循环表 —— 国士实测是 **3~6** 条一串。
BURST_PATTERN = (3, 4, 6, 5)
#: 「弹回」之后的空隙（格）—— 国士是「串尾弹回，4 格后下一串」。
SNAP_GAP_TILES = 4
#: 长锚之后的**静默期**（格）—— 国士是 44 格一条微观都不发。
LULL_TILES = 32
#: 短于这个格数的段不发长锚（免得每 2 格一段都来一发）。
LONG_MIN_TILES = 8

#: 宏观层的缩放（照抄国士 `zoom=300`）。
MACRO_ZOOM = 300.0
#: 宏观层相对**本谱基准位**的偏移（照抄国士 `Player [-4,3]`）。
MACRO_DELTA = (-4.0, 3.0)
#: 微观层的缩放（照抄国士 `zoom=210`）。
MICRO_ZOOM = 210.0
#: 微观层的 6 个位置（照抄国士 `Tile` 帧的小步跳）。
MICRO_POS = ((-2.5, 2.0), (-1.5, 1.0), (-1.5, 2.0),
             (-2.0, 2.0), (-2.0, 1.0), (-2.5, 1.0))

#: 一拍一振：奇格抖出去的姿态（抄 `docs/64` §9.2b 的 Tempest 抖动段口径）。
JIT_TILES = 1.0
JIT_ZOOM = 170.0
JIT_ROT = 5.0
JIT_ROT_STEPS = 4

#: 进场招牌（`--entry`）—— 用户 2026-10：「开局无所谓喵 可以抄为可选项目」。
ENTRY = (
    # (跨格, ease, rel, pos, zoom, rotation, angleOffset)
    (4, "OutElastic", "Tile", (0.0, 0.0), 120.0, 0.0, 0.0),
    (4, "OutCubic", "Tile", (0.0, 0.0), 320.0, 0.0, 0.0),
    (4, "InBack", "Tile", (2.0, 0.0), 1.0, 0.0, 720.0),
)

MV_KEYS = ("floor", "eventType", "duration", "relativeTo", "position",
           "rotation", "zoom", "angleOffset", "ease", "eventTag")

#: action 在同 `floor` 上的先后（`SetSpeed` 必须先于 `MoveCamera` 生效）。
ORDER = {"SetSpeed": 0, "Twirl": 0, "Pause": 0, "MoveCamera": 1}


# ============================================================ 读
def load_json(path: str) -> dict:
    """容错读 —— 语料里不少谱面带**尾随逗号**（国士無双 就是）。"""
    src = open(path, encoding="utf-8-sig").read()
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", src))


def base_pose(settings: dict) -> dict:
    """谱面的**基准位** —— `MoveCamera` 复位时必须回到它，不能抄 demo 的 200/`[0,0]`。

    ★ 这一步很容易错：`settings` 里的 `relativeTo/position/rotation/zoom` 就是
    这张谱「什么都不做时」的镜头。复位写错值 = 每段边界一次瞬跳。
    """
    return {
        "relativeTo": str(settings.get("relativeTo") or "Player"),
        "position": [float(v) for v in (settings.get("position") or [0, 0])],
        "rotation": float(settings.get("rotation") or 0.0),
        "zoom": float(settings.get("zoom") or 100.0),
    }


# ============================================================ 事件构造
def cam(floor: int, *, dur: float, ease: str, rel: str, position, zoom: float,
        rotation: float = 0.0, ang: float = 0.0, tag: str = "") -> dict:
    """一条 `MoveCamera` —— **四样永远给齐**，`zoom` 永远不是 `null` 也不是 0。

    （`docs/64` §8.6.5：v1 把纯旋转事件的 `zoom` 写成 `null`，游戏读成 0，画面直接没了。）
    """
    z = float(zoom)
    if not (z > 0.0):
        raise SystemExit("zoom 必须 > 0（用户实测：0 ⇒ 黑屏）：floor %d z=%r" % (floor, zoom))
    return {
        "floor": int(floor), "eventType": "MoveCamera", "duration": float(dur),
        "relativeTo": str(rel), "position": [float(v) for v in position],
        "rotation": float(rotation), "zoom": z, "angleOffset": float(ang),
        "ease": str(ease), "eventTag": str(tag),
    }


def lock(floor: int, bp: dict) -> dict:
    """**定基**：`duration=0` + 完整复位到**本谱的**基准位 + 无 tag。"""
    return cam(floor, dur=0.0, ease="Linear", rel=bp["relativeTo"],
               position=bp["position"], zoom=bp["zoom"], rotation=bp["rotation"],
               tag="")


# ============================================================ 分段
def cur_segments(curs: list[float]) -> list[tuple[int, int, float]]:
    """把逐格 `cur` 压成 `(起始格, 结束格, cur)` 的连续段。"""
    out: list[tuple[int, int, float]] = []
    s = 0
    for i in range(1, len(curs) + 1):
        if i == len(curs) or abs(curs[i] - curs[s]) > 1e-9:
            out.append((s, i - 1, float(curs[s])))
            s = i
    return out


def dispatch_runs(curs: list[float]) -> list[tuple[int, int, int]]:
    """把逐格分派结果压成 `(起始格, 结束格, 0=一拍一振 / 1=两层)` 的**区域**。

    ★★ 为什么不能按 `cur_segments()` 走：这张谱里 900 / 450 **每隔两三格就来回跳**
      （见 `验收清单.txt` 的逐段表）。按 cur 段走的话，一串微观会被段边界切碎，
      格子网格还会漂（实测出现过 1 格间隔）。国士無双的「串」本来就是跨速度段的,
      所以这里只按**分派类别**（高 cur / 低 cur）分区域，段内的小抖动不打断串。
    """
    cls = [1 if float(c) >= CUR_SPLIT else 0 for c in curs]
    out: list[tuple[int, int, int]] = []
    s = 0
    for i in range(1, len(curs) + 1):
        if i == len(curs) or cls[i] != cls[s]:
            out.append((s, i - 1, cls[s]))
            s = i
    return out


# ============================================================ 编排
def plan(curs: list[float], bp: dict, base_bpm: float,
         entry: bool = False, profile: str = "gs") -> tuple[list[dict], dict]:
    """按 `docs/64` §9.2a 分派，产出全部 `MoveCamera` 事件 + 一份统计。

    按**分派区域**走（`dispatch_runs()`：连续同档的格子算一个区域），区域内按配方铺事件：

    * 低 cur 区域 ⇒ **一拍一振**（每格一条 `duration=0`，偶定基 / 奇抖出去）；
    * 高 cur 区域 ⇒ **两层**：区域首（够长的话）一发**长锚**，然后
      「微观串 + 串尾弹回」循环；长锚之后 `LULL_TILES` 格**一条微观都不发**
      （照抄国士的静默期）。

    ★★ **为什么不按 `cur` 段走**：这张谱里 900 / 450 每隔两三格来回跳，
      按 cur 段走会把一串微观切碎、格子网格还会漂（实测出现 1 格间隔）。
      国士的「串」本来就跨速度段。

    ★★ **长锚不重发**：国士里 32/64 拍的长锚**自己就跨 256~512 格**，
      不会每 10 格再来一发。所以这里按**覆盖格数**节流 ——
      上一条长锚的 `LONG_BEATS` 拍还没走完（`LONG_BEATS × cur / base_bpm` 格）
      就不再发新的。否则段一多，静默期首尾相接，微观层就被挤没了。

    ★ 静默期会**跨区域**（长锚是 5 秒级的漂移，不会因为速度变了一格就断）。
      落在静默期里的格子**一条事件都不发** —— `stats["segments"]` 里如实记着，
      报告会打出来，**不静默**。
    """
    n = len(curs)
    last = n - 1
    runs = dispatch_runs(curs)
    segs = cur_segments(curs)
    macro_pos = [bp["position"][0] + MACRO_DELTA[0],
                 bp["position"][1] + MACRO_DELTA[1]]
    ez = PROFILES[str(profile)]
    stats = {}

    ev: list[dict] = []
    # ★ 开局一条定基：把基准位**显式**钉住（谱面 settings 本来就是这个值，写出来
    #   是为了「复位回到本谱的基准位」这件事在产物里可核对）。
    ev.append(lock(0, bp))

    if entry:
        f = 0
        for span, ease, rel, pos, zoom, rot, ang in ENTRY:
            if f > last:
                break
            ev.append(cam(f, dur=ENTRY_BEATS, ease=ease, rel=rel, position=pos,
                          zoom=zoom, rotation=rot, ang=ang, tag="gs_entry"))
            f += span

    stats = {"macro": 0, "snap": 0, "micro": 0, "shake_lock": 0, "shake_cut": 0,
             "segments": [], "long_skipped": 0, "runs": len(runs)}
    micro_blocked_until = -1
    long_until = -1
    bi = 0
    #: 每一格的档位（事后按 `cur_segments()` 汇总，供报告/清单）
    floor_style: dict[int, str] = {}

    def _mark(f: int, style: str) -> None:
        floor_style[int(f)] = style

    for (rs, re_, rcls) in runs:
        if rcls == 0:
            # ---------------- 低 cur 区域：一拍一振
            for kk, f in enumerate(range(rs, re_ + 1)):
                # ★ 网格落在**格**上，不是拍上 —— 本谱 `cur = 225 ≠ base 900`
                #   （1 格 = 4 拍），落在拍上就没法一格一条了。**报告里写明。**
                if kk % 2 == 1:
                    ev.append(cam(f, dur=0.0, ease="Linear", rel="Player",
                                  position=[bp["position"][0] + JIT_TILES,
                                            bp["position"][1]],
                                  zoom=JIT_ZOOM,
                                  rotation=JIT_ROT * ((kk // 2) % JIT_ROT_STEPS + 1),
                                  tag="gs_shake"))
                    stats["shake_cut"] += 1
                else:
                    ev.append(lock(f, bp))
                    stats["shake_lock"] += 1
                _mark(f, "一拍一振")
            continue

        # ---------------- 高 cur 区域：两层
        f = rs
        while f <= re_:
            if f < micro_blocked_until:
                _mark(f, "两层·静默")
                f += 1
                continue
            # ---- 长锚：上一条的 `LONG_BEATS` 拍走完（按格折算）才发下一条。
            #      国士里 32/64 拍的长锚自己就跨 256~512 格，不会每 10 格来一发。
            if f >= long_until:
                ev.append(cam(f, dur=LONG_BEATS, ease=ez["long"], rel="Player",
                              position=macro_pos, zoom=MACRO_ZOOM,
                              tag="gs_macro_long"))
                stats["macro"] += 1
                _mark(f, "两层·长锚")
                cover = LONG_BEATS * float(curs[f]) / float(base_bpm)
                long_until = f + max(1.0, cover)
                micro_blocked_until = max(micro_blocked_until, f + LULL_TILES)
                continue
            b = BURST_PATTERN[bi % len(BURST_PATTERN)]
            bi += 1
            made = 0
            for _k in range(b):
                if f > re_:
                    break
                px, py = MICRO_POS[stats["micro"] % len(MICRO_POS)]
                ev.append(cam(f, dur=MICRO_BEATS, ease=ez["micro"], rel="Tile",
                              position=[px, py], zoom=MICRO_ZOOM, tag="gs_micro"))
                stats["micro"] += 1
                _mark(f, "两层·微观")
                made += 1
                f += MICRO_TILES
            if made == 0:
                break
            if f <= re_:                                # 串尾「弹回」
                ev.append(cam(f, dur=SNAP_BEATS, ease=ez["snap"], rel="Player",
                              position=macro_pos, zoom=MACRO_ZOOM,
                              tag="gs_macro_snap"))
                stats["snap"] += 1
                _mark(f, "两层·弹回")
                f += SNAP_GAP_TILES

    # ★ 出场：整谱末尾回基准（不收尾的话最后一发补间会一直挂着）
    ev.append(cam(last, dur=SNAP_BEATS, ease="OutCubic", rel=bp["relativeTo"],
                  position=bp["position"], zoom=bp["zoom"],
                  rotation=bp["rotation"], tag="gs_back"))
    _mark(last, "出场")

    # ---- 逐 `cur` 段汇总（报告/清单要按源谱的段来，不许静默）
    for (s, e, cur) in segs:
        style = "两层" if cur >= CUR_SPLIT else "一拍一振"
        n_ev = sum(1 for f in range(s, e + 1) if f in floor_style)
        n_lull = sum(1 for f in range(s, e + 1)
                     if floor_style.get(f) == "两层·静默")
        stats["segments"].append({"lo": s, "hi": e, "cur": float(cur),
                                  "style": style, "events": n_ev,
                                  "lull": n_lull,
                                  "long": floor_style.get(s) == "两层·长锚"})
    return ev, stats


# ============================================================ 写
def write_level(src: dict, ev: list[dict], out_path: str) -> None:
    """把 `MoveCamera` **插**进原 action 表里 —— **原有条目的相对顺序一格不动**。

    ★ 不能用「整体 `sort(key=floor)`」：原谱里同一个 `floor` 上的事件顺序是有意义的
      （例如 `SetSpeed` 必须先生效），整体重排会改动原有行为。所以这里做的是
      **稳定插入**：所有 `floor ≤ 我们的 floor` 的原事件先出，再放我们那条。
      （这样也保证同一格上 `SetSpeed` 在我们前面。）
    """
    orig = list(src.get("actions") or [])
    res: list[dict] = []
    i = 0
    for a in sorted(ev, key=lambda x: int(x["floor"])):
        while i < len(orig) and int(orig[i].get("floor") or 0) <= int(a["floor"]):
            res.append(orig[i])
            i += 1
        res.append(a)
    res.extend(orig[i:])
    out = dict(src)
    out["actions"] = res
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))


def src_floor_sorted(src: dict) -> bool:
    fl = [int(a.get("floor") or 0) for a in (src.get("actions") or [])]
    return fl == sorted(fl)


def verify_output(path: str, src: dict, ev: list[dict]) -> list[str]:
    """把产物**重新读一遍**再核对（含用宏解析器解码）。"""
    bad: list[str] = []
    out = json.load(open(path, encoding="utf-8"))

    # ① 除了 actions，其它字段必须逐字节一样
    for k in src:
        if k == "actions":
            continue
        if out.get(k) != src.get(k):
            bad.append("产物里 `%s` 被改动了（只许加 MoveCamera）" % k)
    if set(out) != set(src):
        bad.append("产物 keys 变了：%s" % sorted(set(out) ^ set(src)))

    # ② 原有条目的**相对顺序**没被动过；我们的事件按 floor 升序
    src_old = [a for a in (src.get("actions") or [])
               if a.get("eventType") != "MoveCamera"]
    if [a for a in out["actions"] if a.get("eventType") != "MoveCamera"] != src_old:
        bad.append("原有 action 的相对顺序/内容被改了（非 MoveCamera 部分对不上）")
    fl = [int(a["floor"]) for a in out["actions"] if a.get("eventType") == "MoveCamera"]
    if fl != sorted(fl):
        bad.append("我们加进去的 MoveCamera 没按 floor 有序")
    if not src_floor_sorted(src):
        bad.append("⚠ 源谱自身的 actions **本来就不是**按 floor 有序的"
                   "（本工具保持了原顺序，没有替你重排）")

    # ④ 我们加的事件一条不少
    mv = [a for a in out["actions"] if a.get("eventType") == "MoveCamera"]
    if len(mv) != len(ev):
        bad.append("MoveCamera 条数 %d != 计划 %d" % (len(mv), len(ev)))

    # ⑤ 字段集 + `zoom` 红线
    for a in mv:
        if set(a) != set(MV_KEYS):
            bad.append("floor %s 的字段集不是标准 10 个：%s"
                       % (a.get("floor"), sorted(set(a) ^ set(MV_KEYS))))
            break
        if a.get("zoom") is None or float(a["zoom"]) <= 0.0:
            bad.append("floor %s 的 zoom = %r（用户实测：null / 0 ⇒ 黑屏）"
                       % (a.get("floor"), a.get("zoom")))
            break
        for k in ("relativeTo", "position", "rotation"):
            if a.get(k) in (None, [None, None]):
                bad.append("floor %s 的 %s 留空（读了会被当 0）" % (a.get("floor"), k))
                break
        if not a.get("relativeTo"):
            bad.append("floor %s 没写 relativeTo" % a.get("floor"))
            break

    # ⑤ 用宏解析器**真的解一遍**
    try:
        a2 = ACC.load_angle(path)
        got = [x for x in (a2.actions or [])
               if x.get("eventType") == "MoveCamera"]
        if len(got) != len(ev):
            bad.append("解析器读出来的 MoveCamera 条数 %d != %d" % (len(got), len(ev)))
        n_ang = len(ACC.floor_bpm(a2))            # 顺带把角度表解出来
        if n_ang != len(src.get("angleData") or []):
            bad.append("解析器解出来的格数 %d != 源谱 %d"
                       % (n_ang, len(src.get("angleData") or [])))
    except Exception as exc:                                  # noqa: BLE001
        bad.append("宏解析器读产物失败：%s: %s" % (type(exc).__name__, exc))
    return bad


# ============================================================ 验收清单
def write_checklist(path: str, meta: dict, ev: list[dict], stats: dict) -> None:
    L: list[str] = []
    add = L.append
    add("=" * 78)
    add("运镜验收清单 · 国士無双两层（离线补写，不是 core 接线）")
    add("=" * 78)
    add("")
    add("源谱      : %s" % meta["src"])
    add("产物      : %s" % meta["out"])
    add("谱面      : %d 格 · base bpm %g · %.1f s" % (meta["tiles"], meta["base"],
                                                      meta["seconds"]))
    add("基准位    : relativeTo=%s position=%s rotation=%g zoom=%g"
        % (meta["bp"]["relativeTo"], meta["bp"]["position"],
           meta["bp"]["rotation"], meta["bp"]["zoom"]))
    add("  ★ 复位回的是**这张谱的**基准位，不是 demo 的 200 / [0,0] —— 写错就是每段一次瞬跳。")
    add("")
    add("── 这一版干了什么 ──────────────────────────────────────────")
    add("")
    add("分派（`docs/64` §9.2a：`cur ≥ %g` 走两层，否则一拍一振）：" % CUR_SPLIT)
    add("  高 cur（两层）   %5d 格" % meta["hi"])
    add("  低 cur（一拍一振）%5d 格" % meta["lo"])
    add("")
    add("两层配方（时值全部**按拍写死**，照抄 `Laur_-_国士無双`）：")
    add("")
    add("  ┌ 宏观层 `relativeTo=Player`（跟人）")
    add("  │   位置 = 基准 + [%g,%g] = %s    缩放 = %g"
        % (MACRO_DELTA[0], MACRO_DELTA[1], meta["macro_pos"], MACRO_ZOOM))
    add("  │   长锚 dur=%g 拍 `OutExpo`（每隔 %g 格左右一发，之后自己在走）"
        % (LONG_BEATS, LONG_BEATS))
    add("  │   弹回 dur=%g 拍 `OutCirc`（每一串微观的串尾）" % SNAP_BEATS)
    add("  └ 节流 %g 格 @cur 900：上一条长锚没走完就不发下一条" % LONG_BEATS)
    add("")
    add("  ┌ 微观层 `relativeTo=Tile`（不跟人）")
    add("  │   位置 = 6 个小值轮换 %s" % (MICRO_POS,))
    add("  │   缩放 = %g     dur=%g 拍 `OutElastic`（照抄国士的主力 ease）"
        % (MICRO_ZOOM, MICRO_BEATS))
    add("  └ 节奏 = 每 %d 格一条，一串 %s 条，串尾一条「弹回」"
        % (MICRO_TILES, list(BURST_PATTERN)))
    add("")
    add("时值换算（用户 2026-10：「base bpm 是谱面的设计，这个曲子实际上 bpm")
    add("可以看特效版本的」）：非特效版 base %g，特效版（作者 pixelo3o）base 225，"
        % meta["base"])
    add("同一首歌 ⇒ **1 乐句拍 = %g 个谱面拍**。" % MUSIC_BEATS)
    add("")
    add("  %-10s %-14s %-10s %s" % ("", "国士（base 340）", "秒", "本谱（base %g）" % meta["base"]))
    add("  %-10s %-14s %-10s %s" % ("微观", "1.66667 拍", "294 ms", "%g 拍" % MICRO_BEATS))
    add("  %-10s %-14s %-10s %s" % ("弹回", "4 拍", "706 ms", "%g 拍" % SNAP_BEATS))
    add("  %-10s %-14s %-10s %s" % ("长锚", "32 拍", "5.65 s", "%g 拍" % LONG_BEATS))
    add("")
    add("事件：" + " · ".join("%s %d" % (k, v) for k, v in meta["counts"]))
    add("  合计 %d 条 `MoveCamera`（密度 %.3f 条/格；国士無双全长是 0.269 条/格）"
        % (len(ev), len(ev) / max(1, meta["tiles"])))
    add("")
    add("── 听的时候看什么 ─────────────────────────────────────────")
    add("")
    add("① **宏观层跟人吗**：整段画面应该始终挂在玩家身上（一个固定的大偏移），")
    add("   而不是钉在某一格上不动。")
    add("② **微观层不跟人吗**：每 2 格镜头在几个小位置之间弹一下（`OutElastic`），")
    add("   是**弹性**的过冲，不是硬切、不是匀速滑。")
    add("③ **两层是不是并存**：上面两件事应当**同时**发生 —— 这是国士那套的核心，")
    add("   也是它解掉「高 cur 只能缓慢 / 低 cur 只能一拍一振」二选一的地方。")
    add("④ **弹回**：每串微观末尾有一条 `Player` 的大偏移把画面拉回宏观位 ——")
    add("   应当感觉像「抖几下 → 呼一口气」，不是一直在抖。")
    add("⑤ **静默期**：长锚之后 %d 格一条微观都没有（照抄国士那 44 格）——" % LULL_TILES)
    add("   那几秒画面应当是**慢慢漂**的，如果还在高频抖就是没照做。")
    add("")
    add("── 已知偏离（不许静默）────────────────────────────────────")
    add("")
    add("1. **「一拍一振」的网格落在格上，不是拍上。** 本谱低 cur 段 `cur=225`、")
    add("   `base=900`（1 格 = 4 拍），落在拍上就没法一格一条了。")
    add("   `tools/make_camera_demo.py::m_beat_shake` 对这种情形是**直接硬拦**的。")
    add("   本工具只有 %d 格走这一档，影响很小，但如实写出来。" % meta["lo"])
    add("2. **出场归位**（末格一条 `Player` 回基准）是本工具加的 —— 源谱本来在整首中间。")
    add("3. **进了 `--entry` 才有进场招牌**（`zoom=1` + 两整圈）：用户说是可选项目，")
    add("   本轮默认**没开**。")
    add("4. **原有 action 一条没改**：`MoveCamera` 是**插**进去的，原事件相对顺序不动。")
    add("")
    add("── 逐段分派 ────────────────────────────────────────────────")
    add("")
    add("  格区间            cur       档         事件数")
    for d in stats["segments"]:
        add("  %5d..%-5d  %8g  %-8s  %4d%s"
            % (d["lo"], d["hi"], d["cur"], d["style"], d["events"],
               "   ← 静默" if d.get("lull") else ""))
    add("")
    add("── 产物怎么用 ─────────────────────────────────────────────")
    add("")
    add("把整个目录拷进：")
    add(r"  C:\Users\<你>\Documents\A Dance of Fire and Ice\Worlds\ ")
    add("（目录里只有 `level.adofai` + 音频；源谱没有任何图片依赖）")
    add("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


# ============================================================ 主
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把国士無双两层运镜写到真实谱面上")
    ap.add_argument("chart", help="源谱面 .adofai")
    ap.add_argument("--out", default=None, help="输出目录（默认 out/运镜验收谱v3-<谱名>）")
    ap.add_argument("--report", action="store_true", help="打印分派与密度报告")
    ap.add_argument("--entry", action="store_true",
                    help="加国士的进场招牌（含 zoom=1，用户说是可选项）")
    ap.add_argument("--macro", default=ACC.MACRO_DIR, help="宏解析器目录")
    args = ap.parse_args(argv)

    src_path = os.path.abspath(args.chart)
    if not os.path.isfile(src_path):
        raise SystemExit("找不到谱面：%s" % src_path)
    # 目录名优先（`level.adofai` 这种通用名认不出是哪张谱）
    stem = os.path.splitext(os.path.basename(src_path))[0]
    if stem.lower() in ("level", "main", "done"):
        stem = os.path.basename(os.path.dirname(src_path)) or stem
    out_dir = args.out or os.path.join(_ROOT, "out", "运镜验收谱v3-" + stem)
    out_dir = os.path.abspath(out_dir)

    src = load_json(src_path)
    bp = base_pose(src["settings"])
    macro_pos = [bp["position"][0] + MACRO_DELTA[0],
                 bp["position"][1] + MACRO_DELTA[1]]
    a = ACC.load_angle(src_path, args.macro)
    curs = ACC.floor_bpm(a)
    msv = ACC.floor_ms(a)

    print("=" * 88)
    print("源谱：%s" % src_path)
    print("  %d 格 · base bpm %g · 时长 %.1f s"
          % (len(curs), float(src["settings"]["bpm"]), sum(msv) / 1000.0))
    print("  基准位（settings）：relativeTo=%s position=%s rotation=%g zoom=%g"
          % (bp["relativeTo"], bp["position"], bp["rotation"], bp["zoom"]))
    print("  已有 MoveCamera：%d 条"
          % len([x for x in (src.get("actions") or [])
                 if x.get("eventType") == "MoveCamera"]))
    print("  乐句拍换算：谱面 base %g ⇒ 1 乐句拍 = %g 个谱面拍（特效版 base 225）"
          % (float(src["settings"]["bpm"]), MUSIC_BEATS))
    print("  配方时值：微观 %g 拍 · 弹回 %g 拍 · 长锚 %g 拍 · 进场 %g 拍"
          % (MICRO_BEATS, SNAP_BEATS, LONG_BEATS, ENTRY_BEATS))

    ev, stats = plan(curs, bp, float(src["settings"]["bpm"]), entry=bool(args.entry))

    n_tiles = len(curs)
    print()
    print("── 分派（`docs/64` §9.2a：`cur ≥ %g` 走两层，否则一拍一振）────────────"
          % CUR_SPLIT)
    hi = sum(1 for c in curs if c >= CUR_SPLIT)
    lo = n_tiles - hi
    print("  高 cur（两层）  %5d 格  %5.1f%%" % (hi, 100.0 * hi / n_tiles))
    print("  低 cur（一拍一振）%5d 格  %5.1f%%" % (lo, 100.0 * lo / n_tiles))
    print()
    print("── 事件 ─────────────────────────────────────────────────────")
    print("  宏观 · 长锚  %4d" % stats["macro"])
    print("  宏观 · 弹回  %4d" % stats["snap"])
    print("  微观 · Tile  %4d" % stats["micro"])
    print("  一拍一振定基 %4d" % stats["shake_lock"])
    print("  一拍一振硬切 %4d" % stats["shake_cut"])
    print("  合计         %4d 条 MoveCamera（源谱 %d 格，密度 %.3f 条/格）"
          % (len(ev), n_tiles, len(ev) / max(1, n_tiles)))
    print("  微观层静默期：长锚后 %d 格（国士是 44 格）" % LULL_TILES)
    print("  长锚节流：上一条长锚的 %g 拍没走完就不重发（本谱 ≈ %g 格 @cur 900）"
          % (LONG_BEATS, LONG_BEATS * 1.0))
    if stats["long_skipped"]:
        print("  因节流而**没发**的长锚：%d 处（段够长但长锚还在走）"
              % stats["long_skipped"])
    segs = stats["segments"]
    zero = [d for d in segs if d["events"] == 0]
    print("  cur 段共 %d 个；其中 **一条事件都没发** 的 %d 个（长锚静默期内）"
          % (len(segs), len(zero)))
    if zero:
        print("    " + " / ".join("格%d..%d(cur %g)" % (d["lo"], d["hi"], d["cur"])
                                  for d in zero[:10])
              + (" …" if len(zero) > 10 else ""))
    if args.report:
        print()
        print("── 逐段（格区间 · cur · 档 · 事件数）─────────────────────────")
        for d in segs:
            print("  格 %5d..%-5d  cur %-8g  %-8s  %4d 条%s"
                  % (d["lo"], d["hi"], d["cur"], d["style"], d["events"],
                     "   ← 静默 %d 格" % d["lull"] if d.get("lull") else ""))

    out_level = os.path.join(out_dir, "level.adofai")
    write_level(src, ev, out_level)

    # 音频
    song = str(src["settings"].get("songFilename") or "")
    copied = None
    if song:
        s_song = os.path.join(os.path.dirname(src_path), song)
        if os.path.isfile(s_song):
            copied = os.path.join(out_dir, song)
            shutil.copyfile(s_song, copied)
        else:
            print("  ⚠ 找不到音频 `%s`，产物里不会有声 —— **不静默**" % s_song)

    bad = verify_output(out_level, src, ev)
    print()
    if bad:
        print("✗ 产物自检失败：")
        for x in bad:
            print("   · " + x)
    else:
        print("✓ 产物自检通过：原 action 一条没改 / floor 有序 / 字段集标准 10 个 / "
              "zoom 全部 > 0 / 宏解析器能解")
    if copied:
        print("✓ 音频已放好：%s" % os.path.basename(copied))

    # 验收清单
    cl = os.path.join(out_dir, "验收清单.txt")
    write_checklist(cl, {
        "src": src_path, "out": out_dir, "tiles": n_tiles,
        "base": float(src["settings"]["bpm"]), "seconds": sum(msv) / 1000.0,
        "bp": bp, "hi": hi, "lo": lo, "macro_pos": macro_pos,
        "counts": [("宏观·长锚", stats["macro"]), ("宏观·弹回", stats["snap"]),
                   ("微观 Tile", stats["micro"]),
                   ("一拍一振定基", stats["shake_lock"]),
                   ("一拍一振硬切", stats["shake_cut"])],
    }, ev, stats)
    print("✓ 验收清单 → %s" % cl)
    print()
    print("产物 → %s" % out_dir)
    print("进游戏：把整个目录拷进")
    print(r"  C:\Users\<你>\Documents\A Dance of Fire and Ice\Worlds\ ")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
