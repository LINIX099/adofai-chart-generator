"""MIDI 解析器自检 —— 对 samples/ 三个样本跑一遍并打印结构。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import midi  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

for fn in sorted(os.listdir(SAMPLES)):
    if not fn.lower().endswith((".mid", ".midi")):
        continue
    m = midi.load(os.path.join(SAMPLES, fn))
    print("=" * 78)
    print(fn)
    print("  " + m.stats())
    print(f"  tempo_map = {m.tempo_map[:6]}{' ...' if len(m.tempo_map) > 6 else ''}")
    print(f"  time_sig  = {m.time_sig[:4]}")
    for t in m.tracks:
        chans = ",".join(str(c) for c in t.channels)
        lo = min((n.pitch for n in t.notes), default=0)
        hi = max((n.pitch for n in t.notes), default=0)
        span = (max((n.t_off_ms for n in t.notes), default=0.0)) / 1000.0
        kind = "DRUM" if t.is_drum_only() else "    "
        print(f"   trk{t.index} {kind} name={t.name!r:22} notes={len(t.notes):5} "
              f"ch=[{chans}] pitch={lo}-{hi} prog={t.program} span={span:7.1f}s")

    # 一致性检查：ms 单调性 + tick<->ms 往返
    bad = 0
    for t in m.tracks:
        for n in t.notes:
            if n.t_off_ms + 1e-9 < n.t_on_ms:
                bad += 1
    rt_err = max((abs(m.ticks_to_ms(m.ms_to_tick(n.t_on_ms)) - n.t_on_ms) for t in m.tracks for n in t.notes),
                 default=0.0)
    print(f"  [自检] 负时长={bad}  tick<->ms 往返最大误差={rt_err*1000:.3f} us")
