"""`.bdg` 当生成源（`core/bdg/source.py`）单测。

    python tests/test_bdg_source.py

验的是：**把它做成一种 `MidiFile` 之后，我们原有的「选轨→采音→求解」那条路直接能用**。
不连宿主、不装插件、不用 GUI。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import bdg                                     # noqa: E402
from core import onsets as O                              # noqa: E402
from core.bdg import aliases as al                        # noqa: E402
from core.bdg import source as S                          # noqa: E402

FAIL = []
FIX = os.path.join(_HERE, "fixtures", "bdg")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def A_file_to_tracks():
    print("=" * 78)
    print("A. 真实 .bdg → MidiFile（每条 BDG 轨 = 一条音轨）")
    p, rep = bdg.load_file(os.path.join(FIX, "v2_real_electric_hornet.bdg"))
    mf = S.to_midi_like(p)
    check(mf.ppqn == S.PPQN and abs(mf.bpm0 - 192.0) < 1e-9,
          f"ppqn={mf.ppqn} bpm0={mf.bpm0}（取他的 baseBpm）")
    check(len(mf.tracks) == 6, f"6 条音轨（实得 {len(mf.tracks)}）")
    check([len(t.notes) for t in mf.tracks] == [413, 231, 29, 191, 2, 0],
          f"每轨点数 {[len(t.notes) for t in mf.tracks]}")
    check(all(not t.is_drum_only() for t in mf.tracks),
          "都不是「架子鼓」（channel 0 ⇒ 显示成旋律）")
    check(sum(len(t.notes) for t in mf.tracks) == 866, "点数合计 866（一个不丢）")

    # 毫秒必须用**他的**时间锚，且与 fixture 里自带的 timeMs 一致
    n0 = mf.tracks[0].notes[0]
    pts = [x for x in p.points if x.track_id == p.tracks[0].id]
    check(abs(n0.t_on_ms - pts[0].time_ms) < 1e-9,
          f"第一个音的毫秒 = {n0.t_on_ms}（= offsetMs 1325 + 0.0064 拍）")
    check(abs(mf.length_ms - 133670.75) < 0.01, f"长度 {mf.length_ms:.2f} ms")
    check(all(n.t_on_ms == n.t_off_ms for t in mf.tracks for n in t.notes),
          "零长音（BDG 只有拍位，没有音长 —— 不假装）")


def B_describe_and_hints():
    print("=" * 78)
    print("B. 给 UI 的轨道清单 + **只做建议**的角色提示")
    p, _ = bdg.load_file(os.path.join(FIX, "v2_real_electric_hornet.bdg"))
    mf = S.to_midi_like(p)
    rows = S.describe_tracks(p, mf)
    check(len(rows) == 6, "6 行")
    check(sum(r[al.K_NOTES] for r in rows) == 866, "点数合计 866")
    check(all(al.K_SUMMARY in r for r in rows), "每行带摘要（现有三条列表直接用）")
    hints = S.role_hints(p)
    check(hints == {4: al.ROLE_OFF, 5: al.ROLE_OFF},
          f"★ 建议角色只给出「控制轨 → 关」：{hints}（其余**留空让用户勾**）")
    check(rows[0][al.K_SUGGEST] == "" and rows[4][al.K_SUGGEST] == al.ROLE_OFF,
          "第 1 行没建议、第 5 行建议 off")

    # 角色轨 + hidden 的建议
    raw = {"name": "x", "baseBpm": 120.0, "offsetMs": 0.0, "bpmPoints": [],
           "tracks": [{"id": "a", "name": "主", "color": "#fff", "locked": False,
                       "hidden": False, "type": "dev.adocharter.bdg-bridge:main"},
                      {"id": "b", "name": "双", "color": "#fff", "locked": False,
                       "hidden": False, "type": "dev.adocharter.bdg-bridge:dp"},
                      {"id": "c", "name": "藏", "color": "#fff", "locked": False,
                       "hidden": True},
                      {"id": "d", "name": "别人", "color": "#fff", "locked": False,
                       "hidden": False, "type": "someone-else:whatever"}],
           "markers": [{"id": "m1", "trackId": "a", "beat": 0.0},
                       {"id": "m2", "trackId": "b", "beat": 1.0},
                       {"id": "m3", "trackId": "c", "beat": 2.0},
                       {"id": "m4", "trackId": "d", "beat": 3.0}]}
    p2, _ = bdg.parse(raw)
    h2 = S.role_hints(p2)
    check(h2.get(0) == al.ROLE_MAIN and h2.get(1) == al.ROLE_DP,
          f"插件角色轨 → 建议 main/dp：{h2}")
    check(h2.get(2) == al.ROLE_OFF, "★ hidden 轨 → 建议「关」（宿主白送的开关）")
    check(h2.get(3) == al.ROLE_OFF, "别家插件的轨 → 建议「关」")


def C_through_our_pipeline():
    print("=" * 78)
    print("C. ★ 走**我们原有的**采音：勾选主轨 → 并集 → onsets")
    p, _ = bdg.load_file(os.path.join(FIX, "v2_real_electric_hornet.bdg"))
    mf = S.to_midi_like(p)
    main = [mf.tracks[i] for i in (0, 1, 2, 3)]        # 用户勾前 4 条当主轨
    ons = O.build_onsets_multi(main, O.OnsetParams(merge_ms=30.0))
    check(len(ons) == 629, f"并集采出 {len(ons)} 个 onset（多轨同刻合并掉）")
    check(all(ons[i].t_ms <= ons[i + 1].t_ms + 1e-9 for i in range(len(ons) - 1)),
          "按时间单调")
    ids = {id(t) for t in main}
    once = O.build_onsets([n for t in mf.tracks if id(t) in ids for n in t.notes],
                          O.OnsetParams(merge_ms=30.0))
    check(len(once) == len(ons), "与把所有音拉平再采的结果一致（并集语义对）")

    # 只勾别的轨：点会变 ⇒ 用户的选择真的有效
    only2 = O.build_onsets_multi([mf.tracks[2]], O.OnsetParams(merge_ms=30.0))
    check(len(only2) == 29, f"只勾第 3 条轨 ⇒ {len(only2)} 个 onset")
    check(len(only2) < len(ons), "勾不同轨结果不同 ⇒ 「让用户自己选择它做什么」成立")

    # 求解器入口也能吃（只验接口，不验音乐性）
    from core.solve import SolveParams
    sp = SolveParams(ppqn=mf.ppqn, midi_bpm=mf.bpm0)
    check(sp.ppqn == 960 and abs(sp.midi_bpm - 192.0) < 1e-9,
          "SolveParams 能直接用 MidiFile 的 ppqn/bpm0（下游无需改）")


def D_speed_blend():
    print("=" * 78)
    print("D. 「结合」的第一步：他的变速能不能用我们的合法档复现")
    p, _ = bdg.load_file(os.path.join(FIX, "v2_real_electric_hornet.bdg"))
    h = S.speed_hints(p)
    check(len(h) == 3 and h[0][al.K_MS] < h[-1][al.K_MS], f"3 个变速点按毫秒排好：{len(h)}")
    check(any(x["at"] == "pluginTrack" and x["value"] == 2.0 for x in h),
          "★ 认出真变速在**插件轨**上（multiplier 2），而不是宿主那个空转的 no-op")
    fit = S.ladder_fit(p)
    check(fit["n_approx"] == 0 and fit["n_exact"] == 3,
          f"★ 他的 3 个变速**全部能落在我们的 2 的幂档上**（精确 {fit['n_exact']} / 近似 {fit['n_approx']}）")
    check(all(r["dev_pct"] == 0.0 for r in fit["rows"] if r.get("dev_pct") is not None),
          "偏差 0%")

    # 不能被照抄的情况：multiplier 1.7
    raw = {"name": "x", "baseBpm": 120.0, "offsetMs": 0.0, "bpmPoints": [],
           "tracks": [{"id": "t", "name": "bpm", "color": "#fff", "locked": False,
                       "hidden": False, "type": "dev.bdg.adofai-export:bpm"}],
           "markers": [{"id": "m", "trackId": "t", "beat": 4.0,
                        "attrs": {"speedType": "multiplier", "value": 1.7}}]}
    p3, _ = bdg.parse(raw)
    fit3 = S.ladder_fit(p3)
    r = fit3["rows"][0]
    check(r["fit"] == "近似" and r["nearest"] in (1.5, 2.0),
          f"★ 1.7 照抄不了 ⇒ 给最近合法档 {r['nearest']}（差 {r['dev_pct']}%）—— **报出来，不静默**")


def main():
    A_file_to_tracks()
    B_describe_and_hints()
    C_through_our_pipeline()
    D_speed_blend()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ .bdg 当生成源 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
