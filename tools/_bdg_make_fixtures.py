# -*- coding: utf-8 -*-
"""生成 `tests/fixtures/bdg/` 的合成 fixture（可重复生成，别手改产物）。

    python tools\\_bdg_make_fixtures.py            # 生成/刷新
    python tools\\_bdg_make_fixtures.py --from <real.bdg>   # 用真实工程当种子

产出的每个文件都用 **`json.dumps(indent=2, ensure_ascii=False)`** 写盘
（= 宿主 `JSON.stringify(p, null, 2)`），所以 `parse → emit` 往返必须**逐字节一致**。
"""

from __future__ import annotations

import json
import os
import sys

_HOME = os.path.expanduser("~")                                #: 用户目录

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

FIX_DIR = os.path.join(_ROOT, "tests", "fixtures", "bdg")
SEED = os.path.join(FIX_DIR, "v2_real_electric_hornet.bdg")
# 第一次生成时的真实种子（用户提供的 electric hornet 工程）
SEED_SRC = (_HOME + r"\.dsh\attachments\v1\files\66"
            r"\66df1f655f240c069033dba2fe3d76df6d479f99db0ff8ca89258bdc41b05920"
            r"\untitled.bdg")


def dump(path, obj):
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    with open(path, "wb") as f:
        f.write(txt.encode("utf-8"))
    print(f"  {os.path.basename(path):<38} {len(txt.encode('utf-8')):>8} bytes")


# ---------------------------------------------------------------- 脱敏
def desensitize(raw):
    """换掉名字类字段；`audioMd5` 保留（它是哈希，用来校验音频身份）。"""
    out = json.loads(json.dumps(raw, ensure_ascii=False))
    out["name"] = "fixture_real"
    out["audioName"] = "fixture_real.ogg"
    for i, t in enumerate(out.get("tracks", [])):
        t["name"] = f"T{i + 1}"
    return out


# ---------------------------------------------------------------- 字段改名
RENAMES = {
    "tracks": "lanes",
    "markers": "points",
    "bpmPoints": "tempoPoints",
    "baseBpm": "bpm",
    "offsetMs": "offset",
    "id": "uid",
    "trackId": "lane",
    "beat": "position",
    "parentId": "parent",
    "attrs": "props",
}
LOOP_RENAMES = {"interval": "step", "count": "times", "exclude": "skip"}


def rename_all(obj):
    """把所有字段名换成同类里的**第二候选**（验证别名表不是摆设）。"""
    if isinstance(obj, list):
        return [rename_all(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        nk = RENAMES.get(k, k)
        if k == "loop" and isinstance(v, dict):
            v = {LOOP_RENAMES.get(kk, kk): vv for kk, vv in v.items()}
        out[nk] = rename_all(v)
    return out


# ---------------------------------------------------------------- 主流程
def main(argv):
    src = SEED
    if "--from" in argv:
        src = argv[argv.index("--from") + 1]
    if not os.path.exists(src) and os.path.exists(SEED_SRC):
        src = SEED_SRC
    if not os.path.exists(src):
        print(f"[!] 找不到种子工程 {src}")
        return 1
    os.makedirs(FIX_DIR, exist_ok=True)
    with open(src, "rb") as f:
        real = json.loads(f.read().decode("utf-8"))

    des = desensitize(real)

    print("[1] v2 真实工程（脱敏）")
    dump(os.path.join(FIX_DIR, "v2_real_electric_hornet.bdg"), des)

    print("[2] v2 字段全改名（别名表真的生效？）")
    dump(os.path.join(FIX_DIR, "v2_renamed.bdg"), rename_all(des))

    print("[3] v3 未来格式（未知版本 + 多包一层 + 未知字段）")
    fut = json.loads(json.dumps(des, ensure_ascii=False))
    fut["version"] = 3
    fut["uiState"] = {"zoom": 1.5, "scroll": 0.0}          # 未知顶层字段
    for t in fut["tracks"]:
        t["soloed"] = False                                # 未知轨字段
    for m in fut["markers"][:5]:
        m["velocity"] = 0.8                                # 未知点字段
    dump(os.path.join(FIX_DIR, "v3_future.bdg"),
         {"schema": "bdg-next", "project": fut, "extra": {"savedAt": 0}})

    print("[4] v2 缺字段（默认值路径 + 报告要记「用了默认」）")
    tiny = {
        "app": "beat-data-generator",
        "version": 2,
        "tracks": [
            {"id": "t1"},
            {"id": "t2", "name": "有名字", "type": "bridge:sub", "hidden": True},
        ],
        "markers": [
            {"id": "m1", "trackId": "t1", "beat": 0.0},
            {"id": "m2", "trackId": "t1", "beat": 1.5},
            {"id": "m3", "trackId": "t2", "beat": 2.0},
            {"trackId": "t1", "beat": "3.25"},             # 无 id，字符串拍位
        ],
    }
    dump(os.path.join(FIX_DIR, "v2_missing.bdg"), tiny)

    print("[5] 坏输入（必须优雅失败，不许抛栈）")
    with open(os.path.join(FIX_DIR, "broken_truncated.bdg"), "wb") as f:
        f.write(b'{"app":"beat-data-generator","version":2,"tracks":[{"id":"t1"')
    print(f"  {'broken_truncated.bdg':<38} {os.path.getsize(os.path.join(FIX_DIR, 'broken_truncated.bdg')):>8} bytes")
    dump(os.path.join(FIX_DIR, "broken_object.bdg"), {})
    dump(os.path.join(FIX_DIR, "broken_list.bdg"), [])
    dump(os.path.join(FIX_DIR, "broken_shape.bdg"), {"foo": [1, 2, 3], "bar": {"x": 1}})

    print("\n完成。收新 fixture 时先跑: python tools\\_bdg_probe.py <file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
