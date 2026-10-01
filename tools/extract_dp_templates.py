# -*- coding: utf-8 -*-
"""从**主人改过的**验收谱里抽出双押配置模板（`patterns/templates_dp.json`）。

    python tools\\extract_dp_templates.py [谱面.adofai]

默认读 `out/双押配置验收谱/user_edited.adofai`（用户 2026-10 改完并确认
「**这个排版是正确的，时值没动**」的那一版）。

## 抽什么

按 `EditorComment` 切段，每段抽成一条模板：

```
记谱      X/O 串（1 字符 = 1 格 = 60ms；X = [θ, 180−θ]，O = [180]）
travel    逐格**有效** travel（奇偶还原后，见 core/path.py）
twirl     逐格是否要翻奇偶
ge        这段占几格
```

★ **段首段尾的平格留白**（主人加的）**单独报出来**，不静默丢 ——
它是「段与段之间的分隔」，不是配置本体。

## 两条不变量（写进模板，也当场核）

```
① 每个双押 Σtravel = 180 × W     ⇒ 双押吃掉的时间与 W 个平格完全相同（时值不动）
② travel 必须落在 15° 网格上     ⇒ 人类只用 15 的整数倍
```
"""
from __future__ import annotations

import json
import os
import re
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

DEFAULT_SRC = os.path.join(_ROOT, "out", "双押配置验收谱", "user_edited.adofai")
OUT_JSON = os.path.join(_ROOT, "patterns", "templates_dp.json")


def load(path: str) -> dict:
    return json.loads(re.sub(r",(\s*[}\]])", r"\1",
                             open(path, encoding="utf-8-sig").read()))


def main(argv) -> int:
    src = argv[0] if argv else DEFAULT_SRC
    if not os.path.exists(src):
        print("找不到谱面：%s" % src)
        return 2
    d = load(src)
    ad = [float(x) for x in d["angleData"]]
    n = len(ad)
    acts = d.get("actions") or []
    tw = {int(a["floor"]) for a in acts if a.get("eventType") == "Twirl"}
    cm = {int(a["floor"]): (a.get("comment") or "") for a in acts
          if a.get("eventType") == "EditorComment"}

    # 段速（speedType=Bpm ⇒ beatsPerMinute 是绝对值）
    ssv = {}
    for a in acts:
        if a.get("eventType") == "SetSpeed":
            bpm = float(a.get("beatsPerMinute") or 0)
            if str(a.get("speedType")) == "Bpm" and bpm > 0:
                ssv[int(a["floor"])] = bpm
            else:
                ssv[int(a["floor"])] = float(d["settings"]["bpm"]) * float(
                    a.get("bpmMultiplier") or 1)

    # 有效 travel（累积奇偶）
    par, x = [], False
    for i in range(n):
        if i in tw:
            x = not x
        par.append(x)
    raw = [180.0]
    for i in range(1, n):
        t = (180.0 + ad[i - 1] - ad[i]) % 360.0
        raw.append(360.0 if abs(t) < 1e-9 else t)
    eff = [round((360.0 - t) if par[i] else t, 6) for i, t in enumerate(raw)]

    cur = float(d["settings"]["bpm"])
    dt: list[float] = [0.0]
    for i in range(1, n):
        cur = ssv.get(i, cur)
        dt.append((eff[i] / 180.0) * (60000.0 / cur))

    starts = sorted(cm)
    tpls: list[dict] = []
    errs: list[str] = []
    print("=" * 94)
    print("从 %s 抽双押配置模板" % os.path.relpath(src, _ROOT))
    print("=" * 94)

    for k, f in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else n
        tiles = eff[f:end]
        tws = [(i in tw) for i in range(f, end)]
        dts = dt[f:end]

        # ---- 记谱：★ **原样整段**，不做首尾裁剪
        #   为什么：配置自己就以 X 开头、以 O 结尾，「首尾的平格是留白还是配置本体」
        #   从数据里**分不出来** —— 猜一次就会把段 1 从 12 格啃成 9 格（实测踩过）。
        #   留白只当**情报**报出来，不进模板。
        s, i = [], 0
        while i < len(tiles):
            if abs(tiles[i] - 30.0) < 1e-6 and i + 1 < len(tiles) \
                    and abs(tiles[i + 1] - 150.0) < 1e-6:
                s.append("X")
                i += 2
            elif abs(tiles[i] - 180.0) < 1e-6:
                s.append("O")
                i += 1
            else:
                s.append("?")
                i += 1
        nota = s
        pat = "".join(nota)
        pad_l = 0
        while pad_l < len(nota) and nota[pad_l] == "O":
            pad_l += 1
        pad_r = 0
        while pad_r < len(nota) - pad_l and nota[-1 - pad_r] == "O":
            pad_r += 1

        # ---- 最小重复周期（★ **推断**：先把首尾的平格留白摘掉再找周期）
        #   `lead/tail_plain_ge` 是**猜**的 —— 配置自己就以 O 结尾，数据里分不出来。
        #   所以 `core_*` 只当**情报**，`travel/twirl/notation` 才是权威（原样整段）。
        body = pat
        core_l = 0
        while core_l < len(body) and body[core_l] == "O":
            core_l += 1
        core_r = len(body)
        while core_r > core_l and body[core_r - 1] == "O":
            core_r -= 1
        core = body[core_l:core_r]
        period = len(core)
        for p in range(1, len(core) // 2 + 1):
            if len(core) % p == 0 and core == core[:p] * (len(core) // p):
                period = p
                break
        core_grouped = " ".join(core[q:q + 4] for q in range(0, len(core), 4))

        # ---- 核对
        ge = len(nota)
        tile_dt = sum(dts)
        exp = ge * 60.0
        if abs(tile_dt - exp) >= 1e-6:
            errs.append("段%s 时长 %.2f ≠ %.2f" % (k + 1, tile_dt, exp))
        bad = [v for v in tiles if abs(v / 15.0 - round(v / 15.0)) > 1e-6]
        if bad:
            errs.append("段%s travel 不在 15° 网格：%s" % (k + 1, sorted(set(bad))))
        if "?" in nota:
            errs.append("段%s 有认不出的格子" % (k + 1))
        # 每个双押 Σtravel = 360？不 —— 是 180（θ + (180−θ)）
        for q in range(len(tiles) - 1):
            if abs(tiles[q] - 30.0) < 1e-6 and abs(tiles[q + 1] - 150.0) < 1e-6:
                if abs(tiles[q] + tiles[q + 1] - 180.0) >= 1e-6:
                    errs.append("段%s 第 %d 格的双押 Σtravel ≠ 180" % (k + 1, q))

        head = (cm[f] or "").split("\n")[0]
        name = head.split("】", 1)[-1].strip() if "】" in head else head
        pat = "".join(nota)
        grouped = " ".join(pat[q:q + 4] for q in range(0, len(pat), 4))
        print("\n  【%d】%s" % (k + 1, name))
        print("       记谱（原样整段） %-30s 格 %2d · %.0fms"
              % (grouped, ge, tile_dt))
        print("       核心（推断） %-34s 周期 %d 格%s"
              % (core_grouped or "（整段都是平格）", period,
                 "  ← 一段一循环" if period == len(core) and core else ""))
        print("       twirl  %s%s"
              % ("".join("T" if v else "." for v in tws),
                 "   （推断留白 首%d/尾%d 格）" % (core_l, len(pat) - core_r)
                 if (core_l or len(pat) - core_r) else ""))
        tpls.append({
            "id": "DP%d" % (k + 1),
            "name": name,
            "notation": grouped,
            "core_notation": core_grouped,
            "core_is_guess": True,
            "core_period_ge": period,
            "ge": ge,
            "theta": 30.0,
            "travel": tiles,
            "twirl": tws,
            "dt_ms": [round(v, 6) for v in dts],
            "lead_plain_ge": core_l,
            "tail_plain_ge": len(pat) - core_r,
            "weight": 0.0,
        })

    out = {
        "_comment": (
            "双押配置模板（用户 2026-10 改完并确认「这个排版是正确的，时值没动」）。\n"
            "记谱：1 字符 = 1 格 = 60ms（×4/base250）；X = 双押 [theta, 180-theta]，"
            "O = 平格 [180]。\n"
            "不变量①：每个双押 Sigma(travel) = 180 ⇒ 吃掉的时间与一个平格完全相同。\n"
            "不变量②：travel 全部落在 15° 网格上。\n"
            "规则②：相邻双押用相反手性 ⇒ 每个新双押的第一格翻一次 Twirl。\n"
            "★★ 权威字段 = `travel` / `twirl` / `notation`（**逐格原样**，来自主人的谱子）。\n"
            "   `core_notation` / `core_period_ge` 是**推断**（首尾的平格是留白还是配置本体，"
            "数据里分不出来，见 core_is_guess）—— **只当情报，别当权威**。\n"
            "来源：out/双押配置验收谱/user_edited.adofai"),
        "_unit_ms": 60.0,
        "_source": os.path.relpath(src, _ROOT).replace("\\", "/"),
        "_core_is_guess": True,
        "templates": tpls,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    print()
    print("=" * 94)
    n_dp = sum(t["notation"].count("X") for t in tpls)
    print("  抽到 %d 条模板 · 双押共 %d 处 · 层数 %d"
          % (len(tpls), n_dp, sum(len(t["travel"]) for t in tpls)))
    if errs:
        print("  ✗ 有问题（不静默）：")
        for e in errs:
            print("     · " + e)
    else:
        print("  ★ 不变量全过：每个双押 Σtravel = 180 ✓ · travel 全在 15° 网格 ✓ · "
              "每格 = 60ms ✓")
    print("产物：%s" % OUT_JSON)
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
