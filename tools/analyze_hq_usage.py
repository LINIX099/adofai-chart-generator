# -*- coding: utf-8 -*-
"""**高质量特效谱用法普查**（用户口径：文件大的一般就是高质量特效谱）。

    python tools/analyze_hq_usage.py            # 全部（列 + 深挖 top N）
    python tools/analyze_hq_usage.py --list     # 只列最大的
    python tools/analyze_hq_usage.py --top 8    # 深挖前 8 张

输出：out\\_hq_usage_report.txt

只读语料，不动任何东西。
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  #: 仓库根（不写死盘符）

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

ROOTS = [
    CORPUS,
    WORKSHOP,
    _HOME + r"\Documents\A Dance of Fire and Ice\Worlds",
]
OUT = ROOT + r"\out\_hq_usage_report.txt"

# 编辑器会漏掉 `]\n\t"key":` 之间的逗号 ⇒ 宽容修复（与 analyze_show_events.py 同一招）
_FIX = re.compile(r'\]\s*\n(\s*)"')
# 也有**多余逗号**（`,\n\t}` / `,\n\t]` / `,,`）⇒ 一起修
_FIX2 = re.compile(r',(\s*[}\]])')
_FIX3 = re.compile(r",\s*,")


def _repairs(t: str) -> list[str]:
    """编辑器各种手抖的组合，按"最少改动"排好序逐个试。"""
    a = _FIX.sub(lambda m: "],\n" + m.group(1) + '"', t)      # 补逗号
    b = _FIX2.sub(r"\1", t)                                   # 去尾逗号
    c = _FIX3.sub(",", t)                                     # 去双逗号
    d = _FIX3.sub(",", a)
    e = _FIX2.sub(r"\1", _FIX3.sub(",", a))
    return [a, b, c, d, e]


def load(path: str):
    with open(path, "r", encoding="utf-8-sig") as fh:
        txt = fh.read()
    try:
        return json.loads(txt)
    except Exception:                                         # noqa: BLE001
        pass
    last: Exception | None = None
    for cand in _repairs(txt):
        try:
            return json.loads(cand)
        except Exception as exc:                              # noqa: BLE001
            last = exc
    raise last if last else RuntimeError("unreachable")


def collect() -> list[tuple[int, str]]:
    """所有 .adofai，按体积降序；**同目录的 backup 让位给 main/level**（去重）。"""
    raw: list[tuple[int, str]] = []
    for r in ROOTS:
        if not os.path.isdir(r):
            continue
        for dp, _dn, fn in os.walk(r):
            for f in fn:
                if not f.lower().endswith(".adofai"):
                    continue
                p = os.path.join(dp, f)
                try:
                    raw.append((os.path.getsize(p), p))
                except OSError:
                    pass
    by_dir: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    for sz, p in raw:
        by_dir[os.path.dirname(p)].append((sz, p))
    out: list[tuple[int, str]] = []
    for _d, items in by_dir.items():
        if len(items) == 1:
            out.extend(items)
            continue
        keep = [x for x in items if "backup" not in os.path.basename(x[1]).lower()]
        out.extend(keep or items[:1])          # 全是 backup 就只留一张
    out.sort(reverse=True)
    return out


# --------------------------------------------------------------------- 深挖
def sig(a: dict, drop=("floor", "eventType")) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in a.items() if k not in drop))


def analyze(path: str, lines: list[str]) -> dict:
    try:
        j = load(path)
    except Exception as exc:                                  # noqa: BLE001
        lines.append(f"  ✗ 读不了：{exc}")
        return {}
    acts = j.get("actions") or []
    ad = j.get("angleData") or []
    st = j.get("settings") or {}
    dec = j.get("decorations") or []
    n = len(ad) or 1
    cnt = collections.Counter(a.get("eventType") for a in acts)

    lines.append(f"  格数 {len(ad):<7} actions {len(acts):<7} "
                 f"decorations {len(dec):<6} 事件/格 {len(acts) / n:.2f}")
    lines.append(f"  settings: bpm={st.get('bpm')} trackAnimation={st.get('trackAnimation')!r} "
                 f"beatsAhead={st.get('beatsAhead')} "
                 f"disappear={st.get('trackDisappearAnimation')!r} beatsBehind={st.get('beatsBehind')} "
                 f"colorType={st.get('trackColorType')!r} color={st.get('trackColor')!r} "
                 f"style={st.get('trackStyle')!r} tileShape={st.get('tileShape')!r}")
    lines.append("  事件普查：" + "  ".join(f"{k}×{v}" for k, v in cnt.most_common(14)))

    # ---- MoveTrack：范围/间隔/相位/标签 ----
    mv = [a for a in acts if a.get("eventType") == "MoveTrack"]
    if mv:
        spans = []
        for a in mv:
            try:
                s0 = int(a["startTile"][0]); s1 = int(a["endTile"][0])
            except Exception:                                 # noqa: BLE001
                continue
            spans.append((s0, s1))
        # 作用范围（相对触发格）
        lo = collections.Counter(s0 for s0, _ in spans)
        hi = collections.Counter(s1 for _, s1 in spans)
        big = sum(1 for s0, s1 in spans if s1 - s0 + 1 >= 20)
        lines.append(f"  MoveTrack {len(mv)}：一次罩≥20格 {big} 条（{big / max(1, len(mv)):.0%}）")
        lines.append("    startTile 高频：" + "  ".join(f"{k}×{v}" for k, v in lo.most_common(8)))
        lines.append("    endTile   高频：" + "  ".join(f"{k}×{v}" for k, v in hi.most_common(8)))
        gaps = collections.Counter(int(a.get("gapLength") or 0) for a in mv)
        lines.append("    gapLength：" + "  ".join(f"{k}×{v}" for k, v in gaps.most_common(6)))
        ang = sum(1 for a in mv if float(a.get("angleOffset") or 0) != 0)
        lines.append(f"    angleOffset≠0（提前/延后）：{ang} 条（{ang / len(mv):.0%}）")
        tags = collections.Counter(str(a.get("eventTag") or "") for a in mv)
        lines.append("    eventTag：" + "  ".join(f"{k or '(空)'}×{v}" for k, v in tags.most_common(6)))
        dur = collections.Counter(float(a.get("duration") or 0) for a in mv)
        lines.append("    duration 高频：" + "  ".join(f"{k:g}×{v}" for k, v in dur.most_common(8)))
        ease = collections.Counter(str(a.get("ease")) for a in mv)
        lines.append("    ease 高频：" + "  ".join(f"{k}×{v}" for k, v in ease.most_common(8)))
        lines.append("    配方 top6：")
        rec = collections.Counter(sig(a) for a in mv)
        for s, c in rec.most_common(6):
            lines.append(f"      ×{c:<6}{dict(s)}")

    # ---- RecolorTrack：范围 / 类型 / 带长 ----
    rc = [a for a in acts if a.get("eventType") == "RecolorTrack"]
    if rc:
        typ = collections.Counter(str(a.get("trackColorType")) for a in rc)
        pul = collections.Counter(str(a.get("trackColorPulse")) for a in rc)
        plen = collections.Counter(int(a.get("trackPulseLength") or 0) for a in rc)
        adur = collections.Counter(float(a.get("trackColorAnimDuration") or 0) for a in rc)
        rng = []
        for a in rc:
            try:
                rng.append(int(a["endTile"][0]) - int(a["startTile"][0]) + 1)
            except Exception:                                 # noqa: BLE001
                pass
        lines.append(f"  RecolorTrack {len(rc)}：type {dict(typ)}")
        lines.append(f"    pulse {dict(pul)} / 带长 {dict(list(plen.most_common(6)))} / "
                     f"呼吸 {dict(list(adur.most_common(6)))}")
        if rng:
            rng.sort()
            lines.append(f"    覆盖格数 min/中位/max = {rng[0]}/{rng[len(rng) // 2]}/{rng[-1]}")

    # ---- MoveDecorations：tag 用途（trail / 光环 / 相机底片…）----
    md = [a for a in acts if a.get("eventType") == "MoveDecorations"]
    if md:
        tg = collections.Counter(str(a.get("tag") or "") for a in md)
        lines.append(f"  MoveDecorations {len(md)}：tag " +
                     "  ".join(f"{k or '(空)'}×{v}" for k, v in tg.most_common(10)))
        fields = collections.Counter()
        for a in md:
            for k in a:
                if k not in ("floor", "eventType", "tag", "angleOffset", "duration", "ease",
                             "eventTag", "parallaxOffset"):
                    fields[k] += 1
        lines.append("    动过的字段：" + "  ".join(f"{k}×{v}" for k, v in fields.most_common(10)))

    # ---- 粒子 / 镜头 / 滤镜（"特效谱"的气味）----
    for et, keep in (("SetParticle", "tag"), ("EmitParticle", "tag"),
                     ("MoveCamera", None), ("SetFilter", "filter"),
                     ("SetFilterAdvanced", "filter"), ("Flash", "plane")):
        lst = [a for a in acts if a.get("eventType") == et]
        if not lst:
            continue
        if keep:
            c = collections.Counter(str(a.get(keep) or "") for a in lst)
            lines.append(f"  {et} {len(lst)}：{keep} " +
                         "  ".join(f"{k or '(空)'}×{v}" for k, v in c.most_common(8)))
        else:
            lines.append(f"  {et} {len(lst)}")

    # ---- RepeatEvents（批量刷事件的写法）----
    re_ = [a for a in acts if a.get("eventType") == "RepeatEvents"]
    if re_:
        lines.append(f"  RepeatEvents {len(re_)} 条 —— 批量复制，examples：")
        for a in re_[:3]:
            lines.append("    " + json.dumps(a, ensure_ascii=False)[:400])

    # ---- 关卡装饰（图片/文字，观感的一半）----
    if dec:
        kinds = collections.Counter(str(d.get("decorationImage") or d.get("text") or "?")[:26]
                                   for d in dec)
        lines.append(f"  decorations {len(dec)}：top {list(kinds.most_common(6))}")
    # ---- ★ 归位 / 甩走 的"前瞻格数"（= 目标格 − 触发格）----
    #   归位 = opacity 100 + pos(0,0) + scale(100,100)（回到常态）
    #   甩走 = opacity 0 或 scale 0
    lead_ret: list[int] = []
    lead_kill: list[int] = []
    for a in mv:
        try:
            if a["startTile"][1] != "ThisTile":
                continue                       # ★ `Start` 锚点是**绝对格号**，不是前瞻量
            k = int(a["startTile"][0])
            if int(a["endTile"][0]) != k:
                continue                       # 只看单格
        except Exception:                                     # noqa: BLE001
            continue
        op = a.get("opacity")
        pos = a.get("positionOffset")
        sc = a.get("scale")
        rot = a.get("rotationOffset")

        def _z(v):
            """`positionOffset` 里的 `null` = **这个轴不动**（语料口径）⇒ 当作 0。"""
            return 0.0 if v is None else float(v)

        # 归位 = **写出来的那些维度全都设回常态**（没写的维度本来就"不动"）
        checks: list[bool] = []
        if op is not None:
            checks.append(_z(op) == 100)
        if sc is not None:
            checks.append(_z(sc[0]) == 100 and _z(sc[1]) == 100)
        if pos is not None:
            checks.append(_z(pos[0]) == 0 and _z(pos[1]) == 0)
        if rot is not None:
            checks.append(_z(rot) == 0)
        is_ret = bool(checks) and all(checks)
        is_kill = ((op is not None and float(op) == 0)
                   or (sc is not None and float(sc[0]) == 0))
        if is_ret and float(a.get("duration") or 0) > 0:
            lead_ret.append(k)
        elif is_kill:
            lead_kill.append(k)
    if lead_ret or lead_kill:
        def _hist(v: list[int], topn: int = 8) -> str:
            c = collections.Counter(v)
            return "  ".join(f"{k}×{n}" for k, n in c.most_common(topn))
        pos_r = sorted(x for x in lead_ret if x > 0)
        pos_k = sorted(x for x in lead_kill if x > 0)
        lines.append(f"  ★ 归位事件 {len(lead_ret)} 条（前瞻格数）：{_hist(lead_ret)}")
        lines.append(f"     其中 >0 的中位数 = {pos_r[len(pos_r) // 2] if pos_r else '—'} 格"
                     f"（max {pos_r[-1] if pos_r else '—'}）")
        lines.append(f"  ★ 甩走事件 {len(lead_kill)} 条（前瞻格数）：{_hist(lead_kill)}")

    lines.append("")
    out: dict = {"tiles": len(ad), "actions": len(acts), "moves": len(mv),
                 "recolor": len(rc), "dec": len(dec), "n_move": len(mv),
                 "rc_total": len(rc)}
    out["leads_ret"] = lead_ret
    out["leads_kill"] = lead_kill
    # ---- 聚合（跨谱相加，用于最后归纳）----
    out["mv_single"] = sum(1 for s0, s1 in spans if s1 - s0 + 1 <= 1)
    out["mv_range20"] = sum(1 for s0, s1 in spans if s1 - s0 + 1 >= 20)
    out["mv_ang"] = sum(1 for a in mv if float(a.get("angleOffset") or 0) != 0)
    out["mv_gap0"] = sum(1 for a in mv if int(a.get("gapLength") or 0) == 0)
    out["dur_le2"] = sum(1 for a in mv if float(a.get("duration") or 0) <= 2)
    out["dur_4_8"] = sum(1 for a in mv if 4 <= float(a.get("duration") or 0) <= 8)
    out["dur_16p"] = sum(1 for a in mv if float(a.get("duration") or 0) >= 16)
    out["rc_glow"] = sum(1 for a in rc if a.get("trackColorType") == "Glow")
    out["rc_rainbow"] = sum(1 for a in rc if a.get("trackColorType") == "Rainbow")
    out["rc_pulse_fwd"] = sum(1 for a in rc if a.get("trackColorPulse") == "Forward")
    out["rc_plen10"] = sum(1 for a in rc if int(a.get("trackPulseLength") or 0) == 10)
    out["filter_grayscale"] = sum(1 for a in acts
                                  if a.get("eventType") in ("SetFilter", "SetFilterAdvanced")
                                  and a.get("filter") == "Grayscale")
    return out


def main() -> int:
    argv = sys.argv[1:]
    listing = collect()
    top = int(argv[argv.index("--top") + 1]) if "--top" in argv else 10
    lines: list[str] = []
    lines.append("=" * 100)
    lines.append("高质量特效谱用法普查（口径：文件大 ≈ 特效密）")
    lines.append(f"语料 {sum(1 for _ in listing)} 张 .adofai，最大 {listing[0][0] / 1048576:.1f} MB")
    lines.append("=" * 100)
    lines.append("")
    lines.append("---- 体积 top 30 ----")
    for sz, p in listing[:30]:
        lines.append(f"  {sz / 1048576:8.2f} MB  {p[len(os.path.commonpath([r for r in ROOTS if p.startswith(r)])) + 1:]}")
    lines.append("")

    if "--list" in argv:
        print("\n".join(lines))
        return 0

    lines.append("=" * 100)
    lines.append(f"深挖 top {top}（按体积）")
    lines.append("=" * 100)
    tot = collections.Counter()
    for i, (sz, p) in enumerate(listing[:top], start=1):
        lines.append("")
        lines.append(f"---- #{i}  {sz / 1048576:.2f} MB ----")
        lines.append(f"  {p}")
        r = analyze(p, lines)
        if r:
            for k, v in r.items():
                if isinstance(v, list):
                    tot.setdefault(k, []).extend(v)
                else:
                    tot[k] = tot.get(k, 0) + v
    lines.append("")
    lines.append("---- top 合计 ----")
    lines.append(f"  格 {tot['tiles']}  事件 {tot['actions']}（{tot['actions'] / max(1, tot['tiles']):.2f}/格）"
                 f"  MoveTrack {tot['moves']}  RecolorTrack {tot['recolor']}  "
                 f"decorations {tot['dec']}")
    lines.append("")
    lines.append("=" * 100)
    lines.append("★ 归纳用的聚合量（全部样本合计）")
    lines.append("=" * 100)
    for k in ("n_move", "mv_single", "mv_range20", "mv_ang", "mv_gap0",
              "rc_glow", "rc_rainbow", "rc_pulse_fwd", "rc_plen10", "rc_total",
              "dur_le2", "dur_4_8", "dur_16p", "filter_grayscale"):
        if k in tot:
            lines.append(f"  {k:<18}{tot[k]}")
    if tot.get("n_move"):
        nm = tot["n_move"]
        lines.append(f"  ⇒ MoveTrack 单格占比 {tot['mv_single'] / nm:.0%} · "
                     f"罩≥20格 {tot['mv_range20'] / nm:.0%} · "
                     f"angleOffset≠0 {tot['mv_ang'] / nm:.0%} · gapLength=0 {tot['mv_gap0'] / nm:.0%}")
        lines.append(f"  ⇒ duration ≤2 拍 {tot['dur_le2'] / nm:.0%} · "
                     f"4~8 拍 {tot['dur_4_8'] / nm:.0%} · ≥16 拍 {tot['dur_16p'] / nm:.0%}")
    if tot.get("rc_total"):
        rc = tot["rc_total"]
        lines.append(f"  ⇒ RecolorTrack：Glow {tot['rc_glow'] / rc:.0%} · "
                     f"Rainbow {tot['rc_rainbow'] / rc:.0%} · "
                     f"Forward {tot['rc_pulse_fwd'] / rc:.0%} · 带长10 {tot['rc_plen10'] / rc:.0%}")
    lr = sorted(x for x in tot.get("leads_ret", []) if x > 0)
    lk = sorted(x for x in tot.get("leads_kill", []) if x > 0)
    if lr:
        lines.append(f"  ⇒ 【归位】前瞻格数 中位 {lr[len(lr) // 2]} · "
                     f"10%~90% = {lr[len(lr) // 10]}~{lr[-len(lr) // 10 - 1]} · max {lr[-1]}"
                     f"（样本 {len(lr)}）")
        c = collections.Counter(lr)
        lines.append("     高频：" + "  ".join(f"{k}格×{n}" for k, n in c.most_common(12)))
    if lk:
        lines.append(f"  ⇒ 【甩走】前瞻格数 中位 {lk[len(lk) // 2]} · max {lk[-1]}（样本 {len(lk)}）")

    txt = "\n".join(lines)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(txt + "\n")
    print(f"→ {OUT}")
    print("\n".join(lines[:60]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
