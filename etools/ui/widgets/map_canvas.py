"""Mercator map with a selectable tile underlay and a WGS84 GPS track."""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QWidget

from etools import __version__
from etools.core.map_basemap import (
    DEFAULT_BASEMAP,
    from_tile_latlon,
    tile_url,
    to_tile_latlon,
)
from etools.core.map_proj import TILE, latlon_to_world, overzoom_source, world_to_latlon
from etools.i18n import tr

_AGENT = f"ETools/{__version__} (desktop GPS map)".encode()
DEFAULT_TRACK = "#FF1F3D"
_TRACK_WIDTH = 5
_HALO_WIDTH = 9
_OVERZOOM = 5
_INFLIGHT = 8
_TileKey = tuple[str, int, int, int]


def tile_is_unavailable(image: QImage) -> bool:
    """Esri answers a missing zoom with a flat gray JPEG instead of an error."""
    width, height = image.width(), image.height()
    if width < 32 or height < 32:
        return True
    points = (
        (width // 8, height // 8),
        (width // 2, height // 8),
        (width * 7 // 8, height // 2),
        (width // 8, height * 7 // 8),
        (width // 2, height * 3 // 4),
        (width // 2, height // 2),
    )
    gray = 0
    for x, y in points:
        color = image.pixelColor(x, y)
        channels = (color.red(), color.green(), color.blue())
        if max(channels) - min(channels) <= 8 and 190 <= channels[0] <= 245:
            gray += 1
    return gray >= len(points) - 1


def _outline(color: QColor) -> QColor:
    luma = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    if luma >= 170:
        return QColor(11, 18, 32, 230)
    return QColor(255, 255, 255, 235)


class MapCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self._zoom = 3
        self._center = latlon_to_world(20.0, 0.0, self._zoom)
        self._points: list[tuple[float, float]] = []
        self._tiles: dict[_TileKey, QPixmap] = {}
        self._missing: set[_TileKey] = set()
        self._inflight: set[_TileKey] = set()
        self.track_color = QColor(DEFAULT_TRACK)
        self._replies: set[QNetworkReply] = set()
        self._failures: dict[_TileKey, tuple[int, float]] = {}
        self._drag: QPoint | None = None
        self._closing = False
        self._epoch = 0
        self.basemap = DEFAULT_BASEMAP
        self._net = QNetworkAccessManager(self)
        self.setMouseTracking(True)

    def clear(self) -> None:
        self._points.clear()
        self.update()

    def points(self) -> list[tuple[float, float]]:
        """Track points as WGS84 ``(lat, lon)``, oldest first."""
        return list(self._points)

    def add_point(self, lat: float, lon: float) -> None:
        self._points.append((float(lat), float(lon)))
        if len(self._points) > 2000:
            del self._points[:-2000]
        if len(self._points) == 1:
            self._zoom = 12
            self._center = self._world(lat, lon)
        self.update()

    def set_basemap(self, basemap: str) -> None:
        """Switch tile source and keep the view on the same WGS84 point."""
        source = basemap if basemap in {"amap", "esri", "osm", "none"} else DEFAULT_BASEMAP
        if source == self.basemap:
            return
        lat, lon = world_to_latlon(self._center[0], self._center[1], self._zoom)
        wgs_lat, wgs_lon = from_tile_latlon(self.basemap, lat, lon)
        self.basemap = source
        placed = to_tile_latlon(source, wgs_lat, wgs_lon)
        self._center = latlon_to_world(placed[0], placed[1], self._zoom)
        self._epoch += 1
        self._tiles.clear()
        self._missing.clear()
        self._failures.clear()
        self._inflight.clear()
        for reply in list(self._replies):
            reply.abort()
        self.update()

    def set_track_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self.track_color = QColor(color)
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
        dim = self.palette().mid().color()
        painter.fillRect(self.rect(), base)
        if self.basemap != "none":
            self._paint_tiles(painter)
        else:
            self._paint_grid(painter, dim)
        self._paint_track(painter)
        painter.setPen(dim)
        label = tr("map.points", n=len(self._points)) if self._points else tr("map.empty")
        painter.drawText(12, 20, label)

    def _world(self, lat: float, lon: float) -> tuple[float, float]:
        lat, lon = to_tile_latlon(self.basemap, lat, lon)
        return latlon_to_world(lat, lon, self._zoom)

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
                key = (self.basemap, self._zoom, tx, ty)
                pix = self._tiles.get(key)
                if pix is not None:
                    painter.drawPixmap(QPointF(ox + tx * TILE, oy + ty * TILE), pix)
                    continue
                if key in self._missing:
                    self._paint_ancestor(painter, ox, oy, tx, ty)
                    continue
                self._request(key)

    def _paint_ancestor(self, painter: QPainter, ox: float, oy: float, tx: int, ty: int) -> None:
        """Stretch the nearest real parent over a zoom Esri does not publish."""
        for levels in range(1, _OVERZOOM + 1):
            parent_zoom = self._zoom - levels
            if parent_zoom < 0:
                return
            parent_x, parent_y, sx, sy, size = overzoom_source(tx, ty, levels)
            parent_key = (self.basemap, parent_zoom, parent_x, parent_y)
            parent = self._tiles.get(parent_key)
            if parent is None:
                if parent_key not in self._missing:
                    self._request(parent_key)
                continue
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(
                QRectF(ox + tx * TILE, oy + ty * TILE, TILE, TILE),
                parent,
                QRectF(sx, sy, size, size),
            )
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            return

    def _request(self, key: _TileKey) -> None:
        if (
            self._closing
            or key in self._missing
            or key in self._inflight
            or len(self._inflight) >= _INFLIGHT
        ):
            return
        _count, retry_at = self._failures.get(key, (0, 0.0))
        if time.monotonic() < retry_at:
            return
        _source, zoom, tx, ty = key
        url = tile_url(self.basemap, zoom, tx, ty)
        if not url:
            return
        self._inflight.add(key)
        epoch = self._epoch
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", _AGENT)
        reply = self._net.get(request)
        self._replies.add(reply)
        reply.finished.connect(lambda k=key, r=reply, epoch=epoch: self._store_tile(k, r, epoch))

    def _store_tile(self, key: _TileKey, reply, epoch: int) -> None:
        self._replies.discard(reply)
        self._inflight.discard(key)
        if self._closing or epoch != self._epoch:
            reply.deleteLater()
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            count = self._failures.get(key, (0, 0.0))[0] + 1
            self._failures[key] = (count, time.monotonic() + min(300.0, 2.0**count))
            reply.deleteLater()
            return
        image = QImage.fromData(reply.readAll())
        reply.deleteLater()
        if image.isNull() or tile_is_unavailable(image):
            self._missing.add(key)
            self.update()
            return
        self._failures.pop(key, None)
        self._tiles[key] = QPixmap.fromImage(image)
        if len(self._tiles) > 128:
            self._tiles.pop(next(iter(self._tiles)))
        self.update()

    def _paint_track(self, painter: QPainter) -> None:
        if not self._points:
            return
        ox, oy = self._origin()
        points: list[QPointF] = []
        for lat, lon in self._points:
            x, y = self._world(lat, lon)
            points.append(QPointF(ox + x, oy + y))
        color = self.track_color
        for pen in (QPen(_outline(color), _HALO_WIDTH), QPen(color, _TRACK_WIDTH)):
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for index in range(1, len(points)):
                painter.drawLine(points[index - 1], points[index])
        current = points[-1]
        painter.setPen(QPen(_outline(color), 2))
        painter.setBrush(color)
        painter.drawEllipse(current, 7, 7)
