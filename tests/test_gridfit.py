"""网格拟合的单测（纯函数，不需要音频）。

    python tests/test_gridfit.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import gridfit as G                              # noqa: E402

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


def lattice(n: int, p: float, phi: float, jitter: float = 0.0,
            seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = phi + p * np.arange(n)
    if jitter:
        t = t + rng.normal(0.0, jitter, size=n)
    return np.sort(t)


print("[1] 集中度 / 相位")
p, phi = 83.3333, 12.5
t = lattice(400, p, phi)
R, ph, d = G.concentration(t, p)
chk("完美格点 R≈1", R > 0.9999, f"R={R}")
chk("相位复原", abs((ph - phi) % p) < 1e-3 or abs((ph - phi) % p - p) < 1e-3,
    f"φ={ph}")
chk("残差≈0", np.abs(d).max() < 1e-6, f"max={np.abs(d).max()}")

t2 = lattice(400, p, phi, jitter=8.0, seed=1)
R2, _, _ = G.concentration(t2, p)
chk("加 8ms 抖动 R 下降但仍有结构", 0.3 < R2 < 0.999, f"R={R2}")

rng = np.random.default_rng(2)
trand = np.sort(rng.uniform(0, 60000, 400))
Rr, _, _ = G.concentration(trand, p)
chk("纯随机 R 低", Rr < 0.15, f"R={Rr}")

print("[2] 周期精修：把 0.15% 的周期误差修回来")
true_p = 41.6667
t3 = lattice(1500, true_p, 3.0, jitter=2.0, seed=3)
hint = true_p * 1.00154                      # 线上那 0.154% 的误差
p_fix, R_fix, _ = G.refine_period(t3, hint)
chk("精修后周期误差 < 0.005%", abs(p_fix / true_p - 1) < 5e-5,
    f"p={p_fix:.6f} vs {true_p:.6f} ({(p_fix / true_p - 1) * 100:+.4f}%)")
chk("精修后 R 上升", R_fix > G.concentration(t3, hint)[0],
    f"{R_fix:.4f} vs {G.concentration(t3, hint)[0]:.4f}")
chk("不精修时 R 明显更低", G.concentration(t3, hint)[0] < 0.95)

print("[3] 漂移量：0.154% 误差在 64s 上会漂多少（修复前后）")
n = 1500
t_end = true_p * (n - 1)
drift_before = abs(t_end * (1.0 / 1.00154 - 1.0))
drift_after = abs(t_end * (1.0 / (p_fix / true_p) - 1.0))
chk("修复前漂移 > 50ms", drift_before > 50.0, f"{drift_before:.1f}ms")
chk("修复后漂移 < 2ms", drift_after < 2.0, f"{drift_after:.2f}ms")
print(f"       修前 {drift_before:.1f}ms → 修后 {drift_after:.2f}ms")

print("[4] fit_grid 的门槛")
good = lattice(500, 83.3333, 10.0, jitter=4.0, seed=4)
f = G.fit_grid(good, 83.3333)
chk("干净数据 ok", f.ok and f.conf > 0.6, f"{f.describe()}")
chk("rms 小", f.rms < 12.0, f"rms={f.rms:.2f}")

noise = np.sort(np.random.default_rng(5).uniform(0, 60000, 500))
fn = G.fit_grid(noise, 83.3333)
chk("噪声不通过门槛", not fn.ok, f"{fn.describe()}")

few = np.array([100.0, 250.0])
ff = G.fit_grid(few, 83.3333)
chk("太少数据不通过", not ff.ok, f"{ff.describe()}")

f0 = G.fit_grid(np.zeros(0), 83.3333)
chk("空输入不炸", (not f0.ok) and f0.n == 0)

print("[5] 吸附：只动小残差，远的原样保留")
lat = lattice(200, 100.0, 0.0)
with_far = np.append(lat, 5450.0)          # 离最近格点 50ms > 上限 35ms
s = G.snap_lattice(with_far, 100.0, 0.0, max_move_frac=0.35)
chk("栅格上不动", np.all(np.isin(np.round(lat, 6), np.round(s, 6))))
chk("远离格点的原样（5450 还在）", 5450.0 in np.round(s, 6).tolist(), f"{s[-1]}")
s2 = G.snap_lattice(np.array([0.0, 30.0]), 100.0, 0.0, max_move_frac=0.35)
chk("30ms 残差被挪到最近格点 0", list(np.round(s2, 6)) == [0.0], f"{list(s2)}")
s2b = G.snap_lattice(np.array([60.0]), 100.0, 0.0, max_move_frac=0.35)
chk("60ms 残差超出上限不挪", abs(s2b[0] - 60.0) < 1e-9, f"{s2b}")
s3 = G.snap_lattice(np.array([45.0]), 100.0, 0.0, max_move_frac=0.35)
chk("45ms 超出上限不挪", abs(s3[0] - 45.0) < 1e-9, f"{s3}")
s4 = G.snap_lattice(np.array([45.0]), 100.0, 0.0, max_move_frac=0.5)
chk("上限放宽后可挪", abs(s4[0] - 100.0) < 1e-9 or abs(s4[0]) < 1e-9, f"{s4}")

print("[6] 相位平移 = 相对时间不变")
a = lattice(300, 83.3333, 0.0)
b = lattice(300, 83.3333, 17.3)
chk("两组 Δt 完全相同", np.allclose(np.diff(a), np.diff(b), atol=1e-6))

print("[7] bpm/period 互推")
f2 = G.GridFit(period=41.6017, phase=0.0, conf=1.0, rms=0.0, vmax=0.0,
               hit=1.0, n=10, period_hint=41.6017, ok=True)
chk("grid=6 反推 bpm", abs(f2.bpm_for(6) - 60000.0 / (41.6017 * 6)) < 1e-9)
chk("bpm_for(1) == bpm", abs(f2.bpm - f2.bpm_for(1)) < 1e-9)

# ------------------------------------------------------------------ [8]
# 端到端复刻「靠后位置随机偏移」（docs/17）：合成 64s 真值 + 检波器常量提前量
# + 估计 BPM 的 0.15% 周期误差，比较「旧吸附」与「新自洽网格吸附」。
print("[8] 端到端：复刻 50~100ms 的靠后偏移，验证修复")


def nearest_shift(det, gt, tol=80.0):
    out = []
    for g in gt:
        j = int(np.argmin(np.abs(det - g)))
        if abs(det[j] - g) < tol:
            out.append(det[j] - g)
    return np.array(out)


def old_fit(t, bpm, grid=6, prefer_beat=0.5, beat_tol_frac=0.18):
    """修复前的吸附公式（docs/17 §2②）。"""
    beat = 60000.0 / bpm
    step = beat / grid
    snapped = np.rint(t / step) * step
    t = np.where(np.abs(t - snapped) <= 0.5 * step, snapped, t)
    bstep = beat * prefer_beat
    banchor = np.rint(t / bstep) * bstep
    t = np.where(np.abs(t - banchor) <= beat_tol_frac * bstep, banchor, t)
    return np.unique(np.round(t, 6))


rng = np.random.default_rng(11)
unit = 60000.0 / 240.0 * 2.0                 # 125ms 音符单位
k = np.sort(rng.choice(np.arange(1, 520), size=330, replace=False))
gt = k * unit
bias = -35.5                                  # 检波器系统性提前量
raw_t = np.sort(gt + bias + rng.normal(0, 1.5, size=len(gt)))
raw_t = raw_t[raw_t > 0]

bpm_est = 240.371                             # librosa 估出的（0.15% 偏）
old = old_fit(raw_t, bpm_est)
new_grid = G.fit_grid(raw_t, G.period_of(bpm_est, 6))
new = G.snap_lattice(raw_t, new_grid.period, new_grid.phase, max_move_frac=0.35)

s_raw, s_old, s_new = (nearest_shift(x, gt) for x in (raw_t, old, new))
print(f"       raw   |·|max {np.abs(s_raw).max():6.1f}  >50ms {np.mean(np.abs(s_raw) > 50)*100:5.1f}%")
print(f"       old   |·|max {np.abs(s_old).max():6.1f}  >50ms {np.mean(np.abs(s_old) > 50)*100:5.1f}%")
print(f"       new   |·|max {np.abs(s_new).max():6.1f}  >50ms {np.mean(np.abs(s_new) > 50)*100:5.1f}%")
print(f"       网格  hint={G.period_of(bpm_est, 6):.4f} → fit={new_grid.period:.4f} "
      f"R={new_grid.conf:.3f} dev={(new_grid.period / G.period_of(bpm_est, 6) - 1)*100:+.3f}%")

chk("旧吸附确实把 onset 挪坏（复刻到 bug）",
    np.abs(s_old).max() > 50.0 and np.mean(np.abs(s_old) > 50) > 0.05,
    f"max={np.abs(s_old).max():.1f} >50ms={np.mean(np.abs(s_old) > 50)*100:.1f}%")
chk("新吸附 ② ≤ ①（判据）",
    np.abs(s_new).max() <= np.abs(s_raw).max() + 1.0,
    f"{np.abs(s_raw).max():.1f} → {np.abs(s_new).max():.1f}")
chk("新吸附 >50ms 占比不高于旧", np.mean(np.abs(s_new) > 50) <= np.mean(np.abs(s_old) > 50))
chk("新吸附 >50ms 占比 ≈ 0", np.mean(np.abs(s_new) > 50) < 0.02,
    f"{np.mean(np.abs(s_new) > 50)*100:.1f}%")
chk("新吸附偏置回升到常量（无漂移）",
    abs(np.abs(s_new).max() - np.abs(s_new).min()) < 15.0,
    f"min={np.abs(s_new).min():.1f} max={np.abs(s_new).max():.1f}")

# 与线上入口一致：fit_onsets 传共享 lattice
from core import audio_onsets as AO                        # noqa: E402
new2 = AO.fit_onsets(raw_t, bpm_est, grid=6,
                     lattice=(new_grid.period, new_grid.phase))
chk("fit_onsets(lattice=…) 与直接吸附一致",
    np.allclose(np.unique(np.round(new, 6)), np.unique(np.round(new2, 6)), atol=1e-6))

print(f"\n{'OK' if bad == 0 else 'FAILED'}  {ok} passed, {bad} failed")
raise SystemExit(1 if bad else 0)
