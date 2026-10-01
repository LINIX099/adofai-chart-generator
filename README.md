# ADOFAI Chart Generator

把 **MIDI / 音频 / 时间戳 JSON** 变成 **A Dance of Fire and Ice（冰与火之舞）** 的可游玩谱面
（`.adofai`），并且**能立刻看见、听见采音对不对**。

```
python main.py                     # 旧前端：PySide6（保留作行为基准）
cd app && npm start                # 新前端：Electron + Python sidecar（推荐）
python tools/gen_from_source.py …  # 无头全流程（**给 agent / 批处理用这条**）
```

**版本** `0.5.0-preview-bugfix`（见 `VERSION` · `CHANGELOG.md`）。
许可 Apache-2.0（`LICENSE` / `NOTICE` / `THIRD-PARTY.md`）。

> **仓库里只有源码 / 文档 / 测试。**
> 语料、音频、MIDI、打包产物、依赖一律排除，逐项说明在 **`EXTERNAL_ASSETS.md`**。

---

## 一、它做什么

```
源 ──► 采音（onset 序列）──► 求解 / 直拟合 ──► 双押 ──► 外观调度 ──► 演出 / 镜头 ──► .adofai
```

**支持的源**（`sidecar.session.load_source` 按扩展名 + 内容嗅探分派）：

| 源 | 说明 |
|---|---|
| `.mid` / `.midi` | MIDI（format 0/1/2、running status、SMPTE/PPQ、tempo map、GBK 轨名容错） |
| `.ogg` / `.wav` / `.mp3` | 音频，自己采音（`core.audio_onsets`） |
| **时间戳 JSON** | DEMUCS 分轨音头（`stems.*.onsets_sec`）—— **一路一轨**，可分开勾选主轨/次轨/双押轨 |
| 纯时间戳 | `.txt/.csv` 一行一个毫秒 |
| `.adofai` / BDG | 已有谱面 / 桥接工程，往返编辑 |

**产物**：`<输出目录>/<曲名>/main.adofai`（+ 绑定音频）。

---

## 二、★★★ 给 Agent 的拟合指南

> 这一节是给人**复制粘贴给 agent** 用的。目标是：**让生成的谱面「像人类写的」**，
> 而不只是「时序对了」。
>
> 时序对 ≠ 谱面能看。这是本项目踩过最多次的坑：曾经有一版 `verify` 逐点 0.0us 全过、
> 实测截图是「碎渣」。**先量靶子，再调参数，最后才看图。**

### 2.1 复制给 agent 的提示词

```text
你在操作一个 ADOFAI 谱面生成器（仓库根目录 = 当前目录）。

目标：把 <源文件> 变成一张**像人类写的、可游玩**的谱面，不是「时序正确」就算完。

── 硬规则 ──────────────────────────────────────────────
1. 不要先调参数。先量靶子：
     python tools/corpus_p12_15.py              # 语料的逐张指标 + P10~P90 判据
     python tools/corpus_report.py <目录>        # 任意目录的体检
   把结果当**验收区间**，不是当参考值。
2. 生成走无头脚本，不要手搓：
     python tools/gen_from_source.py <源> [--audio <ogg>] --out-dir out/<名字> \
            --set key=value …  --json key=<JSON>
3. 每改一轮都要**重新量**：
     python tools/verify_osn1.py out/<名字>
   —— 它一次给出：语料对照 / 同曲参照并排 / 规则违规 / 几何体检 / 逐按键反解。
4. 不许静默：任何跳过、截断、夹紧、碰撞都要在报告里说出来。
   你自己做的取舍（比如「没开某某开关，因为会动时值」）也要写进交付说明。
5. 交付前必须过三关：
     规则   core.rules.check_chart        → 违规（非 info）0 条
     几何   core.geomcheck.metrics        → 像一条路（重叠数低、占地不是个位数）
     时序   core.verify                   → 最大误差 ≤ 1ms

── 目标画像：什么样的谱「像人类写的」 ──────────────────
见 README §2.3 的表。**一句话**：直线率 30~45%、Twirl 每百格 15~26、
角度只用「15° 的整数倍里人类真正在用的那几个」、**几乎不用比基准更慢的速度档**。

── 什么时候该怀疑自己 ────────────────────────────────
见 README §2.4 的「不像人写的 6 个信号」。命中任何一条，先回去查根因，
不要靠继续调参把它盖过去。
```

### 2.2 CLI 的坑（都踩过）

| # | 坑 | 说明 |
|---|---|---|
| 1 | **时间戳来源默认走「直拟合」** | `fit_mode=direct`（时序优先）。这条路上 **`base_bpm` / `auto_bpm` 是死参数** —— 基准 BPM 直接取「去噪砖长」。**唯一入口是 `denoise_hint_ms`**（= 砖长毫秒）。要把基准钉到 330 BPM ⇒ `denoise_hint_ms=181.818182`（`60000/330`）。 |
| 2 | `--set` 只吃**标量** | `dp_checked` / `xk_ranges` / `segments` 这些**列表 / 字典型状态键传不进去**。用 `--json dp_checked=[1]`。 |
| 3 | 来源默认值 vs 你的覆盖 | 时间戳来源会推 `merge_ms=0` / `fit_mode=direct`（`default_*`）。`--set` **覆盖**它们；不写就用来源的。**不要**在不清楚后果时把它改回 30ms —— 30ms 的默认合并会把密集处的音悄悄并掉。 |
| 4 | 编码 | 一律 `PYTHONIOENCODING=utf-8` 再跑。**中文 Python 字符串里不要用 ASCII 双引号**（会炸），用 `「」`。 |
| 5 | 去噪会**挪点** | 典型位移中位 ~1.8ms、最大 ~5.7ms —— 这个量级等于检测器自身的帧量化（如 `hop_ms=5.805`），不是 bug。开 `aggressive_fit`（15° 阶梯）会挪更多，用 `fit_tol_ms` 卡住，挪不动的会**原样保留并报数**。 |
| 6 | 看图要用对工具 | 预览走 Re_ADOJAS 那套（内嵌播放器 / 上游编辑器）。**走向图（`*-path.png` 一类）已废弃**，0.2 之后没人维护，别拿它判断排版。 |
| 7 | 语料要自己准备 | 第三方谱面语料**不入库**（见 `EXTERNAL_ASSETS.md`），用 `tools/tuf_index.py` → `tuf_pick.py` → `tuf_download.py` 自己拉。 |
| 8 | 别碰的目录 | `vendor/` · `_re_adojas/` · `sidecar/bridge.py` · `core/bdg/**` —— 第三方或别人的接口，改了就回不去。 |
| 9 | 开关名是**索引**不是字符串 | 界面上是下拉的参数（`twirl_index` / `straight_preset` / `closed_bias_index` / `snown_index`）在 schema 里存的是**下标**。写 `--set twirl_mode=accum` 是**静默无效**的，要写 `--set twirl_index=1`。 |
| 10 | 有些 core 参数**没接线** | `SolveParams` 里有的字段 sidecar 从没传下去（历史遗留）。用到之前先 `grep` 一遍 `sidecar/session.py::params_solve` 确认它真的被读了。 |

### 2.3 「像人类写的」判据（语料实测）

以 P12~P15 共 45 张社区谱面为样本（`python tools/corpus_p12_15.py` 可复现）。
用 **P10~P90** 当验收区间 —— **不要用均值**，均值会被少数几千格的长谱拉偏。

| 指标 | P10 | 中位 | P90 | 怎么算 |
|---|---|---|---|---|
| **直线率** | 21.9% | 38% | **48.7%** | `abs(travel−180) ≤ 0.5°` 的格占比 |
| **多押** | 0.6% | 8% | 26.9% | `travel ≠ 180` 且单格时长 ≤ 35ms |
| **Twirl /100 格** | 9.5 | 19.8 | **31.1** | Twirl 事件数 ÷ 格数 × 100 |
| **SetSpeed /100 格** | 0.8 | 4.2 | 22.3 | SetSpeed 事件数 ÷ 格数 × 100 |
| **速度档是 2 的幂** | 71.4% | 96% | 100% | 人类也有非 2 的幂档（1.5x / 1.333x） |
| **音值落 1/12 网格** | 56.6% | 88% | 100% | `travel/180/speed × 12` 是整数 |
| **单格时长中位** | 83.7ms | 117ms | 184.5ms | |
| midspin | 0 | 0.43% | 4.22% | `angleData == 999` |

**角度词汇**（同曲真人参照：P14 的 `Mad Piano Party` 两张，1021 / 1026 格）：

```
180° 40.9% · 90° 35.5% · 120° 11.0% · 135° 5.9% · 270° 3.2% · 45° 2.0% · 60° 1.2%
速度 1x 64.6% · 2x 16.9% · 1.333x 8.6% · 1.5x 5.4% · 0.5x 2.7%
```

三条可以直接当规则用的结论：

1. **词汇量极小**：只有 `0 / 45 / 60 / 90 / 120 / 135 / 180 / 270` 这几种。
   `22.5° / 67.5° / 112.5° / 157.5°` **一次都没出现** —— 谱面里成片出现这些角度，
   基本就是「算法没调好」的信号（俗称碎渣）。
2. **人类几乎不降速**：`0.5x` 占 2.7%。想要「更长的一格」，人类的做法是
   **写 270°/360° 的大转角**，而不是把速度砍一半。
   反之，靠 `0.5x` 换直线，是机器产物最典型的口音。
3. **Twirl 不能为 0，也不能太多**：转角**大小**由时值定死，能选的只有**符号**。
   符号不变 ⇒ 航向单调旋转 ⇒ 每 `360/|τ|` 格绕回自己 ⇒ 行星在原地画闭合多边形。
   Twirl 太少（< 9/100）就是「原地打转」，太多（> 31/100）是「图标糊脸」。

**另外两条与游戏模型绑定的硬事实**：

- **第 0 格永远是直线**（真谱 `angleData[0] == 0` 占 95.6%，等价于 `travel₀ = 180°`）。
  生成器强制这么做，与参数无关。
- **不插速度事件时行星全程匀速**，这是「手感正常」的前提。

### 2.4 「不像人写的」6 个信号

命中任何一条，**先查根因再调参**，否则只是把症状挪个位置：

| 信号 | 典型根因 | 去哪看 |
|---|---|---|
| 直线率 > 60% 或 < 20% | 等间隔输入 + 「直线优先」⇒ 求解器靠**降一档速度**换直线 | `docs/13` §5 · `docs/76` §3② |
| `0.5x`/`0.25x` 占 20%+ | 同上。降速档没有代价 ⇒ 全场选它 | `slow_speed_penalty`（见下） |
| 成片 `22.5° / 67.5° / 157.5°` | 去噪/拟合把时值吸到了**非 15° 整数倍**的格子 | 开 15° 阶梯（`aggressive_fit` + `fit_tol_ms`） |
| Twirl ≈ 0 | 「角度回正」的 DP 在偏轴量相同时**选图标最少的那条**，会把 Twirl 全清掉 | `straighten` 关掉试试 |
| SetSpeed ≈ 0（一整首一个档） | 「一档至少连续几层」把零星变档并成了整块 | `speed_min_run` |
| 模板 0 段 / 覆盖 0 格 | 模板闸要求「段落 ≤ `template_max_span_s`」，长段无休止的曲子整曲算一段，全被拒 | `docs/76` §3③ |

### 2.5 两个专门为「像人类」加的旋钮

| 参数 | 默认 | 作用 |
|---|---|---|
| `slow_speed_penalty` | `0.0` | **降速档（k<1）每慢一个八度额外扣的分**。默认 0 = 老口径。设 ~0.55 能把 8 分密集段从「全靠 0.5x 走直线」改成「90° 阶梯为主 + 少量 180°」。**只罚变慢，加速档一个字节不动。** |
| `speed_min_run` | `6` | **一个速度档至少连续几层**。设 1 = 允许逐格变档（SetSpeed 会明显变多）。 |

两个都是 `0.0` / `6` 时**产物与旧版逐字节相同**（有 SHA256 回归守着）。

---

## 三、快速开始

### 3.1 Electron 前端（推荐）

```bash
cd app && npm ci && npm start
```

界面分栏：① 文件 / ② 音轨（主轨可多选 + 区间采音）/ ③ 采音 /
④ 求解·几何 / ④b 去噪·直拟合 / ⑤ 时序·导出 / ⑤b 换手押上色 /
⑤c 算法轨道调度 / ⑤d 演出 / ⑤e（new）镜头调度。

四个视图：**谱面预览**（内嵌官方渲染引擎的 Three.js 播放器）、**钢琴卷帘**、
**谱面路径**、**4K 下落式**；顶部一条**全曲预览条**（导航单位是「格」不是毫秒）。

无头自检：

```bash
cd app
npx electron . --smoke     # 握手
npx electron . --e2e       # 加载 → 求解 → 四视图 → 导出（当前 294 条断言）
npx electron . --probe     # 状态探针
```

### 3.2 PySide6 前端（旧，保留作行为基准）

```bash
python main.py
```

### 3.3 无头 CLI（**agent / 批处理用这条**）

```bash
export PYTHONIOENCODING=utf-8

python tools/gen_from_source.py <源文件> \
    [--audio <ogg>]  [--out-dir out/<名字>]  [--ref <参考谱.adofai>] \
    [--set key=value …]  [--json key=<JSON>]  [--tracks 0,1]  [--no-verify]
```

`--ref` 会从参考谱继承 **原始偏移 / ogg / 轨道颜色**（用户口径：这三样必须来自参考谱）。

常用验收脚本：

```bash
python tools/corpus_report.py <目录>          # 任意谱面目录的指标体检
python tools/corpus_p12_15.py                 # P12~P15 逐张指标 + P10~P90 判据
python tools/verify_osn1.py <目录>            # 交付验收（语料对照+规则+几何+反解）
python tools/align_chart_midi.py <参考谱> <产物> --tol 30 --accept --midi <midi>
python tools/sweep_osn1.py                    # 参数扫描台（一批配置 → 重建 → 导出 → 自动打分）
```

---

## 四、核心模型

### 4.1 时间

```
单格角行程  travel_i = Δt_i × 基准BPM / (1000/3)
⇒ 行星线速度 = R × travel_rad / Δt = R × 基准BPM × π/180000 = 常数
```

**不插速度事件 → 行星全程匀速**，这是手感正常的前提。

```
转角    turn_i    = s_i × (travel_i − 180°)     s_i = ±1（由 Twirl 决定）
航向    heading_i = heading_{i−1} + turn_i
方块    tile_{i+1} = tile_i + 2R × u(heading_i)
angleData[i] = (90 − heading_i) mod 360
```

### 4.2 两条路：**最优化** vs **直拟合**

| | `fit_mode=solve`（最优化） | `fit_mode=direct`（直拟合） |
|---|---|---|
| 口径 | **像人写的谱**（模板 / 三连音 / 自然闭合 / 雪花） | **时序优先，几何服从** |
| 时序 | 会量化、会用 Pause 填长休止 ⇒ 有漂移风险 | **逐点精确**（每个 onset 一层） |
| 基准 BPM | 求解器自己挑八度（`base_bpm` 有效） | 取**去噪砖长**（`denoise_hint_ms` 说了算） |
| 直线率 | 靠模板能到 39~42% | 天然 79~90%（要压下去得靠 `slow_speed_penalty`） |
| 默认 | MIDI 源 | **时间戳源** |

两条路共用同一套 `rs` / `base_bpm` 前处理（`core.solve._prepare_rhythm`），
所以 A/B 比对才有意义。

### 4.3 时序（offset / 倒计时）

```
entryTime[0] = 0
entryTime[1] = (countdownTicks−1)×拍 + T_0      ← 倒计时只补在第 1 层
entryTime[j] = entryTime[j−1] + T_{j−1}
```

行星开局停在第一格上、数完倒计时才第一次按 ⇒ **N 个 onset 需要 N+1 个方块**
（第 0 块是开局站位，不消耗按键，`travel` 固定 180°）。

第 i 次按下的音频时刻 = `offset + entryTime[i+1]`。

- **交出去的是原始音频文件时**：我们原样交出去、**不补前置静音** ⇒ `offset = 首个 onset − entryTime[1]`
- **交出去的是我们合成的 wav 时**：会补 `cd × 一拍` 前置静音，走「零误差配方」

`offset` **默认 0，不自动写**（自己听自己调）；想走零误差配方再开「自动 = 首个 onset」。

### 4.4 双押

ADOFAI 的「双押」不是两个键，而是**两个方块同一瞬间按下**。
做法：在主音格前插一对 `[折返格, midspin 999]` ——
`angleData == 999 ⇒ exitangle = entryangle（不改方向）且 travel = 0（瞬发）`。

恒等式 `travel_X + travel_Y' ≡ travel_f (mod 360)`，只要不缠绕就**零净偏移**：
总时长与原有每层的时刻一个都不动。实测总时长差 **0.000000 ms**。

另有一套 **角度双押**（两个不同角度的格，默认写法），细节见 `docs/74`。

---

## 五、工程结构

```
main.py                     PySide6 前端入口
core/                       业务逻辑（**只有一份**，两套前端共用）
  midi.py                   零依赖 MIDI 解析
  audio_onsets.py           音频采音
  stem_json.py              DEMUCS 分轨时间戳 JSON
  ts_source.py              纯毫秒时间戳
  denoise.py                网格推断 / 吸附
  onsets.py                 采音（主轨并集 / 次轨插空）
  solve.py                  最优化求解（参考音值 + 速度档 DP + Twirl 规划）
  fitdirect.py              直拟合（时序优先）+ 15° 阶梯
  ladder.py                 对音阶梯（第二条路径）
  tilefill.py               补格（把长间隔切碎）
  templates.py              节奏型模板匹配
  dp_angle.py / dp_midspin.py / dp_offset.py   双押
  straighten.py             角度回正（只改 Twirl 符号）
  snowflake.py / figures.py / bigline.py       图形
  camera.py                 镜头调度（漂移 + 呼吸）
  colorize.py / appearance.py / show.py / track_fx.py   渲染侧调度
  path.py / geomcheck.py / rules.py / verify.py         几何与验收
  writer.py                 写盘（.adofai JSON）
  model.py / coerce.py / roundtrip.py / parse.py / emit.py
sidecar/                    桥接服务：HTTP + WS
  schema.py                 129 个参数的唯一真源（界面按它自动渲染）
  session.py                全流程（load → rebuild → export）+ 记账
  server.py / ws.py / hostctl.py
app/                        Electron 前端（renderer/ 是纯前端；e2e.js 是 294 条断言）
ui/                         PySide6 前端（保留作行为基准）
tools/                      探针 / 验收 / 生成脚本（无 `_` 前缀的 67 个是可复用的）
tests/                      39 个自测
docs/                       设计记录（**源码里 755 处引用它当依据**；先看 docs/README.md 的索引）
patterns/                   节奏型模板库
bridge_plugin/              BDG 桥接插件
packaging/                  打包脚本 + 第三方许可全文
```

**不入库的东西**逐项在 `EXTERNAL_ASSETS.md`：语料 / 音频 / MIDI / 打包产物 /
依赖 / 历史快照。仓库里**没有密钥**，凭据只存在操作系统的凭据管理器里。

---

## 六、测试与验收

```bash
python tests/test_pipeline.py     # 端到端 + 时序自检 + 反解校验
python tests/test_sidecar.py      # sidecar 全流程（当前 308 条）
python tests/test_ladder.py       # 对音阶梯 + golden 哈希（防退化）
python tests/test_fitdirect.py    # 直拟合 + 角度上下界
python tests/test_denoise.py      # 去噪/吸附
python tests/test_tilefill.py     # 补格
python tests/test_dp_angle.py     # 双押角度
python tests/test_camera.py       # 镜头调度
# … 共 39 个
```

**交付前必须过的三关**（不能只看时序）：

| 关 | 命令 | 通过标准 |
|---|---|---|
| 规则 | `core.rules.check_chart(chart)` | 违规（`level != "info"`）**0 条** |
| 几何 | `core.geomcheck.metrics(chart)` | 「像一条路」：重叠数低、每格占地不是个位数 |
| 时序 | `core.verify.verify_file / verify_press_subset` | 逐按键最大误差 ≤ 1ms |

---

## 七、已知限制

- 方块基本都是**单击**；midspin（999）**只用于双押插入**，不作其它用途。
- 没有长按 / MultiPlanet。
- 采音只在**单条音轨**内做（刻意）；多轨取并集，不做声部分离。
- **自交规避不是全局最优**。真谱本身就大量重叠（某张真谱实测 14732 对间距 < 1.75R），
  所以「有重叠」不是缺陷，「碎成一团」才是。
- **Pause 区间是双押盲区**：那段时间不属于任何一格的 travel。门控规则把双押锚在主音格上，
  所以实际上不会踩到。
- 尾部长休止会让行星爬得极慢（一个方块吃掉整段）—— 这是角度模型的物理限制，
  真谱靠一个「蜗牛」解决。
- 预览音在没配音源时是 numpy 合成音色，只保证音头位置对，不保证好听。
- **`SPEED_TIERS` 只有 2 的幂** ⇒ 写不出人类常用的 `1.333x / 1.5x`，
  因此 `120° / 135°` 这两档只能近似（这是当前与社区谱面差距最大的一处，
  也是 SetSpeed 密度偏低的原因）。

---

## 八、许可

本程序采用 **Apache License 2.0**（`LICENSE` 全文，`NOTICE` 归属声明）。

- 可以自由使用、修改、再分发（含商用），并且**带专利授权**；
- 分发时请保留 `LICENSE` / `NOTICE` / `THIRD-PARTY.md` / `packaging/` 里的许可全文；
- 改过的文件请注明「已修改」（Apache-2.0 §4(b)）。

随包第三方组件**不是** Apache-2.0，各有各的许可（Electron/Chromium · Python ·
numpy/scipy/numba · librosa/soundfile · three.js · ADOFAI 时间模型），
全文与索引见 `THIRD-PARTY.md`。
`beat_data_generator`（GPL-3.0 宿主）**不随包分发**，由用户自行安装、经插件通信。

本程序**不包含** ADOFAI 游戏本体、也不分发其美术资源与音频；它只生成 `.adofai`
（纯文本 JSON），由用户在自己的游戏里打开。
本项目与 7th Beat Games **无隶属关系**；「A Dance of Fire and Ice」是其商标。
