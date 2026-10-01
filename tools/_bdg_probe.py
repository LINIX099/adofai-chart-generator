# -*- coding: utf-8 -*-
"""`tools/_bdg_probe.py <file.bdg> [--json]` —— BDG 字段形状指纹 + 解析报告。

**收新 fixture 时先跑它。**

    python tools\\_bdg_probe.py tests\\fixtures\\bdg\\v2_real_electric_hornet.bdg
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bdg  # noqa: E402


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv
    if not args:
        print(__doc__)
        return 2
    path = args[0]

    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    if as_json:
        from core.bdg import probe
        try:
            raw = json.loads(text)
        except Exception as e:                   # noqa: BLE001
            print(f"[坏 JSON] {e}")
            return 1
        print(json.dumps(probe.fingerprint(raw), ensure_ascii=False, indent=2))
        return 0

    from core.bdg import probe
    print("=" * 72)
    print(f"文件: {path}   {len(data)} bytes")
    print("=" * 72)
    try:
        raw = json.loads(text)
    except Exception as e:                       # noqa: BLE001
        print(f"[坏 JSON] {e}")
        raw = None
    if isinstance(raw, dict):
        print(probe.report_text(raw))
        print()

    p, rep = bdg.load_text(text, source=path)
    print("=" * 72)
    print(f"规范化模型: {p.name!r}  baseBpm={p.base_bpm}  offsetMs={p.offset_ms}")
    print(f"  轨 {len(p.tracks)} 个:")
    for t in p.tracks:
        print(f"    [{t.role:>4}] {t.name!r:<22} type={t.type or '—':<34}"
              f" hidden={t.hidden}  点={len(p.points_of(t.id))}")
    print(f"  拍点 {len(p.points)}（补出循环子点 {sum(1 for x in p.points if x.synth)}）")
    print(f"  变速点(宿主) {len(p.bpm_points)}   变速点(插件轨) {len(p.bpm_events)}")
    for e in p.bpm_events[:8]:
        print(f"    beat={e.beat:<12} {e.speed_type}={e.value}")
    if p.bpm_events:
        print(f"    beat⇄ms: {p.tempo.time_of_beat(p.bpm_events[0].beat):.2f} ms")
    print()
    print(rep.pretty())

    ok, why = bdg.emit.can_emit(rep)
    out = bdg.build(p, rep)
    if out is None:
        print(f"\n[写回] ✗ {why}")
    else:
        same = bdg.dumps(out) == text
        print(f"\n[写回] ✓ passthrough 往返{'逐字节一致' if same else '**有差异**'}")
        if not same:
            a, b = bdg.dumps(out), text
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"        首个差异 @{i}: {a[i-30:i+30]!r} vs {b[i-30:i+30]!r}")
                    break
            else:
                print(f"        长度不同 {len(a)} vs {len(b)}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
