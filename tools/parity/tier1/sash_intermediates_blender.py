"""Blender side of the Sash v5 mask-generator intermediates (decision 300 item 7). Blender only.

`tools.parity.tier1.sash_intermediates` builds the command, on a hash-checked, read-only private
copy of the preserved `.blend`, and checks everything this script writes. Never run it on the
Assets3D original:

    blender --background --factory-startup --disable-autoexec --offline-mode -noaudio
        <run dir>/25-Faixa-Cintura-v5.blend --python-exit-code 1
        --python tools/parity/tier1/sash_intermediates_blender.py -- extract|ao <run dir>

The algorithm is the `extract` command of Assets3D `Pipeline/painting/garment_blender_io.py`
(`DONOR_SHA256`), as `sashchain.sh` called it, with every choice it left open pinned here. The
donor ran on the round's `bake/baked-v5.blend`, which is lost; the preserved piece `.blend` holds
its low renamed `-Low-Authoring` (`deliver.py`), which still carries the `PartId` point
attribute that `deliver.py` did not copy to `-Low-Game`.

- **extract.** The Authoring low, evaluated through the viewport depsgraph, read exactly as the
  donor reads it (`donor_arrays`): world positions, loop-triangle loops, loop vertices, the active
  UV map's per-loop UVs, world corner normals, and `PartId` per vertex. Unlike the donor, a missing
  `PartId`, one on another domain or of another type refuses the run (`part_values`): it is never
  replaced by zeros. The arrays are written as `.npy` files with the polygon loop starts and
  sizes (for the construction centre). `deliver.py`'s Low-Game construction is replayed on the
  same low and its read-back corner normals are written too (`_redelivered_normals`). The host
  compares all of it with front N's Low-Game table and only then packs `low.npz`.
- **ao.** A new, labelled substitute for the lost AO: the donor's AO bake, selected to active from
  the preserved High onto the Authoring low, at `AO_RESOLUTION` with every Cycles and bake
  option pinned (`CYCLES_SETTINGS`, `BAKE_OPTIONS`) on the CPU with seed 0. Just before baking,
  with the bake's visibility already set, the low is read again and each array's digest must
  equal the accepted extraction's (`ao-expect.json`, written by the host). Any difference, any
  modifier on the low (which would leave the render evaluation unproven) and any baked R value
  outside [0, 1] refuses. The R channel is saved as float16 `ao.npy`, rows bottom first as
  Blender's `image.pixels` holds them, as the donor did. The
  report holds the options passed and, when Blender keeps them, the operator's last-used ones.

- **control** (factory scene, no file opened). Whether this Blender keeps the last-used
  properties of a background Python call at all: `operator_properties_last` before and after a
  `mesh.primitive_cube_add` and a tiny AO bake, with each call's visible effect (`_control`).
  The AO receipt calls its own readback `unavailable` only with this control's outcome linked.

Nothing is ever saved: the opened file is the private copy, and the host checks its hash after
Blender exits. Everything above `main` is plain Python and numpy, so the host and the tests import
it without Blender.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

EXTRACTOR = "uzpainter/parity/sash-intermediates/1"
# The algorithm's source, named for provenance only: it is never run or imported.
DONOR_PATH = "Pipeline/painting/garment_blender_io.py"
DONOR_SHA256 = "f5babc04e3b5688c2654f235d35a0530fe2dd9555a983906345174b5dbe9fdbd"
BLENDER_VERSION = (5, 2)
DEPSGRAPH_MODE = "VIEWPORT"
# Blender runs this file by path, without the repository on `sys.path`, so it imports nothing
# from `tools`; the host checks this equals `sash_low_blender.SOURCE_BLEND_NAME`.
SOURCE_BLEND_NAME = "25-Faixa-Cintura-v5.blend"

LOW_OBJECT = "25-Faixa-Cintura-v5-Low-Authoring"
HIGH_OBJECT = "25-Faixa-Cintura-v5-High"
UV_MAP = "UVMap"
PART_ATTRIBUTE = "PartId"  # sashchain.sh `--lining-attribute PartId`; bakeprep.py made it
PART_DOMAIN = "POINT"
PART_TYPE = "FLOAT"

# low.npz members in the donor's order, with the dtype and trailing shape the donor writes.
LOW_ARRAYS: dict[str, tuple[str, tuple[int, ...]]] = {
    "co": ("<f4", (3,)),
    "lt": ("<i4", (3,)),
    "lv": ("<i4", ()),
    "uv": ("<f4", (2,)),
    "cn": ("<f4", (3,)),
    "lining": ("<f4", ()),
}
FACE_ARRAYS: dict[str, tuple[str, tuple[int, ...]]] = {
    "face_loop_start": ("<i4", ()),
    "face_loop_total": ("<i4", ()),
}
EXTRACT_REPORT = "extract-report.json"
AO_REPORT = "ao-report.json"
AO_EXPECT = "ao-expect.json"
AO_NAME = "ao.npy"
REDELIVERED_NAME = "redelivered.cn.npy"
REDELIVERED_MESH = "uzp_sash_redelivered"
# deliver.py built Low-Game from the evaluated low; replayed for its normal conversion only.
DELIVER_PATH = "Pipeline/retopology/waist-v5/deliver.py"
DELIVER_SHA256 = "69efa5390b2f4380902e84680ad1994ea9c98c60bb45454ac50468335fb3bf9d"

AO_RESOLUTION = 2048  # sashchain.sh `--ao-resolution 2048`
AO_IMAGE = "uzp_sash_ao_bake"
AO_COLORSPACE = "Non-Color"
# Cycles settings set before the bake and read back. The donor set only `samples` (96, from
# sashchain.sh) and asked for OptiX; the device is pinned to the CPU here, and seed, adaptive
# sampling, denoising and the time limit are fixed so the bake does not depend on the file's
# scene or the machine's GPU.
CYCLES_SETTINGS: dict[str, Any] = {
    "device": "CPU",
    "samples": 96,
    "seed": 0,
    "use_animated_seed": False,
    "use_adaptive_sampling": False,
    "use_denoising": False,
    "time_limit": 0.0,
}
# Settings the donor never set, recorded as found in the hash-pinned file (so the repeat must
# reproduce them), never changed.
CYCLES_AS_FOUND = (
    "sampling_pattern",
    "use_light_tree",
    "use_auto_tile",
    "tile_size",
    "sample_offset",
    "scrambling_distance",
    "auto_scrambling_distance",
)
# Every `object.bake` option. The donor passed type AO, use_selected_to_active, max_ray_distance
# 0.014, cage_extrusion 0.006 (its `--cage` default: an extrusion, no cage object) and margin 8;
# the others took the file's bake settings, which are pinned here to Blender's defaults instead.
BAKE_OPTIONS: dict[str, Any] = {
    "type": "AO",
    "pass_filter": [],
    "filepath": "",
    "width": AO_RESOLUTION,
    "height": AO_RESOLUTION,
    "margin": 8,
    "margin_type": "ADJACENT_FACES",
    "use_selected_to_active": True,
    "max_ray_distance": 0.014,
    "cage_extrusion": 0.006,
    "cage_object": "",
    "normal_space": "TANGENT",
    "normal_r": "POS_X",
    "normal_g": "POS_Y",
    "normal_b": "POS_Z",
    "target": "IMAGE_TEXTURES",
    "save_mode": "INTERNAL",
    "use_clear": True,
    "use_cage": False,
    "use_split_materials": False,
    "use_automatic_name": False,
    "uv_layer": UV_MAP,
    "view_from": "ABOVE_SURFACE",
}
# Pinned whether Blender exposes it as an `object.bake` option or only as a scene bake setting
# (`scene.render.bake.view_from`): it is set on the scene either way, and passed to the
# operator only when the operator has it.
SCENE_OR_OPERATOR_OPTIONS = frozenset({"view_from"})


class ExtractError(Exception):
    """The source or the running Blender does not match a pin; nothing is written as valid."""


def array_digest(array: Any) -> str:
    """SHA-256 of an array's dtype, shape and C-order bytes: what the AO run re-derives."""
    value = np.ascontiguousarray(array)
    digest = hashlib.sha256(f"{value.dtype.str}{list(value.shape)}".encode("ascii"))
    digest.update(value.tobytes())
    return digest.hexdigest()


def donor_arrays(
    co: Any,
    lt: Any,
    lv: Any,
    uv: Any,
    cn: Any,
    lining: Any,
    rotation: Any,
    translation: Any,
    normal_matrix: Any,
) -> dict[str, Any]:
    """`garment_blender_io.extract`'s arithmetic, step for step: positions by the 3x3 and the
    translation in float64, corner normals by the inverse transpose and renormalised (plus
    1e-12), both stored as float32; loops, loop vertices and UVs as read."""
    positions = np.asarray(co, np.float32).reshape(-1, 3)
    world = (np.asarray(rotation, np.float64) @ positions.T).T + np.asarray(translation)
    normals = (
        np.asarray(normal_matrix, np.float64) @ np.asarray(cn, np.float32).reshape(-1, 3).T
    ).T
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    return {
        "co": world.astype(np.float32),
        "lt": np.asarray(lt, np.int32).reshape(-1, 3),
        "lv": np.asarray(lv, np.int32),
        "uv": np.asarray(uv, np.float32).reshape(-1, 2),
        "cn": normals.astype(np.float32),
        "lining": np.asarray(lining, np.float32),
    }


def part_values(attribute: Any, vertices: int) -> Any:
    """The `PartId` values per vertex. The donor zeroes a missing attribute and carries on; here
    a missing one, another domain or another type refuses."""
    if attribute is None:
        raise ExtractError(f"the low has no attribute {PART_ATTRIBUTE!r}; no zero fallback")
    if (attribute.domain, attribute.data_type) != (PART_DOMAIN, PART_TYPE):
        raise ExtractError(
            f"{PART_ATTRIBUTE!r} is {attribute.domain}/{attribute.data_type}, "
            f"pinned {PART_DOMAIN}/{PART_TYPE}"
        )
    values = np.empty(vertices, np.float32)
    attribute.data.foreach_get("value", values)
    if not np.isfinite(values).all() or (values != np.rint(values)).any() or values.min() < 1:
        raise ExtractError(f"{PART_ATTRIBUTE!r} holds values that are not part ids >= 1")
    return values


def option_problems(available: Iterable[str], pinned: Mapping[str, Any]) -> list[str]:
    """Every `object.bake` option the pins leave out, and every pin it does not have."""
    names = {name for name in available if name != "rna_type"}
    problems = [
        f"object.bake option {name!r} is not pinned" for name in sorted(names - set(pinned))
    ]
    problems += [
        f"pinned option {name!r} is not an option of object.bake"
        for name in sorted(set(pinned) - names)
    ]
    return problems


def operator_pins(available: Iterable[str]) -> dict[str, Any]:
    """The pins the operator takes: `BAKE_OPTIONS` without the scene-or-operator options the
    running operator does not have."""
    names = set(available)
    return {
        name: value
        for name, value in BAKE_OPTIONS.items()
        if name not in SCENE_OR_OPERATOR_OPTIONS or name in names
    }


def bake_call_options(pins: Mapping[str, Any]) -> dict[str, Any]:
    """The pins as the operator takes them (`pass_filter` is a set)."""
    return {**pins, "pass_filter": set(pins["pass_filter"])}


def ao_array(pixels: Any, resolution: int) -> Any:
    """The donor's `ao.npy`: channel R of the RGBA float pixels, rows bottom first, float16."""
    values = np.asarray(pixels, np.float32).reshape(resolution, resolution, 4)[..., 0]
    return values.astype(np.float16)


def settings_problems(found: Mapping[str, Any], pinned: Mapping[str, Any], what: str) -> list[str]:
    return [
        f"{what} {name} reads back {found.get(name)!r}, pinned {value!r}"
        for name, value in pinned.items()
        if found.get(name) != value
    ]


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8")


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


def _low(bpy: Any) -> tuple[Any, dict[str, Any]]:
    """The Authoring low, made visible in the view layer (as the donor's scene had it)."""
    view_layer = bpy.context.view_layer
    obj = bpy.data.objects.get(LOW_OBJECT)
    if obj is None or view_layer.objects.get(LOW_OBJECT) is None:
        raise ExtractError(f"no object {LOW_OBJECT!r} in the view layer")
    if obj.type != "MESH":
        raise ExtractError(f"{LOW_OBJECT} is a {obj.type}, not a MESH")
    found = _visibility(obj)
    obj.hide_viewport = False
    obj.hide_set(False)
    return obj, found


def _read_low(bpy: Any, obj: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The donor's read of the evaluated low, plus polygon loop starts and sizes."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if depsgraph.mode != DEPSGRAPH_MODE:
        raise ExtractError(f"depsgraph mode is {depsgraph.mode}, pinned {DEPSGRAPH_MODE}")
    mesh = bpy.data.meshes.new_from_object(
        obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph
    )
    try:
        mesh.calc_loop_triangles()
        nv, nl, nf = len(mesh.vertices), len(mesh.loops), len(mesh.polygons)
        co = np.empty(nv * 3, np.float32)
        mesh.vertices.foreach_get("co", co)
        lt = np.empty(len(mesh.loop_triangles) * 3, np.int32)
        mesh.loop_triangles.foreach_get("loops", lt)
        lv = np.empty(nl, np.int32)
        mesh.loops.foreach_get("vertex_index", lv)
        layer = mesh.uv_layers.active
        if layer is None or layer.name != UV_MAP:
            raise ExtractError(
                f"the active UV map is {getattr(layer, 'name', None)!r}, not {UV_MAP}"
            )
        uv = np.empty(nl * 2, np.float32)
        layer.data.foreach_get("uv", uv)
        cn = np.empty(nl * 3, np.float32)
        mesh.corner_normals.foreach_get("vector", cn)
        lining = part_values(mesh.attributes.get(PART_ATTRIBUTE), nv)
        start = np.empty(nf, np.int32)
        mesh.polygons.foreach_get("loop_start", start)
        total = np.empty(nf, np.int32)
        mesh.polygons.foreach_get("loop_total", total)
        attributes = sorted(
            [a.name, a.domain, a.data_type] for a in mesh.attributes if not a.name.startswith(".")
        )
    finally:
        bpy.data.meshes.remove(mesh)
    world = obj.matrix_world
    arrays = donor_arrays(
        co,
        lt,
        lv,
        uv,
        cn,
        lining,
        np.array(world.to_3x3(), np.float64),
        np.array(world.translation),
        np.array(world.to_3x3().inverted().transposed(), np.float64),
    )
    faces = {"face_loop_start": start, "face_loop_total": total}
    matrix = [list(row) for row in world]
    info = {
        "vertices": nv,
        "loops": nl,
        "polygons": nf,
        "loop_triangles": len(lt) // 3,
        "attributes": attributes,
        "matrix_world": matrix,
        "matrix_is_identity": all(
            value == (1.0 if i == j else 0.0)
            for i, row in enumerate(matrix)
            for j, value in enumerate(row)
        ),
        "modifiers": [[m.name, m.type] for m in obj.modifiers],
        "materials": [s.material.name if s.material else None for s in obj.material_slots],
        "depsgraph_mode": depsgraph.mode,
    }
    return arrays, faces, info


def _redelivered_normals(bpy: Any, obj: Any) -> Any:
    """`deliver.py`'s Low-Game construction (`DELIVER_SHA256`, lines 14-25), replayed on the
    Authoring low: per loop triangle a polygon in order, the evaluated corner normals set as
    custom normals per loop, then read back. Its corner normals per triangle corner, float32.
    If the Authoring low is the one Low-Game was built from, through the same conversion, they
    equal Low-Game's normals bit for bit; no tolerance is involved."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    me = evaluated.to_mesh()
    copy = None
    try:
        me.calc_loop_triangles()
        co = np.array([obj.matrix_world @ v.co for v in me.vertices])
        tris = [tuple(t.vertices) for t in me.loop_triangles]
        loops = [tuple(t.loops) for t in me.loop_triangles]
        uv = np.array([d.uv[:] for d in me.uv_layers.active.data])
        cn = np.array([c.vector[:] for c in me.corner_normals])
        copy = bpy.data.meshes.new(REDELIVERED_MESH)
        copy.from_pydata(co.tolist(), [], tris)
        copy.update()
        layer = copy.uv_layers.new(name=UV_MAP)
        for polygon, corner_loops in zip(copy.polygons, loops, strict=True):
            for target, source in zip(polygon.loop_indices, corner_loops, strict=True):
                layer.data[target].uv = uv[source]
        copy.polygons.foreach_set("use_smooth", [True] * len(copy.polygons))
        copy.normals_split_custom_set([tuple(cn[source]) for lt in loops for source in lt])
        if [tuple(p.loop_indices) for p in copy.polygons] != [
            (3 * k, 3 * k + 1, 3 * k + 2) for k in range(len(tris))
        ]:
            raise ExtractError("the re-delivered copy's loops are not one per triangle corner")
        normals = np.empty(len(copy.loops) * 3, np.float32)
        copy.corner_normals.foreach_get("vector", normals)
    finally:
        evaluated.to_mesh_clear()
        if copy is not None:
            bpy.data.meshes.remove(copy)
    return normals.reshape(-1, 3)


def _blender(bpy: Any) -> dict[str, Any]:
    return {
        "version": list(bpy.app.version),
        "version_string": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode("ascii", "replace"),
        "build_branch": bpy.app.build_branch.decode("ascii", "replace"),
        "file_version": list(bpy.data.version),
        "numpy": np.__version__,
    }


def _extract(bpy: Any, run_dir: Path, opened: Path) -> None:
    obj, visibility = _low(bpy)
    arrays, faces, info = _read_low(bpy, obj)
    redelivered = _redelivered_normals(bpy, obj)
    np.save(run_dir / REDELIVERED_NAME, redelivered, allow_pickle=False)
    for name, array in arrays.items():
        np.save(run_dir / f"low.{name}.npy", array, allow_pickle=False)
    for name, array in faces.items():
        np.save(run_dir / f"authoring.{name}.npy", array, allow_pickle=False)
    write_json(
        run_dir / EXTRACT_REPORT,
        {
            "extractor": EXTRACTOR,
            "mode": "extract",
            "blender": _blender(bpy),
            "blend": str(opened),
            "object": {"name": obj.name, "visibility_as_found": visibility, **info},
            "part_attribute": [PART_ATTRIBUTE, PART_DOMAIN, PART_TYPE],
            "uv_map": UV_MAP,
            "digests": {name: array_digest(a) for name, a in {**arrays, **faces}.items()},
            "redelivered": {
                "donor": DELIVER_PATH,
                "donor_sha256": DELIVER_SHA256,
                "digest": array_digest(redelivered),
            },
        },
    )


def _show_everything(bpy: Any) -> None:
    """The donor's `show_everything`: every collection shown and included."""

    def visit(layer_collection: Any) -> None:
        layer_collection.exclude = False
        layer_collection.hide_viewport = False
        for child in layer_collection.children:
            visit(child)

    for collection in bpy.data.collections:
        collection.hide_render = False
        collection.hide_viewport = False
    visit(bpy.context.view_layer.layer_collection)


def _ao(bpy: Any, run_dir: Path, opened: Path) -> None:
    expect = json.loads((run_dir / AO_EXPECT).read_text(encoding="utf-8"))["low_digests"]
    scene = bpy.context.scene
    low, low_visibility = _low(bpy)
    high = bpy.data.objects.get(HIGH_OBJECT)
    if high is None or high.type != "MESH":
        raise ExtractError(f"no MESH object {HIGH_OBJECT!r}")
    materials = list(low.data.materials)
    if not materials or any(m is None or m.node_tree is None for m in materials):
        raise ExtractError("every material slot of the low needs a node tree to bake into")
    world = scene.world
    as_found = {
        "engine": scene.render.engine,
        "cycles": {name: _plain(getattr(scene.cycles, name, None)) for name in CYCLES_SETTINGS},
        "cycles_unpinned": {
            name: _plain(getattr(scene.cycles, name, None)) for name in CYCLES_AS_FOUND
        },
        "bake": {
            name: _plain(getattr(scene.render.bake, name, None))
            for name in (
                "margin",
                "margin_type",
                "use_clear",
                "cage_extrusion",
                "max_ray_distance",
                "view_from",
            )
        },
        "world": None
        if world is None
        else {"name": world.name, "ao_distance": world.light_settings.distance},
        "threads_mode": scene.render.threads_mode,
        "threads": scene.render.threads,
        "compute_device_type": bpy.context.preferences.addons[
            "cycles"
        ].preferences.compute_device_type,
        "objects": sorted([o.name, o.type, *_visibility(o).values()] for o in scene.objects),
        "low_visibility": low_visibility,
        "high_visibility": _visibility(high),
    }
    _show_everything(bpy)
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.hide_render = obj not in (low, high)
    for obj in (low, high):
        obj.hide_viewport = False
        obj.hide_set(False)
    image = bpy.data.images.new(
        AO_IMAGE, AO_RESOLUTION, AO_RESOLUTION, alpha=False, float_buffer=True
    )
    image.colorspace_settings.name = AO_COLORSPACE
    for material in materials:
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        material.node_tree.nodes.active = node
    scene.render.engine = "CYCLES"
    for name, value in CYCLES_SETTINGS.items():
        setattr(scene.cycles, name, value)
    for name in SCENE_OR_OPERATOR_OPTIONS:
        setattr(scene.render.bake, name, BAKE_OPTIONS[name])
    applied = {name: _plain(getattr(scene.cycles, name)) for name in CYCLES_SETTINGS}
    problems = settings_problems(applied, CYCLES_SETTINGS, "cycles")
    problems += [
        f"scene bake {name} reads back {getattr(scene.render.bake, name)!r}"
        for name in SCENE_OR_OPERATOR_OPTIONS
        if getattr(scene.render.bake, name) != BAKE_OPTIONS[name]
    ]
    available = [p.identifier for p in bpy.ops.object.bake.get_rna_type().properties]
    pins = operator_pins(available)
    problems += option_problems(available, pins)
    if scene.render.engine != "CYCLES":
        problems.append(f"the render engine is {scene.render.engine}, not CYCLES")
    if problems:
        raise ExtractError("; ".join(problems))
    # The low is read again in its final bake visibility, just before the bake, so the geometry
    # checked against the accepted extraction is the geometry that is baked.
    arrays, faces, info = _read_low(bpy, low)
    found = {name: array_digest(a) for name, a in {**arrays, **faces}.items()}
    if found != expect:
        differ = sorted(k for k in set(found) | set(expect) if found.get(k) != expect.get(k))
        raise ExtractError(f"the low differs from the accepted extraction in {differ}; no bake")
    # The digests are of the viewport evaluation; with no modifier on the low, the render
    # evaluation the bake may use is the same mesh. A modifier would make that unproven.
    if len(low.modifiers):
        raise ExtractError(f"{LOW_OBJECT} has modifiers; its baked geometry is not proven")
    view_layer = bpy.context.view_layer
    for obj in view_layer.objects:
        obj.select_set(False)
    high.select_set(True)
    low.select_set(True)
    view_layer.objects.active = low
    call = bake_call_options(pins)
    readback_before = _last_properties(bpy, "object.bake", pins)
    result = bpy.ops.object.bake(**call)
    if set(result) != {"FINISHED"}:
        raise ExtractError(f"object.bake returned {sorted(result)}")
    readback = _last_properties(bpy, "object.bake", pins)
    pixels = np.empty(AO_RESOLUTION * AO_RESOLUTION * 4, np.float32)
    image.pixels.foreach_get(pixels)
    red = pixels[0::4]
    if not np.isfinite(red).all() or red.min() < 0 or red.max() > 1:
        raise ExtractError("the baked AO holds values outside [0, 1] before float16")
    ao = ao_array(pixels, AO_RESOLUTION)
    np.save(run_dir / AO_NAME, ao, allow_pickle=False)
    rgba = pixels.reshape(-1, 4)
    write_json(
        run_dir / AO_REPORT,
        {
            "extractor": EXTRACTOR,
            "mode": "ao",
            "blender": _blender(bpy),
            "blend": str(opened),
            "low": {"name": low.name, **info, "digests": found},
            "high": {
                "name": high.name,
                "vertices": len(high.data.vertices),
                "polygons": len(high.data.polygons),
                "modifiers": [
                    [m.name, m.type, bool(m.show_viewport), bool(m.show_render)]
                    for m in high.modifiers
                ],
                "matrix_world": [list(row) for row in high.matrix_world],
            },
            "as_found": as_found,
            "cycles_applied": applied,
            "bake_options": BAKE_OPTIONS,
            "operator_options": sorted(pins),
            "operator_call": {name: _plain(value) for name, value in call.items()},
            "bake_readback_before": readback_before,
            "bake_readback": readback,
            "bake_options_used": readback["used"],
            "scene_bake_after": {
                name: _plain(getattr(scene.render.bake, name, None)) for name in BAKE_OPTIONS
            },
            "image": {
                "name": image.name,
                "colorspace": image.colorspace_settings.name,
                "size": list(image.size),
            },
            "pixels": {
                "finite": bool(np.isfinite(rgba).all()),
                "rgb_equal": bool(
                    (rgba[:, 0] == rgba[:, 1]).all() and (rgba[:, 0] == rgba[:, 2]).all()
                ),
                "min": float(rgba[:, 0].min()),
                "max": float(rgba[:, 0].max()),
                "mean": float(rgba[:, 0].mean()),
            },
            "digest": array_digest(ao),
        },
    )


def readback_state(
    names: Iterable[str],
    values: Mapping[str, Any] | None,
    is_set: Mapping[str, Any] | None,
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    """What `operator_properties_last` says about a call, for exactly the option `names` passed.

    Two kinds: `none` (the API returned no properties) and `populated` (values, `is_property_set`
    flags and RNA defaults, each covering exactly `names`, every flag a bool; anything less
    refuses). Status `unavailable` means Blender kept no call state: kind `none`, or populated
    with no property set and every value its default, the pattern `control` mode measures before
    and after a call. Any set property or non-default value is a `readback` and its values are
    `used`, so a real disagreement is compared, never relabelled. Whether retention is really
    unavailable in the pinned Blender is the control's to show, not this function's."""
    wanted = sorted(names)
    if not wanted:
        raise ExtractError("a readback needs the names of the options passed")
    if sorted(defaults) != wanted:
        raise ExtractError("the readback's defaults do not cover exactly the options passed")
    if values is None:
        if is_set is not None:
            raise ExtractError("a `none` readback carries no is_property_set flags")
        kind, unavailable = "none", True
    else:
        if is_set is None or sorted(values) != wanted or sorted(is_set) != wanted:
            raise ExtractError("the readback does not cover exactly the options passed")
        if not all(isinstance(flag, bool) for flag in is_set.values()):
            raise ExtractError("an is_property_set flag is not a bool")
        kind = "populated"
        unavailable = not any(is_set.values()) and all(
            values[name] == defaults[name] for name in wanted
        )
    return {
        "kind": kind,
        "names": wanted,
        "status": "unavailable" if unavailable else "readback",
        "values": None if values is None else {name: values[name] for name in wanted},
        "set": None if is_set is None else {name: is_set[name] for name in wanted},
        "defaults": {name: defaults[name] for name in wanted},
        "used": None if unavailable or values is None else {n: values[n] for n in wanted},
    }


def _rna_default(prop: Any) -> Any:
    if prop.type == "ENUM":
        return sorted(prop.default_flag) if prop.is_enum_flag else prop.default
    if getattr(prop, "is_array", False):
        return list(prop.default_array)
    return getattr(prop, "default", None)


def _last_properties(bpy: Any, operator: str, names: Iterable[str]) -> dict[str, Any]:
    """`operator_properties_last(operator)` for the passed names, with `is_property_set` and the
    operator's RNA defaults, classified by `readback_state`."""
    names = list(names)
    module, name = operator.split(".")
    rna = getattr(getattr(bpy.ops, module), name).get_rna_type().properties
    defaults = {n: _plain(_rna_default(rna[n])) for n in names}
    last = bpy.context.window_manager.operator_properties_last(operator)
    if last is None:
        return readback_state(names, None, None, defaults)
    values = {n: _plain(getattr(last, n, None)) for n in names}
    is_set = {n: bool(last.is_property_set(n)) for n in names}
    return readback_state(names, values, is_set, defaults)


def _plain(value: Any) -> Any:
    """A JSON-safe copy of an RNA value (enums are strings, sets become sorted lists, sequences
    such as RNA arrays and vectors lists)."""
    if isinstance(value, set | frozenset):
        return sorted(value)
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    try:
        return [_plain(v) for v in value]
    except TypeError:
        return str(value)


# The control: a simple operator whose effect shows the call applied, then a tiny AO bake on a
# factory plane (unoccluded, so AO is 1.0 where baked; the default COMBINED would give the dim
# factory world instead). Each call's readback is taken before and after it.
CONTROL_REPORT = "control-report.json"
CONTROL_CUBE: dict[str, Any] = {"size": 3.0, "location": [1.0, 2.0, 3.0]}
CONTROL_BAKE: dict[str, Any] = {
    "type": "AO",
    "width": AO_RESOLUTION,
    "height": AO_RESOLUTION,
    "margin": 8,
    "margin_type": "ADJACENT_FACES",
    "max_ray_distance": 0.014,
    "cage_extrusion": 0.006,
    "use_clear": True,
    "uv_layer": UV_MAP,
}
CONTROL_IMAGE = 32


def _control(bpy: Any, run_dir: Path) -> None:
    """`operator_properties_last` before and after two background Python calls (EXEC_DEFAULT,
    as the AO bake is called), with each call's observable effect."""
    report: dict[str, Any] = {"extractor": EXTRACTOR, "mode": "control", "blender": _blender(bpy)}
    before = _last_properties(bpy, "mesh.primitive_cube_add", CONTROL_CUBE)
    result = bpy.ops.mesh.primitive_cube_add("EXEC_DEFAULT", **CONTROL_CUBE)
    after = _last_properties(bpy, "mesh.primitive_cube_add", CONTROL_CUBE)
    cube = bpy.context.view_layer.objects.active
    report["cube"] = {
        "call": CONTROL_CUBE,
        "result": sorted(result),
        "before": before,
        "after": after,
        "effect": {"dimensions": _plain(cube.dimensions), "location": _plain(cube.location)},
    }
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    bpy.ops.mesh.primitive_plane_add("EXEC_DEFAULT", size=1.0)
    plane = bpy.context.view_layer.objects.active
    material = bpy.data.materials.new("uzp_control")
    if material.node_tree is None:
        material.use_nodes = True
    image = bpy.data.images.new(
        "uzp_control_bake", CONTROL_IMAGE, CONTROL_IMAGE, alpha=False, float_buffer=True
    )
    image.colorspace_settings.name = AO_COLORSPACE
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    material.node_tree.nodes.active = node
    plane.data.materials.append(material)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj == plane)
    before = _last_properties(bpy, "object.bake", CONTROL_BAKE)
    result = bpy.ops.object.bake("EXEC_DEFAULT", **CONTROL_BAKE)
    after = _last_properties(bpy, "object.bake", CONTROL_BAKE)
    pixels = np.empty(CONTROL_IMAGE * CONTROL_IMAGE * 4, np.float32)
    image.pixels.foreach_get(pixels)
    red = pixels[0::4]
    report["bake"] = {
        "call": CONTROL_BAKE,
        "result": sorted(result),
        "before": before,
        "after": after,
        "effect": {"min": float(red.min()), "max": float(red.max())},
    }
    write_json(run_dir / CONTROL_REPORT, report)


def main(argv: Sequence[str]) -> None:
    import bpy  # type: ignore[import-not-found]

    if "--" not in argv or len(argv) != argv.index("--") + 3:
        raise ExtractError("usage: blender ... --python sash_intermediates_blender.py -- MODE DIR")
    mode, run = argv[argv.index("--") + 1 :]
    run_dir = Path(run).resolve()
    if tuple(bpy.app.version[:2]) != BLENDER_VERSION:
        raise ExtractError(f"Blender {bpy.app.version_string}, pinned {BLENDER_VERSION}")
    opened = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if mode == "control":
        if opened is not None:
            raise ExtractError(f"the control runs on the factory scene, not on {opened}")
        _control(bpy, run_dir)
        return
    if opened is None or opened != run_dir / SOURCE_BLEND_NAME:
        raise ExtractError(f"the open file is {opened}, not {run_dir / SOURCE_BLEND_NAME}")
    if mode == "extract":
        _extract(bpy, run_dir, opened)
    elif mode == "ao":
        _ao(bpy, run_dir, opened)
    else:
        raise ExtractError(f"mode {mode!r} is not extract, ao or control")


if __name__ == "__main__":
    main(sys.argv)
