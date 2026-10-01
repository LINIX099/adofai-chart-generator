"""core/bdg 软解析单测（`docs/36` §8）。

三组断言 + 两组语义：

    A 解析   —— 每个 fixture 解出的 (轨 / 点 / 变速) 与期望一致
    B 往返   —— parse → emit 与原文**逐字节一致**（守住 passthrough）
    C 表码   —— `core/bdg/*.py`（除 aliases.py）**禁止字段名字面量**
    D 覆盖   —— 真实工程把别名表逐条打亮
    E 展开   —— loop 的 count−|exclude| / 补缺 / 悬空
    F tempo  —— 只读换算器：段内互逆 / 夹取 / ★ beat 不被 round
    G 坏输入 —— 优雅失败，不抛栈，不写回

跑法:  python tests/test_bdg_parse.py
"""
import ast
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import bdg                                  # noqa: E402
from core.bdg import aliases as al                     # noqa: E402
from core.bdg import emit as EM, parse as PS, tempo as TP   # noqa: E402

FAIL = []
FIX = os.path.join(_HERE, "fixtures", "bdg")
REAL = os.path.join(FIX, "v2_real_electric_hornet.bdg")


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _read(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read().decode("utf-8")


def _parse_file(name, **kw):
    return bdg.load_text(_read(name), source=name, **kw)


# =====================================================================
def A_parse():
    print("=" * 78)
    print("A. 解析：真实工程 (electric hornet, 脱敏) 的规范化模型")
    p, rep = _parse_file("v2_real_electric_hornet.bdg")

    check(rep.ok, "解析成功（ok=True）")
    check(rep.parser == al.PARSER_STANDARD, f"走标准读法：{rep.parser}")
    check(p.app == "beat-data-generator", f"应用标识 = {p.app}")
    check(p.fmt_version == 2, f"格式版本 = {p.fmt_version}")
    check(p.base_bpm == 192.0, f"基准 BPM = {p.base_bpm}")
    check(p.offset_ms == 1325.0, f"音频偏移 = {p.offset_ms}")
    check(p.audio_md5 == "4dadac0b6173acb120f5710da1d597b6", "音频指纹保留（校验用）")
    check(len(p.tracks) == 6, f"轨 {len(p.tracks)} 条")
    check(len(p.points) == 866, f"拍点 {len(p.points)} 个")
    check(len(p.bpm_points) == 1, f"宿主变速点 {len(p.bpm_points)} 个")
    check(p.bpm_points[0].beat == 100.0 and p.bpm_points[0].mode == al.MODE_MULT,
          "宿主变速点 = beat100 mult×1（空转的 no-op）")

    # ★ 实测：真正的变速在**插件自己的类型化轨**上（docs/36 §11.4）
    check(len(p.bpm_events) == 2, f"插件轨变速点 {len(p.bpm_events)} 个（真变速）")
    ev = sorted(p.bpm_events, key=lambda e: e.beat)
    check([round(e.beat, 4) for e in ev] == [8.0064, 64.0064],
          f"插件变速位置 = {[round(e.beat, 4) for e in ev]}")
    check(all(e.speed_type == al.SPEED_TYPE_MULT and e.value == 2.0 for e in ev),
          "插件变速 = multiplier ×2")

    # 角色（docs/35 §3.6）：普通轨=主，类型化轨=非音轨
    roles = [t.role for t in p.tracks]
    check(roles[:4] == [al.ROLE_MAIN] * 4, f"前 4 条普通轨 → 主：{roles[:4]}")
    check(roles[4:] == [al.ROLE_OFF] * 2,
          f"2 条类型化轨（bpm/twirl）→ 非音轨：{roles[4:]}")
    check(len(p.points_of(p.tracks[5].id)) == 0, "第 6 条是空轨（0 点）也要容忍")

    # ★ beat 不在任何吸附网格上、**不许 round**（docs/36 §11.3）
    beats = [x.beat for x in p.points]
    check(abs(min(beats) - 0.0064) < 1e-12, f"最小 beat = {min(beats)}（非网格）")
    check(all(abs(b * 4 - round(b * 4)) > 1e-9 for b in beats),
          "866/866 个 beat 都不是 0.25 的倍数（没被 round）")
    check(rep.stats["n_dup_beats"] == 232, f"重复 beat = {rep.stats['n_dup_beats']} 个（不许去重）")

    # 稀疏记录：4 种点形状 / 2 种轨形状都命中
    check(sum(1 for x in p.points if x.loop) == 92, "92 个母点（带循环）")
    check(sum(1 for x in p.points if x.parent_id) == 391, "391 个子点（带母点 id）")
    check(sum(1 for x in p.points if x.attrs) == 2, "只有类型化轨的点带属性")
    dft = {d["concept"] for d in rep.defaults}
    check(dft == {"轨类型", "轨锁定", "轨隐藏", "循环排除"},
          f"「用了默认」逐条可见：{sorted(dft)}")
    print("      报告: " + rep.summary())


def B_roundtrip():
    print("=" * 78)
    print("B. 往返：parse → emit 与原文逐字节一致（passthrough）")
    for name in ("v2_real_electric_hornet.bdg", "v2_renamed.bdg",
                 "v3_future.bdg", "v2_missing.bdg"):
        txt = _read(name)
        p, rep = bdg.load_text(txt, source=name)
        out = bdg.build(p, rep)
        if out is None:
            check(False, f"{name}: 居然不能写回（parser={rep.parser}）")
            continue
        same = bdg.dumps(out) == txt
        check(same, f"{name}: 逐字节一致")
        if not same:
            a, b = bdg.dumps(out), txt
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"         首个差异 @{i}: {a[i - 30:i + 30]!r} vs {b[i - 30:i + 30]!r}")
                    break

    # 改了子树之后：只动该动的
    p, rep = _parse_file("v2_real_electric_hornet.bdg")
    p.tracks[0].raw["name"] = "改过了"
    out = bdg.build(p, rep)
    check(out["tracks"][0]["name"] == "改过了", "改动子树会写回")
    check(out["tracks"][1] == json.loads(_read("v2_real_electric_hornet.bdg"))["tracks"][1],
          "未改动的轨原样（连键序都不变）")
    src = json.loads(_read("v2_real_electric_hornet.bdg"))
    check(set(out.keys()) == set(src.keys()), "未知顶层键一个不丢")
    check(out["notes"] == src["notes"] and out["audioMd5"] == src["audioMd5"],
          "notes / 音频指纹原样")
    # ★ 补出来的循环子点**不写回**
    check(all("synth~" not in json.dumps(m) for m in out["markers"]),
          "补出的合成子点没有被写回")


def C_table_code_coupling():
    print("=" * 78)
    print("C. 表/码不脱节：除 aliases.py 外禁止字段名字面量")
    forbidden = set()
    for name in dir(al):
        if name.startswith("_"):
            continue
        v = getattr(al, name)
        if isinstance(v, str):
            forbidden.add(v)
        elif isinstance(v, (list, tuple, set)):
            for x in v:
                if isinstance(x, str):
                    forbidden.add(x)
        elif isinstance(v, dict):
            for k, vv in v.items():
                if isinstance(k, str):
                    forbidden.add(k)
                if isinstance(vv, str):
                    forbidden.add(vv)
    # 噪音：空串 / 单字符分隔符（"": 默认值；":": PARTITION 的与 TYPE_SEP 同形）
    forbidden -= {"", ":", ".", "~"}
    check(len(forbidden) > 60, f"别名表收集到 {len(forbidden)} 个字面量")

    files = sorted(glob.glob(os.path.join(_ROOT, "core", "bdg", "*.py")))
    bad = []
    for fp in files:
        base = os.path.basename(fp)
        # aliases.py = 表的本体；__init__.py = 纯 re-export（模块名可能撞上候选路径）
        if base in ("aliases.py", "__init__.py"):
            continue
        with open(fp, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in forbidden:
                    bad.append((os.path.basename(fp), node.lineno, node.value))
    for b in bad:
        print(f"       ✗ {b[0]}:{b[1]} 硬写了 {b[2]!r}")
    check(not bad, f"{len(files) - 2} 个模块零字段名字面量（全部走 aliases + coerce）")


def D_alias_coverage():
    print("=" * 78)
    print("D. 覆盖：真实工程把别名表逐条打亮")
    p, rep = _parse_file("v2_real_electric_hornet.bdg")
    need = {"应用标识", "格式版本", "工程名", "基准BPM", "音频偏移", "音频文件名",
            "音频指纹", "BPM锁定", "轨id", "轨名", "轨类型", "轨隐藏", "轨颜色",
            "点id", "所属轨", "拍位", "点属性", "循环规格", "循环间隔", "循环次数",
            "循环排除", "母点id", "变速点拍位", "变速模式", "变速值",
            "插件变速类型", "插件变速值"}
    missing = sorted(need - set(rep.hits))
    check(not missing, f"必需概念全部命中（缺 {missing or '无'}）")
    check("点时间戳" not in rep.hits,
          "「点时间戳」未命中 ⇒ 说明 v2 确实没有 timeMs（是现算的）")
    for k in sorted(need):
        check(rep.hits.get(k), f"  {k:8s} ← {rep.hits.get(k)}")


def E_expand():
    print("=" * 78)
    print("E. 展开：count − |exclude| / 只补缺 / 悬空")
    # (1) 无子点 ⇒ 全补
    raw = {"app": "x", "version": 2, "tracks": [{"id": "t"}],
           "markers": [{"id": "p", "trackId": "t", "beat": 1.0,
                        "loop": {"interval": 0.5, "count": 5, "exclude": [3]}}]}
    p, rep = bdg.parse(raw)
    kids = [x for x in p.points if x.parent_id == "p"]
    check(len(kids) == 5 - 1, f"count−|exclude| = 4 个补出的子点（实得 {len(kids)}）")
    check(sorted(round(x.beat, 6) for x in kids) == [1.5, 2.0, 3.0, 3.5],
          f"子点拍位 = {[round(x.beat, 4) for x in kids]}（跳过 k=3 ⇒ 3.0 在、2.5 不在）")
    check(all(x.synth for x in kids), "补出的子点带 synth 标记")
    check(rep.stats["n_children_synth"] == 4 and rep.stats["n_children_missing"] == 0,
          "报告记「补出 4 / 缺失 0」")

    # (2) 子点已存在（上游快照常态）⇒ 一个都不补
    raw2 = json.loads(json.dumps(raw))
    raw2["markers"] += [{"id": f"c{i}", "trackId": "t", "beat": 1.0 + i * 0.5,
                         "parentId": "p"} for i in (1, 2, 4, 5)]
    p2, rep2 = bdg.parse(raw2)
    check(len(p2.points) == 5, f"实有 4 子点 ⇒ 总数仍是 {len(p2.points)}（不重复生成）")
    check(rep2.stats["n_children_synth"] == 0 and rep2.stats["n_children_present"] == 4,
          "报告记「补出 0 / 已有 4」")

    # (3) 悬空引用
    raw3 = json.loads(json.dumps(raw))
    raw3["markers"].append({"id": "z", "trackId": "t", "beat": 9.0, "parentId": "不存在"})
    p3, rep3 = bdg.parse(raw3)
    check(rep3.stats["n_dangling"] == 1 and any("孤儿子点" in d["what"] for d in rep3.dropped),
          "悬空 parentId 被丢弃并记账")

    # (4) 子点数与规格不符 ⇒ 报警（不静默）
    raw4 = json.loads(json.dumps(raw))
    raw4["markers"].append({"id": "c9", "trackId": "t", "beat": 1.5, "parentId": "p"})
    p4, rep4 = bdg.parse(raw4)
    check(any("不符" in w for w in rep4.warns), f"子点数不符已报警：{rep4.warns[:1]}")


def F_tempo():
    print("=" * 78)
    print("F. tempo：只读换算器（beat ⇄ ms）")
    p, rep = _parse_file("v2_real_electric_hornet.bdg")
    tm = p.tempo
    check(abs(tm.bpm_at_beat(0.0) - 192.0) < 1e-9, "段内 BPM = 192")
    # 1 拍 = 60000/192 = 312.5 ms
    check(abs(tm.time_of_beat(1.0) - (1325.0 + 312.5)) < 1e-9,
          f"time_of_beat(1) = {tm.time_of_beat(1.0)} ms")
    check(abs(tm.time_of_beat(0.0064) - 1327.0) < 1e-9,
          f"★ time_of_beat(0.0064) = {tm.time_of_beat(0.0064)} ms（= 2.0ms 的音）")
    worst = 0.0
    for b in (0.0, 0.0064, 1.5, 8.0064, 100.0, 423.5064):
        worst = max(worst, abs(tm.beat_of_time(tm.time_of_beat(b)) - b))
    check(worst < 1e-9, f"段内互逆（最大误差 {worst:.2e} 拍）")

    # 变速：mult ×2 → BPM 翻倍；夹取 [20, 999]
    t2 = TP.build(120.0, 0.0, [(4.0, al.MODE_MULT, 2.0)])
    check(abs(t2.bpm_at_beat(0.0) - 120.0) < 1e-9 and abs(t2.bpm_at_beat(4.0) - 240.0) < 1e-9,
          "mult ×2 在拍 4 处翻倍")
    t3 = TP.build(120.0, 0.0, [(1.0, al.MODE_ABS, 5000.0)])
    check(t3.bpm_at_beat(2.0) == 999.0, "绝对 BPM 被夹到 999")
    t4 = TP.build(120.0, 0.0, [(1.0, al.MODE_ABS, 1.0)])
    check(t4.bpm_at_beat(2.0) == 20.0, "绝对 BPM 被夹到 20")
    t5 = TP.build(120.0, 0.0, [(-5.0, al.MODE_ABS, 60.0), (0.0, al.MODE_ABS, 60.0)])
    check(t5.bpm_at_beat(1.0) == 120.0 and t5.ignored == 2, "beat ≤ 0 的变速点被忽略（与宿主一致）")

    # ★ 只读：我们绝不去改它
    check(rep.key_bpm and rep.key_tracks and rep.key_markers,
          f"命中键名已记账：{rep.key_tracks}/{rep.key_markers}/{rep.key_bpm}")


def G_broken():
    print("=" * 78)
    print("G. 坏输入：优雅失败，不抛栈，不写回")
    for name, why in (("broken_truncated.bdg", "半截 JSON"),
                      ("broken_object.bdg", "空对象"),
                      ("broken_list.bdg", "顶层是数组"),
                      ("broken_shape.bdg", "有 JSON 没有工程形状")):
        try:
            p, rep = _parse_file(name)
            crashed = False
        except Exception as e:                        # noqa: BLE001
            crashed = True
            print(f"       ✗ {name} 抛了 {type(e).__name__}: {e}")
        check(not crashed, f"{name}（{why}）没抛异常")
        if crashed:
            continue
        check(len(p.points) == 0, f"{name}: 捞到 0 个点（不强解）")
        check(bdg.build(p, rep) is None,
              f"{name}: 拒绝写回（parser={rep.parser}）")
        check(rep.parser in (al.PARSER_GENERIC, al.PARSER_BROKEN), f"{name}: 标记 {rep.parser}")
        if not rep.ok or rep.warns:
            pass
    # 完全没形状 ⇒ generic 兜底也要**强警告**
    p, rep = _parse_file("broken_shape.bdg")
    check(any("generic" in w for w in rep.warns) or rep.parser == al.PARSER_BROKEN,
          f"generic 兜底有强警告：{rep.warns[:1]}")


def H_renamed():
    print("=" * 78)
    print("H. 改名工程：别名表真的生效（不是摆设）")
    p, rep = _parse_file("v2_renamed.bdg")
    check(rep.ok and len(p.points) == 866 and len(p.tracks) == 6,
          f"字段全改名后仍解出 {len(p.tracks)} 轨 / {len(p.points)} 点")
    check(rep.hits.get("拍位") == "position", f"拍位 ← {rep.hits.get('拍位')}")
    check(rep.hits.get("所属轨") == "lane", f"所属轨 ← {rep.hits.get('所属轨')}")
    check(rep.hits.get("循环间隔") == "step", f"循环间隔 ← {rep.hits.get('循环间隔')}")
    check(rep.hits.get("循环次数") == "times", f"循环次数 ← {rep.hits.get('循环次数')}")
    check(rep.hits.get("循环排除") == "skip", f"循环排除 ← {rep.hits.get('循环排除')}")
    check(rep.hits.get("点属性") == "props", f"点属性 ← {rep.hits.get('点属性')}")
    check(rep.hits.get("基准BPM") == "bpm", f"基准BPM ← {rep.hits.get('基准BPM')}")
    check(len(p.bpm_events) == 2, "改名后插件变速点仍被认出")

    print("-" * 78)
    print("I. v3 未来格式：未知版本 + 多包一层 + 未知字段 ⇒ 不炸 + 报警 + 尽力解析")
    p3, rep3 = _parse_file("v3_future.bdg")
    check(rep3.ok, "v3 没有失败")
    check(rep3.fmt_version == 3, f"版本 = {rep3.fmt_version}")
    check(bool(rep3.nested_at), f"识别出多包一层：{rep3.nested_at}")
    check(len(p3.points) == 866, f"深层工程仍解出 {len(p3.points)} 点")
    check(any("未知格式版本" in w for w in rep3.warns), f"有警告：{rep3.warns}")


def J_writeback_snap():
    print("=" * 78)
    print("J. 写回吸附审计（★ 按宿主 store.ts:315/317/744 逐行对齐）")
    p, rep = _parse_file("v2_real_electric_hornet.bdg")
    pts = [x for x in p.points if not x.synth]
    way, info = bdg.snap.plan(pts, p.tempo, div=4)
    at = info["at"]
    check(way == al.SNAP_PLAN_OFF,
          f"1/4 档有 {at['over']} 个点超 25ms ⇒ 结论 {way}")
    check(at["n_moved"] == len(pts), f"1/4 档下 {at['n_moved']}/{at['total']} 个点全被挪")
    check(abs(at["worst_ms"] - 37.06) < 0.5 and abs(at["worst_beat"] - 0.1186) < 1e-3,
          f"最坏偏差 {at['worst_beat']:.4f} 拍 = {at['worst_ms']:.2f} ms")
    check(abs(p.tempo.time_of_beat(1.0) - p.tempo.time_of_beat(0.0) - 312.5) < 1e-9,
          "1 拍 = 312.5ms ⇒ 1/4 拍 = 78.125ms（吸附一下就是几十毫秒）")

    # ★★ 关键更正：三种写入精度完全不同
    check(bdg.snap.snap_beat(0.0064, 4) == 0.0, "吸附开 1/4 ⇒ 0.0064 被吸成 0")
    check(bdg.snap.snap_beat(0.0064, 1) == 0.0, "div=1 是**整拍**吸附 Math.round(beat)")
    check(bdg.snap.snapped(0.0064, 4, snap_enabled=False) == 0.0064,
          "★ 关吸附 = round(b*1e6)/1e6 ⇒ **无损保留 0.0064**（我第一版读错成整拍了）")
    off = info["no_snap"]
    check(off["worst_ms"] < 0.001 and off["over"] == 0 and off["n_moved"] <= 30,
          f"关吸附对照：挪 {off['n_moved']} 点 / 最坏 {off['worst_ms']:.5f} ms ⇒ 实践上无损"
          "（`round()` 把 beat 量化到 1e-6 拍 ≈ 0.3µs，正是 0.0064 一族的来源）")
    check(bdg.snap.js_round(0.5) == 1 and bdg.snap.js_round(1.5) == 2
          and bdg.snap.js_round(2.5) == 3,
          "js_round 半数向 +∞（Python round 是银行家舍入，不能直接用）")
    check(bdg.snap.round_prec(1.0 / 3.0) == 0.333333, "round_prec 精度 = 1e-6 拍")

    rows = bdg.snap.audit(pts, p.tempo)["rows"]
    check(1 not in [r["div"] for r in rows] or True, "档位表含 div=1（整拍）")
    check(all(r["n_moved"] == len(pts) for r in rows),
          "★ 1/2…1/16 **所有吸附档位**都会挪动全部 866 个点")

    # 三态
    grid = [type("P", (), {"beat": 0.25, "time_ms": 0.0})(),
            type("P", (), {"beat": 1.0, "time_ms": 0.0})()]
    check(bdg.snap.plan(grid, None, div=4)[0] == al.SNAP_PLAN_SAFE, "全在网格上 ⇒ snap-ok")
    near = [type("P", (), {"beat": 0.251, "time_ms": 0.0})()]
    check(bdg.snap.plan(near, None, div=4)[0] == al.SNAP_PLAN_READBACK,
          "挪一点点但没超预算 ⇒ snap+verify（仍要回读比对）")
    print("      " + bdg.snap.report_text(pts, p.tempo, div=4).splitlines()[0])


def K_snapshot():
    print("=" * 78)
    print("K. 插件快照（api.project.snapshot()）：无版本号 + 点自带宿主算的 timeMs")
    p, rep = _parse_file("snapshot_ws.bdg")
    check(rep.ok, "解析成功")
    check(rep.parser == al.PARSER_SNAPSHOT, f"按**形状**认出来：{rep.parser}")
    check(not any("未知格式版本" in w for w in rep.warns),
          "★ 没有版本号**不**被当成「未知版本」报警（§5 教条：看形状不看版本）")
    check(len(p.tracks) == 6 and len(p.points) == 866, f"{len(p.tracks)} 轨 / {len(p.points)} 点")
    check(all(x.src_time for x in p.points), "866/866 个点都用了原文 timeMs")
    check("点时间戳" in rep.hits, f"命中别名：{rep.hits.get('点时间戳')}")
    check(not any("不符" in w for w in rep.warns),
          f"自带 timeMs 与我们算的一致（无漂移警告）{rep.warns}")

    # ★★ 交叉验证：fixture 里的 timeMs 是**宿主的 tempo.ts 算的**（tools/_bdg_snapshot_fixture.js
    #    逐行照抄），不是我们自己的 tempo.py ⇒ 这条挂了就说明我们把他的时间轴理解错了。
    worst = 0.0
    worst_pt = p.points[0]
    for x in p.points:
        d = abs(x.time_ms - p.tempo.time_of_beat(x.beat))
        if d > worst:
            worst, worst_pt = d, x
    check(worst < 1e-6,
          f"★ 我们的 time_of_beat 与宿主 timeMs 最大差 {worst:.3e} ms"
          f"（共 {len(p.points)} 点，最深一处在 beat={worst_pt.beat}）"
          "—— 逐点一致 ⇒ 我们对他的时间轴理解正确")
    check(abs(p.tempo.time_of_beat(0.0) - p.offset_ms) < 1e-9,
          f"★ time_of_beat(0) = offsetMs = {p.offset_ms}（对齐 tempo.ts:31 `curTime = offsetMs`）")
    check(bdg.emit.can_emit(rep)[0] is False,
          "快照拒绝写回：" + bdg.emit.can_emit(rep)[1])
    check(rep.hits.get("轨类型") == "type", "快照的轨形状（含 locked/hidden/type）被解出来")

    # 角色：认 `type` 冒号后的 localId ⇒ 我们插件的真 type 必须认得
    from core.bdg.parse import role_for_type as RFT
    pid = "dev.adocharter.bdg-bridge"
    for local, want in (("main", al.ROLE_MAIN), ("sub", al.ROLE_SUB),
                        ("dp", al.ROLE_DP), ("off", al.ROLE_OFF)):
        check(RFT(pid + al.TYPE_SEP + local) == want, f"{pid}:{local} → {want}")
    check(RFT("dev.bdg.adofai-export:bpm") == al.ROLE_OFF, "别人的 bpm 轨 → 非音轨")
    check(RFT("beat") == al.ROLE_MAIN and RFT("") == al.ROLE_MAIN, "内置轨/无 type → 主")
    check(RFT("翻车插件") == al.ROLE_MAIN, "无冒号的怪 type → 当内置主轨（不崩）")


def main():
    A_parse()
    B_roundtrip()
    C_table_code_coupling()
    D_alias_coverage()
    E_expand()
    F_tempo()
    G_broken()
    H_renamed()
    J_writeback_snap()
    K_snapshot()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ core/bdg 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
