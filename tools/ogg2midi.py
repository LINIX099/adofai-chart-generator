"""OGG/WAV → MIDI（音头版）。也用来快速体检一份音频的音头质量。

用法：
    python tools/ogg2midi.py song.ogg                 # 写 song.onset.mid + 报告
    python tools/ogg2midi.py song.ogg out.mid --bpm 180 --grid 12
    python tools/ogg2midi.py song.ogg --probe 71 72.5  # 只看某一段的音头
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import audio_onsets as A   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ogg")
    ap.add_argument("out", nargs="?", default=None)
    ap.add_argument("--bpm", type=float, default=0.0, help="0 = 自动估")
    ap.add_argument("--grid", type=int, default=12, help="吸附网格（每拍几格）")
    ap.add_argument("--hop", type=int, default=64)
    ap.add_argument("--min-gap", type=float, default=40.0, help="同音头最小间隔 ms")
    ap.add_argument("--pct", type=float, default=75.0,
                    help="保留最强的前 (100-pct)%% 峰值；越大越稀疏")
    ap.add_argument("--sweep", default="", help="逗号分隔的 pct 列表，只报数量")
    ap.add_argument("--track", type=int, default=0, help="to_smf 用哪条轨")
    ap.add_argument("--split", default="hp+bands",
                    choices=("none", "hp", "bands", "hp+bands"))
    ap.add_argument("--no-snap", action="store_true")
    ap.add_argument("--probe", nargs=2, type=float, metavar=("LO_S", "HI_S"))
    args = ap.parse_args()

    bpm = args.bpm or None
    if args.sweep:
        y, sr = A._load_mono(args.ogg)
        for p in [float(x) for x in args.sweep.split(",")]:
            mf = A.load_as_midi(args.ogg, hop=args.hop, bpm=args.bpm or None,
                                grid=args.grid, snap=not args.no_snap,
                                min_gap_ms=args.min_gap, pct=p, split=args.split)
            cnt = [len(t.notes) for t in mf.tracks]
            print(f"  pct={p:<5g} 各轨={cnt}  合计={sum(cnt)}"
                  f"  每秒={sum(cnt) / (mf.length_ms / 1000):.1f}")
        return

    if args.probe:
        y, sr = A._load_mono(args.ogg)
        bpm = args.bpm or A.estimate_bpm((y, sr), sr, hop=args.hop)
        raw = A.detect_onsets(y, sr, hop=args.hop, min_gap_ms=args.min_gap,
                              pct=args.pct)
        sn = A.snap_to_grid(raw, bpm, grid=args.grid)
        lo, hi = args.probe[0] * 1000, args.probe[1] * 1000
        print(f"{args.ogg}  时长 {len(y)/sr:.2f}s  bpm≈{bpm:.3f}  grid={args.grid}")
        print(f"  原始音头 {len(raw)} 个   吸附后 {len(sn)} 个")
        for tag, arr in (("原始", raw), ("吸附", sn)):
            sel = arr[(arr >= lo) & (arr <= hi)]
            print(f"  -- {tag} 窗口 {args.probe[0]}~{args.probe[1]}s：{len(sel)} 个")
            prev = None
            for t in sel:
                d = "" if prev is None else f"  Δ={t - prev:7.1f}"
                print(f"     {t:9.1f}ms{d}")
                prev = t
        return

    mf = A.load_as_midi(args.ogg, hop=args.hop, bpm=bpm, grid=args.grid,
                        snap=not args.no_snap, min_gap_ms=args.min_gap,
                        pct=args.pct, split=args.split)
    print(A.describe(mf))
    ts = np.array([n.t_on_ms for n in mf.tracks[0].notes])
    if len(ts) > 1:
        d = np.diff(ts)
        vals, cnt = np.unique(np.round(d, 1), return_counts=True)
        print("  Δ 直方图（前 12）:")
        for v, c in sorted(zip(vals, cnt), key=lambda kv: -kv[1])[:12]:
            print(f"     {v:8.1f}ms ×{c}")
    out = args.out or (os.path.splitext(args.ogg)[0] + ".onset.mid")
    A.to_smf(mf, out, track_index=args.track)
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
