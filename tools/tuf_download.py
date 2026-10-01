"""按 `corpus_tuf/_download_list.json` 把谱面下下来（多线程 + 走代理）。

落到 `corpus_tuf/<难度>/<id>_<歌名>.adofai`。已存在就跳过，可重复跑。

    python tools/tuf_download.py            # 默认 12 线程
    python tools/tuf_download.py --jobs 24
    set TUF_PROXY=127.0.0.1:7897            # 或留空走直连
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuf_api as T  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "corpus_tuf")
LIST = os.path.join(DEST, "_download_list.json")

_lock = threading.Lock()
_stat = {"ok": 0, "skip": 0, "bad": 0, "done": 0}


def safe(s, n=60):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(s)).strip(" ._")
    return s[:n] or "untitled"


def one(it):
    sub = safe(it["diff"], 20)
    fn = f"{it['id']}_{safe(it['song'])}.adofai"
    path = os.path.join(DEST, sub, fn)
    if os.path.exists(path) and os.path.getsize(path) > 200:
        k = "skip"
    else:
        k = "ok" if T.download_adofai(it["id"], os.path.join(DEST, sub), name=fn) else "bad"
    with _lock:
        _stat[k] += 1
        _stat["done"] += 1
        if _stat["done"] % 25 == 0:
            print(f"   {_stat['done']}/{len(items)}  "
                  f"新下 {_stat['ok']} 跳过 {_stat['skip']} 失败 {_stat['bad']}",
                  flush=True)


if __name__ == "__main__":
    jobs = 12
    if "--jobs" in sys.argv:
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1])
    items = json.load(open(LIST, encoding="utf-8"))
    print(f"清单 {len(items)} 张   代理={T.PROXY or '直连'}   线程={jobs}")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(one, it) for it in items]
        for _ in as_completed(futs):
            pass
    print(f"\n完成：新下 {_stat['ok']}，跳过 {_stat['skip']}，失败 {_stat['bad']}"
          f"   用时 {time.time()-t0:.0f}s")
    n = mb = 0
    for dp, _d, fs in os.walk(DEST):
        for f in fs:
            if f.endswith(".adofai"):
                n += 1
                mb += os.path.getsize(os.path.join(dp, f))
    print(f"corpus_tuf 里 .adofai {n} 个 / {mb/1e6:.1f} MB")
