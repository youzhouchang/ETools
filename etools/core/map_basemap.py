"""Basemap tile URLs and the datum each provider paints in.

Device coordinates stay WGS84. Amap roads are GCJ-02, so a track must be
converted before it is projected into that tile grid. Esri uses the same
Web-Mercator indices as OSM, but the path is ``z/y/x`` rather than ``z/x/y``.
"""

from __future__ import annotations

import math

BASEMAPS = ("amap", "esri", "osm", "none")
DEFAULT_BASEMAP = "amap"

_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lat: float, lon: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _delta(lat: float, lon: float) -> tuple[float, float]:
    x = lon - 105.0
    y = lat - 35.0
    d_lat = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    d_lat += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    d_lat += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    d_lat += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    d_lon = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    d_lon += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    d_lon += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    d_lon += (
        150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)
    ) * 2.0 / 3.0
    rad = math.radians(lat)
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (_A / sqrt_magic * math.cos(rad) * math.pi)
    return d_lat, d_lon


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """Shift a WGS84 point onto the GCJ-02 tiles Amap serves. Identity outside China."""
    if _out_of_china(lat, lon):
        return lat, lon
    d_lat, d_lon = _delta(lat, lon)
    return lat + d_lat, lon + d_lon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """Inverse of :func:`wgs84_to_gcj02`. Two iterations keep the view from drifting."""
    if _out_of_china(lat, lon):
        return lat, lon
    wgs_lat, wgs_lon = lat, lon
    for _ in range(2):
        got_lat, got_lon = wgs84_to_gcj02(wgs_lat, wgs_lon)
        wgs_lat += lat - got_lat
        wgs_lon += lon - got_lon
    return wgs_lat, wgs_lon


def _uses_gcj02(basemap: str) -> bool:
    return basemap == "amap"


def to_tile_latlon(basemap: str, lat: float, lon: float) -> tuple[float, float]:
    """WGS84 device coordinate to the datum of this basemap's tiles."""
    if _uses_gcj02(basemap):
        return wgs84_to_gcj02(lat, lon)
    return lat, lon


def from_tile_latlon(basemap: str, lat: float, lon: float) -> tuple[float, float]:
    """Tile datum back to WGS84, so switching basemaps keeps the same place."""
    if _uses_gcj02(basemap):
        return gcj02_to_wgs84(lat, lon)
    return lat, lon


def tile_url(basemap: str, zoom: int, x: int, y: int) -> str:
    """XYZ tile address. Empty when the basemap draws no tiles."""
    if basemap == "amap":
        host = 1 + (int(x) + int(y)) % 4
        return (
            f"https://webrd0{host}.is.autonavi.com/appmaptile"
            f"?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={zoom}"
        )
    if basemap == "esri":
        return (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            f"World_Street_Map/MapServer/tile/{zoom}/{y}/{x}"
        )
    if basemap == "osm":
        return f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
    return ""
