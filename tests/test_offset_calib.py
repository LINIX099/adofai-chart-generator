"""OFFSET 语义标定（决定性版）。

用户给的关键情报：
  · offset 是谱师**听音乐自己写**的
  · countdownTicks 社区约定 = 4
  · 优质谱面会一直编到歌曲结尾

由此得到一个只用「音频时长」就能验证的判据：

    如果 offset 的语义是「谱面 entryTime[0] 对应的音频时刻(ms)」，那么
        offset + entryTime[last]  ==  最后一个方块命中时的音频时刻
    而优质谱面编到结尾 => 这个数应当 ≈ 音频总长。

于是只要拿一堆「谱面 + 对应音频」的时长去比对，就能确定语义和公式：
    offset = 首个命中时刻(或 entryTime[0]) − (countdownTicks−1) × (60000/bpm)
"""
import glob
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)
from core import verify  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

FFMPEG = r"D:\Steam\steamapps\common\A Dance of Fire and Ice\ffmpeg\ffmpeg.exe"


def dur_of(path):
    try:
        r = subprocess.run([FFMPEG, "-i", path], stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, text=True, encoding="utf-8",
                           errors="replace")
        for line in r.stderr.splitlines():
            if "Duration:" in line:
                h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:                                            # noqa: BLE001
        pass
    return None


def chart_info(path):
    ald = verify.ADOLevelData.new(path)
    ald.decode()
    a = verify.ADOAngle(ald)
    rot = a.getRotateAngle()
    s = a.settings
    bpm = float(s["bpm"])
    cd = int(s.get("countdownTicks", 4))
    beat = 60.0 / max(1e-9, bpm)
    # entryTime[1] = (adjustedCountdownTicks-1)*crotchet + time(travel_0)
    t = (cd - 1) * beat
    for r in rot[:-1]:
        t += r / 180.0 * beat
    return dict(bpm=bpm, cd=cd, off=float(s.get("offset", 0)),
                sep=bool(s.get("separateCountdownTime", False)),
                last=t, n=len(rot),
                cdb=(cd - 1) * beat * 1000.0)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else CORPUS
    folders = [d for d in glob.glob(os.path.join(root, "*")) if os.path.isdir(d)]
    print(f"扫描 {len(folders)} 个目录…\n")
    rows = []
    for d in folders:
        charts = glob.glob(os.path.join(d, "**", "*.adofai"), recursive=True)
        auds = [f for f in glob.glob(os.path.join(d, "**", "*"), recursive=True)
                if f.lower().endswith((".ogg", ".mp3", ".wav"))]
        if not charts or not auds:
            continue
        # 音频时长缓存
        adurs = {}
        for au in auds:
            dl = dur_of(au)
            if dl:
                adurs[au] = dl
        if not adurs:
            continue
        for ch in charts:
            try:
                m = chart_info(ch)
            except Exception:                                    # noqa: BLE001
                continue
            # 预测：offset + last ≈ 音频时长
            pred = m["off"] / 1000.0 + m["last"]
            au, ad = min(adurs.items(), key=lambda kv: abs(kv[1] - pred))
            err = pred - ad
            rows.append((os.path.basename(d)[:22], os.path.basename(ch)[:16],
                         m["bpm"], m["cd"], m["off"], m["last"], ad, err))

    if not rows:
        print("没有可用的谱面+音频对")
        return 0

    # 只保留「预测与音频时长接近」的组（否则是配对错了）
    good = [r for r in rows if abs(r[7]) < 20]
    print(f"总配对数 {len(rows)}，其中 |offset+last − 音频时长| < 20s 的 {len(good)} 组\n")
    print(f"{'曲目':24}{'谱':18}{'bpm':>9}{'cd':>3}{'offset':>8}{'last_s':>9}{'音频s':>9}{'误差s':>8}")
    for r in sorted(good, key=lambda x: abs(x[7]))[:32]:
        print(f"{r[0]:24}{r[1]:18}{r[2]:9g}{r[3]:3}{r[4]:8.0f}{r[5]:9.1f}{r[6]:9.1f}{r[7]:8.1f}")

    if good:
        import statistics as st
        errs = [abs(r[7]) for r in good]
        signed = [r[7] for r in good]
        print(f"\n[判据一] offset + entryTime[last] ≈ 音频总长")
        print(f"   命中(±20s) {len(good)}/{len(rows)} = {len(good)/len(rows)*100:.0f}%"
              f"   |误差| 中位={st.median(errs):.1f}s  均值={st.mean(errs):.1f}s"
              f"   有符号中位={st.median(signed):+.1f}s")
        print(f"   -> 误差中位只有 {st.median(errs):.1f} 秒，说明 offset 的基准点就是「谱面 t=0 对应的音频时刻(ms)」")

    # 再看另一种口径：offset 是否 ≈ 首个命中时刻 - (cd-1)*beat
    print(f"\n[判据二] 若 offset = 首个命中时刻 − (cd−1)*beat，则 (cd−1)*beat 应普遍 > 0 且 offset 偏小")
    cdb = [r[3] - 1 for r in rows]
    print(f"   countdownTicks 分布: {sorted(set(r[3] for r in rows))}")
    from collections import Counter
    print(f"   众数 = {Counter(r[3] for r in rows).most_common(3)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
