# -*- coding: utf-8 -*-
"""「**不用编辑器默认的方块**」到底有哪几条路 —— 社区语料 Targeted 扫描（只读）。

    python tools/scan_tile_look.py [根目录 ...]

不给参数时扫三份语料：
  · D:\\STEAM\\steamapps\\workshop\\content\\977950   （Steam 工坊）
  · ‹社区语料目录›         （535 份）
  · C:\\Users\\Administrator\\Documents\\A Dance of Fire and Ice\\Worlds

回答四个问题：
  Q1 `settings` 层的轨道外观键，社区在用什么？（trackStyle / trackTexture / trackColor* / trackAnimation…）
  Q2 **自定义贴图**（`trackTexture`）到底有没有人用？用的什么事件？贴图文件在不在一起？
  Q3 **改方块形状/尺寸**的手段（`TileDimensions` 的 length/width）有没有人用？
  Q4 `ScaleRadius` / `ScaleMargin` / `ScalePlanets` 的真实取值分布（它们是"半个轨道事件"吗）

输出：`out\\_tile_look_report.txt`
"""
from __future__ import annotations

import collections
import json
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

ROOTS = [
    WORKSHOP,
    CORPUS,
    _HOME + r"\Documents\A Dance of Fire and Ice\Worlds",
]

#: settings 里的轨道外观键
SETTING_KEYS = [
    "trackColorType", "trackColor", "secondaryTrackColor", "trackColorAnimDuration",
    "trackColorPulse", "trackPulseLength", "trackStyle", "trackTexture",
    "trackTextureScale", "trackGlowIntensity", "trackAnimation", "beatsAhead",
    "beatsBehind", "trackDisappearAnimation", "backgroundColor", "bgImage",
    "imageSmoothing", "loopBG", "scalingRatio", "relativeTo",
]

#: 稀奇/未验证的事件
RARE = ["TileDimensions", "ChangeTrack", "SetFloorIcon", "ScaleRadius",
        "ScaleMargin", "ScalePlanets", "SetPlanetRotation", "Hide", "ColorTrack"]

#: 引用外部资源的字段
ASSET_FIELDS = ("trackTexture",)

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def load_json(p: str):
    with open(p, "r", encoding="utf-8-sig") as fh:
        txt = fh.read()
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        # ★ 手动改过的谱面常见两种畸形：连续逗号 `, ,`（删字段时手滑）和尾逗号。
        cleaned = re.sub(r",(\s*,)+", ",", txt)
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        return json.loads(cleaned, strict=False)


def topn(c: collections.Counter, n: int = 10) -> str:
    its = c.most_common(n)
    s = ", ".join(f"{k!r}×{v}" for k, v in its)
    if len(c) > n:
        s += f"  (+{len(c) - n} 种其他)"
    return s


def main(argv: list[str]) -> int:
    roots = argv or ROOTS
    files: list[str] = []
    for r in roots:
        if os.path.isfile(r):
            files.append(r)
        elif os.path.isdir(r):
            for dp, dn, fns in os.walk(r):
                dn[:] = [d for d in dn if d not in ("node_modules", ".git")]
                for fn in fns:
                    if fn.lower().endswith(".adofai"):
                        files.append(os.path.join(dp, fn))
    files = sorted(set(files))

    out = []
    w = out.append

    set_vals: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    set_nonempty: dict[str, int] = collections.Counter()
    rare_count: collections.Counter = collections.Counter()
    rare_vals: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    rare_keys: dict[str, set] = collections.defaultdict(set)
    tex_users: list[tuple] = []
    style_events: collections.Counter = collections.Counter()
    style_settings: collections.Counter = collections.Counter()
    n_ok = 0
    bad = []

    for p in files:
        try:
            j = load_json(p)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{p}: {e}")
            continue
        if not isinstance(j, dict):
            continue
        n_ok += 1
        st = j.get("settings") or {}
        d = os.path.dirname(p)
        for k in SETTING_KEYS:
            if k in st:
                v = st[k]
                set_vals[k][repr(v)] += 1
                if v not in ("", None, 0, 1, 100, "None", "Standard", False):
                    set_nonempty[k] += 1
        if st.get("trackStyle"):
            style_settings[str(st["trackStyle"])] += 1
        # 贴图：settings 层
        for k in ASSET_FIELDS:
            v = st.get(k)
            if isinstance(v, str) and v.strip():
                f2 = os.path.join(d, v)
                tex_users.append(("settings", os.path.basename(p), v, os.path.isfile(f2)))
        for a in (j.get("actions") or []):
            if not isinstance(a, dict):
                continue
            et = a.get("eventType")
            if et == "trackStyle":
                pass
            if "trackStyle" in a:
                style_events[str(a["trackStyle"])] += 1
            if et in RARE:
                rare_count[et] += 1
                rare_keys[et].add(frozenset(a.keys()))
                for k, v in a.items():
                    if isinstance(v, (str, int, float, bool)) or v is None:
                        rare_vals[(et, k)][repr(v)] += 1
            for k in ASSET_FIELDS:
                v = a.get(k)
                if isinstance(v, str) and v.strip():
                    f2 = os.path.join(d, v)
                    tex_users.append((et, os.path.basename(p), v, os.path.isfile(f2)))

    w("=" * 78)
    w("「不用编辑器默认的方块」社区语料 Targeted 扫描")
    w("=" * 78)
    w(f"扫描根目录：")
    for r in roots:
        w(f"  [{'有' if os.path.exists(r) else '缺'}] {r}")
    w(f"\n读到 {n_ok} 份 .adofai（读不了 {len(bad)} 份）")
    for b in bad[:10]:
        w("   !! " + b)

    w("\n" + "=" * 78)
    w("Q1 · settings 层的轨道外观键")
    w("=" * 78)
    for k in SETTING_KEYS:
        if k not in set_vals:
            continue
        ne = set_nonempty.get(k, 0)
        w(f"\n-- {k}   （非默认取值 {ne} 份）")
        w("   " + topn(set_vals[k], 12))

    w("\n" + "=" * 78)
    w("Q2 · 自定义贴图 trackTexture")
    w("=" * 78)
    if not tex_users:
        w("  **社区语料 0 次非空 trackTexture** —— 没人用自定义贴图")
    else:
        by_ev = collections.Counter(t[0] for t in tex_users)
        w(f"  共 {len(tex_users)} 处，按事件：{dict(by_ev)}")
        w(f"  贴图文件存在的：{sum(1 for t in tex_users if t[3])} / {len(tex_users)}")
        w("  前 20 条：")
        for ev, fn, v, ok in tex_users[:20]:
            w(f"     [{ev}] {fn}  trackTexture={v!r}  文件{'在' if ok else '**不在**'}")

    w("\n" + "=" * 78)
    w("Q3 · 改方块形状/尺寸 TileDimensions")
    w("=" * 78)
    if rare_count.get("TileDimensions", 0) == 0:
        w("  **社区语料 0 次**")
    else:
        w(f"  共 {rare_count['TileDimensions']} 条")

    w("\n" + "=" * 78)
    w("Q4 · 稀有/星球系事件的出现次数与取值")
    w("=" * 78)
    for et in RARE:
        n = rare_count.get(et, 0)
        w(f"\n### {et}   共 {n} 条")
        if not n:
            continue
        for combo in sorted(rare_keys[et], key=lambda c: (-len(c), sorted(c))):
            w(f"    keys({len(combo)}) = {sorted(combo)}")
        for k in sorted({k for (e, k) in rare_vals if e == et}):
            w(f"    · {k}: {topn(rare_vals[(et, k)], 10)}")

    w("\n" + "=" * 78)
    w("S · trackStyle 用法（事件侧 vs settings 侧）")
    w("=" * 78)
    w(f"  事件侧（ColorTrack/RecolorTrack…）：{topn(style_events, 12)}")
    w(f"  settings 侧：{topn(style_settings, 12)}")

    text = "\n".join(out) + "\n"
    os.makedirs("out", exist_ok=True)
    dst = os.path.join("out", "_tile_look_report.txt")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print(f"[已写入 {dst}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
