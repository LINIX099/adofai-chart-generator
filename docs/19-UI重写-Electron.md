# 19 · UI 重写（Electron + Python sidecar）施工记录

> 目标（`docs/15` 附）：现有 PySide6 UI（`ui/` ~2058 行，`main_window.py` 1228→1356 行单体）
> 观感与可维护性不合格，**用 Node/Electron 重写**；架构选 **A：Electron 前端 +
> Python `core/` 当 sidecar**，不重写任何已验证逻辑。
> **功能对等基准 = `docs/18-ui功能清单.md`**（56 个控件 / 4 个视图 / 20 条迁移风险）。

## 1. 形态

```
Electron 主进程 (app/main.js)
  ├ 选一个空闲端口 → spawn `python -m sidecar.server --port N --root <repo>`
  │   ※ stdio: ['ignore', log, log] —— 受限沙箱拦管道，所以父子之间不读 stdout
  ├ 轮询 GET /api/health 握手（实测 310~320ms 就绪）
  ├ 原生对话框（打开文件 / 选导出目录）/ 原生菜单（Ctrl+O / Ctrl+S / Ctrl+R / Ctrl+1..4）
  └ BrowserWindow（contextIsolation=true、无 node 集成）+ preload 白名单

渲染进程 (app/renderer/)
  ├ app.js      状态 + 按 schema 生成参数面板 + 140ms 防抖 + 播放条 + 状态栏
  ├ api.js      fetch 封装 + EventSource(SSE)
  └ views/      chart.js / roll.js / path.js / falling.js（canvas 2D，常量照抄旧视图）

Python sidecar (sidecar/)
  ├ schema.py   参数 schema（**默认值直接从 core 的 dataclass 取**，不可能漂移）
  ├ session.py  会话 + 全流水线（对等旧 MainWindow，注释里标了旧 UI 行号）
  └ server.py   stdlib HTTP + SSE + 音频 Range
```

**为什么参数面板是数据驱动的**：旧 UI 56 个控件是手写的，改一个参数要动三处
（控件 / 取值 / `_params_solve` 映射）。现在 `schema.py` 一处声明
（分区、标签、类型、范围、默认、后缀、`target`），面板由它生成，
映射由 `target` 反向填充 —— 这也让"新旧是否对等"变成可以逐字段核对的事。

## 2. 功能对等：怎么核对的

| 面 | 旧 UI | 新 UI | 核对方式 |
|---|---|---|---|
| 参数控件 | 56 个 | **38 个 schema 字段**（含视图项） | 逐行对照 `docs/18` §1；`tests/test_sidecar.py` 断言 OnsetParams 7 项 + SolveParams 17 项齐全 |
| 流水线 | `rebuild()` 13 步 | `session.rebuild()` 同 13 步 | `docs/18` §2.3 步骤号写进了代码注释 |
| 派生量 | `preview_lead/chart_entry/chart_times/hit_times` | 同名同义 | `hit_times` 用 `dp_old2new` 重映射（与旧 UI 一致） |
| 4 个视图 | QPainter | canvas 2D，**常量逐个照抄** | `app/e2e.js` 检查每个页签的**非背景像素数** > 200 |
| 播放 | QMediaPlayer | `<audio>` + `/media`（自实现 Range） | e2e 验 Range 206；滑块只在 `change`（= sliderReleased）seek |
| 导出 | `writer.write_dir` + `verify_file` | 同 | e2e 真导出 + 第三方反解校验 |
| 防抖 | 140ms 单发 | 140ms 单发 | 同名常量 `schedule()` |
| 滚轮不抢焦 | `NoWheelFilter`（QApplication 级） | document 级 capture（全局，不逐个控件挂） | —— |
| 不进防抖的控件 | `ed_song/artist/author/sp_diff` | 同（`schedule: false`） | schema 里显式标注 |

**没丢的东西**：`core/` 一行没改逻辑（只**新增**了 `verify.verify_press_subset`），
时序模型 / 模板 / 雪花 / 双押插入 / EX 语料标尺全部原样复用。

## 3. 顺手修掉的真 bug（不是重写引入的）

写 e2e 时被真实数据逼出来的，1~4 在旧 UI 里同样存在：

1. **双押插入后 `verify_file` 是假失败**（`docs/18` 风险 7 的实例）
   —— 插了中旋 `999` 层后「层 ↔ onset」不再 1:1，逐层对照把一张正确的谱报成
   **最大误差 999.8ms**。新增 `core.verify.verify_press_subset()`：按**按键集合**
   校验（实测 184/184 全中，最大 1.3889ms 且是常量）。导出时自动分流：
   没插双押层 → 旧口径；插了 → 按键盘口径，并在文案里说明。
2. **`check_offset` 在双押谱上算出十几秒的假误差**（实测 12624ms）
   —— 它内部用 `entry_time_of_onsets()`（朴素 1:1）。sidecar 改用**已重映射的
   `hit_times`**（`session._offset_check`），物理含义不变。
3. **`check_offset` 的单位文案错了**：字段叫 `*_ms`，旧 UI 状态栏写成 `us`。
   实际是**毫秒**。新版文案改为 ms。
4. **`meta` key 写错会让状态栏静默少一条信息**：雪花朵数是 `snow_count`
   （不是 `snowflake_count`）、模板覆盖是 `tpl_covered`（不是 `template_tiles`）。
5. **HTTP 层字段名撞车**：`api.req` 曾把 HTTP 状态码写进响应的 `status`，
   而 sidecar 的 `status` 是**状态文案** → 界面状态栏显示 "200"。改名 `httpStatus`。
6. **窗口被遮挡时播放头会冻住**（e2e 抓到）：播放头/滑块/时间标签原先只挂在
   `requestAnimationFrame` 上；窗口不在前台时 Chromium 节流甚至停掉 rAF，
   于是「音频 `currentTime` 在走、界面不动」。修法两层：
   ① 主进程 `webPreferences.backgroundThrottling: false`（编辑器本来就该这样）；
   ② 渲染进程改用 **`timeupdate` + 100ms 兜底定时器**当权威时钟，rAF 只负责顺滑。

## 4. 验收

| 方式 | 命令 | 结果 |
|---|---|---|
| 冒烟（窗口 + sidecar 握手） | `cd app; npx electron . --smoke` | `SMOKE PASS`（sidecar ~310ms） |
| **无头端到端** | `cd app; npx electron . --e2e` | **72/72 PASS**（含布局体检 / 全曲预览条 / 区间采音） |
| sidecar 接口 | `python tests/test_sidecar.py` | **79/79** |
| sidecar + OGG 长任务/取消 | `python tests/test_sidecar.py --ogg` | **74/74**（OGG 加载 7.9s，取消通道通） |
| 网格拟合（v0.2） | `python tests/test_gridfit.py` | 30/30 |
| 其余 12 个套件 + 语料 + 旧 UI 冒烟 | 见 `docs/15` 附 A1 | 全绿（534/534、0.0µs） |

> 后续增量（**布局整理 / 全曲预览条 / 区间采音**）见 `docs/20`。

e2e 覆盖的链路（都在**真 Electron 窗口**里跑，48 条）：

```
加载 MIDI → 求解 → 四个页签各画一次并数非背景像素
→ 改参数(直线优先) → 换曲(Automaton_Waltz) 开雪花 → 数雪花层与雪花朵数
→ 关双押轨对比层数 → 角度双押 → 中旋双押
→ 取音频 → 真导出 → 第三方反解校验
→ 自动 offset 写回且**不回环**（数重建次数）
→ 真播放：currentTime 递增 / 播放头跟随 / 滑块跟随 / 时间标签格式 / seek 5s / 暂停不再前进
→ 曲名带非法字符的导出目录净化
→ OGG 全链路：SSE 进度事件 / 界面显示自洽网格+检波偏置 / 出谱 / 预览用原曲
→ **真实 DOM 路径**（不走调试钩子）：点页签按钮 / 改数值框派发 change / 勾选框 click
  （含取反与复原）/ 下拉 change / 点「重新生成」/ 拖滑块 change→seek /
  点播放键真播 / 再点暂停 / **未聚焦数字框吃掉滚轮、已聚焦才允许**（NoWheelFilter 等价物）
```

`tests/test_sidecar.py` 里另有一组**参数对等**断言（21 条）：逐个把 UI 字段喂进去，
再断言 `OnsetParams` / `SolveParams` 上确实拿到了对应值 —— 包括三个已知陷阱：
`auto_bpm` 勾上时 `base_bpm` **保持 0**（显示值不是输入）、
`twirl_index` 的 UI 顺序 ≠ `core` 常量顺序、
`straight_preset` 的「少」对应 λ 最大（3.0）。

## 5. 已知取舍 / 与旧 UI 有意的差异

| 项 | 旧 UI | 新 UI | 理由 |
|---|---|---|---|
| 「示例▾」 | 按钮 + 光标处弹菜单 | `<select>` 下拉 | 等价、少一次点击，且不用在渲染进程手搓菜单定位 |
| 参数非法组合 | 无任何禁用 | **同样不禁用**（照搬） | 风险 20：擅自加联动会与旧 UI 不一致，要改得单独决策 |
| 失败时清不清状态 | 不清 `chart`（中断语义） | 同（`stale` 标记 + 提示保留旧谱） | 风险 19 |
| 双押谱的 `verify` | 逐层（假失败） | 按键盘口径 | 见 §3.1，属**修正** |
| 键盘快捷键 | 只有 Ctrl+O/Ctrl+S | **额外加**空格/←→/Home/End/Ctrl+1..4 | 旧 UI 四视图完全无键盘处理；这是纯增量 |
| 视图 3D/WebGL | 无 | 仍 2D canvas | 先把"对等 + 可维护"做到，图形升级另开一轮 |

## 6. 旧 UI 还留着吗

留着（`ui/` 一行没动）。它是**行为基准**，`docs/18` 的行号引用都指向它；
等新 UI 稳定跑一段时间、且用户宣布 v0.2/v0.3 定版后再决定是否删除。

## 7. 下一步（未做）

> ⚠ 本节写于 §1~§4 之后；**§5 之后又做了一轮增量**（布局整理 / 全曲预览条 /
> 区间采音），见 `docs/20`。下面几条里「参数语义化禁用」「导出进度」仍未做。

1. **打包**：`electron-builder` 出 exe（要解决二进制下载问题，见 `app/README.md`）。
2. **图形升级**：谱面预览是 2D canvas；如果要做 4K 下落式的高帧率/3D，再评估 WebGL。
3. **参数联动**：把「自动 BPM 时禁用基准 BPM 框」这类做成语义化的 disable
   （现在照搬旧 UI 的"都能改，靠 core 兜住"）。
4. **把 OGG 长任务做成可取消**已在 sidecar 打通（SSE 进度 + `/api/cancel`），
   但前端只在加载时用了；导出（合成音频）还没接进度。
