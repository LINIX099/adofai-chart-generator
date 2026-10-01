# -*- coding: utf-8 -*-
"""运镜教学谱（`蟑螂个人运镜经验分享`）调研器 —— **只读**。

来源：`%USERPROFILE%\\Downloads\\213.zip` → `蟑螂个人运镜经验分享/{level,backup}.adofai`。
解压后的工作副本在 `out/_camera/213/`。

    python tools/analyze_camera_tutorial.py            # 三份报告都出
    python tools/analyze_camera_tutorial.py --no-corpus  # 跳过语料对照（省时间）

产出（都在 `out/_camera/`）：
  · `report.txt`     —— 讲解正文（144 条 `SetText.decText`）+ 事件参数形状 + 全谱时间线
  · `recipes.txt`    —— 「讲解 → 示例参数」对照表 + 统计 + RepeatEvents 套路
  · `corpus_cmp.txt` —— 教学谱的品味 vs `corpus_tuf/` 全库（533 谱 / 18.35 万条）

★ 为什么值得单独留一个分析器：这张谱是**作者亲手写的运镜教程**（不是"某张好看的谱"），
  它的参数分布与语料总体**系统性不同**（见 `docs/64`），那种差异恰恰是"该学什么"的答案；
  以后实现 ⑤e 运镜时，这份报告就是取值依据 + 回归基准。
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, OrderedDict

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TUT_DIR = os.path.join(ROOT, "out", "_camera", "213", "蟑螂个人运镜经验分享")
TUT = os.path.join(TUT_DIR, "level.adofai")
OUTDIR = os.path.join(ROOT, "out", "_camera")
CORPUS = os.path.join(ROOT, "corpus_tuf")

#: 屏幕级 / 演出级事件（调研时要一起看，镜头很少单独出现）
CAM_EV = ("MoveCamera", "MoveDecorations", "SetFilterAdvanced", "RepeatEvents",
          "PositionTrack", "MoveTrack", "SetSpeed", "Pause", "Flash",
          "ShakeScreen", "PlaySound", "Twirl", "SetText")


def load(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def fl(a) -> int:
    return int(a.get("floor") or 0)


def text_of(a) -> str:
    for k in ("decText", "text", "decorationText", "content", "message"):
        v = a.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def main() -> int:
    if not os.path.exists(TUT):
        print("找不到教学谱：%s\n（先在 out/_camera/213/ 放一份解压出来的 level.adofai）" % TUT)
        return 1
    j = load(TUT)
    acts = sorted(j.get("actions") or [], key=fl)
    os.makedirs(OUTDIR, exist_ok=True)

    probe(j, acts)
    recipes(j, acts)
    if "--no-corpus" not in sys.argv[1:]:
        corpus_cmp(acts)
    return 0


# ============================================================ ① 结构与正文
def probe(j, acts) -> None:
    lines: list[str] = []

    def w(s=""):
        lines.append(str(s))

    decs = j.get("decorations") or []
    angle = j.get("angleData") or []
    w("=" * 78)
    w("文件：蟑螂个人运镜经验分享 / level.adofai")
    w("=" * 78)
    w("angleData 长度（层数）：%d   → 取值分布 %s"
      % (len(angle), Counter(angle).most_common(5)))
    w("actions 总数：%d ；顶层 decorations：%d 个" % (len(acts), len(decs)))
    st = j.get("settings") or {}
    for k in ("song", "artist", "author", "bpm", "offset", "hitsound",
              "hitsoundVolume", "trackColorType", "backgroundColor", "planetEase",
              "separateCountdownTime", "countdownTicks"):
        if k in st:
            w("  settings.%-22s = %r" % (k, st[k]))

    w()
    w("---- 事件类型统计 ----")
    for name, c in Counter(a.get("eventType") for a in acts).most_common():
        w("  %-24s %d" % (name, c))

    w()
    w("=" * 78)
    w("A. ★ 讲解正文（`SetText.decText`，按层号排序）")
    w("=" * 78)
    texts = [(fl(a), text_of(a)) for a in acts
             if a.get("eventType") == "SetText" and text_of(a)]
    w("SetText 带字共 %d 条" % len(texts))
    for f, t in texts:
        w()
        w("── floor %-5d | %s" % (f, str(t).replace("\n", " ⏎ ")))

    w()
    w("=" * 78)
    w("B. 顶层 `decorations`（常驻参照物 / 标签）")
    w("=" * 78)
    for d in decs:
        w("  floor=%-5s %-14s tag=%-4s text=%r" % (
            d.get("floor"), d.get("eventType"), d.get("tag"),
            str(d.get("decText") or d.get("text") or "")[:44]))
        rest = {k: v for k, v in d.items()
                if k not in ("floor", "eventType", "tag", "decText", "text")}
        if rest:
            w("        %s" % json.dumps(rest, ensure_ascii=False))

    w()
    w("=" * 78)
    w("C. 每个事件的参数形状（键 + 出现过的取值）")
    w("=" * 78)
    for typ in CAM_EV:
        ev = [a for a in acts if a.get("eventType") == typ]
        if not ev:
            continue
        w()
        w("### %s   （%d 条）" % (typ, len(ev)))
        keys: OrderedDict = OrderedDict()
        for a in ev:
            for k, v in a.items():
                if k in ("eventType", "floor"):
                    continue
                keys.setdefault(k, []).append(v)
        for k, vs in keys.items():
            uniq = []
            for v in vs:
                if v not in uniq:
                    uniq.append(v)
            w("   · %-20s %s%s" % (k, uniq[:10],
                                   "  …(共 %d 种)" % len(uniq) if len(uniq) > 10 else ""))

    w()
    w("=" * 78)
    w("D. 全谱时间线（floor → 事件），只列非 SetText / 非 Twirl")
    w("=" * 78)
    for a in acts:
        if a.get("eventType") in ("SetText", "Twirl"):
            continue
        rest = {k: v for k, v in a.items()
                if k not in ("eventType", "floor", "angleOffset",
                             "dontDisable", "minVfxOnly")}
        w("  %-5s %-18s %s" % (a.get("floor"), a.get("eventType"),
                               json.dumps(rest, ensure_ascii=False)[:190]))
    _write("report.txt", lines)


# ============================================================ ② 招式表 + 统计
def recipes(j, acts) -> None:
    lines: list[str] = []

    def w(s=""):
        lines.append(str(s))

    cam = [a for a in acts if a.get("eventType") == "MoveCamera"]
    txt = [(fl(a), text_of(a)) for a in acts
           if a.get("eventType") == "SetText" and text_of(a)]
    w("=" * 78)
    w("运镜教学谱 · 招式 / 统计")
    w("=" * 78)
    w("MoveCamera %d 条 · SetText %d 条 · 层数 %d"
      % (len(cam), len(txt), len(j.get("angleData") or [])))

    w()
    w("=" * 78)
    w("1. ★ 讲解 → 示例参数（每条 SetText 到下一段文字之间发生的运镜）")
    w("=" * 78)
    bounds = [f for f, _ in txt]
    for i, (f0, t) in enumerate(txt):
        f1 = bounds[i + 1] if i + 1 < len(bounds) else 10 ** 9
        ev = [a for a in acts if f0 <= fl(a) < f1 and a.get("eventType") in CAM_EV]
        if not ev:
            continue
        w()
        w("── [%d…] %s" % (f0, str(t).replace("\n", " / ")))
        for a in ev:
            et = a.get("eventType")
            if et == "RepeatEvents":
                w("     f%-5d ⟳ Repeat %s rep=%s interval=%s "
                  "floorCount=%s onCurrent=%s tag=%s"
                  % (fl(a), a.get("repeatType"), a.get("repetitions"),
                     a.get("interval"), a.get("floorCount"),
                     a.get("executeOnCurrentFloor"), a.get("tag")))
                continue
            bits = []
            for k, short in (("duration", "dur"), ("zoom", "zoom"),
                             ("rotation", "rot"), ("position", "pos"),
                             ("relativeTo", "rel"), ("ease", "ease"),
                             ("eventTag", "tag")):
                v = a.get(k)
                if v is None or v == "" or v == [None, None]:
                    continue
                bits.append("%s=%s" % (short, json.dumps(v, ensure_ascii=False)))
            extra = {k: v for k, v in a.items()
                     if k not in ("eventType", "floor", "duration", "zoom",
                                  "rotation", "position", "relativeTo", "ease",
                                  "eventTag", "angleOffset", "dontDisable",
                                  "minVfxOnly")}
            if extra:
                bits.append(json.dumps(extra, ensure_ascii=False))
            w("     f%-5d %-16s %s" % (fl(a), et, "  ".join(bits)))

    w()
    w("=" * 78)
    w("2. ★ 统计（只算 MoveCamera）")
    w("=" * 78)

    def vals(key):
        out = []
        for a in cam:
            v = a.get(key)
            if v is not None and v != "" and v != [None, None]:
                out.append(v)
        return out

    w()
    w("ease 使用次数（共 %d 种）" % len(set(vals("ease"))))
    for k, c in Counter(vals("ease")).most_common():
        w("   %-14s %d" % (k, c))
    md = [a for a in acts if a.get("eventType") == "MoveDecorations"]
    w()
    w("MoveDecorations %d 条的 duration 分布：%s"
      % (len(md), Counter(a.get("duration") for a in md).most_common()))
    w("MoveDecorations 的 tag 分布：%s"
      % Counter(str(a.get("tag")) for a in md).most_common())
    w()
    w("duration 分布（拍）")
    for k, c in sorted(Counter(vals("duration")).items(), key=lambda x: float(x[0])):
        w("   %-8s %d" % (k, c))
    w()
    w("zoom 取值（%d 种，最小 %s 最大 %s）"
      % (len(set(vals("zoom"))), min(vals("zoom")), max(vals("zoom"))))
    for k, c in sorted(Counter(vals("zoom")).items(), key=lambda x: -x[1])[:24]:
        w("   %-8s %d" % (k, c))
    w()
    w("rotation 取值（%d 种，最小 %s 最大 %s）"
      % (len(set(vals("rotation"))), min(vals("rotation")), max(vals("rotation"))))
    for k, c in sorted(Counter(vals("rotation")).items(), key=lambda x: -x[1])[:24]:
        w("   %-8s %d" % (k, c))
    w()
    w("relativeTo 次数：" + str(Counter(vals("relativeTo")).most_common()))
    w("angleOffset 取值：" + str(Counter(vals("angleOffset")).most_common(8)))
    w()
    w("position 的 X 分量（relativeTo=Tile 时单位=格）")
    for k, c in sorted(Counter(v[0] for v in vals("position")
                               if v[0] is not None).items(), key=lambda x: -x[1]):
        w("   x=%-8s %d" % (k, c))
    w("position 的 Y 分量")
    for k, c in sorted(Counter(v[1] for v in vals("position")
                               if v[1] is not None).items(), key=lambda x: -x[1]):
        w("   y=%-8s %d" % (k, c))
    w()
    w("一副 MoveCamera 里同时动了哪几个维度")
    combo = Counter()
    for a in cam:
        keys = [k for k in ("zoom", "rotation", "position") if a.get(k) not in
                (None, "", [None, None])]
        combo["+".join(keys) if keys else "（空）"] += 1
    for k, c in combo.most_common():
        w("   %-20s %d" % (k, c))

    w()
    w("=" * 78)
    w("3. ★ RepeatEvents 的两种偷懒姿势（tag 把同一组镜头一起复制）")
    w("=" * 78)
    for a in acts:
        if a.get("eventType") != "RepeatEvents":
            continue
        w("  f%-5d %-6s rep=%-3s interval=%-3s floorCount=%-2s onCur=%-5s tag=%s"
          % (fl(a), a.get("repeatType"), a.get("repetitions"), a.get("interval"),
             a.get("floorCount"), a.get("executeOnCurrentFloor"), a.get("tag")))
        for b in acts:
            if b.get("eventTag") != a.get("tag") or b.get("eventType") != "MoveCamera":
                continue
            if abs(fl(b) - fl(a)) > 2:
                continue
            w("        ↳ f%-5d %s" % (fl(b), json.dumps(
                {k: v for k, v in b.items()
                 if k not in ("eventType", "floor", "angleOffset", "dontDisable",
                              "minVfxOnly")}, ensure_ascii=False)[:150]))
    _write("recipes.txt", lines)


# ============================================================ ③ 语料对照
def corpus_cmp(tut_acts) -> None:
    lines: list[str] = []

    def w(s=""):
        lines.append(str(s))

    files = []
    for base, _d, fs in os.walk(CORPUS):
        for f in fs:
            if f.lower().endswith(".adofai"):
                files.append(os.path.join(base, f))
    w("语料 .adofai：%d 个" % len(files))

    corpus, n_charts, n_acts = [], 0, 0
    for p in files:
        try:
            jj = load(p)
        except Exception:                                    # noqa: BLE001
            continue
        aa = jj.get("actions") or []
        cc = [a for a in aa if a.get("eventType") == "MoveCamera"]
        if cc:
            n_charts += 1
        corpus.extend(cc)
        n_acts += len(aa)
    tut = [a for a in tut_acts if a.get("eventType") == "MoveCamera"]
    w("含 MoveCamera 的谱面：%d 个；MoveCamera 总数：%d（占全部 action %.2f%%）"
      % (n_charts, len(corpus), 100.0 * len(corpus) / max(1, n_acts)))
    w("教学谱：MoveCamera %d 条" % len(tut))

    def dist(name, key, seq, top=14):
        w()
        w("### %s（%d 条）" % (name, len(seq)))
        c = Counter(str(a.get(key)) for a in seq
                    if a.get(key) not in (None, "", [None, None]))
        for k, v in sorted(c.items(), key=lambda x: -x[1])[:top]:
            w("   %-22s %5d   %5.1f%%" % (k, v, 100.0 * v / max(1, len(seq))))

    for label, seq in (("语料总体", corpus), ("教学谱", tut)):
        w()
        w("=" * 78)
        w("【%s】" % label)
        w("=" * 78)
        for key in ("ease", "duration", "relativeTo", "angleOffset",
                    "zoom", "rotation"):
            dist(key, key, seq, top=10)
        combo = Counter()
        for a in seq:
            ks = [k for k in ("zoom", "rotation", "position") if a.get(k) not in
                  (None, "", [None, None])]
            combo["+".join(ks) if ks else "（空）"] += 1
        w()
        w("### 生效字段组合")
        for k, v in combo.most_common(12):
            w("   %-22s %5d   %5.1f%%" % (k, v, 100.0 * v / max(1, len(seq))))
        w()
        w("### position x（相对 Tile 时单位=格）")
        for k, v in Counter(str(a["position"][0]) for a in seq
                            if isinstance(a.get("position"), list)
                            and a["position"][0] is not None).most_common(10):
            w("   %-22s %5d" % (k, v))

    w()
    w("=" * 78)
    w("RepeatEvents.repeatType")
    w("=" * 78)
    rc = Counter()
    for p in files:
        try:
            jj = load(p)
        except Exception:                                    # noqa: BLE001
            continue
        for a in (jj.get("actions") or []):
            if a.get("eventType") == "RepeatEvents":
                rc[str(a.get("repeatType"))] += 1
    rt = Counter(str(a.get("repeatType")) for a in tut_acts
                 if a.get("eventType") == "RepeatEvents")
    w("语料 %s" % rc.most_common())
    w("教学谱 %s" % rt.most_common())
    _write("corpus_cmp.txt", lines)


def _write(name, lines) -> None:
    p = os.path.join(OUTDIR, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("%-16s %4d 行 → %s" % (name, len(lines), p))


if __name__ == "__main__":
    raise SystemExit(main())
