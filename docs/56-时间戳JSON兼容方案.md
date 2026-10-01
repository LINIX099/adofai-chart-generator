# 56 · 兼容「时间戳 JSON（DEMUCS 分轨）」方案

> 规格原文已存进仓库：**`docs/refs/时间戳JSON字段说明.md`**（合作方 `adofai_diffusion`
> 的 `app/training/extract_timestamps.py` 输出）。压缩后**先读那份**，本文只讲怎么接。
>
> 用户口径 2026-10：「这是一个新的常用格式，我希望我们的**桥接器、生成逻辑**可以基于它
> 做一些兼容，**就像是现在兼容纯时间戳那样**」。
>
> 状态：**已实现（v0.4.5）** —— 落地记录见文末 **§8**（含 §6 六个决定点实际是按哪条做的）。

---

## 1. 那份 JSON 是什么（一句话）

**多路音头时间戳**：DEMUCS 把歌拆成 4~6 条分轨，每轨各跑一个检测器（神经网络踩点或
频谱通量），输出 `stems` 字典；**每一路 = 一串秒数**。

```
{ version:1, source_audio, duration_sec, sample_rate, hop_ms,
  separation_model, has_vocals, bpm_hint,
  stems: { melody:{source,method,model,onsets_sec[],onsets_frame[]},
           vocals:…, drums:…, bass:…, guitar:…, piano:… } }
```

| 关键字段 | 我们怎么用 |
| --- | --- |
| `stems.<键>.onsets_sec` | **主消费字段**：秒 → 我们内部一律用**毫秒**（×1000） |
| `stems.<键>.onsets_frame` | 只做**交叉校验**（`sec ≈ frame×hop_ms/1000`）与诊断，不当真源 |
| `stems.<键>.method/model/source` | 诊断：界面上标出来「谁检的、来自哪条分离轨」 |
| `source_audio` | ★ **自动绑定预览/导出音源**（相对 JSON 所在目录解析） |
| `duration_sec` | 谱面**尾部长度**（`max(duration×1000, 末点+4拍)`） |
| `bpm_hint` | 「基准 BPM」默认值（可空） |
| `has_vocals` | 决定有没有 `vocals` 键 —— **消费时必须判存在性** |
| `version` | schema 闸：`1` 认；其它**警告但尝试解析**（不许静默） |

★ 两处命名陷阱（文档自己都标了）：`melody` 的 `source` 是 **`other`**（不是 `melody`）；
键名**不是固定 6 个**（`--no-piano` 就没有 `piano`，无 vocals 就没有 `vocals`）。

---

## 2. 现状：我们「纯时间戳」是怎么接的（新格式照抄这套）

真源 **`core/ts_source.py`**（`session.py` 里叫 `ts_mod`）：

```
时间戳文件 ──read_ts──► [ms…] ──to_midi_like──► MidiFile（一条轨，每点一个 Note）
                                                 │
                        「选轨 → 采音 → 求解/直拟合 → 桥」**一行都不用改**
```

| 件 | 位置 | 作用 |
| --- | --- | --- |
| `TS_EXTS` | `core/ts_source.py:37` | `.txt .csv .tsv .ms .ts .json .log`（`.json` 也认，**但只在真能读出数时**） |
| `read_ts(path)` | `:96` | 一行一个数 / CSV 取末列 / `mm:ss.xxx` / JSON 数组；**取舍全记进 report** |
| `to_midi_like(ts,…)` | `:185` | 造 `MidiFile`，并挂 `mf.is_ts / grid_fit / ts_plan / ts_meta` |
| `session.load()` 分支 | `sidecar/session.py:204` | `elif ext in TS_EXTS:` → `read_ts` → `to_midi_like` |
| `info["is_ts"]` | `:284-295` | 给前端三条默认：`merge_ms=0`（**不许被合并吃掉**）/ `fit_mode=direct` / 去噪开 |
| BDG 的「建议角色」 | `:296-306` + `track_map():399-412` | `bdg_hints` → `info["bdg_roles"]` → 三条列表里带 `suggest`，**默认勾选跟着建议走** |

★ **新格式要复用的正是最后两行那套「建议角色」机制** —— 我们已经有现成的形状。

---

## 3. ★★ 开工第一件事：先堵住「静默吃垃圾」（**已实证**）

**现在**把这份新 JSON 丢进 app：`read_ts` 的 `_from_json()`（`core/ts_source.py:54-93`）
在顶层找不到已知键时会**退化成「把顶层所有数字当时间戳」**。实测：

```
读出来 -> [1.0, 5.805, 202.378, 22050.0]     ← version / hop_ms / duration_sec / sample_rate
来源标注 -> "JSON（键 t_ms/ms/time_ms/times_ms/timestamp/…）"
```

⇒ 用户会得到一张 **4 层**的垃圾谱，**而且界面显示得像成功了**。这必须在做新格式**之前**
先修（改动很小、独立可测）：

1. `_from_json()` 加**结构化黑名单**：命中 `stems` / `app` / `tracks` / `markers` /
   `bpmPoints` / `version` 就 `return None`；
2. 兜底分支（"所有顶层数字"）**收紧**：只在一个都没有上面那些键时才算数；
3. `read_ts` 失败时的文案要**说清是什么**：「这份 JSON 是**结构化文件**（有 stems/version…），
   不是一行一个数的时间戳」——不许静默。

> 这一条与 §4 无关，**可以立刻单独做**（半小时 + 一个测试）。

---

## 4. 方案：新格式怎么接

### 4.1 新增 `core/stem_json.py`（纯函数，可离线测）

```python
STEM_LABEL = {"melody":"旋律","vocals":"人声","drums":"鼓","bass":"贝斯",
              "guitar":"吉他","piano":"钢琴"}      # 认不出的键 → 用键名本身（**不丢**）

def looks_like_stem_json(raw: str) -> bool          # 顶层 dict 且有 stems（version 可选）
def read_stem_json(path) -> (stems, meta, report)   # stems = [Stem(key,label,source,method,model,sec,frame)]
def to_midi_like(stems, *, name, bpm=0.0, hint=None) -> MidiFile   # **一路一 Track**
def report_text(rep, plan) -> str                   # 人话报告（上屏）
def role_hints(stems) -> {index: "main"|"sub"|"dp"|""}             # 建议角色（§6.1 定完再写死表）
```

要点：

- **一路一轨**（不像纯时间戳那样塌成一条）⇒ 用户能像 MIDI 一样**分别勾选**哪些路当主轨/次轨/双押；
- 每点一个 Note（`pitch=60, velocity=100`）—— 与纯时间戳同一套常量；
  **不用 channel 9 冒充鼓**（那会让 `is_drum_only()` 与音高过滤自动改写行为分叉），
  鼓的身份靠 **轨道名 + method** 表达；
- 挂到 `mf` 上的接口（照抄 `ts_source`）：`mf.is_ts=True`、`mf.grid_fit`、`mf.ts_plan`、
  `mf.ts_meta`（补 `n_stems` / `stems` 摘要），**外加** `mf.is_stem_json=True`、
  `mf.stem_hints`、`mf.stem_meta`（音频名/duration/bpm_hint/version）；
- **校验项（全部记进 report，不许静默）**：
  - `version != 1` ⇒ 警告但继续；
  - `onsets_sec` 与 `onsets_frame` 长度不等 ⇒ 警告，只信 `sec`；
  - `sec` 与 `frame×hop_ms/1000` 差 > 1 帧 ⇒ 警告（列出前几个）；
  - 未排序 ⇒ **排序并计数**；重复（<1e-9）⇒ 合并并计数；负/NaN/越界 ⇒ 丢弃并计数；
  - 某一路 `onsets_sec` 为空 ⇒ 该路**不建轨**但**明确报出来**；
  - `has_vocals=true` 却没有 `vocals` 键（或反之）⇒ 警告。

### 4.2 `sidecar/session.py` 的接线（改动集中、形状照抄现有分支）

```python
STEM_EXTS = (".json",)                      # 复用 .json，靠**内容嗅探**分流
...
if ext in BDG_EXTS and looks_like_bdg(...):        # 现有：BDG 工程（JSON，有 app+markers）
elif looks_like_stem_json(raw):                    # ★ 新增，且**必须排在通用 ts 之前**
    stems, srep, smeta = stem_mod.read_stem_json(path)
    mf = stem_mod.to_midi_like(stems, name=…)
    self.stem_meta = smeta ; self.stem_hints = stem_mod.role_hints(stems)
    self.source_audio = <按 source_audio 找同目录音频>
elif ext in TS_EXTS:                               # 现有：纯时间戳
    ...
```

`info` 里新增（前端照 BDG 那套用）：

```python
info["is_stem_json"] = bool(getattr(self, "stem_meta", None))
if info["is_stem_json"]:
    info["stem"] = dict(self.stem_meta)            # version/source_audio/duration/hop/bpm_hint/stems 摘要
    info["stem_roles"] = dict(self.stem_hints)
    info["default_merge_ms"] = 0.0                 # ★ 与纯时间戳同口径（音头是"点"）
    info["default_fit_mode"] = FIT_DIRECT
    info["default_denoise_on"] = True
    info["default_tracks_checked"] = [i for i,r in hints.items() if r=="main"] or [pick]
    info["default_sub_checked"] = [...r=="sub"] ; info["default_dp_checked"] = [...r=="dp"]
    info["default_current_track"] = info["default_tracks_checked"][0]
    info["source_audio"] = <绑到的原曲路径 or "">
```

★ 与 BDG 分支**同形状** ⇒ 前端那一套（`bdg_roles` / `suggest` / `default_*_checked`）几乎照抄。

### 4.3 前端（`app/renderer/app.js`）

- 来源徽标：`来源：时间戳 JSON（DEMUCS 分轨 · N 路）`；
- 「当前文件」信息里加一张小表：`路 / source / method / model / 点数 / 时间范围 / 建议角色`；
- 三条可勾选列表：每一路都是**可选轨**（已有 `suggest` 字段的地方直接填）；
- 绑定提示：`已按 JSON 绑定原曲：xxx` / `★ JSON 里的原曲找不到：xxx`（**不许静默**）；
- `bpm_hint` 提示（见 §6.3）。

### 4.4 桥接器

**不用改**：投射/收回本来就是「按勾选 → 采音 → 按源轨分泳道」，新格式只是多了一个来源。
（若以后想让**每一路 stem 各投一条泳道**，复用 `src_tracks` 把 stem 编号带过去即可 —— 见 §7。）

### 4.5 文件对话框（`app/main.js`）

现在那一栏写的是「毫秒时间戳（一行一个数）」⇒ 改成 **「时间戳（一行一个数 / 时间戳 JSON）」**，
扩展名不变（`.json` 已在）。

---

## 5. 测试与验收

**新 fixture** `tests/fixtures/stemjson/`（都从 §7 那份规格造）：

| 文件 | 验什么 |
| --- | --- |
| `full_6stems.json` | 正常 6 路：轨数、名字、建议角色、毫秒换算 |
| `no_vocals.json` | `has_vocals=false` 且没有 `vocals` 键 ⇒ 不炸 |
| `no_piano.json` | `--no-piano` ⇒ 少一路 |
| `one_stem.json` | 单路也能出谱 |
| `empty_stem.json` | 某路空数组 ⇒ 不建轨 + **报出来** |
| `unsorted.json` | 未排序 ⇒ 排序 + 计数 |
| `dup_and_bad.json` | 重复/负/NaN ⇒ 合并或丢弃 + 计数 |
| `frame_mismatch.json` | `sec` 与 `frame` 差 >1 帧 ⇒ **警告** |
| `version_2.json` | 未知版本 ⇒ 警告但继续 |
| `not_stem.json` | **结构化但不是这个格式** ⇒ 明确报「读不出时间戳」，**不许出垃圾谱** |
| `audio_missing.json` | `source_audio` 指了个不存在的文件 ⇒ 提示 |

**测试套**：
- `tests/test_stem_json.py`（新）：上面 11 个用例 + `role_hints` 表 + `to_midi_like` 的轨/点数；
- `tests/test_ts_source.py`（若已有就扩）：**加「结构化 JSON 不许被当时间戳」**这条回归
  （就是 §3 那个隐患）；
- `tests/test_sidecar.py`：加一节「载入 stem-json ⇒ `is_stem_json`/轨数/建议角色/默认 merge_ms=0/音频绑定」；
- `app/e2e.js`：从 `samples/` 载一份示例 ⇒ 出谱 + 界面显示来源（顺带验 UI 没漏字段）；
- **端到端**：拿**用户给的真实那份**（202s 那首）跑一次「载入 → 勾 melody → 出谱 → 导出」。

---

## 6. ★ 决定点（**要用户拍板才能开工**）

### 6.1 哪几路默认勾上、各当什么角色？（**这条直接决定出谱结果**）

现有机制支持三种角色：`main`（主轨，取并集）/ `sub`（次级，只插空）/ `dp`（双押轨）。
我的建议（**保守**：一次只让一个变量动）：

| 路 | 建议 | 默认勾选 |
| --- | --- | --- |
| `melody` | `main` | ✅ 勾 |
| `vocals` | `main` | ❌ 不勾（**只标注**「建议主轨」） |
| `drums` | `dp` | ❌ 不勾（标注「建议双押」） |
| `bass` | `sub` | ❌ 不勾 |
| `guitar` | `sub` | ❌ 不勾 |
| `piano` | —— | ❌ 不勾（赠品，标注「供选」） |

⇒ 打开就是「只有旋律当主轨」的干净起点；其余**看得见、可勾、不乱动**。
**要你确认或改这张表**（比如你想默认 melody+drums 一起上、或者 vocals 也当主轨）。

### 6.2 网格（砖长/相位/分母）按谁算？

现在的架构是「一次一张谱」，所以只能：
- **(A)** 按**默认主轨那一路**算（推荐：通常就是 melody）；（B）按**所有勾选路的并集**算。
我建议 **(A)**，并把每路各自的最佳砖长**也报出来**（诊断用，不动默认）。

### 6.3 `bpm_hint` 怎么用？

建议：**填进「基准 BPM」框 + 上屏提示**，但**仍然受「自动选基准 BPM」开关管**
（勾着自动时它只是显示，不参与求解）—— 与现在「基准 BPM 框只是显示」的口径一致。

### 6.4 `source_audio` 自动绑成预览音源？

建议 **要**（省得用户再找一遍原曲），解析顺序：`JSON 同目录` → `JSON 的上一级` → 绝对路径；
**绑上/找不到都要上屏说**。找不到时**不报错**，只是不绑。

### 6.5 要不要把一份示例 stem-JSON 放进 `samples/`？

建议 **要**（用户一眼看到支持），用规格里那份 202s 的样例缩一个小点的版本。

### 6.6 要不要**反向导出**这份格式（我们写 JSON 给对方）？

建议**先不做** —— 对方文档明确说「只负责出 JSON，不生成 .adofai」，我们是消费方。
（真要做，落在 `core/bdg/emit.py` 之外另开一个 emitter，别混进 BDG 那条路。）

---

## 7. 明确不做（这一轮）

- ❌ 不碰 `ogg2adofai`（用户口径：正式版隐藏、逻辑层不动）—— 本方案**与它无关**：
  stem-JSON 是**文件来源**，不是「从音频现场采音」。
- ❌ 不做「一路 stem 一条 BDG 泳道」（可以做，但那是**另一个**决定，且要先有 §6.1 的角色表）。
- ❌ 不做自动选角色/自动勾选以外的启发式（先让用户看见、能改）。
- ❌ 不引入新依赖（纯标准库；`numpy` 那套只属于音频采音）。

---

## 8. 落地记录（v0.4.5 · 2026-10）

用户口径：“压缩已经完成，现在对时间戳 JSON 进行兼容层，交付最新版本 & 插件逻辑。
无需打包构建。版本号更新到 0.4.5。”

### 8.1 §6 六个决定点，实际是这么做的

| 决定点 | 采用 | 落在哪 |
| --- | --- | --- |
| 6.1 默认勾选 / 角色 | **保守口径**（方案里推荐的那张表）：只默认勾 `melody` 当主轨；`vocals` 建议主轨、`drums` 建议双押、`bass`/`guitar` 建议次轨、`piano` 赠品 —— **全部只标注，不勾** | `stem_json.ROLE_BY_KEY` / `NOTE_BY_KEY` / `default_checked` |
| 6.2 网格按谁算 | **(A) 主路**：优先 `melody`，没有就点最多的那一路；报告里明说「网格按「melody」算」 | `stem_json._main_stem` → `mf.stem_meta["main_key"]` |
| 6.3 `bpm_hint` | **填进信息行 + 上屏**（不强制参与求解；仍受「自动基准 BPM」管） | `meta["bpm_hint"]` → 文件信息行 |
| 6.4 `source_audio` 自动绑 | **要**：同目录 → 上一级 → 原样；绑上/找不到都上屏 | `stem_json.resolve_audio` + `Session.load` |
| 6.5 放示例进 `samples/` | **要**：`samples/示例·分轨时间戳.json`（6 路 168 点），并让 `samples()` 认它 | `tools/make_stemjson_fixtures.py` |
| 6.6 反向导出 | **不做** | — |

### 8.2 与方案有出入的三处（都是往好的方向）

1. `read_stem_json()` 返回 **`(stems, report)`** 两件（`report["meta"]` 里就是那份紧凑头），
   而不是 `(stems, meta, report)` 三件 —— 少一个返回值少一处不一致；
2. `info["stem_notes"]` + 轨道行的 `note` 是**新增**的（方案只写 `suggest`）：
   「建议主轨但默认不勾」这种话得有个地方说，否则用户不理解我们为什么没勾;
3. `samples()` 也收时间戳 JSON —— 方案 §6.5 只说要放文件，没说菜单得认得它。

### 8.3 ★★ 开工第一件事（§3）连带挖出的**真 bug**

`core/ts_source.py._finish()` 是「先 `sorted()` 再丢 NaN」，而 **NaN 没有全序**
⇒ 含 NaN 的序列排不干净（实测 `[1000,1000,-500,NaN,NaN,2000,NaN,3000]` →
`[2000,3000,1000]`）。已改成**先过滤再排序**。回归在
`tests/test_ts_source.py` H 与 `tests/test_stem_json.py` D。

### 8.4 验收

- `python tests/test_stem_json.py` —— 8 节 60 项全过；
- `python tests/test_sidecar.py` —— **268 passed / 0 failed**（新增 [17b] 18 项）；
- `python tests/test_ts_source.py` —— 含新增 H 节全过；
- `tests/test_*.py` **32 套全绿**；
- `app/e2e.js` 新增一段（分轨 JSON 载入 / 徽标 / 每一路表 / 默认只勾主旋律 / 出谱 64 点
  时序误差 0 / 多勾鼓取并集 / 原曲找不到上屏 / 结构化 JSON 明确拒绝）。

### 8.5 桥接器

**零改动**（`bridge_plugin/` 与 `sidecar/bridge.py`、`core/bdg/**` 一个字没动）——
投射/收回本来就按「勾选 → 采音 → 按源轨分泳道」走，新格式只是多了一个来源。
`bridge_plugin/manifest.json` 版本仍是 `0.1.0`。

