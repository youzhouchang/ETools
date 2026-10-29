"""Dashboard project: widget specs bound to a frame index or a JSON key."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

WIDGET_TYPES = ("value", "gauge", "bar", "lamp", "plot", "multiplot", "attitude3d")
ATTITUDE_MODES = ("euler", "quat")
ATTITUDE_SHAPES = ("aircraft", "quad", "cube", "horizon")
# A fine grid: 12 columns, each row 24 px. Version 1 projects used 4 columns
# and 200 px rows; those coordinates are scaled on load.
GRID_COLUMNS = 12
MAX_ROW_SPAN = 32
CELL_HEIGHT = 24
LEGACY_COL_SCALE = 3
LEGACY_ROW_SCALE = 8


@dataclass
class DashWidget:
    type: str = "value"
    title: str = ""
    unit: str = ""
    minimum: float = 0.0
    maximum: float = 100.0
    bind: str = "1"
    # Only used by "attitude3d": whether `bind` holds roll,pitch,yaw degrees
    # or a w,x,y,z quaternion, and which model draws that orientation.
    mode: str = "euler"
    shape: str = "aircraft"
    # Negative row/col means "not placed yet". The canvas snaps to GRID_COLUMNS.
    row: int = -1
    col: int = -1
    row_span: int = 1
    col_span: int = 1

    def binds(self) -> list[str]:
        return [part.strip() for part in self.bind.split(",") if part.strip()]


def lookup(frame: dict[str, float], bind: str) -> float | None:
    """Digit binds are 1-based positions. Anything else is a JSON key."""
    text = str(bind or "").strip()
    if not text or not frame:
        return None
    if text.isdigit():
        index = int(text) - 1
        values = list(frame.values())
        if 0 <= index < len(values):
            value = float(values[index])
            return value if math.isfinite(value) else None
        return None
    if text in frame:
        value = float(frame[text])
        return value if math.isfinite(value) else None
    return None


def project_to_json(widgets: list[DashWidget]) -> str:
    payload = {"version": 2, "widgets": [asdict(item) for item in widgets]}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def project_from_json(text: str) -> list[DashWidget]:
    raw = json.loads(text or "{}")
    items = raw.get("widgets", []) if isinstance(raw, dict) else []
    legacy = not isinstance(raw, dict) or _as_int(raw.get("version"), 1) < 2
    widgets: list[DashWidget] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "value")
        if kind not in WIDGET_TYPES:
            kind = "value"
        minimum_raw = item.get("minimum", 0)
        maximum_raw = item.get("maximum", 100)
        minimum = float(0 if minimum_raw is None else minimum_raw)
        maximum = float(100 if maximum_raw is None else maximum_raw)
        if not math.isfinite(minimum) or not math.isfinite(maximum):
            raise ValueError("widget range must be finite")
        mode = str(item.get("mode") or "euler")
        if mode not in ATTITUDE_MODES:
            mode = "euler"
        shape = str(item.get("shape") or "aircraft")
        if shape not in ATTITUDE_SHAPES:
            shape = "aircraft"
        row = _as_int(item.get("row"), -1) if "row" in item else -1
        col = _as_int(item.get("col"), -1) if "col" in item else -1
        row_span = max(1, _as_int(item.get("row_span"), 1))
        col_span = max(1, _as_int(item.get("col_span"), 1))
        if legacy:
            if row >= 0:
                row *= LEGACY_ROW_SCALE
            if col >= 0:
                col *= LEGACY_COL_SCALE
            row_span *= LEGACY_ROW_SCALE
            col_span *= LEGACY_COL_SCALE
        row_span = max(1, min(MAX_ROW_SPAN, row_span))
        col_span = max(1, min(GRID_COLUMNS, col_span))
        if col >= 0 and col + col_span > GRID_COLUMNS:
            col = max(0, GRID_COLUMNS - col_span)
        widgets.append(
            DashWidget(
                type=kind,
                title=str(item.get("title") or ""),
                unit=str(item.get("unit") or ""),
                minimum=minimum,
                maximum=maximum,
                bind=str(item.get("bind") or "1"),
                mode=mode,
                shape=shape,
                row=row,
                col=col,
                row_span=row_span,
                col_span=col_span,
            )
        )
    return widgets


def _as_int(raw: object, default: int) -> int:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def new_widget(kind: str, shape: str = "aircraft") -> DashWidget:
    """A palette item. One old cell is 3 columns by 8 rows; plots use two of those."""
    if kind not in WIDGET_TYPES:
        kind = "value"
    if shape not in ATTITUDE_SHAPES:
        shape = "aircraft"
    bind = "1"
    row_span, col_span = LEGACY_ROW_SCALE, LEGACY_COL_SCALE
    if kind == "multiplot":
        bind = "1,2"
        row_span, col_span = LEGACY_ROW_SCALE * 2, LEGACY_COL_SCALE * 2
    elif kind == "plot":
        row_span, col_span = LEGACY_ROW_SCALE * 2, LEGACY_COL_SCALE * 2
    elif kind == "attitude3d":
        bind = "roll,pitch,yaw"
        row_span, col_span = LEGACY_ROW_SCALE * 2, LEGACY_COL_SCALE * 2
    else:
        shape = "aircraft"
    return DashWidget(
        type=kind,
        bind=bind,
        shape=shape,
        row_span=row_span,
        col_span=col_span,
    )


def _clamp_span(item: DashWidget) -> None:
    item.row_span = max(1, min(MAX_ROW_SPAN, int(item.row_span or 1)))
    item.col_span = max(1, min(GRID_COLUMNS, int(item.col_span or 1)))


def _cells(item: DashWidget) -> set[tuple[int, int]]:
    if item.row < 0 or item.col < 0:
        return set()
    return {
        (row, col)
        for row in range(item.row, item.row + item.row_span)
        for col in range(item.col, item.col + item.col_span)
    }


def occupied_cells(
    widgets: list[DashWidget],
    *,
    skip: DashWidget | None = None,
) -> set[tuple[int, int]]:
    taken: set[tuple[int, int]] = set()
    for item in widgets:
        if item is skip:
            continue
        taken.update(_cells(item))
    return taken


def fits(
    widgets: list[DashWidget],
    spec: DashWidget,
    row: int,
    col: int,
    row_span: int,
    col_span: int,
) -> bool:
    """True when the rectangle is inside the grid and does not cover another widget."""
    if row < 0 or col < 0 or row_span < 1 or col_span < 1:
        return False
    if col + col_span > GRID_COLUMNS or row_span > MAX_ROW_SPAN:
        return False
    taken = occupied_cells(widgets, skip=spec)
    for r in range(row, row + row_span):
        for c in range(col, col + col_span):
            if (r, c) in taken:
                return False
    return True


def ensure_layout(widgets: list[DashWidget]) -> None:
    """Give every widget a free cell. Widgets that already have a free cell stay put."""
    for item in widgets:
        _clamp_span(item)
    claimed: set[tuple[int, int]] = set()
    for item in widgets:
        cells = _cells(item)
        if cells and cells.isdisjoint(claimed):
            claimed.update(cells)
            continue
        if cells:
            item.row = -1
            item.col = -1
    for item in widgets:
        if item.row >= 0 and item.col >= 0:
            item.row = max(0, item.row)
            item.col = max(0, min(GRID_COLUMNS - 1, item.col))
            if item.col + item.col_span > GRID_COLUMNS:
                item.col_span = GRID_COLUMNS - item.col
            continue
        placed = False
        for row in range(48):
            for col in range(GRID_COLUMNS):
                if fits(widgets, item, row, col, item.row_span, item.col_span):
                    item.row = row
                    item.col = col
                    placed = True
                    break
            if placed:
                break
        if not placed:
            item.row = 0
            item.col = 0
            item.row_span = 1
            item.col_span = 1


def try_move(widgets: list[DashWidget], spec: DashWidget, row: int, col: int) -> bool:
    if not fits(widgets, spec, row, col, spec.row_span, spec.col_span):
        return False
    spec.row = row
    spec.col = col
    return True


def try_resize(widgets: list[DashWidget], spec: DashWidget, row_span: int, col_span: int) -> bool:
    row_span = max(1, min(MAX_ROW_SPAN, int(row_span)))
    col_span = max(1, min(GRID_COLUMNS - max(0, spec.col), int(col_span)))
    if not fits(widgets, spec, spec.row, spec.col, row_span, col_span):
        return False
    spec.row_span = row_span
    spec.col_span = col_span
    return True
