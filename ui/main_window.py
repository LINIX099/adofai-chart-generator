"""主窗口：采音台 + 生成器 + 双预览。

布局
  左：文件 / 音轨列表 / 采音参数 / 求解参数 / 元信息 / 导出
  中：钢琴卷帘 | 谱面路径 | 4K 下落式
  下：传输条（播放/停止/进度/音量）+ 状态栏
"""
from __future__ import annotations

import bisect
import os
import tempfile
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)

from core import midi as midi_mod
from core import onsets as onsets_mod
from core import solve as solve_mod
from core import synth, verify, writer
from core import audio_onsets as audio_mod
from core import dp_midspin
from core import dp_angle

# ★ 有 OGG/WAV 就能做谱：走 `core.audio_onsets`（音头检测），
#   产出的对象和 `midi_mod.load()` 同构，下游一行都不用改。
#   用音频源比用转谱 MIDI 更可靠 —— 转谱会丢细分的音
#   （实测五月雪版 FallenEra 的 MIDI 里完全没有 55.6ms 的三连音十六分，
#    而 OGG 里有 159 个，`16 16 8 8` 这类配置在 MIDI 上根本不可能命中）。
AUDIO_EXTS = (".ogg", ".oga", ".wav", ".flac", ".mp3")
from ui.falling_view import FallingView
from ui.chart_view import ChartView
from ui.path_view import PathView
from ui.piano_roll import PianoRoll


class NoWheelFilter(QObject):
    """数值框不该抢滚轮。

    PySide 默认让 QSpinBox/QDoubleSpinBox/QComboBox 在鼠标悬停时就吃掉滚轮，
    于是"想滚动参数面板"会变成"悄悄改掉某个数值"（用户实测：求解/几何单元过于敏感）。
    规则改成：**只有已经拿到键盘焦点的数值框才响应滚轮**，其余一律忽略。
    """

    def eventFilter(self, obj, ev):                       # noqa: N802
        if ev.type() == QEvent.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            if not obj.hasFocus():
                ev.ignore()
                return True
        return False


APP_QSS = """
QMainWindow, QWidget { background: #14181e; color: #d5dde6; }
QGroupBox { border: 1px solid #2a333d; border-radius: 6px; margin-top: 10px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #8fb7d9; }
QPushButton { background: #22303c; border: 1px solid #334456; border-radius: 4px; padding: 4px 10px; }
QPushButton:hover { background: #2b3d4c; }
QPushButton:pressed { background: #1a2530; }
QListWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0e1319; border: 1px solid #2a333d; border-radius: 4px; padding: 2px 4px; }
QListWidget::item:selected { background: #2f5d80; }
QTabBar::tab { background: #1b232c; padding: 5px 14px; border: 1px solid #2a333d; }
QTabBar::tab:selected { background: #2f5d80; }
QStatusBar { color: #9fb0c0; }
QLabel#hint { color: #7d8b99; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADOFAI Chart Generator v0.1 — MIDI 采音台")
        self.resize(1560, 940)
        self.setStyleSheet(APP_QSS)
        self.setFont(QFont("Microsoft YaHei UI", 9))

        self.midi: midi_mod.MidiFile | None = None
        self.midi_path: str = ""
        self.source_audio: str | None = None    # 音频源（OGG/WAV）路径，MIDI 源时为 None
        self.onsets: list = []
        self.chart: solve_mod.Chart | None = None
        self.chart_times: list[float] = []
        self.audio_path: str | None = None
        self._audio_key = None
        self.dp_info: str = ""
        self.dp_report: dict = {}

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(0.7)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self._on_pos)
        self.player.playbackStateChanged.connect(self._on_state)

        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(140)
        self._rebuild_timer.timeout.connect(self.rebuild)

        self._nowheel = NoWheelFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._nowheel)

        self._build_ui()
        self._on_track_changed()

    # =================================================================== UI
    def _build_ui(self):
        bar = self.menuBar()
        m = bar.addMenu("文件")
        for text, fn, sc in (("打开 MIDI…", self.open_midi, "Ctrl+O"),
                             ("导出谱面…", self.export_chart, "Ctrl+S")):
            a = QAction(text, self)
            a.setShortcut(sc)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        a = QAction("退出", self); a.triggered.connect(self.close); m.addAction(a)

        mh = bar.addMenu("帮助")
        a = QAction("关于 / 参数说明", self); a.triggered.connect(self.show_about); mh.addAction(a)

        split = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(split)

        # ---------------- 左栏 ----------------
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.setSpacing(8)

        box_f = QGroupBox("① 文件")
        bf = QVBoxLayout(box_f)
        row = QHBoxLayout()
        b = QPushButton("打开 MIDI…"); b.clicked.connect(self.open_midi)
        row.addWidget(b)
        b2 = QPushButton("示例▾")
        b2.clicked.connect(self._sample_menu)
        row.addWidget(b2)
        bf.addLayout(row)
        self.lbl_file = QLabel("未加载")
        self.lbl_file.setObjectName("hint")
        self.lbl_file.setWordWrap(True)
        bf.addWidget(self.lbl_file)
        lv.addWidget(box_f)

        box_t = QGroupBox("② 音轨（勾选要采音的轨）")
        bt = QVBoxLayout(box_t)
        self.cb_scope = QComboBox()
        self.cb_scope.addItems(["主轨 + 补空白（推荐）",
                                "单轨：只采光标那条",
                                "多轨：全部非鼓（全采）",
                                "多轨：含鼓（全采）"])
        self.cb_scope.setToolTip(
            "**采音取舍**：\n\n"
            "  主轨 + 补空白  ← 推荐。节奏线还是主轨那条，只在主轨出现空白的地方\n"
            "                    （超过③里的「补空白阈值」）从其它轨补音。\n"
            "  单轨           ← 最干净，但别的声部在响的地方会变成空白音，\n"
            "                    求解器只能扭轨道/塞速度事件去填。\n"
            "  多轨全采       ← 把伴奏、内声部一起采进来，那已经不是任何一条音乐线了，\n"
            "                    形状会很怪（FallenEra 直线掉到 35%）。\n\n"
            "实测（samples 三首）：\n"
            "  单轨      onset 565~849   空白 5~9 处   直线 60%\n"
            "  补空白    onset 766~1277  空白 0 处      直线 48~66%\n"
            "  全采      onset 957~2331  空白 0 处      直线 35~73%")
        self.cb_scope.currentIndexChanged.connect(self._on_scope_changed)
        bt.addWidget(self.cb_scope)
        self.cb_primary = QComboBox()
        self.cb_primary.addItems(["主轨 = 光标选中的那条（手动）",
                                  "主轨 = 平均音高最高（旋律启发式）",
                                  "主轨 = 平均力度最大",
                                  "主轨 = 音符最多",
                                  "主轨 = 音域最宽"])
        self.cb_primary.setToolTip(
            "哪条轨是「主轨」直接决定整张谱的节奏线与形状。\n\n"
            "实测各启发式（samples）：\n"
            "  音符最多     ← 最差。MemoryLocked 会挑到低音伴奏，\n"
            "                 SetSpeed 密度 21/100 格（EX 标尺是 1.35）\n"
            "  平均音高最高 ← 三首样本都挑到旋律轨，最稳\n"
            "  平均力度最大 ← 结果同上\n\n"
            "⚠ 自动只是起点。最终还是要靠光标手动点着试 —— \n"
            "   哪条音乐线你听着对，就是哪条。")
        self.cb_primary.currentIndexChanged.connect(self._on_primary_changed)
        bt.addWidget(self.cb_primary)
        # —— 双押轨：可多选。双押轨只当**门控**，落点永远取主音那一层
        self.lst_dp = QListWidget()
        self.lst_dp.setMaximumHeight(104)
        self.lst_dp.setToolTip(
            "**双押从哪条轨采**（可勾多条，取并集）。\n\n"
            "规则：**主音有音时双押，否则空过**。\n"
            "  双押轨只是「这里还有一只手」的信号；真正插双押的位置是\n"
            "  **主音那一层**（所以落点永远在主音格上，不会跑进 Pause 里）。\n"
            "  双押轨响了但主音当时没音 —— 那一下没有东西可以「双」，直接空过。\n\n"
            "做法：在主音格前面插一对 [折返格, midspin 999]，999 与该格\n"
            "同一瞬间按下 ⇒ 真·双押；折返格 travel 取最小步长，所以落点\n"
            "就在主音上（亚毫秒级）。插入零净偏移，前后时序一个都不动。\n\n"
            "勾了双押轨之后，它**不会**再参与底部采音（不算主轨/补空白）。")
        self.lst_dp.itemChanged.connect(self._on_track_changed)
        bt.addWidget(self.lst_dp)
        row_dp = QHBoxLayout()
        row_dp.addWidget(QLabel("双押判定窗口"))
        self.sp_dptol = QDoubleSpinBox()
        self.sp_dptol.setRange(1.0, 400.0); self.sp_dptol.setValue(45.0)
        self.sp_dptol.setSuffix(" ms")
        self.sp_dptol.setToolTip(
            "双押轨的音头与主音相隔多少毫秒之内算「同一下」。\n"
            "窗口越小 → 双押越少越准；越大 → 越容易把两下凑成一次。")
        self.sp_dptol.valueChanged.connect(self._schedule)
        row_dp.addWidget(self.sp_dptol)
        row_dp.addWidget(QLabel("写法"))
        self.cb_dpmode = QComboBox()
        self.cb_dpmode.addItems(["中旋双押", "角度双押"])
        self.cb_dpmode.setToolTip(
            "中旋双押：在目标格前插 [折返格, midspin 999] —— 999 那格 travel=0，\n"
            "  两下**同一瞬间**按下（真·同时）。零净偏移。\n\n"
            "角度双押：把目标格拆成 [θ, T−θ]（θ = 15°/30°，按有效 BPM 选）——\n"
            "  两下相隔 1/12 ~ 1/6 拍，落在同一判定窗口。总 travel 不变 ⇒ 零时长偏移。\n"
            "  默认用**反向写法**（缺口第 1 格带 Twirl，自动写补角）：高密度下轨道不会\n"
            "  原路重合（实测重叠对数只有正常写法的 ~7%）。\n"
            "  薄格撞 SetSpeed 时自动退回正常写法（Twirl 不能与 SetSpeed 同格）。")
        self.cb_dpmode.currentIndexChanged.connect(self._schedule)
        row_dp.addWidget(self.cb_dpmode)
        row_dp.addStretch(1)
        bt.addLayout(row_dp)
        self.lst_tracks = QListWidget()
        self.lst_tracks.setMinimumHeight(150)
        self.lst_tracks.currentRowChanged.connect(self._on_track_changed)
        self.lst_tracks.itemChanged.connect(self._on_item_changed)
        bt.addWidget(self.lst_tracks)
        self.lbl_track = QLabel("—"); self.lbl_track.setObjectName("hint"); self.lbl_track.setWordWrap(True)
        bt.addWidget(self.lbl_track)
        lv.addWidget(box_t)

        box_o = QGroupBox("③ 采音")
        fo = QFormLayout(box_o)
        self.sp_merge = QDoubleSpinBox(); self.sp_merge.setRange(0, 500); self.sp_merge.setValue(30)
        self.sp_merge.setSuffix(" ms"); self.sp_merge.setToolTip("间隔小于此值的音合并成一次按键")
        self.cb_anchor = QComboBox(); self.cb_anchor.addItems(["first", "loudest"])
        self.cb_anchor.setToolTip("合并时取簇里最早的音，还是力度最大的音")
        self.sp_minvel = QSpinBox(); self.sp_minvel.setRange(0, 127); self.sp_minvel.setValue(1)
        self.sp_minint = QDoubleSpinBox(); self.sp_minint.setRange(0, 2000); self.sp_minint.setValue(0)
        self.sp_minint.setSuffix(" ms"); self.sp_minint.setToolTip("相邻按键最小间隔（稀疏化）")
        self.sp_maxonset = QSpinBox(); self.sp_maxonset.setRange(0, 200000); self.sp_maxonset.setValue(0)
        self.sp_maxonset.setToolTip("0=不限。按力度保留前 N 个")
        self.sp_plo = QSpinBox(); self.sp_plo.setRange(0, 127); self.sp_plo.setValue(0)
        self.sp_phi = QSpinBox(); self.sp_phi.setRange(0, 127); self.sp_phi.setValue(127)
        self.sp_fillgap = QDoubleSpinBox()
        self.sp_fillgap.setRange(0, 8000); self.sp_fillgap.setValue(2000)
        self.sp_fillgap.setSuffix(" ms")
        self.sp_fillgap.setToolTip(
            "「主轨 + 补空白」模式下：主轨出现多长的空白，才去别的轨补音。\n"
            "调小 → 补得多（更接近全采）；调大 → 补得少（更接近单轨）。\n"
            "0 = 全部补上（等于把其它轨全并进来）。")
        fo.addRow("合并窗口", self.sp_merge)
        fo.addRow("合并取点", self.cb_anchor)
        fo.addRow("最小力度", self.sp_minvel)
        fo.addRow("最小间隔", self.sp_minint)
        fo.addRow("最大音数", self.sp_maxonset)
        fo.addRow("音高下限", self.sp_plo)
        fo.addRow("音高上限", self.sp_phi)
        fo.addRow("补空白阈值", self.sp_fillgap)
        for w in (self.sp_merge, self.sp_minvel, self.sp_minint, self.sp_maxonset,
                  self.sp_plo, self.sp_phi, self.sp_fillgap):
            w.valueChanged.connect(self._schedule)
        self.cb_anchor.currentIndexChanged.connect(self._schedule)
        lv.addWidget(box_o)
        self.box_onset = box_o

        box_s = QGroupBox("④ 求解 / 几何")
        fs = QFormLayout(box_s)
        self.cb_straight = QComboBox()
        self.cb_straight.addItems(["少（省速度事件）", "平衡（推荐）", "多（尽量直线）"])
        self.cb_straight.setCurrentIndex(1)
        self.cb_straight.setToolTip(
            "「一条直线（180°）值多少个 SetSpeed 事件」。\n\n"
            "真谱实测（语料 296 谱 / 79 万层）：直线占 37.7%，是绝对第一；\n"
            "SetSpeed 事件密度 1%~12%。\n"
            "本生成器的目标就是落进这个区间：让音乐里**最常出现的音值变成直线**，\n"
            "长音用 1/2、1/3、1/4 的速度档接住（真谱里的 snails 干的就是这件事）。")
        self.cb_quant = QCheckBox("量化到音值网格（推荐）"); self.cb_quant.setChecked(True)
        self.cb_quant.setToolTip(
            "把每个间隔吸附到「几分音符」再算角度。\n"
            "MIDI 不直接存音值，但能精确算出来：拍数 = Δtick / PPQ。\n"
            "超过 4 拍的间隔按休止处理，保持精确不吸附。")
        self.cb_autobpm = QCheckBox("自动选基准 BPM 与参考音值"); self.cb_autobpm.setChecked(True)
        self.cb_autobpm.setToolTip(
            "自动时求解器遍历所有候选参考音值（1/32…16 拍），\n"
            "选 `直线占比 − λ×事件占比` 最大的那个。")
        self.sp_bpm = QDoubleSpinBox(); self.sp_bpm.setRange(10, 4000); self.sp_bpm.setValue(180)
        self.sp_bpm.setSuffix(" BPM")
        self.sp_bpm.setToolTip("基准 BPM（= 一条 180° 直线占的时长换算）。取消自动后可手改。")
        self.cb_ref = QComboBox()
        self.cb_ref.addItems(["自动（推荐）", "1/16 拍", "1/8 拍", "1/8 附点",
                              "1/4 拍", "1/4 附点", "1/2 拍", "1 拍"])
        self.cb_ref.setCurrentIndex(0)
        self.cb_ref.setToolTip("「一条直线 = 几分音符」。从参考音值反解基准 BPM = 歌曲拍速 ÷ 音值。")
        self.sp_bpmmax = QDoubleSpinBox(); self.sp_bpmmax.setRange(60, 2000)
        self.sp_bpmmax.setValue(400); self.sp_bpmmax.setSuffix(" BPM")
        self.sp_bpmmax.setToolTip("基准 BPM 上限。太大 → 倒计时（cd×一拍）会被压成几十毫秒。")
        self.cb_setspeed = QCheckBox("允许减速档（蜗牛）")
        self.cb_setspeed.setChecked(True)
        self.cb_setspeed.setToolTip(
            "关掉后行星绝对匀速，但 Δt ≥ 2 倍参考音值的长音无法表达（会被夹断、整谱失同步）。\n"
            "开启时长音用 1/2、1/3、1/4 的速度档接住 —— 真谱也是这么干的。")
        self.cb_twirlmode = QComboBox()
        self.cb_twirlmode.addItems(["逐步交替（推荐）", "累积限角", "逐步打分", "完全不使用"])
        self.cb_twirlmode.setToolTip(
            "Twirl = 免费翻转这一层的转向符号，零时间成本，但**是全局状态**。\n\n"
            "实测（真谱参照：Twirl 18%、路径密度 0.25）：\n"
            "  逐步交替   Twirl ~15%   ← 铺得最开，最接近真谱\n"
            "  完全不使用  Twirl  0%    ← 行星锁在原地打转，比有旋转难看得多\n\n"
            "结论：旋转**不能去掉**。去掉它行星会绕一个小多边形空转，那才是真的鬼畜。\n"
            "（直线层的转角是 0，翻不翻都一样，所以 Twirl 只会出现在拐角层上。）")
        self.sp_twirlmax = QDoubleSpinBox(); self.sp_twirlmax.setRange(90, 1080)
        self.sp_twirlmax.setValue(240); self.sp_twirlmax.setSuffix("°")
        self.sp_twirlmax.setToolTip("「累积限角」模式用：累积转角超过它就翻转一次。越小图标越多但铺得越开")
        self.cb_tpl = QCheckBox("用节奏型模板（主体路径）"); self.cb_tpl.setChecked(True)
        self.cb_tpl.setToolTip(
            "匹配 patterns/templates.json 里的手写节奏型，直接套用模板的角度与 Twirl；\n"
            "匹配不上才交给下面的 DP 兜底。\n"
            "模板来源：A 均分 / B 强弱拍 / C 摇摆拍子 / 几种三角形（共 15 个）。")
        self.cb_tplonly = QCheckBox("模板只修非直线（保住直线为主）"); self.cb_tplonly.setChecked(True)
        self.cb_tplonly.setToolTip(
            "0.5 拍的音值有两条路：\n"
            "  速度×2 → 走 180° 直线（DP 的做法）\n"
            "  90° 弧 → 模板 A2「八分×2」\n"
            "勾上 = 只在 DP 会给出非直线的地方才套模板（直线占住）；\n"
            "取消 = 模板能匹配就套，形状完全由模板说了算（直线会掉到 30% 上下）。")
        self.cb_pause = QCheckBox("长休止用 Pause 事件（推荐）"); self.cb_pause.setChecked(True)
        self.cb_pause.setToolTip(
            "音乐长时间没声音时，不要硬对音把轨道扭得奇奇怪怪：\n"
            "这一格走一条直线（180° = 1 拍），剩下的时间全交给 Pause。\n"
            "典型：67000ms 的休止，原来会变成 k=512 的爬行格（travel 158.9°），\n"
            "现在 = travel 180° + Pause 451 拍。")
        self.sp_pausebeats = QDoubleSpinBox()
        self.sp_pausebeats.setRange(0.5, 64.0); self.sp_pausebeats.setValue(4.0)
        self.sp_pausebeats.setSuffix(" 拍")
        self.sp_pausebeats.setToolTip("间隔超过这么多拍才算「长休止」。调太小会让 SetSpeed 变多。")

        # ---- 魔法阵（雪花）----
        self.cb_snow = QCheckBox("魔法阵（雪花）"); self.cb_snow.setChecked(False)
        self.cb_snow.setToolTip(
            "等间隔够长的段落，整段换成「魔法阵」：\n"
            "  一朵雪花 = N 条闭合花瓣，都从同一个中心出发、又回到同一个中心\n"
            "  全程**绝对匀速**（每格时长完全相同，speed ∝ 该格转角）\n"
            "  N=4（正方形包围盒）或 N=6（正六边形包围盒）\n"
            "雪花段的速度档不受「2 的幂」约束 —— 这是唯一豁免区。")
        self.sp_snowmin = QSpinBox()
        self.sp_snowmin.setRange(4, 400); self.sp_snowmin.setValue(10)
        self.sp_snowmin.setSuffix(" 格")
        self.sp_snowmin.setToolTip("段长低于这个数绝对不用雪花（用户口径：10）")
        self.sp_snowfull = QSpinBox()
        self.sp_snowfull.setRange(8, 2000); self.sp_snowfull.setValue(48)
        self.sp_snowfull.setSuffix(" 格")
        self.sp_snowfull.setToolTip("段长到这个数就 100% 用雪花；之间线性升权（10→0%，48→100%）")
        self.cb_snown = QComboBox()
        self.cb_snown.addItems(["自动 6~12", "只要 6 重", "只要 8 重", "只要 12 重"])
        self.cb_snown.setToolTip("旋转阶数，不低于 6（用户口径：6 以下的花瓣不好看）。6 重 = 正六边形包围盒" )
        fs.addRow(self.cb_autobpm)
        fs.addRow(self.cb_quant)
        fs.addRow("基准 BPM", self.sp_bpm)
        fs.addRow("一条直线 = ", self.cb_ref)
        fs.addRow("BPM 上限", self.sp_bpmmax)
        fs.addRow("直线优先", self.cb_straight)
        fs.addRow(self.cb_setspeed)
        fs.addRow("Twirl 策略", self.cb_twirlmode)
        fs.addRow("Twirl 阈值", self.sp_twirlmax)
        fs.addRow(self.cb_tpl)
        fs.addRow(self.cb_tplonly)
        fs.addRow(self.cb_pause)
        fs.addRow("Pause 阈值", self.sp_pausebeats)
        fs.addRow(self.cb_snow)
        fs.addRow("雪花起用", self.sp_snowmin)
        fs.addRow("雪花 100%", self.sp_snowfull)
        fs.addRow("雪花对称", self.cb_snown)
        for w in (self.sp_bpm, self.sp_bpmmax, self.sp_twirlmax, self.sp_pausebeats):
            w.valueChanged.connect(self._schedule)
        for w in (self.sp_snowmin, self.sp_snowfull):
            w.valueChanged.connect(self._schedule)
        for w in (self.cb_autobpm, self.cb_setspeed, self.cb_quant,
                  self.cb_tpl, self.cb_tplonly, self.cb_pause, self.cb_snow):
            w.stateChanged.connect(self._schedule)
        for w in (self.cb_straight, self.cb_ref, self.cb_twirlmode, self.cb_snown):
            w.currentIndexChanged.connect(self._schedule)
        lv.addWidget(box_s)
        self.box_solve = box_s

        box_m = QGroupBox("⑤ 时序 / 导出")
        fm = QFormLayout(box_m)
        self.sp_cd = QSpinBox(); self.sp_cd.setRange(1, 12); self.sp_cd.setValue(4)
        self.sp_cd.setToolTip("社区约定 = 4。倒计时占掉 (cd−1) 拍，"
                              "开谱到第一次按下一共 cd 拍（第 0 层是开局站位，travel 固定 180°）。")
        self.cb_sepcd = QCheckBox("倒计时与歌曲分开计时"); self.cb_sepcd.setChecked(False)
        self.lbl_timing = QLabel("—"); self.lbl_timing.setObjectName("hint")
        self.lbl_timing.setWordWrap(True)
        self.ed_song = QLineEdit()
        self.ed_artist = QLineEdit()
        self.ed_author = QLineEdit("ADOFAI Chart Generator")
        self.sp_offset = QDoubleSpinBox(); self.sp_offset.setRange(-600000, 600000)
        self.sp_offset.setSuffix(" ms")
        self.sp_offset.setValue(0)
        self.sp_offset.setToolTip("谱师听音乐写的值：谱面 t=0 对应的音频时刻。\n"
                                  "**默认 0，你自己听、自己调** —— 调到进游戏对得上为止。\n"
                                  "（勾下面那个才会自动写成「首个 onset + 前置静音」，那是一拧就准的配方）")
        self.cb_autooffset = QCheckBox("自动 = 首个 onset（配合前置静音音频）")
        self.cb_autooffset.setChecked(False)
        self.cb_autooffset.setToolTip(
            "勾上 = 走「零误差配方」：把 (cd 拍) 的静音前置到导出的音频里，offset 写成首个 onset。\n"
            "这样命中时刻误差是 0 —— 但**你必须用我们随包导出的那份音频**。\n"
            "用原曲的话请取消勾选，自己听 offset。")
        self.sp_diff = QSpinBox(); self.sp_diff.setRange(0, 25); self.sp_diff.setValue(0)
        fm.addRow("countdownTicks", self.sp_cd)
        fm.addRow(self.cb_sepcd)
        fm.addRow(self.lbl_timing)
        fm.addRow("曲名", self.ed_song)
        fm.addRow("艺术家", self.ed_artist)
        fm.addRow("作者", self.ed_author)
        fm.addRow(self.cb_autooffset)
        fm.addRow("offset", self.sp_offset)
        fm.addRow("难度", self.sp_diff)
        for w in (self.sp_cd, self.sp_offset):
            w.valueChanged.connect(self._schedule)
        for w in (self.cb_sepcd, self.cb_autooffset):
            w.stateChanged.connect(self._schedule)
        lv.addWidget(box_m)

        rowb = QHBoxLayout()
        b = QPushButton("重新生成"); b.clicked.connect(self.rebuild)
        rowb.addWidget(b)
        b = QPushButton("导出谱面…"); b.clicked.connect(self.export_chart)
        rowb.addWidget(b)
        lv.addLayout(rowb)
        lv.addStretch(1)

        wrap = QScrollArea(); wrap.setWidget(left); wrap.setWidgetResizable(True)
        wrap.setMinimumWidth(360); wrap.setMaximumWidth(460)
        split.addWidget(wrap)

        # ---------------- 中栏 ----------------
        mid = QWidget(); mv = QVBoxLayout(mid); mv.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.roll = PianoRoll(); self.roll.seekRequested.connect(self.seek)
        self.pathv = PathView()
        self.falling = FallingView()
        self.chartv = ChartView()
        self.chartv.seekRequested.connect(self.seek_floor)
        self.tabs.addTab(self.chartv, "★ 谱面预览")
        self.tabs.addTab(self.roll, "钢琴卷帘")
        self.tabs.addTab(self.pathv, "谱面路径（验打结）")
        self.tabs.addTab(self.falling, "4K 下落式（验采音）")
        mv.addWidget(self.tabs)

        # 谱面预览参数条
        cb = QHBoxLayout()
        cb.addWidget(QLabel("可见格数"))
        self.sp_cspan = QSpinBox(); self.sp_cspan.setRange(6, 400)
        self.sp_cspan.setValue(34)
        self.sp_cspan.valueChanged.connect(self._update_chartview)
        cb.addWidget(self.sp_cspan)
        self.cb_cfollow = QCheckBox("跟随播放头"); self.cb_cfollow.setChecked(True)
        self.cb_cfollow.stateChanged.connect(self._update_chartview)
        cb.addWidget(self.cb_cfollow)
        self.cb_ctravel = QCheckBox("按 travel 上色")
        self.cb_ctravel.setToolTip("暖色 = 急转（快）／冷色 = 缓（慢），直线接近中性的青灰")
        self.cb_ctravel.stateChanged.connect(self._update_chartview)
        cb.addWidget(self.cb_ctravel)
        self.cb_cbad = QCheckBox("标出贴太近"); self.cb_cbad.setChecked(True)
        self.cb_cbad.stateChanged.connect(self._update_chartview)
        cb.addWidget(self.cb_cbad)
        bt0 = QPushButton("复位视图"); bt0.clicked.connect(self._reset_chartview)
        cb.addWidget(bt0)
        cb.addStretch(1)
        mv.addLayout(cb)

        # 下落式参数条
        fb = QHBoxLayout()
        fb.addWidget(QLabel("轨道数"))
        self.cb_lanes = QComboBox(); self.cb_lanes.addItems(["4", "8"])
        self.cb_lanes.currentIndexChanged.connect(self._update_falling)
        fb.addWidget(self.cb_lanes)
        fb.addWidget(QLabel("流速"))
        self.sp_speed = QSpinBox(); self.sp_speed.setRange(10, 800); self.sp_speed.setValue(100)
        self.sp_speed.valueChanged.connect(self._update_falling)
        fb.addWidget(self.sp_speed)
        fb.addWidget(QLabel("切分"))
        self.cb_div = QComboBox(); self.cb_div.addItems(["4", "8", "16", "32"])
        self.cb_div.setCurrentText("8")
        self.cb_div.currentIndexChanged.connect(self._update_falling)
        fb.addWidget(self.cb_div)
        fb.addWidget(QLabel("轨道分配"))
        self.cb_lanemode = QComboBox()
        self.cb_lanemode.addItems(["按音高分位", "按音高线性", "左右交替"])
        self.cb_lanemode.currentIndexChanged.connect(self._update_falling)
        fb.addWidget(self.cb_lanemode)
        self.cb_follow = QCheckBox("路径跟随"); self.cb_follow.setChecked(True)
        self.cb_follow.stateChanged.connect(self._update_follow)
        fb.addWidget(self.cb_follow)
        fb.addStretch(1)
        mv.addLayout(fb)
        split.addWidget(mid)
        split.setStretchFactor(1, 1)
        split.setSizes([400, 1140])

        # ---------------- 传输条 ----------------
        tb = QWidget(); th = QHBoxLayout(tb); th.setContentsMargins(8, 4, 8, 4)
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setFixedWidth(90)
        self.btn_play.clicked.connect(self.toggle_play)
        th.addWidget(self.btn_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderReleased.connect(self._on_slider)
        th.addWidget(self.slider, 1)
        self.lbl_time = QLabel("0:00.00 / 0:00.00")
        self.lbl_time.setMinimumWidth(140)
        th.addWidget(self.lbl_time)
        th.addWidget(QLabel("音量"))
        vol = QSlider(Qt.Horizontal); vol.setRange(0, 100); vol.setValue(70); vol.setFixedWidth(90)
        vol.valueChanged.connect(lambda v: self.audio_out.setVolume(v / 100.0))
        th.addWidget(vol)

        central = QWidget()
        cv = QVBoxLayout(central); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(4)
        cv.addWidget(split, 1)
        cv.addWidget(tb)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.status("就绪：打开一个 MIDI，或在「示例▾」里选一个内置样本。")

    # ================================================================ actions
    def status(self, msg: str):
        self.statusBar().showMessage(msg)

    def show_about(self):
        QMessageBox.information(self, "参数说明", ABOUT_TEXT)

    def _sample_menu(self):
        from PySide6.QtWidgets import QMenu
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
        m = QMenu(self)
        if not os.path.isdir(base):
            m.addAction("（samples 目录不存在）")
        else:
            for fn in sorted(os.listdir(base)):
                if fn.lower().endswith((".mid", ".midi") + AUDIO_EXTS):
                    m.addAction(fn, lambda f=fn: self.load_midi(os.path.join(base, f)))
        m.exec(self.cursor().pos())

    def open_midi(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "打开谱面源（MIDI 或音频）", "",
            "全部支持的 (*.mid *.midi *.ogg *.oga *.wav *.flac *.mp3);;"
            "MIDI (*.mid *.midi);;音频 (*.ogg *.oga *.wav *.flac *.mp3);;全部 (*)")
        if p:
            self.load_midi(p)

    def load_midi(self, path: str):
        try:
            if path.lower().endswith(AUDIO_EXTS):
                # ★ 音频转音头要 30~60s，必须给进度条，否则界面像卡死
                from PySide6.QtWidgets import QProgressDialog
                dlg = QProgressDialog("准备转换…", "取消", 0, 100, self)
                dlg.setWindowTitle("音频 → 音头")
                dlg.setMinimumDuration(0)
                dlg.setAutoClose(False)
                dlg.setAutoReset(False)
                dlg.setValue(0)
                QApplication.processEvents()

                def _prog(frac, msg):
                    dlg.setLabelText(f"{msg}\n{frac * 100:.0f}%")
                    dlg.setValue(int(frac * 100))
                    QApplication.processEvents()
                    if dlg.wasCanceled():
                        raise audio_mod.ConversionCancelled()

                try:
                    self.midi = audio_mod.load_as_midi(path, progress=_prog)
                except audio_mod.ConversionCancelled:
                    dlg.close()
                    self.status("已取消音频转换")
                    return
                finally:
                    dlg.close()
                    dlg.deleteLater()
                self.source_audio = path          # 导出时直接带上这份音频
            else:
                self.midi = midi_mod.load(path)
                self.source_audio = None
        except Exception as e:                                  # noqa: BLE001
            QMessageBox.critical(self, "解析失败", str(e))
            return
        self.midi_path = path
        # 音源就是这份音频，预览和导出都用它，不再渲染合成音色
        self.audio_path = self.source_audio
        self._audio_key = None
        self.stop()
        self.lbl_file.setText(f"{os.path.basename(path)}\n{self.midi.stats()}")

        self.lst_tracks.blockSignals(True)
        self.lst_tracks.clear()
        for t in self.midi.tracks:
            it = QListWidgetItem(onsets_mod.track_summary(t))
            it.setData(Qt.UserRole, t.index)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (t.notes and not t.is_drum_only())
                             else Qt.Unchecked)
            if not t.notes:
                it.setForeground(Qt.gray)
            self.lst_tracks.addItem(it)
        if self.cb_scope.currentIndex() == 0:
            # 默认「多轨：全部非鼓」——上面已经按这个勾好了
            pass
        else:
            self.cb_scope.setCurrentIndex(0)
        # 光标默认落在「平均音高最高的非鼓轨」——旋律通常在最上面。
        # （原来的「音符最多」实测最差：MemoryLocked 会挑到低音伴奏，
        #   SetSpeed 密度 21/100 格，是 EX 标尺的 15 倍。）
        cand = [t for t in self.midi.tracks if t.notes and not t.is_drum_only()]
        def _melody(t):
            avg = sum(n.pitch for n in t.notes) / len(t.notes)
            return (avg, len(t.notes))
        pick = max(cand, key=_melody).index if cand else 0
        row = next((i for i in range(self.lst_tracks.count())
                    if self.lst_tracks.item(i).data(Qt.UserRole) == pick), 0)
        self.lst_tracks.setCurrentRow(row)
        self.lst_tracks.blockSignals(False)

        # 双押轨列表（可多选）
        self.lst_dp.blockSignals(True)
        self.lst_dp.clear()
        for t in self.midi.tracks:
            mark = "架子鼓" if t.is_drum_only() else "旋律"
            it = QListWidgetItem(f"双押轨 trk{t.index} {t.name or '(无名)'}"
                                 f"（{len(t.notes)} 音·{mark}）")
            it.setData(Qt.UserRole, t.index)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (t.notes and t.is_drum_only())
                             else Qt.Unchecked)
            if not t.notes:
                it.setForeground(Qt.gray)
            self.lst_dp.addItem(it)
        self.lst_dp.blockSignals(False)

        self.ed_song.setText(os.path.splitext(os.path.basename(path))[0])
        self.status(f"已加载 {os.path.basename(path)}：{self.midi.stats()}")
        self._on_track_changed()

    def _current_track(self) -> int:
        it = self.lst_tracks.currentItem()
        return it.data(Qt.UserRole) if it else 0

    def _checked_tracks(self) -> list[int]:
        out = []
        for i in range(self.lst_tracks.count()):
            it = self.lst_tracks.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _primary_track(self) -> int:
        """主轨：手动 = 光标那条；否则按启发式在勾选的非鼓轨里挑。"""
        mode = self.cb_primary.currentIndex()
        if mode == 0:
            ti = self._current_track()
            if 0 <= ti < len(self.midi.tracks) and self.midi.tracks[ti].notes:
                return ti
            idxs = [i for i in self._checked_tracks() if self.midi.tracks[i].notes]
            return idxs[0] if idxs else 0
        cand = [self.midi.tracks[i] for i in self._checked_tracks()
                if self.midi.tracks[i].notes and not self.midi.tracks[i].is_drum_only()]
        if not cand:
            cand = [t for t in self.midi.tracks if t.notes]
        if not cand:
            return 0

        def avg_pitch(t):
            return sum(n.pitch for n in t.notes) / len(t.notes)

        def avg_vel(t):
            return sum(n.velocity for n in t.notes) / len(t.notes)

        def span(t):
            return max(n.pitch for n in t.notes) - min(n.pitch for n in t.notes)

        key = {1: lambda t: (avg_pitch(t), len(t.notes)),
               2: lambda t: (avg_vel(t), len(t.notes)),
               3: lambda t: (len(t.notes), avg_pitch(t)),
               4: lambda t: (span(t), len(t.notes))}[mode]
        return max(cand, key=key).index

    def _on_primary_changed(self, *_):
        if not self.midi:
            return
        if self.cb_primary.currentIndex() != 0:
            prim = self._primary_track()
            for i in range(self.lst_tracks.count()):
                it = self.lst_tracks.item(i)
                if it.data(Qt.UserRole) == prim:
                    self.lst_tracks.blockSignals(True)
                    self.lst_tracks.setCurrentRow(i)
                    self.lst_tracks.blockSignals(False)
                    break
        self._on_track_changed()

    def _dp_tracks(self) -> list[int]:
        """勾选的双押轨（可多条，取并集）。"""
        if not self.midi:
            return []
        out = []
        for i in range(self.lst_dp.count()):
            it = self.lst_dp.item(i)
            if it.checkState() == Qt.Checked:
                ti = it.data(Qt.UserRole)
                if 0 <= ti < len(self.midi.tracks) and self.midi.tracks[ti].notes:
                    out.append(ti)
        return out

    @staticmethod
    def _interp(t: float, xs: list[float], ys: list[float]) -> float:
        """分段线性：把双押轨的音头时刻（音频 ms）映射到谱面相对时刻（ms）。

        底座 onset 的「音频时刻 ↔ 谱面层时刻」是一一对应的，用它当标尺
        就能把另一条轨的音头摆到正确的音乐位置上。
        """
        if not xs or not ys:
            return 0.0
        if t <= xs[0]:
            return ys[0]
        if t >= xs[-1]:
            return ys[-1]
        i = bisect.bisect_left(xs, t)
        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = ys[i - 1], ys[i]
        if x1 <= x0:
            return y0
        return y0 + (y1 - y0) * (t - x0) / (x1 - x0)

    def _filler_indexes(self) -> list[int]:
        prim = self._primary_track()
        dp = set(self._dp_tracks())
        mode = self.cb_scope.currentIndex()
        checked = [i for i in self._checked_tracks() if self.midi.tracks[i].notes]
        if mode == 3:                       # 含鼓
            return [i for i in checked if i != prim and i not in dp]
        return [i for i in checked
                if i != prim and i not in dp
                and not self.midi.tracks[i].is_drum_only()]

    def _selected_track_indexes(self) -> list[int]:
        """实际会参与采音的轨（用于音高并集 / 预览渲染）。"""
        if not self.midi:
            return []
        mode = self.cb_scope.currentIndex()
        prim = self._primary_track()
        dp = set(self._dp_tracks())
        if mode == 1:                       # 单轨
            return [prim] if self.midi.tracks[prim].notes else []
        if mode in (2, 3):                  # 全采
            return [i for i in self._checked_tracks()
                    if self.midi.tracks[i].notes and i not in dp]
        return [prim] + self._filler_indexes()   # 补空白

    def _on_scope_changed(self, idx: int):
        if not self.midi:
            return
        self.lst_tracks.blockSignals(True)
        for i in range(self.lst_tracks.count()):
            it = self.lst_tracks.item(i)
            t = self.midi.tracks[it.data(Qt.UserRole)]
            want = bool(t.notes) and (idx == 3 or not t.is_drum_only())
            it.setCheckState(Qt.Checked if want else Qt.Unchecked)
        self.lst_tracks.blockSignals(False)
        self._on_track_changed()

    def _on_item_changed(self, *_):
        self._on_track_changed()

    def _on_track_changed(self):
        if not self.midi:
            return
        ti = self._current_track()
        trk = self.midi.tracks[ti]
        idxs = self._selected_track_indexes()
        mode = self.cb_scope.currentIndex()
        dp = self._dp_tracks()
        if dp:
            dptxt = (f"\n双押轨（{len(dp)} 条，门控·主音有音才插）："
                     + "+".join(f"trk{i}" for i in dp)
                     + (f"   窗口 {self.sp_dptol.value():g}ms"))
        else:
            dptxt = "\n双押轨：不用"
        if mode == 0:
            prim = self._primary_track()
            fil = self._filler_indexes()
            src = "手动" if self.cb_primary.currentIndex() == 0 else "自动"
            self.lbl_track.setText(
                f"主轨（{src}）：trk{prim} {self.midi.tracks[prim].name or '(无名)'}"
                f"（{len(self.midi.tracks[prim].notes)} 音）\n"
                f"补空白：{'+'.join(f'trk{i}' for i in fil) or '（无）'}"
                f"   阈值 {self.sp_fillgap.value():g} ms"
                + ("\n⚠ 想换主轨就点上面列表里别的轨" if src == "自动" else "")
                + dptxt)
        else:
            names = "+".join(f"trk{i}" for i in idxs) or "（无）"
            n_notes = sum(len(self.midi.tracks[i].notes) for i in idxs)
            self.lbl_track.setText(
                f"光标：trk{ti} {trk.name or '(无名)'}（{len(trk.notes)} 音）\n"
                f"实际采音：{names}  共 {len(idxs)} 轨 / {n_notes} 个 note-on"
                + dptxt)
        if trk.notes:
            self.sp_plo.setValue(min(n.pitch for n in trk.notes))
            self.sp_phi.setValue(max(n.pitch for n in trk.notes))
        # 多轨时音高范围要取**并集**，否则会把别的轨的音切掉
        notes = [n for i in idxs for n in self.midi.tracks[i].notes]
        if notes:
            self.sp_plo.setValue(min(n.pitch for n in notes))
            self.sp_phi.setValue(max(n.pitch for n in notes))
        self._schedule()

    def _schedule(self, *_):
        self._rebuild_timer.start()

    def _params_onset(self) -> onsets_mod.OnsetParams:
        return onsets_mod.OnsetParams(
            merge_ms=self.sp_merge.value(),
            merge_anchor=self.cb_anchor.currentText(),
            min_velocity=self.sp_minvel.value(),
            min_interval_ms=self.sp_minint.value(),
            pitch_lo=self.sp_plo.value(),
            pitch_hi=self.sp_phi.value(),
            max_onsets=self.sp_maxonset.value(),
        )

    def _params_solve(self, onsets) -> solve_mod.SolveParams:
        preset = ("少", "平衡", "多")[self.cb_straight.currentIndex()]
        ref = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0)[self.cb_ref.currentIndex()]
        ppqn = getattr(self.midi, "ppqn", 480) if self.midi else 480
        mbpm = getattr(self.midi, "bpm0", 0.0) if self.midi else 0.0
        mode = ("alternate", "accum", "steer", "off")[self.cb_twirlmode.currentIndex()]
        p = solve_mod.SolveParams(
            beat_beats=ref,
            straight_weight=solve_mod.STRAIGHT_PRESETS[preset],
            bpm_max=self.sp_bpmmax.value(),
            speed_tiers=((1,) if not self.cb_setspeed.isChecked()
                         else solve_mod.SPEED_TIERS),
            allow_set_speed=self.cb_setspeed.isChecked(),
            allow_twirl=(mode != "off"),
            twirl_mode=mode,
            twirl_limit_deg=self.sp_twirlmax.value(),
            quantize_rhythm=self.cb_quant.isChecked(),
            ppqn=ppqn,
            midi_bpm=mbpm,
            use_templates=self.cb_tpl.isChecked(),
            template_only_nonstraight=self.cb_tplonly.isChecked(),
            use_pause=self.cb_pause.isChecked(),
            pause_min_beats=self.sp_pausebeats.value(),
            use_snowflake=self.cb_snow.isChecked(),
            snowflake_min_tiles=int(self.sp_snowmin.value()),
            snowflake_full_tiles=float(self.sp_snowfull.value()),
            snowflake_n_rot={0: (6, 8, 10, 12), 1: (6,), 2: (8,), 3: (12,)}.get(
                self.cb_snown.currentIndex(), (6, 8, 10, 12)),
        )
        if self.cb_autobpm.isChecked():
            beats, _ = solve_mod.beats_of(onsets, ppqn, mbpm or 120.0)
            if not beats:
                beats = []
            C, bpm, _, _, _ = solve_mod.choose_reference(
                beats, p, mbpm or 120.0) if beats else (0.0, 0.0, 0.0, 0.0, [])
            if bpm <= 0:
                bpm = solve_mod.auto_base_bpm(onsets, 180.0, 0.85, ppqn=ppqn, midi_bpm=mbpm)
            self.sp_bpm.blockSignals(True); self.sp_bpm.setValue(bpm); self.sp_bpm.blockSignals(False)
        else:
            bpm = self.sp_bpm.value()
            p.base_bpm = bpm
        return p

    # ================================================================ rebuild
    def rebuild(self):
        if not self.midi:
            return
        t0 = time.time()
        used = self._selected_track_indexes()
        if not used:
            self.status("没有可采音的音轨（②里勾选一下，或换成「多轨」）")
            return
        mode = self.cb_scope.currentIndex()
        p_on = self._params_onset()
        if mode == 0:                       # 主轨 + 补空白
            prim = self._primary_track()
            fil = self._filler_indexes()
            self.onsets = onsets_mod.build_onsets_fill(
                self.midi.tracks[prim], [self.midi.tracks[i] for i in fil],
                p_on, self.sp_fillgap.value())
        elif mode == 1:                     # 单轨
            prim = self._primary_track()
            self.onsets = onsets_mod.build_onsets(self.midi.tracks[prim].notes, p_on)
        else:                               # 全采
            self.onsets = onsets_mod.build_onsets_multi(
                [self.midi.tracks[i] for i in used], p_on)
        merged_notes = [n for i in used for n in self.midi.tracks[i].notes]
        if len(self.onsets) < 2:
            self.status("采音点少于 2 个，无法成谱。放宽过滤条件试试。")
            return

        p_sv = self._params_solve(self.onsets)
        t_solve = time.time()
        self.chart = solve_mod.solve(self.onsets, p_sv)
        cd = self.sp_cd.value()

        # ---- 双押轨 → 中旋双押（在算任何派生量之前做）
        #      规则：**主音有音时双押，否则空过**。
        #      双押轨只当门控；插双押的位置永远取**主音那一层** ——
        #      于是落点必然在主音格上（亚毫秒级），也不会跑进 Pause 里。
        self.dp_info = ""
        self.dp_report = {}
        n_dp = 0
        dp_tis = self._dp_tracks()
        if dp_tis and len(self.chart.floors) > 2:
            dp_t: list[float] = []
            for ti in dp_tis:
                for o in onsets_mod.build_onsets(self.midi.tracks[ti].notes,
                                                 self._params_onset()):
                    dp_t.append(o.t_ms)
            dp_t.sort()
            if dp_t:
                tol = float(self.sp_dptol.value())
                lead = 1 if self.chart.meta.get("n_lead") else 0
                pre = solve_mod.times_from_chart(self.chart)
                main_t = [o.t_ms for o in self.onsets]

                # 主音那一层 → 双押目标（主音附近有双押轨音头才算）
                tg: list[float] = []
                j = 0
                for k, T in enumerate(main_t):
                    while j < len(dp_t) and dp_t[j] < T - tol:
                        j += 1
                    if j < len(dp_t) and dp_t[j] <= T + tol:
                        tg.append(pre[min(k + lead, len(pre) - 1)])

                # 双押轨里有多少音头主音当时没音（空过）
                skipped = 0
                m = 0
                for T in dp_t:
                    while m < len(main_t) and main_t[m] < T - tol:
                        m += 1
                    if not (m < len(main_t) and main_t[m] <= T + tol):
                        skipped += 1

                rep: dict = {}
                if self.cb_dpmode.currentIndex() == 1:          # 角度双押
                    plan = dp_angle.plan(self.chart, tg, report=rep)
                    n_dp = dp_angle.apply(self.chart, plan)
                    st = dp_angle.stats(self.chart)
                    self.dp_report = dict(rep, **{
                        "dp_onsets": len(dp_t), "dp_hits": n_dp,
                        "dp_skipped": skipped, "dp_extra": len(dp_t) - skipped - n_dp,
                        "reverse": st.get("reverse", 0), "normal": st.get("normal", 0)})
                    self.dp_info = (f"  角度双押 {n_dp} 处（反向 {st.get('reverse', 0)} / "
                                    f"正常 {st.get('normal', 0)}；双押轨 {len(dp_t)} 音头，"
                                    f"空过 {skipped}"
                                    + (f"，借道自然段 {rep['soft_used']}"
                                       if rep.get("soft_used") else "")
                                    + (f"；⚠ 丢 {rep['lost']} 处" if rep.get("lost") else "")
                                    + "）  ")
                else:                                            # 中旋双押
                    plan = dp_midspin.plan(self.chart, tg, report=rep)
                    n_dp = dp_midspin.apply(self.chart, plan)
                    self.dp_report = dict(rep, **{
                        "dp_onsets": len(dp_t), "dp_hits": n_dp,
                        "dp_skipped": skipped, "dp_extra": len(dp_t) - skipped - n_dp})
                    self.dp_info = (f"  双押 {n_dp} 处（双押轨 {len(dp_t)} 音头，"
                                    f"空过 {skipped}）  ")

        self.preview_lead_ms = solve_mod.total_lead_ms(self.chart, cd)
        self.chart_entry = solve_mod.game_entry_times(self.chart, cd)
        self.chart_times = solve_mod.times_from_chart(self.chart)
        # ★ 插了中旋之后层号整体后移，onset↔层 的对应要用 dp_old2new 重映射，
        #   不能直接用 entry_time_of_onsets（它假设第 j 层就是第 j-lead 个 onset）。
        o2n = self.chart.meta.get("dp_old2new") or {}
        nf = len(self.chart.floors)
        lead = 1 if self.chart.meta.get("n_lead") else 0
        self.hit_times = []
        for i in range(len(self.onsets)):
            j = min(i + lead, nf - 1)
            j = o2n.get(j, j) if o2n else j
            self.hit_times.append(self.chart_entry[min(j, nf - 1)])
        ov = solve_mod.path_overlap_stats(self.chart)
        sp = solve_mod.speed_profile(self.chart)

        if self.cb_autooffset.isChecked():
            self.sp_offset.blockSignals(True)
            self.sp_offset.setValue(self.onsets[0].t_ms)
            self.sp_offset.blockSignals(False)

        # 卷帘
        self.roll.set_data(merged_notes, self.onsets, self.midi.length_ms,
                           beats_ms=self._beat_grid_ms())
        # 路径视图用游戏语义的 entryTime，播放头用 (音频位置 − offset)
        self.pathv.set_data(self.chart.floors, self.chart_entry, 0.0)
        self.chartv.set_data(self.chart.floors, self.chart_entry, 0.0,
                             bpm0=self.chart.base_bpm,
                             dp_pairs=self.chart.meta.get("dp_pairs"))
        self._update_chartview()
        self._update_falling()

        n = len(self.chart.floors)
        # 排除"长休止层"后的真实速度范围（休止层会极慢，会吓人但不是问题）
        mild = [f.bpm / self.chart.base_bpm for f in self.chart.floors[1:]
                if f.speed_k <= max(solve_mod.SPEED_TIERS)]
        chk = solve_mod.check_offset(self.chart, self.sp_offset.value(), cd,
                                     [o.t_ms for o in self.onsets],
                                     self.midi.length_ms + self.preview_lead_ms,
                                     self.preview_lead_ms)
        # 音值分布（按几分音符写）
        try:
            from core import rhythm as _Rh
            st = _Rh.extract(self.onsets, getattr(self.midi, "ppqn", 480),
                             60000.0 / max(1e-9, self.midi.bpm0))
            self._rhythm_txt = "  ".join(f"{nm}×{pct:.0f}%" for nm, _, _, pct in st.hist(4))
        except Exception:                                        # noqa: BLE001
            self._rhythm_txt = "—"
        hist = self.chart.travel_hist(4)
        hist_txt = "  ".join(f"{v:g}°×{pct:.0f}%" for v, _, pct in hist)
        self.lbl_timing.setText(
            f"音值: {self._rhythm_txt}\n"
            f"直线(travel 180°): {self.chart.straight_frac*100:.0f}%   "
            f"travel 词汇: {hist_txt}\n"
            f"一条直线 = {self.chart.meta.get('ref_beats', 0):g} 拍    "
            f"前置静音 {self.preview_lead_ms:.0f}ms (cd {cd} 拍)"
            f"   量化误差 ≤{self.chart.meta.get('quant_err_ms', 0):.0f}ms"
            f"   尾部余量 {chk['tail_gap_s']:+.1f}s")
        n_pause = sum(1 for f in self.chart.floors if f.pause_beats > 1e-9)
        n_tpl = self.chart.meta.get("tpl_hits", 0)
        tpl_cov = self.chart.meta.get("tpl_covered", 0)
        msg = (f"采音 {len(used)}轨/{len(merged_notes)}→{len(self.onsets)}  层数 {n}(含开局站位层)  "
               f"直线 {self.chart.straight_frac*100:.0f}%  "
               f"Twirl {self.chart.n_twirl}({self.chart.n_twirl/n*100:.0f}%)  "
               f"SetSpeed {self.chart.n_speed_events}({self.chart.n_speed_events/max(1,n-1)*100:.1f}%)  "
               + (f"模板 {tpl_cov}格/{n_tpl}段  " if tpl_cov or n_tpl else "")
               + (f"Pause {n_pause}  " if n_pause else "")
               + self.dp_info
               + f"行星速度 {min(mild) if mild else 1:.2f}~{max(mild) if mild else 1:.2f}x  "
               f"基准BPM {self.chart.base_bpm:g}  cd={cd}  offset={self.sp_offset.value():.0f}ms  "
               + (f"命中时刻误差 {chk['max_err_ms']*1000:.0f}us"
                  if self.cb_autooffset.isChecked()
                  else f"建议 offset ≈ {chk['suggest_ms']:.0f}ms（自己听）"))
        try:
            from core import rules as _rules
            viol = [v for v in _rules.check_chart(self.chart) if v.get("level") != "info"]
            if viol:
                msg += f"   ⚠ 规则检查 {len(viol)} 条不合格"
            else:
                msg += "   规则检查 ✓"
            if self.chart.meta.get("snow_count"):
                msg += (f"   魔法阵 {self.chart.meta['snow_count']} 朵"
                        f"（{self.chart.meta.get('snow_tiles', 0)} 格）")
        except Exception:                                        # noqa: BLE001
            pass
        self.status(msg)
        self._refresh_time_label()

    def _beat_grid_ms(self, division: int = 4) -> list[float]:
        """按 tempo map 生成节拍线（division 分音符）。"""
        if not self.midi:
            return []
        out: list[float] = []
        bpm = self.midi.bpm0
        ms_per_beat = 60000.0 / max(1e-6, bpm)
        step = ms_per_beat * 4.0 / division
        t = 0.0
        # 只取前 30 秒的节拍线，避免超长曲目拖慢绘制
        while t < min(self.midi.length_ms, 30000.0):
            out.append(t)
            t += step
        return out

    def _update_follow(self):
        self.pathv.follow = self.cb_follow.isChecked()
        self.pathv.update()

    def _update_chartview(self):
        if not self.chart:
            return
        self.chartv.follow = self.cb_cfollow.isChecked()
        self.chartv.span = float(self.sp_cspan.value())
        self.chartv.color_mode = ("travel" if self.cb_ctravel.isChecked()
                                  else "type")
        self.chartv.show_bad = self.cb_cbad.isChecked()
        self.chartv.update()

    def _reset_chartview(self):
        self.chartv.reset_view()
        self.cb_cfollow.setChecked(True)

    def seek_floor(self, floor: int):
        """谱面预览里点格子 → 跳到那一层的时刻。

        预览音频开头补过 `preview_lead_ms` 的静音，所以音频位置与
        `chart_entry`（game entryTime）是同一根时间轴，直接对应，不加减 offset。
        """
        if not self.chart or not (0 <= floor < len(self.chart_entry)):
            return
        self.seek(self.chart_entry[floor])

    def _update_falling(self):
        if not self.chart:
            return
        lanes = int(self.cb_lanes.currentText())
        div = int(self.cb_div.currentText())
        notes = self._falling_notes(lanes)
        caps = self._cap_times_ms(div)
        self.falling.set_chart(self.chart.base_bpm, notes, lanes,
                               speed=self.sp_speed.value(), division=div, cap_times=caps)

    def _cap_times_ms(self, division: int) -> list[float]:
        """下落式横向切分线：以 base_bpm 为基准，按 division 分音（已含前置静音）。"""
        if not self.chart:
            return []
        step = (60000.0 / max(1e-6, self.chart.base_bpm)) * 4.0 / division
        off = self.sp_offset.value()
        t0 = off + (self.chart_entry[1] if len(self.chart_entry) > 1 else 0.0)
        end = off + (self.chart_entry[-1] if self.chart_entry else 30000.0)
        out = []
        t = t0 - ((t0 - off) % step)
        while t < end:
            out.append(t)
            t += step
        return out

    def _falling_notes(self, lanes: int) -> list[dict]:
        """把谱面映射成 (press_time, release_time, is_hold, lane)。

        时间轴 = **成品音频**的时间轴：offset + entryTime，已经含了前置静音。
        """
        if not self.chart or not self.onsets:
            return []
        import bisect as _bs
        off = self.sp_offset.value()
        press = [off + t for t in self.hit_times]
        mode = self.cb_lanemode.currentText() if hasattr(self, "cb_lanemode") else "按音高分位"
        pitches = [o.pitch for o in self.onsets]
        lo, hi = min(pitches), max(pitches)
        span = max(1, hi - lo)
        ranked = sorted(pitches)
        out = []
        for i, o in enumerate(self.onsets):
            if mode == "左右交替":
                lane = i % lanes
            elif mode == "按音高线性":
                lane = int(round((o.pitch - lo) / span * (lanes - 1)))
            else:
                pct = (_bs.bisect_right(ranked, o.pitch) - 0.5) / max(1, len(ranked))
                lane = int(pct * lanes)
            lane = max(0, min(lanes - 1, lane))
            out.append({"press_time": press[i],
                        "release_time": press[i + 1] if i + 1 < len(press) else None,
                        "is_hold": False, "lane": lane})
        return out

    # ================================================================ playback
    def _audio_for_current(self) -> str | None:
        if not self.midi:
            return None
        # 音频源（OGG/WAV…）：直接用原曲，不渲染合成音色
        if getattr(self, "source_audio", None) and os.path.exists(self.source_audio):
            return self.source_audio
        idxs = self._selected_track_indexes() or [self._current_track()]
        key = (self.midi_path, tuple(idxs), len(self.onsets),
               round(self.sp_merge.value(), 3), self.sp_minvel.value(),
               round(self.sp_minint.value(), 3))
        if self._audio_key == key and self.audio_path and os.path.exists(self.audio_path):
            return self.audio_path
        d = tempfile.mkdtemp(prefix="adofai_preview_")
        wav = os.path.join(d, "preview.wav")
        self.status("正在渲染预览音频…（无音源，用内置合成音色）")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            synth.render(self.midi, wav, track_index=idxs[0],
                         track_indexes=idxs,
                         onsets=self.onsets, click=True,
                         lead_ms=getattr(self, "preview_lead_ms", 0.0))
        finally:
            QApplication.restoreOverrideCursor()
        self.audio_path = wav
        self._audio_key = key
        return wav

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("▶ 播放")
            return
        if not self.midi:
            self.status("先加载一个 MIDI。")
            return
        if not self.onsets:
            self.rebuild()
        p = self._audio_for_current()
        if not p:
            return
        if self.player.source().toLocalFile() != p:
            self.player.setSource(QUrl.fromLocalFile(p))
        if self.player.playbackState() == QMediaPlayer.PausedState:
            self.player.play()
        else:
            self.falling.reset()
            self.pathv.cur_floor = 0
            self.player.setPosition(0)
            self.player.play()
        self.btn_play.setText("⏸ 暂停")

    def stop(self):
        self.player.stop()
        self.btn_play.setText("▶ 播放")

    def seek(self, ms: float):
        if self.player.source().isEmpty():
            return
        self.player.setPosition(int(ms))

    def _on_slider(self):
        d = self.player.duration() or 0
        if d > 0:
            self.player.setPosition(int(self.slider.value() / 1000.0 * d))

    def _on_state(self, st):
        if st == QMediaPlayer.StoppedState:
            self.btn_play.setText("▶ 播放")

    def _on_pos(self, ms: int):
        d = self.player.duration() or 0
        if d > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int(ms / d * 1000))
            self.slider.blockSignals(False)
        self.roll.set_playhead(ms)
        self.pathv.set_playhead_ms(ms)
        self.chartv.set_playhead_ms(ms)
        self.falling.set_time(ms)
        self._refresh_time_label(ms, d)

    def _refresh_time_label(self, ms: int | None = None, d: int | None = None):
        if ms is None:
            ms = self.player.position()
        if d is None:
            d = self.player.duration() or 0
        f = lambda v: f"{v//60000}:{(v%60000)/1000:05.2f}"          # noqa: E731
        self.lbl_time.setText(f"{f(ms)} / {f(d)}")

    # ================================================================ export
    def export_chart(self):
        if not self.chart:
            self.status("还没有生成谱面。")
            return
        d = QFileDialog.getExistingDirectory(self, "选择导出目录（会新建一个曲目文件夹）")
        if not d:
            return
        name = (self.ed_song.text() or "main").strip()
        name = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "main"
        outdir = os.path.join(d, name)
        try:
            wav = self._audio_for_current()
            p = writer.write_dir(
                self.chart, outdir, name="main", audio_src=wav,
                song=self.ed_song.text(), artist=self.ed_artist.text(),
                author=self.ed_author.text(), offset_ms=self.sp_offset.value(),
                difficulty=self.sp_diff.value(),
                countdown_ticks=self.sp_cd.value(),
                separate_countdown=self.cb_sepcd.isChecked(),
            )
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))
            return

        cd = self.sp_cd.value()
        vr = verify.verify_file(p, [o.t_ms for o in self.onsets], tol_ms=1.0, lead_floors=1)
        chk = solve_mod.check_offset(self.chart, self.sp_offset.value(), cd,
                                     [o.t_ms for o in self.onsets],
                                     self.midi.length_ms + self.preview_lead_ms,
                                     self.preview_lead_ms)
        msg = (f"已导出：\n{p}\n\n"
               f"audio：{'已随包复制 wav' if wav else '无'}\n"
               f"层数 {len(self.chart.floors)}（含 1 层开局站位，其 travel 固定 180° = 直线）  "
               f"直线 {self.chart.straight_frac*100:.0f}%  "
               f"Twirl {self.chart.n_twirl}  减速事件 {self.chart.n_speed_events}\n"
               f"countdownTicks {cd}   offset {self.sp_offset.value():.0f}ms   "
               f"前置静音 {self.preview_lead_ms:.0f}ms\n"
               f"尾部余量 {chk['tail_gap_s']:+.1f}s（offset+最后一层 vs 音频总长）\n\n"
               f"第三方 parser 反解校验：{vr.summary()}")
        QMessageBox.information(self, "导出完成", msg)
        self.status(vr.summary())


ABOUT_TEXT = """\
【采音】栏 —— 决定 MIDI 里哪些音变成方块
  合并窗口：间隔小于它的音算「同时响」，合并成一次按键（ADOFAI 一层一按）
  合并取点：first = 取簇里最早音（推荐，贴合听感）；loudest = 取力度最大音
  最小间隔：稀疏化，丢掉离得太近的音（对付 16 分连打）
  最大音数：按力度只保留前 N 个（0=不限）
  音高范围：只采这个音区（切声部用）

【求解 / 几何】栏
  一条直线 = 几分音符：本代生成器的核心旋钮。基准 BPM = 歌曲拍速 ÷ 这个音值。
      自动 = 遍历所有候选音值，取「直线占比 − λ×事件占比」最大的那个
  直线优先：一条 180° 直线值多少个减速事件
      少 = 事件最少（~5%）  平衡（推荐）  多 = 尽量直线（事件可到 25%）
      真谱参照：直线 37.7%（中位 36%），减速事件 1%~12%
  基准 BPM：算出后写进 settings.bpm，也顺带决定倒计时长度（cd × 一拍）
  BPM 上限：太大 → 倒计时会被压成几十毫秒，观感很差
  允许减速档：长音用 1/2、1/3、1/4 的速度档接住（真谱的 snails 干的就是这件事）
  量化到音值网格：Δt 吸附到「几分音符」再算角度（拍数 = Δtick / PPQ）
  Twirl 策略：Twirl = 免费翻转转向符号。**不能去掉** —— 去掉后行星会锁在原地
      绕小多边形打转。直线层转角为 0，翻不翻都一样，所以图标只会落在拐角层上。

【时序 / 导出】栏
  offset：**默认 0，你自己听、自己调**。勾上「自动 = 首个 onset」才是零误差配方
      （那条路要求你用随包导出的、前面补了静音的音频）。
  countdownTicks：社区约定 4。开谱到第一次按下 = cd × 一拍。
  第一格：真谱 95.6% 的 angleData[0] == 0，等价于 travel_0 == 180°（直线）。
      本生成器**强制**第 0 层 travel = 180°，不管你怎么调参数。

【音轨】栏 —— 主音轨与双押轨分开选
  主音轨（cb_primary）：决定谱面的节奏线与形状
  双押轨（lst_dp）  ：可勾**多条**（取并集），只当「这里还有一只手」的门控
      规则：**主音有音时双押，否则空过**。
        插双押的位置永远是**主音那一层**，双押轨只是告诉你「这一下是双押」。
        双押轨响了但主音当时没音 → 那一下没有东西可以「双」，直接空过。
      做法：在主音格前面插一对 [折返格, midspin 999]，999 与该格同一瞬间
        按下 ⇒ 真·双押。插入零净偏移，前后时序一个都不动。
      好处：落点必然在主音格上（亚毫秒），不会跑进 Pause 里 —— 所以
        不会出现「双押插在停顿里被迫偏移」的问题。
      判定窗口（默认 45ms）：双押轨的音头与主音相隔多少毫秒内算「同一下」。
      勾了的双押轨**不再参与底部采音**（不算主轨/补空白）。
      ⚠ 别把「和主音轨节奏一样的那条线」勾成双押轨 —— 那样每一格都会变双押。

【预览】栏
  ★ 谱面预览：瓷砖级，跟游戏里长得一样
      滚轮=缩放  Shift+滚轮=切跟随  左键拖动=平移  左键点格=跳转  中键=切跟随
      紫 = Twirl ／ 橙 = 中旋折返格 ／ 红 = midspin 999 ／ 青虚线 = Pause
      「按 travel 上色」：暖色=急转（快）／冷蓝=直线
  『谱面路径』是旧的打结视图，保留备用；『4K 下落式』验采音。

【硬约束】（游戏源码验证）
  单层时长(ms) = 角行程(°) / 180 × 60000 / 该层 BPM
  转角 = ±(角行程 − 180°)，符号由 Twirl 决定
  angleMoved ≤ 1e-6 或 ≥ 2π（且非中旋）→ 游戏强制 2 拍 = 回头方块，必须避免
"""
