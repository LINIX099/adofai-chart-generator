"""TUF (tuforums.com) 开放 API 客户端。

论坛是 SPA + 开放 v2 API（`https://api.tuforums.com`，Swagger 在 `/docs/`，
OpenAPI JSON 在 `/openapi.json`），作者允许爬虫。

用到的端点：
  GET /v2/database/levels            搜索谱面（query / sort / page / offset / limit / pguRange）
  GET /v2/database/levels/{id}       单个谱面
  GET /v2/database/levels/{id}/level.adofai   直接下 .adofai
  GET /v2/database/difficulties      难度表（P1~P20 / G1~G20 / U1~U20 / ...）
  GET /v2/database/passes            通关记录（count 就是总数，5.8 万条）

注意：`limit` 上限 100；`sort` 传什么都没用（服务端忽略），所以排序在本地做。
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

BASE = "https://api.tuforums.com"
UA = "adofai-corpus-audit/0.1 (+local chart analysis)"
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tuf_cache")

#: 本地代理（直连太慢时用）。设 `TUF_PROXY=127.0.0.1:7897` 或直接改这里。
PROXY = os.environ.get("TUF_PROXY", "127.0.0.1:7897") or None


def _opener():
    if not PROXY:
        return urllib.request.build_opener()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": f"http://{PROXY}",
                                     "https": f"http://{PROXY}"}))


_OPENER = _opener()


def _get(url: str, *, retries: int = 3, timeout: int = 25):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": UA})
            with _OPENER.open(req, timeout=timeout) as fh:
                return json.loads(fh.read().decode("utf-8", "replace"))
        except Exception as e:                                   # noqa: BLE001
            last = e
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"GET 失败 {url}: {last}")


def api(path: str, **params):
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()
                 if v is not None)
    return _get(f"{BASE}{path}" + (f"?{q}" if q else ""))


def difficulties() -> dict[int, dict]:
    """难度表：{id: {name, type, legacy, baseScore, sortOrder}}。"""
    arr = api("/v2/database/difficulties")
    if isinstance(arr, dict):
        arr = arr.get("results", [])
    return {int(d["id"]): d for d in arr}


def search_levels(query=None, *, limit=100, offset=0, pgu=None, max_pages=1):
    """按关键词搜谱面。返回原始记录列表。"""
    out = []
    for p in range(max_pages):
        j = api("/v2/database/levels", query=query, limit=limit,
                offset=offset + p * limit, pguRange=pgu)
        res = j.get("results") if isinstance(j, dict) else j
        if not res:
            break
        out += res
        if len(res) < limit:
            break
    return out


def iter_levels(*, limit=100, start_offset=0, max_pages=1000, pgu=None, quiet=False):
    """按 id 倒序分页遍历全库（服务端唯一的稳定顺序）。"""
    for p in range(max_pages):
        j = api("/v2/database/levels", limit=limit, offset=start_offset + p * limit,
                pguRange=pgu)
        res = j.get("results") if isinstance(j, dict) else j
        if not res:
            return
        if not quiet:
            print(f"  [page {p}] offset={start_offset + p * limit} n={len(res)}",
                  flush=True)
        yield from res
        if len(res) < limit:
            return


def download_adofai(level_id: int, dest_dir: str, *, name: str | None = None) -> str | None:
    """下 `level.adofai` 到 dest_dir。已存在就跳过。"""
    os.makedirs(dest_dir, exist_ok=True)
    fn = name or f"{level_id}.adofai"
    path = os.path.join(dest_dir, fn)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    url = f"{BASE}/v2/database/levels/{level_id}/level.adofai"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with _OPENER.open(req, timeout=30) as fh:
            data = fh.read()
    except Exception as e:                                       # noqa: BLE001
        print(f"    [下载失败] id={level_id} {e}", flush=True)
        return None
    if not data or len(data) < 200:
        print(f"    [下载为空] id={level_id}", flush=True)
        return None
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return path
