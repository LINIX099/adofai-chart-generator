"""按**正确口径**扫匀速段。

游戏口径（README + scrLevelMaker 都一致）：
    floor f 的转角 T[f] = (180 + a[f-1] - a[f]) % 360      ← 进这一格的转角
    带 Twirl 时 T[f] → 360 - T[f]
    floor f 的时长 dt[f] = (T[f]/180) / speed[f] × (60000/bpm)

用户的匀速公式：倍率 = 本格转角 ÷ 上一格转角  ⇒  speed[f] ∝ T[f]  ⇒  dt[f] = 常数

所以判据很简单：**dt[f] 在多大范围内是常数**。
但作者不一定逐格写事件，speed 只在 SetSpeed 那几层变 —— 所以要看不含「格内速度突变」的段，
也就是「一个 speed 档 + 转角不变」的段。

这里直接输出 dt 的游程：连续相同的 dt 有多长。
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jsonrepair import load  # noqa: E402
from _pathdata import angle_data_of  # noqa: E402
from _speeds import speeds_for  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

SAMPLES = [
    ("SKY BOX CUBE", CORPUS + r"\SKY BOX CUBE\main.adofai", 628, 1395),
    ("R lv16", CORPUS + r"\A PLUM RUSH\R lv16\main.adofai", 496, 567),
    ("FALLENERA", CORPUS + r"\FALLENERA BY MAYSNOW\main.adofai", 84, 263),
]


def travel_into(a, twirl, n):
    """T[f] = 进第 f 格的转角（含 Twirl 翻转）。长度 = n。"""
    T = [0.0] * n
    for f in range(n):
        if f == 0 or a[f] == 999 or a[f - 1] == 999:
            T[f] = 180.0 if f == 0 else 0.0
            continue
        t = (180.0 + a[f - 1] - a[f]) % 360.0
        if f in twirl:
            t = (360.0 - t) % 360.0
        T[f] = t
    return T


def main():
    for name, path, lo, hi in SAMPLES:
        o, _ = load(path)
        a, src = angle_data_of(o)
        n = len(a)
        sp = speeds_for(o, n)
        bpm = float(o.get("settings", {}).get("bpm") or 120)
        beat = 60000.0 / bpm
        acts = [e for e in (o.get("actions") or []) if e.get("active") is not False]
        tw = {int(e["floor"]) for e in acts if e.get("eventType") == "Twirl"}
        T = travel_into(a, tw, n)
    
        print("=" * 96)
        print(f"{name}  {lo}~{hi}  bpm={bpm:g}  1拍={beat:.2f}ms  {src}  格数={n}")
    
        # ① speed[f] / T[f] 的游程
        r = [sp[f] / T[f] if T[f] > 0 and sp[f] > 0 else 0.0 for f in range(n)]
        runs = []
        i = lo
        while i <= hi and i < n:
            v = round(r[i], 8)
            j = i + 1
            while j <= hi and j < n and abs(r[j] - v) < 1e-7:
                j += 1
            runs.append((i, j - 1, j - i, v))
            i = j
        good = [x for x in runs if x[2] >= 4]
        print(f"  ① speed/T 的游程：共 {len(runs)} 段，其中长度>=4 的 {len(good)} 段")
        for i0, i1, ln, v in good[:14]:
            dt = (1.0 / (180.0 * v)) * beat if v else 0
            print(f"       {i0:>5}~{i1:<5} 长 {ln:>4}   speed/T={v:.8f}  "
                  f"→ dt={dt:7.2f}ms = {dt/beat:.4f} 拍")
    
        # ② dt 的游程
        dt = [((T[f] / 180.0) / sp[f] * beat) if sp[f] > 0 else 0.0 for f in range(n)]
        cnt = collections.Counter(round(dt[f] / beat, 5) for f in range(lo, min(hi + 1, n)))
        print(f"  ② 区间内 dt（拍）分布："
              + "  ".join(f"{k:g}×{v}" for k, v in cnt.most_common(8)))
        nspot = sum(1 for f in range(lo, min(hi + 1, n)) if sp[f] == sp[f - 1])
        print(f"  ③ 区间内「速度没变」的层：{nspot}/{hi-lo+1}，"
              f"「转角没变」的层：{sum(1 for f in range(lo+1, min(hi+1,n)) if abs(T[f]-T[f-1])<1e-9)}")
        print()


if __name__ == "__main__":
    main()
