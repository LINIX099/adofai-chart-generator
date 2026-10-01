"""谱面路径视图：把 angleData 复算成 2D 轨迹，用来看「会不会打结」。

这是 4K 下落式**看不到**的那一面（下落式只显示"什么时刻按哪个键"）。
* 折线 = 方块中心轨迹（相邻方块间距 = 2R）
* 圆点 = 每个方块；当前方块高亮
* 红圈 = 与近邻距离 < 1.75R 的「贴太近」方块
* 颜色 = 该层是否用了 Twirl（青 = 未翻转 / 品红 = 翻转）
* 播放头 = 按时间反查当前层号
"""
from __future__ import annotations

import bisect
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

BG = QColor("#0f1319")
PATH = QColor(255, 255, 255, 60)
TILE_N = QColor("#4fc3f7")
TILE_T = QColor("#e060c0")
CUR = QColor("#ffd166")
BAD = QColor("#ff5252")
TEXT = QColor("#c8d2dd")


class PathView(QWidget):
    seekRequested = Signal(int)        # floor index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.floors: list = []
        self.times: list[float] = []    # 每层相对时间(ms)
        self.base_ms = 0.0              # 第 0 层的绝对时间
        self.cur_floor = 0
        self.scale = 20.0
        self.cx = 0.0
        self.cy = 0.0
        self.show_all = True
        self.follow = True
        self._drag = None
        self.setFont(QFont("Consolas", 8))

    # ------------------------------------------------------------------ data
    def set_data(self, floors, times, base_ms: float = 0.0):
        self.floors = list(floors or [])
        self.times = list(times or [])
        self.base_ms = float(base_ms)
        self.fit()
        self.update()

    def fit(self):
        self.show_all = True
        self.update()

    def set_playhead_ms(self, ms: float):
        if not self.times:
            return
        rel = ms - self.base_ms
        i = max(0, min(len(self.times) - 1, bisect.bisect_right(self.times, rel) - 1))
        self.cur_floor = i
        if self.follow:
            f = self.floors[i]
            self.cx, self.cy = f.x, f.y
        self.update()

    def current_floor(self) -> int:
        return self.cur_floor

    # ------------------------------------------------------------------ geom
    def _bounds(self):
        if not self.floors:
            return (-1, -1, 1, 1)
        xs = [f.x for f in self.floors]
        ys = [f.y for f in self.floors]
        return (min(xs), min(ys), max(xs), max(ys))

    def _screen(self, x, y, sc, ox, oy):
        return QPointF(ox + x * sc, oy - y * sc)

    # ---------------------------------------------------------------- events
    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if d == 0:
            return
        if e.modifiers() & Qt.ShiftModifier:
            self.follow = not self.follow
        else:
            f = 1.15 if d > 0 else 1 / 1.15
            self.scale = max(0.5, min(400.0, self.scale * f))
            self.show_all = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position(), self.cx, self.cy)
        elif e.button() == Qt.MiddleButton and self.floors:
            self.follow = not self.follow
            self.update()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            p0, cx0, cy0 = self._drag
            self.cx = cx0 - (e.position().x() - p0.x()) / self.scale
            self.cy = cy0 + (e.position().y() - p0.y()) / self.scale
            self.follow = False
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG)
        w, h = self.width(), self.height()
        if not self.floors:
            p.setPen(TEXT)
            p.drawText(10, 20, "尚未生成谱面")
            p.end()
            return

        x0, y0, x1, y1 = self._bounds()
        if self.show_all:
            sw = max(1e-6, x1 - x0)
            sh = max(1e-6, y1 - y0)
            self.scale = min((w - 60) / sw, (h - 60) / sh)
            self.scale = max(0.4, min(200.0, self.scale))
            self.cx = (x0 + x1) / 2
            self.cy = (y0 + y1) / 2
        ox, oy = w / 2 - self.cx * self.scale, h / 2 + self.cy * self.scale

        # 轨迹折线
        p.setPen(QPen(PATH, 1))
        prev = None
        for f in self.floors:
            q = self._screen(f.x, f.y, self.scale, ox, oy)
            if prev is not None:
                p.drawLine(prev, q)
            prev = q

        # 方块
        r = max(2.5, min(7.0, self.scale * 0.6))
        n = len(self.floors)
        step = max(1, n // 4000)          # 超长谱面抽样画点
        # 重叠检测（抽样窗口内）—— 与求解层同一判据 1.75R
        bad = set()
        recent = 26
        for i in range(n):
            for j in range(max(0, i - recent), i - 1):
                if math.hypot(self.floors[i].x - self.floors[j].x,
                              self.floors[i].y - self.floors[j].y) < 1.75:
                    bad.add(i)
                    bad.add(j)

        for i in range(0, n, step):
            f = self.floors[i]
            q = self._screen(f.x, f.y, self.scale, ox, oy)
            if q.x() < -20 or q.x() > w + 20 or q.y() < -20 or q.y() > h + 20:
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(TILE_T if f.twirl else TILE_N)
            p.drawEllipse(q, r * 0.8, r * 0.8)
        for i in bad:
            f = self.floors[i]
            q = self._screen(f.x, f.y, self.scale, ox, oy)
            if -20 <= q.x() <= w + 20 and -20 <= q.y() <= h + 20:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(BAD, 1.4))
                p.drawEllipse(q, r, r)

        # 当前方块
        if 0 <= self.cur_floor < n:
            f = self.floors[self.cur_floor]
            q = self._screen(f.x, f.y, self.scale, ox, oy)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(CUR, 2))
            p.drawEllipse(q, r * 2.2, r * 2.2)

        # 文字
        p.setPen(TEXT)
        n_tw = sum(1 for f in self.floors if f.twirl)
        p.drawText(8, 14, f"方块 {n}   Twirl {n_tw}   "
                          f"贴太近 {len(bad)}   floor #{self.cur_floor + 1}/{n}   "
                          f"{'自适应' if self.show_all else f'缩放 {self.scale:.1f}px/R'}   "
                          f"{'跟随' if self.follow else '自由'}")
        p.drawText(8, h - 6, "滚轮=缩放  Shift+滚轮=自适应  左键拖动=平移  中键=切跟随")
        p.end()
