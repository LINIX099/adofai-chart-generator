# 22 · 谱面预览改用 Re_ADOJAS 的渲染引擎

> 用户口径：先是「把现有的谱面预览导航页的逻辑换成它（`adofaiex/Re_ADOJAS`）的」，
> 在我走了一轮弯路之后明确为 **「这个项目的逻辑是完备的，你把它搬过来用」**，
> 范围确认为 **A2：只 vendor 它的播放器引擎，嵌进现有页面；只做「像 ADOFAI 那样播放」
> 的预览，不要编辑器那一套 chrome**。

---

## 0. 先说结论

谱面预览现在跑的就是 **Re_ADOJAS 自己的 Three.js 渲染引擎**（`lib/Player`），
不是我照着它的常量手搓的第二版。旧的 canvas 2D 预览已归档到
`_archive/chart-view-2d/`。

## 1. 我在这件事上错在哪（要留痕）

| 我说过的 | 事实 |
|---|---|
| 「`Player.ts` 201KB + Three.js + WASM，整体移植基本等于重写一个播放器，成本小不了」 | **错的。** `pnpm install` 17.8s，写一个 lib 构建 20 分钟。WASM 是**预编译好的二进制**，核心库 `adofai` 就是**一个 npm 包** |
| 隐含假设「这个环境装不了依赖」 | 失败的只是 **Electron 从 GitHub Releases 下二进制**那一步；`registry.npmjs.org` 一直是通的（实测 HTTP 200） |
| 于是把「直接用它」当成不可行，转而去读它的几何常量、在自己的 canvas 2D 里重写 | 典型的**重复造轮子**，而且两头不靠（见 §2） |

**教训**：把「某个特例失败」当成「通则」，然后据此砍掉一个选项 —— 这次代价是一整轮返工。

## 2. 那条弯路本身也有信息量

我先按 Re_ADOJAS 的 `Geo/mesh_reserve.ts` 在 canvas 2D 里重写了格子几何
（`TILE_WIDTH 0.2695 / TILE_LENGTH 0.49 / OUTLINE 0.0125`，`CaculatePoints` 逐字移植）。
结果很崩坏，而反编译游戏本体后才知道**根本前提就错了**：

真游戏（`Assembly-CSharp.dll`）的 `scrFloor.UpdateAngle` 有**两条完全不同的渲染路径**：

```csharp
// mesh 路径
float num  = (MathF.PI / 2f - (float)entryangle) % (MathF.PI * 2f);
float num2 = (MathF.PI / 2f - (float)exitangle) % (MathF.PI * 2f);
floorMeshRenderer.SetAngle(num, num2);
floorMeshRenderer.floorMesh._curvaturePoints = (midSpin ? 3 : 40);

// sprite 路径
private void SetSpriteFromChar(bool rotate = true) {
    Sprite[] array = Mathf.RoundToInt(scrMisc.getAcuteAngle(entryangle, exitangle) * 57.29578f) switch
    {
        0 => midSpin ? lm2.arrMidspin : lm2.arr0,
        15 => lm2.arr15, 30 => lm2.arr30, 45 => lm2.arr45, 60 => lm2.arr60, 75 => lm2.arr75,
        90 => lm2.BigTiles ? lm2.arr90 : lm2.arrBend,
        105 => lm2.arr105, 108 => lm2.arr108, 120 => lm2.arr120, 129 => lm2.arr128,
        135 => lm2.arr135, 150 => lm2.arr150, 165 => lm2.arr165,
        _ => lm2.BigTiles ? lm2.arr180 : lm2.arrStraight,
    };
    ...
    scrMisc.Rotate2DCW(floorRenderer.transform, rotation);   // 精灵再整体旋转
}
```

即：**格子是「按转角分桶的精灵」或「mesh+shader」，都不是「一个方块转一下」**。
所以我那版无论怎么调都不可能对 —— 而 Re_ADOJAS 是一套完整的替代实现，
直接用它的引擎，比复刻它的常量靠谱得多。

> 顺带：`scnEditor` 里还有一批我们**没建模**的官方键 —— `tileShape`、`scalingRatio`、
> `trackTexture` / `trackTextureScale`、`trackShadowColor`、`floorIconOutlines`、
> `showDefaultBGTile` / `defaultBGTileColor` / `defaultBGShapeType` / `defaultBGShapeColor`
> （参考截图里那个棋盘格背景就是最后这几个）。反编译源码留在 `out/_adofai_src/`。

## 3. 接入方式（A2）

### 3.1 拿仓库 + 装依赖

```powershell
curl.exe -sL -o re_adojas.tar.gz https://codeload.github.com/adofaiex/Re_ADOJAS/tar.gz/refs/heads/main
tar.exe -xzf re_adojas.tar.gz -C vendor          # → vendor/Re_ADOJAS
cd vendor/Re_ADOJAS; pnpm install                # 17.8s
```

### 3.2 一个只有播放引擎的 lib 构建

它主构建的 `vite.config.ts` 里有自定义插件 `vite-plugin-wasm-inline`
（把 wasm 内联成 base64 供 `virtual:wasm-*` 用）和 `vite-plugin-glsl`。
**复用这两个插件**另写 `vite.embed.config.ts`，只打一个入口：

```powershell
pnpm run embed      # → dist-embed/adofai-player.js（9.8MB，gzip 4MB）
```

产物丢到 `app/renderer/vendor/adofai-player.js`，前端动态 `import()`。
**没有 React / Tailwind / Radix 负担**，也不动我现有的参数面板与其它三个视图。

### 3.3 嵌入入口 `vendor/Re_ADOJAS/src/preview-embed.ts`

包一层最小 API：`createPreview(container, levelText, audioUrl, opts) → PreviewHandle`
（`startPlay / pause / resume / seekTo / selectTile / getTileTimeMs / getTileIndexAtTime /
currentTileIndex / destroy`）。加载序列**照抄它自己的 `useFileHandlers.ts`**：

```ts
const level = new ADOFAI.Level(levelText, new Parsers.StringParser())
level.on('load', (loadedLevel) => {
  const player = new Player(loadedLevel, 'webgl')
  player.createPlayer(container)
  ...
})
level.load()          // ★ 少了这句，'load' 永远不来
```

> **踩到的坑**：`level.load()` 必须显式调用。注册完监听不 load，表现是**静默超时**
> ——没有报错、没有事件，只有干等。它自己的代码在 `useFileHandlers.ts:201`。

### 3.4 sidecar 给谱面 JSON

新增 `POST /api/leveljson`，内部走 `Session.level_json()` → **`writer.build_json()`**
—— 和导出写盘是**同一个函数、同一组参数**，所以「预览看到的」和「导出成品」
不会变成两套时序。

## 4. ★ 「走过的格子不消失」的真根因

不是值调小了，是**结构上等于永不消失**：

```csharp
// TimelineManager.buildAnimateTrackKeyframes
if (disappearType !== 'None' && scaledBeatsBehind > 0 && floor < totalTiles - 1)
    this.buildDisappearKeyframes(...)      // beatsBehind = 0 时这个分支根本不进
```

我们导出模板原来是 `beatsBehind: 0`，所以 `trackDisappearAnimation: "Fade"`
写了也白写 —— 一个消失关键帧都不会建。

语料（633 张真实 `.adofai`）分布：**0 占 423、4 占 168**，0 才是多数派。
但用户口径是「要 ADOFAI 那样的播放」，所以**默认改成 4**，
并且预览与导出共用同一个值（`writer.build_json(..., beats_behind=4)`）。

## 5. 前端接线

| 面 | 怎么接 |
|---|---|
| 页签 | `#cv-adofai`（div）就是 `.view`；`setTab` 里 **`chart` → `cv-adofai` 要单独映射**，按 `cv-${name}` 匹配会把所有视图都关掉（页面全黑、容器 0×0） |
| 播放/暂停 | `togglePlay()` 在谱面预览页优先驱动播放器：`isPlaying ? pause() : (播过 ? resume() : startPlay(currentTimeMs))` |
| 定位 | `seek(ms)` 在谱面预览页优先 `preview.seekTo(ms)`；底部滑块与全曲条拖动都走它 |
| 格导航 | 全曲条的 `selectFloor` → `preview.selectTile(i, true)`（它的 API 和我们的格导航本来一一对应） |
| 走带时钟 | 播放器有**自己的音频与时钟**，`<audio>` 那套在这页是停的 → 单独一根 100ms 线把全曲条播放头 / 滑块 / 时间标签跟着它走 |
| `curFloor()` | 预览在播就用播放器的格号；否则按 `<audio>` 位置在全曲条上反查 |

> ★ **2026-10 补**（`docs/24` §3）：这页的「轴」全部改成显式换算 ——
> `payload` 统一输出**采音轴**，`<audio>` 轴 = 采音轴 + `audio_lead_ms`，
> 谱面轴 = 采音轴 − `audio_shift_ms`（喂给播放器）。
> 同时接上了播放器自带的**偏移修正**（`setMusicDelayMs` / `getSuggestedAudioDelayMs`），
> 控制条上给了「音乐延迟补偿」数值框与「按实测建议」按钮：
>
> | 面 | 怎么接 |
> |---|---|
> | 轴换算 | `app.js` 的 `audioToGrid` / `gridToAudio` / `chartToGrid` 三个函数，滑块、全曲条拖动、`curFloor()`、加区间、`seek()` 全走它们 |
> | 偏移修正 | `PreviewOptions.musicDelayMs` + `PreviewHandle.setMusicDelayMs/getMusicDelayMs/getSuggestedMusicDelayMs`；控件是 schema 的 `music_delay_ms`（`schedule:false`，播放中立即生效、不重算谱面） |

## 6. 退役旧的 2D 谱面预览

按用户口径「归档，现有版本不要它了」：

- `app/renderer/views/chart.js` → **`_archive/chart-view-2d/chart.js`**（附 README 说明原因与恢复步骤）
- 拆掉 `index.html` 的 `#cv-chart`、`app.js` 的 `ChartView` 引用与那排 vbar 控件
- `sidecar/schema.py` 删掉旧的 `chartview` 分组（`cspan / cfollow / ctravel / cbad`，均已失效）；
  **2026-10 该分组 id 被复用**来放 `music_delay_ms`（谱面预览的偏移修正）

**代价（记一笔）**：「贴太近」红框那个自交诊断**没有可视化**了。
`core` 的 `path_overlap_stats` / 规则违规仍会在状态栏文字报告里给出。

## 7. 验收

| | 结果 |
|---|---|
| `npx electron . --e2e` | **91/91**（原 83 − 退役掉的几何断言 + 新增播放器断言） |
| `npx electron . --probe` | **4/4**（就绪 / 不自动播 / 播放键能播 / 再按能暂停） |
| `python tests/test_sidecar.py` | **79/79** |
| 其余 15 个 Python 套件 | 全绿（`test_ogg_offset.py` 约 4min，不在例行） |

e2e 新增/改写的断言：
`谱面预览：ADOFAI 引擎就绪` / `引擎给出真实时长` / `播放器把自己的 canvas 挂进了容器` /
`刚进谱面预览不自动播` / `beatsBehind > 0` / `消失动画不是 None` /
`播放键能驱动 ADOFAI 预览` / `再按一次能暂停 ADOFAI 预览` / `全曲条选格同步到 ADOFAI 播放器`。

## 8. 还没做 / 已知问题

1. **相机取景**：行星没有居中（一直在画面中央偏右上），自然播放和 seek 后都一样，
   不是「追不上」。已排除 `setEditorMode`（它只影响 `editorOnly` 的 PositionTrack 事件）。
   可疑点：我们模板 `zoom: 200`，而 Re_ADOJAS 自己的样例关卡是 `zoom: 100`（差 2×）。
   **没有依据之前不动它。**
2. 播放器自带的 `JudgmentDisplay` 判定条和 `OverlayHUD`（FPS/TBPM/CBPM/Map Time/Tiles）
   现在都显示着。HUD 对做题有用，判定条对「预览」是噪音 —— 待定。
3. `dist-embed` 的 9.8MB bundle 目前是**构建产物直接进仓库**，没有 gitignore/CI 概念
   （本工作区不是 git 仓库）。
4. 反向也成立：既然能把它的播放器搬进来，**游戏本体的 `scnEditor`（已反编译）**
   就是做「真·编辑器 chrome」时的权威来源。
