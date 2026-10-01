"""生成「三连音听感」demo：MIDI + WAV + OGG + 一张能直接在游戏里打开的谱面。

设计（120 BPM，1 拍 = 500ms）——每段 8 拍本体 + 4 拍喘息，喘息只有底鼓：

    段  r 序列（每格占几拍）              听感
    0   1 ×8                            纯四分，基准
    1   1/3 ×3 每组                     三连音，一拍三下，均匀
    2   2/3 · 1/3  ×4                   摇摆：长—短   ← 这就是 2/3
    3   1/3 · 2/3  ×4                   倒装：短—长
    4   1/2 · 1/2  ×4                   对照：均匀两下
    5   1/3×3 与 2/3·1/3 交替 4 拍      A/B 直接对比

谱面口径：`travel = 180 × r`（speed 1），于是每格 dt 精确 = r 拍，
和音频**逐格对齐**（offset = 0，谱面前留一格 = 音频前留一拍 = 500ms）。

输出目录（本身就是 ADOFAI 的曲目目录，整个丢进 Worlds 即可）：
    out/_triplet_demo/main.adofai
    out/_triplet_demo/triplet_demo.ogg
    out/_triplet_demo/triplet_demo.wav
    out/_triplet_demo/triplet_demo.mid
"""
from __future__ import annotations

import json
import os
import struct
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from core import writer  # noqa: E402
from core.solve import Chart, Floor  # noqa: E402

BPM = 120.0
PPQ = 480
BEAT_MS = 60000.0 / BPM
SR = 44100
OUT = os.path.join(_ROOT, "out", "_triplet_demo")
NAME = "triplet_demo"
F = 1 / 3.0

# ---- 每段叠在谱面上的 r 序列（8 拍）----
SECTIONS: list[tuple[str, list[float]]] = [
    ("0 基准 纯四分", [1.0] * 8),
    ("1 三连音 1/3×3", [F] * 24),
    ("2 摇摆 2/3+1/3", ([2 * F, F] * 8)),
    ("3 倒装 1/3+2/3", ([F, 2 * F] * 8)),
    ("4 对照 1/2+1/2", [0.5] * 16),
    ("5 A/B 摇摆 ↔ 倒装", ([2 * F, F, 2 * F, F, F, 2 * F, F, 2 * F] * 2)),
]
REST_BEATS = 4.0
LEAD_BEATS = 1.0


def build_onsets():
    """返回 [(起始拍, r 拍, 属于哪段, 是不是图音)]（时间轴从 1 拍起）。"""
    ons: list[tuple[float, float, str, bool]] = []
    t = LEAD_BEATS
    for nm, rs in SECTIONS:
        for k, r in enumerate(rs):
            ons.append((t, r, nm, True))
            t += r
        # 喘息：4 拍，每拍一下，只出底鼓（图音关掉）
        for k in range(4):
            ons.append((t, 1.0, "喘息", False))
            t += 1.0
    for k in range(4):                      # 收尾 4 拍
        ons.append((t, 1.0, "收尾", True))
        t += 1.0
    return ons, t


# ------------------------------------------------------------------ MIDI
def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def write_midi(path: str, events: list[tuple[float, float, int, int]], total_beats: float):
    """events = [(起始拍, 时长拍, 音高, 通道)]"""
    def track(evs):
        evs = sorted(evs)
        data, last = bytearray(), 0
        for tick, msg in evs:
            data += _vlq(tick - last) + msg
            last = tick
        data += _vlq(0) + b"\xFF\x2F\x00"
        return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)

    def on(ch, pitch, vel):
        return bytes([0x90 | ch, pitch, vel])

    def off(ch, pitch):
        return bytes([0x80 | ch, pitch, 0])

    us = int(round(60_000_000 / BPM))
    cond = bytearray()
    cond += b"\xFF\x03" + bytes([7]) + b"demo"
    cond += b"\xFF\x51\x03" + struct.pack(">I", us)[1:]
    cond += b"\xFF\x58\x04" + bytes([4, 2, 24, 8])
    cond += _vlq(int(total_beats * PPQ)) + b"\xFF\x2F\x00"

    fig, puls = [], []
    for b, dur, pitch, ch in events:
        t0 = int(round(b * PPQ))
        t1 = int(round((b + dur) * PPQ))
        vel = 100 if ch == 0 else 62
        (fig if ch == 0 else puls).append((t0, on(ch, pitch, vel)))
        (fig if ch == 0 else puls).append((t1, off(ch, pitch)))

    blob = (b"MThd" + struct.pack(">IHHH", 6, 1, 3, PPQ)
            + b"MTrk" + struct.pack(">I", len(cond)) + bytes(cond)
            + track(fig) + track(puls))
    with open(path, "wb") as fh:
        fh.write(blob)


# ------------------------------------------------------------------ 合成
def _tone(freq, dur_s, sr=SR, decay=16.0, click=0.35):
    n = max(1, int(dur_s * sr))
    t = np.arange(n) / sr
    env = np.exp(-t * decay)
    body = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
    c = click * np.exp(-t * 220.0) * np.random.default_rng(7).standard_normal(n) * 0.3
    return (body * env + c).astype(np.float32)


def render(onsets, total_beats, sr=SR):
    total_s = total_beats * BEAT_MS / 1000.0 + 0.6
    buf = np.zeros(int(total_s * sr) + 1, dtype=np.float32)
    for b, dur, pitch, ch in onsets:
        f = 1046.5 if ch == 0 else 130.81
        amp = 0.85 if ch == 0 else 0.30
        d = min(dur * BEAT_MS / 1000.0, 0.5) if ch == 0 else 0.16
        w = _tone(f, d, sr, decay=18.0 if ch == 0 else 26.0)
        s = int(round(b * BEAT_MS / 1000.0 * sr))
        buf[s:s + len(w)] += w * amp
    buf = buf * (0.9 / max(1e-9, float(np.abs(buf).max())))
    return buf


# ------------------------------------------------------------------ 谱面
def make_chart(onsets) -> Chart:
    """travel = 180×r，speed 1。第 0 层开局站位，末尾补一格。"""
    fl = [Floor(travel=180.0, bpm=BPM, twirl=False, turn=0.0, heading=90.0,
                angle=0.0, speed_k=1.0)]
    a = 0.0
    for b, r, _nm, _fig in onsets:
        tv = 180.0 * r
        a = (a + 180.0 - tv) % 360.0
        fl.append(Floor(travel=tv, bpm=BPM, twirl=False, turn=0.0,
                        heading=90.0 - a, angle=a, speed_k=1.0))
    a = (a + 180.0 - 180.0) % 360.0
    fl.append(Floor(travel=180.0, bpm=BPM, twirl=False, turn=0.0,
                    heading=90.0 - a, angle=a, speed_k=1.0))
    return Chart(base_bpm=BPM, floors=fl, meta={})


def main():
    os.makedirs(OUT, exist_ok=True)
    onsets, total_beats = build_onsets()

    events = [(b, r, 84 if fig else 48, 0 if fig else 1)
              for b, r, _n, fig in onsets]
    # 底鼓铺满每一拍
    nb = int(total_beats) + 1
    events += [(float(k), 1.0, 48, 1) for k in range(nb)]

    mid = os.path.join(OUT, NAME + ".mid")
    write_midi(mid, events, total_beats)

    buf = render(onsets, total_beats)
    import soundfile as sf

    def write_chunked(path, data, **kw):
        """★ 必须分块：该环境上 `sf.write()` 写 150 万点会把 C 栈写爆（stack overflow）。"""
        with sf.SoundFile(path, "w", SR, 1, **kw) as fh:
            for i in range(0, len(data), 65536):
                fh.write(data[i:i + 65536])

    wav = os.path.join(OUT, NAME + ".wav")
    ogg = os.path.join(OUT, NAME + ".ogg")
    write_chunked(wav, buf, format="WAV", subtype="PCM_16")
    write_chunked(ogg, buf, format="OGG", subtype="VORBIS")

    ch = make_chart(onsets)
    p = writer.write_dir(ch, OUT, name="main", audio_src=ogg,
                         song="三连音听感 demo", artist="(generated)",
                         author="ADOFAI Chart Generator",
                         offset_ms=0.0, countdown_ticks=4)

    print(f"onset {len(onsets)} 格   总长 {total_beats:.2f} 拍 = "
          f"{total_beats * BEAT_MS / 1000:.1f}s   BPM {BPM:g}")
    print(f"  谱面 {p}   ({len(ch.floors)} 层)")
    for f in (mid, wav, ogg):
        print(f"  {f}   ({os.path.getsize(f)} bytes)")
    print()
    t = LEAD_BEATS
    print(f"  {'时间':>8}  {'起始拍':>7}  段")
    for nm, rs in SECTIONS:
        print(f"  {t*BEAT_MS/1000:>7.2f}s  {t:>7.2f}  {nm}   （+{sum(rs):g} 拍）")
        t += sum(rs) + REST_BEATS
    print(f"  收尾 {t*BEAT_MS/1000:.2f}s")

    # 谱面 ↔ 音频 对齐自检
    from core import verify
    ons_ms = [b * BEAT_MS for b, _r, _n, _f in onsets]
    vr = verify.verify_file(p, ons_ms, tol_ms=1.0, lead_floors=1)
    print(f"  [校验] {vr.summary()}")


if __name__ == "__main__":
    main()
