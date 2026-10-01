"""毫秒时间戳当来源（`docs/45` §7）。

    python tests/test_ts_source.py

用户那条箭头的第一段：**毫秒时间戳 → （BDG/我们）**。本套件验：

  A 解析（四种格式 + 不静默）
  B `MidiFile-like` 的形状（下游「选轨→采音→求解」一行都不用改）
  C 网格规划（砖长/相位/分母）
  D `Session.load()`：三种默认值（merge_ms=0 / 直拟合 / 去噪开）
  E 直拟合自检：**时序误差 = 0**
  F **没有源文件**也能重建（`ensure_engine`「仅时间轴」引擎）
  G 真数据（那份 1358 个时间戳，有就跑）
"""
import json
import os
import random
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import ts_source as TS                          # noqa: E402
from core import denoise as DN                            # noqa: E402
from sidecar import schema as SC                          # noqa: E402
from sidecar.session import Session                       # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

FAIL = []
REAL = os.path.join(
    _HOME + r"\.dsh\attachments\v1\files\0a",
    "0aed72d9d890d040d5c6834bb8dc527618f8b0b8ec21d0bdaa1d1ef34f912149",
    "Flower_Dance-DJ_OKAWARI-1974307.txt")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _write(text, ext=".txt"):
    d = tempfile.mkdtemp(prefix="adoc_ts_")
    p = os.path.join(d, "ts" + ext)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def _lattice_ts(n=60, period=150.0, phase=76.871, jitter=3.0, seed=3):
    rnd = random.Random(seed)
    out = []
    t = phase
    for i in range(n):
        out.append(t + (rnd.uniform(-jitter, jitter) if jitter else 0.0))
        step = 4 if i % 7 else 2          # 大多数整砖，偶尔半砖
        t += step * period / 4
    return sorted(out)


def A_parse():
    print("=" * 78)
    print("A. 解析：四种格式 + 不静默")
    p = _write("691\n882\n1091\n1248\n")
    ts, rep = TS.read_ts(p)
    check(ts == [691.0, 882.0, 1091.0, 1248.0], f"一行一个数：{ts}")
    check(rep["n_lines"] == 4 and rep["n_skipped"] == 0, str(rep))

    p = _write("# 注释\n0,691\n1,882\n\n2,1091 extra\n")
    ts, rep = TS.read_ts(p)
    check(ts == [691.0, 882.0, 1091.0], f"CSV 取每行**最后一个**数：{ts}")
    check(rep["n_skipped"] >= 2, f"注释与空行计进 skipped：{rep['n_skipped']}")

    p = _write("0:00.691\n0:01.234\n1:02.500\n")
    ts, rep = TS.read_ts(p)
    check(ts == [691.0, 1234.0, 62500.0], f"mm:ss.xxx：{ts}")
    check(rep["fmts"].get("clock") == 3, str(rep["fmts"]))

    p = _write('[691, 882, 1091]', ".json")
    ts, _rep = TS.read_ts(p)
    check(ts == [691.0, 882.0, 1091.0], f"JSON 数组：{ts}")
    p = _write(json.dumps({"timestamps": [691, 882], "junk": 1}), ".json")
    ts, _rep = TS.read_ts(p)
    check(ts == [691.0, 882.0], f"JSON 带键：{ts}")

    p = _write("1000\n1000\n500\n-3\nabc\n")
    ts, rep = TS.read_ts(p)
    check(ts == [500.0, 1000.0] and rep["n_dup"] == 1 and rep["n_bad"] == 1,
          f"去重/丢负数：{ts} dup={rep['n_dup']} bad={rep['n_bad']}")
    check("跳过" in TS.report_text(rep) or rep["n_skipped"] == 1, "报告里有跳过计数")


def B_midi_like():
    print("=" * 78)
    print("B. MidiFile-like：下游一行不用改")
    ts = _lattice_ts()
    mf = TS.to_midi_like(ts)
    check(len(mf.tracks) == 1 and len(mf.tracks[0].notes) == len(ts),
          "一条轨 / {} 个 Note".format(len(ts)))
    check(mf.ppqn == TS.PPQN and mf.bpm0 > 0, f"ppqn={mf.ppqn} bpm0={mf.bpm0:.3f}")
    check(abs(mf.length_ms - (ts[-1] + TS.TAIL_BEATS * 60000.0 / mf.bpm0)) < 1e-6,
          "尾部留了余量（谱面/预览要尾巴）")
    check(all(abs(n.t_on_ms - n.t_off_ms) < 1e-9 for n in mf.tracks[0].notes),
          "零长音（时间戳没有音长信息，不假装）")
    check(mf.grid_fit is not None and "砖长" in mf.grid_fit.describe(),
          "带 grid_fit（文件信息行直接显示网格）")
    check(not mf.tracks[0].is_drum_only(), "不是鼓轨（默认通道 0，显示成旋律）")


def C_grid():
    print("=" * 78)
    print("C. 网格规划 = 去噪/直拟合/桥接锚的**同一个真源**")
    ts = _lattice_ts(n=80)
    info = TS.grid_info(ts)
    g = DN.plan(ts)
    check(info["ok"], f"网格通过：{info.get('reason') or 'OK'}")
    check(abs(info["period_ms"] - 150.0) < 0.05,
          f"砖长精修到 150（实得 {info['period_ms']:.4f}）")
    check(info["div"] == 4, f"自动分母 1/4（实得 1/{info['div']}）")
    check(abs(info["phase_ms"] - g.phase_ms) < 1e-6, "与 core.denoise.plan 同源（只差 6 位取整）")
    # 连不上/算不出来时也要给个说法（不许静默）
    bad = TS.grid_info([0.0, 1.0])
    check(bad["ok"] is False and bad.get("reason"), f"点太少 ⇒ 明确失败：{bad.get('reason')}")


def D_load():
    print("=" * 78)
    print("D. Session.load()：三种默认值")
    ts = _lattice_ts(n=40)
    p = _write("\n".join("%.3f" % x for x in ts) + "\n")
    s = Session(_ROOT)
    info = s.load(p)
    check(info.get("is_ts") is True, "标明来源是时间戳")
    check(len(info["tracks"]) == 1 and info["tracks"][0]["notes"] == len(ts),
          f"一条音轨 / {len(ts)} 点")
    check(info.get("default_merge_ms") == 0.0,
          "★ 默认 merge_ms=0（30ms 会把密集处的点**悄悄并掉**）")
    check(info.get("default_fit_mode") == "direct", "★ 默认走直拟合")
    check(info.get("default_denoise_on") is True, "★ 默认开去噪")
    check(bool(info.get("grid_fit")), "文件信息里有网格行")

    # merge_ms=0 vs 30：造两个只差 8ms 的点，验证「不许被吃掉」
    dense = [1000.0 + i * 8.0 for i in range(20)]
    p2 = _write("\n".join("%.1f" % x for x in dense) + "\n")
    s2 = Session(_ROOT)
    s2.load(p2)
    st = dict(SC.defaults())
    st["tracks_checked"] = [0]
    st["merge_ms"] = 0.0
    st["fit_mode"] = "solve"
    st["dp_checked"] = []
    r0 = s2.rebuild(st)
    st30 = dict(st)
    st30["merge_ms"] = 30.0
    r30 = s2.rebuild(st30)
    check(r0.get("n_onsets") == 20, f"merge=0 ⇒ 20 个点全在（实得 {r0.get('n_onsets')}）")
    check(r30.get("n_onsets", 99) < 20,
          f"merge=30 ⇒ 被并掉（实得 {r30.get('n_onsets')}）—— 这就是默认必须为 0 的原因")


def E_rebuild():
    print("=" * 78)
    print("E. 直拟合自检：时序误差 = 0")
    ts = _lattice_ts(n=60)
    p = _write("\n".join("%.3f" % x for x in ts) + "\n")
    s = Session(_ROOT)
    s.load(p)
    st = dict(SC.defaults())
    st["tracks_checked"] = [0]
    st["merge_ms"] = 0.0
    st["fit_mode"] = "direct"
    st["denoise_on"] = True
    st["dp_checked"] = []
    r = s.rebuild(st)
    check(r.get("ok"), str(r.get("msg") or r.get("error"))[:120])
    check(r.get("n_onsets") == len(ts), f"onset 数 = {r.get('n_onsets')}")
    fit = r.get("fit") or {}
    check(fit.get("err_max_ms") == 0.0,
          f"★★ 时序误差 max {fit.get('err_max_ms')}ms（必须是 0）")
    check((r.get("denoise") or {}).get("grid"), "去噪报告在返回里")
    check(any("直拟合" in w for w in (r.get("warning_list") or [])),
          "直拟合那条警告上屏")
    check(abs((r.get("denoise") or {}).get("bpm", 0) - 400.0) < 1.0,
          f"去噪 bpm≈400（实得 {(r.get('denoise') or {}).get('bpm')}）")


def F_no_file():
    print("=" * 78)
    print("F. 没有源文件也能重建（「仅时间轴」引擎）")
    s = Session(_ROOT)
    check(s.midi is None, "一开始没有文件")
    pay = {"run": "NF", "anchor": {"baseBpm": 400.0, "offsetMs": 2.131},
           "tracks": [{"name": "ADO·时间戳", "role": "main", "lane": "main:0",
                       "src_track": 0,
                       "points": [{"idx": i, "beat": i * 1.0,
                                   "ms": 1000.0 + i * 150.0,
                                   "src_tracks": [0]} for i in range(8)]}]}
    out = s.restore_tracks(pay)
    check(out.get("ok"), str(out)[:120])
    check(s.midi is not None, "★ 自动造了「仅时间轴」引擎")
    check(any("仅时间轴" in w for w in s.warnings), "并把这件事说出来（不许静默）")
    st = dict(SC.defaults())
    st["merge_ms"] = 0.0
    st["fit_mode"] = "direct"
    r = s.rebuild(st)
    check(r.get("ok"), str(r.get("msg") or r.get("error"))[:120])
    check(r.get("n_onsets") == 8, f"收回的 8 个点直接成谱（实得 {r.get('n_onsets')}）")
    check((r.get("fit") or {}).get("err_max_ms") == 0.0, "时序仍然逐点精确")
    check(s.track_map().get("lanes_back") is True, "音轨列表 = 收回的那些轨")


def G_real():
    print("=" * 78)
    print("G. 真数据（Flower_Dance 1358 个时间戳）")
    if not os.path.exists(REAL):
        print("  [SKIP] 找不到那份外部时间戳")
        return
    s = Session(_ROOT)
    info = s.load(REAL)
    check(info.get("is_ts") and (info.get("ts") or {}).get("n_kept") == 1358,
          f"读到 1358 个点（实得 {(info.get('ts') or {}).get('n_kept')}）")
    check(abs((info.get("ts_grid") or {}).get("bpm", 0) - 400.0) < 1e-6,
          f"网格 bpm 恰好 400（实得 {(info.get('ts_grid') or {}).get('bpm')}）")
    st = dict(SC.defaults())
    st["tracks_checked"] = [0]
    st["merge_ms"] = 0.0
    st["fit_mode"] = "direct"
    st["dp_checked"] = []
    r = s.rebuild(st)
    check(r.get("ok") and r.get("n_onsets") == 1358,
          f"1358 个点成谱（实得 {r.get('n_onsets')}）")
    fit = r.get("fit") or {}
    check(fit.get("err_max_ms") == 0.0, f"★★ 时序误差 {fit.get('err_max_ms')}ms")
    check(fit.get("straight_frac", 0) > 0.8,
          f"直线率 {fit.get('straight_frac', 0):.1%}")


def H_struct_json():
    print("=" * 78)
    print("H. ★ 结构化 JSON **不许**被当时间戳（`docs/56` §3 那条隐患）")
    # 症状（修之前）：`_from_json` 在顶层找不到已知键时，把**顶层所有数字**当时刻 ⇒
    # 一份「时间戳 JSON（DEMUCS 分轨）」被读成 [version, hop_ms, duration_sec, sr]
    # = 一张 4 层的垃圾谱，而且界面显示得像成功了。现在必须**明确拒绝**。
    garbage = json.dumps({
        "version": 1, "source_audio": "a.wav", "duration_sec": 202.378,
        "sample_rate": 22050, "hop_ms": 5.805, "has_vocals": True,
        "bpm_hint": None,
        "stems": {"melody": {"source": "other", "method": "onsetnet",
                             "onsets_sec": [1.0, 2.0], "onsets_frame": [1, 2]}}})
    p = _write(garbage, ".json")
    ts, rep = TS.read_ts(p)
    check(ts == [], f"读成空（实得 {ts}）")
    check(ts != [1.0, 5.805, 202.378, 22050.0], "不再是「顶层数字」那张垃圾谱")
    check("结构化文件" in (rep.get("json_reject") or ""),
          f"★ 拒绝原因说清是什么文件：{rep.get('json_reject')}")
    check("stems" in (rep.get("json_reject") or ""), "并点名 `stems`（用户一看就懂）")

    # 不是 JSON（后缀是 .json 但内容是一行一个数）⇒ **照旧**能读（不许误伤）
    p = _write("691\n882\n1091\n", ".json")
    ts, _rep = TS.read_ts(p)
    check(ts == [691.0, 882.0, 1091.0], f"一行一个数的 .json 照旧能读：{ts}")

    # JSON 数组带版本号也照旧（已知键优先于「结构化指纹」）
    p = _write(json.dumps({"version": 3, "timestamps": [691, 882]}), ".json")
    ts, _rep = TS.read_ts(p)
    check(ts == [691.0, 882.0], f"已知键优先：{ts}")

    # ★ 含 NaN 的序列必须**先过滤再排序**（NaN 没有全序，sorted() 会给乱序）
    clean = TS.clean_points([1000.0, 1000.0, -500.0, float("nan"),
                             float("nan"), 2000.0, 3000.0], {})
    check(clean == [1000.0, 2000.0, 3000.0],
          f"★ NaN 不参与排序：{clean}")


def main():
    A_parse()
    B_midi_like()
    C_grid()
    D_load()
    E_rebuild()
    F_no_file()
    G_real()
    H_struct_json()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 时间戳来源全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
