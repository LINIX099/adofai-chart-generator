"""从 TUF 索引里挑要下载的谱面。

EX 语料（`adofaipumian\\ex`）是**官方关卡的重制 EX 版**，在 TUF 上对应 P3~P6
（legacy 4~6）为主。所以「同级的真人高通关谱」= 这个难度带里 clears 高的那些。

另外单独收两组：
  ① 官方战役谱（1-X / 3-X / 7-X …）—— 这游戏最权威的真人写法
  ② 全库 clears 最高的 N 张（不限难度）—— 社区里最经典的谱

输出 `corpus_tuf/_download_list.json`。
"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuf_api as T  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "corpus_tuf", "_index.json")
LIST = os.path.join(ROOT, "corpus_tuf", "_download_list.json")

EX_BAND = ("P3", "P4", "P5", "P6", "P7")
OFFICIAL_RE = re.compile(r"\((?:1|2|3|4|5|6|7|8|9|10|11|12|B|XO)-X\)", re.I)


def usable(r):
    return (not r.get("isDeleted")) and (not r.get("isHidden")) and r.get("fileId")


def main():
    rows = json.load(open(IDX, encoding="utf-8"))
    diffs = T.difficulties()
    for r in rows:
        r["_diff"] = diffs.get(int(r.get("diffId") or 0), {}).get("name", "?")
        r["_legacy"] = diffs.get(int(r.get("diffId") or 0), {}).get("legacy", "?")
        r["_clears"] = int(r.get("clears") or 0)
        r["_dl"] = int(r.get("downloadCount") or 0)

    ok = [r for r in rows if usable(r)]
    print(f"索引 {len(rows)} 条，可用（未删/未隐藏/有文件）{len(ok)} 条")

    print("\n难度分布（可用）：")
    for k, v in collections.Counter(r["_diff"] for r in ok).most_common(12):
        print(f"   {k:<10} {v:>6}")

    # ① 官方战役谱
    official = [r for r in ok if OFFICIAL_RE.search(str(r.get("song", "")))]
    official.sort(key=lambda r: -r["_clears"])
    print(f"\n① 官方战役谱 {len(official)} 张：")
    for r in official[:20]:
        print(f"   id={r['id']:<6} {r['_diff']:<5} clears={r['_clears']:<5} "
              f"dl={r['_dl']:<5} | {str(r['song'])[:56]}")

    # ② 对齐 EX 难度的
    band = [r for r in ok if r["_diff"] in EX_BAND]
    print(f"\n② 难度带 {'/'.join(EX_BAND)} 共 {len(band)} 张")
    for th in (5, 10, 20, 30, 50):
        print(f"   clears>={th:<3} → {sum(1 for r in band if r['_clears'] >= th):>4} 张")

    # ③ 全库高通关
    top = sorted(ok, key=lambda r: -r["_clears"])
    print(f"\n③ 全库 clears 前 100 的难度构成："
          + "  ".join(f"{k}={v}" for k, v in
                      collections.Counter(r["_diff"] for r in top[:100]).most_common()))

    # ---- 组装下载清单
    picked, seen = [], set()

    def add(r, group):
        if r["id"] in seen:
            return
        seen.add(r["id"])
        picked.append({"id": r["id"], "song": r.get("song"), "artist": r.get("artist"),
                       "diff": r["_diff"], "legacy": r["_legacy"],
                       "clears": r["_clears"], "downloads": r["_dl"],
                       "fileId": r.get("fileId"), "group": group})

    for r in official:
        add(r, "official")
    for r in band:
        if r["_clears"] >= 10:
            add(r, "band")
    for r in top[:120]:
        if r["_clears"] >= 50:
            add(r, "top")
    # ④ 全难度 clears>=20 全收 —— 社区「被广泛通关」的那批，
    #    按难度分层后能看出各条统计量随难度怎么走。
    for r in ok:
        if r["_clears"] >= 20:
            add(r, "clears20")

    with open(LIST, "w", encoding="utf-8") as fh:
        json.dump(picked, fh, ensure_ascii=False, indent=1)
    print(f"\n清单写入 {LIST}")
    print(f"   合计 {len(picked)} 张  "
          + "  ".join(f"{g}={sum(1 for p in picked if p['group']==g)}"
                      for g in ("official", "band", "top", "clears20")))


if __name__ == "__main__":
    main()
