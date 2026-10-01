#!/usr/bin/env node
/**
 * `tools/host.js` 体检 —— 全在**临时目录**里跑，不碰真宿主、不碰真 %APPDATA%。
 *
 *     node tools/_host_test.js
 *
 * 验的是几件「错了会很难查」的事：
 *   · junction 真能建、**源码改动立刻透过链接可见**（这正是换掉 copytree 的理由）
 *   · 幂等：跑两次不会把链接删了又建、也不会报错
 *   · **工作区搬过家**（链接指别处）能自愈
 *   · 老拷贝能升级成链接，但**别人的插件**（同名、id 不同）一根手指都不碰
 *   · `plugins-state.json` 是**合并**不是覆盖；坏文件要备份 + 重建 + 说出来
 *   · 宿主没拉 / 没装依赖时，`link` 要**降级为警告、exit 0**（因为挂在 start 前面）
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const H = require('./host.js');

const FAIL = [];
function check(cond, msg) {
  console.log((cond ? '  [OK]   ' : '  [FAIL] ') + msg);
  if (!cond) FAIL.push(msg);
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'hosttest-'));
const REAL_APPDATA = process.env.APPDATA;

/** 一份「假宿主 + 假插件源 + 干净 APPDATA」，每个用例一份，互不干扰。 */
function sandbox(name, { pluginId = 'dev.test.bridge' } = {}) {
  const base = path.join(tmp, name);
  const host = path.join(base, 'host');
  const src = path.join(base, 'plugin');
  const appdata = path.join(base, 'appdata');
  fs.mkdirSync(path.join(host, 'plugins'), { recursive: true });
  fs.mkdirSync(src, { recursive: true });
  fs.mkdirSync(path.join(appdata, 'beat-data-generator'), { recursive: true });
  fs.writeFileSync(path.join(host, 'package.json'), '{"name":"fake-host"}', 'utf8');
  fs.writeFileSync(path.join(src, 'manifest.json'),
    JSON.stringify({ id: pluginId, name: 'test' }), 'utf8');
  fs.writeFileSync(path.join(src, 'renderer.js'), '// v1\n', 'utf8');
  process.env.APPDATA = appdata;
  return { base, host, src, appdata,
    state: path.join(appdata, 'beat-data-generator', 'plugins-state.json') };
}

function stateOf(f) {
  return JSON.parse(fs.readFileSync(f, 'utf8'));
}

// ------------------------------------------------------------------ A
function A_link_and_live_source() {
  console.log('='.repeat(78));
  console.log('A. junction 真能建，而且**源码改动立刻透过链接可见**（换掉 copytree 的理由）');
  const s = sandbox('a');
  const r = H.link({ host: s.host, src: s.src, quiet: true });
  check(r.linked && r.mode === 'junction', `建成了 junction（mode=${r.mode}）`);
  check(r.enabled, '顺手启用了插件');
  check(H.isLink(path.join(s.host, 'plugins', 'bridge_plugin')), '目标确实是个链接');
  check(H.samePath(H.linkTarget(path.join(s.host, 'plugins', 'bridge_plugin')), s.src),
    '链接指向我们的插件源码');
  check(fs.readFileSync(path.join(s.host, 'plugins', 'bridge_plugin', 'renderer.js'), 'utf8')
    === '// v1\n', '透过链接读得到内容');

  // ★ 核心卖点：改源码 → 宿主那份立刻变
  fs.writeFileSync(path.join(s.src, 'renderer.js'), '// v2 live\n', 'utf8');
  check(fs.readFileSync(path.join(s.host, 'plugins', 'bridge_plugin', 'renderer.js'), 'utf8')
    === '// v2 live\n', '★ 改了源码，宿主那份**立刻**是新版本（拷贝做不到）');

  // 幂等
  const r2 = H.link({ host: s.host, src: s.src, quiet: true });
  check(r2.linked && r2.mode === 'already', `跑第二次是 no-op（mode=${r2.mode}）`);
  check(H.samePath(H.linkTarget(path.join(s.host, 'plugins', 'bridge_plugin')), s.src),
    '第二次没把链接弄坏');
  check(fs.readlinkSync(path.join(s.host, 'plugins', 'bridge_plugin')).length > 0, '≡ 仍是链接');
}

// ------------------------------------------------------------------ B
function B_stale_link_selfheals() {
  console.log('='.repeat(78));
  console.log('B. 工作区搬过家（链接指别处）⇒ 自愈重建');
  const s = sandbox('b');
  const other = path.join(s.base, 'old-plugin');
  fs.mkdirSync(other, { recursive: true });
  fs.writeFileSync(path.join(other, 'manifest.json'),
    JSON.stringify({ id: 'dev.test.bridge' }), 'utf8');
  fs.symlinkSync(other, path.join(s.host, 'plugins', 'bridge_plugin'), 'junction');
  check(H.samePath(H.linkTarget(path.join(s.host, 'plugins', 'bridge_plugin')), other),
    '先造一个「指向旧位置」的链接');

  const r = H.link({ host: s.host, src: s.src, quiet: true });
  check(r.mode === 'junction' && H.samePath(
    H.linkTarget(path.join(s.host, 'plugins', 'bridge_plugin')), s.src),
    '★ 自愈：链接被重建成指向当前源码');
}

// ------------------------------------------------------------------ C
function C_old_copy_upgrades() {
  console.log('='.repeat(78));
  console.log('C. 老 `_bdg_install_plugin.py` 留的**拷贝**能升级成链接');
  const s = sandbox('c');
  const dst = path.join(s.host, 'plugins', 'bridge_plugin');
  fs.mkdirSync(dst, { recursive: true });
  fs.writeFileSync(path.join(dst, 'manifest.json'),
    JSON.stringify({ id: 'dev.test.bridge' }), 'utf8');
  fs.writeFileSync(path.join(dst, 'renderer.js'), '// 老拷贝\n', 'utf8');
  check(!H.isLink(dst), '先造一个真目录（拷贝）');

  const r = H.link({ host: s.host, src: s.src, quiet: true });
  check(r.mode === 'junction' && H.isLink(dst), `★ 升级成链接（mode=${r.mode}）`);
  check(fs.readFileSync(path.join(dst, 'renderer.js'), 'utf8') === '// v1\n',
    '读到的已经是源码内容（不再是老拷贝）');
}

// ------------------------------------------------------------------ D
function D_foreign_untouched() {
  console.log('='.repeat(78));
  console.log('D. 同名目录但是**别人的**插件 ⇒ 一根手指都不碰');
  const s = sandbox('d', { pluginId: 'dev.test.bridge' });
  const dst = path.join(s.host, 'plugins', 'bridge_plugin');
  fs.mkdirSync(dst, { recursive: true });
  fs.writeFileSync(path.join(dst, 'manifest.json'),
    JSON.stringify({ id: 'dev.someone.else' }), 'utf8');
  fs.writeFileSync(path.join(dst, 'precious.js'), '别删我\n', 'utf8');

  const r = H.link({ host: s.host, src: s.src, quiet: true });
  check(!r.linked, '没有假装成功');
  check(fs.existsSync(path.join(dst, 'precious.js')), '★ 别人的文件还在');
  check(!H.isLink(dst), '也没被换成链接');
  check(r.notes.some((n) => n.includes('别人的插件')), `明确报出来了：${r.notes}`);
  check(r.enabled, '但**启用**那一步照做（那边只管我们的 id）');
}

// ------------------------------------------------------------------ E
function E_state_merge_and_broken() {
  console.log('='.repeat(78));
  console.log('E. plugins-state.json：**合并**不覆盖 + 坏文件备份重建');
  const s = sandbox('e');
  fs.writeFileSync(s.state,
    JSON.stringify({ enabled: ['dev.other.plugin'], theme: 'dark' }), 'utf8');

  H.link({ host: s.host, src: s.src, quiet: true });
  const st = stateOf(s.state);
  check(st.enabled.includes('dev.test.bridge'), '我们的 id 被加进去了');
  check(st.enabled.includes('dev.other.plugin'), '★ 别人的启用项**还在**（合并）');
  check(st.theme === 'dark', '★ 别的字段也没被冲掉');

  const before = stateOf(s.state).enabled.length;
  H.link({ host: s.host, src: s.src, quiet: true });
  check(stateOf(s.state).enabled.length === before, '再跑一次不会重复添加');

  // 坏文件
  const s2 = sandbox('e2');
  fs.writeFileSync(s2.state, '{ 这不是 json', 'utf8');
  const r2 = H.link({ host: s2.host, src: s2.src, quiet: true });
  check(fs.existsSync(s2.state + '.bak'), '★ 坏文件先备份成 .bak（不毁用户的文件）');
  check(fs.readFileSync(s2.state + '.bak', 'utf8') === '{ 这不是 json', '.bak 内容就是原文');
  check(stateOf(s2.state).enabled.includes('dev.test.bridge'), '重建出一份可用的');
  check(r2.notes.some((n) => n.includes('解析失败')), `明确报出来了：${r2.notes}`);
}

// ------------------------------------------------------------------ F
function F_degrades_without_blocking() {
  console.log('='.repeat(78));
  console.log('F. 宿主没拉/没装 ⇒ 降级为警告（因为这步挂在 `start` 前面）');
  const s = sandbox('f');
  const missing = path.join(s.base, 'no-such-host');
  const r = H.link({ host: missing, src: s.src, quiet: true });
  check(!r.linked && r.notes.some((n) => n.includes('还没拉下来')), `报清楚了：${r.notes}`);

  // 宿主在但缺 manifest
  const s2 = sandbox('f2');
  const r2 = H.link({ host: s2.host, src: path.join(s2.base, 'nope'), quiet: true });
  check(!r2.linked && r2.notes.some((n) => n.includes('manifest')), `报清楚了：${r2.notes}`);

  // 静默模式一句都不吭（供 e2e / CI 用）
  const s3 = sandbox('f3');
  const cap = [];
  const orig = process.stdout.write.bind(process.stdout);
  process.stdout.write = (x) => { cap.push(String(x)); return true; };
  H.link({ host: s3.host, src: s3.src, quiet: true });
  process.stdout.write = orig;
  check(cap.length === 0, `quiet 模式零输出（实得 ${cap.length} 段）`);
}

// ------------------------------------------------------------------ G
function G_fetch_gating() {
  console.log('='.repeat(78));
  console.log('G. fetch 的门控：已经装好就**一个字节都不下**');
  const s = sandbox('g');
  // 造一个「装好了」的假宿主
  const dist = path.join(s.host, 'node_modules', 'electron', 'dist');
  fs.mkdirSync(dist, { recursive: true });
  fs.writeFileSync(path.join(dist, process.platform === 'win32' ? 'electron.exe' : 'electron'), 'x');
  check(H.hostReady(s.host), 'hostReady 认出来了');
  const r = H.fetchHost({ host: s.host, proxy: '' });
  check(r.ok && r.skipped, '★ 直接跳过，不 clone 不 install');

  // 没装好的：只**算**计划，不真的 npm install（单测不许联网/起子进程）
  const s2 = sandbox('g2');
  const p2 = H.fetchPlan(s2.host);
  check(p2.needClone === false, '假宿主有 package.json ⇒ 不用 clone');
  check(p2.needInstall && p2.needElectron, `缺依赖、缺 Electron ⇒ ${JSON.stringify(p2)}`);
  const dry = H.fetchHost({ host: s2.host, planOnly: true });
  check(dry.ok && !dry.skipped && dry.plan.needElectron, 'planOnly 只算不做、且不自称已装好');
  check(!fs.existsSync(path.join(s2.host, 'node_modules')), '★ planOnly 真的没动过磁盘');

  // 完全没有宿主 ⇒ 需要 clone
  const s3 = sandbox('g3');
  const p3 = H.fetchPlan(path.join(s3.base, 'no-host'));
  check(p3.needClone && p3.needInstall && p3.needElectron, '一点都没有 ⇒ 三件事都要做');
}

// ------------------------------------------------------------------ H
function H_status_smoke() {
  console.log('='.repeat(78));
  console.log('H. status 只看不动手（不联网、不改文件）');
  const s = sandbox('h');
  H.link({ host: s.host, src: s.src, quiet: true });
  const before = fs.readFileSync(s.state, 'utf8');
  const cap = [];
  const orig = process.stdout.write.bind(process.stdout);
  process.stdout.write = (x) => { cap.push(String(x)); return true; };
  const r = H.status({ host: s.host, src: s.src });
  process.stdout.write = orig;
  const out = cap.join('');
  check(r.ok, 'status 返回 ok');
  check(out.includes('junction'), 'status 说明了安装方式是 junction');
  check(out.includes('指向正确'), 'status 确认指向正确');
  check(out.includes('dev.test.bridge'), 'status 列出了启用项');
  check(fs.readFileSync(s.state, 'utf8') === before, '★ status 没改任何东西');
}

// ------------------------------------------------------------------ I
async function I_start_stop() {
  console.log('='.repeat(78));
  console.log('I. start / stop：非阻塞起、pid 记下来、stop 收干净（用假 launcher，不真起 BDG）');
  const s = sandbox('i');
  // ★ pidfile/日志都指到沙箱里 —— **绝不碰真的 out/_bdg_host.pid**
  const pidfile = path.join(s.base, 'p.pid');
  const logfile = path.join(s.base, 'p.log');
  const o = { host: s.host, pidfile, logfile };
  // 假 launcher：把 `electron-vite/bin/electron-vite.js` 换成一个「睡到被杀」的脚本
  const binDir = path.join(s.host, 'node_modules', 'electron-vite', 'bin');
  fs.mkdirSync(binDir, { recursive: true });
  const bin = path.join(binDir, 'electron-vite.js');
  fs.writeFileSync(bin, 'setInterval(function () {}, 1000);\n', 'utf8');

  check(!H.alive(H.pidOf(o)), '起之前 pidOf() = 0');
  check(fs.existsSync(path.join(s.host, 'package.json')) || true, '（沙箱里）');
  const upBefore = await H.up({ port: 19999, ms: 400 });
  check(upBefore === false, '没有服务时 up() 说 false（不抛）');

  // ★ 非阻塞：startHost 必须**立刻**返回（对比 `dev` 的 spawnSync 会占住进程）
  const t0 = Date.now();
  const r = H.startHost({ ...o, port: 19998 });
  const dt = Date.now() - t0;
  check(r.ok && r.pid > 0, `start 返回了 pid=${r.pid}`);
  check(dt < 2000, `★ start 立刻返回（${dt}ms）—— 不是 spawnSync 那种占住进程的写法`);

  await new Promise((res) => setTimeout(res, 400));
  check(H.alive(r.pid), '进程真的活着');
  check(H.pidOf(o) === r.pid, 'pid 写进了 pidfile');

  const r2 = H.startHost({ ...o, port: 19998 });
  check(r2.ok && r2.already && r2.pid === r.pid, `第二次 start 是 already（pid ${r2.pid}）`);

  const st = H.stopHost(o);
  check(st.stopped && st.pid === r.pid, 'stop 报出停掉的 pid');
  await new Promise((res) => setTimeout(res, 600));
  check(!H.alive(r.pid), '★ 进程真的没了');
  check(H.pidOf(o) === 0, 'pidfile 清掉了');

  const st2 = H.stopHost(o);
  check(st2.ok && !st2.stopped, `再 stop 一次是干净 no-op：${st2.note}`);
  check(H.pidOf(o) === 0, 'pidfile 仍是清的');

  // ★ 残留 pidfile 指向一个不存在的进程 ⇒ 不猜、明确说、顺手清掉
  fs.writeFileSync(pidfile, '999999\n', 'utf8');
  const st3 = H.stopHost(o);
  check(st3.ok && !st3.stopped && /不在了/.test(st3.note || ''), `进程不存在时：${st3.note}`);
  check(H.pidOf(o) === 0, '残留 pidfile 被清掉');

  // 装了依赖才肯起：缺 electron-vite ⇒ 明确失败，不假装
  const s2 = sandbox('i2');
  const r3 = H.startHost({ host: s2.host, port: 19997,
    pidfile: path.join(s2.base, 'p.pid'), logfile: path.join(s2.base, 'p.log') });
  check(!r3.ok && /host:fetch/.test(r3.error || ''), `缺依赖时：${r3.error}`);
}

// ------------------------------------------------------------------ J
async function J_host_state() {
  console.log('='.repeat(78));
  console.log('J. hostState()：给 sidecar/UI 的那份状态');
  const s = sandbox('j');
  const st = await H.hostState({ host: s.host, port: 19996,
    pidfile: path.join(s.base, 'p.pid'), logfile: path.join(s.base, 'p.log') });
  check(st.present === true, 'present 认出来');
  check(st.deps === false, 'deps 说没装好（没有 electron 二进制）');
  check(st.pid === 0 && st.pid_alive === false, '没在跑');
  check(st.cdp_up === false, 'CDP 不通');
  check(typeof st.log === 'string' && typeof st.pidfile === 'string',
    '带上日志与 pidfile 路径（UI 用来告诉用户去哪看）');

  const s2 = sandbox('j2');
  fs.rmSync(path.join(s2.host, 'package.json'));
  const st2 = await H.hostState({ host: s2.host, port: 19996,
    pidfile: path.join(s2.base, 'p.pid') });
  check(st2.present === false, '宿主不在时 present=false（UI 据此提示先 host:fetch）');

  // up() 对一个真在监听的端口要说 true
  const http = require('http');
  const srv = http.createServer((_q, res) => { res.end('{}'); });
  await new Promise((res) => srv.listen(19995, '127.0.0.1', res));
  check((await H.up({ port: 19995, ms: 800 })) === true, '有服务时 up() 说 true');
  await new Promise((res) => srv.close(res));
}

// ------------------------------------------------------------------ K
function K_main_js_quit_trap() {
  console.log('='.repeat(78));
  console.log('K. ★ 源码守卫：`app/main.js` 的退出路径不许再踩 process.execPath 那个坑');
  const ROOT = path.resolve(__dirname, '..');
  const src = fs.readFileSync(path.join(ROOT, 'app', 'main.js'), 'utf8');
  // ★ 只看**代码**：注释里正大光明地写着这个坑（那段说明本身有价值），别把它当成违规
  const code = src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((l) => !/^\s*(\/\/|\*)/.test(l))
    .join('\n');

  check(src.includes('_bdg_host.pid'),
    '★ main.js **自己读 pidfile** 来停宿主（短、同步、不依赖外部程序）');
  check(!/process\.execPath/.test(code),
    '★★ main.js 的**代码里**不许出现 process.execPath —— 在 Electron 里它是 electron.exe，'
    + '拿它去跑 tools/host.js 等于又拉一个 Electron（实测：退出时**一句日志都没有**、'
    + '宿主被留成孤儿窗口）。注释里提到它是允许的（那段是在说明这个坑）');
  check(/taskkill/.test(code), 'Windows 上用 taskkill /T 收掉整棵进程树');
  check(/stopHostWeStarted\(\)/.test(code),
    '退出路径（window-all-closed / before-quit）真的调了它');
  check(code.indexOf('stopHostWeStarted()') < code.indexOf('sidecar.kill()'),
    '★ 顺序对：**先停宿主再杀 sidecar**（硬杀 sidecar 不跑它的 atexit）');
  check(/} catch \(_e\) \{ return; \}/.test(code),
    '读不到 pidfile 就直接返回（不动手）');
  check(/process\.kill\(pid, 0\)/.test(code), '先探活再杀（pid 复用的误杀风险降到最低）');
  check(!/host\.js/.test(code),
    '退出路径不靠外部脚本（不依赖 node 在不在 PATH 上）');
}

function main() {
  return (async () => {
    try {
      A_link_and_live_source();
      B_stale_link_selfheals();
      C_old_copy_upgrades();
      D_foreign_untouched();
      E_state_merge_and_broken();
      F_degrades_without_blocking();
      G_fetch_gating();
      H_status_smoke();
      await I_start_stop();
      await J_host_state();
      K_main_js_quit_trap();
    } finally {
      if (REAL_APPDATA === undefined) delete process.env.APPDATA;
      else process.env.APPDATA = REAL_APPDATA;
      try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (_e) { /* ignore */ }
    }
    console.log('='.repeat(78));
    if (FAIL.length) {
      console.log(`✗ ${FAIL.length} 项失败:`);
      for (const m of FAIL) console.log('   - ' + m);
      return 1;
    }
    console.log('✓ tools/host.js 全部通过');
    return 0;
  })();
}

if (require.main === module) {
  main().then((c) => process.exit(c), (e) => { console.error(e); process.exit(1); });
}
