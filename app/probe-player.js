/**
 * 轻量探针（只验「内嵌 ADOFAI 播放器」这条链路，不跑整套 e2e）：
 *
 *   npx electron . --probe
 *
 * 验四件事：
 *   ① 播放器能起来（tiles / duration 有值）
 *   ② **不自动播**（刚进来 playing === false）
 *   ③ 按播放键能播、时间在走
 *   ④ **再按能暂停**（时间停住）
 * 最后截图到 out/_shots/probe-adofai.png。退出码 0 = 全通过。
 */
const path = require('node:path');
const fs = require('node:fs');

const MID = path.join(__dirname, '..', 'samples', 'audio', 'doublepress_demo_120.mid');
const SHOTS = path.join(__dirname, '..', 'out', '_shots');

module.exports = async function run(win) {
  const js = (code) => win.webContents.executeJavaScript(code, true);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const results = [];
  const check = (name, cond, extra) => {
    results.push(!!cond);
    console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${extra !== undefined ? `   ${extra}` : ''}`);
  };

  const logs = [];
  win.webContents.on('console-message', (...args) => {
    const d = args[0];
    if (d && typeof d === 'object' && 'message' in d) logs.push(`[${d.level}] ${d.message}`);
    else logs.push(`[${args[1]}] ${args[2]}`);
  });

  for (let i = 0; i < 100; i++) {
    // eslint-disable-next-line no-await-in-loop
    const ok = await js('!!window.__dsh').catch(() => false);
    if (ok) break;
    // eslint-disable-next-line no-await-in-loop
    await sleep(200);
  }

  await js(`window.__dsh.load(${JSON.stringify(MID)})`);
  await sleep(800);
  await js(`window.__dsh.tab('chart')`);

  let st = null;
  for (let i = 0; i < 150; i++) {
    // eslint-disable-next-line no-await-in-loop
    st = await js('window.__dsh.adofaiState()').catch(() => null);
    // eslint-disable-next-line no-await-in-loop
    const err = await js('window.__dsh.adofaiErr()').catch(() => '');
    if (st) break;
    if (err) {
      console.log('播放器报错:', err);
      console.log(logs.slice(-30).join('\n'));
      return 1;
    }
    // eslint-disable-next-line no-await-in-loop
    await sleep(400);
  }
  check('① 播放器就绪（拿到格数与时长）', st && st.tiles > 0 && st.dur > 0, JSON.stringify(st));
  check('② 进来**不自动播**', st && st.playing === false, `playing=${st && st.playing}`);

  // 按播放键
  await js('document.querySelector("#btn-play").click()');
  await sleep(3000);
  const a = await js('window.__dsh.adofaiState()');
  check('③ 按播放键后开始播（时间在走）', a && a.playing === true && a.t > 500,
    `playing=${a && a.playing} t=${a && Math.round(a.t)}`);

  // 再按 = 暂停
  await js('document.querySelector("#btn-play").click()');
  await sleep(200);
  const b = await js('window.__dsh.adofaiState()');
  await sleep(1200);
  const c = await js('window.__dsh.adofaiState()');
  check('④ 再按一次能暂停（时间不再前进）',
    b && c && Math.abs(c.t - b.t) < 400, `${Math.round(b.t)} → ${Math.round(c.t)}`);

  // 记录暂停时的画面（看「走过的格子有没有消失」）
  try {
    fs.mkdirSync(SHOTS, { recursive: true });
    const img = await win.webContents.capturePage();
    const p = path.join(SHOTS, 'probe-adofai.png');
    fs.writeFileSync(p, img.toPNG());
    console.log('SHOT', p);
  } catch (e) {
    console.log('SHOT-FAIL', e && e.message);
  }

  if (logs.length) {
    console.log('--- renderer console（末 12 条）---');
    console.log(logs.slice(-12).join('\n'));
  }
  const bad = results.filter((x) => !x).length;
  console.log(`PROBE ${results.length - bad}/${results.length} 通过`);
  return bad ? 1 : 0;
};
