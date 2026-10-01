# -*- coding: utf-8 -*-
"""**谱面 → 下落式（4K/8K）预览图**（只读）。

    python tools/chart_4k.py <谱面> --from 78000 --to 82000 --out x.png
    python tools/chart_4k.py <谱面> --by planet --lanes 4
    python tools/chart_4k.py <谱面> --text --from 78000 --to 82000

## 方向（★ 抄宏的 `paintEvent`，2026-10 修正）

宏工具 `Adofai-Macro-Adofai_Macro_V5.0/app/ui/falling_notes_window.py` 的几何是：

```python
lane_w   = width / lanes                          # 轨道是**竖列**
judge_y  = max(height * JUDGE_LINE_RATIO, ...)    # 判定线在**下方**（约 78% 处）
px_per_ms= judge_y / LEAD_MS * speed_scale
head_y   = judge_y - (press - chart_time) * px_per_ms   # ★ 未来在上、音符往下落
```

⇒ **横轴 = 轨道（列）**、**纵轴 = 时间（越往上越晚）**、判定线在下边缘。
本工具第一版把两个轴弄反了（画成了钢琴卷），已改。

## 两种轨道映射

| `--by` | 轨道 = | 看什么 |
|---|---|---|
| `technique`（默认） | ★ **宏的手法模拟**（`app/technique.py::AdvancedTechnique`）算出来的**按键** → 左右半区 | 真实的**手法**（哪只手、哪根手指、什么时候轮指换手） |
| `heading` | 该格的**绝对朝向**分 N 档（`Twirl` 翻 180°） | 轨道的**形状** |

### ★ `technique` 档是**调宏的**，不是自己编的

用户 2026-10：「我怀疑你使用了自己造的轮子。宏里面是**有手法模拟**的，
即看起来会**明显有配置的结构**」—— 对。宏的 `AdvancedTechnique` 有：

* 配置（`config.json`）：`left_keys` / `right_keys`（各 16 键，从中间向左右发散）、
  `technique.single_kps`（单手单指速度，×60 = `single_finger_bpm`）、
  `main_hand`、`press_duration`；
  ★ **单指正确阈值是 300 bpm**（= `single_kps` 5.0）；工程里现在配的是 8.0 ⇒ 480，
  那是用户**自己调高的**设置，不是物理上限（用户 2026-10 澄清）。
* 内部**键位梯级表**：`right_hand = [5,6,7,8, 13,…]`、`left_hand = [4,3,2,1, 12,…]`
  （`_TIER_SIZE=4`、`_TIER_COUNT=4`、`_HAND_MAX=16`）；
* 算法：按「累计间隔 < `60/(single_finger_bpm×2)` 秒」把密集按键并成**一组**
  （= 双押 / 三押 / 多押），逐组选左右手，单指跟不上就**换手**（轮指），
  4 押另有一条换位规则；`map_key_number()` 把内部编号映射到用户绑定的键。

本工具直接 `import` 它（MIT），并把 `assignments`（按键名）照
`main_window._falling_lane_of` 映射成轨道：左手 → `per_hand-1-idx`、右手 → `per_hand+idx`。
**左手键位要先每 4 个一组反转**再喂给模拟器（照 `_reverse_key_groups`）。

## 图上有什么

* **音符**：一个方块落在**按下时刻**（贴判定线上方）；颜色按 `cur` 分档；
* **该格的时长**：方块**往上**拖一条淡色细带（= 到下一个按键的距离，长格/拐角一眼可见）；
* **双押 / 三押**：方块套**白描边**（判据 = 40ms 内有 2~3 个键）；`planet` 档下还会**同时出现在两条轨**；
* **节拍线**：每拍一条横线，每 4 拍加亮并写拍号；
* **判定线 + 判定框**：底部的横线 + 每条轨下方的框（照宏的排版）；
* **中旋格**（`angleData == 999`）：不推进，画成空心方块。

时间轴模型来自 `tools/analyze_camera_cur.py`（借宏解析器，与游戏
`CalculateFloorEntryTimes` 同口径）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                              # noqa: BLE001
    pass

from analyze_camera_cur import (                               # noqa: E402
    MACRO_DIR, floor_bpm, floor_ms, load_angle, press_clusters)

OUT_DIR = os.path.join(_ROOT, "out", "_camera", "4k")

BG_TOP = (13, 18, 24)
BG_BOT = (26, 33, 43)
LANE_LINE = (58, 66, 78)
BEAT_LINE = (44, 52, 64)
BAR_LINE = (92, 104, 120)
JUDGE = (235, 235, 245)
CAP_EDGE = (120, 200, 255)
CAP_FILL = (30, 42, 58)
TXT = (205, 212, 222)
DIM = (150, 160, 172)

#: `cur` 分档着色：低 / 中 / 高 / 超高
CUR_COLORS = (
    (90, 170, 255),      # < 1× base
    (110, 220, 150),     # < 2×
    (240, 200, 90),      # < 4×
    (255, 120, 120),     # ≥ 4×
)

JUDGE_RATIO = 0.80       #: 判定线在窗口高度的比例（宏是 0.78 上下）
NOTE_H = 9.0             #: 音符方块高度（px）
CAP_MARGIN = 0.045       #: 判定框距底边的比例


def cur_color(cur: float, base: float):
    r = cur / base if base else 1.0
    if r < 1.0:
        return CUR_COLORS[0]
    if r < 2.0:
        return CUR_COLORS[1]
    if r < 4.0:
        return CUR_COLORS[2]
    return CUR_COLORS[3]


def lane_of_heading(ang: float, lanes: int) -> int:
    step = 360.0 / lanes
    return int(round(float(ang) / step)) % lanes


# ---------------------------------------------------------------- 手法模拟（调宏的）
def macro_config(macro_dir: str) -> dict:
    p = os.path.join(macro_dir, "config.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def reverse_key_groups(keys, size: int = 4) -> list:
    """照抄 `main_window._reverse_key_groups`：左手键位**每 4 个一组反转**再喂给模拟器。"""
    out = []
    for i in range(0, len(keys), size):
        out.extend(reversed(keys[i:i + size]))
    return out


def technique_lanes(press_ms, macro_dir: str, lanes: int):
    """★ **直接用宏的手法模拟**（`app/technique.py::AdvancedTechnique`，MIT）。

    用户 2026-10：「我怀疑你使用了自己造的轮子。宏里面是**有手法模拟**的，
    即看起来会**明显有配置的结构**」—— 对，宏的 `AdvancedTechnique` 就是：

    * 配置：`config.json` 的 `left_keys` / `right_keys`（各 16 键，从中间向左右发散）、
      `technique.single_kps`（单手单指速度，×60 = `single_finger_bpm`）、
      `main_hand`、`press_duration`；
    * 内部键位梯级表：`right_hand = [5,6,7,8, 13,…]`、`left_hand = [4,3,2,1, 12,…]`
      （`_TIER_SIZE=4`、`_TIER_COUNT=4`、`_HAND_MAX=16`）；
    * 算法：按「累计间隔 < `60/(single_finger_bpm*2)` 秒」把密集按键并成**一组**
      （这就是双押/三押/多押），逐组选左右手，单指跟不上时**换手**（轮指），
      4 押还有一条专门的换位规则。

    输出是**按键名**；再照 `main_window._falling_lane_of` 映射成轨道：
    左手 → `per_hand-1-idx`、右手 → `per_hand+idx`。

    返回 `(每按键的轨道号, 按键的按住 ms, 组号, 按键名)`。
    """
    if macro_dir not in sys.path:
        sys.path.insert(0, macro_dir)
    from app.technique import AdvancedTechnique                  # noqa: PLC0415

    cfg = macro_config(macro_dir)
    left_cfg = list(cfg.get("left_keys") or [])
    right_cfg = list(cfg.get("right_keys") or [])
    tech = cfg.get("technique") or {}
    sim = AdvancedTechnique(
        reverse_key_groups(left_cfg, 4), right_cfg,
        single_finger_bpm=float(tech.get("single_kps", 6.5)) * 60.0,
        main_hand=str(tech.get("main_hand", "right")),
        default_hold_ms=float(cfg.get("press_duration") or 40))
    keys, hold_ms, groups = sim.simulate_with_groups(list(press_ms), hold_mask=None)

    per_hand = max(1, lanes // 2)
    out: list[int] = []
    for k in keys:
        if k in left_cfg:
            out.append(per_hand - 1 - (left_cfg.index(k) % per_hand))
        elif k in right_cfg:
            out.append(per_hand + (right_cfg.index(k) % per_hand))
        else:
            out.append(0)
    return out, hold_ms, groups, keys


def lane_of_heading(ang: float, lanes: int) -> int:
    step = 360.0 / lanes
    return int(round(float(ang) / step)) % lanes


def build(path: str, macro_dir: str, lanes: int):
    """返回 (a, msv, bpms, cum, headings, clusters, tech, base)。

    `tech[floor]` = 该格落在哪条轨（宏的手法模拟）；不是按键的格为 `None`。
    """
    a = load_angle(path, macro_dir)
    msv = floor_ms(a)
    bpms = floor_bpm(a)
    n = len(msv)
    cum = [0.0]
    for x in msv:
        cum.append(cum[-1] + x)
    # 朝向：`angleData` 是**绝对朝向**，Twirl 把后续格翻 180°
    tw = sorted({int(x["floor"]) for x in (a.actions or [])
                 if x.get("eventType") == "Twirl"})
    headings: list[float | None] = []
    flip = False
    ti = 0
    for i, ang in enumerate(a.angleData):
        while ti < len(tw) and tw[ti] == i:
            flip = not flip
            ti += 1
        headings.append(None if ang == 999
                        else (float(ang) + (180.0 if flip else 0.0)) % 360.0)
    clusters = press_clusters(msv)

    press_floors = [i for i in range(n) if msv[i] > 1e-9]
    tech: list[int | None] = [None] * n
    if press_floors:
        tl, _hold, _grp, _keys = technique_lanes(
            [cum[i] for i in press_floors], macro_dir, lanes)
        for j, f in enumerate(press_floors):
            if j < len(tl):
                tech[f] = tl[j]
    return a, msv, bpms, cum, headings, clusters, tech, float(a.settings["bpm"])


def lanes_for(i: int, by: str, lanes: int, headings, tech) -> list[int]:
    if by == "technique":
        return [] if tech[i] is None else [tech[i]]
    h = headings[i]
    return [lane_of_heading(h, lanes)] if h is not None else list(range(lanes))


def render_png(path: str, out: str, lanes: int, by: str, t0: float, t1: float,
               width: int, height: int, macro_dir: str) -> str:
    from PIL import Image, ImageDraw
    a, msv, bpms, cum, headings, clusters, tech, base = build(path, macro_dir, lanes)
    n = len(msv)
    total = cum[-1]
    t0 = max(0.0, t0)
    t1 = total if t1 <= 0 else min(total, t1)
    if t1 <= t0:
        t0, t1 = 0.0, total
    span = t1 - t0

    judge_y = height * JUDGE_RATIO
    px_per_ms = judge_y / span                     # 整个窗口落在判定线以上
    lane_w = width / float(lanes)

    img = Image.new("RGB", (width, height), BG_TOP)
    dr = ImageDraw.Draw(img)
    # 背景竖直渐变（照宏：上深下浅）
    for y in range(height):
        f = y / max(1, height - 1)
        dr.line([(0, y), (width, y)],
                fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * f)
                           for i in range(3)))

    def Y(t: float) -> float:
        """时间 → 屏幕 y。★ 越晚越靠上（音符往下落）。"""
        return judge_y - (t - t0) * px_per_ms

    # ---- 节拍 / 小节线（横线）
    ms_per_beat = 60000.0 / base
    b0 = int(math.floor(t0 / ms_per_beat))
    b1 = int(math.ceil(t1 / ms_per_beat))
    for b in range(b0, b1 + 1):
        t = b * ms_per_beat
        if not (t0 <= t <= t1):
            continue
        y = Y(t)
        major = (b % 4 == 0)
        dr.line([(0, y), (width, y)], fill=BAR_LINE if major else BEAT_LINE,
                width=2 if major else 1)
        dr.text((width - 30, y + 2), "%.0f" % b, fill=DIM if not major else TXT)

    # ---- 轨道分隔线（竖线）
    for L in range(1, lanes):
        x = lane_w * L
        dr.line([(x, 0), (x, judge_y)], fill=LANE_LINE, width=1)

    # ---- `cur` 色带（左边缘，竖的）
    seg_lo = 0
    for i in range(n + 1):
        if i < n and abs(bpms[i] - bpms[seg_lo]) <= 0.5:
            continue
        y_a, y_b = Y(cum[seg_lo]), Y(cum[i])
        top = max(0.0, min(y_a, y_b))
        bot = min(judge_y, max(y_a, y_b))
        if bot > top:
            dr.rectangle([0, top, 7, bot], fill=cur_color(bpms[seg_lo], base))
        seg_lo = i

    # ---- 音符
    for i in range(n):
        t = cum[i]
        if not (t0 <= t <= t1):
            continue
        dur = max(msv[i], 0.0)
        y_head = Y(t)
        y_tail = Y(t + dur)                        # 更晚 ⇒ 更靠上
        h = max(0.0, y_head - y_tail)
        # 该格的时长：一条淡色细带（长格 / 拐角一眼可见）
        if dur > 1e-9 and h >= 3.0:
            dr.rectangle([2, y_head - h, 5, y_head], fill=(72, 80, 94))
        ys = lanes_for(i, by, lanes, headings, tech)
        col = cur_color(bpms[i], base)
        sz = clusters[i] if i < len(clusters) else 1
        for L in ys:
            x0 = L * lane_w + max(2.0, lane_w * 0.12)
            x1 = (L + 1) * lane_w - max(2.0, lane_w * 0.12)
            if msv[i] <= 1e-9:                     # 中旋：空心
                dr.rectangle([x0, y_head - NOTE_H / 2, x1, y_head + NOTE_H / 2],
                             outline=(130, 140, 155))
                continue
            dr.rectangle([x0, y_head - NOTE_H / 2, x1, y_head + NOTE_H / 2],
                         fill=col)
            if sz >= 2:                            # 双押 / 三押：白描边
                dr.rectangle([x0, y_head - NOTE_H / 2, x1, y_head + NOTE_H / 2],
                             outline=(255, 255, 255), width=2)

    # ---- 判定线 + 判定框
    dr.line([(0, judge_y), (width, judge_y)], fill=JUDGE, width=2)
    cap_h = max(10.0, height * 0.045)
    cap_y = height - height * CAP_MARGIN
    for L in range(lanes):
        pad = max(3.0, lane_w * 0.12)
        dr.rounded_rectangle([L * lane_w + pad, cap_y - cap_h,
                              (L + 1) * lane_w - pad, cap_y],
                             radius=4, fill=CAP_FILL, outline=CAP_EDGE, width=2)

    # ---- 标题 / 图例
    dr.text((8, 6), "%s  %sK %s  %.1fs~%.1fs"
            % (os.path.basename(path), lanes, by, t0 / 1000.0, t1 / 1000.0),
            fill=TXT)
    dr.text((8, 20), "white=double  hollow=midspin  left bar=cur", fill=DIM)
    for k, c in enumerate(CUR_COLORS):
        dr.rectangle([width - 112 + k * 26, 8, width - 100 + k * 26, 16], fill=c)
    dr.text((width - 112, 22), "low..fast", fill=DIM)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out)
    return out


def render_text(path: str, lanes: int, by: str, t0: float, t1: float,
                cell_ms: float, macro_dir: str) -> str:
    """ASCII 下落式：**每行一个时间格**，列 = 轨道（从上往下的时间顺序读）。"""
    a, msv, bpms, cum, headings, clusters, tech, base = build(path, macro_dir, lanes)
    n = len(msv)
    total = cum[-1]
    t0 = max(0.0, t0)
    t1 = total if t1 <= 0 else min(total, t1)
    if t1 <= t0:
        t0, t1 = 0.0, total
    ms_per_beat = 60000.0 / base
    rows = int((t1 - t0) / cell_ms) + 1
    grid = [[" "] * lanes for _ in range(rows)]

    for i in range(n):
        t = cum[i]
        if not (t0 <= t <= t1):
            continue
        r = int((t - t0) / cell_ms)
        if not (0 <= r < rows):
            continue
        sz = clusters[i] if i < len(clusters) else 1
        ch = "O" if sz <= 1 else ("D" if sz == 2 else "T")
        if by == "heading" and msv[i] <= 1e-9:
            ch = "."
        for L in lanes_for(i, by, lanes, headings, tech):
            grid[r][L] = ch

    L: list[str] = []
    L.append("谱面 %s　%dx %s　每行 %.0fms（= %.3f 拍）"
             % (os.path.basename(path), lanes, by, cell_ms, cell_ms / ms_per_beat))
    L.append("O=单键　D=双押　T=三押　.=中旋　列 = 轨道（左→右）")
    L.append("★ 从上往下读 = **音符往下落**；最下面那行就是判定线（与 PNG 同向）")
    # ★ 行序与 PNG 一致：**时间越晚越靠上**，判定线在最下面。
    for r in range(rows - 1, -1, -1):
        beat = (t0 + r * cell_ms) / ms_per_beat
        tag = ""
        if abs(beat - round(beat)) < cell_ms / ms_per_beat * 0.5:
            tag = ("▬ %d" % int(round(beat))) if int(round(beat)) % 4 == 0 else "·"
        if r == 0:
            tag = "══ 判定线"
        L.append("%9.1f |%s| %s" % (t0 + r * cell_ms, "".join(grid[r]), tag))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chart")
    ap.add_argument("--by", choices=("technique", "heading"), default="technique",
                    help="technique = 宏的手法模拟（默认）；heading = 按绝对朝向分档")
    ap.add_argument("--lanes", type=int, default=8)
    ap.add_argument("--from", dest="t0", type=float, default=0.0, help="起始 ms")
    ap.add_argument("--to", dest="t1", type=float, default=0.0, help="结束 ms")
    ap.add_argument("--width", type=int, default=560)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--cell", type=float, default=25.0, help="ASCII 每行毫秒")
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--macro", default=MACRO_DIR)
    args = ap.parse_args(argv)

    if args.text:
        print(render_text(args.chart, args.lanes, args.by, args.t0, args.t1,
                          args.cell, args.macro))
        return 0
    out = args.out or os.path.join(
        OUT_DIR, "%s_%s_%dK_%d_%d.png" % (os.path.splitext(
            os.path.basename(args.chart))[0], args.by, args.lanes,
            int(args.t0), int(args.t1)))
    print("→ " + render_png(args.chart, out, args.lanes, args.by, args.t0,
                            args.t1, args.width, args.height, args.macro))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
