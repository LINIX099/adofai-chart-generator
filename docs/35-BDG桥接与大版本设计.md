# 35 · BDG 桥接 · 与 0.4 合并的大版本（**先讨论，不开工**）

> 用户 2026-10：
> 「这是他的宿主端 `BUGJI/beat_data_generator`，但是我**极端不建议照搬**，
> 可能会出现难以预料的屎山。我建议走 **websocket 协议**让两个项目可以实时桥接」
> 「`timeMs` 是**反算的**，存储的是 `timeOfBeat`」「BPM **以我们这边为准**」
> 「关于剩下的语义**你去仓库看看**」
>
> 本文 = **读码核实**（逐条给出文件与行）+ **WebSocket 桥设计** + 与
> `docs/27`（xk base）/`docs/34`（分段采音）合并成大版本的方案。

***

## 1. 读码核实：宿主的真面目

### 1.1 `.bdg` 工程文件 = 纯 JSON（版本化、向后兼容）

`src/renderer/src/types.ts`：

```ts
export interface BeatProject {
  app: "beat-data-generator";
  version: 2;                       // ★ 有 format 版本号
  name: string;
  baseBpm: number;
  offsetMs: number;
  audioName: string | null;
  audioMd5: string | null;          // ★ 音频指纹
  bpmLocked?: boolean;
  tracks: MarkerTrack[];
  markers: Marker[];
  bpmPoints: BpmPoint[];
  notes: ProjectNote[];             // 时间轴便签（markdown）
}
```

⇒ **不需要插件也能互通**：`.bdg` 直接可读可写。
⇒ 但 `docs/plugin-system.md` 说 `.bdg` **直接存 `type` + `attrs`，字段全可选、向后兼容**；
未装插件时「轨道与数据照常显示（点属性只读）」——**格式是稳定的**。

### 1.2 ★ `timeMs` 确实是**反算**的（用户说得对，代码坐实）

`src/renderer/src/types.ts` —— 存储层的 `Marker` **根本没有 `timeMs`**：

```ts
export interface Marker { id; trackId; beat; loop?; parentId?; attrs?; }
```

`src/renderer/src/plugins/api.ts` —— 插件看到的 `timeMs` 是**现算**的：

```ts
markers: p.markers.filter(...).map((m) => {
  const out: MarkerView = {
    id: m.id, trackId: m.trackId, beat: m.beat,
    timeMs: map.timeOfBeat(m.beat),      // ★★ 反算：timeOfBeat
  };
```

`src/renderer/src/tempo.ts` —— tempo map 的权威实现：

```
buildTempoMap(baseBpm, offsetMs, bpmPoints)
  · 只取 beat > 0 的点，按 beat 排序
  · 分段线性：段内 ms/beat = 60000/bpm
  · mode "abs" → 该点起绝对 BPM；"mult" → 当前 BPM × value
  · BPM 夹在 [20, 999]
  · 导出 segments{beatStart,beatEnd,bpm,timeStartMs,timeEndMs}
         + bpmAtBeat/bpmAtTime/timeOfBeat/beatOfTime
snapBeat(beat, div)     // 吸附网格
beatParts/fmtBarBeat    // ★ 写死 4 拍一小节
```

**⇒ 结论（对桥极其重要）**：
`timeMs` 是 `beat` 的**纯函数**，**不携带额外信息**。
所以桥**应该传 `beat`，不该传 `timeMs`**；并且**两边的 tempo map 必须一致**，
否则 `beat ⇄ ms` 直接错位。→ 见 §3.4「以我们为准」的落地方式。

### 1.3 剩下的语义（`loop` / `parentId` / `attrs` / `type` / `locked` / `hidden`）

| 字段 | 语义 | 出处 | 对桥的含义 |
|---|---|---|---|
| `loop: {interval, count, exclude?}` | **一个主点循环展开**：`interval` 单位 = **拍**（不是格）；子点 = `parent.beat + k·interval`，`k` 从 **1** 到 `count` ⇒ **父点本身不算**，总共 `count + 1` 个点；`exclude` 是要跳过的下标数组 | `types.ts`；`store.ts:643-648`（`refreshChildren`） | ★ **快照不展开** ⇒ **展开是我们的责任** |
| `parentId` | 循环**实例**指回父点 id | `types.ts` | 展开后当**溯源信息**保留，别当成独立音 |
| `attrs` | **类型化轨道**上的插件自定义字段（`trackTypes.register` 的 `fields` 默认值在放置/粘贴时自动补齐） | `types.ts` + `plugin-system.md` | ★ **逐点可挂任意数据的唯一位置** |
| `track.type` | 缺省或 `"beat"` = 内置音砖轨；否则 `"<pluginId>:<localId>"` | `types.ts`；`api.ts` 里 `t.type ?? "beat"` | ★ **轨道级唯一的自由字段** ⇒ 用它表达**角色**（见 §3.6） |
| `track.locked` / `hidden` | 锁定 / 隐藏 | `types.ts` | ★★ **`hidden` 的轨连 marker 一起不进快照**（`api.ts` 的 `hiddenSet`）⇒ **天然的"这条轨别导"开关** |
| `ProjectNote` | 时间轴便签：`{timeMs, y, text(markdown), locked}` | `types.ts` | 可用于「把我们的说明写进他的时间轴」 |
| `Segment` | `{beatStart,beatEnd,bpm,timeStartMs,timeEndMs}` **是导出的** | `types.ts` | 我们能直接拿它的分段；**我们自己的分段格式可以直接对齐** |
| **吸附** | `addMarker` → `snapped(rawBeat)` = `snapEnabled ? snapBeat(b, snapDiv) : round(b)`（`store.ts:329,678`）⇒ **开 snap 就吸附，关 snap 时连整数都四舍五入**；★ **循环子点是例外，`refreshChildren` 不做吸附**，保留 `interval` 的精确拍位 | `store.ts:645-648` | ★★ **反向写回会被吸附** ⇒ 见 §3.10 |


### 1.4 插件宿主的真实能力（决定桥能不能成立）

`docs/plugin-system.md` + `src/main/plugins.ts`：

- `renderer.js`：普通脚本，`window.__bdgPluginRegister(activate)`；**主世界**执行，
  ⇒ **标准 `WebSocket` / `fetch` / `EventSource` 都能用**（沙箱只挡 Node，不挡 Web API）。
- `main.js`：`require(full)` **在主进程加载，完整 Node + Electron**，`activate` **必须同步**。
  ⇒ **能起 http/ws 服务**。**但是** `ctx = {id, dir, log, registerHandler, onDispose}`
  —— **没有给渲染层回推的通道**（只有 `callMain` 单向 renderer→main）。
- `api.system.audioPath()` → **当前音频的绝对路径**（`api.ts` 里 `store.project.audioPath`）
  ⇒ 我们**不用重新选音频**。
- `api.system.openWindow(url)` → 打开任意页面 ⇒ 可以把我们的界面开在他旁边。
- 编辑 API 齐全且**全部进撤销栈**：`addTrack/removeTrack/renameTrack/setTrackLocked/
  setTrackHidden/addMarker/moveMarker/removeMarker/setMarkerAttrs/setMarkerLoop/
  addTypedTrack/addBpmPoint/removeBpmPoint/setBaseBpm/setOffset/batch/undo/redo`。
- `api.events.on("project"|"selection"|"playhead"|"playing")` ⇒ **推送触发源**齐了。
- 许可：**宿主 GPLv3；插件是作者自己的作品、可自选协议**（`plugin-system.md` 明写）。

**⇒ 桥的形态被这些事实唯一确定了**（见 §3.2）。

***

## 2. 结论：**不照搬，走协议**（用户说的对）

不照搬的理由（不止"屎山"）：

1. 宿主是 **GPLv3**；fork 会把我们拖进传染。
2. 它是 **Electron + Vue**（`Timeline.vue` 64KB、`store.ts` 58KB）；
   我们是 **Python core + 自家 Electron 壳** —— 技术栈不同，抄不动。
3. 它**没有任何求解能力**（只把拍折成角度），我们有整套求解器；
   真正该共享的是**数据**，不是代码。
4. 它的角度逻辑本身有问题（`bdg_plugin_adofai` README #8/#9）——
   **它在等我们 `docs/16` 的那套公式**。

⇒ **桥的目标：让两边各干各的强项 —— BDG 负责"人怎么踩点/分段"，
我们负责"怎么把点变成合法的谱"。**

***

## 3. ★ WebSocket 桥设计

### 3.1 一句话

**我们的 sidecar 当 WebSocket 服务端；BDG 的 bridge 插件 `renderer.js` 当客户端。**
BDG 里改一点 → 我们这边谱面实时重算；我们这边改一点 → 推回去写进 BDG 的工程。

### 3.2 谁当服务端？（**必须是我们**，有硬证据）

`main.js` 虽然有完整 Node、能起 server，但 **`ctx` 没有渲染层回推通道**
（`PluginContext` 只有 `log / registerHandler / onDispose`），
所以「主进程当服务端」= **只能 BDG→我们单推**，我们的编辑指令回不到 BDG 编辑器里。

而 `renderer.js` 在主世界、能用 `WebSocket` ⇒ **它当客户端最顺**。
再加上我们侧本来就是长驻 HTTP 服务（`sidecar/server.py`，`ThreadingHTTPServer`），
**加一条 `/ws` 是零结构改动**。

```
┌─────────── BDG (Electron + Vue) ───────────┐        ┌────── 我们 ──────┐
│ bridge 插件 renderer.js                     │  ws    │ sidecar/server.py │
│   api.events.on("project") ─┐               │◄──────►│   /ws 端点        │
│   api.project.snapshot()   ─┴─► 发          │  :PORT │   ▼               │
│   api.project.edit.batch(...) ◄── 收         │        │ session.rebuild() │
│   api.system.audioPath()                    │        │   ▼               │
└─────────────────────────────────────────────┘        │ 谱面 / 导出        │
                                                       └──────────────────┘
```

### 3.3 传输：WS 还是复用已有的 SSE+POST？

| | **W · WebSocket（用户提议）** | **S · SSE + POST（现成）** |
|---|---|---|
| 双向 | 一条连接 | 两条（`GET /api/events` 推 + `POST /api/*` 收） |
| 我们侧现状 | 要加端点 + 手写握手/帧（stdlib 无 WS） | **`text/event-stream` 已经在跑了**（`server.py:167`），`do_POST` 也在 |
| BDG 侧 | 原生 `WebSocket` | `EventSource` + `fetch` |
| 心跳/重连 | 自己管 ping/pong（或靠 WebSocket 内建 close） | SSE 有自动重连语义 |
| 延迟 | 更低、连接态明确 | 够用 |

**建议：按 W 设计消息层，把传输做成可换的薄壳。**
先落 **W**（用户明确要，且"连接态"对 UI 反馈友好：BDG 插件面板能显示 ●已连接）；
`S` 变体只需 20 行（复用现有 SSE+POST），留作 fallback。
**都用 stdlib + 手写**（项目已有"零依赖 SMF writer"的先例），不引第三方库。

### 3.4 ★★「以我们为准」的落地 —— ⚠️ **原方案是错的，已按实测更正**

**我原来的想法**：把我们的 tempo 表**写进**宿主的 `bpmPoints`，两边共用一张表。
**实测证明这会造成事故** —— 见 `docs/36` §11.4：

```
timeMs = timeOfBeat(beat)      // 它是 baseBpm / offsetMs / bpmPoints 的函数
```

⇒ **改宿主的 `bpmPoints` / `offsetMs` ⇒ 他工程里所有 marker 的 `timeMs` 集体平移**，
整个工程与音频脱钩。**绝对不能动。**

**更正后的设计**：

| | 谁说了算 | 怎么做 |
|---|---|---|
| **`beat ⇄ ms` 的锚**（`baseBpm` / `offsetMs` / `bpmPoints`） | **BDG**（他对着波形对的轴，他是对的） | **只读，不改**。我们用它当**双向换算器**：读 `ms = timeOfBeat(beat)`；写 `beat = beatOfTime(our_ms)` |
| **音乐内容**（SetSpeed 值 / 双押 / 图形 / Δ 预算） | **我们** | 算好之后写进**插件自己的 BPM 轨**的 marker + `attrs`（就是他插件读的那条），**不碰宿主 `bpmPoints`** |
| 两边冲突（宿主 `bpmPoints` 不是 no-op 且有实质变速） | —— | **报出来让人选**，不偷偷改 |

**为什么这样反而更准**：`timeOfBeat` / `beatOfTime` 在段内是**互逆**的。
我们只要把自己算出的**毫秒**用他的 map 反解成 `beat` 交过去，
他再 `timeOfBeat(beat)` 就**精确还原我们的毫秒** —— 不需要两张表长得一样。

> **"以我们为准"的正确含义 = 谱面的音乐内容以我们为准（我们算的才合法：
> 2 的幂档、SetSpeed 落平格、Δ ≤ 25ms）；
> 而"音频与拍号的对齐"以 BDG 为准（他看得见波形）。**
> 这条边界原方案搞反了。

### 3.5 消息协议草案

公共信封：`{"v":1,"type":"…","seq":n,"ts":…}`

| 方向 | type | 载荷 | 说明 |
|---|---|---|---|
| BDG→我们 | `hello` | `{token, plugin:"0.1.0", bdg:"2"}` | 握手，校验一次性 token |
| BDG→我们 | `project` | `{project: <BeatProject-lite>}` | **全量快照**（去掉 notes/颜色等无用字段） |
| BDG→我们 | `selection` | `{kind, id, markerIds}` | 「只导我选的这一段」的来源 |
| BDG→我们 | `playhead` | `{beat}` | 试听对轴（我们预览条跟着动） |
| BDG→我们 | `audio` | `{path, name, md5}` | `system.audioPath()`；**我们直接用这个文件** |
| 我们→BDG | `pull` | `{}` | 请求一次全量 |
| 我们→BDG | `tempo` | `{base_bpm, offset_ms, points:[{beat,mode,value}]}` | §3.4：**改写他的 BPM 表** |
| 我们→BDG | `import` | `{tracks:[…], bpm_points:[…], twirl_beats:[…], notes:[…]}` | 把我们算好的东西写成他的轨道 |
| 双向 | `ping/pong` | `{}` | 心跳；断线由客户端 3s 重连 |
| 双向 | `ack` | `{seq, ok, error?}` | 每次写操作回执（**不许静默失败**，沿用我们 b 的口径） |

**分两期**：
- **v1 = 全量同步**（`project` / `import` / `tempo`）——简单、可测、够用；
- **v2 = 增量 `patch`**（`ops:[{op:"addMarker"|"moveMarker"|…}]`）—— 只在实测到卡顿时再做。

### 3.6 角色（主 / 次 / 双押 / 关）怎么存进去？

`MarkerTrack` **除了 `type` 没有轨道级的自由字段**（`attrs` 只在 marker 上）。
所以我们有四个候选，按推荐度：

1. ★ **`type` = 角色**：bridge 插件 `trackTypes.register` 四条类型
   —— `bridge:main` / `bridge:sub` / `bridge:dp` / `bridge:off`
   （外加内置 `"beat"` 默认 = 主）。
   优点：**格式原生、`.bdg` 会持久化、未装插件也能读**、侧栏 `＋` 直接能建。
2. `marker.attrs.role` 逐点覆盖（给"这一段这条轨改成次"用）——与 1 叠加。
3. 轨道名约定（`[dp] Kick`）——零成本但脆，作为兜底。
4. `hidden` = **整轨不导**（宿主已经这么实现了：hidden 的轨不进快照）——
   **白送的"关"档**，可以直接复用。

⇒ **推荐 1 + 2 + 4**。

### 3.7 `loop` 的展开（必须在我们侧做）—— ✅ 语义已确认

快照**不展开**循环，只给 `{interval, count, exclude}`。已确认（`store.ts:643-648`）：

- `interval` 单位 = **拍**（`parent.beat + k·interval`，beat 本身就是拍）；
  `0.5` = 半拍；
- `k` 从 **1** 开始到 **`count`** ⇒ **`count` 不含第 0 次**，总共 `count + 1` 个点；
- **子点不吸附**（`refreshChildren` 不做 `snapBeat`），保留 `interval` 的精确拍位。

我们侧展开：

```python
emit(parent)                                   # 第 0 次：父点自己
for k in range(1, count + 1):
    if (k - 1) in exclude: continue            # ⚠ 下标基准待与他们对一次（0 基还是 1 基）
    emit(beat = parent.beat + k * interval, parentId = parent.id)
```

`parentId` 保留为**溯源**，不参与「一个音 = 一个 onset」的判定。

### 3.10 ⚠ 反向写回的**吸附风险**（确认吸附之后才暴露出来的）

`store.addMarker` 会 `snapped(rawBeat)`：**开 snap 按 `snapDiv` 吸附；关 snap 也 `Math.round`**。
而循环子点不吸附。

⇒ 我们 `import` 时如果直接把「由 onset 反推的 beat」写进去，**BDG 会把它挪到吸附网格上**，
我们精心算的时序就被改掉了。三条对策（**建议全上**）：

1. **写回后回读校验**：`import` → `pull` → 逐点比对 `beat`，
   偏差超阈值就**报出来**（沿用我们 b/a 那一轮的「不许静默」口径），
   并在 BDG 面板上显示「已同步 N 点 / M 点被吸附偏移（最大 x 拍）」。
2. **可选：写成 `loop` 子点**（子点不吸附）—— 但那是**滥用**，只在极端精度需求下提供，
   且默认关闭。
3. **问清楚 `moveMarker` 是否也吸附**（`addMarker` 吸附已确认，`moveMarker` 未确认）；
   若 `moveMarker` 不吸附，就改用「先在吸附网格上 `addMarker`，再 `moveMarker` 到位」。

### 3.8 安全与健壮

- **只听 `127.0.0.1`**（我们 sidecar 已经是 `--host 127.0.0.1` 默认）。
- **一次性 token**：我们 GUI 里显示 `ws://127.0.0.1:PORT/ws?token=XXXX`，
  粘贴进 BDG 插件面板。理由：宿主的文档明说「**不弹权限确认，安装插件即视为信任**」
  ⇒ 同机任何程序都可能连上来，token 是**我们**的责任。
- **不信任对端数据**：所有进来的东西当**外部输入**校验（拍号有限、值域、数量上限），
  和我们现在校验 MIDI 一样。
- **回执 + 状态**：BDG 面板显示 ●已连接 / 已同步 N 轨 / 上次错误。

### 3.9 顺带白拿的两条通道

| | 说明 |
|---|---|
| **离线 `.bdg` 文件** | `BeatProject` 就是 JSON ⇒ **不做 WS 也能互通**。适合"把工程发给朋友"。桥应该**同时支持**这条：`文件 → 打开 .bdg` + `导出 .bdg`。 |
| **`openWindow(url)`** | 在 BDG 里直接开我们界面（或一个只读的"桥状态/谱面预览"页）。可作为 v2 的彩蛋。 |

***

## 4. 与 0.4 合并：三件事本来就是同一个

```
        ┌────────────── 音轨（第一类对象）──────────────┐
来源： MIDI 轨 │ 音频检测（xk base）│ BDG 工程 │ 手工点
角色： 主 / 次 / 双押 / 关      ← 角色随区间变化（= 泳道模型）
        └──────────────────┬──────────────────┘
                           ▼  onsets + 约束
        solve()（BPM 表 · 双押需求 · 预留槽位 · Δ 预算）
                           ▼
                        .adofai
```

- **分段采音**（`docs/34`）= 音轨角色随时间变。
  **编辑器外包给 BDG**（§3.6 的 `type` = 角色）⇒ `docs/34` 里最贵的泳道编辑器**可以不写**。
- **xk base**（`docs/27`）= 一种新的**来源**；
  而 BDG 的 `bpmPoints` 正是"人工写好的变速表" ⇒
  §3.4 的 `tempo` 消息让两边共用同一张表，**xk base 与 BDG 天然咬合**。
- **桥** = 这一层的**序列化格式**（`.bdg` + WS 消息）。

**一次做大版本**的理由：三者共享同一个中间层；分开做会各造一套。

***

## 5. 落地顺序（建议）

| # | 做什么 | 交付物 | 风险 |
|---|---|---|---|
| 0 | **公式回流**：把 `docs/33` + `docs/16` 整理成一页给朋友 | 一页文档 | 零 |
| 1 | **`core/bdg.py`**：`.bdg` ⇄ 我们的音轨集合（**纯数据、零依赖**，含 loop 展开、`type`→角色） | 模块 + 单测 | 低（离线就能验） |
| 2 | **`/ws` 端点 + token**（stdlib 手写 WS）+ 消息层 v1（全量） | sidecar 改动 | 中 |
| 3 | **BDG 侧 bridge 插件**（我们仓库一个目录，分发物） | ~150 行 JS | 低（只用文档化 API） |
| 4 | **分段采音**：只做「读角色 + 读区间」 | 替换 `docs/34` 的编辑器 | 中 |
| 5 | **xk base** 作为新来源接进中间层 | `docs/27` | 高（详见那篇） |

> **注意 1 和 2 的顺序**：先在**离线**上把格式与语义跑通（`core/bdg.py` + 单测），
> 再上实时 —— 这样即使 WS 出问题，桥也是可用的。

***

## 6. 已确认 / 待确认

### 6.1 ✅ 已确认（用户给行号 + 真实工程实测，2026-10）

| # | 问题 | 答案 | 依据 |
|---|---|---|---|
| 1 | `loop.interval` 单位？ | **拍** | `store.ts:645` |
| 2 | `count` 含第 0 次吗？ | **不含**（`k = 1..count`）⇒ 共 `count+1` 点 | `store.ts:643` |
| 3 | 放点会吸附吗？ | `addMarker` **会**（`store.ts:329,678`）；**循环子点不会**（`store.ts:645-648`）。★ 但真实工程里**存在非网格 beat**（`.0064` 一族）⇒ 说明**另有不吸附的写入路径** | `docs/36` §11.3 |
| 4 | `exclude` 的下标基准？ | **就是 `k` 本身**（`k ∈ [1, count]`）。实测 4 组带 `exclude` 的母点，`缺失的 k` 与 `exclude` **逐一相等**；且 `子点数 = count − |exclude|` 对 **92/92 全中** | `docs/36` §11.2 |
| 5 | `bpmPoints` / 插件 BPM 轨谁权威？ | **宿主 `bpmPoints` 管 `beat⇄ms` 的锚（只读）；插件 BPM 轨管真实变速（我们写）** —— 实测这份工程里宿主 `bpmPoints` **是个 no-op**（`mult 1`），真变速全在插件轨上 | `docs/36` §11.4 |

### 6.2 ✅ 写回吸附：**已按宿主源码定案**（2026-10，proxy 拉到仓库之后）

**用户答复：**「是吸附的，但是**也可以不吸附**」—— 对着源码读，两句话都对，但**是三件不同的事**：

```ts
// store.ts:315,317-319
const round = (b: number): number => Math.round(b * 1e6) / 1e6;   // ★ 1e-6 精度，不是整拍
function snapped(b: number): number {
  return store.ui.snapEnabled ? snapBeat(b, store.ui.snapDiv) : round(b);
}
// store.ts:736-744  ← ★ 用户说的「可以不吸附」
export function moveMarker(id: string, rawBeat: number, force = false): boolean {
  const beat = Math.max(0, force ? round(rawBeat) : snapped(rawBeat));
// tempo.ts:109-112
export function snapBeat(beat: number, div: number): number {
  if (div <= 1) return Math.round(beat);          // div=1 才是整拍
  const step = 1 / div; return Math.round(beat / step) * step;
```

| 情形 | 公式 | 精度 / 损失（866 点实测，1 拍 = 312.5ms） |
|---|---|---|
| 吸附开，`div=1` | `Math.round(beat)` | 整拍 ⇒ 最坏 0.4936 拍 = **154.25 ms**，426 点超预算 |
| **吸附开，`div=4`（常见档）** | 吸到 1/4 网格 | 866/866 被挪，最坏 0.1186 拍 = **37.06 ms**，**23 点超 25ms** |
| 吸附开，`div=16` | 1/16 网格 | 866/866 被挪，最坏 8.65 ms |
| **吸附关** | `round(b*1e6)/1e6` | **1e-6 拍 ≈ 0.3µs ⇒ 实践上无损**（20/866 点动 ≤0.0001ms） |
| `moveMarker(..., force=true)` | `round(b*1e6)/1e6` | 同上 —— **但插件 API 没暴露 `force`** |

**三条结论**：

1. ★ **`beat=0.0064` 的来源找到了**：就是**关吸附**路径（`round()` 把 beat 量化到 1e-6 拍），
   不是什么「神秘的第三条路径」；
2. **写回无损可行**，条件是**用户在 BDG 里关掉吸附**；插件 API 侧要无损则需宿主给
   `api.project.edit.moveMarker` 加一个可选 `force`（向后兼容的小改动，**但那是他那边的事**）；
3. ★ **按用户口径 v0.4 只读**（桥只服务分段采音）⇒ **吸附不再是拦路石**。
   将来真要做写回，账已算好：`core/bdg/snap.py` + `tools/_bdg_snap_audit.py` + 单测 J 组。

> 我第一版把「div=1 吸附」当成「关吸附」来断言（说关吸附最坏 154ms）——**错的**，已更正并落成断言。

### 6.3 需求（用户 2026-10）

> 「他的保存格式后续可能修改。我们需要考虑**软编码格式解析**来方便后续维护。」

⇒ 独立成篇：**`docs/36-BDG格式软解析.md`**。
