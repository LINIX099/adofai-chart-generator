"""端到端管线自检：MIDI -> 采音 -> 求解 -> 写盘 -> 第三方 parser 反解校验。
（无 UI，用于快速回归。）

用法:  python tests/test_pipeline.py [--track N] [--track bpm]
"""
import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import midi, onsets as onsets_mod, solve as solve_mod, writer, verify, synth  # noqa: E402

SAMPLES = os.path.join(_ROOT, "samples")
OUT = os.path.join(_ROOT, "out")


def run(path: str, track_index: int | None, args) -> None:
    t0 = time.time()
    m = midi.load(path)
    print("=" * 84)
    print(os.path.basename(path), "|", m.stats())
    for t in m.tracks:
        print("   ", onsets_mod.track_summary(t))

    if track_index is None:
        # 自动挑一条：优先非鼓、音数适中
        cand = [t for t in m.tracks if t.notes and not t.is_drum_only()]
        if not cand:
            cand = [t for t in m.tracks if t.notes]
        track_index = max(cand, key=lambda t: t.notes[0].channel if False else 0).index
        print(f"    (未指定音轨，自动选 trk{track_index})")

    p_on = onsets_mod.OnsetParams(merge_ms=args.merge, min_velocity=args.minvel,
                                  min_interval_ms=args.minint, max_onsets=args.maxonsets)
    if args.tracks == "fill":
        prim = onsets_mod.select_tracks(m, "auto", -1)[0]
        others = [t for t in onsets_mod.select_tracks(m, "all", -1) if t.index != prim.index]
        trks = [prim] + others
        ons = onsets_mod.build_onsets_fill(prim, others, p_on, args.fill_ms)
        tnames = f"主trk{prim.index} + 补{len(others)}轨空白(>{args.fill_ms:g}ms)"
    else:
        trks = onsets_mod.select_tracks(m, args.tracks, track_index if args.track >= 0 else -1)
        ons = onsets_mod.build_onsets_multi(trks, p_on)
        tnames = "+".join(f"trk{t.index}" for t in trks) + f" ({len(trks)} 轨)"
    print(f"   [采音] {tnames}  note-on="
          f"{sum(len(t.notes) for t in trks)}  ->  onset={len(ons)}"
          f"   {p_on.describe()}")
    if len(ons) < 2:
        print("   !! onset 太少，跳过")
        return

    p_sv = solve_mod.SolveParams(
        base_bpm=(args.bpm if args.bpm > 0 else 0.0),
        beat_beats=args.ref_beats,
        straight_weight=solve_mod.STRAIGHT_PRESETS[args.straight],
        bpm_max=args.bpmmax,
        speed_tiers=((1,) if args.no_setspeed else solve_mod.SPEED_TIERS),
        allow_set_speed=not args.no_setspeed,
        allow_twirl=(args.twirl != "off"),
        twirl_mode=args.twirl,
        twirl_limit_deg=args.twirlmax,
        quantize_rhythm=not args.no_quant,
        ppqn=m.ppqn,
        midi_bpm=m.bpm0,
        use_templates=not args.no_tpl,
        template_only_nonstraight=not args.tpl_all,
        use_snowflake=args.snow,
        snowflake_min_tiles=args.snowmin,
        snowflake_full_tiles=args.snowfull,
        snowflake_n_rot={"auto": (6, 8, 10, 12), "6": (6,), "8": (8,), "12": (12,)}.get(args.snown, (6, 8, 10, 12)),
    )
    if os.environ.get("NAT_NOK"):          # A/B：关掉自然段的速度档复用
        p_sv.natural_reuse_speed = False
    if os.environ.get("TPL1"):             # A/B：模板只写第 1 轮 Twirl（旧行为）
        p_sv.template_all_rounds = False
    if os.environ.get("NATMIN"):           # A/B：自然段变速的最小格数
        p_sv.natural_speed_min_tiles = int(os.environ["NATMIN"])
    ch = solve_mod.solve(ons, p_sv)
    print(f"   [求解] {solve_mod.describe(ch)}"
          + ("" if args.no_tpl else
             f"   模板 {ch.meta.get('tpl_covered', 0)}格/{ch.meta.get('tpl_hits', 0)}段"
             + ("（只修非直线）" if not args.tpl_all else "（全用）")))
    if ch.meta.get("snow_count"):
        det = "  ".join(f"@{st}:{n}重×{m}步={t}格"
                        for st, n, m, t in ch.meta["snow_spans"][:6])
        print(f"   [魔法阵] {ch.meta['snow_count']} 朵 / {ch.meta['snow_tiles']} 格　{det}")
    print(f"   [参考] 一条直线 = {ch.meta.get('ref_beats'):g} 拍   "
          f"基准BPM={ch.base_bpm:g}")

    n = max(1, len(ch.floors))
    sp = solve_mod.speed_profile(ch)
    print(f"   [事件] 直线 {sp['straight_frac']*100:.1f}%  "
          f"Twirl {ch.n_twirl}({ch.n_twirl/n*100:.1f}%)  "
          f"减速事件 {ch.n_speed_events}({sp['event_frac']*100:.1f}%)  "
          f"行星速度 {sp['min']:.2f}~{sp['max']:.2f}x")
    print("   [词汇] " + "  ".join(f"{v:g}°×{pct:.0f}%" for v, _, pct in ch.travel_hist(6)))
    if os.environ.get("SS_AUDIT"):
        _tpl, _nat, _eng = set(), set(), set()
        for s0, total, _t in (getattr(p_sv, "template_flips", None) or []):
            _tpl.update(range(s0, s0 + total))
        for s0, nn in (getattr(p_sv, "natural_spans", None) or []):
            _nat.update(range(s0, s0 + nn))
        for s0, run in (getattr(p_sv, "engine_spans", None) or []):
            _eng.update(range(s0, s0 + run.n))

        _snow = set()
        for s0, _nr, _ar, tl in (ch.meta.get("snow_spans") or []):
            _snow.update(range(max(0, s0 - 1), s0 + tl + 1))

        def _who(i):
            return "雪花" if i in _snow else "模板" if i in _tpl else \
                "自然段" if i in _nat else "引擎" if i in _eng else "DP"
        cat = {"雪花": 0, "模板": 0, "自然段": 0, "引擎": 0, "DP": 0}
        for fl, _bpm in ch.set_speed_floors:
            cat[_who(fl - 1)] += 1
        print(f"   [SS审计] 总={len(ch.set_speed_floors)} 归属={cat}   "
              f"span 数: 模板={len(getattr(p_sv, 'template_flips', []) or [])} "
              f"自然={len(getattr(p_sv, 'natural_spans', []) or [])} "
              f"引擎={len(getattr(p_sv, 'engine_spans', []) or [])}")
        fls = [f for f, _ in ch.set_speed_floors]
        gaps = {}
        for a in range(len(fls) - 1):
            g = fls[a + 1] - fls[a]
            gb = "<=4" if g <= 4 else "<=8" if g <= 8 else "<=16" if g <= 16 else ">16"
            gaps[gb] = gaps.get(gb, 0) + 1
        print(f"   [SS审计] 相邻事件间隔={gaps}")
        d = dict(ch.set_speed_floors)
        seq = "".join(
            "." if i not in d else
            ("T" if (i - 1) in _tpl else "n" if (i - 1) in _nat
             else "e" if (i - 1) in _eng else "D")
            for i in range(min(200, len(ch.floors))))
        print(f"   [SS审计] 前200格: {seq}")
        _ot = [o.t_ms for o in ons]
        bad = []
        for i in range(1, min(len(ch.floors) - 1, len(_ot))):
            f = ch.floors[i]
            dur = (f.travel / 180.0 + f.pause_beats) * (60000.0 / f.bpm)
            act = _ot[i] - _ot[i - 1]
            if abs(dur - act) > 3.0:
                bad.append((abs(dur - act), i, dur, act, f.travel, f.bpm, f.speed_k,
                            _who(i - 1)))
        bad.sort(reverse=True)
        print(f"   [SS审计] 逐格偏差>3ms 的格数={len(bad)} 最大5个:")
        for d, i, dur, act, tv, bp, sk, who in bad[:5]:
            print(f"      floor={i} {who} 谱={dur:.1f} 乐={act:.1f} 差={dur-act:+.1f}ms "
                  f"travel={tv:g} bpm={bp:g} k={sk:g}")
    tvs = [f.travel for f in ch.floors]
    print(f"   [几何] travel {min(tvs):.1f}~{max(tvs):.1f}°  twirl_thr={args.twirlmax}°  "
          f"a[0]={ch.floors[0].angle}  travel[0]={ch.floors[0].travel:g}° (必须 180)")
    ov = solve_mod.path_overlap_stats(ch)
    print(f"   [间距] 非相邻最小={ov['min_dist']:.2f}R  <1.75R 对数={ov['overlaps']}  "
          f"包围盒={ov['bbox'][0]:.0f}x{ov['bbox'][1]:.0f}")
    print(f"          ★ 排掉魔法阵自折返后：最小={ov['min_dist_no_snow']:.2f}R  "
          f"<1.75R 对数={ov['overlaps_no_snow']}  最差一對={ov['worst_no_snow']}")
    print(f"          ★ 距离分布(排雪花)：{ov['hist']}   最挤的 8 个 32 格窗口：{ov['zones']}")

    name = os.path.splitext(os.path.basename(path))[0]
    outdir = os.path.join(OUT, name)
    songs = os.path.join(_ROOT, "out", "_audio")
    os.makedirs(songs, exist_ok=True)
    CD = args.cd
    lead = solve_mod.total_lead_ms(ch, CD)
    off = ons[0].t_ms
    wav = synth.render(m, os.path.join(songs, name + ".wav"),
                       track_index=trks[0].index,
                       track_indexes=[t.index for t in trks],
                       onsets=ons, click=True,
                       lead_ms=lead, max_seconds=args.audio_seconds)
    p = writer.write_dir(
        ch, outdir, name="main", audio_src=wav,
        song=name, artist="(MIDI)", author="ADOFAI Chart Generator",
        offset_ms=off, difficulty=args.difficulty,
        countdown_ticks=CD, separate_countdown=True,
    )
    chk = solve_mod.check_offset(ch, off, CD, [o.t_ms for o in ons],
                                 m.length_ms + lead, lead)
    print(f"   [时序] cd={CD}  offset={off:.0f}ms  前置静音={lead:.0f}ms  "
          f"命中时刻误差 max={chk['max_err_ms']*1000:.1f}us")
    print(f"          offset+最后一层={chk['offset_plus_last_s']:.1f}s  "
          f"成品音频={chk['audio_len_s']:.1f}s  尾部余量={chk['tail_gap_s']:+.1f}s")
    print(f"   [写盘] {p}   ({os.path.getsize(p)} bytes)")
    print(f"   [音频] {wav}   ({os.path.getsize(wav)} bytes)")

    vr = verify.verify_file(p, [o.t_ms for o in ons], tol_ms=1.0, lead_floors=1)
    print("   [校验] " + vr.summary())
    print(f"   [耗时] {time.time()-t0:.2f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mid", nargs="?", default=None)
    ap.add_argument("--track", type=int, default=-1)
    ap.add_argument("--tracks", default="fill",
                    choices=("fill", "auto", "all", "all+drums"),
                    help="采音范围：fill=主轨+补空白（推荐）/ auto=第一条非鼓轨 / "
                         "all=所有非鼓轨全采 / all+drums=含鼓")
    ap.add_argument("--fill-ms", type=float, default=600.0,
                    help="「主轨+补空白」模式下，主轨出现多长的空白才去补")
    ap.add_argument("--bpm", type=float, default=-1)
    ap.add_argument("--merge", type=float, default=30.0)
    ap.add_argument("--minvel", type=int, default=1)
    ap.add_argument("--minint", type=float, default=0.0)
    ap.add_argument("--maxonsets", type=int, default=0)
    ap.add_argument("--target-travel", type=float, default=180.0,
                    help="（已弃用，v3 由 --ref-beats 与 --straight 决定）")
    ap.add_argument("--refq", type=float, default=0.85, help="（已弃用）")
    ap.add_argument("--ref-beats", type=float, default=0.0,
                    help="一条直线 = 几拍（0=自动，遍历候选音值）")
    ap.add_argument("--straight", default="平衡", choices=("少", "平衡", "多"),
                    help="直线优先度")
    ap.add_argument("--bpmmax", type=float, default=400.0)
    ap.add_argument("--no-quant", action="store_true", help="不量化到音值网格")
    ap.add_argument("--bandmin", type=float, default=12.0, help="（已弃用）")
    ap.add_argument("--bandmax", type=float, default=350.0, help="（已弃用）")
    ap.add_argument("--no-setspeed", action="store_true")
    ap.add_argument("--twirl", default="alternate", choices=("off", "accum", "steer", "alternate"))
    ap.add_argument("--twirlmax", type=float, default=300.0)
    ap.add_argument("--cd", type=int, default=4)
    ap.add_argument("--offset", type=float, default=None)
    ap.add_argument("--difficulty", type=int, default=0)
    ap.add_argument("--audio-seconds", type=float, default=0.0,
                    help="渲染音频的长度上限（秒）；0 = 整曲（导出的示例谱要能直接进游戏，必须是整曲）")
    ap.add_argument("--no-tpl", action="store_true", help="不用节奏型模板，纯 DP 兜底")
    ap.add_argument("--tpl-all", action="store_true",
                    help="模板全用（连 DP 本来是直线的地方也换）")
    ap.add_argument("--snow", action="store_true", help="启用魔法阵（雪花）")
    ap.add_argument("--snowmin", type=int, default=10, help="段长低于这个数不用雪花")
    ap.add_argument("--snowfull", type=float, default=48.0, help="段长到这个数就全用雪花")
    ap.add_argument("--snown", default="auto", choices=("auto", "6", "8", "12"),
                    help="雪花旋转阶数：46 = 自动")
    args = ap.parse_args()

    if args.mid:
        run(args.mid, None if args.track < 0 else args.track, args)
    else:
        for fn in sorted(os.listdir(SAMPLES)):
            if fn.lower().endswith((".mid", ".midi")):
                run(os.path.join(SAMPLES, fn), None if args.track < 0 else args.track, args)


if __name__ == "__main__":
    main()
