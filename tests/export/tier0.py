"""Tier 0 comparisons of phase1.15_export-plan-compiler (`tests/export/test_export_plan.py`
items 3.5 and 3.6; decisions 085 and 086), run on the owner's machine against the private oracle
store of the current envelope (decision 037). Nothing recorded leaves memory: the comparisons
return counts, and `publish` writes only |delta| statistics in export units to
`parity/semantics/virtual-maps.json` (CONTRACT §6.4).

- `compare_dry_runs`: for every exporting golden, the dry run of the recorder's documented
  configuration (`tools/parity/recorder/job.py`) over the recording's texture sets lists exactly
  the files Painter wrote in that export step.
- `virtual_map_goldens`: the supported virtual maps compiled as plan files, evaluated through
  `EvaluateFileOn` on the CPU store (`uzp-export-tests files`) and written with the 16-bit write
  rule, against r1 on every texel and r2 wherever r2 equals r1 (decision 032).

Run as a script to regenerate the published file:

    python tests/export/tier0.py <uzp-export-tests.exe> <work-dir>
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

if __name__ == "__main__":
    # Run as a script: the repository root is the import root, and its `tests` folder is the
    # `tests` package even when another distribution installs one.
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root))
    _tests = types.ModuleType("tests")
    _tests.__path__ = [str(_root / "tests")]
    sys.modules["tests"] = _tests

from tests.evaluator.masks_fits import envelope_golden, envelope_manifest, spec_from_steps
from tests.evaluator.test_compositor_tile_dag import TEMPLATES_DIR
from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.common import document, entry, parameter, residual, source
from tools.parity.fit.oracle import Golden, load
from tools.parity.fit.stats import difference
from tools.parity.recorder.job import Step, export_step
from tools.parity.recorder.texture import export_roots
from tools.parity.store.store import locate

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = REPO_ROOT / "parity" / "semantics" / "virtual-maps.json"
SET_MESH_MAP = "substance_painter.textureset.TextureSet.set_mesh_map_resource"
# Refusals of a golden that are release gaps (never planned differently): native-precision mesh
# maps other than normal_base (recording R-090, decision 090), the virtual maps not reproduced
# exactly (recording R-092, decision 092) and View_2D, a render no task owns yet (decision 092;
# its view-state goldens, decision 093).
GAP_OWNERS = ("R-090", "R-092", "Painter's 2D view render")

# plan_many(exe, cases, tmp[, project_path]) of tests/export/test_export_plan.py.
PlanMany = Callable[..., list[dict[str, Any]]]
SkeletonOf = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def needs_store() -> None:
    if locate() is None:
        import pytest

        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")


def write16(values: np.ndarray) -> np.ndarray:
    """The 16-bit export of float32 values: the UNORM write rule (arith::WriteUnorm): truncated to
    16 + 4 fractional bits, then the nearest code with ties down."""
    j = np.floor(np.clip(np.asarray(values, np.float64), 0.0, 1.0) * float(1 << 20)).astype(
        np.int64
    )
    codes: np.ndarray = (j * 65535 + (1 << 19) - 1) >> 20
    return codes


# ── 3.5 Dry run = the files Painter wrote ────────────────────────────────────


def painter_files(golden: Golden, recording: str, step: int) -> set[tuple[str, str]]:
    """(rootPath, file name) of every file Painter wrote in export step `step`: the recorder
    names each output after the requested map (`$textureSet_<map>`) and keeps its container."""
    files = set()
    for output in golden.recordings[recording].outputs.values():
        if output["kind"] != "exported_map" or output["export_settings"]["step"] != step:
            continue
        root = str(output["texture_set"])
        texture_set = root.split("/")[0]
        extension = "exr" if output["storage_format"]["container"] == "exr" else "png"
        files.add((root, f"{texture_set}_{output['map']}.{extension}"))
    return files


def compare_dry_runs(
    exe: Path, tmp: Path, manifests: list[Path], skeleton_of: SkeletonOf, plan_many: PlanMany
) -> dict[str, Any]:
    """Plans every export step of every golden in `manifests` and compares the planned files with
    Painter's, on every recording whose files agree with r1."""
    needs_store()
    store = locate()
    cases: list[tuple[dict[str, Any], Any]] = []
    expected: list[tuple[str, int, list[set[tuple[str, str]]]]] = []
    for path in manifests:
        golden = load(store, path)
        manifest = golden.manifest
        template = golden.output("r1", "template/texture-sets")["values"]
        skeleton = skeleton_of(manifest, template)
        roots = [ts if not st else f"{ts}/{st}" for ts, st in export_roots(template)]
        for raw in manifest["instruction_sequence"]["steps"]:
            if not raw["call"].endswith("export_project_textures"):
                continue
            if raw["args"].get("probe") is True:
                continue  # the probe recorder's export probe: a readback, no exported-map record
            export = export_step(Step(raw["step"], raw["call"], raw["args"]))
            cases.append((skeleton, export.config(Path("C:/export"), roots)))
            recorded = [painter_files(golden, r, raw["step"]) for r in sorted(golden.recordings)]
            expected.append((golden.golden_id, raw["step"], recorded))
    results = plan_many(exe, cases, tmp)
    report: dict[str, Any] = {
        "compared": 0,
        "refused_gaps": [],
        "differing": [],
        "unexpected_refusals": [],
    }
    for (golden_id, step, recorded), result in zip(expected, results, strict=True):
        where = f"{golden_id} step {step}"
        if "error" in result:
            gap = result["error"] == "NotYetSupported" and any(
                o in result["message"] for o in GAP_OWNERS
            )
            (report["refused_gaps"] if gap else report["unexpected_refusals"]).append(
                f"{where}: {result['error']}: {result['message']}"
            )
            continue
        planned = {(f["rootPath"], f["relativePath"]) for f in result["plan"]["files"]}
        report["compared"] += 1
        for i, theirs in enumerate(recorded):
            if i > 0 and theirs != recorded[0]:
                continue  # an unstable recording: r1 is the target (decision 032)
            if planned != theirs:
                report["differing"].append(
                    f"{where}: planned only {sorted(planned - theirs)}, "
                    f"Painter only {sorted(theirs - planned)}"
                )
    return report


# ── Export probes (recording R-085, decisions 087 and 091) ───────────────────

PROBE_GOLDENS = (
    "semantics/export-probes-naming",
    "semantics/export-probes-channels",
    "semantics/export-probes-config",
    "semantics/export-probes-aliases-coat",
    "semantics/export-probes-aliases-fuzz",
    "semantics/export-probes-aliases-subsurface",
)
# Probes the plan still refuses as unrecorded (NotYetSupported naming R-091, decision 091): the
# surviving file of a case-only collision, and srcChannel A (only full and no coverage recorded).
REFUSED_PROBES = (
    "probe-naming-p9-case-only",
    "probe-channels-p6-alpha-of-roughness",
    "probe-channels-p6-alpha-of-basecolor",
)
# The recorder saves r2's project as `golden.spp` before reopening it (texture.py).
SAVED_PROJECT = "C:/recording/project/golden.spp"


def compare_probes(
    exe: Path, tmp: Path, skeleton_of: SkeletonOf, plan_many: PlanMany
) -> dict[str, Any]:
    """Compiles every export probe of `PROBE_GOLDENS` on its recording's texture sets (r1 never
    saved, r2 saved as golden.spp) and compares with Painter: a probe Painter's
    `list_project_textures` refused is a ValueError; one whose export raised makes the dry run
    raise ValueError; otherwise the dry run lists exactly the files on disk after the export
    (Painter's result less the inventory's missing names), with Painter's bit depth and channel
    count. A legacy name's planned channel is the one whose direct control Painter wrote with the
    same bytes."""
    needs_store()
    report: dict[str, Any] = {
        "compared": 0,
        "differing": [],
        "unexpected_refusals": [],
        "refused": [],
        "pairings": 0,
    }
    for name in PROBE_GOLDENS:
        golden = envelope_golden(name)
        manifest = golden.manifest
        inputs = {i["input_id"]: REPO_ROOT / i["path"] for i in manifest["inputs"]}
        steps = manifest["instruction_sequence"]["steps"]
        mesh = next(s["args"]["mesh"] for s in steps if s["call"].endswith("project.create"))
        probes = [s for s in steps if s["call"].endswith("list_project_textures")]
        for recording in sorted(golden.recordings):
            template = golden.output(recording, "template/texture-sets")["values"]
            skeleton = skeleton_of(manifest, template) | {"mesh": inputs[mesh].name}
            cases = []
            for step in probes:
                cfg = json.loads(inputs[step["args"]["config"]].read_text(encoding="utf-8"))
                cases.append((skeleton, cfg | {"exportPath": "C:/export"}))
            results = plan_many(exe, cases, tmp, None if recording == "r1" else SAVED_PROJECT)
            by_blob: dict[str, str] = {}
            aliases: list[tuple[str, str]] = []
            for step, result in zip(probes, results, strict=True):
                probe = str(step["args"]["config"])
                where = f"{golden.golden_id} {recording} {probe}"
                outputs = golden.recordings[recording].outputs
                listed = outputs[f"probe/s{step['step']}/list"]
                exported = outputs.get(f"probe/s{step['step']}/export")
                report["compared"] += 1
                if "error" in result:
                    expected = probe in REFUSED_PROBES and "R-091" in result["message"]
                    if result["error"] == "NotYetSupported" and expected:
                        report["refused"].append(f"{where}: {result['message']}")
                    elif not ("raised" in listed and result["error"] == "ValueError"):
                        report["unexpected_refusals"].append(f"{where}: {result['message']}")
                    continue
                if "raised" in listed or probe in REFUSED_PROBES:
                    report["differing"].append(f"{where}: Painter refused, the plan compiled")
                    continue
                assert exported is not None
                if "raised" in exported:
                    if "list_error" not in result:
                        report["differing"].append(
                            f"{where}: Painter's export raised, the dry run did not"
                        )
                    continue
                missing = set(exported["value"]["directory"]["missing"])
                theirs = {
                    (root, f)
                    for root, files in exported["value"]["textures"].items()
                    for f in files
                    if f not in missing
                }
                planned = {(f["rootPath"], f["relativePath"]): f for f in result["plan"]["files"]}
                if "list_error" in result or set(planned) != theirs:
                    report["differing"].append(
                        f"{where}: planned {sorted(planned)}, Painter {sorted(theirs)}"
                    )
                    continue
                for o in outputs.values():
                    if o["kind"] != "exported_map" or o["export_settings"]["step"] != step["step"]:
                        continue
                    f = planned[(o["texture_set"], o["map"])]
                    fmt = o["storage_format"]
                    if (str(fmt["bits_per_channel"]), fmt["channels"]) != (
                        f["parameters"]["bitDepth"],
                        len(f["channels"]),
                    ):
                        report["differing"].append(f"{where}: {o['map']} depth or channels")
                    channel = f["channels"][0]["source"].get("channel")
                    if "direct" in probe:
                        by_blob[o["blob"]["sha256"]] = channel
                    elif "p13" in probe:
                        aliases.append((o["blob"]["sha256"], channel))
            for blob, channel in aliases:
                report["pairings"] += 1
                if by_blob.get(blob) != channel:
                    report["differing"].append(
                        f"{golden.golden_id} {recording}: alias read {channel}, "
                        f"Painter's bytes are {by_blob.get(blob)}'s"
                    )
    return report


# The recording GPU's log2 and exp2 (src/evaluator/hwmath.h, `src/evaluator/tables/hw-*.zlib`).
def _hw_table(name: str) -> np.ndarray:
    raw = zlib.decompress(
        (REPO_ROOT / "src" / "evaluator" / "tables" / f"hw-{name}.zlib").read_bytes()
    )
    deltas = np.frombuffer(raw, np.uint32)
    with np.errstate(over="ignore"):
        table: np.ndarray = np.cumsum(np.cumsum(deltas, dtype=np.uint32), dtype=np.uint32).view(
            np.float32
        )
    return table


def _hw_log2(x: np.ndarray) -> np.ndarray:
    hi, lo = _hw_table("lg2-hi"), _hw_table("lg2-lo")
    bits = np.asarray(x, np.float32).view(np.uint32)
    e = ((bits >> 23) & 0xFF).astype(np.int64) - 127
    m = bits & 0x7FFFFF
    h, low = hi[m].astype(np.float64), lo[m].astype(np.float64)
    r = np.where(e >= 1, e + h, np.where(e == 0, h, np.where(e == -1, low, (e + 1) + low)))
    f = r.astype(np.float32)  # then toward zero
    f = np.where(np.abs(f.astype(np.float64)) > np.abs(r), np.nextafter(f, np.float32(0)), f)
    result: np.ndarray = np.where(((bits >> 23) & 0xFF) == 0, np.float32(-np.inf), f).astype(
        np.float32
    )
    return result


def _hw_exp2(y: np.ndarray) -> np.ndarray:
    pos, neg = _hw_table("ex2-pos"), _hw_table("ex2-neg")
    v = np.asarray(y, np.float32).astype(np.float64)
    a = np.abs(v)
    k = np.floor(a)
    j = np.floor((a - k) * 2.0**23).astype(np.int64)
    result: np.ndarray = np.where(
        v >= 0, pos[j].astype(np.float64) * 2.0**k, neg[j].astype(np.float64) * 2.0**-k
    ).astype(np.float32)
    return result


def srgb_encode(values: np.ndarray) -> np.ndarray:
    """Painter 12.1.5's sRGB encode of a linear colour value (probe P5, decision 091), float32:
    exponent 0.41666 through the GPU's exp2 and log2, its last step fused."""
    f32 = np.float32
    x = np.asarray(values, f32)
    wide = np.asarray(x, np.float64)
    power = float(f32(0.41666)) * np.asarray(_hw_log2(np.maximum(x, f32(1e-30))), np.float64)
    t = np.asarray(_hw_exp2(power.astype(f32)), np.float64)
    encoded: np.ndarray = np.where(
        x <= f32(0.0031308),
        (float(f32(12.92)) * wide).astype(f32),
        (float(f32(1.055)) * t + float(f32(-0.055))).astype(f32),
    )
    return encoded


def srgb16(values: np.ndarray) -> np.ndarray:
    """Painter 12.1.5's 16-bit export of a linear colour value (probe P5, decision 091): the sRGB
    encode (`srgb_encode`), then the 16-bit write rule."""
    return write16(srgb_encode(values))


# The goldens with an sRGB bitmap: field A on BaseColor in the colour space Painter gives it by
# default (sources.h), with their files holding BaseColor's RGB sRGB-encoded (`srgb_encode`) per
# texture set. The converted maps hold it as Unity4Diff (decision 092: RGB enc(L) on a filled
# set), written at 16 bits or as OpenEXR 32f.
SRGB_BITMAP_FILES: dict[str, dict[str, tuple[str, ...]]] = {
    "semantics/export-probes-config": {"s0": ("probe/s12/s0_basecolor.png",)},
    "semantics/export-probes-naming": {"s0": ("probe/s12/s0_ctl_basecolor.png",)},
    "semantics/virtual-maps-converted": {
        ts: (f"{ts}/Unity4Diff/step51", f"{ts}/Unity4Diff/step52") for ts in ("s0", "s1")
    },
    "semantics/virtual-maps-converted-float": {
        ts: (f"{ts}/Unity4Diff/step51", f"{ts}/Unity4Diff/step52") for ts in ("s0", "s1")
    },
}


def srgb_bitmap_probe(exe: Path, tmp: Path) -> dict[str, int]:
    """The sRGB bitmap through the plan: each texture set of `SRGB_BITMAP_FILES` built from its
    instruction sequence (`export_spec`), BaseColor's RGB evaluated by `EvaluateFileOn` and
    sRGB-encoded, against every listed file of r1 and r2 (16-bit files through the write rule):
    differing values per file."""
    needs_store()
    cfg: dict[str, Any] = {
        "defaultExportPreset": "uzp_recorder",
        "exportParameters": [
            {
                "parameters": {
                    "bitDepth": "16",
                    "dithering": False,
                    "fileFormat": "png",
                    "paddingAlgorithm": "infinite",
                }
            }
        ],
        "exportPresets": [
            {
                "maps": [
                    {
                        "channels": [
                            {
                                "destChannel": c,
                                "srcChannel": c,
                                "srcMapName": "basecolor",
                                "srcMapType": "documentMap",
                            }
                            for c in "RGB"
                        ],
                        "fileName": "$textureSet_rgb",
                    }
                ],
                "name": "uzp_recorder",
            }
        ],
        "exportShaderParams": False,
    }
    report: dict[str, int] = {}
    for name, files in SRGB_BITMAP_FILES.items():
        manifest, golden = envelope_manifest(name), envelope_golden(name)
        for texture_set, keys in files.items():
            workdir = tmp / "srgb" / name.rsplit("/", 1)[-1] / texture_set
            spec = export_spec(manifest, texture_set, workdir)
            rasters = evaluate_files(
                exe,
                spec,
                cfg | {"exportPath": "C:/export", "exportList": [{"rootPath": texture_set}]},
                workdir,
            )
            encoded = srgb_encode(rasters[f"{texture_set}_rgb.png"])
            for recording in sorted(golden.recordings):
                for key in keys:
                    theirs = golden.map(recording, key)
                    ours = write16(encoded) if theirs.integer else encoded
                    differing = ours != theirs.values[..., :3]
                    report[f"{name} {recording} {key}"] = int(differing.sum())
    return report


def luma_probe(exe: Path, tmp: Path) -> tuple[dict[str, int], dict[str, str]]:
    """Probe P5 through the plan: `srcChannel L` of BaseColor (field A in Raw) evaluated by
    `EvaluateFileOn` (the luma of the linear channel) and the channel's RGB, both written with
    `srgb16`, against r1 and r2 of every texel of s0 and of s1, whose BaseColor holds its linear
    base value (decision 126): differing values; and the evaluation failures."""
    needs_store()
    name = "semantics/export-probes-channels"
    manifest, golden = envelope_manifest(name), envelope_golden(name)
    cfg = json.loads(
        (
            REPO_ROOT / "parity/fixtures/tier0-semantics/export-probes/channels/p5-luminance.json"
        ).read_text(encoding="utf-8")
    )
    cfg["exportPresets"][0]["maps"].append(
        {
            "fileName": "$textureSet_rgb",
            "channels": [
                {
                    "destChannel": c,
                    "srcChannel": c,
                    "srcMapType": "documentMap",
                    "srcMapName": "basecolor",
                }
                for c in "RGB"
            ],
        }
    )
    report: dict[str, int] = {}
    refused: dict[str, str] = {}
    for texture_set in ("s0", "s1"):
        workdir = tmp / "p5" / texture_set
        spec = export_spec(manifest, texture_set, workdir)
        rasters, errors = evaluate_files_or_errors(
            exe,
            spec,
            cfg | {"exportPath": "C:/export", "exportList": [{"rootPath": texture_set}]},
            workdir,
        )
        refused |= errors
        if errors:
            continue
        lum = srgb16(rasters[f"{texture_set}_lum.png"][..., 0])
        rgb = srgb16(rasters[f"{texture_set}_rgb.png"])
        for recording in ("r1", "r2"):
            theirs_l = golden.map(recording, f"probe/s12/{texture_set}_lum.png").values[..., 0]
            theirs_rgb = golden.map(recording, f"probe/s15/{texture_set}_rgba_opacity.png").values
            report[f"{texture_set}/lum/{recording}"] = int((lum != theirs_l).sum())
            report[f"{texture_set}/rgb/{recording}"] = int((rgb != theirs_rgb).sum())
    return report, refused


# ── 3.6 Virtual maps through the plan ────────────────────────────────────────

# golden (current envelope, tier0/...) -> (texture sets, supported virtual maps)
VIRTUAL_GOLDENS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "semantics/height-normal-plane-amplitudes": (
        ("s0", "s1", "s2", "s3"),
        ("Normal_OpenGL", "Normal_DirectX"),
    ),
    "semantics-ui/height-normal-sharp-plane-strength": (
        tuple(f"s{i}" for i in range(8)),
        ("Normal_OpenGL", "Normal_DirectX"),
    ),
    "semantics-ui/height-normal-sobel-plane-strength": (
        tuple(f"s{i}" for i in range(8)),
        ("Normal_OpenGL", "Normal_DirectX"),
    ),
}
METHODS = {"Sharp": "Sharp", "Smooth (Sobel)": "SmoothSobel"}
COMPONENTS = {"Normal_OpenGL": "RGB", "Normal_DirectX": "RGB"}


def method_of(manifest: dict[str, Any], texture_set: str) -> str:
    """The texture set's height-to-normal method the operator set (Sharp when no sheet entry)."""
    name = f"Texture Set Settings/Height to normal method ({texture_set})"
    for setting in manifest.get("applied_settings", []):
        if setting["name"] == name:
            return METHODS[setting["value"]]
    return "Sharp"


def export_spec(manifest: dict[str, Any], texture_set: str, workdir: Path) -> dict[str, Any]:
    """The evaluator spec of one texture set with its bound mesh maps: the mesh-map binding steps
    are taken out of the sequence (the evaluator converter does not model them) and become the
    spec's `mesh_maps`, keyed by usage, of the resource each step binds."""
    steps = manifest["instruction_sequence"]["steps"]
    bindings = [s for s in steps if s["call"] == SET_MESH_MAP]
    others = [s for s in steps if s["call"] != SET_MESH_MAP]
    sequence = dict(manifest["instruction_sequence"], steps=others)
    spec = spec_from_steps(dict(manifest, instruction_sequence=sequence), texture_set, workdir, [])
    inputs = {i["input_id"]: REPO_ROOT / i["path"] for i in manifest["inputs"]}
    by_step = {s["step"]: s["args"] for s in steps}
    mesh_maps = {}
    for binding in bindings:
        args = binding["args"]
        if args.get("texture_set", texture_set) != texture_set:
            continue
        resource = by_step[args["resource_step"]]
        data = inputs[resource.get("input", resource.get("image"))].read_bytes()
        mesh_maps[str(args["usage"])] = hashlib.sha256(data).hexdigest()
    spec["name"] = texture_set
    spec["mesh_maps"] = mesh_maps
    spec["height_to_normal_method"] = method_of(manifest, texture_set)
    return spec


def export_config(maps: tuple[str, ...], root: str) -> dict[str, Any]:
    """The recorder's configuration for `maps` on `root` (PNG 16, as the goldens were exported)."""
    step = export_step(
        Step(
            0,
            "substance_painter.export.export_project_textures",
            {
                "maps": [f"virtualMap/{m}:{COMPONENTS[m]}" for m in maps],
                "file_format": "png",
                "bit_depth": 16,
                "padding": "infinite",
                "dithering": False,
            },
        )
    )
    return step.config(Path("C:/export"), [root])


def evaluate_files(
    exe: Path, spec: dict[str, Any], config: dict[str, Any], workdir: Path
) -> dict[str, np.ndarray]:
    """`uzp-export-tests files`: relativePath -> values (height, width, channels) of every planned
    file."""
    rasters, errors = evaluate_files_or_errors(exe, spec, config, workdir)
    assert not errors, errors
    return rasters


def evaluate_files_or_errors(
    exe: Path, spec: dict[str, Any], config: dict[str, Any], workdir: Path
) -> tuple[dict[str, np.ndarray], dict[str, str]]:
    """`uzp-export-tests files`: the planned files evaluated (relativePath -> values) and those
    whose evaluation failed (relativePath -> reason)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (workdir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    out = workdir / "out"
    proc = subprocess.run(
        [
            str(exe),
            "files",
            str(TEMPLATES_DIR),
            str(workdir / "spec.json"),
            str(workdir / "config.json"),
            str(out),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1200,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    rasters = {}
    errors = {}
    for f in index["files"]:
        if "error" in f:
            errors[f["relativePath"]] = str(f["error"])
            continue
        values = np.fromfile(out / f["raw"], dtype=np.float32)
        rasters[f["relativePath"]] = values.reshape(f["height"], f["width"], f["channels"])
    return rasters, errors


def virtual_map_goldens(exe: Path, tmp: Path, repo_root: Path) -> dict[str, Any]:
    """Compares every supported virtual map of `VIRTUAL_GOLDENS`; returns the counts, the
    differing maps and the residuals (golden, map, recording, |delta| statistics)."""
    needs_store()
    del repo_root  # the fixtures are read through the manifests' input paths
    report: dict[str, Any] = {"maps": 0, "differing": [], "residuals": []}
    for name, (texture_sets, maps) in VIRTUAL_GOLDENS.items():
        manifest = envelope_manifest(name)
        golden = envelope_golden(name)
        for texture_set in texture_sets:
            workdir = tmp / name.replace("/", "_") / texture_set
            spec = export_spec(manifest, texture_set, workdir)
            rasters = evaluate_files(exe, spec, export_config(maps, texture_set), workdir)
            for map_name in maps:
                ours = write16(rasters[f"{texture_set}_{map_name}.png"])
                key = f"{texture_set}/{map_name}"
                report["maps"] += 1
                for recording in ("r1", "r2"):
                    if recording == "r2" and golden.map_sha256("r1", key) != golden.map_sha256(
                        "r2", key
                    ):
                        continue
                    theirs = golden.map(recording, key).values
                    diff = difference(ours, theirs[..., : ours.shape[2]].reshape(ours.shape))
                    report["residuals"].append((golden.golden_id, key, recording, diff))
                    if diff.differing:
                        report["differing"].append(
                            f"{golden.golden_id} {key} {recording}: {diff.differing} values"
                        )
    return report


# ── parity/semantics/virtual-maps.json ───────────────────────────────────────

PYDOC = source(
    "A-PYDOC",
    "substance_painter.export: Full json_config dict possibilities, srcMapType virtualMap",
)
HELP = source("A-HELP-EXPORT", "Output templates: converted (virtual) maps")
D3D = source("X-D3D12", "Data conversion rules: FLOAT to UNORM")

# name -> (entry id, components, meaning from the public documentation)
DOCUMENTED: dict[str, tuple[str, int, str]] = {
    "Normal_OpenGL": (
        "normal-opengl",
        3,
        "the mesh normal, the Normal channel and the normal derived from Height combined, encoded "
        "for the OpenGL convention (green up)",
    ),
    "Normal_DirectX": (
        "normal-directx",
        3,
        "the same combined normal encoded for the DirectX convention (green down)",
    ),
    "AO_Mixed": ("ao-mixed", 1, "the baked ambient occlusion mesh map mixed with the AO channel"),
    "Diffuse": (
        "diffuse",
        3,
        "the diffuse colour of a specular/glossiness conversion of the metal/roughness channels",
    ),
    "Specular": (
        "specular",
        3,
        "the specular colour of a specular/glossiness conversion of the metal/roughness channels",
    ),
    "Glossiness": (
        "glossiness",
        1,
        "the glossiness of a specular/glossiness conversion (inverted roughness)",
    ),
    "Unity4Diff": ("unity4diff", 3, "the Unity 4 diffuse map of a metal/roughness conversion"),
    "Unity4Gloss": ("unity4gloss", 1, "the Unity 4 glossiness map of a metal/roughness conversion"),
    "reflection": ("reflection", 3, "the reflection colour of a metal/roughness conversion"),
    "1/ior": ("one-over-ior", 1, "the reciprocal of the index of refraction"),
    "Glossiness2": ("glossiness2", 1, "the squared glossiness of a metal/roughness conversion"),
    "f0": ("f0", 3, "the reflectance at normal incidence of a metal/roughness conversion"),
    "View_2D": ("view-2d", 3, "the 2D view of the shaded material"),
}
FORMULAS = {
    "Normal_OpenGL": (
        "n = normalise(reoriented(normalise(reoriented(flat, H)), decode(C))) with H the "
        "height-derived normal of the texture set's method and C the Normal channel composited "
        "over (0.5, 0.5, 1); Normal_OpenGL = fma(n, 1/2, 1/2), written with the file's write rule "
        "(parity/semantics/height-to-normal.json, decisions 064 and 065)."
    ),
    "Normal_DirectX": (
        "As Normal_OpenGL with n.y negated before the encoding (height-to-normal.json)."
    ),
}


GAP_FORMULA = (
    "Release gap (decisions 086 and 092): not reproduced exactly through the plan; a "
    "configuration naming it is refused with NotYetSupported before anything is written."
)
GAP_CORPUS = (
    "tier0/semantics/ao-mixed",
    "tier0/semantics/ao-mixed-opacity",
    "tier0/semantics/ao-mixed-opacity-float",
    "tier0/semantics/virtual-maps-converted",
    "tier0/semantics/virtual-maps-converted-float",
)
# The converted maps' fits (decision 092), made on virtual-maps-converted (PNG 16) and its
# OpenEXR 32f twin. Inputs: L the BaseColor channel's linear sRGB8 operand
# (`Srgb8OperandTable`), r and m the SpecularRoughness and BaseMetalness codes / 255, in float32;
# enc(x) = x <= 0.0031308 ? 12.92 x : fma(1.055, exp2(0.41666 log2 x), -0.055) with the
# recording GPU's exp2 and log2 (hwmath.h); toL(v) = fma(0.114, v, fma(0.299, v, 0.587 v)). The
# EXR holds the float32 result and the PNG its 16-bit write; an RGBA file loses an all-opaque
# alpha.
CONVERTED_FIT = (
    "Fitted exactly (decision 092): r1 = r2 on every texel of s0-s7 at PNG 16 and OpenEXR 32f, 0 "
    "differing values in each of the 16 comparisons. Inputs: L the BaseColor channel's linear "
    "sRGB8 operand, r and m the SpecularRoughness and BaseMetalness values, float32; enc is "
    "Painter 12.1.5's sRGB encode x <= 0.0031308 ? 12.92 x : fma(1.055, exp2(0.41666 log2 x), "
    "-0.055) with the recording GPU's exp2 and log2; toL(v) = fma(0.114, v, fma(0.299, v, "
    "0.587 v)). Where a channel has no layer the map reads L = 1.3, r = 0.5980393 (0x3F19191A) and "
    "m = 0, not the channel's base value. Still a release gap: the plan needs each channel's "
    "per-texel coverage (the evaluator gives none), and the uncovered constants were seen on one "
    "template only (recording R-092)."
)
CONVERTED_NOTES = {
    "Diffuse": f"Operator: enc(L (1 - m)), RGB. {CONVERTED_FIT}",
    "Specular": f"Operator: enc(fma(L - 0.04, m, 0.04)), RGB. {CONVERTED_FIT}",
    "Glossiness": f"Operator: toL(1 - r), linear. {CONVERTED_FIT}",
    "Glossiness2": f"Operator: g = 1 - r, toL(g g), linear. {CONVERTED_FIT}",
    "Unity4Diff": (
        "Operator: RGB enc(L); alpha the BaseColor channel's coverage (1 on a filled set, written "
        f"RGB; 0 without a layer, written RGBA). {CONVERTED_FIT}"
    ),
    "Unity4Gloss": (
        "Operator: RGB (m + (1 - r)) 0.5, linear; alpha the SpecularRoughness channel's coverage "
        f"(whether BaseMetalness's coverage also counts is not recorded). {CONVERTED_FIT}"
    ),
    "reflection": f"Operator: fma(enc(L) - 1, enc(m), 1), RGB. {CONVERTED_FIT}",
    "1/ior": (
        "Operator: k = 0.66666663 (0x3F2AAAAA), toL(fma(-k, m, k)), linear; k (1 - m) and "
        f"float32(2/3) miss. {CONVERTED_FIT}"
    ),
    "f0": f"Operator: fma(0.96, m, 0.04), grey RGB, linear. {CONVERTED_FIT}",
    "View_2D": (
        "Not fitted (decision 092): a shaded render, not an operator on the channels. It varies "
        "texel to texel without period where roughness is above 0, and differs between sets with "
        "identical inputs (s5 and s6 at 3 texels). It depends on the viewport's environment, "
        "lighting and sampling; its PNG 16 is the 16-bit write of its EXR 32f (0 differing). "
        "Release gap: it needs a reproduction of Painter's 2D view render."
    ),
}
AO_MIXED_NOTES = (
    "Not exact (decision 092). Recording R-086a (ao-mixed-opacity and its OpenEXR 32f twin, "
    "decision 087) shows AO_Mixed on the 8-bit lattice before encoding, step A = step B, and r1"
    " != r2 by one 8-bit step at 9 to 41 values per set, deterministically. Best model: alpha ="
    " the layer opacity's L16 code / 65535 and C = the fill's stored L16 code / 65535 "
    "(float32); c = fma(C - 1, alpha, 1), the AO channel before its L16 write (1 without a "
    "layer; WriteUnorm16(c) is the channel's export, 0 differing on r1); a = the AO mesh map "
    "code / 255; v = a c (float32); AO_Mixed = WriteUnorm(v, 8) (12 fractional bits, nearest, "
    "ties down). It misses r1 at 31 values over the three goldens (ao-mixed-opacity s0-s7 "
    "0/9/2/0/0/9/2/0, its twin the same, ao-mixed s0-s3 0/9/0/0), each within 3 ulps of v from "
    "a 2^-12 boundary; r2 misses more and is not explained. On the row where C = 0, c = 1 - "
    "alpha is exact in any order of operations, yet v must rise by 2 to 3 ulps, so no correctly"
    " rounded float32 evaluation of the tested inputs reproduces r1. Rejected: more than 40 "
    "orders of operations with and without fma, multiply blends over the mesh map, fixed-point "
    "(2^12 to 2^29) and half-float intermediates, a 16-bit intermediate, other conversions of "
    "a, C and alpha, and the recording GPU's measured exp2, log2 and reciprocal. Unknown: "
    "Painter's operand conversions or arithmetic on this path. Recording R-092 isolates them: a"
    " constant AO mesh map with a varying channel, a constant channel with a varying mesh map, "
    "values at the missed coordinates, and the same exports after reopen. Calibrated is not "
    "parity: the plan refuses AO_Mixed."
)


def publish(report: dict[str, Any]) -> dict[str, Any]:
    """The `virtual-maps.json` document of a `virtual_map_goldens` report: the supported maps
    with their residuals through the plan, every other documented virtual map a gap refused
    before writing."""
    entries = []
    corpus = sorted({f"tier0/{name}" for name in VIRTUAL_GOLDENS} | set(GAP_CORPUS))
    for name, (entry_id, components, meaning) in DOCUMENTED.items():
        residuals = [
            residual(g, key, recording, "16-bit code value", diff)
            for g, key, recording, diff in report["residuals"]
            if key.endswith("/" + name)
        ]
        supported = name in FORMULAS
        formula = FORMULAS.get(name, GAP_FORMULA)
        notes = AO_MIXED_NOTES if name == "AO_Mixed" else CONVERTED_NOTES.get(name)
        entries.append(
            entry(
                entry_id,
                f"{name}: {meaning}",
                formula,
                [PYDOC, HELP, *([D3D] if supported else [])],
                [parameter("components", components, "public_documentation")],
                residuals,
                notes,
                gap=not supported,
            )
        )
    return document(
        "virtual-maps",
        "The documented virtualMap sources of the export plan (src/export/virtual_maps.h, "
        "decision 086): the operators reproduced exactly through the plan (evaluated by "
        "EvaluateFileOn and written at 16 bits) and the documented maps without a golden yet.",
        corpus,
        entries,
        painter_build=str(current_envelope()["painter_build"]),
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python tests/export/tier0.py <uzp-export-tests.exe> <work-dir>", file=sys.stderr
        )
        return 2
    if locate() is None:
        print("oracle_unavailable: no private oracle store on this machine", file=sys.stderr)
        return 2
    report = virtual_map_goldens(Path(argv[0]), Path(argv[1]), REPO_ROOT)
    PUBLISHED.write_text(json.dumps(publish(report), indent=2) + "\n", encoding="utf-8")
    print(f"{PUBLISHED}: {report['maps']} maps, {len(report['differing'])} differing")
    return 0 if not report["differing"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
