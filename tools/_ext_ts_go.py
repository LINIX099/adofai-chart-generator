# -*- coding: utf-8 -*-
"""临时：保真模式下真跑一遍，量实际拟合精度（跑完可删）。

    python tools/_ext_ts_go.py

判据（比起上一次那个错的按位置对齐）：
  · 我们谱面的层间隔 diff(times)  vs  输入间隔 diff(ts)
  · 这是**间隔对间隔**，去掉了 offset/lead 的影响
"""
import bisect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import solve as S                                     # noqa: E402
from core.onsets import Onset                                   # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录


def nearest_errs(pool, want):
    """每个 `want` 到 `pool` 里**最近**那个的距离。

    ★ 必须这么量：谱面层数和音数不必一一对应（会插层/休止），
      按**下标**对齐的话，中间多一层就把尾巴整体错位 —— 我上一版就是这么错的。
    """
    pool = sorted(pool)
    out = []
    for t in want:
        i = bisect.bisect_left(pool, t)
        best = None
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(pool):
                d = abs(pool[j] - t)
                best = d if best is None else min(best, d)
        out.append(best if best is not None else float("inf"))
    return out

F = (_HOME + r"\.dsh\attachments\v1\files\0a"
     r"\0aed72d9d890d040d5c6834bb8dc527618f8b0b8ec21d0bdaa1d1ef34f912149"
     r"\Flower_Dance-DJ_OKAWARI-1974307.txt")
ts = sorted(float(s) for s in open(F, encoding="utf-8") if s.strip())
ons = [Onset(t_ms=t, velocity=100, pitch=60) for t in ts]
din = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]

CASES = [
    ("自动（默认量化）", {}),
    ("自动 + 关量化", {"quantize_rhythm": False}),
    ("手动 397.35 + 关量化", {"base_bpm": 397.35, "quantize_rhythm": False}),
    ("手动 397.35 + 关量化 + 关模板/三连/自然段",
     {"base_bpm": 397.35, "quantize_rhythm": False, "use_templates": False,
      "use_triplet_engine": False, "use_natural_spans": False, "emit_twirl": False}),
]
print("输入 %d 个时间戳 · 跨度 %.0f ms" % (len(ts), ts[-1] - ts[0]))
print("=" * 96)
for tag, kw in CASES:
    ch = S.solve(ons, S.SolveParams(**kw))
    times = S.times_from_chart(ch)
    tr = [f.travel for f in ch.floors]
    ks = [f.speed_k for f in ch.floors]
    st = sum(1 for x in tr if abs(x - 180.0) < 1e-6)
    dout = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    e = sorted(nearest_errs(times, ts))          # ★ 就近匹配，不按下标
    n = len(e)
    print("%-44s bpm %-8.2f 层 %-5d 直线 %5.1f%% 换档 %-4d"
          % (tag, ch.base_bpm, len(ch.floors), 100.0 * st / max(1, len(tr)),
             sum(1 for i in range(1, len(ks)) if ks[i] != ks[i - 1])))
    print("%-44s 就近匹配 %d 个音：中位 %.3f ms · 90分位 %.3f · 最大 %.3f"
          % ("", n, e[n // 2], e[int(n * .9)], e[-1]))
    print("%-44s 误差 >1ms: %d (%.1f%%) · >5ms: %d (%.1f%%) · >25ms: %d"
          % ("", sum(1 for x in e if x > 1), 100.0 * sum(1 for x in e if x > 1) / n,
             sum(1 for x in e if x > 5), 100.0 * sum(1 for x in e if x > 5) / n,
             sum(1 for x in e if x > 25)))
    print("-" * 96)
