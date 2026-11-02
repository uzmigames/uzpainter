"""Blender side of the Tunic v10 current-round inspection (decision 300 section 7). Blender only.

`tools.parity.tier1.tunic_intermediates` builds the command, on a hash-checked, read-only private
copy of the preserved `.blend`, and checks what this script writes. Never run it on the Assets3D
original:

    blender --background --factory-startup --disable-autoexec --offline-mode -noaudio
        <run dir>/18-Tunica-v10.blend --python-exit-code 1
        --python tools/parity/tier1/tunic_intermediates_blender.py -- inspect <run dir>

**inspect** reads, and changes nothing that is saved. It looks up only these names, exactly:
- the low `LOW_OBJECT` and the high `HIGH_OBJECT`. For each: its parent, visibility, matrices
  and deltas, constraints, modifiers (with their RNA properties), drivers, shape keys, material
  slots and the polygons' material indices, UV layers (names, active, active render), attributes
  and vertex groups, and the counts (loop triangles included) of the authored mesh and of the
  evaluated one. The evaluated
  mesh is read as the donor's `extract` reads it (`DONOR_PATH`): `new_from_object` of the object
  evaluated in the viewport depsgraph, with every data layer kept, and no visibility changed;
- on both meshes, the attribute `LINING_ATTRIBUTE`: its domain, type and size, and for a scalar
  one its finite range and the 0.5 crossings that the donor's `masks` step uses
  (`lining_summary`);
- the packed image `NORMAL_IMAGE`: the SHA-256, SHA-1 and size of its packed bytes, the PNG
  header of those bytes, its colour-space setting and the precision Blender loads it at
  (`image_report`). Its pixels are not read;
- the candidate names `CANDIDATE_NAMES` (the report's `LiningMask` and its source-recovery note's
  `Source_Lining`), exactly, in a fixed list of data-block collections (`LOOKUP_COLLECTIONS`) and
  in the two objects' attributes, vertex groups, UV layers, shape keys and material slots.

Nothing is normalised, fitted, exported or baked, and nothing is saved: the opened file is the
private copy, and the host checks its hash after Blender exits. Everything above `main` is plain
Python and numpy, so the host and the tests import it without Blender.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

INSPECTOR = "uzpainter/parity/tunic-intermediates-inspect/1"
# The donor whose reading the inspection mirrors, named for provenance only: never run or
# imported. The pin is the raw LF git blob at Assets3D f49fe67c (the contract's Scripts table).
DONOR_PATH = "Pipeline/painting/garment_blender_io.py"
DONOR_BLOB_SHA256 = "805f9ccc5430e47ac49c4b50651e271b2e6da68f8455fa231306f3462b0c8a4d"
BLENDER_VERSION = (5, 2)
# Blender runs this file by path, without the repository on `sys.path`: it imports nothing from
# `tools`, and the host checks that these names match its own pins.
SOURCE_BLEND_NAME = "18-Tunica-v10.blend"
LOW_OBJECT = "18-Tunica-Low"
HIGH_OBJECT = "18-Tunica-High-OriginalFit"
OBJECTS = (LOW_OBJECT, HIGH_OBJECT)
LINING_ATTRIBUTE = "LiningMask"
LINING_THRESHOLD = 0.5  # garment_material_masks.py: `lining - 0.5` changes sign across the rim
NORMAL_IMAGE = "Source_v6_HighNormal"
CANDIDATE_NAMES = (LINING_ATTRIBUTE, "Source_Lining")
LOOKUP_COLLECTIONS = ("images", "objects", "meshes", "materials", "textures", "node_groups")
REPORT_NAME = "inspect-report.json"
# Attribute types whose values are read, with the buffer `foreach_get("value")` fills.
SCALAR_TYPES = {"FLOAT": np.float32, "INT": np.int32, "BOOLEAN": np.bool_}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class InspectError(Exception):
    """The source or the running Blender does not match a pin; nothing is written as valid."""


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8")


def plain(value: Any) -> Any:
    """A JSON-safe copy of an RNA value: enums are strings, sets sorted lists, sequences (RNA
    arrays, vectors, matrices) lists, data-blocks their names."""
    if isinstance(value, set | frozenset):
        return sorted(value)
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    try:
        return [plain(v) for v in value]
    except TypeError:
        return str(value)


def matrix_json(matrix: Any) -> list[list[float]]:
    return [[float(v) for v in row] for row in matrix]


def is_identity(matrix: Sequence[Sequence[float]]) -> bool:
    return all(
        value == (1.0 if i == j else 0.0)
        for i, row in enumerate(matrix)
        for j, value in enumerate(row)
    )


def polygon_triangles(loop_totals: Any) -> int:
    """The triangles a polygon soup fans into: n - 2 per n-gon."""
    totals = np.asarray(loop_totals, np.int64)
    return int((totals - 2).sum()) if totals.size else 0


def triangle_edges(triangle_vertices: Any) -> Any:
    """The undirected edges of loop-triangle vertex triples, each once, as the donor's graph
    (`garment_material_masks.Graph`) builds them, triangulation diagonals included."""
    tris = np.asarray(triangle_vertices, np.int64).reshape(-1, 3)
    pairs = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    return np.unique(np.sort(pairs, axis=1), axis=0)


def crossings(values: Any, edges: Any) -> int:
    """Edges whose two finite values lie strictly on either side of `LINING_THRESHOLD`: the
    donor's `ls[u] * ls[v] < 0` (an endpoint exactly at the threshold does not cross)."""
    pairs = np.asarray(edges, np.int64).reshape(-1, 2)
    if not pairs.size:
        return 0
    shifted = np.asarray(values, np.float64) - LINING_THRESHOLD
    a, b = shifted[pairs[:, 0]], shifted[pairs[:, 1]]
    return int(np.count_nonzero(np.isfinite(a) & np.isfinite(b) & (a * b < 0)))


def lining_summary(values: Any, edges: Any = None, triangles: Any = None) -> dict[str, Any]:
    """Counts and the finite range of a scalar attribute, and its threshold crossings along the
    mesh edges and the loop-triangle graph when those are given (POINT domain only)."""
    data = np.asarray(values, np.float64).ravel()
    finite = data[np.isfinite(data)]
    summary: dict[str, Any] = {
        "count": int(data.size),
        "finite": int(finite.size),
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "distinct": int(np.unique(finite).size),
        "binary": bool(finite.size == data.size and np.isin(finite, (0.0, 1.0)).all()),
        "below": int(np.count_nonzero(finite < LINING_THRESHOLD)),
        "at": int(np.count_nonzero(finite == LINING_THRESHOLD)),
        "above": int(np.count_nonzero(finite > LINING_THRESHOLD)),
        "crossings_mesh_edges": None if edges is None else crossings(data, edges),
        "crossings_triangle_edges": None,
    }
    if triangles is not None:
        summary["crossings_triangle_edges"] = crossings(data, triangle_edges(triangles))
    return summary


def png_header(data: bytes) -> dict[str, Any] | None:
    """The IHDR of PNG bytes (width, height, bit depth, colour type, interlace), or None."""
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", data[16:29])
    return {
        "width": width,
        "height": height,
        "bit_depth": depth,
        "colour_type": colour,
        "interlace": interlace,
    }


def packed_identity(data: bytes) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "size_bytes": len(data),
        "png": png_header(data),
    }


def rna_properties(struct_: Any, skip: Iterable[str] = ()) -> dict[str, Any]:
    """Every RNA property of a struct: plain values, pointers by name, collections by size."""
    skipped = {"rna_type", *skip}
    found: dict[str, Any] = {}
    for prop in struct_.bl_rna.properties:
        name = prop.identifier
        if name in skipped:
            continue
        try:
            value = getattr(struct_, name)
        except (AttributeError, RuntimeError) as error:
            found[name] = f"<unreadable: {error}>"
            continue
        if prop.type == "COLLECTION":
            found[name] = len(value)
        elif prop.type == "POINTER":
            found[name] = None if value is None else getattr(value, "name", type(value).__name__)
        else:
            found[name] = plain(value)
    return found


def image_report(image: Any) -> dict[str, Any]:
    """An image's packed bytes by identity, and the settings Blender decodes it with."""
    packed = image.packed_file
    report: dict[str, Any] = {
        "name": image.name,
        "type": image.type,
        "source": image.source,
        "filepath": image.filepath,
        "filepath_raw": image.filepath_raw,
        "packed_files": len(image.packed_files),
        "packed": None if packed is None else packed_identity(bytes(packed.data)),
        "colorspace": image.colorspace_settings.name,
        "colorspace_is_data": bool(image.colorspace_settings.is_data),
        "alpha_mode": image.alpha_mode,
        "file_format": image.file_format,
        "is_dirty_before_load": bool(image.is_dirty),
    }
    # Reading the size loads the buffer (never written back): the precision Blender gives it.
    report.update(
        {
            "size": list(image.size),
            "channels": int(image.channels),
            "depth": int(image.depth),
            "is_float": bool(image.is_float),
            "use_half_precision": bool(image.use_half_precision),
            "has_data": bool(image.has_data),
            "is_dirty_after_load": bool(image.is_dirty),
        }
    )
    return report


def _blender(bpy: Any) -> dict[str, Any]:
    return {
        "version": list(bpy.app.version),
        "version_string": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode("ascii", "replace"),
        "build_branch": bpy.app.build_branch.decode("ascii", "replace"),
        "file_version": list(bpy.data.version),
        "autoexec_fail": bool(bpy.app.autoexec_fail),
        "numpy": np.__version__,
    }


def _animation(id_block: Any) -> dict[str, Any] | None:
    if id_block is None:
        return None
    data = id_block.animation_data
    if data is None:
        return {"animation_data": False}
    return {
        "animation_data": True,
        "action": None if data.action is None else data.action.name,
        "drivers": sorted(d.data_path for d in data.drivers),
    }


def _shape_keys(obj: Any) -> dict[str, Any] | None:
    key = obj.data.shape_keys
    if key is None:
        return None
    return {
        "name": key.name,
        "use_relative": bool(key.use_relative),
        "reference_key": None if key.reference_key is None else key.reference_key.name,
        "eval_time": float(key.eval_time),
        "active_shape_key_index": int(obj.active_shape_key_index),
        "show_only_shape_key": bool(obj.show_only_shape_key),
        "use_shape_key_edit_mode": bool(obj.use_shape_key_edit_mode),
        "animation": _animation(key),
        "blocks": [
            {
                "name": block.name,
                "value": float(block.value),
                "mute": bool(block.mute),
                "relative_key": None if block.relative_key is None else block.relative_key.name,
                "vertex_group": block.vertex_group,
                "slider_min": float(block.slider_min),
                "slider_max": float(block.slider_max),
                "interpolation": block.interpolation,
            }
            for block in key.key_blocks
        ],
    }


def _ints(collection: Any, name: str, size: int, width: int = 1) -> Any:
    values = np.empty(size * width, np.int32)
    collection.foreach_get(name, values)
    return values.reshape(-1, width) if width > 1 else values


def _uv(mesh: Any) -> dict[str, Any]:
    layers = list(mesh.uv_layers)
    return {
        "names": [layer.name for layer in layers],
        "active": None if mesh.uv_layers.active is None else mesh.uv_layers.active.name,
        "active_render": [layer.name for layer in layers if layer.active_render],
    }


def _attribute(mesh: Any, name: str, edges: Any, triangles: Any) -> dict[str, Any] | None:
    attribute = mesh.attributes.get(name)
    if attribute is None:
        return None
    found: dict[str, Any] = {
        "name": attribute.name,
        "domain": attribute.domain,
        "data_type": attribute.data_type,
        "size": len(attribute.data),
        "values": None,
    }
    buffer = SCALAR_TYPES.get(attribute.data_type)
    if buffer is None:
        found["unread"] = f"{attribute.data_type} is not a scalar type"
        return found
    values: Any = np.empty(len(attribute.data), buffer)
    attribute.data.foreach_get("value", values)
    point = attribute.domain == "POINT"
    found["values"] = lining_summary(
        values, edges if point else None, triangles if point and triangles is not None else None
    )
    return found


def _mesh(mesh: Any, triangulated: bool) -> dict[str, Any]:
    """Counts, UV layers, attributes, material indices and the lining attribute of one mesh."""
    nv, ne, nf, nl = len(mesh.vertices), len(mesh.edges), len(mesh.polygons), len(mesh.loops)
    totals = _ints(mesh.polygons, "loop_total", nf)
    edges = _ints(mesh.edges, "vertices", ne, 2)
    indices = _ints(mesh.polygons, "material_index", nf)
    counts: dict[str, Any] = {
        "vertices": nv,
        "edges": ne,
        "polygons": nf,
        "loops": nl,
        "polygon_triangles": polygon_triangles(totals),
    }
    triangles = None
    if triangulated:
        mesh.calc_loop_triangles()
        counts["loop_triangles"] = len(mesh.loop_triangles)
        triangles = _ints(mesh.loop_triangles, "vertices", len(mesh.loop_triangles), 3)
    used, used_counts = np.unique(indices, return_counts=True)
    return {
        "name": mesh.name,
        "counts": counts,
        "uv": _uv(mesh),
        "attributes": sorted(
            [a.name, a.domain, a.data_type] for a in mesh.attributes if not a.name.startswith(".")
        ),
        "material_indices": {str(int(i)): int(c) for i, c in zip(used, used_counts, strict=True)},
        "lining": _attribute(mesh, LINING_ATTRIBUTE, edges, triangles),
    }


def _visibility(bpy: Any, obj: Any) -> dict[str, Any]:
    try:
        hidden: bool | None = bool(obj.hide_get())
    except RuntimeError:  # not in the view layer
        hidden = None
    return {
        "in_view_layer": bpy.context.view_layer.objects.get(obj.name) is not None,
        "hide_get": hidden,
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "collections": sorted(c.name for c in obj.users_collection),
    }


def _object(bpy: Any, depsgraph: Any, name: str) -> dict[str, Any]:
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"name": name, "present": False}
    world = matrix_json(obj.matrix_world)
    report: dict[str, Any] = {
        "name": obj.name,
        "present": True,
        "type": obj.type,
        "data": None if obj.data is None else obj.data.name,
        "library": obj.library is not None,
        "parent": None
        if obj.parent is None
        else [obj.parent.name, obj.parent_type, obj.parent_bone],
        "visibility": _visibility(bpy, obj),
        "matrices": {
            "world": world,
            "world_is_identity": is_identity(world),
            "local": matrix_json(obj.matrix_local),
            "basis": matrix_json(obj.matrix_basis),
            "parent_inverse": matrix_json(obj.matrix_parent_inverse),
        },
        "deltas": {
            "location": plain(obj.delta_location),
            "rotation_euler": plain(obj.delta_rotation_euler),
            "rotation_quaternion": plain(obj.delta_rotation_quaternion),
            "scale": plain(obj.delta_scale),
        },
        "constraints": [
            {"name": c.name, "type": c.type, "properties": rna_properties(c, ("name", "type"))}
            for c in obj.constraints
        ],
        "modifiers": [
            {"name": m.name, "type": m.type, "properties": rna_properties(m, ("name", "type"))}
            for m in obj.modifiers
        ],
        "animation": {"object": _animation(obj), "data": _animation(obj.data)},
        "materials": {
            "slots": [
                {
                    "index": index,
                    "name": slot.name,
                    "material": None if slot.material is None else slot.material.name,
                    "link": slot.link,
                }
                for index, slot in enumerate(obj.material_slots)
            ],
            "data": [None if m is None else m.name for m in getattr(obj.data, "materials", [])],
        },
    }
    if obj.type != "MESH":
        return report
    report["shape_keys"] = _shape_keys(obj)
    report["vertex_groups"] = [group.name for group in obj.vertex_groups]
    # The loop triangles of the authored mesh are a runtime cache: nothing saved changes.
    report["authored"] = _mesh(obj.data, triangulated=True)
    evaluated = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
    )
    try:
        report["evaluated"] = {
            "is_evaluated": bool(evaluated.is_evaluated),
            "matrix_world": matrix_json(evaluated.matrix_world),
            **_mesh(mesh, triangulated=True),
        }
    finally:
        bpy.data.meshes.remove(mesh)
    return report


def _layer_names(report: Mapping[str, Any]) -> dict[str, list[str]]:
    """The names an inspected object carries, by kind, from its report."""
    if not report.get("present") or report.get("type") != "MESH":
        return {}
    names = {
        "vertex_groups": list(report["vertex_groups"]),
        "material_slots": [slot["name"] for slot in report["materials"]["slots"]],
        "shape_keys": [b["name"] for b in (report["shape_keys"] or {}).get("blocks", [])],
    }
    for side in ("authored", "evaluated"):
        names[f"{side}_attributes"] = [a[0] for a in report[side]["attributes"]]
        names[f"{side}_uv_layers"] = list(report[side]["uv"]["names"])
    return names


def lookup_hits(name: str, objects: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    """Where the inspected objects carry `name`, exactly."""
    return [
        {"object": obj, "kind": kind}
        for obj, report in objects.items()
        for kind, names in _layer_names(report).items()
        if name in names
    ]


def _lookup(bpy: Any, name: str, objects: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """`name`, exactly, in `LOOKUP_COLLECTIONS` and on the inspected objects."""
    blocks = []
    for collection in LOOKUP_COLLECTIONS:
        block = getattr(bpy.data, collection).get(name)
        if block is None:
            continue
        found: dict[str, Any] = {
            "collection": collection,
            "name": block.name,
            "users": int(block.users),
            "library": block.library is not None,
            "type": getattr(block, "type", None),
        }
        if collection == "images":
            found["image"] = image_report(block)
        elif collection == "objects":
            found["data"] = None if block.data is None else block.data.name
        elif collection == "meshes":
            found["vertices"] = len(block.vertices)
        blocks.append(found)
    return {"data_blocks": blocks, "on_objects": lookup_hits(name, objects)}


def _inspect(bpy: Any, run_dir: Path, opened: Path) -> None:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = {name: _object(bpy, depsgraph, name) for name in OBJECTS}
    normal = bpy.data.images.get(NORMAL_IMAGE)
    write_json(
        run_dir / REPORT_NAME,
        {
            "inspector": INSPECTOR,
            "mode": "inspect",
            "blender": _blender(bpy),
            "blend": str(opened),
            "depsgraph_mode": depsgraph.mode,
            "donor": {"path": DONOR_PATH, "blob_sha256": DONOR_BLOB_SHA256},
            "objects": objects,
            "images": {NORMAL_IMAGE: None if normal is None else image_report(normal)},
            "lookups": {name: _lookup(bpy, name, objects) for name in CANDIDATE_NAMES},
        },
    )


def main(argv: Sequence[str]) -> None:
    import bpy  # type: ignore[import-not-found]

    if "--" not in argv or len(argv) != argv.index("--") + 3:
        raise InspectError("usage: blender ... --python tunic_intermediates_blender.py -- MODE DIR")
    mode, run = argv[argv.index("--") + 1 :]
    run_dir = Path(run).resolve()
    if tuple(bpy.app.version[:2]) != BLENDER_VERSION:
        raise InspectError(f"Blender {bpy.app.version_string}, pinned {BLENDER_VERSION}")
    opened = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if opened is None or opened != run_dir / SOURCE_BLEND_NAME:
        raise InspectError(f"the open file is {opened}, not {run_dir / SOURCE_BLEND_NAME}")
    if mode != "inspect":
        raise InspectError(f"mode {mode!r} is not inspect")
    _inspect(bpy, run_dir, opened)


if __name__ == "__main__":
    main(sys.argv)
