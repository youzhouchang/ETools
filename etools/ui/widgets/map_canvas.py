"""Mercator map with an optional OpenStreetMap tile underlay and a GPS track."""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QWidget

from etools import __version__
from etools.core.map_proj import TILE, latlon_to_world, world_to_latlon
from etools.i18n import tr

_AGENT = f"ETools/{__version__} (desktop GPS map)".encode()


class MapCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self._zoom = 3
        self._center = latlon_to_world(20.0, 0.0, self._zoom)
        self._points: list[tuple[float, float]] = []
        self._tiles: dict[tuple[int, int, int], QPixmap] = {}
        self._inflight: set[tuple[int, int, int]] = set()
        self._replies: set[QNetworkReply] = set()
        self._failures: dict[tuple[int, int, int], tuple[int, float]] = {}
        self._drag: QPoint | None = None
        self._closing = False
        self.tiles_enabled = True
        self._net = QNetworkAccessManager(self)
        self.setMouseTracking(True)

    def clear(self) -> None:
        self._points.clear()
        self.update()

    def add_point(self, lat: float, lon: float) -> None:
        self._points.append((float(lat), float(lon)))
        if len(self._points) > 2000:
            del self._points[:-2000]
        if len(self._points) == 1:
            self._zoom = 12
            self._center = latlon_to_world(lat, lon, self._zoom)
        self.update()

    def shutdown(self) -> None:
        self._closing = True
        for reply in list(self._replies):
            reply.abort()
            reply.deleteLater()
        self._replies.clear()
        self._inflight.clear()

    def wheelEvent(self, event) -> None:  # noqa: N802
        lat, lon = world_to_latlon(self._center[0], self._center[1], self._zoom)
        self._zoom = max(2, min(18, self._zoom + (1 if event.angleDelta().y() > 0 else -1)))
        self._center = latlon_to_world(lat, lon, self._zoom)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return
        now = event.position().toPoint()
        dx = now.x() - self._drag.x()
        dy = now.y() - self._drag.y()
        self._drag = now
        self._center = (self._center[0] - dx, self._center[1] - dy)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = None

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        base = self.palette().base().color()
        text = self.palette().text().color()
        dim = self.palette().mid().color()
        painter.fillRect(self.rect(), base)
        if self.tiles_enabled:
            self._paint_tiles(painter)
        self._paint_grid(painter, dim)
        self._paint_track(painter, text)
        painter.setPen(dim)
        label = tr("map.points", n=len(self._points)) if self._points else tr("map.empty")
        painter.drawText(12, 20, label)

    def _origin(self) -> tuple[float, float]:
        return (
            self.width() / 2 - self._center[0],
            self.height() / 2 - self._center[1],
        )

    def _paint_grid(self, painter: QPainter, dim) -> None:
        painter.setPen(QPen(dim, 1, Qt.PenStyle.DotLine))
        ox, oy = self._origin()
        step = TILE
        left = int((-ox) // step) * step
        top = int((-oy) // step) * step
        x = left
        while x < self.width() - ox:
            painter.drawLine(QPointF(ox + x, 0), QPointF(ox + x, self.height()))
            x += step
        y = top
        while y < self.height() - oy:
            painter.drawLine(QPointF(0, oy + y), QPointF(self.width(), oy + y))
            y += step

    def _paint_tiles(self, painter: QPainter) -> None:
        ox, oy = self._origin()
        limit = 2**self._zoom
        x0 = max(0, int((-ox) // TILE))
        y0 = max(0, int((-oy) // TILE))
        x1 = min(limit - 1, int((self.width() - ox) // TILE) + 1)
        y1 = min(limit - 1, int((self.height() - oy) // TILE) + 1)
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                key = (self._zoom, tx, ty)
                pix = self._tiles.get(key)
                if pix is not None:
                    painter.drawPixmap(QPointF(ox + tx * TILE, oy + ty * TILE), pix)
                else:
                    self._request(key)

    def _request(self, key: tuple[int, int, int]) -> None:
        if self._closing or key in self._inflight or len(self._inflight) >= 2:
            return
        _count, retry_at = self._failures.get(key, (0, 0.0))
        if time.monotonic() < retry_at:
            return
        self._inflight.add(key)
        zoom, tx, ty = key
        url = QUrl(f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png")
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", _AGENT)
        reply = self._net.get(request)
        self._replies.add(reply)
        reply.finished.connect(lambda k=key, r=reply: self._store_tile(k, r))

    def _store_tile(self, key: tuple[int, int, int], reply) -> None:
        self._replies.discard(reply)
        self._inflight.discard(key)
        if self._closing:
            reply.deleteLater()
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            count = self._failures.get(key, (0, 0.0))[0] + 1
            self._failures[key] = (count, time.monotonic() + min(300.0, 2.0**count))
            reply.deleteLater()
            return
        image = QImage.fromData(reply.readAll())
        reply.deleteLater()
        if image.isNull():
            return
        self._failures.pop(key, None)
        self._tiles[key] = QPixmap.fromImage(image)
        if len(self._tiles) > 128:
            self._tiles.pop(next(iter(self._tiles)))
        self.update()

    def _paint_track(self, painter: QPainter, color) -> None:
        if not self._points:
            return
        ox, oy = self._origin()
        painter.setPen(QPen(color, 2))
        previous: QPointF | None = None
        for lat, lon in self._points:
            x, y = latlon_to_world(lat, lon, self._zoom)
            point = QPointF(ox + x, oy + y)
            if previous is not None:
                painter.drawLine(previous, point)
            previous = point
        if previous is not None:
            painter.setBrush(color)
            painter.drawEllipse(previous, 5, 5)
