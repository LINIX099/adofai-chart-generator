# -*- coding: utf-8 -*-
"""蓝奏云取文件：解 `acw_sc__v2` JS 挑战 → 解析页面 → ajaxm 换真实地址 → 下载。

    python tools/lanzou_get.py <分享链接> <输出目录>

★ 这是「版权内容只存外部链接」的落地工具：仓库里只留链接，文件下到本地。
★ 挑战算法是公开的（`acw_sc__v2`）：页面给 `arg1`，做 `unsbox` + 定长 hex 异或，
  把结果写回同名 cookie 再请求一次即可。**不涉及任何账号/凭据**。
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlparse

import requests

PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

#: 页面里那段混淆出来的置换表（各站点一致）
_PERM = [0xf, 0x23, 0x1d, 0x18, 0x21, 0x10, 0x1, 0x26, 0xa, 0x9, 0x13, 0x1f, 0x28,
         0x1b, 0x16, 0x17, 0x19, 0xd, 0x6, 0xb, 0x27, 0x12, 0x14, 0x8, 0xe, 0x15,
         0x20, 0x1a, 0x2, 0x1e, 0x7, 0x4, 0x11, 0x5, 0x3, 0x1c, 0x22, 0x25, 0xc, 0x24]
_KEY = "3000176000856006061501533003690027800375"


def _unsbox(arg: str) -> str:
    out = [""] * len(_PERM)
    for i, ch in enumerate(arg):
        for j, v in enumerate(_PERM):
            if v == i + 1:
                out[j] = ch
    return "".join(out)


def _hex_xor(a: str, b: str) -> str:
    return "".join(format(int(a[i:i + 2], 16) ^ int(b[i:i + 2], 16), "02x")
                   for i in range(0, min(len(a), len(b)), 2))


def solve_challenge(html: str) -> str | None:
    m = re.search(r"arg1\s*=\s*'([0-9A-Fa-f]+)'", html)
    if not m:
        return None
    return _hex_xor(_unsbox(m.group(1)), _KEY)


def _set_cookie(s, url, val):
    """把 `acw_sc__v2` 写到该 url 的主域上（裸域 + 上一级都要，蓝奏云会跨域跳）。"""
    host = urlparse(url).netloc.split(":")[0]
    s.cookies.set("acw_sc__v2", val, domain=host)
    parts = host.split(".")
    if len(parts) >= 2:
        s.cookies.set("acw_sc__v2", val, domain="." + ".".join(parts[-2:]))


def get_solved(s, url, *, referer=None, timeout=60, tries=3):
    """GET 一个 url；返回体若还是 JS 挑战就解掉再取（蓝奏云每个域各发一次）。

    ★ 踩过的坑：下载域（`developer4.lanrar.com`）与主站**不是同一个 cookie 域**，
      直接拿链接 GET 会**再拿到一次挑战页**（4 KB 的 HTML 被当成文件存下来）。
    """
    hdrs = {"Referer": referer} if referer else {}
    r = None
    for i in range(tries):
        r = s.get(url, headers=hdrs, timeout=timeout)
        val = solve_challenge(r.text[:20000]) if r.text[:40].lstrip().startswith(("<", "\n", " ")) or "arg1" in r.text[:20000] else None
        if not val:
            return r
        print(f"     ↻ 第 {i+1} 次遇到 JS 挑战 -> 解掉重试（{urlparse(url).netloc}）")
        _set_cookie(s, url, val)
    return r


def main(argv):
    url = argv[0]
    out = argv[1] if len(argv) > 1 else "."
    pwd = argv[2] if len(argv) > 2 else ""
    os.makedirs(out, exist_ok=True)
    host = re.match(r"https?://([^/]+)", url).group(1)

    s = requests.Session()
    s.proxies = PROXY
    s.headers.update({"User-Agent": UA, "Referer": url})

    r = s.get(url, timeout=40)
    r.encoding = "utf-8"
    print(f"  ① 首页 {r.status_code} · {len(r.text)} 字符")
    val = solve_challenge(r.text)
    if val:
        s.cookies.set("acw_sc__v2", val, domain=f".{host.split('.', 1)[1]}")
        r = s.get(url, timeout=40)
        r.encoding = "utf-8"
        print(f"  ② 解挑战后再取 {r.status_code} · {len(r.text)} 字符")
    else:
        print("  （没挑战，直接继续）")

    page = r.text
    iframe = re.search(r'<iframe[^>]+src=["\']([^"\']+)', page)
    ref = url
    if iframe:
        src = iframe.group(1)
        if src.startswith("/"):
            src = f"https://{host}{src}"
        print(f"  ③ iframe -> {src}")
        r = s.get(src, timeout=40)
        r.encoding = "utf-8"
        page = r.text
        ref = src
        print(f"     iframe 页 {r.status_code} · {len(page)} 字符")

    # ★ 2023+ 新 API：页面里给 wp_sign / ajaxdata / domain2，POST ajaxfile.php 换真链
    m_wp = re.search(r"var\s+wp_sign\s*=\s*'([^']*)'", page)
    m_aj = re.search(r"var\s+ajaxdata\s*=\s*'([^']*)'", page)
    m_d1 = re.search(r"var\s+domain1\s*=\s*'([^']*)'", page)
    m_d2 = re.search(r"var\s+domain2\s*=\s*'([^']*)'", page)
    m_kd = re.search(r"var\s+kdns\s*=\s*(\d+)", page)
    m_ki = re.search(r"typeof\(killdns\)\s*==\s*'undefined'", page)
    if m_wp and m_aj and m_d2:
        kdns = 0 if m_ki else int(m_kd.group(1) if m_kd else 1)
        api = m_d2.group(1)
        print(f"  ④ 新 API：POST {api}  (wp_sign 有 · ajaxdata={m_aj.group(1)!r} · kdns={kdns})")
        r3 = s.post(api, data={"action": "downprocess", "websignkey": m_aj.group(1),
                               "signs": m_aj.group(1), "sign": m_wp.group(1),
                               "websign": "", "kd": kdns, "ves": 1},
                    headers={"Referer": ref, "X-Requested-With": "XMLHttpRequest",
                             "Origin": f"https://{host}"}, timeout=60)
        print(f"     {r3.status_code}: {r3.text[:200]}")
        j = r3.json()
        # ★ `zt` 有的接口回 int 1、有的回字符串 "1" ⇒ 一律按整数比（踩过一次）
        if int(j.get("zt") or 0) != 1:
            print(f"  ✗ 蓝奏云拒绝：{j.get('inf')}")
            return 3
        dom = str(j.get("dom") or "") or (
            "https://developer2oss.lanzouc.com:661" if kdns == 0 else "")
        if not dom:
            print("  ✗ 没拿到下载域"); return 4
        link = f"{dom}/file/{j['url']}&toolsdown"
        print(f"  ⑤ 真实下载地址 -> {link[:90]}…")
        return _fetch(s, link, out, j.get("inf") or "")

    # 老 API 兜底
    m_sign = (re.search(r"'sign'\s*:\s*'([^']+)'", page)
              or re.search(r'"sign"\s*:\s*"([^"]+)"', page))
    print(f"  ④ 老 API：sign={'有' if m_sign else '没有'}")
    if not m_sign:
        print("  ✗ 两条路都没解析出来。可见文本片段：")
        t = re.sub(r"<(script|style).*?</\1>", " ", page, flags=re.S)
        t = re.sub(r"<[^>]+>", " ", t)
        print("     " + re.sub(r"\s+", " ", t).strip()[:400])
        return 2

    api = f"https://{host}/ajaxm.php"
    r3 = s.post(api, data={"action": "downprocess", "websign": "", "websignkey": "",
                           "ves": "1", "sign": m_sign.group(1)},
                headers={"Referer": ref, "X-Requested-With": "XMLHttpRequest"}, timeout=40)
    print(f"  ⑤ ajaxm {r3.status_code}: {r3.text[:200]}")
    j = r3.json()
    if j.get("zt") != 1:
        print(f"  ✗ 蓝奏云拒绝：{j.get('inf')}")
        return 3
    return _fetch(s, j["dom"] + "/file/" + j["url"], out, j.get("inf") or "")


def _fetch(s, link, out, hint_name):
    """下真身：先解可能出现的挑战页，再落盘；文件名优先取 `Content-Disposition`。"""
    r = get_solved(s, link, referer=link.split("/file/")[0] + "/", timeout=300)
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    fname = (m.group(1) if m else "") or hint_name
    if not fname:
        fname = os.path.basename(urlparse(link).path.split("&")[0]) or "lanzou_download.bin"
    if "." not in fname:
        # 从最终 URL 的 Content-Type 猜个后缀，避免存成 .bin
        ct = (r.headers.get("Content-Type") or "").lower()
        ext = {"audio/midi": ".mid", "audio/x-midi": ".mid", "application/octet-stream": ""}.get(ct, "")
        fname = "lanzou_download" + (ext or ".bin")
    dst = os.path.join(out, fname)
    with open(dst, "wb") as fh:
        fh.write(r.content)
    n = len(r.content)
    head = r.content[:16]
    print(f"  ✓ 落盘 {dst}（{n/1048576:.2f} MB · 头 {head.hex()[:24]}）")
    if head[:4] == b"MThd" or head[:4] == b"RIFF" or head[:3] == b"ID3" or head[:4] == b"OggS":
        print("     文件头看起来是对的 ✔")
    else:
        print("     ⚠ 文件头不是常见音频/MIDI 魔数 —— 可能还是网页，检查一下")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
