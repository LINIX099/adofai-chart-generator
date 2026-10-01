# 外部资产清单（不进仓库）

> **用户 2026-10 口径**：
> > 「任何**密钥**、任何**可能包含版权内容**的文件，都**直接放外部下载链接**，
> > 别打包在仓库。」
>
> ⇒ 仓库里**只有本项目的源码 / 文档 / 测试**（约 **6 MB**）。
> 下面这些被 `.gitignore` 排除了，需要时从对应来源取。

---

## 一、版权敏感（**不要**再分发）

| 被排除的路径 | 是什么 | 体积 | 从哪来 |
|---|---|---|---|
| `corpus_tuf/` | TUF 论坛社区谱面语料（P0~P20 / G1~G20 / U1~U20，623 张） | 272 MB | `tools/tuf_index.py` + `tools/tuf_pick.py` + `tools/tuf_download.py` 自己抓（`TUF_PROXY=127.0.0.1:7897`） |
| `samples/` | 样例谱面（含他人作品摘录） | 12 MB | 用户提供 |
| `ref_bugcode/` | 排查 bug 用的参考谱面 | 0.02 MB | 用户提供 |
| `_re_adojas/` | 第三方预览器源码（0.2 后停止维护） | 0.37 MB | 上游仓库 |
| `vendor/` | 第三方 vendored 库（`adofai_timemodel` 等） | 38 MB | 见 `NOTICE` / `THIRD-PARTY.md` 里的出处 |
| `_versions/` `_archive/` `out_prev_backup/` | 历史快照 / 归档 / 旧产物备份 | 117 MB | 本地 |
| `out/` `build/` `dist/` | 生成本地产物（**含成品谱面与原曲 ogg**）与打包产物 | 3.2 GB | 本地产出 |

## 二、音频 / MIDI（版权 + 体积，一律外部链接）

`.gitignore` 里全局排除 `*.ogg / *.mp3 / *.wav / *.flac / *.m4a / *.mid / *.midi / *.bdg / *.zip`。

| 用途 | 文件 | 外部链接 |
|---|---|---|
| 最常用的测试 MIDI（**fallen era**） | `fallen era.mid` | <https://wwbti.lanzoue.com/i3DuG3ga01ne> |
| MIDI 还原验收用（Flower Rocket） | `Flower_Rocket.mid` | 用户提供 |
| 本次交付曲的原曲 | `mad_piano_party.ogg` | 用户提供（130.513 s） |

拿到之后放在仓库**外面**或 `.gitignore` 已覆盖的位置（例如 `_assets/`，也已排除）。

### 语料目录用环境变量指定

仓库里那些扫语料的脚本（`tools/tuf_report.py`、`tools/ex_benchmark.py`、
`tools/_*.py` 探针…）**不再写死路径**，统一读环境变量：

| 变量 | 默认 | 指向 |
|---|---|---|
| `ADOFAI_CORPUS` | `<仓库根>/corpus_tuf` | 社区谱面语料根（`tools/tuf_*.py` 下载到 `corpus_tuf/`） |
| `ADOFAI_WORKSHOP` | `<ADOFAI_CORPUS>/_workshop` | Steam 工坊内容目录（冰与火 = appid 977950） |
| `ADOFAI_GAME` | `<ADOFAI_CORPUS>/_game` | 游戏安装目录 |
| `ADOFAI_MACRO` | 空 | 上游宏解析器工程（只用得到它的参考实现时） |

```bash
set ADOFAI_CORPUS=D:\somewhere\adofaipumian      # Windows
export ADOFAI_CORPUS=/home/me/adofaipumian       # *nix
```

## 三、第三方播放器 bundle（**已进仓库**）

| 路径 | 是什么 | 体积 |
|---|---|---|
| `app/renderer/vendor/adofai-player.js` | 预览用的 ADOFAI 谱面播放器（上游 Re_ADOJAS 的 `lib/Player`，rolldown 打包产物，含 three.js） | 9.33 MB |
| `app/renderer/vendor/adofai-player.js.map` | 它的 sourcemap | 12.25 MB |

**决定**：**随仓库分发**（权衡过：不发的话 clone 下来桌面端预览直接缺文件，
而「能立刻看见采音对不对」正是本项目的卖点）。出处与许可见 `NOTICE` / `THIRD-PARTY.md`。

要**自己重建**它（改了上游源码 / 升级依赖）：

```bash
git clone https://github.com/adofaiex/Re_ADOJAS _re_adojas   # 上游源码不在本仓库
cd _re_adojas && pnpm install && pnpm run embed
cp dist-embed/adofai-player.js ../app/renderer/vendor/
```

不想收这 21.6 MB：在 `.gitignore` 里加回这两行即可。

## 四、其它（体积 / 噪音，不是版权问题）

| 路径 | 体积 | 说明 |
|---|---|---|
| `app/node_modules/` | 447 MB | `cd app && npm ci` 装回 |
| `app/.logs/` `*.log` | — | 运行日志 |
| `__pycache__/` `*.pyc` | — | Python 字节码 |
| `_assets/` | — | 本任务下载到本地的往来资产（已 gitignore） |
| `_versions/` `_archive/` | 117 MB | 历史快照 / 归档（本地留着即可） |

---

## 五、密钥

**仓库里一个密钥都没有**（用正则扫过全仓库的 `.py/.js/.json/.md/.txt`，
GitHub token / OpenAI key / AWS id / 私钥块 / 通用 `api_key=` 赋值 —— **0 命中**）。

GitHub 凭据**只存在操作系统的凭据管理器**里：
`git` 用系统级 `credential.helper=manager`（Git Credential Manager），
`gh` 需要时用**单次命令**的 `GH_TOKEN`。
**任何 token 都不要写进仓库、也不要写进 `.git/config`。**
