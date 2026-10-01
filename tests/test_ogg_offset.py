"""OGG 偏移回归（数值断言版）—— docs/17 §5 的判据。

    python tests/test_ogg_offset.py [--quick] [--legacy]

对「由 MIDI 合成、因此有精确真值」的 OGG 成对样本：
  ① `snap=False` 的原始检出（= 检波器偏置）
  ② 线上路径（自洽网格吸附 + 检波偏置校正）
断言：
  - **② 的 |偏移|max 与 >50ms 占比不高于 ①**（吸附不许把 onset 挪坏）
  - ② 的**均值 |偏移| ≤ 10ms**（常量偏置被标定掉）
  - ② 的 **|偏移|max ≤ 15ms**（没有漂移/错格）
  - 分段（0-30/30-60/60+ s）均值差 ≤ 5ms（治"越靠后越糟"）

`--legacy` 用修复前的吸附公式做对照（应当 FAIL），用来确认这个测试**真的能抓到 bug**。
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import audio_onsets as AO                        # noqa: E402
from core import midi as M                                 # noqa: E402

AUD = os.path.join(ROOT, "samples", "audio")
CASES = [("doublepress_demo_120.mid", "doublepress_demo_120.ogg"),
         ("doublepress_demo_90.mid", "doublepress_demo_90.ogg")]
SECTIONS = ((0, 30), (30, 60), (60, 1e9))

args = sys.argv[1:]
QUICK = "--quick" in args
LEGACY = "--legacy" in args

ok = 0
bad = 0


def chk(name: str, cond: bool, extra: str = "") -> None:
    global ok, bad
    if cond:
        ok += 1
        print(f"  ok   {name}")
    else:
        bad += 1
        print(f"  FAIL {name}  {extra}")


def truth(path: str) -> np.ndarray:
    m = M.load(path)
    return np.array(sorted({round(n.t_on_ms, 3)
                            for tr in m.tracks for n in tr.notes}), dtype=float)


def old_fit(t: np.ndarray, bpm: float, grid: int = 6,
            prefer_beat: float = 0.5, beat_tol_frac: float = 0.18) -> np.ndarray:
    beat = 60000.0 / bpm
    step = beat / grid
    snapped = np.rint(t / step) * step
    t = np.where(np.abs(t - snapped) <= 0.5 * step, snapped, t)
    bstep = beat * prefer_beat
    banchor = np.rint(t / bstep) * bstep
    t = np.where(np.abs(t - banchor) <= beat_tol_frac * bstep, banchor, t)
    return np.unique(np.round(t, 6))


def times(mf) -> np.ndarray:
    return np.array(sorted({round(n.t_on_ms, 3)
                            for tr in mf.tracks for n in tr.notes}), dtype=float)


def shifts(det: np.ndarray, gt: np.ndarray, tol: float = 80.0):
    out_g, out_s = [], []
    for g in gt:
        j = int(np.argmin(np.abs(det - g)))
        if abs(det[j] - g) < tol:
            out_g.append(g)
            out_s.append(det[j] - g)
    return np.array(out_g), np.array(out_s)


cases = CASES[:1] if QUICK else CASES
for mid, ogg in cases:
    pm, po = os.path.join(AUD, mid), os.path.join(AUD, ogg)
    if not (os.path.exists(pm) and os.path.exists(po)):
        print(f"  跳过（缺文件）{ogg}")
        continue
    print(f"\n=== {ogg}" + ("   [legacy 对照]" if LEGACY else ""))
    gt = truth(pm)
    raw_mf = AO.load_as_midi(po, sr=22050, hop=64, snap=False, debias=False,
                             pct=75.0)
    fit_mf = AO.load_as_midi(po, sr=22050, hop=64, snap=not LEGACY, pct=75.0,
                             debias=not LEGACY)
    raw, fit = times(raw_mf), times(fit_mf)
    if LEGACY:
        fit = old_fit(raw, AO.estimate_bpm(po, hop=64), grid=6)

    g_r, s_r = shifts(raw, gt)
    g_f, s_f = shifts(fit, gt)
    print(f"       ① raw  n={len(s_r)}  均值 {s_r.mean():+6.1f}  "
          f"|·|max {np.abs(s_r).max():5.1f}  >50ms {np.mean(np.abs(s_r) > 50)*100:5.1f}%")
    print(f"       ② fit  n={len(s_f)}  均值 {s_f.mean():+6.1f}  "
          f"|·|max {np.abs(s_f).max():5.1f}  >50ms {np.mean(np.abs(s_f) > 50)*100:5.1f}%")

    chk("② ≤ ①（|·|max）",
        np.abs(s_f).max() <= np.abs(s_r).max() + 1.0,
        f"{np.abs(s_r).max():.1f} → {np.abs(s_f).max():.1f}")
    chk("② ≤ ①（>50ms 占比）",
        np.mean(np.abs(s_f) > 50) <= np.mean(np.abs(s_r) > 50) + 1e-9,
        f"{np.mean(np.abs(s_r) > 50)*100:.1f}% → {np.mean(np.abs(s_f) > 50)*100:.1f}%")

    if not LEGACY:
        chk("② 常量偏置被标定掉（|均值| ≤ 10ms）", abs(s_f.mean()) <= 10.0,
            f"均值 {s_f.mean():+.1f}")
        chk("② 无漂移/错格（|·|max ≤ 15ms）", np.abs(s_f).max() <= 15.0,
            f"max {np.abs(s_f).max():.1f}")
        sec = []
        for lo, hi in SECTIONS:
            sel = (g_f >= lo * 1000) & (g_f < hi * 1000)
            if sel.sum() >= 5:
                sec.append(s_f[sel].mean())
        if len(sec) >= 2:
            spread = max(sec) - min(sec)
            print(f"       分段均值 {['%+.1f' % x for x in sec]} 极差 {spread:.1f}ms")
            chk("分段均值极差 ≤ 5ms（越靠后不再更糟）", spread <= 5.0,
                f"{spread:.1f}ms")
    else:
        chk("legacy 应当 FAIL（确认测试能抓 bug）",
            np.abs(s_f).max() > 50.0, f"max {np.abs(s_f).max():.1f}")

print(f"\n{'OK' if bad == 0 else 'FAILED'}  {ok} passed, {bad} failed")
raise SystemExit(1 if bad else 0)
