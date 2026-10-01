"""生成「OFFSET / 倒计时 标定包」——一次性把官方时间约定钉死。

为什么不用音频互相关去反推：我试过了（tests/test_offset_calib.py），
真实谱面的音频 onset 包络信噪比太差，提升只有 1.2~1.4 倍，不足以下结论。
所以改成**让用户看一次**：做几张小到肉眼可数的测试谱，咔哒声用不同音高区分，
你只要告诉我「第一次要按的时候，是第几声咔哒」，我就能反推出全部约定。

产出：out/_calib_pack/
  cal_A/ ... cal_D/     每张谱一个目录（main.adofai + main.wav）
  读数说明.txt
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)

from core import onsets as O, solve as S, synth, writer  # noqa: E402

OUT = os.path.join(_HERE, "out", "_calib_pack")
N_TILES = 9
BPM = 60.0                     # 1 拍 = 1 秒；travel=180 => 每层正好 1 秒
SR = 44100

VARIANTS = [
    ("cal_A", dict(offset=0.0,    cd=1, sep=False), 0.0,
     "A：offset=0  countdownTicks=1  separateCountdownTime=false  音频从第 0 秒就有咔哒"),
    ("cal_B", dict(offset=0.0,    cd=4, sep=False), 0.0,
     "B：offset=0  countdownTicks=4  separateCountdownTime=false"),
    ("cal_C", dict(offset=0.0,    cd=4, sep=True),  0.0,
     "C：offset=0  countdownTicks=4  separateCountdownTime=true"),
    ("cal_D", dict(offset=2000.0, cd=1, sep=False), 2.0,
     "D：offset=2000  countdownTicks=1  音频前面有 2 秒静音（第 1 声咔哒在第 2 秒）"),
    ("cal_E", dict(offset=-1000.0, cd=1, sep=False), 0.0,
     "E：offset=-1000  countdownTicks=1  音频从第 0 秒就有咔哒"),
]


def make_click_track(lead_s: float) -> np.ndarray:
    """10 声咔哒，每声间隔 1 秒，音高逐个升高（便于口头描述第几声）。"""
    total = int((lead_s + N_TILES + 2.0) * SR) + SR
    buf = np.zeros(total, dtype=np.float32)
    for k in range(N_TILES + 1):
        t0 = int((lead_s + k) * SR)
        seg = synth._tone(synth._midi_to_freq(60 + k), 0.16, 0.85, SR)
        i1 = min(len(buf), t0 + len(seg))
        buf[t0:i1] += seg[:i1 - t0]
    p = float(np.max(np.abs(buf)))
    if p > 0:
        buf = buf / p * 0.9
    return buf


def write_wav(buf: np.ndarray, path: str) -> None:
    import wave
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((buf * 32767.0).astype("<i2").tobytes())


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    ons = [O.Onset(t_ms=1000.0 * i, velocity=100, pitch=60 + i) for i in range(N_TILES)]
    ch = S.solve(ons, S.SolveParams(base_bpm=BPM,
                                    speed_tiers=(1,), allow_set_speed=False,
                                    allow_twirl=False, twirl_mode="off"))
    travels = sorted(set(round(f.travel, 6) for f in ch.floors))
    print(f"9 层，travel 取值 = {travels}（应当只有 180）")
    print(f"        a[0]={ch.floors[0].angle}（应当是 0）  travel[0]={ch.floors[0].travel}")

    lines = ["ADOFAI OFFSET / 倒计时 标定包",
             "=" * 60,
             "",
             "每个 cal_X 目录里是一张 9 层的小谱 + 它的音频。",
             "音频是 10 声「咔哒」，每声间隔正好 1 秒，音高逐个升高（第 1 声最低）。",
             "谱面每一层也正好 1 秒（bpm=60，travel=180=直线），所以理论上：",
             "",
             "    第 1 次需要按键的时刻，应当正好落在某一声咔哒上。",
             "",
             "请在游戏里逐个加载（把整个 cal_X 目录放进 Documents\\A Dance of Fire and Ice\\Worlds\\ 或直接用编辑器打开 main.adofai），",
             "然后告诉我下面这一句话就够了：",
             "",
             "    「cal_X：第一次要按的时候，是第 ___ 声咔哒」",
             "    （如果完全对不上、或者根本没有咔哒，也直接说）",
             "",
             "顺便也说一下：",
             "    · 这一局开头有没有数拍子的倒计时？几下？",
             "    · 音频是立刻开始，还是延迟了一段时间才开始？",
             "",
             "有了这几句话，我就能把 offset 的符号和基准点一次性钉死，不用再猜。",
             "",
             "各变体的参数：",
             ""]

    for name, cfg, lead, desc in VARIANTS:
        d = os.path.join(OUT, name)
        os.makedirs(d, exist_ok=True)
        write_wav(make_click_track(lead), os.path.join(d, "main.wav"))
        writer.write(
            ch, os.path.join(d, "main.adofai"),
            song=f"calib_{name}", artist="-", author="calibration",
            song_filename="main.wav", offset_ms=cfg["offset"],
            extra_settings={"countdownTicks": cfg["cd"],
                            "separateCountdownTime": cfg["sep"],
                            "previewSongStart": 0, "previewSongDuration": 6},
        )
        lines.append(f"  {name}  offset={cfg['offset']:g}  countdownTicks={cfg['cd']}  "
                     f"separateCountdownTime={cfg['sep']}  音频前置静音={lead:g}s")
        lines.append(f"          {desc}")
        print(f"  {name}: {os.path.join(d, 'main.adofai')}")

    with open(os.path.join(OUT, "读数说明.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n读出说明: " + os.path.join(OUT, "读数说明.txt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
