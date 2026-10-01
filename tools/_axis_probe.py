"""一次性探针：确定 `payload.entry` / `payload.hit` 与「播放器音频时刻」的轴关系。

要回答的问题（决定「播放选中格」该 seek 到哪）：
    audio_ms(floor i) == entry[i] ?
    audio_ms(floor i) == entry[i] + offset ?
    audio_ms(floor i) == entry[i] + offset + lead_ms ?

判据：自动 offset 下，第 i 个 onset 的音频时刻应该等于「该 onset 对应层的 entryTime + offset」
（`core/solve.check_offset` 的预测式）。所以逐个比 onset[i].t_ms 与候选式，看残差。

    python tools/_axis_probe.py [samples/xxx.mid]
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sidecar import schema as SC                            # noqa: E402
from sidecar.session import Session                          # noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "samples", "MemoryLocked.mid")
    s = Session()
    info = s.load(path)
    st = SC.defaults()
    st["tracks_checked"] = list(info.get("default_tracks_checked") or [])
    st["current_track"] = int(info.get("default_current_track") or 0)
    st["auto_offset"] = True

    r = s.rebuild(st)
    if not r.get("ok"):
        print("rebuild failed:", r.get("msg"))
        return 1

    p = r["payload"]
    off = float(r["auto_offset"] or 0.0)
    lead = float(p["lead_ms"])
    total = float(p["total_ms"])
    entry = p["entry"]
    hit = p["hit"]
    on = [o.t_ms for o in s.onsets]

    print(f"file         = {os.path.basename(path)}")
    print(f"n_onsets     = {len(on)}")
    print(f"n_floors     = {len(entry)}")
    print(f"auto_offset  = {off:.3f} ms")
    print(f"lead_ms      = {lead:.3f} ms")
    print(f"total_ms     = {total:.3f} ms")
    print(f"onsets[0]    = {on[0]:.3f} ms      onsets[-1] = {on[-1]:.3f} ms")
    print(f"entry[0]     = {entry[0]:.3f} ms      entry[-1]  = {entry[-1]:.3f} ms")
    print(f"hit[0]       = {hit[0]:.3f} ms      hit[-1]    = {hit[-1]:.3f} ms")
    print()

    n = min(len(on), len(hit))
    for label, f in (
        ("hit[i]          ", lambda i: hit[i]),
        ("hit[i] + offset ", lambda i: hit[i] + off),
        ("hit[i]+offset+ld", lambda i: hit[i] + off + lead),
    ):
        res = [on[i] - f(i) for i in range(n)]
        mean = sum(res) / len(res)
        mad = max(abs(x - mean) for x in res)
        print(f"{label}: mean residual = {mean:+9.3f} ms   max dev = {mad:7.3f} ms")

    print()
    print("结论：mean residual ≈ 0 的那一行就是正确的 seek 映射。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
