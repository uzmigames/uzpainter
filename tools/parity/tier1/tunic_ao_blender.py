"""Blender side of the Tunic v10 AO substitute and its readback control (decision 300 s. 7).

Blender only. `tools.parity.tier1.tunic_ao` builds the command, on a hash-checked, read-only
private copy of the preserved `.blend`, writes the donor's raw blob into the run directory, and
checks everything this script and the donor write. Never run it on the Assets3D original:

    blender --background --factory-startup --disable-autoexec --offline-mode -noaudio
        <run dir>/18-Tunica-v10.blend --python-exit-code 1
        --python tools/parity/tier1/tunic_ao_blender.py -- ao <run dir>
    blender --background --factory-startup --disable-autoexec --offline-mode -noaudio
        --python-exit-code 1 --python tools/parity/tier1/tunic_ao_blender.py -- control <run dir>

**ao** executes the donor, Assets3D `garment_blender_io.py` (`DONOR_FILE`, the raw LF blob
`DONOR_BLOB_SHA256`, re-hashed here before it runs), unchanged, as a script, with the contract's
arguments (`DONOR_ARGS`): `extract --low-object 18-Tunica-Low --lining-attribute LiningMask
--normal-image Source_v6_HighNormal --high-object 18-Tunica-High-OriginalFit --ao-resolution
2048 --ao-samples 96 --cage 0.006 --max-ray 0.014`, writing into `<run dir>/donor`. Its `ao.npy`
is a NEW AO substitute, not the lost historical AO. This script only observes around it; it sets
no setting and passes no argument of its own:

1. **Before the donor.** The low as front U3 pinned it (`tunic_low_blender.source_problems`), its
   material slots' node trees, the High (`high_problems`: a mesh with no modifier, constraint or
   shape key, the identity matrix and the inspection's counts), no image already named as the
   donor's bake image (`AO_IMAGE`, so the image observed is the one the donor creates), and the
   packed Normal's bytes and settings, with its buffer not yet loaded. The low is read the
   donor's way with U3's own code, and every array's digest must equal front U3's accepted
   record (`ao-expect.json`).
2. **The bake, observed.** `bpy.ops.object` is replaced, while the donor runs, by a proxy whose
   `bake` is `ObservedBake`: it records the donor's exact arguments and refuses any other than
   `BAKE_CALL`, and any second bake. Before it calls the real operator it reads the low again in
   the donor's bake state (after `show_everything`, `hide_render`, `hide_set`), which must still
   equal U3's record, and the device: all three of `device_problems` must hold, since the donor's
   `use_gpu` swallows its errors (`scene.cycles.device` is `GPU`, the compute type is `OPTIX`,
   and the enabled devices are exactly the one pinned OptiX GPU, so CUDA, a CPU fallback or a
   hybrid refuses). It records every setting the donor leaves as found (`scene_state`) and
   Blender's `operator_properties_last` before and after. After the operator it checks the device
   again, and checks the baked float32 R channel before any cast: finite and in [0, 1], never
   clipped.
3. **After the donor.** The Normal's settings and loaded state must still be the pins, and the
   donor's `ao.npy` must be the float16 cast of the values checked in the bake (its digest).

**control** (factory scene, no file opened). Whether this Blender keeps the last-used properties
of a background Python call: a cube add, then a lone-plane AO bake called with the real bake's
five keyword names (`CONTROL_BAKE`) after the donor's own `use_gpu` (the blob loaded as a module,
not run). It shows only whether keyword arguments are retained; it proves neither the device nor
the bake's quality.

The low's read and the Normal's pins are front U3's `tunic_low_blender.py`, the bytes that made
the accepted arrays; the readback is front P's `sash_intermediates_blender.py`. Both are loaded
from this file's folder (`HELPERS`); the host pins their SHA-256, and this script records the
hashes of what it loaded. Nothing is saved but what the donor writes into `<run dir>/donor`.
Everything above `main` is plain Python and numpy, so the host and the tests import it without
Blender.
"""

from __future__ import annotations

import hashlib
import json
import sys
import types
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

EXTRACTOR = "uzpainter/parity/tunic-ao/1"
DONOR_PATH = "Pipeline/painting/garment_blender_io.py"
DONOR_BLOB_SHA256 = "805f9ccc5430e47ac49c4b50651e271b2e6da68f8455fa231306f3462b0c8a4d"
DONOR_FILE = "garment_blender_io.py"  # the raw blob, written into the run directory by the host
DONOR_OUT = "donor"  # the donor's --out, inside the run directory
BLENDER_VERSION = (5, 2)
DEPSGRAPH_MODE = "VIEWPORT"  # the donor's background `evaluated_depsgraph_get()`

# Blender runs this file by path, without the repository on `sys.path`; the host checks that
# these names match its own pins.
SOURCE_BLEND_NAME = "18-Tunica-v10.blend"
LOW_OBJECT = "18-Tunica-Low"
HIGH_OBJECT = "18-Tunica-High-OriginalFit"
HIGH_VERTICES = 726_509  # the inspection (report 61ec5736...): authored and evaluated agree
HIGH_TRIANGLES = 1_453_234  # every polygon a triangle
NORMAL_IMAGE = "Source_v6_HighNormal"
LINING_ATTRIBUTE = "LiningMask"
HELPERS = {
    "low": "tunic_low_blender.py",  # front U3: read_mesh, donor_arrays, the Normal's pins
    "readback": "sash_intermediates_blender.py",  # front P: operator_properties_last
}

# The contract's arguments (its "Generator intermediates" table); they equal the donor's defaults.
AO_RESOLUTION = 2048
AO_SAMPLES = 96
DONOR_ARGS = (
    "extract",
    "--low-object",
    LOW_OBJECT,
    "--lining-attribute",
    LINING_ATTRIBUTE,
    "--normal-image",
    NORMAL_IMAGE,
    "--high-object",
    HIGH_OBJECT,
    "--ao-resolution",
    str(AO_RESOLUTION),
    "--ao-samples",
    str(AO_SAMPLES),
    "--cage",
    "0.006",
    "--max-ray",
    "0.014",
)
AO_IMAGE = "garment_ao_bake"  # the donor's bake image
AO_COLORSPACE = "Non-Color"
# What the donor passes `object.bake` with those arguments, and nothing else.
BAKE_CALL: dict[str, Any] = {
    "type": "AO",
    "use_selected_to_active": True,
    "max_ray_distance": 0.014,
    "cage_extrusion": 0.006,
    "margin": 8,
}
# What the donor's `use_gpu` must have achieved.
COMPUTE_DEVICE_TYPE = "OPTIX"
SCENE_DEVICE = "GPU"
GPU_NAME = "NVIDIA GeForce RTX 4090"  # the one enabled device, as Blender names it
ENABLED_DEVICES = ((GPU_NAME, COMPUTE_DEVICE_TYPE),)

AO_EXPECT = "ao-expect.json"
AO_REPORT = "ao-report.json"
AO_NAME = "ao.npy"
DONOR_OUTPUTS = frozenset({"low.npz", "highnormal.npy", AO_NAME, "extract_report.json"})
LOW_DIGESTS = ("co", "lt", "lv", "uv", "cn", "lining", "evaluated_cn")

CONTROL_REPORT = "control-report.json"
CONTROL_CUBE: dict[str, Any] = {"size": 3.0, "location": [1.0, 2.0, 3.0]}
# The real bake's five names; a lone plane bakes onto itself (AO 1.0 where baked).
CONTROL_BAKE: dict[str, Any] = {**BAKE_CALL, "use_selected_to_active": False}
CONTROL_IMAGE = 32


class AoError(Exception):
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


def plain(value: Any) -> Any:
    """A JSON-safe copy of an RNA value: sets sorted, sequences lists."""
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


def rna_values(struct: Any) -> dict[str, Any]:
    """Every RNA property of a settings struct but its collections; pointers by name."""
    found: dict[str, Any] = {}
    for prop in struct.bl_rna.properties:
        name = prop.identifier
        if name == "rna_type" or prop.type == "COLLECTION":
            continue
        try:
            value = getattr(struct, name)
        except (AttributeError, RuntimeError) as error:
            found[name] = f"<unreadable: {error}>"
            continue
        if prop.type == "POINTER":
            found[name] = None if value is None else getattr(value, "name", type(value).__name__)
        else:
            found[name] = plain(value)
    return found


def device_state(scene: Any, preferences: Any) -> dict[str, Any]:
    """The device Cycles will use: the scene's device, the compute type and every device."""
    return {
        "scene_device": scene.cycles.device,
        "compute_device_type": preferences.compute_device_type,
        "devices": [[d.name, d.id, d.type, bool(d.use)] for d in preferences.devices],
    }


def device_problems(state: Mapping[str, Any]) -> list[str]:
    """Effective OptiX on the pinned GPU: all three, or a refusal (a `GPU` string alone would
    also accept CUDA or a hybrid with the CPU)."""
    try:
        problems = []
        if state["scene_device"] != SCENE_DEVICE:
            problems.append(f"scene.cycles.device is {state['scene_device']!r}, not {SCENE_DEVICE}")
        if state["compute_device_type"] != COMPUTE_DEVICE_TYPE:
            problems.append(
                f"the compute device type is {state['compute_device_type']!r}, "
                f"not {COMPUTE_DEVICE_TYPE}"
            )
        enabled = tuple((name, kind) for name, _, kind, use in state["devices"] if use is True)
        if enabled != ENABLED_DEVICES:
            problems.append(f"the enabled devices are {list(enabled)}, pinned {ENABLED_DEVICES}")
    except (KeyError, TypeError, ValueError) as error:
        return [f"the device state cannot be read ({type(error).__name__}: {error})"]
    return problems


def high_problems(obj: Any) -> list[str]:
    """The High against the inspection: a plain mesh in world space at the pinned counts."""
    if obj is None or obj.type != "MESH":
        return [f"no MESH object {HIGH_OBJECT!r}"]
    problems = []
    if len(obj.modifiers) or len(obj.constraints):
        problems.append(f"{HIGH_OBJECT} has modifiers or constraints")
    if obj.data.shape_keys is not None:
        problems.append(f"{HIGH_OBJECT} has shape keys")
    rows = [list(row) for row in obj.matrix_world]
    if rows != [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]:
        problems.append(f"{HIGH_OBJECT}'s world matrix is not the identity")
    counts = (len(obj.data.vertices), len(obj.data.polygons))
    if counts != (HIGH_VERTICES, HIGH_TRIANGLES):
        problems.append(f"{HIGH_OBJECT} has {counts}, pinned {(HIGH_VERTICES, HIGH_TRIANGLES)}")
    return problems


def high_digests(mesh: Any) -> dict[str, str]:
    """The High's positions and corner vertices; every polygon must be a triangle."""
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    totals = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_total", totals)
    if (totals != 3).any():
        raise AoError(
            f"{HIGH_OBJECT} has {int((totals != 3).sum())} polygons that are not triangles"
        )
    corners = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", corners)
    return {"co": array_digest(co.reshape(-1, 3)), "corners": array_digest(corners.reshape(-1, 3))}


def digest_problems(found: Mapping[str, str], expected: Mapping[str, str], what: str) -> list[str]:
    differ = sorted(k for k in set(found) | set(expected) if found.get(k) != expected.get(k))
    return [f"{what} differs from front U3's accepted record in {differ}"] if differ else []


def call_problems(args: Sequence[Any], kwargs: Mapping[str, Any], calls: int) -> list[str]:
    """The donor's `object.bake` call against the contract's: once, keywords only, exactly."""
    problems = []
    if calls != 1:
        problems.append(f"this is object.bake call {calls}; the donor bakes once")
    if args:
        problems.append(f"object.bake was given positional arguments {list(map(plain, args))}")
    if dict(kwargs) != BAKE_CALL or any(
        type(kwargs[k]) is not type(v) for k, v in BAKE_CALL.items()
    ):
        problems.append(f"object.bake was called with {plain(dict(kwargs))}, pinned {BAKE_CALL}")
    return problems


def donor_argv(donor_path: Path, run_dir: Path) -> list[str]:
    """The donor's `sys.argv` as Blender would give it: everything after `--` is its command."""
    command, *options = DONOR_ARGS
    return [str(donor_path), "--", command, "--out", str(run_dir / DONOR_OUT), *options]


def ao_values(pixels: Any, resolution: int) -> tuple[Any, list[str]]:
    """The donor's `ao.npy` (channel R, rows bottom first, float16) and the problems of its
    float32 values before the cast: finite and in [0, 1], never clipped."""
    red = np.asarray(pixels, np.float32).reshape(resolution, resolution, 4)[..., 0]
    problems = []
    if not np.isfinite(red).all():
        problems.append("the baked AO holds non-finite values")
    elif red.min() < 0 or red.max() > 1:
        problems.append(f"the baked AO spans [{red.min()}, {red.max()}], outside [0, 1]")
    return red.astype(np.float16), problems


def pixel_summary(pixels: Any) -> dict[str, Any]:
    rgba = np.asarray(pixels, np.float32).reshape(-1, 4)
    red = rgba[:, 0]
    finite = bool(np.isfinite(red).all())
    return {
        "finite": finite,
        "in_unit_range": finite and bool(red.min() >= 0 and red.max() <= 1),
        "min": float(red.min()),
        "max": float(red.max()),
        "mean": float(red.mean(dtype=np.float64)),
        "rgb_equal": bool((rgba[:, 0] == rgba[:, 1]).all() and (rgba[:, 0] == rgba[:, 2]).all()),
    }


def load_module(path: Path, name: str, pinned: str | None = None) -> tuple[Any, str]:
    """A module executed from its file's bytes (refused off its pin), with their SHA-256."""
    data = path.read_bytes()
    found = hashlib.sha256(data).hexdigest()
    if pinned is not None and found != pinned:
        raise AoError(f"{path} has SHA-256 {found}, pinned {pinned}")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(data, str(path), "exec"), module.__dict__)
    return module, found


def load_helpers(here: Path) -> tuple[dict[str, Any], dict[str, str]]:
    modules, hashes = {}, {}
    for key, name in HELPERS.items():
        modules[key], hashes[key] = load_module(here / name, f"uzp_{Path(name).stem}")
    return modules, hashes


class ObservedBake:
    """`object.bake` while the donor runs: `before` checks and records, then the real operator,
    then `after`. Attribute reads (`get_rna_type`, ...) go to the real operator."""

    def __init__(
        self,
        real: Any,
        before: Callable[[Sequence[Any], Mapping[str, Any], int], None],
        after: Callable[[Any], None],
    ) -> None:
        self._real, self._before, self._after = real, before, after
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self._before(args, kwargs, self.calls)
        result = self._real(*args, **kwargs)
        self._after(result)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class ObjectOps:
    """`bpy.ops.object` with `bake` observed; every other operator is the real one."""

    def __init__(self, real: Any, bake: ObservedBake) -> None:
        self._real, self.bake = real, bake

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


# --------------------------------------------------------------------------------- Blender
def _blender(bpy: Any) -> dict[str, Any]:
    return {
        "version": list(bpy.app.version),
        "version_string": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode("ascii", "replace"),
        "build_branch": bpy.app.build_branch.decode("ascii", "replace"),
        "file_version": list(bpy.data.version),
        "numpy": np.__version__,
    }


def _preferences(bpy: Any) -> Any:
    return bpy.context.preferences.addons["cycles"].preferences


def scene_state(bpy: Any) -> dict[str, Any]:
    """Every setting the bake may read that the donor leaves as found, and the device."""
    scene = bpy.context.scene
    world = scene.world
    view_layer = bpy.context.view_layer
    return {
        "engine": scene.render.engine,
        "cycles": rna_values(scene.cycles),
        "bake": rna_values(scene.render.bake),
        "bake_image_settings": rna_values(scene.render.bake.image_settings),
        "render": {
            "threads_mode": scene.render.threads_mode,
            "threads": int(scene.render.threads),
            "use_persistent_data": bool(scene.render.use_persistent_data),
        },
        "view_layer": {"name": view_layer.name, "cycles": rna_values(view_layer.cycles)},
        "world": None
        if world is None
        else {"name": world.name, "light_settings": rna_values(world.light_settings)},
        "device": device_state(scene, _preferences(bpy)),
    }


def _visibility(obj: Any) -> dict[str, Any]:
    try:
        hidden: bool | None = bool(obj.hide_get())
    except RuntimeError:  # not in the view layer
        hidden = None
    return {
        "hide_get": hidden,
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "selected": bool(obj.select_get()) if hidden is not None else None,
    }


def _read_low(bpy: Any, low_side: Any, obj: Any) -> dict[str, str]:
    """The donor's read of the evaluated low with U3's code: the digests U3 recorded."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if depsgraph.mode != DEPSGRAPH_MODE:
        raise AoError(f"depsgraph mode is {depsgraph.mode}, pinned {DEPSGRAPH_MODE}")
    mesh = bpy.data.meshes.new_from_object(
        obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph
    )
    try:
        mesh.calc_loop_triangles()
        raw = low_side.read_mesh(mesh)
        nv = len(mesh.vertices)
        lining = low_side.lining_values(mesh.attributes.get(low_side.LINING_ATTRIBUTE), nv)
        problems = low_side.triangulation_problems(raw["lt"], raw["loop_total"], nv)
        if not problems:
            problems = low_side.lining_problems(lining, nv, raw["lv"][raw["lt"]])
        if problems:
            raise AoError("; ".join(problems))
    finally:
        bpy.data.meshes.remove(mesh)
    world = obj.matrix_world
    arrays = low_side.donor_arrays(
        raw,
        lining,
        np.array(world.to_3x3(), np.float64),
        np.array(world.translation),
        np.array(world.to_3x3().inverted().transposed(), np.float64),
    )
    digests = {name: array_digest(a) for name, a in arrays.items()}
    digests["evaluated_cn"] = array_digest(raw["cn"].reshape(-1, 3))
    return digests


def _pins(bpy: Any, low_side: Any) -> tuple[Any, Any, dict[str, Any]]:
    """The low, the High and the packed Normal against their pins, before the donor runs."""
    view_layer = bpy.context.view_layer
    low = bpy.data.objects.get(LOW_OBJECT)
    if low is None or view_layer.objects.get(LOW_OBJECT) is None:
        raise AoError(f"no object {LOW_OBJECT!r} in the view layer")
    high = bpy.data.objects.get(HIGH_OBJECT)
    problems = low_side.source_problems(low) + high_problems(high)
    materials = list(low.data.materials)
    if not materials or any(m is None or m.node_tree is None for m in materials):
        problems.append("every material of the low needs a node tree to bake into")
    # The donor creates its bake image by this name; an image already holding it would make the
    # donor's one `.001` and the observation read the wrong image.
    if bpy.data.images.get(AO_IMAGE) is not None:
        problems.append(f"the file already holds an image named {AO_IMAGE!r}")
    image = bpy.data.images.get(NORMAL_IMAGE)
    normal: dict[str, Any] = {"image": NORMAL_IMAGE}
    if image is None:
        problems.append(f"no image {NORMAL_IMAGE!r}")
    else:
        packed = image.packed_file
        normal["packed"] = None if packed is None else low_side.packed_identity(bytes(packed.data))
        normal["settings"] = low_side.image_settings(image)
        problems += low_side.normal_problems(normal["packed"], normal["settings"])
    if problems:
        raise AoError("; ".join(problems))
    return low, high, normal


def _ao(bpy: Any, run_dir: Path, opened: Path, helpers: Mapping[str, Any], hashes: Any) -> None:
    expect = json.loads((run_dir / AO_EXPECT).read_text(encoding="utf-8"))
    low_side, readback = helpers["low"], helpers["readback"]
    donor_path = run_dir / DONOR_FILE
    donor_bytes = donor_path.read_bytes()
    if hashlib.sha256(donor_bytes).hexdigest() != DONOR_BLOB_SHA256:
        raise AoError(f"{donor_path} is not the donor's pinned blob")
    scene = bpy.context.scene
    low, high, normal = _pins(bpy, low_side)
    first = _read_low(bpy, low_side, low)
    problems = digest_problems(first, expect["low_digests"], "the low (before the donor)")
    if problems:
        raise AoError("; ".join(problems))
    setup = scene_state(bpy)
    as_found = {"low": _visibility(low), "high": _visibility(high)}
    evidence: dict[str, Any] = {}
    preferences = _preferences(bpy)

    def before(args: Sequence[Any], kwargs: Mapping[str, Any], calls: int) -> None:
        problems = call_problems(args, kwargs, calls)
        evidence["call"] = {name: plain(value) for name, value in kwargs.items()}
        evidence["bake_state_read"] = second = _read_low(bpy, low_side, low)
        problems += digest_problems(second, expect["low_digests"], "the low (in its bake state)")
        evidence["device_before_bake"] = device = device_state(scene, preferences)
        problems += device_problems(device)
        evidence["engine_samples"] = [scene.render.engine, int(scene.cycles.samples)]
        if evidence["engine_samples"] != ["CYCLES", AO_SAMPLES]:
            problems.append(f"the engine and samples are {evidence['engine_samples']}")
        view_layer = bpy.context.view_layer
        evidence["selection"] = {
            "selected": sorted(o.name for o in view_layer.objects if o.select_get()),
            "active": None if view_layer.objects.active is None else view_layer.objects.active.name,
        }
        evidence["visibility"] = {"low": _visibility(low), "high": _visibility(high)}
        evidence["high_digests"] = high_digests(high.data)
        evidence["before_bake"] = scene_state(bpy)
        evidence["readback_before"] = readback._last_properties(bpy, "object.bake", BAKE_CALL)
        if problems:
            raise AoError("; ".join(problems))

    def after(result: Any) -> None:
        evidence["result"] = sorted(result)
        evidence["readback"] = readback._last_properties(bpy, "object.bake", BAKE_CALL)
        evidence["device_after_bake"] = device = device_state(scene, preferences)
        evidence["after_bake"] = scene_state(bpy)
        problems = [f"after the bake: {p}" for p in device_problems(device)]
        if set(result) != {"FINISHED"}:
            problems.append(f"object.bake returned {sorted(result)}")
        image = bpy.data.images.get(AO_IMAGE)
        if image is None or list(image.size) != [AO_RESOLUTION, AO_RESOLUTION]:
            raise AoError("; ".join([*problems, f"no {AO_RESOLUTION}² image {AO_IMAGE!r}"]))
        evidence["image"] = {
            "name": image.name,
            "colorspace": image.colorspace_settings.name,
            "size": list(image.size),
            "is_float": bool(image.is_float),
        }
        pixels = np.empty(AO_RESOLUTION * AO_RESOLUTION * 4, np.float32)
        image.pixels.foreach_get(pixels)
        ao, value_problems = ao_values(pixels, AO_RESOLUTION)
        evidence["pixels"] = pixel_summary(pixels)
        evidence["digest"] = array_digest(ao)
        if problems + value_problems:
            raise AoError("; ".join(problems + value_problems))

    observed = ObservedBake(bpy.ops.object.bake, before, after)
    argv = list(sys.argv)
    bpy.ops.object = ObjectOps(bpy.ops.object, observed)
    sys.argv = donor_argv(donor_path, run_dir)
    try:
        # The blob runs as committed, as a script (`__main__`), from its own bytes.
        code = compile(donor_bytes, str(donor_path), "exec")
        exec(code, {"__name__": "__main__", "__file__": str(donor_path)})
    finally:
        sys.argv = argv
        del bpy.ops.object
    if observed.calls != 1 or "digest" not in evidence:
        raise AoError(f"the donor called object.bake {observed.calls} times")
    image = bpy.data.images[NORMAL_IMAGE]
    normal["after_donor"] = {
        "settings": low_side.image_settings(image),
        "loaded": low_side.image_loaded(image),
    }
    problems = low_side.settings_problems(
        normal["after_donor"]["settings"], low_side.NORMAL_SETTINGS, NORMAL_IMAGE
    )
    problems += low_side.settings_problems(
        normal["after_donor"]["loaded"], low_side.NORMAL_LOADED, NORMAL_IMAGE
    )
    saved = np.load(run_dir / DONOR_OUT / AO_NAME, allow_pickle=False)
    if array_digest(saved) != evidence["digest"]:
        problems.append("the donor's ao.npy is not the float16 cast of the checked bake")
    if problems:
        raise AoError("; ".join(problems))
    write_json(
        run_dir / AO_REPORT,
        {
            "extractor": EXTRACTOR,
            "mode": "ao",
            "blender": _blender(bpy),
            "blend": str(opened),
            "helpers": hashes,
            "donor": {
                "path": DONOR_PATH,
                "blob_sha256": DONOR_BLOB_SHA256,
                "executed": "the raw blob as __main__, unchanged",
                "args": list(DONOR_ARGS),
            },
            "low": {"name": low.name, "first_read": first},
            "normal": normal,
            "high": {
                "name": high.name,
                "vertices": len(high.data.vertices),
                "triangles": len(high.data.polygons),
            },
            "visibility_as_found": as_found,
            "setup": setup,
            "bake": evidence,
        },
    )


def _control(bpy: Any, run_dir: Path, helpers: Mapping[str, Any], hashes: Any) -> None:
    """`operator_properties_last` before and after two background Python calls, with each
    call's observable effect; the bake after the donor's own `use_gpu`."""
    readback = helpers["readback"]
    donor, _ = load_module(run_dir / DONOR_FILE, "garment_blender_io", DONOR_BLOB_SHA256)
    report: dict[str, Any] = {
        "extractor": EXTRACTOR,
        "mode": "control",
        "blender": _blender(bpy),
        "helpers": hashes,
    }
    before = readback._last_properties(bpy, "mesh.primitive_cube_add", CONTROL_CUBE)
    result = bpy.ops.mesh.primitive_cube_add("EXEC_DEFAULT", **CONTROL_CUBE)
    after = readback._last_properties(bpy, "mesh.primitive_cube_add", CONTROL_CUBE)
    cube = bpy.context.view_layer.objects.active
    report["cube"] = {
        "call": CONTROL_CUBE,
        "result": sorted(result),
        "before": before,
        "after": after,
        "effect": {"dimensions": plain(cube.dimensions), "location": plain(cube.location)},
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
    donor.use_gpu(scene)
    scene.cycles.samples = AO_SAMPLES
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj == plane)
    device = device_state(scene, _preferences(bpy))
    before = readback._last_properties(bpy, "object.bake", CONTROL_BAKE)
    result = bpy.ops.object.bake("EXEC_DEFAULT", **CONTROL_BAKE)
    after = readback._last_properties(bpy, "object.bake", CONTROL_BAKE)
    pixels = np.empty(CONTROL_IMAGE * CONTROL_IMAGE * 4, np.float32)
    image.pixels.foreach_get(pixels)
    red = pixels[0::4]
    report["bake"] = {
        "call": CONTROL_BAKE,
        "result": sorted(result),
        "before": before,
        "after": after,
        "device": device,
        "effect": {"min": float(red.min()), "max": float(red.max())},
    }
    write_json(run_dir / CONTROL_REPORT, report)


def main(argv: Sequence[str]) -> None:
    import bpy  # type: ignore[import-not-found]

    if "--" not in argv or len(argv) != argv.index("--") + 3:
        raise AoError("usage: blender ... --python tunic_ao_blender.py -- ao|control DIR")
    mode, run = argv[argv.index("--") + 1 :]
    run_dir = Path(run).resolve()
    if tuple(bpy.app.version[:2]) != BLENDER_VERSION:
        raise AoError(f"Blender {bpy.app.version_string}, pinned {BLENDER_VERSION}")
    helpers, hashes = load_helpers(Path(__file__).resolve().parent)
    opened = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if mode == "control":
        if opened is not None:
            raise AoError(f"the control runs on the factory scene, not on {opened}")
        _control(bpy, run_dir, helpers, hashes)
        return
    if opened is None or opened != run_dir / SOURCE_BLEND_NAME:
        raise AoError(f"the open file is {opened}, not {run_dir / SOURCE_BLEND_NAME}")
    if mode != "ao":
        raise AoError(f"mode {mode!r} is not ao or control")
    _ao(bpy, run_dir, opened, helpers, hashes)


if __name__ == "__main__":
    main(sys.argv)
