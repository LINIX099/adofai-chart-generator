# 71 · 从 MIDI 还原已有谱面：**Flower Rocket**

---

## 0. ★★ 压缩后从这里接（用户 2026-10 停在这里）

> ★★★ **本轮（迭代 2）已经接上了 —— 先读 `docs/72`。**
> 一句话：**② 的 84.3% 是尺子 bug（两条时间基差 913 ms），真值 99.9% ✅**；
> ① 用尽「只靠 MIDI 能推出来的补点规则」最好到 **76.2%**，**80% 从 MIDI 推不出来**（`docs/72` §4）。

> 用户原话：「**谱面对谱面 80%。+ 能对上 midi 的音 95%**」
> 「调整了一下偏移，**883 是环境下正确的偏移**」
> 「下一环中，需要使用**镜头回正公式**，并且适当使用**分段采音设置双押**、
>   **bpm 采音**来增加相似度到 **80% 以上**」
> 「**等我压缩再开工**」

### 0.1 验收口径（已经做成命令，别再手算）

```powershell
$env:PYTHONIOENCODING='utf-8'
python tools\align_chart_midi.py `
  '‹社区语料目录›\Flower_Rocket\main - 副本.adofai' `
  'out\flower_883\main\main.adofai' --tol 30 `
  --accept --midi '‹下载盘›/Flower_Rocket\Flower_Rocket.mid'
```

```
① **谱面 ↔ 谱面 = 80%**        → 一对一
② **能对上 MIDI 的音 = 95%**   → 生成谱的每次按键里有 MIDI 音头的比例
```

### 0.2 现在的站位（2026-10 实测）

| 门槛 | 现在 | 目标 | |
|---|---|---|---|
| ① 谱面↔谱面（**一对一**） | **60.4%** | 80% | ❌ |
| ② 能对上 MIDI（生成谱的按键里有 MIDI 音头的比例） | **84.3%** | 95% | ❌ |

同一对的另外两个读数（判据只用上面那两个）：覆盖 **82.0%** · 命中 **88.3%** ·
中位频差 **0.0 ms**（参考 2543 次按键 · 生成 1742 次）。

### 0.3 ★★ 关键：① 现在**数学上到不了 80%**

```
一对一的上限 = min(参考 2543, 生成 1742) / max(...) = 1742/2543 = **68.5%**
```

⇒ **必须多发按键**（每多一个「落在参考谱也有按键的位置」的按键，上限就往上抬）。
至少要到 **0.80 × 2543 = 2035 个**匹配对 —— 也就是生成谱的按键数得从 1742
往 **2035+** 走，而且新增的都要落在参考谱有按键的位置上。

**这正好就是用户说的那三件事要干的**（§9.1）：

1. **镜头回正公式**（`docs/59` §3.1 + `docs/64` §9.2a #3）
2. **分段采音 → 双押**（`docs/39` + `core/dp_angle.py`）
3. **bpm 采音**（`docs/27` + `core/xkbase.py`）

★ 参考谱比 MIDI 的**独立音头**（1773）还多 **770 个按键**（§3.1），
那些多出来的与最近音头的距离**全是 1/4 拍的整数倍**（65.2 ms）
⇒ 大概率就是「拆层 / 双押 / 更细网格」这一类补点。

### 0.4 本轮末的产出与命令

| 产物 | 说明 |
|---|---|
| `out/flower_883/main/` | ★ **当前最新**：2 轨 + `--ref` 继承 + **offset 883** |
| `out/flower_ref/main/` | 同前但 offset=1053（`--ref` 的原始值） |
| `out/flower_midi2/main/` | 只用两轨、auto_offset（对照） |
| `out/flower_midi/main/` | 只 tr0（对照） |

```powershell
$env:PYTHONIOENCODING='utf-8'
python tools\gen_from_source.py '‹下载盘›/Flower_Rocket\Flower_Rocket.mid' `
  --tracks 0,1 `
  --ref '‹社区语料目录›\Flower_Rocket\main - 副本.adofai' `
  --set offset=883 --out-dir 'out\flower_883'
```

**优先级**：`--set offset`（环境标定 **883**）> `--ref` 的 `offset`（文件里 1053）> `auto_offset`。

### 0.5 ⚠ 三处**没做完 / 没查清**，下一轮开头先看

1. **② 的偏移搜索可疑**：同一份产物，`--chart-offset` 时按覆盖搜到 **−60 ms → 99.9%**，
   不带时搜到 **+106 ms → 84.3%**。MIDI 很密（4747 音头 / 201 s ≈ 24 音/秒，
   平均间隔 42 ms），±30 ms 的窗口几乎处处都有音 ⇒ **这个读数可能被"密集"灌水**。
   下一轮要先定：② 到底用哪条时间基、窗口多宽、要不要**双向**算。
   （`--accept` 里已经把范围放宽到 ±600 ms，仍然停在 84.3%。）
2. **参考谱有 533 条 `Twirl`，产物 0 条**（`docs/25` 的阶梯 / `core/triple_engine` 都还没接）。
3. **参考谱基准位** `position=[0,-0.5] zoom=150 relativeTo=Tile lockRot=true`
   与产物不同 —— `--ref` 目前只继承**偏移 / ogg / 轨道颜色**三样（用户点名的）。

---

> 用户 2026-10：
>
> > 「下一环中，我们要基于我下一个提供的 **midi**，尝试从 midi **用求解器还原一个已有的
> >   adofai 谱面**。并不需要完全一致，**60~80% 一致**即可」
> > 材料：`‹社区语料目录›\Flower_Rocket\` + `‹下载盘›/Flower_Rocket\`
> > 判据（先）：「**按键时刻对齐率**」→（后定）「**谱面对谱面 80% + 能对上 MIDI 的音 95%**」

★ **压缩后先读 §0**（验收口径 / 现在站位 / 关键结论 / 未做完的三处）。

**结论：两轨跑一遍 = 一对一 60.4%（±30 ms），已经落进 60~80%。**
外加两个必须先定的发现（§4）。

---

## 1. 材料

| 边 | 文件 | 说明 |
|---|---|---|
| **参考谱** | `Flower_Rocket\main - 副本.adofai` | **2601 格 · base 230 · 200.3 s · offset 1053 ms · 难度 10 · 533 Twirl · 119 SetSpeed**（`backup.adofai` 同尺寸；`Flower Rocket.adofai` 是全特效版） |
| 音频 | `Flower_Rocket\Flower Rocket.ogg` | 3.90 MB（生成时直接拿来当预览源） |
| **MIDI** | `‹下载盘›\Flower_Rocket\Flower_Rocket.mid` | **format 1 · ppqn 480 · bpm 230 · 4/4 · 201.39 s** |
| 其它 | `.mscx` / `.pdf` / `.mp3` | MuseScore 工程与谱面，本轮没用到 |

**MIDI 两条轨都叫「钢琴」**：

| 轨 | 音数 | 音域 | 首个音头 |
|---|---|---|---|
| tr0（右手） | 1712 | 63–104 | 913 ms |
| tr1（左手） | 3035 | 27–80 | 1043.5 ms |
| **合并** | **4747** | | |

**独立音头**（同一时刻的和弦算一个）：tr0 **1276** · tr1 **1438** · **两轨 1773**。

---

## 2. 判据：`tools/align_chart_midi.py`（新）

```powershell
$env:PYTHONIOENCODING='utf-8'
python tools\align_chart_midi.py <参考谱.adofai> <生成谱.adofai 或 .mid> [--tol 30]
```

三个读数**都打出来**，以**一对一**为准（「60~80% 一致」说的是同一张谱）：

| 读数 | 定义 | 为什么要有 |
|---|---|---|
| **覆盖（召回）** | 参考的每次按键，容差内有没有对应的另一边按键 | 单独看会被"堆音刷分"骗 |
| **命中（精确）** | 另一边的每次按键，容差内有没有对应的参考按键 | 单独看会被"只挑几个准的"骗 |
| ★ **一对一** | 双向最小匹配后的匹配数 ÷ `max(两边条数)` | **主读数** |

**参考谱按键数 = 2543**（2601 格里 **58 格是中旋**，不按键 —— 工具会跳过）。

### 2.1 ★ 容差必须钉住 + `offset` 加不加是会翻盘的

同一对谱，只改容差：**±5 ms ⇒ 51.6% · ±30 ms ⇒ 71.6% · ±80 ms ⇒ 94.1%**。
所以判据里**容差是判据的一部分**，默认 **30 ms**（230 BPM 下约 1/8.7 拍）。

★★ 更坑的一条：**谱面 ↔ 谱面比的时候不能加 `settings.offset`**。
实测加了之后一对一从 **60.4% 掉到 53.2%**，而且出现**容差悬崖**
（±20 ms ⇒ 6.4%，±30 ms ⇒ 65.6%）。**看到悬崖就是有固定系统偏移，先怀疑 `offset`。**
⇒ 工具里做成开关 `--chart-offset`，**默认关**。

---

## 3. 结果

管线：`tools/gen_from_source.py`（headless 全流程，走的是**和界面完全同一条路**）。

```powershell
$env:PYTHONIOENCODING='utf-8'
python tools\gen_from_source.py '‹下载盘›/Flower_Rocket\Flower_Rocket.mid' `
  --tracks 0,1 --audio '‹社区语料目录›\Flower_Rocket\Flower Rocket.ogg' `
  --out-dir 'out\flower_midi2'
```

> ★ `--tracks` 是**本轮新加的参数** —— `tracks_checked` 是**列表**，
> 原来的 `--set key=value`（`coerce` 只出标量）表达不了，所以只能勾默认的第 1 条。

| | 只用 tr0（默认） | **两轨 tr0+tr1** |
|---|---|---|
| 生成按键 | 1248 | **1742** |
| 覆盖（±30 ms） | 68.8% | **82.0%** |
| 命中 | 99.6% | **88.3%** |
| ★ **一对一** | 48.9% | **★ 60.4%** |
| 中位频差 | 10.8 ms | **0.0 ms** |

**对照组的「天花板」**：直接拿 MIDI 的 4747 个音头去比，覆盖 **71.5%**、
一对一 **36.6%** —— 所以「堆音」是刷不了分的，**必须真的选对音**。

★ 生成谱另有两个变化（两轨 vs tr0）：直线率 41% → **68%**，
几何体检从「✗ 像一把碎渣」→「✓ **像一条路**（重叠 0.12 对/格）」。

### 3.1 差距在哪

参考 2543 次按键 vs 生成 1742 —— **少 801 个（31.5%）**，而且：

* 参考谱**没有任何同时押**（2543 次按键全是独立时刻，±5 ms 分组 2543 组，组大小全是 1）；
* MIDI 的**独立音头**（±1 ms）只有 **1773** 个 —— 生成器出 1741，**基本就是全部**。

⇒ **参考谱的按键比 MIDI 的独立音头还多 770 个**。
那些多出来的按键，与最近音头的距离**全是 65.2 ms 的整数倍**
（65.2 ms = 230 BPM 的**四分之一拍**），且系统性偏移 **+130.4 ms（半拍）**。

⇒ 两个方向：① 作者把一部分音**拆成了两格**（长音拆层 / 装饰格）；
② 作者用的是**更细的节拍网格**。**下一轮要先定这个**（见 §4）。

---

## 4. ★★ 两个必须先定的发现

### 4.1 ✅ 已解：`offset` 必须**继承参考谱**（用户 2026-10 定）

> 用户 2026-10：
> > 「**后面使用的原始偏移、ogg 都需要是参考谱面中的。轨道颜色同理**」

⇒ 本轮加了 `--ref <参考谱.adofai>`（见 §7），把 `offset` **钉成参考谱的 1053**、
关掉 `auto_offset`。落地后的效果：

| | 之前（auto_offset） | **之后（`--ref`）** |
|---|---|---|
| 生成谱 `offset` | −130 | **1053**（= 参考谱） |
| 谱面 ↔ 谱面（不加 offset） | 60.4% | **60.4%** |
| 谱面 ↔ 谱面（加 offset） | 53.2%（要另补 +110） | **60.4%** ← ★ 两个读数**终于一致** |
| 中位频差 | 0.0 ms | **0.0 ms** |

★ **两个读数一致**就是「`offset` 标定对了」的判据 —— 之前加不加差 7 个百分点，
正是 `offset` 语义不一致的信号。

**本轮原始记录的异常**（留档）：生成器 auto_offset 给的是 **−130 ms**，
与参考谱差 1183 ms。原因是**两条时间基不同**：

* 生成器的 auto_offset 对齐的是 **MIDI 的时间基**（所以它和 MIDI 在 ±5 ms 内吻合 **83.6%**）；
* 参考谱的 1053 对齐的是 **音频的时间基**；
* 两者差 9.4~9.5 ms 量级 —— 参考谱 + offset vs MIDI 的中位频差也是 **9.5 ms**，
  与本产物 + offset vs MIDI 的 **9.4 ms** 一致 ⇒ **两份谱现在互相对得上**。

⇒ 结论：**出谱一律用参考谱的 `offset`**（用户口径），auto_offset 只在没有参考谱时用。

### 4.2 「60~80%」到底以哪个读数为准

* **一对一 60.4%** ⇒ 已达标（本轮的结论）；
* **覆盖 82.0%** ⇒ 略超上限；
* 拿全 MIDI 硬堆 ⇒ 覆盖 71.5% 但一对一 36.6%。

三个数差很远，**请主人点名以哪个为准**（人家建议**一对一**）。

---

## 5. 复现

```powershell
$env:PYTHONIOENCODING='utf-8'

# ① 生成（两轨）
python tools\gen_from_source.py '‹下载盘›/Flower_Rocket\Flower_Rocket.mid' `
  --tracks 0,1 --audio '‹社区语料目录›\Flower_Rocket\Flower Rocket.ogg' `
  --out-dir 'out\flower_midi2'

# ② 量对齐率
python tools\align_chart_midi.py `
  '‹社区语料目录›\Flower_Rocket\main - 副本.adofai' `
  'out\flower_midi2\main\main.adofai' --tol 30
```

产物：`out/flower_midi2/main/{main.adofai, main.ogg}`（第三方反解校验通过）。
对照组：`out/flower_midi/`（只 tr0）。

---

## 7. ★★ `--ref`：从参考谱继承「原始偏移 / ogg / 轨道颜色」

> 用户 2026-10（规格）：
> > 「**后面使用的原始偏移、ogg 都需要是参考谱面中的。轨道颜色同理**」

`tools/gen_from_source.py` 新增 `--ref <参考谱.adofai>`：

| 搬什么 | 从哪 | 怎么搬 |
|---|---|---|
| **原始偏移** | `settings.offset` | `auto_offset = False`，`offset = 参考值`（**覆盖**自动值） |
| **ogg** | `settings.songFilename` + 同目录下的文件 | `--audio` 没给时自动指过去（预览 + 导出都用它） |
| **轨道颜色** | 下面 8 个键 | 导出后**逐键贴回**产物的 `settings` |

`REF_TRACK_KEYS`（`tools/gen_from_source.py`）：

```
trackColor · secondaryTrackColor · trackColorType · trackColorPulse
trackColorAnimDuration · trackPulseLength · trackGlowIntensity · trackStyle
```

★ 为什么轨道颜色是**导出后贴回**而不是走参数：`sidecar/schema.py` 里**没有**
`trackColor`/`secondaryTrackColor` 这两个字段（只有 `appearance_*` 的皮肤/发光/脉冲），
所以贴回是唯一不改 schema、不动 UI 的做法。

★ `--ref` 会**跳过**「按建议 offset 再算一次」那一遍（offset 已经钉死了），
并在控制台写明理由 —— **不静默**。

### 7.1 实得

```
参考谱 : ...\Flower_Rocket\main - 副本.adofai
   继承 原始偏移 offset=1053（关掉 auto_offset）· ogg=Flower Rocket.ogg · 轨道颜色 8 个键
（参考谱模式 ⇒ **不**按建议 offset=-130.43 重算，offset 钉在参考谱的 1053）
-- 从参考谱贴回轨道颜色 -------------------------------------------
   trackColor                 'ffffff' → 'f2ff00ff'
   secondaryTrackColor        'ffffff' → '15fcffff'
   trackColorAnimDuration     2 → 1
   trackPulseLength           10 → 16
```

（`trackStyle` / `trackColorType` / `trackColorPulse` / `trackGlowIntensity` 本来就一致 ⇒ 0 处改动。）

产物：`out/flower_ref/main/{main.adofai, main.ogg}`。

---

## 8. 复现（含 `--ref`）

```powershell
$env:PYTHONIOENCODING='utf-8'

python tools\gen_from_source.py '‹下载盘›/Flower_Rocket\Flower_Rocket.mid' `
  --tracks 0,1 `
  --ref '‹社区语料目录›\Flower_Rocket\main - 副本.adofai' `
  --out-dir 'out\flower_ref'

python tools\align_chart_midi.py `
  '‹社区语料目录›\Flower_Rocket\main - 副本.adofai' `
  'out\flower_ref\main\main.adofai' --tol 30
```

★ `--audio` 现在可以省 —— `--ref` 会自动指到参考谱目录里的那个 `songFilename`。

---

## 9. ★★ 下一环（用户 2026-10 指定）

> 用户原话：
> > 「调整了一下偏移，**883 是环境下正确的偏移**」
> > 「下一环中，需要使用**镜头回正公式**，并且适当使用**分段采音设置双押**、
> >   **bpm 采音**来增加相似度到 **80% 以上**」

### 9.0 偏移改成 883（已落地）

**显式 `--set offset=` 现在优先于 `--ref` 带过来的值**（优先级：
`--set offset` > `--ref` 的 `offset` > `auto_offset`）。
参考谱文件里写的是 1053，但在（游戏 + 这份 ogg 的）**环境**里 **883** 才对。

```powershell
python tools\gen_from_source.py '‹下载盘›/Flower_Rocket\Flower_Rocket.mid' `
  --tracks 0,1 `
  --ref '‹社区语料目录›\Flower_Rocket\main - 副本.adofai' `
  --set offset=883 `
  --out-dir 'out\flower_883'
```

实得：产物 `settings.offset = 883`，轨道颜色照旧继承，控制台写明
「显式 `--set offset=883` **覆盖**参考谱的 1053（环境标定值优先）」—— 不静默。
产物：`out/flower_883/main/`。

★ **对齐率读数不受它影响** —— 那个尺子比的是**关卡本地时间轴**（默认不加 `offset`），
所以 883 / 1053 都得到同一个 60.4%。`offset` 管的是**音频能不能对上**。

### 9.1 三条要做的，与现有落点

| # | 做什么 | 现有落点（直接用，不新造） | 目标 |
|---|---|---|---|
| 1 | **镜头回正公式** | `docs/59` §3.1 + `docs/64` §9.2a #3：**出拐角后第 1 格**发一条 `rotation = ±90`、`OutCubic`、**4 拍**（符号与转向一致）；拐角那一格**什么都不发**。参考实现 `tools/make_camera_demo.py::m_rectify_pos/neg` | 恢复原谱的镜头调度（参考谱有 **466 条 `MoveCamera`**） |
| 2 | **分段采音 → 双押** | `docs/39-分段采音.md` + `core/dp_angle.py`（双押几何 `[θ₁,θ₂,余量]`）+ `docs/31-双押写法总纲` | 参考谱 2543 次按键里，**约 770 个「多出来的按键」**（§3.1）很可能就是这类补点 |
| 3 | **bpm 采音** | `docs/27-v0.4-xk-base采音` + `core/xkbase.py` | 参考谱 **119 条 `SetSpeed`**（本产物 191 条但分布不同）——采 bpm 段对上了，时间轴才对得上 |

**当前基线**：一对一 **60.4%** · 覆盖 82.0% · 命中 88.3% · 中位频差 **0.0 ms**。
**下一环目标**：一对一 **≥ 80%**。

★ 另外两条**还没做**、下一轮可以一起看：

* 参考谱 **533 条 `Twirl`**，本产物 **0 条**；
* 参考谱基准位是 `position=[0,-0.5] zoom=150 relativeTo=Tile lockRot=true`，
  本产物是另一套（主人本轮只点名了「偏移 / ogg / 轨道颜色」三样）。

---

## 10. 还悬着的一条：判据口径

| # | 事 | 为什么 |
|---|---|---|
| 1 | 定「60~80% / 80% 以上」以**哪条读数**为准 | §4.2：一对一 60.4% / 覆盖 82.0% / 硬堆全 MIDI 覆盖 71.5% 但一对一 36.6% —— 三个数差很远。**建议以「一对一」为准**，下一环按它冲 80% |
