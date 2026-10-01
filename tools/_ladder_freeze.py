# -*- coding: utf-8 -*-
"""P-1：**先冻基线**（`docs/25` §10）。

「原逻辑保留」不能靠嘴说 —— 这个工具把三首示例曲在几组代表性参数下的
**导出产物哈希**钉到 `tests/golden/off_hashes.json`。
之后 `tests/test_ladder.py::test_off_is_identical` 只要拿 `aggressive_pick=False`
再跑一遍、比对同一份文件，就能机器化地证明「老路径一行没变」。

用法:
    python tools/_ladder_freeze.py          # 写入/覆盖 golden 文件
    python tools/_ladder_freeze.py --check  # 只校验当前代码是否仍与 golden 一致
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.midi import load                                     # noqa: E402
from core.onsets import build_onsets, OnsetParams              # noqa: E402
from core import solve as S, writer as W                       # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "golden", "off_hashes.json")

#: ★★ 2026-10 第二次重冻（**几何零变化，只是 settings 多了一个键**）：
#:   合并那份「重做 UI 的 fork」时，`core/writer.build_json` 在白名单里补了
#:   **`songArtist`**（v2 的键名，导出要用，见 `EXPORT_SETTINGS_KEYS`）。
#:   它进了 `settings` ⇒ 整个 JSON 的哈希全变 ⇒ 这条冻结断言**假红**。
#:   证据（`tools/_grin_freeze_check.py` 留档）：
#:     · 把 `settings.songArtist` 去掉再算哈希 ⇒ **11/11 与旧 golden 逐字节一致**；
#:     · 也就是说 angleData / actions / 其它 settings 一个字节都没动。
#:   ⇒ 重冻基线。以后若再出现「全用例一起变」，先用那个工具做同样的排除，
#:     不要直接重冻（那会把真正的几何改动一起吞掉）。
#:
#: (曲名, 参数覆盖) —— 覆盖默认 / 雪花 / 双押 / 高最小角度 四种路径
#: ★ 2026-10 用户把 `pause_min_beats` 默认从 1.0 改成 4.0，**默认参数变了**，
#:   所以基线跟着重冻。同时补两条**显式钉死**参数的用例 ——
#:   以后再有默认值漂移时，那两条仍然能守住「代码没被改坏」。
CASES = [
    ("Automaton_Waltz", {}),
    ("FallenEra", {}),
    ("MemoryLocked", {}),
    ("Automaton_Waltz", {"use_snowflake": True, "snowflake_min_tiles": 4,
                         "snowflake_full_tiles": 8.0}),
    ("Automaton_Waltz", {"travel_min": 45.0}),
    ("Automaton_Waltz", {"pause_min_beats": 1.0}),        # 钉死：旧默认
    ("Automaton_Waltz", {"pause_min_beats": 4.0, "travel_min": 20.0,
                         "use_snowflake": False}),
    # ★ 2026-10 用户「方块位置偏移的选项可以开局为关闭了」⇒ 默认 False。
    #   基线跟着重冻（它记的是「当前默认参数下的产物」），并补两条**显式钉死**
    #   的用例，保证以后无论默认怎么飘，「开 / 关」两条路径都还被守着。
    ("Automaton_Waltz", {"use_position_track": True}),
    ("Automaton_Waltz", {"use_position_track": False}),   # = 新默认
    # ★★ 2026-10 用户：「算法会贪心地倾向于**原地打转**，建议**增加原地惩罚**，
    #   让算法可以更倾向于**向规划的方向铺设轨道**」⇒ **默认行为变了**
    #   （`core/figures.score` 的 `waste` + `dp_candidate` 对照项），
    #   所以基线跟着重冻。同时补两条**显式钉死**的用例：
    #     · `inplace_waste=True`  = 新默认（原地惩罚开）
    #     · `inplace_waste=False` = **老口径**（只看 0/1 的 Y>0）
    #   这样以后无论默认怎么飘，「开 / 关」两条路径都还被守着。
    ("Automaton_Waltz", {"inplace_waste": True}),
    ("Automaton_Waltz", {"inplace_waste": False}),
]


def digest(name: str, kw: dict) -> str:
    """把一首曲子在某组参数下的**谱面产物**压成一个哈希。

    哈希的对象是 `writer.build_json` 的整个 dict（含 angleData / actions /
    settings），也就是写到 `.adofai` 里的全部内容 —— 任何一格 travel / bpm /
    Twirl / PositionTrack 变了都会变。
    """
    mf = load(os.path.join(ROOT, "samples", "_external", name + ".mid"))
    ons = build_onsets(mf.tracks[0].notes, OnsetParams(merge_ms=30.0))
    p = S.SolveParams(ppqn=mf.ppqn, midi_bpm=mf.bpm0, **kw)
    assert p.aggressive_pick is False, "冻结基线时开关必须是关的"
    ch = S.solve(ons, p)
    js = W.build_json(ch)
    blob = json.dumps(js, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def compute() -> dict:
    out = {}
    for name, kw in CASES:
        key = name + "|" + json.dumps(kw, sort_keys=True, ensure_ascii=False)
        out[key] = digest(name, kw)
    return out


def main() -> int:
    check = "--check" in sys.argv[1:]
    now = compute()
    if check:
        if not os.path.exists(GOLDEN):
            print(f"缺少 golden 文件：{GOLDEN}\n先跑 python tools/_ladder_freeze.py")
            return 2
        with open(GOLDEN, "r", encoding="utf-8") as fh:
            old = json.load(fh)
        bad = [k for k in old if old.get(k) != now.get(k)]
        extra = [k for k in now if k not in old]
        for k in bad:
            print(f"  ✗ {k}\n      golden {old.get(k)}\n      now    {now.get(k)}")
        for k in extra:
            print(f"  ? {k} 不在 golden 里（新增了用例？）")
        if bad:
            print(f"\n=> FAIL  老路径改了 {len(bad)} 个用例")
            return 1
        print(f"=> OK   {len(old)} 个用例与 golden 完全一致（老路径逐字节未变）")
        return 0
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(now, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"已写入 {GOLDEN}（{len(now)} 个用例）")
    for k, v in sorted(now.items()):
        print(f"  {v[:16]}…  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
