"""Tests of phase1.12_compositor-height-normal (P1-COMPOSITOR,
`docs/architecture/04-layer-stack-and-compositing.md` §6; `src/evaluator/height_to_normal.h`,
`parity/semantics/height-to-normal.json`, decisions 064, 065, 079 and 080).

The native cases run `uzp-evaluator-tests.exe` (`tests/evaluator/evaluator_test.cpp`):
`height-normal` on the CPU anywhere; `height-normal-gpu-vs-cpu` needs the DX12 adapter and skips
under `UZP_NO_GPU=1` (hosted CI, decision 028). The Tier 0 comparisons evaluate the recorded
instruction sequences of the current oracle envelope (decision 037) and read the private oracle
store; they skip, saying so, on a machine without it, and the local run on the owner's machine
(`parity/reports/phase1/compositor-height-normal.md`) is their evidence. Painter 12.1.5's r1 is the
exact target where its two recordings differ (decision 032): r2 is compared wherever it equals r1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.evaluator.masks_fits import (
    envelope_golden,
    envelope_manifest,
    resource_entry,
    spec_from_steps,
)
from tests.evaluator.test_compositor_tile_dag import (
    REPO_ROOT,
    backends,
    evaluate,
    needs_store,
    raster,
    run_case,
)
from tests.evaluator.union_run import observe
from tools.parity.fit import normal as normal_fit
from tools.parity.fit.common import Context
from tools.parity.fit.oracle import Golden

MAPS = ("Normal_OpenGL", "Normal_DirectX")
METHODS = {"Sharp": "Sharp", "Smooth (Sobel)": "SmoothSobel"}
# golden (current envelope, tier0/...) -> texture sets
GOLDENS: dict[str, tuple[str, ...]] = {
    "semantics-ui/height-normal-sharp-plane-strength": tuple(f"s{i}" for i in range(8)),
    "semantics-ui/height-normal-sobel-plane-strength": tuple(f"s{i}" for i in range(8)),
    "semantics-ui/height-normal-sharp-sphere": ("uzp_sphere",),
    "semantics-ui/height-normal-sobel-sphere": ("uzp_sphere",),
    "semantics-ui/height-normal-sharp-bevelled-cube": ("uzp_bevelled_cube",),
    "semantics-ui/height-normal-sobel-bevelled-cube": ("uzp_bevelled_cube",),
    "semantics/height-normal-plane-amplitudes": ("s0", "s1", "s2", "s3"),
    "semantics/height-normal-sphere": ("uzp_sphere",),
    "semantics/height-normal-bevelled-cube": ("uzp_bevelled_cube",),
}
NORMAL_CHANNEL = "semantics/blend-normal-channel"


def write16(e: np.ndarray) -> np.ndarray:
    """The 16-bit export of encoded normals: the UNORM write rule (arith::WriteUnorm)."""
    j = np.floor(np.clip(np.asarray(e, np.float64), 0.0, 1.0) * float(1 << 20)).astype(np.int64)
    codes: np.ndarray = (j * 65535 + (1 << 19) - 1) >> 20
    return codes


def method_of(manifest: dict[str, Any], texture_set: str) -> str:
    """The texture set's height-to-normal method the operator set (Sharp when no sheet entry)."""
    name = f"Texture Set Settings/Height to normal method ({texture_set})"
    for setting in manifest.get("applied_settings", []):
        if setting["name"] == name:
            return METHODS[setting["value"]]
    return "Sharp"


def virtual_spec(
    manifest: dict[str, Any], texture_set: str, workdir: Path, outputs: list[str]
) -> dict[str, Any]:
    """The evaluator spec of `texture_set` with its method, the project's normal-map format and,
    when the sequence binds one, the Normal mesh map (an imported resource in the project's
    convention, as Painter reads a mesh map it is given)."""
    steps = manifest["instruction_sequence"]["steps"]
    create = next(s for s in steps if s["call"] == "substance_painter.project.create")
    convention = str(create["args"].get("normal_map_format", "OpenGL"))
    inputs = {i["input_id"]: REPO_ROOT / i["path"] for i in manifest["inputs"]}
    imports = {
        s["step"]: s["args"]["input"]
        for s in steps
        if s["call"].endswith("import_project_resource")
    }
    mesh = [s for s in steps if s["call"].endswith("TextureSet.set_mesh_map_resource")]
    rest = {
        **manifest,
        "instruction_sequence": {
            **manifest["instruction_sequence"],
            "steps": [s for s in steps if s not in mesh],
        },
    }
    spec = spec_from_steps(rest, texture_set, workdir, outputs)
    spec["height_to_normal_method"] = method_of(manifest, texture_set)
    spec["normal_map_format"] = convention
    spec["virtual_outputs"] = list(MAPS)
    for step in mesh:
        if step["args"]["usage"] != "Normal":
            raise ValueError(f"step {step['step']}: only a Normal mesh map is modelled")
        entry = resource_entry(inputs[imports[step["args"]["resource_step"]]], workdir)
        spec["normal_mesh_map"] = {"sha256": entry["sha256"], "convention": convention}
    return spec


def domain_of(golden: str) -> np.ndarray | None:
    """The compared texels: the whole image on the planes, the UV coverage eroded by one texel on
    the sphere and the bevelled cube (outside it the export holds padding)."""
    from tools.parity.tier0_semantics import fixtures

    if golden.endswith("sphere"):
        return normal_fit.uv_domain(fixtures.sphere())
    if golden.endswith("bevelled-cube"):
        return normal_fit.uv_domain(fixtures.bevelled_cube())
    return None


def differing(ours: np.ndarray, theirs: np.ndarray, domain: np.ndarray | None) -> int:
    delta = ours.astype(np.float64) != theirs.astype(np.float64).reshape(ours.shape)
    if domain is not None:
        delta = delta & domain.reshape(domain.shape + (1,) * (delta.ndim - 2))
    return int(np.count_nonzero(delta))


def stable(golden: Golden, map_name: str) -> bool:
    return golden.map_sha256("r1", map_name) == golden.map_sha256("r2", map_name)


# ── Native cases ─────────────────────────────────────────────────────────────


def test_height_normal_on_the_cpu(evaluator_tests: Path) -> None:
    """2.2-2.4, 3.3, 3.4: the stencils and the combination, z as 100 / W, the GPU's Vulkan acos,
    the Normal channel at partial coverage, the mesh map as F, the float32 read-out before the
    write rule, the Normal-channel import (green inverted, both conventions), the EXP-09 tags (a
    combined normal carries `combined` and its relief round, which follows the Height content and
    the method; the geometry-only pass-through carries `geometry_only`), the flat cases and the
    explicit failures of what is not recorded."""
    passed, _ = run_case(evaluator_tests, "height-normal")
    assert {
        "a flat height and an empty Normal channel give the flat normal (32767, 32767, 65535) in "
        "both methods and conventions",
        "Sharp: (h(-1,0) - h(0,0), h(0,0) - h(0,-1), 0.390625)",
        "Smooth (Sobel): ((1,2,1) left - right, bottom - top, 3.125)",
        "a combined normal is tagged `combined` with its relief round (revision, Height read-out "
        "hash, method)",
        "the relief round follows the Height content and the method, not the other channels",
        "the Normal channel stores an imported normal map as (r, 65535 - g, b) / 65535, half "
        "toward zero",
        "a DirectX project's Normal channel stores an imported normal map as an OpenGL project "
        "does",
        "z is a UV-space gradient: 100 / W (Sharp) and 800 / W (Sobel)",
        "hw::Acos equals the recording GPU's Vulkan acos on 48 measured inputs",
        "a Normal layer at opacity 1/2 is composited over the flat colour (0.5, 0.5, 1)",
        "a mesh map declared in the other convention fails with unsupported_source (not recorded)",
        "the geometry-only pass-through is the Normal mesh map's codes (8 and 16 bits), green "
        "inverted across conventions, tagged `geometry_only` without a relief round",
    } <= passed
    assert any(p.startswith("the Height read-out before the write rule") for p in passed)
    assert any(p.startswith("unrecorded cases fail explicitly") for p in passed)
    assert any(p.startswith("the Normal channel at coverage 0 is flat") for p in passed)
    assert any(p.startswith("a bound Normal mesh map is F of the combination") for p in passed)
    assert any(
        p.startswith("a DirectX project's Normal channel other than one bitmap") for p in passed
    )
    assert any(p.startswith("a 512 set evaluates") for p in passed)


def test_height_normal_gpu_equals_cpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.2, 2.4: the virtual normal kernel across tile edges, the raw float32 read-out on every
    channel format and whole evaluations equal the CPU reference bit for bit."""
    passed, _ = run_case(evaluator_tests, "height-normal-gpu-vs-cpu", str(tmp_path), needs_gpu=True)
    assert any(p.startswith("the virtual normal kernel equals the CPU reference") for p in passed)
    assert any(p.startswith("the float32 read-out (raw blend) equals") for p in passed)
    assert any(p.startswith("Evaluator (GPU) and CpuEvaluator give the same") for p in passed)


# ── Tier 0 (owner's machine) ─────────────────────────────────────────────────


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("golden_name", sorted(GOLDENS))
def test_height_normal_goldens_exact(
    evaluator_tests: Path, tmp_path: Path, backend: str, golden_name: str
) -> None:
    """3.1, 3.2, 4.1: both methods over the height-amplitude sweep (opacity 1, 0.75, 0.5, 0.25,
    0.1 and 2, 3, 4 copies in LinearDodge), the sphere and the bevelled cube, and the older
    default-method goldens: Normal_OpenGL, Normal_DirectX and the Height channel equal r1 on every
    compared texel, and r2 wherever r2 equals r1."""
    needs_store()
    manifest = envelope_manifest(golden_name)
    golden = envelope_golden(golden_name)
    domain = domain_of(golden_name)
    problems = []
    for texture_set in GOLDENS[golden_name]:
        workdir = tmp_path / texture_set
        spec = virtual_spec(manifest, texture_set, workdir, ["Height"])
        result = evaluate(evaluator_tests, spec, workdir, backend)
        for map_name in MAPS:
            ours = write16(raster(result, map_name))
            for recording in ("r1", "r2"):
                key = f"{texture_set}/{map_name}"
                if recording == "r2" and not stable(golden, key):
                    continue
                theirs = golden.map(recording, key).values
                observe(golden, key, recording, "16-bit code value", ours, theirs, domain)
                n = differing(ours, theirs, domain)
                if n:
                    problems.append(f"{key} {recording}: {n} values differ")
        height = raster(result, "Height")
        for recording in ("r1", "r2"):
            key = f"{texture_set}/height"
            if recording == "r2" and not stable(golden, key):
                continue
            theirs = golden.map(recording, key).values[..., :1]
            observe(golden, key, recording, "float32 value", height, theirs, domain)
            n = differing(height, theirs, domain)
            if n:
                problems.append(f"{key} {recording}: {n} values differ")
    assert not problems, problems


@pytest.mark.parametrize("backend", backends())
def test_normal_channel_in_the_virtual_map_exact(
    evaluator_tests: Path, tmp_path: Path, backend: str
) -> None:
    """2.3, 3.3 (the part recorded): the Normal channel (imported normal maps blended in Normal,
    NormalMapCombine, NormalMapDetail, NormalMapInverseDetail; empty Height) reoriented onto the
    flat height normal gives Normal_OpenGL exactly, on both recordings."""
    needs_store()
    manifest = envelope_manifest(NORMAL_CHANNEL)
    golden = envelope_golden(NORMAL_CHANNEL)
    problems = []
    for texture_set in ("s0", "s1", "s2", "s3"):
        workdir = tmp_path / texture_set
        spec = virtual_spec(manifest, texture_set, workdir, ["Normal"])
        result = evaluate(evaluator_tests, spec, workdir, backend)
        ours = write16(raster(result, "Normal_OpenGL"))
        for recording in ("r1", "r2"):
            theirs = golden.map(recording, f"{texture_set}/Normal_OpenGL").values
            observe(
                golden, f"{texture_set}/Normal_OpenGL", recording, "16-bit code value", ours, theirs
            )
            n = differing(ours, theirs, None)
            if n:
                problems.append(f"{texture_set} {recording}: {n} values differ")
    assert not problems, problems


def normal_export(raster_: np.ndarray, directx: bool) -> np.ndarray:
    """The exported Normal channel of its stored values: a DirectX project's export inverts the
    stored green once more (half toward zero of 1 - g; height-to-normal.json
    height-normal-channel-import)."""
    values = raster_.astype(np.float32)
    if directx:
        values = values.copy()
        values[..., 1] = normal_fit.half_toward_zero(np.float32(1) - values[..., 1])
    return values


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("golden_name", sorted(normal_fit.RECORDED_SETS))
def test_recorded_inputs_exact(
    evaluator_tests: Path, tmp_path: Path, backend: str, golden_name: str
) -> None:
    """3.1, 3.3, 4.1 (decisions 077, 079): the Normal mesh map in OpenGL and DirectX projects,
    SignedAddition on Height, Normal-channel coverage, 8- and 16-bit Normal imports in both
    conventions and the sweep at 512, 1024 and 2048 px: Normal_OpenGL, Normal_DirectX, the Height
    channel and the Normal channel (where it holds layers; its export in the project's convention)
    equal r1 on every texel, and r2 wherever r2 equals r1 (decision 032: EXC-004 and EXC-005
    bound the two r2 divergences)."""
    needs_store()
    manifest = envelope_manifest(golden_name)
    golden = envelope_golden(golden_name)
    directx = normal_fit.directx_project(manifest)
    problems = []
    for texture_set in normal_fit.RECORDED_SETS[golden_name]:
        workdir = tmp_path / texture_set
        spec = virtual_spec(manifest, texture_set, workdir, ["Height", "Normal"])
        result = evaluate(evaluator_tests, spec, workdir, backend)
        ours: dict[str, np.ndarray] = {m: write16(raster(result, m)) for m in MAPS}
        ours["height"] = raster(result, "Height")[..., :1]
        if "constant" not in result["channels"]["Normal"]:
            ours["normal"] = normal_export(raster(result, "Normal"), directx)
        for map_name, values in ours.items():
            key = f"{texture_set}/{map_name}"
            if key not in golden.maps("r1"):
                continue
            for recording in ("r1", "r2"):
                if recording == "r2" and not stable(golden, key):
                    continue
                theirs = golden.map(recording, key).values
                if map_name == "height":
                    theirs = theirs[..., :1]
                unit = "16-bit code value" if map_name in MAPS else "float32 value"
                observe(golden, key, recording, unit, values, theirs)
                n = differing(values, theirs, None)
                if n:
                    problems.append(f"{key} {recording}: {n} values differ")
    assert not problems, problems


def test_published_fit_reproduces() -> None:
    """2.5: `python -m tools.parity.fit check --fit normal` reproduces the published
    `parity/semantics/height-to-normal.json` against the current envelope."""
    from tools.parity.fit.cli import reproduction_problems
    from tools.parity.store.store import locate

    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")
    assert reproduction_problems(Context(store, REPO_ROOT), "normal") == []
