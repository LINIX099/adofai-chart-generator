"""先摸清 EX 语料对应的 TUF 难度档位。

`‹社区语料目录›\ex` 里的 14 张是**官方关卡的重制 EX 版**
（1-EX A Dance of Fire and Ice、10-EX Butterfly Planet …）。
在 TUF 上按歌名搜，拿到它们的难度，才知道该去哪个档位找「同级的真人高通关谱」。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuf_api as T  # noqa: E402

EX = CORPUS + r"\ex"
SKIP = {"XO", "B"}

names = []
for d in sorted(os.listdir(EX)):
    p = os.path.join(EX, d)
    if not os.path.isdir(p):
        continue
    tag, _, rest = d.partition("-")
    if tag in SKIP:
        continue
    # "1-EX A Dance of Fire and Ice (Plum Remix)" → "A Dance of Fire and Ice"
    song = rest.split("(", 1)[0].replace("EX", "", 1).strip()
    if song.endswith("Remix"):
        song = song[: -len("Remix")].strip()
    names.append((tag, song))
# 补上被 SKIP 掉的两张
for d in sorted(os.listdir(EX)):
    tag, _, rest = d.partition("-")
    if tag in SKIP:
        names.append((tag, rest.split("(", 1)[0].replace("EX", "", 1).strip()))

diffs = T.difficulties()
print(f"难度表 {len(diffs)} 条\n")

rows = []
for tag, song in names:
    try:
        res = T.search_levels(song, limit=100, max_pages=1)
    except Exception as e:                                       # noqa: BLE001
        print(f"{tag:>3} {song:<44} 搜索失败 {e}")
        continue
    # 只看歌名高度吻合的
    key = song.lower().replace(" ", "")
    hits = [r for r in res
            if key in str(r.get("song", "")).lower().replace(" ", "")]
    print(f"{tag:>3} {song:<44} 命中 {len(hits):>3} 条（总返回 {len(res)}）")
    for r in hits[:4]:
        d = diffs.get(int(r.get("diffId") or 0), {})
        print(f"        id={r['id']:<6} diff={d.get('name','?'):<10} "
              f"legacy={d.get('legacy','?'):<5} clears={r.get('clears',0):<5} "
              f"dl={r.get('downloadCount',0):<5} likes={r.get('likes',0):<4} "
              f"{str(r.get('song'))[:40]}")
        rows.append((tag, song, r, d))
    time.sleep(0.25)

print("\n===== 汇总：EX 对应难度 =====")
import collections  # noqa: E402

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")
c = collections.Counter(d.get("name", "?") for _t, _s, _r, d in rows)
for k, v in c.most_common():
    print(f"   {k:<10} {v} 张")
