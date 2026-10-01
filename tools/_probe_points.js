(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const URL2 = "ws://127.0.0.1:18865/ws?token=omOUFp6ySoaJqO2ZTaPsb-De";
  const out = [];
  for (let i = 0; i < 20 && !window.__adocBridge; i++) await wait(500);
  if (!window.__adocBridge) return "插件钩子没出现（页面没重载成功？）";
  const br = window.__adocBridge;
  const api = br.api;
  const P = api.id;

  // 1) 建 4 条角色轨 + 放点（= 分段采音的区间边界）
  const roleTypes = { main: [0, 16, 64], sub: [32, 48], dp: [40, 44, 56], off: [8] };
  const made = [];
  api.project.edit.batch(() => {
    for (const local of Object.keys(roleTypes)) {
      const tid = api.project.edit.addTypedTrack(P + ":" + local);
      if (!tid) {
        made.push(local + ":null");
        continue;
      }
      let n = 0;
      for (const b of roleTypes[local]) {
        if (api.project.edit.addMarker({ trackId: tid, beat: b })) n++;
      }
      made.push(local + ":ok/" + n);
    }
  });
  out.push("[建轨放点] " + made.join("  "));

  const s = api.project.snapshot();
  out.push("[快照] tracks=" + s.tracks.length + " markers=" + s.markers.length);
  out.push("[类型] " + JSON.stringify(s.tracks.map((t) => t.type || "beat")));

  // 2) 开面板 + 填地址 + 连接
  br.panel.open();
  await wait(700);
  const panel = [...document.querySelectorAll("div")]
    .filter((e) => e.querySelector("input") && e.textContent.includes("ADO 谱面桥 v0.1.0"))
    .sort((a, b) => a.textContent.length - b.textContent.length)[0];
  if (!panel) return out.join("\n") + "\n[面板] 开不出来";
  const input = panel.querySelector("input");
  input.value = URL2;
  input.dispatchEvent(new Event("change", { bubbles: true }));
  await wait(300);
  const btns = [...panel.querySelectorAll("button")];
  if (!btns[0].textContent.includes("断开")) {
    btns[0].click();
    await wait(2000);
  }
  const b2 = [...panel.querySelectorAll("button")];
  b2[1].click();
  await wait(2000);
  out.push("[面板]\n" + panel.innerText);
  return out.join("\n");
})()
