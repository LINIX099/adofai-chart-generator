# -*- coding: utf-8 -*-
"""把一份 .adofai 逐格算开：角度 / 转角 / travel / 拍 / 毫秒 / 累计 / Twirl，
并画出轨迹（ASCII），再看 `OOX` 换手押判据在它身上认得几组。

    python tools/read_adofai.py [路径]     # 默认读测试夹具那份换手押样例

时间口径（两边一致，见 `vendor/Re_ADOJAS` 的 levelLoaderWorker.ts:130-135
与 `core/path.py:67`）：
    travel   = 180 − |ΔangleData|        # 180 = 直线 = 1 拍
    duration = travel/180 × 60000/bpm
几何：angleData[i] = 第 i 格的行进方向（0 = 上，顺时针为正）。

★ 这是 `docs/59` 那一轮为了「读用户样例」写的工具，**留着重用**：
  以后再来一份「看看它像什么」的谱面，直接跑它，别再临时造脚本。
输出同时写 out/_read_adofai.txt。
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

PATH = (sys.argv[1] if len(sys.argv) > 1 else
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tests", "fixtures", "colorize", "handswitch_sample.adofai"))


def main() -> int:
    with open(PATH, "r", encoding="utf-8-sig") as f:
        j = json.load(f)
    ad = [float(v) for v in j["angleData"]]
    st = j["settings"]
    acts = [a for a in (j.get("actions") or []) if isinstance(a, dict)]

    base_bpm = float(st.get("bpm") or 100)
    twirls = {int(a["floor"]) for a in acts if a.get("eventType") == "Twirl"}
    speeds = {int(a["floor"]): a for a in acts if a.get("eventType") == "SetSpeed"}

    # 逐格：bpm / travel / 拍 / ms / Twirl / 位置
    bpm = base_bpm
    tiles = []
    pos = (0.0, 0.0)
    t_ms = 0.0
    for i, a in enumerate(ad):
        if i in speeds:
            e = speeds[i]
            if e.get("speedType") == "Multiplier":
                bpm = bpm * float(e.get("bpmMultiplier") or 1)
            else:
                bpm = float(e.get("beatsPerMinute") or bpm)
        if i == 0:
            travel, turn = 180.0, None          # 第 0 格：开局站位，恒为直线
        else:
            turn = (a - ad[i - 1] + 540.0) % 360.0 - 180.0
            travel = 180.0 - abs(turn)
        beats = travel / 180.0
        ms = beats * 60000.0 / bpm
        t_ms += ms
        tw = i in twirls
        tiles.append(dict(i=i, ang=a, turn=turn, travel=travel, beats=beats, ms=ms,
                          t=t_ms, tw=tw, bpm=bpm, pos=pos))
        th = math.radians(a)
        pos = (pos[0] + math.sin(th), pos[1] + math.cos(th))

    os.makedirs("out", exist_ok=True)
    log = os.path.join("out", "_read_adofai.txt")
    with open(log, "w", encoding="utf-8") as out:
        print(f"=== {os.path.basename(PATH)} ===", file=out)
        print(f"格数={len(ad)}  bpm={base_bpm}  SetSpeed={speeds and '有'}"
              f"  Twirl={len(twirls)}  总时长={t_ms:.1f}ms", file=out)
        print("\n i  角度    Δ角    travel   拍     ms     累计ms  Twirl  bpm", file=out)
        for d in tiles:
            tn = "  .  " if d["turn"] is None else f"{d['turn']:+6.1f}"
            print(f"{d['i']:>3} {d['ang']:>6.0f} {tn} {d['travel']:>7.1f} "
                  f"{d['beats']:>6.3f} {d['ms']:>7.2f} {d['t']:>9.1f}   "
                  f"{'*TW*' if d['tw'] else '    '} {d['bpm']:>6.0f}", file=out)

        # 节奏汇总：把“直线 / 急转”按 travel 归类
        print("\n-- travel 分布 --", file=out)
        cnt = {}
        for d in tiles:
            cnt[round(d["travel"], 3)] = cnt.get(round(d["travel"], 3), 0) + 1
        for k in sorted(cnt):
            ms = k / 180.0 * 60000.0 / (tiles[-1]["bpm"])
            print(f"   travel={k:>6.1f}°  耗时={ms:>6.2f}ms  共 {cnt[k]} 格", file=out)

        # ---- ★★ 几何体检：一眼看出「这是一条路」还是「一把碎渣」----
        #   用户 2026-10 拿编辑器截图问「为什么碎成这样了」⇒ 这个体检就是回答它的尺子。
        #   判据（都是**相对**量，可跨谱比较）：
        #     · 直线率   = travel==180 的比例
        #     · 发卡弯   = travel<60 或 >300 的比例（`core.fitdirect` 同一口径）
        #     · 平均|Δ角| = 每格方向变化的平均绝对值（越小越"像一条路"）
        #     · 回折率   = |Δ角| ≥ 135 的比例（原地往回走）
        #     · 重叠格   = 非相邻格落在 0.35 格以内的对数（碎渣会**成片**重叠）
        #     · 紧凑度   = 路径长 / bbox 对角线（>2 是"一条路"，≈1 是"摊成一团"）
        import collections as _c
        n = len(tiles)
        dv = [tiles[i]["turn"] for i in range(1, n) if tiles[i]["turn"] is not None]
        n_straight = sum(1 for d in tiles if abs(d["travel"] - 180.0) < 1e-6)
        n_hairpin = sum(1 for d in tiles if d["travel"] < 60.0 or d["travel"] > 300.0)
        n_fold = sum(1 for a in dv if abs(a) >= 135.0)
        pos = [d["pos"] for d in tiles]
        xs = [p[0] for p in pos]
        ys = [p[1] for p in pos]
        diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        # 重叠：只在 ±48 格窗口内两两比（够用，且 O(n·48)）
        ov = 0
        for i in range(n):
            for j in range(i + 2, min(n, i + 49)):
                if math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]) < 0.35:
                    ov += 1
        print("\n-- ★ 几何体检 --", file=out)
        print(f"   直线率     {n_straight / n:.1%}（{n_straight}/{n} 格）", file=out)
        print(f"   发卡弯     {n_hairpin / n:.1%}（{n_hairpin} 格，travel<60 或 >300）", file=out)
        print(f"   平均|Δ角|  {sum(abs(a) for a in dv) / max(1, len(dv)):.1f}°", file=out)
        print(f"   回折率     {n_fold / max(1, len(dv)):.1%}（|Δ角|≥135°，{n_fold} 格）", file=out)
        print(f"   重叠格     {ov} 对（非相邻、0.35 格内；碎渣会成片重叠）", file=out)
        print(f"   节奏分布   ", file=out)
        _rate = _c.Counter(round(d["ms"]) for d in tiles)
        print(f"      {_rate.most_common(8)}", file=out)
        print(f"   bbox       {max(xs) - min(xs):.1f} × {max(ys) - min(ys):.1f} 格"
              f"（对角线 {diag:.1f}）", file=out)
        print(f"   紧凑度     {n / diag:.2f} 格/单位（>2 ≈ 一条路；≈1 ≈ 摊成一团）", file=out)

        # 每 4 格一组的“换手”位置
        print("\n-- Twirl（换手）落在哪一类格子上 --", file=out)
        for d in tiles:
            if d["tw"]:
                print(f"   floor={d['i']:<3} 角度={d['ang']:>6.0f}  "
                      f"Δ角={d['turn']:+6.1f}  travel={d['travel']:>6.1f}°  "
                      f"耗时={d['ms']:.2f}ms", file=out)

        # ---- ASCII 画轨迹（前 24 格 + 全图）----
        def plot(n: int, title: str) -> None:
            pts = [d["pos"] for d in tiles[:n + 1]]
            if not pts:
                return
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            W, H = 92, 26
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            if x1 - x0 < 1e-9:
                x1 = x0 + 1
            if y1 - y0 < 1e-9:
                y1 = y0 + 1
            g = [[" "] * W for _ in range(H)]
            for k, (px, py) in enumerate(pts):
                cx = int(round((px - x0) / (x1 - x0) * (W - 1)))
                cy = int(round((y1 - py) / (y1 - y0) * (H - 1)))
                ch = "." if k == 0 else ("#" if k % 8 == 0 else "+")
                if k > 0 and tiles[k - 1]["tw"]:
                    ch = "T"
                if ch == "." and g[cy][cx] != " ":
                    ch = g[cy][cx]
                g[cy][cx] = ch
            print(f"\n-- 轨迹图：{title}（+ = 每格交点，# = 每 8 格，T = 上一格带 Twirl）--",
                  file=out)
            for row in g:
                print("   |" + "".join(row) + "|", file=out)

        plot(20, "前 20 格")
        plot(len(ad) - 1, f"全图（{len(ad)} 格）")
    with open(log, "r", encoding="utf-8") as f:
        sys.stdout.write(f.read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
