"""生成节奏型骨架 —— 一个家族一个 .adofai。

格式照抄 samples/三种三连音写法.adofai：
  - EditorComment 当分界线（写清编号 / 乐理名 / travel / 记谱 / 几何结论）
  - PositionTrack 把每段错开，方便在编辑器里看
  - Twirl 全部留空，等用户来摆

角度公式（已验证）：
  travel_i (miner 序，i=0 是 floor1→floor2 的间隔)
  a[0] = 0,  a[k] = (a[k-1] + 180 - travel[k-1]) % 360
  于是 (180 + a[i] - a[i+1]) % 360 == travel[i]

几何（来自 scrLevelMaker：相邻两格恒距 1 格；先按当前朝向走一格，再转）：
  h[0] = 90°, turn_k = travel_k - 180°, h += turn
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.writer import SETTINGS_TEMPLATE, _num  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "patterns")
BPM = 120
UNIT = 15.0            # 1 个字符 = 15°

# 每项 = (编号, 乐理名, gaps)  gaps = 记谱里相邻 X 之间的字符数 = travel/15
FAMILIES: dict[str, list] = {
    # ---- 已定 ----
    "A_均分骨架": [
        ("A1", "四分（直线）",      [12]),
        ("A2", "八分 x2",           [6, 6]),
        ("A3", "十六分 x4",         [3, 3, 3, 3]),
    ],
    "B_强弱拍": [
        ("B1", "附点四分 + 八分",   [18, 6]),
        ("B2", "八分 + 附点四分",   [6, 18]),
        ("C1", "八分 + 四分",       [6, 12]),
        ("C2", "四分 + 八分",       [12, 6]),
        ("C3", "附点四分 + 四分",   [18, 12]),
        ("C4", "四分 + 附点四分",   [12, 18]),
    ],
    "C_摇摆拍子": [
        ("D1", "附点八分 + 十六分", [9, 3]),
        ("D2", "十六分 + 附点八分", [3, 9]),
    ],
    # ---- 待定：三连家族 / 拿不准的 ----
    "F_三连家族_待定": [
        ("F01", "等边三角形",        [4, 4, 4]),
        ("F02", "等边三角形·镜像",   [20, 20, 20]),
        ("F03", "60°折线",          [8, 8, 8]),
        ("F04", "60°折线·镜像",      [16, 16, 16]),
        ("F05", "菱形",             [8, 4, 8, 4]),
        ("F06", "菱形·镜像",         [16, 20, 16, 20]),
        ("F07", "双等边三角",        [4, 4, 4, 4, 4, 4]),
        ("F08", "三连爬升",          [20, 4, 8]),
        ("F09", "三连环绕",          [16, 20, 4, 8]),
        ("F10", "直角三角形",        [6, 3, 3]),
        ("F11", "直角三角形·镜像",   [18, 21, 21]),
        ("F12", "直角三角形(中)",    [3, 6, 3]),
        ("F13", "直角三角形(后)",    [3, 3, 6]),
        ("F14", "菱形(错位)",        [4, 8, 4, 8]),
        ("F15", "摇摆 x2",          [9, 3, 9, 3]),
    ],
}

SEP = 180.0            # 段间留一格直线
SHIFT = [3.0, 0.0]     # 每段错开 3 格


def notation_of(gaps: list[int]) -> str:
    """gaps → X 记谱（1 字符 = 15°，两个 X 之间隔 g-1 个点）。"""
    out = []
    for g in gaps:
        out.append("X")
        out.append("·" * (g - 1))
    return "".join(out)


def geom_note(travels: list[float]) -> str:
    """转角序列 + 是否闭合 + 位置。"""
    p = [(0.0, 0.0)]
    h, turns = 90.0, []
    for t in travels:
        p.append((p[-1][0] + math.cos(math.radians(h)),
                  p[-1][1] + math.sin(math.radians(h))))
        turns.append(t - 180.0)
        h += turns[-1]
    closed = abs(p[-1][0]) < 1e-6 and abs(p[-1][1]) < 1e-6
    ts = " ".join(f"{x:+.0f}" for x in turns)
    ps = " ".join(f"({x:+.2f},{y:+.2f})" for x, y in p)
    return (f"转角: {ts}  合计 {sum(turns):+.0f}°\n"
            f"位置: {ps}\n"
            f"{'★ 闭合（回到起点）' if closed else '不闭合'}")


def travels_of(a: list[float]) -> list[float]:
    return [round((180.0 + a[i] - a[i + 1]) % 360.0, 4) for i in range(len(a) - 1)]


def build_angles(T: list[float]) -> list[float]:
    a = [0.0]
    for t in T:
        v = (a[-1] + 180.0 - t) % 360.0
        if abs(v - 360.0) < 1e-9:
            v = 0.0
        a.append(v)
    return a


def build_family(cells):
    T: list[float] = []
    actions: list[dict] = []
    checks: list[tuple[str, int, list[float]]] = []

    for cid, mus, gaps in cells:
        want = [g * UNIT for g in gaps]
        start = len(T)                       # miner 序号（= floor-1）
        T.extend(want)
        T.append(SEP)                        # 段间直线
        floor = start + 1
        comment = (f"{cid} {mus}\n"
                   f"travel: " + " · ".join(f"{x:g}°" for x in want) + "\n"
                   f"记谱(1字符=15°): {notation_of(gaps)}\n"
                   f"{geom_note(want)}\n"
                   f"（Twirl 待摆）")
        actions.append({"floor": floor, "eventType": "EditorComment",
                        "comment": comment})
        actions.append({"floor": floor, "eventType": "PositionTrack",
                        "positionOffset": list(SHIFT),
                        "relativeTo": [0, "ThisTile"],
                        "justThisTile": False, "editorOnly": False})
        checks.append((cid, start, want))

    a = build_angles(T)
    s = dict(SETTINGS_TEMPLATE)
    s.update({
        "bpm": BPM, "offset": 0,
        "beatsAhead": 3, "beatsBehind": 4,
        "trackDisappearAnimation": "None",
        "countdownTicks": 4, "separateCountdownTime": False,
        "zoom": 200, "hitsoundVolume": 25,
    })
    return {"angleData": [_num(v) for v in a], "settings": s,
            "actions": actions, "decorations": []}, checks


def load_loose(path: str):
    import re as _re
    txt = open(path, encoding="utf-8-sig").read()
    txt = _re.sub(r",(\s*[}\]])", r"\1", txt)
    return json.loads(txt, strict=False)


def has_twirl(path: str) -> bool:
    try:
        d = load_loose(path)
    except Exception:
        return False
    return any(a.get("eventType") == "Twirl" for a in d.get("actions", []))


def identical(path: str, data: dict) -> bool:
    """文件里的 angleData 和这次要生成的是否一致。"""
    try:
        d = load_loose(path)
    except Exception:
        return False
    return d.get("angleData") == data["angleData"]


# 以前生成过、现在已从清单移除的骨架 —— 只有这些允许自动删
LEGACY = {"B_附点", "C_直线拐一格", "D_长短切分", "E_30度网格"}


def main():
    force = "--force" in sys.argv
    os.makedirs(OUT, exist_ok=True)

    # 只清掉「以前自己生成过、现已从清单移除」的骨架。别的一律不动。
    for fn in os.listdir(OUT):
        stem, ext = os.path.splitext(fn)
        if ext != ".adofai" or stem not in LEGACY:
            continue
        p = os.path.join(OUT, fn)
        if has_twirl(p):
            print(f"[留] {fn}（有 Twirl，不动）")
        else:
            os.remove(p)
            print(f"[删] {fn}（已从清单移除）")

    ok = True
    for name, cells in FAMILIES.items():
        data, checks = build_family(cells)
        tv = travels_of([float(x) for x in data["angleData"]])
        problems = []
        for cid, start, want in checks:
            got = tv[start:start + len(want)]
            if [round(x, 4) for x in got] != [round(x, 4) for x in want]:
                problems.append(f"{cid}: 期望 {want} 实际 {got}")
            nxt = tv[start + len(want)] if start + len(want) < len(tv) else None
            if nxt is not None and abs(nxt - SEP) > 1e-6:
                problems.append(f"{cid}: 段尾应为 {SEP}°，实际 {nxt}")

        path = os.path.join(OUT, f"{name}.adofai")
        if os.path.exists(path) and not force:
            if has_twirl(path):
                print(f"[SKIP] {name} —— 已含 Twirl（你手改过的），不覆盖")
                continue
            if not identical(path, data):
                print(f"[SKIP] {name} —— 文件内容和本次要生成的不一样（你手改过的），不覆盖")
                print(f"       确认要重写加 --force")
                continue
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent="\t")
        if problems:
            ok = False
        print(f"[{'OK' if not problems else 'FAIL'}] {name:16s} "
              f"{len(checks):>2} 段  {len(data['angleData']):>3} 格")
        print(f"       -> {path}")
        for p in problems:
            print("        ! " + p)

    print("\n全部自检通过" if ok else "\n有段落不合格，见上")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
