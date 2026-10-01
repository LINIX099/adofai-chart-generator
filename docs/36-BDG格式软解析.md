# 36 · BDG 格式**软解析**（面向格式会变的设计）

> 用户 2026-10：「他的保存格式**后续可能修改**。我们需要考虑**软编码格式解析**
> 来方便后续维护。」
>
> 本文 = 这一层的设计。**不改任何现有代码**，只定规矩——
> 但规矩要在 `core/bdg.py` **第一次落笔时**就照它写，否则以后补不上。

***

## 0. 一句话

**把「格式」从代码里抽出来变成一张数据表 + 一层容错取值器**：
上游改格式 ⇒ **改表（加几行）**，不改逻辑；
上游加了我们没见过的字段 ⇒ **无视**；
上游删了我们依赖的字段 ⇒ **用默认值 + 报警**；
任何"猜"过的地方 ⇒ **写进解析报告，让人看得见**。

***

## 1. 五条铁律

| # | 铁律 | 反面（要避免的写法） |
|---|---|---|
| 1 | **永不因未知字段失败**（向前兼容） | `for k in data: …` 把未知键也当数据 |
| 2 | **永不因缺字段失败**（向后兼容） | `data["markers"]` 直接下标 |
| 3 | **不信任 `version`**，用**能力探测**决定走哪条路；`version` 只用于报告与协商 | `if version == 3: …` 散落在各处 |
| 4 | **原文保留**：写回时改子树，未知字段/未知轨道原样回去 | 写回时 `json.dump(重建的对象)` |
| 5 | **一切假设都要能看见**：解析产出一份 `ParseReport` | 静默用默认值 |

> 第 5 条是我们这个项目一贯的口径（双押 `lost` 原因、Δ 预算超支 —— **不许静默**）。

***

## 2. 模块结构

```
core/bdg/
  __init__.py    # 对外只暴露 parse() / emit() / ParseReport
  aliases.py     # ★ 纯数据表：概念 → 候选路径（唯一需要跟着上游改的地方）
  coerce.py      # 容错取值：pick / as_float / as_beat / as_time_ms / one_or_many
  model.py       # 规范化中间模型（我们的口径）
  report.py      # ParseReport：命中的别名 / 用了默认 / 丢了什么 / 哪里是猜的
  probe.py       # 能力探测（caps）+「字段形状指纹」（tools/_bdg_probe.py 用它）
  parse.py       # raw dict → 规范化模型（版本适配 + 调 expand）
  expand.py      # loop / parentId 展开（语义已实测确认，独立模块好单测）
  emit.py        # 写回（passthrough 保留未知字段）
```

**依赖方向**（禁止反向）：

```
model ← coerce ← aliases
  ↑
report
  ↑
parse → expand
  ↑
emit（只依赖 model + report 里记下的键名）
```

**依赖方向**：`parse → aliases + coerce + model`。
**除 `aliases.py` 外，其余文件都不该出现任何字段名字面量**（可以用一条 lint/单测守住，见 §8）。

***

## 3. 别名表（`aliases.py`）

```python
# 概念 → 候选路径（按优先级；支持 dotted path）
ROOT_APP      = ["app", "type", "format"]
ROOT_VERSION  = ["version", "formatVersion", "v"]
TRACKS        = ["tracks", "markerTracks", "lanes"]
MARKERS       = ["markers", "points", "events", "beats"]
BPM_POINTS    = ["bpmPoints", "tempoPoints", "tempo", "bpmEvents"]
AUDIO_NAME    = ["audioName", "audio", "audioFile", "songFilename"]
AUDIO_MD5     = ["audioMd5", "audioHash", "audioMd5sum"]
BASE_BPM      = ["baseBpm", "bpm", "tempo"]
OFFSET_MS     = ["offsetMs", "offset"]

TRACK_ID      = ["id", "uid", "key"]
TRACK_NAME    = ["name", "title", "label"]
TRACK_TYPE    = ["type", "kind", "role"]
TRACK_HIDDEN  = ["hidden", "muted", "disabled"]

MARK_ID       = ["id", "uid", "key"]
MARK_TRACK    = ["trackId", "track", "lane", "laneId"]
MARK_BEAT     = ["beat", "position", "pos", "t"]
# ★ 可选覆盖：实测 v2 **没有**这个字段（timeMs 是 timeOfBeat(beat) 现算的），
#   但上游将来很可能真的落一个时间戳。有就用它，没有就回落到 map 换算。
MARK_TIME     = ["timeMs", "time_ms", "time", "ms"]
MARK_LOOP     = ["loop", "repeat", "loopConfig"]
MARK_PARENT   = ["parentId", "parent", "ownerId"]
MARK_ATTRS    = ["attrs", "attributes", "data", "props"]

LOOP_INTERVAL = ["interval", "step", "gap", "period"]
LOOP_COUNT    = ["count", "times", "repeats", "n"]
LOOP_EXCLUDE  = ["exclude", "skip", "excludeIndices", "except"]

BPM_BEAT      = ["beat", "position"]
BPM_MODE      = ["mode", "type", "kind"]
BPM_VALUE     = ["value", "bpm", "multiplier", "amount"]
```

**规矩**：这张表是**唯一**允许跟着上游改的地方。加一个新版本，就是在这里加候选路径
（**不是**在 `parse.py` 里写适配分支）。

***

## 4. 容错取值器（`coerce.py`）

```python
MISSING = object()

def pick(obj, paths, default=MISSING):
    """按候选路径取值；返回 (值, 命中的路径)。命中路径要记进 report。"""

def one_or_many(x):
    """单对象 → [x]。上游常在版本间把「一个」和「多个」改来改去。"""

def as_float(x, default=0.0) -> float     # "120" → 120.0；None → default
def as_int(x, default=0)   -> int
def as_str(x, default="")  -> str
def as_bool(x, default=False) -> bool     # "true"/1/"yes" → True

def as_beat(x, default=0.0) -> float
    """数字直接用；也认 "17.25" / "17:2" / {bar,beat} / {bar:5,beat:2}。"""

def as_time_ms(x, default=0.0) -> float
    """数字；或 {ms:…}/{timeMs:…}；或 "00:01.234"。"""
```

**全部不抛异常**：失败 → 返回 `default` **并记进 report**（哪条路径、原值是什么）。
外部数据用异常控制流是反模式。

***

## 5. 能力探测（替代 version 判断）

```python
caps = {
    "loop":        any(pick(m, MARK_LOOP, default=None) for m in markers),
    "typedTracks": any(pick(t, TRACK_TYPE, default=None) for t in tracks),
    "attrs":       any(pick(m, MARK_ATTRS, default=None) for m in markers),
    "bpmPoints":   bool(bpm_points),
    "notes":       bool(notes),
}
```

- **走哪条路以 `caps` 为准**，`version` 只写进报告；
- 若**连 `tracks`/`markers` 都找不到**（形态整个变了）⇒ 进 **generic 兜底**：
  递归找「带 beat 的对象列表」，能救多少救多少，**并强警告**（不是静默）。

***

## 6. 版本适配器 + 协商

```python
ADAPTERS = {2: AdapterV2}                # 已知版本 → 适配器

def parse(raw):
    rep = ParseReport()
    ver = as_int(pick(raw, ROOT_VERSION, default=0))
    ad = ADAPTERS.get(ver)
    if ad is None:
        ad = ADAPTERS["generic"]
        rep.warn(f"未知格式版本 {ver} ⇒ generic 兜底（已尽力解析，请核对）")
    return ad(raw, rep)
```

- 新增上游版本 = **`aliases.py` 加行**（多数情况）+ 必要时加一个 `AdapterVN`；
- **禁止**在 `parse.py` 里散落 `if version == N:`。

**WS 侧同样**：`hello` 里带对端的 `format/version/caps`，
我们回一个 `accepted` 区间；**超出就 warn，不拒**（沟通成本最低）。

***

## 7. 写回（passthrough，`emit.py`）

```python
out = deepcopy(raw)                       # ★ 原文全留
out[tk.tracks_key]  = 新 tracks            # ★ 用**解析时命中的键名**，不硬写 "tracks"
out[tk.markers_key] = 新 markers
out[tk.bpm_key]     = 新 bpm_points
# notes / 颜色 / locked / 未知顶层键 —— 一个都不动
```

- 解析时把**实际命中的键名**记在 `ParseReport` 上（`tracks_key="lanes"`），写回照抄；
- **兜底模式（generic）下禁止写回**，只读，并明说理由
  （宁可不写，也不要写出一份让上游读不懂的工程）。

***

## 8. 测试策略（这一层能不能立住全靠它）

`tests/fixtures/bdg/`：

| fixture | 造法 | 守住什么 |
|---|---|---|
| `v2_real_*.bdg` | 真实工程（脱敏） | 「今天能解」，且**别名表每条都命中** |
| `v2_renamed.bdg` | 字段改名：`tracks→lanes`、`beat→position`、`loop.interval→loop.step` | **别名表真的生效**（不是摆设） |
| `v3_future.bdg` | 未知版本号 + 未知字段 + **多包一层** `{project:{…}}` | **不炸 + 报警 + 尽力解析** |
| `v2_missing.bdg` | 缺 `bpmPoints` / 缺 `name` / 缺 `type` | 默认值路径 + report 里记「用了默认」 |
| `garbage.bdg` | `{}` / `[]` / 半截 JSON | **优雅失败**：返回带 `error` 的报告，不是抛栈 |

`tests/test_bdg_parse.py` 三组断言：

1. **解析**：每个 fixture 解出的 `(tracks, points, bpm)` 与期望一致；
2. **往返**：`parse → emit` 后与原文**除被改动的子树外逐字节一致** ⇒ 守住 passthrough；
3. **表/码不脱节**：扫描 `core/bdg/*.py`（除 `aliases.py`），
   **禁止出现字段名字面量** ⇒ 防止有人绕过表直接硬写。

**诊断工具** `tools/_bdg_probe.py <file.bdg>`：
打印「字段形状指纹」（顶层键 / 每个列表的元素键集合 / 值样例 / 探测到的能力 / 解析报告）。
**收新 fixture 时先跑它。**

***

## 9. 与既有东西的关系

| | 关系 |
|---|---|
| **WS 桥**（`docs/35` §3） | `project` 消息与 `.bdg` 文件**走同一个 `parse()`**；只是来源不同 |
| **我们的内部模型** | 解析结果落成 `Track/Point` 规范化模型，**下游只认它**，永不认 `.bdg` 形状 |
| **溯源** | `chart.meta["source"] = {kind:"bdg", version, parser, unknown_keys}` ⇒ 出问题时一眼看出「这份谱从哪来、解析器认不认」 |
| **`docs/34` 分段采音** | 角色来自 `track.type`（`docs/35` §3.6），而 `type` 的值也由**别名表**解析 ⇒ 上游改 `type` 命名不影响我们 |

***

## 10. 明确不做的事

- ❌ 不做「格式嗅探猜版本」的玄学 —— 只用**候选路径 + 能力探测**，命中什么写进报告；
- ❌ 不做「自动修复写入」（会把用户的工程改坏）；
- ❌ 不 fork 宿主、不读它的 TypeScript 类型做代码生成 —— **只按概念解析**。

> 一句话收束：**我们依赖的是「概念」（拍 / 轨 / 环 / 变速 / 属性），
> 而不是「字段」。概念的名字可以换，概念本身不能。**

***

## 11. ★ 真实工程实测（`electric hornet`，866 点 / 6 轨）

样本：用户给的 `untitled.bdg`（114 KB，`app="beat-data-generator"`, `version=2`）。
**这份实测同时验证了软解析的必要性，也照出了两个设计错误。**

### 11.1 顶层形状：**没有未知字段**

```
app="beat-data-generator"  version=2  name="electric hornet"
baseBpm=192  offsetMs=1325  audioName="electric hornet.ogg"
audioMd5="4dadac0b…"  bpmLocked=False
tracks[6]  markers[866]  bpmPoints[1]  notes[0]
```

⇒ 今天的格式**是干净的**。软解析不是为今天写的，是**为明天写的**
⇒ 所以 §8 那条「**必须合成 future fixture**」不是可选项，是**唯一**的验证手段。

### 11.2 ★ `loop` / `parentId`：语义**完全确认**

92 个母点（带 `loop`），391 个子点（带 `parentId`）。

- **`interval` 单位 = 拍**，取值有 `0.125 / 0.25 / 0.5 / 0.6666 / 1 / 1.33 / 4` ——
  ★ 注意 **`0.6666` 和 `1.33` 是"手打的近似值"**（不是 2/3、4/3 的精确分数）
  ⇒ **不许假设 `interval` 是整齐分数**；
- **`exclude` 就是 `k` 本身**（`k ∈ [1, count]`）：实测 4 组带 `exclude` 的母点，
  「缺失的 k」与 `exclude` **逐一相等**；
- **`子点数 = count − |exclude|`：92/92 全中**；
- **`parentId` 完整性满分**：391 个子点全部指向**存在且带 `loop` 的母点**；
  母点自己**从不带 `parentId`**；没有悬空引用。

⇒ 展开逻辑可以写得很干净（`docs/35` §3.7），**不需要防御性猜测**。

### 11.3 ★★ 发现一：`beat` **不在任何吸附网格上**（软解析/桥的硬事实）

**866/866 个 beat 都不是 0.25 的倍数**，连一个整数拍都没有：

```
beat 抽样： 0.0064 · 1.0064 · 3.0064 · 1.91265 · 3.97515 …（范围 0.0064 ~ 423.5064）
分母分布：  1/625 ×438 · 1/1250 ×228 · 1/2500 ×168 · 1/1875 ×18 · …
```

而 `baseBpm=192` ⇒ **1 拍 = 312.5 ms**，`offsetMs = 1325`。
`0.0064 × 312.5 = 2.0 ms` ⇒ **`beat` 其实就是「用 192BPM 平铺 map 编码的毫秒」**。

**三条结论**（都影响设计）：

1. **不许假设 beat 是整齐的**（没有网格、没有整数）⇒ 换算全程 `float`，
   别做任何 `round`；
2. **`timeOfBeat`/`beatOfTime` 在段内互逆** ⇒ 用宿主的 map 换算
   **能精确还原毫秒**，两边不必共用同一张表（→ `docs/35` §3.4 的更正）；
3. **存在"不吸附的写入路径"** —— `addMarker` 要么 `snapBeat` 到 0.25 网格、
   要么 `Math.round`，**两者都产不出 0.0064**。所以这些点来自别处
   （导入 / `moveMarker` / 旧版本）⇒ **待用户确认是哪条**（`docs/35` §6.2）。

### 11.4 ★★ 发现二：**两套 BPM 模型并存，实锤**（推翻我一个设计）

```
宿主 bpmPoints : [ {beat: 100, mode: "mult", value: 1} ]        ← ★ 是个 no-op
插件 BPM 轨     : 2 个 marker，attrs={speedType:"multiplier", value:2}
                  @ beat 8.0064 / 64.0064                        ← 真正的变速在这
```

⇒ **宿主的 `bpmPoints` 是空转的，真实变速只在插件自己的类型化轨上。**

⚠️ 这一条直接推翻了我原来在 `docs/35` §3.4 写的
「**把我们的 tempo 表写进宿主的 `bpmPoints`**」——
因为 `timeMs = timeOfBeat(beat)` 是 `baseBpm/offsetMs/bpmPoints` 的函数，
**改它就等于把他工程里所有点集体平移、与音频脱钩**。
已改为：**宿主 map 只读（当换算器），我们的变速写进插件 BPM 轨**。

### 11.5 其他可复用的实测事实

| 事实 | 对解析的含义 |
|---|---|
| **marker 有 4 种键组合**（`{beat,id,trackId}` / `+parentId` / `+loop` / `+attrs`） | ★ 记录**稀疏且多变** ⇒ 必须 `缺省即默认`，绝不下标 |
| **track 有 2 种**：普通 `{id,name,color,hidden}`（4 条）；类型化 `{id,name,color,type}`（2 条，**没有 `hidden`**） | `locked`/`hidden`/`type` **全可选** |
| **空轨照样存在**（`ADOFAI 旋转轨道` 0 个点） | 空列表必须容忍 |
| **232 / 866 是重复 beat** | 同拍多点（双押/和弦）是常态 ⇒ **beat 不唯一** |
| **`attrs` 只出现在类型化轨的点上** | 类型化轨的点**也在这同一个 `markers` 数组里** |
| `notes: []` | 便签未使用；保留 passthrough 即可 |
| 文件里恰好按 beat 有序 | **但不要依赖顺序**（解析时自己排） |

### 11.6 修正后的模块划分（推荐给 v0.4）

```
core/bdg/
  aliases.py     # ★ 唯一允许出现字段名的地方（§3 那张表）
  coerce.py      # 容错取值：pick/one_or_many/as_float/as_beat/as_time_ms
  probe.py       # 能力探测（caps）+「字段形状指纹」
  parse.py       # raw dict → 规范化模型（含版本适配、loop 展开）
  expand.py      # ★ 新增：loop/parentId 展开（§11.2 已确认，独立成模块好单测）
  emit.py        # 规范化模型 → raw dict（passthrough，见 §7）
  report.py      # ★ 新增：ParseReport（命中的别名/默认值/丢弃/猜测/警告）
  model.py       # 规范化模型本身（Track/Point/BpmPoint/Source）
```

新增两个模块的理由：

- **`expand.py`**：循环展开有**明确语义**（`k=1..count` 跳过 `exclude`）且
  **很容易写错一处就整体错位** ⇒ 必须能被单测单独钉住，不要混在 `parse.py` 里；
- **`report.py`**：报告是这个设计能维护下去的**唯一保障**（铁律 5）。
  它要能回答四个问题：**命中了哪些别名 / 哪里用了默认 / 丢了什么 / 哪里是猜的**。

**依赖方向**（禁止反向）：

```
model ← coerce ← aliases
  ↑
report
  ↑
parse → expand
  ↑
emit（只依赖 model + report 记下的键名）
```

**硬性纪律**（用单测守，见 §8 第 3 条）：
`parse.py` / `expand.py` / `emit.py` **不得出现任何字段名字面量** ——
所有 `.get("beat")`、`["markers"]` 一律走 `aliases.py` + `pick()`。
**这是"上游改格式我们只改一张表"这句话能不能成立的唯一技术保障。**

### 11.7 这个样本的第一个用途：**当第一号 fixture**

`tests/fixtures/bdg/v2_real_electric_hornet.bdg`（脱敏：换掉 `name`/`audioName`，
`audioMd5` 保留用于校验）。它能一次性守住：

- 4 种 marker 形状全部命中；
- `loop` 展开（92 母点 / 391 子点 / 4 组带 `exclude`）与 `count − |exclude|` 一致；
- `parentId` 完整性；
- 重复 beat（232 个）不被去重掉；
- 非网格 beat（`0.0064` 一族）**不被 round**；
- `tracks` 稀疏（2 条没有 `hidden`）+ 1 条空轨；
- **往返 passthrough**：`parse → emit` 与原文逐字节一致。


- ❌ 不做「格式嗅探猜版本」的玄学 —— 只用**候选路径 + 能力探测**，命中什么写进报告；
- ❌ 不做「自动修复写入」（会把用户的工程改坏）；
- ❌ 不 fork 宿主、不读它的 TypeScript 类型做代码生成 —— **只按概念解析**。

> 一句话收束：**我们依赖的是「概念」（拍 / 轨 / 环 / 变速 / 属性），
> 而不是「字段」。概念的名字可以换，概念本身不能。**
