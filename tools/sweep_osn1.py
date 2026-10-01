# -*- coding: utf-8 -*-
"""osn1 参数扫描台：一次起服务器，跑多组配置，导出并体检。

    python tools/sweep_osn1.py [--only 前缀] [--src 源] [--audio ogg]

每组配置 = 一个 dict（覆盖 schema 默认值）。产出：
    out/osn1_sweep/<tag>/main/main.adofai
并且打印一张对照表（对齐 corpus_report 口径）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                     # noqa: BLE001
    pass

from sidecar import schema as SC                      # noqa: E402
from sidecar import server as SV                      # noqa: E402
from _jsonrepair import loads_lenient, _read_text     # noqa: E402
from _pathdata import angle_data_of                   # noqa: E402
from _speeds import is_pow2, speeds_for, travel_into  # noqa: E402
import statistics as st                               # noqa: E402
from collections import Counter                       # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

SRC = _HOME + r"\Downloads\osn1_timestamps.json"
AUDIO = _HOME + r"\Downloads\mad_piano_party.ogg"
OUT = os.path.join(_ROOT, "out", "osn1_sweep")

#: ★ P12~P15 语料的目标带 = **P10~P90**（`tools/_p12_15_per_chart.py` 实测 45 张）
TARGET = {
    "直线":      (0.2191, 0.4869),
    "多押":      (0.0055, 0.2685),
    "Twirl":     (9.5287, 31.0520),
    "SetSpeed":  (0.8134, 22.2624),
    "2幂":       (0.7140, 1.0000),
    "1/12格":    (0.5663, 1.0000),
    "中位dt":    (83.7079, 184.5123),
    "midspin":   (0.0000, 0.0422),
}


def post(url, obj, timeout=1800.0):
    req = urllib.request.Request(url, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode("utf-8"))
        except Exception:                              # noqa: BLE001
            d = {"ok": False, "error": f"HTTP {e.code}"}
        d["status"] = e.code
        return d


# ------------------------------------------------------------------ 体检
GRID = 12.0


def metrics(chart_file):
    d, _kind = loads_lenient(_read_text(chart_file))
    a, _src = angle_data_of(d)
    n = len(a)
    if n < 2:
        return None
    bpm = float(d.get("settings", {}).get("bpm") or 0)
    acts = [e for e in (d.get("actions") or []) if e.get("active") is not False]
    twirl = {int(e.get("floor", 0)) for e in acts if e.get("eventType") == "Twirl"}
    ss = [e for e in acts if e.get("eventType") == "SetSpeed"]
    tv = travel_into(a, twirl)
    sp = speeds_for(d, n)
    if len(sp) != len(tv):
        sp = (sp + [1.0] * n)[:len(tv)]
    val, dts = [], []
    for i, t in enumerate(tv):
        v = (t / 180.0) / (sp[i] or 1.0)
        val.append(v)
        if bpm > 0:
            dts.append(v * 60000.0 / bpm)
    n_str = sum(1 for t in tv if abs(t - 180.0) <= .5)
    n_mp = sum(1 for i, t in enumerate(tv)
               if abs(t - 180.0) > .5 and i < len(dts) and dts[i] <= 35.0)
    n_mid = sum(1 for i in range(1, len(a)) if a[i] == 999)
    on12 = sum(1 for v in val if abs(v * GRID - round(v * GRID)) < 1e-6)
    return {
        "n": n, "bpm": bpm,
        "直线": n_str / n, "多押": n_mp / n,
        "Twirl": len(twirl) / n * 100, "SetSpeed": len(ss) / n * 100,
        "midspin": n_mid / n,
        "2幂": sum(1 for s in sp if is_pow2(s)) / n,
        "1/12格": on12 / n,
        "中位dt": st.median(dts) if dts else 0.0,
        "ang": Counter(round(t) for t in tv),
        "spd": Counter(round(x, 4) for x in sp),
        "val": Counter(round(v, 4) for v in val),
        "pause": sum(1 for e in acts if e.get("eventType") == "Pause"),
    }


def verdict(m):
    """对照目标带，返回 (命中数, 总数, 明细)。"""
    bits, hit, tot = [], 0, 0
    for k, (lo, hi) in TARGET.items():
        v = m[k]
        ok = lo <= v <= hi
        hit += ok
        tot += 1
        if not ok:
            bits.append(f"{k}={v if k in ('Twirl','SetSpeed','中位dt') else round(v*100,1)}"
                        f"(要{round(lo if k in ('Twirl','SetSpeed','中位dt') else lo*100,1)}"
                        f"~{round(hi if k in ('Twirl','SetSpeed','中位dt') else hi*100,1)})")
    return hit, tot, bits


# ------------------------------------------------------------------ 配置表
def base(**kw):
    """（保留给单点调试用）"""
    d = {"auto_bpm": False, "base_bpm": 330.0}
    d.update(kw)
    return d


#: 所有配置共用的：绑预览音源（否则 offset 会按「合成音频前置静音」算）
COMMON = {"preview_audio_mode": 2, "preview_audio_path": AUDIO,
          "song": "Mad Piano Party", "artist": "Plum"}


#: 基准 = 砖长 181.818（bpm 330，同曲参照的写法）
B = {"denoise_hint_ms": 181.818182, "straighten": False}

CONFIGS: list[tuple[str, dict]] = [
    ("A_052_t0",  dict(B, slow_speed_penalty=0.52)),
    ("A_054_t0",  dict(B, slow_speed_penalty=0.54)),
    ("A_055_t0",  dict(B, slow_speed_penalty=0.55)),
    ("A_056_t0",  dict(B, slow_speed_penalty=0.56)),
    ("A_058_t0",  dict(B, slow_speed_penalty=0.58)),
    ("A_055_t1_240", dict(B, slow_speed_penalty=0.55, twirl_index=1, twirl_limit_deg=240.0)),
    ("A_058_t1_280", dict(B, slow_speed_penalty=0.58, twirl_index=1, twirl_limit_deg=280.0)),
]


def main(argv):
    only = ""
    src, audio, out = SRC, AUDIO, OUT
    i = 0
    while i < len(argv):
        if argv[i] == "--only":
            only = argv[i + 1]; i += 2
        elif argv[i] == "--src":
            src = argv[i + 1]; i += 2
        elif argv[i] == "--audio":
            audio = argv[i + 1]; i += 2
        elif argv[i] == "--out":
            out = argv[i + 1]; i += 2
        else:
            print("未知参数", argv[i]); return 2

    SV.APP = SV.App(_ROOT)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SV.Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1},
                     daemon=True).start()
    b = f"http://127.0.0.1:{port}"

    r = post(b + "/api/load", {"path": src})
    if not r.get("ok"):
        print("载入失败", r.get("error")); return 1
    dflt = list(r.get("default_tracks_checked") or [0])

    rows = []
    for tag, ov in CONFIGS:
        if only and not tag.startswith(only):
            continue
        st = SC.defaults()
        st.update(COMMON)
        # ★★ 顺序：**来源默认值先落，用户覆盖后落**（`gen_from_source` 用的是
        #   `over.setdefault(k, v)` ⇒ 用户赢）。上一版这里无条件写了来源默认值，
        #   把 `fit_mode=solve` 的覆盖**原地吃掉了** —— 整轮扫描结果全一样。
        _srcdef = {}
        for _dk, _sk in (("default_merge_ms", "merge_ms"),
                         ("default_fit_mode", "fit_mode"),
                         ("default_denoise_on", "denoise_on")):
            if _dk in r:
                _srcdef[_sk] = r[_dk]
        _srcdef.update(ov)
        st.update(_srcdef)
        st["song"] = "Mad Piano Party"
        st["artist"] = "Plum"
        st["tracks_checked"] = list(ov.get("tracks_checked") or dflt)
        d = os.path.join(out, tag)
        rb = post(b + "/api/rebuild", {"state": st})
        if not rb.get("ok"):
            print(f"✗ {tag}: {str(rb.get('error'))[:200]}")
            rows.append((tag, None, None))
            continue
        ex = post(b + "/api/export", {"state": st, "dir": d})
        if not ex.get("ok"):
            print(f"✗ {tag} 导出: {str(ex.get('error'))[:200]}")
            rows.append((tag, None, None))
            continue
        cf = os.path.join(ex.get("dir") or d, "main.adofai")
        m = metrics(cf) if os.path.isfile(cf) else None
        idx = [x for x in (rb.get("payload") or {}).get("appearance", {}) and [] ] or []
        rows.append((tag, m, rb))
        if m:
            h, t, bits = verdict(m)
            print(f"  {tag:24s} 格={m['n']:5d} bpm={m['bpm']:7.2f} "
                  f"命中 {h}/{t}   {'OK' if h == t else ' '.join(bits)}")

    print()
    print("=" * 130)
    hdr = (f"{'tag':24s}{'格':>6s}{'bpm':>8s}{'直线':>7s}{'多押':>7s}{'Twirl':>7s}"
           f"{'SS':>7s}{'mid':>7s}{'2幂':>7s}{'1/12':>7s}{'中位dt':>8s}{'Pause':>6s}{'命中':>6s}")
    print(hdr)
    print("-" * 130)
    for tag, m, _rb in rows:
        if not m:
            print(f"{tag:24s}  —— 失败")
            continue
        h, t, _ = verdict(m)
        print(f"{tag:24s}{m['n']:6d}{m['bpm']:8.2f}{m['直线']*100:7.1f}{m['多押']*100:7.1f}"
              f"{m['Twirl']:7.2f}{m['SetSpeed']:7.2f}{m['midspin']*100:7.2f}"
              f"{m['2幂']*100:7.1f}{m['1/12格']*100:7.1f}{m['中位dt']:8.1f}"
              f"{m['pause']:6d}{h:4d}/{t}")
    print()
    print("目标带（P12~P15 逐张中位）：" + "  ".join(
        f"{k}={v[0]}~{v[1]}" for k, v in TARGET.items()))

    print()
    print("=" * 130)
    print("角谱 / 速度档（只列得分 >= 3 的）")
    for tag, m, _rb in rows:
        if not m:
            continue
        h, t, _ = verdict(m)
        if h < 3:
            continue
        n = m["n"]
        print(f"\n[{tag}]  格={n} bpm={m['bpm']:.1f}  命中 {h}/{t}")
        print("   角度: " + "  ".join(
            f"{a:g}°({c*100.0/n:.1f}%)" for a, c in m["ang"].most_common(8)))
        print("   速度: " + "  ".join(
            f"{s:g}x({c*100.0/n:.1f}%)" for s, c in m["spd"].most_common(8)))
        print("   音值: " + "  ".join(
            f"{v:g}({c*100.0/n:.1f}%)" for v, c in m["val"].most_common(8)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
