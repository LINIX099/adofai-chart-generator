# -*- coding: utf-8 -*-
"""**headless 全流程生成**：源文件 → 求解 → 双押 → 上色 → 算法轨道调度 → 导出 → 校验。

    python tools/gen_from_source.py <源文件> [--audio 原曲.ogg] [--out-dir out/名字]
                                    [--set key=value ...] [--no-verify]

为什么需要它：用户在 GUI 里点一遍能得到的东西，脚本里也要能得到 ——
否则「拿别人的时间戳生成一份试试」就得手动开界面。
★ 它走的是**和界面完全同一条路**：`sidecar.server` 的 `/api/source` → `/api/rebuild`
  → `/api/export`（见 `tests/test_sidecar.py` 同一套调用），所以报告/记账/校验都一致。

支持的源（由 `sidecar.session.load_source` 按扩展名分派）：
    `.mid` MIDI · `.ogg/.wav/.mp3` 音频（自己采音） · `.adofai`/BDG 工程 ·
    时间戳（`.txt/.csv`，一行一个毫秒） · 时间戳 JSON（DEMUCS 分轨） · stem-JSON
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                     # noqa: BLE001
    pass

from sidecar import schema as SC                      # noqa: E402
from sidecar import server as SV                      # noqa: E402


def post(url: str, obj: dict, timeout: float = 900.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode("utf-8"))
        except Exception:                             # noqa: BLE001
            d = {"ok": False, "error": f"HTTP {e.code}"}
        d["status"] = e.code
        return d


def coerce(v: str):
    low = v.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("none", "null", ""):
        return None if low != "" else ""
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


# ============================================================ ★ --ref：从参考谱继承
#: 用户 2026-10（原话）：
#: > 「后面使用的**原始偏移、ogg 都需要是参考谱面中的**。**轨道颜色同理**」
#:
#: ⇒ `--ref <参考谱.adofai>` 时，从参考谱的 `settings` 里**照搬**这三样：
#:
#: | 搬什么 | 从哪 | 怎么搬 |
#: |---|---|---|
#: | **原始偏移** | `settings.offset` | 关掉 `auto_offset`，把 `offset` 钉成参考值 |
#: | **ogg** | `settings.songFilename` + 同目录下的文件 | 当 `--audio` 没给时自动指过去 |
#: | **轨道颜色** | 下面这 8 个键 | 导出后**逐键贴回**产物（schema 里没有对应字段） |
REF_TRACK_KEYS = (
    "trackColor", "secondaryTrackColor", "trackColorType", "trackColorPulse",
    "trackColorAnimDuration", "trackPulseLength", "trackGlowIntensity",
    "trackStyle",
)


def read_ref_settings(path: str) -> dict:
    """读参考谱的 `settings`（容错：BOM + 尾随逗号，语料里两种都有）。"""
    import re
    src = open(path, encoding="utf-8-sig").read()
    return (json.loads(re.sub(r",(\s*[}\]])", r"\1", src)) or {}).get("settings") or {}


def patch_ref_settings(chart_file: str, ref: dict) -> list[tuple[str, object, object]]:
    """把参考谱的**轨道颜色**（`REF_TRACK_KEYS`）贴回产物。返回 `(键, 旧值, 新值)`。"""
    with open(chart_file, encoding="utf-8-sig") as fh:
        j = json.load(fh)
    s = j.setdefault("settings", {})
    changed = []
    for k in REF_TRACK_KEYS:
        if k not in ref:
            continue
        if s.get(k) != ref[k]:
            changed.append((k, s.get(k), ref[k]))
        s[k] = ref[k]
    if changed:
        with open(chart_file, "w", encoding="utf-8") as fh:
            json.dump(j, fh, ensure_ascii=False, separators=(",", ":"))
    return changed


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    src = argv[0]
    audio = ""
    out_dir = ""
    ref_path = ""
    over: dict = {}
    verify = True
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--audio":
            audio = argv[i + 1]; i += 2
        elif a == "--out-dir":
            out_dir = argv[i + 1]; i += 2
        elif a == "--ref":
            # ★ 从参考谱继承「原始偏移 / ogg / 轨道颜色」（用户 2026-10 的规格）
            ref_path = argv[i + 1]; i += 2
        elif a == "--set":
            k, _, v = argv[i + 1].partition("=")
            over[k] = coerce(v); i += 2
        elif a == "--tracks":
            # ★ `tracks_checked` 是**列表**，`--set` 表达不了（`coerce` 只出标量）。
            #   用法：`--tracks 0,1` ⇒ 主轨勾选这两条。
            over["tracks_checked"] = [int(x) for x in argv[i + 1].split(",") if x.strip() != ""]
            i += 2
        elif a == "--json":
            # ★★ 通用出口：`--set` 的 `coerce` 只出标量，**列表 / 字典型的状态键根本传不进去**
            #   （`dp_checked` 双押轨、`xk_ranges` 采bpm 区间、`segments` 分段采音……）。
            #   `--tracks` 当初就是为这一个键开的口子 —— 这里补成通用形式：
            #       --json dp_checked=[1]
            #       --json xk_ranges=[{"start_ms":0,"end_ms":200000,"xk_base":4}]
            #   ★ 解析失败**抛**，不静默降级成字符串（静默降级会让整条实验悄悄跑偏）。
            k, _, v = argv[i + 1].partition("=")
            if not k or not _:
                print(f"--json 需要 key=<JSON> 形式，拿到 {argv[i + 1]!r}")
                return 2
            try:
                over[k] = json.loads(v)
            except ValueError as e:
                print(f"--json {k} 不是合法 JSON：{e}（原文 {v!r}）")
                return 2
            i += 2
        elif a == "--no-verify":
            verify = False; i += 1
        else:
            print(f"未知参数 {a}"); return 2
    if not os.path.exists(src):
        print(f"源文件不存在：{src}")
        return 2
    name = over.get("song") or os.path.splitext(os.path.basename(src))[0]
    out_dir = out_dir or os.path.join(_ROOT, "out", str(name))

    # ---- ★ `--ref`：先把参考谱的三样读出来
    ref_set: dict = {}
    if ref_path:
        if not os.path.exists(ref_path):
            print(f"参考谱不存在：{ref_path}")
            return 2
        ref_set = read_ref_settings(ref_path)
        ref_dir = os.path.dirname(os.path.abspath(ref_path))
        # ① 原始偏移：关掉自动，钉成参考值。
        #   ★★ 优先级：**显式 `--set offset=` > `--ref` 的 offset > auto_offset**。
        #   用户 2026-10：「调整了一下偏移，**883 是环境下正确的偏移**」——
        #   参考谱文件里写的是 1053，但在（游戏 + 这份 ogg 的）环境里 883 才对，
        #   所以要用 `--set offset=883` 能覆盖掉 `--ref` 带过来的值。
        if "offset" in ref_set:
            over["auto_offset"] = False
            if "offset" not in over:
                over["offset"] = float(ref_set["offset"])
            else:
                print(f"   偏移   : 显式 --set offset={over['offset']} **覆盖**参考谱的 "
                      f"{ref_set['offset']}（环境标定值优先）")
        # ② ogg：`--audio` 没给就指到参考谱目录里的那个文件名
        if not audio and ref_set.get("songFilename"):
            cand = os.path.join(ref_dir, str(ref_set["songFilename"]))
            if os.path.isfile(cand):
                audio = cand
        if ref_set.get("bpm") is not None and float(ref_set["bpm"]) != float(
                over.get("base_bpm") or ref_set["bpm"]):
            print(f"⚠ 参考谱 base bpm = {ref_set['bpm']}（本工具不改它，"
                  f"时序对不上时先看这一条）")

    SV.APP = SV.App(_ROOT)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SV.Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1},
                     daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    print("=" * 74)
    print("headless 全流程生成")
    print("=" * 74)
    print(f"源文件 : {src}")
    print(f"输出   : {out_dir}")
    if ref_path:
        print(f"参考谱 : {ref_path}")
        print(f"   继承 原始偏移 offset={ref_set.get('offset')}"
              f"（关掉 auto_offset）· ogg={os.path.basename(audio) if audio else '（没找到）'}"
              f" · 轨道颜色 {len([k for k in REF_TRACK_KEYS if k in ref_set])} 个键")

    r = post(base + "/api/load", {"path": src})
    if not r.get("ok"):
        print("✗ 载入失败：" + str(r.get("error") or r.get("msg"))[:400])
        return 1
    n_tr = len(r.get("tracks") or [])
    print(f"载入   : ok · 音轨 {n_tr} 条")
    for w in (r.get("warnings") or [])[:6]:
        print(f"   ⚠ {w}")
    # ★ 勾选主轨：来源没给默认就用第 1 条（界面里也是「至少勾一条」才有音）
    _dft = list(r.get("default_tracks_checked") or [])
    if not _dft and (r.get("tracks") or []):
        _dft = [int((r["tracks"])[0]["index"])]
    if _dft:
        over.setdefault("tracks_checked", _dft)
        print(f"主轨   : 勾选 {_dft}"
              + ("（来源给的默认）" if r.get("default_tracks_checked") else "（没给默认 ⇒ 取第 1 条）"))
    # ★★ 来源自带的**默认值**必须被采纳（界面也是这么做的）：
    #   时间戳来源会要求 `merge_ms=0`（否则 30ms 默认合并会把密集处的音**悄悄并掉**）、
    #   `fit_mode=direct`（时序优先）、去噪开。不采纳 ⇒ 轮指段会被吃掉。
    adopted = {}
    for k, v in (("default_merge_ms", "merge_ms"),
                 ("default_fit_mode", "fit_mode"),
                 ("default_denoise_on", "denoise_on")):
        if k in r:
            adopted[v] = r[k]
    if adopted:
        for k, v in adopted.items():
            over.setdefault(k, v)
        print(f"来源默认值: {adopted}（`default_*` ⇒ 不采纳会把密集处的音并掉）")

    state = SC.defaults()
    state.update(over)
    if audio:
        state["preview_audio_mode"] = 2
        state["preview_audio_path"] = audio
        print(f"预览音源: 指定文件 {audio}")
    state.setdefault("song", str(name))
    state.setdefault("artist", "")

    print("\n-- 重建 ------------------------------------------------------------")
    rb = post(base + "/api/rebuild", {"state": state})
    if not rb.get("ok"):
        print("✗ 重建失败：" + str(rb.get("error") or rb.get("msg"))[:400])
        return 1
    print(f"状态: {rb.get('status')}")
    for w in (rb.get("warning_list") or [])[:8]:
        print(f"   ⚠ {w}")
    chk = rb.get("check") or {}
    sug = chk.get("suggest_ms")
    print(f"校验: {'OK' if chk.get('ok') else '注意'}  {chk.get('text') or chk.get('msg') or ''}"
          f"  建议 offset={sug}")
    ap = (rb.get("payload") or {}).get("appearance") or {}
    if ap:
        print(f"\n算法轨道调度: {ap.get('text')}")
        print(f"   皮肤        : {ap.get('skin')} {ap.get('settings')}")
        print(f"   涟漪环      : {[(x['floor'], x['rings'] + 1) for x in (ap.get('ripples') or [])]}")
        print(f"   半径切换    : {[(x['floor'], x['scale']) for x in (ap.get('radius_spans') or [])]}")
        print(f"   事件 {ap.get('n_events')} 条 / 同格最多 {ap.get('max_per_floor')}"
              f" / 避让 {ap.get('n_collide')} / 截断 {ap.get('n_capped')}"
              f" / 扫过换手押 {ap.get('n_overlap_occupied')}")
        for w in (ap.get("skipped_why") or [])[:6]:
            print(f"     · {w}")
    co = (rb.get("payload") or {}).get("color") or {}
    if co:
        print(f"换手押上色  : {co.get('text')}")

    # ★★ 几何体检（`docs/60` §15 的教训）：**时序校验过了不等于谱面能看**。
    #   ASGORE 60s 那一版就是"`verify` 0.0us 全过、用户一看截图是碎渣"。
    try:
        from core import geomcheck as GC
        _ch = SV.APP.session.chart
        if _ch is not None:
            _m = GC.metrics(_ch)
            for _ln in GC.report_lines(_m):
                print(_ln)
    except Exception as _e:                                  # noqa: BLE001
        print(f"（几何体检跳过：{_e}）")

    if sug is not None and not ref_path:
        try:
            state["offset"] = float(sug)
            state["auto_offset"] = False
            print(f"\n-- 按建议 offset={sug} 再算一次 ------------------------------------")
            rb2 = post(base + "/api/rebuild", {"state": state})
            if rb2.get("ok"):
                rb = rb2
                print(f"状态: {rb.get('status')}")
                ap = (rb.get("payload") or {}).get("appearance") or {}
                if ap:
                    print(f"算法轨道调度: {ap.get('text')}")
                    print(f"   半径切换: {[(x['floor'], x['scale']) for x in (ap.get('radius_spans') or [])]}")
        except (TypeError, ValueError):
            pass
    elif sug is not None:
        print(f"\n（参考谱模式 ⇒ **不**按建议 offset={sug} 重算，"
              f"offset 钉在参考谱的 {ref_set.get('offset')}）")

    print("\n-- 导出 ------------------------------------------------------------")
    ex = post(base + "/api/export", {"state": state, "dir": out_dir})
    if not ex.get("ok"):
        print("✗ 导出失败：" + str(ex.get("error") or ex.get("msg"))[:400])
        return 1
    got = ex.get("dir") or out_dir
    print(f"导出: {got}")
    for f in sorted(os.listdir(got)) if os.path.isdir(got) else []:
        p = os.path.join(got, f)
        if os.path.isfile(p):
            print(f"   {os.path.getsize(p):>10} B  {f}")

    # ---- ★ `--ref`：把参考谱的**轨道颜色**贴回产物
    if ref_path and os.path.isdir(got):
        cf = os.path.join(got, "main.adofai")
        if os.path.isfile(cf):
            ch = patch_ref_settings(cf, ref_set)
            if ch:
                print("\n-- 从参考谱贴回轨道颜色 -------------------------------------------")
                for k, old, new in ch:
                    print(f"   {k:<26} {old!r} → {new!r}")
            else:
                print("\n-- 轨道颜色：产物与参考谱已经一致（0 处改动）----------------------")

    if verify:
        print("\n-- 反解校验（第三方，逐按键）--------------------------------------")
        try:
            from core import verify as V
            chart_file = os.path.join(got, "main.adofai")
            ons = [o.t_ms for o in SV.APP.session.onsets]
            n_dp = int((rb.get("dp") or {}).get("n", 0) or 0)
            has_dp = n_dp > 0 or (rb.get("n_floors", 0) != len(ons) + 1)
            if has_dp:
                vr = V.verify_press_subset(chart_file, ons, tol_ms=2.0)
                print(f"（带双押层：层数 {rb.get('n_floors')} ≠ onset {len(ons)}+1 ⇒ 按键盘集合校验）")
            else:
                vr = V.verify_file(chart_file, ons, tol_ms=2.0, lead_floors=1)
            print(f"{'✓' if vr.ok else '✗'} {vr.summary()}")
        except Exception as exc:                      # noqa: BLE001
            print(f"（校验跳过：{exc}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
