"""`pathData` 解码 —— ADOFAI 旧格式（version < 5）的谱面。

权威实现：`_decomp\\game\\ADOFAI\\FloorHelper.cs`
    MigratePathData()      : angleData[i] = 查表(pathData[i])
    TryGetPathInDegrees()  : 24 个方向 + '!' = 999(midspin)
`LevelData.Decode()` 里 `isOldLevel` 就走这条路：
    angleData = new List<float>(FloorHelper.MigratePathData(pathData))

也就是说 **pathData 的每个字符直接就是一个 angleData 值**，不是增量。

我们从语料里一直**静默跳过**这类谱（`angleData` 为空 → 被当成"太小"扔掉），
包括 `SKY BOX CUBE` 和 `1-EX A Dance of Fire and Ice`。
"""
from __future__ import annotations

#: 字符 → 角度（度）。按角度排序：
#:   0=R 15=p 30=J 45=E 60=T 75=o 90=U 105=q
#: 120=G 135=Q 150=H 165=W 180=L 195=x 210=N 225=Z
#: 240=F 255=V 270=D 285=Y 300=B 315=C 330=M 345=A
PATH_TABLE: dict[str, float] = {
    "R": 0.0, "p": 15.0, "J": 30.0, "E": 45.0,
    "T": 60.0, "o": 75.0, "U": 90.0, "q": 105.0,
    "G": 120.0, "Q": 135.0, "H": 150.0, "W": 165.0,
    "L": 180.0, "x": 195.0, "N": 210.0, "Z": 225.0,
    "F": 240.0, "V": 255.0, "D": 270.0, "Y": 285.0,
    "B": 300.0, "C": 315.0, "M": 330.0, "A": 345.0,
    "!": 999.0,                      # midspin
}

#: 更老的格式里这些字符是「相对上一格的角度增量」（MigratePathData 的 _ 分支）
LEGACY_DELTA: dict[str, float] = {
    "5": 72.0, "6": -72.0, "7": 52.0, "8": -52.0, "9": -30.0,
    "h": 120.0, "j": -120.0, "t": 60.0, "y": 300.0,
}


def migrate(path_data: str) -> list[float]:
    """pathData → angleData（度）。和游戏完全一致。"""
    out: list[float] = []
    prev = 0.0
    for c in path_data:
        if c in PATH_TABLE:
            a = PATH_TABLE[c]
        else:
            a = prev + LEGACY_DELTA.get(c, 0.0)
        out.append(a)
        prev = a
    return out


def angle_data_of(obj: dict) -> tuple[list[float], str]:
    """从已解析的谱面 dict 里取 angleData。

    返回 (角度列表, 来源)。来源 = 'angleData' / 'pathData' / 'none'。
    `angleData` 里夹 null 的（有导出工具会写坏）会把坏项剔掉。
    """
    a = obj.get("angleData")
    if isinstance(a, list) and a:
        good = [float(x) for x in a
                if isinstance(x, (int, float)) and x == x]
        if good:
            src = "angleData" if len(good) == len(a) else "angleData(脏)"
            return good, src
    p = obj.get("pathData")
    if isinstance(p, str) and p:
        return migrate(p), "pathData"
    return [], "none"


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _jsonrepair import load  # noqa: E402

    for path in sys.argv[1:]:
        o, k = load(path)
        a, src = angle_data_of(o)
        print(f"{os.path.basename(path):<24} 解析={k:<8} 来源={src:<10} 格数={len(a)}")
        if a:
            print(f"   前 40 个角度：{a[:40]}")
