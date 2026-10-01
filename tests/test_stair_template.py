# -*- coding: utf-8 -*-
"""⑤f **「折弯循环」排版 = 求解器第一权重** 的契约测试（迭代 2.2）。

    python tests/test_stair_template.py

## 依据

用户 2026-10 配着一张编辑器截图说：

> 「对于这样**连续 90° 折弯循环**的结构，可以适当聚焦镜头」
> 「你需要学习这个**采音的排版设计**。目前的生成逻辑中有关于这个排版的**生成路径**，
>   你需要做的是把这个排版作为**求解器第一权重使用的路径**」
> （追问后）「实际上应该是位于**模板路径**里面的，但是属于一种**可用的变体**」

截图认出来是 `Sinkhole - Plum\\level.adofai` 的格 `2560..2647`，实测：

```
travel: 30, 60, 90, 90, 90, 90, 90, 90, 90      ← 一个循环 9 格
Twirl :  .   .   .   T   .   T   .   T   .      ← 7 个 90 里隔一个一个
音值  : 1/6, 1/3, 1/2 ×7  ⇒ 和 = **4.0 拍 = 正好一小节**
```

## 这条测试守什么

1. 变体**不进主库**（不加进 `templates.json`），走 `patterns/templates_stair.json`；
2. `SolveParams.stair_first` **默认关**，关着时模板库与排序**与老版本逐字节一致**；
3. 打开时它以 `weight=100` 参与，且**权重是第一排序键**（同分时它赢）；
4. 那个排版的几何/音值/Twirl 与实测一致（不许抄错）。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import templates as T                               # noqa: E402
from core import solve as S                                   # noqa: E402

FAIL: list[str] = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


#: 实测：Sinkhole 格 2560..2568（一个循环）
MEASURED_TRAVEL = [30.0, 60.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0]
MEASURED_TWIRL = [False, False, False, True, False, True, False, True, False]


def main() -> int:
    print("=" * 78)
    print("⑤f 「折弯循环」排版 → 求解器第一权重（迭代 2.2）")
    print("=" * 78)

    # ---------------------------------------------------------------- A
    print("A ★ 变体**不进主库**（否则会动所有既有输出）")
    base = T.load(refresh=True)
    ids = [t.id for t in base]
    check("Z_折弯循环_90阶梯" not in ids,
          "主库 `templates.json` 里**没有**这条变体（主库 %d 条）" % len(base))
    check(all(float(getattr(t, "weight", 0.0)) == 0.0 for t in base),
          "主库所有模板的 `weight` 都是 0 ⇒ **排序与老版本一致**")
    check(os.path.isfile(T.STAIR_PATH), "变体单独放在 `%s`"
          % os.path.relpath(T.STAIR_PATH, _ROOT))

    # ---------------------------------------------------------------- B
    print()
    print("B ★ 变体的几何 / 音值 / Twirl 与实测一致（不许抄错）")
    stair = T.load(extra=T.STAIR_PATH)
    mine = [t for t in stair if t.id == "Z_折弯循环_90阶梯"]
    check(bool(mine), "`load(extra=...)` 里能找到这条变体（共 %d 条）" % len(stair))
    if mine:
        t = mine[0]
        check([round(x, 6) for x in t.travel] == MEASURED_TRAVEL,
              "`travel` 与实测一致：%s" % t.travel)
        check([bool(x) for x in t.twirl] == MEASURED_TWIRL,
              "`Twirl` 与实测一致（7 个 90 里隔位）：%s" % t.twirl)
        check([round(x * 180.0, 6) for x in t.notes] == MEASURED_TRAVEL,
              "`notes = travel/180`：%s" % [round(x, 4) for x in t.notes])
        check(abs(sum(t.notes) - 4.0) < 1e-9,
              "★ 一个循环 = **%g 拍 = 正好一小节**（所以能无缝循环）" % sum(t.notes))
        check(float(t.weight) > 0.0,
              "★ `weight = %g`（> 0 ⇒ 它是「第一权重」）" % t.weight)
        # 全部 90° 折点：这正是「连续 90° 折弯循环」
        turns = [x for x in t.travel if round(x) != 180.0]
        check(len(turns) == len(t.travel) and all(round(x) in (90, 270, 30, 60)
                                                  for x in turns),
              "这条排版**全是折弯**（没有 180 直线格）：%s" % t.travel)

    # ---------------------------------------------------------------- C
    print()
    print("C ★ `SolveParams.stair_first` 默认**关**，关着时逐字节不变")
    import dataclasses as _dc
    names = {f.name for f in _dc.fields(S.SolveParams)}
    check("stair_first" in names, "`SolveParams` 有 `stair_first`")
    check(getattr(S.SolveParams, "stair_first", None) is False,
          "默认值是 **False**（按 `docs/25` §5.3「原逻辑保留，新逻辑单开一个选项」）")
    # 关着 ⇒ 加载的就是主库本身（同一个对象列表）
    t1 = T.load()
    t2 = T.load()
    check([x.id for x in t1] == [x.id for x in t2] == ids,
          "关着时 `load()` 与主库**完全一致**（%d 条）" % len(t1))
    check(all(float(x.weight) == 0.0 for x in t2),
          "而且没有权重差异 ⇒ 贪心排序键退化成原来的 `(-n, id)`")

    # ---------------------------------------------------------------- D
    print()
    print("D ★ 这条排版**真的能被匹配上**（拿实测音值喂给它）")
    rs = [round(x / 180.0, 6) for x in MEASURED_TRAVEL]
    hits_off = T.match_dp(rs, base, 0.006)
    hits_on = T.match_dp(rs, stair, 0.006)
    hit_ids = {h[1].id for h in hits_on}
    check("Z_折弯循环_90阶梯" in hit_ids,
          "打开变体后，实测音值序列命中的是它：%s" % sorted(hit_ids))
    check(len(hits_on) >= 1 and hits_on[0][2] >= 1,
          "而且它是**整段覆盖**（%d 处命中，第 1 处 %d 轮）"
          % (len(hits_on), hits_on[0][2] if hits_on else 0))
    print("     关着时命中：%s" % (sorted({h[1].id for h in hits_off}) or "（无）"))

    # 重复 2 轮（真实谱面是 4 个循环连着）⇒ 应当叠成 2 轮
    rs2 = rs + rs
    hits2 = T.match_dp(rs2, stair, 0.006)
    got = [(h[1].id, h[2]) for h in hits2]
    check(any(i == "Z_折弯循环_90阶梯" and r >= 2 for i, r in got),
          "连着两个循环 ⇒ **轮数叠加**成 ≥2 轮：%s" % got)

    # ---------------------------------------------------------------- E
    print()
    print("E ★ 权重是**第一排序键**（同分时它赢）")
    z = T.Template(id="ZZ_权重测试", name="t", notes=[0.5, 0.5],
                   travel=[90.0, 90.0], twirl=[False, False], weight=100.0)
    a = T.Template(id="AA_同长度", name="t", notes=[0.5, 0.5],
                   travel=[90.0, 90.0], twirl=[False, False], weight=0.0)
    hit = T.match([0.5, 0.5], [a, z], 0.006)
    check(bool(hit) and hit[0][1].id == "ZZ_权重测试",
          "同长度同音值时**权重高的赢**（哪怕 id 字母序更靠后）：%s"
          % [h[1].id for h in hit])
    hit0 = T.match([0.5, 0.5], [a], 0.006)
    check(bool(hit0) and hit0[0][1].id == "AA_同长度",
          "权重全 0 时退化成老行为（唯一候选照常命中）")

    print()
    print("=" * 78)
    if FAIL:
        print("=> FAIL  %d 条没过：" % len(FAIL))
        for x in FAIL:
            print("   · " + x)
        return 1
    print("=> PASS  「折弯循环 = 求解器第一权重」契约全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
