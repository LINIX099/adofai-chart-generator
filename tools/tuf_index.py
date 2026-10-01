"""把 TUF 谱面库整个拉一遍，存成本地索引。

服务端的 `sort` 参数被忽略（永远按 id 倒序），所以排序只能在本地做。
索引存到 `corpus_tuf/_index.json`，重复跑直接读缓存。

用法：
    python tools/tuf_index.py            # 用缓存
    python tools/tuf_index.py --refresh  # 重新拉
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuf_api as T  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "corpus_tuf", "_index.json")


def build(refresh=False):
    if os.path.exists(CACHE) and not refresh:
        with open(CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    rows, offset = [], 0
    while True:
        try:
            j = T.api("/v2/database/levels", limit=100, offset=offset)
        except Exception as e:                                    # noqa: BLE001
            print(f"  第 {offset} 页失败，跳过：{e}", flush=True)
            offset += 100
            continue
        res = j.get("results") if isinstance(j, dict) else j
        if not res:
            break
        rows += res
        offset += 100
        if offset % 1000 == 0:
            print(f"  {offset:>6} 条 ... 最后 id={res[-1].get('id')}", flush=True)
            with open(CACHE, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False)
        if len(res) < 100:
            break
        time.sleep(0.12)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    return rows


if __name__ == "__main__":
    t0 = time.time()
    rows = build("--refresh" in sys.argv)
    print(f"\n索引 {len(rows)} 条  ({os.path.getsize(CACHE)/1e6:.1f} MB, "
          f"{time.time()-t0:.0f}s)")

    diffs = T.difficulties()
    have_dl = [r for r in rows if r.get("dlLink") or r.get("fileId")]
    print(f"有下载链接的 {len(have_dl)} 条")

    import collections
    cl = collections.Counter()
    for r in rows:
        c = int(r.get("clears") or 0)
        cl["0" if c == 0 else "1-4" if c < 5 else "5-19" if c < 20 else
           "20-49" if c < 50 else "50-99" if c < 100 else ">=100"] += 1
    print("\nclears 分布：")
    for k in ("0", "1-4", "5-19", "20-49", "50-99", ">=100"):
        print(f"   {k:>7} : {cl[k]:>6} 张")

    print("\nclears 最多的 25 张：")
    for r in sorted(rows, key=lambda x: -int(x.get("clears") or 0))[:25]:
        d = diffs.get(int(r.get("diffId") or 0), {})
        print(f"   id={r['id']:<6} clears={r.get('clears',0):<5} "
              f"dl={r.get('downloadCount',0):<6} likes={r.get('likes',0):<4} "
              f"{d.get('name','?'):<9} | {str(r.get('song'))[:52]}")
