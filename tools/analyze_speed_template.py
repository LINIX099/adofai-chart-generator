# -*- coding: utf-8 -*-
"""**超高速段**的轨道写法 + 镜头写法 → 模板（只读）。

    python tools/analyze_speed_template.py --scan "E:\\...\\adofaipumian"
    python tools/analyze_speed_template.py <谱面.adofai> --fast 40

## 筛选口径（用户 2026-10 定）

> 「先去**遍历所有最大 CUR 在 40 以上、平均 cur 在 20 以上**的谱子，
> 看看他们关于**超高速的 bpm 段落**是使用什么样子的**镜头写法**和**轨道写法**，
> 作为模板来使用」

★ **`cur` 的单位是「格/秒」**（用户口径）。本项目内部 `Floor.bpm` 是 cbpm（格/分钟），
所以 **`cur(格/秒) = cbpm / 60`**。
（判定依据见 `docs/66`：145 份语料里按「格/秒」筛出 9 份，按「×base」只有 1 份、
按 cbpm 几乎全中 —— 只有「格/秒」给出有选择性的子集。）

## 每个超高速段报什么

**轨道写法**：段长 / `cur` / `travel` 组成 / 是否全 90 的倍数 / Twirl 数 /
`SetSpeed` 粒度（几格一个）/ 每格 ms / 是否等间隔。

**镜头写法**：段内（含前后各 4 格的过渡）所有 `MoveCamera` 的
`dur / rel / pos / rot / zoom / ease`，并换算成**覆盖格数**与**覆盖毫秒**
（口径见 `docs/64` §11.2：`覆盖格数 = dur(拍) × cur / base_bpm`）。

输出落 `out/_camera/cur/speed_template.txt`。
"""
from __future__ import annotations

import argparse
import collections
import os
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                              # noqa: BLE001
    pass

from analyze_camera_cur import (                               # noqa: E402
    MACRO_DIR, cover_tiles, floor_bpm, floor_ms, is_cut, is_lock,
    load_angle, move_cameras, segment_kind)

OUT_DIR = os.path.join(_ROOT, "out", "_camera", "cur")
NAMES = ("level.adofai", "main.adofai", "全特效.adofai")

#: 超高速段的判定：`cur`（格/秒）≥ 这个值
FAST_KPS = 40.0
#: 段的合并间隙（格）：≤ 这个距离的两段并成一段
MERGE_GAP = 4
#: 一个段至少要几格才算数
MIN_RUN = 4


def kps(cbpm: float) -> float:
    return float(cbpm) / 60.0


def find_runs(bpms, msv, thr_kps: float, merge_gap: int = MERGE_GAP):
    """找出 `cur ≥ thr` 的**连续区间**（间隙 ≤ `merge_gap` 的合并）。"""
    idx = [i for i in range(len(bpms)) if msv[i] > 1e-9 and kps(bpms[i]) >= thr_kps]
    runs = []
    for i in idx:
        if runs and i - runs[-1][1] <= merge_gap:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [(a, b) for a, b in runs if b - a + 1 >= MIN_RUN]


def profile(a, msv, bpms, cum, angles, lo, hi):
    """一个超高速段的轨道写法。"""
    base = float(a.settings["bpm"])
    floors = list(range(lo, hi + 1))
    tv = [angles[i] for i in floors if i < len(angles)]
    # ★ 只接受合法的 `travel`：中旋是 999、另有极少数解析异常值（实测见过 33300）
    #   —— 它们不是"角度"，混进来会把「全是 90 的倍数」判成真。
    real = [t for t in tv if 1e-9 < t <= 360.0]
    weird = [t for t in tv if not (1e-9 < t <= 360.0) and abs(t - 999.0) > 1e-9]
    cs = [bpms[i] for i in floors]
    # SetSpeed 粒度：段内 bpm 变化了几次
    changes = sum(1 for x, y in zip(cs, cs[1:]) if abs(x - y) > 0.5)
    # 等间隔检查
    gaps = [round(msv[i], 3) for i in floors if msv[i] > 1e-9]
    return dict(
        lo=lo, hi=hi, n=hi - lo + 1,
        ms=cum[hi + 1] - cum[lo],
        cur_lo=min(cs), cur_hi=max(cs),
        kps_lo=kps(min(cs)), kps_hi=kps(max(cs)),
        tv_kinds=len({round(t) for t in real}),
        tv=sorted({round(t) for t in real})[:8],
        all90=bool(real) and all(abs(t % 90.0) < 1e-9 for t in real),
        midspins=sum(1 for t in tv if abs(t - 999.0) < 1e-9),
        weird=len(weird),
        twirls=sum(1 for x in (a.actions or [])
                   if x.get("eventType") == "Twirl" and lo <= int(x.get("floor") or -1) <= hi),
        bpm_changes=changes,
        per_tile_gap=round(changes / max(1, hi - lo), 3),
        gap_kinds=len(set(gaps)),
        even=len(set(gaps)) <= 1,
        base=base,
    )


def cam_lines(cams, msv, bpms, cum, lo, hi, base: float, span: int = 4):
    """段内（含前后 `span` 格过渡）的镜头写法。"""
    out = []
    for x in cams:
        f = int(x.get("floor") or 0)
        if not (lo - span <= f <= hi + span):
            continue
        dur = float(x.get("duration") or 0.0)
        cur = bpms[f] if 0 <= f < len(bpms) else 0.0
        cover = cover_tiles(x, cur, base) if cur else 0.0
        ms = dur * (60000.0 / base) if base else 0.0
        role = ("定基" if is_lock(x) else "硬切") if is_cut(x) else "补间"
        out.append(dict(f=f, t=cum[f] if f < len(cum) else 0.0, role=role,
                        dur=dur, rel=x.get("relativeTo") or "<继承>",
                        pos=x.get("position"), rot=x.get("rotation"),
                        zoom=x.get("zoom"), ang=x.get("angleOffset"),
                        ease=x.get("ease"), tag=x.get("eventTag") or "",
                        cover=cover, ms=ms, cur=cur,
                        phase=("段前" if f < lo else ("段后" if f > hi else "段内"))))
    return out


def analyze_one(path: str, macro_dir: str, thr_kps: float) -> tuple[dict, list[str]]:
    a = load_angle(path, macro_dir)
    msv = floor_ms(a)
    bpms = floor_bpm(a)
    n = len(msv)
    cum = [0.0]
    for x in msv:
        cum.append(cum[-1] + x)
    angles = list(a.originRotateAngleList)
    base = float(a.settings["bpm"])
    cams = move_cameras(a)

    live = [bpms[i] for i in range(n) if msv[i] > 1e-9]
    info = dict(path=path, name=os.path.basename(os.path.dirname(path)) or os.path.basename(path),
                n=n, base=base, total=cum[-1],
                max_kps=kps(max(live)) if live else 0.0,
                mean_kps=kps(statistics.mean(live)) if live else 0.0,
                n_cam=len(cams))

    L: list[str] = []
    L.append("=" * 104)
    L.append("谱面：%s" % info["name"])
    L.append("  %d 格 · base %.1f bpm · %.1f s · MoveCamera %d 条 · "
             "cur max **%.2f** 格/s · mean **%.2f** 格/s"
             % (n, base, cum[-1] / 1000.0, len(cams), info["max_kps"], info["mean_kps"]))
    L.append("=" * 104)

    runs = find_runs(bpms, msv, thr_kps)
    profiles = []
    for lo, hi in runs:
        pr = profile(a, msv, bpms, cum, angles, lo, hi)
        profiles.append(pr)
        L.append("")
        L.append("── 超高速段 %d..%d（%d 格 · %.2f s）"
                 % (lo, hi, pr["n"], pr["ms"] / 1000.0) + "─" * 40)
        L.append("  轨道: cur %.1f→%.1f 格/s　每格 %.2f ms　段内格长种类 %d %s"
                 % (pr["kps_lo"], pr["kps_hi"],
                    pr["ms"] / max(1, pr["n"]), pr["gap_kinds"],
                    "（等间隔）" if pr["even"] else ""))
        L.append("        travel 种类 %d %s　%s　中旋 %d　异常 %d　Twirl %d"
                 % (pr["tv_kinds"], pr["tv"],
                    "★全是 90 的倍数" if pr["all90"] else "（含非 90 倍数）",
                    pr["midspins"], pr["weird"], pr["twirls"]))
        L.append("        SetSpeed 变化 %d 次 ⇒ 平均每 %.2f 格一次"
                 % (pr["bpm_changes"], 1.0 / pr["per_tile_gap"]
                    if pr["per_tile_gap"] else float("inf")))
        cl = cam_lines(cams, msv, bpms, cum, lo, hi, base)
        if not cl:
            L.append("  镜头: **这一段一个 MoveCamera 都没有**（= 不写镜头）")
        else:
            L.append("  镜头: %d 条" % len(cl))
            for c in cl:
                L.append("    %-4s f%-6d dur=%-7g %-4s rel=%-14s pos=%-14s rot=%-7s "
                         "zoom=%-6s ang=%-6s %-11s 跨%6.2f格 / %7.0fms  cur=%.1f"
                         % (c["phase"], c["f"], c["dur"], c["role"], c["rel"],
                            "[" + ",".join("·" if v is None else "%g" % v
                                           for v in c["pos"]) + "]"
                            if isinstance(c["pos"], list) else str(c["pos"]),
                            c["rot"], c["zoom"], c["ang"], c["ease"],
                            c["cover"], c["ms"], kps(c["cur"])))
    return dict(info=info, profiles=profiles, cams=cams, msv=msv, bpms=bpms,
                cum=cum, base=base), L


def scan(root: str, macro_dir: str, thr_kps: float,
         min_mean_kps: float) -> list[str]:
    found = []
    for dp, _d, fs in os.walk(root):
        for w in NAMES:
            if w in fs:
                p = os.path.join(dp, w)
                if "backup" not in p.lower():
                    found.append(p)
                break
    found.sort()

    L = ["=" * 104,
         "【超高速模板扫描】%s" % root,
         "  判据：cur（格/秒）max ≥ %g 且 mean ≥ %g" % (thr_kps, min_mean_kps),
         "  找到 %d 份谱面" % len(found),
         "=" * 104]

    hit = []
    seen = set()
    for p in found:
        try:
            d, _ = analyze_one(p, macro_dir, thr_kps)
        except Exception as exc:                               # noqa: BLE001
            continue
        if d["info"]["max_kps"] >= thr_kps and d["info"]["mean_kps"] >= min_mean_kps:
            # ★ 去重：同一份谱常在不同文件夹里各存一份（内容一致 ⇒ 统计会翻倍）
            key = (d["info"]["n"], round(d["info"]["max_kps"], 2),
                   round(d["info"]["mean_kps"], 2), d["info"]["n_cam"])
            if key in seen:
                continue
            seen.add(key)
            hit.append((p, d))
    hit.sort(key=lambda x: -x[1]["info"]["max_kps"])

    L.append("")
    L.append("【命中 %d 份】" % len(hit))
    L.append("  %-30s %-8s %-10s %-10s %-8s %s"
             % ("谱", "格数", "max 格/s", "mean 格/s", "MMC", "超高速段数"))
    for _p, d in hit:
        L.append("  %-30s %-8d %-10.2f %-10.2f %-8d %d"
                 % (d["info"]["name"][:30], d["info"]["n"], d["info"]["max_kps"],
                    d["info"]["mean_kps"], d["info"]["n_cam"],
                    len(d["profiles"])))

    # ---- 聚合
    tv_all: collections.Counter = collections.Counter()
    tw = 0
    mid = 0
    n90 = 0
    nseg = 0
    even = 0
    cam_roles: collections.Counter = collections.Counter()
    cam_ease: collections.Counter = collections.Counter()
    cam_rel: collections.Counter = collections.Counter()
    cam_dur: list[float] = []
    cam_cover: list[float] = []
    cam_zoom: list[float] = []
    cam_pos: collections.Counter = collections.Counter()
    cam_cnt_in = 0
    seg_with_cam = 0
    for _p, d in hit:
        for pr in d["profiles"]:
            nseg += 1
            tv_all[pr["tv_kinds"]] += 1
            tw += pr["twirls"]
            mid += pr["midspins"]
            n90 += 1 if pr["all90"] else 0
            even += 1 if pr["even"] else 0
            lo, hi = pr["lo"], pr["hi"]
            cl = cam_lines(d["cams"], d["msv"], d["bpms"], d["cum"], lo, hi, d["base"])
            if cl:
                seg_with_cam += 1
            for c in cl:
                cam_roles[c["role"]] += 1
                if c["phase"] == "段内":
                    cam_cnt_in += 1
                    cam_ease[str(c["ease"])] += 1
                    cam_rel[str(c["rel"])] += 1
                    cam_dur.append(c["dur"])
                    cam_cover.append(c["cover"])
                    if c["zoom"] is not None:
                        cam_zoom.append(float(c["zoom"]))
                    pos = c["pos"]
                    if isinstance(pos, list):
                        cam_pos["[" + ",".join(
                            "·" if v is None else ("0" if abs(float(v)) < 1e-9 else "≠0")
                            for v in pos) + "]"] += 1

    L.append("")
    L.append("─" * 104)
    L.append("【模板 A · 轨道写法】（%d 个超高速段）" % nseg)
    L.append("  · 段内每格 ms 只有 1 种（**严格等间隔**）：**%d / %d** = %.0f%%"
             % (even, nseg, even * 100.0 / max(1, nseg)))
    L.append("  · `travel` 全是 90 的倍数：**%d / %d** = %.0f%%"
             % (n90, nseg, n90 * 100.0 / max(1, nseg)))
    L.append("  · `travel` 种类数分布（种类:段数）：%s"
             % ", ".join("%d:%d" % kv for kv in sorted(tv_all.items())))
    L.append("  · 中旋格合计 %d　Twirl 合计 %d（平均每段 %.1f 个）"
             % (mid, tw, tw / max(1, nseg)))
    with_cam = [d for _p, d in hit if d["info"]["n_cam"] > 0]
    L.append("  · ★ **命中的 %d 份里只有 %d 份有镜头事件**；"
             "%d 份 `MoveCamera` 数量为 **0**（整个谱面都没有镜头）"
             % (len(hit), len(with_cam), len(hit) - len(with_cam)))
    L.append("")
    L.append("【模板 B · 镜头写法】（段内 %d 条 MoveCamera；有镜头的段 %d / %d）"
             % (cam_cnt_in, seg_with_cam, nseg))
    if cam_cnt_in:
        L.append("  · 角色：%s" % ", ".join("%s×%d" % kv
                                           for kv in cam_roles.most_common()))
        L.append("  · `ease`（前 6）：%s"
                 % ", ".join("%s×%d" % kv for kv in cam_ease.most_common(6)))
        L.append("  · `relativeTo`：%s"
                 % ", ".join("%s×%d" % kv for kv in cam_rel.most_common(6)))
        L.append("  · `duration`（拍）：中位 %.2f　最小 %.2f　最大 %.2f"
                 % (statistics.median(cam_dur), min(cam_dur), max(cam_dur)))
        L.append("  · **覆盖格数**：中位 %.1f　最小 %.1f　最大 %.1f"
                 % (statistics.median(cam_cover), min(cam_cover), max(cam_cover)))
        if cam_zoom:
            L.append("  · `zoom`：中位 %.0f　范围 %.0f~%.0f（%d 条给了 zoom）"
                     % (statistics.median(cam_zoom), min(cam_zoom), max(cam_zoom),
                        len(cam_zoom)))
        L.append("  · `position` 形态（x,y 是否归零）：%s"
                 % ", ".join("%s×%d" % kv for kv in cam_pos.most_common(6)))
    else:
        L.append("  · **这些超高速段里一条镜头事件都没有**")

    L.append("")
    L.append("─" * 104)
    L.append("【模板 B2 · 超高速段里的镜头事件逐条】（这是真正要抄的那张表）")
    L.append("  %-22s %-4s %-5s %-6s %-4s %-14s %-16s %-8s %-7s %-7s %-10s %s"
             % ("谱", "阶段", "floor", "kps", "角色", "rel", "pos", "rot",
                "zoom", "dur", "ease", "跨格"))
    n_listed = 0
    for _p, d in hit:
        if d["info"]["n_cam"] == 0:
            continue
        for pr in d["profiles"]:
            for c in cam_lines(d["cams"], d["msv"], d["bpms"], d["cum"],
                               pr["lo"], pr["hi"], d["base"]):
                if c["phase"] != "段内":
                    continue
                n_listed += 1
                L.append("  %-22s %-4s %-5d %-6.1f %-4s %-14s %-16s %-8s %-7s %-7g %-10s %.1f"
                         % (d["info"]["name"][:22], c["phase"], c["f"], kps(c["cur"]),
                            c["role"], c["rel"],
                            "[" + ",".join("·" if v is None else "%g" % v
                                           for v in c["pos"]) + "]"
                            if isinstance(c["pos"], list) else str(c["pos"]),
                            c["rot"], c["zoom"], c["dur"], c["ease"], c["cover"]))
    if not n_listed:
        L.append("  （一个都没列出来）")

    L.append("")
    L.append("─" * 104)
    L.append("【逐谱明细】")
    for p, d in hit:
        _, lines = analyze_one(p, macro_dir, thr_kps)
        L.extend(lines)
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("charts", nargs="*")
    ap.add_argument("--scan", metavar="DIR")
    ap.add_argument("--fast", type=float, default=FAST_KPS,
                    help="超高速阈值（格/秒），默认 40")
    ap.add_argument("--min-mean", type=float, default=20.0,
                    help="平均 cur 下限（格/秒），默认 20")
    ap.add_argument("--macro", default=MACRO_DIR)
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "speed_template.txt"))
    args = ap.parse_args(argv)

    if args.scan:
        lines = scan(args.scan, args.macro, args.fast, args.min_mean)
    else:
        lines = []
        for p in args.charts:
            _, L = analyze_one(p, args.macro, args.fast)
            lines.extend(L)
    text = "\n".join(lines)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("→ %s（%d 行）" % (args.out, len(lines)))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
