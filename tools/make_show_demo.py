# -*- coding: utf-8 -*-
"""**演出验收谱 v9：把现有招式挨个排一遍，逐段验收**。

    python tools/make_show_demo.py [输出目录]

★ 用户 2026-09：「挨个排练一下 让我验收」⇒ 一谱到底，**每一招独占一段**，
段首有游戏内标签（`EditorComment`）+ 专属颜色 + 节拍重音，另附 `验收清单.txt` 打勾。

段落顺序（每段 = 跑道 RUNWAY 格 + 正文 BODY 格 + 间隔 SEP 格）：

    ① 出A ② 出B ③ 出C ④ 出D          ← 离场 4 招
    ⑤ 入A ⑥ 入B ⑦ 入C                ← 入场 3 招
    ⑧ 逐格 ⑨ 组2 ⑩ 组3 ⑪ 组4         ← 反向 QE 四档（g = 1/2/3/4）
    ⑫ 叠合（出A + 入A 同段）           ← 验证 §5.10 同格事件顺序

★ 招式参数与 `docs/62 §1` 逐字一致（那份文件是唯一依据）。
★ 只写 `actions`，绝不碰 `angleData / bpm / travel / Twirl / settings` ⇒ 时序零影响。
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import wave
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import path as path_mod                             # noqa: E402
from core import show as S                                    # noqa: E402
from core import solve as solve_mod                           # noqa: E402
from core import writer as W                                  # noqa: E402

BPM = 120.0
CD = 4
SR = 44100
OPEN = 10               # 开场跑道（让玩家起步、听清节拍）
RUNWAY = 14             # 每段正文之前的跑道（≥ 入场 lead 10 + 余量，否则会盖到上一段）
BODY = 8                # 离场 / 入场 的正文格数
BODY_QE = 12            # 反向 QE 的正文格数（能被 1/2/3/4 整除 ⇒ 分组整齐）
BODY_FX = 16            # 轨道底噪（泛白）段的正文格数（够看两三条带）
SEP = 2                 # 段间分隔

#: ★★ 招式表**唯一源头 = `core/show.py`**（改那边这一份自动跟着变，不许抄两份）
MOVES_OUT = S.MOVES_OUT
MOVES_IN = S.MOVES_IN
REV_QE = S.REV_QE

ENTER_LEAD = 10         # 入场前瞻（格）—— 定稿 10（`docs/62 §4.3`）
ENTER_MARGIN = 4.0      # 入场余量（拍）
INIT_ANGLE = S.INIT_ANGLE
ANIM_AHEAD = ENTER_LEAD + ENTER_MARGIN      # = 14 拍（≥ 起跑点，否则动画播在方块出现前）

# ------------------------------------------------------------------ 招式表
#: ★★ 招式表在 `core/show.py`（上面已 import）。这里只留"这一段用哪一招"的编排。

#: ★ 附加：**轨道底噪 / 泛白**（`RecolorTrack`，QE 的做法）
#:   `Glow` 的着色公式（`scrFloor.cs:1251-1255`，从游戏反编译读出来的）：
#:       t = (1 − cos(2π·(Time.time + off) / animDuration)) / 2
#:       color = Lerp(color1, color2, t)
#:   `off`（逐格相位，`scrFloor.cs:1856`）：
#:       Forward : (1 − (seqID % pulseLength)/pulseLength) · animDuration
#:       Backward:      (seqID % pulseLength)/pulseLength  · animDuration
#:   ⇒ 每格相位按**绝对格号**错开 ⇒ 沿轨道形成一条向前扫的色带。
#:      `pulseLength` = 带长（QE 用 10 密集涟漪 / **114 长带**）。
#:      `animDuration` = 呼吸周期（秒）⇒ 0.4 快闪 / 2 慢呼吸。
#:   ⚠ 它是**状态**：一写就保持到被下一条覆盖 ⇒ 每个 fx 段结尾都补一条 restore。
FX_MOVES: dict[str, dict] = {
    "泛白·长带": dict(text="RecolorTrack · Glow + Forward + 带长 10 · 呼吸 1s\n"
                          "看什么：一条灰白色的带沿轨道向前扫过，**走过的格子会泛白**再回落\n"
                          "        （带长按 §4.5E 取证定稿 10；QE 那条 114 是特例）",
                     color="9c9c9cff", color2="585858ff", ctype="Glow", pulse="Forward",
                     plen=10, adur=1.0, glow=40, style="Standard"),
    "泛白·慢呼吸": dict(text="RecolorTrack · Glow + Forward + 带长 10 · 呼吸 2s · glow 100\n"
                            "看什么：同样的带，周期拉到 2 秒 —— 慢而稳的呼吸（对比上一段的 1 秒）",
                       color="ffffffff", color2="909090ff", ctype="Glow", pulse="Forward",
                       plen=10, adur=2.0, glow=100, style="Neon"),
    "泛白·闪烁": dict(text="RecolorTrack · Blink + Forward + 带长 10 · 呼吸 0.4s\n"
                          "看什么：把 Glow 换成 **Blink**（线性锯齿、不往返）—— 锐利闪烁对照",
                     color="3a3a3aff", color2="8c8c8cff", ctype="Blink", pulse="Forward",
                     plen=10, adur=0.4, glow=10, style="Standard"),
}

#: `RecolorTrack` 恢复常态（`Single` + 基准米色）—— 每条 fx 段结尾必须补一条
FX_RESTORE = dict(color="debb7bff", color2="ffffffff", ctype="Single", pulse="None",
                  plen=10, adur=2.0, glow=100, style="Standard")

#: (招名, 类别, 游戏内说明)
SECTIONS: list[tuple[str, str, str]] = [
    ("出A", "out", "出A · InBack 4 拍 → 位置(0,-2) 转-25° 缩到 0\n"
                   "看什么：前一格先微微一顿，再整个缩成 0 被甩上去（最有力）"),    ("出B", "out", "出B · OutQuad **4 拍** → 位置不动 缩到 20% 消失（原 1 拍，已按「4拍子」改）\n"
                   "看什么：原地缩没、不位移，最干脆、最不抢戏 —— 但 4 拍让它是「看得见」的"),
    ("出C", "out", "出C · InSine 4 拍 → 位置(0,-1.5) 转+15° 缩到 95%\n"
                   "看什么：几乎不缩，慢慢淡出 + 轻轻飘上去（最含蓄）"),
    ("出D", "out", "出D · InExpo 4 拍 → 位置(-1,6) 转+30° 缩到 90%\n"
                   "看什么：前 3 拍几乎不动，最后一拍猛地向右下飞走（最炸）"),
    ("入A", "in",  "入A · InOutBack 回位 2 拍，初态 pos(6,4) rot90 缩0 透0\n"
                   "看什么：从右上 4~6 格带 90° 自转飞进来，冲过头再弹回（幅度最大）"),
    ("入B", "in",  "入B · OutBack 回位 2 拍，初态 pos(0,2) rot90 缩0 透0\n"
                   "看什么：从正上方 2 格旋落，落地回弹一下"),
    ("逐格", "qe", "反向QE 逐格（g=1）· OutElastic 3 拍 lead 4\n"
                   "看什么：整段先全藏（pos(0,-6) 缩0 透0），再一格一格从下方弹回来（最滚）"),
    ("组2", "qe",  "反向QE 组2（g=2）· 一条事件罩 2 格\n"
                   "看什么：两格一组，成对从下方弹回来"),
    ("组3", "qe",  "反向QE 组3（g=3）★ 三连音那一档 · 一条事件罩 3 格\n"
                   "看什么：**三个三个地出来** —— 你说 QE 适合三连音的那一档"),
    ("组4", "qe",  "反向QE 组4（g=4）· 一条事件罩 4 格\n"
                   "看什么：四格一组，成块从下方弹回来"),
    ("叠合", "mix", "叠合验收 · 出A + 入A 写在**同一段**上\n"
                    "看什么：同一格「飞进来 → 踩到 → 被踹走」应当连贯；\n"
                    "        若变成「刚踹走又飞回来」⇒ §5.10 同格事件顺序（angleOffset）错了"),
    ("泛白·长带", "fx", FX_MOVES["泛白·长带"]["text"]),
    ("泛白·慢呼吸", "fx", FX_MOVES["泛白·慢呼吸"]["text"]),
    ("泛白·闪烁", "fx", FX_MOVES["泛白·闪烁"]["text"]),
]

PALETTE = ["808080", "66ccff", "3399ff", "66ff99", "ffcc66", "ff6666", "cc66ff",
           "ffffff", "ff99cc", "99ffcc", "ffcc99", "cccccc"]

USER_ANIM = ("None", 3.0, "None", 0.0)


# ---------------------------------------------------------------- 事件构造

def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if abs(f - round(f)) < 1e-9 else round(f, 4)


def move_track(floor: int, s0: int, s1: int, *, dur: float, ease: str = "Linear",
               pos=None, rot=None, scale=None, op=None, angle: float = 0.0,
               gap: int = 0, tag: str = "") -> dict:
    """一条 `MoveTrack`（`ThisTile` 相对偏移）；**只写要生效的字段**（§3.1）。"""
    a: dict = {"floor": int(floor), "eventType": "MoveTrack",
               "startTile": [int(s0), "ThisTile"], "endTile": [int(s1), "ThisTile"],
               "gapLength": int(gap), "duration": _num(dur)}
    if pos is not None:
        a["positionOffset"] = [_num(pos[0]), _num(pos[1])]
    if rot is not None:
        a["rotationOffset"] = _num(rot)
    if scale is not None:
        a["scale"] = [_num(scale[0]), _num(scale[1])]
    if op is not None:
        a["opacity"] = _num(op)
    a["angleOffset"] = _num(angle)
    a["ease"] = ease
    a["eventTag"] = tag
    return a


def animate_track(floor: int, anim: tuple) -> dict:
    return {"floor": int(floor), "eventType": "AnimateTrack",
            "trackAnimation": anim[0], "beatsAhead": _num(anim[1]),
            "trackDisappearAnimation": anim[2], "beatsBehind": _num(anim[3])}


def color_track(floor: int, rgb: str) -> dict:
    return {"floor": int(floor), "eventType": "ColorTrack", "justThisTile": True,
            "trackColorType": "Single", "trackColor": rgb,
            "secondaryTrackColor": "ffffff", "trackColorAnimDuration": 2,
            "trackColorPulse": "None", "trackPulseLength": 10,
            "trackStyle": "Standard", "trackTexture": "", "trackTextureScale": 1,
            "trackGlowIntensity": 100}


# ---------------------------------------------------------------- 三段实现

def emit_out(ev: list, s: int, e: int, key: str) -> None:
    """离场：正文每一格写一条，踹走前一格（`span[-1,-1]`，`angleOffset 0`）。"""
    m = MOVES_OUT[key]
    for f in range(s, e + 1):
        ev.append(move_track(f, -1, -1, dur=m["dur"], ease=m["ease"],
                             pos=m["pos"], rot=m["rot"], scale=m["scale"],
                             op=m["op"], angle=0.0, tag=key))


def emit_in(ev: list, s: int, e: int, key: str) -> None:
    """入场：初态 + 回位两条在同格；目标 = `f + lead`；多铺两格免得段尾断掉。"""
    m = MOVES_IN[key]
    lead = ENTER_LEAD
    ret = -180.0 * ENTER_MARGIN
    for f in range(s - lead, e - lead + 1 + 2):           # 尾后多 2 格
        ev.append(move_track(f, lead, lead, dur=0.0, angle=INIT_ANGLE,
                             ease="Linear", tag="in_init", **m["init"]))
        ev.append(move_track(f, lead, lead, dur=m["dur"], angle=ret,
                             ease=m["ease"], pos=(0, 0), rot=0,
                             scale=(100, 100), op=100, tag="in_ret"))


def emit_qe(ev: list, s: int, e: int, key: str) -> None:
    """反向 QE：① 总藏罩整段 ② 拉回**一条罩 g 格**逐组推进。"""
    m = REV_QE[key]
    q_s = S.QE_HIDE
    q_e = S.QE_SHOW
    lead = int(m["lead"])
    body = e - s + 1
    ev.append(move_track(s - RUNWAY, RUNWAY, RUNWAY + body - 1, dur=0.0,
                         angle=INIT_ANGLE, ease="Linear", tag="hide", **q_s))
    # ★ 偏移量**恒为 lead**（写成 lead+k 会漏一半方块，见 §1.3 / §5.5）
    g = max(1, int(m["group"]))
    k = 0
    while k < body:
        size = min(g, body - k)
        ev.append(move_track(s + k - lead, lead, lead + size - 1,
                             dur=m["dur"], ease=m["ease"], pos=q_e["pos"],
                             rot=q_e["rot"], scale=q_e["scale"], op=q_e["op"],
                             angle=0.0, tag="pull"))
        k += g


def recolor_track(floor: int, s0: int, s1: int, cfg: dict, *, dur: float = 0.0,
                  gap: int = 0, tag: str = "") -> dict:
    """一条 `RecolorTrack`（**范围**事件，见 `ffxRecolorFloorPlus.cs:83`）。

    `startTile`/`endTile` 用 `ThisTile` 相对锚点；`gapLength` 是**步长减 1**。
    """
    return {"floor": int(floor), "eventType": "RecolorTrack",
            "startTile": [int(s0), "ThisTile"], "endTile": [int(s1), "ThisTile"],
            "gapLength": int(gap), "duration": _num(dur), "ease": "Linear",
            "angleOffset": 0, "eventTag": tag,
            "trackColor": cfg["color"], "secondaryTrackColor": cfg["color2"],
            "trackColorType": cfg["ctype"], "trackColorPulse": cfg["pulse"],
            "trackPulseLength": int(cfg["plen"]),
            "trackColorAnimDuration": _num(cfg["adur"]),
            "trackStyle": cfg["style"], "trackGlowIntensity": int(cfg["glow"]),
            "trackTexture": "", "trackTextureScale": 1}


def emit_mix(ev: list, s: int, e: int) -> None:
    """叠合：入场（入A）+ 离场（出A）写在**同一段**上，验证同格顺序。"""
    emit_in(ev, s, e, "入A")
    emit_out(ev, s, e, "出A")


def emit_fx(ev: list, s: int, e: int, key: str) -> None:
    """轨道底噪：一条 `RecolorTrack` 罩住整段 + 段尾一条 restore。

    ★ 它是**状态**（`scrFloor.specialColor*`），不 restore 会一路留到谱尾。
    """
    ev.append(recolor_track(s, 0, e - s, FX_MOVES[key], tag=key))
    ev.append(recolor_track(e, 1, 2, FX_RESTORE, tag="fx_restore"))


# ---------------------------------------------------------------- 主流程

def build():
    secs: list[dict] = []
    cursor = OPEN
    for key, kind, text in SECTIONS:
        body = BODY_QE if kind == "qe" else (BODY_FX if kind == "fx" else BODY)
        s = cursor + RUNWAY
        e = s + body - 1
        secs.append(dict(key=key, kind=kind, text=text, s=s, e=e,
                         body=body, runway0=cursor))
        cursor = e + 1 + SEP
    n_tiles = cursor + 8                                   # 尾巴：留出 restore 的落点

    floors = [solve_mod.Floor(travel=180.0, bpm=BPM, twirl=False, turn=0.0,
                              heading=0.0, angle=0.0, speed_k=1.0, pause_beats=0.0)
              for _ in range(n_tiles)]
    p = path_mod.Path.from_floors(floors, [False] * n_tiles, allow_twirl=True)
    p.commit_to(floors, write_twirl=False)
    ch = solve_mod.Chart(base_bpm=BPM, floors=floors, meta={})

    ev: list[dict] = []
    for i, sec in enumerate(secs):
        s, e, kind = sec["s"], sec["e"], sec["kind"]
        if kind == "qe":
            anim = ("None", float(REV_QE[sec["key"]]["lead"] + 2), "None", 0.0)
        elif kind == "fx":
            anim = ("Fade", 8.0, "Fade", 4.0)
        else:
            # ★ 入场段的 beatsAhead 必须 ≥ lead + margin（= 14），否则整套飞行动画
            #   播在**方块出现之前** ⇒ 方块凭空出现在终点（`docs/62 §3.7`）
            anim = ("Fade", float(ANIM_AHEAD), "Fade", 4.0)
        sec["anim"] = anim
        ev.append(animate_track(sec["runway0"], anim))
        if kind != "fx":          # fx 段靠 RecolorTrack 整段换色，不逐格上色
            for f in range(s, e + 1):
                ev.append(color_track(f, PALETTE[i % len(PALETTE)]))
        if kind == "out":
            emit_out(ev, s, e, sec["key"])
        elif kind == "in":
            emit_in(ev, s, e, sec["key"])
        elif kind == "qe":
            emit_qe(ev, s, e, sec["key"])
        elif kind == "mix":
            emit_mix(ev, s, e)
        else:
            emit_fx(ev, s, e, sec["key"])

    ev.sort(key=lambda a: (int(a["floor"]), _order(a["eventType"]),
                           a.get("angleOffset") or 0))
    return ch, ev, secs


def _order(et: str) -> int:
    return {"SetSpeed": 0, "Pause": 0, "Twirl": 0, "AnimateTrack": 1,
            "MoveTrack": 2, "MoveCamera": 3, "Flash": 4, "ColorTrack": 5,
            "RecolorTrack": 6, "EditorComment": 9}.get(et, 7)


# ---------------------------------------------------------------- 自检（§5）

_MV_KEYS = {"floor", "eventType", "startTile", "endTile", "gapLength", "duration",
            "positionOffset", "rotationOffset", "scale", "opacity",
            "angleOffset", "ease", "eventTag"}


def _span(a: dict) -> tuple[int, int]:
    f = int(a["floor"])
    return f + int(a["startTile"][0]), f + int(a["endTile"][0])


def verify(ev: list[dict], ch, secs: list[dict]) -> list[str]:
    """§5 的断言：白名单 / 越界 / gapLength / 不变量 / 完整性 / 有序 / 同格顺序。"""
    bad: list[str] = []
    n = len(ch.floors)
    n_in = n_out = n_big = 0
    for a in ev:
        if a.get("eventType") != "MoveTrack":
            continue
        f = int(a["floor"])
        lo, hi = _span(a)
        if lo > hi:
            bad.append(f"floor {f} startTile > endTile"); continue
        if int(a.get("gapLength", 0)) < 0:
            bad.append(f"floor {f} gapLength<0（步长变 0 ⇒ 死循环）")
        if not (0 <= lo and hi < n) or not (0 <= f < n):
            bad.append(f"floor {f} 作用范围越界：{lo}..{hi}（共 {n} 格）")
        if hi - lo + 1 >= 4:
            n_big += 1
        if lo > f:
            n_in += 1
        elif hi <= f:
            n_out += 1
        elif float(a.get("duration", 0)) > 0:
            bad.append(f"floor {f} 带动画的 MoveTrack 跨过玩家：{lo}..{hi} 含 {f}")
        if not set(a) <= _MV_KEYS:
            bad.append(f"floor {f} MoveTrack 多出字段 {sorted(set(a) - _MV_KEYS)}")
    fl = [int(a["floor"]) for a in ev]
    if fl != sorted(fl):
        bad.append("事件没有按 floor 有序")

    # ★ RecolorTrack（范围类）：越界 / gapLength / 字段齐不齐（缺字段=继承上一个状态）
    _rc_need = {"floor", "eventType", "startTile", "endTile", "gapLength", "duration",
                "ease", "angleOffset", "eventTag", "trackColor",
                "secondaryTrackColor", "trackColorType", "trackColorPulse",
                "trackPulseLength", "trackColorAnimDuration", "trackStyle",
                "trackGlowIntensity", "trackTexture", "trackTextureScale"}
    n_fx = 0
    for a in ev:
        if a.get("eventType") != "RecolorTrack":
            continue
        n_fx += 1
        f = int(a["floor"])
        lo, hi = _span(a)
        if lo > hi or not (0 <= lo and hi < n):
            bad.append(f"floor {f} RecolorTrack 范围越界：{lo}..{hi}（共 {n} 格）")
        if int(a.get("gapLength", 0)) < 0:
            bad.append(f"floor {f} RecolorTrack gapLength<0")
        if not _rc_need <= set(a):
            bad.append(f"floor {f} RecolorTrack 缺字段 {sorted(_rc_need - set(a))}"
                       f"（缺失 = 继承上一状态，不是「不改」）")
        if a.get("trackColorType") in ("Glow", "Blink", "Rainbow") \
                and float(a.get("trackColorAnimDuration") or 0) <= 0:
            bad.append(f"floor {f} {a['trackColorType']} 的 trackColorAnimDuration ≤ 0"
                       f"（呼吸周期为 0 ⇒ 除零）")

    # §5.5 完整性：反向 QE 段每一格必须被「拉回」命中**恰好一次**
    n_pull = 0
    for sec in secs:
        if sec["kind"] != "qe":
            continue
        hits: list[int] = []
        for a in ev:
            if a.get("eventTag") != "pull":
                continue
            lo, hi = _span(a)
            gap = int(a.get("gapLength", 0))
            for t in range(lo, hi + 1, 1 + gap):
                if sec["s"] <= t <= sec["e"]:
                    hits.append(t)
        for t in range(sec["s"], sec["e"] + 1):
            c = hits.count(t)
            if c == 0:
                bad.append(f"段「{sec['key']}」：格 {t} 没有任何『拉回』命中（会永远看不见）")
                break
            if c > 1:
                bad.append(f"段「{sec['key']}」：格 {t} 被『拉回』命中 {c} 次（会互相打断）")
                break
        n_pull += len(hits)

    # §5.10 同格事件顺序：同一 floor 上 MoveTrack 的 angleOffset 必须递增
    #   （入场初态 -1440 < 入场回位 -720 < 离场 0 ⇒ 先摆好再踹走）
    per: dict[int, list[float]] = {}
    for a in ev:
        if a.get("eventType") == "MoveTrack":
            per.setdefault(int(a["floor"]), []).append(float(a.get("angleOffset") or 0.0))
    for f, angs in sorted(per.items()):
        if angs != sorted(angs):
            bad.append(f"floor {f} 同格 MoveTrack 顺序错：angleOffset {angs} "
                       f"（应为递增：先入场后离场）")

    print(f"  · 入场 {n_in} 条 · 离场/脚下 {n_out} 条 · 一次罩 ≥4 格 {n_big} 条")
    print(f"  · 轨道底噪 RecolorTrack {n_fx} 条（含 restore）")
    print(f"  · 完整性：反向 QE {sum(1 for s in secs if s['kind'] == 'qe')} 段共 "
          f"{n_pull} 格全部被『拉回』命中且不重复")
    return bad


def verify_file(path: str) -> list[str]:
    bad: list[str] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        j = json.load(f)
    acts = j.get("actions", [])
    if not any(a.get("eventType") == "MoveTrack" for a in acts):
        bad.append("落盘文件里一条 MoveTrack 都没有")
    for a in acts:
        if a.get("eventType") == "MoveTrack" and a.get("startTile", [None])[1] != "ThisTile":
            bad.append(f"floor {a.get('floor')} startTile 不是 ThisTile"); break
    fl = [int(a["floor"]) for a in acts if "floor" in a]
    if fl != sorted(fl):
        bad.append("落盘 actions 没有按 floor 有序")
    return bad


# ---------------------------------------------------------------- 音频

def write_click_track(path: str, ch, accents: set[int]):
    """合成节拍点击轨：普通格低音、**段首重音**，让验收时能对上段落。"""
    lead_ms = solve_mod.total_lead_ms(ch, CD)
    times = solve_mod.times_from_chart(ch)
    n = int((lead_ms + (times[-1] if times else 0.0) + 1200.0) / 1000.0 * SR)
    buf = [0.0] * max(1, n)

    def click(at_ms: float, freq: float, amp: float) -> None:
        i0 = int(at_ms / 1000.0 * SR)
        dur = int(0.035 * SR)
        for k in range(dur):
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
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 32767))))
                               for v in buf))
    return lead_ms, n


# ---------------------------------------------------------------- 输出

def write_checklist(path: str, secs: list[dict]) -> None:
    lines = ["演出验收谱 v9 · 逐段验收清单", "=" * 60,
             "每段：段首有游戏内文字标签 + 重音节拍 + 专属颜色。",
             "看完一段就在 [ ] 里打勾，不满意的直接说段号。", ""]
    for i, s in enumerate(secs, start=1):
        lines.append(f"[ ] 段{i:>2} 「{s['key']}」 格 {s['s']}~{s['e']}"
                     f"（正文 {s['body']} 格）")
        for ln in s["text"].split("\n"):
            lines.append("        " + ln)
        lines.append("")
    lines += ["—" * 60,
              "叠合段若出现「刚踹走又飞回来」⇒ 说明同格事件顺序（angleOffset）没排对。",
              "反向 QE 段若有个别方块**从头到尾看不见**⇒ 说明偏移量算错（§5.5）。"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def make_one(out_dir: str) -> int:
    ch, ev, secs = build()
    wav = os.path.join(out_dir, "main.wav")
    write_click_track(wav, ch, {s["s"] for s in secs})

    W.write_dir(ch, out_dir, name="main", audio_src=wav,
                song="演出验收谱 v9（逐招排练）", artist="(合成节拍点击)",
                author="ADOFAI Chart Generator",
                offset_ms=0.0, difficulty=1, countdown_ticks=CD)

    p = os.path.join(out_dir, "main.adofai")
    with open(p, "r", encoding="utf-8") as f:
        j = json.load(f)
    for i, s in enumerate(secs, start=1):
        j["actions"].append({"floor": s["s"], "eventType": "EditorComment",
                             "comment": f"★ 段{i}/{len(secs)} · {s['text']}\n"})
    j["actions"].extend(ev)
    j["actions"].sort(key=lambda a: (int(a.get("floor") or 0),
                                     _order(a.get("eventType", "")),
                                     a.get("angleOffset") or 0))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent="\t")

    ms = 60000.0 / BPM
    print("=" * 92)
    print("演出验收谱 v9 · 逐招排练（每招独占一段）")
    print("=" * 92)
    print(f"输出目录 : {out_dir}")
    print(f"谱面     : {len(ch.floors)} 格 · bpm {BPM:g} · 每格 {ms:.0f} ms · "
          f"全长 {len(ch.floors) * ms / 1000:.0f} s")
    print()
    print(f"{'段':<4}{'招':<6}{'正文格':<11}{'类别':<6}看什么")
    for i, s in enumerate(secs, start=1):
        first = s["text"].split("\n")[1] if "\n" in s["text"] else ""
        print(f"{i:<4}{s['key']:<6}{str(s['s']) + '~' + str(s['e']):<11}"
              f"{s['kind']:<6}{first}")
    print()
    n_mv = sum(1 for a in ev if a["eventType"] == "MoveTrack")
    n_an = sum(1 for a in ev if a["eventType"] == "AnimateTrack")
    n_cl = sum(1 for a in ev if a["eventType"] == "ColorTrack")
    n_rc = sum(1 for a in ev if a["eventType"] == "RecolorTrack")
    print(f"事件总量 : {len(ev)} = MoveTrack {n_mv} + AnimateTrack {n_an} + "
          f"ColorTrack {n_cl} + RecolorTrack {n_rc} + EditorComment {len(secs)}")

    ok = True
    bad = verify(ev, ch, secs)
    if bad:
        ok = False
        print("✗ 自检失败：")
        for x in bad:
            print("   - " + x)
    else:
        print("✓ 自检通过：入场只碰未来 / 离场不碰未来 / 无带动画事件跨过玩家 / "
              "字段集对齐语料 / 同格顺序正确")
    bad = verify_file(p)
    if bad:
        ok = False
        print("✗ 回读落盘失败：")
        for x in bad:
            print("   - " + x)
    else:
        print("✓ 回读落盘通过：startTile 全 ThisTile / 按 floor 有序")
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

    write_checklist(os.path.join(out_dir, "验收清单.txt"), secs)
    print(f"\n验收清单 → {os.path.join(out_dir, '验收清单.txt')}")
    return 0 if ok else 1


def main() -> int:
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else os.path.join(_ROOT, "out", "演出验收谱"))
    rc = make_one(out_dir)
    print("\n进游戏：整个输出目录拷进")
    print(r"  C:\Users\<你>\Documents\A Dance of Fire and Ice\Worlds\ ")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
