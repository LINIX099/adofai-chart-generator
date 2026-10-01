# 21 · 谱面预览导航：改成 Re_ADOJAS 的「格」导航

> 用户口径：「前往这个仓库 `adofaiex/Re_ADOJAS`，把现有的谱面预览导航页的逻辑换成它的」。
> 确认过范围 = **全曲预览条的导航逻辑**（不是整页路由、不是 3D 播放器），
> 且**保留**现有的「Shift+拖动框选区间」与「滚轮缩放」。
> 前置：`docs/20`（全曲预览条 + 区间采音）。本篇记录替换后的语义、映射与验收。

---

## 1. 参考实现到底做了什么

去仓库读了源码。**关键：不要认错文件。**

- `src/lib/Player/TimelineManager.ts`（53KB）**不是**导航 —— 它是 `MoveTrack` /
  `AnimateTrack` / `MoveCamera` 的关键帧-补间引擎（DOTween 语义、`Kill(complete:true)`、
  离散时间轴）。和「导航」无关。
- `src/pages/HomePage.tsx` 只是落地页（logo + 进编辑器的按钮 + mesh/settings 链接）。
- **真正要抄的是 `src/pages/Editor/EditorPage.tsx` 里那条 Timeline**：

```tsx
// 开关按钮 —— 播放键旁边
<button title="Timeline" onClick={() => setTimelineOpen(!timelineOpen)}>…</button>

// 整曲 slider
{timelineOpen && (
  <input type="range" min={0} max={totalMs} value={sliderValue}
    onChange={e => {
      const v = Number(e.target.value)
      setSliderValue(v)
      p.seekTo(v, !playModeActive)              // ① 先 seek
      p.selectTile(p.getTileIndexAtTime(v))     // ② 再反查「第几格」并选中
    }} />
)}

// 播放中 100ms 轮询推进 slider
useEffect(() => {
  if (!playModeActive) return
  const id = setInterval(() => setSliderValue(previewerRef.current.currentTimeMs), 100)
  return () => clearInterval(id)
}, [playModeActive])

// 键盘逐格（播放中直接 return，不抢）
if (e.code === 'Home')        p.selectTile(0)
else if (e.code === 'End')    p.selectTile(len - 1)
else if (e.code === 'ArrowRight') p.selectTile(Math.min(cur + 1, len - 1))
else if (e.code === 'ArrowLeft')  p.selectTile(Math.max(cur - 1, 0))

// 播放键：有选中的格就从那一格开始
const handlePlayWithSeek = () => {
  const selectedIdx = p?.selectedTileIndex ?? null
  if (p) p.deselectTile()
  if (playMode === 'preview' && selectedIdx !== null) handlePlay(p.getTileTimeMs(selectedIdx))
  else handlePlay()
}
```

**它的导航单位是「格（tile / floor）」，不是毫秒。** 这是跟本项目原实现最本质的差别：
原实现是「音频毫秒轴的 scrub + Shift 框选」，格只用来画细线。

## 2. 名词映射

| Re_ADOJAS | 本项目（`overview.js`） | 说明 |
|---|---|---|
| `selectedTileIndex` | `selFloor` | `null` = 未选 |
| `selectTile(i)` | `selectFloor(i)` | 只改状态 + 通知，**不 seek**（原版 seek 也由发起者做） |
| `getTileIndexAtTime(ms)` | `floorAt(ms)` | 二分：`entry[i] <= ms` 的最后一格 |
| `getTileTimeMs(i)` | `floorTime(i)` | 就是 `entry[i]`（音频轴毫秒） |
| `tileCount` | `nFloors` | `= entries.length` |
| `deselectTile()` | `clearFloor()` | |
| `handlePlayWithSeek` | `togglePlay()` 里的分支 | |
| slider `min=0 max=totalMs` | 就是全曲条本身 | 本项目用**条**代替了那条 slider |

`entry[]` 直接当音频毫秒用是对的：`tools/_axis_probe.py` 实测预览音频里
「第一次按下的发声时刻 == `entry[1]`」，差 **−0.544ms**（渲染起振时间），
且与既有 `chart.js` 点击跳转的用法一致。

## 3. 实现

### 3.1 `app/renderer/views/overview.js`

- 新增 `selFloor` + `floorAt / floorTime / selectFloor / stepFloor / firstFloor /
  lastFloor / clearFloor`。
- **左键按下/拖动** = `_pickAt(t)`：`onSeek(t)` **然后** `selectFloor(floorAt(t))`
  —— 严格对应原版的 `seekTo` + `getTileIndexAtTime` + `selectTile`。
  `stepFloor()` 在 `selFloor === null` 时从**播放头所在的格**起步（原版同样用 `cur` 兜底）。
- 新增「选中格」绘制：把 **本格进入到下一格进入** 整段铺一层淡绿
  （`rgba(126,231,135,0.13)`）＋ 左侧 2px 绿线 ＋ 顶部小三角 ＋ 格号 `#i`；
  角标追加 `格 #i/末格 @ 12.34s`。
- 提示行改成 `点击/拖动=选格定位 / ←→=逐格 / Home End=首尾 / Shift+拖动=框选 / 滚轮=缩放`。

**顺手修掉一个命中测试 bug**：原来 `draw()` 算区间色带 `bandY` 用的是
`h - hudH - bandH - 1`（`bandH = clamp(h*0.2, 12, 18)`），而 `mousedown` 里重算的却是
`clientHeight - clamp(clientHeight*0.22, 12, 20) - 2` —— **两套公式不一致**，
点色带选中区间时灵时不灵。现在 `draw()` 把矩形存进 `this._bandRect`，命中测试只用这一份。

### 3.2 `app/renderer/app.js`

新键盘表（`←→/Home/End` 的真实行为按**是否在播放**分流）：

| 键 | 暂停时 | 播放时 |
|---|---|---|
| `Space` | 播放 / 暂停 | 播放 / 暂停 |
| `←` `→` | **上一格 / 下一格**（选中并 seek 过去） | 原来的 ∓5s |
| `Home` `End` | **第 0 格 / 最后一格** | 原来的音频首 / 尾 |
| `Esc` | 取消选中格 | — |

原版播放中直接 `return` 不抢方向键；本项目保留播放时的 ±5s，
否则会丢掉一个原本就有的常用操作（偏离，见 §4）。

- `togglePlay()`：`ensureAudio()` 之后、`play()` 之前，若有选中格就
  `seek(floorTime(selFloor))`。新增 `whenReady()` 等 `loadedmetadata`
  —— 设 `currentTime` 之前必须先有 `duration`，否则这次 seek 会被直接丢掉
  （2s 超时兜底，避免加载失败时把播放卡住）。
- 底部播放条 `#slider` 的 `change` 也 `floorAt()` 反查一次格号，两个走带控件行为一致。
- `doLoad()` 里 `overview.clearFloor()`：换文件后格号作废（跟区间同理）。
- 调试钩子新增 `selFloor / nFloors / floorAt / floorTime / selectFloor / stepFloor /
  gotoFloor / clearFloor`，`app/e2e.js` 直接驱动。

## 4. 有意偏离原版的地方（3 处）

1. **播放后不清除选中标记。** 原版 `handlePlayWithSeek` 里先 `deselectTile()`，
   因为它那条 slider 只在播放态才展开。本项目的全曲条是**常驻**的，
   标记留着就是「从这一格开始播」的锚点；播完就消失反而让人以为没选中。
2. **播放时方向键退回 ±5s**（原版播放中不响应）。
3. **保留 Shift+拖动框选 / 滚轮缩放 / 中键平移 / 双击复位**（原版没有）——
   区间采音依赖框选，用户明确要求保留。

## 5. 附带发现（★ 2026-10 已修，见 `docs/24` §3）

`session.audio_for_current()` 对两种输入是**两副面孔**：
MIDI 走 `core.synth.render(..., lead_ms=...)`（在**谱面时间轴**上重新合成、前置静音），
而 OGG 有 `source_audio` 时**直接返回原始 ogg**（不前置静音）。

于是「第 j 格在预览音频里的时刻」两者不同：

| 输入 | 预览音频 | 正确 seek 映射 | 用 `entry[j]` 的误差 |
|---|---|---|---|
| MIDI | 重新合成 | `entry[j]` | −0.544ms ✅ |
| OGG | **原始 ogg** | `entry[j] + (offset − lead)` | **−2313ms** ❌ |

OGG 那行的残差是**常数 2313.268ms、673 个音最大漂移 0.121ms**（精确、非噪声），
也就是 OGG 输入下播放头/当前格高亮整体偏 2.3 秒。
探针脚本：`tools/_axis_probe.py`。

> ★ **现状（2026-10 起）**：已按本文当时建议的方向修好 —— sidecar 在 payload 里直接给出
> `audio_shift_ms` / `audio_lead_ms` 两个常量，**payload 里所有时刻统一输出在采音轴**，
> 前端所有视图与滑块都用它们换算。同时 `offset` 的口径也修了（`Session.audio_lead_ms()`
> 是「交出去的音频补了多少静音」的唯一真源）。旧实测数字保留在上面作对照，
> 新的验收见 `docs/24` §3 与 `tools/_axis_probe_v2.py`（OGG/MIDI 残差 ≤2ms）。

## 6. 验收

`app/e2e.js` §13 新增 **11 条**（全部走真实鼠标/键盘事件，不直接改内部状态）：

```
拖动预览条后选中了某一格                     selFloor 是整数（实测 #80）
选中格 == 播放位置反查的格（getTileIndexAtTime）
预览条画出选中格标记                        画布上绿色像素 19
→ 逐格前进一格                              80 → 81
逐格后播放位置落在该格 entryTime             |pos − floorTime| < 2ms
← 逐格退回一格                              回到 80
End 跳到最后一格 / Home 跳到第 0 格          （真实 keydown，#228）
Esc 取消选中格
播放从选中的格开始（不是从 0）              按播放键后 want≈17833 got≈18052
Shift+拖动框选不会动到选中的格               40 → 40
```

回归：`npx electron . --e2e` **83/83**（原 72 + 新 11）；
`python tests/test_sidecar.py` **79/79**；15 个 Python 套件全绿
（前端改动不碰 `core/`，后端行为无变化）。
