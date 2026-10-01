# -*- coding: utf-8 -*-
"""**按键时刻对齐率** —— 参考谱 ↔ 生成谱（或 MIDI）的时间对齐尺子。

    python tools\\align_chart_midi.py <参考谱.adofai> <另一边> [--tol 30] [--pitch-lo N]
                                     [--pitch-hi N] [--track N] [--search-offset]

`<另一边>` 可以是 `.adofai`（比生成谱）或 `.mid`（比 MIDI）。

## 这个工具为什么存在

用户 2026-10：

> 「下一环中，我们要基于我下一个提供的 midi，尝试从 midi 用求解器**还原一个已有的
>   adofai 谱面**。并不需要完全一致，**60~80% 一致**即可」
> 「（判据）**按键时刻对齐率**」

## 三个读数（都打出来，不藏）

| 读数 | 定义 | 用途 |
|---|---|---|
| **覆盖（召回）** | 参考的每次按键，在容差内有没有对应的另一边按键 | ★ 主读数 |
| **命中（精确）** | 另一边的每次按键，在容差内有没有对应的参考按键 | 防止"堆一堆音上去"刷分 |
| **一对一匹配率** | 双向最小匹配后的匹配数 ÷ max(两边条数) | 最严格；两边条数差很大时最能说明问题 |

★ 主读数用**一对一双向匹配率**还是**覆盖**？两个都打，**以一对一为准**，
因为「60~80% 一致」说的是**同一张谱**，不是"我的每个音都能在参考里找到"。

## 容差

`--tol` 默认 **30 ms**。本项目里「同一拍」的判定口径是 `docs/57` 的拟合容差；
30 ms 在 230 BPM（一拍 260.9 ms）下约 **1/8.7 拍**，是"听起来同一时刻"的量级。
**换容差数字会大变**（实测 ±5 ms → 51.6%，±80 ms → 94.1%），所以判据必须钉住容差。
"""
import argparse
import bisect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # noqa: BLE001
    pass

import analyze_camera_cur as ACC                              # noqa: E402
from core import midi as M                                    # noqa: E402


# ============================================================ 取时刻
def chart_key_times(path: str, with_offset: bool = False) -> list[float]:
    """谱面每次**按键**的时刻（ms）。

    = 每一格的**到达时刻** `T[f]`；`with_offset=True` 时再加上 `settings.offset`。
    `angleData == 999`（中旋）没有按键，跳过。

    ★★ **`offset` 要不要加，取决于"另一边"是什么**（实测踩过，别想当然）：

    | 比什么 | 加不加 `offset` | 实测（Flower Rocket） |
    |---|---|---|
    | **谱面 ↔ 谱面** | **不加** | 不加：一对一 **60.4%**、中位频差 **0.0 ms**<br>加了：53.2%，而且要再补 +110 ms |
    | 谱面 ↔ 外部 MIDI | 视情况 | 这份 MIDI 的时间轴**与关卡本地轴一致**（不加就 0.0 ms 吻合） |

    加了 `offset` 会出现**容差悬崖**（±20 ms ⇒ 6.4%，±30 ms ⇒ 65.6%）——
    看到悬崖就是有固定系统偏移，先怀疑 `offset` 该不该加。

    ★ 时间模型用的是本项目唯一真源（`core/path.py` + `SetSpeed` 分段），
      与 `tools/chart_digest.py` 同一套。
    """
    a = ACC.load_angle(path)
    off = float(a.settings.get("offset") or 0.0) if with_offset else 0.0
    ms = ACC.floor_ms(a)
    a.getRotateAngle()
    ang = list(a.originRotateAngleList)
    out: list[float] = []
    t = off
    for i, m in enumerate(ms):
        t += float(m)
        if i < len(ang) and round(float(ang[i])) == 999:
            continue                                          # 中旋格不按键
        out.append(t)
    return out


def midi_key_times(path: str, track: int | None = None,
                   pitch_lo: int | None = None,
                   pitch_hi: int | None = None) -> list[float]:
    mf = M.load(path)
    out: list[float] = []
    for tr in mf.tracks:
        if track is not None and tr.index != track:
            continue
        for n in tr.notes:
            if pitch_lo is not None and n.pitch < pitch_lo:
                continue
            if pitch_hi is not None and n.pitch > pitch_hi:
                continue
            out.append(float(n.t_on_ms))
    return sorted(out)


def anchor(seq: list[float]) -> list[float]:
    """把序列平移到「第一个按键 = 0」。

    ★★ **为什么必须有这一步**（2026-10 实测踩到，读数会差 15 个百分点）：

    `chart_key_times` 给的是**谱面本地轴**（第 0 层是开局站位，parser 把它的角行程
    置 0 ⇒ 第一个按键落在 0 ms）；而 `midi_key_times` 给的是 **MIDI 的绝对轴**
    （Flower Rocket 的第一个音头在 **913.0 ms**）。两条轴差着一个「首音时刻」。

    后果：拿 `got`（本地轴 0 起）去比 MIDI 的绝对轴，等于凭空加了 913 ms 的整体
    平移 ⇒ ② 只能搜到一个假的局部最优（实测 **84.3% @ +106 ms**），
    而真正对齐后是 **99.9%**。

    ★ 更阴的一点：913.0 ms 恰好是 130.43 ms（460 BPM 的砖长）的**整数倍**
    （913.04 = 7 × 130.435），所以两条轴**在粗网格上仍然对得齐** ——
    偏移曲线看起来「到处都还行」，不会出现明显的悬崖把自己暴露出来。**别靠悬崖判断。**

    ★ 谱面 ↔ 谱面时**两边本来就都是本地轴**（都以自己的第一个按键为 0），
    所以那一侧不需要也不应该再动 —— 见 `chart_key_times` 的说明。
    """
    return [x - seq[0] for x in seq] if seq else []


# ============================================================ 三个读数
def coverage(ref: list[float], got: list[float], tol: float) -> tuple[int, list[float]]:
    """参考的每个时刻，在 `got` 里 ±tol 内有没有东西。返回 (命中数, 逐点最小距离)。"""
    n = 0
    dists: list[float] = []
    for x in ref:
        i = bisect.bisect_left(got, x - tol)
        if i < len(got) and got[i] <= x + tol:
            n += 1
        j = bisect.bisect_left(got, x)
        cand = [got[k] for k in (j - 1, j) if 0 <= k < len(got)]
        dists.append(min(abs(x - y) for y in cand) if cand else float("inf"))
    return n, dists


def one_to_one(ref: list[float], got: list[float], tol: float) -> int:
    """双向**一对一**匹配（两边各自按时间顺序贪心配对，一个只能配一次）。"""
    used = [False] * len(got)
    n = 0
    j0 = 0
    for x in ref:
        j = max(j0, bisect.bisect_left(got, x - tol))
        while j < len(got) and got[j] <= x + tol:
            if not used[j]:
                used[j] = True
                n += 1
                j0 = j
                break
            j += 1
    return n


def best_offset(ref: list[float], got: list[float], tol: float,
                span: float = 120.0, step: float = 1.0) -> tuple[float, int]:
    """在 ±span ms 里找让「一对一双向匹配率」最高的整体偏移。"""
    best = (0.0, -1)
    k = int(span / step)
    for i in range(-k, k + 1):
        off = i * step
        n = one_to_one(ref, [x + off for x in got], tol)
        if n > best[1]:
            best = (off, n)
    return best


def report(ref: list[float], got: list[float], tol: float, tag: str,
           off: float = 0.0) -> dict:
    g = [x + off for x in got]
    cov, dists = coverage(ref, g, tol)
    prec, _ = coverage(g, ref, tol)
    o2o = one_to_one(ref, g, tol)
    d = sorted(x for x in dists if x != float("inf"))
    print("  %-22s 参考 %-5d 实得 %-5d | 覆盖 %5.1f%% | 命中 %5.1f%% | "
          "★一对一 %5.1f%% | 中位频差 %s"
          % (tag, len(ref), len(g),
             100.0 * cov / max(1, len(ref)), 100.0 * prec / max(1, len(g)),
             100.0 * o2o / max(1, max(len(ref), len(g))),
             ("%.1f ms" % d[len(d) // 2]) if d else "-"))
    return {"n_ref": len(ref), "n_got": len(g), "tol": tol, "offset": off,
            "coverage": cov / max(1, len(ref)),
            "precision": prec / max(1, len(g)),
            "one_to_one": o2o / max(1, max(len(ref), len(g))),
            "median_dist": (d[len(d) // 2] if d else None)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按键时刻对齐率")
    ap.add_argument("ref", help="参考谱 .adofai")
    ap.add_argument("got", help="要比的东西：.adofai 或 .mid")
    ap.add_argument("--tol", type=float, default=30.0, help="容差 ms（默认 30）")
    ap.add_argument("--track", type=int, default=None, help="只取这一条 MIDI 轨")
    ap.add_argument("--pitch-lo", type=int, default=None)
    ap.add_argument("--pitch-hi", type=int, default=None)
    ap.add_argument("--search-offset", action="store_true",
                    help="先搜一遍整体最优偏移（±120 ms）")
    ap.add_argument("--chart-offset", action="store_true",
                    help="比对谱面时把 settings.offset 加进去（默认**不加**，见函数注释）")
    ap.add_argument("--midi-absolute", action="store_true",
                    help="★ 不要把 MIDI 锚到首音（默认**锚**；见 anchor()：不锚会凭空多一个"
                         "首音时刻的整体平移，② 会假掉十几个百分点）")
    ap.add_argument("--accept", action="store_true",
                    help="★ 按用户 2026-10 的两条门槛判达标：谱面↔谱面 80%% / 能对上 MIDI 95%%")
    ap.add_argument("--midi", default=None,
                    help="第二条门槛要比的 MIDI（不给就跳过 ②）")
    args = ap.parse_args(argv)

    ref = chart_key_times(args.ref, args.chart_offset)
    print("=" * 100)
    print("按键时刻对齐率 · 容差 ±%g ms" % args.tol)
    print("  参考谱：%s" % os.path.basename(args.ref))
    print("          按键 %d 个 · 首 %.1f / 末 %.1f ms" % (len(ref), ref[0], ref[-1]))

    got_path = args.got
    is_midi = got_path.lower().endswith((".mid", ".midi"))
    if is_midi:
        got_raw = midi_key_times(got_path, args.track, args.pitch_lo, args.pitch_hi)
        if args.midi_absolute:
            got = got_raw
            print("  另一边：MIDI %s（%d 个音头%s）★ 未锚定（--midi-absolute）"
                  % (os.path.basename(got_path), len(got),
                     "" if args.track is None else "，只取 tr%d" % args.track))
        else:
            got = anchor(got_raw)
            print("  另一边：MIDI %s（%d 个音头%s）"
                  % (os.path.basename(got_path), len(got),
                     "" if args.track is None else "，只取 tr%d" % args.track))
            print("          ★ 已锚到首音：绝对轴首音 %.2f ms ⇒ 整体 −%.2f ms"
                  "（谱面走的是本地轴，不锚就是拿两条不同的轴硬比）"
                  % (got_raw[0] if got_raw else 0.0, got_raw[0] if got_raw else 0.0))
    else:
        got = chart_key_times(got_path, args.chart_offset)
        print("  另一边：谱面 %s（%d 次按键）"
              % (os.path.basename(got_path), len(got)))
    print()

    off = 0.0
    if args.search_offset:
        best_off, best_n = best_offset(ref, got, args.tol)
        off = best_off
        print("  搜索最优整体偏移：%+g ms（一对一 %d → %.1f%%）"
              % (off, best_n, 100.0 * best_n / max(1, max(len(ref), len(got)))))
        print()

    # ★ 修过一个标签 bug：这一行原来把「偏移 0」的**数值**贴上了「偏移 ±N ms」的**标签**
    r = report(ref, got, args.tol, "偏移 0", 0.0)
    if off:
        report(ref, got, args.tol, "偏移 %+g ms" % off, off)

    # 容差敏感度（判据必须钉住容差，所以把它摊开）
    print()
    print("  容差敏感度（同一对，只改容差）：")
    for t in (5, 10, 20, 30, 50, 80):
        cov, _ = coverage(ref, [x + off for x in got], t)
        o2o = one_to_one(ref, [x + off for x in got], t)
        print("    ±%3g ms ⇒ 覆盖 %5.1f%% · 一对一 %5.1f%%"
              % (t, 100.0 * cov / max(1, len(ref)),
                 100.0 * o2o / max(1, max(len(ref), len(got)))))
    print()
    print("  ★ 对齐率 = %s" % ("**一对一 %.1f%%**"
                              % (100.0 * r["one_to_one"])))

    # ---------------------------------------------------------------- ★★ 验收口径
    if args.accept:
        print()
        print("=" * 100)
        print("验收（用户 2026-10 定的两条门槛）")
        print("  ① **谱面 ↔ 谱面 = 80%**        → 一对一")
        print("  ② **能对上 MIDI 的音 = 95%**   → 生成谱的每次按键里有 MIDI 音头的比例")
        print("-" * 100)
        # ① 谱面 ↔ 谱面（关卡本地轴，不加 offset）
        n1 = max(len(ref), len(got))
        ok1 = r["one_to_one"] >= 0.80
        print("  ① 谱面↔谱面  一对一第 %5.1f%% / 80%%   %s   （参考 %d · 生成 %d ⇒ 一对一"
              "**上限** %.1f%%）"
              % (100.0 * r["one_to_one"], "✅ 达标" if ok1 else "❌ 未达",
                 len(ref), len(got),
                 100.0 * min(len(ref), len(got)) / n1))
        # ② 生成谱 → MIDI
        if args.midi:
            mt_raw = midi_key_times(args.midi)
            # ★★ 锚到首音再比（见 `anchor()`）—— 两条轴不锚就是错的，
            #   实测锚定前 84.3%、锚定后 99.9%。
            mt = mt_raw if args.midi_absolute else anchor(mt_raw)
            print("  ② 的 MIDI：%d 个音头 · 首音 %.2f ms%s"
                  % (len(mt_raw), mt_raw[0] if mt_raw else 0.0,
                     "（★ 未锚定）" if args.midi_absolute else
                     "（已锚定 ⇒ 整体 −%.2f ms）" % (mt_raw[0] if mt_raw else 0.0)))
            # ★★ 判据钉在**真对齐**上（锚定后 = 0 ms），**不拿搜出来的偏移判达标**。
            #   为什么：搜索会为了凑覆盖把边界情况「削」进容差里。实测踩到过 ——
            #   补格产物有一批键正好落在「离最近音头 32.571 ms」上（> 30 ms 容差），
            #   而按覆盖搜出 **+3 ms** 之后 |32.571−3| = 29.571 ≤ 30 ⇒ 全部算「对上了」，
            #   ② 直接虚报成 **100.0%**（真值 75.5%）。搜出来的偏移只**报出来**，不参与判。
            mo, mx = 0.0, -1
            for _i in range(-60, 61, 1):
                _o = _i * 1.0
                _c, _ = coverage(got, [x + _o for x in mt], args.tol)
                if _c > mx:
                    mo, mx = _o, _c
            cov2, _ = coverage(got, mt, args.tol)          # ★ 偏移 0 = 判据
            p2 = 100.0 * cov2 / max(1, len(got))
            ok2 = p2 >= 95.0
            extra = ""
            if mo and mx > cov2:
                extra = ("　★ 但按覆盖能搜到 %+g ms ⇒ %.1f%% —— **只报不判**"
                         "（搜出来的偏移会把边界情况削进容差）"
                         % (mo, 100.0 * mx / max(1, len(got))))
            print("  ② 能对上 MIDI  %5.1f%% / 95%%       %s   （生成谱按键 %d · **偏移 0**）%s"
                  % (p2, "✅ 达标" if ok2 else "❌ 未达", len(got), extra))
        else:
            print("  ② 能对上 MIDI  —— 没给 `--midi` ⇒ 跳过")
        print("-" * 100)
        if ok1 and (not args.midi or ok2):
            print("  ⇒ 全部达标")
        else:
            print("  ⇒ 还差的：%s"
                  % "、".join([x for x, k in (("① 谱面↔谱面", ok1),
                                              ("② 能对上 MIDI",
                                               ok2 if args.midi else True)) if not k]))
        print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
