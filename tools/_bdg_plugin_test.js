/**
 * `bridge_plugin/renderer.js` 的离线单测 + **线格式抓取**。
 *
 *     node tools/_bdg_plugin_test.js
 *
 * 用假的 `window` / `document` / `localStorage` / `WebSocket` 把插件跑起来，
 * 验它：注册了什么、握手发了什么、去抖有没有生效、回执怎么记。
 * 最后把**插件真正发出去的每一条消息**写进
 * `tests/fixtures/bdg/_bridge_capture.json` —— 交给
 * `tests/test_bridge.py` 用**我们真正的服务端** `Bridge.handle_text()` 再吃一遍。
 *
 * 这样即使没装 BDG，也能证明「插件发的东西我们的服务端认」。
 */
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const CAPTURE = path.join(ROOT, "tests", "fixtures", "bdg", "_bridge_capture.json");
const SNAPSHOT = path.join(ROOT, "tests", "fixtures", "bdg", "snapshot_ws.bdg");
const BAR = new Array(79).join("=");

const FAIL = [];
function check(cond, msg) {
  console.log((cond ? "  [OK]   " : "  [FAIL] ") + msg);
  if (!cond) FAIL.push(msg);
}

/* ------------------------------------------------------------ 假 DOM */
function fakeEl(tag) {
  const e = {
    tagName: tag,
    children: [],
    style: { cssText: "" },
    textContent: "",
    className: "",
    value: "",
    type: "",
    placeholder: "",
    handlers: {},
    addEventListener(name, fn) {
      e.handlers[name] = fn;
    },
    appendChild(c) {
      e.children.push(c);
      return c;
    },
    fire(name) {
      if (e.handlers[name]) e.handlers[name]();
    },
  };
  return e;
}

/* ------------------------------------------------------------ 假 WebSocket */
const sent = [];
let socket = null;

function FakeWebSocket(url) {
  this.url = url;
  this.readyState = 1;
  this.onopen = null;
  this.onmessage = null;
  this.onclose = null;
  this.onerror = null;
  this.send = (t) => sent.push(t);
  this.close = () => {
    this.readyState = 3;
    if (this.onclose) this.onclose();
  };
  socket = this;
}

/* ------------------------------------------------------------ 假环境 */
const listeners = {};
const registered = { panels: [], actions: [], shortcuts: [], trackTypes: [], events: [] };
let activation = null;

global.window = {
  __bdgPluginRegister: (fn) => {
    activation = fn;
  },
  localStorage: {
    _d: {},
    getItem(k) {
      return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null;
    },
    setItem(k, v) {
      this._d[k] = String(v);
    },
  },
  WebSocket: FakeWebSocket,
};
global.WebSocket = FakeWebSocket;
global.document = { createElement: fakeEl };

/* ------------------------------------------------------------ 假 api */
const snapshot = JSON.parse(fs.readFileSync(SNAPSHOT, "utf-8"));

const api = {
  id: "dev.adocharter.bdg-bridge",
  version: "0.1.0",
  dir: "/tmp/bridge_plugin",
  log: () => {},
  project: {
    snapshot: () => JSON.parse(JSON.stringify(snapshot)),
    beatOfTime: (ms) => (ms - snapshot.offsetMs) / (60000 / snapshot.baseBpm),
  },
  selection: { current: () => ({ kind: "marker", id: "m1", markerIds: ["m1", "m2"] }) },
  player: { positionMs: () => 12345 },
  events: {
    on(name, cb) {
      listeners[name] = cb;
      registered.events.push(name);
      return () => {
        delete listeners[name];
      };
    },
  },
  ui: {
    registerPanel(def) {
      registered.panels.push(def);
      return { uid: 1, dispose() {}, open() {}, close() {}, toggle() {}, isOpen: () => true };
    },
    registerAction(def) {
      registered.actions.push(def);
      return () => {};
    },
    registerShortcut(def) {
      registered.shortcuts.push(def);
      return () => {};
    },
  },
  trackTypes: {
    register(def) {
      registered.trackTypes.push(def);
      return { ok: true };
    },
  },
  system: {
    audioPath: () => "/music/electric hornet.ogg",
    // ★ 「导入时间戳」（docs/45 §7）：假宿主也得有挑文件/读文件的能力
    pickFile: async () => TS_PATH,
    readText: async (p) => ({ canceled: false, filePath: p, content: TS_TEXT }),
  },
  callMain: async () => null,
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const parse = (t) => JSON.parse(t);
const byType = (t) => sent.map(parse).filter((m) => m.type === t);

/** 测试用的「时间戳文件」（`docs/45` §7）：8 个点，2.131 + k·150ms。 */
let TS_PATH = "C:/tmp/timestamps.txt";
const TS_TEXT = [0, 1, 2, 3, 4, 5, 6, 7]
  .map((k) => (2.131 + k * 150).toFixed(3)).join("\n") + "\n";

/* ------------------------------------------------------------ 可写假宿主（测投射） */
// 模拟宿主的 store：addMarker 走 snapped()（吸附开着就挪点），attrs 是**合并**写入。
// ★ 还得支持 `addTrack`（内置轨）/ `setBaseBpm` / `setOffset` / `beatOfTime`
//   —— 插件现在用它们（`docs/41` #1/#2）。可变锚 = 更接近真宿主的行为。
function makeWritableApi(opts) {
  opts = opts || {};
  const snapDiv = opts.snapDiv || 0;          // 0 = 关吸附（round 到 1e-6）
  const round6 = (b) => Math.round(b * 1e6) / 1e6;
  const snapped = (b) => (snapDiv ? Math.round(b * snapDiv) / snapDiv : round6(b));
  const store = { tracks: [], markers: [], seq: 0 };
  const anchor = { baseBpm: opts.baseBpm || 120, offsetMs: opts.offsetMs || 0 };
  const msPerBeat = () => 60000 / anchor.baseBpm;
  const api = {
    id: "dev.adocharter.bdg-bridge",
    version: "0.1.0",
    log: () => {},
    project: {
      timeOfBeat: (b) => anchor.offsetMs + b * msPerBeat(),
      beatOfTime: (ms) => (ms - anchor.offsetMs) / msPerBeat(),
      snapshot: () => JSON.parse(JSON.stringify({
        name: "t", baseBpm: anchor.baseBpm, offsetMs: anchor.offsetMs,
        audioName: null, audioMd5: null,
        bpmLocked: false, bpmPoints: [],
        tracks: store.tracks, markers: store.markers,
      })),
      edit: {
        batch: (fn) => fn(),
        // ★ 内置踩点轨（没有 type）—— 插件现在用这个
        //   ★★ 注意：**真宿主**在快照里把内置轨的 type 报成 `"beat"`，不是空串。
        //      假宿主第一版用了 `type: ""`，于是漏掉了「每次投射都新建一条轨」那个 bug
        //      （实测：推两次变成两条 ADO·主轨）。这里跟真宿主对齐。
        addTrack: (o) => {
          const id = "T" + store.tracks.length;
          store.tracks.push({ id, name: (o && o.name) || "Track",
                              color: "#fff", locked: false, hidden: false, type: "beat" });
          return id;
        },
        addTypedTrack: (typeKey, name) => {
          const id = "T" + store.tracks.length;
          store.tracks.push({ id, name: name || typeKey, color: "#fff", locked: false,
                              hidden: false, type: typeKey });
          return id;
        },
        setBaseBpm: (v) => { anchor.baseBpm = v; },
        setOffset: (v) => { anchor.offsetMs = v; },
        addMarker: ({ trackId, beat }) => {
          const id = "M" + store.seq++;
          store.markers.push({ id, trackId, beat: snapped(beat),
                               timeMs: api.project.timeOfBeat(snapped(beat)) });
          return id;
        },
        removeMarker: (id) => {
          store.markers = store.markers.filter((m) => m.id !== id);
        },
        setMarkerAttrs: (id, patch) => {
          const m = store.markers.find((x) => x.id === id);
          if (m) m.attrs = Object.assign({}, m.attrs || {}, patch);   // ★ 合并
        },
      },
    },
    selection: { current: () => ({ kind: null, id: null, markerIds: [] }) },
    player: { positionMs: () => 0 },
    events: { on: () => () => {} },
    ui: { registerPanel: () => ({ open() {}, toggle() {}, close() {} }),
          registerAction: () => () => {}, registerShortcut: () => () => {} },
    trackTypes: { register: () => ({ ok: true }) },
    system: {
      audioPath: () => null,
      // ★ 「导入时间戳」（docs/45 §7）：真宿主能挑文件/读文件，假宿主也得能
      pickFile: async () => TS_PATH,
      readText: async (p) => ({ canceled: false, filePath: p, content: TS_TEXT }),
    },
    callMain: async () => null,
  };
  return { api, store, anchor };
}

function mkImport(run, beats, extra) {
  const t = { role: "main", name: "ADO·主轨", clear: true,
    onsets: beats.map((b, i) => ({ idx: i, beat: b,
      attrs: { adbIdx: i, adbRun: run, adbRole: "main" } })) };
  return Object.assign({ type: "import", run, tracks: [t] }, extra || {});
}

async function E_import() {
  console.log(BAR);
  console.log("E. 投射 import（docs/38）：真的写进宿主 + 吸附如实上报");
  // ---- E1 吸附关 ⇒ 逐点无损
  let h = makeWritableApi({ snapDiv: 0 });
  let act = activation(h.api);
  await sleep(50);
  window.__adocBridge.session.handle(mkImport("R1", [0.0064, 1.91265, 3.97515]));
  const r1 = window.__adocBridge.session.lastImport;
  check(r1 && r1.n_placed === 3, `写进 3 个点（实得 ${r1 && r1.n_placed}）`);
  check(r1.n_off_grid === 0 && r1.drift_max_ms === 0,
    `★ 关吸附：零偏移（n_off_grid=${r1.n_off_grid}, drift=${r1.drift_max_ms}ms）`);
  check(h.store.tracks.length === 1
        && (!h.store.tracks[0].type || h.store.tracks[0].type === "beat"),
    "★ 建的是**内置踩点轨**（快照里 type 是 \"beat\"），不是插件轨：" +
    h.store.tracks.map((t) => t.type || "(空)").join(","));
  check(h.store.tracks[0].name === "ADO·主轨",
    "轨名仍然是 ADO·主轨（用户一眼看得出角色）：" + h.store.tracks[0].name);
  check(h.anchor && h.anchor.baseBpm === 120 && h.anchor.offsetMs === 0,
    "★ 假宿主的锚没被乱改（载荷没带 baseBpm 时不动它）");
  check(h.store.markers[0].attrs.adbIdx === 0 && h.store.markers[0].attrs.adbRun === "R1",
    "★ 对账标记写进了 attrs（且是合并写入，不冲掉别的字段）");
  check(Math.abs(h.store.markers[1].beat - 1.91265) < 1e-12,
    "非网格 beat 原样落进去：" + h.store.markers[1].beat);
  act();

  // ---- E2 吸附开 1/4 档 ⇒ 必须如实报出来
  h = makeWritableApi({ snapDiv: 4 });
  act = activation(h.api);
  await sleep(50);
  window.__adocBridge.session.handle(mkImport("R2", [0.0064, 0.62, 1.91265]));
  const r2 = window.__adocBridge.session.lastImport;
  check(r2.n_off_grid === 3, `★ 3 个点被挪（实得 ${r2.n_off_grid}）`);
  check(r2.drift_max_ms > 25, `★ 最大偏移 ${r2.drift_max_ms}ms 被报出来（>25ms 预算）`);
  check(r2.drift_over >= 1, `超预算计数 ${r2.drift_over}`);
  check(h.store.markers.map((m) => m.beat).join(",") === "0,0.5,2",
    "点确实被吸附挪走了（0.0064→0 / 0.62→0.5 / 1.91265→2）："
      + h.store.markers.map((m) => m.beat).join(","));
  act();

  // ---- E2b ★★ 把**我们的时序锚**交过去，并用 ms 换算拍位（docs/41 #2）
  //   宿主的锚一开始是 120/0；我们发 baseBpm=180 / offsetMs=1000。
  //   若插件的顺序错了（先算拍位再设锚），beat 会是 2/4 而不是 0/3 —— 这条能抓住。
  h = makeWritableApi({ snapDiv: 0, baseBpm: 120, offsetMs: 0 });
  act = activation(h.api);
  await sleep(50);
  window.__adocBridge.session.handle({
    type: "import", run: "R-ANCHOR", baseBpm: 180, offsetMs: 1000,
    tracks: [{ role: "main", name: "ADO·主轨", clear: true,
      onsets: [{ idx: 0, beat: -999, ms: 1000, attrs: { adbIdx: 0, adbRun: "R-ANCHOR" } },
               { idx: 1, beat: -999, ms: 2000, attrs: { adbIdx: 1, adbRun: "R-ANCHOR" } }] }],
  });
  const ra = window.__adocBridge.session.lastImport;
  check(h.anchor.baseBpm === 180 && h.anchor.offsetMs === 1000,
    `★ 我们的时序锚被采用了（bpm=${h.anchor.baseBpm} offset=${h.anchor.offsetMs}ms）`);
  check(ra && ra.anchor && ra.anchor.baseBpm === 180, "回执里也报了用的锚（不静默）");
  check(ra.via_ms === 2, `★ 2 个点走的是 ms→beat 换算（实得 ${ra && ra.via_ms}）`);
  check(h.store.markers.map((m) => Math.round(m.beat * 1e6) / 1e6).join(",") === "0,3",
    "★ 拍位是**用新锚**算的（1000ms→0 拍 / 2000ms→3 拍，180bpm）；"
      + "若先算拍位再设锚就会是 -2/-1：" + h.store.markers.map((m) => m.beat).join(","));
  check(Math.abs(h.store.markers[1].timeMs - 2000) < 1e-6,
    `★ 回读 timeMs 回到我们给的毫秒（${h.store.markers[1].timeMs} vs 2000）`);
  check(ra.n_off_grid === 0 && ra.drift_max_ms === 0,
    `★ 关吸附 + 锚对齐 ⇒ 零漂移（n_off_grid=${ra.n_off_grid} drift=${ra.drift_max_ms}）`);
  act();

  // ---- E2c 载荷没带 ms（旧版）⇒ 退回用 beat，且不动锚
  h = makeWritableApi({ snapDiv: 0, baseBpm: 120, offsetMs: 0 });
  act = activation(h.api);
  await sleep(50);
  window.__adocBridge.session.handle(mkImport("R-OLD", [0, 2.5]));
  const ro = window.__adocBridge.session.lastImport;
  check(ro && ro.n_placed === 2 && ro.via_ms === 0,
    `旧载荷（无 ms）仍能写点（placed=${ro && ro.n_placed} via_ms=${ro && ro.via_ms}）`);
  check(h.anchor.baseBpm === 120 && h.anchor.offsetMs === 0, "旧载荷不动宿主锚");
  check(h.store.markers.map((m) => m.beat).join(",") === "0,2.5", "旧载荷用 beat 原样落");
  act();

  // ---- E3 用户手加的点不许被下一批清掉
  h = makeWritableApi({ snapDiv: 0 });
  act = activation(h.api);
  await sleep(50);
  const sess = window.__adocBridge.session;
  sess.handle(mkImport("R3", [0, 1, 2]));
  // 用户自己在这条轨上加一个点（没有 adbIdx）
  const tid = h.store.tracks[0].id;
  const uid = h.api.project.edit.addMarker({ trackId: tid, beat: 9 });
  check(h.store.markers.length === 4, "现在 3 个我们的 + 1 个用户的");
  sess.handle(mkImport("R4", [0, 1, 2, 3]));      // 再投一次
  const kept = h.store.markers.filter((m) => m.id === uid);
  check(kept.length === 1, "★ 用户手加的点**没被清掉**（只清带 adbIdx 的）");
  check(window.__adocBridge.session.lastImport.n_cleared === 3,
    `清掉上一批 3 个（实得 ${window.__adocBridge.session.lastImport.n_cleared}）`);
  check(h.store.markers.length === 5, `投完后 = 4 个我们的 + 1 个用户的（实得 ${h.store.markers.length}）`);
  check(h.store.tracks.length === 1,
    "★★ 投两次**只该有一条轨**（真机踩过：内置轨的 type 是 \"beat\"，"
    + `用 !t.type 匹配会每次新建一条 ⇒ 两条轨 + 点翻倍）。实得 ${h.store.tracks.length} 条`);
  act();

  // ---- E3b ★★ 真机回归：连续投两次，轨数不涨、点数不翻倍
  h = makeWritableApi({ snapDiv: 0 });
  act = activation(h.api);
  await sleep(50);
  window.__adocBridge.session.handle(mkImport("D1", [0, 1, 2]));
  window.__adocBridge.session.handle(mkImport("D2", [0, 1, 2]));
  window.__adocBridge.session.handle(mkImport("D3", [0, 1, 2]));
  check(h.store.tracks.length === 1,
    `★★ 投三次仍然只有 1 条轨（实得 ${h.store.tracks.length}）`);
  check(h.store.markers.length === 3,
    `★★ 投三次点数不累积（实得 ${h.store.markers.length}，应为 3）`);
  check(window.__adocBridge.session.lastImport.n_cleared === 3,
    "★ 第三批清掉了第二批的 3 个（clear 真的生效了）");
  // 浮点 ε 不算「被挪」
  h = makeWritableApi({ snapDiv: 0, baseBpm: 180, offsetMs: 1000 });
  act = activation(h.api);
  await sleep(50);
  window.__adocBridge.session.handle({
    type: "import", run: "EPS", baseBpm: 180, offsetMs: 1000,
    tracks: [{ role: "main", name: "ADO·主轨", clear: true,
      onsets: [0, 1, 2, 3, 4, 5].map((i) => ({
        idx: i, ms: 1000 + i * (60000 / 180),
        attrs: { adbIdx: i, adbRun: "EPS" } })) }],
  });
  const re = window.__adocBridge.session.lastImport;
  check(re.n_off_grid === 0 && re.drift_max_ms === 0,
    `★★ 整拍点不许报「被挪」（真机踩过：>1e-9 把浮点 ε 也算上，`
    + `报了 5 个「被挪」而 drift=0，自相矛盾）。实得 n_off_grid=${re.n_off_grid}`);
  act();

  // ---- E3c ★★ 真机回归（docs/42）：**多条泳道**不许塌成一条轨
  //   真机踩过：按 `adbRole` 兜底找轨 ⇒ 4 条主轨泳道全指向 trk0，
  //   然后每条的 clear 把上一条刚放的清掉（631 点只落 83、548 被清又被拒）。
  h = makeWritableApi({ snapDiv: 0, baseBpm: 180, offsetMs: 0 });
  act = activation(h.api);
  await sleep(50);
  window.__adocBridge.session.handle({
    type: "import", run: "LANES", baseBpm: 180, offsetMs: 0,
    tracks: [
      { role: "main", lane: "main:0", name: "ADO·主轨 trk0", clear: true,
        onsets: [0, 1, 2].map((i) => ({ idx: i, ms: i * (60000 / 180),
          attrs: { adbIdx: i, adbRun: "LANES", adbRole: "main", adbTrack: 0 } })) },
      { role: "main", lane: "main:1", name: "ADO·主轨 trk1", clear: true,
        onsets: [0, 1].map((i) => ({ idx: 10 + i, ms: i * (60000 / 180) + 5,
          attrs: { adbIdx: 10 + i, adbRun: "LANES", adbRole: "main", adbTrack: 1 } })) },
      { role: "dp", lane: "dp:", name: "ADO·双押轨", clear: true,
        onsets: [{ idx: 20, ms: 1000,
          attrs: { adbIdx: 20, adbRun: "LANES", adbRole: "dp" } }] },
    ],
  });
  const rl = window.__adocBridge.session.lastImport;
  const names = h.store.tracks.map((t) => t.name).sort().join(",");
  check(h.store.tracks.length === 3,
    `★★ 3 条泳道 ⇒ **3 条轨**（实得 ${h.store.tracks.length}：${names}）`);
  check(h.store.markers.length === 6,
    `★★ 点不丢（3+2+1=6，实得 ${h.store.markers.length}）`);
  check(rl && rl.n_placed === 6 && !rl.n_lane_collision,
    `★ 6 个点全落地、没有泳道塌陷（placed=${rl && rl.n_placed} `
    + `collision=${rl && rl.n_lane_collision}）`);
  check(names === "ADO·主轨 trk0,ADO·主轨 trk1,ADO·双押轨",
    `★ 轨名各带源轨后缀、各占一条：${names}`);
  const per = {};
  for (const m of h.store.markers) per[m.trackId] = (per[m.trackId] || 0) + 1;
  check(Object.values(per).sort().join(",") === "1,2,3",
    `★ 每条的条数 = 3/2/1：${JSON.stringify(per)}`);
  act();
  return true;
}

/* ------------------------------------------------------------ F 返回数据 */
/** ★★ 「返回数据到谱面生成器」（`docs/45`）：把带时值数据的**轨**整条收回来。
 *
 *  用户口径：「我们的工具使用的音轨就是 BDG 里面带时值数据的音轨」。
 *  所以这里的验收线是：
 *    · 一条 BDG 轨 = 我们那边的一条音轨（**按轨分组**，不是按泳道键）；
 *    · 用户自己新建的轨**不搬**（那是他的素材）；
 *    · 轨上**用户新加的点**照搬并计数；
 *    · 毫秒用宿主算好的 `timeMs`；
 *    · 没有我们的轨时**明确说出来**，不假装成功。
 */
async function F_back() {
  console.log(BAR);
  console.log("F. 返回数据到谱面生成器（docs/45）");

  /* ---- F1 真的投一批进去，再整条收回来（出去什么、回来什么）---- */
  let h = makeWritableApi({ snapDiv: 0, baseBpm: 400, offsetMs: 2.131 });
  let act = activation(h.api);
  await sleep(60);
  window.__adocBridge.session.handle({
    type: "import", run: "RB", baseBpm: 400, offsetMs: 2.131,
    tracks: [
      { role: "main", lane: "main:0", name: "ADO·主轨 trk0", clear: true,
        onsets: [0, 1, 2].map((i) => ({ idx: i, ms: 2.131 + i * 150,
          attrs: { adbIdx: i, adbRun: "RB", adbRole: "main", adbTrack: 0 } })) },
      { role: "dp", lane: "dp:", name: "ADO·双押轨", clear: true,
        onsets: [{ idx: 3, ms: 2.131 + 600,
          attrs: { adbIdx: 3, adbRun: "RB", adbRole: "dp" } }] },
    ],
  });
  // 用户自己在我们的轨上加一个点（没有标记），又新建一条自己的轨
  const hostTrack = h.store.tracks.find((t) => t.name === "ADO·主轨 trk0");
  h.api.project.edit.addMarker({ trackId: hostTrack.id, beat: 100 });
  const ownId = h.api.project.edit.addTrack({ name: "我的素材" });
  h.api.project.edit.addMarker({ trackId: ownId, beat: 7 });

  const s = window.__adocBridge.session;
  const p = s.collectBack();
  check(!!p, "collectBack 有东西（不是空手而归）");
  check(p.tracks.length === 2,
    `★ 一条 BDG 轨 = 我们的一条音轨：2 条（实得 ${p.tracks.length}：`
    + `${p.tracks.map((t) => t.name).join(",")}）`);
  check(p.tracks.map((t) => t.role).join(",") === "main,dp",
    "按角色排序（主 → 双押）：" + p.tracks.map((t) => t.role).join(","));
  const nm = p.tracks[0];
  check(nm.points.length === 4,
    `★ 用户新加的点照搬（3+1=4，实得 ${nm.points.length}）`);
  check(p.n_added === 1, `新加计数 = ${p.n_added}`);
  check(nm.points[3].idx === null, "新加的点没有 idx（null = 我们没投过它）");
  check(p.run === "RB", `批次号取多数派：${p.run}`);
  check(p.anchor && p.anchor.baseBpm === 400 && p.anchor.offsetMs === 2.131,
    `带上宿主的锚：${JSON.stringify(p.anchor)}`);
  check(Math.abs(nm.points[1].ms - (2.131 + 150)) < 1e-6,
    `毫秒用宿主算的 timeMs（${nm.points[1].ms}）`);
  check(!p.tracks.some((t) => t.name === "我的素材"),
    "★★ 用户自己的轨**不搬**（那是他的素材，不是我们的谱）");
  check(p.tracks[1].src_track === null, "双押没有源轨维（它本身就是单开那条轨）");

  /* ---- F2 发出去：type=tracks，而且能被服务端认（tests/test_bridge.py 复验）---- */
  sent.length = 0;
  s.ws = { readyState: 1, send: (t) => sent.push(t) };
  s.connected = true;
  const ok = s.sendBack();
  await sleep(20);
  const back = sent.map(parse).filter((m) => m.type === "tracks").pop();
  check(ok && !!back, "sendBack 真的发了 type=tracks");
  check(back && back.tracks.length === 2 && back.n_points === 5,
    `载荷自洽：${back && back.tracks.length} 轨 / ${back && back.n_points} 点`);
  check(back && back.tracks[0].points[0].src_tracks.join(",") === "0",
    "每个点带源轨号（我们那边靠它还原泳道）");
  // 回执：报告「已返回 N 轨 / M 点」
  s.handle({ type: "ack", ok: true, n_tracks: 2, n_points: 5, n_onsets: 4,
    n_added: 1, n_dup: 0 });
  check(s.lastBack && s.lastBack.n_tracks === 2, "回执被记下来（面板要显示）");
  act();

  /* ---- F3 没有我们的轨 ⇒ 明说，不假装成功 ---- */
  const h2 = makeWritableApi({ snapDiv: 0 });
  const act2 = activation(h2.api);
  await sleep(60);
  const p2 = window.__adocBridge.session.collectBack();
  check(p2 === null, "空工程 ⇒ collectBack 明确返回 null（面板里也说了一句）");
  act2();

  return JSON.parse(JSON.stringify(back));
}


/* ------------------------------------------------------------ G 导入时间戳 */
/** ★★ 「毫秒时间戳 → BDG」（`docs/45` §7）：插件那条箭头的前半段。
 *
 *  验收线：
 *    · 四种文本格式都能解析（一行一个数 / CSV 取最后一列 / mm:ss.xxx / JSON）；
 *    · **先问我们**要网格（`type:"grid"`）再摆点 —— 格子数学只有一个真源；
 *    · 摆完的点落在 k/div 上、且带上我们的标记（这样「返回数据」能整条收回）；
 *    · 锚被设成我们的（`baseBpm/offsetMs`）；
 *    · 没连上我们时不假装成功（按宿主当前锚硬摆 + 明说）。
 */
async function G_ts_import() {
  console.log(BAR);
  console.log("G. 导入毫秒时间戳（docs/45 §7）");

  const { parseTimestamps } = require(path.join(ROOT, "bridge_plugin", "renderer.js"));
  check(typeof parseTimestamps === "function", "解析器被导出（可离线测）");
  const p1 = parseTimestamps("691\n882\n1091\n");
  check(p1.join(",") === "691,882,1091", "一行一个数：" + p1.join(","));
  const p2 = parseTimestamps("# 注释\n0,691\n1,882 extra\n");
  check(p2.join(",") === "691,882", "CSV 取每行最后一个数：" + p2.join(","));
  const p3 = parseTimestamps("0:00.691\n1:02.500\n");
  check(p3.join(",") === "691,62500", "mm:ss.xxx：" + p3.join(","));
  const p4 = parseTimestamps("[691, 882, 1091]");
  check(p4.join(",") === "691,882,1091", "JSON 数组：" + p4.join(","));
  const p5 = parseTimestamps('{"timestamps": [691, 882]}');
  check(p5.join(",") === "691,882", "JSON 带键：" + p5.join(","));

  // ---- G2 连着 ⇒ 先问网格，再摆点
  const h = makeWritableApi({ snapDiv: 0 });
  const act = activation(h.api);
  await sleep(60);
  const s = window.__adocBridge.session;
  sent.length = 0;
  s.ws = { readyState: 1, send: (t) => sent.push(t) };
  s.connected = true;
  const job = s.importTimestamps();          // 不 await：先看它发了什么
  let gm = null;
  for (let i = 0; i < 40 && !gm; i++) {      // pickFile/readText 都是异步的，等一下
    await sleep(20);
    gm = sent.map(parse).filter((m) => m.type === "grid").pop();
  }
  check(!!gm && gm.times && gm.times.length === 8,
    `★ 先问我们要网格（type=grid，${gm && gm.times && gm.times.length} 个点）`
    + `　[已发 ${sent.map((x) => parse(x).type).join(",")}]`);
  check(!!gm && typeof gm.ts === "number",
    "★ 信封的 ts（发送时刻）没被我们的数组挤掉 —— 所以键名用 times");
  s.handle({ type: "ack", ok: true, kind: "grid",
    grid: { bpm: 400, phase_ms: 2.131, div: 4, step_ms: 37.5, period_ms: 150 } });
  const rep = await job;
  check(!!rep && rep.n_placed === 8, `8 个点全落：${rep && rep.n_placed}`);
  const snap = h.api.project.snapshot();
  check(Math.abs(snap.baseBpm - 400) < 1e-9 && Math.abs(snap.offsetMs - 2.131) < 1e-9,
    `★ 锚被设成我们的：bpm=${snap.baseBpm} offset=${snap.offsetMs}`);
  check(snap.markers.every((m) => Math.abs(m.beat * 4 - Math.round(m.beat * 4)) < 1e-6),
    "★ 点全落在 k/4 上（不会被宿主的吸附挪）");
  const trk = h.store.tracks.find((t) => t.name === "ADO·时间戳");
  check(!!trk, "建了一条「ADO·时间戳」轨");
  check(snap.markers.every((m) => m.attrs && m.attrs.adbRole === "main"
    && m.attrs.adbSrc === "ts" && m.attrs.adbRun),
    "★ 每个点都打上我们的标记（「返回数据」才收得回来）");
  check(snap.markers.filter((m) => m.attrs.adbIdx === 0).length === 1,
    "adbIdx 从 0 开始（是身份，不是行号）");
  act();

  // ---- G3 没连上 ⇒ 按宿主当前锚硬摆，并且**明说**
  const h2 = makeWritableApi({ snapDiv: 0, baseBpm: 120, offsetMs: 0 });
  const act2 = activation(h2.api);
  await sleep(60);
  const s2 = window.__adocBridge.session;
  s2.connected = false;
  s2.ws = null;
  const rep2 = await s2.importTimestamps();
  check(rep2 && rep2.grid === null && rep2.n_placed === 8,
    `没连上也能摆（硬摆 ${rep2 && rep2.n_placed} 点，grid=null）`);
  const snap2 = h2.api.project.snapshot();
  check(snap2.baseBpm === 120, "没连上时**不动**宿主的锚");
  check(!!(s2.logs || []).find((x) => x.indexOf("没连上") >= 0),
    "★ 明说了「没连上 ⇒ 可能被吸附挪动」（不许静默）");
  act2();

  // ---- G4 读不到文件 ⇒ 明确说话
  const h3 = makeWritableApi({ snapDiv: 0 });
  const act3 = activation(h3.api);
  await sleep(50);
  const s3 = window.__adocBridge.session;
  s3.api = Object.assign({}, h3.api, {
    system: Object.assign({}, h3.api.system, {
      pickFile: async () => null,
      readText: async () => ({ canceled: true }),
    }),
  });
  const rep3 = await s3.importTimestamps();
  check(rep3 === undefined, "取消选文件 ⇒ 干脆什么都不做（undefined）");
  act3();
}


async function main() {
  console.log(BAR);
  console.log("A. 注册与 DOM");
  require(path.join(ROOT, "bridge_plugin", "renderer.js"));

  check(typeof activation === "function", "renderer.js 自注册到 __bdgPluginRegister");
  if (!activation) process.exit(1);

  const dispose = activation(api);
  check(typeof dispose === "function", "activate 返回了 dispose");
  check(
    registered.trackTypes.map((t) => t.id).join(",") === "main,sub,dp,off",
    "注册 4 条角色轨：" + JSON.stringify(registered.trackTypes.map((t) => t.id)),
  );
  check(
    registered.trackTypes.every((t) => t.color && t.trackName && Array.isArray(t.fields)),
    "每条角色轨都有 color / trackName / fields（宿主 TrackTypeSchema 要的字段齐全）",
  );
  check(registered.panels.length === 1 && registered.panels[0].id === "bridge", "注册了桥面板");
  check(registered.shortcuts.length >= 1, "注册了快捷键 " + registered.shortcuts[0].combo);

  const host = fakeEl("div");
  const unmount = registered.panels[0].mount(host);
  check(host.children.length > 0, "面板 mount 出 DOM（" + host.children.length + " 个节点）");
  check(typeof unmount === "function", "mount 返回清理函数");
  check(
    [...registered.events].sort().join(",") === "playhead,project,selection",
    "订阅事件（挂在面板上，随 mount 生效）：" + registered.events.join(","),
  );
  const wrap = host.children[0];
  const input = wrap.children[2];
  const row = wrap.children[3];
  const btnConnect = row.children[0];
  const btnPush = row.children[1];
  check(input && input.placeholder.indexOf("ws://") === 0, "地址输入框有占位提示");

  console.log(BAR);
  console.log("B. 连接 / 握手 / 去抖");
  input.value = "ws://127.0.0.1:8765/ws?token=TESTTOKEN";
  input.fire("change");
  btnConnect.fire("click");
  check(socket !== null && socket.url === input.value, "点连接 ⇒ 连的是填的地址：" + (socket && socket.url));

  sent.length = 0;
  socket.onopen();
  await sleep(30);
  const hello = byType("hello")[0];
  check(!!hello, "开连即发 hello");
  check(hello && hello.v === 1 && hello.token === undefined, "hello 不打 token（token 在 URL 里）");
  check(hello && hello.caps && hello.caps.snapshot === true, "hello 带 caps（能力表）");
  const audioMsg = byType("audio")[0];
  check(audioMsg !== undefined, "开连即报音频路径：" + (audioMsg || {}).path);

  await sleep(450);                       // 等首次 project 落下去
  check(byType("project").length === 1, "开连推 1 次全量快照");

  sent.length = 0;
  for (let i = 0; i < 10; i++) if (listeners.project) listeners.project();
  await sleep(500);
  const np = byType("project").length;
  check(np === 1, "★ 10 次 project 事件去抖成 1 条（实得 " + np + "）");
  const proj = byType("project")[0];
  check(proj && proj.project.markers.length === 866, "快照 866 个点");
  check(proj && proj.project.markers[0].timeMs !== undefined, "点自带 timeMs（宿主算的）");
  check(proj && proj.project.version === undefined, "快照没有 version 字段（我们要按形状识别）");

  btnPush.fire("click");
  await sleep(30);
  check(byType("project").length === 2, "「立即推一次」绕过去抖");

  console.log(BAR);
  console.log("C. 回执与节流");
  socket.onmessage({ data: JSON.stringify({ v: 1, type: "accepted", accepted: [1] }) });
  socket.onmessage({
    data: JSON.stringify({ v: 1, type: "ack", ok: true, n_tracks: 6, n_points: 866, n_bpm_events: 2, dup_beats: 232 }),
  });
  check(true, "accepted / ack 被消化（不抛）");
  socket.onmessage({ data: JSON.stringify({ v: 1, type: "failed", error: "token 不匹配" }) });
  socket.onmessage({ data: "这不是 JSON" });
  check(true, "failed / 坏 JSON 不炸");

  sent.length = 0;
  for (let i = 0; i < 20; i++) {
    if (listeners.playhead) listeners.playhead();
    if (listeners.selection) listeners.selection();
  }
  await sleep(250);
  check(byType("playhead").length === 1, "20 次 playhead 被节流成 1 条");
  const ph = byType("playhead")[0];
  const want = (12345 - snapshot.offsetMs) / (60000 / snapshot.baseBpm);
  check(ph && Math.abs(ph.beat - want) < 1e-9, "playhead beat 换算正确：" + ph.beat);
  check(byType("selection").length === 1, "20 次 selection 被节流成 1 条");

  console.log(BAR);
  console.log("D. 抓取线格式（交给 Python 侧用真服务端复验）");
  fs.writeFileSync(
    CAPTURE,
    JSON.stringify(
      {
        _note: "tools/_bdg_plugin_test.js 抓取：bridge_plugin/renderer.js 真正发出去的消息",
        hello: hello,
        project: proj,
        audio: audioMsg,
        selection: byType("selection")[0],
        playhead: ph,
      },
      null,
      2,
    ),
    "utf-8",
  );
  console.log("  [OK]   → " + path.relative(ROOT, CAPTURE));

  unmount();
  dispose();
  check(true, "unmount / dispose 不炸");

  const backMsg = await F_back();
  await G_ts_import();

  await E_import();

  // ★ 把「返回数据」那条也抓进线格式（交给 tests/test_bridge.py 用真服务端复验）
  try {
    const cap = JSON.parse(fs.readFileSync(CAPTURE, "utf-8"));
    cap.back = backMsg;
    fs.writeFileSync(CAPTURE, JSON.stringify(cap, null, 2), "utf-8");
    console.log("  [OK]   → 抓包补上了 back（" + (backMsg ? backMsg.tracks.length : 0) + " 轨）");
  } catch (e) {
    check(false, "抓包补 back 失败：" + e.message);
  }

  console.log(BAR);
  if (FAIL.length) {
    console.log("✗ " + FAIL.length + " 项失败：");
    FAIL.forEach((m) => console.log("   - " + m));
    process.exit(1);
  }
  console.log("✓ 插件离线单测全部通过");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
