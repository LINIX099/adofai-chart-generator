# -*- coding: utf-8 -*-
"""**osu!mania 谱面 → MIDI**（零依赖 SMF 写出器）。

为什么需要它（`docs/63` §10）：
  · 找遍公开渠道，`HyuN - Grin` **没有现成的 MIDI**；能拿到的权威时序只有
    **人写的谱面**（osu! 的 `.osu` 是纯文本，`https://osu.ppy.sh/osu/<id>` 直接给原文）；
  · 人写谱面的音**时间干净**（BPM/offset 写死、没有 AI 抖动的 10ms 帧量化），
    正好是生成器最想要的那种输入。

用法::

    python tools/osu2mid.py in.osu -o out.mid [--per-lane-tracks] [--base-pitch 48]

口径（都写在代码里，避免"生成的 MIDI 到底是什么"说不清）：
  · 时间轴 **t=0 = 音频 t=0**（把 `[TimingPoints]` 的 offset 也算成 tick 加回去）；
  · 速度表照抄（正 beatLength ⇒ BPM；负值是 SV，**不参与 tempo**）；
  · **每一条 column 一个轨**（默认）：这样生成器里可以把「某一条 lane」当一条音轨挑；
  · 音高 = `base_pitch + column*5`（只为了"分得开"，不代表任何音高含义）；
  · 普通音时值 = min(同列下一个音, 1/8 拍)，下限 30ms；长条（type 128）用真实结束时刻。
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

PPQN = 480


# ------------------------------------------------------------------ .osu 解析
def parse_osu(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        txt = fh.read()
    sec = ""
    out = {"timing": [], "objects": [], "meta": {}, "general": {},
           "difficulty": {}}
    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            continue
        if sec in ("General", "Metadata", "Difficulty"):
            if ":" in line:
                k, v = line.split(":", 1)
                key = {"Metadata": "meta", "General": "general",
                       "Difficulty": "difficulty"}[sec]
                out[key][k.strip()] = v.strip()
            continue
        if sec == "TimingPoints":
            p = line.split(",")
            if len(p) < 2:
                continue
            try:
                t = float(p[0]); bl = float(p[1])
            except ValueError:
                continue
            # ★ 正 beatLength = 一拍多少毫秒；负值 = inherited（SV），不是 tempo
            bpm = (60000.0 / bl) if bl > 0 else 0.0
            out["timing"].append((t, bpm, bl))
            continue
        if sec == "HitObjects":
            out["objects"].append(line)
    out["timing"].sort(key=lambda x: x[0])
    return out


def keys_of(d: dict) -> int:
    for v in (d["difficulty"].get("CircleSize"), d["general"].get("CircleSize")):
        if v:
            try:
                return max(1, int(round(float(v))))
            except ValueError:
                pass
    return 4


def parse_objects(d: dict, keys: int) -> list[tuple[int, int, int]]:
    """→ [(column, t_start_ms, t_end_ms)]"""
    rows: list[tuple[int, int, int]] = []
    for line in d["objects"]:
        p = line.split(",")
        if len(p) < 5:
            continue
        try:
            x = int(float(p[0])); t = int(float(p[2])); typ = int(p[3])
        except ValueError:
            continue
        col = min(keys - 1, max(0, int(x * keys / 512)))
        end = t
        if typ & 128:                          # mania 长条：第 6 段是 endTime:...
            tail = p[5] if len(p) > 5 else ""
            if ":" in tail:
                try:
                    end = int(float(tail.split(":", 1)[0]))
                except ValueError:
                    end = t
        rows.append((col, t, max(end, t)))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows


# ------------------------------------------------------------------ SMF 写出
def _vlq(v: int) -> bytes:
    if v < 0:
        v = 0
    b = [v & 0x7F]
    v >>= 7
    while v:
        b.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(b))


def _track(events: list[tuple[int, bytes]]) -> bytes:
    """events = [(abs_tick, 原始事件字节)]，按 tick 稳定排序后补 delta 时间。"""
    events = sorted(events, key=lambda e: e[0])
    body = bytearray()
    prev = 0
    for tick, raw in events:
        body += _vlq(tick - prev) + raw
        prev = tick
    body += _vlq(0) + b"\xFF\x2F\x00"          # End of Track
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def _tempo_events(timing, ms_to_tick) -> list[tuple[int, bytes]]:
    """速度事件。

    ★ **第一个速度点必须写在 tick 0**（而不是它在 .osu 里的那个 tick）：
      MIDI 的约定是「第一个 tempo 事件之前，默认 120 BPM」。原本把第一个 tempo 写在
      `ms_to_tick(895)=931` ⇒ 前面 931 个 tick 被当成 120 BPM ⇒ 同一个音读回来
      **偏 +75ms**（实测）。写出时把 offset 折算成"静音"，而不是"一段 120 BPM"。
    """
    ev: list[tuple[int, bytes]] = []
    seen = set()
    first = True
    for t, bpm, bl in timing:
        if bpm <= 0:                            # SV 点：不写 tempo
            continue
        tick = 0 if first else ms_to_tick(t)
        first = False
        if tick in seen:
            continue
        seen.add(tick)
        us = int(round(60_000_000.0 / bpm))
        ev.append((tick, b"\xFF\x51\x03" + struct.pack(">I", us)[1:]))
    if not ev:
        ev.append((0, b"\xFF\x51\x03" + struct.pack(">I", 500_000)[1:]))
    return ev


def build_midi(d: dict, keys: int, rows: list[tuple[int, int, int]],
               per_lane: bool, base_pitch: int) -> bytes:
    # ---- 时间 → tick（分段速度表）----
    pts = [(t, bpm) for (t, bpm, _bl) in d["timing"] if bpm > 0] or [(0.0, 120.0)]
    def ms_to_tick(ms: float) -> int:
        tick = 0.0
        prev_ms, prev_bpm = 0.0, pts[0][1]
        for t, bpm in pts:
            if ms <= t:
                break
            tick += (t - prev_ms) * PPQN * prev_bpm / 60_000.0
            prev_ms, prev_bpm = t, bpm
        tick += (ms - prev_ms) * PPQN * prev_bpm / 60_000.0
        return int(round(tick))

    # ---- 时值：同列下一个音 / 1/8 拍 / 30ms 下限 ----
    by_col: dict[int, list[tuple[int, int]]] = {}
    for col, t0, t1 in rows:
        by_col.setdefault(col, []).append((t0, t1))
    bpm0 = pts[0][1]
    eighth = 60_000.0 / bpm0 / 2.0

    tracks: list[tuple[str, list[tuple[int, bytes]]]] = []
    # 轨 0：tempo + 曲名
    ev0 = [(0, b"\xFF\x03" + bytes([len(b"Conductor")]) + b"Conductor")]
    ev0 += _tempo_events(d["timing"], ms_to_tick)
    tracks.append(("Conductor", ev0))

    cols = sorted(by_col) if per_lane else [-1]
    for col in cols:
        name = "all" if col < 0 else f"lane{col}"
        ev: list[tuple[int, bytes]] = [
            (0, b"\xFF\x03" + bytes([len(name)]) + name.encode("ascii")),
            (0, b"\xC0\x00"),                   # program 0 = Acoustic Grand Piano
        ]
        if col < 0:
            note_rows = [(c, t0, t1) for c, t0, t1 in rows]
        else:
            note_rows = [(c, t0, t1) for c, t0, t1 in rows if c == col]
        # 逐音：长条用真实 end，普通音用「同列下一个音的起点」封顶
        nxt: dict[int, float] = {}
        for c, t0, t1 in sorted(note_rows, key=lambda r: -r[1]):
            nxt[c] = t0
        for c, t0, t1 in sorted(note_rows, key=lambda r: (r[1], r[0])):
            dur = t1 - t0
            if dur <= 0:
                dur = min(eighth, max(0.0, nxt.get(c, t0 + eighth) - t0))
            dur = max(30.0, dur)
            pitch = max(0, min(127, base_pitch + (c if c >= 0 else 0) * 5))
            ch = 0
            ev.append((ms_to_tick(t0), bytes([0x90 | ch, pitch, 100])))
            ev.append((ms_to_tick(t0 + dur), bytes([0x80 | ch, pitch, 0])))
        tracks.append((name, ev))

    head = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQN)
    return head + b"".join(_track(ev) for _n, ev in tracks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("osu")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--per-lane-tracks", action="store_true", default=True)
    ap.add_argument("--single-track", dest="per_lane_tracks", action="store_false")
    ap.add_argument("--base-pitch", type=int, default=48)
    a = ap.parse_args()
    d = parse_osu(a.osu)
    keys = keys_of(d)
    rows = parse_objects(d, keys)
    if not rows:
        print("没有解析到任何音符（不是 mania 谱面？）")
        return 2
    blob = build_midi(d, keys, rows, a.per_lane_tracks, a.base_pitch)
    out = a.out or (os.path.splitext(a.osu)[0] + ".mid")
    with open(out, "wb") as fh:
        fh.write(blob)
    m = d["meta"]
    print(f"{m.get('Artist')} - {m.get('Title')} [{m.get('Version')}]  "
          f"keys={keys} 音符={len(rows)}  "
          f"bpm={[round(b,3) for t,b,_ in d['timing'] if b>0][:3]}")
    print(f"→ {out}  ({len(blob)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
