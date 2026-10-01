# -*- coding: utf-8 -*-
"""谱面预览（瓷砖级）：把 Chart 画成跟游戏里长得一样的方块路径。

为什么重做而不是改 `path_view`
------------------------------
`path_view` 把整条路径自适应塞进窗口，还**每帧**跑一次 O(n×26) 的重叠检测 ——
对几百格以上的谱面既看不清也卡。这边：

* **瓷砖级**：方块画成游戏里的样子（边长 2R、按自身角度旋转、相邻格贴边），
  而不是小圆点。一眼就能看出拐角、双押、三角形/方块段。
* **几何全部缓存**：重叠检测、包围盒、逐格旋转角只在 `set_data` 算一次。
* **跟随播放头**：默认把当前格放在画面偏下位置，滚轮缩放、左键拖动平移、中键切跟随。
* **双押/中旋单独标色**：折返格、midspin 999 一眼可见。
* **拖动 / 点击定位**：点空格子直接 seek 过去（发 `seekRequested`）。
* **按 travel 上色**（可选）：直白看出哪里快哪里慢。

坐标约定与 `core.solve._apply` 一致：相邻格中心距 = 2 × planar_radius。
"""
from __future__ import annotations

import bisect
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPen, QPolygonF,
                           QTransform)
from PySide6.QtWidgets import QWidget

BG = QColor("#0d1117")
GRID = QColor(255, 255, 255, 14)
TRACK = QColor(255, 255, 255, 46)
TEXT = QColor("#c9d4e0")
DIM = QColor("#6b7785")

FILL = QColor("#7fb3d5")
FILL_TW = QColor("#c07ad0")
FILL_X = QColor("#f2a63b")          # 中旋折返格
EDGE = QColor("#e8eef5")
CUR = QColor("#ffd166")
BAD = QColor("#ff5252")
PAUSE = QColor("#4fd1c5")
MID = QColor("#ff6b6b")

#: planar_radius（与 core.solve.SolveParams 默认一致）；相邻格中心距 = 2R
PLANAR_RADIUS = 1.0
TILE_STEP = 2.0 * PLANAR_RADIUS
#: 判定「靠太近」的世界距离（方块边长 2.0，小于 1.0 就是肉眼可辨的叠）
NEAR_R = 1.0
RECENT = 32


class ChartView(QWidget):
    seekRequested = Signal(int)          # floor index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFont(QFont("Consolas", 8))

        self.floors: list = []
        self.times: list[float] = []
        self.base_ms = 0.0
        self.bpm0 = 180.0
        self.cur = 0
        self.follow = True
        self.span = 34.0                 # 纵向可见格数（zoom = h/span/step）
        self.color_mode = "type"          # type | travel
        self.show_bad = True
        self._cx = self._cy = 0.0
        self._drag = None
        self._hover = -1

        # ---- 缓存（set_data 里一次性算好）
        self._xs: list[float] = []
        self._ys: list[float] = []
        self._rot: list[float] = []       # 方块自身旋转（度）
        self._kind: list[int] = []        # 0 普通 1 Twirl 2 折返格 3 midspin
        self._tv: list[float] = []        # travel（度）
        self._pause: list[bool] = []
        self._bad: set[int] = set()
        self._bounds = (0.0, 0.0, 0.0, 0.0)
        self._mid_of: dict[int, int] = {}  # 999 下标 → 折返格下标

    # ------------------------------------------------------------------ data
    def set_data(self, floors, times, base_ms: float = 0.0, *,
                 bpm0: float = 180.0, dp_pairs=None):
        self.floors = list(floors or [])
        self.times = list(times or [])
        self.base_ms = float(base_ms)
        self.bpm0 = float(bpm0 or 180.0)
        n = len(self.floors)
        self._xs = [f.x for f in self.floors]
        self._ys = [f.y for f in self.floors]
        self._tv = [f.travel for f in self.floors]
        self._rot = [-(f.angle if abs(f.angle - 999.0) > 1e-9 else 0.0)
                     for f in self.floors]
        self._pause = [f.pause_beats > 1e-9 for f in self.floors]
        self._mid_of = {}
        for (ix, iy, _ib) in (dp_pairs or []):
            if 0 <= iy < n:
                self._mid_of[iy] = ix
        self._kind = []
        for i, f in enumerate(self.floors):
            if abs(f.angle - 999.0) < 1e-9:
                self._kind.append(3)
            elif i in self._mid_of:
                self._kind.append(2)
            elif f.twirl:
                self._kind.append(1)
            else:
                self._kind.append(0)
        if self._xs:
            self._bounds = (min(self._xs), min(self._ys),
                            max(self._xs), max(self._ys))
        else:
            self._bounds = (0.0, 0.0, 0.0, 0.0)
        self._bad = self._find_bad()
        self.cur = min(self.cur, max(0, n - 1))
        self.update()

    def _find_bad(self) -> set[int]:
        """与近邻距离 < NEAR_R 的格子。只在 set_data 里算一次。"""
        n = len(self._xs)
        bad: set[int] = set()
        if n < 2:
            return bad
        for i in range(n):
            xi, yi = self._xs[i], self._ys[i]
            lo = max(0, i - RECENT)
            for j in range(lo, i - 1):
                dx = xi - self._xs[j]
                dy = yi - self._ys[j]
                if dx * dx + dy * dy < NEAR_R * NEAR_R:
                    bad.add(i)
                    bad.add(j)
        return bad

    def set_playhead_ms(self, ms: float, *, keep_follow=True):
        if not self.times:
            return
        rel = ms - self.base_ms
        i = max(0, min(len(self.times) - 1,
                       bisect.bisect_right(self.times, rel) - 1))
        self.cur = i
        self.update()

    def current_floor(self) -> int:
        return self.cur

    def reset_view(self):
        self.follow = True
        self.update()

    # ---------------------------------------------------------------- events
    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if not d:
            return
        if e.modifiers() & Qt.ShiftModifier:
            self.follow = not self.follow
        else:
            self.span = max(6.0, min(400.0, self.span * (1 / 1.2 if d > 0
                                                          else 1.2)))
            self.follow = False
        self.update()

    def _scale(self) -> float:
        return max(0.4, self.height() / max(1e-6, self.span * TILE_STEP))

    def _origin(self, w: int, h: int):
        sc = self._scale()
        if self.follow and 0 <= self.cur < len(self._xs):
            # 当前格放在画面偏下位置，前方留出视野
            self._cx, self._cy = self._xs[self.cur], self._ys[self.cur]
            return (w / 2 - self._cx * sc,
                    h * 0.72 + self._cy * sc, sc)
        return (w / 2 - self._cx * sc, h / 2 + self._cy * sc, sc)

    def _screen(self, x, y, sc, ox, oy):
        return QPointF(ox + x * sc, oy - y * sc)

    def _world(self, px, py, w, h):
        sc = self._scale()
        ox, oy = w / 2 - self._cx * sc, h / 2 + self._cy * sc
        return ((px - ox) / sc, (oy - py) / sc)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position(), self._cx, self._cy)
        elif e.button() == Qt.MiddleButton:
            self.follow = not self.follow
            self.update()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            p0, cx0, cy0 = self._drag
            sc = self._scale()
            self._cx = cx0 - (e.position().x() - p0.x()) / sc
            self._cy = cy0 + (e.position().y() - p0.y()) / sc
            self.follow = False
            self.update()
            return
        # 悬停：找最近的格子（只在小窗口内找，避免每次全扫）
        if self.floors:
            wx, wy = self._world(e.position().x(), e.position().y(),
                                 self.width(), self.height())
            i = self.cur
            lo, hi = max(0, i - 400), min(len(self._xs), i + 400)
            best, bd = -1, 1e9
            for j in range(lo, hi):
                dx, dy = wx - self._xs[j], wy - self._ys[j]
                d = dx * dx + dy * dy
                if d < bd:
                    best, bd = j, d
            if best >= 0 and bd < (TILE_STEP * 1.2) ** 2:
                self._hover = best
            else:
                self._hover = -1
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            p0, cx0, cy0 = self._drag
            moved = (abs(e.position().x() - p0.x())
                     + abs(e.position().y() - p0.y()))
            self._drag = None
            if moved < 4 and self._hover >= 0:
                self.cur = self._hover
                self.seekRequested.emit(self._hover)

    def leaveEvent(self, _e):
        self._hover = -1
        self.update()

    # ---------------------------------------------------------------- paint
    def _tile_color(self, i: int) -> QColor:
        k = self._kind[i]
        if k == 3:
            return MID
        if k == 2:
            return FILL_X
        if k == 1:
            return FILL_TW
        if self.color_mode == "travel":
            tv = max(0.0, min(360.0, self._tv[i]))
            # travel 0(急转) → 暖红 ; 180(直线) → 中性 ; 360(缓) → 冷蓝
            t = tv / 360.0
            if t < 0.5:
                a, b, u = QColor("#e05a3a"), QColor("#8fb8cc"), t / 0.5
            else:
                a, b, u = QColor("#8fb8cc"), QColor("#5a7fd0"), (t - 0.5) / 0.5
            return QColor(int(a.red() + (b.red() - a.red()) * u),
                          int(a.green() + (b.green() - a.green()) * u),
                          int(a.blue() + (b.blue() - a.blue()) * u))
        return FILL

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG)
        w, h = self.width(), self.height()
        n = len(self.floors)
        if not n:
            p.setPen(TEXT)
            p.drawText(12, 22, "尚未生成谱面")
            p.end()
            return

        ox, oy, sc = self._origin(w, h)
        half = TILE_STEP * 0.5 * sc

        # 视野内的格号范围（世界坐标近似）
        lo_wx = (0 - ox) / sc
        hi_wx = (w - ox) / sc
        lo_wy = (oy - h) / sc
        hi_wy = (oy - 0) / sc
        pad = TILE_STEP * 2
        vis = []
        for i in range(n):
            if (lo_wx - pad <= self._xs[i] <= hi_wx + pad
                    and lo_wy - pad <= self._ys[i] <= hi_wy + pad):
                vis.append(i)
        if not vis:
            vis = list(range(max(0, self.cur - 20),
                             min(n, self.cur + 20)))

        self._paint_grid(p, w, h, sc, ox, oy)

        # 轨道连线
        p.setPen(QPen(TRACK, max(1.0, sc * 0.25)))
        prev = None
        for i in vis:
            q = self._screen(self._xs[i], self._ys[i], sc, ox, oy)
            if prev is not None:
                p.drawLine(prev, q)
            prev = q

        # 方块（旋转的正方形）
        i0, i1 = vis[0], vis[-1]
        stepdraw = 1
        if len(vis) > 3000:
            stepdraw = max(1, len(vis) // 3000)
        for i in vis[::stepdraw]:
            q = self._screen(self._xs[i], self._ys[i], sc, ox, oy)
            edge = BAD if (self.show_bad and i in self._bad) else None
            self._draw_tile(p, q, half, self._rot[i], self._tile_color(i),
                            edge=edge, wid=1.8 if edge else 1.0)

        # Pause 标记
        p.setPen(QPen(PAUSE, 2))
        for i in vis:
            if self._pause[i]:
                q = self._screen(self._xs[i], self._ys[i], sc, ox, oy)
                p.drawLine(QPointF(q.x() - half * 0.5, q.y()),
                           QPointF(q.x() + half * 0.5, q.y()))

        # 当前格
        if 0 <= self.cur < n:
            q = self._screen(self._xs[self.cur], self._ys[self.cur], sc, ox, oy)
            self._draw_tile(p, q, half, self._rot[self.cur],
                            QColor(255, 209, 102, 90), edge=CUR, wid=2.4)
            # 指向下一格的方向箭头
            if self.cur + 1 < n:
                q2 = self._screen(self._xs[self.cur + 1], self._ys[self.cur + 1],
                                  sc, ox, oy)
                p.setPen(QPen(CUR, 1.6))
                p.drawLine(q, q2)

        # 悬停格
        if 0 <= self._hover < n and self._hover != self.cur:
            q = self._screen(self._xs[self._hover], self._ys[self._hover],
                             sc, ox, oy)
            self._draw_tile(p, q, half, self._rot[self._hover], None,
                            edge=EDGE, wid=1.2)

        self._paint_hud(p, w, h, n)
        p.end()

    def _draw_tile(self, p: QPainter, q: QPointF, half: float, rot: float,
                   fill: QColor | None, *, edge=None, wid: float = 1.0):
        if half < 0.6:
            # 太小就退回圆点，省得糊成一团
            p.setPen(Qt.NoPen)
            p.setBrush(fill or QColor(0, 0, 0, 0))
            p.drawEllipse(q, 1.5, 1.5)
            return
        p.save()
        p.translate(q)
        p.rotate(rot)
        r = QRectF(-half, -half, half * 2, half * 2)
        if fill is not None:
            p.setBrush(QBrush(fill))
        else:
            p.setBrush(Qt.NoBrush)
        p.setPen(QPen(edge or QColor(255, 255, 255, 70), wid))
        p.drawRect(r)
        p.restore()

    def _paint_grid(self, p, w, h, sc, ox, oy):
        """按 base bpm 画拍线，方便对时间。"""
        if self.bpm0 <= 0 or sc <= 0:
            return
        beat_px = 60000.0 / self.bpm0 / 1000.0 * 0  # 时间轴不在这张图里
        _ = beat_px
        p.setPen(QPen(GRID, 1))
        # 以当前格为锚画一组等距参考线（世界格距 2R）
        if 0 <= self.cur < len(self._xs):
            bx, by = self._xs[self.cur], self._ys[self.cur]
            for k in range(-40, 41):
                y = by + k * TILE_STEP
                q = self._screen(bx, y, sc, ox, oy)
                if -20 <= q.y() <= h + 20:
                    p.drawLine(QPointF(0, q.y()), QPointF(w, q.y()))

    def _paint_hud(self, p, w, h, n):
        p.setPen(TEXT)
        f = self.floors[self.cur] if 0 <= self.cur < n else None
        spd = (self.bpm0 / f.bpm) if (f and f.bpm) else 1.0
        t = self.times[self.cur] + self.base_ms if 0 <= self.cur < len(self.times) else 0.0
        n_dp = sum(1 for k in self._kind if k in (2, 3))
        head = (f"格 #{self.cur + 1}/{n}   t={t / 1000:.3f}s   "
                f"travel {f.travel:.0f}°   " if f else f"格 #-/{n}   ")
        head += (f"速度 ×{1 / spd:.2f}   " if spd else "")
        head += (f"双押 {n_dp // 2} 处   " if n_dp else "")
        head += (f"贴太近 {len(self._bad)}   " if self._bad else "")
        head += f"{'跟随' if self.follow else '自由'}  可见 {self.span:.0f} 格"
        p.drawText(10, 16, head)
        if 0 <= self._hover < n:
            fh = self.floors[self._hover]
            p.setPen(DIM)
            p.drawText(10, 32, f"悬停 格 #{self._hover + 1}  "
                               f"angleData {fh.angle:g}°  travel {fh.travel:.0f}°")
        p.setPen(DIM)
        p.drawText(10, h - 8,
                   "滚轮=缩放  Shift+滚轮=切跟随  左键拖动=平移  左键点格=跳转  "
                   "中键=切跟随")
