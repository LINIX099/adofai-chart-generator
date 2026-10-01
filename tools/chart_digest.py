# -*- coding: utf-8 -*-
"""**谱面 → 人能读的时间轴**（只读）。

    python tools/chart_digest.py <谱面.adofai> [--mode timeline|camera|summary]
    python tools/chart_digest.py out/_camera/tempest/level.adofai --from 880 --to 930
    python tools/chart_digest.py <谱面> --mode timeline --all      # 每一格都列

## 为什么

纯 `.adofai` 是一坨 JSON：`angleData` 只有角度、`actions` 里只有 `floor` 下标，
**看不出"第几秒发生什么"**，也看不出 `cur`（当前速度）——
而这正是运镜分派唯一要看的量。

这个工具把它摊成一张**带时间的时间轴**：

    格   时间ms    Δms     拍      cur     travel  事件
    894  5371.4   71.4    4.257   840.0   210     MoveCamera dur=0 Tile pos=[0,0] rot=0 zoom=160

时间轴来自 **`tools/analyze_camera_cur.py` 的同一套模型**（借
`Adofai-Macro-Adofai_Macro_V5.0/parser` —— 照着游戏 `CalculateFloorEntryTimes`
复刻的那种，按**角度**推进，正确处理 SetSpeed / angleOffset / Pause / midspin）。

## 三种模式

| 模式 | 看什么 |
|---|---|
| `timeline`（默认） | 逐格：时间 / Δ / 拍 / `cur` / `travel` / 转角 / Twirl + 该格全部事件 |
| `camera` | 只列 `MoveCamera`，附**拍数**、**覆盖格数**、解出来的角色（定基/硬切/补间） |
| `summary` | 只有头部 + `cur` 分段表 + 事件计数 |

`timeline` 默认**只列"有事件的格"**（外加每段第一格做锚点）；`--all` 才是每一格。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from analyze_camera_cur import (                              # noqa: E402
    MACRO_DIR, cover_tiles, cur_at_floor, ease_family, floor_bpm,
    floor_ms, is_cut, is_lock, load_angle, ms_at_floor, press_clusters,
    segment_kind, windowed_kinds)

#: `angleData` 里 999 = midspin（中旋格）
MIDSPIN = 999.0

#: `pathData` 字符 → 角度（官方表，与宏解析器一致）
PATH_MAP = {
    "p": 15.0, "J": 30.0, "E": 45.0, "T": 60.0, "o": 75.0, "U": 90.0,
    "q": 105.0, "G": 120.0, "Q": 135.0, "H": 150.0, "W": 165.0, "L": 180.0,
    "x": 195.0, "N": 210.0, "Z": 225.0, "F": 240.0, "V": 255.0, "D": 270.0,
    "Y": 285.0, "B": 300.0, "C": 315.0, "M": 330.0, "A": 345.0, "R": 360.0,
    "!": 999.0,
}


def _num(v, nd=1):
    if v is None:
        return "·"
    if isinstance(v, bool):
        return "Y" if v else "·"
    if isinstance(v, (int, float)):
        f = float(v)
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return ("%." + str(nd) + "f") % f
    return str(v)


def _pos(p):
    if p in (None, [None, None]):
        return "·"
    return "[" + ",".join("·" if v is None else _num(v, 2) for v in p) + "]"


def _cam_role(a: dict) -> str:
    if not is_cut(a):
        return "补间"
    return "定基" if is_lock(a) else "硬切"


def _cam_line(a: dict, bpms: list, base_bpm: float) -> str:
    """一条 `MoveCamera` 的紧凑一行。"""
    f = int(a.get("floor") or 0)
    cur = cur_at_floor(bpms, f)
    role = _cam_role(a)
    cover = ("" if is_cut(a) else
             " 跨%s格" % _num(cover_tiles(a, cur, base_bpm), 2))
    return ("    MoveCamera %-4s dur=%-6s rel=%-6s pos=%-12s rot=%-7s "
            "zoom=%-6s ang=%-6s %-10s %s%s"
            % (role, _num(a.get("duration", 0)),
               a.get("relativeTo") or "<继承>",
               _pos(a.get("position")), _num(a.get("rotation")),
               _num(a.get("zoom")), _num(a.get("angleOffset")),
               a.get("ease"), ("tag=" + str(a["eventTag"])) if a.get("eventTag") else "",
               cover))


def _short(v, n: int = 90) -> str:
    s = str(v).replace("\n", "⏎")
    return s if len(s) <= n else s[:n] + "…"


def _other_line(a: dict) -> str:
    t = a.get("eventType")
    if t == "SetSpeed":
        st = a.get("speedType", "Bpm")
        v = a.get("beatsPerMinute") if st == "Bpm" else a.get("bpmMultiplier")
        return "    SetSpeed %s=%s" % (st, _num(v, 4))
    if t == "Twirl":
        return "    Twirl"
    if t == "Pause":
        return "    Pause %s拍" % _num(a.get("duration"))
    if t in ("MoveCamera",):
        return ""
    if t == "RepeatEvents":
        return ("    RepeatEvents %s×%s interval=%s floorCount=%s tag=%s"
                % (a.get("repeatType"), a.get("repetitions"), a.get("interval"),
                   a.get("floorCount"), a.get("tag")))
    if t == "MoveDecorations":
        bits = {k: a[k] for k in ("tag", "duration", "opacity", "scale",
                                  "positionOffset", "rotationOffset",
                                  "visible", "color") if k in a}
        return "    MoveDecorations " + _short(json.dumps(bits, ensure_ascii=False), 120)
    if t == "EditorComment":
        return "    EditorComment " + _short(a.get("comment", ""), 80)
    if t in ("AddDecoration", "AddText", "SetText"):
        return "    %s %s" % (t, _short(json.dumps(
            {k: v for k, v in a.items() if k not in ("floor", "eventType")},
            ensure_ascii=False), 110))
    return "    " + str(t)


def _cur_segments(bpms: list[float], tol: float = 0.5) -> list[dict]:
    """把「SetSpeed bpm 相同」的连续格合成段。"""
    out: list[dict] = []
    for i, c in enumerate(bpms):
        if out and abs(out[-1]["cur"] - c) < tol:
            out[-1]["hi"] = i
            out[-1]["n"] += 1
        else:
            out.append(dict(lo=i, hi=i, n=1, cur=float(c)))
    return out


def digest(path: str, mode: str, lo: int, hi: int, show_all: bool,
           macro_dir: str) -> str:
    a = load_angle(path, macro_dir)
    msv = floor_ms(a)
    bpms = floor_bpm(a)
    n = len(msv)
    base = float(a.settings.get("bpm") or 120.0)
    ms_per_beat = 60000.0 / base
    cum = [0.0]
    for ms in msv:
        cum.append(cum[-1] + ms)
    total = cum[-1]

    acts = list(a.actions or [])
    byfloor: dict[int, list[dict]] = {}
    for x in acts:
        byfloor.setdefault(int(x.get("floor") or 0), []).append(x)
    cams = [x for x in acts if x.get("eventType") == "MoveCamera"]
    angles = list(a.originRotateAngleList)

    L: list[str] = []
    L.append("=" * 100)
    L.append("谱面：%s" % os.path.basename(path))
    s = a.settings
    L.append("  %d 格 · base bpm %s · 时长 %.1f s · offset %sms · countdown %s"
             % (n, _num(s.get("bpm")), total / 1000.0, _num(s.get("offset")),
                _num(s.get("countdownTicks"))))
    L.append("  曲目 %s / %s · 难度 %s · 打击音 %s"
             % (s.get("song") or "?", s.get("artist") or "?", _num(s.get("difficulty")),
                s.get("hitsound") or "-"))
    kinds: dict[str, int] = {}
    for x in acts:
        kinds[x.get("eventType")] = kinds.get(x.get("eventType"), 0) + 1
    L.append("  actions %d —— %s" % (len(acts), " · ".join(
        "%s %d" % kv for kv in sorted(kinds.items(), key=lambda kv: -kv[1])[:10])))
    L.append("=" * 100)

    # ---------------- cur 分段
    segs = _cur_segments(bpms)
    clusters = press_clusters(msv)
    ndbl = sum(1 for c in clusters if c >= 2)
    L.append("")
    L.append("── `cur` 分段（= SetSpeed bpm 相同的连续格；只列 ≥2 格）" + "─" * 30)
    L.append("  %-4s %-14s %-6s %-10s %-9s %-8s %-10s %s"
             % ("#", "格区间", "格数", "cur(cbpm)", "每格ms", "拍/格", "类别", "起点时间"))
    k = 0
    for sg in segs:
        if sg["n"] < 2:
            continue
        k += 1
        if k > 40:
            L.append("  ...（还有 %d 段）" % (len([x for x in segs if x["n"] >= 2]) - 40))
            break
        tms = ms_at_floor(msv, sg["lo"])
        kind = segment_kind(sg["lo"], sg["hi"], angles, bpms, base)
        L.append("  %-4d %-14s %-6d %-10s %-9s %-8s %-10s %.1fms"
                 % (k, "%d..%d" % (sg["lo"], sg["hi"]), sg["n"],
                    _num(sg["cur"], 1), _num(tms, 2),
                    _num(tms / ms_per_beat, 3), kind, cum[sg["lo"]]))
    L.append("  ★ 类别：「采bpm」= cur ≥ 2×base 且 travel 全是 90 的倍数（不是雪花）；"
             "「自由形状」= travel 种类 ≥ 4")
    cl_cnt = {}
    for c in clusters:
        if c >= 2:
            cl_cnt[c] = cl_cnt.get(c, 0) + 1
    L.append("  ★ 双押/三押：**%d 格**（%.1f%%）＝ %d 个按键簇（%s；判据 = 40ms 内有 2~3 个键）"
             % (ndbl, ndbl * 100.0 / max(1, n),
                sum(v // k for k, v in cl_cnt.items()),
                "、".join("%d押×%d 簇" % (k, v // k)
                          for k, v in sorted(cl_cnt.items())) or "无"))

    kinds = windowed_kinds(bpms, angles, base)
    if kinds:
        L.append("")
        L.append("── 滑窗分类（32 格窗，合并同类；只列非「常规」）" + "─" * 34)
        for a_, b_, k_ in kinds[:30]:
            t0 = cum[a_] / 1000.0
            tv = {round(angles[i]) for i in range(a_, min(b_, len(angles) - 1) + 1)}
            L.append("  %-10s %-6s %-9s %8.1fs  travel 种类 %d %s"
                     % ("%d..%d" % (a_, b_), "%d 格" % (b_ - a_ + 1), k_, t0,
                        len(tv), sorted(tv)[:8]))
        if len(kinds) > 30:
            L.append("  ...（还有 %d 段）" % (len(kinds) - 30))
        L.append("  ★ 「采bpm」= 90 的倍数 + 超快匀速 ⇒ **不是雪花**；"
                 "「自由形状」= travel 五花八门 ⇒ 雪花 / 魔法阵候选")

    if mode == "summary":
        return "\n".join(L)

    # ---------------- camera 模式
    if mode == "camera":
        L.append("")
        L.append("── `MoveCamera` %d 条" % len(cams) + "─" * 60)
        L.append("  %-6s %-10s %-9s %-9s %-10s %s"
                 % ("floor", "时间ms", "拍", "cur", "角色", "参数"))
        for x in cams:
            f = int(x.get("floor") or 0)
            if not (lo <= f <= hi):
                continue
            cur = cur_at_floor(bpms, f)
            L.append("  %-6d %-10.1f %-9.3f %-9s %-10s"
                     % (f, cum[f], cum[f] / ms_per_beat, _num(cur, 1),
                        _cam_role(x)))
            L.append(_cam_line(x, bpms, base).replace("    MoveCamera ", "      · "))
        return "\n".join(L)

    # ---------------- timeline
    L.append("")
    L.append("── 时间轴（格 %d..%d）" % (lo, hi) + "─" * 60)
    L.append("  %-5s %-10s %-9s %-8s %-9s %-7s %-6s %-5s %-4s"
             % ("格", "起始ms", "本格ms", "拍", "cur", "travel", "转角", "Twirl", "键"))
    last_cur = None
    for f in range(max(0, lo), min(n, hi + 1)):
        evs = byfloor.get(f, [])
        ms = msv[f]
        c = bpms[f] if f < len(bpms) else None
        anchor = (last_cur is None or (c is not None and abs(c - last_cur) > 0.5))
        if c is not None:
            last_cur = c
        if not evs and not show_all and not anchor:
            continue
        ang = angles[f] if f < len(angles) else None
        if ang is None or ang == MIDSPIN:
            travel, turn = "中旋", "·"
            tw = "Twirl" if any(e.get("eventType") == "Twirl" for e in evs) else "·"
        else:
            # ★ `parser.angle.py::getRotateAngle()` 给出的就是**每格的 `travel`**
            #   （180 = 直线，90/270 = 直角，与游戏 `CalculateFloorEntryTimes` 同口径）。
            travel = float(ang)
            turn = travel - 180.0
            tw = "Twirl" if any(e.get("eventType") == "Twirl" for e in evs) else "·"
        csz = clusters[f] if f < len(clusters) else 1
        keymark = "·" if csz <= 1 else ("双" if csz == 2 else "%d押" % csz)
        L.append("  %-5d %-10.1f %-9s %-8.3f %-9s %-7s %-6s %-5s %-4s"
                 % (f, cum[f], _num(ms, 2) if ms > 1e-9 else "中旋",
                    cum[f] / ms_per_beat,
                    _num(c, 1) if c else "中旋",
                    _num(travel, 0) if travel != "中旋" else "中旋",
                    _num(turn, 0) if travel != "中旋" else "·",
                    tw, keymark))
        for e in evs:
            if e.get("eventType") == "MoveCamera":
                L.append(_cam_line(e, bpms, base))
            else:
                ln = _other_line(e)
                if ln.strip():
                    L.append(ln)
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chart")
    ap.add_argument("--mode", choices=("timeline", "camera", "summary"),
                    default="timeline")
    ap.add_argument("--from", dest="lo", type=int, default=0)
    ap.add_argument("--to", dest="hi", type=int, default=10 ** 9)
    ap.add_argument("--all", action="store_true", help="每一格都列（默认只列有事件的格）")
    ap.add_argument("--macro", default=MACRO_DIR)
    ap.add_argument("--out", default=None, help="写到文件（默认打到屏幕）")
    args = ap.parse_args(argv)

    text = digest(args.chart, args.mode, args.lo, args.hi, args.all, args.macro)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("→ %s" % args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
