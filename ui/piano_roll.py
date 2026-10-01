"""钢琴卷帘：显示选定音轨的音符 + 采音点 + 播放头。

横轴 = 时间(ms)，纵轴 = 音高。
* 音符矩形 = MIDI 原始音符（灰蓝）
* 采音点 = 合并/过滤后的 onset（橙红三角 + 竖线），这就是真正会变成方块的东西
* 播放头 = 音频当前时刻
滚轮缩放时间，Shift+滚轮平移，Ctrl+滚轮缩放音高。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

BG = QColor("#12161c")
GRID = QColor(255, 255, 255, 14)
GRID_BEAT = QColor(255, 255, 255, 38)
NOTE = QColor("#3d6ea8")
NOTE_EDGE = QColor("#6fa8dc")
ONSET = QColor("#ff8a3d")
ONSET_LINE = QColor(255, 138, 61, 90)
PLAYHEAD = QColor("#ffd166")
TEXT = QColor("#c8d2dd")


class PianoRoll(QWidget):
    seekRequested = Signal(float)      # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.notes: list = []           # core.midi.Note
        self.onsets: list = []          # core.onsets.Onset
        self.beats_ms: list[float] = []  # 节拍线时刻
        self.t0 = 0.0
        self.t1 = 10000.0
        self.pitch_lo = 36
        self.pitch_hi = 96
        self.playhead_ms = 0.0
        self.view_t0 = 0.0
        self.view_span = 10000.0

        self._drag = None
        self._hover_ms = None
        self.setFont(QFont("Consolas", 8))

    # ------------------------------------------------------------------ data
    def set_data(self, notes, onsets, total_ms: float, beats_ms=None):
        self.notes = list(notes or [])
        self.onsets = list(onsets or [])
        self.beats_ms = list(beats_ms or [])
        self.t0 = 0.0
        self.t1 = max(1000.0, float(total_ms or 1000.0))
        if self.notes:
            self.pitch_lo = max(0, min(n.pitch for n in self.notes) - 2)
            self.pitch_hi = min(127, max(n.pitch for n in self.notes) + 2)
        self.view_t0 = self.t0
        self.view_span = self.t1 - self.t0
        self.update()

    def set_playhead(self, ms: float):
        self.playhead_ms = float(ms)
        self.update()

    def fit_all(self):
        self.view_t0 = self.t0
        self.view_span = max(500.0, self.t1 - self.t0)
        self.update()

    def focus_to(self, ms: float, span_ms: float):
        self.view_span = max(80.0, span_ms)
        self.view_t0 = ms - self.view_span * 0.35
        self.update()

    # ------------------------------------------------------------------ geom
    def _x(self, ms: float) -> float:
        return (ms - self.view_t0) / max(1e-9, self.view_span) * self.width()

    def _ms(self, x: float) -> float:
        return self.view_t0 + x / max(1, self.width()) * self.view_span

    def _y(self, pitch: int) -> float:
        lo, hi = self.pitch_lo, max(self.pitch_lo + 1, self.pitch_hi)
        return self.height() - (pitch - lo) / (hi - lo) * self.height()

    def _ph(self) -> float:
        lo, hi = self.pitch_lo, max(self.pitch_lo + 1, self.pitch_hi)
        return max(3.0, self.height() / (hi - lo) * 0.85)

    # ---------------------------------------------------------------- events
    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if d == 0:
            return
        mods = e.modifiers()
        if mods & Qt.ControlModifier:
            self.pitch_lo = max(0, self.pitch_lo - (1 if d > 0 else -1))
            self.pitch_hi = min(127, self.pitch_hi + (1 if d > 0 else -1))
        elif mods & Qt.ShiftModifier:
            self.view_t0 -= d / 1200.0 * self.view_span
        else:
            anchor = self._ms(e.position().x())
            f = 0.8 if d > 0 else 1.25
            self.view_span = max(80.0, min(600000.0, self.view_span * f))
            self.view_t0 = anchor - (anchor - self.view_t0) * f
            # 保持鼠标下的时间点不动
            self.view_t0 = anchor - (e.position().x() / max(1, self.width())) * self.view_span
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position().x(), self.view_t0)
        elif e.button() == Qt.MiddleButton:
            self.seekRequested.emit(self._ms(e.position().x()))

    def mouseMoveEvent(self, e):
        self._hover_ms = self._ms(e.position().x())
        if self._drag is not None:
            dx = e.position().x() - self._drag[0]
            self.view_t0 = self._drag[1] - dx / max(1, self.width()) * self.view_span
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def leaveEvent(self, e):
        self._hover_ms = None
        self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG)
        w, h = self.width(), self.height()

        # 节拍线
        if self.beats_ms and self.view_span < 120000:
            p.setPen(QPen(GRID_BEAT, 1))
            for b in self.beats_ms:
                x = self._x(b)
                if -2 <= x <= w + 2:
                    p.drawLine(QPointF(x, 0), QPointF(x, h))
        # 音高线
        p.setPen(QPen(GRID, 1))
        for pit in range(self.pitch_lo, self.pitch_hi + 1):
            if pit % 12 == 0:
                y = self._y(pit)
                p.drawLine(QPointF(0, y), QPointF(w, y))

        ph_h = self._ph()
        # 音符
        p.setPen(QPen(NOTE_EDGE, 1))
        p.setBrush(QBrush(NOTE))
        for n in self.notes:
            x0, x1 = self._x(n.t_on_ms), self._x(n.t_off_ms)
            if x1 < -4 or x0 > w + 4:
                continue
            if x1 - x0 < 1.2:
                x1 = x0 + 1.2
            y = self._y(n.pitch)
            p.drawRoundedRect(QRectF(x0, y - ph_h / 2, max(1.2, x1 - x0), ph_h), 2, 2)

        # 采音点
        p.setPen(QPen(ONSET_LINE, 1, Qt.DashLine))
        for o in self.onsets:
            x = self._x(o.t_ms)
            if -2 <= x <= w + 2:
                p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(ONSET))
        tri = 7.0
        for o in self.onsets:
            x = self._x(o.t_ms)
            if -tri <= x <= w + tri:
                p.drawPolygon(QPolygonF([QPointF(x - tri, h), QPointF(x + tri, h),
                                         QPointF(x, h - tri * 1.6)]))

        # 播放头
        xp = self._x(self.playhead_ms)
        p.setPen(QPen(PLAYHEAD, 2))
        p.drawLine(QPointF(xp, 0), QPointF(xp, h))

        # 文字
        p.setPen(TEXT)
        p.drawText(6, 14, f"音符 {len(self.notes)}   采音点 {len(self.onsets)}   "
                          f"视窗 {self.view_t0/1000:.2f}s → {(self.view_t0+self.view_span)/1000:.2f}s   "
                          f"音高 {self.pitch_lo}-{self.pitch_hi}")
        if self._hover_ms is not None:
            p.drawText(6, h - 6, f"t = {self._hover_ms:.1f} ms")
        p.end()
