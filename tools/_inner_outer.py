"""内圈 / 外圈 判定：travel < 180 = 内圈（行星切角走短线），> 180 = 外圈（绕大圈）。

依据 `scrFloor.cs:985`：
    num = GetAngleMoved(entry, exit, !isCCW) ∈ [0, 2π)
    flag2 = num < π          → 红 swirl（小圈）
    else                     → 蓝 swirl（大圈）

用法：
    python tools/_inner_outer.py <path> <lo> <hi> [<path> <lo> <hi> ...]
    python tools/_inner_outer.py --auto        # 读 out/*/main.adofai 的 meta snow_spans
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jsonrepair import load  # noqa: E402
from _pathdata import angle_data_of  # noqa: E402
from _speeds import speeds_for, travel_into  # noqa: E402


def probe(path, lo, hi, label=None):
    o, _ = load(path)
    a, src = angle_data_of(o)
    n = len(a)
    bpm = float(o.get("settings", {}).get("bpm") or 120)
    acts = [e for e in (o.get("actions") or []) if e.get("active") is not False]
    tw = {int(e["floor"]) for e in acts if e.get("eventType") == "Twirl"}
    T = travel_into(a, tw)
    sp = speeds_for(o, n)
    hi = min(hi, n - 1)

    seg = T[lo:hi + 1]
    beats = [round((T[f] / 180.0) / sp[f], 6) for f in range(lo, hi + 1) if sp[f] > 0]
    inner = sum(1 for t in seg if t < 180.0 - 1e-9)
    outer = sum(1 for t in seg if t > 180.0 + 1e-9)
    straight = sum(1 for t in seg if abs(t - 180.0) < 1e-9)

    name = label or os.path.basename(os.path.dirname(path)) or path
    print("=" * 100)
    print(f"{name}   {lo}~{hi}  {len(seg)} 格   bpm={bpm:g}   {src}")
    print(f"  内圈(travel<180) {inner:>5} 格 {inner/len(seg)*100:5.1f}%   "
          f"外圈(>180) {outer:>5} 格 {outer/len(seg)*100:5.1f}%   "
          f"直线(=180) {straight:>5} 格 {straight/len(seg)*100:5.1f}%")
    c = collections.Counter(round(t, 3) for t in seg)
    print("  travel 取值：" + "  ".join(f"{k:g}×{v}" for k, v in c.most_common(12)))
    if beats:
        cb = collections.Counter(beats)
        print("  每格拍数：" + "  ".join(f"{k:g}×{v}" for k, v in cb.most_common(8))
              + f"   （不同取值 {len(cb)} 种）")
    print(f"  travel 序列（前 40）：{', '.join(f'{t:g}' for t in seg[:40])}")
    return inner, outer, straight, len(seg)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "--auto":
        for p in sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "out", "*", "main.adofai"))):
            try:
                o, _ = load(p)
                spans = o.get("settings", {}).get("_meta_snow_spans")
            except Exception:
                spans = None
            if not spans:
                continue
            for s in spans:
                probe(p, int(s[0]), int(s[1]))
        sys.exit(0)

    args = argv
    for i in range(0, len(args), 3):
        probe(args[i], int(args[i + 1]), int(args[i + 2]))
