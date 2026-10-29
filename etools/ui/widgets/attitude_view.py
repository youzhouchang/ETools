"""A small Qt3D viewport that shows one rigid body's orientation.

The scene is a light aircraft in the aerospace body frame used by
:mod:`etools.core.attitude`: nose along +X, right wing along +Y, belly along
+Z. A horizon pad stays fixed in the world, so roll, pitch and yaw read off
the airframe instead of off a bare box.

Qt3D's aspect engine needs a real GPU/OpenGL context. On a machine without
working OpenGL drivers the import or the window creation can fail; callers
must still get a working widget, just without the 3D render, so the rest of
the dashboard keeps working. :func:`build_attitude_view` is the one entry
point other modules should use; it always returns something paintable.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtGui import QColor, QVector3D
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from etools.core.attitude import Quat
from etools.i18n import tr
from etools.logger import get_logger

log = get_logger("ui.attitude3d")


class AttitudeViewProtocol(Protocol):
    """Shared surface between the real Qt3D view and the text fallback."""

    def set_quaternion(self, quat: Quat) -> None: ...  # noqa: D102


class _FallbackAttitudeView(QWidget):
    """No OpenGL available: show the numeric orientation as text only."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.notice = QLabel(tr("dash.attitude_no_gl"))
        self.notice.setWordWrap(True)
        self.notice.setObjectName("hint")
        self.readout = QLabel("—")
        lay.addWidget(self.notice)
        lay.addWidget(self.readout, 1)
        lay.addStretch(1)

    def set_quaternion(self, quat: Quat) -> None:
        from etools.core.attitude import quat_to_euler

        roll, pitch, yaw = quat_to_euler(*quat)
        self.readout.setText(f"roll {roll:+.1f}  pitch {pitch:+.1f}  yaw {yaw:+.1f}")


def _build_qt3d_view(parent: QWidget | None, shape: str) -> QWidget:
    """Raises on any failure; the caller decides when to fall back."""
    from PySide6.Qt3DCore import Qt3DCore as Core
    from PySide6.Qt3DExtras import Qt3DExtras as Extras
    from PySide6.Qt3DRender import Qt3DRender as Render

    # Matte finishes: a tight specular lobe is what made the old cube a white blob.
    body = "#E7EDF4"
    belly = "#9AA6B5"
    wing = "#4C7DFF"
    nose = "#FF5A36"
    canopy = "#1B2433"
    metal = "#C5CED8"
    mark = "#FFB020"
    pad = "#1A2230"
    ring = "#5A6D88"
    axis = "#31445F"

    window = Extras.Qt3DWindow()
    window.defaultFrameGraph().setClearColor(QColor(16, 20, 28))
    root = Core.QEntity()
    kept: list[object] = [window, root]

    def add(parent_entity, mesh, color, x=0.0, y=0.0, z=0.0, rx=0.0, ry=0.0, rz=0.0):
        entity = Core.QEntity(parent_entity)
        mesh.setParent(entity)
        diffuse = QColor(color)
        material = Extras.QPhongMaterial(entity)
        material.setDiffuse(diffuse)
        material.setAmbient(diffuse.darker(250))
        material.setSpecular(QColor(46, 54, 66))
        material.setShininess(16.0)
        transform = Core.QTransform(entity)
        transform.setTranslation(QVector3D(x, y, z))
        transform.setRotationX(rx)
        transform.setRotationY(ry)
        transform.setRotationZ(rz)
        entity.addComponent(mesh)
        entity.addComponent(material)
        entity.addComponent(transform)
        kept.extend((entity, mesh, material, transform))
        return entity

    def cylinder(radius: float, length: float, slices: int = 36):
        mesh = Extras.QCylinderMesh()
        mesh.setRadius(radius)
        mesh.setLength(length)
        mesh.setSlices(slices)
        return mesh

    def cone(radius: float, length: float):
        mesh = Extras.QConeMesh()
        mesh.setBottomRadius(radius)
        mesh.setTopRadius(0.0)
        mesh.setLength(length)
        mesh.setSlices(36)
        return mesh

    def box(x: float, y: float, z: float):
        mesh = Extras.QCuboidMesh()
        mesh.setXExtent(x)
        mesh.setYExtent(y)
        mesh.setZExtent(z)
        return mesh

    def sphere(radius: float):
        mesh = Extras.QSphereMesh()
        mesh.setRadius(radius)
        mesh.setRings(24)
        mesh.setSlices(32)
        return mesh

    def light(color: str, intensity: float, x: float, y: float, z: float) -> None:
        entity = Core.QEntity(root)
        point = Render.QPointLight(entity)
        point.setColor(QColor(color))
        point.setIntensity(intensity)
        transform = Core.QTransform(entity)
        transform.setTranslation(QVector3D(x, y, z))
        entity.addComponent(point)
        entity.addComponent(transform)
        kept.extend((entity, point, transform))

    # Key from the front-left and above (-Z is up), fill from the other side,
    # and a dim bounce from below so the belly is not a black hole. Intensities
    # stay low so the pad does not bloom into a white disc.
    light("#FFFFFF", 0.55, 5.0, -6.0, -7.0)
    light("#D5DDEA", 0.42, -6.0, 4.5, -4.0)
    light("#9AA8BE", 0.20, 0.0, 0.0, 6.0)

    rig_entity = Core.QEntity(root)
    rig_transform = Core.QTransform(rig_entity)
    rig_entity.addComponent(rig_transform)
    kept.extend((rig_entity, rig_transform))

    def aircraft() -> None:
        # Primitives are built along +Y; rz=-90 turns that into the nose axis (+X).
        add(rig_entity, cylinder(0.155, 1.22), body, rz=-90)
        add(rig_entity, cylinder(0.125, 1.02), belly, x=-0.02, z=0.05, rz=-90)
        add(rig_entity, cylinder(0.175, 0.26), body, x=0.62, rz=-90)
        add(rig_entity, cone(0.175, 0.38), nose, x=0.90, rz=-90)
        add(rig_entity, sphere(0.12), canopy, x=0.16, z=-0.15)
        add(rig_entity, box(0.40, 2.10, 0.04), wing, x=0.06, z=-0.14)
        add(rig_entity, box(0.40, 0.09, 0.05), mark, x=0.06, y=1.07, z=-0.14)
        add(rig_entity, box(0.24, 0.78, 0.032), wing, x=-0.64, z=-0.02)
        add(rig_entity, box(0.30, 0.036, 0.40), wing, x=-0.58, z=-0.30)
        add(rig_entity, box(0.09, 0.042, 0.07), mark, x=-0.68, z=-0.48)
        # Two blades in the YZ plane, so the propeller faces along the nose.
        add(rig_entity, box(0.02, 0.64, 0.07), metal, x=1.14)
        add(rig_entity, box(0.02, 0.07, 0.64), metal, x=1.14)
        add(rig_entity, sphere(0.05), metal, x=1.14)

    def quad() -> None:
        # Arms along +X and +Y. Front motors (+X) are amber so heading is obvious.
        add(rig_entity, box(0.46, 0.46, 0.14), body, z=-0.04)
        add(rig_entity, box(0.14, 0.08, 0.08), mark, x=0.26, z=-0.05)
        add(rig_entity, cylinder(0.035, 1.35, slices=12), metal, z=-0.02, rz=-90)
        add(rig_entity, cylinder(0.035, 1.35, slices=12), metal, z=-0.02)
        motors = (
            (0.62, 0.62, True),
            (0.62, -0.62, True),
            (-0.62, 0.62, False),
            (-0.62, -0.62, False),
        )
        for mx, my, front in motors:
            shell = mark if front else metal
            disc = wing if front else "#8E99A8"
            add(rig_entity, cylinder(0.09, 0.07, slices=20), shell, x=mx, y=my, z=-0.08, rx=90)
            add(rig_entity, cylinder(0.16, 0.015, slices=24), disc, x=mx, y=my, z=-0.13, rx=90)

    def cube() -> None:
        # Body axes in the same NED frame as the aircraft: X forward, Y right, Z down.
        add(rig_entity, box(1.15, 1.15, 1.15), body)
        add(rig_entity, cylinder(0.04, 1.05, slices=16), "#FF4D4D", x=0.85, rz=-90)
        add(rig_entity, cone(0.09, 0.28), "#FF4D4D", x=1.48, rz=-90)
        add(rig_entity, cylinder(0.04, 1.05, slices=16), "#3DDC97", y=0.85)
        add(rig_entity, cone(0.09, 0.28), "#3DDC97", y=1.48)
        add(rig_entity, cylinder(0.04, 1.05, slices=16), "#4C7DFF", z=0.85, rx=90)
        add(rig_entity, cone(0.09, 0.28), "#4C7DFF", z=1.48, rx=90)

    def ground() -> None:
        # The pad stays fixed while the rig rotates. Its amber arrow is heading zero.
        add(root, cylinder(1.42, 0.018, slices=72), ring, z=0.82, rx=90)
        add(root, cylinder(1.22, 0.02, slices=72), pad, z=0.79, rx=90)
        add(root, box(0.92, 0.012, 0.008), axis, z=0.768)
        add(root, box(0.012, 0.92, 0.008), axis, z=0.768)
        add(root, box(0.36, 0.036, 0.01), mark, x=0.92, z=0.762)
        add(root, cone(0.05, 0.14), mark, x=1.14, z=0.750, rz=-90)

    if shape == "cube":
        cube()
    elif shape == "quad":
        quad()
        ground()
    else:
        aircraft()
        ground()

    camera = window.camera()
    # Far enough that the whole airframe fits the narrow dashboard card.
    # The lens aspect is corrected to the real window size below.
    camera.lens().setPerspectiveProjection(32.0, 0.6, 0.05, 100.0)
    camera.setPosition(QVector3D(5.8, -4.6, -3.5))
    camera.setViewCenter(QVector3D(0.0, 0.0, 0.12))
    camera.setUpVector(QVector3D(0.0, 0.0, -1.0))

    def sync_aspect(*_args: object) -> None:
        height = window.height()
        if height <= 0:
            return
        camera.lens().setAspectRatio(max(window.width(), 1) / float(height))

    window.widthChanged.connect(sync_aspect)
    window.heightChanged.connect(sync_aspect)

    window.setRootEntity(root)
    container = QWidget.createWindowContainer(window, parent)
    container.setMinimumHeight(80)
    # addComponent() does not reparent. A mesh left parentless is destroyed
    # when this function's locals are collected, and the entity renders
    # nothing. `kept` holds every wrapper for as long as the container lives.
    container._qt3d_refs = kept
    container._sync_aspect = sync_aspect

    def set_quaternion(quat: Quat) -> None:
        from PySide6.QtGui import QQuaternion

        rig_transform.setRotation(QQuaternion(quat[0], quat[1], quat[2], quat[3]))

    container.set_quaternion = set_quaternion  # type: ignore[attr-defined]
    return container


def _with_legend(inner: QWidget, text: str) -> QWidget:
    shell = QWidget(inner.parentWidget())
    inner.setParent(shell)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lay.addWidget(inner, 1)
    label = QLabel(text, shell)
    label.setObjectName("hint")
    lay.addWidget(label)
    shell.setMinimumHeight(max(96, inner.minimumHeight()))

    def set_quaternion(quat: Quat) -> None:
        inner.set_quaternion(quat)

    shell.set_quaternion = set_quaternion  # type: ignore[attr-defined]
    return shell


def build_attitude_view(parent: QWidget | None = None, shape: str = "aircraft") -> QWidget:
    """A Qt3D viewport, a horizon instrument, or a text fallback if Qt3D cannot start."""
    if shape == "horizon":
        from etools.ui.widgets.horizon_view import HorizonView

        return HorizonView(parent)
    model = shape if shape in {"aircraft", "quad", "cube"} else "aircraft"
    try:
        view = _build_qt3d_view(parent, model)
    except Exception as exc:  # noqa: BLE001 - Qt3D failures vary by platform/driver
        log.warning("Qt3D unavailable, using text fallback: %s", exc)
        return _FallbackAttitudeView(parent)
    if model == "cube":
        return _with_legend(view, tr("dash.axis_legend"))
    return view


__all__ = ["build_attitude_view", "AttitudeViewProtocol"]
