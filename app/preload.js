/**
 * preload：把「主进程能力」按白名单暴露给渲染进程（contextIsolation 打开时
 * 渲染进程拿不到 node，只能走这里）。
 *
 * sidecar 的端口通过 `additionalArguments` 传进来，所以渲染进程不需要问主进程
 * 就能直接打 `http://127.0.0.1:<port>/api/...`。
 */
const { contextBridge, ipcRenderer } = require('electron');

const arg = process.argv.find((a) => a.startsWith('--sidecar-port='));
const port = arg ? Number(arg.split('=')[1]) : 0;

contextBridge.exposeInMainWorld('dsh', {
  port,
  base: `http://127.0.0.1:${port}`,

  // 对话框 / 系统
  openFile: () => ipcRenderer.invoke('dialog:openFile'),
  openAudio: () => ipcRenderer.invoke('dialog:openAudio'),
  openDir: (opts) => ipcRenderer.invoke('dialog:openDir', opts),
  reveal: (p) => ipcRenderer.invoke('shell:reveal', p),
  info: () => ipcRenderer.invoke('app:info'),

  // ★ UI 布局（docs/49 §5.4）：存 <userData>/ui-layout.json，下次打开复现
  layoutGet: () => ipcRenderer.invoke('ui:layout:get'),
  layoutSet: (txt) => ipcRenderer.invoke('ui:layout:set', txt),

  // 握手（--smoke 用）
  ready: (info) => ipcRenderer.send('renderer:ready', info),
  reportError: (msg) => ipcRenderer.send('renderer:error', msg),

  // 原生菜单 → 渲染进程
  onMenu: (cb) => ipcRenderer.on('menu', (_e, name) => cb(name)),
  onSidecarDown: (cb) => ipcRenderer.on('sidecar:down', (_e, d) => cb(d)),
});
