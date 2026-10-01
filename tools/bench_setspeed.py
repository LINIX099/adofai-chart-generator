"""标尺：EX 权威语料 / 主语料 里 SetSpeed 与 Pause 的密度。

用来回答「人类的谱面到底有多少速度事件」。
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from tools import _ex_audit as ex  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")


def load_lenient(path):
    txt = open(path, encoding="utf-8-sig").read()
    txt = re.sub(r",(\s*[}\]])", r"\1", txt)
    return __import__("json").loads(txt, strict=False)


def audit(root, label, min_tiles=100):
    rows = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(".adofai") or fn.lower().startswith("backup"):
                continue
            try:
                d = load_lenient(os.path.join(dirpath, fn))
                a = d.get("angleData")
                if not a or len(a) < min_tiles:
                    continue
                bpm = float(d.get("settings", {}).get("bpm") or 0)
                if bpm <= 0:
                    continue
            except Exception:
                continue
            n = len(a) + 1
            ss = pa = 0
            for e in d.get("actions") or []:
                et = e.get("eventType")
                if et == "SetSpeed":
                    ss += 1
                elif et == "Pause":
                    pa += 1
            rows.append((fn, n, ss, pa, bpm, bool(d.get("pathData"))))
    if not rows:
        print(f"{label}: 无数据")
        return
    tot_t = sum(r[1] for r in rows)
    tot_s = sum(r[2] for r in rows)
    tot_p = sum(r[3] for r in rows)
    nones = sum(1 for r in rows if r[2] == 0)
    print(f"\n{label}   谱 {len(rows)} 张 / {tot_t} 格")
    print(f"   SetSpeed  合计 {tot_s}   = 每 100 格 {tot_s/max(1,tot_t)*100:.2f} 个"
          f"   = 每张谱 {tot_s/len(rows):.0f} 个")
    print(f"   完全没用 SetSpeed 的谱: {nones}/{len(rows)} = {nones/len(rows)*100:.0f}%")
    print(f"   Pause     合计 {tot_p}   = 每张谱 {tot_p/len(rows):.2f} 个")
    top = sorted(rows, key=lambda r: -r[2])[:6]
    print("   SetSpeed 最多的 6 张：")
    for fn, n, ss, pa, bpm, has_path in top:
        print(f"      {ss:>5} 个 / {n:>6} 格  bpm={bpm:<9g} pathData={has_path}  {fn[:42]}")
    # 分布：每 100 格的速度事件数
    buckets = collections.Counter()
    for _fn, n, ss, pa, bpm, _hp in rows:
        r = ss / n * 100
        b = ("0" if r == 0 else "<0.5" if r < 0.5 else "<1" if r < 1
             else "<2" if r < 2 else "<5" if r < 5 else ">=5")
        buckets[b] += 1
    print("   分布（每 100 格的 SetSpeed 数 → 谱数）：" +
          "  ".join(f"{k}={buckets[k]}" for k in
                    ("0", "<0.5", "<1", "<2", "<5", ">=5") if buckets[k]))


audit(CORPUS + r"\ex", "★ EX 权威语料")
audit(CORPUS, "主语料（含 ex，只统计 >=100 格）")
