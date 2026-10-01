"""真 · EX 权威标尺。

以前 `adofaipumian\\ex` 之所以给出「直线 45.2% / Twirl 2.1 / SetSpeed 1.39」，
是因为 71 个 .adofai 里只有 11 个能解析，而且里面大半是 **20~70 格的碎片**
（`level1.adofai` / `level2.adofai` … 那些是作者的子关卡）。

修好宽松 JSON 之后，把**13 张主谱**（每个 `<n>-EX …/level.adofai`）单独拎出来算，
才是能当标尺的那份数据。

    python tools/ex_benchmark.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus_report import load_any, one_chart  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

EX_DIR = CORPUS + r"\ex"


def main():
    files = sorted(glob.glob(os.path.join(EX_DIR, "*", "level.adofai")))
    print(f"找到 {len(files)} 个 level.adofai")
    charts, skipped = [], []
    for p in files:
        title = os.path.basename(os.path.dirname(p))
        try:
            o, _k = load_any(p)
        except Exception as e:                                   # noqa: BLE001
            skipped.append((title, f"解析失败 {e}"))
            continue
        r = one_chart(o)
        if r is None or r["n"] < 100:
            n = len(o.get("angleData") or []) if isinstance(o, dict) else 0
            skipped.append((title, f"只有 {n} 格（可能用 pathData）"))
            continue
        r["title"] = title
        charts.append(r)
        print(f"  {r['n']:>5} 格  SS={r['setspeed']:>3}  TW={r['twirl']:>3}  "
              f"直线={r['straight']/r['n']*100:4.1f}%  {title}")

    T = sum(c["n"] for c in charts)
    if not T:
        print("没有可用主谱")
        return
    pct = lambda k: sum(c[k] for c in charts) / T * 100      # noqa: E731

    print(f"\n{'='*78}")
    print(f"真 · EX 权威语料：{len(charts)} 谱 / {T} 格")
    if skipped:
        print(f"  跳过 {len(skipped)}：")
        for t, why in skipped:
            print(f"     {t[:50]:<52} {why}")
    print(f"\n{'指标':<18}{'EX 真值':>10}   {'对照：TUF P4 档':>16}")
    print(f"{'直线 (180°)':<18}{pct('straight'):>9.1f}%   {'41.5%':>16}")
    print(f"{'多押 (Δt≤35ms)':<18}{pct('multipress'):>9.1f}%   {'4.0%':>16}")
    print(f"{'SetSpeed /100格':<18}{sum(c['setspeed'] for c in charts)/T*100:>9.2f}    {'3.17':>16}")
    print(f"{'Twirl /100格':<18}{sum(c['twirl'] for c in charts)/T*100:>9.2f}    {'7.93':>16}")
    print(f"{'Pause /张':<18}{sum(c['pause'] for c in charts)/len(charts):>9.2f}    {'1.41':>16}")
    print(f"{'midspin 占比':<18}{sum(c['midspin'] for c in charts)/T*100:>9.2f}%")
    print(f"{'速度是 2 的幂':<18}{pct('pow2'):>9.1f}%   {'89.3%':>16}")
    print(f"{'音值落 1/12 网格':<18}{pct('on12'):>9.1f}%   {'86.7%':>16}")
    med = sorted(c["median_dt"] for c in charts)
    print(f"{'单格时长中位':<18}{med[len(med)//2]:>9.1f}ms")


if __name__ == "__main__":
    main()
