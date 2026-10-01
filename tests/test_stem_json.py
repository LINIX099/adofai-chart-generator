# -*- coding: utf-8 -*-
"""**时间戳 JSON（DEMUCS 分轨 · 多路音头）** 当来源（`docs/56`）。

    python tests/test_stem_json.py

用户口径（2026-10）：「这是一个新的常用格式，我希望我们的**桥接器、生成逻辑**可以
基于它做一些兼容，**就像是现在兼容纯时间戳那样**。」

本套件验：

  A 嗅探：认得出 `stems`，认不出别的结构化 JSON
  B 正常 6 路：路名 / 点数 / 毫秒换算 / head 字段 / **零警告**
  C 键不固定：no_vocals / no_piano / one_stem / empty_stem（不建轨 + 报出来）
  D 取舍账：未排序 / 重复 / 负 / null / NaN / sec↔frame 偏差 / 未知版本
  E ★ 结构化 JSON **不许**被当时间戳（`not_stem.json` 这条回归）
  F `to_midi_like`：**一路一轨** / 建议角色 / 默认勾选
  G `Session.load()`：默认值（merge_ms=0 / 直拟合 / 去噪开）+ 原曲绑定 + 出谱
  H 内置示例（`samples/` 那份）能被列出并出谱
"""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

# ★ 本套件的说明里带 `⇒`（GBK 里没有）—— 直接跑 `python tests/test_stem_json.py`
#   也能出结果（不然会在打印第一条断言时 UnicodeEncodeError）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import stem_json as SJ                          # noqa: E402
from core import ts_source as TS                          # noqa: E402
from sidecar import schema as SC                          # noqa: E402
from sidecar.session import BadRequest, Session           # noqa: E402

FIX = os.path.join(_HERE, "fixtures", "stemjson")
SAMPLE = os.path.join(_ROOT, "samples", "示例·分轨时间戳.json")
FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _fix(name):
    return os.path.join(FIX, name)


def _read(name):
    with open(_fix(name), "r", encoding="utf-8") as fh:
        return fh.read()


def _warns(rep):
    return "\n".join(rep.get("warnings") or [])


def A_looks():
    print("=" * 78)
    print("A. 嗅探：认得出 stems，认不出别的结构化 JSON")
    check(SJ.looks_like_stem_json(_read("full_6stems.json")), "6 路那份认得出")
    check(SJ.looks_like_stem_json("{\"stems\": {}}"), "空 stems 也算这个格式（会明确报空）")
    check(not SJ.looks_like_stem_json(_read("not_stem.json")),
          "★ BDG 味的工程**不**算时间戳 JSON")
    check(not SJ.looks_like_stem_json("[]"), "JSON 数组不是")
    check(not SJ.looks_like_stem_json("1\n2\n3\n"), "一行一个数不是")
    check(SJ.looks_like_stem_json_file(_fix("full_6stems.json")), "按文件嗅探 == 按内容嗅探")
    check(not SJ.looks_like_stem_json_file(_fix("not_stem.json")), "not_stem 文件为假")


def B_full():
    print("=" * 78)
    print("B. 正常 6 路：路名 / 点数 / 毫秒换算 / head / 零警告")
    stems, rep = SJ.read_stem_json(_fix("full_6stems.json"))
    keys = [s.key for s in stems]
    check(keys == ["melody", "vocals", "drums", "bass", "guitar", "piano"],
          "路名与顺序照 JSON：{}".format(keys))
    check([s.label for s in stems] == ["旋律", "人声", "鼓", "贝斯", "吉他", "钢琴"],
          "中文路名")
    check([s.n for s in stems] == [32, 8, 16, 12, 9, 6], "每路点数")
    check(rep["n_kept"] == 83 and rep["meta"]["n_points"] == 83, "共 83 个音头")
    mel = stems[0]
    check(abs(mel.ms[0] - 1000.0) < 1e-9 and abs(mel.ms[1] - 1150.0) < 1e-9,
          "★ 秒 → 毫秒（×1000）：{}".format(mel.ms[:3]))
    check(mel.source == "other" and mel.method == "onsetnet"
          and mel.model == "onset_net_melody.pt",
          "★ melody 的 source 是 **other**（文档自己标过的命名陷阱）")
    check(stems[2].method == "spectral_flux" and not stems[2].model,
          "频谱通量通道没有 model 字段（照实）")
    m = rep["meta"]
    check(m["version"] == 1 and m["version_ok"], "version=1")
    check(abs(m["hop_ms"] - 5.0) < 1e-9 and m["sample_rate"] == 22050,
          "hop={} sr={}".format(m["hop_ms"], m["sample_rate"]))
    check(abs(m["duration_ms"] - 202378.0) < 1e-6,
          "duration_sec → ms：{}".format(m["duration_ms"]))
    check(m["separation_model"] == "htdemucs_6s" and m["has_vocals"] is True,
          "separation_model / has_vocals 带出来")
    check(rep["warnings"] == [],
          "★ 干净文件**一条警告都没有**（实得 {} 条）".format(len(rep["warnings"])))
    check(SJ.report_text(rep).count("\n") >= 7, "人话报告有每一路一行")
    check([s.n_frame for s in stems] == [s.n for s in stems],
          "onsets_frame 等长（规格要求）")
    check(stems[0].n_frame_bad == 0, "sec 与 frame×hop 对得上 ⇒ 不报偏差")


def C_variants():
    print("=" * 78)
    print("C. 键不固定：no_vocals / no_piano / one_stem / empty_stem")
    st, rep = SJ.read_stem_json(_fix("no_vocals.json"))
    check([s.key for s in st] == ["melody", "drums"], "纯音乐：没有 vocals 键也不炸")
    check(rep["meta"]["has_vocals"] is False, "has_vocals=false 带出来")
    check(rep["warnings"] == [], "has_vocals 与键一致 ⇒ 不警告")

    st, rep = SJ.read_stem_json(_fix("no_piano.json"))
    check("piano" not in [s.key for s in st], "--no-piano ⇒ 少一路")
    check([s.n for s in st] == [8, 2, 2, 2, 2], "其余路照常")

    st, rep = SJ.read_stem_json(_fix("one_stem.json"))
    check(len(st) == 1 and st[0].n == 7, "单路也能读")
    mf = SJ.to_midi_like(st, meta=rep["meta"])
    check(len(mf.tracks) == 1 and len(mf.tracks[0].notes) == 7, "单路也能出谱（1 轨 7 点）")

    st, rep = SJ.read_stem_json(_fix("empty_stem.json"))
    check([s.key for s in st] == ["melody", "bass", "drums"], "空路仍然在报告里")
    check(st[1].key == "bass" and st[1].n == 0, "空路 0 点")
    check(rep["n_live"] == 2 and rep["n_kept"] == 12, "只有 2 路有料")
    check("不建轨" in _warns(rep), "★ 空路**明确报出来**：{}".format(
        (rep["warnings"] or ["（无）"])[0][:60]))
    mf = SJ.to_midi_like(st, meta=rep["meta"])
    check(len(mf.tracks) == 2, "空路**不建轨**（实得 {} 条）".format(len(mf.tracks)))


def D_clean():
    print("=" * 78)
    print("D. 取舍账：未排序 / 重复 / 负 / null / NaN / sec↔frame / 未知版本")
    st, rep = SJ.read_stem_json(_fix("unsorted.json"))
    mel = st[0]
    check(mel.ms == sorted(mel.ms), "未排序 ⇒ 已排序：{}".format(mel.ms[:4]))
    check(mel.n_unsorted >= 1, "逆序**计数**记下来（{} 处）".format(mel.n_unsorted))
    check("未排序" in _warns(rep), "报告里说出来")

    st, rep = SJ.read_stem_json(_fix("dup_and_bad.json"))
    mel = st[0]
    check(mel.n == 3, "清洗后 3 个点（实得 {}）：{}".format(mel.n, mel.ms))
    check(mel.n_dup == 1, "同刻合并计数（{}）".format(mel.n_dup))
    check(mel.n_bad == 4, "负 / null / 非数字 / NaN 全进 n_bad（{}）".format(mel.n_bad))
    check(mel.ms == [1000.0, 2000.0, 3000.0],
          "★ 含 NaN 也**真的排好序**（NaN 没有全序 ⇒ 必须先过滤再排序）")
    w = _warns(rep)
    check("同刻合并" in w and ("丢弃" in w or "非数字" in w), "报告里逐项说出来")

    st, rep = SJ.read_stem_json(_fix("frame_mismatch.json"))
    mel = st[0]
    check(mel.n_frame_bad == 6, "6 个点差 > 1 帧（实得 {}）".format(mel.n_frame_bad))
    check(mel.n == 6, "★ 只信 sec：点数照旧（{}）".format(mel.n))
    check("差超过 1 帧" in _warns(rep), "报告里说出来（最大偏差 {:.3f}ms）".format(
        mel.frame_gap_ms))

    st, rep = SJ.read_stem_json(_fix("version_2.json"))
    check(rep["meta"]["version_ok"] is False, "version=2 记成「不认」")
    check("version" in _warns(rep), "★ 警告但继续（点数照旧 {})".format(rep["n_kept"]))


def E_reject():
    print("=" * 78)
    print("E. ★ 结构化 JSON 不许被当时间戳（`docs/56` §3 那条回归）")
    ts, trep = TS.read_ts(_fix("not_stem.json"))
    check(ts == [], "读出来是**空的**，不是垃圾点（实得 {}）".format(ts))
    check("结构化文件" in (trep.get("json_reject") or ""),
          "★ 拒绝原因说清是结构化文件：{}".format(trep.get("json_reject")))

    # 旧行为（bug）：顶层数字全被当时刻 —— 这里必须**不再**发生
    old_garbage = [1.0, 5.805, 202.378, 22050.0]
    check(ts != old_garbage, "★ 不再是 [version, hop_ms, duration, sample_rate]")

    s = Session(_ROOT)
    try:
        s.load(_fix("not_stem.json"))
    except BadRequest as exc:
        check("读不出时间戳" in str(exc), "Session 明确拒绝：{}".format(str(exc)[:70]))
    else:
        check(False, "Session 竟然收下了这份结构化文件")

    # 空 stems 也不行（但理由不同：是这份格式，只是没料）
    p = os.path.join(tempfile.mkdtemp(prefix="adoc_stem_"), "empty.json")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"version": 1, "stems": {}}')
    s = Session(_ROOT)
    try:
        s.load(p)
    except BadRequest as exc:
        check("每一路都是空的" in str(exc), "空 stems 明确拒绝：{}".format(str(exc)[:60]))
    else:
        check(False, "空 stems 竟然收下了")


def F_midi_like():
    print("=" * 78)
    print("F. to_midi_like：一路一轨 / 建议角色 / 默认勾选")
    stems, rep = SJ.read_stem_json(_fix("full_6stems.json"))
    mf = SJ.to_midi_like(stems, meta=rep["meta"],
                         duration_ms=rep["meta"]["duration_ms"])
    check(len(mf.tracks) == 6, "★ 一路一轨（不像纯时间戳塌成一条）")
    check([len(t.notes) for t in mf.tracks] == [32, 8, 16, 12, 9, 6], "每轨点数")
    check(mf.tracks[0].name == "旋律·melody", "轨名带中文路名：{}".format(
        mf.tracks[0].name))
    check(all(not t.is_drum_only() for t in mf.tracks),
          "★ 不用 channel 9 冒充鼓（鼓的身份靠轨名 + method）")
    check(all(abs(n.t_on_ms - n.t_off_ms) < 1e-9
              for t in mf.tracks for n in t.notes), "零长音（不假装有音长）")
    check(abs(mf.bpm0 - 400.0) < 1.0, "★ 网格按 melody 算：bpm {:.3f}".format(mf.bpm0))
    check(abs(mf.length_ms - 202378.0) < 1e-6,
          "★ 尾部长度 = duration_sec（{} > 末点+4 拍）".format(mf.length_ms))
    check(getattr(mf, "is_stem_json", False) and getattr(mf, "is_ts", False),
          "两个来源标记都有（下游沿用时间戳那套默认值）")
    check(mf.stem_meta.get("main_key") == "melody", "报告里说清网格按哪一路算")
    check(mf.stem_main_track == 0, "主路 = 第 0 条轨")

    h = SJ.role_hints(stems)
    check(h == {0: "main", 1: "main", 2: "dp", 3: "sub", 4: "sub"},
          "★ 建议角色表：{}".format(h))
    check(5 not in h, "piano 不表态（赠品通道）")
    mains, subs, dps = SJ.default_checked(stems)
    check(mains == [0] and subs == [] and dps == [],
          "★ 默认只勾 melody 当主轨（保守口径）：{} {} {}".format(mains, subs, dps))
    check(len(SJ.role_notes(stems)) == 6, "每一路都有人话注释")

    # 只有 melody 不表态时才退回第一路
    only = [s for s in stems if s.key == "drums"]
    check(SJ.default_checked(only) == ([0], [], []), "没有 melody ⇒ 退回有料的第一路")

    # 空 ⇒ 明确抛
    try:
        SJ.to_midi_like([s for s in stems if False])
    except ValueError as exc:
        check("空的" in str(exc), "全空 ⇒ ValueError：{}".format(str(exc)[:40]))
    else:
        check(False, "全空竟然没抛")


def G_session():
    print("=" * 78)
    print("G. Session.load()：默认值 / 原曲绑定 / 出谱")
    s = Session(_ROOT)
    info = s.load(_fix("full_6stems.json"))
    check(info.get("is_stem_json") is True, "标明来源是时间戳 JSON")
    check(len(info["tracks"]) == 6, "6 路音轨进列表")
    check(info.get("default_tracks_checked") == [0],
          "★ 默认只勾主旋律：{}".format(info.get("default_tracks_checked")))
    check(info.get("default_sub_checked") == []
          and info.get("default_dp_checked") == [], "次轨/双押轨默认不勾")
    check(info.get("default_merge_ms") == 0.0, "★ merge_ms=0（与纯时间戳同口径）")
    check(info.get("default_fit_mode") == "direct", "★ 默认直拟合")
    check(info.get("default_denoise_on") is True, "★ 默认开去噪")
    check(abs(info.get("length_ms", 0) - 202378.0) < 1e-6, "时长 = duration_sec")
    check((info.get("stem") or {}).get("n_points") == 83, "文件信息里有每一路摘要")
    check((info.get("stem_roles") or {}).get("2") == "dp", "建议角色带进 info")
    check("主旋律" in ((info["tracks"][0].get("note") or "")), "轨道行带人话注释")
    check(info["tracks"][0].get("suggest") == "main", "轨道行带建议角色")
    check("原曲找不到" in "\n".join(s.warnings),
          "★ JSON 里的原曲不在 ⇒ 上屏说明（试过哪些地方）")
    check(info.get("source_audio") == "", "找不到就不绑（不报错）")

    st = dict(SC.defaults())
    st["tracks_checked"] = [0]
    st["sub_checked"] = []
    st["dp_checked"] = []
    st["merge_ms"] = 0.0
    st["fit_mode"] = "direct"
    st["denoise_on"] = True
    r = s.rebuild(st)
    check(r.get("ok"), str(r.get("msg") or r.get("error"))[:100])
    check(r.get("n_onsets") == 32, "melody 32 个点成谱（实得 {}）".format(
        r.get("n_onsets")))
    check((r.get("fit") or {}).get("err_max_ms") == 0.0, "★ 时序误差 = 0")
    g = (r.get("denoise") or {}).get("grid") or {}
    check(abs(g.get("period_ms", 0) - 150.0) < 0.05,
          "砖长精修到 150（实得 {}）".format(g.get("period_ms")))

    # 多勾一路 ⇒ 主轨取并集
    st2 = dict(st)
    st2["tracks_checked"] = [0, 2]
    r2 = s.rebuild(st2)
    check(r2.get("ok") and r2.get("n_onsets") > 32,
          "★ 再勾鼓轨 ⇒ 并集（32 → {}）".format(r2.get("n_onsets")))

    # 双押轨（drums）也能当双押用
    st3 = dict(st)
    st3["dp_checked"] = [2]
    r3 = s.rebuild(st3)
    check(r3.get("ok"), "勾 drums 当双押轨不炸")

    # ★ 原曲在 ⇒ 自动绑预览音源
    d = tempfile.mkdtemp(prefix="adoc_stem_audio_")
    with open(os.path.join(d, "orig.wav"), "wb") as fh:
        fh.write(b"")                       # 只要文件在，绑的是路径（不解析内容）
    obj = json.loads(_read("full_6stems.json"))
    obj["source_audio"] = "orig.wav"
    p = os.path.join(d, "t.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    s2 = Session(_ROOT)
    info2 = s2.load(p)
    check(info2.get("source_audio") == os.path.join(d, "orig.wav"),
          "★ 原曲自动绑成预览音源（不用用户再找一遍）：{}".format(
              os.path.basename(info2.get("source_audio") or "")))
    check(s2.preview_audio_file(dict(SC.defaults())) == os.path.join(d, "orig.wav"),
          "预览音源模式 0（默认）真的把原曲交出去")


def H_sample():
    print("=" * 78)
    print("H. 内置示例（samples/ 那份）")
    check(os.path.exists(SAMPLE), "示例文件在：{}".format(os.path.relpath(SAMPLE, _ROOT)))
    s = Session(_ROOT)
    check(SAMPLE in s.samples(), "★ 进「示例▾」菜单（靠内容嗅探）")
    info = s.load(SAMPLE)
    check(info.get("is_stem_json") and (info.get("stem") or {}).get("n_live") == 6,
          "示例 6 路都能读")
    st = dict(SC.defaults())
    st["tracks_checked"] = list(info["default_tracks_checked"])
    st["merge_ms"] = 0.0
    st["fit_mode"] = "direct"
    r = s.rebuild(st)
    check(r.get("ok") and r.get("n_onsets") == 64,
          "示例出谱 64 点（实得 {}）".format(r.get("n_onsets")))


def main():
    A_looks()
    B_full()
    C_variants()
    D_clean()
    E_reject()
    F_midi_like()
    G_session()
    H_sample()
    print("=" * 78)
    if FAIL:
        print("✗ {} 项失败:".format(len(FAIL)))
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 时间戳 JSON（分轨）全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
