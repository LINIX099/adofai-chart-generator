# -*- coding: utf-8 -*-
"""重型特效语料 · 轨道事件的**调度套路**分析（只读）。

    python tools/analyze_track_patterns.py

第一份 `analyze_track_events.py` 回答「有什么事件、字段长什么样」；
这一份回答「**它们怎么被调度**」——周期、并行度、参数签名、共现、重复器。

输出 `out\\_track_patterns_report.txt`。
"""
from __future__ import annotations

import collections
import io
import json
import os
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
#: 官方谱面本体（不是备份/无特效版），只挑这些做逐谱分析
SKIP_NAME = ("backup", "backup2", "去特效", "No Effect", "test", "old", "video", "scam(non)")

FOCUS = ["RecolorTrack", "ColorTrack", "MoveTrack", "PositionTrack", "AnimateTrack",
         "SetFilter", "SetFilterAdvanced", "Bloom", "Flash", "ShakeScreen",
         "Hide", "ScaleRadius", "ScalePlanets", "HallOfMirrors", "RepeatEvents"]


def charts(paths):
    out = []
    for p in paths:
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isdir(p):
            for dp, dn, fns in os.walk(p):
                for fn in fns:
                    if fn.lower().endswith(".adofai"):
                        out.append(os.path.join(dp, fn))
    return sorted(out)


def load_json(p: str):
    """★ 宽松解析：真实谱面里有一堆**非严格 JSON**（删事件时留下的尾逗号、
      字符串里有裸控制字符），`json.load` 会直接抛。这些恰恰是重型特效谱
      （手动删过事件的版本），不能跳过 —— CFM1/main.adofai 就是这么被漏掉的。
    """
    with open(p, "r", encoding="utf-8-sig") as fh:
        txt = fh.read()
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        import re
        cleaned = re.sub(r",(\s*,)+", ",", txt)                   # 连续逗号 `, ,`
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)          # 尾逗号
        # ★ `strict=False`：允许字符串里出现裸控制字符（谱面里真有，
        #   比如 CFM1/main.adofai 第 9137 行）；自己用正则清会漏掉 \t\r\n，
        #   而它们同样是 json 严格模式拒绝的字符。
        return json.loads(cleaned, strict=False)


def topn(c, n=12):
    its = c.most_common(n)
    s = ", ".join(f"{k}×{v}" for k, v in its)
    if len(c) > n:
        s += f"  (+{len(c) - n})"
    return s


def sig(a: dict, keys) -> tuple:
    out = []
    for k in keys:
        if k in a:
            v = a[k]
            out.append(f"{k}={v!r}")
    return tuple(out)


def is_interesting(name: str) -> bool:
    low = name.lower()
    return not any(s.lower() in low for s in SKIP_NAME)


def main(argv):
    paths = argv or [os.path.join(BASE, d) for d in DEFAULT_CHARTS]
    files = [f for f in charts(paths) if is_interesting(os.path.basename(f))]
    buf = io.StringIO()

    def w(s=""):
        buf.write(s + "\n")

    w("=" * 78)
    w("重型特效语料 · 轨道事件调度套路")
    w("=" * 78)
    w("分析谱面：")
    for f in files:
        w(f"  {f}")

    for f in files:
        try:
            j = load_json(f)
        except Exception as e:  # noqa: BLE001
            w(f"\n!! 跳过 {f}: {e}")
            continue
        st = j.get("settings", {}) or {}
        acts = [a for a in (j.get("actions") or []) if isinstance(a, dict)]
        name = os.path.basename(f)
        n_tiles = len(st.get("pathData") or "")
        w("\n" + "=" * 78)
        w(f"【{name}】  version={st.get('version')} bpm={st.get('bpm')} "
          f"tiles={n_tiles} actions={len(acts)}  bpmChanges={st.get('bpmChanges') and 'yes' or 'no'}")
        w("=" * 78)

        byfloor = collections.defaultdict(list)
        bytype = collections.defaultdict(list)
        for a in acts:
            fl = a.get("floor")
            byfloor[fl].append(a)
            bytype[a.get("eventType")].append(a)

        # --- 0. 速览：这份谱每种轨道事件用了多少条 ---
        brief = "  ".join(f"{et}={c}" for et in FOCUS if (c := len(bytype.get(et) or [])))
        w(f"\n[0] 轨道事件计数: {brief or '(无)'}")

        # --- 1. 周期：每种事件相邻 floor 差 ---
        w("\n[1] 事件周期（相邻事件 floor 差的众数；0=同一格叠多条）")
        for et in FOCUS:
            seq = bytype.get(et)
            if not seq:
                continue
            fls = sorted({int(a["floor"]) for a in seq if isinstance(a.get("floor"), int)})
            d = collections.Counter(b - a for a, b in zip(fls, fls[1:]))
            w(f"  {et:<18} {len(seq):>6} 条 / {len(fls):>5} 格   floor间距众数: {topn(d, 8)}")

        # --- 2. 并行度：同格同类型条数 ---
        w("\n[2] 同格并行度（同一 floor 上同类型事件的条数分布）")
        for et in FOCUS:
            seq = bytype.get(et)
            if not seq:
                continue
            cnt = collections.Counter()
            for fl, group in byfloor.items():
                n = sum(1 for a in group if a.get("eventType") == et)
                if n:
                    cnt[n] += 1
            mx = max(cnt) if cnt else 0
            w(f"  {et:<18} 一格最多 {mx:>4} 条   分布: {topn(cnt, 8)}")

        # --- 3. 参数签名 ---
        SIGS = {
            "MoveTrack": ["positionOffset", "rotationOffset", "scale", "opacity", "duration",
                          "ease", "gapLength", "startTile", "endTile"],
            "PositionTrack": ["relativeTo", "positionOffset", "scale", "opacity",
                              "justThisTile", "editorOnly"],
            "AnimateTrack": ["trackAnimation", "trackDisappearAnimation", "beatsAhead", "beatsBehind"],
            "ScalePlanets": ["targetPlanet", "scale", "duration", "ease"],
            "SetFilter": ["filter", "enabled", "intensity", "duration", "ease"],
            "ShakeScreen": ["strength", "intensity", "duration", "fadeOut"],
            "Hide": ["hideJudgment", "hideTileIcon"],
            "RepeatEvents": ["repeatType", "repetitions", "floorCount", "interval",
                             "executeOnCurrentFloor", "tag", "gapLength"],
            "RecolorTrack": ["trackColorType", "trackStyle", "trackColorPulse",
                             "trackPulseLength", "duration", "ease", "startTile", "endTile",
                             "gapLength", "trackGlowIntensity", "angleOffset"],
            "ColorTrack": ["trackColorType", "trackStyle", "trackColor", "justThisTile",
                           "trackGlowIntensity"],
        }
        w("\n[3] 参数签名 Top（同签名条数）")
        for et, keys in SIGS.items():
            seq = bytype.get(et)
            if not seq:
                continue
            counter = collections.Counter(sig(a, keys) for a in seq)
            w(f"\n  -- {et}（{len(seq)} 条，{len(counter)} 种签名）")
            for s, n in counter.most_common(8):
                body = " ".join(s)
                if len(body) > 300:
                    body = body[:300] + " …"
                w(f"     {n:>6}  {body}")

        # --- 4. 共现（同格出现的事件类型组合）---
        w("\n[4] 同格共现 Top（同 floor 上出现的事件类型集合；只统计含轨道事件的格）")
        co = collections.Counter()
        for fl, group in byfloor.items():
            types = tuple(sorted({a.get("eventType") for a in group}))
            if any(t in FOCUS for t in types):
                co[types] += 1
        for types, n in co.most_common(10):
            shown = ",".join(t for t in types if t in FOCUS) or "(无轨道)"
            w(f"     {n:>6}  [{shown}]   全集合={','.join(types)}")

        # --- 5. 事件最密的一格：窗口原文 ---
        dens = max(byfloor.items(), key=lambda kv: (sum(1 for a in kv[1] if a.get("eventType") in FOCUS), len(kv[1])), default=None)
        if dens:
            fl, group = dens
            w(f"\n[5] 最密集的一格 floor={fl}（{len(group)} 条），窗口 ±1 格原文：")
            for f2 in sorted([fl - 1, fl, fl + 1]):
                g2 = byfloor.get(f2) or []
                if not g2:
                    continue
                w(f"   floor {f2}: {len(g2)} 条")
                for a in g2:
                    et = a.get("eventType")
                    if et not in FOCUS:
                        continue
                    body = json.dumps(a, ensure_ascii=False)
                    w(f"      {body[:260]}")

        # --- 6. 同格同类型的 angleOffset 扫描（"扫光/波纹"套路）---
        w("\n[6] 同格同类型 · angleOffset 扫描检测（同 floor 上 ≥3 条同类型且 angleOffset 不同）")
        hits = 0
        for fl, group in sorted(byfloor.items()):
            per = collections.defaultdict(list)
            for a in group:
                per[a.get("eventType")].append(a)
            for et, lst in per.items():
                if et not in FOCUS or len(lst) < 3:
                    continue
                aos = [a.get("angleOffset") for a in lst]
                if len(set(aos)) >= 3:
                    hits += 1
                    if hits <= 6:
                        w(f"   floor {fl} {et} ×{len(lst)}: angleOffset={sorted(set(aos))[:12]}")
                        for a in lst[:3]:
                            w(f"      {json.dumps(a, ensure_ascii=False)[:230]}")
        w(f"   …共 {hits} 处")

        # --- 7. RepeatEvents 与 tag 的联动 ---
        reps = bytype.get("RepeatEvents") or []
        if reps:
            w("\n[7] RepeatEvents 的 tag → 谁在用")
            tag2ev = collections.defaultdict(collections.Counter)
            for a in acts:
                t = a.get("eventTag") or a.get("tag")
                if t:
                    tag2ev[t][a.get("eventType")] += 1
            for a in reps[:12]:
                t = a.get("tag")
                used = tag2ev.get(t) or {}
                pairs = sorted(used.items(), key=lambda kv: -kv[1])[:6]
                use_s = ", ".join(f"{k}×{v}" for k, v in pairs) or "**没人用**"
                w(f"   floor {a.get('floor')}: repeatType={a.get('repeatType')} "
                  f"repetitions={a.get('repetitions')} interval={a.get('interval')} "
                  f"floorCount={a.get('floorCount')} tag={t!r} → {use_s}")

    text = buf.getvalue()
    os.makedirs("out", exist_ok=True)
    outp = os.path.join("out", "_track_patterns_report.txt")
    with open(outp, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"[已写入 {outp}（{len(text)} 字符，{text.count(chr(10))} 行）]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
