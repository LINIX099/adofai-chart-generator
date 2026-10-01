# -*- coding: utf-8 -*-
"""双押写法演示素材生成器 —— 输出 MIDI + OGG。

用途
----
给「常见双押写法」做一份可听、可编辑、时间精确的练习素材。
所有网格音都严格落在拍网格上（数学精确，不是演奏录音），
所以重音位置可以直接拿来当双押点的 ground truth 对照。

约定
----
* 一个「音」= 一个 ADOFAI 台阶候选。
* 重音（accent）= 双押点。重音 = 力度跳变 + 高音铃铛层双重标识。
* 小节 = 4 拍；拍 = 1/cbpm 分钟。

分轨（MIDI 为 format 1）
------------------------
trk0  指挥轨（tempo / 拍号 / 段落标记 marker）
trk1  节拍器（ch9 打击乐：76 高音节拍 / 42 弱拍 / 49 段落镲）
trk2  主旋律（ch0 钢琴）—— 完整乐谱，重音处力度 120，其余 72
trk3  双押重音层（ch2 木琴）—— 只包含重音点，单独一条方便独奏/静音

OGG 是同一份事件表用 numpy 合成器渲染的（不是 soundfont 音源），
好处是重音起点误差为 0。

用法
----
    python tools/make_doublepress.py                 # 120 cbpm
    python tools/make_doublepress.py --bpm 90 120    # 两个速度
    python tools/make_doublepress.py --no-ogg        # 只出 MIDI
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

import numpy as np

try:
    from scipy.signal import lfilter
except Exception:  # pragma: no cover
    lfilter = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 44100
PPQ = 480
BEATS_PER_BAR = 4
BELL_PITCH = 91          # G6，永远高于旋律，避免和旋律音混淆
CRASH_PITCH = 49
CLICK_HI = 76
CLICK_LO = 42

# ---------------------------------------------------------------- 段落定义

MEL_1 = [60, 64, 67, 72]
MEL_2 = [60, 62, 64, 65, 67, 69, 71, 72]
MEL_3 = [60, 64, 67, 62, 65, 69, 60, 64, 67, 62, 67, 69]
MEL_4 = [60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60, 62]
CONTOUR = {1: MEL_1, 2: MEL_2, 3: MEL_3, 4: MEL_4}

# 八分网格上，每小节一组的重音掩码（强弱混合段用）
M8_MIX = (
    (1, 0, 0, 1, 0, 1, 0, 0),
    (1, 0, 1, 0, 1, 0, 1, 0),
    (0, 1, 1, 0, 0, 1, 1, 0),
    (1, 1, 0, 1, 0, 1, 1, 0),
)
# 十六分网格上，每一拍一组（循环）
M16 = ((1, 0, 1, 0), (1, 1, 0, 0), (0, 1, 0, 1), (1, 1, 1, 1))

_NO = lambda pos, j, bar: False            # noqa: E731
_STRONG = lambda pos, j, bar: j == 0 and pos % 2 == 0   # noqa: E731
_WEAK = lambda pos, j, bar: j == 0 and pos % 2 == 1     # noqa: E731

SECTIONS = [
    dict(name="基准·四分",           bars=1, sub=1, acc=_NO,
         rule="每拍一个音，无重音。先锁速度。"),
    dict(name="基准·八分",           bars=1, sub=2, acc=_NO,
         rule="每半拍一个音，无重音。先锁八分网格。"),
    dict(name="双押·强拍",           bars=2, sub=2, acc=_STRONG,
         rule="八分网格；重音落在 1、3 拍（强拍）。"),
    dict(name="双押·弱拍",           bars=2, sub=2, acc=_WEAK,
         rule="八分网格；重音落在 2、4 拍（弱拍）。"),
    dict(name="双押·后半拍",         bars=2, sub=2, acc=lambda pos, j, bar: j == 1,
         rule="八分网格；重音落在每拍的后半拍（反拍）。"),
    dict(name="双押·强弱混合",       bars=2, sub=2,
         acc=lambda pos, j, bar: M8_MIX[bar % 4][pos * 2 + j] == 1,
         rule="八分网格；每小节换一个 8 位掩码，正拍/反拍/弱拍混排。"),
    dict(name="基准·三连音",         bars=1, sub=3, acc=_NO,
         rule="每拍三个音，无重音。先锁三连音网格。"),
    dict(name="双押·三连音·首",      bars=2, sub=3, acc=lambda pos, j, bar: j == 0,
         rule="三连音网格；重音固定在三连音第 1 个（正拍）。"),
    dict(name="双押·三连音·中",      bars=2, sub=3, acc=lambda pos, j, bar: j == 1,
         rule="三连音网格；重音固定在三连音第 2 个（+1/3 拍）。"),
    dict(name="双押·三连音·尾",      bars=2, sub=3, acc=lambda pos, j, bar: j == 2,
         rule="三连音网格；重音固定在三连音第 3 个（+2/3 拍）。"),
    dict(name="双押·三连音·首尾",    bars=2, sub=3, acc=lambda pos, j, bar: j in (0, 2),
         rule="三连音网格；重音在第 1、3 个 ⇒ 交替 2/3 拍与 1/3 拍间隔的双押接双押。"),
    dict(name="双押接双押 ×2",       bars=2, sub=2,
         acc=lambda pos, j, bar: (pos * 2 + j) % 4 in (0, 1),
         rule="八分网格；掩码 1100 —— 连两个双押，休两个。"),
    dict(name="双押接双押 ×3",       bars=2, sub=2,
         acc=lambda pos, j, bar: (pos * 2 + j) % 4 in (0, 1, 2),
         rule="八分网格；掩码 1110 —— 连三个双押。"),
    dict(name="双押接双押 ×4",       bars=2, sub=2, acc=lambda pos, j, bar: True,
         rule="八分网格；掩码 1111 —— 八分双押连打，无空隙。"),
    dict(name="基准·十六分",         bars=1, sub=4, acc=_NO,
         rule="每拍四个音，无重音。先锁十六分网格。"),
    dict(name="高速双押·全重",       bars=2, sub=4, acc=lambda pos, j, bar: True,
         rule="十六分网格；全部重音 —— 十六分双押连打。"),
    dict(name="高速双押·穿插",       bars=2, sub=4,
         acc=lambda pos, j, bar: M16[pos % 4][j] == 1,
         rule="十六分网格；每拍轮换掩码 1010 / 1100 / 0101 / 1111。"),
    dict(name="收尾·强拍双押",       bars=2, sub=2, acc=_STRONG,
         rule="回到双押·强拍，便于循环接回段落 3。"),
]

# 每种密度的整体增益，避免密集段听起来明显更响
DENS_GAIN = {1: 1.00, 2: 0.86, 3: 0.78, 4: 0.66}


class Note:
    __slots__ = ("t", "pitch", "vel", "layer", "dur", "sub", "sec")

    def __init__(self, t, pitch, vel, layer, dur, sub, sec):
        self.t, self.pitch, self.vel = t, pitch, vel
        self.layer, self.dur, self.sub, self.sec = layer, dur, sub, sec


def build() -> tuple[list[Note], list[dict]]:
    """返回 (音符表, 段落表)。时间单位为「拍」。"""
    notes: list[Note] = []
    marks: list[dict] = []
    t = 0.0
    bar_no = 0
    for sec in SECTIONS:
        marks.append(dict(t=t, bar_from=bar_no + 1,
                          bar_to=bar_no + sec["bars"], name=sec["name"],
                          sub=sec["sub"], bars=sec["bars"], rule=sec["rule"]))
        bar_no += sec["bars"]
        for bar in range(sec["bars"]):
            for pos in range(BEATS_PER_BAR):
                for j in range(sec["sub"]):
                    tb = t + bar * BEATS_PER_BAR + pos + j / sec["sub"]
                    acc = bool(sec["acc"](pos, j, bar))
                    step = pos * sec["sub"] + j
                    pit = CONTOUR[sec["sub"]][step % len(CONTOUR[sec["sub"]])]
                    dur = min(0.28, 0.55 / sec["sub"])
                    notes.append(Note(tb, pit, 120 if acc else 72,
                                      "mel", dur, sec["sub"], sec["name"]))
                    if acc:
                        notes.append(Note(tb, BELL_PITCH, 110,
                                          "acc", 0.34, sec["sub"], sec["name"]))
        t += sec["bars"] * BEATS_PER_BAR
    total_beats = t
    # 节拍器：每拍一下；段落首拍加镲
    marks_at = {round(m["t"], 6) for m in marks}
    click: list[Note] = []
    for b in range(int(total_beats)):
        hi = (b % BEATS_PER_BAR == 0)
        click.append(Note(float(b), CLICK_HI if hi else CLICK_LO,
                          100 if hi else 58, "click", 0.10, 1, "metronome"))
        if round(float(b), 6) in marks_at:
            click.append(Note(float(b), CRASH_PITCH, 92, "crash", 0.6, 1, "metronome"))
    notes.extend(click)
    notes.sort(key=lambda n: (n.t, n.layer))
    return notes, marks


# ---------------------------------------------------------------- MIDI 写出

def _vlq(n: int) -> bytes:
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def _text_meta(kind: int, text: str) -> bytes:
    b = text.encode("utf-8")
    return bytes([0xFF, kind]) + _vlq(len(b)) + b


def _trk(events: list[tuple[int, bytes]]) -> bytes:
    events = sorted(events, key=lambda e: e[0])
    data = bytearray()
    last = 0
    for tick, msg in events:
        data += _vlq(tick - last) + msg
        last = tick
    data += _vlq(0) + b"\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)


def write_midi(path: str, notes: list[Note], marks, bpm: float) -> None:
    us = int(round(60_000_000 / bpm))

    def tick(t: float) -> int:
        return int(round(t * PPQ))

    # --- trk0 指挥轨
    ev0: list[tuple[int, bytes]] = [(0, _text_meta(0x03, "double-press demo"))]
    ev0.append((0, b"\xFF\x51\x03" + us.to_bytes(3, "big")))
    ev0.append((0, b"\xFF\x58\x04\x04\x02\x18\x08"))   # 4/4
    for m in marks:
        ev0.append((tick(m["t"]),
                    _text_meta(0x06, f'{m["bar_from"]}-{m["bar_to"]} {m["name"]}')))
    conductor = _trk(ev0)

    # --- trk1 节拍器 / trk2 主旋律 / trk3 重音层
    ch_of = {"click": 9, "crash": 9, "mel": 0, "acc": 2}
    prog_of = {0: 0, 2: 13}
    buckets: dict[int, list[tuple[int, bytes]]] = {9: [], 0: [], 2: []}
    used_ch = set()
    for n in notes:
        ch = ch_of[n.layer]
        used_ch.add(ch)
        buckets[ch].append((tick(n.t),
                            bytes([0x90 | ch, n.pitch & 0x7F, n.vel & 0x7F])))
        buckets[ch].append((tick(n.t + n.dur),
                            bytes([0x80 | ch, n.pitch & 0x7F, 0])))
    names = {9: "metronome", 0: "melody", 2: "accent-bell"}
    tracks = [conductor]
    for ch in (9, 0, 2):
        ev: list[tuple[int, bytes]] = [(0, _text_meta(0x03, names[ch]))]
        if ch in prog_of:
            ev.append((0, bytes([0xC0 | ch, prog_of[ch]])))
        ev.extend(buckets[ch])
        tracks.append(_trk(ev))

    blob = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ)
    with open(path, "wb") as fh:
        fh.write(blob)
        for tr in tracks:
            fh.write(tr)


# ---------------------------------------------------------------- 合成器

def _rng(seed=12345):
    return np.random.default_rng(seed)


def _onepole_lp(x, a):
    if lfilter is None:
        y = np.empty_like(x)
        acc = 0.0
        for i, v in enumerate(x):
            acc += a * (v - acc)
            y[i] = acc
        return y
    return lfilter([a], [1.0, -(1.0 - a)], x)


def _freq(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def _pluck(m, dur, amp, rng):
    n = max(int(dur * SR), 32)
    t = np.arange(n) / SR
    f = _freq(m)
    y = np.zeros(n)
    for k, a, d in ((1, 1.0, 13.0), (2, 0.40, 21.0), (3, 0.22, 33.0),
                    (4, 0.10, 48.0), (5, 0.05, 68.0)):
        y += a * np.sin(2 * np.pi * f * k * t) * np.exp(-d * t)
    y *= 1.0 - np.exp(-3000.0 * t)
    # 拨弦噪声起音
    nt = min(n, int(0.004 * SR))
    if nt > 4:
        nz = _onepole_lp(rng.standard_normal(nt), 0.55)
        nz *= np.exp(-np.arange(nt) / (0.0012 * SR))
        y[:nt] += 0.30 * nz
    # 尾部短衰减，避免切出咔哒
    rel = min(n, int(0.012 * SR))
    if rel > 2:
        y[-rel:] *= np.linspace(1.0, 0.0, rel)
    return y * amp


def _bell(m, dur, amp):
    n = max(int(dur * SR), 32)
    t = np.arange(n) / SR
    f = _freq(m)
    y = np.zeros(n)
    for k, a, d in ((1.0, 1.00, 4.2), (2.01, 0.50, 7.0), (3.02, 0.25, 11.0),
                    (4.18, 0.12, 16.0), (5.43, 0.06, 22.0)):
        y += a * np.sin(2 * np.pi * f * k * t) * np.exp(-d * t)
    y *= 1.0 - np.exp(-9000.0 * t)
    rel = min(n, int(0.015 * SR))
    if rel > 2:
        y[-rel:] *= np.linspace(1.0, 0.0, rel)
    return y * amp


def _click(hi, dur, amp, rng):
    n = max(int(dur * SR), 16)
    t = np.arange(n) / SR
    if hi:
        y = (np.sin(2 * np.pi * 1180 * t) * 0.7 +
             np.sin(2 * np.pi * 2360 * t) * 0.3)
        y *= np.exp(-t * 260.0)
    else:
        nz = rng.standard_normal(n)
        nz = nz - _onepole_lp(nz, 0.35)          # 高通
        y = nz * np.exp(-t * 320.0)
    return y * amp


def _crash(dur, amp, rng):
    n = max(int(dur * SR), 32)
    t = np.arange(n) / SR
    nz = rng.standard_normal(n)
    nz = nz - _onepole_lp(nz, 0.22)
    return nz * np.exp(-t * 6.5) * amp


def render(notes: list[Note], bpm: float, sr: int = SR) -> np.ndarray:
    spb = 60.0 / bpm
    total = max(n.t for n in notes) * spb + 2.0
    L = int(total * sr) + sr // 10
    buf = np.zeros((L, 2), dtype=np.float64)
    rng = _rng(20250823)

    def add(sig, at_sec, pan, g=1.0):
        i = int(round(at_sec * sr))
        if i < 0:
            sig = sig[-i:]
            i = 0
        j = min(L, i + len(sig))
        if j <= i:
            return
        s = sig[: j - i] * g
        rl = np.sqrt(0.5 * (1.0 - pan))
        rr = np.sqrt(0.5 * (1.0 + pan))
        buf[i:j, 0] += s * rl
        buf[i:j, 1] += s * rr

    for n in notes:
        at = n.t * spb
        if n.layer == "mel":
            g = DENS_GAIN.get(n.sub, 1.0)
            amp = 0.46 if n.vel >= 100 else 0.30
            add(_pluck(n.pitch, n.dur * spb * 0.96, amp * g, rng), at, -0.12)
        elif n.layer == "acc":
            add(_bell(n.pitch, 0.34 * spb * 2.2, 0.40), at, +0.30)
        elif n.layer == "click":
            hi = n.pitch == CLICK_HI
            add(_click(hi, 0.10 * spb, 0.10 if hi else 0.055, rng), at, -0.34)
        elif n.layer == "crash":
            add(_crash(0.6 * spb, 0.18, rng), at, +0.34)
    return buf


def loudness_normalize(buf: np.ndarray, peak_db=-1.5) -> np.ndarray:
    pk = float(np.max(np.abs(buf)))
    if pk <= 0:
        return buf
    return buf * (10.0 ** (peak_db / 20.0) / pk)


def write_ogg(path: str, buf: np.ndarray, block: int = 1 << 16) -> None:
    """分块写 OGG。

    踩过的坑：libsndfile 1.2.2 用 sf.write() 一次性写 ~2.9M 帧的立体声会
    以 0xC00000FD(STATUS_STACK_OVERFLOW) 直接崩掉进程（300k 帧正常）。
    走 SoundFile + 64k 帧分块就没事。
    """
    import soundfile as sf
    x = np.ascontiguousarray(buf, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    with sf.SoundFile(path, "w", samplerate=SR, channels=x.shape[1],
                      format="OGG", subtype="VORBIS") as fh:
        for i in range(0, x.shape[0], block):
            fh.write(x[i:i + block])


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bpm", type=float, nargs="+", default=[120.0])
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "samples", "audio"))
    ap.add_argument("--no-ogg", action="store_true")
    ap.add_argument("--tag", default="doublepress_demo")
    args = ap.parse_args(argv)

    notes, marks = build()
    total_beats = max(n.t for n in notes) + 1
    os.makedirs(args.out_dir, exist_ok=True)

    n_acc = sum(1 for n in notes if n.layer == "acc")
    print(f"[谱面] {len(SECTIONS)} 段 / {int(total_beats // BEATS_PER_BAR)} 小节 / "
          f"{int(total_beats)} 拍 / 音符 {sum(1 for n in notes if n.layer=='mel')} / "
          f"重音(双押点) {n_acc}")

    for bpm in args.bpm:
        base = os.path.join(args.out_dir, f"{args.tag}_{int(bpm)}")
        write_midi(base + ".mid", notes, marks, bpm)
        print(f"[MIDI] {base}.mid  bpm={bpm:g}")
        if args.no_ogg:
            continue
        import soundfile as sf
        buf = loudness_normalize(render(notes, bpm))
        write_ogg(base + ".ogg", buf)
        dur = buf.shape[0] / SR
        print(f"[OGG ] {base}.ogg  {dur:.2f}s  peak={np.max(np.abs(buf)):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
