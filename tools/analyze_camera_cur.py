# -*- coding: utf-8 -*-
"""**段落 `cur` 速度 ↔ 镜头** 的关系分析（只读）。

    python tools/analyze_camera_cur.py <谱面.adofai> [--bin 400] [--top 12]
    python tools/analyze_camera_cur.py --suite          # 跑内置的一组谱

## 为什么单开一个工具

`docs/64` §9.2 的**按 `cur` 分派**（高 cur 走缓慢补间 / 低 cur 走一拍一振硬切）
以前只有"用户口径"作依据，**没有实测**。这个工具就是去实测：

> 用户 2026-10：「你可以拿去自己检查**谱子的段落 cur 速度和镜头关系**」

## 时序从哪来（★ 不自己复刻）

用 **`Adofai-Macro-Adofai_Macro_V5.0/parser`** —— 它的 `angle.py` 是照着游戏
`scrLevelMaker.CalculateFloorEntryTimes` 复刻的（按**角度**推进，正确处理
`SetSpeed{ Bpm / Multiplier }`、`angleOffset`、`Pause`、midspin/autoplay 的剔除）。

本工具只用它两样东西：

* `ADOAngle._buildSpeedSegments()` —— **BPM 分段模型**（`[(起角度, 止角度, bpm)]`）；
* `ADOAngle.getRotateAngle()` —— **每格的角度行程**（`originRotateAngleList`）。

每格毫秒数就是这两者的 6 行合并（见 `_floor_ms`）—— 和 `getAbsBeatList()` 里
的内层循环逐字一致，只是为了**保留原始 floor 下标**（那边的结果会剔掉 midspin，
下标就不再是 floor 了，没法跟 `MoveCamera.floor` 对齐）。

## `cur` 的口径

本项目 `cur` = **`cbpm` = 每分钟走几格** = `60000 / 每格毫秒数`
（与 `Floor.bpm` 同口径，见 `docs/64` §9.2）。默认分箱阈值 `--bin 400`
（= `SolveParams.ladder_outer_cbpm` = `CameraParams.cur_split`）。

## 输出

`out/_camera/cur/<谱名>.txt` + 屏幕摘要。**只读，不改任何谱面。**
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

#: 第三方解析器（用户 2026-10 指定的宏工具）。可用 `--macro` 或环境变量覆盖。
MACRO_DIR = os.environ.get(
    "ADOFAI_MACRO_DIR",
    os.environ.get("ADOFAI_MACRO", ""))

OUT_DIR = os.path.join(_ROOT, "out", "_camera", "cur")

#: 内置一组对照谱：Tempest 的两朵雪花 + 我们自己的验收谱
SUITE = (
    os.path.join(_ROOT, "out", "_camera", "tempest", "level.adofai"),
    os.path.join(_ROOT, "out", "运镜验收谱v2", "main.adofai"),
    os.path.join(_ROOT, "out", "_camera", "tut.adofai"),
)

#: `cur` 分箱的**上界**（cbpm）。最后一箱是 +∞。
BINS = (200.0, 400.0, 800.0)

EASE_FAMILY = (
    ("linear", ("Linear",)),
    ("sine/quad", ("OutSine", "InSine", "InOutSine", "OutQuad", "InQuad",
                   "InOutQuad")),
    ("cubic/quart", ("OutCubic", "InCubic", "InOutCubic", "OutQuart", "InQuart",
                     "InOutQuart", "OutExpo", "InExpo", "InOutExpo")),
    ("circ", ("OutCirc", "InCirc", "InOutCirc")),
    ("back", ("OutBack", "InBack", "InOutBack")),
    ("elastic/bounce", ("OutElastic", "InElastic", "InOutElastic",
                        "OutBounce", "InBounce", "InOutBounce")),
    ("flash", ("OutFlash", "InFlash", "InOutFlash")),
)


def ease_family(e: str) -> str:
    for name, members in EASE_FAMILY:
        if e in members:
            return name
    return "其他"


# ---------------------------------------------------------------- 时序
def load_angle(path: str, macro_dir: str = MACRO_DIR):
    """返回第三方解析器的 `ADOAngle`（路径不存在时抛 `SystemExit`）。"""
    if not os.path.isdir(macro_dir):
        raise SystemExit(
            "找不到宏解析器目录：%s\n  用 --macro 或 ADOFAI_MACRO_DIR 指过去"
            % macro_dir)
    if macro_dir not in sys.path:
        sys.path.insert(0, macro_dir)
    from parser.reader import ADOLevelData        # noqa: PLC0415
    from parser.angle import ADOAngle             # noqa: PLC0415

    ald = ADOLevelData.new(path)
    ald.decode()
    return ADOAngle(ald)


def floor_ms(a) -> list[float]:
    """每一格的**毫秒数**（与 `parser/angle.py::getAbsBeatList` 同模型）。

    只用解析器的 `originRotateAngleList`（角度行程）+ `_buildSpeedSegments()`
    （BPM 分段），逐格算「这一格跨了多少角度 × 该段的每角度毫秒」。
    ★ 这里**不复刻**任何速度规则本身 —— `Bpm` / `Multiplier` / `angleOffset`
      全在 `_buildSpeedSegments()` 里，那是解析器验过的部分。
    """
    a.getRotateAngle()
    base = float(a.settings["bpm"])
    segs = a._buildSpeedSegments(base)                       # noqa: SLF001
    angles = a.originRotateAngleList

    cum = [0.0]
    for ang in angles:
        cum.append(cum[-1] + (0.0 if ang == 999 else ang))

    ms_per_beat_at_base = 60000.0 / base
    out: list[float] = []
    for i in range(len(angles)):
        if angles[i] == 999:
            out.append(0.0)                                  # midspin：没有按键
            continue
        t0, t1 = cum[i], cum[i + 1]
        beats = 0.0
        for s0, s1, seg_bpm in segs:
            ov = min(s1, t1) - max(s0, t0)
            if ov > 0 and seg_bpm > 0:
                beats += ov / 180.0 * (base / seg_bpm)
        out.append(beats * ms_per_beat_at_base)
    return out


def cur_of(ms: float) -> float:
    """`cur` = cbpm = 每分钟格数。`ms` 是这一格的毫秒数。"""
    return 60000.0 / ms if ms > 1e-9 else float("inf")


# ---------------------------------------------------------------- 镜头
def move_cameras(a) -> list[dict]:
    """从**解析器**取 `MoveCamera`。

    ★ 不能用 `json.load`：语料里有不少谱面带尾随逗号 / 非严格 JSON，
      解析器的 `ADOLevelData.decode()` 已经容错了，所以走它。
    """
    return [x for x in (a.actions or [])
            if x.get("eventType") == "MoveCamera"]


#: 双押 / 三押的判定窗口：**40ms 内按下的 2~3 个键**（用户 2026-10 口径）。
PRESS_CLUSTER_MS = 40.0


def press_clusters(msv: list[float], tol: float = PRESS_CLUSTER_MS) -> list[int]:
    """每个 floor 属于一个多大的「按键簇」。

    ★★ 用户 2026-10：「有时你可以发现在**短短的 40ms 内有 2~3 个键被按下**，
    搭配角度时，它们构成**双押或三押**」。

    实现：按**实际按键时刻**（格起点时间）扫一遍，把相邻间隔 ≤ `tol` 的格并成一组。
    返回值里，同一簇的每一格都是簇的大小（1 = 普通单键）。
    例：`[1,1,2,2,1,3,3,3]` = 两格双押、一格三押。

    ★ 为什么必须知道这个：双押会让「相邻事件的间隔（拍）」**凭空减半**，
      也会让"每格一振"这类判据失真 —— Tempest 有 **26.4%** 的格是双押，
      教学谱只有 **1.4%**。
    """
    n = len(msv)
    if n == 0:
        return []
    cum = [0.0]
    for x in msv:
        cum.append(cum[-1] + x)
    out = [1] * n
    # ★ 第 0 格是**站位格**（不是按键），`msv == 0` 的是中旋/瞬时格 —— 都不算按键。
    idx = [i for i in range(1, n) if msv[i] > 1e-9]
    k = 0
    while k < len(idx):
        j = k
        # 相邻两键的间隔 = `msv[第 j 键]`
        while (j + 1 < len(idx)
               and msv[idx[j]] <= tol + 1e-9):
            j += 1
        size = j - k + 1
        if size >= 2:
            for m in range(k, j + 1):
                out[idx[m]] = size
        k = j + 1
    return out


def segment_kind(lo: int, hi: int, travels: list[float],
                 bpms: list[float], base_bpm: float) -> str:
    """把一个 `cur` 段分类（用户 2026-10 提醒的两个干扰项）。

    | 类别 | 判据 | 含义 |
    |---|---|---|
    | **采bpm** | `cur ≥ 2×base` **且** travel 全是 90 的倍数（无中旋）**且** ≥8 格 | 「在角度为 90 的倍数下匀速以超快速度运行」的**采音段** —— **不是雪花** |
    | **自由形状** | travel 的**种类 ≥ 4** 且 ≥8 格 | 形状自由的段落（雪花 / 魔法阵候选） |
    | **常规** | 其余 | |
    """
    n = hi - lo + 1
    tv = [travels[i] for i in range(lo, hi + 1)] if hi < len(travels) else []
    if not tv:
        return "常规"
    has_mid = any(abs(t - 999.0) < 1e-9 for t in tv)
    real = [t for t in tv if abs(t - 999.0) > 1e-9]
    only90 = bool(real) and all(abs(t % 90.0) < 1e-9 for t in real)
    fast = lo < len(bpms) and float(bpms[lo]) >= 2.0 * float(base_bpm)
    if fast and only90 and not has_mid and n >= 8:
        return "采bpm"
    if len({round(t) for t in tv}) >= 4 and n >= 8:
        return "自由形状"
    return "常规"


def windowed_kinds(bpms: list[float], angles: list[float], base: float,
                   win: int = 32) -> list[tuple[int, int, str]]:
    """滑窗分类后**合并相邻同类**，返回 `[(lo, hi, 类别)]`。

    为什么要滑窗：雪花段的 `SetSpeed` 是**逐格**的，按"bpm 相同的连续格"切分会被切成
    一堆 1~3 格的碎片，看不出整体形状。滑窗看的是**纹理**：这一段的角度是
    「只有 90 的倍数」还是「五花八门」。
    """
    n = len(bpms)
    if n == 0:
        return []
    tags: list[str] = []
    for lo in range(n):
        hi = min(n - 1, lo + win - 1)
        tags.append(segment_kind(lo, hi, angles, bpms, base))
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and tags[j + 1] == tags[i]:
            j += 1
        if j - i + 1 >= win // 2 and tags[i] != "常规":
            out.append((i, j, tags[i]))
        i = j + 1
    return out


def floor_bpm(a) -> list[float]:
    """每一格**生效的 SetSpeed bpm** —— 这才是本项目的 `cur`（cbpm）。

    ★★ 为什么不能拿 `60000 / 每格ms` 当 `cur`：

    一格的时间是 `travel/180 × (base/该段bpm)` —— **正比于这一格走了多少角度**。
    所以 270° 的拐角格时间天然是直线格的 1.5 倍，`60000/ms` 会把它读成"变慢了"，
    而实际上 SetSpeed 根本没变。本项目的 `Floor.bpm` 是那个 **bpm 值**，不是格的速率。

    ⇒ 这里直接取 `_buildSpeedSegments()` 的分段，按**格的中位角度**落到哪一段。
    """
    a.getRotateAngle()
    base = float(a.settings["bpm"])
    segs = a._buildSpeedSegments(base)                       # noqa: SLF001
    angles = a.originRotateAngleList
    cum = [0.0]
    for ang in angles:
        cum.append(cum[-1] + (0.0 if ang == 999 else ang))
    out: list[float] = []
    for i in range(len(angles)):
        mid = (cum[i] + cum[i + 1]) / 2.0
        b = base
        for s0, s1, sb in segs:
            if s0 <= mid < s1:
                b = sb
                break
        else:
            if segs:
                b = segs[-1][2]
        out.append(float(b))
    return out


def cur_at_floor(bpms: list[float], f: int) -> float:
    """某个 floor 上的 `cur`（= 该格生效的 SetSpeed bpm）。

    ★ **midspin（`angleData == 999`）那一格没有自己的角度**，时间算在**下一格**上；
      autoplay / 越界的格同理。这里往前/往后找一个正常的格代表它。
    """
    if not bpms:
        return float("nan")
    if 0 <= f < len(bpms):
        return float(bpms[f])
    for g in range(f + 1, min(len(bpms), f + 8)):
        return float(bpms[g])
    for g in range(min(f, len(bpms) - 1), max(-1, f - 8), -1):
        return float(bpms[g])
    return float("nan")


def ms_at_floor(msv: list[float], f: int) -> float:
    """某一格的毫秒数（midspin 为 0，往前/往后找一个正常的格）。"""
    if not msv:
        return 0.0
    if 0 <= f < len(msv) and msv[f] > 1e-9:
        return msv[f]
    for g in range(f + 1, min(len(msv), f + 8)):
        if msv[g] > 1e-9:
            return msv[g]
    for g in range(min(f, len(msv) - 1), max(-1, f - 8), -1):
        if msv[g] > 1e-9:
            return msv[g]
    return 0.0


def cover_tiles(a: dict, cur: float, base_bpm: float) -> float:
    """这条补间**跨了多少格**。

    `duration` 的单位是**拍**（拍长 = `60000 / base_bpm` 毫秒，与 `SetSpeed` 无关）；
    该段的每格 = `ms` 毫秒 ⇒ 每格拍数 = `ms / (60000/base_bpm)` = `base_bpm / cur`。
    所以

        覆盖格数 = duration ÷ 每格拍数 = duration × cur / base_bpm

    ★ 这是本工具里最有信息量的一个量：它把「时值」和「cur」合起来看。
      如果各 cur 档的**覆盖格数**都差不多，说明作者的真实规则是
      「**每 N 格动一下**」，而不是「按 cur 分档」—— 时值只是被 cur 除出来的。
    """
    cur = float(cur)
    if not (cur > 0) or cur == float("inf") or base_bpm <= 0:
        return 0.0
    return float(a.get("duration") or 0.0) * cur / base_bpm


def is_cut(a: dict) -> bool:
    """硬切：`duration=0`。定基（完整复位）与硬切都算 —— 都是"瞬时换姿态"。"""
    return float(a.get("duration") or 0.0) <= 0.0


def is_lock(a: dict) -> bool:
    """完整复位型定基（`Player` + `[0,0]` + 无 tag）—— 跟"硬切"分开数。"""
    return (is_cut(a) and a.get("relativeTo") == "Player"
            and a.get("position") == [0, 0] and not a.get("eventTag"))


def pos_moved(a: dict) -> bool:
    p = a.get("position")
    return p not in (None, [None, None]) and p != [0, 0]


# ---------------------------------------------------------------- 统计
def bucket_of(cur: float, split: float) -> str:
    lo = 0.0
    for hi in (split / 2.0, split, split * 2.0):
        if cur < hi:
            return f"{lo:g}~{hi:g}"
        lo = hi
    return f"≥{lo:g}"


def analyze(path: str, split: float, top: int,
            macro_dir: str = MACRO_DIR) -> tuple[str, list[str]]:
    a = load_angle(path, macro_dir)
    msv = floor_ms(a)
    cams = move_cameras(a)
    total = len(a.angleData)

    # ---- cur 分段（把等速的连续格合成"段"）
    segs: list[dict] = []
    for i, ms in enumerate(msv):
        c = cur_of(ms)
        if segs and abs(segs[-1]["cur"] - c) < 0.5:
            segs[-1]["hi"] = i
            segs[-1]["n"] += 1
        else:
            segs.append(dict(lo=i, hi=i, n=1, cur=c))
    segs = [s for s in segs if s["n"] >= 2]

    base_bpm = float(a.settings["bpm"])
    bpms = floor_bpm(a)
    by_bin: dict[str, list[dict]] = {}
    for cam in cams:
        f = int(cam.get("floor") or 0)
        by_bin.setdefault(bucket_of(cur_at_floor(bpms, f), split), []).append(cam)

    L: list[str] = []
    L.append("=" * 96)
    L.append("谱面：%s" % os.path.basename(path))
    L.append("  总格数 %d　基础 bpm %s　时长 %.1f s　MoveCamera %d 条"
             % (total, a.settings.get("bpm"), sum(msv) / 1000.0, len(cams)))
    L.append("  `cur` = cbpm = 60000 / 每格ms　分箱阈值 = %g" % split)
    L.append("=" * 96)

    # ---- 1. cur 段表（只打前 top 长的）
    L.append("")
    L.append("【1】`cur` 分段（只列 ≥2 格的段，按长度前 %d）" % top)
    L.append("  %-14s %-6s %-10s %-10s %s" % ("格区间", "格数", "cur(cbpm)", "每格ms", "拍/格"))
    for s in sorted(segs, key=lambda x: -x["n"])[:top]:
        beat = (msv[s["lo"]] or 0.0) / (60000.0 / float(a.settings["bpm"]))
        L.append("  %-14s %-6d %-10.1f %-10.2f %.3f"
                 % ("%d..%d" % (s["lo"], s["hi"]), s["n"], s["cur"],
                    msv[s["lo"]], beat))

    # ---- 2. 镜头按 cur 分箱
    L.append("")
    L.append("【2】`MoveCamera` 按所在格的 `cur` 分箱")
    L.append("  %-12s %-6s %-8s %-8s %-9s %-9s %s"
             % ("cur 箱", "条数", "硬切%", "其中定基", "平均dur", "中位dur", "ease 家族（前 3）"))
    for b in sorted(by_bin, key=lambda k: (k == "≥800", k)):
        rows = by_bin[b]
        n = len(rows)
        cuts = [r for r in rows if is_cut(r)]
        locks = [r for r in cuts if is_lock(r)]
        perf = [r for r in rows if not is_cut(r)]
        durs = [float(r["duration"]) for r in perf]
        fam: dict[str, int] = {}
        for r in perf:
            fam[ease_family(str(r.get("ease")))] = fam.get(ease_family(
                str(r.get("ease"))), 0) + 1
        topfam = sorted(fam.items(), key=lambda kv: -kv[1])[:3]
        L.append("  %-12s %-6d %-8s %-8d %-9s %-9s %s"
                 % (b, n, "%.0f%%" % (len(cuts) * 100.0 / n),
                    len(locks),
                    "%.2f" % (statistics.mean(durs) if durs else 0.0),
                    "%.2f" % (statistics.median(durs) if durs else 0.0),
                    ", ".join("%s×%d" % kv for kv in topfam) or "—"))
        if durs:
            hist: dict[float, int] = {}
            for d in durs:
                hist[round(d, 2)] = hist.get(round(d, 2), 0) + 1
            L.append("       └ 补间时值（拍:次数）%s"
                     % ", ".join("%.2f:%d" % kv
                                 for kv in sorted(hist.items(),
                                                  key=lambda kv: -kv[1])[:8]))
            cov = [cover_tiles(r, cur_at_floor(bpms, int(r.get("floor") or 0)),
                               base_bpm)
                   for r in perf]
            hist2: dict[float, int] = {}
            for cv in cov:
                hist2[round(cv, 1)] = hist2.get(round(cv, 1), 0) + 1
            L.append("       └ **覆盖格数**（格:次数）中位 %.2f　众数 %s"
                     % (statistics.median(cov),
                        ", ".join("%.1f:%d" % kv
                                  for kv in sorted(hist2.items(),
                                                   key=lambda kv: -kv[1])[:6])))

    # ---- 3. 慢 / 快两档的对照
    slow = [r for r in cams if cur_of(msv[int(r.get("floor") or 0)]) < split]
    fast = [r for r in cams if cur_of(msv[int(r.get("floor") or 0)]) >= split]
    L.append("")
    L.append("【3】低 cur（< %g） vs 高 cur（≥ %g）" % (split, split))

    def line(name: str, rows: list[dict]) -> str:
        if not rows:
            return "  %-10s （没有事件）" % name
        cuts = [r for r in rows if is_cut(r)]
        hard = [r for r in cuts if not is_lock(r)]
        durs = [float(r["duration"]) for r in rows if not is_cut(r)]
        return ("  %-10s n=%-4d 硬切 %-3d（定基 %-3d / 表演硬切 %-3d）"
                "　平均dur %-6s　zoom 用 %-3d　pos 动 %-3d"
                % (name, len(rows), len(cuts),
                   len([r for r in cuts if is_lock(r)]), len(hard),
                   ("%.2f" % statistics.mean(durs)) if durs else "—",
                   len([r for r in rows if r.get("zoom") is not None]),
                   len([r for r in rows if pos_moved(r)])))

    L.append(line("低 cur", slow))
    L.append(line("高 cur", fast))

    # ---- 4. 硬切之间的间隔（「一拍一振」的指纹）
    L.append("")
    L.append("【4】`duration=0` 事件的间隔（**拍**，按该段 `cur` 换算）")
    ms_per_beat = 60000.0 / float(a.settings["bpm"])

    def _gaps(rows: list[dict]) -> list[float]:
        rows = sorted(rows, key=lambda r: int(r.get("floor") or 0))
        out = []
        for x, y in zip(rows, rows[1:]):
            f0, f1 = int(x["floor"]), int(y["floor"])
            if not (0 <= f0 < f1 <= len(msv)):
                continue
            out.append(sum(msv[f0:f1]) / ms_per_beat)
        return out

    all0 = [r for r in cams if is_cut(r)]
    hard = [r for r in all0 if not is_lock(r)]
    for tag, rows in (("全部 duration=0（含定基）", all0),
                      ("只看表演型硬切（不含定基）", hard)):
        g = _gaps(rows)
        if len(g) < 2:
            L.append("  %-24s 只有 %d 条，看不出间隔" % (tag, len(rows)))
            continue
        cnt: dict[float, int] = {}
        for v in g:
            cnt[round(v, 2)] = cnt.get(round(v, 2), 0) + 1
        L.append("  %-24s n=%-4d 中位 %-7.3f 拍　最小 %-7.3f"
                 % (tag, len(rows), statistics.median(g), min(g)))
        L.append("     间隔分布（拍:次数）：%s"
                 % ", ".join("%.2f:%d" % kv
                             for kv in sorted(cnt.items(), key=lambda kv: -kv[1])[:8]))
    L.append("  ★ 判据：「**一拍一振**」⇒ 「全部 duration=0」的中位间隔 ≈ **1.000 拍**"
             "（每拍换一次姿态）；只看硬切会得到 ≈ 2.000 拍，那是「出」的间隔，"
             "不是「振」的间隔。")

    # ---- 5. 每条事件的明细（截断）
    L.append("")
    L.append("【5】MoveCamera 明细（前 %d 条）" % top)
    L.append("  %-6s %-9s %-7s %-8s %-18s %-8s %-8s %s"
             % ("floor", "cur", "dur", "rel", "position", "rot", "zoom", "ease"))
    for r in cams[:top]:
        f = int(r.get("floor") or 0)
        L.append("  %-6d %-9.1f %-7g %-8s %-18s %-8s %-8s %s"
                 % (f, cur_at_floor(bpms, f), float(r.get("duration") or 0.0),
                    r.get("relativeTo", "-"), str(r.get("position")),
                    str(r.get("rotation")), str(r.get("zoom")), r.get("ease")))

    return os.path.splitext(os.path.basename(path))[0], L


def _brief(path: str, split: float, macro_dir: str) -> dict | None:
    """轻量版：只算「按 cur 分箱的镜头形状」，供 `--scan` 批量聚合。"""
    try:
        a = load_angle(path, macro_dir)
        msv = floor_ms(a)
    except Exception as exc:                                   # noqa: BLE001
        return dict(path=path, err="%s: %s" % (type(exc).__name__, exc))
    cams = move_cameras(a)
    if not cams:
        return dict(path=path, err="没有 MoveCamera")
    ms_per_beat = 60000.0 / float(a.settings["bpm"])
    base_bpm = float(a.settings["bpm"])
    bpms = floor_bpm(a)
    clusters = press_clusters(msv)
    n_dbl = sum(1 for c in clusters if c >= 2)
    n_tri = sum(1 for c in clusters if c >= 3)
    kinds = windowed_kinds(bpms, a.originRotateAngleList, base_bpm)
    bins: dict[str, dict] = {}
    for cam in cams:
        f = int(cam.get("floor") or 0)
        c = cur_at_floor(bpms, f)
        b = bins.setdefault(bucket_of(c, split),
                            dict(n=0, cuts=0, locks=0, hard=0, durs=[], covers=[]))
        b["n"] += 1
        if is_cut(cam):
            b["cuts"] += 1
            b["locks" if is_lock(cam) else "hard"] += 1
        else:
            b["durs"].append(float(cam["duration"]))
            b["covers"].append(cover_tiles(cam, c, base_bpm))
    z = [m for m in cams if is_cut(m)]
    gaps: list[float] = []
    z.sort(key=lambda r: int(r.get("floor") or 0))
    for x, y in zip(z, z[1:]):
        f0, f1 = int(x["floor"]), int(y["floor"])
        if 0 <= f0 < f1 <= len(msv):
            gaps.append(sum(msv[f0:f1]) / ms_per_beat)
    return dict(path=path, n_floors=len(a.angleData), n_cam=len(cams),
                bpm=float(a.settings["bpm"]), bins=bins, gaps=gaps, err=None,
                n_dbl=n_dbl, n_tri=n_tri,
                kinds=[(x[0], x[1], x[2]) for x in kinds])


def _scan(root: str, limit: int, split: float, macro_dir: str) -> list[str]:
    names = ("level.adofai", "main.adofai", "全特效.adofai")
    found: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for want in names:
            if want in files:
                p = os.path.join(dirpath, want)
                if "backup" not in p.lower():
                    found.append(p)
                break
        if limit and len(found) >= limit:
            break
    found.sort()

    agg: dict[str, dict] = {}
    ok = 0
    tot_floors = tot_cam_floors = tot_dbl = tot_tri = 0
    kind_charts: dict[str, int] = {}
    errs: list[tuple[str, str]] = []
    nocam: list[str] = []
    for p in found:
        r = _brief(p, split, macro_dir)
        if r is None or r.get("err"):
            msg = (r or {}).get("err", "?")
            if msg == "没有 MoveCamera":
                nocam.append(p)
            else:
                errs.append((p, msg))
            continue
        ok += 1
        tot_floors += r["n_floors"]
        tot_cam_floors += r.get("n_dbl") or 0
        tot_dbl += r.get("n_dbl") or 0
        tot_tri += r.get("n_tri") or 0
        for _lo, _hi, kk in (r.get("kinds") or []):
            if kk != "常规":
                kind_charts[kk] = kind_charts.get(kk, 0) + 1
        for b, v in r["bins"].items():
            A = agg.setdefault(b, dict(n=0, cuts=0, locks=0, hard=0, durs=[],
                                       covers=[], gaps=[], charts=0))
            A["n"] += v["n"]
            A["cuts"] += v["cuts"]
            A["locks"] += v["locks"]
            A["hard"] += v["hard"]
            A["durs"].extend(v["durs"])
            A["covers"].extend(v.get("covers") or [])
            A["gaps"].extend(r["gaps"])
            A["charts"] += 1

    L = ["=" * 96,
         "【批量扫描】%s" % root,
         "  找到 %d 份谱面　有镜头 %d　无镜头 %d　解析失败 %d　分箱阈值 %g"
         % (len(found), ok, len(nocam), len(errs), split),
         "  总格数 %d　双押/三押簇覆盖 %d 格（%.1f%%）"
         "　其中含三押的 %d 格"
         % (tot_floors, tot_dbl, tot_dbl * 100.0 / max(1, tot_floors), tot_tri),
         "  滑窗分类命中：%s" % ("、".join("%s %d 段" % kv
                                          for kv in sorted(kind_charts.items(),
                                                           key=lambda kv: -kv[1]))
                                 or "无"),
         "=" * 96]

    def key(b: str) -> float:
        return float("inf") if b.startswith("≥") else float(b.split("~")[1])

    L.append("")
    L.append("  %-12s %-8s %-8s %-9s %-9s %-9s %-10s %s"
             % ("cur 箱", "事件数", "硬切率", "其中定基", "表演硬切",
                "中位dur", "中位覆盖格", "硬切间隔中位"))
    for b in sorted(agg, key=key):
        A = agg[b]
        durs = A["durs"]
        gaps = A["gaps"]
        cov = A["covers"]
        L.append("  %-12s %-8d %-8s %-9d %-9d %-9s %-10s %s"
                 % (b, A["n"], "%.1f%%" % (A["cuts"] * 100.0 / A["n"]),
                    A["locks"], A["hard"],
                    "%.2f" % statistics.median(durs) if durs else "—",
                    "%.2f" % statistics.median(cov) if cov else "—",
                    "%.2f 拍" % statistics.median(gaps) if gaps else "—"))
    L.append("")
    L.append("  注 1：「硬切间隔中位」= 全部 `duration=0` 事件的相邻间隔（拍）。")
    L.append("      ≈1.00 拍 ⇒ 每拍换一次姿态（= 一拍一振）；≈0.50 ⇒ 每半拍。")
    L.append("  注 2：「中位覆盖格」= 补间时值 × base_bpm / cur —— 一条补间跨了几格。")
    L.append("      **各 cur 档如果都差不多，说明作者的真实规则是「每 N 格动一下」，")
    L.append("        而不是「按 cur 分档」** —— 时值只是被 cur 除出来的。")
    if errs:
        L.append("")
        L.append("  失败 %d 份（前 5）：" % len(errs))
        for p, e in errs[:5]:
            L.append("    · %s　%s" % (os.path.basename(os.path.dirname(p)), e))
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("charts", nargs="*", help="谱面路径（.adofai）")
    ap.add_argument("--suite", action="store_true", help="跑内置的一组对照谱")
    ap.add_argument("--scan", metavar="DIR",
                    help="递归扫描一个目录下所有谱面并聚合")
    ap.add_argument("--limit", type=int, default=0, help="扫描时的最大谱面数")
    ap.add_argument("--bin", type=float, default=400.0, dest="split",
                    help="cur 分箱阈值（cbpm），默认 400")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--macro", default=MACRO_DIR, help="宏解析器目录")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.scan:
        lines = _scan(args.scan, args.limit, args.split, args.macro)
        print("\n".join(lines))
        if not args.no_write:
            dst = os.path.join(OUT_DIR, "_scan_%s.txt"
                               % os.path.basename(args.scan.rstrip("\\/")) or "scan")
            with open(dst, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print("\n→ %s" % dst)
        return 0

    charts = list(args.charts)
    if args.suite or not charts:
        charts += [p for p in SUITE if os.path.exists(p)]
    if not charts:
        raise SystemExit("没给谱面，也没有内置谱可用")

    for p in charts:
        if not os.path.exists(p):
            print("跳过（不存在）：%s" % p)
            continue
        name, lines = analyze(p, args.split, args.top, args.macro)
        print("\n".join(lines))
        if not args.no_write:
            dst = os.path.join(OUT_DIR, name + ".txt")
            with open(dst, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print("\n→ %s\n" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
