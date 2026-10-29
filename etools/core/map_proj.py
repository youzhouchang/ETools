"""Web-Mercator helpers for the map page. Zoom 0 is one 256px world tile."""

from __future__ import annotations

import math

TILE = 256


def _lat_rad(lat: float) -> float:
    return math.radians(max(-85.05112878, min(85.05112878, lat)))


def latlon_to_world(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    scale = TILE * (2**int(zoom))
    x = (lon + 180.0) / 360.0 * scale
    lat_r = _lat_rad(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * scale
    return x, y


def world_to_latlon(x: float, y: float, zoom: int) -> tuple[float, float]:
    scale = TILE * (2**int(zoom))
    lon = x / scale * 360.0 - 180.0
    merc = math.pi * (1.0 - 2.0 * y / scale)
    lat = math.degrees(math.atan(math.sinh(merc)))
    return lat, lon


def tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    x, y = latlon_to_world(lat, lon, zoom)
    limit = 2**int(zoom)
    return int(x // TILE) % limit, int(y // TILE) % limit


def overzoom_source(x: int, y: int, levels_up: int) -> tuple[int, int, float, float, float]:
    """Parent tile index and this child's source square inside that 256px tile."""
    levels = max(1, int(levels_up))
    scale = 1 << levels
    size = TILE / scale
    return x >> levels, y >> levels, (x & (scale - 1)) * size, (y & (scale - 1)) * size, size
