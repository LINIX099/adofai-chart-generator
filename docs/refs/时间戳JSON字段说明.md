# 时间戳 JSON 字段说明（新架构：DEMUCS 分轨 → 多路时间戳）

> 本文件对应 `app/training/extract_timestamps.py` 的输出。
> 我们**只负责**把音频拆成多条音轨、各自打出「踩点 / 音头」时间戳，输出一个干净 JSON。
> **不**生成 `.adofai` —— 那是合作方拿这份 JSON 写适配算法去做的。

---

## 一、怎么生成这份 JSON

### 命令行（一行）

```bat
cd /d D:\last_bak\adofai_diffusion
set PYTHONPATH=D:\last_bak\adofai_diffusion\venv\Lib\site-packages
D:\last_bak\adofai_diffusion\python313\python.exe app\training\extract_timestamps.py --audio "D:\你的歌.wav" --out "D:\输出.json"
```

- 不写 `--out` → 自动在**音频旁边**生成 `<歌名>_timestamps.json`
- `--no-piano` → 去掉 piano 赠品通道
- `--bpm 120` → 把 BPM 提示写进 JSON
- 同首歌重跑不重分离（分轨缓存在 `data/demucs_cache/demucs_sep/`）

### GUI（双击启动器）

侧边栏最上面「提取时间戳」页 → 选音频 → 点「提取时间戳」→ 跑完在音频同目录出 `<歌名>_timestamps.json`。

---

## 二、JSON 顶层字段

| 字段名 | 类型 | 示例 | 含义 |
|---|---|---|---|
| `version` | int | `1` | JSON 结构版本号，当前固定为 `1`，合作方做解析时据此判断 schema |
| `source_audio` | string | `"Automaton Waltz - Plum.wav"` | 输入音频的路径。**相对路径**：当音频与 JSON 同目录时，这里就是文件名本身（如上）；若用 `--out` 指定了别的目录，则与 `--out` 同基准 |
| `duration_sec` | float | `202.378` | 音频总时长（秒），保留 3 位小数 |
| `sample_rate` | int | `22050` | 统一重采样后的采样率（Hz），所有时间戳都基于这个采样率 |
| `hop_ms` | float | `5.805` | **每帧的时间长度（毫秒）**，由 `sample_rate` 与帧长算得。换算时间戳用得到（见第四节） |
| `separation_model` | string | `"htdemucs_6s"` | 实际使用的 DEMUCS 分离模型名（6 轨：含 guitar/piano） |
| `has_vocals` | bool | `true` | 是否检测到人声。为 `true` 时 `stems` 里会多出 `vocals` 这一路 |
| `bpm_hint` | float / null | `120` 或 `null` | 可选 BPM 提示（由 `--bpm` 传入），没传就是 `null`，仅供合作方参考拍速 |
| `stems` | object | `{ "melody": {...}, ... }` | **核心数据**：每路音轨的时间戳，键名见第三节 |

---

## 三、`stems` 里有哪些键

键**不是固定 6 个**，取决于音频内容：

| 键名 | 一定出现？ | 来自哪条分离轨 (`source`) | 检测器 (`method`) | 说明 |
|---|---|---|---|---|
| `melody` | ✅ 一定 | `other` | `onsetnet` | 旋律。把 DEMUCS 的 **other 轨**（除鼓/贝斯/吉他/人声/钢琴外的其余内容）喂 OnsetNet 踩点 |
| `vocals` | ⚠️ 仅 `has_vocals=true` | `vocals` | `onsetnet` | 人声。有人声时才输出，喂 OnsetNet(`onset_net_vocal.pt`) |
| `drums` | ✅ 一定 | `drums` | `spectral_flux` | 鼓点。频谱通量谱峰检测，对硬攻击最锐利 |
| `bass` | ✅ 一定 | `bass` | `spectral_flux` | 贝斯 |
| `guitar` | ✅ 一定 | `guitar` | `spectral_flux` | 吉他 |
| `piano` | ⚠️ 默认有（除非 `--no-piano`） | `piano` | `spectral_flux` | 钢琴。**赠品通道**：`htdemucs_6s` 白送的，用频谱通量打出，合作方可选是否用 |

> 注意：键名 ≠ 分离轨名。`melody` 的 `source` 其实是 `other`，`vocals` 才是真正的人声轨。
> 这样命名是给合作方看的语义（"旋律时间戳"比 "other 时间戳"直观）。

---

## 四、每条 stem 的子字段

以 `melody` 为例，每个 stem 对象结构相同：

```json
"melody": {
  "source": "other",
  "method": "onsetnet",
  "model": "onset_net_melody.pt",
  "onsets_sec": [18.0709, 18.158, 18.2857, "..."],
  "onsets_frame": [3113, 3128, 3150, "..."]
}
```

| 子字段 | 类型 | 示例 | 含义 |
|---|---|---|---|
| `source` | string | `"other"` | 这条时间戳**来自哪条 DEMUCS 分离轨**（见第三节表） |
| `method` | string | `"onsetnet"` 或 `"spectral_flux"` | 用的检测器：`onsetnet`=神经网络踩点；`spectral_flux`=频谱通量谱峰 |
| `model` | string | `"onset_net_melody.pt"` | **仅 `method=onsetnet` 时有**，标识用的权重文件名。频谱通量通道没有这个字段 |
| `onsets_sec` | float[] | `[18.0709, 18.158, 18.2857, ...]` | **主消费字段**：每个踩点/音头的时刻（秒），保留 4 位小数，已升序排列 |
| `onsets_frame` | int[] | `[3113, 3128, 3150, ...]` | 同上每个时刻对应的**帧索引**（整数），与 `onsets_sec` 一一对应、等长 |

### 换算关系（给合作方）

两个数组下标对齐，且满足近似关系：

```
onsets_sec[i] ≈ onsets_frame[i] × hop_ms / 1000
```

- `melody` / `vocals`（OnsetNet 通道）：`onsets_sec` 就是直接由 `onsets_frame × hop_ms / 1000` 算出来的。
- `drums` / `bass` / `guitar` / `piano`（频谱通量通道）：`onsets_frame` 是 librosa 帧号，`onsets_sec` 同样按同一 `hop_ms` 换算（数值上与 `frames_to_time` 一致）。

> 实战建议：直接用 `onsets_sec`，最省事；只有需要反查原始帧（比如对齐梅尔频谱）时才用 `onsets_frame`。

---

## 五、完整示例片段

```json
{
  "version": 1,
  "source_audio": "Automaton Waltz - Plum.wav",
  "duration_sec": 202.378,
  "sample_rate": 22050,
  "hop_ms": 5.805,
  "separation_model": "htdemucs_6s",
  "has_vocals": true,
  "bpm_hint": null,
  "stems": {
    "melody": {
      "source": "other", "method": "onsetnet", "model": "onset_net_melody.pt",
      "onsets_sec": [18.0709, 18.158, 18.2857],
      "onsets_frame": [3113, 3128, 3150]
    },
    "vocals": {
      "source": "vocals", "method": "onsetnet", "model": "onset_net_vocal.pt",
      "onsets_sec": [0.0058, 0.4296, 0.5341],
      "onsets_frame": [1, 74, 92]
    },
    "drums": {
      "source": "drums", "method": "spectral_flux",
      "onsets_sec": [32.0726, 33.0652, 34.023],
      "onsets_frame": [5525, 5696, 5861]
    },
    "bass": {
      "source": "bass", "method": "spectral_flux",
      "onsets_sec": [32.1364, 32.7401, 33.0826],
      "onsets_frame": [5536, 5640, 5699]
    },
    "guitar": {
      "source": "guitar", "method": "spectral_flux",
      "onsets_sec": [40.8671, 64.5166, 65.5964],
      "onsets_frame": [7040, 11114, 11300]
    },
    "piano": {
      "source": "piano", "method": "spectral_flux",
      "onsets_sec": [0.9636, 1.3061, 1.4687],
      "onsets_frame": [166, 225, 253]
    }
  }
}
```

---

## 六、合作方最小消费示例（伪代码）

```python
import json
d = json.load(open("歌名_timestamps.json", encoding="utf-8"))

# 1) 拿到全部旋律踩点时刻（秒）
melody_hits = d["stems"]["melody"]["onsets_sec"]

# 2) 有人声就顺便拿人声踩点
if d["has_vocals"]:
    vocal_hits = d["stems"]["vocals"]["onsets_sec"]

# 3) 鼓 / 贝斯 / 吉他 / 钢琴 都是同结构
for name in ("drums", "bass", "guitar", "piano"):
    if name in d["stems"]:
        hits = d["stems"][name]["onsets_sec"]

# 4) 把任意一路的秒数组直接喂进你自己的轨道生成算法即可
```

---

## 七、常见疑问

- **为什么 `melody` 的 `source` 是 `other`？**
  DEMUCS 没有专门的「旋律」轨，`other` 是「除鼓/贝斯/吉他/人声/钢琴之外的一切」，对器乐/钢琴曲而言恰好就是主旋律所在，所以拿它当旋律喂 OnsetNet。

- **`onsets_frame` 和 `onsets_sec` 用哪个？**
  直接用 `onsets_sec`（秒）即可，已经按统一 `hop_ms` 换算好、升序排列。

- **`piano` 通道要不要？**
  默认送（赠品，零额外成本）。若不需要，生成时加 `--no-piano`，或消费时忽略该键。

- **人声歌 vs 纯音乐**
  纯音乐：`has_vocals=false`，`stems` 里没有 `vocals`。人声歌：`has_vocals=true`，多一路 `vocals`。消费代码记得判存在性。
