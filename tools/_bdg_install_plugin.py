# -*- coding: utf-8 -*-
"""把 `bridge_plugin/` 装进 BDG 的插件目录。

    python tools\\_bdg_install_plugin.py                  # 只打印路径与现状（不动手）
    python tools\\_bdg_install_plugin.py --user           # 装到 userData/plugins（正式版）
    python tools\\_bdg_install_plugin.py --dev-root DIR   # 装到 <宿主仓库>/plugins（开发模式）
    python tools\\_bdg_install_plugin.py --user --force   # 覆盖已存在的同名目录

路径依据（`vendor/beat_data_generator/src/main/plugins.ts`）：

    43  const USER_PLUGIN_DIR = "plugins";
    46  function userPluginsDir() { return join(app.getPath("userData"), USER_PLUGIN_DIR); }
    50  function pluginRoots() {
    51    const roots = [userPluginsDir()];
    54    if (!app.isPackaged) {                 // ★ 只有开发模式才扫仓库根的 plugins/
    55      const dev = join(app.getAppPath(), "plugins");
    56      if (existsSync(dev)) roots.push(dev);
    58    }

⇒ 打包版只认 `%APPDATA%\\<应用名>\\plugins`；开发模式**额外**认 `<宿主仓库>/plugins`。

★ `app.getPath("userData")` 用的是 Electron 的 `app.getName()`，取自 `package.json` 的
  `productName`（这个仓库是 `"Beat Data Generator"`）。
  **最权威的确认方式：在宿主里点「设置 → 打开插件目录」**（`plugins.ts:361` 的
  `shell.openPath(userPluginsDir())`）—— 它打开的就是那个目录。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
SRC = os.path.join(_ROOT, "bridge_plugin")
NAME = "bridge_plugin"

# Electron: app.getName() ← package.json 的 productName
# ★★ 2026-10 真机更正：**安装版也用 `beat-data-generator`**。
#   上游 `package.json` 的 `productName` 是**空的** ⇒ `app.getName()` 回退到 `name`；
#   `build.productName`（"Beat Data Generator"）只决定**安装包/快捷方式/exe 名**。
#   所以这个顺序**必须**把 `beat-data-generator` 放前面（以前反了 ⇒ 装进错目录，
#   症状是「插件永远不加载」，查了半天）。无连字符那个只作兜底。
CANDIDATE_NAMES = ("beat-data-generator", "Beat Data Generator", "bdg", "Electron")
# ★ 只往**这两个**目录里装（BDG 的两种可能名字）；`bdg` / `Electron` 只作**发现用**的
#   候选印出来，不往里写 —— 那俩常是别的 Electron 程序留下的，塞进去只会变垃圾。
INSTALL_NAMES = CANDIDATE_NAMES[:2]


def user_data_dirs():
    out = []
    appdata = os.environ.get("APPDATA")          # Windows
    if appdata:
        for n in CANDIDATE_NAMES:
            out.append(os.path.join(appdata, n))
    home = os.path.expanduser("~")
    out.append(os.path.join(home, "Library", "Application Support", "Beat Data Generator"))
    out.append(os.path.join(home, ".config", "Beat Data Generator"))
    return out


def show():
    print("插件源:      " + SRC)
    print("             manifest id = ", end="")
    import json
    with open(os.path.join(SRC, "manifest.json"), encoding="utf-8") as f:
        print(json.load(f)["id"])
    print()
    print("候选 userData 目录（%APPDATA%\\<应用名>）：")
    print("  ★ 名字来自 Electron 的 `app.getName()` ← app 自己 package.json 的 productName：")
    print("     · 上游那个字段是**空的** ⇒ 回退到 name = `beat-data-generator`")
    print("       ⇒ **安装版（NSIS）和开发模式用的是同一个目录**（2026-10 真机实测）")
    print("     · `build.productName`（\"Beat Data Generator\"）只改安装包/快捷方式/exe 名，")
    print("       **不参与** getName() ⇒ 别照抄它建目录")
    for d in user_data_dirs():
        p = os.path.join(d, "plugins")
        mark = "存在" if os.path.isdir(d) else "还没有"
        print("  [{:<6}]  {}".format(mark, p))
    print()
    print("开发模式额外扫描： <宿主仓库>/plugins/     ← 只有 !app.isPackaged 时才生效")
    host = os.path.join(_ROOT, "vendor", "beat_data_generator", "plugins")
    if os.path.isdir(host):
        print("  （本工作区那份 clone 是 {}）".format(host))
        print("    ⇒ 那份跑 `npm run dev` 时，直接拷进去即可，不用管 userData。")
    print()
    print("★ 最权威：在宿主里点「设置 → 打开插件目录」，它打开的就是该放的位置。")


def copy_into(plugins_dir: str, force: bool):
    dst = os.path.join(plugins_dir, NAME)
    if os.path.exists(dst):
        if not force:
            print("  跳过（已存在，加 --force 覆盖）：" + dst)
            return False
        shutil.rmtree(dst)
    os.makedirs(plugins_dir, exist_ok=True)
    shutil.copytree(SRC, dst)
    n = sum(len(fs) for _, _, fs in os.walk(dst))
    print("  [OK] 装好：{}  （{} 个文件）".format(dst, n))
    return True


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--user", action="store_true", help="装到 userData/plugins")
    ap.add_argument("--dev-root", default="", help="宿主仓库根（装到它的 plugins/）")
    ap.add_argument("--force", action="store_true", help="覆盖同名目录")
    a = ap.parse_args(argv[1:])

    if not a.user and not a.dev_root:
        show()
        print()
        print("（什么都没改。要动手加 --user 或 --dev-root DIR）")
        return 0

    done = 0
    if a.user:
        # ★★ 装进**每一个已经存在**的候选目录 —— 别只挑第一个。
        #   实测过：机器上可能同时存在 `beat-data-generator`（**真·宿主在用**）和
        #   `Beat Data Generator`（可能是别的程序/旧版本/手建的）⇒ 只装第一个会装错，
        #   而且**没有任何迹象**，只是插件永远不出现（我们踩过）。
        #   多装一份没有任何副作用；一个都不存在就建首选那个并说清楚。
        cands = [d for d in user_data_dirs()
                 if os.path.basename(d) in INSTALL_NAMES]
        existing = [d for d in cands if os.path.isdir(d)]
        targets = existing or cands[:1]
        if not existing:
            print("注：{} 还不存在 ⇒ 宿主还没跑过，我照样建出来（第一次启动它会直接用）。"
                  .format(targets[0]))
        for d in targets:
            done += copy_into(os.path.join(d, "plugins"), a.force)
        if len(targets) > 1:
            print("   （装了 {} 个候选目录：{}）".format(
                len(targets), ", ".join(os.path.basename(x) for x in targets)))
    if a.dev_root:
        root = os.path.abspath(a.dev_root)
        if not os.path.isfile(os.path.join(root, "package.json")):
            print("  [!] {} 里没有 package.json ⇒ 可能不是宿主仓库根".format(root))
        done += copy_into(os.path.join(root, "plugins"), a.force)

    print()
    print("装完后：重载/重启宿主 ⇒ 顶部「插件」菜单里出现 **ADO 谱面桥**（Alt+Shift+B 开面板）。")
    print("卸载：删掉那个 {} 目录即可。".format(NAME))
    return 0 if done or True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
