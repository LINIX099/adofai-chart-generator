# -*- coding: utf-8 -*-
"""**从别人的 `.adofai` 里抽出「时间戳」**，当我们的采音源用（只读）。

    python tools/adofai_to_ts.py <谱面.adofai> [--until-ms 62000] [--out 输出.txt]
                                [--json 输出.json] [--audio 音频名] [--no-stats]

为什么需要它：用户 2026-10「**时间戳从 X 里面拿，写 1min 左右**」——
即不去分析音频，直接借用一份成熟谱面的**每格命中时刻**当 onset 表，
再让我们的全流程（求解 / 双押 / 上色 / 算法轨道调度）生成自己的谱。

时间口径（与 `tools/read_adofai.py`、`core/path.py:67` 同一套）：
    travel = 180 − |ΔangleData|            # 180 = 直线 = 1 拍
    dt     = (travel/180 + pause_beats) × 60000/bpm_effective
    ★ 音频时刻 = `settings.offset` + Σdt   （session 的口径：「游戏时刻 = offset + entryTime」）
    ⇒ 抽出来的时间戳**含 offset**，这样绑同一份音频时能直接对上。

处理的事件：`SetSpeed`（Multiplier / Bpm，含 `angleOffset` 的切格变速）、`Pause`。
**Twirl 不影响时间**（只翻转奇偶）。认不出的事件会在报告里点出来（不许静默）。

输出格式（`core/ts_source.read_ts` 认的）：一行一个毫秒数，`#` 开头是注释。
`--json` 则写「时间戳 JSON（DEMUCS 风格）」并把 `--audio` 写进 `source_audio`
⇒ 走 session 的 stem-JSON 那条路时**会自动绑原曲**当预览/成品音频。
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")


def load_lenient(p: str):
    with open(p, "r", encoding="utf-8-sig") as fh:
        txt = fh.read()
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        txt = re.sub(r",(\s*,)+", ",", txt)
        txt = re.sub(r",(\s*[}\]])", r"\1", txt)
        return json.loads(txt, strict=False)


def tile_times(j) -> tuple[list[float], list[float], dict]:
    """→ (每格**进入时刻**的绝对音频毫秒, 每格 travel 度, 报告)。`t[0]` = 开局站位格。"""
    ad = [float(v) for v in (j.get("angleData") or [])]
    st = j.get("settings") or {}
    acts = [a for a in (j.get("actions") or []) if isinstance(a, dict)]
    base_bpm = float(st.get("bpm") or 100.0)
    offset = float(st.get("offset") or 0.0)

    twirls = {int(a["floor"]) for a in acts
              if a.get("eventType") == "Twirl" and "floor" in a}
    speeds: dict[int, dict] = {}
    pauses: dict[int, float] = {}
    other: dict[str, int] = {}
    for a in acts:
        et = a.get("eventType")
        if "floor" not in a:
            continue
        fl = int(a["floor"])
        if et == "SetSpeed":
            speeds[fl] = a
        elif et == "Pause":
            pauses[fl] = float(a.get("duration") or 0.0)
        elif et in ("Twirl", "EditorComment", "Bookmark", "ColorTrack", "RecolorTrack",
                    "MoveTrack", "MoveCamera", "MoveDecorations", "SetFilter", "Flash",
                    "Bloom", "ShakeScreen", "Hide", "PositionTrack", "AnimateTrack",
                    "SetHitsound", "PlaySound", "CustomBackground", "ScaleRadius",
                    "ScaleMargin", "ScalePlanets", "HallOfMirrors", "ScreenTile",
                    "ScreenScroll", "SetFrameRate", "RepeatEvents", "AddDecoration",
                    "SetText", "AddText", "SetParticle", "EmitParticle", "SetObject",
                    "AddObject", "SetDefaultText", "SetConditionalEvents",
                    "ScaleMargin", "Multitap", "Hold", "Checkpoint", "SetFilterAdvanced",
                    "SetPlanetRotation", "MoveTrack", "CustomBackground"):
            pass
        else:
            other[et] = other.get(et, 0) + 1

    bpm = base_bpm
    # ★★ 倒计时怎么算（`docs/24` §5 / `core.solve.game_entry_times`）：
    #   `separateCountdownTime=true` ⇒ 倒计时**不占音频时间**（第 1 格就在 offset+T0）；
    #   `false` ⇒ 倒计时占前 (cd−1) 拍，**只补在第 1 格上** ⇒ t[1] 要多加 (cd−1)×一拍。
    #   实测：ASGORE 那份是 `true`（所以直接抽就对）；我们自己导出的谱是 `false`
    #   （writer 默认），拿它当源时**必须**加这段，否则整体早 (cd−1) 拍。
    cd = int(st.get("countdownTicks") or 0)
    sep_cd = bool(st.get("separateCountdownTime", False))
    lead = 0.0 if sep_cd else max(0, cd - 1) * 60000.0 / base_bpm
    t: list[float] = []
    tv: list[float] = []
    cur = offset
    n_split = 0
    n_pause = 0
    for i in range(len(ad)):
        t.append(cur + (lead if i >= 1 else 0.0))
        if i == 0:
            travel = 180.0
        else:
            turn = (ad[i] - ad[i - 1] + 540.0) % 360.0 - 180.0
            travel = 180.0 - abs(turn)
        tv.append(travel)
        if i in speeds:
            e = speeds[i]
            ao = float(e.get("angleOffset") or 0.0)
            if str(e.get("speedType") or "Bpm") == "Multiplier":
                new_bpm = bpm * float(e.get("bpmMultiplier") or 1.0)
            else:
                new_bpm = float(e.get("beatsPerMinute") or bpm)
            if ao > 1e-9:
                # 这一格被切成「前段旧速 / 后段新速」（`core/dp_offset` 同一口径）
                n_split += 1
                a1 = min(ao, travel)
                cur += (a1 / 180.0) * 60000.0 / bpm
                cur += ((travel - a1) / 180.0) * 60000.0 / new_bpm
            else:
                cur += (travel / 180.0) * 60000.0 / new_bpm
            bpm = new_bpm
        else:
            cur += (travel / 180.0) * 60000.0 / bpm
        pb = pauses.get(i, 0.0)
        if pb > 1e-9:
            n_pause += 1
            cur += pb * 60000.0 / bpm
    rep = {"bpm": base_bpm, "offset_ms": offset, "tiles": len(ad),
           "twirls": len(twirls), "speeds": len(speeds), "split_speeds": n_split,
           "pauses": n_pause, "other_events": other,
           "countdown_ticks": cd, "separate_countdown": sep_cd,
           "countdown_lead_ms": lead,
           "total_ms": cur - offset}
    return t, tv, rep


def dense_runs(t: list[float], *, gap_ms: float = 90.0, min_n: int = 8):
    """找出「轮指/连打」段：连续 ≥min_n 个音、间隔 ≤gap_ms 的run。"""
    out = []
    i = 1
    while i < len(t):
        j = i
        while j + 1 < len(t) and (t[j + 1] - t[j]) <= gap_ms:
            j += 1
        n = j - i + 1
        if n >= min_n:
            span = t[j] - t[i - 1]
            out.append((i, j, n, t[i - 1], t[j], (n - 1) / span * 1000.0 if span > 0 else 0.0))
            i = j + 1
        else:
            i += 1
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]
    args = argv[1:]
    until = None
    out_txt = None
    out_json = None
    audio = ""
    stats = True
    for k, a in enumerate(args):
        if a == "--until-ms":
            until = float(args[k + 1])
        elif a == "--out":
            out_txt = args[k + 1]
        elif a == "--json":
            out_json = args[k + 1]
        elif a == "--audio":
            audio = args[k + 1]
        elif a == "--no-stats":
            stats = False

    j = load_lenient(path)
    t_all, tv_all, rep = tile_times(j)
    # ★★ 自检：本工具用的是**简化时间模型**（travel + SetSpeed + Pause 累加）。
    #   含大量 `Pause`/`SetSpeed` 组合的谱（**我们自己导出的谱就是**）上它会偏 ——
    #   实测在 `out/ASGORE轮指60s/main.adofai` 上累计偏 **3918ms**，而第三方 parser
    #   （`core.verify.parse_times`，vendored）只差 60.8ms 全谱。所以这里必须**主动核对**，
    #   差超过阈值就明说"这份抽出来的不可信"，绝不静默给出一份错的时间戳。
    _warn = ""
    try:
        from core import verify as _V
        _cum, _a = _V.parse_times(path)
        _mine = t_all[-1] - t_all[0]
        _theirs = float(_cum[-1]) if _cum else 0.0
        if abs(_mine - _theirs) > 20.0:
            _warn = (f"⚠ **本工具的时间模型与第三方 parser 差 {_mine - _theirs:.1f}ms**"
                     f"（本工具 {_mine:.1f} / parser {_theirs:.1f}）——"
                     f"这份谱的 Pause/SetSpeed 组合超出了本工具的简化模型，"
                     f"**抽出来的时间戳不可信**，别拿它当采音源。"
                     f"（用 `core.verify.parse_times` 自己按间隔重建）")
    except Exception as _e:                       # noqa: BLE001
        _warn = f"（第三方 parser 自检跳过：{_e}）"
    # 第 0 格是开局站位（不是音符）⇒ onset 从第 1 格起
    idx = [i for i in range(1, len(t_all))
           if (until is None or t_all[i] <= until)]
    ons = [t_all[i] for i in idx]
    tv_sel = [tv_all[i] for i in idx]

    print("=" * 70)
    print(f"源谱      : {path}")
    print(f"层数      : {rep['tiles']}   首格(站位)在 {t_all[0]:.1f}ms，"
          f"全谱 {rep['tiles'] - 1} 个音 / 到 {rep['total_ms']:.1f}ms")
    print(f"settings  : bpm={rep['bpm']:g} offset={rep['offset_ms']:.0f}ms "
          f"Twirl={rep['twirls']} SetSpeed={rep['speeds']}（其中切格 {rep['split_speeds']}）"
          f" Pause={rep['pauses']}")
    print(f"倒计时    : countdownTicks={rep['countdown_ticks']} "
          f"separateCountdownTime={rep['separate_countdown']}"
          + (f" ⇒ 不占音频时间（不用补）" if rep["separate_countdown"]
             else f" ⇒ 占前 {rep['countdown_lead_ms']:.1f}ms，已补到第 1 格之后"))
    if rep["other_events"]:
        print(f"⚠ 未处理的事件类型（不影响时间，但要知道）: {rep['other_events']}")
    if _warn:
        print("\n" + _warn)

    print(f"\n抽取      : {len(ons)} 个音"
          + (f"，截止 {until:.0f}ms（源谱时间轴）" if until is not None else ""))
    if ons:
        print(f"            第一个 {ons[0]:.1f}ms / 最后一个 {ons[-1]:.1f}ms "
              f"⇒ 时长 {(ons[-1] - ons[0]) / 1000.0:.1f}s")
        gaps = [b - a for a, b in zip(ons, ons[1:])]
        gaps_s = sorted(gaps)
        print(f"            音间隔  最小 {gaps_s[0]:.1f} / 中位 "
              f"{gaps_s[len(gaps_s) // 2]:.1f} / 最大 {gaps_s[-1]:.1f} ms")
        bins: dict[int, int] = {}
        for x in ons:
            bins[int(x // 1000)] = bins.get(int(x // 1000), 0) + 1
        mx = max(bins.values())
        print(f"\n密度画像（每秒音数，峰值 {mx}）:")
        for s in range(0, int(ons[-1] // 1000) + 1, 5):
            n = sum(bins.get(k, 0) for k in range(s, s + 5))
            bar = "#" * min(60, int(n / max(1, mx) * 60))
            print(f"  {s:>4}s {n:>4} |{bar}")
        runs = dense_runs(ons)
        if runs:
            print(f"\n★ 连打/轮指段（≥8 个音、间隔 ≤90ms）：{len(runs)} 段")
            for (i, j2, n, t0, t1, rate) in runs[:14]:
                print(f"   {t0 / 1000:>7.2f}s → {t1 / 1000:>7.2f}s  "
                      f"{n} 音 / {rate:.1f} 音每秒（第 {i}~{j2} 个音）")
            if len(runs) > 14:
                print(f"   …另有 {len(runs) - 14} 段")
        else:
            print("\n（这段里没有 ≥8 连、间隔 ≤90ms 的连打段）")
        # ★ 角度画像：连打段靠什么角度撑起来的（我们的求解器有最小角度门槛）
        import collections
        hist = collections.Counter(round(x, 2) for x in tv_sel)
        print("\n角度画像（这段里每格 travel 的分布，度）:")
        for a, n in sorted(hist.items()):
            if a <= 1e-9:
                print(f"   {a:>7.2f}°  ×{n}   （travel=0：中旋/重复角，不占时间）")
                continue
            print(f"   {a:>7.2f}°  ×{n}"
                  f"   ≈ 1/{180.0 / a:.2f} 拍 @bpm {rep['bpm']:g}"
                  f" = {a / 180.0 * 60000.0 / rep['bpm']:.1f}ms")
        # 连打段内到底是多少度
        if runs:
            i0, i1 = runs[0][0], runs[0][1]
            seg = collections.Counter(round(tv_sel[k], 2) for k in range(i0 - 1, i1))
            print(f"\n第一段连打（{runs[0][3] / 1000:.2f}s）里的角度："
                  f"{dict(sorted(seg.items()))}")

    if out_txt:
        os.makedirs(os.path.dirname(os.path.abspath(out_txt)), exist_ok=True)
        with open(out_txt, "w", encoding="utf-8") as fh:
            fh.write(f"# 时间戳（毫秒）· 抽自 {os.path.basename(path)}\n")
            fh.write(f"# bpm={rep['bpm']:g} offset={rep['offset_ms']:.0f}ms "
                     f"共 {len(ons)} 个音"
                     + (f"（截止 {until:.0f}ms）" if until is not None else "") + "\n")
            for x in ons:
                fh.write(f"{x:.1f}\n")
        print(f"\n[已写 {out_txt}]")
    if out_json:
        os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
        obj = {
            "version": 1,
            "format": "adoc-ts/1",
            "source_audio": audio or "",
            "duration_ms": (ons[-1] + 2000.0) if ons else 0.0,
            "tracks": [{"name": "main", "role": "main",
                        "onsets_ms": [round(x, 3) for x in ons]}],
        }
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        print(f"[已写 {out_json}（stem-JSON 口径，source_audio={audio!r}）]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
