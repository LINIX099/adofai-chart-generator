# -*- coding: utf-8 -*-
"""重型特效语料里「**轨道表现**相关事件」的用法调研（只读）。

    python tools/analyze_track_events.py [chart.adofai | 目录 ...]

不给参数时用内置的 8 份重型特效语料（用户 2026-10 指定）。
输出：`out\\_track_events_report.txt`（完整）+ stdout（浓缩版）。

为什么单独写一个而不是复用 scan_adofai_events.py：
  1) 那个是「全量扫一遍拿字段真值」，粒度是一台机器；
     这个要的是「**一个事件在真实谱里怎么被用**」——分布、组合、共现、时间轴。
  2) 这份语料里的谱面巨大（gamma ray burst 3.5 MB），逐事件字段真值 + 分布才看得出套路。
"""
from __future__ import annotations

import collections
import io
import json
import os
import re
import sys

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

sys.stdout.reconfigure(encoding="utf-8")

BASE = CORPUS

#: 用户指定的 8 份高质量重型特效谱（目录 → 递归找 .adofai）
DEFAULT_CHARTS = [
    r"7. QuomodocunquizE",
    r"Archangel",
    r"Camellia - First Town Of This Journey",
    r"CFM1",
    r"Hello (BPM) 2025_fix[VFX pro]_1080p",
    r"Hello (BPM) 2024[Video VFX]",
    r"gamma ray burst by 土豆",
    r"PLUM_MEGAMIX[Video VFX]重制版",
]

#: 「轨道表现」相关的候选事件（LevelEventType.cs 里筛出来的）
TRACK_EVENTS = [
    "TrackSettings", "ColorTrack", "RecolorTrack", "AnimateTrack", "ChangeTrack",
    "MoveTrack", "PositionTrack", "TileDimensions", "Hide", "SetFloorIcon",
    "ScaleMargin", "ScaleRadius", "ScalePlanets", "MultiPlanet", "SetPlanetRotation",
    "SetFilter", "SetFilterAdvanced", "Bloom", "HallOfMirrors", "ShakeScreen",
    "ScreenTile", "ScreenScroll", "Flash", "SetFrameRate",
    "AddDecoration", "MoveDecorations", "DecorationSettings", "SetDefaultText",
    "AddText", "SetText", "AddObject", "SetObject", "AddParticle", "SetParticle",
    "EmitParticle", "CustomBackground", "BackgroundSettings", "MoveCamera",
    "SetDefaultText", "SetConditionalEvents", "RepeatEvents", "MoveTrack",
]

#: 打印字段分布时，超过这个数就折叠
TOP = 14


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
    """★ 宽松解析（同 `analyze_track_patterns.load_json`）：
    真实谱面里删过事件的版本会留**尾逗号 / 裸控制字符**，严格 `json.load` 会抛。
    """
    with open(p, "r", encoding="utf-8-sig") as f:   # ★ 游戏写出的是 UTF-8 with BOM
        txt = f.read()
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        cleaned = re.sub(r",(\s*,)+", ",", txt)          # 连续逗号 `, ,`
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)  # 尾逗号
        return json.loads(cleaned, strict=False)   # strict=False 容忍裸控制字符


def topn(c: collections.Counter, n: int = TOP) -> str:
    items = c.most_common(n)
    body = ", ".join(f"{k!r}×{v}" for k, v in items)
    if len(c) > n:
        body += f"  (+{len(c) - n} 种其他)"
    return body


def main(argv: list[str]) -> int:
    paths = argv or [os.path.join(BASE, d) for d in DEFAULT_CHARTS]
    files = sorted(chart_files(paths))
    buf = io.StringIO()

    def w(s: str = "") -> None:
        buf.write(s + "\n")

    w("=" * 78)
    w("重型特效语料 · 轨道表现相关事件用法调研")
    w("=" * 78)

    allc: collections.Counter = collections.Counter()
    per_chart: dict[str, collections.Counter] = {}
    keys: dict[str, set] = collections.defaultdict(set)
    vals: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    rows: dict[str, list[tuple]] = collections.defaultdict(list)
    meta: dict[str, dict] = {}

    for p in files:
        try:
            j = load(p)
        except Exception as e:  # noqa: BLE001
            w(f"!! 读不了 {p}: {e}")
            continue
        st = j.get("settings", {}) or {}
        actions = j.get("actions", []) or []
        # ★ 用「父目录/文件名」当键：这份语料里 `backup.adofai` / `level.adofai` /
        #   `main.adofai` 各出现好几次，只用 basename 会**互相覆盖**，
        #   C 矩阵那一节会显示成"两份不同的谱数字完全一样"（2026-10 踩过）。
        name = os.path.join(os.path.basename(os.path.dirname(p)), os.path.basename(p))
        c: collections.Counter = collections.Counter()
        for a in actions:
            if not isinstance(a, dict):
                continue
            et = a.get("eventType") or "<none>"
            c[et] += 1
            allc[et] += 1
            keys[et].add(frozenset(a.keys()))
            for k, v in a.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    vals[(et, k)][repr(v)] += 1
            rows[et].append((name, a))
        per_chart[name] = c
        meta[name] = {
            "version": st.get("version"),
            "bpm": st.get("bpm"),
            "pathData": st.get("pathData"),
            "tiles": len(st.get("pathData", "") or ""),
            "actions": len(actions),
            "file": p,
        }
        w(f"\n--- {name}")
        w(f"    version={st.get('version')} bpm={st.get('bpm')} "
          f"tiles={len(st.get('pathData', '') or '')} actions={len(actions)}")
        w(f"    artist={st.get('artist')!r} song={st.get('song')!r}")

    # ---------- B. 全量事件排行 ----------
    w("\n" + "=" * 78)
    w("B. 全量 eventType 排行（8 份语料合计）")
    w("=" * 78)
    for et, n in allc.most_common():
        mark = "" if et in TRACK_EVENTS else "   ·非轨道"
        w(f"  {n:>7}  {et}{mark}")

    # ---------- C. 每份谱的轨道事件矩阵 ----------
    w("\n" + "=" * 78)
    w("C. 轨道表现事件 × 谱面 矩阵（空=0）")
    w("=" * 78)
    names = [n for n in meta]
    seen_track = [et for et in dict.fromkeys(TRACK_EVENTS) if allc.get(et)]
    hdr = ["event"] + [n[:22] for n in names]
    w("  " + " | ".join(f"{h:<22}" for h in hdr))
    for et in seen_track:
        cells = [f"{per_chart[n].get(et, 0):<22}" for n in names]
        w(f"  {et:<26} " + " ".join(cells))

    # ---------- D. 字段真值 + 分布 ----------
    w("\n" + "=" * 78)
    w("D. 字段真值集与取值分布（只列真实出现过的轨道事件）")
    w("=" * 78)
    for et in seen_track:
        w(f"\n### {et}   共 {allc[et]} 条")
        for combo in sorted(keys[et], key=lambda c: (-len(c), sorted(c))):
            w(f"    keys({len(combo)}) = {sorted(combo)}")
        for k in sorted({k for (e, k) in vals if e == et}):
            w(f"    · {k}: {topn(vals[(et, k)])}")

    # ---------- E. 逐事件样例（前若干条）----------
    w("\n" + "=" * 78)
    w("E. 样例（每种事件前 3 条原始 JSON）")
    w("=" * 78)
    for et in sorted(rows):
        if et not in seen_track:
            continue
        w(f"\n### {et}")
        for name, a in rows[et][:3]:
            w(f"  [{name}] {json.dumps(a, ensure_ascii=False)}")

    text = buf.getvalue()
    os.makedirs("out", exist_ok=True)
    outp = os.path.join("out", "_track_events_report.txt")
    with open(outp, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\n[已写入 {outp}（{len(text)} 字符）]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
