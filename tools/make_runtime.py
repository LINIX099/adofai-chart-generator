#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拼一份**可移植的 Python 运行时**（打进便携包，用户机器上不用装 Python）。

    python tools/make_runtime.py            # 幂等：装好了就跳过
    python tools/make_runtime.py --force    # 重来

产物：`build/runtime/python/`（可直接拷走，`python.exe` 双击就能用）

为什么要这一份而不是直接拷宿主机的 Python：
  · 开发环境装的是 3.14.3，`python-3.14.3-amd64.zip` 是**官方完整树**（33.9MB），
    版本一致 ⇒ 依赖轮子（cp314）与 ABI 完全对得上，不用担心 3.14.0/3.14.2 混用。
  · ★ 3.14.3 **没有** `-embed-amd64.zip`（python.org 只给到 3.14.0 的 embed），
    所以用完整树；完整树自带 DLL（含 vcruntime），拷到干净机器也能跑。

第三方只装**音频采音**那一支要用的（`core/audio_onsets.py`）：
numpy / scipy / librosa（librosa 会带 numba、soundfile、soxr、audioread…）。
算法其余部分全是标准库 —— 所以就算这一支装不上，MIDI/.bdg 那两条路照样能用
（`sidecar/session.py` 里有懒加载 + 环境自检，见 docs/49 §10）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "runtime")
PYDIR = os.path.join(OUT, "python")
PY_VER = "3.14.3"          # 与开发机一致（`python-3.14.3-amd64.zip` 是官方完整树）
# ★ 开发环境代理（verge-mihomo 监听 7897，出口在新加坡）。**pip 直连索引会静默失败**
#   （报「from versions: none」，看着像没有轮子，其实是根本连不上）——真机踩过。
#   和 `tools/host.js` 的 DEFAULT_PROXY 是同一个。
DEFAULT_PROXY = "http://127.0.0.1:7897"

# 打进包里的那一支（音频采音用）。顺序无所谓，pip 会解析依赖。
PKGS = ["numpy", "scipy", "librosa", "soundfile", "numba"]


def proxy_alive(url: str, ms: int = 400) -> bool:
    """探一下代理端口通不通。

    ★ **探到才用**：代理关着的时候如果还把它设进环境变量，本来直连能下的东西
    也会被一个死代理挡住，报错还很难懂（真机踩过一次）。宁可不设。
    """
    try:
        u = urllib.parse.urlparse(url)
        host, port = u.hostname or "", u.port or 0
        if not host or not port:
            return False
        with socket.create_connection((host, port), timeout=ms / 1000.0):
            return True
    except OSError:
        return False


def say(s):
    print(s, flush=True)


def http_get(url, dst, expect_mb=None, tries=3):
    """下载。★ 必须能重试 + 走镜像 —— 官方源实测会 **read timeout**（120s 只下了几 MB）。"""
    last = None
    for i in range(tries):
        try:
            say("    下载(%d/%d) %s" % (i + 1, tries, url))
            tmp = dst + ".part"
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                n = 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    n += len(b)
            os.replace(tmp, dst)
            say("    %.1f MB" % (os.path.getsize(dst) / 1048576.0))
            return True
        except Exception as e:                                        # noqa: BLE001
            last = e
            say("      ！失败：%s" % e)
    say("    放弃：%s" % last)
    return False


def fetch_python_zip(zip_name: str, dst: str) -> bool:
    """★ 顺序实测定的：**镜像优先**。

    官方 `python.org` 在实测会 read timeout（60s 只下几 MB），而
    `registry.npmmirror.com/-/binary/python/` 是同一个文件、秒下。
    官方留作最后一档（别人网络环境可能相反）。
    """
    urls = [
        "https://registry.npmmirror.com/-/binary/python/%s/%s" % (PY_VER, zip_name),
        "https://mirrors.huaweicloud.com/python/%s/%s" % (PY_VER, zip_name),
        "https://www.python.org/ftp/python/%s/%s" % (PY_VER, zip_name),
    ]
    for u in urls:
        if http_get(u, dst, expect_mb=34, tries=1):
            return True
    return False


def py_tag(ver: str) -> str:
    """`3.14.3` → `314`（pip 的 `--python-version` 用它）。"""
    a, b = ver.split(".")[:2]
    return ("%s%s" % (a, b)).replace(" ", "")


def main():
    global PY_VER                      # ★ 必须在任何用到 PY_VER 的语句**之前**声明
    ap = argparse.ArgumentParser()
    ap.add_argument("--py", default=PY_VER, help="要拼的 Python 版本")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--proxy", default=DEFAULT_PROXY,
                    help="下载/pip 走的代理（`--proxy ''` 关掉）")
    ap.add_argument("--prune", action="store_true",
                    help="只对**已装好的**运行时瘦身，不重装（幂等，可反复跑）")
    ap.add_argument("--no-prune", action="store_true", help="装完不瘦身")
    a = ap.parse_args()
    PY_VER = a.py
    if a.proxy:
        if proxy_alive(a.proxy):
            # urllib 认这两个环境变量；pip 子进程也继承
            os.environ.setdefault("HTTP_PROXY", a.proxy)
            os.environ.setdefault("HTTPS_PROXY", a.proxy)
            os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
            say("    代理：" + a.proxy)
        else:
            # ★ 不许静默：说清为什么没用它（否则「明明配了代理还下不动」很费解）
            say("    代理 %s 没在监听 ⇒ **直连**（要强制用就自己设 HTTP(S)_PROXY）"
                % a.proxy)

    pyexe = os.path.join(PYDIR, "python.exe")

    # `--prune`：只瘦身（装好了也能反复跑；删完照样自检）
    if a.prune:
        if not os.path.exists(pyexe):
            say("[!] 还没装运行时，先跑一次不带 --prune 的")
            return 1
        prune(PYDIR)
        return smoke(pyexe)

    if os.path.exists(pyexe) and not a.force:
        say("[=] 运行时已就位，跳过（要重来加 --force）：" + pyexe)
        if not a.no_prune:
            say("    顺手瘦身一次（幂等）…")
            prune(PYDIR)
        return smoke(pyexe)

    if a.force and os.path.isdir(OUT):
        say("    清掉旧的 " + OUT)
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(PYDIR, exist_ok=True)

    zip_name = "python-%s-amd64.zip" % a.py
    zpath = os.path.join(OUT, zip_name)
    if not os.path.exists(zpath):
        if not fetch_python_zip(zip_name, zpath):
            say("[!] 三处镜像都下不动 —— 网络问题，不是脚本问题。")
            say("    也可以手动把 python-%s-amd64.zip 放到 %s" % (a.py, OUT))
            return 1

    say("    解包 → " + PYDIR)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(PYDIR)
    if not os.path.exists(pyexe):
        say("[!] 解包后没有 python.exe —— 包结构变了？")
        return 1

    # ★ 用**开发机**的 pip 往目标目录装（开发机就是 win_amd64/cp314，目标同平台）
    site = os.path.join(PYDIR, "Lib", "site-packages")
    os.makedirs(site, exist_ok=True)
    say("    装依赖 → " + site)
    cmd = [sys.executable, "-m", "pip", "install", "--no-warn-script-location",
           "--only-binary=:all:", "--target", site] + PKGS
    say("    $ " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        say("[!] pip 装依赖失败（返回 %d）—— 音频采音那一支会不可用，"
            "但 MIDI/.bdg 两条路不受影响" % r.returncode)
        # 不算致命：把情况说清楚，别静默
    if not a.no_prune:
        say("    瘦身…")
        prune(PYDIR)
    return smoke(pyexe)


# 可以安全删掉的（**不动任何 import 得到的东西**）：
#   · Doc/        官方完整树里带的**全套 HTML 文档**（74MB，实测最大单项）
#   · Lib/test    标准库自测（~25MB）
#   · Lib/tkinter + tcl + DLLs/tcl*、_tkinter —— 我们**没有 GUI**（界面是 Electron）
#   · Lib/idlelib / lib2to3 / ensurepip / venv —— 用不上
#   · include/ libs/ Scripts/ —— 给「嵌入/编译/命令行脚本」用的
#   · site-packages/pip —— 用户机器上不会再装包（我们要的就是「不用装」）
PRUNE_TOP = ["Doc", "tcl", "include", "libs", "Scripts"]
PRUNE_LIB = ["test", "tkinter", "idlelib", "lib2to3", "ensurepip", "venv",
             "turtledemo", "pydoc_data"]
PRUNE_SITE = ["pip", "setuptools", "wheel",
              # ★★ sklearn 41MB + narwhals 5MB —— **实测可以不装**：
              #   librosa 的元数据里写了 `Requires-Dist: scikit-learn>=1.6`，但代码里
              #   只有 `librosa/decompose.py` 的**文档字符串**和 NMF 那条函数用到它。
              #   我们真正调的两条路（`onset_detect` / `decompose.hpss`）都不碰 sklearn
              #   —— 用**打包的解释器**实测过：挪走 sklearn 后 hpss 照样出结果。
              #   少了它只是「用 sklearn 的 NMF 做分解」不可用，我们不用那个。
              "sklearn", "narwhals", "threadpoolctl"]


def prune(pydir: str) -> int:
    """瘦身。返回省下的字节数。**只删确定用不上的**（删完必须再跑一次 smoke）。"""
    freed = 0

    def rm(p):
        nonlocal freed
        if not os.path.exists(p):
            return
        s = 0
        if os.path.isdir(p):
            s = sum(os.path.getsize(os.path.join(r, f))
                    for r, _d, fs in os.walk(p) for f in fs
                    if os.path.exists(os.path.join(r, f)))
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                s = os.path.getsize(p)
                os.remove(p)
            except OSError:
                s = 0
        freed += s
        say("      - %-42s %7.1f MB" % (os.path.relpath(p, pydir), s / 1048576.0))

    for n in PRUNE_TOP:
        rm(os.path.join(pydir, n))
    for n in PRUNE_LIB:
        rm(os.path.join(pydir, "Lib", n))
    for n in PRUNE_SITE:
        rm(os.path.join(pydir, "Lib", "site-packages", n))
    # tkinter 的 DLL（在 DLLs/ 和根下）
    for n in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "tclpip86t.dll",
              "zlib1.dll"):
        for sub in ("", "DLLs"):
            rm(os.path.join(pydir, sub, n))
    # 其它解释器（我们只用 python.exe）
    rm(os.path.join(pydir, "pythonw.exe"))
    # __pycache__：**保留** —— 删了首次启动要重编译，得不偿失（README 里说明）
    say("    瘦身共省 %.1f MB" % (freed / 1048576.0))
    return freed


def smoke(pyexe: str) -> int:
    """★ 必须用**这个** python.exe 自己去 import —— 在开发机上 import 成功不算数。"""
    say("    自检（用打包的这个解释器）：")
    code = (
        "import sys, importlib\n"
        "print('    python', sys.version.split()[0], sys.executable)\n"
        "ok = True\n"
        "for m in ('numpy','scipy','librosa','soundfile','numba'):\n"
        "    try:\n"
        "        mod = importlib.import_module(m)\n"
        "        print('      OK  %-10s %s' % (m, getattr(mod,'__version__','?')))\n"
        "    except Exception as e:\n"
        "        ok = False\n"
        "        print('      --  %-10s %s: %s' % (m, type(e).__name__, e))\n"
        "print('    AUDIO_OK' if ok else '    AUDIO_DEGRADED')\n"
    )
    r = subprocess.run([pyexe, "-c", code], cwd=ROOT)
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
