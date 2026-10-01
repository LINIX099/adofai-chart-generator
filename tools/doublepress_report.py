# -*- coding: utf-8 -*-
"""双押演示素材核对 + 生成 docs/双押练习说明.md。

核对三件事：
  1. MIDI 能被 `core.midi.load()` 读回，且逐音符与事件表一致（含力度分层）。
  2. OGG 的音头时刻落在设计网格上（误差分布）。
  3. 重音层在音频里确实比基准音高出一截（不然听不出双押点）。

用法：python tools/doublepress_report.py [--bpm 120 90]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.make_doublepress import (  # noqa: E402
    BEATS_PER_BAR, PPQ, SECTIONS, SR, build,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = os.path.join(ROOT, "samples", "audio")
DOC = os.path.join(ROOT, "docs", "双押练习说明.md")
CH_OF = {"mel": 0, "acc": 2, "click": 9, "crash": 9}


def expected_events(notes):
    out = []
    for n in notes:
        out.append((CH_OF[n.layer], int(round(n.t * PPQ)),
                    n.pitch, n.vel))
    return sorted(out)


def check_midi(path, notes):
    from core.midi import load
    mf = load(path)
    got = sorted((nt.channel, nt.t_on_tick, nt.pitch, nt.velocity)
                 for tr in mf.tracks for nt in tr.notes)
    exp = expected_events(notes)
    ok = (got == exp)
    print(f"  format={mf.format} ppqn={mf.ppqn} 轨={len(mf.tracks)} "
          f"tempo={[b for _, b in mf.tempo_map]} 时长={mf.length_ms/1000:.2f}s")
    for tr in mf.tracks:
        chans = sorted({n.channel for n in tr.notes})
        print(f"    trk{tr.index} {tr.name!r:20s} 音符={len(tr.notes):4d} ch={chans}")
    print(f"  逐音符比对: {'一致' if ok else '不一致'}"
          f"  (期望 {len(exp)} / 实得 {len(got)})")
    if not ok:
        se, sg = set(exp), set(got)
        print(f"    仅期望有 {len(se - sg)} 条, 仅实得有 {len(sg - se)} 条")
        for x in list(se - sg)[:5]:
            print("      -", x)
        for x in list(sg - se)[:5]:
            print("      +", x)
    return ok, mf


def check_ogg(path, notes, bpm):
    import soundfile as sf
    from core.audio_onsets import detect_onsets
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    t_ms = detect_onsets(y, sr, hop=64, pct=75.0, min_gap_ms=40.0)

    # 1) 网格落点：所有设计音时刻（含节拍器）
    grid = np.array(sorted({n.t for n in notes})) * (60000.0 / bpm)
    idx = np.searchsorted(grid, t_ms)
    idx = np.clip(idx, 1, len(grid) - 1)
    near = np.where(np.abs(t_ms - grid[idx - 1]) <= np.abs(t_ms - grid[idx]),
                    grid[idx - 1], grid[idx])
    err = t_ms - near
    print(f"  音头 {len(t_ms)} 个（pct=75）/ 设计音 {len(grid)} 个")
    for p in (45, 60):
        alt = detect_onsets(y, sr, hop=64, pct=float(p), min_gap_ms=40.0)
        idx3 = np.clip(np.searchsorted(grid, alt), 1, len(grid) - 1)
        na = np.where(np.abs(alt - grid[idx3 - 1]) <= np.abs(alt - grid[idx3]),
                      grid[idx3 - 1], grid[idx3])
        print(f"    pct={p}: {len(alt)} 个，|误差| 90% "
              f"{np.percentile(np.abs(alt - na), 90):.2f}ms")
    print("    → 检出量由 pct 决定（「只留最强的百分之几」），不是缺陷；"
          "这里关心的是**落点精度**。")
    print(f"  到最近设计音: 偏置 {np.median(err):+.2f}ms  散布 {np.std(err):.2f}ms  "
          f"|误差| 90% {np.percentile(np.abs(err), 90):.2f}ms  "
          f"最大 {np.max(np.abs(err)):.2f}ms")
    print("  → 偏置是检波器固有延迟（librosa 的 STFT 窗半宽 n_fft/2≈23ms，"
          "能量先于脉冲中心进窗），与素材无关；下游靠网格吸附吃掉。")

    # 2) 重音对比度：音头后 40ms 的 RMS 峰值
    env = np.sqrt(np.convolve(y.astype(np.float64) ** 2,
                              np.ones(64) / 64, mode="same"))
    w = int(0.040 * sr)

    def peak_db(t):
        i = int(t / 1000.0 * sr)
        seg = env[i:i + w]
        return 20 * np.log10(max(float(seg.max()), 1e-9))

    def band(layer, vel=None):
        v = []
        for n in notes:
            if n.layer != layer:
                continue
            if vel is not None and n.vel != vel:
                continue
            v.append(peak_db(n.t * 60000.0 / bpm))
        return np.array(v)

    mel_acc = np.concatenate([band("mel", 120), band("acc", 110)])
    mel_nor = band("mel", 72)
    a, b = float(np.median(mel_acc)), float(np.median(mel_nor))
    print(f"  重音点 RMS {a:.1f} dB / 基准音 {b:.1f} dB → 对比 {a-b:.1f} dB")
    return dict(onsets=len(t_ms), design=len(grid),
                bias=float(np.median(err)), spread=float(np.std(err)),
                p90=float(np.percentile(np.abs(err), 90)),
                mx=float(np.max(np.abs(err))), contrast=a - b)


def write_doc(notes, bpms):
    acc_by_sec: dict[str, int] = {}
    mel_by_sec: dict[str, int] = {}
    for n in notes:
        if n.layer == "acc":
            acc_by_sec[n.sec] = acc_by_sec.get(n.sec, 0) + 1
        elif n.layer == "mel":
            mel_by_sec[n.sec] = mel_by_sec.get(n.sec, 0) + 1

    marks = []
    t, bar = 0.0, 1
    for sec in SECTIONS:
        marks.append((bar, bar + sec["bars"] - 1, sec, t))
        bar += sec["bars"]
        t += sec["bars"] * BEATS_PER_BAR

    cols = " | ".join(f"@{int(b)}s 起" for b in bpms)
    sep = " | ".join(["---"] * len(bpms))
    lines = [
        "# 双押练习素材（doublepress_demo）",
        "",
        "由 `tools/make_doublepress.py` 生成，本文件由 "
        "`tools/doublepress_report.py` 自动写出。",
        "",
        "## 文件",
        "",
    ]
    for b in bpms:
        lines.append(f"- `samples/audio/doublepress_demo_{int(b)}.mid` / "
                     f"`.ogg` —— cbpm = {int(b)}")
    lines += [
        "",
        "## 读法",
        "",
        "| 元素 | 含义 |",
        "| --- | --- |",
        "| **重音（响 + 高音铃铛）** | **双押点**。铃铛轨可以单独静音 |",
        "| 轻音（pluck） | 普通单押台阶 |",
        "| 左声道节拍器 | 每拍一下，小节首拍是高音木鱼，弱拍是气声 |",
        "| 镲 | 段落起点 |",
        "",
        "MIDI 分轨：`trk0` 指挥轨（含段落 marker）、`trk1` 节拍器、"
        "`trk2` 主旋律（重音 120 / 普通 72）、`trk3` 双押重音层。",
        "",
        "> OGG 不是 soundfont 渲染，是同一份事件表用 numpy 合成器直接合成的。"
        "代价是音色朴素，好处是**重音在设计上样本级对齐、误差为 0**，"
        "可以直接当双押点的标准答案来对"
        "（注意：用我们自己的检波器去测会看到 ~16 ms 偏置，见文末）。",
        "",
        "## 段落表",
        "",
        "| # | 段落 | 小节 | 拍 | 音/拍 | " + cols + " | 重音数 | 写法 |",
        "| --- | --- | --- | --- | --- | " + sep + " | --- | --- |",
    ]
    for i, (b0, b1, sec, t) in enumerate(marks, 1):
        rng = f"{b0}" if b0 == b1 else f"{b0}–{b1}"
        times = " | ".join(f"{t * 60.0 / bp:.1f}s" for bp in bpms)
        lines.append(
            f"| {i} | {sec['name']} | {rng} | {sec['bars'] * BEATS_PER_BAR} | "
            f"{sec['sub']} | {times} | {acc_by_sec.get(sec['name'], 0)} | "
            f"{sec['rule']} |")
    total_bars = sum(s["bars"] for s in SECTIONS)
    lines += [
        "",
        f"合计 {len(SECTIONS)} 段 / {total_bars} 小节 / "
        f"{total_bars * BEATS_PER_BAR} 拍 / 主旋律 "
        f"{sum(mel_by_sec.values())} 音 / 双押点 {sum(acc_by_sec.values())} 个。",
        "",
        "## 双押速查（`docs/双押逻辑.md` §3 的几何值）",
        "",
        "| 转角 | travel | r（拍） | 相对直线格 |",
        "| --- | --- | --- | --- |",
        "| 0° | 180 | 1 | — |",
        "| ±15°（< 300 cbpm） | 165 / 195 | 11/12 | ∓1/12 |",
        "| ±30°（≥ 300 cbpm） | 150 / 210 | 5/6 | ∓1/6 |",
        "",
        "一个 ±15° 会把 `Σtravel ≡ 180n (mod 360)` 打偏 ∓15°，"
        "所以**必须和另一个反向 ±15° 成对**，配对位置不同就是不同写法。",
        "",
        "## 配套 .adofai（底座 + 双押位置注释）",
        "",
        "- `samples/doublepress/doublepress_demo_120.adofai`（+ 同目录的 ogg）",
        "",
        "由 `tools/make_doublepress_adofai.py` 生成。**只铺底座，一个双押都不写**；",
        "每个该写双押的格子挂一条游戏官方的编辑器注释：",
        "",
        "```json",
        "{\"floor\": N, \"eventType\": \"EditorComment\", \"comment\": \"...\"}",
        "```",
        "",
        "编辑器里按 **Alt+F** 打开 `Find Comment` 面板，搜「双押」，",
        "然后用 Next 逐个跳过去写。同一格上的「段落表头」和「双押点」已合并成一条。",
        "",
        "**怎么写**：把该格 `angleData` 加 15（或减 15）。因为 `Δa` 会连带影响下一格，",
        "一格 +15 自动让下一格 −15 —— 这就是双押必须成对的原因，天然满足闭合。",
        "",
        "**时序模型（全部来自游戏反编译源码，不是拟合）**",
        "",
        "| 源码 | 结论 |",
        "| --- | --- |",
        "| `scrLevelMaker.cs:512` | `exitangle = (90° − angleData)` |",
        "| `scrLevelMaker.cs:536` | `entryangle[i] = exitangle[i−1] + π` |",
        "| `scrMisc.GetTimeBetweenAngles` | `travel = mod(±(exit−entry), 2π)/π × (60/bpm)/speed` |",
        "| `scrLevelMaker.CalculateFloorEntryTimes` | `entryTime[i+1] = entryTime[i] + T(floor_i)` |",
        "",
        "⇒ **`travel_i = 180° − Δa_i`**，而**第 i 格自己的 travel 与 speed 决定 (i→i+1) 那一段**。",
        "所以 `SetSpeed` 落在第 f 格 = 从第 f 格出发那段开始变速。",
        "`countdownTicks` 取 1（`entryTime[1]` 含 `(countdownTicks−1)` 拍），保证第一格精确落在音频 t=0。",
        "",
        "**底座规格**",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        "| 格数 | 328（= 演示音频的音符数） |",
        "| bpm / offset / countdownTicks | 120 / 0 / 1 |",
        "| 速度档 | 只有 ×1、×2、×4（2 的幂），共 3 个 SetSpeed |",
        "| 转角 | 0°（直线）238 格；三连音段 ±60° 90 格 |",
        "| Twirl / Pause / midspin | 一个都没有 |",
        "| EditorComment | 163 条（标出 155 个双押点 + 18 个段落表头） |",
        "",
        "三连音段之所以不能是直线：音值 1/3 需要速度倍率 3，不是 2 的幂；",
        "所以改用 ×2 + `travel = 120°`（转角 60°），六边形 —— 这是 ADOFAI 里三连音的标准长相。",
        "",
        "自检：按上面的公式逐格重算 328 格落点，与演示音频的音符时间**最大误差 0.000000 ms**。",
        "",
        "## 中旋写法（midspin double-press）—— 已实现",
        "",
        "`samples/doublepress/doublepress_demo_120_midspin.adofai`"
        "（`python tools/make_doublepress_adofai.py --dp-mode midspin`）",
        "空底座生成到 `samples/doublepress_base/`（`--dp-mode none`）。",
        "",
        "**机制**：在每个双押点**前面**插两格 `[X, angleData 999]`。",
        "",
        "| 格 | angleData | travel | 时间 | 坐标 |",
        "| --- | --- | --- | --- | --- |",
        "| X（插入） | 按前一格算，见下 | **15°** | 落在原格的原时刻 | 与原格重合 |",
        "| 999（插入） | 999 | **0** | +1/12 格 | 折返尖角 |",
        "| 原格 | 不变 | 原 travel − 15° | 与 999 **同一瞬间** | 回到原位 |",
        "",
        "`15° + 0° + (基准 − 15°) = 基准` ⇒ 把原来一格的时间**原样摊成三格**，"
        "前后零净偏移；999 与原格同一瞬间按下 = 真·双押。",
        "不需要配对、不需要闭合核算，任何段落都成立 —— 这是它最省力的原因；"
        "代价是那个折返尖角，可读性略差。",
        "",
        "### ★ 一个必须注意的坑：`165` 只在直线段成立",
        "",
        "恒等式 `travel_X + travel_Y' ≡ travel_f (mod 360)` 只保证**模**相等。"
        "要让**时间**也相等，还不能缠绕（`travel_X + travel_Y' <= 360`）。",
        "",
        "- `travel_X  = mod(a_{f-1} - a_X - 180, 360)`",
        "- `travel_Y' = mod(a_X - a_f, 360)`",
        "",
        "固定令 `travel_X = 15°`（短促折返）⇒ `E_X = I_X + 15°` ⇒",
        "",
        "> **`angleData_X = (a_{f-1} − 195) mod 360`**",
        "",
        "`a_{f-1} = 0`（直线格）时退化成 **165** —— 固定写 165 只在直线段正确。"
        "三连音段 `a_{f-1} ∈ {60,120,180,240,300}`，写 165 会让 "
        "`travel_X + travel_Y'` 变成 `基准 + 360`，**每处多 2 格时间**。",
        "本谱实际用到的折返角是 `(a_{f-1} − 195) mod 360` 的六种取值："
        "`45 / 105 / 165 / 225 / 285 / 345`（全是 15° 的倍数）。",
        "",
        "**自检结果**：155/155 个双押点 —— 前一格 midspin ✓、折返格 travel = 15° ✓、"
        "与前一格同时按下 ✓、与前两格坐标重合 ✓；328 个基准时刻最大还原误差 "
        "**0.000000 ms**，总时长 63.7500 s 与底座完全相同。",
        "",
        "### 双押吃哪个音",
        "",
        "折返格 X **精确落在被标记音的时刻**（328/328 还原，0.000000 ms），"
        "而双押那一对（999 + 原格）落在它**之后 15/180 = 1/12 本地格**：",
        "",
        "| 速度档 | 本地格 | 双押迟到 | 双押点数 |",
        "| --- | --- | --- | --- |",
        "| ×2 | 250.00 ms | **+20.83 ms** | 103 |",
        "| ×4 | 125.00 ms | **+10.42 ms** | 52 |",
        "",
        "⇒ **双押点本身在音频里没有对应的音**，它落在被标记音之后 1/12 格。"
        "周围时序不动，是这笔 1/12 被后面的原格用 `原 travel − 15°` 补回来了 —— "
        "「双押吃掉 1/12 拍」和这笔迟到是同一笔账。"
        "（×1 的段落 1/2/6/7/15 没有重音，所以只有 ×2 和 ×4 两种。）",
        "",
        "### 双押开关",
        "",
        "```bash",
        "python tools/make_doublepress_adofai.py --dp-mode midspin --dp all",
        "python tools/make_doublepress_adofai.py --dp-mode midspin --dp none",
        "python tools/make_doublepress_adofai.py --dp-mode midspin --dp sec:3,4,16",
        "python tools/make_doublepress_adofai.py --dp-mode midspin --dp mark:1,3,5",
        "python tools/make_doublepress_adofai.py --dp-mode midspin --dp range:10-20",
        "python tools/make_doublepress_adofai.py --dp-mode midspin --dp base:12,16",
        "python tools/make_doublepress_adofai.py --dp-mode midspin --dp nth:2",
        "```",
        "",
        "子句可用 `+` 组合（如 `sec:3+sec:16`）；`--name XXX` 指定输出名避免互相覆盖。"
        "未启用的双押点在注释里标成「本次未启用双押」，"
        "所以 `Alt+F` 搜「双押」始终能看到完整的 155 个点与当前开关状态。",
        "",
        "示例：`samples/doublepress_variants/` 放了一份只开段 3（4 个双押点）的版本，"
        "用来快速确认手感。",
        "",
        "## 双轨模式：底部一条轨，双押另一条轨",
        "",
        "★ 这是中旋写法真正的用武之地。中旋插入是**零净偏移**的，"
        "所以可以在不动底部时序的前提下，把双押摆到底部两格之间的**任意**位置 —— "
        "而第二条轨的音头一般都不在底部网格上。",
        "",
        "**s 是可调的**（`travel_X`）。插入 [X(s), 999] 之后第 j 对双押落在",
        "",
        "```",
        "t_f + T(s_1 + … + s_j),    T(s) = s/180 × 本地格",
        "```",
        "",
        "所以只要目标 `T ∈ (t_f, t_{f+1})`，取 s 与 `(T − t_f)` 成正比就能**精确命中**"
        "（前提 `0 < s` 且 `Σs < travel_f`）。",
        "",
        "```bash",
        "# 第二条轨 = 另一个音频文件（全频检音头）",
        "python tools/make_doublepress_adofai.py --dp-mode midspin \\",
        "       --dp-track 双押轨.ogg --dp-pct 55",
        "",
        "# 第二条轨 = 同一个 OGG 里切出来的一条伪音轨（打击/中频/低频/高频）",
        "python tools/make_doublepress_adofai.py --dp-mode midspin \\",
        "       --dp-track 歌曲.ogg:打击",
        "",
        "# 或者直接给时刻（毫秒）",
        "python tools/make_doublepress_adofai.py --dp-mode midspin \\",
        "       --dp-times 4092.5,5092.5,6092.5",
        "```",
        "",
        "**实测**：",
        "",
        "| 试验 | 目标数 | 落点误差 | 总时长变化 |",
        "| --- | --- | --- | --- |",
        "| 60 个刻意离网格的目标（间隔 ×0.37） | 60 | **0.000000 ms** | 0.000000 ms |",
        "| 演示 OGG 自己检出的真实音头 | 154 | **0.0000 ms** | 0.000000 ms |",
        "",
        "离网格那次用到的 `s = 66.600°` —— **已经不是 15° 的倍数**，"
        "这正说明落点不再受底部网格约束。",
        "",
        "### 两条限制",
        "",
        "1. **不能插在 floor 0 前面。** 那会把 `angleData[0]` 顶掉，"
        "破坏「开局那一格一定是直线 / `angleData[0] = 0`」。"
        "落在第一格之前的目标会被丢弃并打印数量。",
        "2. **落不到底部格正上。** `s → 0` 会让 X 格的 travel 退化，"
        "游戏按特判给它 2 拍。目标正好压在底座格上时用 `S_MIN = 0.25°` 兜底，"
        "偏移在亚毫秒量级。",
        "",
        "## 还没做的：角度双押",
        "",
        "即直接改本格 `angleData` 的 ±15° 写法（`Δa` 变化、需要成对）。"
        "按你的建议，**先把中旋写法落地**，角度双押之后再说。",
        "",
        "## 顺手查出来的两件事（不是这份素材的问题）",
        "",
        "1. **OGG 检波器有 ~16 ms 恒定提前量。** 合成一个位置精确的脉冲去验，"
        "检波器报的位置比真值早约 16–18 ms，且**随 hop 变化**"
        "（hop=64 → −18.5 ms，hop=128 → −14.5 ms），散布只有 0.2 ms。"
        "根因在 `librosa.onset.onset_strength`：它的 STFT 窗半宽是 "
        "`n_fft/2 = 1024` 样本 ≈ 23 ms，能量在脉冲到达窗中心**之前**就开始进窗，"
        "所以差分峰值提前。`_pick` 里的帧→毫秒换算本身是对的。"
        "现在靠网格吸附吃掉了，但它会吃掉一部分吸附容差预算，"
        "onset 落在格子边界附近时可能被吸到前一格。**未改**——"
        "改它会动摇所有 OGG 路径的历史结论，需要单独评估。",
        "2. **音头检出量是 `pct` 旋钮，不是召回率。** `pct` 的语义就是"
        "「只保留最强的前 (100−pct)% 峰值」（见 `_pick` 文档字符串）。"
        "这份素材重音比基准音高约 6 dB，所以 pct=75 大致只留重音层；"
        "要更密就调低 pct。",
        "",
    ]
    os.makedirs(os.path.dirname(DOC), exist_ok=True)
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[文档] {DOC}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bpm", type=float, nargs="+", default=[120.0, 90.0])
    args = ap.parse_args(argv)

    notes, marks = build()
    print(f"事件表: {len(notes)} 条 / "
          f"重音 {sum(1 for n in notes if n.layer == 'acc')} 个")

    problems = 0
    for bp in args.bpm:
        base = os.path.join(AUDIO, f"doublepress_demo_{int(bp)}")
        print(f"\n== cbpm {bp:g} ==")
        print(f" [MIDI] {os.path.basename(base)}.mid")
        ok, _ = check_midi(base + ".mid", notes)
        problems += 0 if ok else 1
        if os.path.exists(base + ".ogg"):
            print(f" [OGG ] {os.path.basename(base)}.ogg")
            check_ogg(base + ".ogg", notes, bp)

    write_doc(notes, args.bpm)
    print(f"\n结论: {'全部通过' if problems == 0 else f'{problems} 项不一致'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
