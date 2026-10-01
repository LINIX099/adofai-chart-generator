/**
 * 「照样子对比」截图器：`npx electron . --pick-look`
 *
 * 读 `out/_look/jobs.json`，逐组：
 *   ① 复位布局（e2e 会把浮窗拖到画面中间并落盘 ⇒ 会挡住截图）
 *   ② `window.__dsh.load(mid)` 载入来源，然后**手工清掉** `dp_checked` / `sub_checked`
 *      （`/api/load` 会**自动建议**双押轨 —— grin.mid 建议的是鼓轨 trk5，
 *        那正是 docs/58 §3 警告过的「鼓轨当双押会插出成百上千个双押」）
 *   ③ 逐项 `setParam(k, v)`（走界面那条路）+ `setTracks([...])`
 *   ④ `rebuild()` 等到「本轮真的落地」
 *   ⑤ 切视图 → 等**内嵌播放器真的换成新谱面**（`tiles` 对上 `nFloors+1`）→ `seek(ms)`
 *   ⑥ `capturePage(rect)` 截那一个视图元素 → `out/_look/<tag>__<view>.png`
 *
 * 作业文件格式见 `out/_look/jobs.json`。
 */
"use strict";

const path = require("node:path");
const fs = require("node:fs");

const ROOT = path.join(__dirname, "..");
const JOBS = process.env.PICK_LOOK_JOBS
  ? path.resolve(process.env.PICK_LOOK_JOBS)
  : path.join(ROOT, "out", "_look", "jobs.json");

module.exports = async function run(win) {
  const js = (code) => win.webContents.executeJavaScript(code, true);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const cfg = JSON.parse(fs.readFileSync(JOBS, "utf-8"));
  const outDir = path.resolve(__dirname, cfg.out || path.join(ROOT, "out", "_look"));
  fs.mkdirSync(outDir, { recursive: true });
  console.log("JOBS", JOBS, "→", outDir, `(${(cfg.jobs || []).length} 组)`);

  for (let i = 0; i < 150; i++) {
    // eslint-disable-next-line no-await-in-loop
    const ok = await js("!!window.__dsh").catch(() => false);
    if (ok) break;
    // eslint-disable-next-line no-await-in-loop
    await sleep(200);
  }

  const rebuildCount = async () => (await js("window.__dsh.stats()")).rebuildCount;
  const waitRebuild = async (from, maxMs = 180000) => {
    const t0 = Date.now();
    for (;;) {
      // eslint-disable-next-line no-await-in-loop
      const s = String(await js("window.__dsh.status()"));
      // eslint-disable-next-line no-await-in-loop
      const c = await rebuildCount();
      if (c > from && !/求解中|加载中|准备|开始…/.test(s)) return s;
      if (Date.now() - t0 > maxMs) return s + "（超时）";
      // eslint-disable-next-line no-await-in-loop
      await sleep(150);
    }
  };
  /** 等内嵌播放器真的换成这一轮的谱面。
   *  判据 = `tiles ≈ 本轮 lastResult.n_floors + 1`（**用本轮结果当基准**：
   *  `nFloors()` 是 overview 的口径，实测偶尔与本轮不一致，会把等待卡死）。
   *  ★ 作业之间的层数**必须互不相同**，否则「没换」和「换了」看不出来。 */
  const waitPreview = async (wantTiles, maxMs = 120000) => {
    const t0 = Date.now();
    let s = null;
    for (;;) {
      // eslint-disable-next-line no-await-in-loop
      s = await js("window.__dsh.adofaiState()");
      // eslint-disable-next-line no-await-in-loop
      const err = String(await js("window.__dsh.adofaiErr() || ''"));
      if (err) return { err };
      if (s && wantTiles > 1 && Math.abs(Number(s.tiles) - wantTiles) <= 1) return s;
      if (Date.now() - t0 > maxMs) return { stale: s, want: wantTiles, timeout: true };
      // eslint-disable-next-line no-await-in-loop
      await sleep(300);
    }
  };
  const viewRect = (sel) => js(`(() => {
    const e = document.querySelector(${JSON.stringify(sel)});
    if (!e) return null;
    const b = e.getBoundingClientRect();
    return { x: b.x, y: b.y, width: b.width, height: b.height };
  })()`);
  const shot = async (sel, file) => {
    const r = await viewRect(sel);
    if (!r || r.width < 4 || r.height < 4) {
      console.log(`SHOT-SKIP ${file} 元素没有尺寸`, JSON.stringify(r));
      return;
    }
    const img = await win.webContents.capturePage({
      x: Math.round(r.x), y: Math.round(r.y),
      width: Math.round(r.width), height: Math.round(r.height),
    });
    const p = path.join(outDir, file);
    fs.writeFileSync(p, img.toPNG());
    console.log(`SHOT ${p}  ${Math.round(r.width)}x${Math.round(r.height)}`);
  };

  // ① 复位布局（e2e 落盘的布局会把「来源与段」浮窗摆在画面正中）
  try {
    // eslint-disable-next-line no-await-in-loop
    await js(`(() => { const b = document.getElementById('btn-reset-layout');
      if (b) { b.click(); return 'reset'; } return 'no-btn'; })()`);
    // eslint-disable-next-line no-await-in-loop
    await sleep(400);
  } catch (_e) { /* 无所谓 */ }

  let bad = 0;
  const summary = [];
  for (const job of cfg.jobs || []) {
    const tag = job.tag || "job";
    console.log("=".repeat(70));
    console.log(`▶ ${tag}`);
    try {
      const mid = path.isAbsolute(job.mid) ? job.mid : path.join(ROOT, job.mid);
      // eslint-disable-next-line no-await-in-loop
      await js(`window.__dsh.load(${JSON.stringify(mid)})`);
      // eslint-disable-next-line no-await-in-loop
      await sleep(job.load_wait_ms || 900);
      // ② 参数（只改 job 点名的，其余保持 schema 默认）
      for (const [k, v] of Object.entries(job.params || {})) {
        // eslint-disable-next-line no-await-in-loop
        await js(`window.__dsh.setParam(${JSON.stringify(k)}, ${JSON.stringify(v)})`);
      }
      // ③ **不采双押 / 不采次级轨**：直接写活动 state（这两项不是 schema 字段）
      //    `/api/load` 会把「鼓轨」当默认双押轨（grin.mid → dp_checked=[5]），必须清掉。
      // eslint-disable-next-line no-await-in-loop
      await js(`(() => { const S = window.__dsh.state;
        S.dp_checked = ${JSON.stringify(job.dp || [])};
        S.sub_checked = []; return S.dp_checked.length; })()`);
      const tracks = job.tracks
        ? job.tracks
        : // eslint-disable-next-line no-await-in-loop
          (await js("(window.__dsh.loadInfo()||{}).default_tracks_checked || []"));
      // eslint-disable-next-line no-await-in-loop
      const from = await rebuildCount();
      // eslint-disable-next-line no-await-in-loop
      await js(`window.__dsh.setTracks(${JSON.stringify(tracks)})`);
      // setTracks 会重跑 onTracksChanged —— 再清一次，保证这一轮真的没双押
      // eslint-disable-next-line no-await-in-loop
      await js(`(() => { const S = window.__dsh.state;
        S.dp_checked = ${JSON.stringify(job.dp || [])};
        S.sub_checked = []; return true; })()`);
      // eslint-disable-next-line no-await-in-loop
      await js("window.__dsh.rebuild()");
      // eslint-disable-next-line no-await-in-loop
      const st = await waitRebuild(from);
      // eslint-disable-next-line no-await-in-loop
      const lr = await js("window.__dsh.lastResult() || {}");
      const lite = {
        ok: lr.ok, n_onsets: lr.n_onsets, n_floors: lr.n_floors,
        base_bpm: lr.base_bpm, display_bpm: lr.display_bpm,
        fit_mode: lr.fit_mode, dp: lr.dp, fit: lr.fit, denoise: lr.denoise,
        n_violations: lr.n_violations, violations: lr.violations,
        speed: lr.speed, overlap: lr.overlap,
        warning_list: (lr.warning_list || []).slice(0, 12),
      };
      console.log("   tracks=" + JSON.stringify(tracks)
        + "  onsets=" + lite.n_onsets + "  floors=" + lite.n_floors
        + "  dp=" + JSON.stringify(lite.dp && {
          hits: lite.dp.dp_hits, dropped: lite.dp.dropped })
        + "  base_bpm=" + lite.base_bpm);
      console.log("   status: " + String(st).slice(0, 220));
      for (const view of job.views || ["chart"]) {
        // eslint-disable-next-line no-await-in-loop
        await js(`window.__dsh.tab(${JSON.stringify(view)})`);
        let pv = null;
        if (view === "chart") {
          // eslint-disable-next-line no-await-in-loop
          pv = await waitPreview(Number(lite.n_floors || 0) + 1);
          console.log("   preview: " + JSON.stringify(pv));
        } else {
          // eslint-disable-next-line no-await-in-loop
          await sleep(400);
        }
        if (job.seek_ms) {
          // eslint-disable-next-line no-await-in-loop
          await js(`window.__dsh.seek(${Number(job.seek_ms)})`);
        }
        // eslint-disable-next-line no-await-in-loop
        await sleep(job.wait_ms || 1500);
        const sel = view === "chart" ? "#cv-adofai"
          : view === "path" ? "#cv-path"
          : view === "roll" ? "#cv-roll" : "#cv-falling";
        // eslint-disable-next-line no-await-in-loop
        await shot(sel, `${tag}__${view}.png`);
      }
      const rec = { tag, tracks, seek_ms: job.seek_ms || 0, params: job.params || {},
                    status: String(st), last: lite };
      fs.writeFileSync(path.join(outDir, `${tag}.json`),
        JSON.stringify(rec, null, 1));
      summary.push({ tag, n_onsets: lite.n_onsets, n_floors: lite.n_floors,
                     base_bpm: lite.base_bpm, dp: lite.dp, status: String(st) });
    } catch (e) {
      bad++;
      console.log(`JOB-FAIL ${tag} ${(e && e.stack) || e}`);
    }
  }
  fs.writeFileSync(path.join(outDir, "_summary.json"),
    JSON.stringify(summary, null, 1));
  console.log(`PICK-LOOK 完成：${(cfg.jobs || []).length - bad}/${(cfg.jobs || []).length}`);
  return bad ? 1 : 0;
};
