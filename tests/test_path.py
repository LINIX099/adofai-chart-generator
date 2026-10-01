"""core/path.py 单测：几何底座（朝向 / 坐标 / 转角）。

重点：**与 `_apply` 的旧内联算法逐格等价** —— 这是 P0 重构不回退的回归锚。
另有回正/偏移要用到的查询接口（deviation / diagonal_runs / position / offset）。

跑法:  python tests/test_path.py
"""
import math
import os
import sys

_ROUTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTE)

from core import path as path_mod                      # noqa: E402
from core.path import Path, build_path                 # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


# ---------------------------------------------------------------------------
# 参考实现：重构前 `_apply()` 内联的那段（逐字照抄，作为等价性基准）
def legacy_apply(travels, flips, radius=1.0, allow_twirl=True):
    R2 = 2.0 * radius
    pts = [(0.0, 0.0)]
    heading = 90.0
    ccw = False
    out = {"turn": [], "heading": [], "angle": [], "twirl": [], "pts": None}
    for i, tv in enumerate(travels):
        if flips[i] and allow_twirl:
            ccw = not ccw
        turn = (180.0 - tv) if ccw else (tv + 180.0)
        turn = ((turn + 180.0) % 360.0) - 180.0
        heading = ((heading + turn) + 180.0) % 360.0 - 180.0
        out["turn"].append(turn)
        out["twirl"].append(bool(flips[i] and allow_twirl))
        out["heading"].append(heading % 360.0)
        a = round((90.0 - (heading % 360.0)) % 360.0, 6)
        out["angle"].append(0.0 if abs(a - 360.0) < 1e-6 or abs(a) < 1e-6 else a)
        x, y = pts[-1]
        pts.append((x + R2 * math.cos(math.radians(heading)),
                    y + R2 * math.sin(math.radians(heading))))
    out["pts"] = pts
    return out


CASES = [
    # (travels, flips) —— 覆盖：纯直线、45°族、三连音、内/外圈、Twirl 交替
    ([180.0] * 8, [False] * 8),
    ([180.0, 90.0, 90.0, 180.0, 90.0, 90.0, 180.0, 180.0], [False] * 8),
    ([45.0, 45.0, 90.0, 180.0, 45.0, 45.0, 90.0, 180.0], [False] * 8),
    ([120.0] * 6, [False] * 6),
    ([60.0, 60.0, 60.0, 60.0, 60.0, 60.0], [False] * 6),
    ([180.0, 135.0, 45.0, 270.0, 90.0, 180.0, 315.0, 180.0], [False] * 8),
    # Twirl 交替：每格都翻
    ([90.0] * 8, [True] * 8),
    ([45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0, 180.0], [True, False] * 4),
    # travel < 180（内圈）/ > 180（外圈）
    ([165.0, 150.0, 195.0, 210.0, 165.0, 180.0], [False] * 6),
    ([170.0, 180.0, 10.0, 350.0, 15.0, 345.0, 180.0], [False] * 7),
]


def equivalence():
    print("=" * 78)
    print("A. 与旧 _apply 内联算法逐格等价")
    print("=" * 78)
    for ci, (tv, fl) in enumerate(CASES):
        for radius in (1.0, 0.5, 2.0):
            for allow in (True, False):
                ref = legacy_apply(tv, fl, radius=radius, allow_twirl=allow)
                pth = Path.from_travels(tv, flips=fl, radius=radius, allow_twirl=allow)
                ok = True
                for i in range(len(tv)):
                    ok &= abs(pth.turns[i] - ref["turn"][i]) < 1e-12
                    ok &= abs(pth.headings[i] - ref["heading"][i]) < 1e-12
                    ok &= abs(pth.angles[i] - ref["angle"][i]) < 1e-12
                    ok &= bool(pth.twirl[i]) == ref["twirl"][i]
                for i in range(len(tv) + 1):
                    ok &= abs(pth.points[i][0] - ref["pts"][i][0]) < 1e-12
                    ok &= abs(pth.points[i][1] - ref["pts"][i][1]) < 1e-12
                check(ok, f"case{ci} r={radius} allow={allow}: 逐格等价")
        # 只打一行汇总，避免刷屏
    print(f"  → 共 {len(CASES)} 组 × (r=3) × (allow=2) = {len(CASES)*6} 次比对")


def invariants():
    print("=" * 78)
    print("B. 几何不变量")
    print("=" * 78)
    p = Path.from_travels([180.0] * 5)
    check(len(p.points) == 6, f"points 长度 == 格数+1 （{len(p.points)}）")
    check(all(abs(t) < 1e-12 for t in p.turns), "全直线 → turn 全为 0")
    check(all(abs(a) < 1e-12 for a in p.angles), "全直线 → angleData 全为 0")
    check(p.is_axis_aligned(0) and p.is_axis_aligned(4), "全直线 → 全正交")

    # travel = 180 ⇒ turn = 0（ccw 与否都一样）
    p2 = Path.from_travels([180.0, 180.0], flips=[True, False])
    check(abs(p2.turns[1]) < 1e-12, "travel=180 的 turn 恒为 0（与 Twirl 无关）")

    # angle = (90 − heading) mod 360
    p3 = Path.from_travels([90.0, 90.0, 90.0, 90.0])
    for i in range(p3.n):
        a = (90.0 - p3.headings[i]) % 360.0
        a = 0.0 if abs(a - 360.0) < 1e-9 or abs(a) < 1e-9 else round(a, 6)
        check(abs(a - p3.angles[i]) < 1e-9, f"angle[{i}] == (90−heading) mod 360")

    # 第一步恒朝 90°（angleData[0] == 0 的由来）—— 前提是首格 travel=180（turn=0）
    p0 = Path.from_travels([180.0, 90.0, 90.0, 90.0])
    check(abs(p0.headings[0] - 90.0) < 1e-12,
          "首格 travel=180 → heading[0] == 90°")


def twirl_parity():
    print("=" * 78)
    print("C. Twirl 奇偶：只改转向符号，不改第 0 格直线")
    print("=" * 78)
    base = Path.from_travels([90.0], flips=[False])
    flip = Path.from_travels([90.0], flips=[True])
    check(abs(base.turns[0] - (-90.0)) < 1e-12, "非 ccw：travel=90 → turn = −90")
    check(abs(flip.turns[0] - 90.0) < 1e-12, "ccw：travel=90 → turn = +90")
    check(flip.twirl[0] is True and base.twirl[0] is False, "twirl 标志跟随翻转位")

    # allow_twirl=False 时翻转位被忽略
    off = Path.from_travels([90.0] * 3, flips=[True, True, True], allow_twirl=False)
    check(all(not t for t in off.twirl), "allow_twirl=False → 不产生 Twirl")
    check(off.ccw[-1] is False, "allow_twirl=False → ccw 始终 False")


def queries():
    print("=" * 78)
    print("D. 查询接口（项1 回正 / 项2 偏移）")
    print("=" * 78)
    # 一条持续斜轨：heading 恒定 45°（全 travel=180 不变向），即「斜着的一条长轨」
    diag = Path.from_travels([180.0] * 12, heading0=45.0)
    dev_ok = all(abs(diag.deviation(i) - 45.0) < 1e-9 for i in range(diag.n))
    check(dev_ok, "heading=45° 的直线段：每格 deviation == 45（持续斜）")
    check(not diag.is_axis_aligned(0), "斜轨格不判为「正交」")
    runs = diag.diagonal_runs(theta=20.0, min_run=8, start=0)
    check(runs == [(0, 12)], f"diagonal_runs 找到整段斜轨 （{runs}）")
    runs2 = diag.diagonal_runs(theta=20.0, min_run=8, start=1)
    check(runs2 == [(1, 11)], f"start=1 跳过开场格 （{runs2}）")
    # 阈值/长度门槛
    check(not diag.diagonal_runs(theta=50.0, min_run=2),
          "theta 太大（45° 不算斜）→ 不报斜段")
    check(not diag.diagonal_runs(theta=20.0, min_run=100),
          "min_run 太大 → 不报斜段")

    # 锯齿情形：travel=165 每格转 −15°，heading 会扫过主轴
    saw = Path.from_travels([180.0] + [165.0] * 10)
    devs = [round(saw.deviation(i), 6) for i in range(saw.n)]
    check(max(devs) > 20.0, f"渐转段有偏离主轴的格 （max dev={max(devs):.1f}）")
    check(min(devs) < 1e-6, "渐转段会扫过主轴（dev 归零）")

    # 位置 / 相对位移
    check(len(diag.points) == diag.n + 1, "points 长度 = 格数+1")
    off = diag.offset_of(0)
    check(abs(math.hypot(off[0], off[1]) - 2.0) < 1e-9,
          "相邻格中心距 == 2R（R=1）")
    rel = diag.relative_of(1, 0)
    check(abs(rel[0] - off[0]) < 1e-12 and abs(rel[1] - off[1]) < 1e-12,
          "relative_of(1,0) == offset_of(0)")

    # 质心 / 最小距离
    cx, cy = diag.recent_centroid(4, 4)
    check(isinstance(cx, float) and isinstance(cy, float), "recent_centroid 返回浮点")
    d = diag.min_distance_recent(diag.n - 1, recent=24)
    check(d > 0, f"min_distance_recent > 0 （{d:.3f}）")

    # 包围盒
    w, h = diag.size
    check(w > 0 or h > 0, f"包围盒非退化 （{w:.2f} × {h:.2f}）")


def commit_roundtrip():
    print("=" * 78)
    print("E. commit_to 写回 Floor 等价")
    print("=" * 78)

    class F:
        __slots__ = ("travel", "turn", "heading", "angle", "x", "y", "twirl")

        def __init__(self, tv):
            self.travel = tv
            self.turn = 0.0
            self.heading = 0.0
            self.angle = 0.0
            self.x = self.y = 0.0
            self.twirl = False

    tv = [180.0, 90.0, 45.0, 135.0, 180.0]
    fl = [False, True, False, True, False]
    floors = [F(t) for t in tv]
    p = build_path(floors, fl)
    p.commit_to(floors, write_twirl=True)
    ref = legacy_apply(tv, fl)
    ok = True
    for i in range(len(tv)):
        ok &= abs(floors[i].turn - ref["turn"][i]) < 1e-12
        ok &= abs(floors[i].heading - ref["heading"][i]) < 1e-12
        ok &= abs(floors[i].angle - ref["angle"][i]) < 1e-12
        ok &= bool(floors[i].twirl) == ref["twirl"][i]
        ok &= abs(floors[i].x - ref["pts"][i][0]) < 1e-12
        ok &= abs(floors[i].y - ref["pts"][i][1]) < 1e-12
    check(ok, "commit_to 写回与旧 _apply 等价")
    check(abs(floors[0].x) < 1e-12 and abs(floors[0].y) < 1e-12,
          "第 0 格坐标 == (0,0)")


def main():
    equivalence()
    invariants()
    twirl_parity()
    queries()
    commit_roundtrip()
    print("=" * 78)
    if FAIL:
        print(f"=> FAIL  （{len(FAIL)} 条）")
        for m in FAIL[:12]:
            print("   · " + m)
        return 1
    print("=> PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
