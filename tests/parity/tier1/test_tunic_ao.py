"""The Tunic v10 AO substitute's host and Blender-side helpers, with no Blender (decision 300 s. 7).

The "Blender" of the host tests is a Python function that writes what the Blender side and the
donor would write for a two-triangle stand-in low; front U3's accepted records are authored with
the fields its records hold; the donor is a stand-in blob committed to a throwaway git repository
at the donor's Assets3D path, so the host reads it the way it reads Assets3D. Nothing here opens
the Tunic `.blend`, runs Blender or the real donor, queries the real GPU or claims anything
about the real AO.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import numpy as np
import pytest

from tests.parity.tier1.test_sash_intermediates import BAKE_DEFAULTS, unset_readback
from tests.parity.tier1.test_tunic_low_export import source_object
from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import sash_intermediates_blender as readback_side
from tools.parity.tier1 import tunic_ao as host
from tools.parity.tier1 import tunic_ao_blender as side
from tools.parity.tier1 import tunic_low_blender as low_side
from tools.parity.tier1 import tunic_low_export as low_host
from tools.parity.tier1.sash_intermediates import npz_bytes
from tools.parity.tier1.sash_low_export import SourcePin
from tools.parity.tier1.sash_masks import Source, git_blob_id
from tools.parity.tier1.tunic_ao_blender import AoError

Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]
AO_RES = 4
GOOD_DEVICE: dict[str, Any] = {
    "scene_device": "GPU",
    "compute_device_type": "OPTIX",
    "devices": [[side.GPU_NAME, "OPTIX_0000:01:00", "OPTIX", True], ["CPU", "CPU", "CPU", False]],
}
GPU = host.GpuPin().as_json()


# ------------------------------------------------------------------------- shared stand-ins
def git(root: Path, *args: str) -> str:
    command = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    command += ["-c", "core.autocrlf=false", *args]
    return subprocess.run(command, capture_output=True, check=True).stdout.decode().strip()


def commit_donor(root: Path, name: str, path: str, code: str) -> tuple[Source, str]:
    """A stand-in donor committed at its Assets3D path: its pin and the commit."""
    data = code.encode("utf-8")
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_bytes(data)
    if not (root / ".git").exists():
        git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"stand-in {name}")
    source = Source(name, path, git_blob_id(data), sha256_bytes(data), len(data))
    return source, git(root, "rev-parse", "HEAD")


def low_stand_in() -> tuple[dict[str, Any], Any]:
    """Two triangles of a quad, as front U3's Blender side derives them, and the raw normals."""
    raw = {
        "co": np.array([0, 0, 0, 1, 0, 0, 1, 0.0078125, 0, 0, 1, 0.25], np.float32),
        "lt": np.arange(6, dtype=np.int32),
        "lv": np.array([0, 1, 2, 0, 2, 3], np.int32),
        "uv": np.array([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0.0078125, 1], np.float32),
        "cn": np.array([[0.0, 0.0, 1.0], [0.6, 0.0, 0.8], [0.0, 0.6, 0.8]] * 2, np.float32).ravel(),
    }
    lining = np.array([0.0, 0.25, 1.0, 0.0], np.float32)
    arrays = low_side.donor_arrays(raw, lining, np.eye(3), np.zeros(3), np.eye(3))
    return arrays, raw["cn"].reshape(-1, 3)


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def build_low(root: Path, normal_res: int = 4) -> NS:
    """Front U3's r1 and r1-repeat records as they hold their fields, and their files."""
    arrays, raw_cn = low_stand_in()
    normal = (np.arange(normal_res * normal_res * 3, dtype=np.float32) / 64).reshape(
        normal_res, normal_res, 3
    )
    r1 = root / "low-r1"
    r1.mkdir(parents=True)
    for name, array in arrays.items():
        np.save(r1 / low_side.LOW_FILES[name], array, allow_pickle=False)
    np.save(r1 / low_side.RAW_NORMALS, raw_cn, allow_pickle=False)
    np.save(r1 / low_side.HIGHNORMAL, normal, allow_pickle=False)
    members = [(n, (r1 / low_side.LOW_FILES[n]).read_bytes()) for n in low_side.LOW_ARRAYS]
    (r1 / low_host.LOW_NPZ).write_bytes(npz_bytes(members))
    outputs: dict[str, dict[str, Any]] = {
        name: {"sha256": sha256_file(r1 / name), "size_bytes": (r1 / name).stat().st_size}
        for name in host.LOW_FILES
    }
    digests = {name: side.array_digest(a) for name, a in arrays.items()}
    digests |= {"evaluated_cn": side.array_digest(raw_cn), "highnormal": side.array_digest(normal)}
    record = {
        "schema": low_host.RECORD_SCHEMA,
        "status": "exported",
        "script": {"blender_side_sha256": host.HELPER_SHA256["low"]},
        "outputs": outputs,
        "mesh": {"digests": digests},
    }
    write_json(r1 / low_host.RECORD_NAME, record)
    repeat = root / "low-r1-repeat"
    repeat.mkdir()
    write_json(
        repeat / low_host.RECORD_NAME, {**record, "expect": {"reproduced": True, "problems": []}}
    )
    pins = host.LowPins(
        record_sha256=sha256_file(r1 / low_host.RECORD_NAME),
        repeat_sha256=sha256_file(repeat / low_host.RECORD_NAME),
        low_npz_sha256=outputs[low_host.LOW_NPZ]["sha256"],
        highnormal_sha256=outputs[low_side.HIGHNORMAL]["sha256"],
    )
    return NS(
        record=r1 / low_host.RECORD_NAME,
        repeat=repeat / low_host.RECORD_NAME,
        pins=pins,
        arrays=arrays,
        raw_cn=raw_cn,
        normal=normal,
    )


def accepted_low(world: NS) -> host.LowInputs:
    return host.load_low(world.record, world.repeat, world.pins)


# ------------------------------------------------------------------------- the Blender side
def test_pins_follow_the_contract_and_the_precedents() -> None:
    assert host.pin_problems() == []
    assert side.DONOR_ARGS == (
        "extract",
        "--low-object",
        "18-Tunica-Low",
        "--lining-attribute",
        "LiningMask",
        "--normal-image",
        "Source_v6_HighNormal",
        "--high-object",
        "18-Tunica-High-OriginalFit",
        "--ao-resolution",
        "2048",
        "--ao-samples",
        "96",
        "--cage",
        "0.006",
        "--max-ray",
        "0.014",
    )
    assert side.BAKE_CALL == {
        "type": "AO",
        "use_selected_to_active": True,
        "max_ray_distance": 0.014,
        "cage_extrusion": 0.006,
        "margin": 8,
    }
    assert (host.DONOR.sha256, host.DONOR.size_bytes) == (side.DONOR_BLOB_SHA256, 13_617)
    assert host.SNAPSHOT.startswith("f49fe67c")
    for key, path in host.HELPERS.items():
        assert sha256_file(path) == host.HELPER_SHA256[key]
    assert host.HELPER_SHA256["low"] == host.LowPins().blender_side_sha256
    assert (side.HIGH_VERTICES, side.HIGH_TRIANGLES) == (726_509, 1_453_234)
    assert side.ENABLED_DEVICES == (("NVIDIA GeForce RTX 4090", "OPTIX"),)


def test_the_blender_side_imports_nothing_from_the_repository_and_saves_nothing() -> None:
    tree = ast.parse(Path(side.__file__).read_text(encoding="utf-8"))
    modules = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    modules += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith("tools")]
    saves = [
        n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr.startswith("save")
    ]
    assert not saves  # only the donor writes arrays; this script writes its JSON report
    # Around the donor it sets nothing in Blender: its only attribute assignments are the
    # donor's argv and the observing proxy (records go into dicts).
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    targets = {
        ast.unparse(target)
        for name in ("_ao", "_pins", "_read_low", "scene_state", "device_state")
        for node in ast.walk(functions[name])
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute)
    }
    assert targets == {"sys.argv", "bpy.ops.object"}


def test_the_donor_gets_the_contracts_arguments_after_its_marker(tmp_path: Path) -> None:
    argv = side.donor_argv(tmp_path / side.DONOR_FILE, tmp_path)
    assert argv[:5] == [
        str(tmp_path / side.DONOR_FILE),
        "--",
        "extract",
        "--out",
        str(tmp_path / side.DONOR_OUT),
    ]
    assert argv[5:] == list(side.DONOR_ARGS[1:])


def test_device_problems_need_all_three() -> None:
    assert side.device_problems(GOOD_DEVICE) == []
    cuda = {**GOOD_DEVICE, "compute_device_type": "CUDA"}
    assert "compute device type" in side.device_problems(cuda)[0]
    cpu = {**GOOD_DEVICE, "scene_device": "CPU"}
    assert "scene.cycles.device" in side.device_problems(cpu)[0]
    hybrid = {
        **GOOD_DEVICE,
        "devices": [[side.GPU_NAME, "x", "OPTIX", True], ["CPU", "c", "CPU", True]],
    }
    assert "enabled devices" in side.device_problems(hybrid)[0]
    other = {**GOOD_DEVICE, "devices": [["NVIDIA GeForce RTX 3090", "x", "OPTIX", True]]}
    assert "enabled devices" in side.device_problems(other)[0]
    none = {**GOOD_DEVICE, "devices": []}
    assert "enabled devices" in side.device_problems(none)[0]
    assert "cannot be read" in side.device_problems({})[0]


def test_call_problems_admit_the_donors_call_only() -> None:
    assert side.call_problems((), dict(side.BAKE_CALL), 1) == []
    assert "call 2" in side.call_problems((), dict(side.BAKE_CALL), 2)[0]
    assert "positional" in side.call_problems(("INVOKE_DEFAULT",), dict(side.BAKE_CALL), 1)[0]
    extra = {**side.BAKE_CALL, "use_clear": True}
    assert "called with" in side.call_problems((), extra, 1)[0]
    as_int = {**side.BAKE_CALL, "use_selected_to_active": 1}
    assert "called with" in side.call_problems((), as_int, 1)[0]


def test_ao_values_check_float32_before_the_cast_and_never_clip() -> None:
    pixels = np.full(AO_RES * AO_RES * 4, 0.75, np.float32)
    ao, problems = side.ao_values(pixels, AO_RES)
    assert problems == [] and ao.dtype == np.float16 and ao.shape == (AO_RES, AO_RES)
    over = pixels.copy()
    over[0] = 1.0000001  # rounds to 1.0 in float16; refused before the cast
    assert "outside [0, 1]" in side.ao_values(over, AO_RES)[1][0]
    nan = pixels.copy()
    nan[4] = np.nan
    assert "non-finite" in side.ao_values(nan, AO_RES)[1][0]
    rows = np.arange(AO_RES * AO_RES * 4, dtype=np.float32) / 64
    assert side.ao_values(rows, AO_RES)[0][1, 0] == np.float16(rows[AO_RES * 4])  # rows as found
    summary = side.pixel_summary(over)
    assert summary["finite"] and not summary["in_unit_range"]


def test_the_observed_bake_checks_first_and_delegates_the_rest() -> None:
    calls: list[str] = []

    class Real:
        def __call__(self, **kwargs: Any) -> set[str]:
            calls.append("real")
            return {"FINISHED"}

        def get_rna_type(self) -> str:
            return "rna"

    def refuse(args: Sequence[Any], kwargs: Mapping[str, Any], count: int) -> None:
        raise AoError("refused before the bake")

    observed = side.ObservedBake(Real(), refuse, lambda result: calls.append("after"))
    with pytest.raises(AoError, match="before the bake"):
        observed(**side.BAKE_CALL)
    assert calls == [] and observed.calls == 1 and observed.get_rna_type() == "rna"
    passing = side.ObservedBake(Real(), lambda *a: None, lambda result: calls.append("after"))
    ops = side.ObjectOps(NS(select_all="real select_all"), passing)
    assert ops.bake(**side.BAKE_CALL) == {"FINISHED"} and calls == ["real", "after"]
    assert ops.select_all == "real select_all"


def high(**changes: Any) -> NS:
    identity = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    data = NS(
        shape_keys=None,
        vertices=[0] * side.HIGH_VERTICES,
        polygons=[0] * side.HIGH_TRIANGLES,
    )
    obj = NS(type="MESH", modifiers=[], constraints=[], matrix_world=identity, data=data)
    obj.__dict__.update(changes)
    return obj


def test_high_problems() -> None:
    assert side.high_problems(high()) == []
    assert side.high_problems(None) == [f"no MESH object {side.HIGH_OBJECT!r}"]
    assert "modifiers" in side.high_problems(high(modifiers=[object()]))[0]
    scaled = [[2.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    assert "identity" in side.high_problems(high(matrix_world=scaled))[0]
    small = high()
    small.data = NS(shape_keys=None, vertices=[0], polygons=[0])
    assert "pinned" in side.high_problems(small)[0]


def test_pins_refuse_an_image_already_named_as_the_donors_bake() -> None:
    """An existing `garment_ao_bake` would make the donor's image `.001`: refused, so the image
    the bake observes by name is the donor's."""
    modules, _ = side.load_helpers(Path(side.__file__).parent)
    low = source_object()
    low.data.materials = [NS(node_tree=object())]
    objects = {side.LOW_OBJECT: low, side.HIGH_OBJECT: high()}
    bpy = NS(
        context=NS(view_layer=NS(objects={side.LOW_OBJECT: low})),
        data=NS(objects=objects, images={side.AO_IMAGE: object()}),
    )
    with pytest.raises(AoError, match="already holds an image named 'garment_ao_bake'"):
        side._pins(bpy, modules["low"])


def test_helpers_load_from_their_files_and_report_what_ran(tmp_path: Path) -> None:
    modules, hashes = side.load_helpers(Path(side.__file__).parent)
    assert hashes == host.HELPER_SHA256
    assert modules["low"].NORMAL_SHA256 == low_side.NORMAL_SHA256
    assert callable(modules["readback"]._last_properties)
    (tmp_path / "m.py").write_text("VALUE = 3\n", encoding="utf-8")
    module, found = side.load_module(tmp_path / "m.py", "m")
    assert module.VALUE == 3 and found == sha256_file(tmp_path / "m.py")
    with pytest.raises(AoError, match="pinned"):
        side.load_module(tmp_path / "m.py", "m", "0" * 64)


# ----------------------------------------------------------------------------- the host
DONOR_CODE = '"""Stand-in garment_blender_io: never executed by these tests."""\n'


def ao_report(
    cwd: Path, scripts: Mapping[str, str], donor_sha256: str, ao: Any, readback: Any
) -> dict[str, Any]:
    expect = json.loads((cwd / side.AO_EXPECT).read_text(encoding="utf-8"))
    pixel = float(ao.astype(np.float32).ravel()[0])
    return {
        "extractor": side.EXTRACTOR,
        "mode": "ao",
        "blender": {"version": [5, 2, 3]},
        "blend": str(cwd / side.SOURCE_BLEND_NAME),
        "helpers": {key: scripts[key] for key in side.HELPERS},
        "donor": {
            "path": side.DONOR_PATH,
            "blob_sha256": donor_sha256,
            "executed": "the raw blob as __main__, unchanged",
            "args": list(side.DONOR_ARGS),
        },
        "low": {"name": side.LOW_OBJECT, "first_read": expect["low_digests"]},
        "normal": {
            "image": side.NORMAL_IMAGE,
            "packed": {"sha256": low_side.NORMAL_SHA256, "png": low_side.NORMAL_PNG},
            "settings": low_side.NORMAL_SETTINGS,
            "after_donor": {"settings": low_side.NORMAL_SETTINGS, "loaded": low_side.NORMAL_LOADED},
        },
        "high": {
            "name": side.HIGH_OBJECT,
            "vertices": side.HIGH_VERTICES,
            "triangles": side.HIGH_TRIANGLES,
        },
        "visibility_as_found": {"high": {"hide_get": True}},
        "setup": {"engine": "BLENDER_EEVEE", "cycles": {"seed": 0}},
        "bake": {
            "call": side.BAKE_CALL,
            "bake_state_read": expect["low_digests"],
            "device_before_bake": GOOD_DEVICE,
            "device_after_bake": GOOD_DEVICE,
            "engine_samples": ["CYCLES", side.AO_SAMPLES],
            "selection": {
                "selected": sorted([side.HIGH_OBJECT, side.LOW_OBJECT]),
                "active": side.LOW_OBJECT,
            },
            "result": ["FINISHED"],
            "readback_before": readback["before"],
            "readback": readback["after"],
            "image": {
                "name": side.AO_IMAGE,
                "colorspace": side.AO_COLORSPACE,
                "size": [side.AO_RESOLUTION] * 2,
                "is_float": True,
            },
            "pixels": {"finite": True, "in_unit_range": True, "min": pixel, "max": pixel},
            "digest": side.array_digest(ao),
        },
    }


def unset() -> dict[str, Any]:
    names = sorted(side.BAKE_CALL)
    readback = unset_readback(names, {n: BAKE_DEFAULTS[n] for n in names})
    return {"before": readback, "after": readback}


def fake_ao(
    scene: NS,
    value: float = 0.5,
    code: int = 0,
    report: Callable[[dict[str, Any]], None] = lambda document: None,
    donor: Callable[[Path], None] = lambda folder: None,
    readback: Mapping[str, Any] | None = None,
    timeout: bool = False,
) -> Runner:
    def run(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, t: int) -> int:
        assert command[-2:] == ("ao", str(cwd)) and t == host.TIMEOUTS_S["ao"]
        assert command[6] == str(cwd / side.SOURCE_BLEND_NAME) and env["TEMP"] == str(cwd)
        assert (cwd / side.SOURCE_BLEND_NAME).stat().st_mode & 0o222 == 0  # read-only copy
        assert (cwd / side.DONOR_FILE).read_text(encoding="utf-8") == DONOR_CODE
        log.write_text("authored\n", encoding="utf-8")
        if timeout:
            raise subprocess.TimeoutExpired(list(command), t)
        if code:
            return code
        folder = cwd / side.DONOR_OUT
        folder.mkdir()
        world = scene.low
        np.savez(folder / "low.npz", **world.arrays)  # the donor's own np.savez
        np.save(folder / low_side.HIGHNORMAL, world.normal)
        ao = np.full((side.AO_RESOLUTION,) * 2, value, np.float16)
        np.save(folder / side.AO_NAME, ao)
        extract = {
            "low": side.LOW_OBJECT,
            "vertices": 4,
            "triangles": 2,
            "uv_map": "UVMap",
            "lining_attribute": side.LINING_ATTRIBUTE,
            "bounds_min": [0, 0, 0],
            "bounds_max": [1, 1, 0.25],
            "normal_image": {
                "name": side.NORMAL_IMAGE,
                "size": [4096, 4096],
                "colorspace": "Non-Color",
            },
            "ao": {
                "high": side.HIGH_OBJECT,
                "resolution": side.AO_RESOLUTION,
                "samples": 96,
                "cage_m": 0.006,
                "max_ray_m": 0.014,
                "mean": value,
            },
        }
        (folder / "extract_report.json").write_text(json.dumps(extract, indent=1), encoding="utf-8")
        donor(folder)
        document = ao_report(cwd, scene.scripts, scene.donor.sha256, ao, readback or unset())
        report(document)
        side.write_json(cwd / side.AO_REPORT, document)
        return 0

    return run


def fake_control(scene: NS, retains: bool = False, device: Any = None) -> Runner:
    def readbacks(call: Mapping[str, Any]) -> tuple[Any, Any]:
        names = sorted(call)
        defaults = {n: {"size": 2.0, "location": [0.0] * 3, **BAKE_DEFAULTS}[n] for n in names}
        before = unset_readback(names, defaults)
        if not retains:
            return before, before
        kept = readback_side.readback_state(names, dict(call), dict.fromkeys(names, True), defaults)
        return before, kept

    def run(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, t: int) -> int:
        assert command[-2:] == ("control", str(cwd)) and t == host.TIMEOUTS_S["control"]
        assert side.SOURCE_BLEND_NAME not in " ".join(command)  # the factory scene
        log.write_text("authored\n", encoding="utf-8")
        cube_before, cube_after = readbacks(side.CONTROL_CUBE)
        bake_before, bake_after = readbacks(side.CONTROL_BAKE)
        report = {
            "extractor": side.EXTRACTOR,
            "mode": "control",
            "blender": {"version": [5, 2, 3]},
            "helpers": {key: scene.scripts[key] for key in side.HELPERS},
            "cube": {
                "call": side.CONTROL_CUBE,
                "result": ["FINISHED"],
                "before": cube_before,
                "after": cube_after,
                "effect": {"dimensions": [3.0] * 3, "location": [1.0, 2.0, 3.0]},
            },
            "bake": {
                "call": side.CONTROL_BAKE,
                "result": ["FINISHED"],
                "before": bake_before,
                "after": bake_after,
                "device": device or GOOD_DEVICE,
                "effect": {"min": 1.0, "max": 1.0},
            },
        }
        side.write_json(cwd / side.CONTROL_REPORT, report)
        return 0

    return run


def fixed_gpu(*reads: Any) -> Callable[[], Any]:
    """The GPU reads in order (the last one repeats)."""
    queue = list(reads) or [[GPU]]

    def query() -> Any:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return query


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NS:
    monkeypatch.setattr(side, "AO_RESOLUTION", AO_RES)
    assets = tmp_path / "assets"
    assets.mkdir()
    donor, snapshot = commit_donor(assets, "garment_blender_io", side.DONOR_PATH, DONOR_CODE)
    blend = b"authored blend bytes"
    pin = SourcePin(
        "blend", "piece/" + side.SOURCE_BLEND_NAME, hashlib.sha256(blend).hexdigest(), len(blend)
    )
    (assets / pin.assets3d_path).parent.mkdir(parents=True)
    (assets / pin.assets3d_path).write_bytes(blend)
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"authored blender bytes")
    scripts = {
        "blender_side": sha256_file(host.SCRIPT),
        **{key: sha256_file(path) for key, path in host.HELPERS.items()},
        "host": sha256_file(host.HOST),
    }
    return NS(
        root=tmp_path,
        assets=assets,
        donor=donor,
        snapshot=snapshot,
        pin=pin,
        blender=blender,
        scripts=scripts,
        low=build_low(tmp_path / "u3"),
    )


def planned(scene: NS, mode: str, run: str, **kwargs: Any) -> host.Plan:
    pins: dict[str, Any] = {
        "blender_sha256": sha256_file(scene.blender),
        "source_pin": scene.pin,
        "donor": scene.donor,
        "snapshot": scene.snapshot,
        "work": scene.root / "work",
    }
    return host.plan(mode, scene.blender, run, scene.assets, None, **{**pins, **kwargs})


def control(scene: NS, run: str = "c1", runner: Runner | None = None) -> Path:
    host.run(planned(scene, "control", run), runner or fake_control(scene), gpu=fixed_gpu())
    path: Path = scene.root / "work" / run / host.RECORD_NAME
    return path


def bake(
    scene: NS, run: str, runner: Runner, proof: Path | None = None, **kwargs: Any
) -> dict[str, Any]:
    return host.run(
        planned(scene, "ao", run),
        runner,
        low=accepted_low(scene.low),
        control=proof or control(scene, f"{run}-control"),
        counts=(4, 2),
        **{"gpu": fixed_gpu(), **kwargs},
    )


def on_disk(scene: NS, run: str) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((scene.root / "work" / run / host.RECORD_NAME).read_bytes())
    return record


def test_plan_pins_the_commands_and_writes_nothing(scene: NS) -> None:
    ao = planned(scene, "ao", "ao-r1")
    assert not ao.run_dir.exists() and ao.source_origin == "assets3d"
    assert ao.command[6] == str(ao.run_dir / side.SOURCE_BLEND_NAME)
    assert ao.command[-4:] == (str(host.SCRIPT), "--", "ao", str(ao.run_dir))
    assert ao.donor_code == DONOR_CODE.encode("utf-8")
    document = ao.as_json()
    assert document["donor_args"] == list(side.DONOR_ARGS) and document["gpu"] == GPU
    assert (
        document["scripts"]["helpers"]["low"]["path"] == "tools/parity/tier1/tunic_low_blender.py"
    )
    check = planned(scene, "control", "c1")
    assert check.source is None and side.SOURCE_BLEND_NAME not in " ".join(check.command)


def test_plan_refuses_its_pins(scene: NS) -> None:
    with pytest.raises(AoError, match="pinned"):
        planned(scene, "ao", "r", helper_sha256={"low": "0" * 64, "readback": "0" * 64})
    with pytest.raises(AoError, match="run name"):
        planned(scene, "ao", "../escape")
    (scene.root / "work" / "taken").mkdir(parents=True)
    with pytest.raises(AoError, match="already exists"):
        planned(scene, "ao", "taken")
    with pytest.raises(Exception, match="repository"):
        host.plan("ao", scene.blender, "r", scene.assets, None, work=REPO_ROOT / "tmp" / "scratch")
    with pytest.raises(AoError, match="SHA-256"):
        host.plan("ao", scene.blender, "r", scene.assets, None, work=scene.root / "work")
    other = Source("garment_blender_io", side.DONOR_PATH, "0" * 40, "0" * 64, 1)
    with pytest.raises(Exception, match="blob"):
        planned(scene, "ao", "r2", donor=other)


def test_the_control_records_retention_unavailable(scene: NS) -> None:
    control(scene)
    record = on_disk(scene, "c1")
    assert record["status"] == "controlled" and record["outcome"] == host.RETENTION_UNAVAILABLE
    assert record["gpu"]["before"] == record["gpu"]["after"] == [GPU]
    assert record["hashes"]["donor_sha256_after"] == scene.donor.sha256
    control(scene, "c2", fake_control(scene, retains=True))
    assert on_disk(scene, "c2")["outcome"] == "retention-observed"
    cuda = {**GOOD_DEVICE, "compute_device_type": "CUDA"}
    control(scene, "c3", fake_control(scene, device=cuda))
    assert on_disk(scene, "c3")["outcome"] == "inconclusive"


def test_the_ao_bakes_on_the_accepted_low_and_reproduces_byte_for_byte(scene: NS) -> None:
    proof = control(scene)
    record = bake(scene, "ao-r1", fake_ao(scene), proof)
    assert record == on_disk(scene, "ao-r1") and record["status"] == "baked"
    assert "NEW AO substitute" in record["label"] and "unchanged" in record["label"]
    assert record["control"]["outcome"] == host.RETENTION_UNAVAILABLE
    assert record["low_inputs"]["record_sha256"] == scene.low.pins.record_sha256
    assert sorted(record["outputs"]) == sorted(host.RECORD_OUTPUTS["ao"])
    for stem, _, pinned in planned(scene, "ao", "unused").files():
        assert record["hashes"][f"{stem}_sha256_before"] == pinned
        assert record["hashes"][f"{stem}_sha256_after"] == pinned
    expect = json.loads((scene.root / "work" / "ao-r1" / side.AO_EXPECT).read_bytes())
    assert expect["low_digests"] == {
        k: accepted_low(scene.low).digests[k] for k in side.LOW_DIGESTS
    }
    first_sha = sha256_file(scene.root / "work" / "ao-r1" / host.RECORD_NAME)
    again = bake(
        scene, "ao-r1-repeat", fake_ao(scene), proof, expected=record, expected_sha256=first_sha
    )
    assert again["expect"] == {"of_record_sha256": first_sha, "reproduced": True, "problems": []}
    other = bake(scene, "ao-r1-other", fake_ao(scene, value=0.25), proof, expected=record)
    assert other["expect"]["reproduced"] is False
    assert any(p.startswith("outputs") for p in other["expect"]["problems"])


def other_member(folder: Path) -> None:
    arrays, _ = low_stand_in()
    np.savez(folder / "low.npz", **{**arrays, "lining": arrays["lining"] + np.float32(0.5)})


def other_normal(folder: Path) -> None:
    np.save(folder / low_side.HIGHNORMAL, np.zeros((4, 4, 3), np.float32))


def no_lining(folder: Path) -> None:
    path = folder / "extract_report.json"
    path.write_text(json.dumps({**json.loads(path.read_bytes()), "lining_attribute": None}))


def moved_low(document: dict[str, Any]) -> None:
    document["bake"]["bake_state_read"] = {**document["bake"]["bake_state_read"], "co": "0" * 64}


def cpu_after(document: dict[str, Any]) -> None:
    document["bake"]["device_after_bake"] = {**GOOD_DEVICE, "scene_device": "CPU"}


def clipped(document: dict[str, Any]) -> None:
    document["bake"]["pixels"]["in_unit_range"] = False


def another_call(document: dict[str, Any]) -> None:
    document["bake"]["call"] = {**side.BAKE_CALL, "margin": 16}


def other_digest(document: dict[str, Any]) -> None:
    document["bake"]["digest"] = "0" * 64


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda s: fake_ao(s, code=3), "exited 3"),
        (lambda s: fake_ao(s, donor=other_member), "member lining"),
        (lambda s: fake_ao(s, donor=other_normal), "highnormal.npy is not U3's"),
        (lambda s: fake_ao(s, donor=no_lining), "lining attribute"),
        (lambda s: fake_ao(s, report=moved_low), "low in its bake state"),
        (lambda s: fake_ao(s, report=cpu_after), "device after the bake"),
        (lambda s: fake_ao(s, report=clipped), r"pixels in \[0, 1\]"),
        (lambda s: fake_ao(s, report=another_call), "bake call"),
        (lambda s: fake_ao(s, report=other_digest), "float16 cast"),
        (lambda s: fake_ao(s, value=1.5), "outside"),
    ],
)
def test_a_refused_bake_still_records_every_hash(
    scene: NS, make: Callable[[NS], Runner], message: str
) -> None:
    proof = control(scene)
    with pytest.raises(AoError, match=message):
        bake(scene, "ao-r1", make(scene), proof)
    record = on_disk(scene, "ao-r1")
    assert record["status"] == "refused" and record["gpu"]["after"] == [GPU]
    assert all(record["hashes"][key] is not None for key in record["hashes"])


def test_unavailable_needs_the_controls_proof(scene: NS) -> None:
    for run, runner, outcome in (
        ("c-retains", fake_control(scene, retains=True), "retention-observed"),
        ("c-cuda", fake_control(scene, device={**GOOD_DEVICE, "devices": []}), "inconclusive"),
    ):
        proof = control(scene, run, runner)
        with pytest.raises(AoError, match=f"the control shows {outcome}"):
            bake(scene, f"ao-{run}", fake_ao(scene), proof)
    proof = control(scene, "c-ok")
    record = json.loads(proof.read_bytes())
    proof.write_text(json.dumps({**record, "outcome": "inconclusive"}), encoding="utf-8")
    with pytest.raises(AoError, match="re-derives as retention-unavailable"):
        bake(scene, "ao-tampered", fake_ao(scene), proof)
    tampered = on_disk(scene, "ao-tampered")
    assert tampered["status"] == "refused" and tampered["gpu"]["before"] == [GPU]
    assert tampered["hashes"]["original_sha256_before"] == scene.pin.sha256
    assert tampered["hashes"]["copy_sha256_before"] is None  # refused before the copy
    assert set(tampered["files"]) == set()  # no Blender was launched


def test_the_record_cites_the_validated_control_bytes(scene: NS) -> None:
    proof = control(scene)
    record = bake(scene, "ao-1", fake_ao(scene), proof)
    report = proof.parent / side.CONTROL_REPORT
    assert record["control"]["record_sha256"] == sha256_file(proof)
    assert record["control"]["report_sha256"] == sha256_file(report)
    for stem, path in (("control_record", proof), ("control_report", report)):
        assert record["hashes"][f"{stem}_sha256_before"] == sha256_file(path)
        assert record["hashes"][f"{stem}_sha256_after"] == sha256_file(path)


@pytest.mark.parametrize(
    ("name", "stem"),
    [(host.RECORD_NAME, "control_record"), (side.CONTROL_REPORT, "control_report")],
)
def test_a_control_changed_while_the_bake_runs_is_refused(scene: NS, name: str, stem: str) -> None:
    """Another process edits the validated control during the bake: refused, and the record
    holds the validated hash before and the changed one after."""
    proof = control(scene)
    target = proof.parent / name
    validated = sha256_file(target)
    inner = fake_ao(scene)

    def runner(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, t: int) -> int:
        code = inner(command, cwd, env, log, t)
        target.write_bytes(target.read_bytes() + b"\n")  # the separate writer
        return code

    with pytest.raises(AoError, match=f"after the run {stem}"):
        bake(scene, "ao-1", runner, proof)
    record = on_disk(scene, "ao-1")
    assert record["status"] == "refused"
    assert record["hashes"][f"{stem}_sha256_before"] == validated
    assert record["hashes"][f"{stem}_sha256_after"] == sha256_file(target) != validated


def test_a_retained_readback_is_compared_with_the_call(scene: NS) -> None:
    names = sorted(side.BAKE_CALL)
    defaults = {n: BAKE_DEFAULTS[n] for n in names}
    before = unset_readback(names, defaults)
    used = {**side.BAKE_CALL, "max_ray_distance": float(np.float32(0.014))}
    kept = readback_side.readback_state(names, used, dict.fromkeys(names, True), defaults)
    record = bake(scene, "ao-1", fake_ao(scene, readback={"before": before, "after": kept}))
    assert record["ao"]["bake"]["readback"]["status"] == "readback"
    wrong = readback_side.readback_state(
        names, {**used, "margin": 16}, dict.fromkeys(names, True), defaults
    )
    with pytest.raises(AoError, match="ran with margin 16"):
        bake(scene, "ao-2", fake_ao(scene, readback={"before": before, "after": wrong}))


def test_the_gpu_is_read_before_and_after_and_must_not_change(scene: NS) -> None:
    proof = control(scene)
    other = [{**GPU, "driver_version": "620.00"}]
    with pytest.raises(AoError, match="before the run nvidia-smi"):
        bake(scene, "ao-1", fake_ao(scene), proof, gpu=fixed_gpu(other))
    assert set(on_disk(scene, "ao-1")["files"]) == set()  # nothing launched
    with pytest.raises(AoError, match="after the run nvidia-smi"):
        bake(scene, "ao-2", fake_ao(scene), proof, gpu=fixed_gpu([GPU], other))
    assert on_disk(scene, "ao-2")["gpu"] == {"pin": GPU, "before": [GPU], "after": other}
    assert host.gpu_problems([GPU, GPU], host.GpuPin())  # two GPUs: not the one pinned


def test_a_timeout_records_the_after_hashes(scene: NS) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        bake(scene, "ao-1", fake_ao(scene, timeout=True))
    record = on_disk(scene, "ao-1")
    assert record["status"] == "refused" and "TimeoutExpired" in record["error"]
    assert record["hashes"]["copy_sha256_after"] == scene.pin.sha256


def test_load_low_checks_both_records_and_every_file(scene: NS) -> None:
    low = accepted_low(scene.low)
    assert sorted(low.digests) == sorted([*side.LOW_DIGESTS, "highnormal"])
    world = scene.low
    with pytest.raises(AoError, match="pinned"):
        host.load_low(world.record, world.repeat, host.LowPins())
    original = world.repeat.read_bytes()
    record = json.loads(original)
    world.repeat.write_text(json.dumps({**record, "expect": {"reproduced": False}}))
    pins = host.LowPins(**{**world.pins.__dict__, "repeat_sha256": sha256_file(world.repeat)})
    with pytest.raises(AoError, match="reproduced r1"):
        host.load_low(world.record, world.repeat, pins)
    world.repeat.write_bytes(original)
    (world.record.parent / low_side.RAW_NORMALS).write_bytes(b"changed")
    with pytest.raises(AoError, match="does not hash"):
        host.load_low(world.record, world.repeat, world.pins)


def test_compare_records_leaves_out_only_the_runs_paths() -> None:
    record = {
        "schema": host.RECORD_SCHEMA,
        "blender": {"sha256": "a", "executable": "x"},
        "low_inputs": {"record": "p1", "record_sha256": "s"},
        "outputs": {side.AO_REPORT: {"sha256": "1"}, "donor/ao.npy": {"sha256": "2"}},
    }
    other = json.loads(json.dumps(record))
    other["blender"]["executable"] = "y"
    other["low_inputs"]["record"] = "p2"
    other["outputs"][side.AO_REPORT]["sha256"] = "3"
    assert host.compare_records(record, other) == []
    other["outputs"]["donor/ao.npy"]["sha256"] = "4"
    assert [p for p in host.compare_records(record, other) if p.startswith("outputs")]
    # A key named like a run path deep inside an observation is still compared.
    deep = {"ao": {"donor": {"path": "a"}}}
    assert host.compare_records(deep, {"ao": {"donor": {"path": "b"}}})


def test_the_cli_dry_run_writes_nothing(
    scene: NS, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    the_plan = planned(scene, "control", "c-dry")
    monkeypatch.setattr(host, "plan", lambda *args, **kwargs: the_plan)
    argv = ["control", "--blender", str(scene.blender), "--assets-root", str(scene.assets)]
    assert host.main([*argv, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["command"][-2] == "control"
    assert not (scene.root / "work").exists()
    wrong = scene.root / "wrong.json"
    wrong.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert host.main([*argv, "--expect", str(wrong)]) == 2
    assert "is not a controlled" in capsys.readouterr().err
