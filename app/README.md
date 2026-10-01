# app/ · Electron 前端（ADOFAI 谱面生成器）

架构 A：**Electron 前端 + Python `core/` 当 sidecar**（见 `docs/15` 附「已定方向」、
`docs/19` 施工记录）。前端只画界面和收参数，**所有已验证的业务逻辑仍在 Python**。

```
python -m sidecar.server --port N      ← Electron 主进程自己选端口后 spawn
        ▲
        │  HTTP + SSE（127.0.0.1）
        │
app/main.js（找端口 / 起 sidecar / 原生对话框 / 菜单）
   └─ app/renderer/（index.html + app.js + 4 个 canvas 视图）
```

## 跑起来

```powershell
cd app
npm install          # 只装 electron
npm start            # 正常启动
npm run dev          # 带 DevTools
npm run smoke        # 冒烟：窗口+sidecar 就绪即退出（CI 用）
npm run probe        # 只验内嵌 ADOFAI 播放器那条链路（就绪/不自动播/播放/暂停）
npm run e2e          # 无头端到端：加载→求解→四视图→导出→校验（退出码 0/1）
```

## 重建内嵌的 ADOFAI 播放器 bundle

谱面预览跑的是上游 [Re_ADOJAS](https://github.com/adofaiex/Re_ADOJAS) 的渲染引擎
（`docs/22`）。改了它的源码、或升级了它的依赖之后，要重新打包并拷进来：

```powershell
# ★ 上游源码不在本仓库里（第三方，见 ../EXTERNAL_ASSETS.md），先自己 clone 一份
git clone https://github.com/adofaiex/Re_ADOJAS ..\_re_adojas
cd ..\_re_adojas
pnpm install                       # 首次
pnpm run embed                     # → dist-embed/adofai-player.js（9.8MB ESM）
Copy-Item dist-embed\adofai-player.js ..\app\renderer\vendor\ -Force
```

> 打好的 `app/renderer/vendor/adofai-player.js`（+ `.map`）**是进仓库的** ——
> clone 下来就能用预览，不用先跑一遍上游构建。

`vite.embed.config.ts` 是**专为宿主写的 lib 构建**：复用它自己的
`vite-plugin-wasm-inline`（内联 wasm 供 `virtual:wasm-*` 用）和 `vite-plugin-glsl`，
但只打 `src/preview-embed.ts` 一个入口，不带 React/Tailwind。

主进程会把 sidecar 的日志写到 `app/.logs/sidecar.log`（菜单「帮助 → 打开 sidecar 日志」）。

## ⚠ 装 electron 二进制的坑（已踩）

`npm install` 会去 GitHub Releases 下 electron 的二进制，**在受限网络下会下不动**，
于是 `node_modules/electron/dist/` 是空的（`npx electron` 会卡住）。
如果缓存目录里已经有现成的 zip，直接解开即可：

```powershell
# 版本必须与 package.json 里 pin 的一致（当前 44.0.0）
$zip = "$env:LOCALAPPDATA\electron\Cache\*\electron-v44.0.0-win32-x64.zip"
Expand-Archive (Get-Item $zip)[0].FullName -DestinationPath node_modules\electron\dist -Force
Set-Content node_modules\electron\path.txt -Value "electron.exe" -NoNewline
& node_modules\electron\dist\electron.exe --version    # 应打印 v44.0.0
```

因为拿不到校验文件（`@electron/get` 会去联网取 `SHASUMS256.txt` 而失败），
**package.json 里 electron 是精确版本号而不是 `^`** —— 换版本前先确认缓存里有对应 zip。

## 为什么 sidecar 不打印端口、也不走管道

受限环境（沙箱）会拦「父进程通过管道读子进程 stdout」（`EPERM`）。
所以：**Electron 自己选空闲端口 → 用 `--port` 传给 Python**，
sidecar 的 stdout/stderr 直接重定向到日志文件（`stdio: ['ignore', out, out]`），
握手改成轮询 `GET /api/health`。这样父子之间一根管道都不需要。

## 前端新增的（旧 PySide6 UI 没有的）

- **谱面预览 = Re_ADOJAS 的渲染引擎**：上游 `lib/Player` 用 `pnpm run embed`
  打成一个 ESM（`renderer/vendor/adofai-player.js`，已随仓库分发），
  页面动态 `import()`。格形/行星/HUD 都是官方那套，见 `docs/22`。
- **全曲预览条**：**点击/拖动 = 定位并选中该处的格**（导航单位是「格」不是毫秒）；
  `←/→` 逐格、`Home/End` 首尾格（暂停时）、`Esc` 取消、播放键从选中的格开始播；
  **Shift+拖动 = 框选区间**（区间采音）；滚轮缩放 / 中键平移 / 双击复位。
  它是**音频毫秒轴**，谱面视图是 entryTime 轴。详见 `docs/21`。
  （2026-10 起两轴由 `payload.audio_shift_ms` / `audio_lead_ms` 显式换算，见 `docs/24` §3）
- **区间采音**：框出来的一段改用指定音轨采音（`state.regions`），区间外仍走全局选择。
  只覆盖「采哪些音」，求解/模板/雪花/双押全部无感。
- **分区可折叠**、状态区折叠、布局体检（溢出/截断/压扁）进 e2e 回归。
- **偏移修正**（`docs/24` §3）：
  · 谱面预览控制条上有播放器自带的**音乐延迟补偿**（`music_delay_ms`，"按实测建议"按钮）；
  · 侧栏「⑤ 时序」有「**应用建议 offset**」；
  · **轴口径统一** —— `payload` 输出采音轴，`<audio>` 轴 = 采音轴 + `audio_lead_ms`，
    谱面轴 = 采音轴 − `audio_shift_ms`（`audioToGrid` / `gridToAudio` / `chartToGrid`）。
    滑块、全曲条拖动、`curFloor()`、加区间、`seek()` 全部走这三个函数 ——
    **别再自己拼 offset/lead**（旧代码混轴，ogg 输入下整体偏 1.5~2.3 秒）。
- **空格** 播放/暂停、**暂停时 ←/→** 逐格、**Home/End** 首尾格、**Ctrl+1..4** 切页签
  （播放时 ←/→ 仍为前后 5s）
- Ctrl+R 重新生成；`window.__dsh` 调试钩子（DevTools 里可直接调状态）
- 状态栏会显示网格拟合 / 检波偏置（OGG 源）

## 截图

`npx electron . --e2e` 会把关键画面写到 `out/_shots/ui-*.png`
（谱面预览 / 卷帘 / 路径 / 下落式 / 面板折叠与展开），改完布局可以直接看图复核。
