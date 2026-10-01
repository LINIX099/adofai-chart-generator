# tools/ 导航

> **2026-10 做过一次大扫除**：从 248 个文件删到 **89 个**。
> 删掉的是**一次性探针 + 抓包日志 + 旧版源码快照 + 宿主 UI 手动调试脚本** ——
> 它们服务过某一次具体取证，任务完了就只剩噪音。
> **东西没丢**：全部在 git 历史里（见文末「怎么翻回去」）。

---

## 一、命名约定

| 前缀 | 含义 |
|---|---|
| **无前缀**（`corpus_report.py`） | **给人用的入口**：CLI 脚本 / 分析器 / 生成器。留着就是因为「还会再用」 |
| **`_` 前缀**（`_speeds.py`） | 历史惯例是「一次性探针」。**现在只留两类**：① 被 `core/` 注释点名当复现依据的；② 被代码 / 测试真调用的 |

> `_` 前缀**不代表可以随便删** —— 比如 `_speeds.py` / `_jsonrepair.py` / `_pathdata.py`
> 是 tools 内部被 import 二十多次的公共模块。

---

## 二、按用途找

### 日常生成 / 验收（README 里承诺的那条链）

| 脚本 | 干什么 |
|---|---|
| `gen_from_source.py` | **无头全流程**：源 → 求解 → 双押 → 上色 → 调度 → 导出 → 校验 |
| `corpus_report.py` | 任意谱面目录的指标体检（直线 / 多押 / Twirl / SS / 2 的幂 / 网格…） |
| `corpus_p12_15.py` | P12~P15 逐张指标 + **P10~P90 判据**（README §2.3 那张表就是它出的） |
| `verify_osn1.py` | 交付验收：语料对照 + 同曲参照并排 + 规则 + 几何 + 逐按键反解 |
| `sweep_osn1.py` | 参数扫描台：一批配置 → 重建 → 导出 → 自动打分 |
| `align_chart_midi.py` | 谱面对 MIDI 的对齐率（① 一对一 / ② 按键覆盖） |
| `ex_benchmark.py` | 真·EX 标尺（官方关卡重制版的统计基线） |

### 语料（第三方谱面，**不入库** —— 见 `../EXTERNAL_ASSETS.md`）

`tuf_api.py` · `tuf_index.py` · `tuf_pick.py` · `tuf_download.py` · `tuf_report.py` ·
`tuf_ex_diff.py` · `scan_adofai_events.py` · `scan_tile_look.py` ·
`analyze_*.py`（7 个）· `read_adofai.py` · `read_patterns.py` · `passage_stats.py`

**路径不写死**，走环境变量（见文末）。

### 生成「能直接进游戏看」的验收谱 / 演示谱

`make_rhythm_demo.py` · `make_dp_config_demo.py` · `make_doublepress.py` ·
`make_doublepress_adofai.py` · `make_triplet_demo.py` · `make_handswitch_demo.py` ·
`make_appearance_demo.py` · `make_camera_demo.py` · `make_show_demo.py` ·
`make_calibration.py` · `make_pattern_skeletons.py`

产物落在 `out/`（已 gitignore）。

### 打包 / 分发

`make_runtime.py`（拼便携 Python 运行时）· `pack_verify.py`（包内自检）·
`make_src_package.py` / `make_algo_package.py`（打源码 zip）

### 宿主联动（BDG 桥接，见 `../bridge_plugin/README.md`）

`host.js` · `_cdp.js` · `_bdg_install_plugin.py` · `_bdg_plugin_test.js` ·
`_host_test.js` · `_shotmain.ps1` · `_probe_points.js` · `_probe_popup.js`

> ★ `host.js` / `_cdp.js` 是 **`app/package.json` 与 `sidecar/hostctl.py` 真调用的**，
> 便携版不带它们（联动功能在包里是关的）。

### 公共模块（被 import 二十多次，别删）

`_speeds.py`（**速度读取唯一正确实现**：`bpmMultiplier` 且**累乘**）·
`_jsonrepair.py`（宽松 JSON：尾逗号 / 缺逗号 / 裸控制字符）·
`_pathdata.py`（`angleData` / `pathData` 双格式取角）

### 测试依赖

`_ladder_freeze.py`（重冻 `test_ladder` 的 golden 哈希）·
`make_stemjson_fixtures.py` · `_bdg_make_fixtures.py`（fixture 生成器）·
`_bdg_plugin_test.js` / `_bdg_snapshot_fixture.js`（`test_bridge` 要先跑它们产抓包）

### 被 `core/` docstring 点名当**复现依据**（删了注释变死链）

`_analyze_straight.py`（直线率 37.7% 的来源）· `_seg_probe.py` · `_ext_ts_go.py` ·
`_inner_outer.py` · `snowflake_anatomy.py` · `_ogg_impulse_calib.py` ·
`_subdiv_check.py` · `_axis_probe.py` · `_dp_offset_audit.py` · `_ladder_verify.py` ·
`check_events.py` · `diag_ogg_offset.py`

---

## 三、环境变量（路径不写死盘符）

| 变量 | 默认 | 指向 |
|---|---|---|
| `ADOFAI_CORPUS` | `<仓库根>/corpus_tuf` | 社区谱面语料根 |
| `ADOFAI_WORKSHOP` | `<ADOFAI_CORPUS>/_workshop` | Steam 工坊内容（冰与火 = appid 977950） |
| `ADOFAI_GAME` | `<ADOFAI_CORPUS>/_game` | 游戏安装目录 |
| `ADOFAI_MACRO` | 空 | 上游宏解析器工程 |

```powershell
$env:ADOFAI_CORPUS = "D:\somewhere\adofaipumian"
```

---

## 四、怎么把删掉的探针翻回来

删掉的 159 个文件（一次性探针 / 日志 / 旧快照）**都在 git 历史里**：

```bash
# ① 找到删它的那次提交
git log --diff-filter=D --name-only -- tools/ | head -80

# ② 从删除前的那次提交里捞回单个文件
git show <那次提交>^:tools/_grin_grid.py > tools/_grin_grid.py

# ③ 或者一次性列出「那次提交之前 tools/ 的全貌」
git ls-tree -r --name-only <那次提交>^ tools/
```

`docs/` 里仍有许多「这个数字是拿 `tools/_xxx.py` 实测的」的引用 ——
那些脚本不在当前版本里了，按上面②从历史取即可。

**为什么删**：它们是某一次取证的现场记录，不是工具。
留着会让 `tools/` 从「89 个入口」变成「248 个文件里翻自己要的那个」，而 `docs/` 已经把结论写下来了。
