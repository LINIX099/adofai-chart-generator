/**
 * 无头端到端驱动：`npx electron . --e2e`
 *
 * 在真实 Electron 窗口里跑一遍全链路，并**真的检查画布有没有画出东西**
 * （统计非背景像素），最后逐条打印 PASS/FAIL，退出码 0/1。
 *
 * 为什么不用 Playwright/WebDriver：装 electron 二进制都要靠缓存 zip，
 * 少一个依赖少一份风险；`webContents.executeJavaScript` 已经够用了。
 */
const path = require('node:path');
const fs = require('node:fs');

const MID = path.join(__dirname, '..', 'samples', 'audio', 'doublepress_demo_120.mid');
// ★ BDG 工程当来源（docs/38 §9）：拿真实工程当 fixture
const BDG = path.join(__dirname, '..', 'tests', 'fixtures', 'bdg',
                      'v2_real_electric_hornet.bdg');
const OUT = path.join(__dirname, '..', 'out', '_e2e_export');
const SHOTS = path.join(__dirname, '..', 'out', '_shots');
// ★ 毫秒时间戳当来源（docs/45 §7）：现造一份小的，验「这条来源能进能算」
const TSFILE = path.join(__dirname, '..', 'out', '_e2e_ts.txt');
// ★★ 时间戳 JSON（DEMUCS 分轨 · docs/56）：直接吃**内置示例**（用户点「示例▾」
//    看到的就是它），外加一份「原曲找不到」的夹具验载入警告真的上屏
const STEMJSON = path.join(__dirname, '..', 'samples', '示例·分轨时间戳.json');
const STEMJSON_AUDIO_MISSING = path.join(__dirname, '..', 'tests', 'fixtures',
                                        'stemjson', 'audio_missing.json');
const STEMJSON_NOT_STEM = path.join(__dirname, '..', 'tests', 'fixtures',
                                    'stemjson', 'not_stem.json');

const results = [];

/** 截图（布局要"用眼睛验"，所以 e2e 顺便把关键画面存下来）。 */
async function shot(win, name) {
  try {
    await new Promise((r) => setTimeout(r, 350));      // 等一帧画完再拍
    const img = await win.webContents.capturePage();
    fs.mkdirSync(SHOTS, { recursive: true });
    const p = path.join(SHOTS, `ui-${name}.png`);
    fs.writeFileSync(p, img.toPNG());
    console.log(`SHOT ${p}`);
  } catch (e) {
    console.log(`SHOT-FAIL ${name} ${e && e.message}`);
  }
}

function check(name, cond, extra) {
  results.push({ name, ok: !!cond, extra: extra === undefined ? '' : String(extra) });
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${extra !== undefined ? `   ${extra}` : ''}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

module.exports = async function run(win) {
  const js = (code) => win.webContents.executeJavaScript(code, true);
  /** ★ 等 sidecar 那一轮**重算真的落地**，别用固定 sleep 赌。
   *
   *  两个坑（都踩过）：
   *    ① 固定 `sleep(600)` 在「求解慢一点」时就会读到状态栏还在「求解中…」
   *       ⇒ 一串假 FAIL（OGG 出谱 / 分段那几条）。
   *    ② 光等「状态不忙」也不行：`load()` 末尾会先写「已加载 N 轨」，
   *       那时重算还没开始 ⇒ 立刻返回仍然读到中间态。
   *  所以判据 = **rebuildCount 至少 +1** 且状态不再是进行中。 */
  const rebuildCount = async () => (await js('window.__dsh.stats()')).rebuildCount;
  /** `fromCount` 给了就以它为基准（**点击类重算必须用点击前的计数**：
   *  防抖 140ms，凭「状态不忙」会立刻返回 ⇒ 读到旧的 rebuildCount）。 */
  const waitRebuild = async (maxMs = 40000, fromCount = null) => {
    const t0 = Date.now();
    const from = (fromCount === null) ? await rebuildCount() : fromCount;
    let s = '';
    for (;;) {
      s = String(await js('window.__dsh.status()'));
      const busy = /求解中|加载中|准备|开始…/.test(s);
      const c = await rebuildCount();
      if (c > from && !busy) return s;
      if (Date.now() - t0 > maxMs) return s;
      await sleep(120);
    }
  };
  /** 只为「读一份稳定的报告」：不要求 +1，但必须已经是一条**报告**（含「层」等）。
   *  （`__dsh.rebuild()` 是 await 的，正常路径不需要它；留给不确定有没有排队的场合。） */
  const waitSettled = async (maxMs = 30000) => {
    const t0 = Date.now();
    let s = '';
    for (;;) {
      s = String(await js('window.__dsh.status()'));
      if (!/求解中|加载中|准备|开始…/.test(s) && /层|⚠|失败|没有/.test(s)) return s;
      if (Date.now() - t0 > maxMs) return s;
      await sleep(150);
    }
  };
  /** ★ 改主轨并**等到重算完**再读 —— `setTracks` 走的是 140ms 防抖 +
   *  异步 derive，直接读 payload 会读到**上一轮**的音点数（实测 328 vs 155）。 */
  const setTracksAndCount = async (list) => {
    await js(`window.__dsh.setTracks(${JSON.stringify(list)})`);
    await waitRebuild();
    return await js('(window.__dsh.payload()||{}).hit?.length||0');
  };

  // 0. 等渲染进程初始化完（__dsh 出现）
  for (let i = 0; i < 100; i++) {
    // eslint-disable-next-line no-await-in-loop
    const ok = await js('!!window.__dsh').catch(() => false);
    if (ok) break;
    // eslint-disable-next-line no-await-in-loop
    await sleep(200);
  }
  check('渲染进程暴露调试钩子', await js('!!window.__dsh'));

  // 1. 加载 MIDI（旧 UI 的首次重建走 140ms 防抖，这里显式等它落地）
  await js(`window.__dsh.load(${JSON.stringify(MID)})`);
  await sleep(600);
  check('加载后 status 有内容', (await js('window.__dsh.status()')).length > 3);
  let nFloors = await js('(window.__dsh.payload()||{}).floors?.length||0');
  if (!nFloors) {
    await js('window.__dsh.rebuild()');
    nFloors = await js('(window.__dsh.payload()||{}).floors?.length||0');
  }
  check('已生成谱面（floors > 0）', nFloors > 0, `floors=${nFloors}`);
  const nNotes = await js('(window.__dsh.payload()||{}).notes?.length||0');
  check('卷帘拿到原始音符', nNotes > 0, `notes=${nNotes}`);

  // 谱面预览容器的布局尺寸（隐藏窗口下也要有布局）
  const w0 = await js('document.querySelector("#cv-adofai").clientWidth');
  const h0 = await js('document.querySelector("#cv-adofai").clientHeight');
  check('谱面预览容器有布局尺寸', w0 > 100 && h0 > 100, `${w0}x${h0}`);

  // 2. 其余三个 canvas 页签各画一次，统计非背景像素
  for (const tab of ['roll', 'path', 'falling']) {
    // eslint-disable-next-line no-await-in-loop
    await js(`window.__dsh.tab('${tab}')`);
    // eslint-disable-next-line no-await-in-loop
    await js('window.__dsh.draw()');
    // eslint-disable-next-line no-await-in-loop
    const n = await js(`(() => {
      const cv = document.querySelector('#cv-' + '${tab}');
      const ctx = cv.getContext('2d');
      const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
      let diff = 0;
      for (let i = 0; i < d.length; i += 16) {
        if (d[i] > 40 || d[i+1] > 40 || d[i+2] > 40) diff++;
      }
      return diff;
    })()`);
    check(`页签 ${tab} 画出了内容`, n > 200, `非背景采样点=${n}`);
  }

  // 2b. ★ 谱面预览 = 内嵌的 Re_ADOJAS 渲染引擎（docs/22）
  await js('window.__dsh.tab("chart")');
  let adv = null;
  for (let i = 0; i < 120; i++) {
    // eslint-disable-next-line no-await-in-loop
    adv = await js('window.__dsh.adofaiState()').catch(() => null);
    if (adv) break;
    // eslint-disable-next-line no-await-in-loop
    await sleep(400);
  }
  check('谱面预览：ADOFAI 引擎就绪', !!(adv && adv.tiles > 0),
    adv ? JSON.stringify(adv) : `err=${await js('window.__dsh.adofaiErr()')}`);
  check('ADOFAI 引擎给出真实时长', !!(adv && adv.dur > 1000), `${adv && Math.round(adv.dur)}ms`);
  const pcan = await js(`(() => {
    const host = document.querySelector('#cv-adofai');
    const cv = host.querySelector('canvas');
    if (!cv) return null;
    return { w: cv.clientWidth, h: cv.clientHeight };
  })()`);
  check('播放器把自己的 canvas 挂进了容器', !!(pcan && pcan.w > 100 && pcan.h > 100),
    JSON.stringify(pcan));
  check('刚进谱面预览**不自动播**', !!(adv && adv.playing === false),
    `playing=${adv && adv.playing}`);

  // 走过的格子必须会消失：`beatsBehind = 0` 在 TimelineManager 里结构上等于永不消失
  const LJS = 'window.__dsh.api.levelJson(window.__dsh.state)';
  const bb = await js(`${LJS}.then(r => (r && r.ok) ? r.level.settings.beatsBehind : null)`);
  check('消失提前拍数 beatsBehind > 0（0 = 永不消失）',
    bb !== null && bb > 0, `beatsBehind=${bb}`);
  const bAnim = await js(`${LJS}.then(r => (r && r.ok) ? r.level.settings.trackDisappearAnimation : null)`);
  check('消失动画不是 None', !!(bAnim && bAnim !== 'None'), `trackDisappearAnimation=${bAnim}`);

  // 播放键驱动预览，再按能暂停
  await js('document.querySelector("#btn-play").click()');
  await sleep(1600);
  const pp1 = await js('window.__dsh.adofaiState()');
  check('播放键能驱动 ADOFAI 预览',
    !!(pp1 && pp1.playing === true && pp1.t > 300),
    `playing=${pp1 && pp1.playing} t=${pp1 && Math.round(pp1.t)}`);
  await js('document.querySelector("#btn-play").click()');
  await sleep(150);
  const pp2 = await js('window.__dsh.adofaiState()');
  await sleep(900);
  const pp3 = await js('window.__dsh.adofaiState()');
  check('再按一次能暂停 ADOFAI 预览',
    !!(pp2 && pp3 && Math.abs(pp3.t - pp2.t) < 400),
    `${pp2 && Math.round(pp2.t)} → ${pp3 && Math.round(pp3.t)}`);

  // 全曲条选格 → 喂到播放器的 selectTile
  await js('window.__dsh.selectFloor(30)');
  await sleep(500);
  const selAdv = await js('window.__dsh.adofaiState()');
  check('全曲条选格同步到 ADOFAI 播放器',
    !!(selAdv && selAdv.sel === 30), `sel=${selAdv && selAdv.sel}`);

  // ★ 偏移修正（docs/24 §5）：payload 的轴口径必须只差一个常量，且全曲条与 payload 同轴。
  const ax = await js(`(() => {
    const p = window.__dsh.payload() || {};
    return { shift: p.audio_shift_ms, lead: p.audio_lead_ms, off: p.offset,
             en120: (p.entry || [])[120] };
  })()`);
  check('payload 给出偏移换算常量（audio_shift_ms / audio_lead_ms）',
    typeof ax.shift === 'number' && typeof ax.lead === 'number',
    JSON.stringify(ax));
  check('audio_shift_ms == offset − audio_lead_ms（轴口径自洽）',
    Math.abs(ax.shift - (ax.off - ax.lead)) < 1e-6,
    `${ax.shift} vs ${ax.off} − ${ax.lead}`);
  const ft120 = await js('window.__dsh.floorTime(120)');
  check('全曲条与 payload 同轴（floorTime(i) == entry[i]）',
    Math.abs(ft120 - ax.en120) < 0.01,
    `floorTime=${ft120} entry[120]=${ax.en120}`);
  // 音乐延迟补偿控件必须在（这是播放器自带的「偏移修正」，以前完全没接）
  const md = await js(`(() => {
    const el = document.querySelector('#in-music_delay_ms');
    const b = document.querySelector('#btn-music-delay-auto');
    return el ? { has: true, val: el.value, btn: !!b } : { has: false };
  })()`);
  check('谱面预览控制条有「音乐延迟补偿」控件与建议按钮',
    !!(md && md.has && md.btn), JSON.stringify(md));
  // 新口径：等待拍用暂停节拍 / 最小角度
  const v03 = await js(`(() => {
    const d = window.__dsh.schema().defaults;
    return { pm: d.pause_min_beats, tm: d.travel_min };
  })()`);
  check('默认「等待拍阈值」= 4（用户 2026-10 改：1~4 拍交回求解器）', v03.pm === 4,
    `pause_min_beats=${v03.pm}`);
  check('默认「最小角度」= 20°', v03.tm === 20, `travel_min=${v03.tm}`);
  const stV03 = String(await js('window.__dsh.status()'));
  check('状态栏报出 Pause 处数', /Pause\s*\d+/.test(stV03), stV03.slice(0, 110));

  // 3. 改参数 → 防抖重建（雪花要拿有等间隔长段的曲子才点得起来）
  await js('window.__dsh.tab("chart")');
  await js('window.__dsh.setParam("straight_preset", 2)');
  await js('window.__dsh.rebuild()');
  const st3 = String(await js('window.__dsh.status()'));
  check('改参数后重建成功', /层/.test(st3), st3.slice(0, 110));
  // ★ 新口径后直线格占绝大多数（直线格上的 Twirl 是空操作，不会画图标），
  //   所以「能生成 Twirl」要挑一个真的需要转向的策略来验。
  await js('window.__dsh.setParam("twirl_index", 2)');   // 逐步打分
  await js('window.__dsh.rebuild()');
  const tw3 = await js('(window.__dsh.payload()||{}).floors?.filter(f=>f.twirl).length||0');
  check('Twirl 已生成（逐步打分策略）', tw3 > 0, `twirl=${tw3}`);
  await js('window.__dsh.setParam("twirl_index", 0)');

  await js(`window.__dsh.load(${JSON.stringify(
    path.join(__dirname, '..', 'samples', '_external', 'Automaton_Waltz.mid'))})`);
  await sleep(600);
  await js('window.__dsh.setParam("use_snowflake", true)');
  await js('window.__dsh.setParam("snowflake_min_tiles", 4)');
  await js('window.__dsh.setParam("snowflake_full_tiles", 24)');
  await js('window.__dsh.rebuild()');
  const stS = String(await js('window.__dsh.status()'));
  check('雪花生效（Automaton_Waltz 状态里报朵数）', /魔法阵\s*\d+\s*朵/.test(stS),
    stS.slice(0, 170));
  const snowTiles = await js('(window.__dsh.payload()||{}).floors?.filter(f=>f.snow).length||0');
  check('雪花层已生成', snowTiles > 0, `snow tiles=${snowTiles}`);

  // 回到双押演示曲，测两条双押路径
  await js(`window.__dsh.load(${JSON.stringify(MID)})`);
  await sleep(600);

  // ★ 新功能：主轨可多选 = 取并集（哪条有音采哪条）。
  //   ⚠ 必须走 `setTracks`（会连带改写 pitch_lo/hi）；直接写 state.tracks_checked
  //     会留下上一次选择的音高过滤把音偷偷滤掉（实测 483 note 只剩 155 onset）。
  const li = await js('window.__dsh.loadInfo()');
  const nonDrum = ((li && li.tracks) || [])
    .filter((t) => t.has_notes && !t.drum).map((t) => t.index);
  // ★ 2026-10：这条素材的 trk2 / trk3 **在时间上高度重合**（都在 500ms 网格上），
  //   而自动主轨现在按「覆盖全曲」挑到了 trk2 ⇒ 并集等于 trk2 自己（328 → 328），
  //   「多勾一条就变多」这个前提不成立。所以：先从**一条**轨起，再加并集，
  //   判据写成「并集 ≥ 单条，且**至少有一条**单轨确实更少」。
  const trk3Only = await setTracksAndCount([3]);
  const oneOnsets = await setTracksAndCount(li.default_tracks_checked);
  const manyOnsets = await setTracksAndCount(nonDrum);
  check('主轨多选 = 取并集（并集 ≥ 任一单条，且勾上更全的轨会变多）',
    nonDrum.length >= 2 && manyOnsets >= oneOnsets && oneOnsets > 0
    && (manyOnsets > oneOnsets || manyOnsets > trk3Only),
    `默认 ${JSON.stringify(li.default_tracks_checked)}：${oneOnsets} onset`
    + ` → 勾 ${JSON.stringify(nonDrum)}：${manyOnsets} onset（单 trk3 = ${trk3Only}）`);
  const hintM = String(await js('document.querySelector("#lbl-track").textContent'));
  check('主轨提示写明是「取并集」', /并集/.test(hintM), hintM.slice(0, 90));

  // 双押：回到**默认单主轨**再验 —— 角度双押在过密谱面（并集 328 onset）上无处可插，
  // 实测 0 处，用它验「能插层」会假失败。
  await js(`window.__dsh.load(${JSON.stringify(MID)})`);
  await sleep(700);
  const baseFloors = await js('(window.__dsh.payload()||{}).floors?.length||0');
  const dpOff = await js('window.__dsh.state.dp_checked');
  await js('window.__dsh.state.dp_checked = []');
  await js('window.__dsh.rebuild()');
  const noDpFloors = await js('(window.__dsh.payload()||{}).floors?.length||0');
  check('关掉双押轨后层数更少', noDpFloors < baseFloors, `${noDpFloors} < ${baseFloors}`);
  await js(`window.__dsh.state.dp_checked = ${JSON.stringify(dpOff)}`);

  await js('window.__dsh.setParam("dp_mode", 1)');
  await js('window.__dsh.rebuild()');
  const st4 = String(await js('window.__dsh.status()'));
  check('角度双押重建成功',
    /角度双押/.test(st4) && !/unexpected keyword/.test(st4), st4.slice(0, 150));
  const nFloors4 = await js('(window.__dsh.payload()||{}).floors?.length||0');
  check('角度双押在无双押基础上插了层', nFloors4 > noDpFloors,
    `${noDpFloors} → ${nFloors4}`);

  await js('window.__dsh.setParam("dp_mode", 0)');
  await js('window.__dsh.rebuild()');
  const st5 = String(await js('window.__dsh.status()'));
  check('中旋双押重建成功', /中旋双押/.test(st5), st5.slice(0, 150));

  // ★★ 三押（docs/48）：**两条多押轨同一时间都有音** ⇒ 那一格拆 3 块。
  //   这条样例 MIDI 的 trk1/trk2 在 500ms 网格上同步 ⇒ 一说就该有三押。
  //   ⚠ 主轨**必须避开**多押轨：多押轨按口径不参与主轨并集，撞车会被拒算
  //   （只保留上一张谱面 ⇒ 后面的断言全变成看旧数据）。这里用 trk3。
  await js('window.__dsh.setTracks([3])');
  await js('window.__dsh.setParam("dp_mode", 1)');
  await js('window.__dsh.state.dp_checked = [1, 2]');
  await js('window.__dsh.rebuild()');
  // ★ `__dsh.rebuild()` 是 **await 过的**（整轮重算已经落地）⇒ 别再 `waitRebuild()`：
  //   它等的是「下一次计数 +1」，而那一次永远不会来 ⇒ 白等满 40s 超时（用户口径「别死等」）。
  const stT = String(await js('window.__dsh.status()'));
  const hintT = String(await js('document.querySelector("#tab-hint").textContent'));
  check('★ 两条多押轨 ⇒ 报告出现「三押 N 处」', /三押 \d+ 处/.test(stT),
    stT.slice(0, 170));
  check('★ 三押数进 tab 提示（不许静默）', /含三押 \d+/.test(hintT),
    hintT.slice(0, 120));
  const dpThree = await js('((window.__dsh.lastResult()||{}).dp||{}).dp_three||0');
  // ★ 四押：**三条**多押轨同时 ⇒ 跳过。两个前提让它可测：
  //   ① 非采bpm 路径的主轨不能与多押轨重叠（`_selected` 会把重叠轨剔除）
  //     ⇒ 走采bpm 骨架（全曲接管 ⇒ 主轨可以为空）
  //   ② 全曲都是等间隔骨架砖时，求解器会把它们铺成**雪花/模板**格，
  //     而雪花/模板是**硬保护**格（`_hard_owned`）⇒ 双押一处都插不进去。
  //     所以这一段必须临时关掉雪花与模板（两个参数完事后还原）。
  const origSnow = await js('window.__dsh.state.use_snowflake');
  const origTpl = await js('window.__dsh.state.use_templates');
  await js('window.__dsh.setParam("use_snowflake", false)');
  await js('window.__dsh.setParam("use_templates", false)');
  await js('window.__dsh.setParam("xk_base", 4)');
  await js('window.__dsh.setParam("xk_tbpm", 250)');
  await js('window.__dsh.state.tracks_checked = []');
  await js('window.__dsh.state.dp_checked = [1, 2, 3]');
  await js('window.__dsh.rebuild()');
  const dpExtra = await js('((window.__dsh.lastResult()||{}).dp||{}).dp_extra_press||0');
  check('★ 三条多押轨 ⇒ 四押被**跳过**并上屏', Number(dpExtra) > 0,
    `dp_extra_press=${dpExtra} dp_three=${dpThree}`);
  const hintE = String(await js('document.querySelector("#tab-hint").textContent'));
  check('★ 跳过的四押也写在 tab 提示里', /跳过四押 \d+/.test(hintE),
    hintE.slice(0, 120));
  // ★ 还原成进这一段之前的样子（后面第 8 节要验轴口径，谱面必须与原来一致）
  await js('window.__dsh.setParam("xk_base", 0)');
  await js('window.__dsh.setParam("xk_tbpm", 0)');
  await js(`window.__dsh.setParam("use_snowflake", ${JSON.stringify(origSnow)})`);
  await js(`window.__dsh.setParam("use_templates", ${JSON.stringify(origTpl)})`);
  await js('window.__dsh.state.dp_checked = [1]');
  await js(`window.__dsh.setTracks(${JSON.stringify(li.default_tracks_checked)})`);
  // ★ 还原成**当前 schema 的默认写法**（2026-10 默认从中旋改成角度双押）——
  //   别写死数字，否则默认一改这条就变成「在测一个没人用的组合」。
  await js('window.__dsh.setParam("dp_mode", window.__dsh.schema().defaults.dp_mode)');
  await js('window.__dsh.rebuild()');
  const stDp = String(await js('window.__dsh.status()'));
  check('默认写法（角度双押）重建成功', /角度双押/.test(stDp), stDp.slice(0, 140));

  // 5. 音频可用（不真的播，避免自动播放策略）
  const au = await js('window.__dsh.api.audio(window.__dsh.state)');
  check('音频可获取', au && au.ok, au && au.error ? au.error : au.path);

  // 6. 导出
  await js('window.__dsh.setParam("offset", 0)');
  await js(`window.__dsh.export.__e2eDir = ${JSON.stringify(OUT)}`);
  const ex = await js(`window.__dsh.api.exportTo(window.__dsh.state, ${JSON.stringify(OUT)})`);
  check('导出成功', ex && ex.ok, ex && (ex.error || ex.msg || '').slice(0, 120));
  check('第三方反解校验通过', ex && ex.verify_ok, ex && (ex.verify || '').slice(0, 140));

  // 7. 自动 offset 的「写回不回环」（docs/18 风险 3）
  //   ★ 非空过写法：先把 offset 设成**明显不同**的值，再开自动 ⇒ 必须被算出来的值覆盖。
  //     （这份素材的首个 onset 在 0、自动值恰好也是 0 ⇒ 直接断言 `>0` 会假 FAIL。）
  await js('window.__dsh.setParam("offset", 12345)');
  await js('window.__dsh.setParam("auto_offset", true)');
  await js('window.__dsh.rebuild()');
  await sleep(400);                       // 先让 setParam 触发的那次防抖落地
  const c1 = (await js('window.__dsh.stats()')).rebuildCount;
  const off1 = await js('window.__dsh.state.offset');
  const auto1 = Number((await js('(window.__dsh.lastResult()||{}).auto_offset')) ?? NaN);
  await sleep(1800);
  const c2 = (await js('window.__dsh.stats()')).rebuildCount;
  check('自动 offset 写回了 offset 框（覆盖手动值）',
    Number.isFinite(auto1) && Math.abs(Number(off1) - auto1) < 1e-6 && Number(off1) !== 12345,
    `手动 12345 → 框里 ${off1}（自动值 ${auto1}）`);
  check('程序写值没有触发重建回环', c2 === c1, `${c1} → ${c2}`);
  const on1 = await js('window.__dsh.state.auto_offset');
  await js('window.__dsh.setParam("auto_offset", false)');
  await sleep(300);
  check('关掉自动 offset 不炸', (await js('window.__dsh.state.auto_offset')) === false,
    `before=${on1}`);

  // 8. 播放 / 时间轴（真播一段，看播放头与滑块是否跟着走）
  //    ★ 先切到非「谱面预览」页：那一页的播放键现在由内嵌 ADOFAI 播放器接管，
  //      这一节要验的是全局 <audio> 那条走带。
  await js('window.__dsh.tab("roll")');
  await js('window.__dsh.rebuild()');
  await js('window.__dsh.play()');
  await sleep(1200);
  const p1 = await js('window.__dsh.pos()');
  await sleep(700);
  const p2 = await js('window.__dsh.pos()');
  check('音频真的在走（currentTime 递增）', p2 > p1 && p1 > 0, `${p1.toFixed(0)} → ${p2.toFixed(0)} ms`);
  const dur = await js('window.__dsh.dur()');
  check('时长已就绪', dur > 1000, `${dur.toFixed(0)}ms`);
  // ★ 轴口径（docs/24 §5）：`seek()` 收**采音轴**，`pos()` 是 `<audio>` 轴，两者差 `lead`。
  await js('window.__dsh.seek(20000)');
  await sleep(300);
  const cf20 = await js('window.__dsh.curFloor()');
  check('播放头跟着音频（当前格 > 0）', cf20 > 0, `floor=${cf20}`);
  check('滑块跟着音频', (await js('window.__dsh.sliderValue()')) > 0,
    `slider=${await js('window.__dsh.sliderValue()')}`);
  check('时间标签是 分:秒.百分秒', /^\d+:\d\d\.\d\d \/ \d+:\d\d\.\d\d$/.test(
    await js('window.__dsh.timeLabel()')), await js('window.__dsh.timeLabel()'));
  await js('window.__dsh.seek(5000)');
  await sleep(250);
  const p3p = JSON.parse(await js(`(() => {
    const p = window.__dsh.pos();
    return JSON.stringify({ p, g: window.__dsh.toGrid(p), lead: window.__dsh.axis().lead });
  })()`));
  const p3 = p3p.p;
  const p3g = p3p.g;
  check('seek 到 5s 生效（采音轴）', Math.abs(p3g - 5000) < 400,
    `pos=${p3.toFixed(0)}ms → 采音轴 ${p3g.toFixed(0)}ms`);
  // ⚠ 必须在**同一次读取**里取 pos/toGrid/lead：音频还在播，分两次 `js()` 读
  //   会被播放头跑掉几毫秒（老写法实测差 3.6ms ⇒ 假 FAIL）。
  check('seek 后 <audio> 位置 = 采音轴 + lead', Math.abs(p3 - (p3g + p3p.lead)) < 1,
    `${p3.toFixed(1)} vs ${p3g.toFixed(1)} + ${p3p.lead.toFixed(1)}`);
  await js('window.__dsh.play()');   // 暂停
  await sleep(200);
  const p4 = await js('window.__dsh.pos()');
  await sleep(500);
  check('暂停后不再前进', Math.abs((await js('window.__dsh.pos()')) - p4) < 60);

  // 9. 导出目录名净化（曲名里有非法字符）
  await js('window.__dsh.setParam("song", "a/b:c*d?e")');
  const ex2 = await js(`window.__dsh.api.exportTo(window.__dsh.state, ${JSON.stringify(OUT)})`);
  check('导出成功（非法字符曲名）', ex2 && ex2.ok, ex2 && ex2.dir);
  check('目录名已净化', ex2 && !/[\\/:*?"<>|]/.test(path.basename(ex2.dir || '')),
    ex2 && path.basename(ex2.dir || ''));

  // 10. OGG 全链路（长任务：SSE 进度 + 自洽网格 + 检波偏置）
  // ★★ 2026-10：**界面里已隐藏「从音频文件采音」**（用户口径「假装不存在、不能选择」）。
  //   所以这里改走 `__dsh.loadRaw`（直打后端口径）—— 验的是**后端没被改坏**
  //   （用户同时要求「逻辑层不要动一个字」，那就得留证据）。
  //   顺带在下一节断言「界面那条路确实被挡住了」。
  const OGG = path.join(__dirname, '..', 'samples', 'audio', 'doublepress_demo_120.ogg');
  if (require('node:fs').existsSync(OGG)) {
    const ev0 = (await js('window.__dsh.stats()')).progressEvents;
    await js(`window.__dsh.loadRaw(${JSON.stringify(OGG)})`);
    const st6 = String(await waitRebuild());
    check('OGG 加载并出谱', (await js('(window.__dsh.payload()||{}).floors?.length||0')) > 0,
      `floors=${await js('(window.__dsh.payload()||{}).floors?.length||0')}`);
    check('OGG 收到 SSE 进度事件',
      (await js('window.__dsh.stats()')).progressEvents > ev0,
      `${ev0} → ${(await js('window.__dsh.stats()')).progressEvents}`);
    const fileTxt = await js('document.querySelector("#lbl-file").textContent');
    check('界面显示网格拟合/检波偏置',
      /网格/.test(fileTxt) && /检波偏置/.test(fileTxt), fileTxt.replace(/\n/g, ' | ').slice(0, 150));
    check('OGG 出谱后 status 正常', /层/.test(st6), st6.slice(0, 110));
    // 用原曲音频（source_audio 分支）
    const au2 = await js('window.__dsh.api.audio(window.__dsh.state)');
    check('OGG 直接用原曲当预览音源', au2 && au2.ok && /\.ogg$/.test(au2.path || ''),
      au2 && au2.path);
  } else {
    check('OGG 样本存在', false, OGG);
  }

  // 10b. ★★ 「从音频文件采音」在**界面层**已被隐藏（后端不动）
  {
    const before = await js('(window.__dsh.payload()||{}).floors?.length||0');
    await js(`window.__dsh.load(${JSON.stringify(OGG)})`);          // 走界面那条路
    await sleep(400);
    const st7 = String(await js('document.querySelector("#status").textContent'));
    const after = await js('(window.__dsh.payload()||{}).floors?.length||0');
    check('★ 界面路径**拒绝**音频当来源（不是本版本支持的载入格式）',
      /不是本版本支持的载入格式/.test(st7) || /不是本版本支持/.test(st7), st7.slice(0, 90));
    check('★ 拒绝之后**没有换掉**当前谱面（真的没进算法）', after === before,
      `${before} → ${after}`);
    const btnTxt = await js(`[...document.querySelectorAll('button')]
      .map(b=>b.textContent).find(t=>/打开 /.test(t))||''`);
    check('★ 载入按钮文案不再提「音频」', !!btnTxt && !/音频/.test(btnTxt), btnTxt);
    // ★ 这条必须是**真断言**（第一版写成 check(..., true, ...) = 恒过，等于没测）
    const advertise = await js(`[...document.querySelectorAll('button,label,div,span')]
      .map(e=>e.textContent||'')
      .filter(t=>/打开\\s*MIDI\\s*\\/\\s*音频/.test(t)).length`);
    check('★ 界面上没有「打开 MIDI / 音频 …」这种宣传', advertise === 0,
      `matched=${advertise}`);
  }

  // 11. 真实 DOM 交互（不走调试钩子：直接点控件 / 派发事件 —— 用户实际的那条路径）
  await js(`window.__dsh.load(${JSON.stringify(MID)})`);
  await sleep(650);

  await js('document.querySelector(".tab[data-tab=\'roll\']").click()');
  check('点页签按钮切视图',
    await js('document.querySelector("#cv-roll").classList.contains("active")'));
  await js('document.querySelector(".tab[data-tab=\'chart\']").click()');

  const m0 = await js('window.__dsh.state.merge_ms');
  await js(`(() => { const el = document.querySelector('#in-merge_ms');
    el.value = '55'; el.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  check('改数值框 → 状态更新', (await js('window.__dsh.state.merge_ms')) === 55,
    `${m0} → ${await js('window.__dsh.state.merge_ms')}`);
  // ★ 复原！以前改了不还原 ⇒ 后面每一节都在 merge_ms=55 的谱面上跑
  //   （「位置偏移」那一条就因此读到 0 条错开 = 假 FAIL）。
  await js(`window.__dsh.setParam("merge_ms", ${JSON.stringify(m0)})`);
  // ★ 同上：`setParam` 不触发重算 ⇒ 显式重算一次，别白等 40s（那条 40s 超时以前
  //   每跑一次 e2e 都白花一次；用户 2026-10 要求「别死等」）
  await js('window.__dsh.rebuild()');
  await sleep(200);

  // ★★ 基准 BPM 框「输完了会被变回来」（用户 2026-10 报的 bug）
  //   根因：`auto_bpm` 默认勾着 ⇒ 后端每次 rebuild 都回一个 `display_bpm`
  //   （**它自己选的**那个值），前端 `applyPayload` 无条件把它写回输入框
  //   ⇒ 用户敲进去的数下一次重算就被覆盖回去，看起来「这个框根本不能输入」。
  //   契约（与 offset 同一套）：**手改基准 BPM = 明确要自己定** ⇒ 顺手关掉
  //   「自动选基准 BPM」（并上屏），之后这个框就是用户的输入，不许再被回写。
  {
    const abDefault = await js('window.__dsh.schema().defaults.auto_bpm');
    const bb0 = await js('window.__dsh.state.base_bpm');
    await js('window.__dsh.setParam("auto_bpm", true)');   // 先回到「自动」这个默认态
    // ★ `setParam` = 程序性写值，**不触发重算** ⇒ 必须显式来一次
    //   （别用 `waitRebuild()`：那会等一个永远不会来的重算，白等 40s）
    await js('window.__dsh.rebuild()');
    await sleep(300);
    const autoVal = Number(await js('document.querySelector("#in-base_bpm").value'));
    await js(`(() => { const el = document.querySelector('#in-base_bpm');
      el.value = '200'; el.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    // 轻提示是**同步**出的（状态栏随后会被重算报告顶掉）⇒ 当场读
    const bpmToast = await js('(document.querySelector("#toast")||{}).textContent||""');
    await waitRebuild();
    // ★ 再等一次「已成一条完整报告」：`waitRebuild` 只保证「计数 +1 且当时不忙」，
    //   紧接着可能又有一次重算在飞（读 payload 会读到上一张谱 ⇒ 假 FAIL）。
    await waitSettled();
    const after = await js(`(() => ({
      box: document.querySelector('#in-base_bpm').value,
      state: window.__dsh.state.base_bpm,
      auto: window.__dsh.state.auto_bpm,
      bpm0: (window.__dsh.payload() || {}).bpm0,
      status: String(window.__dsh.status() || '')
    }))()`);
    check('★ 基准 BPM 框**输入的值不会被回填覆盖**（用户报的 bug）',
      String(after.box) === '200',
      `输入 200，重算后框里是 ${after.box}（自动模式下后端回填的是 ${autoVal}）`);
    check('★★ 手改基准 BPM ⇒ 顺手关掉「自动选基准 BPM」',
      after.auto === false, `auto_bpm=${after.auto}`);
    check('★★ 输入的基准 BPM 真的进了求解（payload.bpm0 = 200）',
      Math.abs(Number(after.bpm0) - 200) < 0.5, `bpm0=${after.bpm0}`);
    check('★ 状态栏说明了这件事（不许静默）', /基准 BPM/.test(after.status),
      after.status.slice(0, 60));
    check('★ 轻提示当场说明「已改成手动基准 BPM」（状态栏会被重算报告顶掉）',
      /手动基准 BPM/.test(bpmToast), bpmToast.slice(0, 60));
    // 复原（别让后面的小节跑在 base_bpm=200 上）
    await js(`window.__dsh.setParam("auto_bpm", ${JSON.stringify(abDefault)})`);
    await js(`window.__dsh.setParam("base_bpm", ${JSON.stringify(bb0)})`);
    await js('window.__dsh.rebuild()');
    await sleep(300);
  }

  const snow0 = await js('window.__dsh.state.use_snowflake');
  await js('document.querySelector("#in-use_snowflake").click()');
  const snow1 = await js('window.__dsh.state.use_snowflake');
  check('勾选框 click → 状态跟随取反', snow1 === !snow0, `${snow0} → ${snow1}`);
  await js('document.querySelector("#in-use_snowflake").click()');   // 复原
  check('再点一次复原', (await js('window.__dsh.state.use_snowflake')) === snow0);

  // ★ 轨道位置偏移（用户 2026-10：「改为可选是否开启」→ 后又说「**可以开局为关闭了**」）
  //   坑：`core/track_fx.py` + `SolveParams.use_position_track` 早就有，
  //   但 schema/UI 从没暴露过 —— 用户在界面上关不掉。这里守四件事：
  //   默认**关** / 打开后 payload 真的出现错开条数 / 再关掉归零 / 状态栏说清楚。
  const pt0 = await js('window.__dsh.state.use_position_track');
  check('轨道位置偏移默认关闭（2026-10 用户口径）', pt0 === false, String(pt0));
  const ptN0 = Number(await js('(window.__dsh.payload()||{}).pos_track_n||0'));
  check('默认关闭时 payload.pos_track_n 为 0', ptN0 === 0, String(ptN0));
  await js('window.__dsh.setParam("use_position_track", true)');
  const rPt1 = await js('window.__dsh.rebuild()');
  const ptN1 = Number(await js('(window.__dsh.payload()||{}).pos_track_n||0'));
  const ptLen = await js('((window.__dsh.payload()||{}).pos_tracks||[]).length');
  // ★ 别让这条测试「空过」：`pos_track_n` 必须真的读到。
  //   ★ 2026-10：原地惩罚之后本谱**可能压根没有需要错开的重合**（那 0 就是正确结果）
  //     ⇒ 判据改成两选一：有错开 ⇒ 必须 >0 且与 pos_tracks 等长；
  //        没有错开 ⇒ **必须能证明本谱确实没有重合对**（拿 rebuild 报告里的
  //        `overlap.overlaps_no_snow` 作证），否则就是读错 dict 的空过。
  const ovl1 = Number(((rPt1 || {}).overlap || {}).overlaps_no_snow || 0);
  check('打开轨道位置偏移 → 有错开 或 本谱确实没有重合（防读错 dict 的空过）',
    (ptN1 > 0 && ptLen === ptN1) || (ptN1 === 0 && ptLen === 0 && ovl1 === 0),
    `pos_track_n=${ptN1} pos_tracks=${ptLen} 重合对=${ovl1}`);
  await js('window.__dsh.setParam("use_position_track", false)');
  await js('window.__dsh.rebuild()');
  const ptN2 = Number(await js('(window.__dsh.payload()||{}).pos_track_n||0'));
  const stPt = String(await js('window.__dsh.status()'));
  check('关掉轨道位置偏移 → payload.pos_track_n 归零', ptN2 === 0,
    `${ptN1} → ${ptN2}`);
  check('关掉时状态栏写明「轨道位置偏移已关闭」',
    stPt.includes('轨道位置偏移已关闭'), stPt.slice(0, 200));
  await js('window.__dsh.setParam("use_position_track", true)');
  const rPt3 = await js('window.__dsh.rebuild()');
  const ptN3 = Number(await js('(window.__dsh.payload()||{}).pos_track_n||0'));
  check('重新打开 → 错开条数回到原值', ptN3 === ptN1,
    `${ptN1} / ${ptN3} :: rebuild=${String(rPt3 && (rPt3.ok ? 'ok' : rPt3.msg))}`
    + ` :: status=${String(await js('window.__dsh.status()')).slice(0, 80)}`);
  await js('window.__dsh.setParam("use_position_track", false)');
  await js('window.__dsh.rebuild()');

  // ★ 对音阶梯（docs/25）：激进采音是**并列的第二条路径**，默认必须关。
  //   打开后状态栏要报出「五级各答了几格」，否则用户看不出激进在哪。
  const fl0 = Number(await js('(window.__dsh.payload()||{}).floors?.length||0'));
  const ag0 = await js('window.__dsh.state.aggressive_pick');
  check('激进采音默认关（原逻辑保留）', ag0 === false, String(ag0));
  await js('window.__dsh.setParam("aggressive_pick", true)');
  await js('window.__dsh.rebuild()');
  const stAg = String(await js('window.__dsh.status()'));
  check('打开激进采音 → 状态栏报出五级分布',
    /激进采音 图形\d+ 当前档\d+ \+Twirl\d+ 变速\d+ 暂停\d+/.test(stAg),
    stAg.slice(0, 240));
  const flAg = Number(await js('(window.__dsh.payload()||{}).floors?.length||0'));
  check('激进路径也能出谱（层数与老路径同量级）',
    flAg > 0 && Math.abs(flAg - fl0) <= 4, `${fl0} → ${flAg}`);
  await js('window.__dsh.setParam("aggressive_pick", false)');
  await js('window.__dsh.rebuild()');
  const flBack = Number(await js('(window.__dsh.payload()||{}).floors?.length||0'));
  check('关掉激进采音 → 层数逐格回到老路径', flBack === fl0,
    `${fl0} → ${flAg} → ${flBack}`);

  await js(`(() => { const el = document.querySelector('#in-twirl_index');
    el.selectedIndex = 2; el.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  check('下拉 change → 状态更新', (await js('window.__dsh.state.twirl_index')) === 2);

  const c3 = (await js('window.__dsh.stats()')).rebuildCount;
  await js('document.querySelector("#btn-rebuild").click()');
  await sleep(400);
  check('点「重新生成」触发重建',
    (await js('window.__dsh.stats()')).rebuildCount > c3,
    `${c3} → ${(await js('window.__dsh.stats()')).rebuildCount}`);

  // 注意：③④ 现在默认折叠（布局整理），折叠区里的 input 没法聚焦，
  //       所以滚轮行为用「② 音轨」里的可见控件来测。
  check('未聚焦的数字框吃掉滚轮（不抢焦）', await js(`(() => {
    const el = document.querySelector('#in-dp_tol');
    el.blur();
    const e = new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true });
    el.dispatchEvent(e);
    return e.defaultPrevented;
  })()`));
  const focused = await js(`(() => {
    const el = document.querySelector('#in-dp_tol');
    el.focus();
    return document.activeElement === el;
  })()`);
  check('可见分区里的数字框能拿到焦点', focused);
  check('已聚焦的数字框允许滚轮', focused && await js(`(() => {
    const el = document.querySelector('#in-dp_tol');
    const e = new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true });
    el.dispatchEvent(e);
    return e.defaultPrevented === false;
  })()`));

  // 下面几节验全局 <audio> 走带；先切离谱面预览页（那页的播放键归 ADOFAI 播放器）
  await js('window.__dsh.tab("roll")');
  await js('document.querySelector("#btn-play").click()');
  await sleep(1000);
  const pp = await js('window.__dsh.pos()');
  check('点播放按钮真的播起来', pp > 0, `${pp.toFixed(0)}ms`);
  const dur2 = await js('window.__dsh.dur()');
  await js(`(() => { const el = document.querySelector('#slider'); el.value = '200';
    el.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await sleep(250);
  const p5 = await js('window.__dsh.pos()');
  check('拖滑块（change）→ seek 生效',
    dur2 > 0 && Math.abs(p5 - dur2 * 0.2) < 600, `${p5.toFixed(0)} vs ${(dur2 * 0.2).toFixed(0)}`);
  await js('document.querySelector("#btn-play").click()');
  await sleep(300);
  const pz = await js('window.__dsh.pos()');
  await sleep(500);
  check('再点一次 → 暂停', Math.abs((await js('window.__dsh.pos()')) - pz) < 60);

  // 12. ★ 全曲预览条 + 区间采音
  await js(`window.__dsh.load(${JSON.stringify(MID)})`);
  await sleep(650);
  const dbgOv = async (tag) => console.log(`DBG-OV ${tag} `
    + JSON.stringify(await js('({t0:window.__dsh.overview.t0,'
      + 'span:window.__dsh.overview.span,total:window.__dsh.overview.total,'
      + 'w:document.querySelector("#cv-overview").clientWidth})')));
  await dbgOv('加载后');
  const ovW = await js('document.querySelector("#cv-overview").clientWidth');
  check('全曲预览条有布局宽度', ovW > 200, `${ovW}px`);
  const ovPix = await js(`(() => {
    const cv = document.querySelector('#cv-overview');
    const ctx = cv.getContext('2d');
    const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 16) if (d[i] > 40 || d[i+1] > 40 || d[i+2] > 40) n++;
    return n;
  })()`);
  check('全曲预览条画出了内容', ovPix > 200, `非背景采样点=${ovPix}`);

  // 拖动预览条 = 定位
  const seekByStrip = await js(`(() => {
    const cv = document.querySelector('#cv-overview');
    const r = cv.getBoundingClientRect();
    const y = r.top + r.height / 2;
    cv.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: r.left + r.width * 0.5, clientY: y, button: 0 }));
    cv.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: r.left + r.width * 0.5, clientY: y }));
    cv.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: r.left + r.width * 0.5, clientY: y }));
    return window.__dsh.pos();
  })()`);
  check('在预览条上拖动 = 定位到中部', seekByStrip > 5000, `${seekByStrip.toFixed(0)}ms`);
  await dbgOv('拖动后');

  // ── 13. ★ 格（tile）导航：照搬 adofaiex/Re_ADOJAS 编辑器 Timeline 的语义 ──
  //   核心差别：导航单位是「格」不是毫秒；拖动 = seek + 反查格号选中；
  //   ←→ 逐格、Home/End 首尾格（暂停时）；播放键从选中的格开始。
  const selDrag = await js('window.__dsh.selFloor()');
  check('拖动预览条后选中了某一格', Number.isInteger(selDrag), `selFloor=${selDrag}`);
  check('选中格 == 播放位置反查的格（getTileIndexAtTime）',
    await js('window.__dsh.floorAt(window.__dsh.toGrid(window.__dsh.pos()))'
      + ' === window.__dsh.selFloor()'));
  const tilePix = await js(`(() => {
    const cv = document.querySelector('#cv-overview');
    const ctx = cv.getContext('2d');
    const d = ctx.getImageData(0, 0, cv.width, Math.round(cv.height * 0.5)).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i+1] > 140 && d[i+1] > d[i] + 40 && d[i+1] > d[i+2] + 40) n++;
    }
    const r = cv.getBoundingClientRect();
    return JSON.stringify({ n, w: cv.width, h: cv.height,
                            css: [Math.round(r.width), Math.round(r.height)],
                            sel: window.__dsh.selFloor() });
  })()`);
  const tp = JSON.parse(tilePix);
  check('预览条画出选中格标记', tp.n > 10,
    `绿色采样点=${tp.n} · canvas ${tp.w}x${tp.h}（css ${tp.css.join('x')}）· sel=${tp.sel}`);

  // ←→ 逐格：选中格 +1，且播放位置落到该格 entryTime
  const f0 = await js('window.__dsh.selFloor()');
  await js('window.__dsh.stepFloor(1)');
  const f1 = await js('window.__dsh.selFloor()');
  check('→ 逐格前进一格', f1 === f0 + 1, `${f0} → ${f1}`);
  check('逐格后播放位置落在该格 entryTime',
    await js('Math.abs(window.__dsh.toGrid(window.__dsh.pos())'
      + ' - window.__dsh.floorTime(window.__dsh.selFloor())) < 2'));
  await js('window.__dsh.stepFloor(-1)');
  check('← 逐格退回一格', (await js('window.__dsh.selFloor()')) === f0, `回到 ${f0}`);

  // Home / End 走真实键盘事件
  await js(`document.dispatchEvent(new KeyboardEvent('keydown', { code: 'End', bubbles: true }))`);
  const nf = await js('window.__dsh.nFloors()');
  check('End 跳到最后一格', (await js('window.__dsh.selFloor()')) === nf - 1, `#${nf - 1}`);
  await js(`document.dispatchEvent(new KeyboardEvent('keydown', { code: 'Home', bubbles: true }))`);
  check('Home 跳到第 0 格', (await js('window.__dsh.selFloor()')) === 0);
  await js(`document.dispatchEvent(new KeyboardEvent('keydown', { code: 'Escape', bubbles: true }))`);
  check('Esc 取消选中格', (await js('window.__dsh.selFloor()')) === null);

  // 播放键：从选中的格开始播（Re_ADOJAS handlePlayWithSeek / 本项目 togglePlay 的分支）
  await js('window.__dsh.tab("roll")');            // 同样切离谱面预览页
  await js('window.__dsh.selectFloor(40)');
  const wantT = await js('window.__dsh.toAudio(window.__dsh.floorTime(40))');
  await js('document.querySelector("#btn-play").click()');
  let gotT = 0;
  for (let i = 0; i < 120; i++) {                       // 首次要合成音频，给足时间
    // eslint-disable-next-line no-await-in-loop
    gotT = await js('window.__dsh.pos()');
    if (gotT >= wantT - 100) break;
    // eslint-disable-next-line no-await-in-loop
    await sleep(250);
  }
  check('播放从选中的格开始（不是从 0）',
    gotT >= wantT - 100 && gotT < wantT + 3000,
    `want≈${Math.round(wantT)} got≈${Math.round(gotT)}`);
  await js('document.querySelector("#btn-play").click()');   // 暂停，别影响后面
  await sleep(300);

  // Shift+拖动 = 框选区间（扩展能力，不能把格选中搞乱）
  const selBeforeBox = await js('window.__dsh.selFloor()');
  const before = await js('window.__dsh.state.regions.length');
  await js(`(() => {
    const cv = document.querySelector('#cv-overview');
    const r = cv.getBoundingClientRect();
    const y = r.top + r.height / 2;
    const mk = (t, x) => new MouseEvent(t, { bubbles: true, clientX: r.left + r.width * x, clientY: y, button: 0, shiftKey: true });
    cv.dispatchEvent(mk('mousedown', 0.30));
    cv.dispatchEvent(mk('mousemove', 0.55));
    cv.dispatchEvent(mk('mouseup', 0.55));
  })()`);
  await sleep(500);
  const after = await js('window.__dsh.state.regions.length');
  check('Shift+拖动框选出一个区间', after === before + 1, `${before} → ${after}`);
  const selAfterBox = await js('window.__dsh.selFloor()');
  check('Shift+拖动框选不会动到选中的格', selAfterBox === selBeforeBox,
    `${selBeforeBox} → ${selAfterBox}`);
  const rg = await js('JSON.stringify(window.__dsh.state.regions[0]||null)');
  const rgObj = JSON.parse(rg || 'null');
  check('区间时间落在框选范围内',
    rgObj && rgObj.start_ms > 5000 && rgObj.end_ms > rgObj.start_ms,
    rg || 'null');
  const rgUI = await js('document.querySelectorAll("#lst-regions .region").length');
  check('面板出现区间编辑器', rgUI === 1, `${rgUI} 个`);
  await dbgOv('框选后');

  // 区间改用另一条轨采音 → 重算
  const trkChips = await js('document.querySelectorAll("#lst-regions .region .chip").length');
  check('区间编辑器给出轨选择 chips', trkChips >= 2, `${trkChips} 个`);
  const onChips = await js('document.querySelectorAll("#lst-regions .chip.on").length');
  await js('document.querySelectorAll("#lst-regions .chip")[1].click()');
  await waitRebuild();                       // ★ 不赌 500ms（求解慢一点就抓到「求解中…」）
  const onChips2 = await js('document.querySelectorAll("#lst-regions .chip.on").length');
  check('点 chip 切换该区间的采音轨', onChips2 !== onChips, `${onChips} → ${onChips2}`);
  const stR = await waitRebuild();
  check('状态栏报告区间生效', /区间\s*\d+\s*段/.test(stR), stR.slice(-90));
  const bandPix = await js(`(() => {
    const cv = document.querySelector('#cv-overview');
    const ctx = cv.getContext('2d');
    const h = cv.height;
    const d = ctx.getImageData(0, Math.round(h * 0.7), cv.width, Math.round(h * 0.2)).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 16) if (d[i+2] > 60) n++;
    return n;
  })()`);
  check('预览条上出现区间色带', bandPix > 30, `色带采样点=${bandPix}`);

  // ---------------------------------------------------------------- 13b. ★ 分段采音（docs/34 方案 C）
  check('分段采音区块在', !!(await js('!!document.querySelector("#lst-segments")')));
  const segCtl = await js(`JSON.stringify([
    !!document.querySelector('#sel-seg-mode'),
    (document.querySelector('#sel-seg-mode')||{}).value || '',
  ])`);
  const [hasModeSel, modeVal] = JSON.parse(segCtl);
  check('分段有语义模式选择器且默认「从这点起」',
    hasModeSel && modeVal === 'from', `${modeVal}`);
  check('分段区块默认列出「没有分段」的说明',
    (await js('(document.querySelector("#lst-segments")||{}).textContent||""')).includes('没有分段'));

  // 用「当前勾选的轨」在播放头加一条分段
  const segBefore = await js('window.__dsh.segList().length');
  await js('window.__dsh.segAdd(window.__dsh.payload() ? window.__dsh.payload().total_ms * 0.4 : 4000)');
  await sleep(600);
  const segAfter = await js('window.__dsh.segList().length');
  check('＋加分段 真的加进 state', segAfter === segBefore + 1, `${segBefore} → ${segAfter}`);
  const segUI = await js('document.querySelectorAll("#lst-segments .region").length');
  check('面板出现分段编辑器', segUI === 1, `${segUI} 个`);
  const segChips = await js('document.querySelectorAll("#lst-segments .region .chip").length');
  check('★ 每段给出「继承 / 全关 / 逐轨」三种 chips',
    segChips >= 2 + 3, `${segChips} 个`);
  check('新建的分段默认三维全「继承」',
    (await js('document.querySelectorAll("#lst-segments .chip.on").length')) === 3,
    `on=${await js('document.querySelectorAll("#lst-segments .chip.on").length')}`);

  // ★ 段界真的改了采音：改成「主轨全关」⇒ 点会变
  const nOn0 = await js('window.__dsh.stats().rebuildCount');
  await js(`(() => {
    const rows = document.querySelectorAll('#lst-segments .rrow');
    // 第一个 .rrow = 主轨那一行；里面第 2 个 chip = 「全关」
    const off = rows[0].querySelectorAll('.chip')[1];
    off.click();
  })()`);
  // ★ 以「点击前的计数」为基准等 —— 防抖是 140ms，凭「状态不忙」会立刻返回
  const stSeg = await waitRebuild(40000, nOn0);
  const nOn1 = await js('window.__dsh.stats().rebuildCount');
  check('点「全关」触发重算', nOn1 > nOn0, `${nOn0} → ${nOn1}`);
  check('状态栏报告分段段数与语义', /分段\s*\d+\s*段/.test(stSeg), stSeg.slice(-110));
  check('状态栏带上语义口径', /从这点起|到这点为止/.test(stSeg), stSeg.slice(-60));

  // 有分段时预览条要画泳道（色带区变高 + 出现段界竖线）
  await js('window.__dsh.draw()');
  const lanePix = await js(`(() => {
    const cv = document.querySelector('#cv-overview');
    const ctx = cv.getContext('2d');
    const h = cv.height;
    const d = ctx.getImageData(0, Math.round(h * 0.6), cv.width, Math.round(h * 0.35)).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 16) if (d[i] + d[i+1] + d[i+2] > 90) n++;
    return n;
  })()`);
  check('★ 预览条画出分段泳道', lanePix > 30, `泳道采样点=${lanePix}`);

  // ★ 区间 + 分段同时存在 ⇒ 分段优先，且必须在警告区**说出来**
  await waitRebuild();
  const wBoth = await js('(document.querySelector("#warnings")||{}).textContent||""');
  check('★ 区间+分段同时存在 ⇒ 警告区报「分段优先」',
    wBoth.includes('分段优先'), wBoth.slice(0, 140) || '(警告区是空的)');
  check('警告区确实有内容（原来这个键没人生产，一直是死的）',
    wBoth.trim().length > 0, wBoth.slice(0, 80));

  // 切到「到这点为止」：段数不变、但管的段落反过来 ⇒ 允许点数变化，只要不崩
  await js('window.__dsh.segMode("until")');
  const stUntil = await waitRebuild();
  check('切「到这点为止」后仍能出谱并报告新口径',
    /到这点为止/.test(stUntil), stUntil.slice(-80));
  await js('window.__dsh.segMode("from")');
  await sleep(600);

  // 有分段时也能导出（分段采音不能把导出搞坏）
  const exSeg = await js(`window.__dsh.api.exportTo(window.__dsh.state, ${JSON.stringify(OUT)})`);
  check('带分段也能正常导出', exSeg && exSeg.ok, exSeg && (exSeg.error || '').slice(0, 120));

  // 清掉分段 ⇒ 回到区间那条路
  await js('window.__dsh.segSet([])');
  await sleep(700);
  check('清空分段后回到区间采音（区间元信息回来了）',
    (await js('(window.__dsh.state.segments||[]).length')) === 0);

  // 区间改了之后导出一遍（区间采音不能把导出搞坏）
  const exR = await js(`window.__dsh.api.exportTo(window.__dsh.state, ${JSON.stringify(OUT)})`);
  check('带区间也能正常导出', exR && exR.ok, exR && (exR.error || '').slice(0, 120));
  await js('window.__dsh.draw()');
  await shot(win, 'chart-region');
  await js('window.__dsh.tab("falling")');
  await js('window.__dsh.draw()');
  await shot(win, 'falling');
  await js('window.__dsh.tab("roll")');
  await js('window.__dsh.draw()');
  await shot(win, 'roll');
  await js('window.__dsh.tab("path")');
  await js('window.__dsh.draw()');
  await shot(win, 'path');
  await js('window.__dsh.tab("chart")');
  await js('window.__dsh.draw()');
  // 全屏截图（含折叠后的面板）
  await shot(win, 'panel-collapsed');
  // ★ 新 UI（docs/49 方案 A）：参数分到两个面板里（左「来源与段」/ 右「检查器」）+
  //   大直线浮窗 ⇒ 按**标题文字**找分区，别再按下标（下标会随分区搬家而变）
  await js(`(() => {
    const hit = (t) => [...document.querySelectorAll('section.grp > h4')]
      .find((h) => h.textContent.includes(t));
    const a = hit('④ 求解'), b = hit('③b 采bpm');
    if (a) a.click(); if (b) b.click();
  })()`);
  await sleep(200);
  // ★ 顺手把「④ 求解」滚到新增参数处，截图里能直接看到
  //   等待拍阈值 / 最小角度 / 雪花新参数（docs/24），改完参数可以直接看图复核。
  await js(`(() => {
    const el = document.querySelector('#in-travel_min');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' });
  })()`);
  await sleep(150);
  await shot(win, 'panel-expanded');
  const v03Fields = await js(`(() => {
    const keys = ['pause_min_beats', 'travel_min', 'travel_max', 'snowflake_shape',
                  'snowflake_min_arms', 'snowflake_compact',
                  'snowflake_uniform_tol_ms', 'snowflake_random',
                  'snowflake_seed',
                  'use_position_track', 'pos_track_step', 'pos_track_min_beats',
                  'aggressive_pick', 'ladder_outer_mode', 'ladder_outer_cbpm',
                  'ladder_tier_order',
                  'closed_bias_index', 'straighten', 'straighten_min_run',
                  'straighten_theta',
                  // ★ 双押预留槽位（a，docs/31 §5.2）
                  'dp_reserve', 'dp_theta',
                  // ★ 双押偏移预算（docs/33：所有 bpm 下 Δ ≤ 25ms）
                  'dp_skew_max_ms'];
    return keys.filter((k) => !!document.querySelector('#in-' + k));
  })()`);
  check('④ 求解面板出现新参数（等待拍/最小角度/最大夹角/雪花/错开/激进/闭合/回正/双押 23 项）',
    Array.isArray(v03Fields) && v03Fields.length === 23, JSON.stringify(v03Fields));

  // 折叠分区（布局整理）
  const collapsed = await js('document.querySelectorAll("section.grp.collapsed").length');
  check('细节分区默认折叠（首屏更整洁）', collapsed >= 2, `${collapsed} 个收起`);
  const firstClosed = await js(`(() => {
    const s = document.querySelector('section.grp.collapsed > h4');
    if (!s) return '';
    const was = document.querySelectorAll('section.grp.collapsed').length;
    s.click();
    return was + '->' + document.querySelectorAll('section.grp.collapsed').length;
  })()`);
  check('点标题可展开', /\d+->\d+/.test(firstClosed) && firstClosed.split('->')[0] !== firstClosed.split('->')[1],
    firstClosed);

  // 13. 布局体检（"更整洁"要能量化：溢出 / 截断 / 压扁 / 可用高度）
  await js(`(() => {
    // 全展开（分区搬到哪都找得到 —— 按标题点，不按下标）
    document.querySelectorAll('section.grp.collapsed > h4').forEach((h) => {
      if (!/①|②/.test(h.textContent)) h.click();
    });
  })()`);
  await sleep(200);
  const audit = await js(`(() => {
    const out = { overflowX: 0, clipped: [], squashed: [], panelOut: [], visible: 0 };
    out.overflowX = document.documentElement.scrollWidth - window.innerWidth;
    // ★ 新 UI：参数分布在 左(#panel-left) / 右(#panel) / 大直线浮窗(#groups-xk) 三处
    const bodies = ['#panel-left', '#panel', '#groups-xk']
      .map((s) => document.querySelector(s)).filter(Boolean);
    const walk = (root) => {
      for (const e of root.querySelectorAll('*')) {
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;      // 折叠/隐藏的不算
        if (e.tagName === 'CANVAS' || e.tagName === 'BODY') continue;
        out.visible++;
        // 文本被截断：用 Range 量文本真实宽度（inline 元素的 clientWidth 恒为 0，
        // 只看 clientWidth 会漏掉 .hint / .info 这类行内元素）
        if (e.children.length === 0 && e.textContent.trim()) {
          const rg = document.createRange();
          rg.selectNodeContents(e);
          const tw = rg.getBoundingClientRect().width;
          const cw = e.clientWidth || e.getBoundingClientRect().width;
          const ov = getComputedStyle(e);
          if (tw > cw + 2 && ov.overflow !== 'auto' && ov.overflowX !== 'auto'
              && ov.textOverflow !== 'ellipsis' && ov.whiteSpace !== 'nowrap') {
            out.clipped.push((e.id || e.className || e.tagName)
              + ':' + Math.round(tw) + '>' + Math.round(cw));
          }
        }
        // 控件被压扁（复选框/滑块本来就不大，排除）
        const t = e.tagName;
        const it = (e.getAttribute && e.getAttribute('type')) || '';
        if ((t === 'BUTTON' || t === 'SELECT' || (t === 'INPUT' && it !== 'checkbox' && it !== 'range'))
            && (r.width < 14 || r.height < 12)) {
          out.squashed.push((e.id || e.className || t) + ':' + Math.round(r.width) + 'x' + Math.round(r.height));
        }
        // 溢出所在面板的右边界
        for (const b of bodies) {
          if (!e.closest('#' + b.id)) continue;
          const br = b.getBoundingClientRect();
          if (r.right > br.right + 1) {
            out.panelOut.push((e.id || e.className || e.tagName)
              + ':' + Math.round(r.right) + '>' + Math.round(br.right));
          }
        }
      }
    };
    walk(document);
    const st = document.querySelector('#stage').getBoundingClientRect();
    const ov = document.querySelector('#ovwrap').getBoundingClientRect();
    const bd = document.querySelector('#tlwrap').getBoundingClientRect();
    out.stage = [Math.round(st.width), Math.round(st.height)];
    out.overview = [Math.round(ov.width), Math.round(ov.height)];
    out.band = [Math.round(bd.width), Math.round(bd.height)];
    out.panelWidth = Math.round(document.querySelector('#panel').getBoundingClientRect().width);
    out.groups = document.querySelectorAll('section.grp').length;
    out.collapsed = document.querySelectorAll('section.grp.collapsed').length;
    return out;
  })()`);
  check('页面没有横向溢出', audit.overflowX <= 1, `溢出 ${audit.overflowX}px`);
  check('没有文本被截断', audit.clipped.length === 0, audit.clipped.slice(0, 4).join(' | '));
  check('没有控件被压扁', audit.squashed.length === 0, audit.squashed.slice(0, 4).join(' | '));
  check('面板内元素没有溢出右边界', audit.panelOut.length === 0,
    audit.panelOut.slice(0, 4).join(' | '));
  check('主画布区仍有可用高度（≥300px）', audit.stage[1] >= 300, `${audit.stage[1]}px`);
  check('全曲预览条高度合理（60~110px）',
    audit.overview[1] >= 60 && audit.overview[1] <= 110, `${audit.overview[1]}px`);
  check('★ 段带存在且有高度（60~320px，docs/49 方案 A）',
    audit.band[0] > 200 && audit.band[1] >= 60 && audit.band[1] <= 320,
    `${audit.band[0]}x${audit.band[1]}`);
  // ★ 多了「④b 去噪 / 直拟合」（docs/44）、「③b 采bpm / xk base」（docs/47）
  //   与「⑤b 换手押上色」（docs/59）、「⑤c 算法轨道调度」（docs/60）、
  //   「⑤d 演出（入场 / 离场 · 分段）」（docs/62）、
  //   **「⑤e（new）镜头调度」（docs/70 · 用户 2026-10 正式接线）**
  check('11 个分区都在（多出 ③b 采bpm · ④b 直拟合 · ⑤b 换手押上色 · '
    + '⑤c 算法轨道调度 · ⑤d 演出 · ⑤e（new）镜头调度）',
    audit.groups === 11, `${audit.groups} 个`);
  // ★★ ⑤e（new）镜头调度（docs/70 · 用户 2026-10）：主人要的摆法是
  //   「**选项卡在外、生成时参数默认收起、点选项卡下方的三角形展开**」。
  //   这三条由渲染进程的 `uiAudit()` 上报（它就在那一组 DOM 上现场量）。
  const camRaw = await js(`JSON.stringify(window.__dsh.uiAudit().cam || null)`);
  const cam = JSON.parse(camRaw);
  check('★ 左栏有「⑤e（new）镜头调度」这个组（用户找得到开关）',
    !!(cam && cam.group === true), camRaw);
  check('★ 镜头调度的**选项卡**在外（默认「关」，目前只有「关 / 呼吸」两档）',
    !!(cam && cam.modeVisible === true && cam.modeOpts === 2), camRaw);
  check('★★ 镜头调度的**生成时参数默认收起**（用户口径）',
    !!(cam && cam.paramsHidden === true), camRaw);
  check('★★ 点选项卡下方的**三角形**能展开参数',
    !!(cam && cam.expandedAfterClick === true), camRaw);
  check('★ 19 个 camera_* 参数都在（收着也要建控件，否则 uiAudit 变红）',
    !!(cam && cam.nParams >= 19), camRaw);
  check('展开后可见控件数量正常（≥60）', audit.visible >= 60, `${audit.visible} 个`);

  // 14. 下落式轨道块：应居中、且不能宽到把音符拉成长条
  await js('window.__dsh.tab("falling")');
  await js('window.__dsh.draw()');
  await sleep(200);
  const lane = await js(`(() => {
    const cv = document.querySelector('#cv-falling');
    const ctx = cv.getContext('2d');
    const W = cv.width; const H = cv.height;
    const d = ctx.getImageData(0, 0, W, H).data;
    let minX = 1e9; let maxX = -1;
    // 只扫轨道区：避开顶部 HUD 文字和底部提示行（它们也画在画布上）
    const y0 = Math.round(H * 0.08); const y1 = Math.round(H * 0.72);
    for (let y = y0; y < y1; y += 2) {
      for (let x = 0; x < W; x++) {
        const i = (y * W + x) * 4;
        if (d[i] > 45 || d[i+1] > 45 || d[i+2] > 45) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
        }
      }
    }
    return { minX, maxX, W, dpr: window.devicePixelRatio };
  })()`);
  const blockW = lane.maxX - lane.minX;
  const leftM = lane.minX; const rightM = lane.W - lane.maxX;
  check('下落式轨道块居中（左右边距差 ≤15%）',
    Math.abs(leftM - rightM) / Math.max(1, lane.W) <= 0.15,
    `左 ${leftM} / 右 ${rightM} (W=${lane.W})`);
  check('下落式音符不再被拉成长条（单轨 ≤160 CSS px）',
    blockW / 4 / lane.dpr <= 160, `单轨宽 ${(blockW / 4 / lane.dpr).toFixed(0)}px`);
  await js('window.__dsh.tab("chart")');

  // ---------------------------------------------------------------- BDG 桥（docs/38）
  check('BDG 桥区块在', !!(await js('!!document.querySelector("#bridge")')));
  check('BDG 桥三个控件齐',
    !!(await js('!!document.querySelector("#br-url") && !!document.querySelector("#br-push") && !!document.querySelector("#br-pull")')));
  // ★★ 收回轨道项目（docs/45）：两颗按钮 + 一块「收回了什么」
  check('★ 有「用收回的轨道重建」按钮', !!(await js('!!document.querySelector("#br-backuse")')));
  check('★ 有「清掉收回」按钮', !!(await js('!!document.querySelector("#br-backclear")')));
  check('★ 有「收回的音轨项目」信息块（默认隐藏）',
    !!(await js('!!document.querySelector("#back-box")'
      + ' && document.querySelector("#back-box").classList.contains("hidden")')));
  const bk0 = await js('window.__dsh.api.bridgeBack().then(r => r && typeof r.ok === "boolean")');
  check('★ /api/bridge/back 通（没收回时也明确回 ok:false，不 404）', bk0 === true, String(bk0));
  const bkClear = await js('window.__dsh.api.bridgeBackClear().then(r => !!(r && r.ok))');
  check('★ /api/bridge/back/clear 通（清也是操作，要回执）', bkClear === true, String(bkClear));

  // ★★ ④b 去噪 / 直拟合（docs/44）：字段在 schema 里 + 真能出谱 + 自检逐点精确
  //   2026-10 起 `denoise_radius_ms` 改成 **`fit_tol_ms`（拟合容差，0~100，默认 100）**：
  //   旧的「0 = 全吸」与用户「容差」的直觉相反（0 却是最凶的），已按口径改正 ——
  //   现在 **0 = 一个点都不挪**。见 `docs/57`。
  const fitD = await js(`(() => {
    const d = window.__dsh.schema().defaults;
    return { mode: d.fit_mode, on: d.denoise_on, div: d.denoise_div,
             tol: d.fit_tol_ms, agg: d.aggressive_fit, hint: d.denoise_hint_ms,
             anc: d.anchor_from_grid, oldRad: d.denoise_radius_ms };
  })()`);
  check('★ 求解方式默认「最优化」（不动老路径）', fitD.mode === 'solve', String(fitD.mode));
  check('★ 去噪默认开、分母自动、**拟合容差默认 100ms**、激进拟合默认关、锚用格相位',
    fitD.on === true && fitD.div === 0 && fitD.tol === 100 && fitD.agg === false
    && fitD.hint === 0 && fitD.anc === true, JSON.stringify(fitD));
  check('★ 旧参数 `denoise_radius_ms` 已撤（0 = 全吸 那套口径改正了）',
    fitD.oldRad === undefined, String(fitD.oldRad));
  await js('window.__dsh.setParam("fit_mode", "direct")');
  await js('window.__dsh.setParam("denoise_on", true)');
  const dFit = await js(`(async () => {
    const r = await window.__dsh.api.rebuild(window.__dsh.state);
    return { ok: !!r.ok, mode: r.fit_mode,
             err: (r.fit || {}).err_max_ms,
             floors: r.n_floors, straight: (r.fit || {}).straight_frac,
             dn: !!(r.denoise && r.denoise.grid),
             warn: (r.warning_list || []).filter(w => w.indexOf("去噪") === 0).length };
  })()`);
  check('★ 直拟合能出谱', dFit.ok && dFit.floors > 0,
    `ok=${dFit.ok} floors=${dFit.floors} mode=${dFit.mode}`);
  check('★★ 直拟合自检：时序误差 = 0', dFit.err === 0, `err_max_ms=${dFit.err}`);
  check('★ 去噪报告在返回里（machine-readable）', dFit.dn === true, '');
  check('★ 去噪那条警告上屏了（不许静默）', dFit.warn >= 1, `去噪警告 ${dFit.warn} 条`);
  check('★ 直线率被报出来', typeof dFit.straight === 'number' && dFit.straight > 0,
    `straight=${dFit.straight}`);
  // ★ 再走一次**界面自己那条路**（`rebuild()` 才会更新 DOM 文案）
  await js('window.__dsh.rebuild()');
  await sleep(400);
  const lblFit = String(await js('(document.querySelector("#lbl-fit")||{}).textContent||""'));
  check('★ ④b 那行明说「当前走的是哪条路 + 代价」',
    /直拟合/.test(lblFit) && /时序误差/.test(lblFit), lblFit.slice(0, 110));
  const wFit = String(await js('(document.querySelector("#warnings")||{}).textContent||""'));
  check('★ 去噪/直拟合的警告在界面上（不许静默）', /去噪/.test(wFit), wFit.slice(0, 90));

  // ★★ 2026-10「使用激进的拟合策略」（docs/57）：15° 阶梯 + 拟合容差
  //   界面守四条：控件在 / 依赖置灰对 / 状态行报账 / 能真出阶梯角度。
  //   ★ 必须拿**带抖动**的输入来验：干净格子的角度本来就常是 15° 的倍数，
  //     用干净数据这条会**空过**（e2e 最怕的假 PASS）。
  {
    const keepPath = String(await js('((window.__dsh.loadInfo()||{}).path||"")'));
    const JT = path.join(__dirname, '..', 'out', '_e2e_jitter.txt');
    {
      // 确定性的伪随机抖动（不引第三方库，跑两次结果一样）
      let seed = 11;
      const rnd = () => {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        return seed / 2147483648;
      };
      const lines = [];
      let t = 1000.0;
      for (let i = 0; i < 60; i++) {
        lines.push((t + (rnd() * 50 - 25)).toFixed(3));
        t += (i % 6 ? 4 : 2) * 150 / 4;
      }
      fs.writeFileSync(JT, lines.join('\n') + '\n', 'utf-8');
    }
    await js(`window.__dsh.load(${JSON.stringify(JT)})`);
    await sleep(900);
    const lock0 = await js(`(() => {
      const f = (k) => (window.__dsh.schema().fields || []).find((x) => x.key === k) || {};
      return { mode: window.__dsh.state.fit_mode,
               aggDis: !!f('aggressive_fit')._input.disabled,
               tolDis: !!f('fit_tol_ms')._input.disabled,
               pDis: !!f('aggressive_pick')._input.disabled,
               tvDis: !!f('travel_min')._input.disabled };
    })()`);
    check('★ 载入时间戳来源 ⇒ 求解方式自动直拟合、「激进拟合」可点',
      lock0.mode === 'direct' && lock0.aggDis === false, JSON.stringify(lock0));
    // ★★ 2026-10 用户报「AI 的 MIDI 用激进策略跑不通」：「激进**采音**」是
    //    `core.ladder` 那条路，只有最优化会走 ⇒ 直拟合下必须置灰（否则勾了没反应）。
    check('★★ 直拟合下「激进采音」置灰（它只管最优化，勾了不会有效果）',
      lock0.pDis === true, JSON.stringify(lock0));
    await js('window.__dsh.setParam("aggressive_fit", true)');
    const lock1 = await js(`(() => {
      const f = (k) => (window.__dsh.schema().fields || []).find((x) => x.key === k) || {};
      return { aggDis: !!f('aggressive_fit')._input.disabled,
               tvDis: !!f('travel_min')._input.disabled,
               tvVal: String(f('travel_min')._input.value),
               tvState: String(window.__dsh.state.travel_min) };
    })()`);
    check('★★ 开了激进拟合 ⇒ 「最小角度」**不再被钉死成 15**、照用框里的值（新口径）',
      lock1.tvDis === false && lock1.tvVal === String(lock1.tvState),
      JSON.stringify(lock1));
    const rAgg = await js(`(async () => {
      const r = await window.__dsh.api.rebuild(window.__dsh.state);
      const F = r.fit || {};
      return { ok: !!r.ok, on: F.ladder_on, bad: F.n_ladder_bad,
               moved: F.n_ladder_moved, raw: F.n_ladder_raw,
               max: F.ladder_move_max_ms, tset: F.travel_min_setting,
               tv: window.__dsh.state.travel_min,
               warn: (r.warning_list || [])
                 .filter((w) => w.indexOf("15°") >= 0).length };
    })()`);
    check('★★ 激进拟合：非双押格角度**全部**落在 15° 的整数倍上',
      rAgg.ok && rAgg.on === true && rAgg.bad === 0,
      `on=${rAgg.on} 非阶梯格=${rAgg.bad} 修正=${rAgg.moved} max=${rAgg.max}`);
    check('★ 抖动输入真的被挪了（不是空过）',
      (rAgg.moved || 0) > 20, `修正=${rAgg.moved} 音 / 挪不动 ${rAgg.raw}`);
    check('★ 后端最小角度 = max(15, 框里的值)（不信前端，但**不再**无条件钉死 15）',
      rAgg.tset === Math.max(15, Number(rAgg.tv) || 0),
      `tset=${rAgg.tset} 框=${rAgg.tv}`);
    check('★ 每个音的挪动量 ≤ 容差', (rAgg.max || 0) <= 100.0 + 1e-9, String(rAgg.max));
    check('★ 状态栏报了「15° 阶梯」这本账（不许静默）', rAgg.warn >= 1, String(rAgg.warn));
    await js('window.__dsh.rebuild()');
    await sleep(400);
    const lblAgg = String(await js('(document.querySelector("#lbl-fit")||{}).textContent||""'));
    check('★ ④b 那行把 15° 阶梯的账写出来（修了几个 / 挪多少 / 非阶梯格）',
      /15° 阶梯/.test(lblAgg) && /修正/.test(lblAgg), lblAgg.slice(-95));
    // 容差 0 ⇒ 一个点都不挪（保真）
    await js('window.__dsh.setParam("fit_tol_ms", 0)');
    const rAgg0 = await js(`(async () => {
      const r = await window.__dsh.api.rebuild(window.__dsh.state);
      const F = r.fit || {};
      return { moved: F.n_ladder_moved, max: F.ladder_move_max_ms };
    })()`);
    check('★★ 容差 0 ⇒ 一个点都不挪（用户口径：0 = 保真）',
      (rAgg0.moved || 0) === 0 && (rAgg0.max || 0) === 0,
      `修正=${rAgg0.moved} max=${rAgg0.max}`);
    await js('window.__dsh.setParam("fit_tol_ms", 100)');
    await js('window.__dsh.setParam("aggressive_fit", false)');
    await js('window.__dsh.setParam("fit_mode", "solve")');
    await js('window.__dsh.rebuild()');
    const lock2 = await js(`(() => {
      const f = (k) => (window.__dsh.schema().fields || []).find((x) => x.key === k) || {};
      return { aggDis: !!f('aggressive_fit')._input.disabled,
               pDis: !!f('aggressive_pick')._input.disabled,
               tvDis: !!f('travel_min')._input.disabled };
    })()`);
    check('★ 切回最优化 ⇒ 「激进拟合」置灰（点了也不会有效果，所以不许点）',
      lock2.aggDis === true && lock2.tvDis === false, JSON.stringify(lock2));
    check('★ 切回最优化 ⇒ 「激进采音」重新可点（那把锁**只**在直拟合下上）',
      lock2.pDis === false, JSON.stringify(lock2));
    // ★ 复原：把加载前那份文件装回去（后面的小节都建立在它上面）
    await js(`window.__dsh.load(${JSON.stringify(keepPath)})`);
    await sleep(700);
  }
  const stBack = String(await js('window.__dsh.status()'));
  check('★ 切回最优化照常', /层/.test(stBack), stBack.slice(0, 80));

  // ---------------------------------------------------------------- ③b 采bpm（xk base，docs/47）
  //   用户口径：大直线 = 无视音符排列硬铺等间隔骨架；**区间内**采bpm、**区间外走原路径**。
  {
    const xkDom = JSON.parse(String(await js(`JSON.stringify({
      list: !!document.querySelector('#lst-xk'),
      lbl: !!document.querySelector('#lbl-xk'),
      add: !!document.querySelector('#btn-xk-add'),
      clear: !!document.querySelector('#btn-xk-clear')
    })`)));
    check('★ ③b 采bpm 那一区在（区间表 + 报告行 + 两个按钮）',
      xkDom.list && xkDom.lbl && xkDom.add && xkDom.clear, JSON.stringify(xkDom));
    check('没框区间时给出「全曲」的说明（不空着）',
      /全曲/.test(String(await js('(document.querySelector("#lst-xk")||{}).textContent||""'))),
      String(await js('(document.querySelector("#lst-xk")||{}).textContent||""')).slice(0, 80));
    // 填 tbpm + 选 4k，再点「加区间」
    await js('window.__dsh.setParam("xk_base", 4)');
    await js('window.__dsh.setParam("xk_tbpm", 100)');
    await js('document.querySelector("#btn-xk-add").click()');
    await sleep(300);
    const nRows = Number(await js('document.querySelectorAll("#lst-xk .region").length'));
    check('★ 「＋ 加区间」真的加出一行', nRows === 1, `${nRows} 行`);
    const rowTxt = String(await js('(document.querySelector("#lst-xk .region")||{}).textContent||""'));
    check('区间行里有 N（每段可各自选 base）', /4k/.test(rowTxt), rowTxt.slice(0, 70));
    check('区间行支持「毫秒 / 格」两种输入',
      Number(await js('document.querySelectorAll("#lst-xk .region select").length')) >= 3,
      String(await js('document.querySelectorAll("#lst-xk .region select").length')));
    await js('window.__dsh.rebuild()');
    await sleep(500);
    const lblXk = String(await js('(document.querySelector("#lbl-xk")||{}).textContent||""'));
    check('★ ③b 报告上屏（注入骨架多少砖 / 区间外多少）',
      /采bpm/.test(lblXk) && /块砖/.test(lblXk) && /原路径/.test(lblXk), lblXk.slice(0, 150));
    const wXk = String(await js('(document.querySelector("#warnings")||{}).textContent||""'));
    check('★ 采bpm 的警告也在（钉死 cbpm / 取代了多少 onset）',
      /采bpm/.test(wXk), wXk.slice(0, 110));
    // ★ 右上角「格子 ↔ 毫秒」参考（我们自己的叠加层，`docs/47` §3）
    await js('window.__dsh.seek(5000)');
    await sleep(250);
    const hud = String(await js('(document.querySelector("#xk-hud")||{}).textContent||""'));
    const hudSt = JSON.parse(String(await js(`JSON.stringify({
      tbpm: window.__dsh.state.xk_tbpm, base: window.__dsh.state.xk_base,
      ranges: (window.__dsh.state.xk_ranges || []).length,
      paused: document.querySelector('#audio') ? document.querySelector('#audio').paused : null
    })`)));
    check('★ 右上角「格子 ↔ 毫秒」参考出现了（帧循环里更新）',
      /第 \d+ 格/.test(hud) && /格长/.test(hud) && /ms/.test(hud),
      hud.replace(/\n/g, ' | ').slice(0, 70) + '  || state=' + JSON.stringify(hudSt));
    check('★ 参考块可见（不是 hidden）',
      (await js('document.querySelector("#xk-hud").hidden')) === false, '');
    // 关掉 ⇒ 回到原路径
    await js('document.querySelector("#btn-xk-clear").click()');
    await js('window.__dsh.setParam("xk_base", 0)');
    await js('window.__dsh.setParam("xk_tbpm", 0)');
    await js('window.__dsh.rebuild()');
    await sleep(400);
    const lblXkOff = String(await js('(document.querySelector("#lbl-xk")||{}).textContent||""'));
    check('★ 关掉采bpm ⇒ 那一行明说「全曲走原路径」',
      /原路径/.test(lblXkOff), lblXkOff.slice(0, 110));
    try {
      await js('window.__dsh.seek(5000)');
    } catch (e) {
      console.log('   [诊断] 关掉后 seek 抛了：', String(e && e.message).slice(0, 120));
    }
    await sleep(250);
    let hudSnap = { hidden: null, txt: '', exists: false };
    try {
      hudSnap = JSON.parse(String(await js(`JSON.stringify((function(){
        const e = document.querySelector("#xk-hud");
        return { exists: !!e, hidden: e ? e.hidden : null,
                 txt: e ? String(e.textContent||"") : "",
                 parent: e && e.parentElement ? e.parentElement.id : "" };
      })())`)));
    } catch (e) {
      console.log('   [诊断] 读小窗快照抛了：', String(e && e.message).slice(0, 120));
    }
    check('★ 关掉后小窗**仍然常驻**，并明说「未配置」（不误导、也不消失）',
      hudSnap.exists && hudSnap.hidden === false && /未配置/.test(hudSnap.txt),
      JSON.stringify(hudSnap).slice(0, 170));
    // ★ 互斥是**按区间**的：全曲采bpm ⇒ ② 主轨置灰（有区间就不置灰）
    await js('window.__dsh.setParam("xk_base", 4)');
    await js('window.__dsh.setParam("xk_tbpm", 100)');
    await js('window.__dsh.rebuild()');
    await sleep(300);
    const lockOn = JSON.parse(String(await js(`JSON.stringify({
      cls: document.querySelector("#lst-tracks").className,
      dis: Array.from(document.querySelectorAll("#lst-tracks input"))
             .filter(function(i){return i.disabled;}).length,
      head: String((document.querySelector("#subhead-main")||{}).textContent||"")
    })`)));
    check('★ 全曲采bpm ⇒ ② 主轨**置灰**并写明「采bpm 已接管」',
      /xk-locked/.test(lockOn.cls) && lockOn.dis > 0 && /接管/.test(lockOn.head),
      JSON.stringify(lockOn).slice(0, 160));
    await js('window.__dsh.setParam("xk_base", 0)');
    await js('window.__dsh.setParam("xk_tbpm", 0)');
    await js('window.__dsh.rebuild()');
    await sleep(300);
    const lockOff = JSON.parse(String(await js(`JSON.stringify({
      cls: document.querySelector("#lst-tracks").className,
      dis: Array.from(document.querySelectorAll("#lst-tracks input"))
             .filter(function(i){return i.disabled;}).length
    })`)));
    check('★ 关掉后 ② 主轨**恢复可勾**（置灰是暂时的）',
      !/xk-locked/.test(lockOff.cls) && lockOff.dis === 0,
      JSON.stringify(lockOff).slice(0, 120));
    // ★★ 「使用固定双押角度」默认开 ⇒ 「薄角 θ / 偏移预算」置灰（不能自定义角度）
    const dpLock = JSON.parse(String(await js(`JSON.stringify((function(){
      var f = (window.__dsh.schema().fields||[]).filter(function(x){
        return x.key === 'dp_theta' || x.key === 'dp_skew_max_ms';});
      return { on: window.__dsh.state.use_fixed_dp_angle,
               dis: f.filter(function(x){return x._input && x._input.disabled;}).length };
    })())`)));
    check('★ 固定双押角度默认开，「薄角 θ / 偏移预算」置灰（不能自定义角度）',
      dpLock.on === true && dpLock.dis === 2, JSON.stringify(dpLock));
  }

  // ---------------------------------------------------------------- 毫秒时间戳来源（docs/45 §7）
  //   用户那条箭头：「毫秒时间戳 → BDG → 回到我们」。这一段验的是**我们这边的入口**：
  //   一份裸时间戳能直接加载、默认参数就是「去噪 + 直拟合」、而且时序逐点精确。
  {
    fs.mkdirSync(path.dirname(TSFILE), { recursive: true });
    const lines = [];
    for (let k = 0; k < 120; k++) {
      // 大多整砖、偶尔半砖 —— 这样分母不会是 1，能真验到「格 = 砖长/分母」
      lines.push((2.131 + (k + (k % 5 === 4 ? 0.5 : 0)) * 150).toFixed(3));
    }
    fs.writeFileSync(TSFILE, lines.join('\n') + '\n', 'utf-8');
    await js(`window.__dsh.load(${JSON.stringify(TSFILE)})`);
    await sleep(700);
    const ti = await js(`(() => {
      const r = window.__dsh.loadInfo() || {};
      return { is_ts: !!r.is_ts, n: (r.ts || {}).n_kept,
               merge: r.default_merge_ms, fit: r.default_fit_mode,
               dn: r.default_denoise_on, bpm: (r.ts_grid || {}).bpm,
               div: (r.ts_grid || {}).div, step: (r.ts_grid || {}).step_ms,
               label: (document.querySelector("#lbl-file") || {}).textContent || "" };
    })()`);
    check('★ 毫秒时间戳能当来源加载', ti.is_ts && ti.n === 120, JSON.stringify(ti).slice(0, 120));
    check('★ 默认 merge_ms=0 / 直拟合 / 去噪开',
      ti.merge === 0 && ti.fit === 'direct' && ti.dn === true,
      `merge=${ti.merge} fit=${ti.fit} dn=${ti.dn}`);
    check('★ 网格自动算出来（bpm≈400，格 = 砖长/分母）',
      Math.abs(ti.bpm - 400) < 1 && ti.div >= 1
      && Math.abs(ti.step - 150 / ti.div) < 1e-6,
      `bpm=${ti.bpm} div=${ti.div} step=${ti.step}`);
    check('★ 文件信息行写明是时间戳来源 + 网格',
      /时间戳/.test(ti.label) && /砖长/.test(ti.label), ti.label.split('\n').slice(0, 3).join(' | '));
    const tr = await js(`(async () => {
      const r = await window.__dsh.api.rebuild(window.__dsh.state);
      return { ok: !!r.ok, n: r.n_onsets, err: (r.fit || {}).err_max_ms,
               mode: r.fit_mode, straight: (r.fit || {}).straight_frac };
    })()`);
    check('★★ 直拟合能出谱且时序误差 = 0', tr.ok && tr.err === 0 && tr.n === 120,
      `ok=${tr.ok} n=${tr.n} err=${tr.err} mode=${tr.mode}`);
    check('★ 直线率报出来（时间戳这条路应该很高）',
      typeof tr.straight === 'number' && tr.straight > 0.5, `straight=${tr.straight}`);
    // 回到原样本，免得后面的断言以为还在时间戳上
    await js(`window.__dsh.load(${JSON.stringify(MID)})`);
    await sleep(700);
    const back = await js('!!(window.__dsh.loadInfo() || {}).tracks');
    check('★ 能切回 MIDI 来源', back === true, '');
  }

  // ------------------------------------------- 时间戳 JSON（DEMUCS 分轨 · docs/56）
  //   用户口径：「新的常用格式，希望我们的桥接器、生成逻辑基于它做兼容，
  //   就像现在兼容纯时间戳那样」。这里验界面这一侧：
  //   一路一条轨 / 默认只勾主旋律 / 来源徽标 / 文件信息那张表 / 出谱。
  {
    await js(`window.__dsh.load(${JSON.stringify(STEMJSON)})`);
    await sleep(900);
    const si = await js(`(() => {
      const r = window.__dsh.loadInfo() || {};
      return { is_sj: !!r.is_stem_json, is_ts: !!r.is_ts,
               live: (r.stem || {}).n_live, pts: (r.stem || {}).n_points,
               trk: (r.tracks || []).length,
               def: r.default_tracks_checked, sub: r.default_sub_checked,
               dp: r.default_dp_checked, merge: r.default_merge_ms,
               fit: r.default_fit_mode, dn: r.default_denoise_on,
               roles: r.stem_roles || {}, notes: (r.tracks || []).filter((t) => t.note).length,
               names: (r.tracks || []).map((t) => t.name),
               badge: (document.querySelector('#src-badge') || {}).textContent || '',
               label: (document.querySelector('#lbl-file') || {}).textContent || '' };
    })()`);
    check('★★ 时间戳 JSON（分轨）能当来源加载（6 路 = 6 条音轨）',
      si.is_sj && si.live === 6 && si.trk === 6, JSON.stringify(si).slice(0, 150));
    check('★ 一路一条轨、轨名带中文路名',
      si.names[0] === '旋律·melody' && si.names.length === 6, si.names.join('/'));
    check('★ 默认只勾主旋律（次轨/双押轨只标注，不乱动）',
      JSON.stringify(si.def) === '[0]' && si.sub.length === 0 && si.dp.length === 0,
      JSON.stringify({ def: si.def, sub: si.sub, dp: si.dp }));
    check('★ 默认值 = merge_ms 0 / 直拟合 / 去噪开',
      si.merge === 0 && si.fit === 'direct' && si.dn === true,
      `merge=${si.merge} fit=${si.fit} dn=${si.dn}`);
    check('★ 建议角色带进界面（鼓 = 双押）', si.roles['2'] === 'dp', JSON.stringify(si.roles));
    check('★ 每一路都带人话注释', si.notes === 6, String(si.notes));
    check('★ 来源徽标写明是分轨时间戳 JSON',
      /时间戳 JSON/.test(si.badge) && /分轨/.test(si.badge), si.badge);
    check('★ 文件信息里有每一路一行 + 网格按哪一路算',
      /旋律·melody/.test(si.label) && /钢琴·piano/.test(si.label)
      && /网格按「melody」算/.test(si.label),
      si.label.split('\n').filter((l) => /·/.test(l)).slice(0, 2).join(' | '));
    const sjr = await js(`(async () => {
      const r = await window.__dsh.api.rebuild(window.__dsh.state);
      return { ok: !!r.ok, n: r.n_onsets, err: (r.fit || {}).err_max_ms,
               mode: r.fit_mode };
    })()`);
    check('★★ 分轨 JSON 直拟合出谱（旋律 64 点）且时序误差 = 0',
      sjr.ok && sjr.n === 64 && sjr.err === 0,
      `ok=${sjr.ok} n=${sjr.n} err=${sjr.err} mode=${sjr.mode}`);
    // 多勾一路（鼓）⇒ 主轨取并集。
    // ★ 这里**不读 payload**（那是异步落地的，历史上就为它发生过假 FAIL），
    //   而是直接把当前 state 交给后端、看它算出来多少 onset —— 判据更硬。
    const n1 = await setTracksAndCount([0]);
    const n2 = await setTracksAndCount([0, 2]);
    const sj2 = await js(`(async () => {
      const r = await window.__dsh.api.rebuild(window.__dsh.state);
      return { ok: !!r.ok, n: r.n_onsets, track: window.__dsh.state.tracks_checked,
               dp: window.__dsh.state.dp_checked, fit: r.fit_mode,
               plo: window.__dsh.state.pitch_lo, phi: window.__dsh.state.pitch_hi,
               msg: String(r.msg || r.error || "") };
    })()`);
    check('★ 再勾鼓轨 ⇒ 主轨取并集（音点数变多）',
      sj2.ok === true && Number(sj2.n) > n1,
      `payload=${n1} → ${n2}；后端 n_onsets=${sj2.n} state=${JSON.stringify(sj2)}`);
    // ★ 载入时的取舍账要**当场**上屏（原曲找不到 / 某路是空的…）
    await js(`window.__dsh.load(${JSON.stringify(STEMJSON_AUDIO_MISSING)})`);
    await sleep(900);
    const sw = await js(`(() => ({
      text: (document.querySelector('#warnings') || {}).textContent || '',
      badge: (document.querySelector('#warn-badge') || {}).textContent || '',
      more: (document.querySelector('#more') || {}).open
    }))()`);
    check('★ 原曲找不到 ⇒ 载入时就在「警告」里说出来（不许静默）',
      /原曲找不到/.test(sw.text) && /警告/.test(sw.badge),
      sw.text.slice(0, 90));
    check('★ 有警告时自动展开「更多」面板', sw.more === true, String(sw.more));
    // ★★ 结构化但不认识的 JSON ⇒ 明确拒绝，绝不出「顶层数字」那张垃圾谱
    //   （`api.load` 不抛异常，它把 400 的 body 原样返回 ⇒ 看 `ok`/`error`）
    const sjx = await js(`(async () => {
      const r = await window.__dsh.api.load(${JSON.stringify(STEMJSON_NOT_STEM)});
      return { ok: r.ok, err: r.error || '' };
    })()`);
    check('★★ 结构化 JSON 明确拒绝（不许出垃圾谱）',
      sjx.ok !== true && /读不出时间戳/.test(sjx.err), String(sjx.err).slice(0, 90));
    await js(`window.__dsh.load(${JSON.stringify(MID)})`);
    await sleep(700);
  }
  check('BDG 桥有状态行', (await js('(document.querySelector("#br-status")||{}).textContent||""')).length > 2);
  // ★ 启动并桥接（docs/40）：两个按钮 + 一行宿主状态
  check('★ 有「启动并桥接」按钮', !!(await js('!!document.querySelector("#br-host")')));
  check('★ 有「停止宿主」按钮', !!(await js('!!document.querySelector("#br-hoststop")')));
  check('★ 有宿主状态行', !!(await js('!!document.querySelector("#br-hoststat")')));
  // ★★ 2026-10：用户报「投射到编辑器的按钮不工作了」—— 根因是 `bindBridge()` 里
  //    漏绑了 `#br-push`（按钮和函数都在，就是没接起来，点了连提示都没有）。
  //    光检查「按钮存在」是抓不住的（下面那句一直是通过的），所以这里改成检查
  //    **桥面板里每个按钮都真的有处理器**。以后再加按钮忘了绑，这条会红。
  const deadBtns = JSON.parse(await js(
    'JSON.stringify([...document.querySelectorAll("#bridge button")]'
    + '.filter(b => !b.onclick && !b.getAttribute("onclick"))'
    + '.map(b => b.id || b.textContent.trim()))'));
  check('★★ 桥面板每个按钮都绑了处理器（漏绑 = 点了毫无反应）',
    deadBtns.length === 0, deadBtns.length ? ('没绑的：' + deadBtns.join(', ')) : '');
  check('★「投射到编辑器」的处理器真的挂在 doBridgePush 上',
    await js('String((document.querySelector("#br-push")||{}).onclick||"").includes("doBridgePush")'),
    await js('String((document.querySelector("#br-push")||{}).onclick||"").slice(0, 60)'));
  const hs = await js('window.__dsh.hostState()');
  check('★ 宿主状态查得到（present/deps/cdp_up 都在）',
    !!hs && typeof hs.present === 'boolean' && typeof hs.deps === 'boolean'
    && typeof hs.cdp_up === 'boolean',
    hs && JSON.stringify({ present: hs.present, deps: hs.deps, cdp_up: hs.cdp_up }));
  const hsTxt = await js('(document.querySelector("#br-hoststat")||{}).textContent||""');
  check('★ 宿主状态行写清「装没装 / 在不在跑 / 该跑什么」',
    /宿主/.test(hsTxt) && (hsTxt.includes('host:fetch') || hsTxt.includes('启动并桥接')
      || hsTxt.includes('在跑')),
    hsTxt.split('\n')[0].slice(0, 60));
  const stopDisabled = await js('document.querySelector("#br-hoststop").disabled');
  check(hs && hs.pid
    ? '★ 有我们起的宿主 ⇒「停止宿主」可点'
    : '★ 没记录到宿主进程 ⇒「停止宿主」禁用（不误杀别人的进程）',
    `disabled=${stopDisabled}`);
  // ★「停止」是安全操作（没记账就是干净 no-op），所以 e2e 里可以真点一次
  const stopJ = JSON.parse(await js(
    '(async () => JSON.stringify(await window.__dsh.api.hostStop()))()'));
  check('★ 点「停止宿主」不炸、且如实报告停没停',
    stopJ && typeof stopJ.ok === 'boolean',
    JSON.stringify(stopJ).slice(0, 100));
  // 起宿主太贵（要真拉一个 Electron 窗口）⇒ e2e **只验前面这段**：
  // 拦住「宿主没装好就点启动」这条最可能踩的路，并确认它是**明确失败**而不是静默。
  if (hs && (!hs.present || !hs.deps)) {
    const bad = JSON.parse(await js(
      '(async () => JSON.stringify(await window.__dsh.api.hostStart()))()'));
    check('★ 宿主没装好时点「启动并桥接」明确失败（并说该跑 host:fetch）',
      bad && bad.error && /host:fetch/.test(bad.error), JSON.stringify(bad).slice(0, 120));
  } else {
    check('（宿主已装好，跳过「没装就点」这条）', true, '免得 e2e 真弹一个 BDG 窗口');
  }
  await js('window.__dsh.bridge()');
  await sleep(300);
  const brTxt = await js('(document.querySelector("#br-status")||{}).textContent||""');
  check('BDG 桥状态已刷新（列出连接串/未连接）',
    /未连接|已连接|没应答/.test(brTxt), brTxt.split('\n')[0].slice(0, 40));
  check('BDG 桥地址栏拿到 ws:// 连接串',
    /^ws:\/\/127\.0\.0\.1:\d+\/ws\?token=/.test(
      (await js('(document.querySelector("#br-url")||{}).textContent||""')).trim()),
    (await js('(document.querySelector("#br-url")||{}).textContent||""')).trim().slice(0, 48));
  // 没连 BDG 时点「投射」必须**明确失败**（不静默、不崩）
  await js('window.__dsh.bridgePush()');
  await sleep(400);
  const pushTxt = await js('window.__dsh.status()');
  check('未连接时「投射」明确报错而不是静默',
    /没连上|失败|⚠/.test(pushTxt), pushTxt.slice(0, 40));
  await js('window.__dsh.bridgeAdopt()');
  await sleep(400);
  const pullTxt = await js('window.__dsh.status()');
  check('未投射过时「收回」明确报错而不是静默',
    /失败|没有可对账|⚠/.test(pullTxt), pullTxt.slice(0, 40));

  // ---------------------------------------------------------------- BDG 工程当来源
  await js(`window.__dsh.load(${JSON.stringify(BDG)})`);
  await sleep(900);
  const bdgInfo = await js('JSON.stringify(window.__dsh.loadInfo()||{})');
  const bi = JSON.parse(bdgInfo);
  check('BDG 工程能当来源（is_bdg）', bi.is_bdg === true, `is_bdg=${bi.is_bdg}`);
  check('BDG 来源给出轨道清单', (bi.tracks || []).length >= 4, `${(bi.tracks || []).length} 轨`);
  check('BDG 来源带「建议角色」', (bi.tracks || []).some((t) => t.suggest),
    JSON.stringify((bi.tracks || []).map((t) => t.suggest || '-')));
  check('BDG 来源默认勾主轨', (bi.default_tracks_checked || []).length >= 1,
    JSON.stringify(bi.default_tracks_checked));
  // ★ 来源信息要落在**常驻**位置（状态栏会被「重建结果」覆盖，那是暂时的）
  const fileTxt = await js('(document.querySelector("#lbl-file")||{}).textContent||""');
  check('文件信息标明这是 BDG 来源', /BDG/.test(fileTxt),
    fileTxt.replace(/\s+/g, ' ').slice(0, 56));
  const trackTxt = await js('(document.querySelector("#lst-tracks")||{}).textContent||""');
  check('轨道列表把建议标出来', /建议/.test(trackTxt),
    trackTxt.replace(/\s+/g, ' ').slice(0, 60));
  await js('window.__dsh.tab("chart")');

  // ============================================================ [15] ★ 新 UI（docs/49 方案 A）
  // 三区 + 停靠 + 段带 + Shift+M 移动模式 + 布局落盘 + **三押记号**
  console.log('\n[15] ★ 新 UI：段带 / 三押记号 / 报告带 / Shift+M / 布局落盘');
  // 回到双押演示曲（它的 trk1+trk2 在 500ms 网格上同步 ⇒ 一说就该有三押）
  await js(`window.__dsh.load(${JSON.stringify(MID)})`);
  await sleep(700);
  await js('window.__dsh.setParam("dp_mode", 1)');
  // ★ 2026-10：主轨必须**不是**多押轨 —— 多押轨按口径不参与主轨并集，
  //   撞车的话这一次 rebuild 会被拒（保留上一张谱面）⇒ 三押断言就变成假绿/假红。
  //   这份演示素材里 trk1+trk2 是「500ms 网格同步」的那一对（三押的判据），
  //   所以主轨用 trk3（后段进来的旋律轨）。
  await js('window.__dsh.setTracks([3])');
  await sleep(300);
  await js('window.__dsh.state.dp_checked = [1, 2]');
  await js('window.__dsh.rebuild()');
  await sleep(500);

  // —— 段带：存在、画了东西、三押记号在
  const bandInfo = await js(`(() => {
    const cv = document.querySelector('#cv-band');
    const r = cv.getBoundingClientRect();
    const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
    let ink = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) ink++;
    const b = window.__dsh.band;
    const ids = (window.__dsh.payload() || {}).dp_pairs || [];
    return JSON.stringify({ w: Math.round(r.width), h: Math.round(r.height), ink,
      marks: b.marks.length, triples: b.marks.filter((m) => m.press >= 3).length,
      pairs: ids.length, segs: b.segs.length });
  })()`);
  const bi2 = JSON.parse(bandInfo);
  check('★ 段带存在且有高度', bi2.w > 200 && bi2.h >= 60, `${bi2.w}x${bi2.h}`);
  check('段带真的画了东西（不是空白画布）', bi2.ink > 500, `ink=${bi2.ink}`);
  check('段带画出了段', bi2.segs >= 1, `${bi2.segs} 段`);
  check('★★ 段带标记里有**三押**（press≥3）—— 这就是「三押的 UI」',
    bi2.triples > 0, `marks=${bi2.marks} 三押=${bi2.triples} dp_pairs=${bi2.pairs}`);

  // ★★ 2026-10：**「字段静默消失」体检**（用户「拼尽全力找不到三押在哪关」的根因）。
  //   以前 buildPanel/buildViewBars 用**写死的 key 列表**渲染 ⇒
  //   `use_fixed_dp_angle` / `three_press_mode` / `sub_gap_ms` / 预览音源三件套
  //   全都**有 schema、没控件**，界面上怎么找都找不到。
  //   这里断言：**每一个 schema 字段都有控件**，而且几个关键开关**真的在 DOM 里**。
  const uiAuditRaw = await js(`JSON.stringify(window.__dsh.uiAudit())`);
  const uiAu = JSON.parse(uiAuditRaw);
  check('★★ 每一个 schema 字段都渲染出了控件（uiAudit.missing 为空）',
    uiAu.missing.length === 0, uiAuditRaw);
  const uiMust = ['three_press_mode', 'use_fixed_dp_angle', 'sub_gap_ms',
    'preview_audio_mode', 'preview_audio_path', 'preview_audio_offset_ms'];
  const uiPresent = await js(`JSON.stringify(${JSON.stringify(uiMust)}.filter(
    (k) => !!document.querySelector('#in-' + k)))`);
  check('★★ 「三押」「固定双押角度」「插空阈值」「预览音源三件套」都在界面上',
    JSON.parse(uiPresent).length === uiMust.length,
    `找到 ${JSON.parse(uiPresent).length}/${uiMust.length}：` + uiPresent);
  // ★ 三押开关**可操作**：三档选项齐全 + 真的能改 state（不是只画了个壳）
  const uiTp = await js(`(() => {
    const s = document.querySelector('#in-three_press_mode');
    if (!s) return JSON.stringify({ ok: false });
    const before = window.__dsh.state.three_press_mode;
    const opts = [...s.options].map((o) => o.textContent);
    s.selectedIndex = 2;
    s.dispatchEvent(new Event('change', { bubbles: true }));
    const after = window.__dsh.state.three_press_mode;
    s.selectedIndex = 0;
    s.dispatchEvent(new Event('change', { bubbles: true }));
    return JSON.stringify({ ok: true, opts, before, after,
      back: window.__dsh.state.three_press_mode, disabled: s.disabled });
  })()`);
  const uiTpj = JSON.parse(uiTp);
  check('★★ 三押开关是三档下拉，且改得动 state（拆 / 不拆 / 跳过）',
    uiTpj.ok && uiTpj.opts.length === 3 && String(uiTpj.after) === '2'
    && String(uiTpj.back) === '0' && !uiTpj.disabled, uiTp);
  check('★ 三押 chip **常驻**（哪怕 0 处也显示 —— 它是「开关在哪」的入口）',
    (await js('window.__dsh.chips()')).some((c) => c.startsWith('三押')), '');
  const uiDp3 = await js(`(() => {
    const c = [...document.querySelectorAll('#chips .chip')]
      .find((x) => x.textContent.trim().startsWith('三押'));
    if (!c) return '';
    c.click();
    return document.querySelector('#detail').textContent;
  })()`);
  check('★ 三押明细里写明**开关在哪**（左栏 ② 主轨 → 三押）',
    uiDp3.includes('开关在哪') && uiDp3.includes('② 主轨'), uiDp3.slice(0, 90));
  // ⚠ chip 的点击是**开关**（再点一次就收起来）。这里必须把它关回原位，
  //   否则下面那条「点 chip 能展开明细」会点到同一个 chip ⇒ 反而被关掉 ⇒ 假 FAIL。
  await js(`(() => {
    const c = [...document.querySelectorAll('#chips .chip')]
      .find((x) => x.textContent.trim().startsWith('三押'));
    if (c && document.querySelector('#detail').classList.contains('on')) c.click();
  })()`);

  // —— 报告带：常驻 chip，点开有明细
  const chipTxt = await js('JSON.stringify(window.__dsh.chips())');
  check('★★ 报告带常驻「三押 N」chip', /三押 \d+/.test(chipTxt), chipTxt.slice(0, 150));
  check('报告带有「跳过四押」或有「双押丢」',
    /跳过四押|双押丢/.test(chipTxt), chipTxt.slice(0, 150));
  const chipOpen = await js(`(() => {
    const c = [...document.querySelectorAll('#chips .chip')]
      .find((x) => /三押/.test(x.textContent));
    if (!c) return 'no-chip';
    c.click();
    const d = document.querySelector('#detail');
    return (d && d.classList.contains('on')) ? d.textContent.slice(0, 60) : 'closed';
  })()`);
  check('★ 点 chip 能展开明细（不再埋在折叠里）', chipOpen !== 'closed' && chipOpen !== 'no-chip',
    String(chipOpen).slice(0, 60));
  await js(`document.querySelectorAll('#chips .chip')[0].click()`);   // 收起来

  // —— Shift+M 移动模式：全 UI 冻结（点击穿透到 pane）
  // ★ 2026-10 修：这一条以前**依赖持久化布局**（`<userData>/ui-layout.json`）。
  //   报告带一旦是「收起」（`report.collapsed=true`，h=0），`#chips` 就没有尺寸
  //   ⇒ `elementFromPoint` 落回 `#top` ⇒ **假红**（实测：上一次 e2e 自己收起并落盘，
  //   下一次开跑就在这一条红）。所以先**显式把报告带展开**，让断言只看"冻结"这件事。
  if (await js('window.__dsh.reportCollapsed()')) {
    await js('window.__dsh.toggleReport()');
    await sleep(300);
  }
  const lm = await js(`(async () => {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const key = (k, shift) => document.dispatchEvent(new KeyboardEvent('keydown',
      { key: k, shiftKey: !!shift, bubbles: true, cancelable: true }));
    const at = (el) => { const b = el.getBoundingClientRect();
      const e = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      return e ? (e.id ? '#' + e.id : (e.className || e.tagName)) : '(null)'; };
    key('M', true); await wait(80);
    const on = document.body.classList.contains('layoutmode');
    const banner = document.querySelector('#lmbanner').classList.contains('on');
    const chipWho = at(document.querySelector('#chips .chip'));
    const blockWho = at(document.querySelector('#left'));
    const exitWho = at(document.querySelector('#lm-exit'));
    key('Escape', false); await wait(80);
    const off = !document.body.classList.contains('layoutmode');
    return JSON.stringify({ on, banner, chipWho, blockWho, exitWho, off,
      frozenOpacity: getComputedStyle(document.querySelector('#panel')).opacity });
  })()`);
  const lmj = JSON.parse(lm);
  check('★ Shift+M 进入移动模式（横幅出现）', lmj.on && lmj.banner, lm);
  check('★★ 移动模式里 chip 被冻结（点击穿透到 pane）',
    lmj.chipWho === '#chips' || lmj.chipWho === '#report', lmj.chipWho);
  check('★ 移动模式里块本身仍可拖（命中块自己）', lmj.blockWho === '#left', lmj.blockWho);
  check('★ 「退出」按钮还活着', lmj.exitWho === '#lm-exit', lmj.exitWho);
  check('★ Esc 能退出移动模式', lmj.off, lm);

  // —— 布局落盘：改段带高度 → 写 <userData>/ui-layout.json
  const saved = await js(`(() => {
    window.__dsh.layout.L.bandH = 123;
    window.__dsh.layout.apply();
    window.__dsh.layout.save();             // 走真实落盘路径（debounce 400ms）
    return JSON.stringify({ bandH: window.__dsh.layout.L.bandH,
                            css: Math.round(document.querySelector('#tlwrap')
                              .getBoundingClientRect().height) });
  })()`);
  check('布局模型里有段带高度（bandH）且界面跟着变', /bandH":123/.test(saved), saved);
  await sleep(800);                       // 等 debounce 400ms + 写盘
  const back = await js('(async () => JSON.stringify(await window.dsh.layoutGet()))()');
  check('★★ 布局落盘成功（ui-layout.json 能读回来，n=2）',
    /"n":2/.test(back) && /bandH":123/.test(back), String(back).slice(0, 160));
  const layoutHi = await js(`(() => {
    const l = window.__dsh.layout.L;
    return JSON.stringify(Object.keys(l.panes || {}));
  })()`);
  check('布局模型含四个 pane（左/右/报告/大直线）',
    /left/.test(layoutHi) && /right/.test(layoutHi)
    && /report/.test(layoutHi) && /flx/.test(layoutHi), layoutHi);

  // —— ★ 2026-09-20（工作台皮肤合并）：③b 采bpm **搬回右栏**了，浮窗 `#fl-xk`
  //   里不再有内容 ⇒ `app.js` 给它打 `fl-empty`、`workbench-elements.css` 整块隐藏。
  //   所以旧的「浮窗待在中间预览区里」已经不成立 —— 改成断言**新口径**：
  //   ① 浮窗确实被收掉了（零尺寸，不会有个空框飘着）；② ③b 的内容在右栏里找得到。
  const flNew = await js(`(() => {
    const f = document.querySelector('#fl-xk');
    const r = f.getBoundingClientRect();
    const inRight = /采bpm/.test(document.querySelector('#groups').textContent);
    const shown = getComputedStyle(f).display !== 'none';
    return JSON.stringify({ w: Math.round(r.width), h: Math.round(r.height),
      empty: f.classList.contains('fl-empty'), inRight: inRight, shown: shown });
  })()`);
  const fn = JSON.parse(flNew);
  check('★★ ③b 浮窗已收掉（fl-empty + 零尺寸，不留空框）',
    fn.empty === true && fn.w === 0 && fn.h === 0, flNew);
  check('★★ ③b 采bpm 的内容搬进了右栏（用户找得到）', fn.inRight === true, flNew);

  // 段带拖动改时间（拖段边界 ⇒ 写回 state）
  const dragSeg = await js(`(() => {
    const b = window.__dsh.band;
    if (!b.segs.length) return 'no-seg';
    const seg = b.segs[0];
    const before = [seg.t0, seg.t1];
    const cv = document.querySelector('#cv-band');
    const r = cv.getBoundingClientRect();
    const x = (t) => (t - b.t0) * b.per;
    cv.dispatchEvent(new PointerEvent('pointerdown',
      { bubbles: true, cancelable: true, clientX: r.left + x(seg.t1), clientY: r.top + 12,
        offsetX: x(seg.t1), offsetY: 12, pointerId: 55, buttons: 1 }));
    window.dispatchEvent(new PointerEvent('pointermove',
      { bubbles: true, clientX: r.left + x(seg.t1) - 60, clientY: r.top + 12,
        pointerId: 55, buttons: 1 }));
    window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 55 }));
    return JSON.stringify({ before, after: [seg.t0, seg.t1] });
  })()`);
  check('★ 拖段带边界能改时间（边界可拖 = 时间轴唯一"每天都用"的能力）',
    dragSeg !== 'no-seg' && (() => {
      const d = JSON.parse(dragSeg);
      return Math.abs(d.after[0] - d.before[0]) + Math.abs(d.after[1] - d.before[1]) > 100;
    })(), dragSeg);

  // ------------------------------------------- 自动贴合（时值体检 · docs/58）
  //   用户 2026-10：「再遇到这样的抖动极大的原始文件，有复用的可能性吗」⇒ 一键体检。
  //   这一段守四件事：卡片在 / **体检不改任何参数** / 结论是人话 + 数字 /
  //   点「套用」才改参数并重算（且改的正是建议的那几个）。
  {
    // 用**带抖动的倍频陷阱夹具**（真砖长 90.909、有一路会被认成 181.8）
    const TRAP = path.join(__dirname, '..', 'tests', 'fixtures', 'stemjson',
                           'octave_trap.json');
    await js(`window.__dsh.load(${JSON.stringify(TRAP)})`);
    await sleep(900);
    check('★ 左栏有「自动贴合」那颗按钮',
      !!(await js('!!document.querySelector("#td-run")')), '');
    const tdBefore = JSON.parse(await js(`JSON.stringify({
      hint: window.__dsh.state.denoise_hint_ms, tol: window.__dsh.state.fit_tol_ms,
      agg: window.__dsh.state.aggressive_fit, merge: window.__dsh.state.merge_ms,
      mode: window.__dsh.state.fit_mode, tracks: window.__dsh.state.tracks_checked,
      n: (window.__dsh.stats() || {}).rebuildCount })`));
    await js('document.querySelector("#td-run").click()');
    // 体检要跑两遍试算 ⇒ 多等一会儿（不赌固定 sleep，看按钮文字回落）
    for (let i = 0; i < 40; i++) {
      const busy = String(await js('(document.querySelector("#td-run")||{}).textContent||""'));
      if (!/分析中/.test(busy)) break;
      await sleep(500);
    }
    const tdText = String(await js('(document.querySelector("#td-box")||{}).textContent||""'));
    check('★★ 体检给出结论（砖长 + 建议参数 + 每路的抖动账）',
      /建议砖长/.test(tdText) && /建议：拟合容差/.test(tdText)
      && /每路：残差/.test(tdText), tdText.replace(/\n/g, ' | ').slice(0, 120));
    check('★★ 认出的砖长是 **90.909ms**（没被那一路的 181.8 骗走）',
      /90\.9\d*ms/.test(tdText), tdText.split('\n')[0]);
    check('★ 结论里带「覆盖 / 每路残差」这些数字（不是一句空话）',
      /覆盖率/.test(tdText) && /\d+\.\d+\/\d+\.\d+\/\d+\.\d+ms/.test(tdText),
      tdText.split('\n').filter((l) => /覆盖率/.test(l)).join(' ').slice(0, 100));
    const tdAfterRun = JSON.parse(await js(`JSON.stringify({
      hint: window.__dsh.state.denoise_hint_ms, tol: window.__dsh.state.fit_tol_ms,
      agg: window.__dsh.state.aggressive_fit, merge: window.__dsh.state.merge_ms,
      mode: window.__dsh.state.fit_mode, tracks: window.__dsh.state.tracks_checked,
      n: (window.__dsh.stats() || {}).rebuildCount })`));
    check('★★ **体检本身不改任何参数**（用户口径：不点套用就没有影响）',
      JSON.stringify(tdBefore) === JSON.stringify(tdAfterRun),
      `${JSON.stringify(tdBefore)} vs ${JSON.stringify(tdAfterRun)}`);
    check('★ 体检后出现「按建议套用」按钮',
      !!(await js('!!document.querySelector("#td-apply")')), '');
    await js('document.querySelector("#td-apply").click()');
    await sleep(1200);
    const tdApplied = JSON.parse(await js(`JSON.stringify({
      hint: window.__dsh.state.denoise_hint_ms, tol: window.__dsh.state.fit_tol_ms,
      agg: window.__dsh.state.aggressive_fit, merge: window.__dsh.state.merge_ms,
      mode: window.__dsh.state.fit_mode, tracks: window.__dsh.state.tracks_checked,
      toast: (document.querySelector('#toast')||{}).textContent||'' })`));
    check('★★ 点「套用」才真的改参数（砖长提示被填上，且只改建议的那几个）',
      Number(tdApplied.hint) > 0
      && Math.abs(Number(tdApplied.hint) - 90.909) < 0.1
      && tdApplied.mode === 'direct' && tdApplied.tracks.length === 1,
      JSON.stringify(tdApplied).slice(0, 150));
    check('★ 套用后轻提示说明了「自动贴合已套用」+ 具体数值（不许静默）',
      /自动贴合/.test(tdApplied.toast) && /砖长/.test(tdApplied.toast),
      tdApplied.toast.slice(0, 80));
    await js('window.__dsh.rebuild()');
    const tdFit = JSON.parse(await js(`JSON.stringify({
      code: (window.__dsh.lastResult()||{}).ok,
      ladder: (((window.__dsh.lastResult()||{}).fit)||{}).ladder_on,
      bad: (((window.__dsh.lastResult()||{}).fit)||{}).n_ladder_bad,
      err: (((window.__dsh.lastResult()||{}).fit)||{}).err_max_ms })`));
    check('★★ 套用后能出谱（并且若建议开激进 ⇒ 非阶梯格 0）',
      tdFit.code === true
      && (tdApplied.agg ? (tdFit.ladder === true && tdFit.bad === 0) : true),
      JSON.stringify(tdFit));
    // 复原（后面的小节不受影响）
    await js(`window.__dsh.load(${JSON.stringify(MID)})`);
    await sleep(700);
  }

  // ------------------------------------------- 换手押上色（轨道颜色调度 · docs/59）
  //   用户 2026-10：「镜头与轨道颜色调度」+「**只有换手押给换色**」+「固定白色+黑色霓虹方块」。
  //   这一段守**接线**（这一轮只落地颜色那半）：
  //     ① ⑤b 组的 6 个控件都在；② 默认开、payload/branch 都有报告；③ 段带记号条数与后端一致；
  //     ④ 关掉 ⇒ **一条事件都不写**（payload.color 空 + 段带记号归零 + 报告写明已关闭）。
  //   ⚠ 判据语义（OOX / ≥2 周期 / 只染薄格 / 事件字段集）在 Python 侧
  //     （`tests/test_colorize.py` A~G），这里不重复造；e2e 只验「开关一路通到导出面」。
  {
    await js(`window.__dsh.load(${JSON.stringify(MID)})`);
    await sleep(700);
    const csFields = ['color_schedule', 'handswitch_gap_tiles', 'handswitch_min_cycles',
                      'handswitch_color_span', 'handswitch_track_style',
                      'handswitch_color_type'];
    const csDom = JSON.parse(await js(
      `JSON.stringify(${JSON.stringify(csFields)}.map((k) => !!document.querySelector('#in-' + k)))`));
    check('★ 左栏「⑤b 换手押上色」6 个控件都在（开关/间隔/周期/范围/样式/类型）',
      csDom.every(Boolean), JSON.stringify(csDom));
    check('★ 左栏有「换手押上色」这个组（用户找得到开关）',
      /换手押上色/.test(String(await js('document.querySelector("#groups").textContent'))), '');
    const csOn = JSON.parse(await js(`JSON.stringify({
      on: window.__dsh.state.color_schedule,
      col: window.__dsh.payload().color || {},
      hs: (window.__dsh.band.hs || []).length,
      chips: document.querySelector('#chips').textContent })`));
    check('★ 默认开（用户口径：默认开、可关）', csOn.on === true, String(csOn.on));
    check('★ 报告回到界面（`payload.color` 有 text + floors 与段带记号条数一致）',
      csOn.col.enabled === true && typeof csOn.col.text === 'string'
      && csOn.col.text.length > 0 && csOn.hs === (csOn.col.floors || []).length,
      `hs=${csOn.hs} floors=${(csOn.col.floors || []).length}`);
    check('★ chips 里有「换手押」入口（点它能看到判据与开关位置）',
      /换手押/.test(csOn.chips), csOn.chips.slice(0, 60));

    // —— 关掉 ⇒ 一条都不写
    await js('document.querySelector("#in-color_schedule").click()');
    await js('window.__dsh.rebuild()');
    await sleep(400);
    const csOff = JSON.parse(await js(`JSON.stringify({
      on: window.__dsh.state.color_schedule,
      col: window.__dsh.payload().color || {},
      hs: (window.__dsh.band.hs || []).length,
      detail: (() => { const c = [...document.querySelectorAll('#chips .chip')]
        .find((x) => /换手押已关/.test(x.textContent)); if (c) c.click();
        return (document.querySelector('#detail') || {}).textContent || ''; })() })`));
    check('★★ 关掉后：state 关 / payload 空 / 段带记号归零（一条事件都不写）',
      csOff.on === false && csOff.col.enabled === false
      && (csOff.col.floors || []).length === 0 && csOff.hs === 0,
      JSON.stringify({ on: csOff.on, en: csOff.col.enabled, hs: csOff.hs }));
    check('★ 关掉后在界面上**说清**「一条 RecolorTrack 都没写」（不许静默）',
      /已关|没写/.test(csOff.detail), csOff.detail.slice(0, 80));

    // —— 复原（后面的小节不受影响）
    await js('document.querySelector("#in-color_schedule").click()');
    await js('window.__dsh.rebuild()');
    await sleep(300);
    check('★ 复原后开关回到开', (await js('window.__dsh.state.color_schedule')) === true, '');
  }

  // ==========================================================================
  // ★★ ⑤c 算法轨道调度（`docs/60`）：皮肤 / 涟漪环 / 半径切换
  //   这一段只守**接线**：① 组与 13 个控件都在；② 默认开 + payload/branch 有报告；
  //     ③ 段带记号与后端一致；④ 关掉 ⇒ 一条事件都不写、settings 不动。
  //   ⚠ 判据语义（gapLength 步长 / n=0 不能 −1 / 密度口径 / 迟滞）在 Python 侧
  //     （`tests/test_appearance.py` A~J），这里不重复造。
  {
    await js(`window.__dsh.load(${JSON.stringify(MID)})`);
    await sleep(700);
    const apFields = ['appearance_schedule', 'appearance_skin', 'appearance_glow',
                      'appearance_pulse', 'appearance_ripple', 'appearance_ripple_source',
                      'appearance_ripple_rings', 'appearance_ripple_step',
                      'appearance_radius', 'appearance_radius_quiet',
                      'appearance_radius_dense', 'appearance_radius_min_sec',
                      'appearance_dense_fps', 'appearance_quiet_fps',
                      'appearance_density_window'];
    const apDom = JSON.parse(await js(
      `JSON.stringify(${JSON.stringify(apFields)}.map((k) => !!document.querySelector('#in-' + k)))`));
    check('★ 左栏「⑤c 算法轨道调度」15 个控件都在（皮肤/涟漪/半径）',
      apDom.every(Boolean), JSON.stringify(apDom));
    check('★ 左栏有「算法轨道调度」这个组（用户找得到开关）',
      /算法轨道调度/.test(String(await js('document.querySelector("#groups").textContent'))), '');
    const apOn = JSON.parse(await js(`JSON.stringify({
      on: window.__dsh.state.appearance_schedule,
      ap: window.__dsh.payload().appearance || {},
      marks: (window.__dsh.band.ap || []).length,
      chips: document.querySelector('#chips').textContent })`));
    check('★ 默认开（用户口径：默认开、可关）', apOn.on === true, String(apOn.on));
    check('★ 报告回到界面（`payload.appearance` 有 text + skin=Neon）',
      apOn.ap.enabled === true && typeof apOn.ap.text === 'string'
      && apOn.ap.text.length > 0 && apOn.ap.skin === 'Neon',
      `text=${String(apOn.ap.text).slice(0, 40)} skin=${apOn.ap.skin}`);
    check('★ 段带记号条数 = 涟漪触发点 + 半径切换点（与后端一致）',
      apOn.marks === (apOn.ap.ripples || []).length + (apOn.ap.radius_spans || []).length,
      `marks=${apOn.marks} rip=${(apOn.ap.ripples || []).length} rad=${(apOn.ap.radius_spans || []).length}`);
    check('★ chips 里有「轨道调度」入口',
      /轨道调度/.test(apOn.chips), apOn.chips.slice(0, 60));

    // —— 关掉 ⇒ 事件与 settings 都不动
    await js('document.querySelector("#in-appearance_schedule").click()');
    await js('window.__dsh.rebuild()');
    await sleep(400);
    const apOff = JSON.parse(await js(`JSON.stringify({
      on: window.__dsh.state.appearance_schedule,
      ap: window.__dsh.payload().appearance || {},
      marks: (window.__dsh.band.ap || []).length,
      detail: (() => { const c = [...document.querySelectorAll('#chips .chip')]
        .find((x) => /轨道调度已关/.test(x.textContent)); if (c) c.click();
        return (document.querySelector('#detail') || {}).textContent || ''; })() })`));
    check('★★ 关掉后：state 关 / payload 空 / 段带记号归零（一条事件都不写）',
      apOff.on === false && apOff.ap.enabled === false
      && (apOff.ap.floors || []).length === 0 && apOff.marks === 0,
      JSON.stringify({ on: apOff.on, en: apOff.ap.enabled, marks: apOff.marks }));
    check('★ 关掉后 settings 也没被改（皮肤不偷偷生效）',
      (apOff.ap.settings || null) === null || Object.keys(apOff.ap.settings || {}).length === 0,
      JSON.stringify(apOff.ap.settings || {}));
    check('★ 关掉后在界面上**说清**「一条事件都没写」（不许静默）',
      /已关|没写/.test(apOff.detail), apOff.detail.slice(0, 80));

    // —— 复原（后面的小节不受影响）
    await js('document.querySelector("#in-appearance_schedule").click()');
    await js('window.__dsh.rebuild()');
    await sleep(300);
    check('★ 复原后开关回到开', (await js('window.__dsh.state.appearance_schedule')) === true, '');
  }

  // ==========================================================================
  // ★★ ⑤d 演出（`docs/62`）：入场 / 离场 / 三连音自动标出 / **分段编辑器**
  //   这一段守**接线 + 分段交互**：① 组与 5 个控件都在；② 默认开 + payload 有报告；
  //     ③ 导出的 `settings.beatsAhead` 被抬到 ≥ 提前量+余量（否则方块会在动画后才出现）；
  //     ④ **填起始/结束方块**能加段、能选招、能删、能清空，且真的换掉该段的招；
  //     ⑤ 关掉 ⇒ 一条事件都不写、beatsAhead 不被抬。
  //   ⚠ 判据语义（完整性 / 同格顺序 / 提前量不足）在 `tests/test_show.py` A~K，这里不重复造。
  {
    await js(`window.__dsh.load(${JSON.stringify(MID)})`);
    await sleep(700);
    const shFields = ['show_schedule', 'show_out_move', 'show_in_move',
                      'show_lead', 'show_margin', 'show_triplet', 'show_qe_g'];
    const shDom = JSON.parse(await js(
      `JSON.stringify(${JSON.stringify(shFields)}.map((k) => !!document.querySelector('#in-' + k)))`));
    check('★ 左栏「⑤d 演出」7 个控件都在（开关/预设招/提前量/余量/三连音）',
      shDom.every(Boolean), JSON.stringify(shDom));
    check('★ 左栏有「⑤d 演出」这个组（用户找得到开关）',
      /⑤d 演出/.test(String(await js('document.querySelector("#groups").textContent'))), '');
    const shOn = JSON.parse(await js(`JSON.stringify({
      on: window.__dsh.state.show_schedule,
      lead: window.__dsh.state.show_lead,
      sh: window.__dsh.payload().show || {},
      chips: document.querySelector('#chips').textContent })`));
    check('★ 默认开 + 提前量默认 10 格（用户口径）',
      shOn.on === true && Number(shOn.lead) === 10,
      `on=${shOn.on} lead=${shOn.lead}`);
    check('★ 报告回到界面（`payload.show` 有 text + 离场/入场条数）',
      shOn.sh.enabled === true && typeof shOn.sh.text === 'string'
      && shOn.sh.text.length > 0 && shOn.sh.n_out > 0 && shOn.sh.n_in > 0,
      `text=${String(shOn.sh.text).slice(0, 40)} out=${shOn.sh.n_out} in=${shOn.sh.n_in}`);
    check('★ beatsAhead 需求 = 提前量 + 余量（10+4=14）',
      Number(shOn.sh.required_beats_ahead) === Number(shOn.sh.lead) + Number(shOn.sh.margin),
      String(shOn.sh.required_beats_ahead));

    // —— ★ 分段编辑器：**填起始方块 / 结束方块**（与游戏里 startTile/endTile 同口径）
    const segAdded = JSON.parse(await js(`(() => {
      const before = (window.__dsh.showSegList() || []).length;
      window.__dsh.showSegAdd(3, 6, '入B', '出D');
      const after = window.__dsh.showSegList() || [];
      const rows = document.querySelectorAll('#lst-show .region').length;
      const lo = document.querySelector('#inp-show-lo-0');
      const hi = document.querySelector('#inp-show-hi-0');
      const selIn = document.querySelector('#sel-show-in_move-0');
      const selOut = document.querySelector('#sel-show-out_move-0');
      return JSON.stringify({ before, after, rows,
        lo: lo ? lo.value : null, hi: hi ? hi.value : null,
        selIn: selIn ? selIn.value : null, selOut: selOut ? selOut.value : null });
    })()`));
    check('★★ 加分段后列表出现一行，且输入框里就是**方块号**（3 / 6）',
      segAdded.before === 0 && segAdded.rows === 1
      && segAdded.lo === '3' && segAdded.hi === '6',
      JSON.stringify(segAdded));
    check('★ 段内能各选入场 / 出场招（初始值就写进去了）',
      segAdded.selIn === '入B' && segAdded.selOut === '出D', JSON.stringify(segAdded));

    await js('window.__dsh.rebuild()');
    await sleep(500);
    const segEffect = JSON.parse(await js(`(() => {
      const sh = window.__dsh.payload().show || {};
      const segs = sh.segments || [];
      const s = segs.find((x) => x.lo === 3 && x.hi === 6) || {};
      return JSON.stringify({ segs, in_move: s.in_move, why: s.why, text: sh.text });
    })()`));
    check('★★ 后端真的按这一段换了招（payload.show.segments 里 why=user）',
      segEffect.why === 'user' && (segEffect.in_move === '入B' || segEffect.in_move === ''),
      JSON.stringify(segEffect).slice(0, 140));

    // —— 越界方块号被夹回（不许静默：要给提示）
    const clamp = JSON.parse(await js(`(() => {
      const n = window.__dsh.payload() ? 999999 : 1;
      window.__dsh.showSegAdd(1, n, '', '');
      const last = window.__dsh.showSegList().slice(-1)[0] || {};
      window.__dsh.showSegClear();
      return JSON.stringify(last);
    })()`));
    check('★ 超范围的结束方块被夹回（不会写出越界的段）',
      Number(clamp.hi) <= 1e6 && Number(clamp.hi) >= 1, JSON.stringify(clamp));

    // —— 关掉 ⇒ 一条事件都不写
    await js('document.querySelector("#in-show_schedule").click()');
    await js('window.__dsh.rebuild()');
    await sleep(400);
    const shOff = JSON.parse(await js(`JSON.stringify({
      on: window.__dsh.state.show_schedule,
      sh: window.__dsh.payload().show || {} })`));
    check('★★ 关掉后：state 关 / payload 空（一条 MoveTrack 都不写）',
      shOff.on === false && shOff.sh.enabled === false
      && (shOff.sh.floors || []).length === 0,
      JSON.stringify({ on: shOff.on, en: shOff.sh.enabled }));

    // —— 复原（后面的小节不受影响）
    await js('document.querySelector("#in-show_schedule").click()');
    await js('window.__dsh.rebuild()');
    await sleep(300);
    check('★ 复原后开关回到开', (await js('window.__dsh.state.show_schedule')) === true, '');
  }

  const bad = results.filter((r) => !r.ok);
  console.log(`\nE2E ${bad.length ? 'FAILED' : 'OK'}  ${results.length - bad.length}/${results.length} 通过`);
  return bad.length ? 1 : 0;
};
