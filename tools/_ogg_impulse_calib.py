"""探针：能不能用**合成脉冲**当场标定检波器偏置（与素材无关）。

    python tools/_ogg_impulse_calib.py

在 22050Hz 上生成已知时刻的脉冲串，走**同一条检测代码**（load_as_midi snap=False），
量「检出时刻 − 真值」= 检波器的固有偏置。测三种嗓音形态：
  a) 单样本脉冲    b) 3ms 噪声爆发    c) 20ms 衰减正弦（更像乐器）
"""
from __future__ import annotations

import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audio_onsets as AO                        # noqa: E402

SR = 22050
PERIOD = 500.0      # ms
N_CLICKS = 40


def write_wav(path: str, y: np.ndarray, sr: int = SR) -> str:
    d = np.clip(y, -1.0, 1.0)
    pcm = (d * 32000).astype("<i2").tobytes()
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(pcm)
    return path


def make(kind: str) -> np.ndarray:
    n = int(SR * (PERIOD / 1000.0 * N_CLICKS + 1.0))
    y = np.zeros(n, dtype=np.float64)
    rng = np.random.default_rng(0)
    for k in range(N_CLICKS):
        i = int(k * PERIOD / 1000.0 * SR)
        if kind == "impulse":
            y[i] = 1.0
        elif kind == "noise":
            w = int(SR * 0.003)
            env = np.exp(-np.arange(w) / (SR * 0.0015))
            y[i:i + w] += 0.6 * env * rng.normal(0, 1, w)
        elif kind == "tone":
            w = int(SR * 0.020)
            env = np.exp(-np.arange(w) / (SR * 0.006))
            y[i:i + w] += 0.6 * env * np.sin(2 * np.pi * 880 * np.arange(w) / SR)
    return y


def main() -> int:
    truth = np.arange(N_CLICKS) * PERIOD
    for kind in ("impulse", "noise", "tone"):
        p = write_wav(os.path.join("out", f"_click_{kind}.wav"), make(kind))
        mf = AO.load_as_midi(p, sr=SR, hop=64, snap=False, debias=False,
                             pct=60.0)
        det = np.array(sorted({round(n.t_on_ms, 3)
                               for tr in mf.tracks for n in tr.notes}))
        sh = []
        for g in truth:
            if len(det) == 0:
                break
            j = int(np.argmin(np.abs(det - g)))
            if abs(det[j] - g) < 60:
                sh.append(det[j] - g)
        a = np.array(sh)
        if a.size:
            print(f"  {kind:8s} 检出 {len(det):4d} 匹配 {a.size:4d}  "
                  f"偏置 均值 {a.mean():+7.2f}  中位 {np.median(a):+7.2f}  "
                  f"MAD {np.median(np.abs(a - np.median(a)))*1.4826:5.2f}  "
                  f"p10 {np.percentile(a,10):+6.2f} p90 {np.percentile(a,90):+6.2f}")
        else:
            print(f"  {kind:8s} 未匹配（检出 {len(det)}）")
        # 直接用短窗 RMS 复核：脉冲的 RMS 峰在哪
        y, sr = AO._load_mono(p, SR)
        e = AO.rms_envelope(y, sr, 2.0)
        pk = []
        for g in truth:
            lo = int((g - 25.0) / 1000.0 * sr)
            hi = int((g + 55.0) / 1000.0 * sr)
            if 2 <= lo < hi < e.size - 2:
                pk.append((lo + int(np.argmax(e[lo:hi]))) / sr * 1000.0 - g)
        pk = np.array(pk)
        if pk.size:
            print(f"           RMS 峰复核 中位 {np.median(pk):+7.2f}  "
                  f"MAD {np.median(np.abs(pk - np.median(pk)))*1.4826:5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
