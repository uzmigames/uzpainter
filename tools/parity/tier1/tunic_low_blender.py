"""Blender side of the Tunic v10 low exporter and extraction (decision 300 section 7). Blender only.

`tools.parity.tier1.tunic_low_export` builds the command, on a hash-checked, read-only private
copy of the preserved `.blend`, and checks everything this script writes. Never run it on the
Assets3D original:

    blender --background --factory-startup --disable-autoexec --offline-mode -noaudio
        <run dir>/18-Tunica-v10.blend --python-exit-code 1
        --python tools/parity/tier1/tunic_low_blender.py -- export <run dir>

One run, one evaluated low. It writes the round's OBJ/MTL and the arrays of `low.npz` and
`highnormal.npy` from the same mesh, so the two cannot come from different objects or runs.

1. **Pins first.** Before anything is evaluated: the source object `SOURCE_OBJECT` (a mesh in
   the view layer, no modifier, no constraint, the exact identity world matrix, no shape keys,
   the one UV layer `UV_MAP` active), its material slots (`SOURCE_MATERIALS`: literally
   `DefaultMaterial.001`), no datablock already named after the export (`source_problems`,
   `name_problems`), every `wm.obj_export` option (`option_problems`, front N's
   `sash_low_blender` pins unchanged), and the packed Normal `NORMAL_IMAGE`: the SHA-256 and PNG
   header of its packed bytes and every setting Blender decodes it with, as the inspection read
   them (`normal_problems`). Nothing is set on the image to improve agreement.
2. **One evaluation.** The donor's read (`DONOR_PATH`, `garment_blender_io.py extract`, LF blob
   `DONOR_BLOB_SHA256`): `new_from_object` of the low evaluated in the viewport depsgraph, every
   data layer kept, no visibility changed, then `calc_loop_triangles` and `foreach_get` into the
   donor's float32 and int32 buffers (`read_mesh`). The low must be all triangles, its loop
   triangles exactly its polygons in order (`triangulation_problems`), at the pinned counts.
3. **Arrays.** `donor_arrays` is the donor's arithmetic step for step (positions by the 3x3 and
   the translation in float64, corner normals by the inverse transpose and renormalised with
   `+ 1e-12`, stored float32). The lining is the donor's POINT attribute `LINING_ATTRIBUTE`, read
   into float32, but refused where the donor zero-fills: absent, another domain or type, a
   non-finite value, or no triangle edge whose ends lie strictly on either side of 0.5
   (`lining_values`, `crossings`). The raw evaluated corner normals are kept as well
   (`evaluated.cn.npy`), so the host can redo the donor's normal arithmetic bit for bit.
4. **The export copy.** The evaluated mesh itself becomes the export: renamed `EXPORT_OBJECT`, its
   material list replaced by one NEW material named `TEXTURE_SET` (`DefaultMaterial`), linked to
   a new object. That is an authored name remap on the copy only (`REMAP`): the source slot's
   `DefaultMaterial.001` is pinned and left as found, and the new material is not the recovered
   historical one. Geometry, UVs and corner normals are not rebuilt, fitted or recomputed (no
   custom-normal re-encoding). Just before `wm.obj_export`, the export object is evaluated
   again and its positions, triangles, loops, UVs and corner normals must equal the arrays bit
   for bit (`export_readback`).
5. **Normal.** The donor's decode, unchanged: `image.pixels.foreach_get` into float32,
   `reshape(height, width, 4)[..., :3]`, `np.save` (rows bottom first, no transfer function).
   The settings are read again after the decode and must still be the pins.

Nothing is ever saved: the opened file is the private copy, and the host checks its hash after
Blender exits. Everything above `main` is plain Python and numpy, so the host and the tests import
it without Blender.
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

EXPORTER = "uzpainter/parity/tunic-low-export/1"
# The extraction donor, named for provenance only: never run or imported. The pin is the raw LF
# git blob at Assets3D f49fe67c (the contract's Scripts table; the same blob at 1c9a312a).
DONOR_PATH = "Pipeline/painting/garment_blender_io.py"
DONOR_BLOB_SHA256 = "805f9ccc5430e47ac49c4b50651e271b2e6da68f8455fa231306f3462b0c8a4d"
# The export's precedent in this repository (front N): its options and remap are followed.
PRECEDENT = "tools/parity/tier1/sash_low_blender.py"
BLENDER_VERSION = (5, 2)
DEPSGRAPH_MODE = "VIEWPORT"  # the donor's background `evaluated_depsgraph_get()`

# Blender runs this file by path, without the repository on `sys.path`: it imports nothing from
# `tools`, and the host checks that these names match its own pins.
SOURCE_BLEND_NAME = "18-Tunica-v10.blend"  # Blender writes this base name into the MTL
SOURCE_OBJECT = "18-Tunica-Low"
SOURCE_MATERIALS = ("DefaultMaterial.001",)  # the slots' materials, literally, in order
SOURCE_MODIFIERS: tuple[tuple[str, str], ...] = ()
UV_MAP = "UVMap"
UV_LAYERS = (UV_MAP,)
VERTICES = 5392  # the inspection (record d5d5a6d5...): authored and evaluated agree
TRIANGLES = 11000  # the report's 11,000; every polygon is a triangle

TEXTURE_SET = "DefaultMaterial"  # the record's texture set; the OBJ material must give it
EXPORT_OBJECT = "18-Tunica_low"
OBJ_NAME = "18-Tunica-v10-low.obj"
MTL_NAME = "18-Tunica-v10-low.mtl"
REMAP = {
    "kind": "authored name remap",
    "source_material": SOURCE_MATERIALS[0],
    "export_material": TEXTURE_SET,
    "scope": "a new, empty material on the exported copy only; the source slot is left as found",
    "historical": "not the recovered historical material",
}

LINING_ATTRIBUTE = "LiningMask"  # the report's mask recipe and the donor's default
LINING_DOMAIN = "POINT"
LINING_TYPE = "FLOAT"
LINING_THRESHOLD = 0.5  # garment_material_masks.py: `lining - 0.5` changes sign across the rim

NORMAL_IMAGE = "Source_v6_HighNormal"
NORMAL_SHA256 = "5815e0782be67818d31b1f99d108ecc4a0462bdeb18ba9bc1d9eb508eb44f55a"
NORMAL_PNG = {"width": 4096, "height": 4096, "bit_depth": 16, "colour_type": 2, "interlace": 0}
# The settings as the inspection read them (report 61ec5736...), before the buffer loads.
NORMAL_SETTINGS: dict[str, Any] = {
    "type": "IMAGE",
    "source": "FILE",
    "file_format": "PNG",
    "packed_files": 1,
    "colorspace": "Non-Color",
    "colorspace_is_data": True,
    "alpha_mode": "STRAIGHT",
    "use_half_precision": True,
}
# And once Blender has loaded it: the precision the donor's `image.pixels` reads.
NORMAL_LOADED: dict[str, Any] = {
    "size": [4096, 4096],
    "channels": 4,
    "depth": 96,
    "is_float": True,
    "has_data": True,
    "is_dirty": False,
}
NORMAL_DECODE = (
    "image.pixels.foreach_get into float32[width * height * 4], reshape(height, width, 4)"
    "[..., :3], np.save: the donor's decode, rows bottom first, no transfer function"
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# low.npz members in the donor's `np.savez` order, with the dtype and trailing shape it writes.
LOW_ARRAYS: dict[str, tuple[str, tuple[int, ...]]] = {
    "co": ("<f4", (3,)),
    "lt": ("<i4", (3,)),
    "lv": ("<i4", ()),
    "uv": ("<f4", (2,)),
    "cn": ("<f4", (3,)),
    "lining": ("<f4", ()),
}
LOW_FILES = {name: f"low.{name}.npy" for name in LOW_ARRAYS}
RAW_NORMALS = "evaluated.cn.npy"  # the corner normals as read, before the donor's arithmetic
HIGHNORMAL = "highnormal.npy"
REPORT_NAME = "export-report.json"

FORWARD_AXIS = "NEGATIVE_Z"
UP_AXIS = "Y"
# Front N's `sash_low_blender.OBJ_EXPORT_OPTIONS`, unchanged (the host checks the equality).
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


class ExportError(Exception):
    """The source or the running Blender does not match a pin; nothing is written as valid."""


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8")


def array_digest(array: Any) -> str:
    """SHA-256 of an array's dtype, shape and C-order bytes (front P's `array_digest`)."""
    value = np.ascontiguousarray(array)
    digest = hashlib.sha256(f"{value.dtype.str}{list(value.shape)}".encode("ascii"))
    digest.update(value.tobytes())
    return digest.hexdigest()


def is_identity(matrix: Iterable[Iterable[float]]) -> bool:
    rows = [list(row) for row in matrix]
    return len(rows) == 4 and all(
        len(row) == 4 and all(value == (1.0 if i == j else 0.0) for j, value in enumerate(row))
        for i, row in enumerate(rows)
    )


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


def source_problems(obj: Any) -> list[str]:
    """The source object against its pins."""
    if obj.type != "MESH":
        return [f"{obj.name} is a {obj.type}, not a MESH"]
    problems: list[str] = []
    modifiers = tuple((m.name, m.type) for m in obj.modifiers)
    if modifiers != SOURCE_MODIFIERS:
        problems.append(f"modifier stack is {list(modifiers)}, pinned {list(SOURCE_MODIFIERS)}")
    if len(obj.constraints):
        problems.append(f"the object has {len(obj.constraints)} constraints")
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
    layers = tuple(layer.name for layer in obj.data.uv_layers)
    active = obj.data.uv_layers.active
    if layers != UV_LAYERS or active is None or active.name != UV_MAP:
        problems.append(f"UV layers are {list(layers)}, pinned {list(UV_LAYERS)}, {UV_MAP} active")
    return problems


def name_problems(materials: Any, objects: Any, meshes: Any) -> list[str]:
    """The new datablocks must get their exact names: none may exist already."""
    return [
        f"the file already holds a {kind} named {name!r}"
        for kind, collection, name in (
            ("material", materials, TEXTURE_SET),
            ("object", objects, EXPORT_OBJECT),
            ("mesh", meshes, EXPORT_OBJECT),
        )
        if collection.get(name) is not None
    ]


def png_header(data: bytes) -> dict[str, int] | None:
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


def image_settings(image: Any) -> dict[str, Any]:
    """The settings Blender decodes the image with; reading them loads no buffer."""
    return {
        "type": image.type,
        "source": image.source,
        "file_format": image.file_format,
        "packed_files": len(image.packed_files),
        "colorspace": image.colorspace_settings.name,
        "colorspace_is_data": bool(image.colorspace_settings.is_data),
        "alpha_mode": image.alpha_mode,
        "use_half_precision": bool(image.use_half_precision),
    }


def image_loaded(image: Any) -> dict[str, Any]:
    """The loaded buffer's shape and precision (reading the size loads it; nothing is written)."""
    return {
        "size": list(image.size),
        "channels": int(image.channels),
        "depth": int(image.depth),
        "is_float": bool(image.is_float),
        "has_data": bool(image.has_data),
        "is_dirty": bool(image.is_dirty),
    }


def settings_problems(found: Mapping[str, Any], pinned: Mapping[str, Any], what: str) -> list[str]:
    return [
        f"{what} {name} is {found.get(name)!r}, pinned {value!r}"
        for name, value in pinned.items()
        if found.get(name) != value
    ] + [f"{what} {name} is not pinned" for name in sorted(set(found) - set(pinned))]


def normal_problems(identity: Mapping[str, Any] | None, settings: Mapping[str, Any]) -> list[str]:
    """The packed Normal's bytes and settings against the pins, before its buffer loads."""
    if identity is None:
        return [f"{NORMAL_IMAGE} has no packed file"]
    problems = []
    if identity["sha256"] != NORMAL_SHA256:
        problems.append(f"{NORMAL_IMAGE} packed SHA-256 is {identity['sha256']}, pinned")
    if identity["png"] != NORMAL_PNG:
        problems.append(f"{NORMAL_IMAGE} PNG header is {identity['png']}, pinned {NORMAL_PNG}")
    return problems + settings_problems(settings, NORMAL_SETTINGS, NORMAL_IMAGE)


def triangle_edges(triangle_vertices: Any) -> Any:
    """The undirected edges of loop-triangle vertex triples, each once, as the donor's graph
    (`garment_material_masks.Graph`) builds them."""
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


def lining_summary(lining: Any, triangle_vertices: Any) -> dict[str, Any]:
    values = np.asarray(lining, np.float32)
    return {
        "attribute": [LINING_ATTRIBUTE, LINING_DOMAIN, LINING_TYPE],
        "count": int(values.size),
        "finite": int(np.isfinite(values).sum()),
        "min": float(values.min()) if values.size else None,
        "max": float(values.max()) if values.size else None,
        "below": int(np.count_nonzero(values < LINING_THRESHOLD)),
        "at": int(np.count_nonzero(values == LINING_THRESHOLD)),
        "above": int(np.count_nonzero(values > LINING_THRESHOLD)),
        "crossings_triangle_edges": crossings(values, triangle_edges(triangle_vertices)),
    }


def lining_problems(lining: Any, vertices: int, triangle_vertices: Any) -> list[str]:
    """Where the donor zero-fills or treats the mesh as outer cloth, the round refuses."""
    values = np.asarray(lining)
    if values.dtype != np.float32 or values.shape != (vertices,):
        return [f"{LINING_ATTRIBUTE} is {values.dtype}{list(values.shape)}, pinned float32"]
    if not np.isfinite(values).all():
        return [f"{LINING_ATTRIBUTE} holds non-finite values"]
    if crossings(values, triangle_edges(triangle_vertices)) == 0:
        return [f"{LINING_ATTRIBUTE} crosses {LINING_THRESHOLD} on no triangle edge"]
    return []


def lining_values(attribute: Any, vertices: int) -> Any:
    """The donor's read of the POINT attribute into float32; absent, another domain or another
    type refuses (the donor would zero-fill and warn)."""
    if attribute is None:
        raise ExportError(f"the low has no attribute {LINING_ATTRIBUTE!r}; no zero fallback")
    if (attribute.domain, attribute.data_type) != (LINING_DOMAIN, LINING_TYPE):
        raise ExportError(
            f"{LINING_ATTRIBUTE!r} is {attribute.domain}/{attribute.data_type}, "
            f"pinned {LINING_DOMAIN}/{LINING_TYPE}"
        )
    values = np.zeros(vertices, np.float32)
    attribute.data.foreach_get("value", values)
    return values


def read_mesh(mesh: Any) -> dict[str, Any]:
    """The donor's buffers from an evaluated mesh after `calc_loop_triangles`: positions, loop
    triangles' loops, loop vertices, the active UV layer's UVs and the corner normals, flat as
    `foreach_get` fills them, plus each polygon's loop count."""
    nv, nl = len(mesh.vertices), len(mesh.loops)
    co = np.empty(nv * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    lt = np.empty(len(mesh.loop_triangles) * 3, np.int32)
    mesh.loop_triangles.foreach_get("loops", lt)
    lv = np.empty(nl, np.int32)
    mesh.loops.foreach_get("vertex_index", lv)
    layer = mesh.uv_layers.active
    if layer is None or layer.name != UV_MAP:
        raise ExportError(f"the active UV layer is {getattr(layer, 'name', None)!r}, not {UV_MAP}")
    uv = np.empty(nl * 2, np.float32)
    layer.data.foreach_get("uv", uv)
    cn = np.empty(nl * 3, np.float32)
    mesh.corner_normals.foreach_get("vector", cn)
    totals = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_total", totals)
    return {"co": co, "lt": lt, "lv": lv, "uv": uv, "cn": cn, "loop_total": totals}


def raw_digests(raw: Mapping[str, Any]) -> dict[str, str]:
    return {name: array_digest(raw[name]) for name in ("co", "lt", "lv", "uv", "cn")}


def triangulation_problems(lt: Any, loop_totals: Any, vertices: int) -> list[str]:
    """Every polygon a triangle and loop triangle k exactly polygon k's loops in order, so the
    OBJ's faces (polygons) are the loop triangles corner for corner; the pinned counts."""
    tris = np.asarray(lt, np.int64).reshape(-1, 3)
    totals = np.asarray(loop_totals, np.int64)
    problems = []
    if vertices != VERTICES or len(tris) != TRIANGLES:
        problems.append(f"{vertices} vertices and {len(tris)} triangles, pinned {VERTICES}")
    if (totals != 3).any():
        problems.append(f"{int((totals != 3).sum())} polygons are not triangles")
    elif len(tris) != len(totals) or not np.array_equal(
        tris, np.arange(3 * len(totals)).reshape(-1, 3)
    ):
        problems.append("the loop triangles are not the polygons' loops in order")
    return problems


def donor_normals(cn: Any, normal_matrix: Any) -> Any:
    """The donor's corner normals: the inverse transpose in float64, renormalised (+ 1e-12),
    stored float32."""
    normals = (
        np.asarray(normal_matrix, np.float64) @ np.asarray(cn, np.float32).reshape(-1, 3).T
    ).T
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    return normals.astype(np.float32)


def donor_arrays(
    raw: Mapping[str, Any], lining: Any, rotation: Any, translation: Any, normal_matrix: Any
) -> dict[str, Any]:
    """`garment_blender_io.extract`'s arithmetic, step for step, in `np.savez`'s member order."""
    positions = np.asarray(raw["co"], np.float32).reshape(-1, 3)
    world = (np.asarray(rotation, np.float64) @ positions.T).T + np.asarray(translation)
    return {
        "co": world.astype(np.float32),
        "lt": np.asarray(raw["lt"], np.int32).reshape(-1, 3),
        "lv": np.asarray(raw["lv"], np.int32),
        "uv": np.asarray(raw["uv"], np.float32).reshape(-1, 2),
        "cn": donor_normals(raw["cn"], normal_matrix),
        "lining": np.asarray(lining, np.float32),
    }


def decode_normal(pixels: Any, width: int, height: int) -> Any:
    """The donor's `highnormal.npy` array: RGB of the float RGBA pixels, rows bottom first."""
    return np.asarray(pixels, np.float32).reshape(height, width, 4)[..., :3]


def _blender(bpy: Any) -> dict[str, Any]:
    return {
        "version": list(bpy.app.version),
        "version_string": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode("ascii", "replace"),
        "build_branch": bpy.app.build_branch.decode("ascii", "replace"),
        "file_version": list(bpy.data.version),
        "numpy": np.__version__,
    }


def _visibility(obj: Any) -> dict[str, bool | None]:
    try:
        hidden: bool | None = bool(obj.hide_get())
    except RuntimeError:  # not in the view layer
        hidden = None
    return {
        "hide_get": hidden,
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
    }


def _export(bpy: Any, run_dir: Path, opened: Path) -> None:
    view_layer = bpy.context.view_layer
    obj = bpy.data.objects.get(SOURCE_OBJECT)
    if obj is None or view_layer.objects.get(SOURCE_OBJECT) is None:
        raise ExportError(f"no object {SOURCE_OBJECT!r} in the view layer")
    problems = source_problems(obj)
    problems += name_problems(bpy.data.materials, bpy.data.objects, bpy.data.meshes)
    available = [p.identifier for p in bpy.ops.wm.obj_export.get_rna_type().properties]
    problems += option_problems(available, OBJ_EXPORT_OPTIONS)
    image = bpy.data.images.get(NORMAL_IMAGE)
    if image is None:
        problems.append(f"no image {NORMAL_IMAGE!r}")
        identity, settings = None, {}
    else:
        packed = image.packed_file
        identity = None if packed is None else packed_identity(bytes(packed.data))
        settings = image_settings(image)
        problems += normal_problems(identity, settings)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if depsgraph.mode != DEPSGRAPH_MODE:
        problems.append(f"depsgraph mode is {depsgraph.mode}, pinned {DEPSGRAPH_MODE}")
    if problems:
        raise ExportError("; ".join(problems))
    visibility = _visibility(obj)

    # The one evaluation: the donor's read; this mesh then becomes the export copy.
    mesh = bpy.data.meshes.new_from_object(
        obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph
    )
    mesh.calc_loop_triangles()
    raw = read_mesh(mesh)
    nv = len(mesh.vertices)
    lining = lining_values(mesh.attributes.get(LINING_ATTRIBUTE), nv)
    problems = triangulation_problems(raw["lt"], raw["loop_total"], nv)
    if not problems:
        problems = lining_problems(lining, nv, raw["lv"][raw["lt"]])
    if problems:
        raise ExportError("; ".join(problems))
    world = obj.matrix_world
    arrays = donor_arrays(
        raw,
        lining,
        np.array(world.to_3x3(), np.float64),
        np.array(world.translation),
        np.array(world.to_3x3().inverted().transposed(), np.float64),
    )
    attributes = sorted(
        [a.name, a.domain, a.data_type] for a in mesh.attributes if not a.name.startswith(".")
    )

    mesh.name = EXPORT_OBJECT
    mesh.materials.clear()
    material = bpy.data.materials.new(TEXTURE_SET)
    mesh.materials.append(material)
    exported = bpy.data.objects.new(EXPORT_OBJECT, mesh)
    bpy.context.scene.collection.objects.link(exported)
    names = (exported.name, mesh.name, material.name)
    if names != (EXPORT_OBJECT, EXPORT_OBJECT, TEXTURE_SET):
        raise ExportError(f"the copy was named {names}")
    for other in view_layer.objects:
        other.select_set(False)
    exported.select_set(True)
    view_layer.objects.active = exported

    # What the exporter evaluates is the extracted mesh, bit for bit.
    view_layer.update()
    check = bpy.context.evaluated_depsgraph_get()
    evaluated = exported.evaluated_get(check)
    again = evaluated.to_mesh()
    try:
        again.calc_loop_triangles()
        readback = raw_digests(read_mesh(again))
    finally:
        evaluated.to_mesh_clear()
    if readback != raw_digests(raw):
        differ = sorted(k for k in readback if readback[k] != raw_digests(raw)[k])
        raise ExportError(f"the export object's evaluated mesh differs in {differ}; no export")

    bpy.ops.wm.obj_export(filepath=str(run_dir / OBJ_NAME), **OBJ_EXPORT_OPTIONS)

    loaded = image_loaded(image)
    problems = settings_problems(loaded, NORMAL_LOADED, NORMAL_IMAGE)
    if problems:
        raise ExportError("; ".join(problems))
    width, height = image.size
    pixels = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    normal = decode_normal(pixels, width, height)
    after = {"settings": image_settings(image), "loaded": image_loaded(image)}
    problems = settings_problems(after["settings"], NORMAL_SETTINGS, NORMAL_IMAGE)
    problems += settings_problems(after["loaded"], NORMAL_LOADED, NORMAL_IMAGE)
    if problems:
        raise ExportError("after the decode: " + "; ".join(problems))

    for name, array in arrays.items():
        np.save(run_dir / LOW_FILES[name], array, allow_pickle=False)
    np.save(run_dir / RAW_NORMALS, raw["cn"].reshape(-1, 3), allow_pickle=False)
    np.save(run_dir / HIGHNORMAL, normal, allow_pickle=False)
    matrix = [list(row) for row in world]
    write_json(
        run_dir / REPORT_NAME,
        {
            "exporter": EXPORTER,
            "mode": "export",
            "blender": _blender(bpy),
            "blend": str(opened),
            "depsgraph_mode": depsgraph.mode,
            "donor": {"path": DONOR_PATH, "blob_sha256": DONOR_BLOB_SHA256},
            "precedent": PRECEDENT,
            "source": {
                "object": obj.name,
                "materials": [s.material.name for s in obj.material_slots],
                "modifiers": [[m.name, m.type] for m in obj.modifiers],
                "matrix_world": matrix,
                "matrix_is_identity": is_identity(matrix),
                "uv_layers": [layer.name for layer in obj.data.uv_layers],
                "visibility_as_found": visibility,
            },
            "remap": REMAP,
            "export": {
                "object": exported.name,
                "material": material.name,
                "obj": OBJ_NAME,
                "mtl": MTL_NAME,
                "options": OBJ_EXPORT_OPTIONS,
                "readback_digests": readback,
            },
            "mesh": {
                "vertices": nv,
                "loops": len(mesh.loops),
                "polygons": len(mesh.polygons),
                "triangles": len(arrays["lt"]),
                "attributes": attributes,
                "uv_map": UV_MAP,
            },
            "lining": lining_summary(arrays["lining"], arrays["lv"][arrays["lt"]]),
            "normal": {
                "image": NORMAL_IMAGE,
                "packed": identity,
                "settings": settings,
                "loaded": loaded,
                "after_decode": after,
                "decode": NORMAL_DECODE,
            },
            "digests": {
                **{name: array_digest(a) for name, a in arrays.items()},
                "evaluated_cn": array_digest(raw["cn"].reshape(-1, 3)),
                "highnormal": array_digest(normal),
            },
        },
    )


def main(argv: Sequence[str]) -> None:
    import bpy  # type: ignore[import-not-found]

    if "--" not in argv or len(argv) != argv.index("--") + 3:
        raise ExportError("usage: blender ... --python tunic_low_blender.py -- export DIR")
    mode, run = argv[argv.index("--") + 1 :]
    run_dir = Path(run).resolve()
    if tuple(bpy.app.version[:2]) != BLENDER_VERSION:
        raise ExportError(f"Blender {bpy.app.version_string}, pinned {BLENDER_VERSION}")
    opened = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if opened is None or opened != run_dir / SOURCE_BLEND_NAME:
        raise ExportError(f"the open file is {opened}, not {run_dir / SOURCE_BLEND_NAME}")
    if mode != "export":
        raise ExportError(f"mode {mode!r} is not export")
    _export(bpy, run_dir, opened)


if __name__ == "__main__":
    main(sys.argv)
