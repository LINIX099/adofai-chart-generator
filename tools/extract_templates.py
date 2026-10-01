"""patterns/*.adofai（权威） → patterns/templates.json

模板 = { notes(音值/拍), travel(度), twirl, positiontrack, rounds }
notes 是身份：匹配时按「音值序列」对，travel 由 notes × 180 给出。
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import read_patterns as rp  # noqa: E402

PATS = os.path.join(ROOT, "patterns")
OUT = os.path.join(PATS, "templates.json")

# 只有这些文件是权威（用户口径：以新文档为准，旧文档只做参考）
AUTHORITATIVE = ["A_均分骨架.adofai", "B_强弱拍.adofai",
                 "C_摇摆拍子.adofai", "几种三角形.adofai"]

NAME_OVERRIDE = {
    "几种三角形.adofai:1": "等边三角形",
    "几种三角形.adofai:2": "三角形 90·60·30",
    "几种三角形.adofai:3": "三角形 90·30·60",
    "几种三角形.adofai:4": "直角三角形 前16后8",
    "几种三角形.adofai:5": "直角三角形 前8后16",
}

GEN_SHIFT = [3.0, 0.0]      # 生成器加的整段错开，不算模板内容


def extract_one(fname: str) -> list[dict]:
    path = os.path.join(PATS, fname)
    r = rp.read_file(path)
    out = []
    for floor, text, gap in r["segs"]:
        label = text.split("⏎")[0].strip()
        body, _sep = rp.split_sep(gap)
        if not body:
            continue
        if all(abs(t - 180.0) < 1e-6 for t in body):    # 「空」间隔段
            continue

        twirl = [bool((floor + k) in r["twirls"]) for k in range(len(body))]
        pos = []
        for f, dx, dy, just in r["pt"]:
            if not (floor <= f <= floor + len(body)):
                continue
            if (f == floor and not just
                    and abs(dx - GEN_SHIFT[0]) < 1e-9 and abs(dy - GEN_SHIFT[1]) < 1e-9):
                continue                                  # 生成器的错开，丢弃
            pos.append({"k": f - floor, "dx": dx, "dy": dy, "just": just})

        ms = rp.ms_of(body, r["bpms"], floor)
        notes = [t / 180.0 for t in body]
        out.append({
            "id": f"{os.path.splitext(fname)[0]}_{label}",
            "name": NAME_OVERRIDE.get(f"{fname}:{label}", f"{label}"),
            "src": fname,
            "label": label,
            "notes": notes,
            "travel": list(body),
            "twirl": twirl,
            "pos": pos,
            "rounds": 1,
            "beats": round(sum(notes), 6),
            "tags": rp.speed_tags(ms),
            "ms_at_120": [round(m * 120.0 / (r["bpm"] or 120.0), 1) for m in ms],
        })
    return out


def main() -> int:
    from core import rhythm as _rhythm  # noqa: F401
    tpls: list[dict] = []
    for f in AUTHORITATIVE:
        got = extract_one(f)
        tpls.extend(got)
        print(f"{f:<22} → {len(got)} 个模板")

    # 音值必须落在词汇表里，否则匹配端量化不到
    bad = []
    for t in tpls:
        for v in t["notes"]:
            q = _rhythm.quantize(v)
            if abs(q - v) > 1e-6:
                bad.append((t["id"], v, q))
    if bad:
        print("\n⚠ 以下音值不在 NOTE_VALUES 里，匹配会失配：")
        for i, v, q in bad:
            print(f"    {i}: {v:.6f} → 最近的是 {q:.6f}")

    # 去重（notes+twirl 相同只留第一个）
    seen, uniq = set(), []
    for t in tpls:
        key = (tuple(round(x, 6) for x in t["notes"]), tuple(t["twirl"]))
        if key in seen:
            print(f"    （去重）{t['id']}")
            continue
        seen.add(key)
        uniq.append(t)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "templates": uniq}, fh,
                  ensure_ascii=False, indent=1)

    print(f"\n{'id':<28} {'名字':<22} {'travel':<26} {'音值':<22} 快慢")
    for t in uniq:
        tv = " · ".join(f"{x:g}°" for x in t["travel"])
        nt = " · ".join(f"{x:.4g}" for x in t["notes"])
        print(f"{t['id']:<28} {t['name']:<22} {tv:<26} {nt:<22} {t['tags']}")

    print(f"\n共 {len(uniq)} 个模板  → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
