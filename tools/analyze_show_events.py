# -*- coding: utf-8 -*-
"""「演出」事件语料调研：**位置轨道 PositionTrack / 移动轨道 MoveTrack** 为主。

    python tools/analyze_show_events.py [chart.adofai | 目录 ...]

不给参数时扫**全语料**（用户 535 份 + 创意工坊 37 份 + 官方 Worlds）。

为什么单开一个工具（不复用 analyze_track_events.py）：
  1) 那个工具只看 8 份重型特效谱、只看「字段真值」；
     这个要看**全语料**的用法，并且要把「事件落在**什么形状的格子**上」算出来
     —— 演出调度的驱动源是**谱面结构**（用户口径），没有结构关联就没法定公式。
  2) 演出两件套（PositionTrack/MoveTrack）在重特效谱里几乎不出现，
     它们的主场是**普通谱的视觉演出**，必须全量扫。

输出：`out\\_show_events_report.txt`（完整）+ stdout（浓缩版）。

★ 真实性守则（跟上一轮一致）：
  - 宽松解析（尾逗号 / 裸控制字符 / 连续逗号）
  - 用「父目录/文件名」当键（backup/level/main 会重名）
  - `angleData` 里的 `NaN`（中旋）单独计数，不当 0 用
"""
from __future__ import annotations

import collections
import io
import json
import math
import os
import re
import sys

#: Steam 工坊内容目录（冰与火 = 977950）。用 `ADOFAI_WORKSHOP` 指定。
WORKSHOP = os.environ.get("ADOFAI_WORKSHOP") or os.path.join(CORPUS, "_workshop")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: Steam 工坊内容目录（冰与火 = 977950）。用 `ADOFAI_WORKSHOP` 指定。
WORKSHOP = os.environ.get("ADOFAI_WORKSHOP") or os.path.join(CORPUS, "_workshop")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

_HOME = os.path.expanduser("~")                                #: 用户目录

sys.stdout.reconfigure(encoding="utf-8")

CORPUS_ROOTS = [
    CORPUS,
    WORKSHOP,
    _HOME + r"\Documents\A Dance of Fire and Ice\Worlds",
]

#: 演出家族（按「它改的是**轨道的外观/位置**，不改判定」筛）
SHOW_EVENTS = [
    "PositionTrack", "MoveTrack", "AnimateTrack", "ChangeTrack", "TileDimensions",
    "SetFloorIcon", "ScaleRadius", "ScalePlanets", "MultiPlanet", "SetPlanetRotation",
    "Hide", "Hold", "RepeatEvents", "SetConditionalEvents",
    # 装饰/屏幕类（对照用，看演出到底靠哪一层实现）
    "AddDecoration", "MoveDecorations", "AddParticle", "SetParticle", "EmitParticle",
    "Flash", "Bloom", "ShakeScreen", "SetFilter", "SetFilterAdvanced",
    "ScreenTile", "ScreenScroll", "HallOfMirrors", "MoveCamera", "PlaySound",
]

TOP = 16
MAX_FLOOR_ROW = 400000     # 单谱最多统计多少个事件（防超大谱卡死）


def chart_files(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        if os.path.isfile(p) and p.lower().endswith(".adofai"):
            out.append(p)
            continue
        if os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git")]
                for fn in filenames:
                    if fn.lower().endswith(".adofai"):
                        out.append(os.path.join(dirpath, fn))
    return out


def load(p: str):
    """宽松解析：真实谱面删过事件会留尾逗号 / 裸控制字符。"""
    with open(p, "r", encoding="utf-8-sig") as f:
        txt = f.read()
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        cleaned = re.sub(r",(\s*,)+", ",", txt)          # 连续逗号 `, ,`
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)  # 尾逗号
        # ★ 2026-10 新发现：编辑器删事件后会把 `"actions": [ … ]` 与下一个键之间的
        #   **逗号也一起删掉**（`]\n\t"decorations":`）⇒ 43/573 份谱这么挂的。
        #   只在严格解析失败后走这一步，且只在 `]`/`}` 之后紧跟 `"键":` 时补逗号。
        cleaned = re.sub(r'([\]\}])(\s*)"([A-Za-z_][A-Za-z0-9_]*)"\s*:',
                         r'\1,\2"\3":', cleaned)
        return json.loads(cleaned, strict=False)


def topn(c: collections.Counter, n: int = TOP) -> str:
    items = c.most_common(n)
    body = ", ".join(f"{k!r}×{v}" for k, v in items)
    if len(c) > n:
        body += f"  (+{len(c) - n} 种其他)"
    return body


def quant(xs: list[float], qs=(0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)) -> str:
    if not xs:
        return "(空)"
    s = sorted(xs)
    n = len(s)
    out = []
    for q in qs:
        i = min(n - 1, max(0, int(round(q * (n - 1)))))
        out.append(f"p{int(q * 100)}={s[i]:.3g}")
    return " ".join(out)


def travel_series(angle_data) -> list[float]:
    """每格的 travel（度）。180 = 直线。

    `angleData` 里可能有 "NaN"（中旋格）⇒ 该格 travel 记 NaN 并单独计数。
    """
    a: list[float] = []
    nan_idx: list[int] = []
    for i, v in enumerate(angle_data or []):
        try:
            fv = float(v)
            if math.isnan(fv):
                raise ValueError
        except Exception:  # noqa: BLE001
            a.append(float("nan"))
            nan_idx.append(i)
            continue
        a.append(fv)
    out = [float("nan")] * len(a)
    for i in range(1, len(a)):
        if math.isnan(a[i]) or math.isnan(a[i - 1]):
            continue
        d = abs(a[i] - a[i - 1]) % 360.0
        if d > 180.0:
            d = 360.0 - d
        out[i] = 180.0 - d
    return out


def _param_key(a: dict) -> tuple:
    """一个演出事件「观感参数」的指纹（用来判断一段演出里参数是否在变）。"""
    out = []
    for k in ("positionOffset", "rotationOffset", "scale", "opacity", "duration", "ease"):
        v = a.get(k)
        out.append((k, repr(v)))
    return tuple(out)


def shape_of(travel: float) -> str:
    if travel != travel:      # NaN
        return "?"            # 中旋/未知
    if travel >= 179.999:
        return "直线"
    if travel >= 90:
        return "缓弯"
    if travel >= 30:
        return "急弯"
    return "发卡"


def main(argv: list[str]) -> int:
    paths = argv or list(CORPUS_ROOTS)
    files = sorted(chart_files(paths))
    buf = io.StringIO()

    def w(s: str = "") -> None:
        buf.write(s + "\n")

    w("=" * 78)
    w("演出事件语料调研（PositionTrack / MoveTrack 为主）")
    w("=" * 78)
    w(f"语料根: {paths}")
    w(f"谱面数: {len(files)}")

    allc: collections.Counter = collections.Counter()
    keys: dict[str, set] = collections.defaultdict(set)
    vals: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    rows: dict[str, list[tuple]] = collections.defaultdict(list)
    per_chart: list[tuple[str, collections.Counter]] = []
    n_ok = n_bad = 0

    # 结构关联（仅演出家族）
    shape_cnt: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    gap_tiles: dict[str, list[float]] = collections.defaultdict(list)   # 相邻事件间隔（格）
    span_tiles: list[float] = []                                        # MoveTrack 扫过的格数
    pt_off: list[float] = []                                            # PositionTrack 偏移模长
    mt_off: list[float] = []                                            # MoveTrack 偏移模长
    cooccur: collections.Counter = collections.Counter()                # 同格事件组合
    floor_frac: dict[str, list[float]] = collections.defaultdict(list)  # 事件在曲中的相对位置
    # ★ 演出的「配方」：哪几个可选字段被启用（缺字段 = 不生效，见 LevelEvent.Decode）
    recipe: collections.Counter = collections.Counter()
    run_hist: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    RUN_EVENTS = ("MoveTrack", "PositionTrack")
    RUN_KEYS = ("positionOffset", "rotationOffset", "scale", "opacity")
    best_runs: dict[str, list] = collections.defaultdict(list)   # (长度, 谱名, 事件串)
    vary_runs: dict[str, list] = collections.defaultdict(list)   # 参数**在变**的段

    for p in files:
        try:
            j = load(p)
        except Exception as e:  # noqa: BLE001
            n_bad += 1
            w(f"!! 读不了 {p}: {e}")
            continue
        n_ok += 1
        st = j.get("settings", {}) or {}
        actions = j.get("actions", []) or []
        name = os.path.join(os.path.basename(os.path.dirname(p)), os.path.basename(p))
        # ★ `angleData` 在**顶层**，不在 settings 里（v19 格式：{angleData, settings, actions, decorations}）
        angle_data = j.get("angleData") or st.get("angleData") or []
        tv = travel_series(angle_data)
        n_tiles = len(tv)

        c: collections.Counter = collections.Counter()
        by_floor: dict[int, list[str]] = collections.defaultdict(list)
        last_floor: dict[str, int] = {}
        cur_floors: dict[str, list] = {k: [] for k in RUN_EVENTS}
        for a in actions[:MAX_FLOOR_ROW]:
            if not isinstance(a, dict):
                continue
            et = a.get("eventType") or "<none>"
            c[et] += 1
            allc[et] += 1
            if et in RUN_EVENTS:
                on = "+".join(k for k in RUN_KEYS if k in a)
                recipe[f"{et}|{on or '-'}"] += 1
            if et not in SHOW_EVENTS:
                continue
            keys[et].add(frozenset(a.keys()))
            for k, v in a.items():
                if isinstance(v, (str, int, float, bool)) or v is None or isinstance(v, list):
                    vals[(et, k)][repr(v)] += 1
            rows[et].append((name, a))

            fl = a.get("floor")
            if not isinstance(fl, int):
                continue
            by_floor[fl].append(et)
            if et in RUN_EVENTS:
                cur_floors[et].append((fl, a))
            if n_tiles:
                floor_frac[et].append(fl / n_tiles)
            # ★ 事件落在「什么形状的格子」上：看它**之后一格**的 travel
            #   （floor N 上的演出事件作用在 N 及其之后；N+1 决定它出场时脚下是什么）
            if 0 <= fl + 1 < n_tiles:
                shape_cnt[et][shape_of(tv[fl + 1])] += 1
            if et in last_floor:
                gap_tiles[et].append(fl - last_floor[et])
            last_floor[et] = fl

            if et == "PositionTrack":
                off = a.get("positionOffset")
                if isinstance(off, list) and len(off) == 2:
                    try:
                        pt_off.append(math.hypot(float(off[0]), float(off[1])))
                    except Exception:  # noqa: BLE001
                        pass
            if et == "MoveTrack":
                off = a.get("positionOffset")
                if isinstance(off, list) and len(off) == 2:
                    try:
                        mt_off.append(math.hypot(float(off[0]), float(off[1])))
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    s0 = a.get("startTile")
                    e0 = a.get("endTile")
                    s0 = s0[0] if isinstance(s0, list) else s0
                    e0 = e0[0] if isinstance(e0, list) else e0
                    if isinstance(s0, int) and isinstance(e0, int):
                        span_tiles.append(abs(e0 - s0))
                except Exception:  # noqa: BLE001
                    pass

        # 同格共现（只留 ≥2 种的组合）
        for fl, ets in by_floor.items():
            if len(ets) >= 2:
                cooccur["+".join(sorted(set(ets)))] += 1
        # 连续出现段长度（相邻 floor 都发同一个事件 = 一段）
        for et, fls in cur_floors.items():
            if not fls:
                continue
            fls = sorted(fls, key=lambda t: t[0])
            seg: list = [fls[0]]
            for i in range(1, len(fls) + 1):
                cont = i < len(fls) and fls[i][0] == fls[i - 1][0] + 1
                if cont:
                    seg.append(fls[i])
                else:
                    run_hist[et][len(seg)] += 1
                    if len(seg) > 1:
                        best_runs[et].append((len(seg), name, seg))
                        keys_ = {_param_key(a) for _, a in seg}
                        if len(keys_) > 1:
                            vary_runs[et].append((len(seg), name, seg))
                    seg = [fls[i]] if i < len(fls) else []
        per_chart.append((name, c))

    # ---------- B. 全量 eventType 排行 ----------
    w("\n" + "=" * 78)
    w(f"B. 全量 eventType 排行（{n_ok} 份可读 / {n_bad} 份读不了）")
    w("=" * 78)
    for et, n in allc.most_common():
        mark = "" if et in SHOW_EVENTS else "   ·非演出"
        w(f"  {n:>8}  {et}{mark}")

    # ---------- C. 出现谱面数（比条数更能说明「是不是常规手法」）----------
    w("\n" + "=" * 78)
    w("C. 演出事件在多少份谱里出现过（覆盖率）")
    w("=" * 78)
    cover: collections.Counter = collections.Counter()
    for _, c in per_chart:
        for et in SHOW_EVENTS:
            if c.get(et):
                cover[et] += 1
    for et in SHOW_EVENTS:
        if cover[et]:
            w(f"  {et:<22} 出现在 {cover[et]:>4}/{n_ok} 份谱   共 {allc[et]:>7} 条")

    # ---------- D. 字段真值 + 取值分布 ----------
    w("\n" + "=" * 78)
    w("D. 字段真值集与取值分布")
    w("=" * 78)
    for et in SHOW_EVENTS:
        if not allc.get(et):
            continue
        w(f"\n### {et}   共 {allc[et]} 条")
        for combo in sorted(keys[et], key=lambda c: (-len(c), sorted(c)))[:6]:
            w(f"    keys({len(combo)}) = {sorted(combo)}")
        if len(keys[et]) > 6:
            w(f"    … 另有 {len(keys[et]) - 6} 种字段组合")
        for k in sorted({k for (e, k) in vals if e == et}):
            w(f"    · {k}: {topn(vals[(et, k)])}")

    # ---------- E. 结构关联 ----------
    w("\n" + "=" * 78)
    w("E. 结构关联（演出落在什么形状的格子上 / 间隔多少格）")
    w("=" * 78)
    for et in SHOW_EVENTS:
        if not shape_cnt.get(et):
            continue
        tot = sum(shape_cnt[et].values())
        parts = ", ".join(f"{k}={v}({v * 100.0 / tot:.0f}%)"
                          for k, v in shape_cnt[et].most_common())
        w(f"  {et:<20} 脚下形状: {parts}")
        if gap_tiles.get(et):
            w(f"    {'':<18} 相邻事件间隔(格): {quant(gap_tiles[et])}")
        if floor_frac.get(et):
            w(f"    {'':<18} 曲中位置(0=曲首 1=曲尾): {quant(floor_frac[et])}")

    # ---------- F. 关键量的数值分布 ----------
    w("\n" + "=" * 78)
    w("F. 关键量分布")
    w("=" * 78)
    w(f"  PositionTrack.positionOffset 模长(格): {quant(pt_off)}   n={len(pt_off)}")
    w(f"  MoveTrack.positionOffset 模长(格):     {quant(mt_off)}   n={len(mt_off)}")
    w(f"  MoveTrack startTile→endTile 跨度(格):  {quant(span_tiles)}   n={len(span_tiles)}")

    # ---------- G. 同格共现 ----------
    w("\n" + "=" * 78)
    w("G. 同一格上同时出现的事件组合（≥2 种的格数）")
    w("=" * 78)
    for k, v in cooccur.most_common(25):
        w(f"  {v:>7}  {k}")

    # ---------- H. 样例 ----------
    w("\n" + "=" * 78)
    w("H. 样例（PositionTrack / MoveTrack / AnimateTrack / TileDimensions 各前 6 条）")
    w("=" * 78)
    for et in ("PositionTrack", "MoveTrack", "AnimateTrack", "TileDimensions", "RepeatEvents"):
        if not rows.get(et):
            continue
        w(f"\n### {et}")
        for name, a in rows[et][:6]:
            w(f"  [{name}] {json.dumps(a, ensure_ascii=False)}")

    # ---------- J. 演出的「配方」----------
    w("\n" + "=" * 78)
    w("J. 演出配方（可选字段的启用组合；缺字段 = 不生效）")
    w("=" * 78)
    for et in RUN_EVENTS:
        tot = sum(v for k, v in recipe.items() if k.startswith(et + "|"))
        if not tot:
            continue
        w(f"\n### {et}   共 {tot} 条")
        for k, v in recipe.most_common(12):
            if k.startswith(et + "|"):
                w(f"  {v:>8}  {v * 100.0 / tot:5.1f}%   {k.split('|', 1)[1]}")
        w(f"  连续段长度(相邻格都发): {topn(run_hist[et])}")

    # ---------- K. 整段演出样例（最长的连续段）----------
    w("\n" + "=" * 78)
    w("K. 整段演出样例（连续段最长的 3 段，逐格参数轨迹）")
    w("=" * 78)
    for et in RUN_EVENTS:
        runs = sorted(best_runs.get(et, []), key=lambda r: -r[0])[:3]
        for ln, name, seg in runs:
            w(f"\n### {et}  {ln} 格连续   [{name}]   floor {seg[0][0]}→{seg[-1][0]}")
            w(f"    {'floor':>7} {'pos':>14} {'rot':>6} {'scale':>12} {'op':>6} "
              f"{'dur':>5} {'ease':<10} {'angleOff':>8}")
            for fl, a in seg[:40]:
                w(f"    {fl:>7} {str(a.get('positionOffset') or a.get('positionOffset', '-')):>14} "
                  f"{str(a.get('rotationOffset', '-')):>6} {str(a.get('scale', '-')):>12} "
                  f"{str(a.get('opacity', '-')):>6} {str(a.get('duration', '-')):>5} "
                  f"{str(a.get('ease', '-')):<10} {str(a.get('angleOffset', '-')):>8}")
            if len(seg) > 40:
                w(f"    … 余下 {len(seg) - 40} 格")

    # ---------- L. 参数在变的段（真正的「演出」动机）----------
    w("\n" + "=" * 78)
    w("L. 参数在变的连续段（4~64 格，长度前 5）—— 这才是「演出手法」")
    w("=" * 78)
    for et in RUN_EVENTS:
        runs = [r for r in vary_runs.get(et, []) if 4 <= r[0] <= 64]
        runs = sorted(runs, key=lambda r: -r[0])[:5]
        if not runs:
            w(f"\n### {et}: 没有参数在变的连续段")
            continue
        for ln, name, seg in runs:
            w(f"\n### {et}  {ln} 格参数递变   [{name}]   floor {seg[0][0]}→{seg[-1][0]}")
            w(f"    {'floor':>7} {'pos':>16} {'rot':>7} {'scale':>12} {'op':>6} "
              f"{'dur':>5} {'ease':<10} {'angleOff':>8}")
            for fl, a in seg[:32]:
                w(f"    {fl:>7} {str(a.get('positionOffset', '-')):>16} "
                  f"{str(a.get('rotationOffset', '-')):>7} {str(a.get('scale', '-')):>12} "
                  f"{str(a.get('opacity', '-')):>6} {str(a.get('duration', '-')):>5} "
                  f"{str(a.get('ease', '-')):<10} {str(a.get('angleOffset', '-')):>8}")
            if len(seg) > 32:
                w(f"    … 余下 {len(seg) - 32} 格")

    # ---------- I. 谁在用演出 ----------
    w("\n" + "=" * 78)
    w("I. 演出大户（按 PositionTrack+MoveTrack 条数排）")
    w("=" * 78)
    rank = sorted(per_chart, key=lambda kv: -(kv[1].get("PositionTrack", 0) + kv[1].get("MoveTrack", 0)))
    for name, c in rank[:30]:
        pt = c.get("PositionTrack", 0)
        mt = c.get("MoveTrack", 0)
        if pt + mt == 0:
            break
        w(f"  PT={pt:>6}  MT={mt:>6}   {name}")

    text = buf.getvalue()
    os.makedirs("out", exist_ok=True)
    outp = os.path.join("out", "_show_events_report.txt")
    with open(outp, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\n[已写入 {outp}（{len(text)} 字符）]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
