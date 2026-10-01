# -*- coding: utf-8 -*-
"""把**算法本体**单独打一个 zip（供学习 / 交流 / 传播）。

与 `make_src_package.py` 的区别：

| | `make_src_package.py` | 本脚本 |
| --- | --- | --- |
| 范围 | 整仓源码（core+ui+vendor+tests+docs+tools+samples） | **只要算法层** |
| 包里 | 含 Electron 前端与内嵌渲染引擎 | 不含界面/服务/宿主 |
| 入口文档 | `README.md`（工程 README） | `README.md` = `docs/51-算法源码外发版说明.md` |

**收录白名单**（显式写死，不做递归猜）：

    core/**            算法本体（必须）
    docs/              **算法相关**的设计笔记（下面 DOCS 清单）
    tests/**           单测（**只收只依赖 core 的**，见 TESTS）
    tests/fixtures/**  参考谱 fixture（自带）
    tests/golden/**    冻结哈希（`test_ladder` 用）
    samples/**         自制素材（`--with-songs` 才带第三方曲目 MIDI）
    tools/             少数能独立跑的工具 + 重冻脚本

用法：

    python tools/make_algo_package.py                  # 干净版（不含第三方曲目）
    python tools/make_algo_package.py --with-songs     # 连三首示例曲 MIDI 一起（版权自负）
    python tools/make_algo_package.py --selfcheck      # 打完包**解包跑一遍单测**
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 打包时必须写进去的顶层文件（没有 `main.py`/`requirements.txt` —— 算法层不需要界面壳）
TOP_FILES = ("VERSION",)

#: 算法相关的设计笔记（**显式清单**：不按目录一把抓，免得把 UI/BDG/交接单也发出去）
DOCS = (
    "02-角度限制澄清.md",
    "03-MIDI转谱的技术难点.md",
    "04-首版交付.md",
    "05-修鬼畜与标定.md",
    "06-时序定稿.md",
    "07-按音值写谱.md",
    "08-直线优先.md",
    "09-规则落地.md",
    "10-节奏型库.md",
    "11-节奏型需求清单.md",
    "12-模板接入.md",
    "13-TUF语料与真EX标尺.md",
    "16-双押偏移回正公式.md",
    "17-靠后位置随机偏移-根因.md",
    "24-等待拍-偏移修正-雪花-最小角度.md",
    "25-对音阶梯（待实现）.md",
    "26-轨道位置偏移开关.md",
    "27-v0.4-xk-base采音（待开工）.md",
    "28-主次级-绕圈偏好-等待拍默认.md",
    "29-闭合图形-回正体检-布局待办.md",
    "30-连续双押（待人类写法）.md",
    "31-双押写法总纲（压缩后接续）.md",
    "32-闭合图形-位置偏移-双押偏移（三处体检）.md",
    "33-角度双押偏移计算.md",
    "34-区间采音可选方案.md",
    "39-分段采音.md",
    "43-友项目时间戳拟合.md",
    "44-去噪评估.md",
    "46-直拟合选档与奇怪轨道.md",
    "47-xk-base定稿.md",
    "48-三押设计.md",
    "双押逻辑.md",
    "51-算法源码外发版说明.md",          # ← 会同时被当成包内 README.md
)

#: `docs/51…` 在包里的落点（包根 README）
README_SRC = "51-算法源码外发版说明.md"

#: tests 只收**只依赖 core** 的那些（`test_sidecar` / `ui` / `bridge` / `hostctl` /
#: `corpus` 要界面、服务、宿主或 272MB 语料，**不进包**）
TESTS = (
    "test_path.py",
    "test_dp_offset.py",
    "test_dp_angle.py",
    "test_dp_angle_twirl.py",
    "test_gridfit.py",
    "test_denoise.py",
    "test_fitdirect.py",
    "test_snowflake.py",
    "test_straighten.py",
    "test_bigline.py",
    "test_xkbase.py",
    "test_segments.py",
    "test_templates_dp.py",
    "test_ts_source.py",
    "test_v3_rules.py",
    "test_ladder.py",                  # 需要 tools/_ladder_freeze.py + golden
    "test_inplace.py",                 # ★ 原地惩罚
    "test_midi.py",
    "test_ogg_offset.py",
    "test_wait_angle_snow.py",
    "test_pipeline.py",
    "test_bdg_parse.py",
    "test_bdg_roundtrip.py",
    "test_bdg_source.py",
)

#: tools 只收这些（一次性诊断脚本里写着私有路径与语料，不打包）
TOOLS = (
    "_ladder_freeze.py",       # 重冻 golden（test_ladder 依赖它）
    "make_doublepress.py",     # 生成双押演示音频 + MIDI（包里那份素材就是它产的）
    "ogg2midi.py",             # OGG → 伪 MIDI（走 core.audio_onsets）
    "ex_benchmark.py",         # 真 EX 标尺对照
    "_verify_rules.py",        # 规则体检
)

#: 第三方曲目（默认**不进包**；`--with-songs` 才带）
SONGS = ("FallenEra.mid", "Automaton_Waltz.mid", "MemoryLocked.mid")

#: samples 下**永远不收**的（第三方音频/中间产物/体积）
SAMPLES_SKIP = (
    "audio/FallenEra_MaySnow.ogg",
    "audio/FallenEra_MaySnow.onset.mid",
    "audio/FallenEra_orig.ogg",
    "audio/_slice20.wav",
    "audio/level.adofai",
    "doublepress/doublepress_demo_120.ogg",
    "doublepress_base/doublepress_demo_120.ogg",
    "doublepress_variants/doublepress_demo_120.ogg",
)

#: 额外整目录：算法的**数据依赖**
#:   `patterns/` —— `core/templates.load()` 要 `patterns/templates.json`，
#:   同目录那些 `.adofai` 就是模板的**来源谱**（学习价值很高，一起给）
EXTRA_DIRS = ("patterns",)

#: 第三方依赖（**MIT，保留 LICENSE**）：`core/verify.py` 用它的独立时间模型做反解校验，
#: 是我们「导出的谱真的能被第三方读对」这条验收的依据。原包就在 `vendor/` 下。
VENDOR_DIRS = (os.path.join("vendor", "adofai_timemodel"),)

#: 编排层 + 参数表：
#:   `session.py` —— **端到端编排**（采音 → 求解 → 双押 → offset → 导出 + 报告），
#:                  界面只是它的壳；只依赖 `core.*`，可以独立读/跑
#:   `schema.py`  —— 参数手册（算法默认值与「为什么是这个值」都在这里）
EXTRA_FILES = (os.path.join("sidecar", "__init__.py"),
               os.path.join("sidecar", "schema.py"),
               os.path.join("sidecar", "session.py"))

PATH_REWRITE = (
    # ★ 不写死具体路径（原版那张表本身就是被抹掉的那些路径的副本）。
    #   根目录 / 用户目录算出来，其余按**形状**兜底。
    (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "‹仓库根›"),
    (os.path.expanduser("~"), "‹用户目录›"),
    (r"adofaipumian", "‹社区语料›"),
    (r"ADOFAI MARCO", "‹游戏反编译工作区›"),
    (r"[A-Za-z]:[\\/][^\s`\"'\)\]，。；、]*", "‹路径›"),
    (r"\\\\[^\s`\"'\)\]]+", "‹网络路径›"),
)
TEXT_EXT = {".py", ".md", ".txt", ".json", ".adofai"}
SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode"}

#: 包内自检要跑的（都**不需要**第三方曲目）
SELFCHECK = ("test_path.py", "test_dp_offset.py", "test_denoise.py",
             "test_gridfit.py", "test_snowflake.py", "test_straighten.py",
             "test_bigline.py", "test_ts_source.py", "test_segments.py",
             "test_templates_dp.py", "test_dp_angle_twirl.py", "test_xkbase.py",
             "test_bdg_parse.py")


def _ok(p: str) -> bool:
    b = os.path.basename(p)
    return not (b.startswith(".") or b.endswith(".pyc"))


def collect(with_songs: bool) -> list[str]:
    out: list[str] = []
    for f in TOP_FILES:
        if os.path.exists(os.path.join(ROOT, f)):
            out.append(f)
    # core：全收
    for dp, dns, fns in os.walk(os.path.join(ROOT, "core")):
        dns[:] = [x for x in dns if x not in SKIP_DIRS]
        for fn in fns:
            if _ok(fn) and fn != "make_bdg_fixtures.py":
                out.append(os.path.relpath(os.path.join(dp, fn), ROOT))
    # docs：白名单
    for f in DOCS:
        p = os.path.join(ROOT, "docs", f)
        if os.path.exists(p):
            out.append(os.path.join("docs", f))
        else:
            print(f"  ! docs 缺 {f}（跳过）")
    # tests：白名单 + fixtures/golden 整收
    for f in TESTS:
        p = os.path.join(ROOT, "tests", f)
        if os.path.exists(p):
            out.append(os.path.join("tests", f))
        else:
            print(f"  ! tests 缺 {f}（跳过）")
    for sub in ("fixtures", "golden"):
        for dp, dns, fns in os.walk(os.path.join(ROOT, "tests", sub)):
            dns[:] = [x for x in dns if x not in SKIP_DIRS]
            for fn in fns:
                if _ok(fn):
                    out.append(os.path.relpath(os.path.join(dp, fn), ROOT))
    # tools：白名单
    for f in TOOLS:
        p = os.path.join(ROOT, "tools", f)
        if os.path.exists(p):
            out.append(os.path.join("tools", f))
        else:
            print(f"  ! tools 缺 {f}（跳过）")
    # 额外目录（patterns）+ 第三方时间模型 + 参数表
    for d in EXTRA_DIRS + VENDOR_DIRS:
        for dp, dns, fns in os.walk(os.path.join(ROOT, d)):
            dns[:] = [x for x in dns if x not in SKIP_DIRS]
            for fn in fns:
                if _ok(fn):
                    out.append(os.path.relpath(os.path.join(dp, fn), ROOT))
    for f in EXTRA_FILES:
        if os.path.exists(os.path.join(ROOT, f)):
            out.append(f)
        else:
            print(f"  ! 缺 {f}（跳过）")
    # samples：自制素材；曲目 MIDI 看开关
    smp = os.path.join(ROOT, "samples")
    for dp, dns, fns in os.walk(smp):
        dns[:] = [x for x in dns if x not in SKIP_DIRS]
        for fn in fns:
            p = os.path.join(dp, fn)
            if not _ok(p):
                continue
            rel = os.path.relpath(p, smp).replace("\\", "/")
            if rel in SAMPLES_SKIP:
                continue
            if rel in SONGS and not with_songs:
                continue
            out.append(os.path.join("samples", rel))
    return sorted(set(out))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--name", default=None)
    ap.add_argument("--with-songs", action="store_true",
                    help="连三首第三方示例曲 MIDI 一起打包（默认不带）")
    ap.add_argument("--selfcheck", action="store_true",
                    help="打完包**解包**跑一遍不依赖外部素材的单测")
    args = ap.parse_args(argv)

    ver = "0.4"
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
            ver = fh.read().strip() or ver
    except OSError:
        pass
    name = args.name or f"ADOFAI_ChartGenerator_algo_src_v{ver}"

    files = collect(args.with_songs)
    os.makedirs(args.out, exist_ok=True)
    stage = os.path.join(args.out, name)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    total, n_scrub = 0, 0
    for rel in files:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(stage, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.splitext(rel)[1].lower() in TEXT_EXT:
            with open(src, encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
            new = txt
            for a, b in PATH_REWRITE:
                if a in new:
                    new = new.replace(a, b)
            if new != txt:
                n_scrub += 1
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
        else:
            shutil.copy2(src, dst)
        total += os.path.getsize(src)
    # 包内 README = 那篇说明
    if os.path.exists(os.path.join(stage, "docs", README_SRC)):
        shutil.copy2(os.path.join(stage, "docs", README_SRC),
                     os.path.join(stage, "README.md"))
        files = sorted(set(files + ["README.md"]))

    zpath = os.path.join(args.out, name + ".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            z.write(os.path.join(stage, rel), arcname=os.path.join(name, rel))
    zs = os.path.getsize(zpath)

    print(f"[算法源码包] {zpath}")
    print(f"  文件 {len(files)} 个   原始 {total/1024:.0f} KB   压缩后 {zs/1024:.0f} KB")
    print(f"  已抹私有路径 {n_scrub} 个文件")
    print(f"  第三方曲目 MIDI：{'**已包含**（--with-songs）' if args.with_songs else '未包含（默认）'}")
    print(f"  解包目录 {stage}")
    by: dict[str, int] = {}
    for rel in files:
        k = rel.split(os.sep)[0] if os.sep in rel else "(顶层)"
        by[k] = by.get(k, 0) + 1
    for k in sorted(by):
        print(f"    {k:<10s} {by[k]:4d} 个")

    if args.selfcheck:
        print("\n[自检] 解包到临时目录跑单测…")
        tmp = tempfile.mkdtemp(prefix="algo_pkg_")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        root = os.path.join(tmp, name)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        bad = []
        for t in SELFCHECK:
            p = os.path.join(root, "tests", t)
            if not os.path.exists(p):
                print(f"  - {t} 不在包里，跳过")
                continue
            r = subprocess.run([sys.executable, p], cwd=root, env=env,
                               capture_output=True, text=True, errors="replace")
            tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
            flag = "ok  " if r.returncode == 0 else "FAIL"
            print(f"  {flag} {t:<26} {tail[0][:80]}")
            if r.returncode != 0:
                bad.append(t)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"  自检：{len(SELFCHECK) - len(bad)} 通过 / {len(bad)} 失败"
              + (f"  {bad}" if bad else "  ✔ 包是自洽的"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
