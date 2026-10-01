/**
 * 极简 CDP 遥控器（Node 24 自带 WebSocket，不需要任何依赖）。
 *
 *   node tools/_cdp.js "document.title"                 # 在「主窗」页面里求值
 *   node tools/_cdp.js "..." --target welcome
 *   node tools/_cdp.js --file tools/_probe_xxx.js       # 表达式写在文件里（免得引号地狱）
 *   node tools/_cdp.js --list
 *   node tools/_cdp.js --keys "Alt+Shift+B"             # 往页面里发组合键
 *
 * 用途：BDG 跑在 `--remote-debugging-port=9222` 时，直接读/点它的界面，
 * 这样「插件到底加载了没、面板长什么样」不用靠肉眼看截图。
 */
"use strict";

const PORT = Number(process.env.CDP_PORT || 9222);
// ★ 求值超时：长活（载入 + 重建 + 等预览挂上）会超过 15s。
//   `CDP_EVAL_TIMEOUT=180000 node tools/_cdp.js --file xxx.js`
const EVAL_TIMEOUT = Number(process.env.CDP_EVAL_TIMEOUT || 20000);

async function targets() {
  const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  return r.json();
}

function pick(list, which) {
  const pages = list.filter((t) => t.type === "page");
  if (which === "welcome") return pages.find((p) => p.url.includes("welcome")) || pages[0];
  // ★★ `main` 不能只认 dev 的 `:5173`：**打包版**（安装出来的）没有 dev server，
  //   URL 是 `.../app.asar/out/renderer/index.html` —— 只认 5173 的话会回退到
  //   `pages[0]`，而那里往往是 **welcome 窗口**。于是「插件怎么没加载」这种假故障
  //   能查半天（真机踩过：`__adocBridge` 一直 undefined，其实是在问欢迎页）。
  if (which === "index") {
    return pages.find((p) => /\/index\.html/.test(p.url)) || pages[0];
  }
  if (which === "main") {
    return pages.find((p) => !p.url.includes("welcome")
      && (/\/index\.html/.test(p.url) || p.url.includes("5173"))) || pages[0];
  }
  return pages[0];
}

class Cdp {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0;
    this.waits = new Map();
    this.ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.waits.has(m.id)) {
        const { res, rej } = this.waits.get(m.id);
        this.waits.delete(m.id);
        m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      }
    };
  }
  open() {
    return new Promise((res, rej) => {
      this.ws.onopen = () => res();
      this.ws.onerror = (e) => rej(new Error("ws error: " + (e.message || "")));
    });
  }
  send(method, params = {}, timeoutMs = EVAL_TIMEOUT) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((res, rej) => {
      this.waits.set(id, { res, rej });
      setTimeout(() => {
        if (this.waits.has(id)) {
          this.waits.delete(id);
          rej(new Error("timeout " + method + "（可用 CDP_EVAL_TIMEOUT 调大）"));
        }
      }, timeoutMs);
    });
  }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate", {
      expression: expr,
      returnByValue: true,
      awaitPromise: true,
    });
    if (r.exceptionDetails) {
      throw new Error("JS 抛错: " + JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails));
    }
    return r.result.value;
  }
  async keys(combo) {
    // "Alt+Shift+B" → CDP 的 rawKeyDown/keyUp，带 modifiers
    const parts = combo.split("+");
    const key = parts.pop();
    let mod = 0;
    if (parts.includes("Alt")) mod |= 1;
    if (parts.includes("Ctrl")) mod |= 2;
    if (parts.includes("Meta")) mod |= 4;
    if (parts.includes("Shift")) mod |= 8;
    const code = /^[A-Za-z]$/.test(key) ? "Key" + key.toUpperCase() : key;
    const vk = /^[A-Za-z]$/.test(key) ? key.toUpperCase().charCodeAt(0) : 0;
    const base = { modifiers: mod, key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk };
    await this.send("Input.dispatchKeyEvent", { type: "rawKeyDown", ...base });
    await this.send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
  }
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv[0] === "--list" || argv.length === 0) {
    const list = await targets();
    for (const t of list) console.log(`${t.type}\t${t.title}\t${t.url}`);
    return 0;
  }
  const which = argv.includes("--target") ? argv[argv.indexOf("--target") + 1] : "main";
  const list = await targets();
  const t = pick(list, which);
  if (!t || !t.webSocketDebuggerUrl) {
    console.error("找不到目标页面（宿主没带 --remote-debugging-port 跑？）");
    return 1;
  }
  const cdp = new Cdp(t.webSocketDebuggerUrl);
  await cdp.open();
  await cdp.send("Runtime.enable");

  if (argv[0] === "--keys") {
    await cdp.keys(argv[1]);
    console.log("sent keys:", argv[1], "to", t.url);
  } else if (argv[0] === "--mouse") {
    const [x, y] = String(argv[1]).split(",").map(Number);
    for (const type of ["mousePressed", "mouseReleased"]) {
      await cdp.send("Input.dispatchMouseEvent", {
        type, x, y, button: "left", clickCount: 1, buttons: type === "mousePressed" ? 1 : 0,
      });
      await new Promise((r) => setTimeout(r, 60));
    }
    console.log(`clicked (${x},${y}) in ${t.url}`);
  } else if (argv[0] === "--shot") {
    // ★ `--shot out.png [selector]`：截整页，或只截某个元素（`Page.captureScreenshot`
    //   + `clip`）。用来**从外面**确认软件里的预览画面（不必改 app 的代码）。
    const fs = require("fs");
    const file = argv[1];
    const sel = argv[2] || "";
    await cdp.send("Page.enable");
    let clip = null;
    if (sel) {
      const r = await cdp.eval(`(() => {
        const e = document.querySelector(${JSON.stringify(sel)});
        if (!e) return null;
        const b = e.getBoundingClientRect();
        return { x: b.x, y: b.y, width: b.width, height: b.height };
      })()`);
      if (!r || r.width < 2) {
        console.error("找不到元素或尺寸为 0:", sel, JSON.stringify(r));
        return 2;
      }
      clip = { x: r.x, y: r.y, width: r.width, height: r.height, scale: 1 };
    }
    const shot = await cdp.send("Page.captureScreenshot",
      clip ? { format: "png", clip, captureBeyondViewport: false }
           : { format: "png" });
    fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
    console.log("shot:", file, clip ? JSON.stringify(clip) : "(整页)");
  } else if (argv[0] === "--file") {
    const fs = require("fs");
    const expr = fs.readFileSync(argv[1], "utf-8");
    const out = await cdp.eval(expr);
    console.log(typeof out === "string" ? out : JSON.stringify(out, null, 1));
  } else {
    const out = await cdp.eval(argv[0]);
    console.log(typeof out === "string" ? out : JSON.stringify(out, null, 1));
  }
  cdp.ws.close();
  return 0;
}

main().then(
  (c) => process.exit(c),
  (e) => {
    console.error(String(e));
    process.exit(1);
  },
);
