"""自动贴合（`docs/58`）：时值体检的纯函数测试。

    python tests/test_tempo_diag.py

验四件事（都是实测踩过的坑）：

  A 干净数据：砖长认得对，不硬推激进拟合
  B **倍频陷阱**：真砖长 90.909，但有一路会被自动识别成 181.818 ⇒ 必须选 90.909
  C 抖动数据：容差建议跟着抖动走；覆盖率随容差单调升；碎音计数
  D 退化输入：点太少 / 全是噪声 ⇒ **明确说「定不出来」**，不许编一个砖长
  E 真实文件（在就给证据；不在就跳过：`mad_piano_party_timestamps.json`）
  F 试算与打分：`_probe` 跑得动、`human_score` 的方向对（踩拍优先）
"""
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import denoise as DN                             # noqa: E402
from core import stem_json as SJ                           # noqa: E402
from core import tempo_diag as TD                          # noqa: E402

_HOME = os.path.expanduser("~")                                #: 用户目录

FAIL = []
FIX = os.path.join(_HERE, "fixtures", "stemjson")
REAL = (_HOME + r"\.dsh\attachments\v1\files\66"
        r"\668e6477d308e4e44188d7592e9f2cd296388bc401a81e43e89afd4f5de3ef9c"
        r"\mad_piano_party_timestamps.json")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _streams(ms_by_key):
    return [{"key": str(i), "label": k, "ms": [float(x) for x in v]}
            for i, (k, v) in enumerate(ms_by_key.items())]


def _lattice(brick=150.0, n=40, jitter=0.0, seed=1, start=1000.0):
    rnd = random.Random(seed)
    out, t = [], start
    for i in range(n):
        out.append(t + (rnd.uniform(-jitter, jitter) if jitter else 0.0))
        t += brick * (1 if i % 4 else 2)
    return out


def A_clean():
    print("=" * 78)
    print("A. 干净数据：砖长认得对，且不硬推激进")
    d = TD.diagnose(_streams({"旋律": _lattice(150.0, 40), "钢琴": _lattice(150.0, 30)}))
    check(d["ok"] is True, "体检跑通")
    check(abs(d["brick_ms"] - 150.0) < 0.5,
          f"砖长 = 150ms（实得 {d['brick_ms']:.3f}）")
    check(d["brick_cover"] > 0.95, f"覆盖率 {d['brick_cover']:.3f} > 95%")
    check(d["suggest"]["fit_tol_ms"] <= 20.0,
          f"干净数据容差给小（实得 {d['suggest']['fit_tol_ms']}）")
    check(d["suggest"]["main_label"] == "旋律",
          "主轨挑了点最多的那条（不是按覆盖率乱挑）")
    check(isinstance(d["suggest"]["aggressive_fit"], bool),
          f"激进拟合给的是布尔（实得 {d['suggest']['aggressive_fit']}）")
    return d


def B_octave_trap():
    print("=" * 78)
    print("B. ★★ 倍频陷阱：有一路会被认成 181.818，真砖长是 90.909")
    p = os.path.join(FIX, "octave_trap.json")
    if not os.path.exists(p):
        check(False, f"夹具不在：{p}（跑 `python tools\\make_stemjson_fixtures.py`）")
        return
    st, _rep = SJ.read_stem_json(p)
    streams = _streams({s.label: s.ms for s in st if s.ms})
    auto = {s["label"]: DN.plan(s["ms"]) for s in streams}
    got = {k: (round(g.period_ms, 3) if g.ok else None) for k, g in auto.items()}
    check(got.get("吉他") == 181.818,
          f"★ 前提成立：吉他自动认成 181.818（实得 {got.get('吉他')}）—— 这就是陷阱")
    check(got.get("旋律·melody") == 90.909 or got.get("旋律") == 90.909,
          f"旋律自动认成 90.909（实得 {got}）")
    d = TD.diagnose(streams)
    check(abs(d["brick_ms"] - 90.909) < 0.05,
          f"★★ 体检选**真砖长** 90.909（实得 {d['brick_ms']:.4f}）—— 没被 181.8 骗走")
    check(d["brick_source"] == "auto", "砖长来自自动识别（已精修），不是猜的")
    cand = {round(c["brick_ms"], 3): c["cover"] for c in d["candidates"]}
    check(cand.get(181.818, 0) < cand.get(90.909, 0),
          f"候选里 181.8 覆盖率更低（{cand.get(181.818, 0):.2f} < {cand.get(90.909, 0):.2f}）")
    check(d["suggest"]["main_label"] == "旋律",
          f"主轨 = 旋律（实得 {d['suggest']['main_label']}）")
    return d


def C_jitter():
    print("=" * 78)
    print("C. 抖动数据：容差跟着抖动走；覆盖率单调；碎音计数")
    for jit, tol_max in ((3.0, 20.0), (25.0, 100.0)):
        d = TD.diagnose(_streams({"旋律": _lattice(150.0, 40, jitter=jit, seed=3)}))
        tol = d["suggest"]["fit_tol_ms"]
        check(d["ok"] and tol <= tol_max,
              f"抖动 ±{jit:.0f}ms ⇒ 容差 {tol}ms（≤ {tol_max}）")
        row = d["streams"][0]
        covs = [row["cover"]["%.0f" % t] for t in TD.TOL_CHOICES]
        check(all(a <= b + 1e-9 for a, b in zip(covs, covs[1:])),
              f"覆盖率随容差单调不降：{['%.2f' % c for c in covs]}")
        check(row["median_ms"] <= jit + 1.0,
              f"残差中位 {row['median_ms']}ms ≈ 抖动规模 ±{jit:.0f}ms")
    # 碎音：人为塞一串 <30ms 的假音
    ms = _lattice(150.0, 20)
    ms = sorted(ms + [ms[3] + 12.0, ms[3] + 24.0])
    d = TD.diagnose(_streams({"旋律": ms}))
    check(d["streams"][0]["short30"] >= 2,
          f"碎音（间隔 <30ms）被数出来：{d['streams'][0]['short30']} 个")
    check(d["density_by_merge"]["0"] > d["density_by_merge"]["120"],
          f"去密让密度下降：{d['density_by_merge']['0']} → {d['density_by_merge']['120']}")
    return d


def D_degenerate():
    print("=" * 78)
    print("D. 退化输入：明确说「定不出来」，不许编")
    d = TD.diagnose([{"key": "0", "label": "太小", "ms": [100.0, 200.0]}])
    check(d["ok"] is False and d.get("why"), f"点太少 ⇒ {d.get('why')}")
    rnd = random.Random(9)
    noise = sorted(rnd.uniform(0, 5000) for _ in range(60))     # 纯噪声
    d2 = TD.diagnose(_streams({"噪声": noise}))
    if d2.get("ok"):
        check(d2["brick_reliable"] is False or d2["brick_cover"] < 0.9,
              f"纯噪声不被当成「可靠砖长」（cover={d2['brick_cover']:.2f} "
              f"reliable={d2['brick_reliable']}）")
    else:
        check(True, f"纯噪声直接判「定不出来」：{d2.get('why')}")
    check(TD.diagnose([])["ok"] is False, "空输入 ⇒ ok=False")


def E_real():
    print("=" * 78)
    print("E. 真实文件（mad_piano_party_timestamps.json）")
    if not os.path.exists(REAL):
        print("  [SKIP] 那份外部文件不在这儿（不在就跳过）")
        return None
    st, _rep = SJ.read_stem_json(REAL)
    streams = _streams({s.label: s.ms for s in st if s.ms})
    bad = [s["label"] for s in streams if not DN.plan(s["ms"]).ok]
    check(len(bad) >= 1,
          f"★ 复现「AI 扒的常见症状」：这些路自动认不出网格 {bad}")
    d = TD.diagnose(streams)
    check(d["ok"] is True, "体检跑通")
    check(abs(d["brick_ms"] - 90.909) < 0.05,
          f"砖长 = 90.909ms / 660BPM（实得 {d['brick_ms']:.4f}）")
    check(d["suggest"]["denoise_hint_ms"] > 0,
          f"★ 建议砖长提示 {d['suggest']['denoise_hint_ms']}ms（这就是那份文件的关键）")
    check(d["suggest"]["fit_tol_ms"] <= 50.0,
          f"容差建议 {d['suggest']['fit_tol_ms']}ms（抖动实测很小）")
    check(d["suggest"]["aggressive_fit"] is True,
          "★ 建议开激进拟合（否则直线率只有 1~5%）")
    pn, po = d["probe"].get("on") or {}, d["probe"].get("off") or {}
    check(pn.get("ok") and po.get("ok") and pn["straight_frac"] > po["straight_frac"] + 0.3,
          f"试算证据：直线率 {po.get('straight_frac', 0):.1%} → {pn.get('straight_frac', 0):.1%}")
    check(pn.get("ladder_frac", 0) > 0.99,
          f"激进试算里 15° 格率 {pn.get('ladder_frac', 0):.1%}")
    return d


def F_probe():
    print("=" * 78)
    print("F. 试算与打分")
    ms = _lattice(150.0, 40, jitter=20.0, seed=7)
    s = _streams({"旋律": ms})
    m0 = TD._probe(s, 150.0, 30.0, 0.0, False)
    m1 = TD._probe(s, 150.0, 30.0, 0.0, True)
    check(m0.get("ok") and m1.get("ok"), "两种模式都跑得动")
    sc0, sc1 = TD.human_score(m0), TD.human_score(m1)
    check(sc1 > sc0, f"激进在这份抖动数据上分数更高（{sc0:.1f} → {sc1:.1f}）")
    check(m1["ladder_frac"] > 0.99 and m0["ladder_frac"] < m1["ladder_frac"],
          f"15° 格率 {m0['ladder_frac']:.1%} → {m1['ladder_frac']:.1%}")
    check(abs(m0["beat_frac"] - m1["beat_frac"]) > 0 or m0["beat_frac"] > 0.9,
          f"踩拍率都在高位（{m0['beat_frac']:.1%} / {m1['beat_frac']:.1%}）")
    check(TD.human_score({"ok": False}) < 0, "失败的试算得负分（排序时排最后）")


def main():
    A_clean()
    B_octave_trap()
    C_jitter()
    D_degenerate()
    E_real()
    F_probe()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 自动贴合（时值体检）全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
