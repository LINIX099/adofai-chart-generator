#!/usr/bin/env node
/**
 * BDG 宿主联动：把 `bridge_plugin/` **链接**进宿主的插件目录，并按需拉取/启动宿主。
 *
 *   node tools/host.js             # = status：只看现状，什么都不改
 *   node tools/host.js link        # 建 junction + 启用插件（毫秒级、幂等、**永远 exit 0**）
 *   node tools/host.js fetch       # 缺宿主才拉（clone + npm install + Electron 二进制）
 *   node tools/host.js dev         # 起宿主（electron-vite dev --remote-debugging-port=9222）
 *
 * 为什么 `link` 永远 exit 0：它挂在 `app` 的 `start` 前面（`node ../tools/host.js link && electron .`）。
 * 宿主没拉、没装、junction 建不了，都**不该挡住我们自己的 app 启动** ——
 * 那时桥面板会显示「未连接」，用户照样能用其它功能。所以异常一律降级为 `[!]` 警告。
 *
 * 为什么用 junction 而不是拷贝：宿主那两个插件根（`plugins.ts:50-58`）
 *   · `<userData>/plugins`              永远扫
 *   · `<宿主仓库>/plugins`              **只有 !app.isPackaged（dev 模式）**才扫
 * 开发模式下我们要的是第二个。以前 `tools/_bdg_install_plugin.py` 用 `copytree`，
 * 于是**改了 `bridge_plugin/renderer.js` 必须重跑 --force 才生效** —— 这是个反复踩的坑。
 * 换成 junction 后源码即生效。
 *
 * Windows 注意：junction **只能同盘**，且不需要管理员（实测 `fs.symlinkSync(src,dst,'junction')` 即可）。
 * 跨盘/无权限时自动退化为拷贝，并**明确说出来**（不许静默降级）。
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const DEFAULT_HOST = path.join(ROOT, 'vendor', 'beat_data_generator');
const DEFAULT_SRC = path.join(ROOT, 'bridge_plugin');
const PLUGIN_DIR_NAME = 'bridge_plugin';
const HOST_GIT = 'https://github.com/BUGJI/beat_data_generator.git';
const DEFAULT_PROXY = 'http://127.0.0.1:7897';
const CDP_PORT = 9222;
// 我们起的宿主进程：pid 与日志都记在**我们的** out/ 里（不往宿主目录里塞东西）
const PIDFILE = path.join(ROOT, 'out', '_bdg_host.pid');
const LOGFILE = path.join(ROOT, 'out', '_bdg_host.log');

// Electron 的 app.getName() ← package.json 的 productName。
// 开发模式（npm run dev）顶层没有 productName ⇒ 用 name = beat-data-generator。
const USERDATA_NAMES = ['beat-data-generator', 'Beat Data Generator'];

const say = (s) => process.stdout.write(s + '\n');
const warn = (s) => process.stdout.write('[!] ' + s + '\n');
const ok = (s) => process.stdout.write('[OK] ' + s + '\n');

// ------------------------------------------------------------------ 小工具
function exists(p) {
  try { fs.lstatSync(p); return true; } catch (_e) { return false; }
}

function isLink(p) {
  try { return fs.lstatSync(p).isSymbolicLink(); } catch (_e) { return false; }
}

/** 解析链接的真实目标（junction 也走这条）。失败返回 ''。 */
function linkTarget(p) {
  try { return path.resolve(fs.realpathSync(p)); } catch (_e) { return ''; }
}

function samePath(a, b) {
  if (!a || !b) return false;
  const n = (s) => path.resolve(s).replace(/[\\/]+$/, '').toLowerCase();
  return n(a) === n(b);
}

function readManifestId(src) {
  try {
    const m = JSON.parse(fs.readFileSync(path.join(src, 'manifest.json'), 'utf8'));
    return String(m.id || '');
  } catch (_e) { return ''; }
}

function userDataDirs() {
  const out = [];
  const appdata = process.env.APPDATA;              // ★ 运行时读，测试里能换
  if (appdata) for (const n of USERDATA_NAMES) out.push(path.join(appdata, n));
  return out;
}

/** 宿主是否已经装好（有 Electron 二进制才算）。 */
function hostReady(host) {
  return exists(path.join(host, 'node_modules', 'electron', 'dist',
    process.platform === 'win32' ? 'electron.exe' : 'electron'));
}

// ------------------------------------------------------------------ link
/**
 * 建链接 + 启用插件。返回 `{linked, mode, enabled, notes: []}`。
 * `mode` ∈ `junction` | `copy` | `already` | `none`。
 */
function link(opts = {}) {
  const host = opts.host || DEFAULT_HOST;
  const src = opts.src || DEFAULT_SRC;
  const quiet = !!opts.quiet;
  const notes = [];
  const info = { linked: false, mode: 'none', enabled: false, notes };

  if (!fs.existsSync(path.join(host, 'package.json'))) {
    notes.push('宿主还没拉下来：' + host);
    if (!quiet) {
      warn('宿主还没拉下来 —— 桥会显示「未连接」，其它功能不受影响。');
      say('    要装：npm run host:fetch   （或 pnpm run host:fetch）');
    }
    return info;
  }
  if (!exists(path.join(src, 'manifest.json'))) {
    notes.push('插件源缺 manifest.json：' + src);
    if (!quiet) warn('插件源不完整（缺 manifest.json）：' + src);
    return info;
  }

  const pluginsDir = path.join(host, 'plugins');
  const dst = path.join(pluginsDir, PLUGIN_DIR_NAME);
  const myId = readManifestId(src);

  if (isLink(dst)) {
    const tgt = linkTarget(dst);
    if (samePath(tgt, src)) {
      info.linked = true; info.mode = 'already';
      if (!quiet) ok('插件已链接（junction 有效）：' + dst);
    } else {
      // 悬空/指错（工作区搬过家就会这样）⇒ 重建；链接每次都跑就是为了修这个
      if (!quiet) warn('链接指向别处（工作区搬过家？）→ 重建：' + tgt);
      try { fs.unlinkSync(dst); } catch (e) { notes.push('删旧链接失败：' + e.message); }
    }
  } else if (exists(dst)) {
    // 老 `_bdg_install_plugin.py` 留下的是**拷贝**。只删确定是我们自己的那份。
    const oid = readManifestId(dst);
    if (oid && myId && oid !== myId) {
      notes.push(`同名目录是别人的插件（id=${oid}）⇒ 不动它`);
      if (!quiet) warn(`plugins/${PLUGIN_DIR_NAME} 是别的插件（id=${oid}）⇒ 不碰。`);
      enable(myId, info, notes, quiet);
      return info;
    }
    if (!quiet) say('    把旧拷贝换成链接（源码即生效）…');
    try { fs.rmSync(dst, { recursive: true, force: true }); }
    catch (e) { notes.push('删旧拷贝失败：' + e.message); }
  }

  if (!exists(dst)) {
    try { fs.mkdirSync(pluginsDir, { recursive: true }); } catch (_e) { /* 下面会报 */ }
    try {
      // ★ Windows 上 'junction' 不需要管理员，也不需要开发者模式
      fs.symlinkSync(src, dst, 'junction');
      info.linked = true; info.mode = 'junction';
      if (!quiet) ok('插件已链接：' + dst + '  →  ' + src);
    } catch (e) {
      notes.push('建 junction 失败（跨盘/无权限？）：' + e.code);
      try {
        fs.cpSync(src, dst, { recursive: true });
        info.linked = true; info.mode = 'copy';
        if (!quiet) {
          warn('建 junction 失败（' + e.code + '）⇒ 退化成**拷贝**。');
          say('    ⇒ 以后改了 bridge_plugin/ 要重跑 `npm run host:link -- --force`');
        }
      } catch (e2) {
        notes.push('拷贝也失败：' + e2.message);
        if (!quiet) warn('装插件失败：' + e2.message);
      }
    }
  } else if (info.mode === 'none') {
    info.linked = true; info.mode = 'already';
  }

  enable(myId, info, notes, quiet);
  return info;
}

/** 把插件 id 并进宿主的 `plugins-state.json`（**合并**，不覆盖别人的）。 */
function enable(myId, info, notes, quiet) {
  if (!myId) return;
  const dirs = userDataDirs().filter((d) => fs.existsSync(d));
  const target = (dirs.length ? dirs : userDataDirs())[0];
  if (!target) return;
  const f = path.join(target, 'plugins-state.json');
  let state = { enabled: [] };
  if (fs.existsSync(f)) {
    try {
      state = JSON.parse(fs.readFileSync(f, 'utf8')) || {};
    } catch (e) {
      // 坏文件不硬写：备份后在干净对象上加，且**说清楚**
      const bak = f + '.bak';
      try { fs.copyFileSync(f, bak); } catch (_e) { /* ignore */ }
      notes.push('plugins-state.json 解析失败，已备份到 ' + bak);
      if (!quiet) warn('plugins-state.json 坏了（已备份 .bak），重建一份。');
      state = {};
    }
  }
  if (!Array.isArray(state.enabled)) state.enabled = [];
  if (state.enabled.includes(myId)) {
    info.enabled = true;
    if (!quiet) ok('插件已启用：' + myId);
  } else {
    state.enabled.push(myId);
    try {
      fs.mkdirSync(target, { recursive: true });
      fs.writeFileSync(f, JSON.stringify(state, null, 2) + '\n', 'utf8');
      info.enabled = true;
      if (!quiet) ok('已启用插件：' + myId + '（' + f + '）');
    } catch (e) {
      notes.push('写 plugins-state.json 失败：' + e.message);
      if (!quiet) warn('启用失败，请在宿主里手动打开插件：' + e.message);
    }
  }
}

// ------------------------------------------------------------------ start / stop
/** CDP 端口通不通 = 宿主在不在跑。**不假设** 9222 上的一定是我们起的那个。 */
async function up(opts = {}) {
  const port = opts.port || CDP_PORT;
  const ms = opts.ms || 1500;
  try {
    const r = await fetch(`http://127.0.0.1:${port}/json/version`,
      { signal: AbortSignal.timeout(ms) });
    return r.ok;
  } catch (_e) { return false; }
}

function pidOf(opts = {}) {
  const f = opts.pidfile || PIDFILE;
  try { return Number(fs.readFileSync(f, 'utf8').trim()) || 0; } catch (_e) { return 0; }
}

function clearPid(opts = {}) {
  try { fs.unlinkSync(opts.pidfile || PIDFILE); } catch (_e) { /* ignore */ }
}

function alive(pid) {
  if (!pid) return false;
  try { process.kill(pid, 0); return true; } catch (_e) { return false; }
}

/**
 * **不阻塞**地起宿主（UI 的「启动并桥接」用它）。
 *
 * 与 `dev` 的区别：`dev` 用 `spawnSync` + `stdio:'inherit'`，会**占住调用者的进程**直到
 * 宿主退出 —— 适合人在终端里跑。这里必须能立刻返回，所以：
 *   · 直接 spawn `node node_modules/electron-vite/bin/electron-vite.js`
 *     （不走 `.cmd`，就没有 shell 中转，pid 就是真进程，`taskkill /T` 能收干净）
 *   · `detached + unref` ⇒ 我们这边退出不会把它带走（要停就显式 `stop`）
 *   · 输出写进 `out/_bdg_host.log`，pid 写进 `out/_bdg_host.pid`
 */
function startHost(opts = {}) {
  const host = opts.host || DEFAULT_HOST;
  const port = opts.port || CDP_PORT;
  const pidfile = opts.pidfile || PIDFILE;
  const logfile = opts.logfile || LOGFILE;
  const bin = path.join(host, 'node_modules', 'electron-vite', 'bin', 'electron-vite.js');
  if (!exists(bin)) {
    return { ok: false, error: '宿主没装依赖（缺 electron-vite）—— 先跑 host:fetch' };
  }
  const old = pidOf({ pidfile });
  if (alive(old)) return { ok: true, already: true, pid: old, log: logfile };
  fs.mkdirSync(path.dirname(pidfile), { recursive: true });
  fs.mkdirSync(path.dirname(logfile), { recursive: true });
  const fd = fs.openSync(logfile, 'a');
  let child;
  try {
    child = spawn(process.execPath,
      [bin, 'dev', '--', '--remote-debugging-port=' + String(port)],
      { cwd: host, detached: true, stdio: ['ignore', fd, fd], windowsHide: false });
  } catch (e) {
    try { fs.closeSync(fd); } catch (_e) { /* ignore */ }
    return { ok: false, error: '起不来：' + e.message };
  }
  child.unref();
  try { fs.writeFileSync(pidfile, String(child.pid) + '\n', 'utf8'); } catch (_e) { /* ignore */ }
  return { ok: true, pid: child.pid, log: logfile, port };
}

/**
 * 停掉**我们起的**宿主。
 *
 * ★ 如果 9222 上有东西在跑、但**不是我们起的**（没有 pidfile / pid 已经不属于那个进程），
 *   就**什么都不做**并说清楚 —— 不去猜、不去杀别人的进程。
 */
function stopHost(opts = {}) {
  const pidfile = opts.pidfile || PIDFILE;
  const pid = pidOf(opts);
  if (!pid) return { ok: true, stopped: false, note: '没有记录到宿主进程（不是本脚本起的）' };
  if (!alive(pid)) {
    clearPid(opts);
    return { ok: true, stopped: false, note: '进程已经不在了' };
  }
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid, 'SIGTERM'); }
    catch (_e) { try { process.kill(pid, 'SIGTERM'); } catch (_e2) { /* ignore */ } }
  }
  clearPid(opts);
  return { ok: true, stopped: true, pid };
}

/** 给 sidecar / UI 用的一份机器可读状态（一行 JSON）。 */
async function hostState(opts = {}) {
  const host = opts.host || DEFAULT_HOST;
  const pidfile = opts.pidfile || PIDFILE;
  const pid = pidOf(opts);
  return {
    host,
    present: fs.existsSync(path.join(host, 'package.json')),
    deps: hostReady(host),
    pid,
    pid_alive: alive(pid),
    cdp_up: await up(opts),
    port: opts.port || CDP_PORT,
    log: opts.logfile || LOGFILE,
    pidfile,
  };
}

// ------------------------------------------------------------------ fetch
/** 只**算**要干什么，不执行 —— 测试用它，避免单测真的去 npm install。 */
function fetchPlan(host) {
  return {
    needClone: !fs.existsSync(path.join(host, 'package.json')),
    needInstall: !exists(path.join(host, 'node_modules', '.bin',
      process.platform === 'win32' ? 'electron-vite.cmd' : 'electron-vite')),
    needElectron: !hostReady(host),
  };
}

function fetchHost(opts = {}) {
  const host = opts.host || DEFAULT_HOST;
  const proxy = opts.proxy !== undefined ? opts.proxy : (process.env.DSG_PROXY || DEFAULT_PROXY);
  const plan = fetchPlan(host);
  if (opts.planOnly) return { ok: true, plan, skipped: !plan.needInstall && !plan.needElectron };
  if (hostReady(host)) {
    ok('宿主已装好，跳过拉取：' + host);
    return { ok: true, skipped: true, plan };
  }
  const env = { ...process.env };
  if (proxy) {
    env.HTTPS_PROXY = env.HTTPS_PROXY || proxy;
    env.HTTP_PROXY = env.HTTP_PROXY || proxy;
    env.NO_PROXY = env.NO_PROXY || '127.0.0.1,localhost';
    env.npm_config_proxy = env.npm_config_proxy || proxy;
    env.npm_config_https_proxy = env.npm_config_https_proxy || proxy;
    env.ELECTRON_GET_USE_PROXY = env.ELECTRON_GET_USE_PROXY || '1';
    say('    代理：' + proxy);
  } else {
    warn('没设代理 —— 如果 git/npm/Electron 下不动，用 `--proxy http://host:port`。');
  }
  const run = (cmd, args, cwd) => {
    say('    $ ' + [cmd].concat(args).join(' '));
    const r = spawnSync(cmd, args, { cwd, env, stdio: 'inherit', shell: process.platform === 'win32' });
    return r.status === 0;
  };

  if (plan.needClone) {
    fs.mkdirSync(path.dirname(host), { recursive: true });
    if (!run('git', ['clone', HOST_GIT, host], ROOT)) {
      warn('git clone 失败 —— 检查代理/网络。宿主没拉下来不影响我们自己的 app。');
      return { ok: false, step: 'clone', plan };
    }
  }
  if (plan.needInstall && !run('npm', ['install', '--no-audit', '--no-fund'], host)) {
    warn('npm install 失败。');
    return { ok: false, step: 'install', plan };
  }
  if (plan.needElectron && !hostReady(host)) {
    if (!run('node', [path.join('node_modules', 'electron', 'install.js')], host)) {
      warn('Electron 二进制没下下来（233MB，最容易卡在这一步）。');
      return { ok: false, step: 'electron', plan };
    }
  }
  ok('宿主装好了：' + host);
  return { ok: true, plan };
}

// ------------------------------------------------------------------ dev
function runHost(opts = {}) {
  const host = opts.host || DEFAULT_HOST;
  if (!fs.existsSync(path.join(host, 'package.json'))) {
    warn('宿主还没装。先跑：npm run host:fetch');
    return { ok: false };
  }
  const bin = path.join(host, 'node_modules', '.bin',
    process.platform === 'win32' ? 'electron-vite.cmd' : 'electron-vite');
  if (!exists(bin)) {
    warn('宿主没装依赖（缺 electron-vite）。先跑：npm run host:fetch');
    return { ok: false };
  }
  say('    起宿主（CDP 端口 ' + CDP_PORT + '，可以用 tools/_cdp.js 遥控）…');
  const r = spawnSync(bin, ['dev', '--', '--remote-debugging-port=' + String(CDP_PORT)],
    { cwd: host, stdio: 'inherit', shell: process.platform === 'win32' });
  return { ok: r.status === 0, status: r.status };
}

// ------------------------------------------------------------------ status
function status(opts = {}) {
  const host = opts.host || DEFAULT_HOST;
  const src = opts.src || DEFAULT_SRC;
  say('插件源      : ' + src);
  say('            id = ' + (readManifestId(src) || '(读不到 manifest.json)'));
  say('宿主        : ' + host);
  say('            仓库 ' + (fs.existsSync(path.join(host, 'package.json')) ? '在' : '**不在**')
    + ' · 依赖 ' + (hostReady(host) ? '装好' : '**没装好**'));
  const pid = pidOf();
  if (pid) {
    say('宿主进程    : pid ' + pid + ' · ' + (alive(pid) ? '在跑'
      : '**已退出**（pid 文件残留，跑 `stop` 清掉）'));
  } else {
    say('宿主进程    : 不是本脚本起的（可能是你手动 host:dev）');
  }  const dst = path.join(host, 'plugins', PLUGIN_DIR_NAME);
  if (isLink(dst)) {
    say('插件安装    : junction → ' + linkTarget(dst)
      + (samePath(linkTarget(dst), src) ? '  ✔ 指向正确' : '  **指向别处**'));
  } else if (exists(dst)) {
    say('插件安装    : **拷贝**（改源码不生效，跑 link 换成链接）');
  } else {
    say('插件安装    : 还没装');
  }
  for (const d of userDataDirs()) {
    const f = path.join(d, 'plugins-state.json');
    if (!fs.existsSync(f)) { say('启用状态    : 无 ' + f); continue; }
    try {
      const st = JSON.parse(fs.readFileSync(f, 'utf8'));
      say('启用状态    : ' + (Array.isArray(st.enabled) ? st.enabled.join(', ') : '(坏)')
        + '   ← ' + f);
    } catch (e) { say('启用状态    : **坏文件** ' + f); }
  }
  say('命令        : node tools/host.js link | start | stop | state | fetch | dev');
  return { ok: true };
}

// ------------------------------------------------------------------ CLI
async function main(argv) {
  const cmd = (argv[2] || 'status').toLowerCase();
  const flag = (n) => argv.includes('--' + n);
  const val = (n, d) => {
    const i = argv.indexOf('--' + n);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : d;
  };
  const opts = { host: val('host', DEFAULT_HOST), src: val('src', DEFAULT_SRC),
    quiet: flag('quiet'), proxy: val('proxy', undefined),
    port: Number(val('port', CDP_PORT)) || CDP_PORT };
  if (cmd === 'status') { status(opts); return 0; }
  if (cmd === 'state') { say(JSON.stringify(await hostState(opts))); return 0; }
  if (cmd === 'link') {
    try { link(opts); } catch (e) { warn('link 出意外：' + e.message); }
    return 0;                                   // ★ 永远 0：不许挡住 app 启动
  }
  if (cmd === 'start') {
    const r = startHost(opts);
    if (r.ok) ok(r.already ? '宿主已在跑（pid ' + r.pid + '）' : '宿主已启动（pid ' + r.pid + '）');
    else warn(r.error || '启动失败');
    say(JSON.stringify(r));
    return r.ok ? 0 : 1;
  }
  if (cmd === 'stop') {
    const r = stopHost(opts);
    if (r.stopped) ok('宿主已停（pid ' + r.pid + '）');
    else say('    ' + (r.note || '没停'));
    say(JSON.stringify(r));
    return 0;
  }
  if (cmd === 'fetch') {
    if (flag('plan')) { say(JSON.stringify(fetchPlan(opts.host).valueOf(), null, 2)); return 0; }
    return fetchHost(opts).ok ? 0 : 1;
  }
  if (cmd === 'dev') return runHost(opts).ok ? 0 : 1;
  warn('不认识：' + cmd + '（可用：status / state / link / start / stop / fetch / dev）');
  return 2;
}

module.exports = { link, enable, fetchHost, fetchPlan, runHost, status, hostReady,
  readManifestId, userDataDirs, samePath, linkTarget, isLink,
  startHost, stopHost, hostState, up, alive, pidOf,
  DEFAULT_HOST, DEFAULT_SRC, PLUGIN_DIR_NAME, HOST_GIT, CDP_PORT, PIDFILE, LOGFILE };

if (require.main === module) {
  main(process.argv).then((c) => process.exit(c),
    (e) => { warn('出意外：' + (e && e.message)); process.exit(1); });
}
