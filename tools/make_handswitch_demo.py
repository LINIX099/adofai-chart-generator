# -*- coding: utf-8 -*-
"""**换手押上色测试谱**：造一份能直接进游戏看的 `.adofai`（+ 自合成节拍点击音）。

    python tools/make_handswitch_demo.py [输出目录]

为什么专门造一份：`OOX` 结构（每 2 个普通格夹 1 个双押）是**玩家手写**的写法，
生成器出不出得来完全看音源 —— 测试谱要能**精确控制结构**。所以这里直接按 `docs/59`
的定义拼格子，而且**正例 + 两个反例并排**：

    段1  换手押 · 正例     8 个周期   → 应当 **染色**（每 2 个双押染 1 个 ⇒ 4 处）
    段2  反例 · 间隔 3 格  3 个双押   → 结构不是 OOX ⇒ **不染色**
    段3  反例 · 孤立双押   1 个双押   → 不足 2 周期 ⇒ **不染色**
    段4  换手押 · 恢复     3 个周期   → 应当 **染色**（⇒ 1 处）

三段的双押**几何一样、Twirl 一样**（都在薄格上），**只有间距不同** ⇒ 游戏里看到的颜色差异，
就只能是判据造成的（A/B 对照，不是巧合）。

★ 写的事件是 **`ColorTrack` + `justThisTile:true`**（游戏里的「设置轨道颜色」+
  「仅作用于当前方块」），**不是** `RecolorTrack`（「重新设置轨道颜色」）：
  · `scnGame.cs:379-461` 建关时**逐格预演** ⇒ 那格**一出现就是霓虹**（「设置」语义）；
  · `scnGame.cs:447-461`：`justThisTile` 为真 ⇒ 不写回全局当前颜色 ⇒ **只改这一格**；
  · ⇒ 既不「走过后才变色」，也**不会几百条事件堆在同一格**（一格一条）。

输出：<输出目录>/main.adofai + main.wav（默认 out/换手押测试谱/）
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import wave

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

from core import colorize as CZ                              # noqa: E402
from core import path as path_mod                            # noqa: E402
from core import solve as solve_mod                          # noqa: E402
from core import writer as W                                 # noqa: E402

BPM = 180.0
THETA = 30.0            # 双押薄格 travel（= 用户样例里那对 30/150）
CD = 4                  # countdownTicks
SR = 44100


# ------------------------------------------------------------------ 拼谱面
class Builder:
    """逐格拼：`pair()` 落一个双押组，`straight()` 落一个普通格，`note()` 开一段。"""

    def __init__(self) -> None:
        self.travels: list[float] = [180.0]        # 第 0 格 = 开局站位（恒直线）
        self.twirls: list[bool] = [False]
        self.pairs: list[tuple[int, int, int]] = []    # (薄格, 薄格, 剩余格)
        self.marks: list[tuple[int, str]] = []         # 段落注释：(floor, 文本)
        self.sections: list[dict] = []                 # [{floor,text,expect,pairs,u0,u1}]
        self.units: list[tuple[str, int | None]] = []  # 结构串单位：("X", 薄格) / ("O", None)

    def pair(self, theta: float = THETA) -> int:
        """一个双押组：`[薄格 θ, 剩余格 180−θ]`；Twirl 放在薄格上（= 真·换手押）。"""
        thin = len(self.travels)
        self.travels.append(float(theta))
        self.twirls.append(True)
        rest = len(self.travels)
        self.travels.append(180.0 - float(theta))
        self.twirls.append(False)
        self.pairs.append((thin, thin, rest))
        if self.sections:
            self.sections[-1]["pairs"].append(thin)
        self.units.append(("X", thin))
        return thin

    def straight(self, n: int = 1) -> None:
        for _ in range(n):
            self.travels.append(180.0)
            self.twirls.append(False)
            self.units.append(("O", None))

    def note(self, text: str, expect: bool = False) -> None:
        floor = len(self.travels)
        self.marks.append((floor, text))
        if self.sections:                      # 收上一段的「单位区间」
            self.sections[-1]["u1"] = len(self.units)
        self.sections.append({"floor": floor, "text": text, "expect": bool(expect),
                              "pairs": [], "u0": len(self.units), "u1": None})


def build() -> tuple[solve_mod.Chart, list[tuple[int, str]], CZ.ColorPlan, list[int],
                    list[dict], list[tuple[str, int | None]]]:
    """返回 (chart, 段落注释, 方案, **期望被染色的 floor**, 段落表, 结构单位表)。

    ★ 段与段之间必须插**分隔格**：段1 末尾天然带 2 个普通格，
      若段2 的第一个双押紧跟其后，间隔恰好 = 2 ⇒ **会跨段接上链**（造谱时实测踩过：
      段2 的第一个双押被染了，反例就不成反例）。所以每段之间补 2 个普通格，
      把边界间隔顶到 ≥ 4。`main()` 里会**自检**「染色的正好是期望的那些格」。
    """
    b = Builder()
    sep = 2                                   # 段间分隔普通格数

    b.note("段1／4 · 换手押 **正例** —— 8 个周期（每 2 个普通格夹 1 个双押）⇒ 应当染色",
           expect=True)
    for _ in range(8):
        b.pair()
        b.straight(2)
    b.straight(sep)

    b.note("段2／4 · 反例 **间隔 3 格** —— 双押之间夹 3 个普通格 ⇒ 不是 OOX，**不染色**")
    for _ in range(3):
        b.pair()
        b.straight(3)
    b.straight(sep)

    b.note("段3／4 · 反例 **孤立双押** —— 全段只有 1 个双押（不足 2 周期）⇒ **不染色**")
    b.pair()
    b.straight(4)
    b.straight(sep)

    b.note("段4／4 · 换手押 **恢复** —— 3 个周期 ⇒ 应当染色", expect=True)
    for _ in range(3):
        b.pair()
        b.straight(2)

    b.travels.append(180.0)          # 尾层（不影响任何 onset）
    b.twirls.append(False)
    if b.sections:                   # 收最后一段
        b.sections[-1]["u1"] = len(b.units)

    floors = [solve_mod.Floor(travel=t, bpm=BPM, twirl=tw, turn=0.0, heading=0.0,
                              angle=0.0, speed_k=1.0, pause_beats=0.0)
              for t, tw in zip(b.travels, b.twirls)]
    # ★ 与 `dp_angle.apply` 同一口径：用 core.path 统一重算几何（angleData 自洽）
    p = path_mod.Path.from_floors(floors, [f.twirl for f in floors], allow_twirl=True)
    p.commit_to(floors, write_twirl=True)

    ch = solve_mod.Chart(base_bpm=BPM, floors=floors, meta={})
    # ★ 权威双押表（就是我们自己生成谱面时 `dp_angle.apply` 回填的那个键）
    ch.meta["dp_pairs"] = list(b.pairs)
    plan = CZ.plan(ch)
    ch.meta["color_events"] = list(plan.events)

    # —— 期望分录：标了 `expect` 的段，按**用户记号串**取「每 every 个双押里的第 phase 个」
    #   （独立按用户给的定义算一遍，不调用 core.colorize —— 否则就是自己验自己）
    every, phase = CZ.COLOR_EVERY, CZ.COLOR_PHASE
    want = sorted(f for s in b.sections if s["expect"]
                  for f in s["pairs"][phase - 1::every])
    return ch, b.marks, plan, want, b.sections, b.units


def notation_units(units, colored: set[int]) -> str:
    """把结构单位渲染成用户那套记号：`X`=双押 / `O`=普通格 / **`D`=染色的双押**。"""
    return " ".join("D" if (fl is not None and fl in colored) else k for k, fl in units)


# ------------------------------------------------------------------ 点击音
def write_click_track(path: str, ch: solve_mod.Chart, plan: CZ.ColorPlan) -> tuple[float, int]:
    """按**真实命中时刻**合成点击音：换手押那一下高音（1320Hz），其余 660Hz。"""
    lead_ms = solve_mod.total_lead_ms(ch, CD)
    times = solve_mod.times_from_chart(ch)
    hi = set(int(f) for f in plan.floors)
    n = int((lead_ms + (times[-1] if times else 0.0) + 1200.0) / 1000.0 * SR)
    buf = [0.0] * max(1, n)

    def click(at_ms: float, freq: float, amp: float) -> None:
        i0 = int(at_ms / 1000.0 * SR)
        dur = int(0.035 * SR)
        for k in range(dur):
            j = i0 + k
            if j < 0 or j >= n:
                continue
            env = math.exp(-k / (0.006 * SR))          # 快衰减，避免糊成一片
            if k < 0.002 * SR:
                env *= k / (0.002 * SR)                # 起音 2ms 淡入（防爆音）
            buf[j] += amp * env * math.sin(2 * math.pi * freq * k / SR)

    for i in range(1, len(times)):                     # 每个格子的命中时刻一下
        click(lead_ms + times[i], 1320.0 if i in hi else 660.0, 0.30 if i in hi else 0.22)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 32767))))
                               for v in buf))
    return lead_ms, n


# ------------------------------------------------------------------ 回读落盘文件
def verify_file(path: str, want_tiles: list[int]) -> list[str]:
    """**回头读一遍落盘文件**（不信任内存里的对象）：

    · 每条事件都在**换手押格**上、且是 `ColorTrack` + `justThisTile:true`；
    · 字段集与 `core.colorize.EVENT_KEYS` **完全相等**（少一个字段游戏就是 NRE，踩过）；
    · **一格最多一条**（用户拿编辑器截图指出过的堆叠问题）；
    · 覆盖的格 == 期望的换手押格。
    """
    bad: list[str] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        j = json.load(f)
    ad = [float(v) for v in j["angleData"]]
    tv = [180.0] + [180.0 - abs((ad[i] - ad[i - 1] + 540.0) % 360.0 - 180.0)
                    for i in range(1, len(ad))]
    seen: dict[int, int] = {}
    got: list[int] = []
    n_old = 0
    for a in j["actions"]:
        et = a.get("eventType")
        if et == "RecolorTrack":
            n_old += 1
            continue
        if et != "ColorTrack":
            continue
        f0 = int(a.get("floor") or 0)
        got.append(f0)
        seen[f0] = seen.get(f0, 0) + 1
        if f0 < 0 or f0 >= len(tv):
            bad.append(f"事件 floor {f0} 超出谱面 {len(tv)} 格")
        elif abs(tv[f0] - THETA) > 1e-6:
            bad.append(f"事件 floor {f0} 不在薄格上（travel={tv[f0]:g}°）")
        if a.get("justThisTile") is not True:
            bad.append(f"floor {f0} 没有 justThisTile:true ⇒ 会连带影响后面的格")
        if set(a.keys()) != set(CZ.EVENT_KEYS):
            bad.append(f"floor {f0} 字段集不符：多 {sorted(set(a) - set(CZ.EVENT_KEYS))} "
                       f"少 {sorted(set(CZ.EVENT_KEYS) - set(a))}")
        if a.get("trackColor") != "000000" or a.get("secondaryTrackColor") != "ffffff":
            bad.append(f"floor {f0} 颜色不是黑底白边：{a.get('trackColor')}"
                       f"/{a.get('secondaryTrackColor')}")
    if n_old:
        bad.append(f"文件里有 {n_old} 条 **RecolorTrack**（应当一条都没有 —— 那是「重新设置」）")
    if not got:
        bad.append("文件里一条 ColorTrack 都没有")
    dup = [f for f, c in seen.items() if c > 1]
    if dup:
        bad.append(f"这些格上压了不止一条事件（堆叠）：{sorted(dup)[:6]}")
    if sorted(got) != sorted(want_tiles):
        bad.append(f"事件格与期望的换手押格不一致：{sorted(got)} vs {sorted(want_tiles)}")
    return bad


# ------------------------------------------------------------------ 主流程
def make_one(out_dir: str) -> int:
    ch, marks, plan, want, sections, units_all = build()
    wav = os.path.join(out_dir, "main.wav")
    lead_ms, n = write_click_track(wav, ch, plan)

    W.write_dir(ch, out_dir, name="main", audio_src=wav,
                song="换手押上色测试谱", artist="(合成节拍点击)",
                author="ADOFAI Chart Generator",
                offset_ms=0.0, difficulty=1, countdown_ticks=CD)

    # ★ 段落注释（EditorComment）只在**测试谱**里加：让他 Alt+F 搜得到。
    #   生产导出不写注释 ⇒ 这里用后处理，不污染 core.writer。
    p = os.path.join(out_dir, "main.adofai")
    with open(p, "r", encoding="utf-8") as f:
        j = json.load(f)
    for floor, txt in marks:
        j["actions"].append({"floor": int(floor), "eventType": "EditorComment",
                             "comment": txt + "\n"})
    j["actions"].sort(key=lambda a: (int(a.get("floor") or 0),
                                     a.get("eventType") != "EditorComment"))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent="\t")

    acts = j["actions"]
    ct = [a for a in acts if a.get("eventType") == "ColorTrack"]
    got = sorted(int(a["floor"]) for a in ct)
    ok = (got == want)
    print("=== 换手押上色测试谱 ===")
    print(f"输出目录 : {out_dir}")
    print(f"事件     : **ColorTrack + justThisTile:true**（= 游戏里的「设置轨道颜色」+"
          f"「仅作用于当前方块」）")
    print(f"谱面     : main.adofai（{len(ch.floors)} 格 · bpm {BPM:g} · "
          f"Twirl {ch.n_twirl} · SetSpeed {ch.n_speed_events}）")
    print(f"音频     : main.wav（自合成点击音 {n / SR:.1f}s，倒计时 {CD} 拍 = "
          f"{lead_ms:.0f}ms；换手押那一下是 1320Hz 高音）")
    print(f"双押组   : {len(ch.meta['dp_pairs'])} 个（全在 meta['dp_pairs'] 里，走权威路径）")
    print(f"被染的格 : {plan.n_events} 处 → {plan.tiles}")
    print(f"堆叠检查 : 一格最多 {plan.max_per_floor} 条事件")
    print(f"         {plan.report_text()}")
    print(f"actions  : {len(acts)} 条（其中 ColorTrack {len(ct)} 条、EditorComment "
          f"{sum(1 for a in acts if a.get('eventType') == 'EditorComment')} 条）")
    print(f"记账     : meta['color_written']={ch.meta.get('color_written')} "
          f"越界={ch.meta.get('color_out_of_range')}")
    print()
    print("逐段对照（★ = 该段有染色 / · = 没染）：")
    for s in sections:
        n_pair = len(s["pairs"])
        n_hit = sum(1 for f in s["pairs"] if f in set(got))
        flag = "★" if n_hit else "·"
        print(f"  floor {s['floor']:>4}  {flag} 该段双押 {n_pair} 个 / 染了 {n_hit} 个"
              f"   {s['text']}")
    print()
    print("结构串（X=双押 / O=普通格 / **D=染色的那双押**）—— 对照你写的 `XOODOOXOODOO`：")
    col = set(got)
    for idx, s in enumerate(sections, 1):
        u0, u1 = int(s["u0"]), int(s["u1"] if s["u1"] is not None else len(units_all))
        seg = notation_units(units_all[u0:u1], col)
        print(f"  段{idx}（染 {seg.count('D')} 处）: {seg}")
    print()
    if ok:
        print(f"✓ 自检通过：判据染色的正好是期望的 {len(want)} 个薄格")
        print("  （段2「间隔 3 格」与段3「孤立双押」**一个都没染** —— 反例对照成立）")
    else:
        print(f"✗ 自检失败：染了 {got}")
        print(f"           期望 {want}")
    bad = verify_file(p, want)
    if bad:
        print("✗ 回读落盘文件失败：")
        for x in bad:
            print("   - " + x)
    else:
        print(f"✓ 回读落盘文件通过：{len(ct)} 条 ColorTrack 全在薄格上、"
              "`justThisTile:true`、字段集与语料真值一致、颜色是黑底白边、**一格一条不堆叠**")
    try:
        from core import rules as rules_mod
        # ★ `check_chart` 返回的是 **dict**（不是对象）—— 用 getattr 取 level 会恒为空，
        #   于是 `level='info'` 的提示被当成违规（第一次跑就踩了）。
        def _lv(v):
            return v.get("level") if isinstance(v, dict) else getattr(v, "level", "")

        def _msg(v):
            return v.get("msg") if isinstance(v, dict) else getattr(v, "msg", v)

        allr = rules_mod.check_chart(ch)
        viol = [v for v in allr if _lv(v) != "info"]
        info = [v for v in allr if _lv(v) == "info"]
        if viol:
            print(f"⚠ 规则检查有 {len(viol)} 条违规：")
            for v in viol[:6]:
                print("   - " + str(_msg(v)))
        else:
            print(f"✓ 规则检查通过（{len(info)} 条 info 提示不算违规，"
                  f"例如：{_msg(info[0]) if info else '无'}）")
    except Exception as exc:                                  # noqa: BLE001
        print(f"（规则检查跳过：{exc}）")
    print()
    return 0 if (ok and ct and not bad) else 1


def main() -> int:
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else os.path.join(_ROOT, "out", "换手押测试谱"))
    rc = make_one(out_dir)
    print("进游戏：把整个输出目录（main.adofai + main.wav）拷进")
    print("  C:\\Users\\<你>\\Documents\\A Dance of Fire and Ice\\Worlds\\")
    print("然后在游戏里选这首；Alt+F 打开 Find Comment 能按段跳。")
    print("★ 那些换手押格**一出现就是黑底白边霓虹**（不是走过才变），"
          "而且编辑器里每格上只有 1 条事件（不会堆成 1/N）。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
