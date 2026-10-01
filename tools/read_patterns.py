"""反解 patterns/*.adofai —— 手改过的文件读回来。

输出每段：编号 / 乐理名 / travel 序列 / Twirl 位置 / 转角 / 位置 / 是否闭合。

几何：
  相邻两格恒距 1 格；gap 从 floor f 开始时用第 f-1 个 miner travel
  Twirl 落在 floor f → 翻转从 floor f 出发的那一格（后续持续到下一个 Twirl）
  turn = ±(travel - 180)，反向时取负
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATS = os.path.join(ROOT, "patterns")

# 用户定：以新文档为准，旧文档只做参考。这些不进模板库。
REFERENCE = {"F_三连家族_待定.adofai"}


def load_lenient(path):
    txt = open(path, encoding="utf-8-sig").read()
    txt = re.sub(r",(\s*[}\]])", r"\1", txt)
    return json.loads(txt, strict=False)


def miner_travels(a):
    return [((180.0 + a[i] - a[i + 1]) % 360.0) for i in range(len(a) - 1)]


def tile_offsets(actions, n):
    """PositionTrack → 每格的累计位置偏移。

    justThisTile=True  → 只动这一格
    justThisTile=False → 从这一格起，后面全部平移（会累加）
    """
    per, persist = {}, []
    for e in actions:
        if e.get("eventType") != "PositionTrack":
            continue
        f = int(e["floor"])
        off = e.get("positionOffset") or [0.0, 0.0]
        if e.get("justThisTile"):
            dx, dy = per.get(f, (0.0, 0.0))
            per[f] = (dx + off[0], dy + off[1])
        else:
            persist.append((f, off[0], off[1]))
    acc = [0.0] * (n + 1)
    for k in range(n + 1):
        dx = dy = 0.0
        for f, ox, oy in persist:
            if f <= k:
                dx += ox
                dy += oy
        acc[k] = (dx, dy)
    return per, acc


def bpm_series(actions, n, base: float):
    """每格的有效 BPM（settings.bpm × SetSpeed）。SetSpeed 有 Bpm / Multiplier 两种写法。"""
    ev = {}
    for e in actions:
        if e.get("eventType") != "SetSpeed":
            continue
        f = int(e["floor"])
        m = e.get("bpmMultiplier", None)
        m = float(m) if m is not None else float(e.get("speed", 1.0) or 1.0)
        bpm = float(e.get("beatsPerMinute") or base) if e.get("speedType") == "Bpm" else base
        ev[f] = bpm * m
    out, cur = [base] * (n + 1), base
    for i in range(n + 1):
        if i in ev:
            cur = ev[i]
        out[i] = cur
    return out


def ms_of(travels, bpm_list, floor0):
    """travel(度) → 毫秒。第 k 个 travel 从 floor0+k 出发。"""
    return [abs(t) / 180.0 * 60000.0 / (bpm_list[floor0 + k] or 120.0)
            for k, t in enumerate(travels)]


def read_file(path):
    d = load_lenient(path)
    a = [float(x) for x in d.get("angleData") or []]
    acts = d.get("actions") or []
    twirls = set(int(e["floor"]) for e in acts if e.get("eventType") == "Twirl")
    speeds = set(int(e["floor"]) for e in acts if e.get("eventType") == "SetSpeed")
    comments = [(int(e["floor"]), str(e.get("comment", "")).replace("\n", " ⏎ "))
                for e in acts if e.get("eventType") == "EditorComment"]
    comments.sort()

    tv = miner_travels(a)
    segs = []
    for k, (floor, text) in enumerate(comments):
        end = comments[k + 1][0] if k + 1 < len(comments) else len(tv) + 1
        gap = tv[floor - 1: end - 1]           # 该段覆盖的 travel
        segs.append((floor, text, gap))
    per, acc = tile_offsets(acts, len(a))
    pt = [(int(e["floor"]), (e.get("positionOffset") or [0.0, 0.0])[0],
           (e.get("positionOffset") or [0.0, 0.0])[1], bool(e.get("justThisTile")))
          for e in acts if e.get("eventType") == "PositionTrack"]
    bpms = bpm_series(acts, len(a), float(d.get("settings", {}).get("bpm") or 120.0))
    return dict(path=path, bpm=d.get("settings", {}).get("bpm"),
                twirls=twirls, speeds=speeds, n=len(a), segs=segs,
                per=per, acc=acc, pt=pt, bpms=bpms)


def split_sep(gap):
    """段尾若是 180° 直线，才算分隔格；否则整段都是图形本体。

    用户的写法：图形 3 个 travel（和 = 180° = 一拍），第 3 个是 30/60/45 这种，
    不是 180，所以不能被吃掉。
    """
    if len(gap) > 1 and abs(gap[-1] - 180.0) < 1e-6:
        return gap[:-1], gap[-1]
    return gap, None


def geom(travels, twirl_offsets):
    """twirl_offsets: 该段内第几个 gap 起被翻转（相对段首的 0-based 下标集合）。"""
    p = [(0.0, 0.0)]
    h = 90.0
    flip = False
    turns = []
    for k, t in enumerate(travels):
        if k in twirl_offsets:
            flip = not flip
        turn = (t - 180.0) * (-1.0 if flip else 1.0)
        turns.append(turn)
        p.append((p[-1][0] + math.cos(math.radians(h)),
                  p[-1][1] + math.sin(math.radians(h))))
        h += turn
    closed = abs(p[-1][0]) < 1e-6 and abs(p[-1][1]) < 1e-6
    return turns, p, closed


# 用户口径：隔得特别长 → 第一格需要旋转事件；反之不需要。
# 阈值用用户之前自己用过的 150 ms（写法三「只适用高速」那条）。
TWIRL_THRESH_MS = float(os.environ.get("TWIRL_THRESH_MS", "150"))


def speed_tags(ms):
    """把一段的 ms 标成 快/中/慢 —— 用来核对「前16后8」这类名字。

    前16后8 (`45·45·90`) 应该是 150/150/300 = 快快慢
    前8后16 (`90·45·45`) 应该是 300/150/150 = 慢快快
    """
    if not ms:
        return ""
    avg = sum(ms) / len(ms)
    out = []
    for m in ms:
        if m > avg * 1.05:
            out.append("慢")
        elif m < avg * 0.95:
            out.append("快")
        else:
            out.append("中")
    return "".join(out)


def report(path):
    r = read_file(path)
    print("=" * 92)
    ref = os.path.basename(path) in REFERENCE
    print(f"{os.path.basename(path)}   bpm={r['bpm']}   angleData {r['n']} 格"
          + ("   【仅参考 · 不进模板库】" if ref else "   【权威】"))
    for floor, text, gap in r["segs"]:
        head = text.split("⏎")[0].strip()
        body, sep = split_sep(gap)
        offs = {i for i in range(len(body)) if (floor + i) in r["twirls"]}
        extra = [f for f in sorted(r["twirls"]) if floor <= f < floor + len(gap)]
        turns, p, closed = geom(body, offs)
        print(f"\n  floor {floor:>4}  {head}")
        print(f"     travel : " + " · ".join(f"{x:.4g}°" for x in body)
              + (f"   [段尾分隔 {sep:.4g}°]" if sep is not None else ""))
        if body:
            ms = ms_of(body, r["bpms"], floor)
            print(f"     毫秒   : " + " ".join(f"{m:>7.1f}" for m in ms)
                  + f"    合计 {sum(ms):>8.1f} ms")
            print(f"     快慢   : " + "".join(f"{c:>7}" for c in speed_tags(ms)))
            # Twirl 会把 travel 翻成 360-θ，时值跟着变。
            # θ > 180° 说明这一格取的是「慢的那一支」，翻过来就快了。
            flips = [360.0 - t for t in body]
            ms_f = ms_of(flips, r["bpms"], floor)
            cells = []
            for t, m, ft, fm in zip(body, ms, flips, ms_f):
                mark = "★可翻快" if (t > 180.5 and ft < 179.5) else ""
                cells.append(f"{t:.4g}°/{m:.0f}ms→{ft:.4g}°/{fm:.0f}ms{mark}")
            print(f"     取反后 : " + "   ".join(cells))
        print(f"     Twirl  : " + (", ".join(f"floor {f}" for f in extra) or "无"))
        if body:
            print(f"     转角   : " + " ".join(f"{t:+7.1f}" for t in turns)
                  + f"   合计 {sum(turns):+.1f}°")
            print(f"     位置   : " + " ".join(f"({x:+.2f},{y:+.2f})" for x, y in p)
                  + ("   ★闭合" if closed else ""))
        # 位置轨道微调（floor 到 floor+len(gap) 之间）
        moved = [f for f, _, _, _ in r["pt"] if floor <= f <= floor + len(gap)]
        if moved:
            print("     PositionTrack：")
            for f in moved:
                ent = next((e for e in r["pt"] if e[0] == f), None)
                dx, dy = (ent[1], ent[2]) if ent else (0.0, 0.0)
                just = ent[3] if ent else False
                ax, ay = r["acc"][f]
                base = p[f - floor] if f - floor < len(p) else None
                tip = "单格" if just else "整轨"
                mark = ""
                if just or abs(dx - round(dx)) > 1e-9 or abs(dy - round(dy)) > 1e-9:
                    mark = "  ← 手改"
                print(f"        floor {f:>3}  {tip}  本格 +({dx:+.2f},{dy:+.2f})"
                      f"  累计 +({ax:+.2f},{ay:+.2f})"
                      + (f"   基准 ({base[0]:+.2f},{base[1]:+.2f})" if base else "")
                      + mark)
        if floor in r["speeds"]:
            print("     ⚠ 本段有 SetSpeed")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        files = [os.path.join(PATS, f) for f in args]
    else:
        files = [os.path.join(PATS, f) for f in sorted(os.listdir(PATS))
                 if f.endswith(".adofai")
                 and not f.lower().startswith("backup")]      # 编辑器自动备份，忽略
    for p in files:
        report(p)
