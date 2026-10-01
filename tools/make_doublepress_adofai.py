# -*- coding: utf-8 -*-
"""生成双押练习用的 .adofai：干净的「底部」+ EditorComment 标注双押位置。

底部（我写）与双押（你写）的分工
--------------------------------
本工具只铺「底座」：每一格的时间、角度、速度全部按双押演示音频排好，
**一个双押都不写**。每一处该写双押的格子挂一条官方编辑器注释
（`{"floor":N,"eventType":"EditorComment","comment":"..."}`），
你在编辑器里按 `Alt+F` 搜「双押」就能逐个跳过去写。

时序模型 —— 全部来自游戏反编译源码，不是猜的
---------------------------------------------
`scrLevelMaker.CalculateFloorEntryTimes()`：

    num += GetTimeBetweenAngles(floor_i.entryangle, floor_i.exitangle,
                                floor_i.speed, bpm, !floor_i.isCCW);
    listFloors[i + 1].entryTime = num;

⇒ **第 i 格自己的 travel 与 speed 决定 (i → i+1) 那一段的时间**。
  于是 `SetSpeed` 落在第 f 格 = 从第 f 格出发那一段开始变速。

`scrMisc.GetTimeBetweenAngles`：

    return mod(±(exitAngle - entryAngle), 2π) / π * (60/bpm) / speed;

⇒ `travel` 就是「行星绕这一格转过的角度」，直线 = 180° = 一拍。

于是，想让 (i → i+1) 这一段是 `r` 拍（cbpm 口径）：
    travel_i = 180 · r · m_i        （m_i = 第 i 格的速度倍率）
    Δa_i     = (180 − travel_i) mod 360,  a_i = (a_{i-1} + Δa_i) mod 360
    a_{-1}   = 0  ⇒  第一格 a_0 = 0（符合你的硬规则）

`countdownTicks = 1` 是刻意的：`entryTime[1] = (countdownTicks−1)·crotchet
+ T(floor0)`，取 1 才能让倒计时项精确为 0，第一格就落在音频 t=0。

速度档（你的硬规则：只允许 2 的幂）
-----------------------------------
    音值 1   → ×1 → travel 180 → Δa   0（直线）
    音值 1/2 → ×2 → travel 180 → Δa   0（直线）
    音值 1/4 → ×4 → travel 180 → Δa   0（直线）
    音值 1/3 → ×2 → travel 120 → Δa  60（六边形，三连音没法用 2 的幂消掉）

用法
----
    python tools/make_doublepress_adofai.py            # 生成 + 自检
    python tools/make_doublepress_adofai.py --check    # 只跑自检
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.writer import SETTINGS_TEMPLATE          # noqa: E402
from tools.make_doublepress import BEATS_PER_BAR, SECTIONS, SR  # noqa: E402

CBPM = 120.0
HIT_MS = 60000.0 / CBPM                            # 一拍多少毫秒
OUT_DIR = os.path.join(ROOT, "samples", "doublepress")
TAG = "doublepress_demo_120"
AUDIO_SRC = os.path.join(ROOT, "samples", "audio", TAG + ".ogg")

#: 音值 → 速度倍率。1/3 只能用 ×2 配上 travel 120（六边形）
SPEED_OF_SUB = {1: 1, 2: 2, 3: 2, 4: 4}

#: 中旋写法的默认折返步长（X 格的 travel）。s 可调，见 pivot_for()
MIDSPIN_STEP = 15.0
#: s 的下限（度）。s→0 时 X 格几乎瞬发；留一点点避免和 0 浮点比较纠缠
S_MIN = 0.25
TAU = 2 * math.pi
HALF_PI = math.pi


def pivot_for(a_prev: float, s: float = MIDSPIN_STEP) -> float:
    """中旋插入格 X 的 angleData。

    ★ 恒等式 `travel_X + travel_Y' ≡ travel_f (mod 360)` 只保证**模**相等；
      要连**时间**也相等，就不能缠绕，即要求 `0 < s < travel_f`：

        travel_X  = mod(a_{f-1} - a_X - 180, 360) = s
        travel_Y' = mod(a_X - a_f,        360) = travel_f - s

      解出 `E_X = I_X + s`（E = exitangle = 90 - angleData、I_X = E_{f-1} + 180）：

        ⇒ a_X = (a_{f-1} - 180 - s) mod 360

      `s = 15`、`a_{f-1} = 0` 时退化成 **165** —— 这就是「固定 165」的由来，
      只在直线段成立。

    **s 可调是关键**：双押落点 = 底部格 f 的时刻 + T(s)，
      所以只要 0 < s < travel_f，双押可以落在底部两格之间的**任意**位置。
      第二条轨（双押轨）的音头一般不在底部网格上，靠的就是这个自由度。
    """
    return (a_prev - 180.0 - s) % 360.0


def midspin_pivot(a_prev: float) -> float:
    """默认步长（15°）的折返角。"""
    return pivot_for(a_prev, MIDSPIN_STEP)


# --------------------------------------------------------------- 事件表

class Cell:
    __slots__ = ("i", "t", "acc", "sec", "sec_i", "bar", "beat", "j", "sub",
                 "label")

    def __init__(self, i, t, acc, sec, sec_i, bar, beat, j, sub, label):
        self.i, self.t, self.acc = i, t, acc
        self.sec, self.sec_i = sec, sec_i
        self.bar, self.beat, self.j, self.sub = bar, beat, j, sub
        self.label = label


def _pos_label(sub: int, j: int) -> str:
    if sub == 1:
        return "正拍"
    if sub == 2:
        return "正拍" if j == 0 else "后半拍"
    if sub == 3:
        return ("三连音·第1个", "三连音·第2个", "三连音·第3个")[j]
    if sub == 4:
        return ("十六分·第1个", "十六分·第2个", "十六分·第3个", "十六分·第4个")[j]
    return f"第{j + 1}个"


def cells():
    out: list[Cell] = []
    t = 0.0
    for si, sec in enumerate(SECTIONS):
        for bar in range(sec["bars"]):
            for pos in range(BEATS_PER_BAR):
                for j in range(sec["sub"]):
                    tt = t + bar * BEATS_PER_BAR + pos + j / sec["sub"]
                    out.append(Cell(len(out), tt,
                                    bool(sec["acc"](pos, j, bar)),
                                    sec["name"], si, bar, pos, j, sec["sub"],
                                    _pos_label(sec["sub"], j)))
        t += sec["bars"] * BEATS_PER_BAR
    return out


def acc_cells(cs: list[Cell]) -> list[Cell]:
    """按顺序的全部双押点；序号 = 下标 + 1。"""
    return [c for c in cs if c.acc]


def select_marks(cs: list[Cell], spec: str) -> set[int]:
    """双押开关。返回启用的**双押点序号**（1-based，与注释里的 `#N` 一致）。

    子句可用 `+` 组合，例如 `sec:3+sec:16`：

        all / *          全开（默认）
        none             全关（= 空底座）
        mark:1,3,5       按双押点序号
        range:10-20      按序号区间
        sec:3,4,8        按段落号（1..18，见 docs/双押练习说明.md）
        base:12,16       按底座格下标
        nth:2            每 2 个取 1
    """
    acc = acc_cells(cs)
    n = len(acc)
    if not spec or spec in ("all", "*"):
        return set(range(1, n + 1))
    out: set[int] = set()
    for clause in spec.split("+"):
        clause = clause.strip()
        if not clause:
            continue
        kind, _, val = clause.partition(":")
        vals = [v.strip() for v in val.split(",") if v.strip()]
        if kind == "none":
            return set()
        if kind == "all":
            out |= set(range(1, n + 1))
        elif kind == "nth":
            k = max(1, int(vals[0]))
            out |= set(range(k, n + 1, k))
        elif kind == "mark":
            out |= {int(v) for v in vals}
        elif kind == "sec":
            s = {int(v) for v in vals}
            out |= {i for i, c in enumerate(acc, 1) if c.sec_i + 1 in s}
        elif kind == "base":
            b = {int(v) for v in vals}
            out |= {i for i, c in enumerate(acc, 1) if c.i in b}
        elif kind == "range":
            for v in vals:
                a, _, z = v.partition("-")
                out |= set(range(int(a), int(z) + 1))
        else:
            raise SystemExit(f"未知的双押开关子句: {clause!r}"
                             "（可用 all/none/mark/range/sec/base/nth）")
    return {i for i in out if 1 <= i <= n}


# --------------------------------------------------------------- 几何

def base_travels(cs: list[Cell], mult: list[float] | None = None) -> list[float]:
    """底座每一格的 travel（度）。travel_i 管 (i → i+1)。"""
    n = len(cs)
    mult = mult or [SPEED_OF_SUB[c.sub] for c in cs]
    out = []
    for i in range(n):
        r = 1.0 / cs[i].sub if i == n - 1 else cs[i + 1].t - cs[i].t
        out.append(180.0 * r * mult[i])
    return out


def inserts_from_marks(cs: list[Cell], enabled: set[int] | None) -> dict[int, list[float]]:
    """按「演示重音标记」生成插入计划，每个点一个默认步长。"""
    acc = acc_cells(cs)
    on = set(range(1, len(acc) + 1)) if enabled is None else set(enabled)
    out: dict[int, list[float]] = {}
    for k, c in enumerate(acc, 1):
        if k in on:
            out.setdefault(c.i, []).append(MIDSPIN_STEP)
    return out


def plan_from_times(cs: list[Cell], targets_ms, *,
                    s_min: float = S_MIN) -> dict[int, list[float]]:
    """把一串「双押目标时刻」翻译成插入计划。

    这是「第二条轨采双押」的核心：目标时刻来自**另一个音轨的音头**，
    一般不在底部网格上，所以必须能落在底部两格之间的任意位置。

    插入 [X(s), 999] 之后，第 j 对双押落在
        t_f + T(s_1 + … + s_j),   T(s) = s/180 × 本地格
    所以只要目标 T ∈ (t_f, t_{f+1})，取 s 与 (T − t_f) 成正比即可**精确**命中
    （前提 0 < s 且 Σs < travel_f）。

    T 正好压在底座格上时 s→0 做不到严格 0 —— s = 0 会让 X 格的 travel 退化，
    游戏会按特判给它 2 拍。此时用 s_min 兜底（≈ 亚毫秒偏移）。
    """
    n = len(cs)
    if n < 2:
        return {}
    tv = base_travels(cs)
    t = [c.t * HIT_MS for c in cs]
    gaps = [t[i + 1] - t[i] for i in range(n - 1)]

    by_floor: dict[int, list[float]] = {}
    skipped = 0
    for T in sorted(targets_ms):
        # ★ 不允许插在 floor 0 前面：那会把 angleData[0] 顶掉，
        #   破坏「开局那一格一定是直线 / angleData[0] = 0」这条硬规则。
        if T < t[1]:
            skipped += 1
            continue
        if T > t[-1]:
            skipped += 1
            continue                          # 落在谱面之外，丢弃
        k = bisect.bisect_right(t, T) - 1
        k = max(1, min(k, n - 2))
        frac = (T - t[k]) / gaps[k] if gaps[k] > 1e-9 else 0.0
        by_floor.setdefault(k, []).append(min(max(frac, 0.0), 1.0))
    if skipped:
        print(f"[计划] 丢弃 {skipped} 个目标（落在第一格之前或谱面之外；"
              f"插在 floor 0 前会破坏 angleData[0]=0）")

    plan: dict[int, list[float]] = {}
    for k, fracs in by_floor.items():
        fracs.sort()
        prev_S, ss = 0.0, []
        for fr in fracs:
            S = max(tv[k] * fr, prev_S + s_min)
            ss.append(S - prev_S)
            prev_S = S
        if prev_S > tv[k] - s_min:                    # 塞不下：整体压回去
            scale = (tv[k] - s_min) / prev_S
            ss = [s * scale for s in ss]
        plan[k] = ss
    return plan


def build_chart(cs: list[Cell],
                inserts: dict[int, list[float]] | None = None):
    """返回 (angleData, speed_mult_per_floor, set_speed_floors, marks, idx, on)。

    `inserts` = dict: base 格下标 → [s, …]；在该格**前面**依次插 [X(s), 999]。
    `idx[i]`  = 第 i 个基准格在输出里的下标（插了格，所以要映射）。
    `marks`   = 全部双押点的基准格下标（按顺序，仅作注释参考）。
    `on`      = 实际插了双押的那些基准格下标。
    """
    inserts = {k: v for k, v in (inserts or {}).items() if v}
    n = len(cs)
    base_mult = [SPEED_OF_SUB[c.sub] for c in cs]
    base_ang: list[float] = []
    prev = 0.0                                   # a_{-1} = 0
    for i in range(n):
        if i == n - 1:
            r = 1.0 / cs[i].sub                  # 末格没有下一格，随便取本段音值
        else:
            r = cs[i + 1].t - cs[i].t
        travel = 180.0 * r * base_mult[i]
        da = (180.0 - travel) % 360.0
        prev = (prev + da) % 360.0
        base_ang.append(0.0 if abs(prev) < 1e-9 else prev)

    if inserts:
        # ★ 中旋写法：在目标格「前面」依次插 [X(s), 999]。
        #   X 落在该格的**原位与原时刻**（它继承前一格的 travel）；
        #   999 的 travel = 0 且不改方向，于是第 j 对 (999, 下一格) 同一瞬间按下。
        #   X 的角度必须按前一格 + 步长 s 算（pivot_for），不能写死 165。
        #   插入格沿用**后一个基准格**的速度档，否则 travel 抵消了速度不抵消。
        ang: list[float] = []
        mult: list[float] = []
        idx: list[int] = []
        for i in range(n):
            for s in inserts.get(i, []):
                ang.append(pivot_for(ang[-1] if ang else 0.0, s))
                ang.append(999.0)
                mult += [base_mult[i]] * 2
            idx.append(len(ang))
            ang.append(base_ang[i])
            mult.append(base_mult[i])
    else:
        ang, mult, idx = base_ang, base_mult, list(range(n))

    marks = [c.i for c in acc_cells(cs)]
    on = set(inserts)
    speeds: list[tuple[int, float]] = []
    for i in range(1, len(mult)):
        if mult[i] != mult[i - 1]:
            speeds.append((i, CBPM * mult[i]))
    return ang, mult, speeds, marks, idx, on


def _angle_state(ang):
    """(exitangle[], entryangle[], midspin[])，严格按 scrLevelMaker。

    scrLevelMaker.cs:500  entryangle[0] = 3π/2
    scrLevelMaker.cs:512  exitangle[j] = (90 − angleData[j])·π/180；
                          angleData[j] == 999 时 exitangle[j] = entryangle[j]
    scrLevelMaker.cs:536  entryangle[j] = (exitangle[j−1] + π) mod 2π
    scrLevelMaker.cs:541  angleData[j] == 999 ⇒ midSpin[j] = true
    """
    n = len(ang)
    exit_a = [0.0] * n
    entry_a = [3.0 * math.pi / 2.0] * n
    mid = [False] * n
    for i, a in enumerate(ang):
        if a == 999:
            exit_a[i] = entry_a[i]
            mid[i] = True
        else:
            exit_a[i] = math.radians(90.0 - a)
        if i + 1 < n:
            entry_a[i + 1] = (exit_a[i] + math.pi) % TAU
    return exit_a, entry_a, mid


def travels(ang) -> list[float]:
    """每格的 travel（度）。

    scrMisc.GetTimeBetweenAngles = mod(±(exit−entry), 2π)/π × (60/bpm)/speed，
    所以 travel 度 = mod(exit−entry, 2π) 的度数；
    CalculateFloorEntryTimes 对 angleMoved≈0/2π 另有特判：midSpin ? 0 : 2 拍。
    """
    exit_a, entry_a, mid = _angle_state(ang)
    out = []
    for i in range(len(ang)):
        moved = (exit_a[i] - entry_a[i]) % TAU
        if moved <= 1e-6 or moved >= TAU - 1e-6:
            out.append(0.0 if mid[i] else 360.0)
        else:
            out.append(math.degrees(moved))
    return out


def simulate(ang, mult) -> list[float]:
    """按游戏源码逐格重算 entryTime（毫秒）。第 i 格自己的 travel+speed 管 i→i+1。"""
    tv = travels(ang)
    n = len(ang)
    t = [0.0] * n
    for i in range(n - 1):
        t[i + 1] = t[i] + tv[i] / 180.0 * (60.0 / CBPM) * 1000.0 / mult[i]
    return t


def positions(ang):
    """pts[i+1] = pts[i] + dir(exitangle[i])，半径 1。"""
    exit_a, _, _ = _angle_state(ang)
    n = len(ang)
    x = y = 0.0
    pts = [(0.0, 0.0)]
    for i in range(n - 1):
        x += math.cos(exit_a[i])
        y += math.sin(exit_a[i])
        pts.append((x, y))
    return pts


# --------------------------------------------------------------- 输出

def _num(v: float):
    return int(round(v)) if abs(v - round(v)) < 1e-9 else round(float(v), 6)


def comment_text(c: Cell, a: float, k: int, dp_mode: str = "none",
                 on: bool = False) -> str:
    base = (f"双押点 #{k} · 段{c.sec_i + 1}「{c.sec}」 · "
            f"第{c.bar + 1}小节第{c.beat + 1}拍 · {c.label}")
    if dp_mode == "midspin":
        if on:
            return (base + " · 【中旋写法·已启用】本格与前一格（angleData 999 → "
                           "travel 0）同一瞬间按下；再前一格是折返格（travel 15°），"
                           "坐标与本格完全重合。双押落在本音之后 1/12 本地格；"
                           "15° + 0° + (基准 − 15°) ≡ 基准 ⇒ 前后零净偏移")
        return base + " · 【本次未启用双押】（开关：--dp sec:N / mark:N / base:N）"
    if on:
        return (base + f" · 【角度双押·已启用】本格 angleData "
                       f"{_num(a)}° → {_num((a + 15) % 360)}°")
    return (base + f" · 【本次未启用双押】角度双押写法：本格 angleData "
                   f"{_num(a)}° → +15 = {_num((a + 15) % 360)}°"
                   "（下一格会自动 −15，成对闭合）")


def section_text(sec_i: int, first_a: float, n_marks: int) -> str:
    sec = SECTIONS[sec_i]
    m = SPEED_OF_SUB[sec["sub"]]
    spd = f"×{m}（{_num(CBPM * m)}bpm）" if m != 1 else "×1（原速）"
    return (f"【段{sec_i + 1}/{len(SECTIONS)}】{sec['name']} · "
            f"小节{sum(s['bars'] for s in SECTIONS[:sec_i]) + 1}-"
            f"{sum(s['bars'] for s in SECTIONS[:sec_i + 1])} · "
            f"{sec['bars'] * BEATS_PER_BAR}拍 · "
            f"{sec['sub']}音/拍 · 速度{spd} · 本段双押点 {n_marks} 个 ｜ "
            f"{sec['rule']}")


HEADER = (
    "【双押练习谱 · 底座】重音处 = 要写双押的位置，本谱一个双押都没写。\n"
    "怎么用：Alt+F 打开 Find Comment → 搜「双押」→ Next 逐个跳过去写。\n"
    "怎么写：把该格 angleData 改 +15（或 −15）。因为 Δa 每格都会连带影响下一格，"
    "一格 +15 会自动让下一格 −15 —— 这就是双押必须「成对」的原因，天然闭合。\n"
    "几何对照：0°=直线(1拍) ／ ±15°=双押(11/12拍, 300cbpm以下) ／ "
    "±30°=双押(5/6拍, 300cbpm以上)。本谱 120cbpm ⇒ 用 15°。\n"
    "速度档：只有 ×1 / ×2 / ×4 三档（2 的幂）；三连音段用 ×2 + 60° 转角。\n"
    "音频：doublepress_demo_120.ogg（重音点与双押点一一对应）。"
)

HEADER_MIDSPIN = (
    "【双押练习谱 · 中旋写法已实现】\n"
    "机制：在每个双押点前面插两格 [angleData 165, angleData 999]。\n"
    "  165 格 → travel 15°（快）\n"
    "  999 格 → midspin，travel 0（瞬发，且 exitangle = entryangle 不改方向）\n"
    "  原格 → travel 165°\n"
    "恒等式 travel_X + travel_Y' ≡ travel_f (mod 360) ⇒ 15°+0°+165° = 180°，"
    "把原来一格的时间原样摊成三格，所以前后时序**零净偏移**。\n"
    "效果：999 格与原格同一瞬间按下（真·双押）；165 格与原格坐标完全重合。"
    "不需要配对、不需要闭合核算，任何速度档/任何段落都成立 —— 这是它最省力的原因。\n"
    "代价：999 格视觉上是个折返小尖角，可读性略差。\n"
    "Alt+F 搜「双押」逐个查看；注释挂在被双押的那一格上。"
)


def _header(n_on: int, n_total: int, n_ins: int, targets=None) -> str:
    body = HEADER_MIDSPIN if n_on else HEADER
    s = (f"{body}\n【双押开关】启用 {n_on}/{n_total} 个双押点，"
         f"共插入 {n_ins} 对 [X, 999]。")
    if targets:
        s += ("\n【双押来源】第二条轨的音头（外部时刻），"
              "s 按目标时刻反算，双押**精确**落在音头上。")
    s += "\n（--dp all|none|mark:N|range:A-B|sec:N|base:N|nth:N ／ --dp-times ／ --dp-track）"
    return s


def check(path: str, inserts: dict[int, list[float]] | None = None,
          targets_ms=None) -> int:
    j = json.load(open(path, encoding="utf-8-sig"))
    ang = j["angleData"]
    cs = cells()
    st = j["settings"]
    spd = {a["floor"]: a["beatsPerMinute"] for a in j["actions"]
           if a["eventType"] == "SetSpeed"}
    mult = [1.0] * len(ang)
    cur = 1.0
    for i in range(len(ang)):
        if i in spd:
            cur = spd[i] / CBPM
        mult[i] = cur

    t = simulate(ang, mult)
    pts = positions(ang)
    want = [c.t * HIT_MS for c in cs]
    n_mark = sum(1 for c in cs if c.acc)
    gen_ang, gen_mult, _, _, idx, on = build_chart(cs, inserts)
    n_on = len(on)
    n_ins = sum(len(v) for v in (inserts or {}).values())

    bad = 0
    print("\n[自检] 1) 格数")
    exp_n = len(cs) + 2 * n_ins
    print(f"   angleData {len(ang)} / 期望 {exp_n} -> "
          f"{'OK' if len(ang) == exp_n else '不一致'}")
    bad += 0 if len(ang) == exp_n else 1
    print(f"   双押：{n_ins} 对，落在 {n_on} 个底座格上"
          f"（演示标记点共 {n_mark} 个）")

    print("[自检] 2) 基准音符时刻是否全部保留（零净偏移）")
    worst = max(min(abs(x - w) for x in t) for w in want)
    print(f"   328 个基准时刻的最大还原误差 {worst:.6f}ms")
    bad += 0 if worst < 0.5 else 1

    print("[自检] 3) 总时长")
    base_ang, base_mult = build_chart(cs)[:2]
    t_base = simulate(base_ang, base_mult)
    d = t[-1] - t_base[-1]
    print(f"   本谱 {t[-1]/1000:.4f}s  底座 {t_base[-1]/1000:.4f}s  差 {d:.6f}ms")
    bad += 0 if abs(d) < 0.5 else 1

    if n_ins:
        print("[自检] 4) 中旋双押点")
        same = len(ang) == len(gen_ang) and all(
            abs(x - y) < 1e-6 for x, y in zip(ang, gen_ang))
        print(f"   angleData 与生成器逐格一致: {same}")
        tv = travels(ang)
        tv_n, sim_n, pos_n, struct_ok = 0, 0, 0, True
        landed = []                          # (目标时刻, 实际落点)
        for k, ss in (inserts or {}).items():
            m = idx[k]                       # 被双押的那一格在新序列里的下标
            # 该格前面共插了 len(ss) 对，从 m-2*len(ss) 开始
            for q, s in enumerate(ss):
                x_i = m - 2 * len(ss) + 2 * q        # X 格
                y_i = x_i + 1                        # 999 格
                if ang[y_i] != 999:
                    struct_ok = False
                if abs(tv[x_i] - s) < 1e-6:
                    tv_n += 1
                if abs(t[y_i + 1] - t[y_i]) < 0.05:  # 999 与下一格同时
                    sim_n += 1
                if math.dist(pts[y_i + 1], pts[x_i]) < 1e-6:
                    pos_n += 1
        if targets_ms:
            # 目标时刻 -> 实际落点：每对双押的落点就是 999 格的时刻
            tb = [c.t * HIT_MS for c in cs]
            tg = sorted(T for T in targets_ms if tb[1] <= T <= tb[-1])
            got = []
            for k, ss in (inserts or {}).items():
                m = idx[k]
                for q in range(len(ss)):
                    got.append(t[m - 2 * len(ss) + 2 * q + 1])
            got.sort()
            n_cmp = min(len(got), len(tg))
            landed = [abs(p - r) for p, r in zip(got[:n_cmp], tg[:n_cmp])]
            if len(got) != len(tg):
                print(f"   （对不齐：落点 {len(got)} vs 目标 {len(tg)}，"
                      f"只比前 {n_cmp} 个）")
        print(f"   前一格是 midspin(999): {struct_ok}")
        print(f"   折返格 travel = 设定值 s: {tv_n}/{n_ins}")
        print(f"   与下一格同时按下: {sim_n}/{n_ins}")
        print(f"   与折返格坐标重合: {pos_n}/{n_ins}")
        if landed:
            print(f"   ★ 双押落点 vs 第二条轨音头: 最大误差 {max(landed):.4f}ms，"
                  f"中位 {sorted(landed)[len(landed)//2]:.4f}ms（{len(landed)} 对）")
        bad += 0 if (same and struct_ok and tv_n == n_ins and sim_n == n_ins
                     and pos_n == n_ins) else 1

    print("[自检] 5) 结构")
    probs = []
    if ang[0] != 0:
        probs.append(f"angleData[0]={ang[0]} 应为 0")
    n999 = sum(1 for a in ang if a == 999)
    if not n_ins and n999:
        probs.append(f"出现 midspin 999 ×{n999}")
    if any(not (0 <= a < 360) for a in ang if a != 999):
        probs.append("angleData 越界")
    if st["countdownTicks"] != 1:
        probs.append(f"countdownTicks={st['countdownTicks']} 应为 1")
    if st["offset"] != 0:
        probs.append(f"offset={st['offset']} 应为 0")
    if st["songFilename"] != TAG + ".ogg":
        probs.append("songFilename 不对")
    mults = sorted({round(m, 6) for m in mult})
    if not all(abs(m - 2 ** round(math.log2(m))) < 1e-9 for m in mults):
        probs.append(f"速度档不是 2 的幂: {mults}")
    floors_ss = {a["floor"] for a in j["actions"] if a["eventType"] == "SetSpeed"}
    floors_tw = {a["floor"] for a in j["actions"] if a["eventType"] == "Twirl"}
    n_cm = sum(1 for a in j["actions"] if a["eventType"] == "EditorComment")
    if floors_tw:
        probs.append("出现 Twirl")
    if floors_ss & floors_tw:
        probs.append("Twirl 与 SetSpeed 同格（社区硬规则）")
    for a in j["actions"]:
        if a["eventType"] != "EditorComment":
            continue
        if set(a) != {"floor", "eventType", "comment"}:
            probs.append(f"EditorComment 字段不对: {sorted(a)}")
            break
    print(f"   速度档 {mults}  SetSpeed {len(floors_ss)} 个  "
          f"EditorComment {n_cm} 条（落在 "
          f"{len({a['floor'] for a in j['actions'] if a['eventType'] == 'EditorComment'})} 格上）")
    for p in probs:
        print("   ✗", p)
    bad += len(probs)
    if not probs:
        print("   全部通过")
    print(f"\n结论: {'全部通过' if bad == 0 else f'{bad} 项问题'}")
    return 1 if bad else 0


BANDS = ("打击", "中频", "低频", "高频")


def targets_from_track(path: str, band: str | None = None, *,
                       pct: float = 60.0, min_gap_ms: float = 40.0,
                       grid: int = 6, prefer_beat: float = 0.5,
                       snap: bool = True) -> list[float]:
    """从音频（可指定伪音轨/频段）取音头，返回**毫秒**时刻。

    ★ 这就是「第二条轨采双押」的入口：底部音一条轨铺谱面，
      双押音另一条轨取音头，再用 plan_from_times 把 [X,999] 摆到音头上。
    """
    if band:
        from core.audio_onsets import load_as_midi
        mf = load_as_midi(path, split="hp+bands", grid=grid,
                          prefer_beat=prefer_beat, min_gap_ms=min_gap_ms,
                          pct=pct)
        tr = next((t for t in mf.tracks
                   if band in (getattr(t, "name", "") or "")), None)
        if tr is None:
            names = ", ".join(repr(getattr(t, "name", "")) for t in mf.tracks)
            raise SystemExit(f"没有含 {band!r} 的轨；该文件切出的是: {names}")
        got = [n.t_on_ms for n in tr.notes]
        if snap:
            got = sorted(got)
        print(f"[双押轨] {path} 频段「{band}」→ {len(got)} 个音头")
        return got
    import soundfile as sf
    from core.audio_onsets import detect_onsets
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    got = detect_onsets(y, sr, hop=64, pct=pct,
                        min_gap_ms=min_gap_ms).tolist()
    print(f"[双押轨] {path} 全频 → {len(got)} 个音头")
    return got


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--dp-mode", choices=("none", "midspin"), default="none",
                    help="none=空底座 / midspin=中旋写法（插 [X, 999]）")
    ap.add_argument("--dp", default="all",
                    help="双押开关（用演示重音标记）：all | none | mark:1,3 | "
                         "range:10-20 | sec:3,4 | base:12,16 | nth:2")
    ap.add_argument("--dp-times", default=None,
                    help="直接用一组时刻（毫秒，逗号分隔）作为双押点")
    ap.add_argument("--dp-track", default=None,
                    help="第二条轨的音频文件（可选 `路径:频段`，"
                         "频段 ∈ 打击/中频/低频/高频）")
    ap.add_argument("--dp-pct", type=float, default=60.0,
                    help="双押轨音头检出的分位阈值（越小越密）")
    ap.add_argument("--name", default=None, help="输出文件名（不含扩展名）")
    ap.add_argument("--check", action="store_true", help="只跑自检，不写盘")
    args = ap.parse_args(argv)

    cs = cells()
    targets: list[float] | None = None
    note = ""
    if args.dp_mode == "none":
        inserts: dict[int, list[float]] = {}
    elif args.dp_track:
        p, _, band = args.dp_track.partition(":")
        targets = targets_from_track(p, band or None, pct=args.dp_pct)
        inserts = plan_from_times(cs, targets)
        note = f"双押源：{os.path.basename(p)}"
    elif args.dp_times:
        targets = [float(x) for x in args.dp_times.replace(" ", "").split(",")
                   if x]
        inserts = plan_from_times(cs, targets)
        note = "双押源：显式时刻"
    else:
        inserts = inserts_from_marks(cs, select_marks(cs, args.dp))

    tag = args.name or (TAG if args.dp_mode == "none"
                        else f"{TAG}_{'track' if targets is not None else 'midspin'}")
    path = os.path.join(args.out_dir, tag + ".adofai")
    if not args.check:
        make(args.out_dir, inserts=inserts, name=args.name,
             targets_ms=targets, note=note)
    if not os.path.exists(path):
        print("找不到谱面文件"); return 1
    return check(path, inserts, targets)


def make(out_dir: str, *, inserts: dict[int, list[float]] | None = None,
         name: str | None = None, targets_ms=None, note: str = "",
         copy_audio=True) -> str:
    cs = cells()
    inserts = {k: v for k, v in (inserts or {}).items() if v}
    ang, mult, speeds, marks, idx, on = build_chart(cs, inserts)
    n = len(ang)
    tag = name or (TAG if not inserts else f"{TAG}_midspin")
    n_ins = sum(len(v) for v in inserts.values())

    s = dict(SETTINGS_TEMPLATE)
    s.update({
        "song": "", "songFilename": TAG + ".ogg",
        "artist": "self-made", "author": "ADOFAICHARTGENERETOR",
        "bpm": _num(CBPM), "offset": 0, "volume": 100,
        "countdownTicks": 1, "separateCountdownTime": False,
        "levelDesc": f"双押写法练习：{n_ins} 对中旋双押。{note}".strip(),
        "difficulty": 0, "previewSongStart": 0, "previewSongDuration": 10,
        "trackAnimation": "Fade", "beatsAhead": 8,
        "trackDisappearAnimation": "Fade", "beatsBehind": 0,
        "backgroundColor": "000000",
    })

    actions: list[dict] = []
    for f, bpm in speeds:
        actions.append({"floor": f, "eventType": "SetSpeed",
                        "speedType": "Bpm", "beatsPerMinute": _num(bpm),
                        "bpmMultiplier": 1, "angleOffset": 0})

    # ---- 编辑器注释（同一格的表头 + 双押点合并成一条，避免堆叠）
    by_sec: dict[int, list[int]] = {}
    for c in cs:
        if c.acc:
            by_sec.setdefault(c.sec_i, []).append(c.i)
    head = _header(len(on), len(marks), n_ins, targets_ms)
    cmap: dict[int, list[str]] = {0: [head]}
    for si in range(len(SECTIONS)):
        first = next(c.i for c in cs if c.sec_i == si)
        cmap.setdefault(idx[first], []).append(
            section_text(si, ang[idx[first]], len(by_sec.get(si, []))))
    for k, c in enumerate((c for c in cs if c.acc), 1):
        cmap.setdefault(idx[c.i], []).append(
            comment_text(c, ang[idx[c.i]], k, "midspin" if n_ins else "none",
                         c.i in on))
    # 插了双押但本身不是演示标记点的格子，也标出来
    for k, ss in inserts.items():
        if not cs[k].acc:
            cmap.setdefault(idx[k], []).append(
                f"中旋双押 ×{len(ss)}（底部格 {k} 前插入，"
                f"步长 s = {', '.join(f'{x:.3f}' for x in ss)}°）")
    comments = [{"floor": f, "eventType": "EditorComment",
                 "comment": " ｜ ".join(v)} for f, v in sorted(cmap.items())]
    # EditorComment 属于 actions（语料 822 条全在 actions 里）
    actions.extend(comments)
    actions.sort(key=lambda a: a["floor"])

    data = {
        "angleData": [_num(a) for a in ang],
        "settings": s,
        "actions": actions,
        "decorations": [],
    }

    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, tag + ".adofai")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent="\t")
    if copy_audio and os.path.exists(AUDIO_SRC):
        shutil.copy2(AUDIO_SRC, os.path.join(out_dir, TAG + ".ogg"))
    extra = f"（含中旋插入格 {2 * n_ins} 个）" if n_ins else ""
    print(f"[谱面] {dst}")
    print(f"       格 {n}{extra} · SetSpeed {len(speeds)} · "
          f"EditorComment {len(comments)}")
    print(f"       中旋双押 {n_ins} 对，落在 {len(on)} 个底座格上"
          f"（演示标记点 {len(marks)} 个）")
    return dst


# --------------------------------------------------------------- 自检

if __name__ == "__main__":
    sys.exit(main())
