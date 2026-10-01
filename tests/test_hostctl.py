# -*- coding: utf-8 -*-
"""「启动并桥接」（`sidecar/hostctl.py`）单测。

    python tests/test_hostctl.py

★ **一个真进程都不起、一个端口都不开**（除了最后那一条本地回环）。
  所有子进程调用都被替身接住 —— 单测不该去拉起一个 Electron。
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from sidecar import hostctl as HC                              # noqa: E402

FAIL = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAIL.append(msg)


def _ctl(**st):
    """一个把 `_node` / `_cdp` 全部替身掉的 HostCtl。"""
    c = HC.HostCtl(_ROOT)
    base = {"present": True, "deps": True, "pid": 0, "pid_alive": False,
            "cdp_up": False, "port": 9222}
    base.update(st)
    c.calls = []
    c.state_ret = [base]
    c.node_ret = {}

    def fake_node(args, timeout=30.0):
        c.calls.append(("node", tuple(args)))
        # 先按命令查表，再按「状态序列」推进
        if args and args[0] == "state":
            if len(c.state_ret) > 1:
                return 0, json.dumps(c.state_ret.pop(0)), ""
            return 0, json.dumps(c.state_ret[0]), ""
        return c.node_ret.get(args[0], (0, "", ""))
    c._node = fake_node
    c.cdp_ret = []
    c.cdp_calls = []

    def fake_cdp(expr, target="main", timeout=25.0):
        c.cdp_calls.append(expr)
        if c.cdp_ret:
            return 0, json.dumps(c.cdp_ret.pop(0)), ""
        return 124, "", "CDP 超时"
    c._cdp = fake_cdp
    return c


# ------------------------------------------------------------------ A
def A_inject_expr():
    print("=" * 78)
    print("A. 注入表达式：连接串里的引号/反斜杠/查询串顶不破它")
    c = _ctl()
    url = 'ws://127.0.0.1:18865/ws?token=a"b\\c&d=e'
    js = c._inject_expr(url)
    check('"adoc.bridge.url"' in js or "'adoc.bridge.url'" in js
          or json.dumps(HC.LS_KEY) in js, "带上 localStorage 的键")
    check(json.dumps(url) in js,
          "★ URL 是用 json.dumps 生成的字符串字面量（引号/反斜杠都转义好了）")
    check('\\"' in js and '\\\\' in js, "字面量里真的出现了转义（说明没裸塞）")
    check("__adocBridge" in js and ".connect()" in js, "拿插件钩子并调 connect()")
    check("插件没加载" in js, "插件不在时给得出人话原因")
    check("already" in js, "已经连上时不重复连（幂等）")

    # ★ 真正的安全性质：把这串 JS 当 JSON 的字符串回读，URL 必须原样
    lit = js.split("const U = ", 1)[1].split(", K =", 1)[0]
    check(json.loads(lit) == url, "★ 从生成的 JS 里把字面量解回来 == 原 URL（逐字节）")

    print("  注入表达式里的键/取值一律走 json.dumps —— 所以 `?`/`&`/引号都不会被解释")


# ------------------------------------------------------------------ B
def B_state_parsing():
    print("=" * 78)
    print("B. state()：认得出 host.js 的 JSON，认不出时给安全的兜底")
    c = _ctl()
    st = c.state()
    check(st["present"] is True and st["deps"] is True, f"解析出 present/deps：{st['present']}")
    check(st["cdp_up"] is False and st["port"] == 9222, "解析出 cdp_up / port")

    # 前面有杂音（比如 `    $ npm install` 那种日志行）也要能认
    c2 = _ctl()
    c2._node = lambda args, timeout=30.0: (
        0, "    $ npm install\n[OK] 宿主已装好\n" + json.dumps({"present": True, "deps": True})
        + "\n", "")
    st2 = c2.state()
    check(st2.get("present") is True, "★ 日志行混在一起也能挑出最后一行 JSON")

    # 完全拿不到 ⇒ 兜底成「什么都不知道」，**不假装成功**
    c3 = _ctl()
    c3._node = lambda args, timeout=30.0: (127, "", "找不到 node")
    st3 = c3.state()
    check(st3["present"] is False and st3["deps"] is False and st3["pid"] == 0,
          "拿不到时报「都没有」")
    check(bool(st3.get("error")), f"并且带上了原因：{st3.get('error')}")


# ------------------------------------------------------------------ C
def C_link_and_host_cmds():
    print("=" * 78)
    print("C. link / start / stop 的输出解析")
    c = _ctl()
    c.node_ret["link"] = (0, "[OK] 插件已链接（junction 有效）：…\n[OK] 插件已启用：id\n", "")
    r = c.link()
    check(r["ok"] and len(r["notes"]) == 2, f"link 收下两条 note：{len(r['notes'])}")
    check("call" in ("x"), "（占位）") if False else None

    c.node_ret["start"] = (0, '[OK] 宿主已启动（pid 4242）\n{"ok":true,"pid":4242}\n', "")
    s = c.start_host()
    check(s.get("ok") and s.get("pid") == 4242, f"start 解析出 pid：{s.get('pid')}")

    c.node_ret["stop"] = (0, '    进程已经不在了\n{"ok":true,"stopped":false,'
                             '"note":"进程已经不在了"}\n', "")
    t = c.stop_host()
    check(t.get("ok") and t.get("stopped") is False, f"stop 解析出 stopped：{t.get('stopped')}")
    u = c.stop_and_unbridge()
    check("ok" in u and "stopped" in u and "note" in u, f"stop_and_unbridge 字段齐：{sorted(u)}")


# ------------------------------------------------------------------ D
def D_fail_fast():
    print("=" * 78)
    print("D. 缺宿主/缺依赖 ⇒ **立刻**明确失败（不去起、不去等）")
    c = _ctl(present=False, deps=False)
    r = c.start_and_bridge("ws://x", progress=None)
    check(not r["ok"] and r["stage"] == "host", f"stage=host：{r.get('error')}")
    check("host:fetch" in r["error"], "★ 错误里给出**下一步该跑什么**")
    check(c.cdp_calls == [], "一个 CDP 调用都没发（没白等）")

    c2 = _ctl(present=True, deps=False)
    r2 = c2.start_and_bridge("ws://x")
    check(not r2["ok"] and r2["stage"] == "deps", f"stage=deps：{r2.get('error')}")
    check("host:fetch" in r2["error"], "也说清了要先 host:fetch")


# ------------------------------------------------------------------ E
def E_happy_path():
    print("=" * 78)
    print("E. 顺路：链接 → 起宿主 → 等 CDP → 注入 ⇒ ok（每一步都汇报）")
    HC.WAIT_CDP_S, HC.WAIT_PLUGIN_S, HC.RETRY_S = 3.0, 3.0, 0.05
    c = _ctl()
    # state()：第 1 次（预检）没在跑，第 2 次（轮询）CDP 通了
    c.state_ret = [
        {"present": True, "deps": True, "pid": 0, "pid_alive": False, "cdp_up": False},
        {"present": True, "deps": True, "pid": 11, "pid_alive": True, "cdp_up": True},
    ]
    c.node_ret["link"] = (0, "[OK] 插件已链接\n", "")
    c.node_ret["start"] = (0, '{"ok":true,"pid":11}\n', "")
    c.cdp_ret = [{"ok": True, "already": False}]
    seen = []
    r = c.start_and_bridge("ws://127.0.0.1:1/ws?token=t",
                           progress=lambda f, m: seen.append((round(f, 2), m)))
    check(r["ok"] and r.get("pid") == 11, f"成功且带上 pid：{r}")
    check(r.get("already") is False, "报出「不是本来就连着」")
    check(len(seen) >= 3, f"★ 汇报了 {len(seen)} 步（不是闷头跑）")
    check(seen[-1][0] == 1.0, f"最后一步进度是 1.0：{seen[-1]}")
    check(any("链接" in m for _f, m in seen), "汇报里有「检查插件链接」")
    check(("node", ("link",)) in c.calls and ("node", ("start",)) in c.calls,
          "真的依次跑了 link 和 start")
    check(len(c.cdp_calls) == 1, "注入只发了一次")

    # 已经在跑 + 桥已经连着 ⇒ 不重复起、不重复连
    c2 = _ctl(pid=7, pid_alive=True, cdp_up=True)
    c2.node_ret["link"] = (0, "", "")
    c2.node_ret["start"] = (9, "", "不该跑到这")
    c2.cdp_ret = [{"ok": True, "already": True}]
    r2 = c2.start_and_bridge("ws://x")
    check(r2["ok"] and r2.get("already") is True, "已经在跑时直接用，且报 already")
    check(("node", ("start",)) not in c2.calls, "★ 没有重复起宿主")


# ------------------------------------------------------------------ F
def F_failure_stages():
    print("=" * 78)
    print("F. 失败一定落到**具体阶段**并给人话（不许静默、不许假装成功）")
    HC.WAIT_CDP_S, HC.WAIT_PLUGIN_S, HC.RETRY_S = 0.6, 0.9, 0.05
    # CDP 一直不通（比如宿主是别人手动起的、没带调试端口）
    c = _ctl()
    c.state_ret = [{"present": True, "deps": True, "pid": 5, "pid_alive": True,
                    "cdp_up": False}]
    c.node_ret["link"] = (0, "", "")
    c.node_ret["start"] = (0, '{"ok":true,"pid":5,"already":true}\n', "")
    r = c.start_and_bridge("ws://1/ws?token=t")
    check(not r["ok"] and r["stage"] == "cdp", f"stage=cdp：{r.get('error')}")
    check("手动" in r["error"] and "%d" % HC.CDP_PORT in r["error"],
          "★ 告诉用户「手动把连接串贴进面板」并报出端口")
    check(r.get("url", "").startswith("ws://"), "把连接串回给 UI（面板上有复制按钮）")

    # CDP 通了但插件一直不出现
    c2 = _ctl()
    c2.state_ret = [{"present": True, "deps": True, "pid": 6, "pid_alive": True,
                     "cdp_up": True}]
    c2.node_ret["link"] = (0, "", "")
    c2.cdp_ret = []
    r2 = c2.start_and_bridge("ws://2/ws?token=t")
    check(not r2["ok"] and r2["stage"] == "inject", f"stage=inject：{r2.get('error')}")
    check("插件" in r2["error"], "说清是「没等到插件」而不是笼统的失败")
    check(len(c2.cdp_calls) >= 2, f"★ 重试过（发了 {len(c2.cdp_calls)} 次）而不是试一次就放弃")

    # 取消
    c3 = _ctl()
    c3.node_ret["link"] = (0, "", "")
    r3 = c3.start_and_bridge("ws://3", should_cancel=lambda: True)
    check(not r3["ok"] and r3["stage"] == "cancelled", f"能取消：{r3.get('stage')}")

    # 起不来
    c4 = _ctl()
    c4.node_ret["link"] = (0, "", "")
    c4.node_ret["start"] = (1, '{"ok":false,"error":"起不来：boom"}\n', "")
    r4 = c4.start_and_bridge("ws://4")
    check(not r4["ok"] and r4["stage"] == "start", f"stage=start：{r4.get('error')}")
    check("boom" in r4["error"], "把底层原因带出来")


# ------------------------------------------------------------------ G
def G_inject_real_return():
    print("=" * 78)
    print("G. inject_url 认各种回报；拿不到应答时说清「可能是缺调试端口」")
    c = _ctl()
    c.cdp_ret = [{"ok": True, "already": True}]
    check(c.inject_url("ws://x").get("already") is True, "认 ok/already")

    c2 = _ctl()
    c2.cdp_ret = [{"ok": False, "why": "插件没加载"}]
    r = c2.inject_url("ws://x")
    check(r["ok"] is False and r["why"] == "插件没加载", f"把 why 带回来：{r}")

    c3 = _ctl()          # cdp_ret 空 ⇒ 替身返回 124/超时
    r3 = c3.inject_url("ws://x")
    check(r3["ok"] is False and "CDP" in r3["why"], f"拿不到应答时说清：{r3['why']}")


def main():
    A_inject_expr()
    B_state_parsing()
    C_link_and_host_cmds()
    D_fail_fast()
    E_happy_path()
    F_failure_stages()
    G_inject_real_return()
    print("=" * 78)
    if FAIL:
        print(f"✗ {len(FAIL)} 项失败:")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("✓ 启动并桥接（hostctl）全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
