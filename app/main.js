/**
 * Electron 主进程：负责「起 Python sidecar + 开窗口 + 原生对话框」。
 *
 * 为什么这么起（都是运行环境约束逼出来的）：
 *  1. **端口由主进程选好传给 Python**，父子之间不读管道 —— 受限沙箱会拦
 *     `stdio: 'pipe'`（EPERM），所以 sidecar 用 `stdio: ['ignore', log, log]`，
 *     握手改成轮询 `GET /api/health`。
 *  2. sidecar 的日志写 `app/.logs/sidecar.log`，出问题时能直接看。
 *  3. 渲染进程不开 node 集成（`contextIsolation: true`），只通过 preload 暴露
 *     白名单能力；HTTP 请求由渲染进程直接打 `127.0.0.1:<port>`。
 */
const { app, BrowserWindow, Menu, dialog, ipcMain, shell, nativeTheme } = require('electron');
const { spawn, spawnSync } = require('node:child_process');
const net = require('node:net');
const os = require('node:os');
const fs = require('node:fs');
const path = require('node:path');

// ★★ 仓库根（`core/` 在那里）。
//   打包后**没有**「上一级仓库根」了 —— `__dirname` 在 `resources/app.asar` 里，
//   `..` 会指到 `resources/`。而 `electron-builder` 的 `extraResources` 正是把
//   `core/ sidecar/ patterns/ vendor/ samples/` 放到 `resources/` ⇒ 正好就是这里。
const PACKAGED = app.isPackaged;
const ROOT = PACKAGED ? process.resourcesPath : path.resolve(__dirname, '..');
const ARGS = process.argv.slice(1);
const DEV = ARGS.includes('--dev');
const SMOKE = ARGS.includes('--smoke');
const E2E = ARGS.includes('--e2e');
// ★ `--hidden`：不弹窗（给 e2e / CI 用 —— 省得每次跑测试都抢一下前台）
const HIDDEN = ARGS.includes('--hidden');
const PROBE = ARGS.includes('--probe');
// ★ `--pick-look`：把「软件内的谱面预览」按若干组参数各截一张图（照样子对比用）
const PICK_LOOK = ARGS.includes('--pick-look');
// ★ 看工作台皮肤那一版加的：窗口材质（亚克力）开关。
//   `--no-material` = 强制退回不透明深色底（万一某台机器上材质渲染异常，
//   一个开关就能回到"纯净深色"，不用改代码）。细节见下面「窗口材质」一节。
const NO_MATERIAL = ARGS.includes('--no-material');

let win = null;
let sidecar = null;
let port = 0;
let readyTimer = null;
let MATERIAL = 'none';                 // 'acrylic' | 'none'（createWindow 前定好）

// ---------------------------------------------------------------- 窗口材质
/* 「工作台皮肤」的亚克力材质。
 *
 * 原理：Electron 的 `backgroundMaterial` 让 **DWM** 在窗口背后画一层系统材质
 *   （亚克力 = 桌面模糊 + 噪点 + 着色），位置在**非客户区与页面内容之后**。
 *   ⇒ 想让它在**内容区**也看得见，页面自己就**不能刷不透明底色** ——
 *     这正是皮肤里 `html,body{background:transparent}` + 面板 rgba 半透明的作用。
 *
 * 什么时候**不能用**（都要退回实底，否则窗口会糊/透得发脏）：
 *   · 不是 Windows，或系统版本 < Win11 (build 22000)
 *   · 用户在「设置 → 个性化 → 颜色」里**关掉了「透明效果」** —— 关了之后
 *     系统不会画材质，页面又已经透明，就会露出桌面（未模糊），很难看
 *   · 命令行带 `--no-material`
 *
 * 读取「透明效果」开关：注册表 `HKCU\...\Themes\Personalize\EnableTransparency`
 *   （DWORD 1=开 0=关）。读不到就当"开"——老系统/精简版没这项时行为与之前一致。
 */
function sysBuild() {
  // `process.getSystemVersion()` 是 Electron 提供的（"10.0.22621"）；
  // 纯 Node 下没有 → 退回 `os.release()`，两条路结果一致，避免静默降级成"没有材质"。
  let v = '';
  try { if (process.getSystemVersion) v = String(process.getSystemVersion()); } catch (_e) { /* ignore */ }
  if (!v) { try { v = String(os.release()); } catch (_e2) { v = '0.0.0'; } }
  const p = v.split('.');
  return Number(p[2] || 0);            // "10.0.22621" → 22621
}

function transparencyEnabled() {
  if (process.platform !== 'win32') return false;
  try {
    const r = spawnSync('reg', ['query',
      'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize',
      '/v', 'EnableTransparency'], { encoding: 'utf8', windowsHide: true });
    const m = /EnableTransparency\s+REG_DWORD\s+0x([0-9a-f]+)/i.exec(r.stdout || '');
    return m ? parseInt(m[1], 16) === 1 : true;
  } catch (_e) {
    return true;
  }
}

function pickMaterial() {
  if (NO_MATERIAL) return 'none';
  if (process.platform !== 'win32') return 'none';
  if (sysBuild() < 22000) return 'none';          // Win10 没有 Mica/Acrylic
  if (!transparencyEnabled()) return 'none';
  return 'acrylic';
}

// ------------------------------------------------------------------ 端口
function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const p = srv.address().port;
      srv.close(() => resolve(p));
    });
  });
}

// --------------------------------------------------------------- sidecar
/**
 * sidecar 的日志。
 * ★ `__dirname` 在打包后是 **asar 里**（只读）⇒ 必须写到用户目录，
 *   否则「开袋即食」的包一启动就在 `mkdir .logs` 上摔（真机必踩）。
 */
function logFile() {
  const dir = PACKAGED
    ? path.join(app.getPath('userData'), 'logs')
    : path.join(__dirname, '.logs');
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, 'sidecar.log');
}

/**
 * 用哪个 Python 解释器。
 *   1. `ADOFAI_PYTHON` 环境变量（开发 / 排障时指定，**永远最优先**）
 *   2. 包内自带的运行时 `resources/runtime/python/python.exe`（开袋即食靠它）
 *   3. 系统的 `python`（开发机就是这样跑的）
 */
function pythonExe() {
  if (process.env.ADOFAI_PYTHON) return process.env.ADOFAI_PYTHON;
  const bundled = path.join(process.resourcesPath || '', 'runtime', 'python', 'python.exe');
  if (PACKAGED && fs.existsSync(bundled)) return bundled;
  return 'python';
}

async function startSidecar() {
  port = await freePort();
  const out = fs.openSync(logFile(), 'a');
  const py = pythonExe();
  const argv = ['-m', 'sidecar.server', '--port', String(port), '--root', ROOT];
  sidecar = spawn(py, argv, {
    cwd: ROOT,
    stdio: ['ignore', out, out],       // ← 不用管道：沙箱会拦
    windowsHide: true,
  });
  sidecar.on('error', (e) => {
    console.error('[sidecar] 启动失败：', e.message);
  });
  sidecar.on('exit', (code, sig) => {
    console.error(`[sidecar] 退出 code=${code} sig=${sig}`);
    if (win && !SMOKE) {
      win.webContents.send('sidecar:down', { code });
    }
  });

  const t0 = Date.now();
  for (;;) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (r.ok) {
        const j = await r.json();
        console.log(`[sidecar] 就绪 ${Date.now() - t0}ms  py=${j.py}  root=${j.root}`);
        return j;
      }
    } catch (_e) { /* 还没起来 */ }
    if (Date.now() - t0 > 60000) throw new Error('sidecar 启动超时（60s）');
    await new Promise((r) => setTimeout(r, 250));
  }
}

/**
 * ★ 关我们自己的 app 时，要把它**顺手拉起来的 BDG 宿主**也带走（`docs/40`）。
 *
 * `tools/host.js start` 起的宿主是 `detached + unref` 的 —— 设计上它**不跟随**
 * 我们这边退出（这样 sidecar 重启不会把窗口一起带走）。所以必须显式停。
 *
 * ## ★ 为什么这里**不**去调 `node tools/host.js stop`
 *
 * 踩过：`spawnSync(process.execPath, [...])` 在 Electron 里 `process.execPath` 是
 * **electron.exe**，不是 node ⇒ 等于又拉了一个 Electron 去跑那个脚本。
 * 实测后果：**退出时一句日志都没有、宿主被留成孤儿窗口**（pidfile 还在、9222 还通）。
 *
 * 所以这里**不依赖 node**，直接在进程内做（读 pidfile + 杀进程树）——
 * 退出路径上要的是「短、同步、不依赖任何外部程序」。
 * 与 `tools/host.js stop` 的口径完全一致：**只杀 pidfile 里记着的那个**，
 * 没有记录就什么都不做（用户手动 `host:dev` 起的宿主不由我们负责）。
 */
function stopHostWeStarted() {
  const pf = path.join(ROOT, 'out', '_bdg_host.pid');
  let pid = 0;
  try { pid = Number(fs.readFileSync(pf, 'utf8').trim()) || 0; } catch (_e) { return; }
  if (!pid) return;
  const gone = () => { try { fs.unlinkSync(pf); } catch (_e) { /* ignore */ } };
  try {
    process.kill(pid, 0);                    // 还在吗
  } catch (_e) {
    gone();                                  // 早就不在了 ⇒ 清掉残留 pid 文件
    return;
  }
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      try { process.kill(-pid, 'SIGTERM'); } catch (_e) { process.kill(pid, 'SIGTERM'); }
    }
    gone();
    console.log(`[host] 已停掉我们起的 BDG 宿主（pid ${pid}）`);
  } catch (e) {
    console.error(`[host] 停宿主失败（pid ${pid}）：`, e.message);
  }
}

function stopSidecar() {
  if (!sidecar) return;
  stopHostWeStarted();                       // ★ 必须在 kill 之前（硬杀不跑 atexit）
  try {
    sidecar.kill();
  } catch (_e) { /* ignore */ }
  sidecar = null;
}

// ---------------------------------------------------------------- 窗口
async function createWindow() {
  MATERIAL = pickMaterial();
  // 深色标题栏 / 深色原生控件：本项目没有任何 prefers-color-scheme 分支，锁 dark 无副作用
  nativeTheme.themeSource = 'dark';

  const opts = {
    width: 1560,
    height: 940,
    minWidth: 1100,
    minHeight: 700,
    // ★★ 材质生效时窗口底必须**透明**：DWM 把亚克力画在页面**之后**，
    //    窗口底若不透明就会把它整个盖住（皮肤里那套半透明面板也就白费了）。
    //    材质不可用时给实底 —— 同一套 CSS 会叠在它上面，观感是纯净深色主题。
    backgroundColor: MATERIAL === 'acrylic' ? '#00000000' : '#0e1116',
    title: 'ADOFAI 谱面生成器',
    show: !SMOKE && !HIDDEN,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      // ★ 关掉后台节流：谱面编辑器希望「窗口没在前台也继续走播放头」。
      //   不关的话 Chromium 会把 rAF/timer 节流甚至停掉，播放头会冻住
      //   （e2e 实测：音频 currentTime 在走，但界面不动）。
      backgroundThrottling: false,
      additionalArguments: [`--sidecar-port=${port}`],
    },
  };
  if (MATERIAL !== 'none') opts.backgroundMaterial = MATERIAL;   // 'acrylic'
  win = new BrowserWindow(opts);
  win.on('closed', () => { win = null; });
  // ★ 只写在构造函数里，个别 Electron 版本不会真正激活材质 —— 社区实测在
  //   `ready-to-show` 后再补一次 `setBackgroundMaterial()` 才稳定生效。
  win.once('ready-to-show', () => {
    if (MATERIAL === 'none') return;
    try { win.setBackgroundMaterial(MATERIAL); } catch (_e) { /* 老版本没有此方法，忽略 */ }
  });
  await win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  if (DEV) win.webContents.openDevTools({ mode: 'detach' });
}

// ---------------------------------------------------------------- 菜单
function buildMenu() {
  const send = (name) => () => win && win.webContents.send('menu', name);
  const template = [
    {
      label: '文件',
      submenu: [
        { label: '打开 MIDI / 音频…', accelerator: 'CmdOrCtrl+O', click: send('open') },
        { label: '导出谱面…', accelerator: 'CmdOrCtrl+S', click: send('export') },
        { type: 'separator' },
        { label: '重新生成', accelerator: 'CmdOrCtrl+R', click: send('rebuild') },
        { type: 'separator' },
        { label: '退出', role: 'quit' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { label: '谱面预览', accelerator: 'CmdOrCtrl+1', click: send('tab:chart') },
        { label: '钢琴卷帘', accelerator: 'CmdOrCtrl+2', click: send('tab:roll') },
        { label: '谱面路径', accelerator: 'CmdOrCtrl+3', click: send('tab:path') },
        { label: '4K 下落式', accelerator: 'CmdOrCtrl+4', click: send('tab:falling') },
        { type: 'separator' },
        { label: '重载界面', accelerator: 'CmdOrCtrl+Shift+R', role: 'forceReload' },
        { label: '开发者工具', accelerator: 'F12', role: 'toggleDevTools' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        { label: '关于 / 参数说明', click: send('about') },
        { label: '打开 sidecar 日志', click: () => shell.openPath(logFile()) },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------- IPC
ipcMain.handle('dialog:openFile', async () => {
  const r = await dialog.showOpenDialog(win, {
    title: '打开 MIDI / BDG 工程 / 时间戳',
    properties: ['openFile'],
    // ★★ 2026-10 用户口径：「ogg2adofai 在正式版**隐藏**，假装不存在，也不能选择；
    //   逻辑层不要动一个字」。⇒ 这里**不再列音频扩展名**（连「全部支持」里也没有，
    //   免得用户从兜底那一栏挑到 ogg）。
    //   音频仍可用作**预览音源**：那条走下面的 `dialog:openAudio`，没动。
    filters: [
      { name: '全部支持', extensions: ['mid', 'midi',
                                      'bdg', 'txt', 'csv', 'tsv', 'ms', 'log', 'json'] },
      { name: 'MIDI', extensions: ['mid', 'midi'] },
      // ★ BDG 工程当**生成源**（docs/38 §9）：每条轨变成一条音轨，角色由用户勾
      { name: 'Beat Data Generator 工程', extensions: ['bdg'] },
      // ★ 时间戳当**生成源**（docs/45 §7 · docs/56）：两种都收 ——
      //   「一行一个数 / 毫秒时间戳」与「时间戳 JSON（DEMUCS 分轨，多路音头）」，
      //   两者后缀一模一样（都会是 .json）⇒ 靠**内容**分流，不靠后缀。
      { name: '时间戳（一行一个数 / 时间戳 JSON）',
        extensions: ['txt', 'csv', 'tsv', 'ms', 'log', 'json'] },
    ],
  });
  return r.canceled ? null : r.filePaths[0];
});

// ★ 2026-10「预览音源」用：**只挑音频**（ogg / oga / wav / flac / mp3）。
//   与上面的「打开来源文件」分开 —— 那个还会收 mid/bdg/txt，容易挑错。
ipcMain.handle('dialog:openAudio', async () => {
  const r = await dialog.showOpenDialog(win, {
    title: '选择原曲音频（作预览音源）',
    properties: ['openFile'],
    filters: [
      { name: '音频', extensions: ['ogg', 'oga', 'wav', 'flac', 'mp3'] },
      { name: '全部文件', extensions: ['*'] },
    ],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle('dialog:openDir', async (_e, opts) => {
  const r = await dialog.showOpenDialog(win, {
    title: (opts && opts.title) || '选择目录',
    properties: ['openDirectory', 'createDirectory'],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle('shell:reveal', async (_e, p) => {
  if (p) shell.showItemInFolder(p);
  return true;
});

ipcMain.handle('app:info', async () => ({
  root: ROOT,
  port,
  version: app.getVersion(),
  electron: process.versions.electron,
  chrome: process.versions.chrome,
  node: process.versions.node,
}));

// ---------------------------------------------------- UI 布局（docs/49 §5.4）
// ★ 布局存**真文件**：<userData>/ui-layout.json（用户能打开看、能备份、重装也能带走）。
//   渲染进程拿不到 node ⇒ 只能走这两个 IPC。
const LAYOUT_FILE = () => path.join(app.getPath('userData'), 'ui-layout.json');
ipcMain.handle('ui:layout:get', async () => {
  try {
    const txt = await fs.promises.readFile(LAYOUT_FILE(), 'utf8');
    const j = JSON.parse(txt);
    return { ok: true, n: j && j.v, layout: j, path: LAYOUT_FILE() };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e), path: LAYOUT_FILE() };
  }
});
ipcMain.handle('ui:layout:set', async (_e, txt) => {
  try {
    const s = String(txt == null ? '' : txt);
    JSON.parse(s);                       // 先验一遍，别把坏 JSON 写进去
    await fs.promises.mkdir(path.dirname(LAYOUT_FILE()), { recursive: true });
    await fs.promises.writeFile(LAYOUT_FILE(), s, 'utf8');
    return { ok: true, path: LAYOUT_FILE() };
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
});

ipcMain.on('renderer:ready', (_e, info) => {
  console.log('[renderer] ready', JSON.stringify(info || {}));
  if (SMOKE) {
    if (readyTimer) clearTimeout(readyTimer);
    console.log('SMOKE PASS: 窗口 + sidecar 就绪，渲染进程已握手');
    setTimeout(() => app.quit(), 300);
  }
  if (E2E) {
    if (readyTimer) clearTimeout(readyTimer);
    const run = require('./e2e.js');
    run(win).then((code) => {
      setTimeout(() => app.exit(code), 400);
    }).catch((err) => {
      console.error('E2E CRASH', err && (err.stack || err));
      app.exit(3);
    });
  }
  if (PROBE) {
    if (readyTimer) clearTimeout(readyTimer);
    const run = require('./probe-player.js');
    run(win).then((code) => {
      setTimeout(() => app.exit(code), 400);
    }).catch((err) => {
      console.error('PROBE CRASH', err && (err.stack || err));
      app.exit(3);
    });
  }
  if (PICK_LOOK) {
    // ★ 照样子对比（`--pick-look`）：按 `out/_look/jobs.json` 逐组改参数、重建，
    //   把**软件内的谱面预览**（Re_ADOJAS）+ 路径视图截图下来，人工/程序一起看。
    if (readyTimer) clearTimeout(readyTimer);
    const run = require('./pick-look.js');
    run(win).then((code) => {
      setTimeout(() => app.exit(code), 400);
    }).catch((err) => {
      console.error('PICK-LOOK CRASH', err && (err.stack || err));
      app.exit(3);
    });
  }
});

ipcMain.on('renderer:error', (_e, msg) => {
  console.error('[renderer:error]', msg);
});

// ---------------------------------------------------------------- 启动
app.whenReady().then(async () => {
  buildMenu();
  try {
    await startSidecar();
  } catch (e) {
    dialog.showErrorBox('sidecar 启动失败', String(e.message || e));
    app.quit();
    return;
  }
  await createWindow();
  if (SMOKE) {
    readyTimer = setTimeout(() => {
      console.error('SMOKE FAIL: 30s 内渲染进程没有握手');
      app.exit(2);
    }, 30000);
  }
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopSidecar();
  app.quit();
});
app.on('before-quit', stopSidecar);
process.on('exit', stopSidecar);
