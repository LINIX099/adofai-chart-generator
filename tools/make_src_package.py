# -*- coding: utf-8 -*-
"""把仓库打包成一份可分享的源码 zip。

只挑**源码 + 文档 + 自制素材**；语料、生成产物、历史快照、第三方音乐一律不进包。
清单是显式的（下面几个常量），改一眼就能看懂，不做递归猜。

用法：
    python tools/make_src_package.py
    python tools/make_src_package.py --out dist --name ADOFAI_ChartGenerator_src_v0.1
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 顶层单文件
TOP_FILES = ("main.py", "README.md", "CHANGELOG.md", "VERSION",
             "requirements.txt")

#: 整目录收录（会自动跳过 __pycache__ / *.pyc / 隐藏文件）
DIRS = ("core", "ui", "vendor", "patterns", "tests", "docs")

#: tools 只收有文档、能独立跑的那几个（其余是一次性诊断脚本，
#: 里面还写着私有语料路径，不适合外发）
TOOLS = (
    "make_doublepress.py",          # 生成双押演示音频 + MIDI
    "make_doublepress_adofai.py",   # 生成谱面（空底座 / 中旋双押）
    "doublepress_report.py",        # 素材自检 + 自动写说明文档
    "test_dp_midspin.py",           # 中旋插入五项自检
    "make_pattern_skeletons.py",    # 节奏型骨架
    "make_triplet_demo.py",         # 三连音演示
    "ogg2midi.py",                  # OGG → 伪 MIDI（走 core.audio_onsets）
    "_schema_check.py",             # 事件字段和已知能加载的谱面对照
    "_midspin_analyze.py",          # 按游戏源码完整模拟一张谱
    "_setspeed_convention.py",      # SetSpeed 作用区间的取证脚本
    "_timing_fit.py",               # 时序约定拟合（含反例）
)

#: samples 下**不收**的（第三方音乐 / 编辑器备份 / 中间产物）
SAMPLES_SKIP = (
    "Automaton_Waltz.mid",
    "FallenEra.mid",
    "MemoryLocked.mid",
    "audio/FallenEra_MaySnow.ogg",
    "audio/FallenEra_MaySnow.onset.mid",
    "audio/FallenEra_orig.ogg",
    "audio/_slice20.wav",
    "audio/level.adofai",
    "audio/backup.adofai",
    "doublepress/backup.adofai",
)

#: tests 下**不收**的：这两条是语料harness，没有 272MB 的 corpus 跑不起来
TESTS_SKIP = ("test_corpus.py", "test_offset_calib.py")

#: 输出前把文本里的**私有路径**换成占位符（调研笔记里到处引用了它们）
#: ★ 顺序：先长后短。
#: ★★ 这张表**不写死具体路径** —— 一张「列出所有要抹掉的路径」的表，本身就是
#:    那些路径的副本（原版就是这个问题）。改成「根目录 + 用户目录」算出来，
#:    剩下的一律**按形状**兜底（`X:\…` / `\\服务器\共享\…`）。
PATH_REWRITE = (
    (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "‹仓库根›"),
    (os.path.expanduser("~"), "‹用户目录›"),
    (r"adofaipumian", "‹社区语料›"),
    (r"ADOFAI MARCO", "‹游戏反编译工作区›"),
    (r"[A-Za-z]:[\\/][^\s`\"'\)\]，。；、]*", "‹路径›"),
    (r"\\\\[^\s`\"'\)\]]+", "‹网络路径›"),
)

TEXT_EXT = {".py", ".md", ".txt", ".json", ".adofai", ".cfg", ".toml"}

SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode"}


def _ok(p: str) -> bool:
    base = os.path.basename(p)
    return not (base.startswith(".") or base.endswith(".pyc"))


def collect():
    out: list[str] = []
    for f in TOP_FILES:
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            out.append(f)
    for d in DIRS:
        base = os.path.join(ROOT, d)
        for dp, dns, fns in os.walk(base):
            dns[:] = [x for x in dns if x not in SKIP_DIRS]
            for fn in fns:
                p = os.path.join(dp, fn)
                if not _ok(p):
                    continue
                if d == "tests" and fn in TESTS_SKIP:
                    continue
                out.append(os.path.relpath(p, ROOT))
    for f in TOOLS:
        p = os.path.join(ROOT, "tools", f)
        if os.path.exists(p):
            out.append(os.path.join("tools", f))
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
            out.append(os.path.join("samples", rel))
    return sorted(set(out))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--name", default=None)
    args = ap.parse_args(argv)

    ver = "0.1"
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
            ver = fh.read().strip() or ver
    except OSError:
        pass
    name = args.name or f"ADOFAI_ChartGenerator_src_v{ver}"

    files = collect()
    os.makedirs(args.out, exist_ok=True)
    stage = os.path.join(args.out, name)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    total = 0
    n_scrub = 0
    for rel in files:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(stage, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        ext = os.path.splitext(rel)[1].lower()
        if ext in TEXT_EXT:
            with open(src, encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
            new = txt
            for a, b in PATH_REWRITE:
                if a in new:
                    new = new.replace(a, b)
            if new != txt:
                n_scrub += 1
            # 文本一律按 UTF-8 落盘，顺手统一换行
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
        else:
            shutil.copy2(src, dst)
        total += os.path.getsize(src)

    zpath = os.path.join(args.out, name + ".zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            z.write(os.path.join(stage, rel), arcname=os.path.join(name, rel))

    zs = os.path.getsize(zpath)
    print(f"[源码包] {zpath}")
    print(f"         文件 {len(files)} 个   原始 {total/1024/1024:.2f} MB   "
          f"压缩后 {zs/1024/1024:.2f} MB")
    print(f"         已抹掉私有路径的文件 {n_scrub} 个"
          f"（→ ‹社区语料目录› / ‹游戏反编译源码目录› / ‹仓库根› …）")
    print(f"         未收录：corpus_tuf / out / out_prev_backup / _versions / "
          f"第三方音乐 / {', '.join(TESTS_SKIP)}")
    print(f"         解包目录 {stage}（可直接删，zip 里已经有一份）")
    by_dir: dict[str, int] = {}
    for rel in files:
        k = rel.split(os.sep)[0] if os.sep in rel else "(顶层)"
        by_dir[k] = by_dir.get(k, 0) + 1
    for k in sorted(by_dir):
        print(f"           {k:<16s} {by_dir[k]:4d} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
