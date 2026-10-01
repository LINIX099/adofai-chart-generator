"""OGG/WAV 路径的「靠后位置随机偏移」体检。

用法：
    python tools/diag_ogg_offset.py <ground_truth.mid> <audio.ogg> [--hop 64]
                                    [--bpm 120] [--legacy] [--grid 6]

原理：拿**有精确 ground truth 的音频**（例如从 MIDI 合成的 OGG），
把「检出 + 吸附」后的 onset 与 MIDI 音符逐一对齐，量化：

  ① 原始检出偏置（不含吸附）—— 反映检波器本身的偏置
  ② 吸附后偏移（按时间分段，看是否随位置变化）—— 线上实际产出
  ③ 网格及其自洽性（周期精修前后、估计 BPM vs 真值）

`--legacy` 走修复前的旧吸附（用估计 BPM 直接建网格），用来做 A/B。

判据（docs/17 §5）：**② 的 |·|max 与 >50ms 占比必须不高于 ①**。
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audio_onsets as AO                        # noqa: E402
from core import gridfit as GF                             # noqa: E402
from core import midi as M                                 # noqa: E402

SECTIONS = ((0, 30), (30, 60), (60, 120), (120, 1e9))


def truth(path: str) -> np.ndarray:
    m = M.load(path)
    return np.array(sorted({round(n.t_on_ms, 3)
                            for tr in m.tracks for n in tr.notes}), dtype=float)


def _old_fit(t: np.ndarray, bpm: float, grid: int, prefer_beat: float = 0.5,
             tol_frac: float = 0.5, beat_tol_frac: float = 0.18) -> np.ndarray:
    """修复前的吸附（就是 docs/17 里那段代码）：估计 BPM 直接建网格，无相位。"""
    if len(t) == 0 or bpm <= 0:
        return t
    beat = 60000.0 / bpm
    step = beat / max(1, int(grid))
    snapped = np.rint(t / step) * step
    t = np.where(np.abs(t - snapped) <= tol_frac * step, snapped, t)
    if prefer_beat > 0.0:
        bstep = beat * prefer_beat
        banchor = np.rint(t / bstep) * bstep
        t = np.where(np.abs(t - banchor) <= beat_tol_frac * bstep, banchor, t)
    return np.unique(np.round(t, 6))


def detected(audio: str, *, hop: int, bpm: float | None, snap: bool,
             grid: int = 6, legacy: bool = False, debias: bool = True):
    """→ (onset 时刻数组, MidiFile)。legacy=True 时套修复前的吸附公式。"""
    mf = AO.load_as_midi(audio, sr=22050, hop=hop, bpm=bpm,
                         snap=(snap and not legacy), pct=75.0, grid=grid,
                         debias=debias)
    t = np.array(sorted({round(n.t_on_ms, 3)
                         for tr in mf.tracks for n in tr.notes}), dtype=float)
    if legacy and snap:
        t = _old_fit(t, float(bpm), grid)
    return t, mf


def stats(det: np.ndarray, gt: np.ndarray, tol: float = 80.0):
    shifts = []
    for g in gt:
        j = int(np.argmin(np.abs(det - g)))
        if abs(det[j] - g) < tol:
            shifts.append((g, det[j] - g))
    if not shifts:
        return None
    gs = np.array([s[0] for s in shifts])
    ss = np.array([s[1] for s in shifts])
    return gs, ss


def report(label: str, det: np.ndarray, gt: np.ndarray, tol: float = 80.0):
    r = stats(det, gt, tol)
    if r is None:
        print(f"  {label:26s} 无匹配（检出 {len(det)}）")
        return None
    gs, ss = r
    print(f"  {label:26s} 匹配 {len(ss):4d}/{len(gt):4d} | "
          f"均值 {ss.mean():+7.1f}  中位 {np.median(ss):+7.1f}  "
          f"|·|max {np.abs(ss).max():6.1f}  >50ms {np.mean(np.abs(ss) > 50)*100:5.1f}%")
    for lo, hi in SECTIONS:
        sel = (gs >= lo * 1000) & (gs < hi * 1000)
        if sel.sum():
            tag = f"{lo}-{hi if hi < 1e9 else '+'}s"
            print(f"       {tag:>10s} n={sel.sum():4d}  均值 {ss[sel].mean():+7.1f}  "
                  f"|·|max {np.abs(ss[sel]).max():6.1f}  (>50ms "
                  f"{np.mean(np.abs(ss[sel]) > 50)*100:4.1f}%)")
    return gs, ss


def verdict(raw: tuple, fit: tuple) -> bool:
    """② ≤ ① ⇒ True。"""
    if raw is None or fit is None:
        return False
    _, a = raw
    _, b = fit
    ok = (np.abs(b).max() <= np.abs(a).max() + 1.0
          and np.mean(np.abs(b) > 50) <= np.mean(np.abs(a) > 50) + 1e-9)
    print(f"  判据 ②≤①： |·|max {np.abs(a).max():.1f}→{np.abs(b).max():.1f}  "
          f">50ms {np.mean(np.abs(a) > 50)*100:.1f}%→"
          f"{np.mean(np.abs(b) > 50)*100:.1f}%   {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mid")
    ap.add_argument("audio")
    ap.add_argument("--hop", type=int, default=64)
    ap.add_argument("--grid", type=int, default=6)
    ap.add_argument("--bpm", type=float, default=None,
                    help="不传则用 estimate_bpm（复现线上行为）")
    ap.add_argument("--legacy", action="store_true",
                    help="旧吸附（估计 BPM 直接建网格，不做周期精修）")
    ap.add_argument("--no-debias", action="store_true",
                    help="关掉检波偏置自标定（A/B 用）")
    a = ap.parse_args()
    deb = not a.no_debias

    gt = truth(a.mid)
    print(f"ground truth: {len(gt)} 个音符，最后 {gt[-1]:.1f} ms  ({a.mid})")
    bpm_est = a.bpm if a.bpm else AO.estimate_bpm(a.audio, hop=a.hop)
    print(f"BPM: 估计 {bpm_est:.3f}"
          + (f" / 真值 {a.bpm:g}" if a.bpm else "")
          + ("   [legacy 模式]" if a.legacy else ""))

    print("\n① 原始检出（不吸附）—— 反映检波器本身的偏置")
    raw, _ = detected(a.audio, hop=a.hop, bpm=bpm_est, snap=False, grid=a.grid,
                      debias=False)
    st_raw = report("raw", raw, gt)

    print("\n② 吸附后 —— 线上实际产出的 onset")
    fit, mf2 = detected(a.audio, hop=a.hop, bpm=bpm_est, snap=True,
                        grid=a.grid, legacy=a.legacy, debias=deb)
    st_fit = report("snapped", fit, gt)

    r = verdict(st_raw, st_fit)
    print(f"  结论：{'PASS（吸附没有把 onset 挪坏）' if r else 'FAIL（吸附把 onset 挪坏了）'}")

    if not a.legacy:
        print("\n③ 网格自洽性 + 检波偏置")
        gf = getattr(mf2, "grid_fit", None)
        bi = getattr(mf2, "bias_info", {}) or {}
        if gf is not None:
            hint = GF.period_of(bpm_est, a.grid)
            print(f"  估计 BPM {bpm_est:9.3f} → 网格步长 {hint:7.3f}ms "
                  f"（该网格 R={GF.concentration(raw, hint)[0]:.3f}）")
            print(f"  自洽拟合 {gf.bpm_for(a.grid):9.3f} → 网格步长 "
                  f"{gf.period:7.3f}ms  R={gf.conf:.3f}  rms={gf.rms:.2f}  "
                  f"ok={gf.ok} {gf.reason}")
            dr = GF.concentration(raw, gf.period)[2]
            print(f"  残差（相对自洽网格）：rms={np.sqrt((dr**2).mean()):.2f}ms  "
                  f"max={np.abs(dr).max():.2f}ms")
            print(f"  ⇒ tempo_map 用自洽 BPM：{mf2.bpm0:.3f}")
        print(f"  检波偏置：{getattr(mf2, 'detector_bias', 0.0):+.2f}ms  "
              f"n_kept={bi.get('n_kept', 0)}  iqr={bi.get('iqr', 0.0):.1f}ms  "
              f"ok={bi.get('ok')} {bi.get('reason', '')}")
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(main())
