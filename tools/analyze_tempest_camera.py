# -*- coding: utf-8 -*-
"""Tempest（加强版）运镜调研 —— **只读**分析器。

输入：`out/_camera/tempest/level.adofai`（从 `‹社区语料目录›`
拷来的第三方谱面，只做只读参考，不参与生成）。

做三件事：

1. **几何**：按 `angleData` + `Twirl` 还原逐格坐标，附逐格 `turn` / `travel`。
2. **环路**：找出所有「回到走过坐标」的闭合区间（雪花/魔法阵的几何特征）。
3. **图片**：把整谱 + 每个候选环路渲染成 PNG，人工确认哪一段是雪花。

输出目录 `out/_camera/tempest/`。

用法：
    python tools/analyze_tempest_camera.py            # 全部
    python tools/analyze_tempest_camera.py --region 1359 1633
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "out", "_camera", "tempest", "level.adofai")
OUT = os.path.join(ROOT, "out", "_camera", "tempest")


# ---------------------------------------------------------------- 基础

def load(path: str = SRC) -> dict:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def twirl_floors(level: dict) -> set[int]:
    return {int(a["floor"]) for a in level["actions"] if a.get("eventType") == "Twirl"}


def travels_of(level: dict, src: str = SRC) -> list[float]:
    """逐格 `travel`（度）—— **权威来源是宏解析器**。

    `parser.angle.py::getRotateAngle()` 给的 `originRotateAngleList` 就是 `travel`
    （180 = 直线、90/270 = 直角，与游戏 `CalculateFloorEntryTimes` 同口径）。

    ★ 早先这里拿 `angleData` 的相邻差当转角是**错的**（`angleData` 是绝对朝向）。
    """
    sys.path.insert(0, HERE)
    from analyze_camera_cur import load_angle           # noqa: PLC0415
    a = load_angle(src)
    a.getRotateAngle()
    return [float(x) for x in a.originRotateAngleList]


def turns_of(level: dict, src: str = SRC) -> list[float]:
    """逐格转角 = `travel − 180`（正 = 逆时针那一边）。"""
    return [t - 180.0 for t in travels_of(level, src)]


def positions(level: dict) -> list[tuple[float, float]]:
    """逐格**边界点**坐标（长度 = 格数 + 1）。

    ★ **`angleData[i]` 是这一格的绝对朝向**（度），不是转角；`Twirl` 把后续格翻转 180°，
      中旋格（`999`）不推进。早先这里把 `angleData` 当增量累加，**是错的**
      （于是渲染出来的形状也不对）。正确的 `travel` 现在从
      `tools/analyze_camera_cur.py`（借宏解析器）取。
    """
    ad = level["angleData"]
    tw = twirl_floors(level)
    pts = [(0.0, 0.0)]
    flip = False
    for i, ang in enumerate(ad):
        if i in tw:
            flip = not flip
        if ang == 999:
            pts.append(pts[-1])                     # 中旋格：原地不动
            continue
        d = (float(ang) + (180.0 if flip else 0.0)) % 360.0
        x, y = pts[-1]
        pts.append((x + math.cos(math.radians(d)), y + math.sin(math.radians(d))))
    return pts


# ---------------------------------------------------------------- 撤销/闭合

def closed_loops(pts: list[tuple[float, float]], min_len: int = 12,
                 tol: float = 1e-6) -> list[tuple[int, int]]:
    """返回 `(i, j)`：`pts[i] ≈ pts[j]` 且 `j − i ≥ min_len`。"""
    cells: dict[tuple[float, float], int] = {}
    out: list[tuple[int, int]] = []
    for i, (x, y) in enumerate(pts):
        k = (round(x, 4), round(y, 4))
        j = cells.get(k)
        if j is not None and i - j >= min_len:
            out.append((j, i))
        cells.setdefault(k, i)
    return out


def radial_symmetry(pts: list[tuple[float, float]], i0: int, i1: int,
                    n: int, tol: float = 0.15) -> float:
    """把 `pts[i0:i1]` 绕起点转 `360/n` 的整数倍，看能对上多少比例。"""
    L = i1 - i0
    if L % n:
        return 0.0
    step = L // n
    cx, cy = pts[i0]
    hit = tot = 0
    for k in range(1, n):
        ang = 2 * math.pi * k / n
        ca, sa = math.cos(ang), math.sin(ang)
        for j in range(0, step, 2):
            x, y = pts[i0 + j]
            rx = (x - cx) * ca - (y - cy) * sa + cx
            ry = (x - cx) * sa + (y - cy) * ca + cy
            x2, y2 = pts[i0 + k * step + j]
            tot += 1
            if math.dist((rx, ry), (x2, y2)) < tol:
                hit += 1
    return hit / tot if tot else 0.0


# ---------------------------------------------------------------- 渲染

def render(pts, i0, i1, path, *, size=900, pad=40, title=""):
    from PIL import Image, ImageDraw
    seg = pts[i0:i1 + 1]
    xs = [p[0] for p in seg]
    ys = [p[1] for p in seg]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    span = max(maxx - minx, maxy - miny, 1.0)
    s = (size - 2 * pad) / span
    W = int((maxx - minx) * s) + 2 * pad
    H = int((maxy - miny) * s) + 2 * pad
    W, H = max(W, size // 3), max(H, size // 3)
    img = Image.new("RGB", (W, H), (18, 18, 22))
    dr = ImageDraw.Draw(img)

    def T(p):
        return (pad + (p[0] - minx) * s, H - pad - (p[1] - miny) * s)

    for k in range(len(seg) - 1):
        dr.line([T(seg[k]), T(seg[k + 1])], fill=(120, 190, 255), width=2)
    for k in range(len(seg)):
        x, y = T(seg[k])
        dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(60, 110, 160))
    x, y = T(seg[0])
    dr.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(80, 255, 120), width=3)
    x, y = T(seg[-1])
    dr.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 80, 80), width=3)
    if title:
        dr.text((10, 8), title, fill=(230, 230, 120))
    img.save(path)
    return path


# ---------------------------------------------------------------- 镜头

CAM_KEYS = ("duration", "relativeTo", "position", "rotation", "zoom",
            "ease", "angleOffset", "eventTag")


def camera_events(level: dict) -> list[tuple[int, dict]]:
    out = []
    for a in level["actions"]:
        if a.get("eventType") == "MoveCamera":
            out.append((int(a["floor"]), a))
    return out


def fmt(ev: dict) -> str:
    parts = []
    for k in CAM_KEYS:
        v = ev.get(k, "<继承>")
        if k == "position" and isinstance(v, list):
            v = "[" + ",".join("·" if e is None else f"{e:g}" for e in v) + "]"
        parts.append(f"{k}={v}")
    return " ".join(parts)


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--region", nargs=2, type=int, default=None)
    ap.add_argument("--min-len", type=int, default=24)
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args(argv)

    lv = load(args.src)
    pts = positions(lv)
    tv = travels_of(lv, args.src)
    n = len(lv["angleData"])
    print(f"谱面：{n} 格　起点 {pts[0]}　终点 {pts[-1]}")
    print(f"travel 分布：<180 {sum(1 for t in tv if t < 179.9)}"
          f"　=180 {sum(1 for t in tv if abs(t - 180) < 0.1)}"
          f"　>180 {sum(1 for t in tv if t > 180.1)}")

    if not args.no_render:
        render(pts, 0, n, os.path.join(OUT, "map_full.png"),
               title=f"Tempest full {n} tiles")

    loops = closed_loops(pts, min_len=args.min_len)
    loops.sort(key=lambda ij: -(ij[1] - ij[0]))
    print(f"\n闭合环路（≥{args.min_len} 格）　{len(loops)} 个；按长度前 12：")
    for i0, i1 in loops[:12]:
        L = i1 - i0
        sym = {N: round(radial_symmetry(pts, i0, i1, N), 2)
               for N in (2, 3, 4, 5, 6, 8, 10, 12) if L % N == 0}
        best = max(sym.items(), key=lambda kv: kv[1]) if sym else (0, 0.0)
        print(f"  {i0:5d}..{i1:5d} len={L:4d} 最佳径向对称 N={best[0]} "
              f"({best[1] * 100:.0f}%)")
        if not args.no_render:
            render(pts, i0, i1, os.path.join(OUT, f"loop_{i0}_{i1}.png"),
                   title=f"loop {i0}..{i1} len={L}")

    if args.region:
        i0, i1 = args.region
        print(f"\n=== 区域 {i0}..{i1} ===")
        seg = pts[i0:i1 + 1]
        xs = [p[0] for p in seg]
        ys = [p[1] for p in seg]
        print(f"包围盒 {max(xs) - min(xs):.1f} × {max(ys) - min(ys):.1f}　"
              f"闭合误差 {math.dist(seg[0], seg[-1]):.3f}")
        for i0b, i1b in loops:
            if i0b >= i0 and i1b <= i1:
                print(f"  内含环路 {i0b}..{i1b} len={i1b - i0b}")
        if not args.no_render:
            render(pts, i0, i1, os.path.join(OUT, f"region_{i0}_{i1}.png"),
                   title=f"region {i0}..{i1}")

    print("\n=== MoveCamera（区域过滤后）===")
    lo, hi = (args.region if args.region else (0, n))
    k = 0
    for f, ev in camera_events(lv):
        k += 1
        if not (lo - 4 <= f <= hi + 4):
            continue
        print(f"#{k:3d} f{f:5d} {fmt(ev)}")

    print(f"\n输出目录：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
