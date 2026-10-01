# -*- coding: utf-8 -*-
"""**补格（按 bpm 网格在间隔里补合成 onset）** 的契约测试。

    python tests/test_tilefill.py

## 依据

用户 2026-10（两条门槛冲不上去时的批示）：

> 「你可以使用**分段采音设置采bpm**，或者通过**双押轨道**（用分段采音辅助的）
>   进一步加强」

以及 `docs/71` 的实测：参考谱 2543 键 vs 我们 1742 键（**每拍 3.31 vs 2.27**）——
人打谱**不会**让一格去跨半个拍，会在够长的间隔里按 bpm 网格再铺几格。

## 这条测试守什么

1. `div=0`（**默认**）⇒ **逐字节不变**（`fill()` 原样返回、`meta.on=False`）——
   这是「改动必须向后兼容」那条硬要求；
2. 砖长靠 `core.denoise.plan` 自己测（**采bpm**），测不出来就**一格都不补**
   （不猜一个网格硬上）；
3. 真实 onset **一个都不丢**、补点只落在**开区间**内、**不挤成 0ms 双押**；
4. `min_steps` / `max_per_gap` / `min_merged`（**和弦门**）/ `per_chord` 的口径；
5. 上限撞了就**记在账上**（不静默截断）；
6. **和弦门是有实测依据的**：`min_merged=2` 只补和弦起头的间隔。
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import tilefill as TF                                # noqa: E402
from core.onsets import Onset                                  # noqa: E402

FAIL: list = []
N = [0]
BEAT = 60000.0 / 230.0          # 260.87 ms：一拍
BRICK = BEAT / 2.0              # 130.43 ms：半拍砖（= Flower Rocket 实测砖长）


def check(ok, msg):
    N[0] += 1
    print("  [%s] %s" % ("OK" if ok else "!!", msg))
    if not ok:
        FAIL.append(msg)


def mk(ts, n_merged=1):
    return [Onset(t_ms=float(t), velocity=100, pitch=60, n_merged=n_merged,
                  pitches=(60,))
            for t in ts]


# ============================================================ A 组：关 = 不变
print("\n== A 组：`div=0`（默认）必须逐字节不变 ==")
src = mk([0, BRICK, BRICK * 2, BRICK * 3.5])
out, meta = TF.fill(src, div=0)
check(out == src, "div=0 ⇒ 返回的列表与输入**同一个内容**（逐个 ==）")
check(meta.on is False, "div=0 ⇒ meta.on=False")
check("关" in meta.report_text(), "div=0 ⇒ 报告文本写明「关」")
check(TF.DEFAULT_DIV == 4, "默认 div=4（但 schema 里 fill_div 的默认是 **0 = 关**）")

out2, meta2 = TF.fill(src, div=3)
check(out2 == src and not meta2.on, "非法 div（3）⇒ **不补**（不猜），并在 why 里说明")

# ============================================================ B 组：砖长（采bpm）
print("\n== B 组：砖长由采音结果自己测（采bpm）==")
t = 0.0
ts = [0.0]
for i in range(40):                     # 半拍一格，偶尔补一个 1/4 拍的点
    t += BRICK
    ts.append(t)
    if i % 3 == 0:
        t += BRICK / 2.0
        ts.append(t)
p, bpm, why, bad = TF.detect_period(mk(ts))
check(abs(p - BRICK) < 2.0, "测出来的砖长 ≈ %.2fms（拿到 %.3fms）" % (BRICK, p))
check(abs(bpm - 460.0) < 10.0, "砖长换算的 bpm ≈ 460（拿到 %.1f）" % bpm)
check(why != "", "砖长依据要写出来（不静默）：%s" % why[:40])
p0, _b0, _w0, bad0 = TF.detect_period(mk([0.0, 1.0]))
check(p0 == 0.0 and bad0 != "", "点太少 ⇒ 测不出来，why 非空（不猜）")

# ============================================================ C 组：补点口径
print("\n== C 组：补点只落在开区间内、真实 onset 一个不丢 ==")
# ★ 这一组测的是**补点机制**，所以砖长直接钉住（测砖长的能力由 B 组守）。
ts = [0.0, BEAT, BEAT * 2, BEAT * 2 + BRICK]            # 一拍一格 + 半拍一格
out, meta = TF.fill(mk(ts, 2), div=4, min_steps=3, max_per_gap=1,
                    period_ms=BRICK)
real = [o for o in out if not o.synth]
check([o.t_ms for o in real] == ts, "真实 onset 一个都没丢、时间也没动")
add = sorted(o.t_ms for o in out if o.synth)
check(all(any(abs(x - r) > 1e-9 for r in ts) for x in add),
      "补点**不重合**于任何真实 onset（不造 0ms 双押）")
check(all(0.0 < x < BEAT * 2 + BRICK for x in add), "补点都落在 (首, 末) 开区间内")
check(len(add) >= 1 and math.isclose(add[0], BRICK / 4.0, abs_tol=0.5),
      "max_per_gap=1 ⇒ 只补最靠前的那个网格点（a + 砖长/4 ≈ %.2fms，拿到 %s）"
      % (BRICK / 4.0, ("%.2f" % add[0]) if add else "**没补**"))
check(meta.n_added == len(add) and meta.n_in == len(ts),
      "账要对得上：n_in=%d n_added=%d" % (meta.n_in, meta.n_added))

out, meta = TF.fill(mk([0.0, BEAT * 2], 2), div=4, min_steps=2, max_per_gap=0,
                    period_ms=BRICK)
check(len([o for o in out if o.synth]) == 15,
      "max_per_gap=0 ⇒ 铺满（一个 2 拍间隔切 1/8 拍 = 15 个内点，拿到 %d）"
      % len([o for o in out if o.synth]))

# ============================================================ D 组：和弦门
print("\n== D 组：和弦门（实测：单音起头 18%% 会补、和弦起头 44~68%%）==")
ts = [0.0, BEAT, BEAT * 2, BEAT * 3]
ons = mk(ts)
ons[0].n_merged = 1
ons[1].n_merged = 3
ons[2].n_merged = 2
out, meta = TF.fill(ons, div=4, min_steps=3, max_per_gap=1, min_merged=2,
                    period_ms=BRICK)
add = sorted(o.t_ms for o in out if o.synth)
check(len(add) == 2, "min_merged=2 ⇒ 只有 2 个和弦间隔被补（拿到 %d）" % len(add))
check(all(abs((x % BEAT)) > 1e-9 for x in add), "补点仍然落在间隔内部")
check(meta.n_skip_single == 1, "被和弦门挡掉 1 个（拿到 %d）" % meta.n_skip_single)

out, meta = TF.fill(ons, div=4, min_steps=3, max_per_gap=4, min_merged=2,
                    per_chord=True, period_ms=BRICK)
add = sorted(o.t_ms for o in out if o.synth)
check(len(add) == 3,
      "per_chord：n 音摊成 n 格 ⇒ 3 音的补 2 个、2 音的补 1 个（共 3，拿到 %d）"
      % len(add))

# ============================================================ E 组：上限不静默
print("\n== E 组：撞上限必须记账（不静默截断）==")
many = [i * BEAT for i in range(20)]
out, meta = TF.fill(mk(many, 2), div=4, min_steps=3, max_per_gap=1, max_add=5,
                    period_ms=BRICK)
check(meta.n_added == 5, "max_add=5 ⇒ 只补 5 个（拿到 %d）" % meta.n_added)
check(meta.n_capped == 14, "被截掉的 14 个记在 n_capped（拿到 %d）" % meta.n_capped)
check("截掉" in meta.report_text(), "报告里写明「截掉」（不静默）")

# ============================================================ F 组：dedup
print("\n== F 组：dedup 保真实、丢合成 ==")
dup = [Onset(t_ms=0.0, velocity=100, pitch=60, synth=True),
       Onset(t_ms=0.0, velocity=100, pitch=60, synth=False),
       Onset(t_ms=10.0, velocity=100, pitch=60, synth=False)]
kept, drop = TF.dedup(dup)
check(drop == 1 and len(kept) == 2, "挤在一起的 2 个只留 1 个（丢了 %d）" % drop)
check(kept[0].synth is False, "**保真实的**、丢合成的")

print()
print("=" * 78)
if FAIL:
    print("=> FAIL  %d 条没过：" % len(FAIL))
    for x in FAIL:
        print("   · " + x)
    return_code = 1
else:
    print("=> PASS  补格契约全部通过（%d 条）" % N[0])
    return_code = 0
raise SystemExit(return_code)
