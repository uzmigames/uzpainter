"""Expected silhouette of a fixture seen from the recorded camera (07 §2.2 step 5).

Painter documents its camera only as `position`, `rotation` (Euler angles in degrees),
`field_of_view` (degrees) and `projection_type` in scene space (python-doc `display.Camera`).
The projection below states the remaining conventions as hypotheses that the probe session
confirms or rejects (`iray_probe.py`, step `camera`):

- scene space is right-handed with +Y up; the camera looks along its local -Z with local +Y up;
- `rotation` is applied to the camera as elemental rotations about the scene axes, in
  `order` (the axes in the order they are applied; `ZXY` = roll, then pitch, then yaw);
- `field_of_view` is the full angle across the rendered image, which must be square (the
  axis the angle refers to is not documented, and a square image makes it irrelevant);
- only `Perspective` projection is qualified.

The mask is 8-bit grey: 0 background, 255 object, 128 the don't-care band of `band` pixels on
both sides of the projected outline (anti-aliasing and Iray's pixel filter).
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.recorder.session import RecorderError

Vec3 = tuple[float, float, float]
Matrix = tuple[Vec3, Vec3, Vec3]

ROTATION_ORDERS = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")
DEFAULT_ORDER = "ZXY"
BACKGROUND, BAND, OBJECT = 0, 128, 255


@dataclass(frozen=True)
class Mesh:
    vertices: tuple[Vec3, ...]
    triangles: tuple[tuple[int, int, int], ...]

    def bounds(self) -> tuple[Vec3, Vec3]:
        xs, ys, zs = zip(*self.vertices, strict=True)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def load_obj(path: Path) -> Mesh:
    """Positions and faces of a Wavefront OBJ (faces fan-triangulated)."""
    vertices: list[Vec3] = []
    triangles: list[tuple[int, int, int]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif parts[0] == "f":
            index = []
            for ref in parts[1:]:
                i = int(ref.split("/", 1)[0])
                index.append(i - 1 if i > 0 else len(vertices) + i)
            triangles += [(index[0], index[k], index[k + 1]) for k in range(1, len(index) - 1)]
    if not vertices or not triangles:
        raise RecorderError(f"{path.name}: no geometry")
    return Mesh(tuple(vertices), tuple(triangles))


@dataclass(frozen=True)
class Camera:
    position: Vec3
    rotation: Vec3
    field_of_view: float
    projection_type: str

    @staticmethod
    def from_render_state(state: dict[str, Any]) -> Camera:
        """The camera the recorder read back (`render_state`, keys `camera.*`)."""
        px, py, pz = (float(v) for v in state["camera.position"])
        rx, ry, rz = (float(v) for v in state["camera.rotation"])
        return Camera(
            (px, py, pz),
            (rx, ry, rz),
            float(state["camera.field_of_view"]),
            str(state["camera.projection_type"]),
        )


def axis_matrix(axis: str, degrees: float) -> Matrix:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    if axis == "X":
        return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))
    if axis == "Y":
        return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def multiply(a: Matrix, b: Matrix) -> Matrix:
    rows = tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )
    return rows  # type: ignore[return-value]


def apply(m: Matrix, v: Vec3) -> Vec3:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def rotation_matrix(rotation: Vec3, order: str = DEFAULT_ORDER) -> Matrix:
    """Camera-to-scene rotation: elemental rotations applied in `order`."""
    if order not in ROTATION_ORDERS:
        raise RecorderError(f"rotation order {order!r} is not one of {ROTATION_ORDERS}")
    angles = dict(zip("XYZ", rotation, strict=True))
    result: Matrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    for axis in order:
        result = multiply(axis_matrix(axis, angles[axis]), result)
    return result


def orbit_position(rotation: Vec3, distance: float, order: str = DEFAULT_ORDER) -> Vec3:
    """Where a camera with `rotation` must sit to look at the scene origin from `distance`."""
    return apply(rotation_matrix(rotation, order), (0.0, 0.0, distance))


def project(
    points: tuple[Vec3, ...], camera: Camera, width: int, height: int, order: str = DEFAULT_ORDER
) -> list[tuple[float, float]]:
    """Continuous pixel coordinates (origin at the top-left image corner) of scene points."""
    if camera.projection_type != "Perspective":
        raise RecorderError("only Perspective cameras are qualified for silhouette verification")
    if width != height:
        raise RecorderError(
            "the field-of-view axis is not documented: silhouette verification needs a square "
            f"render, got {width}x{height}"
        )
    rotation = rotation_matrix(camera.rotation, order)
    tangent = math.tan(math.radians(camera.field_of_view) / 2.0)
    projected: list[tuple[float, float]] = []
    for point in points:
        offset = (
            point[0] - camera.position[0],
            point[1] - camera.position[1],
            point[2] - camera.position[2],
        )
        # Scene to camera: the transpose of the camera-to-scene rotation.
        local = (
            rotation[0][0] * offset[0] + rotation[1][0] * offset[1] + rotation[2][0] * offset[2],
            rotation[0][1] * offset[0] + rotation[1][1] * offset[1] + rotation[2][1] * offset[2],
            rotation[0][2] * offset[0] + rotation[1][2] * offset[1] + rotation[2][2] * offset[2],
        )
        depth = -local[2]
        if depth <= 1e-6:
            raise RecorderError("the fixture is not entirely in front of the camera")
        x_ndc = local[0] / (depth * tangent)
        y_ndc = local[1] / (depth * tangent)
        projected.append(((x_ndc + 1.0) * width / 2.0, (1.0 - y_ndc) * height / 2.0))
    return projected


def coverage_rows(
    mesh: Mesh, camera: Camera, width: int, height: int, order: str = DEFAULT_ORDER
) -> list[int]:
    """Per image row, a bitmask of the pixels whose centre the projected mesh covers."""
    points = project(mesh.vertices, camera, width, height, order)
    rows = [0] * height
    full = (1 << width) - 1
    for a, b, c in mesh.triangles:
        tri = (points[a], points[b], points[c])
        y_low = max(0, math.ceil(min(p[1] for p in tri) - 0.5))
        y_high = min(height - 1, math.floor(max(p[1] for p in tri) - 0.5))
        for y in range(y_low, y_high + 1):
            centre = y + 0.5
            xs: list[float] = []
            for (x0, y0), (x1, y1) in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                if (y0 <= centre < y1) or (y1 <= centre < y0):
                    xs.append(x0 + (centre - y0) * (x1 - x0) / (y1 - y0))
            if len(xs) < 2:
                continue
            first = max(0, math.ceil(min(xs) - 0.5))
            last = min(width - 1, math.floor(max(xs) - 0.5))
            if first <= last:
                rows[y] |= ((1 << (last - first + 1)) - 1) << first
    return [row & full for row in rows]


def silhouette_mask(
    mesh: Mesh,
    camera: Camera,
    width: int,
    height: int,
    order: str = DEFAULT_ORDER,
    band: int = 2,
) -> list[bytes]:
    """Rows of the expected-silhouette mask (0 background, 255 object, 128 don't care)."""
    rows = coverage_rows(mesh, camera, width, height, order)
    full = (1 << width) - 1
    edges = []
    for y, row in enumerate(rows):
        above = rows[y - 1] if y > 0 else row
        below = rows[y + 1] if y + 1 < height else row
        horizontal = (row ^ (row << 1)) | (row ^ (row >> 1))
        edges.append((horizontal | (row ^ above) | (row ^ below)) & full)
    for _ in range(band):
        grown = []
        for y, row in enumerate(edges):
            wide = row | (row << 1) | (row >> 1)
            above = edges[y - 1] if y > 0 else 0
            below = edges[y + 1] if y + 1 < height else 0
            grown.append((wide | above | below) & full)
        edges = grown
    mask: list[bytes] = []
    for row, edge in zip(rows, edges, strict=True):
        line = bytearray(width)
        for x in range(width):
            bit = 1 << x
            line[x] = BAND if edge & bit else OBJECT if row & bit else BACKGROUND
        mask.append(bytes(line))
    return mask


def write_grey_png(path: Path, rows: list[bytes]) -> None:
    """Write 8-bit grey rows as a PNG (filter 0)."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def check_scene_bounds(mesh: Mesh, bounding_box: dict[str, Any], tolerance: float = 1e-3) -> None:
    """Refuse when Painter's scene bounding box is not the mesh file's (moved or rescaled)."""
    low, high = mesh.bounds()
    centre = [(lo + hi) / 2.0 for lo, hi in zip(low, high, strict=True)]
    size = [hi - lo for lo, hi in zip(low, high, strict=True)]
    scale = max(size)
    for name, expected, actual in (
        ("center", centre, bounding_box["center"]),
        ("dimensions", size, bounding_box["dimensions"]),
    ):
        if any(
            abs(float(a) - e) > tolerance * scale for a, e in zip(actual, expected, strict=True)
        ):
            raise RecorderError(
                f"scene bounding box {name} {list(actual)} differs from the mesh file's "
                f"{expected}: Painter moved or rescaled the fixture; the silhouette cannot be "
                "projected"
            )
