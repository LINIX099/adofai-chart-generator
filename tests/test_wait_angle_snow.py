"""v0.3 三项口径的单测（docs/24）。

① 等待拍优先用**暂停节拍**，而不是让行星减速爬过去
   （`SolveParams.pause_min_beats` 默认 1.0 = 只要比一拍长就暂停）
② 雪花层修好「Twirl 与 SetSpeed 同格 → 写盘时被挪位 → 反解差 180°/324ms」
③ 新增「最小角度」`SolveParams.travel_min`，全线生效

跑法:  python tests/test_wait_angle_snow.py
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import midi as midi_mod, solve as solve_mod, writer, verify, rules  # noqa: E402
from core.onsets import Onset, OnsetParams, build_onsets                       # noqa: E402
from sidecar import schema as SC                                              # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def synth_onsets(ms_list, pitch=60):
    return [Onset(t_ms=float(t), velocity=100, pitch=pitch) for t in ms_list]


# ---------------------------------------------------------------------------
def wait_uses_pause():
    print("=" * 84)
    print("① 等待拍 → 暂停节拍（不再用减速档）")
    print("=" * 84)
    # 120bpm ⇒ 500ms = 1 拍。间隔：1,1,2,3,1,1 拍  ⇒ 两处「等待」
    base = 120.0
    ms = [0, 500, 1000, 2000, 3500, 4000]
    ons = synth_onsets(ms)
    p = solve_mod.SolveParams(base_bpm=base, midi_bpm=base, ppqn=480,
                              beat_beats=1.0, use_templates=False,
                              use_triplet_engine=False, use_natural_spans=False,
                              pause_min_beats=1.0)
    ch = solve_mod.solve(ons, p)
    # floor i+1 对应 onset i 之后的那个间隔
    pa = [ch.floors[i + 1].pause_beats for i in range(len(ons) - 1)]
    ks = [ch.floors[i + 1].speed_k for i in range(len(ons) - 1)]
    print(f"   间隔(拍) = {[(ons[i+1].t_ms - ons[i].t_ms) / 500.0 for i in range(len(ons)-1)]}")
    print(f"   Pause(拍) = {pa}")
    print(f"   速度档 k  = {ks}")
    check(all(x > 1e-9 for x in (pa[2], pa[3])),
          f"两处等待（2 拍 / 3 拍）都用了 Pause：{pa[2]:.2f} / {pa[3]:.2f} 拍")
    check(abs(pa[3] - 2.0) < 1e-6, f"3 拍等待 = travel 180(1拍) + Pause {pa[3]:.2f} 拍")
    check(all(abs(pa[i]) < 1e-9 for i in (0, 1, 4)),
          "非等待格不带 Pause")
    check(all(ks[i] <= 1.0 + 1e-9 for i in (2, 3)),
          f"**等待格**一个减速档都没有（k = {ks[2]:g} / {ks[3]:g}）")
    # 时序仍然精确
    et = solve_mod.times_from_chart(ch)
    err = max(abs((et[i + 1] - et[1]) - (ons[i].t_ms - ons[0].t_ms))
              for i in range(len(ons) - 1))
    check(err < 1e-6, f"逐格时序仍精确（最大差 {err * 1000:.3f} us）")
    # 阈值调回 4 拍 ⇒ 退回旧行为（2/3 拍的等待改成减速档）
    p2 = solve_mod.SolveParams(base_bpm=base, midi_bpm=base, ppqn=480,
                               beat_beats=1.0, use_templates=False,
                               use_triplet_engine=False, use_natural_spans=False,
                               pause_min_beats=4.0)
    ch2 = solve_mod.solve(ons, p2)
    pa2 = [ch2.floors[i + 1].pause_beats for i in range(len(ons) - 1)]
    check(all(abs(x) < 1e-9 for x in pa2),
          f"阈值 4 拍时没有 Pause（旧行为，{pa2}）")


# ---------------------------------------------------------------------------
SAMPLES = ("Automaton_Waltz", "FallenEra", "MemoryLocked")


def min_angle_takes_effect():
    print("=" * 84)
    print("③ 最小角度 travel_min 全线生效")
    print("=" * 84)
    m = midi_mod.load(os.path.join(_ROOT, "samples", "_external", "Automaton_Waltz.mid"))
    ons = build_onsets(m.tracks[0].notes, OnsetParams(merge_ms=30.0))
    for tmin in (20.0, 45.0, 60.0):
        p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0, travel_min=tmin)
        ch = solve_mod.solve(ons, p)
        dp_pole = ch.dp_pole_indexes()
        tv = [f.travel for i, f in enumerate(ch.floors)
              if i not in dp_pole and i not in (0, len(ch.floors) - 1)]
        lo = min(tv) if tv else 180.0
        viols = [v for v in rules.check_chart(ch)
                 if v["code"] == "travel_below_min"]
        print(f"   travel_min={tmin:5.1f}° → 实测最小 travel {lo:6.2f}°  "
              f"违规 {len(viols)}  直线率 {ch.straight_frac*100:.1f}%")
        check(lo >= tmin - 1e-9, f"travel_min={tmin:g}° 时没有更小的角度（min={lo:.2f}°）")
    # 参数真的被 rules 读到（把 chart.meta 改小再查，应该报违规）
    ch.meta["travel_min"] = 1e9
    vs = [v for v in rules.check_chart(ch) if v["code"] == "travel_below_min"]
    check(bool(vs), "rules 会把低于最小角度的格点出来（把阈值抬到 1e9 就报错）")
    ch.meta["travel_min"] = 20.0
    check(not [v for v in rules.check_chart(ch) if v["code"] == "travel_below_min"],
          "恢复阈值后不再报错")


# ---------------------------------------------------------------------------
def snowflake_geometry_parity():
    print("=" * 84)
    print("② 雪花：不再偷挪 Twirl，反解器与模型逐格一致")
    print("=" * 84)
    for name in SAMPLES:
        m = midi_mod.load(os.path.join(_ROOT, "samples", "_external", name + ".mid"))
        ons = build_onsets(m.tracks[0].notes, OnsetParams(merge_ms=30.0))
        p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0, use_snowflake=True,
                                  snowflake_min_tiles=10, snowflake_full_tiles=48.0)
        ch = solve_mod.solve(ons, p)
        n_snow = ch.meta.get("snow_count", 0)
        if not n_snow:
            print(f"   {name}: 没有雪花段，跳过")
            continue
        d = tempfile.mkdtemp()
        fp = os.path.join(d, "main.adofai")
        writer.write_dir(ch, d, name="main", audio_src=None)
        js = writer.build_json(ch)
        ch.meta["twirl_on_setspeed"] = js and ch.meta.get("twirl_on_setspeed") or []
        on_speed = ch.meta.get("twirl_on_setspeed") or []
        vr = verify.verify_file(fp, [o.t_ms for o in ons], tol_ms=1.0,
                                lead_floors=1)
        errs = [v for v in rules.check_chart(ch) if v.get("level") != "info"]
        codes = sorted({v["code"] for v in errs})
        print(f"   {name}: 雪花 {n_snow} 朵/{ch.meta.get('snow_tiles')} 格  "
              f"形状 {ch.meta.get('snow_shapes')}  "
              f"Twirl/SetSpeed 同格 {len(on_speed)}  违规 {codes}  "
              f"反解 max {vr.max_err_ms * 1000:.1f}us")
        check(not on_speed, f"{name}: 没有「Twirl 与 SetSpeed 同格」（{on_speed[:4]}）")
        check(ch.meta.get("twirl_moved") == 0,
              f"{name}: writer 没有偷挪 Twirl（twirl_moved=0）")
        check(vr.ok, f"{name}: 第三方反解通过（max {vr.max_err_ms * 1000:.1f}us）")
        check(vr.max_err_ms < 1.0, f"{name}: 反解误差 < 1ms（{vr.max_err_ms:.4f}ms）")


# ---------------------------------------------------------------------------
def snowflake_params_are_live():
    print("=" * 84)
    print("②b 雪花参数真的能用（形状 / 最少步数 / 紧凑 / 等间隔容差）")
    print("=" * 84)
    from core import snowflake as SN
    m = midi_mod.load(os.path.join(_ROOT, "samples", "_external", "Automaton_Waltz.mid"))
    ons = build_onsets(m.tracks[0].notes, OnsetParams(merge_ms=30.0))
    seen = {}
    for shape in ("uniform", "step", "zigzag"):
        p = solve_mod.SolveParams(ppqn=m.ppqn, midi_bpm=m.bpm0, use_snowflake=True,
                                  snowflake_min_tiles=10, snowflake_full_tiles=48.0,
                                  snowflake_shape=shape)
        ch = solve_mod.solve(ons, p)
        seen[shape] = ch.meta.get("snow_shapes") or []
    for shape, got in seen.items():
        check(got == [shape], f"snowflake_shape='{shape}' 真的被用上 → {got}")
    # plan() 的 travel_min 过滤
    s = SN.plan(200, travel_min=170.0)
    check(s is None or min(s.travels()) >= 170.0 - 1e-9,
          "plan(travel_min=170) 要么不产雪花，要么全格 ≥170°")
    s2 = SN.plan(200, travel_min=0.0)
    check(s2 is not None, "plan(travel_min=0) 照常产出")
    # 最少步数
    s3 = SN.plan(200, min_arms=5)
    check(s3 is None or s3.arms >= 5, f"min_arms=5 → arms={None if s3 is None else s3.arms}")


# ---------------------------------------------------------------------------
def schema_defaults():
    print("=" * 84)
    print("④ schema 默认值与新字段")
    print("=" * 84)
    d = SC.defaults()
    keys = {f["key"] for f in SC.FIELDS}
    for k in ("travel_min", "snowflake_shape", "snowflake_min_arms",
              "snowflake_compact", "snowflake_uniform_tol_ms", "snowflake_random",
              "snowflake_seed"):
        check(k in keys and k in d, f"schema 里有 {k}")
    check(d["pause_min_beats"] == solve_mod.SolveParams().pause_min_beats,
          f"pause_min_beats 默认跟随 core（{d['pause_min_beats']}）")
    vf = {f["key"] for f in SC.VIEW_FIELDS}
    check("music_delay_ms" in vf, "view_fields 里有 music_delay_ms（偏移修正）")
    check(d["music_delay_ms"] == 0, "music_delay_ms 默认 0")


def main():
    wait_uses_pause()
    min_angle_takes_effect()
    snowflake_geometry_parity()
    snowflake_params_are_live()
    schema_defaults()
    print()
    if FAIL:
        print(f"FAILED  {len(FAIL)} 条不通过：")
        for f in FAIL:
            print("   · " + f)
        return 1
    print("=> PASS  全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
