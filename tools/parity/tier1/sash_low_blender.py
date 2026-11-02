"""Blender side of the Sash v5 low exporter (decision 300 item 7). It runs only inside Blender.

`tools.parity.tier1.sash_low_export` builds the command, on a hash-checked, read-only private copy
of the preserved `.blend`, and checks everything this script writes. Never run it on the Assets3D
original:

    blender --background --factory-startup --disable-autoexec --offline-mode -noaudio
        <run dir>/25-Faixa-Cintura-v5.blend --python-exit-code 1
        --python tools/parity/tier1/sash_low_blender.py -- <run dir>

It is the algorithm of Assets3D `Pipeline/retopology/waist-v5/export_lows.py`, reduced to the
Sash and with every choice pinned below. That script ran on the round's `bake/baked-v5.blend`,
which is lost, and read `25-Faixa-Cintura-v5-Low`. The preserved piece `.blend` holds that
object renamed `-Low-Authoring` and the game low `25-Faixa-Cintura-v5-Low-Game`, which
`deliver.py` built from its evaluated loop triangles. The piece manifest (`meshes.low`) names the
game low, so that is the object read here.

1. **Selection.** The source object, its material slots, its modifier stack (as evaluated), its
   world matrix and its UV map are each checked against a pin; any difference refuses the export
   before anything is built. The only admitted world matrix is the exact identity. The donor
   moves positions by `matrix_world` but copies corner normals untransformed and keeps the
   winding, which is wrong for a non-uniform scale or a negative determinant; here no transform
   is applied at all, and any other matrix (non-uniform, mirrored, rotated, translated) is
   refused, so object space is world space. The export is a current reference: it makes no claim
   to equal the historical low or the donor's output byte for byte.
2. **Evaluation.** The object is evaluated through the viewport depsgraph and its loop triangles,
   the pinned UV map's per-corner UVs and the corner normals are read (`triangle_table`).
3. **Copy.** A new mesh is built from those triangles, in their order and winding, with the same
   UVs per corner and the corner normals as custom split normals, both taken per loop
   (`tri.loops`), never per vertex; nothing is welded and no normal is recalculated, so Painter's
   tangent frame follows Blender's. The evaluated mesh is released in a `finally` block. The
   copy gets one new material named after the Painter texture set (`TEXTURE_SET`), as
   `export_lows.py` did; the source material is checked but not exported, so no texture path
   reaches the MTL.
4. **Export.** `wm.obj_export` with every option it has pinned (`OBJ_EXPORT_OPTIONS`); an option
   the running Blender has and the pins do not name refuses the export (`option_problems`).
5. **Report.** `export-report.json` names the Blender build, what was selected, the options and
   per-table SHA-256 digests (`table_digests`); `export-table.json` holds the table itself and
   the copy's corner normals, so the host checks every OBJ value (`table_document`). Nothing
   is ever saved: the opened file is the private copy, and the host checks its hash after
   Blender exits.

Everything above the `main` function is plain Python, so the host and the tests import it
without Blender.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPORTER = "uzpainter/parity/sash-low-export/1"
# The algorithm's source, named for provenance only: it is never run or imported.
DONOR_PATH = "Pipeline/retopology/waist-v5/export_lows.py"
DONOR_SHA256 = "6cffef1ba796b2fcadcfe08acb729edb7ad7a58308fd0d1734871c3c6c91d428"
BLENDER_VERSION = (5, 2)  # major and minor; the host pins the executable's SHA-256 too
DEPSGRAPH_MODE = "VIEWPORT"

SOURCE_BLEND_NAME = "25-Faixa-Cintura-v5.blend"  # Blender writes this base name into the MTL
SOURCE_OBJECT = "25-Faixa-Cintura-v5-Low-Game"
SOURCE_MATERIALS = ("25-Faixa-Cintura-v5",)  # the object's material slots, in order
SOURCE_MODIFIERS: tuple[tuple[str, str], ...] = ()  # (name, type) of every modifier, in order
UV_MAP = "UVMap"
TRIANGLES = 4038  # v5.json `meshes.low.triangles`

TEXTURE_SET = "25-Faixa-Cintura"
EXPORT_OBJECT = "25-Faixa-Cintura_low"
OBJ_NAME = "25-Faixa-Cintura-v5-low.obj"
MTL_NAME = "25-Faixa-Cintura-v5-low.mtl"
REPORT_NAME = "export-report.json"
TABLE_NAME = "export-table.json"

FORWARD_AXIS = "NEGATIVE_Z"
UP_AXIS = "Y"

# Every `wm.obj_export` option, by identifier, except the file-browser ones below and `filepath`.
OBJ_EXPORT_OPTIONS: dict[str, Any] = {
    "export_animation": False,
    "start_frame": 1,
    "end_frame": 1,
    "forward_axis": FORWARD_AXIS,
    "up_axis": UP_AXIS,
    "global_scale": 1.0,
    "apply_modifiers": False,
    "apply_transform": True,
    "export_eval_mode": "DAG_EVAL_VIEWPORT",
    "export_selected_objects": True,
    "export_uv": True,
    "export_normals": True,
    "export_colors": False,
    "export_materials": True,
    "export_pbr_extensions": False,
    "path_mode": "STRIP",
    "export_triangulated_mesh": False,
    "export_curves_as_nurbs": False,
    "export_object_groups": False,
    "export_material_groups": False,
    "export_vertex_groups": False,
    "export_smooth_groups": False,
    "smooth_group_bitflags": False,
    "collection": "",
}
FILE_BROWSER_OPTIONS = frozenset(
    {
        "filepath",
        "directory",
        "filename",
        "files",
        "check_existing",
        "display_type",
        "sort_method",
        "filemode",
        "hide_props_region",
        "relative_path",
        "show_multiview",
        "use_multiview",
    }
)

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Triple = tuple[int, int, int]


class ExportError(Exception):
    """The source or the running Blender does not match a pin; nothing is exported."""


@dataclass(frozen=True)
class TriangleTable:
    """The evaluated low, as `export_lows.py` reads it: positions per vertex, and per loop
    triangle its vertex indices and its loop (corner) indices; UVs and normals per loop."""

    positions: tuple[Vec3, ...]
    triangles: tuple[Triple, ...]
    loops: tuple[Triple, ...]
    uv: tuple[Vec2, ...]
    normals: tuple[Vec3, ...]


def option_problems(available: Iterable[str], pinned: Mapping[str, Any]) -> list[str]:
    """Every operator option the pins leave out, and every pin the operator does not have."""
    names = {name for name in available if name != "rna_type"}
    problems = [
        f"wm.obj_export option {name!r} is not pinned"
        for name in sorted(names - set(pinned) - FILE_BROWSER_OPTIONS)
        if not name.startswith("filter_")
    ]
    problems += [
        f"pinned option {name!r} is not an option of wm.obj_export"
        for name in sorted(set(pinned) - names)
    ]
    return problems


def is_identity(matrix: Iterable[Iterable[float]]) -> bool:
    rows = [list(row) for row in matrix]
    return len(rows) == 4 and all(
        len(row) == 4 and all(value == (1.0 if i == j else 0.0) for j, value in enumerate(row))
        for i, row in enumerate(rows)
    )


def source_problems(obj: Any) -> list[str]:
    """The source object against its pins: type, modifier stack, world matrix, material slots,
    shape keys and UV map."""
    problems: list[str] = []
    if obj.type != "MESH":
        return [f"{obj.name} is a {obj.type}, not a MESH"]
    modifiers = tuple((m.name, m.type) for m in obj.modifiers)
    if modifiers != SOURCE_MODIFIERS:
        problems.append(f"modifier stack is {list(modifiers)}, pinned {list(SOURCE_MODIFIERS)}")
    if not is_identity(obj.matrix_world):
        problems.append(
            f"world matrix is {[list(row) for row in obj.matrix_world]}; only the exact identity "
            "is admitted (no transform is applied to positions, normals or winding)"
        )
    materials = tuple(
        slot.material.name if slot.material is not None else None for slot in obj.material_slots
    )
    if materials != SOURCE_MATERIALS:
        problems.append(f"material slots are {list(materials)}, pinned {list(SOURCE_MATERIALS)}")
    if obj.data.shape_keys is not None:
        problems.append("the mesh has shape keys")
    if obj.data.uv_layers.get(UV_MAP) is None:
        problems.append(f"the mesh has no UV map {UV_MAP!r}")
    return problems


def _finite(values: Iterable[float], size: int, what: str) -> tuple[float, ...]:
    out = tuple(float(value) for value in values)
    if len(out) != size or not all(math.isfinite(value) for value in out):
        raise ExportError(f"{what} is {out}, not {size} finite numbers")
    return out


def _triple(values: Iterable[int], what: str) -> Triple:
    out = tuple(int(value) for value in values)
    if len(out) != 3:
        raise ExportError(f"{what} has {len(out)} entries, not 3")
    return out[0], out[1], out[2]


def triangle_table(mesh: Any, uv_name: str) -> TriangleTable:
    """Read an evaluated mesh (after `calc_loop_triangles`) into plain tuples, checking that every
    triangle corner's loop lies on that corner's vertex."""
    positions = tuple(_vec3(_finite(v.co, 3, f"vertex {i}")) for i, v in enumerate(mesh.vertices))
    triangles: list[Triple] = []
    loops: list[Triple] = []
    for k, tri in enumerate(mesh.loop_triangles):
        corner_vertices = _triple(tri.vertices, f"loop triangle {k}")
        corner_loops = _triple(tri.loops, f"loop triangle {k}")
        for vertex, loop in zip(corner_vertices, corner_loops, strict=True):
            if not 0 <= vertex < len(positions):
                raise ExportError(f"loop triangle {k} names vertex {vertex} out of range")
            if not 0 <= loop < len(mesh.loops) or mesh.loops[loop].vertex_index != vertex:
                raise ExportError(f"loop triangle {k}: loop {loop} is not on vertex {vertex}")
        triangles.append(corner_vertices)
        loops.append(corner_loops)
    layer = mesh.uv_layers.get(uv_name)
    if layer is None:
        raise ExportError(f"the evaluated mesh has no UV map {uv_name!r}")
    uv = tuple(_vec2(_finite(d.uv, 2, f"UV of loop {i}")) for i, d in enumerate(layer.data))
    normals = tuple(
        _vec3(_finite(c.vector, 3, f"normal of corner {i}"))
        for i, c in enumerate(mesh.corner_normals)
    )
    if len(uv) != len(mesh.loops) or len(normals) != len(mesh.loops):
        raise ExportError(
            f"{len(mesh.loops)} loops, but {len(uv)} UVs and {len(normals)} corner normals"
        )
    return TriangleTable(positions, tuple(triangles), tuple(loops), uv, normals)


def _vec2(values: tuple[float, ...]) -> Vec2:
    return values[0], values[1]


def _vec3(values: tuple[float, ...]) -> Vec3:
    return values[0], values[1], values[2]


def _digest(fmt: str, rows: Iterable[Sequence[float] | Sequence[int]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(struct.pack(fmt, *row))
    return digest.hexdigest()


def table_digests(table: TriangleTable) -> dict[str, str]:
    """SHA-256 of the table, little-endian: positions as float32 x, y, z per vertex in vertex
    order; triangulation as uint32 vertex indices per triangle; UVs (float32 u, v) and corner
    normals (float32 x, y, z) per triangle corner, in loop-triangle order. Object space, which
    the pinned identity world matrix makes world space; Blender axes, before the OBJ's."""
    corners = [loop for corner_loops in table.loops for loop in corner_loops]
    return {
        "positions": _digest("<3f", table.positions),
        "triangulation": triangulation_digest(table.triangles),
        "corner_uv": _digest("<2f", (table.uv[loop] for loop in corners)),
        "corner_normals": _digest("<3f", (table.normals[loop] for loop in corners)),
    }


def triangulation_digest(triangles: Iterable[Sequence[int]]) -> str:
    return _digest("<3I", triangles)


def bounds(points: Sequence[Sequence[float]]) -> list[list[float]]:
    """Per-axis minimum and maximum."""
    if not points:
        raise ExportError("no points to bound")
    size = len(points[0])
    low = [min(p[i] for p in points) for i in range(size)]
    high = [max(p[i] for p in points) for i in range(size)]
    return [low, high]


def table_document(table: TriangleTable, exported_normals: Sequence[Vec3]) -> dict[str, Any]:
    """`export-table.json`: the evaluated table in full, plus the copy's corner normals per
    triangle corner as Blender holds them after `normals_split_custom_set` (what the OBJ's `vn`
    are written from). The host checks every OBJ value against it."""
    return {
        "positions": [list(p) for p in table.positions],
        "triangles": [list(t) for t in table.triangles],
        "loops": [list(lo) for lo in table.loops],
        "uv": [list(uv) for uv in table.uv],
        "normals": [list(n) for n in table.normals],
        "exported_normals": [list(n) for n in exported_normals],
    }


def table_from_document(document: Mapping[str, Any]) -> tuple[TriangleTable, tuple[Vec3, ...]]:
    """The inverse of `table_document`, with every value checked for shape and finiteness."""
    positions = tuple(_vec3(_finite(p, 3, "position")) for p in document["positions"])
    triangles = tuple(_triple(t, "triangle") for t in document["triangles"])
    loops = tuple(_triple(lo, "triangle loops") for lo in document["loops"])
    uv = tuple(_vec2(_finite(p, 2, "UV")) for p in document["uv"])
    normals = tuple(_vec3(_finite(n, 3, "normal")) for n in document["normals"])
    exported = tuple(_vec3(_finite(n, 3, "exported normal")) for n in document["exported_normals"])
    if len(loops) != len(triangles) or len(exported) != 3 * len(triangles):
        raise ExportError("the table's triangles, loops and exported normals disagree in count")
    if len(uv) != len(normals) or any(not 0 <= i < len(uv) for lo in loops for i in lo):
        raise ExportError("the table's loops name UVs or normals it does not hold")
    if any(not 0 <= i < len(positions) for t in triangles for i in t):
        raise ExportError("the table's triangles name vertices it does not hold")
    return TriangleTable(positions, triangles, loops, uv, normals), exported


def to_obj_axes(point: Sequence[float]) -> Vec3:
    """Blender (Z up) to the OBJ's pinned axes (forward -Z, up Y): (x, y, z) -> (x, z, -y)."""
    return point[0], point[2], -point[1]


def report_document(
    blender: Mapping[str, Any], source: Mapping[str, Any], table: TriangleTable
) -> dict[str, Any]:
    """`export-report.json`: the Blender build, what was selected, the pinned export and the
    exported table's counts, bounds and digests."""
    return {
        "exporter": EXPORTER,
        "blender": dict(blender),
        "source": dict(source),
        "export": {
            "object": EXPORT_OBJECT,
            "material": TEXTURE_SET,
            "obj": OBJ_NAME,
            "mtl": MTL_NAME,
            "options": OBJ_EXPORT_OPTIONS,
        },
        "mesh": {
            "vertices": len(table.positions),
            "triangles": len(table.triangles),
            "corners": len(table.uv),
            "bounds": bounds(table.positions),
            "digests": table_digests(table),
        },
    }


def main(argv: Sequence[str]) -> None:
    import bpy  # type: ignore[import-not-found]

    if "--" not in argv or len(argv) != argv.index("--") + 2:
        raise ExportError("usage: blender ... --python sash_low_blender.py -- <run dir>")
    run_dir = Path(argv[argv.index("--") + 1]).resolve()
    if tuple(bpy.app.version[:2]) != BLENDER_VERSION:
        raise ExportError(f"Blender {bpy.app.version_string}, pinned {BLENDER_VERSION}")
    opened = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if opened != run_dir / SOURCE_BLEND_NAME:
        raise ExportError(f"the open file is {opened}, not {run_dir / SOURCE_BLEND_NAME}")

    view_layer = bpy.context.view_layer
    obj = bpy.data.objects.get(SOURCE_OBJECT)
    if obj is None or view_layer.objects.get(SOURCE_OBJECT) is None:
        raise ExportError(f"no object {SOURCE_OBJECT!r} in the view layer")
    problems = source_problems(obj)
    for collection, name in (
        (bpy.data.materials, TEXTURE_SET),
        (bpy.data.objects, EXPORT_OBJECT),
        (bpy.data.meshes, EXPORT_OBJECT),
    ):
        if collection.get(name) is not None:
            problems.append(f"the file already holds a datablock named {name!r}")
    available = [p.identifier for p in bpy.ops.wm.obj_export.get_rna_type().properties]
    problems += option_problems(available, OBJ_EXPORT_OPTIONS)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if depsgraph.mode != DEPSGRAPH_MODE:
        problems.append(f"depsgraph mode is {depsgraph.mode}, pinned {DEPSGRAPH_MODE}")
    if problems:
        raise ExportError("; ".join(problems))

    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        table = triangle_table(mesh, UV_MAP)
    finally:
        evaluated.to_mesh_clear()
    if len(table.triangles) != TRIANGLES:
        raise ExportError(f"{len(table.triangles)} loop triangles, pinned {TRIANGLES}")

    copy = bpy.data.meshes.new(EXPORT_OBJECT)
    copy.from_pydata(list(table.positions), [], list(table.triangles))
    copy.update()
    if [tuple(p.vertices) for p in copy.polygons] != list(table.triangles):
        raise ExportError("the copy's faces are not the loop triangles in order")
    layer = copy.uv_layers.new(name=UV_MAP)
    for polygon, corner_loops in zip(copy.polygons, table.loops, strict=True):
        for target, loop in zip(polygon.loop_indices, corner_loops, strict=True):
            layer.data[target].uv = table.uv[loop]
    copy.polygons.foreach_set("use_smooth", [True] * len(copy.polygons))
    copy.normals_split_custom_set([table.normals[loop] for lt in table.loops for loop in lt])
    exported_normals = [
        _vec3(tuple(copy.corner_normals[target].vector))
        for polygon in copy.polygons
        for target in polygon.loop_indices
    ]
    material = bpy.data.materials.new(TEXTURE_SET)
    copy.materials.append(material)
    exported = bpy.data.objects.new(EXPORT_OBJECT, copy)
    bpy.context.scene.collection.objects.link(exported)
    if (exported.name, material.name) != (EXPORT_OBJECT, TEXTURE_SET):
        raise ExportError(f"the copy was named {exported.name!r} / {material.name!r}")
    for other in view_layer.objects:
        other.select_set(False)
    exported.select_set(True)
    view_layer.objects.active = exported

    bpy.ops.wm.obj_export(filepath=str(run_dir / OBJ_NAME), **OBJ_EXPORT_OPTIONS)

    active_uv = obj.data.uv_layers.active
    blender = {
        "version": list(bpy.app.version),
        "version_string": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode("ascii", "replace"),
        "build_branch": bpy.app.build_branch.decode("ascii", "replace"),
        "file_version": list(bpy.data.version),
    }
    source = {
        "blend": str(opened),
        "object": obj.name,
        "materials": [s.material.name for s in obj.material_slots],
        "modifiers": [[m.name, m.type] for m in obj.modifiers],
        "uv_map": UV_MAP,
        "uv_map_active": active_uv is not None and active_uv.name == UV_MAP,
        "depsgraph_mode": depsgraph.mode,
    }
    for name, document in (
        (TABLE_NAME, table_document(table, exported_normals)),
        (REPORT_NAME, report_document(blender, source, table)),
    ):
        text = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        (run_dir / name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
