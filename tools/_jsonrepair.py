"""宽松 JSON 解析 —— 专门对付 ADOFAI 编辑器/手工编辑写出来的坏 JSON。

已知三种毛病（按出现频率）：

① **尾逗号**：`[1, 2, ]` / `{"a": 1, }`
② **裸控制字符**：字符串里直接塞 \r \n \t（`json.loads(..., strict=False)` 能收）
③ **相邻成员/元素之间少逗号**：`... ]\r\n "decorations": [`、`} {`、`1 2`

③ 是导致「EX 语料 28 张解析失败」的真凶（那些文件是有人手改过的）。
修法：扫一遍 token，遇到值的起点时看前一个有效字符 —— 该有逗号没逗号就补上。
判断「是不是键」靠向后看：字符串后面跟 `:` 就是键，不补。

    python tools/_jsonrepair.py <文件或目录>      # 自测
"""
from __future__ import annotations

import json
import os
import re

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

#: 语料目录（第三方谱面，**不入库** —— 见 EXTERNAL_ASSETS.md）。
#: 用环境变量 `ADOFAI_CORPUS` 指定；没设就退回 <仓库根>/corpus_tuf。
CORPUS = os.environ.get("ADOFAI_CORPUS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus_tuf")

_WS = " \t\r\n\x0b\x0c"
_NUM_START = set("0123456789-")


def _scan_string(txt: str, i: int) -> int:
    """i 指向开引号，返回闭合引号的下一位置。"""
    n = len(txt)
    j = i + 1
    esc = False
    while j < n:
        c = txt[j]
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif c == '"':
            return j + 1
        j += 1
    return n


def repair(txt: str) -> str:
    """给坏 JSON 补逗号 + 去尾逗号。字符串内容原样保留。"""
    out: list[str] = []
    i, n = 0, len(txt)
    last = ""                       # 上一个「值结束」的字符（引号内不算）
    while i < n:
        c = txt[i]

        if c in _WS:
            out.append(c)
            i += 1
            continue

        # ---- 字符串：判键 / 判值，必要时补逗号
        if c == '"':
            end = _scan_string(txt, i)
            s = txt[i:end]
            need = False
            if last and last in "]}":
                need = True
            elif last and (last == '"' or last in _NUM_START or last in "eE"):
                k = end
                while k < n and txt[k] in _WS:
                    k += 1
                if k < n and txt[k] != ":":       # 后面不是冒号 → 不是键 → 是数组里的值
                    need = True
            if need:
                out.append(",")
            out.append(s)
            last = '"'
            i = end
            continue

        # ---- 容器起点
        if c in "{[":
            if last and (last in "]}" or last == '"' or last in _NUM_START):
                out.append(",")
            out.append(c)
            last = c
            i += 1
            continue

        # ---- 数字起点
        if c in _NUM_START:
            if last and last in "]}":
                out.append(",")
            out.append(c)
            last = c
            i += 1
            continue

        # ---- 字面量 true/false/null 的起点
        if txt.startswith(("true", "false", "null"), i) and (
                last and (last in "]}" or last == '"' or last in _NUM_START)):
            out.append(",")
            last = "e"
            i += 1
            continue

        out.append(c)
        last = c
        i += 1

    t = "".join(out)
    t = re.sub(r",(\s*[}\]])", r"\1", t)          # 尾逗号
    t = re.sub(r",(\s*,)+", ",", t)               # 重复逗号
    return t


def loads_lenient(txt: str):
    """能严格解析就严格解析，不行再修补。返回 (obj, kind)。"""
    try:
        return json.loads(txt), "strict"
    except Exception:                                          # noqa: BLE001
        pass
    try:
        return json.loads(txt, strict=False), "lenient"
    except Exception:                                          # noqa: BLE001
        pass
    return json.loads(repair(txt), strict=False), "repaired"


def _read_text(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:                                      # noqa: BLE001
            continue
    return raw.decode("utf-8", "replace")


def load(path: str):
    """读文件并宽松解析。返回 (obj, kind)。"""
    return loads_lenient(_read_text(path))


if __name__ == "__main__":
    import sys
    args = sys.argv[1:] or [CORPUS]
    import collections
    for a in args:
        files = []
        if os.path.isdir(a):
            for dp, _d, fs in os.walk(a):
                files += [os.path.join(dp, f) for f in fs
                          if f.lower().endswith(".adofai")]
        else:
            files = [a]
        c = collections.Counter()
        bad = []
        for p in files:
            try:
                _obj, k = load(p)
                c[k] += 1
            except Exception as e:                             # noqa: BLE001
                c["fail"] += 1
                bad.append((p, str(e)[:90]))
        print(f"{a}: {dict(c)}")
        for p, e in bad[:10]:
            print("   FAIL", e, "|", p[-70:])
