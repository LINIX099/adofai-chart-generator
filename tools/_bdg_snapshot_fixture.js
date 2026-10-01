/**
 * 用**宿主的 tempo 实现**算出 `timeMs`，生成 `ProjectSnapshot` 形状的 fixture。
 *
 *     node tools/_bdg_snapshot_fixture.js
 *
 * ★ `buildTempoMap` 下面这段是**逐行照抄**宿主
 *   `src/renderer/src/tempo.ts`（1-113 行），只去掉了 `import type`。
 *   目的是让 fixture 里的 `timeMs` 出自**他的算法**，而不是我们自己的
 *   `core/bdg/tempo.py` —— 否则就是拿自己的答案验自己。
 *
 *   ⇒ `tests/test_bdg_parse.py` 用这份 fixture 断言：
 *     `|我们的 time_of_beat(beat) − 宿主给的 timeMs| < 1e-6 ms`
 *     这条一旦挂掉，说明我们把他的时间轴**理解错了**。
 */
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SRC = path.join(ROOT, "tests", "fixtures", "bdg", "v2_real_electric_hornet.bdg");
const OUT = path.join(ROOT, "tests", "fixtures", "bdg", "snapshot_ws.bdg");

// ======================================================================
// ↓↓↓ 以下 19 行照抄 vendor/beat_data_generator/src/renderer/src/tempo.ts ↓↓↓
const BPM_MIN = 20;
const BPM_MAX = 999;

function clampBpm(v) {
  return Math.min(BPM_MAX, Math.max(BPM_MIN, v));
}

function buildTempoMap(baseBpm, offsetMs, points) {
  const sorted = [...points]
    .filter((p) => Number.isFinite(p.beat) && p.beat > 0)
    .sort((a, b) => a.beat - b.beat);

  const seg = [];
  let curBpm = clampBpm(baseBpm);
  let curBeat = 0;
  let curTime = offsetMs;
  for (const p of sorted) {
    if (p.beat <= curBeat) continue;
    seg.push({
      beatStart: curBeat,
      beatEnd: p.beat,
      bpm: curBpm,
      timeStartMs: curTime,
      timeEndMs: null,
    });
    const durBeats = p.beat - curBeat;
    curTime += (durBeats * 60_000) / curBpm;
    curBpm = p.mode === "abs" ? clampBpm(p.value) : clampBpm(curBpm * p.value);
    curBeat = p.beat;
  }
  seg.push({
    beatStart: curBeat,
    beatEnd: null,
    bpm: curBpm,
    timeStartMs: curTime,
    timeEndMs: null,
  });

  seg.forEach((s, i) => {
    if (i + 1 < seg.length) s.timeEndMs = seg[i + 1].timeStartMs;
  });

  const msPerBeat = (bpm) => 60_000 / bpm;

  function timeOfBeat(beat) {
    if (seg.length === 0) return offsetMs;
    if (beat <= seg[0].beatStart) {
      const s = seg[0];
      return s.timeStartMs + (beat - s.beatStart) * msPerBeat(s.bpm);
    }
    for (let i = 0; i < seg.length; i++) {
      const s = seg[i];
      if (s.beatEnd === null || beat < s.beatEnd) {
        return s.timeStartMs + (beat - s.beatStart) * msPerBeat(s.bpm);
      }
    }
    const last = seg[seg.length - 1];
    return last.timeStartMs + (beat - last.beatStart) * msPerBeat(last.bpm);
  }

  return { segments: seg, timeOfBeat };
}
// ↑↑↑ 照抄结束 ↑↑↑
// ======================================================================

/** 宿主 `api.ts` 的 MarkerView 组装：`timeMs: map.timeOfBeat(m.beat)` */
function snapshot(project) {
  const map = buildTempoMap(project.baseBpm, project.offsetMs, project.bpmPoints);
  return {
    name: project.name,
    baseBpm: project.baseBpm,
    offsetMs: project.offsetMs,
    audioName: project.audioName,
    audioMd5: project.audioMd5,
    bpmLocked: project.bpmLocked === true,
    tracks: project.tracks.map((t) => ({
      id: t.id,
      name: t.name,
      color: t.color,
      locked: t.locked === true,
      hidden: t.hidden === true,
      type: t.type,
    })),
    markers: project.markers.map((m) => {
      const out = { id: m.id, trackId: m.trackId, beat: m.beat, timeMs: map.timeOfBeat(m.beat) };
      if (m.parentId !== undefined) out.parentId = m.parentId;
      if (m.loop !== undefined) out.loop = m.loop;
      if (m.attrs !== undefined) out.attrs = m.attrs;
      return out;
    }),
    bpmPoints: project.bpmPoints.map((b) => ({
      id: b.id,
      beat: b.beat,
      mode: b.mode,
      value: b.value,
    })),
  };
}

function main() {
  const project = JSON.parse(fs.readFileSync(SRC, "utf-8"));
  const snap = snapshot(project);
  fs.writeFileSync(OUT, JSON.stringify(snap, null, 2), "utf-8");
  console.log(
    "写出 " +
      path.relative(ROOT, OUT) +
      "  " +
      fs.statSync(OUT).size +
      " bytes  tracks=" +
      snap.tracks.length +
      " markers=" +
      snap.markers.length,
  );
  const last = snap.markers[snap.markers.length - 1];
  console.log(
    "抽查：beat " + last.beat + " → 宿主 timeMs " + last.timeMs +
      "（offsetMs=" + snap.offsetMs + ", 1 拍=" + (60000 / snap.baseBpm) + "ms）",
  );
}

main();
