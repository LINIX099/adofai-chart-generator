# -*- coding: utf-8 -*-
"""**算法轨道调度测试谱**：造一份能直接进游戏看的 `.adofai`（+ 自合成节拍点击音）。

    python tools/make_appearance_demo.py [输出目录]

为什么专门造一份：涟漪环要**图形段起点**、半径要**密度跳变**，生成器出不出得来完全看音源。
测试谱要能精确控制这两件事，所以直接拼格子（几何走 `core.path`，与生成器同一真源）：

    段1  稀疏长直     16 格 180°      密度 1.0 格/拍      → 半径保持 100（**不写事件**）
    段2  图形（八边形） 8 格 135°      密度 1.33 格/拍     → ★ 涟漪环触发点（图形段起点）
    段3  密集         48 格 30°       密度 6.0 格/拍      → ★ 半径切到 125（摊开）
    段4  换手押       4 个周期                          → ⑤b 上色（黑底白边霓虹）同场对照
    段5  稀疏回归     12 格 180°                        → ★ 半径切回 100

段间插 4 格分隔（直格），免得密度窗口/图形段粘连。

★ 八边形 = `[135°] × 8`：`turn = 180 − 135 = 45`，8×45 = 360 ⇒ **真的闭合**，
  不是随手写的数字（闭合图形在游戏里看得出来）。

输出：<输出目录>/main.adofai + main.wav（默认 out/算法轨道调度测试谱/）
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

from core import appearance as AP                             # noqa: E402
from core import colorize as CZ                               # noqa: E402
from core import path as path_mod                             # noqa: E402
from core import solve as solve_mod                           # noqa: E402
from core import writer as W                                  # noqa: E402

BPM = 180.0
SEP = 4                 # 段间分隔直格
THETA = 30.0            # 双押薄格 travel（同换手押测试谱）
CD = 4
SR = 44100


class Builder:
    def __init__(self) -> None:
        self.travels: list[float] = [180.0]
        self.twirls: list[bool] = [False]
        self.snow: list[bool] = [False]
        self.pairs: list[tuple[int, int, int]] = []
        self.marks: list[tuple[int, str]] = []
        self.sections: list[dict] = []

    def _push(self, travel: float, *, twirl=False, snow=False) -> int:
        i = len(self.travels)
        self.travels.append(float(travel))
        self.twirls.append(bool(twirl))
        self.snow.append(bool(snow))
        return i

    def straight(self, n: int = 1) -> list[int]:
        return [self._push(180.0) for _ in range(n)]

    def figure8(self, n: int = 8) -> list[int]:
        """闭合八边形：`135°` × n（turn 45°/格）。"""
        return [self._push(135.0, snow=True) for _ in range(n)]

    def dense(self, n: int = 48) -> list[int]:
        return [self._push(THETA) for _ in range(n)]

    def pair(self) -> int:
        thin = self._push(THETA, twirl=True)
        rest = self._push(180.0 - THETA)
        self.pairs.append((thin, thin, rest))
        return thin

    def note(self, text: str) -> int:
        floor = len(self.travels)
        self.marks.append((floor, text))
        self.sections.append({"floor": floor, "text": text, "u0": floor})
        return floor


def build() -> tuple[solve_mod.Chart, AP.AppearancePlan, CZ.ColorPlan, list[dict]]:
    b = Builder()
    b.note("段1／5 · 稀疏长直（16 格 180°）—— 密度 1.0 格/拍 ⇒ 半径保持 100，**不写事件**")
    b.straight(16)
    b.straight(SEP)

    b.note("段2／5 · **图形**（八边形 8 格 135°，真的闭合）—— ★ 涟漪环从这里向外扩散")
    b.figure8(8)
    b.straight(SEP)

    b.note("段3／5 · **密集**（48 格 30°）—— 密度 6.0 格/拍 ⇒ ★ 半径切到 **125**（轨道摊开）")
    b.dense(48)
    b.straight(SEP)

    b.note("段4／5 · 换手押（4 个周期）—— ⑤b 上色同场对照（黑底白边霓虹）")
    for _ in range(4):
        b.pair()
        b.straight(2)
    b.straight(SEP)

    b.note("段5／5 · 稀疏回归（12 格 180°）—— ★ 半径切回 **100**")
    b.straight(12)

    b.straight(1)                      # 尾层

    floors = [solve_mod.Floor(travel=t, bpm=BPM, twirl=tw, turn=0.0, heading=0.0,
                              angle=0.0, speed_k=1.0, pause_beats=0.0)
              for t, tw in zip(b.travels, b.twirls)]
    for f, sn in zip(floors, b.snow):
        f.snowflake = bool(sn)
    p = path_mod.Path.from_floors(floors, [f.twirl for f in floors], allow_twirl=True)
    p.commit_to(floors, write_twirl=True)

    ch = solve_mod.Chart(base_bpm=BPM, floors=floors, meta={})
    ch.meta["dp_pairs"] = list(b.pairs)
    # ⑤b：换手押上色（黑底白边霓虹）—— 与 ⑥ 同场，用来验证「⑤b 优先」的观感
    cplan = CZ.plan(ch)
    ch.meta["color_events"] = list(cplan.events)
    # ⑥：算法轨道调度（皮肤 + 涟漪环 + 半径），**必须拿 ⑤b 的格去避让**
    aplan = AP.plan(ch, occupied=set(cplan.tiles))
    ch.meta["appearance_events"] = list(aplan.events)
    ch.meta["appearance_settings"] = dict(aplan.settings)
    return ch, aplan, cplan, b.sections


def write_click_track(path: str, ch: solve_mod.Chart, hi: set[int]) -> tuple[float, int]:
    lead_ms = solve_mod.total_lead_ms(ch, CD)
    times = solve_mod.times_from_chart(ch)
    n = int((lead_ms + (times[-1] if times else 0.0) + 1200.0) / 1000.0 * SR)
    buf = [0.0] * max(1, n)

    def click(at_ms: float, freq: float, amp: float) -> None:
        i0 = int(at_ms / 1000.0 * SR)
        dur = int(0.035 * SR)
        for k in range(dur):
            j = i0 + k
            if j < 0 or j >= n:
                continue
            env = math.exp(-k / (0.006 * SR))
            if k < 0.002 * SR:
                env *= k / (0.002 * SR)
            buf[j] += amp * env * math.sin(2 * math.pi * freq * k / SR)

    for i in range(1, len(times)):
        click(lead_ms + times[i], 1320.0 if i in hi else 660.0, 0.30 if i in hi else 0.22)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 32767))))
                               for v in buf))
    return lead_ms, n


def verify_file(path: str) -> list[str]:
    """**回读落盘文件**（不信任内存对象）。"""
    bad: list[str] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        j = json.load(f)
    st = j["settings"]
    if st.get("trackStyle") != "Neon":
        bad.append(f"settings.trackStyle 不是 Neon：{st.get('trackStyle')!r}")
    if abs(float(st.get("trackColorAnimDuration", 0)) - 2.0) > 1e-9:
        bad.append("settings.trackColorAnimDuration 不是 2")
    want_rec = {"floor", "eventType", "startTile", "endTile", "gapLength", "duration",
                "trackColorType", "trackColor", "secondaryTrackColor",
                "trackColorAnimDuration", "trackColorPulse", "trackPulseLength",
                "trackStyle", "trackGlowIntensity", "angleOffset", "ease", "eventTag"}
    rec = [a for a in j["actions"] if a.get("eventType") == "RecolorTrack"]
    srs = [a for a in j["actions"] if a.get("eventType") == "ScaleRadius"]
    for a in rec:
        if set(a.keys()) != want_rec:
            bad.append(f"floor {a.get('floor')} RecolorTrack 字段集不符："
                       f"多 {sorted(set(a) - want_rec)} 少 {sorted(want_rec - set(a))}")
            break
    for a in srs:
        if set(a.keys()) != {"floor", "eventType", "scale"}:
            bad.append(f"floor {a.get('floor')} ScaleRadius 键集不符：{sorted(a)}")
            break
    if not rec:
        bad.append("一条 RecolorTrack 都没有（涟漪环没写进去）")
    if [int(a["scale"]) for a in srs] != [125, 100]:
        bad.append(f"半径切换序列不是 [125, 100]：{[a['scale'] for a in srs]}")
    # n=0 绝不许出现 gapLength = -1（游戏里是步长 ⇒ 死循环）
    for a in rec:
        if int(a.get("gapLength", 0)) < 0:
            bad.append(f"floor {a.get('floor')} 出现 gapLength={a['gapLength']}（步长会变 0 ⇒ 死循环）")
            break
    fl = [int(a.get("floor", 0)) for a in j["actions"] if "floor" in a]
    if fl != sorted(fl):
        bad.append("actions 没有按 floor 有序")
    if not any(a.get("eventType") == "ColorTrack" for a in j["actions"]):
        bad.append("⑤b 的 ColorTrack 不见了（同场对照失效）")
    return bad


def make_one(out_dir: str) -> int:
    ch, aplan, cplan, sections = build()
    wav = os.path.join(out_dir, "main.wav")
    hi = ({r.floor for r in aplan.ripples} | {s.floor for s in aplan.radius_spans}
          | set(cplan.tiles))
    lead_ms, n = write_click_track(wav, ch, hi)

    W.write_dir(ch, out_dir, name="main", audio_src=wav,
                song="算法轨道调度测试谱", artist="(合成节拍点击)",
                author="ADOFAI Chart Generator",
                offset_ms=0.0, difficulty=1, countdown_ticks=CD)

    p = os.path.join(out_dir, "main.adofai")
    with open(p, "r", encoding="utf-8") as f:
        j = json.load(f)
    for floor, txt in [(s["floor"], s["text"]) for s in sections]:
        j["actions"].append({"floor": int(floor), "eventType": "EditorComment",
                             "comment": txt + "\n"})
    j["actions"].sort(key=lambda a: (int(a.get("floor") or 0),
                                     a.get("eventType") != "EditorComment"))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent="\t")

    rec = [a for a in j["actions"] if a.get("eventType") == "RecolorTrack"]
    srs = [a for a in j["actions"] if a.get("eventType") == "ScaleRadius"]
    print("=== 算法轨道调度测试谱 ===")
    print(f"输出目录 : {out_dir}")
    print(f"谱面     : main.adofai（{len(ch.floors)} 格 · bpm {BPM:g} · "
          f"Twirl {ch.n_twirl} · SetSpeed {ch.n_speed_events}）")
    print(f"音频     : main.wav（{n / SR:.1f}s，倒计时 {CD} 拍 = {lead_ms:.0f}ms；"
          f"高音 = 涟漪/半径切换/换手押）")
    print(f"皮肤     : settings.trackStyle={j['settings'].get('trackStyle')} "
          f"type={j['settings'].get('trackColorType')} "
          f"pulse={j['settings'].get('trackColorPulse')} "
          f"glow={j['settings'].get('trackGlowIntensity')}")
    print(f"涟漪环   : {len(aplan.ripples)} 处 → "
          f"{[(r.floor, r.rings + 1) for r in aplan.ripples]}（格, 环数）")
    print(f"半径切换 : {[(s.floor, s.scale) for s in aplan.radius_spans]}（格, 半径%）")
    print(f"⑤b 上色  : {cplan.n_events} 格 {cplan.tiles}")
    print(f"事件总计 : {aplan.n_events} 条 = RecolorTrack {len(rec)} + ScaleRadius {len(srs)}")
    print(f"         {aplan.report_text()}")
    print(f"记账     : meta['appearance_written']={ch.meta.get('appearance_written')} "
          f"越界={ch.meta.get('appearance_out_of_range')} "
          f"同格最多={aplan.max_per_floor}")
    print()
    ok = True
    if [int(a["scale"]) for a in srs] != [125, 100]:
        ok = False
        print(f"✗ 自检失败：半径切换序列应为 [125, 100]，实际 {[a['scale'] for a in srs]}")
    else:
        print("✓ 自检通过：密集段切 125、稀疏段切回 100（只在档位变化时写事件）")
    if len(aplan.ripples) != 1 or aplan.ripples[0].floor != sections[1]["floor"]:
        ok = False
        print(f"✗ 自检失败：涟漪触发点应只有段2 起点 {sections[1]['floor']}，"
              f"实际 {[(r.floor, r.kind) for r in aplan.ripples]}")
    else:
        print(f"✓ 自检通过：涟漪环正好打在图形段起点（格 {aplan.ripples[0].floor}，"
              f"{aplan.ripples[0].rings + 1} 环）")
    bad = verify_file(p)
    if bad:
        ok = False
        print("✗ 回读落盘文件失败：")
        for x in bad:
            print("   - " + x)
    else:
        print("✓ 回读落盘文件通过：皮肤进 settings / RecolorTrack 17 字段 / ScaleRadius 3 键 / "
              "gapLength 无 −1 / actions 按 floor 有序 / ⑤b 的 ColorTrack 仍在")
    try:
        from core import rules as rules_mod

        def _lv(v):
            return v.get("level") if isinstance(v, dict) else getattr(v, "level", "")

        def _msg(v):
            return v.get("msg") if isinstance(v, dict) else getattr(v, "msg", v)

        allr = rules_mod.check_chart(ch)
        viol = [v for v in allr if _lv(v) != "info"]
        info = [v for v in allr if _lv(v) == "info"]
        if viol:
            ok = False
            print(f"⚠ 规则检查有 {len(viol)} 条违规：")
            for v in viol[:6]:
                print("   - " + str(_msg(v)))
        else:
            print(f"✓ 规则检查通过（{len(info)} 条 info 提示不算违规）")
    except Exception as exc:                                  # noqa: BLE001
        print(f"（规则检查跳过：{exc}）")
    print()
    return 0 if ok else 1


def main() -> int:
    out_dir = (sys.argv[1] if len(sys.argv) > 1
               else os.path.join(_ROOT, "out", "算法轨道调度测试谱"))
    rc = make_one(out_dir)
    print("进游戏：把整个输出目录（main.adofai + main.wav）拷进")
    print("  C:\\Users\\<你>\\Documents\\A Dance of Fire and Ice\\Worlds\\")
    print("然后选这首；Alt+F 能按段跳。看这四件事：")
    print("  1) **皮肤**：整条轨道已经不是默认方块（Neon + Glow + Forward 流动）")
    print("  2) **段2 图形起点**：白环从脚下向两侧扩散，每环晚 1/6 拍（涟漪环）")
    print("  3) **段3 密集 / 段5 稀疏**：轨道整体摊开 125% → 收回 100%（半径调度）")
    print("  4) **段4 换手押**：黑底白边霓虹那一格（⑤b）与涟漪同时存在时的观感")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
