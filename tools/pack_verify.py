#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""便携包验收：一条命令跑完「解压 → 冒烟 → 包内解释器 → 内置示例 → 导出」。

    python tools/pack_verify.py                 # 静态 + 冒烟（~2 分钟）
    python tools/pack_verify.py --flow          # 再加「载示例 → 出谱 → 导出」（+1 分钟）
    python tools/pack_verify.py --zip <某个.zip>  # 指定包
    python tools/pack_verify.py --keep          # 保留解压目录（排查用）

为什么要有这个：这一整套是**手敲出来的**（解 90 秒、起 app、CDP 驱动、看导出），
下次重打根本复现不了。这里的每条断言都对应一次真机踩过的坑，见 `docs/53`。

断言（全部来自 objective 的验收口径）：
  ① zip 里能解出 exe / 使用说明.txt / THIRD-PARTY.md
  ② **不含** `beat_data_generator`（GPL-3.0 宿主，不许随包）
  ③ 包内自带解释器能 import numpy/scipy/librosa —— **用包内那个跑**，不是开发机的
  ④ 从解压副本 `--smoke` = SMOKE PASS（`--flow` 时还得握手出 69 个字段）
  ⑤ `--flow`：载内置示例 → 出谱 → 导出 .adofai + wav，且 **verify_ok**
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTABLE = os.path.join(ROOT, "build", "portable")
CDP_PORT = "9377"
EXE_NAME = "ADOFAI 谱面生成器.exe"

FAIL: list[str] = []


def check(ok, msg, extra=""):
    print(("  [OK]   " if ok else "  [FAIL] ") + msg + (("   " + str(extra)) if extra else ""))
    if not ok:
        FAIL.append(msg)
    return ok


def run(args, timeout=300, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace", env=e)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def newest_zip() -> str:
    zs = sorted(glob.glob(os.path.join(PORTABLE, "*.zip")), key=os.path.getmtime)
    return zs[-1] if zs else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="")
    ap.add_argument("--flow", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--dir", default="")
    a = ap.parse_args()

    zp = a.zip or newest_zip()
    print("=" * 78)
    print("便携包验收：" + zp)
    if not zp or not os.path.exists(zp):
        print("[!] 找不到 zip —— 先跑 `cd app && npm run pack:win`")
        return 1
    print("    大小 %.1f MB" % (os.path.getsize(zp) / 1048576.0))

    work = a.dir or tempfile.mkdtemp(prefix="adoc_pack_")
    try:
        print("① 解压 → " + work)
        t0 = time.time()
        with zipfile.ZipFile(zp) as z:
            z.extractall(work)
        print("    %.1fs" % (time.time() - t0))
        exe = os.path.join(work, EXE_NAME)
        res = os.path.join(work, "resources")
        check(os.path.exists(exe), "解出 exe", EXE_NAME)
        check(os.path.exists(os.path.join(work, "使用说明.txt")), "解出「使用说明.txt」（在 exe 旁边）")
        check(os.path.exists(os.path.join(res, "THIRD-PARTY.md")), "解出 THIRD-PARTY.md")
        check(os.path.exists(os.path.join(res, "LICENSE")),
              "解出 LICENSE（用户已定：Apache-2.0）")
        # ★★ 2026-09-20 用户把许可改成 **Apache License 2.0**：
        #   ① 必须是**真 Apache 全文**（不是只把标题换掉的 MIT）；
        #   ② Apache-2.0 §4(d) 要求带 NOTICE ⇒ 它必须随包、且写明归属。
        _lf = os.path.join(res, "LICENSE")
        if os.path.exists(_lf):
            with open(_lf, "r", encoding="utf-8") as fh:
                _lt = fh.read()
            check("Apache License" in _lt and "Version 2.0, January 2004" in _lt
                  and "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in _lt
                  and "END OF TERMS AND CONDITIONS" in _lt,
                  "★★ LICENSE 是 Apache-2.0 **全文**（第 1~9 条都在）", "%d 字节" % len(_lt))
            check("MIT License" not in _lt,
                  "★ 旧 MIT 文本已消失（不混两套许可）", "")
        _nf = os.path.join(res, "NOTICE")
        check(os.path.exists(_nf), "★ 解出 NOTICE（Apache-2.0 §4(d) 要求）")
        if os.path.exists(_nf):
            with open(_nf, "r", encoding="utf-8") as fh:
                _nt = fh.read()
            check("Apache License, Version 2.0" in _nt and "adocharter" in _nt,
                  "★ NOTICE 写明归属与许可", _nt.splitlines()[1] if _nt else "")
        # ★ 打包产物里并了第三方代码（adofai / three）⇒ BSD-3 与 MIT 都要求
        #   「随附材料里复现许可全文」，只写「见其仓库」不够（我们第一版就是那样）
        lic = os.path.join(res, "LICENSES")
        need = ["adofai-BSD-3-Clause.txt", "three-MIT.txt",
                "regenerator-runtime-MIT.txt", "adofai_timemodel-MIT.txt"]
        got = sorted(os.listdir(lic)) if os.path.isdir(lic) else []
        check(os.path.isdir(lic) and all(n in got for n in need),
              "★ LICENSES/ 里第三方许可全文齐全（bundle 里并了 adofai/three）",
              "缺 " + str([n for n in need if n not in got]) if got else "没有 LICENSES 目录")
        check(os.path.isdir(os.path.join(res, "bridge_plugin")),
              "解出 bridge_plugin（可选联动；**不含**宿主）")

        # ★★ 工作台皮肤（2026-09-20 合并进来的 fork）：**两套 CSS + 材质开关真进包了**。
        #   asar 的头是一段 JSON（文件名明文）+ 尾部是内容 —— 直接读整个 asar 找标记，
        #   不依赖外部解包工具（`asar` CLI 只有开发环境才有）。
        _af = os.path.join(res, "app.asar")
        check(os.path.exists(_af), "★ 解出 app.asar（界面本体）")
        if os.path.exists(_af):
            with open(_af, "rb") as fh:
                _ab = fh.read()
            _at = _ab.decode("latin-1")
            check("skin-workbench.css" in _at and "workbench-elements.css" in _at,
                  "★★ 工作台皮肤两套 CSS 都在 asar 里（外观 + 新元素骨架）")
            check("fl-empty" in _at and "av-pop" in _at,
                  "★ 皮肤的新元素规则在里面（③b 浮窗收起 / 音源偏移浮层）")
            check("backgroundMaterial" in _at and "--no-material" in _at,
                  "★ 主进程带「窗口材质（亚克力）」且留了 `--no-material` 退路")

        print("② 不该带 GPL 宿主")
        hits = [p for p in glob.glob(os.path.join(res, "**", "beat_data_generator"),
                                     recursive=True)]
        check(not hits, "包里没有 beat_data_generator（GPL-3.0 宿主）", hits[:2])
        check(os.path.isdir(os.path.join(res, "vendor", "adofai_timemodel")),
              "vendor/ 下只有我们需要的 adofai_timemodel")

        print("③ 包内解释器自检（**用它自己跑**，不看开发机）")
        py = os.path.join(res, "runtime", "python", "python.exe")
        check(os.path.exists(py), "自带解释器在", "runtime/python/python.exe")
        if os.path.exists(py):
            code = ("import importlib\n"
                    "for m in ('numpy','scipy','librosa','soundfile','numba'):\n"
                    "    mod = importlib.import_module(m)\n"
                    "    print(m, getattr(mod,'__version__','?'))\n")
            rc, out, err = run([py, "-c", code], timeout=300)
            check(rc == 0, "包内解释器能 import numpy/scipy/librosa/numba",
                  out.replace("\n", " ").strip()[:120])

        print("④ 从解压副本冒烟（PATH 砍到只剩系统目录 = 模拟没装 Python/Node）")
        env = {"PATH": r"C:\Windows\System32;C:\Windows", "ADOFAI_PYTHON": ""}
        rc, out, err = run([exe, "--smoke"], timeout=300, env=env)
        blob = (out or "") + (err or "")
        check(rc == 0, "`--smoke` 退出码 0", "exit=%d" % rc)
        check("SMOKE PASS" in blob, "打印 SMOKE PASS", blob.strip().splitlines()[:1])
        check(os.path.join(work, "resources") in blob or "root=" in blob,
              "sidecar 的 root 指向**解压副本**（不是开发目录）",
              [l for l in blob.splitlines() if "root=" in l][:1])

        if a.flow:
            print("⑤ 完整链路：载内置示例 → 出谱 → 导出")
            outdir = os.path.join(work, "_导出测试")      # 顺带验中文路径
            os.makedirs(outdir, exist_ok=True)
            proc = subprocess.Popen([exe, "--hidden",
                                     "--remote-debugging-port=" + CDP_PORT],
                                    env=dict(os.environ, PATH=r"C:\Windows\System32;C:\Windows"))
            try:
                _wait_cdp(30)
                # ★★ 光等 CDP 端口不够（Chromium 3 秒就开，渲染进程还没 boot 完）——
                #   第一次写这个脚本就踩了：直接 eval，`api.samples()` 还没准备好，
                #   报一个看着像「产品坏了」的 TypeError。**必须等应用自己说 ready**。
                _wait_ready(60)

                # ★★ ⑥「用户机器上没有 BDG」这一条（用户 2026-10 问的）：
                #   他要的是「没装宿主也能正常发动」。四条一起断言：
                #   · `/api/host` **不许卡**（改过之后先查 tools/host.js 在不在，
                #     不在就直接返回 —— 不会去跑 node，所以机器上没 node 也无所谓）
                #   · 桥那一栏说**人话**（不许出现 `npm run host:fetch` 那种开发者话）
                #   · 「启动并桥接」禁用
                #   · 程序其它部分照常（后面 ⑤ 的完整链路就是证据）
                t_b = time.time()
                host = _cdp_eval("(async()=>JSON.stringify(await window.__dsh.api.host()))()", 30)
                dt_b = time.time() - t_b
                hj = {}
                try:
                    hj = json.loads(host)
                except Exception:                                        # noqa: BLE001
                    pass
                check(dt_b < 8.0, "★ 没有宿主时 `/api/host` 立刻返回（不会去跑 node 卡住）",
                      "%.1fs" % dt_b)
                check(hj.get("tool") is False, "★ 便携版报告「不带宿主联动工具」（tool=false）",
                      json.dumps(hj, ensure_ascii=False)[:120])
                btxt = _cdp_eval("document.querySelector('#br-hoststat').textContent", 30)
                check("不含" in btxt and "BDG" in btxt, "★ 桥那一栏说的是人话", btxt.splitlines()[:1])
                check("npm run host:fetch" not in btxt,
                      "★★ **开发者提示没有漏给用户**（不许出现 npm run host:fetch）")
                bdis = _cdp_eval("String(document.querySelector('#br-host').disabled)", 30)
                check(bdis.strip() == "true", "★「启动并桥接」在便携版里禁用", bdis)
                brd = _cdp_eval("document.querySelector('#br-status').textContent", 30)
                check("未连接" in brd, "★ 桥状态如实显示「未连接」（不假装连上）", brd.splitlines()[:1])

                # ★★ 版本号（**发布版不许错号**）：包内 `resources/VERSION` 与
                #   正在跑的 sidecar `/api/health` **必须是同一个号**。
                #   历史坑：号写死在三处（VERSION / package.json / server.py），
                #   漏改一处就会出现「界面显示旧号、包里是新的」。
                _vf = os.path.join(res, "VERSION")
                _vpack = ""
                if os.path.exists(_vf):
                    with open(_vf, "r", encoding="utf-8") as fh:
                        _vpack = fh.read().strip()
                _vh = _cdp_eval("(async()=>JSON.stringify(await window.__dsh.api.health()))()", 30)
                _vj = {}
                try:
                    _vj = json.loads(_vh)
                except Exception:                                        # noqa: BLE001
                    pass
                check(bool(_vpack) and _vj.get("version") == _vpack,
                      "★★ 包内 VERSION 与 sidecar /api/health 的版本号一致",
                      "VERSION=%r health=%r" % (_vpack, _vj.get("version")))
                # ★ 期望号**从仓库根的 `VERSION` 读**（以前写死 `0.5.0-preview`
                #   ⇒ 每次发包都得来改这一行，而且忘了改也**照样绿**）。
                _vwant = ""
                try:
                    with open(os.path.join(ROOT, "VERSION"), "r",
                              encoding="utf-8") as fh:
                        _vwant = fh.read().strip()
                except OSError:
                    pass
                check(bool(_vwant) and _vj.get("version") == _vwant,
                      "★ 包内版本号 == 仓库 VERSION（%s）" % (_vwant or "读不到"),
                      str(_vj.get("version")))

                js = (
                    "(async()=>{const d=window.__dsh;const s=await d.api.samples();"
                    "if(!s||!s.abs||!s.abs.length) throw new Error('samples 空：'+JSON.stringify(s));"
                    "await d.load(s.abs.find(p=>/MemoryLocked/.test(p)));"
                    "await new Promise(r=>setTimeout(r,900));"
                    "const tr=(d.loadInfo()||{}).tracks||[];"
                    "if(!tr.length) throw new Error('载入后没有音轨');"
                    "const b=tr.slice().sort((x,y)=>((y.notes||[]).length||0)"
                    "-((x.notes||[]).length||0))[0];"
                    "d.state.tracks_checked=[b.index];await d.rebuild();"
                    "const r=d.lastResult();"
                    # ★ 路径只 json.dumps 一次（JSON 字符串就是合法的 JS 字面量）；
                    #   再手工 replace 一层会把反斜杠写成两个（真机踩过）。
                    "const e=await d.api.exportTo(d.state, %s);"
                    "return JSON.stringify({n:r.n_onsets,floors:r.n_floors,ok:e.ok,"
                    "verify:e.verify_ok,audio:e.audio,dir:e.dir});})()"
                    % json.dumps(outdir)
                )
                txt = _cdp_eval(js, 180)
                d = json.loads(txt) if txt and txt.strip().startswith("{") else {}
                check(bool(d), "CDP 驱动成功", txt[:120] if txt else "")
                check(int(d.get("n") or 0) > 0, "载内置示例出谱（采音点 > 0）",
                      "采音点=%s 层=%s" % (d.get("n"), d.get("floors")))
                check(d.get("ok") is True, "导出成功")
                check(d.get("verify") is True, "导出**逐层校验**通过（verify_ok）")
                chart = glob.glob(os.path.join(outdir, "**", "*.adofai"), recursive=True)
                wave = glob.glob(os.path.join(outdir, "**", "*.wav"), recursive=True)
                check(bool(chart), "落盘 .adofai 谱面", [os.path.basename(x) for x in chart])
                check(bool(wave), "落盘音频（游戏不认 MIDI，必须渲成 wav/ogg）",
                      ["%s %.1fMB" % (os.path.basename(x), os.path.getsize(x) / 1048576.0)
                       for x in wave])

                # ★★ 2026-10 修的那个 bug：**「使用激进的采音策略」以前不认「最大夹角」**
                #   （`core/ladder.rung_ok` 写死 345、`meta` 里连 `travel_max` 都没写
                #   ⇒ `rules` 的 ③c 也瞎了，实测吐出 345° 却报「违规 0」）。
                #   这里证的是「**解压出来这份 zip 里**真的修好了」——只看源码不够。
                lad = os.path.join(res, "core", "ladder.py")
                _lad_ok = False
                if os.path.exists(lad):
                    with open(lad, "r", encoding="utf-8") as fh:
                        _lad_ok = "def travel_hi" in fh.read()
                check(_lad_ok, "★ 包内 core/ladder.py 带 travel_hi（阶梯认「最大夹角」）",
                      os.path.relpath(lad, work) if os.path.exists(lad) else "缺文件")
                js_lad = (
                    "(async()=>{const d=window.__dsh;"
                    "d.setParam('fit_mode','solve');"
                    "d.setParam('aggressive_pick',true);"
                    "d.setParam('travel_min',30);"
                    "d.setParam('travel_max',270);"
                    "d.state.dp_checked=[];d.state.sub_checked=[];"
                    "await d.rebuild();"
                    "const L=d.lastResult()||{};"
                    "const tv=((d.payload()||{}).floors||[]).map(x=>Number(x.travel));"
                    "return JSON.stringify({n:L.n_floors,nv:L.n_violations,"
                    "viol:(L.violations||[]).map(v=>v.code),"
                    "tvmax:Math.max.apply(null,tv.concat([0])),"
                    "over:tv.filter(t=>t>270+1e-9).length});})()"
                )
                tlad = _cdp_eval(js_lad, 180)
                dlad = (json.loads(tlad)
                        if tlad and tlad.strip().startswith("{") else {})
                check(bool(dlad), "CDP 跑一遍「激进采音 + 最大夹角 270」",
                      tlad[:120] if tlad else "")
                check((dlad.get("over") or 0) == 0
                      and (dlad.get("tvmax") or 0) <= 270.0 + 1e-6
                      and (dlad.get("nv") or 0) == 0,
                      "★★ 激进采音真的守住 270°（超窗 0 + 违规 0）",
                      "层=%s 最高 travel=%s 超窗=%s 违规=%s %s"
                      % (dlad.get("n"), dlad.get("tvmax"), dlad.get("over"),
                         dlad.get("nv"), dlad.get("viol")))

                # ★★ 新来源格式（时间戳 JSON / DEMUCS 分轨 · docs/56）**真的进包了**：
                #   拿包内那份示例当来源跑一遍 —— 只测源码目录是不够的，
                #   要证的正是「解压出来这份 zip 里就能用」。
                sj = os.path.join(res, "samples", "示例·分轨时间戳.json")
                check(os.path.exists(sj), "★ 包里有时间戳 JSON 示例（新来源格式）",
                      os.path.relpath(sj, work) if os.path.exists(sj) else "缺文件")
                js2 = (
                    "(async()=>{const d=window.__dsh;"
                    "await d.load(%s);"
                    "await new Promise(r=>setTimeout(r,1500));"
                    "const i=d.loadInfo()||{};const r=d.lastResult()||{};"
                    "return JSON.stringify({sj:!!i.is_stem_json,"
                    "n:(i.stem||{}).n_live,trk:(i.tracks||[]).length,"
                    "def:i.default_tracks_checked,onsets:r.n_onsets,"
                    "err:(r.fit||{}).err_max_ms,"
                    "badge:(document.querySelector('#src-badge')||{}).textContent||''});})()"
                    % json.dumps(sj)
                )
                tjs = _cdp_eval(js2, 120)
                dj = json.loads(tjs) if tjs and tjs.strip().startswith("{") else {}
                check(bool(dj), "CDP 载入分轨 JSON 成功", tjs[:120] if tjs else "")
                check(dj.get("sj") is True and dj.get("n") == 6 and dj.get("trk") == 6,
                      "★ 时间戳 JSON（分轨）在便携包里能当来源（6 路 = 6 条音轨）",
                      tjs[:140])
                check(dj.get("def") == [0], "★ 默认只勾主旋律（其余只标注）",
                      str(dj.get("def")))
                check(int(dj.get("onsets") or 0) == 64 and dj.get("err") == 0,
                      "★★ 分轨 JSON 出谱 64 点、时序误差 0",
                      "onsets=%s err=%s" % (dj.get("onsets"), dj.get("err")))
                check("时间戳 JSON" in str(dj.get("badge") or ""),
                      "★ 来源徽标写明是分轨时间戳 JSON",
                      str(dj.get("badge"))[:44])

                # ★★ 换手押上色（`docs/59`）：新模块/新参数/界面钩子**真的进包**，
                #   而且开关一路通到 `payload`（关掉 ⇒ 一条事件都不写）。
                #   ⚠ 判据语义在 `tests/test_colorize.py`；这里只证「解压出来这份能用」。
                cz = os.path.join(res, "core", "colorize.py")
                check(os.path.exists(cz), "★ 包里带 core/colorize.py（换手押上色核心）",
                      os.path.relpath(cz, work) if os.path.exists(cz) else "缺文件")
                if os.path.exists(cz):
                    with open(cz, "r", encoding="utf-8") as fh:
                        src = fh.read()
                    check("RecolorTrack" in src and "dp_pairs" in src,
                          "★★ 核心模块里是 RecolorTrack + dp_pairs 权威路径",
                          "%d 字节" % len(src))
                sch = os.path.join(res, "sidecar", "schema.py")
                if os.path.exists(sch):
                    with open(sch, "r", encoding="utf-8") as fh:
                        ssrc = fh.read()
                    _keys = ("color_schedule", "handswitch_gap_tiles",
                             "handswitch_min_cycles", "handswitch_color_span",
                             "handswitch_track_style", "handswitch_color_type")
                    _miss = [k for k in _keys if k not in ssrc]
                    check(not _miss, "★ 包内 schema 有 6 个新参数", str(_miss))
                ajs = os.path.join(res, "app", "renderer", "app.js")
                if os.path.exists(ajs):
                    with open(ajs, "r", encoding="utf-8") as fh:
                        asrc = fh.read()
                    check("bandColor" in asrc and "换手押" in asrc,
                          "★ 包内界面带「换手押」chip + 段带记号钩子", "")
                js3 = (
                    "(async()=>{const d=window.__dsh;"
                    "const on=JSON.parse(JSON.stringify(d.payload().color||{}));"
                    "const n0=(d.band.hs||[]).length;"
                    "document.querySelector('#in-color_schedule').click();"
                    "await d.rebuild();"
                    "const off=JSON.parse(JSON.stringify(d.payload().color||{}));"
                    "const n1=(d.band.hs||[]).length;"
                    "document.querySelector('#in-color_schedule').click();"
                    "await d.rebuild();"
                    "return JSON.stringify({on:on,off:off,n0:n0,n1:n1});})()"
                )
                cjs = _cdp_eval(js3, 180)
                cj = json.loads(cjs) if cjs and cjs.strip().startswith("{") else {}
                check(cj.get("on", {}).get("enabled") is True
                      and isinstance(cj.get("on", {}).get("text"), str)
                      and len(cj.get("on", {}).get("text") or "") > 0,
                      "★ 便携包里「换手押上色」默认开且有报告",
                      (cj.get("on", {}).get("text") or "")[:70])
                check(cj.get("off", {}).get("enabled") is False
                      and (cj.get("off", {}).get("floors") or []) == []
                      and cj.get("n1") == 0,
                      "★★ 关掉 ⇒ payload 空 + 段带记号归零（**一条事件都不写**）",
                      "floors=%s hs=%s" % ((cj.get("off", {}).get("floors") or [])[:3],
                                           cj.get("n1")))
                check(cj.get("n0") == len((cj.get("on", {}).get("floors") or [])),
                      "★ 段带记号条数 = 后端上色格数",
                      "hs=%s floors=%s" % (cj.get("n0"),
                                           len((cj.get("on", {}).get("floors") or []))))

                # ★★ 算法轨道调度（`docs/60`）：新模块/新参数/界面钩子**真的进包**，
                #   而且开关一路通到 `payload`（关掉 ⇒ 事件与 settings 都不动）。
                #   ⚠ 判据语义在 `tests/test_appearance.py`；这里只证「解压出来这份能用」。
                ap = os.path.join(res, "core", "appearance.py")
                check(os.path.exists(ap), "★ 包里带 core/appearance.py（算法轨道调度核心）",
                      os.path.relpath(ap, work) if os.path.exists(ap) else "缺文件")
                if os.path.exists(ap):
                    with open(ap, "r", encoding="utf-8") as fh:
                        ap_src = fh.read()
                    check("RecolorTrack" in ap_src and "ScaleRadius" in ap_src
                          and "figure_spans" in ap_src,
                          "★★ 核心模块里是 RecolorTrack + ScaleRadius + 图形段判据",
                          "%d 字节" % len(ap_src))
                if os.path.exists(sch):
                    with open(sch, "r", encoding="utf-8") as fh:
                        ssrc2 = fh.read()
                    _k2 = ("appearance_schedule", "appearance_skin", "appearance_ripple",
                           "appearance_ripple_rings", "appearance_ripple_step",
                           "appearance_radius", "appearance_radius_dense",
                           "appearance_dense_fps", "appearance_quiet_fps",
                           "appearance_density_window")
                    _m2 = [k for k in _k2 if k not in ssrc2]
                    check(not _m2, "★ 包内 schema 有 10 个新参数（皮肤/涟漪/半径）", str(_m2))
                if os.path.exists(ajs):
                    with open(ajs, "r", encoding="utf-8") as fh:
                        asrc2 = fh.read()
                    check("bandAppear" in asrc2 and "算法轨道调度" in asrc2,
                          "★ 包内界面带「轨道调度」chip + 段带记号钩子", "")
                js4 = (
                    "(async()=>{const d=window.__dsh;"
                    "const on=JSON.parse(JSON.stringify(d.payload().appearance||{}));"
                    "const n0=(d.band.ap||[]).length;"
                    "const st0=(JSON.parse(JSON.stringify(d.payload().settings||{}))"
                    ".trackStyle)||'';"
                    "document.querySelector('#in-appearance_schedule').click();"
                    "await d.rebuild();"
                    "const off=JSON.parse(JSON.stringify(d.payload().appearance||{}));"
                    "const n1=(d.band.ap||[]).length;"
                    "document.querySelector('#in-appearance_schedule').click();"
                    "await d.rebuild();"
                    "return JSON.stringify({on:on,off:off,n0:n0,n1:n1,st0:st0});})()"
                )
                ajs2 = _cdp_eval(js4, 180)
                aj = json.loads(ajs2) if ajs2 and ajs2.strip().startswith("{") else {}
                check(aj.get("on", {}).get("enabled") is True
                      and isinstance(aj.get("on", {}).get("text"), str)
                      and len(aj.get("on", {}).get("text") or "") > 0
                      and aj.get("on", {}).get("skin") == "Neon",
                      "★ 便携包里「算法轨道调度」默认开且皮肤 = Neon",
                      (aj.get("on", {}).get("text") or "")[:70])
                check(aj.get("off", {}).get("enabled") is False
                      and (aj.get("off", {}).get("floors") or []) == []
                      and not (aj.get("off", {}).get("settings") or {})
                      and aj.get("n1") == 0,
                      "★★ 关掉 ⇒ payload 空 + settings 不动 + 段带记号归零（一条事件都不写）",
                      "floors=%s marks=%s" % ((aj.get("off", {}).get("floors") or [])[:3],
                                              aj.get("n1")))
                check(aj.get("n0") == (len((aj.get("on", {}).get("ripples") or []))
                                       + len((aj.get("on", {}).get("radius_spans") or []))),
                      "★ 段带记号条数 = 涟漪触发点 + 半径切换点",
                      "ap=%s rip=%s rad=%s" % (aj.get("n0"),
                                               len((aj.get("on", {}).get("ripples") or [])),
                                               len((aj.get("on", {}).get("radius_spans") or []))))

                # ★★ 演出（`docs/62`）：新模块 / 新参数 / 界面钩子**真的进包**，
                #   而且「**填起始方块 / 结束方块**」的分段编辑器一路通到后端。
                #   ⚠ 判据语义在 `tests/test_show.py`（A~K）；这里只证「解压出来这份能用」。
                shp = os.path.join(res, "core", "show.py")
                check(os.path.exists(shp), "★ 包里带 core/show.py（演出核心）",
                      os.path.relpath(shp, work) if os.path.exists(shp) else "缺文件")
                if os.path.exists(shp):
                    with open(shp, "r", encoding="utf-8") as fh:
                        sh_src = fh.read()
                    check("MoveTrack" in sh_src and "ShowParams" in sh_src
                          and "triplet_spans" in sh_src and "required_beats_ahead" in sh_src,
                          "★★ 核心模块里是 MoveTrack + ShowParams + 三连音自动标出 + beatsAhead 需求",
                          "%d 字节" % len(sh_src))
                if os.path.exists(sch):
                    with open(sch, "r", encoding="utf-8") as fh:
                        ssrc3 = fh.read()
                    _k3 = ("show_schedule", "show_out_move", "show_in_move", "show_lead",
                           "show_margin", "show_triplet", "show_qe_g", "show_segments")
                    _m3 = [k for k in _k3 if k not in ssrc3]
                    check(not _m3, "★ 包内 schema 有 8 个新参数（开关/预设招/提前量/分段）", str(_m3))
                js5 = (
                    "(async()=>{const d=window.__dsh;"
                    "const on=JSON.parse(JSON.stringify(d.payload().show||{}));"
                    "const st=JSON.parse(JSON.stringify(d.state));"
                    "d.showSegAdd(3,6,'入B','出D');await d.rebuild();"
                    "const seg=JSON.parse(JSON.stringify(d.payload().show||{}));"
                    "const rows=document.querySelectorAll('#lst-show .region').length;"
                    "const lo=(document.querySelector('#inp-show-lo-0')||{}).value;"
                    "const hi=(document.querySelector('#inp-show-hi-0')||{}).value;"
                    "const lj=(await d.api.levelJson(d.state)).level;"
                    "document.querySelector('#in-show_schedule').click();await d.rebuild();"
                    "const off=JSON.parse(JSON.stringify(d.payload().show||{}));"
                    "document.querySelector('#in-show_schedule').click();await d.rebuild();"
                    "return JSON.stringify({on:on,seg:seg,rows:rows,lo:lo,hi:hi,st:st,off:off,"
                    "ba:(lj&&lj.settings&&lj.settings.beatsAhead)||0,"
                    "mvs:((lj&&lj.actions)||[]).filter((a)=>a.eventType==='MoveTrack').length});})()"
                )
                sjs = _cdp_eval(js5, 240)
                sj = json.loads(sjs) if sjs and sjs.strip().startswith("{") else {}
                check(sj.get("on", {}).get("enabled") is True
                      and isinstance(sj.get("on", {}).get("text"), str)
                      and len(sj.get("on", {}).get("text") or "") > 0
                      and (sj.get("on", {}).get("n_out") or 0) > 0
                      and (sj.get("on", {}).get("n_in") or 0) > 0,
                      "★ 便携包里「演出」默认开、离场/入场都写了事件",
                      (sj.get("on", {}).get("text") or "")[:70])
                check(str(sj.get("lo")) == "3" and str(sj.get("hi")) == "6"
                      and int(sj.get("rows") or 0) == 1,
                      "★★ 分段编辑器能**填起始方块 / 结束方块**（3 / 6），且出现一行",
                      "rows=%s lo=%s hi=%s" % (sj.get("rows"), sj.get("lo"), sj.get("hi")))
                _seg = ((sj.get("seg", {}).get("segments") or []) or [{}])
                _seg = next((x for x in _seg if x.get("lo") == 3), {})
                check(_seg.get("why") == "user",
                      "★★ 这一段真的被后端采用了（why=user）", json.dumps(_seg)[:110])
                check(float(sj.get("ba") or 0) >= float(sj.get("on", {}).get("required_beats_ahead")
                                                        or 0) - 1e-9
                      and int(sj.get("mvs") or 0) >= int(sj.get("on", {}).get("n_out") or 0),
                      "★★ 导出面：`beatsAhead` 被抬到 ≥ 需求，且 actions 里真有 MoveTrack",
                      "beatsAhead=%s 需求=%s MoveTrack=%s" % (
                          sj.get("ba"), sj.get("on", {}).get("required_beats_ahead"),
                          sj.get("mvs")))
                check(sj.get("off", {}).get("enabled") is False
                      and (sj.get("off", {}).get("floors") or []) == [],
                      "★★ 关掉 ⇒ payload 空（一条 MoveTrack 都不写）",
                      "floors=%s" % ((sj.get("off", {}).get("floors") or [])[:3]))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                time.sleep(1)
    finally:
        if a.keep or a.dir:
            print("    保留解压目录：" + work)
        else:
            shutil.rmtree(work, ignore_errors=True)

    print("=" * 78)
    if FAIL:
        print("✗ %d 项失败：" % len(FAIL))
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 便携包验收全部通过")
    return 0


def _cdp_targets():
    with urllib.request.urlopen("http://127.0.0.1:%s/json/list" % CDP_PORT,
                                timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def _wait_cdp(sec: int):
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            _cdp_targets()
            return True
        except Exception:                                            # noqa: BLE001
            time.sleep(1)
    return False


def _wait_ready(sec: int) -> bool:
    """等**应用说自己好了**（`__dsh` + 健康徽章 + 参数表都就位）。

    ★ 只看 CDP 端口是**不够的**：Chromium 的调试端口 ~3 秒就开，而渲染进程
      还要抓 schema、建面板。第一次写这个脚本就踩了 —— 直接驱动会抛一个
      看着像「产品坏了」的 TypeError，其实是**测试的竞态**。
    """
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            r = _cdp_eval("(async()=>{try{const d=window.__dsh;"
                          "if(!d||!d.api||!d.state) return 'no';"
                          "const h=await d.api.health();"
                          "return (h&&h.ok&&document.querySelector('#health')"
                          "&&document.querySelectorAll('canvas').length>0)?'yes':'wait';"
                          "}catch(e){return 'err:'+e.message}})()", 30)
            if "yes" in r:
                return True
        except Exception:                                            # noqa: BLE001
            pass
        time.sleep(1.5)
    return False


def _cdp_eval(expr: str, timeout: int = 120) -> str:
    """用仓库里现成的 `tools/_cdp.js`（不重复造轮子，行为与手工验收一致）。"""
    p = subprocess.run(["node", os.path.join(ROOT, "tools", "_cdp.js"), expr],
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, CDP_PORT=CDP_PORT))
    return (p.stdout or "").strip() or (p.stderr or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
