# -*- coding: utf-8 -*-
"""扫描社区真实 .adofai 谱面，提取各 eventType 的**字段真值集**。

    python tools/scan_adofai_events.py

用途：写 `RecolorTrack` / `MoveCamera` 这类渲染事件前，先确认字段名和取值范围，
避免重演 `PositionTrack` 那次 `LevelEvent.Decode` 取 null ⇒ `NullReferenceException`。
（`docs/59` 那一轮就是靠它发现「**v19 没有 `SetTrackColors`，真名是 `RecolorTrack`**」。）
也给 `docs/58` 的 fixture（`tests/fixtures/stemjson/octave_trap.json`）找过候选。

★ 两个坑（2026-10 首扫踩过）：
  1) 游戏自己写出来的 .adofai 是 **UTF-8 with BOM** ⇒ 必须 utf-8-sig，
     否则 json.load 抛 Unexpected UTF-8 BOM，整个文件被跳过。
  2) Documents\\...\\Worlds 里只有极少数谱面；真正的语料在
     Steam 工坊 `steamapps\\workshop\\content\\977950\\`（ADOFAI 的 appid = 977950）。

只读，不写任何东西（除 stdout）。**留下的理由**：下一轮做镜头那半还要用它抄
`MoveCamera` 的真值（现在语料里已知 15 种字段组合）。
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

_HOME = os.path.expanduser("~")                                #: 用户目录

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  #: 仓库根（不写死盘符）

sys.stdout.reconfigure(encoding="utf-8")

STEAM_APPID = "977950"          # A Dance of Fire and Ice
STEAM_COMMON_GUESS = ["C:\\Program Files (x86)\\Steam", "C:\\Program Files\\Steam",
                      "D:\\Steam", "D:\\SteamLibrary", "E:\\Steam", "E:\\SteamLibrary",
                      "F:\\Steam", "F:\\SteamLibrary", "G:\\SteamLibrary"]

CANDIDATE_ROOTS = [
    _HOME + r"\Documents",
    _HOME + r"\OneDrive\Documents",
    _HOME + r"\OneDrive\文档",
    _HOME + r"\Desktop",
    r"D:\Users\Windows\Desktop",
    r"D:\Users\Windows\Documents",
    _HOME + r"\AppData\LocalLow\7th Beat Games",
    ROOT + r"\samples",
    ROOT + r"\tests\fixtures",
    ROOT + r"\patterns",
    ROOT + r"\out",
]

INTEREST = (
    "SetTrackColors", "ColorTrack", "RecolorTrack", "MoveCamera", "SetCameraZoom",
    "SetPlanetColors", "SetBackground", "Flash", "PositionTrack", "AddDecoration",
    "SetSpeed", "Twirl", "Pause", "SetTrackStyle", "CustomBackground", "MoveTrack",
    "SetHitsound", "Bloom", "ShakeScreen", "ScreenScroll", "ScreenTile",
    "SetFilter", "SetFrameRate", "HallOfMirrors",
    "EditorComment",
)

#: ★★ 观测盲区的教训（2026-10）：第一版只统计 `INTEREST` 里列的事件，
#: 于是「语料里没有 `ColorTrack`」成了**我的观测盲区**而不是事实 ——
#: 全量重扫发现它用了几千次（`floor` 3898 种取值）。所以现在**所有** eventType 都计数，
#: `INTEREST` 只管「要不要打印字段真值」。


def steam_roots() -> list[str]:
    """从 libraryfolders.vdf 挖出所有 Steam 库，拼出工坊 / 游戏目录。"""
    out: list[str] = []
    vdf = os.path.join("steamapps", "libraryfolders.vdf")
    for base in STEAM_COMMON_GUESS:
        p = os.path.join(base, vdf)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
                txt = f.read()
        except Exception as e:  # noqa: BLE001
            print(f"   (读不了 {p}: {e})")
            continue
        paths = re.findall(r'"path"\s*"([^"]+)"', txt)
        for lib in paths:
            lib = lib.replace("\\\\", "\\")
            out.append(os.path.join(lib, "steamapps", "workshop", "content", STEAM_APPID))
            out.append(os.path.join(lib, "steamapps", "common", "A Dance of Fire and Ice"))
    return out


def scan_file(p: str, keys: dict, values: dict, ver: dict, samples: dict,
              allc: collections.Counter) -> str | None:
    try:
        with open(p, "r", encoding="utf-8-sig") as f:   # ★ BOM 兼容
            j = json.load(f)
    except Exception as e:  # noqa: BLE001
        return f"BAD {p}: {e}"
    if not isinstance(j, dict):
        return None
    v = j.get("settings", {}).get("version")
    ver[v] = ver.get(v, 0) + 1
    actions = j.get("actions")
    if not isinstance(actions, list):
        return None
    for a in actions:
        if not isinstance(a, dict):
            continue
        et = a.get("eventType") or "<none>"
        allc[et] += 1                     # ★ **所有** eventType 都计数（防观测盲区）
        if et not in INTEREST:
            continue                      # 只有不关心的才不打印字段真值
        keys[et].add(frozenset(a.keys()))
        for k, val in a.items():
            if isinstance(val, (str, int, float, bool)) or val is None:
                values[(et, k)][repr(val)] += 1
        if et not in samples:
            samples[et] = (p, a)
    return None


def main() -> int:
    keys: dict[str, set] = collections.defaultdict(set)
    values: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    ver: collections.Counter = collections.Counter()
    samples: dict[str, tuple] = {}
    allc: collections.Counter = collections.Counter()
    n_files = 0
    problems = []

    roots = list(CANDIDATE_ROOTS)
    sr = steam_roots()
    roots += sr
    print("=== 根目录 ===")
    for r in roots:
        print(f"  [{'有' if os.path.isdir(r) else '无'}] {r}")
    print()

    seen = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in
                           ("node_modules", ".git", "System Volume Information", "$RECYCLE.BIN")]
            for fn in filenames:
                if not fn.lower().endswith(".adofai"):
                    continue
                p = os.path.join(dirpath, fn)
                rp = os.path.realpath(p)
                if rp in seen:
                    continue
                seen.add(rp)
                n_files += 1
                err = scan_file(p, keys, values, ver, samples, allc)
                if err:
                    problems.append(err)

    print(f"=== 扫描到 .adofai 文件 {n_files} 份 ===")
    print(f"版本分布: {dict(sorted((str(k), v) for k, v in ver.items()))}")
    print()
    print("=== 出现过的 **所有** eventType（按条数降序；★ 防观测盲区）===")
    for et, n in allc.most_common():
        mark = "" if et in INTEREST else "   (字段真值未打印)"
        print(f"  {et}: {n} 条{mark}")
    print()
    print("=== 关注事件的字段真值 ===")
    for et in INTEREST:
        if et not in keys:
            print(f"\n-- {et}: (语料样本里没有)")
            continue
        print(f"\n-- {et}:")
        for combo in sorted(keys[et], key=lambda c: -len(c)):
            print(f"     keys = {sorted(combo)}")
        for k in sorted({k for (e, k) in values if e == et}):
            c = values[(et, k)]
            top = c.most_common(12)
            more = "" if len(c) <= 12 else f"  (+{len(c) - 12} 种其他取值)"
            print(f"     {k}: {[t[0] for t in top]}{more}")
    print()
    print("=== 样例（每种关注事件各一份）===")
    for et, (p, a) in sorted(samples.items()):
        if et == "EditorComment":
            continue
        print(f"\n-- {et}  来自 {p}")
        print(json.dumps(a, ensure_ascii=False, indent=2))
    if problems:
        print()
        print(f"=== 读不了的文件（{len(problems)} 份，前 40）===")
        for x in problems[:40]:
            print("  " + x)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
