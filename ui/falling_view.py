"""4K / 8K 下落式预览（重写版，样式对齐你惯用的那个宏窗口）。

* 方块从窗口顶部下落，落到判定线的瞬间 = 该音符的 press_time
* 左半区红色（前半轨道），右半区蓝色
* 长按画成长条，按下后停在判定线，松开才消失
* 判定线下方的判定框：按下时缩小再回弹
* 横向节拍/切分线密度可选 4/8/16/32

这是用耳朵+眼睛一起验「采音对不对」的主视图：
音符压线的瞬间，若与合成音频里的音头/咔哒重合，采音就是准的。
"""
from __future__ import annotations

import bisect

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

LANE_CHOICES = (4, 8)
DIVISIONS = (4, 8, 16, 32)

LEFT_COLOR = QColor("#e8590c")
RIGHT_COLOR = QColor("#2f7fb5")
EDGE = QColor("#ffffff")
LANE_LINE = QColor(255, 255, 255, 24)
BEAT_LINE = QColor(255, 255, 255, 30)
JUDGE_LINE = QColor(255, 255, 255, 150)
CAP_FILL = QColor(26, 33, 42)
CAP_EDGE = QColor(86, 96, 110)
TEXT = QColor(200, 210, 220)

CAP_PRESS_MS = 180.0
CAP_PRESS_MIN = 0.70


class FallingView(QWidget):
    LEAD_MS = 1500.0
    JUDGE_RATIO = 0.86
    NOTE_H = 20.0
    PAD = 0.10
    CAP_H_RATIO = 0.06
    CAP_GAP_RATIO = 0.025
    CAP_BOTTOM_RATIO = 0.015

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 380)
        self.setFocusPolicy(Qt.StrongFocus)
        self.notes: list[dict] = []
        self._press: list[float] = []
        self.lanes = 4
        self.speed = 100.0
        self.division = 8
        self.bpm = 180.0
        self.cap_times: list[float] = []     # 切分线时刻（4/8/16/32 分）
        self.chart_time = 0.0
        self._press_until: dict[int, float] = {}
        self._last_time = 0.0
        self.setFont(QFont("Consolas", 8))

    # ------------------------------------------------------------------ data
    def set_chart(self, bpm: float, notes, lanes: int = 4, speed: float = 100.0,
                  division: int = 8, cap_times=None):
        self.bpm = float(bpm or 0.0)
        self.notes = sorted(list(notes or []), key=lambda n: n.get("press_time", 0.0))
        self._press = [float(n["press_time"]) for n in self.notes]
        self.lanes = lanes if lanes in LANE_CHOICES else 4
        self.speed = max(5.0, float(speed or 100.0))
        self.division = division if division in DIVISIONS else 8
        self.cap_times = list(cap_times or [])
        self.chart_time = 0.0
        self._last_time = 0.0
        self._press_until.clear()
        self.update()

    def set_cap_times(self, times):
        self.cap_times = list(times or [])
        self.update()

    def set_time(self, ms: float):
        now = max(0.0, float(ms))
        # 跨越 press_time 时触发判定框反馈
        if self._press:
            i0 = bisect.bisect_right(self._press, self._last_time)
            i1 = bisect.bisect_right(self._press, now)
            for i in range(i0, min(i1, len(self.notes))):
                self._press_until[self.notes[i]["lane"]] = self._press[i] + CAP_PRESS_MS
        self._last_time = now
        self.chart_time = now
        self.update()

    def reset(self):
        self.chart_time = 0.0
        self._last_time = 0.0
        self._press_until.clear()
        self.update()

    def _lead(self) -> float:
        return self.LEAD_MS * 100.0 / self.speed

    # ---------------------------------------------------------------- paint
    def _layout(self, w: float, h: float):
        cap_h = max(10.0, min(44.0, h * self.CAP_H_RATIO))
        cap_gap = max(4.0, h * self.CAP_GAP_RATIO)
        bottom = max(4.0, h * self.CAP_BOTTOM_RATIO)
        judge_y = h - bottom - cap_h - cap_gap
        return cap_h, cap_gap, bottom, judge_y

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor("#0b0f14"))
        grad.setColorAt(1.0, QColor("#141b23"))
        p.fillRect(self.rect(), grad)

        lanes = self.lanes
        lw = w / lanes
        cap_h, cap_gap, bottom, judge_y = self._layout(w, h)
        lead = self._lead()

        # 轨道分隔
        p.setPen(QPen(LANE_LINE, 1))
        for i in range(1, lanes):
            p.drawLine(QPointF(i * lw, 0.0), QPointF(i * lw, judge_y))
        p.setPen(QPen(QColor(255, 255, 255, 46), 1))
        p.drawLine(QPointF(lanes // 2 * lw, 0.0), QPointF(lanes // 2 * lw, judge_y))

        # 切分线
        if self.cap_times:
            p.setPen(QPen(BEAT_LINE, 1))
            i0 = bisect.bisect_left(self.cap_times, self.chart_time)
            for bt in self.cap_times[i0:]:
                dy = (bt - self.chart_time) / lead * judge_y
                if dy > judge_y + 2:
                    break
                if dy >= -2:
                    p.drawLine(QPointF(0.0, judge_y - dy), QPointF(w, judge_y - dy))

        # 音符
        per_hand = max(1, lanes // 2)
        nw = lw * (1 - 2 * self.PAD)
        start = max(0, bisect.bisect_left(self._press, self.chart_time - lead) - 1) if self._press else 0
        for i in range(start, len(self.notes)):
            n = self.notes[i]
            t = self._press[i]
            dy = (t - self.chart_time) / lead * judge_y
            if dy > judge_y + 40:
                break
            lane = n["lane"]
            x0 = lane * lw + lw * self.PAD
            color = LEFT_COLOR if lane < per_hand else RIGHT_COLOR
            rel = n.get("release_time")
            is_hold = bool(n.get("is_hold")) and rel is not None and rel > t + 1.0

            if is_hold:
                y_rel = judge_y - (rel - self.chart_time) / lead * judge_y
                top = y_rel
                bottom_y = judge_y if t <= self.chart_time else judge_y - dy
                if bottom_y < top:
                    top, bottom_y = bottom_y, top
                if bottom_y < -40 or top > judge_y + 4:
                    continue
                top = max(top, -20.0)
                bottom_y = min(bottom_y, judge_y)
                p.setPen(QPen(EDGE, 1))
                p.setBrush(color)
                p.drawRoundedRect(QRectF(x0, top, nw, max(2.0, bottom_y - top)), 3, 3)
            else:
                y = judge_y - dy
                if y < -40 or y > judge_y + 40:
                    continue
                p.setPen(QPen(EDGE, 1))
                p.setBrush(color)
                p.drawRoundedRect(QRectF(x0, y - self.NOTE_H / 2, nw, self.NOTE_H), 4, 4)

        # 判定线
        p.setPen(QPen(JUDGE_LINE, 2))
        p.drawLine(QPointF(0.0, judge_y), QPointF(w, judge_y))

        # 判定框
        for lane in range(lanes):
            x0 = lane * lw + lw * self.PAD * 0.5
            cw0 = lw * (1 - self.PAD)
            sc = CAP_PRESS_MIN if (lane in self._press_until
                                   and self.chart_time < self._press_until[lane]) else 1.0
            cw, chh = cw0 * sc, cap_h * sc
            p.setPen(QPen(CAP_EDGE, 1))
            p.setBrush(CAP_FILL)
            p.drawRoundedRect(QRectF(x0 + (cw0 - cw) / 2,
                                     judge_y + cap_gap + (cap_h - chh) / 2, cw, chh), 3, 3)

        p.setPen(TEXT)
        idx = bisect.bisect_right(self._press, self.chart_time) if self._press else 0
        p.drawText(8, 15, f"{self.lanes}K   流速 {self.speed:.0f}   {self.division}分切分   "
                          f"BPM {self.bpm:g}   t={self.chart_time / 1000:.2f}s   "
                          f"#{idx}/{len(self.notes)}")
        p.end()
