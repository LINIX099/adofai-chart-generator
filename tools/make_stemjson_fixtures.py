# -*- coding: utf-8 -*-
"""生成「时间戳 JSON（DEMUCS 分轨）」的测试夹具 + 内置示例。

    python tools/make_stemjson_fixtures.py

规格：`docs/refs/时间戳JSON字段说明.md`；方案：`docs/56` §5。

为什么用生成器而不是手写 JSON：**`onsets_frame` 必须和 `onsets_sec` 对得上**
（`sec ≈ frame×hop_ms/1000`）—— 手算 30 个点的帧号一定会有人写错，
而「对不上」恰恰是我们**故意**要在 `frame_mismatch.json` 里造的场景。

夹具里的毫秒数一律取 5 的整数倍（hop 取 5.0ms）⇒ `onsets_sec` 只保留 3 位小数，
`frame×hop` 与 `sec` **逐点精确相等**，干净的用例不会带一堆「差 0.0001ms」的噪声。
"""
from __future__ import annotations

import io
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
OUT = os.path.join(ROOT, "tests", "fixtures", "stemjson")
SAMPLE = os.path.join(ROOT, "samples", "示例·分轨时间戳.json")

HOP = 5.0


def _stem(ms_list, *, source="", method="spectral_flux", model=None, hop=HOP,
          frames=None, raw_sec=None, raw_frame=None):
    """一路：`ms_list`（毫秒）→ `onsets_sec`（秒）+ `onsets_frame`（帧）。"""
    d = {"source": source, "method": method}
    if model:
        d["model"] = model
    if raw_sec is not None:
        d["onsets_sec"] = raw_sec
    else:
        d["onsets_sec"] = [round(float(x) / 1000.0, 4) for x in ms_list]
    if raw_frame is not None:
        d["onsets_frame"] = raw_frame
    elif frames is not None:
        d["onsets_frame"] = list(frames)
    else:
        d["onsets_frame"] = [int(round(float(x) / hop)) for x in ms_list]
    return d


def _head(**kw):
    stems = kw.get("stems") or {}
    d = {"version": 1, "source_audio": "Automaton Waltz - Plum.wav",
         "duration_sec": 202.378, "sample_rate": 22050, "hop_ms": HOP,
         "separation_model": "htdemucs_6s",
         # ★ `has_vocals` 与「有没有 vocals 键」必须**自洽** —— 否则每个夹具都会
         #   带一条「has_vocals=true 却没有 vocals」的警告，把真警告淹掉。
         "has_vocals": "vocals" in stems,
         "bpm_hint": None}
    d.update(kw)
    return d


def _lattice(n=32, start=1000.0, step=150.0):
    return [start + i * step for i in range(n)]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    files = {}

    # 1) 正常 6 路（带完整 head）
    mel = _lattice(32)
    files["full_6stems.json"] = _head(stems={
        "melody": _stem(mel, source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "vocals": _stem([500, 1500, 2500, 3500, 4500, 5500, 6500, 7500],
                        source="vocals", method="onsetnet",
                        model="onset_net_vocal.pt"),
        # ★ 故意与 melody **错开** 75ms：这样「多勾一路 ⇒ 主轨取并集」真的多出点来
        #   （全部重合的话并集还是 32，验不出东西）
        "drums": _stem([1075 + i * 300 for i in range(16)],
                       source="drums", method="spectral_flux"),
        "bass": _stem([1000, 1600, 2200, 2500, 2800, 3100, 3400, 3700,
                       4000, 4300, 4600, 5200], source="bass"),
        "guitar": _stem([2000, 2050, 2600, 3200, 3800, 4400, 5000, 5600, 6000],
                        source="guitar"),
        "piano": _stem([900, 1200, 1800, 2400, 3000, 3600], source="piano"),
    })

    # 2) 纯音乐：has_vocals=false 且**没有** vocals 键
    files["no_vocals.json"] = _head(has_vocals=False, stems={
        "melody": _stem(mel, source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "drums": _stem([1000, 1600, 2200, 2800], source="drums"),
    })

    # 3) --no-piano：少一路（键本来就不固定）
    files["no_piano.json"] = _head(stems={
        "melody": _stem(mel[:8], source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "vocals": _stem([500, 2500], source="vocals", method="onsetnet",
                        model="onset_net_vocal.pt"),
        "drums": _stem([1000, 1600], source="drums"),
        "bass": _stem([1000, 2200], source="bass"),
        "guitar": _stem([2000, 3200], source="guitar"),
    })

    # 4) 单路也能出谱
    files["one_stem.json"] = _head(source_audio="", stems={
        "melody": _stem([1000, 1150, 1300, 1450, 1600, 1750, 1900],
                        source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
    })

    # 5) 某一路空数组 ⇒ 不建轨 + 报出来
    files["empty_stem.json"] = _head(stems={
        "melody": _stem(mel[:8], source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "bass": _stem([], source="bass"),
        "drums": _stem([1000, 1600, 2200, 2800], source="drums"),
    })

    # 6) 未排序 ⇒ 排序 + 计数
    files["unsorted.json"] = _head(stems={
        "melody": _stem([1000, 1150, 1450, 1300, 1600, 1900, 1750],
                        source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "drums": _stem([1000, 1600, 2200], source="drums"),
    })

    # 7) 重复 / 负 / null / 非数字 / NaN ⇒ 合并或丢弃 + 计数
    #    ★ 帧号要**跟 sec 对得上**（这台用例考的不是 frame 校验，别混进来）
    bad_sec = [1.0, 1.0, -0.5, None, "abc", 2.0, float("nan"), 3.0]
    bad_frm = [200, 200, -100, None, None, 400, None, 600]
    files["dup_and_bad.json"] = _head(stems={
        "melody": _stem([], source="other", method="onsetnet",
                        model="onset_net_melody.pt", raw_sec=bad_sec,
                        raw_frame=bad_frm),
        "drums": _stem([1000, 1600, 2200], source="drums"),
    })

    # 8) sec 与 frame 差 > 1 帧 ⇒ 警告（用规格里的真 hop 5.805）
    hop2 = 5.805
    sec = [round(18.0709 + i * 0.15, 4) for i in range(6)]
    files["frame_mismatch.json"] = _head(hop_ms=hop2, stems={
        "melody": _stem([], source="other", method="onsetnet",
                        model="onset_net_melody.pt", raw_sec=sec,
                        raw_frame=[3113 + i * 26 + 3 for i in range(6)]),
        "drums": _stem([1000, 1600], source="drums", hop=hop2),
    })

    # 9) 未知版本 ⇒ 警告但继续
    files["version_2.json"] = _head(version=2, stems={
        "melody": _stem(mel[:6], source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "drums": _stem([1000, 1600], source="drums"),
    })

    # 10) 结构化但**不是**这个格式（BDG 味的工程）⇒ 必须明确拒绝，不许出垃圾谱
    files["not_stem.json"] = {
        "app": "beat-data-generator", "version": 2,
        "baseBpm": 137.0, "offsetMs": 12.5,
        "tracks": [{"id": "t1", "name": "主轨", "type": "beat"}],
        "markers": [{"id": "m1", "trackId": "t1", "beat": 0},
                    {"id": "m2", "trackId": "t1", "beat": 4}],
    }

    # 11) source_audio 指了个不存在的文件 ⇒ 提示（不报错）
    files["audio_missing.json"] = _head(source_audio="不存在的原曲.wav", stems={
        "melody": _stem(mel[:8], source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "drums": _stem([1000, 1600], source="drums"),
    })

    # 12) ★★ 倍频陷阱（`docs/58` 自动贴合）：真砖长 **90.909ms**，但有一路
    #     「自动网格识别」会认成 **181.818ms**（2 倍）—— 体检必须选 90.909。
    #     旋律是 90.909 的整数倍（16 分音为主），吉他走 181.8，钢琴同 90.909。
    import random as _rnd
    _r = _rnd.Random(20261017)
    brick = 60000.0 / 660.0                       # 90.9090909…
    mel = []
    t = 1360.0
    for i in range(48):                            # 16 分音为主，偶尔 8/4 分
        mel.append(t + _r.uniform(-3.0, 3.0))
        t += brick * (2 if i % 8 == 7 else (1 if i % 4 else 1))
    gtr = [2000.0 + k * brick * 2 + _r.uniform(-3.0, 3.0) for k in range(24)]
    pia = [1360.0 + k * brick + _r.uniform(-3.0, 3.0) for k in range(40)]
    files["octave_trap.json"] = _head(source_audio="", duration_sec=12.0, stems={
        "melody": _stem([], source="other", method="onsetnet",
                        model="onset_net_melody.pt",
                        raw_sec=[round(x / 1000.0, 6) for x in mel],
                        raw_frame=[int(round(x / HOP)) for x in mel]),
        "guitar": _stem([], source="guitar", method="spectral_flux",
                        raw_sec=[round(x / 1000.0, 6) for x in gtr],
                        raw_frame=[int(round(x / HOP)) for x in gtr]),
        "piano": _stem([], source="piano", method="spectral_flux",
                       raw_sec=[round(x / 1000.0, 6) for x in pia],
                       raw_frame=[int(round(x / HOP)) for x in pia]),
    })

    for name, obj in files.items():
        p = os.path.join(OUT, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, indent=2))
            fh.write("\n")
        print("wrote", os.path.relpath(p, ROOT))

    # 内置示例：比夹具更像真曲子（旋律 64 点 · 双押 48 点），名字一眼看出是什么
    demo = _head(source_audio="", duration_sec=60.0, sample_rate=22050,
                 separation_model="htdemucs_6s", bpm_hint=None, stems={
        "melody": _stem([1000 + i * 150 for i in range(64)],
                        source="other", method="onsetnet",
                        model="onset_net_melody.pt"),
        "vocals": _stem([2000 + i * 300 for i in range(20)],
                        source="vocals", method="onsetnet",
                        model="onset_net_vocal.pt"),
        "drums": _stem([1000 + i * 200 for i in range(48)], source="drums"),
        "bass": _stem([1000 + i * 600 for i in range(16)], source="bass"),
        "guitar": _stem([3000 + i * 700 for i in range(12)], source="guitar"),
        "piano": _stem([1200 + i * 900 for i in range(8)], source="piano"),
    })
    with io.open(SAMPLE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(demo, ensure_ascii=False, indent=2))
        fh.write("\n")
    print("wrote", os.path.relpath(SAMPLE, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
