"""TUF 语料 vs 我们的输出 —— 一张表看完。

    python tools/tuf_report.py

分层维度：
  ① TUF 全库（下载的那 625 张高通关谱）
  ② 按难度档分层（P3-P7 / P9-P12 / P15-P17 / G 系 / U 系 …）
  ③ 对照：用户自己的语料 `adofaipumian` + `ex`
  ④ 对照：我们 `out/` 里生成的谱
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus_report import report  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TUF = os.path.join(ROOT, "corpus_tuf", )

# 难度子目录 → 展示名（按 PGU 档位由易到难粗分）
BANDS = [
    ("P1", "P1"), ("P2", "P2"), ("P3", "P3"), ("P4", "P4"), ("P5", "P5"),
    ("P6", "P6"), ("P7", "P7"), ("P8", "P8"), ("P9", "P9"), ("P10", "P10"),
    ("P11", "P11"), ("P12", "P12"), ("P13", "P13"), ("P14", "P14"),
    ("P16", "P16"), ("P17", "P17"), ("P18", "P18"), ("P19", "P19"),
    ("P20", "P20"),
    ("G1", "G1"), ("G3", "G3"), ("G5", "G5"), ("G7", "G7"), ("G11", "G11"),
    ("G12", "G12"), ("G17", "G17"), ("G19", "G19"),
    ("U4", "U4"),
]


def main():
    rows = []
    print("=" * 78)
    print("TUF 高通关谱（clears>=20 全难度 + P3-P7 clears>=10 + top120）")
    rows.append(report(TUF, "TUF 全部"))
    for sub, label in BANDS:
        p = os.path.join(TUF, sub)
        if os.path.isdir(p) and any(f.endswith(".adofai") for f in os.listdir(p)):
            rows.append(report(p, f"TUF {label}"))

    print("\n" + "=" * 78)
    print("对照语料")
    for p, label in ((CORPUS, "社区主语料 303 张"),
                     (CORPUS + r"\ex", "EX 目录全文件"),
                     (os.path.join(ROOT, "out"), "我们 out/ 输出")):
        if os.path.isdir(p):
            rows.append(report(p, label))

    # 真 · EX 标尺：只取 13 张主谱（把 20~70 格的碎片滤掉）
    rows.append(report(os.path.join(CORPUS + r"\ex",
                                    "*", "level.adofai"),
                       "★ 真·EX 权威 (13主谱)", min_tiles=100))

    print("\n" + "=" * 78)
    print("汇总表")
    hdr = (f"{'语料':<22}{'谱':>5}{'格':>8}{'直线':>8}{'多押':>8}"
           f"{'SS/100':>8}{'Pause/张':>9}{'Twirl/100':>10}{'2幂':>7}{'1/12格':>8}")
    print(hdr)
    print("-" * len(hdr))
    for a in rows:
        if not a:
            continue
        print(f"{a['tag']:<22}{a['charts']:>5}{a['tiles']:>8}"
              f"{a['straight']*100:>7.1f}%{a['multipress']*100:>7.1f}%"
              f"{a['setspeed_per100']:>8.2f}{a['pause_per_chart']:>9.2f}"
              f"{a['twirl_per100']:>10.2f}{a['pow2']*100:>6.1f}%"
              f"{a['on12']*100:>7.1f}%")


if __name__ == "__main__":
    main()
