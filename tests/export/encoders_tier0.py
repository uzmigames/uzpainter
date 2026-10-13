"""Tier 0 comparisons of phase1.16_export-processing-encoders
(`tests/export/test_export_encoders.py`; decisions 089 and 090), run on the owner's machine
against the private oracle store of the current envelope (decision 037). Nothing recorded leaves
memory or the store: the comparisons return counts, and `publish` writes only numbers to
`parity/semantics/export-processing.json` (CONTRACT §6.4).

- `reencode_painter_files`: every distinct PNG and OpenEXR file Painter exported in the current
  envelope, decoded at native depth and encoded again by UzPainter's writers
  (`uzp-export-tests reencode`): the bytes must be identical (items 2.6, 3.4).
- `export_goldens`: the goldens of `EXPORT_GOLDENS`, rebuilt per texture set on their mesh and
  written by `WriteExport` (`uzp-export-tests export`) with the recorder's configuration of each
  export step: the written files must be exactly the dry run's (item 3.5) and byte-identical to
  Painter's files of that step, on r1 and on r2 wherever r2 equals r1 (decision 032; items 3.1,
  3.3, 3.4).

Run as a script to regenerate the published file:

    python tests/export/encoders_tier0.py <uzp-export-tests.exe> <work-dir>
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from collections import defaultdict
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

from tests.evaluator.test_compositor_tile_dag import TEMPLATES_DIR
from tests.export.tier0 import export_spec, needs_store
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.common import document, entry, parameter, residual, source
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import Golden, load
from tools.parity.fit.stats import difference
from tools.parity.recorder.job import Step, export_step
from tools.parity.schemas import REGISTER_PATH, load_json
from tools.parity.store.store import OracleStore, Status, load_oracle, locate
from tools.parity.verdict import Comparison, evaluate

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = REPO_ROOT / "parity" / "semantics" / "export-processing.json"
MESHES = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes"

# golden (current envelope, tier0/...) -> its texture sets. Each is rebuilt by `export_spec` (fill
# and group layers, bound mesh maps) on the grid mesh it was recorded on, whose quads cover the
# whole UV tile, and every export step of the sequence is written.
EXPORT_GOLDENS: dict[str, tuple[str, ...]] = {
    "semantics/height-normal-plane-amplitudes": ("s0", "s1", "s2", "s3"),
    "semantics-ui/height-normal-sharp-plane-strength": tuple(f"s{i}" for i in range(8)),
    "semantics-ui/height-normal-sobel-plane-strength": tuple(f"s{i}" for i in range(8)),
}


def _run(args: list[str]) -> str:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=3600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def _envelope_goldens() -> list[Golden]:
    """Every golden of the current envelope with an export step."""
    store = locate()
    out = []
    for path in sorted(manifest_root(current_envelope()).rglob("*.json")):
        steps = json.loads(path.read_text(encoding="utf-8"))["instruction_sequence"]["steps"]
        if any(s["call"].endswith("export_project_textures") for s in steps):
            out.append(load(store, path))
    return out


def _blob_path(store: OracleStore, golden: Golden, blob: dict[str, Any]) -> Path:
    resolved = store.resolve("exported-map", str(blob["sha256"]), int(blob["size_bytes"]))
    assert resolved.status == Status.AVAILABLE and resolved.path is not None, resolved.reason
    return resolved.path


# ── Painter's files through UzPainter's encoders ─────────────────────────────


def reencode_painter_files(exe: Path, tmp: Path) -> dict[str, Any]:
    """Re-encodes every distinct exported PNG and OpenEXR file of the current envelope. Returns
    per format the files and the identical ones, the goldens that differ, and per golden and
    format the byte comparison (concatenated over its files) for the residuals."""
    needs_store()
    store = locate()
    assert store is not None
    paths: dict[str, Path] = {}
    goldens_of: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for golden in _envelope_goldens():
        for recording in golden.recordings.values():
            for output in recording.outputs.values():
                if output["kind"] != "exported_map":
                    continue
                sha = str(output["blob"]["sha256"])
                paths.setdefault(sha, _blob_path(store, golden, output["blob"]))
                goldens_of[sha].add((golden.golden_id, recording.recording_id))
    tmp.mkdir(parents=True, exist_ok=True)
    listing = tmp / "reencode.txt"
    shas = sorted(paths)
    listing.write_text("".join(f"{paths[s]}\n" for s in shas), encoding="utf-8")
    lines = _run([str(exe), "reencode", str(listing)]).splitlines()
    assert len(lines) == len(shas)
    report: dict[str, Any] = {
        "files": defaultdict(int),
        "identical": defaultdict(int),
        "differing": [],
    }
    per_golden: dict[tuple[str, str, str], list[bool]] = defaultdict(list)
    for sha, line in zip(shas, lines, strict=True):
        result = json.loads(line)
        fmt = str(result["format"])
        report["files"][fmt] += 1
        report["identical"][fmt] += int(result["equal"])
        if not result["equal"]:
            report["differing"].append(f"{sorted(goldens_of[sha])[0][0]} {fmt} {sha[:12]}")
        for golden_id, recording_id in goldens_of[sha]:
            per_golden[(golden_id, fmt, recording_id)].append(bool(result["equal"]))
    report["per_golden"] = {k: (len(v), sum(v)) for k, v in sorted(per_golden.items())}
    return report


# ── Painter's files through UzPainter's processing (phase1.18) ───────────────

# The sRGB8 material channels, exported sRGB-encoded to PNG (R-090 P10; decisions 091 and 126).
SRGB8_MATERIAL = ("basecolor", "specular", "emissive")
# export-bit-depth: the OpenEXR 32f step of each group, and its other steps (format, bit depth).
BIT_DEPTH_STEPS = {
    359: ((353, "png", "8"), (355, "png", "16"), (357, "exr", "16f")),  # document maps
    373: ((367, "png", "8"), (369, "png", "16"), (371, "exr", "16f")),  # mesh maps
}


def processing_cases(store: OracleStore) -> list[dict[str, Any]]:
    """The cases of `uzp-export-tests process` (decision 103), on r1 and on r2 of each golden, each
    case's source and target from the same recording (decision 032: r1 is the exact target, the
    residuals against r2 are published):

    - export-bit-depth: every map's OpenEXR 32f file as the raster of its PNG 8, PNG 16 and
      OpenEXR 16f files (R-090 P1, P2, P7), an sRGB8 material channel sRGB-encoded in a PNG (P10);
    - export-dither: every map's PNG 16 file without dithering as the raster of its PNG 16 file
      with dithering (R-090 P3);
    - export-alpha-layouts: the L+A and RGB+A OpenEXR 32f files as the rasters of their PNG 16
      files, an all-opaque alpha appended where Painter dropped it (R-090 P6)."""
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    cases: list[dict[str, Any]] = []

    def path(golden: Golden, recording: str, output_id: str) -> str:
        return str(_blob_path(store, golden, golden.output(recording, output_id)["blob"]))

    bit_depth = load(store, root / "export-bit-depth.json")
    dither = load(store, root / "export-dither.json")
    alpha = load(store, root / "export-alpha-layouts.json")
    for recording in ("r1", "r2"):
        for output_id in bit_depth.maps(recording):
            texture_set, name, step = output_id.split("/")
            group = BIT_DEPTH_STEPS.get(int(step.removeprefix("step")))
            if group is None:
                continue
            for target_step, fmt, depth in group:
                cases.append(
                    {
                        "golden": bit_depth.golden_id,
                        "recording": recording,
                        "source": path(bit_depth, recording, output_id),
                        "target": path(
                            bit_depth, recording, f"{texture_set}/{name}/step{target_step}"
                        ),
                        "format": fmt,
                        "bit_depth": depth,
                        "height": name == "height",
                        "srgb8_material": name in SRGB8_MATERIAL,
                    }
                )
        for output_id in dither.maps(recording):
            texture_set, name, step = output_id.split("/")
            # The PNG 16 source of an sRGB8 material channel holds encoded values.
            if step != "step106" or name in SRGB8_MATERIAL:
                continue
            cases.append(
                {
                    "golden": dither.golden_id,
                    "recording": recording,
                    "source": path(dither, recording, output_id),
                    "target": path(dither, recording, f"{texture_set}/{name}/step104"),
                    "format": "png",
                    "bit_depth": "16",
                    "dithering": True,
                    # The PNG 16 source of a Height map already holds its written values.
                    "height": False,
                }
            )
        for output_id in alpha.maps(recording):
            if not output_id.endswith(".exr"):
                continue
            source = alpha.map(recording, output_id)
            layout = output_id.rsplit("_", 1)[1].removesuffix(".exr")
            target = output_id.replace("s19", "s18").replace(".exr", ".png")
            cases.append(
                {
                    "golden": alpha.golden_id,
                    "recording": recording,
                    "source": path(alpha, recording, output_id),
                    "target": path(alpha, recording, target),
                    "format": "png",
                    "bit_depth": "16",
                    "append_opaque_alpha": source.values.shape[2] == {"la": 1, "rgba": 3}[layout],
                }
            )
    return cases


def process_painter_files(exe: Path, tmp: Path) -> dict[str, Any]:
    """Runs `processing_cases` through `uzp-export-tests process`. Returns per golden and recording
    the cases and the identical ones, the differing targets, and the written layouts."""
    needs_store()
    store = locate()
    assert store is not None
    cases = processing_cases(store)
    tmp.mkdir(parents=True, exist_ok=True)
    listing = tmp / "process.json"
    listing.write_text(json.dumps(cases), encoding="utf-8")
    lines = _run([str(exe), "process", str(listing)]).splitlines()
    assert len(lines) == len(cases)
    report: dict[str, Any] = {
        "cases": defaultdict(int),
        "identical": defaultdict(int),
        "differing": [],
        "layouts": defaultdict(int),
        "srgb8_cases": defaultdict(int),
        "srgb8_identical": defaultdict(int),
    }
    for case, line in zip(cases, lines, strict=True):
        result = json.loads(line)
        kind = f"{case['golden']} {case['format']} {case['bit_depth']} {case['recording']}"
        report["cases"][kind] += 1
        report["identical"][kind] += int(result["equal"])
        if case.get("srgb8_material"):
            report["srgb8_cases"][kind] += 1
            report["srgb8_identical"][kind] += int(result["equal"])
        report["layouts"][str(result["layout"])] += 1
        if not result["equal"]:
            report["differing"].append(f"{kind} {Path(case['target']).name[:12]}")
    return report


# ── `infinite` padding on UV islands (decision 223) ──────────────────────────

# The recorded `infinite` padding goldens whose UV islands leave texels uncovered.
PADDING_GOLDENS = (
    *(f"export-padding-ramp-{r}-{p}-v2" for r in ("r1", "r2", "r15") for p in ("p0", "p25", "p75")),
    "export-padding-tie-512",
    "export-padding-tie-2048-v2",
    "export-padding-tie-512-box16",
    "export-padding-ramp-r1-p0-box17",
    "export-padding-seam-ramp-1024",
    "export-padding",
    "export-padding-bevelled-cube",
    "export-padding-sphere",
    "export-padding-seam-256",
    "export-padding-seam-1024",
    "export-padding-seam-field-256",
    "export-padding-seam-field-1024",
)
# The P-ramp and P-tie probes hold each covered texel's own centre (u, v) in their first channels.
POSITION_PROBES = tuple(g for g in PADDING_GOLDENS if "-ramp-" in g or "-tie-" in g)


def padding_goldens(exe: Path, tmp: Path) -> dict[str, Any]:
    """Every r1 `infinite` file of `PADDING_GOLDENS`, padded by `uzp-export-tests process` from the
    map's OpenEXR 32f file over the golden's mesh: per file, whether the covered texels equal
    Painter's file exactly, whether the export's coverage equals `tools.parity.coverage`, and the
    padding texels' max |delta| (native units). Per position probe, the texels holding their own
    centre against that coverage."""
    from tools.parity.coverage import coverage, obj_triangles

    needs_store()
    store = locate()
    assert store is not None
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    cases: list[dict[str, Any]] = []
    meta: list[tuple[str, str, Path]] = []
    probes: dict[str, int] = {}
    tmp.mkdir(parents=True, exist_ok=True)
    for name in PADDING_GOLDENS:
        golden = load(store, root / f"{name}.json")
        mesh = _mesh_of(golden.manifest)
        steps = {s["step"]: s["args"] for s in golden.manifest["instruction_sequence"]["steps"]}
        outputs = golden.recordings["r1"].outputs
        infinite = {
            oid: o
            for oid, o in outputs.items()
            if o["kind"] == "exported_map"
            and steps[o["export_settings"]["step"]].get("padding") == "infinite"
        }
        sources = {
            (o["texture_set"], o["map"]): oid
            for oid, o in infinite.items()
            if o["storage_format"]["container"] == "exr"
            and o["storage_format"]["bits_per_channel"] == 32
        }
        for _, o in sorted(infinite.items()):
            source = sources[o["texture_set"], o["map"]]
            fmt = o["storage_format"]
            depth = "32f" if fmt["container"] == "exr" else str(fmt["bits_per_channel"])
            if fmt["container"] == "exr" and fmt["bits_per_channel"] == 16:
                depth = "16f"
            index = len(cases)
            cases.append(
                {
                    "source": str(_blob_path(store, golden, outputs[source]["blob"])),
                    "target": str(_blob_path(store, golden, o["blob"])),
                    "format": fmt["container"],
                    "bit_depth": depth,
                    "height": o["map"] == "height",
                    "srgb8_material": o["map"] in SRGB8_MATERIAL,
                    "mesh": str(mesh),
                    "material": str(o["texture_set"]).split("/")[0],
                    "out": str(tmp / f"{index}.{fmt['container']}"),
                    "coverage_out": str(tmp / f"{index}.coverage"),
                }
            )
            meta.append((name, f"{o['map']} {fmt['container']} {depth}", mesh))
        if name in POSITION_PROBES:
            values = golden.map("r1", next(iter(sources.values()))).values
            size = values.shape[0]
            y, x = np.mgrid[0:size, 0:size]
            own = (values[..., 0] == np.float32((x + 0.5) / size)) & (
                values[..., 1] == np.float32((y + 0.5) / size)
            )
            material = str(next(iter(sources))[0]).split("/")[0]
            covered = coverage(obj_triangles(mesh, material), size, size)
            probes[name] = int((own != covered).sum())
    listing = tmp / "padding.json"
    listing.write_text(json.dumps(cases), encoding="utf-8")
    lines = _run([str(exe), "process", str(listing)]).splitlines()
    assert len(lines) == len(cases)
    files: list[dict[str, Any]] = []
    for case, (name, label, mesh), line in zip(cases, meta, lines, strict=True):
        result = json.loads(line)
        ours = decode(Path(case["out"]).read_bytes()).values
        theirs = decode(Path(case["target"]).read_bytes()).values
        size = theirs.shape[:2]
        native = np.frombuffer(Path(case["coverage_out"]).read_bytes(), np.uint8).reshape(size) != 0
        covered = coverage(obj_triangles(mesh, case["material"]), size[1], size[0])
        delta = np.abs(ours.astype(np.float64) - theirs.astype(np.float64))
        files.append(
            {
                "golden": name,
                "file": label,
                "covered_texels": int(result["covered_texels"]),
                "coverage_equal": bool(np.array_equal(native, covered)),
                "covered_equal": bool(np.array_equal(ours[covered], theirs[covered])),
                "padding_max_abs_diff": float(delta[~covered].max()) if (~covered).any() else 0.0,
            }
        )
    return {"files": files, "position_probe_mismatches": probes}


# ── Goldens written by WriteExport ───────────────────────────────────────────


def _mesh_of(manifest: dict[str, Any]) -> Path:
    for s in manifest["instruction_sequence"]["steps"]:
        if s["call"].endswith("project.create"):
            return MESHES / f"{s['args']['mesh']}.obj"
    raise AssertionError(f"{manifest['golden_id']}: no project.create step")


def _painter_files(golden: Golden, recording: str, step: int, texture_set: str) -> dict[str, str]:
    """relativePath -> blob SHA-256 of the files Painter wrote for `texture_set` in `step` (the
    recorder names each `$textureSet_<map>` with its container's extension)."""
    files = {}
    for output in golden.recordings[recording].outputs.values():
        if output["kind"] != "exported_map" or output["export_settings"]["step"] != step:
            continue
        if str(output["texture_set"]).split("/")[0] != texture_set:
            continue
        extension = "exr" if output["storage_format"]["container"] == "exr" else "png"
        files[f"{texture_set}_{output['map']}.{extension}"] = str(output["blob"]["sha256"])
    return files


def write_export(
    exe: Path, spec: dict[str, Any], spec_dir: Path, config: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    """`uzp-export-tests export`: the plan, dry run and written files, or the refusal. The spec is
    written into `spec_dir`, where its resources are; the configuration into `run_dir`."""
    spec_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    out = _run(
        [
            str(exe),
            "export",
            str(TEMPLATES_DIR),
            str(spec_dir / "spec.json"),
            str(run_dir / "config.json"),
        ]
    )
    result: dict[str, Any] = json.loads(out)
    return result


def export_goldens(exe: Path, tmp: Path, runs: int = 1) -> dict[str, Any]:
    """Writes every export step of every texture set of `EXPORT_GOLDENS` `runs` times (each run in
    its own process and folder) and compares. Returns the counts, the problems and per file the
    decoded comparison with Painter (golden, `<set>/<map>`, recording, unit, Difference)."""
    needs_store()
    report: dict[str, Any] = {
        "steps": 0,
        "files": 0,
        "identical_to_painter": 0,
        "comparisons": 0,
        "problems": [],
        "residuals": [],
    }
    for name, texture_sets in EXPORT_GOLDENS.items():
        manifest_path = manifest_root(current_envelope()) / "tier0" / f"{name}.json"
        golden = load(locate(), manifest_path)
        manifest = golden.manifest
        steps = [
            s
            for s in manifest["instruction_sequence"]["steps"]
            if s["call"].endswith("export_project_textures")
        ]
        for texture_set in texture_sets:
            for raw in steps:
                workdir = tmp / name.replace("/", "_") / texture_set / str(raw["step"])
                spec = export_spec(manifest, texture_set, workdir / "spec")
                spec["mesh"] = str(_mesh_of(manifest))
                where = f"{golden.golden_id} {texture_set} step {raw['step']}"
                written_runs = []
                for run in range(runs):
                    out_dir = workdir / f"out{run}"
                    config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                        out_dir, [texture_set]
                    )
                    result = write_export(
                        exe, spec, workdir / "spec", config, workdir / f"run{run}"
                    )
                    if "error" in result:
                        report["problems"].append(
                            f"{where}: {result['error']}: {result['message']}"
                        )
                        break
                    # The dry run (list_project_textures) lists full paths under exportPath.
                    listed = {
                        Path(f).relative_to(out_dir).as_posix()
                        for _, _, files in result["list"]
                        for f in files
                    }
                    written = {f["relativePath"]: f for f in result["written"]}
                    on_disk = {
                        p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file()
                    }
                    if listed != set(written) or on_disk != set(written):
                        report["problems"].append(
                            f"{where}: dry run {sorted(listed)}, written {sorted(written)}, "
                            f"on disk {sorted(on_disk)}"
                        )
                    written_runs.append({k: (v["sha256"], out_dir / k) for k, v in written.items()})
                if len(written_runs) != runs:
                    continue
                report["steps"] += 1
                first = written_runs[0]
                for other in written_runs[1:]:
                    if {k: v[0] for k, v in other.items()} != {k: v[0] for k, v in first.items()}:
                        report["problems"].append(f"{where}: the runs wrote different bytes")
                theirs_r1 = _painter_files(golden, "r1", raw["step"], texture_set)
                if set(theirs_r1) != set(first):
                    report["problems"].append(
                        f"{where}: Painter wrote {sorted(theirs_r1)}, UzPainter {sorted(first)}"
                    )
                    continue
                for rel, (sha, path) in sorted(first.items()):
                    report["files"] += 1
                    ours = decode(path.read_bytes())
                    map_name = rel.rsplit(".", 1)[0].split("_", 1)[1]
                    key = f"{texture_set}/{map_name}"
                    for recording in ("r1", "r2"):
                        theirs_sha = _painter_files(
                            golden, recording, raw["step"], texture_set
                        ).get(rel)
                        if recording == "r2" and theirs_sha != theirs_r1[rel]:
                            continue  # an unstable recording: r1 is the target (decision 032)
                        report["comparisons"] += 1
                        if sha == theirs_sha:
                            report["identical_to_painter"] += 1
                        else:
                            report["problems"].append(
                                f"{where}: {rel} differs from Painter's {recording} bytes"
                            )
                        theirs = golden.map(recording, key)
                        unit = "16-bit code value" if ours.integer else "float32 value"
                        diff = difference(ours.values, theirs.values.reshape(ours.values.shape))
                        report["residuals"].append((golden.golden_id, key, recording, unit, diff))
    return report


# ── export-bit-depth's sRGB8 material channels written end to end (decision 126) ─

# export-bit-depth: the document-map steps of r1 (PNG 8, PNG 16, OpenEXR 16f, OpenEXR 32f).
SRGB8_STEPS = (353, 355, 357, 359)
SRGB8_CHANNELS = ("BaseColor", "Specular", "Emissive")


def _f32(value: float) -> float:
    return float(np.float32(value))


def srgb_to_working(value: float) -> float:
    """A uniform colour component in the sRGB space as the working value every path stores on a
    colour-managed channel (`evaluator::PainterLegacySrgbDecode` through `python::WorkingColour`,
    decisions 214 and 240), an independent mirror of it:
    float32 operands, products with the float32 reciprocals 1.0f / 12.92f and 1.0f / 1.055f, the
    power rounded once to float32."""
    x = _f32(value)
    if x <= _f32(0.04045):
        return _f32(x * _f32(1.0 / _f32(12.92)))
    base = _f32(_f32(x + _f32(0.055)) * _f32(1.0 / _f32(1.055)))
    return _f32(base ** _f32(2.4))


def working_colours(manifest: dict[str, Any]) -> dict[str, Any]:
    """`manifest` reduced to its sRGB8 material channels' sources (the other channels' sources
    dropped: they are not exported here), with every uniform colour given in the sRGB space (or in
    none: Painter's default there) replaced by its working value, as the facade stores it
    (decision 107): the evaluator takes a stored colour as linear. A bitmap on Specular or
    Emissive without a colour space takes sRGB: Painter's OpenEXR 32f files of both equal
    BaseColor's (whose default is sRGB) texel for texel on every set filled from the same bitmap
    (s0, s1, s4, s5)."""
    steps = []
    for raw in manifest["instruction_sequence"]["steps"]:
        args = raw.get("args", {})
        channel = args.get("channel")
        if raw["call"].endswith("set_source") and channel not in (None, *SRGB8_CHANNELS):
            continue  # a mask's source (channel None) stays
        if raw["call"].endswith("set_source") and args.get("channel") in SRGB8_CHANNELS:
            if "color" in args and args.get("color_space", "sRGB") == "sRGB":
                colour = [srgb_to_working(float(c)) for c in args["color"]]
                raw = dict(raw, args=dict(args, color=colour, color_space="Working"))
            elif "resource_step" in args and "color_space" not in args:
                raw = dict(raw, args=dict(args, color_space="sRGB"))
        steps.append(raw)
    return dict(manifest, instruction_sequence=dict(manifest["instruction_sequence"], steps=steps))


def _add_template_channels(spec: dict[str, Any]) -> None:
    """The stack holds the default template's channels (BaseColor among them) and the added ones."""
    added = {c["type"] for c in spec["channels"]}
    spec["channels"] += [
        {"type": c["type"], "format": c["format"]}
        for c in json.loads((TEMPLATES_DIR / "default.json").read_text(encoding="utf-8"))[
            "channels"
        ]
        if c["type"] not in added
    ]


def _semantics_golden(stem: str) -> Golden:
    needs_store()
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    return load(locate(), root / f"{stem}.json")


def _set_spec(
    manifest: dict[str, Any],
    texture_set: str,
    spec_dir: Path,
    *,
    template_channels: bool = False,
    ocio: bool = False,
) -> dict[str, Any]:
    """`export_spec` of `texture_set` on the grid mesh it was recorded on; with the default
    template's channels added, and as an OCIO project with Painter's substance config."""
    spec = export_spec(manifest, texture_set, spec_dir)
    spec["mesh"] = str(_mesh_of(manifest))
    if template_channels:
        _add_template_channels(spec)
    if ocio:
        spec["color_management"] = "ocio"
        spec["config_hash"] = OCIO_CONFIG_SHA256
    return spec


def _bit_depth_golden() -> tuple[Golden, dict[str, Any]]:
    """export-bit-depth and its sequence with the colours the facade stores (`working_colours`)."""
    golden = _semantics_golden("export-bit-depth")
    return golden, working_colours(golden.manifest)


def srgb8_material_written(exe: Path, tmp: Path) -> dict[str, Any]:
    """export-bit-depth's BaseColor, Specular and Emissive maps (bitmaps, uniform colours, empty
    channels over their linear template constants) rebuilt per texture set on the grid mesh and
    written by `WriteExport` at PNG 8, PNG 16, OpenEXR 16f and OpenEXR 32f: compared byte for
    byte with Painter's files of r1, and of r2 wherever r2 equals r1 (decision 032). Returns the
    counts and the differing files or refusals."""
    golden, manifest = _bit_depth_golden()
    by_step = {s["step"]: s for s in manifest["instruction_sequence"]["steps"]}
    report: dict[str, Any] = {
        "files": 0,
        "comparisons": 0,
        "identical": 0,
        "problems": [],
    }
    for texture_set in sorted({k.split("/")[0] for k in golden.maps("r1")}):
        spec_dir = tmp / texture_set / "spec"
        spec = _set_spec(manifest, texture_set, spec_dir, template_channels=True)
        for step in SRGB8_STEPS:
            raw = by_step[step]
            out_dir = tmp / texture_set / f"out{step}"
            config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                out_dir, [texture_set]
            )
            preset = config["exportPresets"][0]
            preset["maps"] = [
                m for m in preset["maps"] if m["fileName"].rsplit("_", 1)[1] in SRGB8_MATERIAL
            ]
            result = write_export(exe, spec, spec_dir, config, tmp / texture_set / f"run{step}")
            where = f"{texture_set} step {step}"
            if "error" in result:
                report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                continue
            theirs_r1 = _painter_files(golden, "r1", step, texture_set)
            theirs_r2 = _painter_files(golden, "r2", step, texture_set)
            for written in result["written"]:
                rel = written["relativePath"]
                report["files"] += 1
                for recording, theirs in (("r1", theirs_r1), ("r2", theirs_r2)):
                    if recording == "r2" and theirs_r2.get(rel) != theirs_r1.get(rel):
                        continue
                    report["comparisons"] += 1
                    if written["sha256"] == theirs.get(rel):
                        report["identical"] += 1
                    else:
                        report["problems"].append(f"{where}: {rel} differs from {recording}")
    return report


# The OpenEXR exports of an empty base on a shipped template (decisions 168, 169, 172): every
# `export-template-base-*` golden (plane, BaseColor and Specular where the template has them,
# OpenEXR 32f then PNG 16, each twice), and the empty set s7 of three float virtual-map twins
# (decision 093): golden stem, texture set, export steps, and the maps or None for every base map
# Painter wrote.
TEMPLATE_BASE_MAPS = ("basecolor", "specular")
TWIN_BASE_FILES = (
    ("virtual-maps-template-openpbr-coat-float", "s7", (84, 85), ("basecolor",)),
    (
        "virtual-maps-template-pbr-metallic-roughness-alpha-blend-float",
        "s7",
        (84, 85),
        ("basecolor",),
    ),
    ("virtual-maps-template-pbr-specular-glossiness-float", "s7", (84, 85), ("specular",)),
)


def template_base_files() -> list[tuple[str, str, tuple[int, ...], tuple[str, ...] | None]]:
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    stems = sorted(p.stem for p in root.glob("export-template-base-*.json"))
    return [(stem, "uzp_plane", (2, 3, 4, 5), None) for stem in stems] + list(TWIN_BASE_FILES)


def template_bases_written(exe: Path, tmp: Path) -> dict[str, Any]:
    """The empty texture set of each `template_base_files` golden, on its mesh and its shipped
    template (no layer: the channel is its template base), written by `WriteExport` one base map
    per file at each export step: compared byte for byte with Painter's files of r1, and of r2
    wherever r2 equals r1 (decision 032). Returns the counts, the differing files or evaluation
    failures (`problems`) and the files refused before writing (`refused`: where, message)."""
    needs_store()
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    templates = {
        document["painter_template"]: document
        for document in (
            json.loads(p.read_text(encoding="utf-8")) for p in TEMPLATES_DIR.glob("*.json")
        )
        if document["kind"] == "project" and document["painter_template"] is not None
    }
    report: dict[str, Any] = {
        "files": 0,
        "comparisons": 0,
        "identical": 0,
        "problems": [],
        "refused": [],
    }
    for stem, texture_set, steps, maps in template_base_files():
        golden = load(locate(), root / f"{stem}.json")
        manifest = golden.manifest
        by_step = {s["step"]: s for s in manifest["instruction_sequence"]["steps"]}
        create = by_step[1]["args"]
        template = templates[create["template"]]
        mesh = next(i["path"] for i in manifest["inputs"] if i["input_id"] == create["mesh"])
        spec = {
            "template": template["id"],
            "resolution": [create["default_texture_resolution"]] * 2,
            "channels": [{"type": c["type"], "format": c["format"]} for c in template["channels"]],
            "resources": [],
            "layers": [],
            "outputs": [],
            "name": texture_set,
            "mesh": str(REPO_ROOT / mesh),
            "mesh_maps": {},
            "height_to_normal_method": "Sharp",
        }
        for step in steps:
            raw = by_step[step]
            theirs_r1 = _painter_files(golden, "r1", step, texture_set)
            theirs_r2 = _painter_files(golden, "r2", step, texture_set)
            written_maps = maps or tuple(
                m
                for m in TEMPLATE_BASE_MAPS
                if any(rel.rsplit(".", 1)[0].endswith(f"_{m}") for rel in theirs_r1)
            )
            for base_map in written_maps:
                work = tmp / stem / f"{step}-{base_map}"
                config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                    work / "out", [texture_set]
                )
                preset = config["exportPresets"][0]
                preset["maps"] = [
                    m for m in preset["maps"] if m["fileName"].endswith(f"_{base_map}")
                ]
                result = write_export(exe, spec, work / "spec", config, work / "run")
                where = f"{stem} {texture_set} step {step} {base_map}"
                if result.get("error") == "NotYetSupported":
                    report["refused"].append((where, result["message"]))
                    continue
                if "error" in result:
                    report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                    continue
                for written in result["written"]:
                    rel = written["relativePath"]
                    report["files"] += 1
                    for recording, theirs in (("r1", theirs_r1), ("r2", theirs_r2)):
                        if recording == "r2" and theirs_r2.get(rel) != theirs_r1.get(rel):
                            continue
                        report["comparisons"] += 1
                        if written["sha256"] == theirs.get(rel):
                            report["identical"] += 1
                        else:
                            report["problems"].append(f"{where}: {rel} differs from {recording}")
    return report


# export-l8-material (decision 204): BaseColor edited to L8, Specular and Emissive added as L8,
# filled per set (s3 empty), the three maps as RGB and as L at PNG 8 (steps 40-43), PNG 16 (44-47)
# and OpenEXR 32f (48-51), each export twice.
L8_MATERIAL_SETS = ("s0", "s1", "s2", "s3")
L8_MATERIAL_STEPS = tuple(range(40, 52))


def _l8_material_golden() -> tuple[Golden, dict[str, Any]]:
    """export-l8-material and its sequence as the evaluator builds it: the BaseColor edit an L8
    channel of the stack, every uniform colour in the sRGB space as the facade stores it, each grey
    bitmap in the sRGB space (Painter's files of s0 and s1 hold the bitmaps' codes decoded,
    decision 208)."""
    golden = _semantics_golden("export-l8-material")
    sequence = golden.manifest["instruction_sequence"]
    steps = []
    for raw in sequence["steps"]:
        args = raw.get("args", {})
        if raw["call"].endswith("Stack.edit_channel"):
            raw = dict(raw, call="substance_painter.textureset.Stack.add_channel")
        elif raw["call"].endswith("set_source") and "color" in args:
            colour = [srgb_to_working(float(c)) for c in args["color"]]
            raw = dict(raw, args=dict(args, color=colour, color_space="Working"))
        elif raw["call"].endswith("set_source") and "resource_step" in args:
            raw = dict(raw, args=dict(args, color_space="sRGB"))
        steps.append(raw)
    return golden, dict(golden.manifest, instruction_sequence=dict(sequence, steps=steps))


def l8_material_written(exe: Path, tmp: Path) -> dict[str, Any]:
    """export-l8-material's sets rebuilt on the grid mesh (`_l8_material_golden`) and written by
    `WriteExport` at every export step: compared byte for byte with Painter's files of r1, and of
    r2 wherever r2 equals r1 (decision 032). Returns the counts, the differing files or
    evaluation failures (`problems`) and per set the first refusal of its evaluation (`refused`:
    set, message)."""
    golden, manifest = _l8_material_golden()
    by_step = {s["step"]: s for s in manifest["instruction_sequence"]["steps"]}
    report: dict[str, Any] = {
        "files": 0,
        "comparisons": 0,
        "identical": 0,
        "problems": [],
        "refused": [],
    }
    for texture_set in L8_MATERIAL_SETS:
        spec_dir = tmp / texture_set / "spec"
        spec = export_spec(manifest, texture_set, spec_dir)
        spec["mesh"] = str(_mesh_of(manifest))
        _add_template_channels(spec)
        for step in L8_MATERIAL_STEPS:
            raw = by_step[step]
            out_dir = tmp / texture_set / f"out{step}"
            config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                out_dir, [texture_set]
            )
            result = write_export(exe, spec, spec_dir, config, tmp / texture_set / f"run{step}")
            where = f"{texture_set} step {step}"
            if "unsupported_source" in result.get("message", ""):
                report["refused"].append((texture_set, result["message"]))
                break
            if "error" in result:
                report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                continue
            theirs_r1 = _painter_files(golden, "r1", step, texture_set)
            theirs_r2 = _painter_files(golden, "r2", step, texture_set)
            for written in result["written"]:
                rel = written["relativePath"]
                report["files"] += 1
                for recording, theirs in (("r1", theirs_r1), ("r2", theirs_r2)):
                    if recording == "r2" and theirs_r2.get(rel) != theirs_r1.get(rel):
                        continue
                    report["comparisons"] += 1
                    if written["sha256"] == theirs.get(rel):
                        report["identical"] += 1
                    else:
                        report["problems"].append(f"{where}: {rel} differs from {recording}")
    return report


# export-l8-material's OpenEXR 32f steps and the PNG steps they are the raster of: RGB (48) for
# PNG 8 (40) and PNG 16 (44), L (50) for PNG 8 (42) and PNG 16 (46).
L8_PROCESSING_STEPS = {48: ((40, "8"), (44, "16")), 50: ((42, "8"), (46, "16"))}


def l8_material_processed(exe: Path, tmp: Path) -> dict[str, Any]:
    """Painter's own OpenEXR 32f file of each export-l8-material map (every set, BaseColor,
    Specular and Emissive, RGB and L) as the raster of its PNG 8 and PNG 16 files, encoded by
    `uzp-export-tests process` with the L8 material channel's encode (`SrgbEncodedRead`): each
    case's source and target from the same recording, r1 and r2. Returns the counts and the
    differing targets."""
    needs_store()
    store = locate()
    assert store is not None
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    golden = load(store, root / "export-l8-material.json")

    def path(recording: str, output_id: str) -> str:
        return str(_blob_path(store, golden, golden.output(recording, output_id)["blob"]))

    cases = [
        {
            "recording": recording,
            "source": path(recording, f"{key}/step{step}"),
            "target": path(recording, f"{key}/step{target}"),
            "format": "png",
            "bit_depth": depth,
            "l8_material": True,
            "where": f"{recording} {key} step {target}",
        }
        for recording in ("r1", "r2")
        for key in (f"{t}/{m}" for t in L8_MATERIAL_SETS for m in SRGB8_MATERIAL)
        for step, targets in L8_PROCESSING_STEPS.items()
        for target, depth in targets
    ]
    tmp.mkdir(parents=True, exist_ok=True)
    listing = tmp / "process-l8.json"
    listing.write_text(json.dumps(cases), encoding="utf-8")
    lines = _run([str(exe), "process", str(listing)]).splitlines()
    assert len(lines) == len(cases)
    report: dict[str, Any] = {
        "cases": len(cases),
        "identical": 0,
        "layouts": defaultdict(int),
        "differing": [],
    }
    for case, line in zip(cases, lines, strict=True):
        result = json.loads(line)
        report["identical"] += int(result["equal"])
        report["layouts"][str(result["layout"])] += 1
        if not result["equal"]:
            report["differing"].append(case["where"])
    return report


# export-ocio-encode-legacy: the authored 8-bit sRGB ramp at 1:1 on BaseColor in the sRGB space
# (s3), in Raw (s4) and in the sRGB space inside a group masked by grey A (s5), exported at PNG 16,
# PNG 8 and OpenEXR 32f (sources.h).
SRGB8_BITMAP_SETS = ("s3", "s4", "s5")
SRGB8_BITMAP_STEPS = (46, 47, 48)


def _legacy_bitmap_golden() -> tuple[Golden, dict[str, Any]]:
    """export-ocio-encode-legacy and its sequence without the colour-space listings (readbacks: the
    stack does not depend on them)."""
    golden = _semantics_golden("export-ocio-encode-legacy")
    sequence = golden.manifest["instruction_sequence"]
    built = [s for s in sequence["steps"] if not s["call"].endswith("list_available_color_spaces")]
    return golden, dict(golden.manifest, instruction_sequence=dict(sequence, steps=built))


def srgb8_bitmap_written(exe: Path, tmp: Path) -> dict[str, Any]:
    """export-ocio-encode-legacy's BaseColor of `SRGB8_BITMAP_SETS` rebuilt per texture set on the
    grid mesh and written by `WriteExport` at each step of `SRGB8_BITMAP_STEPS`: compared byte for
    byte with Painter's files of r1, and of r2 wherever r2 equals r1. Painter is unstable on s5
    (decision 032): r1 is its exact target, and a file whose r2 differs from r1 is judged against
    r2 through the exception register (`tools/parity/verdict.py`), its outcome and the entries
    relied on listed in `register`. Returns the counts and the differing files or refusals."""
    golden, manifest = _legacy_bitmap_golden()
    by_step = {s["step"]: s for s in golden.manifest["instruction_sequence"]["steps"]}
    entries = load_json(REGISTER_PATH)["entries"]
    report: dict[str, Any] = {
        "files": 0,
        "comparisons": 0,
        "identical": 0,
        "register": [],
        "problems": [],
    }
    for texture_set in SRGB8_BITMAP_SETS:
        spec_dir = tmp / texture_set / "spec"
        spec = _set_spec(manifest, texture_set, spec_dir)
        for step in SRGB8_BITMAP_STEPS:
            raw = by_step[step]
            out_dir = tmp / texture_set / f"out{step}"
            config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                out_dir, [texture_set]
            )
            preset = config["exportPresets"][0]
            preset["maps"] = [m for m in preset["maps"] if m["fileName"].endswith("_basecolor")]
            result = write_export(exe, spec, spec_dir, config, tmp / texture_set / f"run{step}")
            where = f"{texture_set} step {step}"
            if "error" in result:
                report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                continue
            theirs_r1 = _painter_files(golden, "r1", step, texture_set)
            theirs_r2 = _painter_files(golden, "r2", step, texture_set)
            for written in result["written"]:
                rel = written["relativePath"]
                report["files"] += 1
                for recording, theirs in (("r1", theirs_r1), ("r2", theirs_r2)):
                    if recording == "r2" and theirs_r2.get(rel) != theirs_r1.get(rel):
                        ours = decode(Path(written["path"]).read_bytes()).values
                        key = f"{texture_set}/basecolor/step{step}"
                        verdicts = [
                            evaluate(
                                Comparison(
                                    "0",
                                    str(golden.manifest["domain"]),
                                    golden.map(r, key).values.reshape(ours.shape),
                                    ours,
                                    oracle_stable=False,
                                    exact_target=r == "r1",
                                ),
                                entries,
                            )
                            for r in ("r1", "r2")
                        ]
                        report["register"].append(
                            (
                                where,
                                rel,
                                [v.outcome.value for v in verdicts],
                                sorted({e for v in verdicts for e in v.exceptions_relied_on}),
                            )
                        )
                        continue
                    report["comparisons"] += 1
                    if written["sha256"] == theirs.get(rel):
                        report["identical"] += 1
                    else:
                        report["problems"].append(f"{where}: {rel} differs from {recording}")
    return report


# export-ocio-encode (Session O, decision 180): R5 under OCIO with Painter's substance config, the
# sets of its Legacy twin (decision 190). Steps 46-49 write every map of each set at PNG 16, PNG 8,
# OpenEXR 32f (BaseColor) and PNG 16 (Normal_OpenGL); the probes 50 and 51 name the PNG 16 and 8
# files with $colorSpace.
OCIO_CONFIG_SHA256 = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
OCIO_ENCODE_SETS = tuple(f"s{i}" for i in range(8))
OCIO_ENCODE_STEPS = (46, 47, 48, 49)
OCIO_PROBE_STEPS = {
    50: "probe-colour-space-colour-space-png16",
    51: "probe-colour-space-colour-space-png8",
}


def _ocio_encode_golden() -> tuple[Golden, dict[str, Any]]:
    """export-ocio-encode and its sequence without the colour-space listings (readbacks), every
    uniform colour in the sRGB space (or in none: Painter's default on BaseColor) given as its
    working value."""
    golden = _semantics_golden("export-ocio-encode")
    sequence = golden.manifest["instruction_sequence"]
    steps = []
    for raw in sequence["steps"]:
        args = raw.get("args", {})
        if raw["call"].endswith("list_available_color_spaces"):
            continue  # readbacks: the stack does not depend on them
        if (
            raw["call"].endswith("set_source")
            and args.get("channel") in SRGB8_CHANNELS
            and "color" in args
            and args.get("color_space", "sRGB") == "sRGB"
        ):
            colour = [srgb_to_working(float(c)) for c in args["color"]]
            raw = dict(raw, args=dict(args, color=colour, color_space="Working"))
        steps.append(raw)
    return golden, dict(golden.manifest, instruction_sequence=dict(sequence, steps=steps))


def ocio_encode_written(exe: Path, tmp: Path) -> dict[str, Any]:
    """export-ocio-encode rebuilt per texture set on the grid mesh as an OCIO project with Painter's
    substance config and written by `WriteExport`: every map of steps 46-49, and the probe
    configurations of steps 50 and 51 (`$colorSpace` in the names), compared byte for byte with
    Painter's files of r1, and of r2 wherever r2 equals r1 (decision 032: r1 is the exact target
    of a file whose r2 differs, listed in `unstable`). Uniform colours in the sRGB space (or in
    none, Painter's default on BaseColor) are given as their working values (`working_colours`).
    The probes' written names are compared with Painter's listing (`names`). Returns the counts
    and the differing files or refusals."""
    golden, manifest = _ocio_encode_golden()
    by_step = {s["step"]: s for s in golden.manifest["instruction_sequence"]["steps"]}
    inputs = {i["input_id"]: REPO_ROOT / i["path"] for i in golden.manifest["inputs"]}
    report: dict[str, Any] = {
        "files": 0,
        "comparisons": 0,
        "identical": 0,
        "names": 0,
        "unstable": [],
        "problems": [],
    }

    def compare(where: str, written: dict[str, Any], r1: str | None, r2: str | None) -> None:
        report["files"] += 1
        for recording, theirs in (("r1", r1), ("r2", r2)):
            if recording == "r2" and r2 != r1:
                report["unstable"].append(f"{where}: {written['relativePath']}")
                continue
            report["comparisons"] += 1
            if theirs is not None and written["sha256"] == theirs:
                report["identical"] += 1
            else:
                report["problems"].append(
                    f"{where}: {written['relativePath']} differs from {recording}"
                )

    for texture_set in OCIO_ENCODE_SETS:
        spec_dir = tmp / texture_set / "spec"
        spec = _set_spec(manifest, texture_set, spec_dir, ocio=True)
        for step in OCIO_ENCODE_STEPS:
            raw = by_step[step]
            config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                tmp / texture_set / f"out{step}", [texture_set]
            )
            result = write_export(exe, spec, spec_dir, config, tmp / texture_set / f"run{step}")
            where = f"{texture_set} step {step}"
            if "error" in result:
                report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                continue
            theirs_r1 = _painter_files(golden, "r1", step, texture_set)
            theirs_r2 = _painter_files(golden, "r2", step, texture_set)
            if sorted(w["relativePath"] for w in result["written"]) != sorted(theirs_r1):
                report["problems"].append(
                    f"{where}: written {result['written']} vs {sorted(theirs_r1)}"
                )
            for written in result["written"]:
                rel = written["relativePath"]
                compare(where, written, theirs_r1.get(rel), theirs_r2.get(rel))
        for step, input_id in OCIO_PROBE_STEPS.items():
            config = json.loads(inputs[input_id].read_text(encoding="utf-8"))
            config["exportList"] = [e for e in config["exportList"] if e["rootPath"] == texture_set]
            config["exportPath"] = str(tmp / texture_set / f"out{step}")
            result = write_export(exe, spec, spec_dir, config, tmp / texture_set / f"run{step}")
            where = f"{texture_set} probe {step}"
            if "error" in result:
                report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                continue
            listed = golden.recordings["r1"].outputs[f"probe/s{step}/list"]["value"][texture_set]
            if [w["relativePath"] for w in result["written"]] != listed:
                report["problems"].append(f"{where}: names {result['written']} vs {listed}")
            else:
                report["names"] += len(listed)
            for written in result["written"]:
                rel = written["relativePath"]
                files = []
                for recording in ("r1", "r2"):
                    output = golden.recordings[recording].outputs.get(f"probe/s{step}/{rel}")
                    files.append(None if output is None else str(output["blob"]["sha256"]))
                compare(where, written, files[0], files[1])
    return report


# srgb-bitmap-variants-v2 (decisions 156, 166, 167, 174): one export step of each kind (PNG 16,
# PNG 8, OpenEXR 32f; each was done twice, the repeats identical).
SRGB_VARIANT_STEPS = (78, 80, 82)
# Sets whose every map is compared: s0 the 8-bit grey ramp at 1:1, s2 BilinearHQ magnification
# (scale 0.5) and s3 Nearest at scale 2 of field A (16-bit) on BaseColor and srgb8-ramp (8-bit)
# on Emissive, s4 field A and grey A on the six user channels whose sRGB Painter refused (they
# stay Data), s5 BaseColor under a mask whose grey A source stays Data (r1 only: Painter is
# unstable there, decision 032), s6-s8 field A on BaseColor in Working, Legacy Linear and
# Legacy sRGB.
SRGB_VARIANT_SETS = ("s0", "s2", "s3", "s4", "s5", "s6", "s7", "s8")
# s1: BilinearHQ minification (scale 2) at 30 degrees, refused for every bitmap (decisions 061,
# 084).
SRGB_VARIANT_REFUSED = {"s1": "at a rotation of 30.000000 degrees is a release gap"}


def _variants_golden() -> tuple[Golden, dict[str, Any]]:
    """srgb-bitmap-variants-v2 and its sequence without the colour-space listings (readbacks) and
    the `set_color_space` steps Painter refused (recorded as not applied: they left Painter's
    project unchanged)."""
    golden = _semantics_golden("srgb-bitmap-variants-v2")
    store = locate()
    assert store is not None
    reference = next(
        r for r in golden.manifest["private_records"] if r["record_id"] == "golden-record"
    )
    data = load_oracle(store, reference)
    assert data is not None, "srgb-bitmap-variants-v2: the golden record is not in the store"
    record = json.loads(data.decode("utf-8"))
    attempted = record["key"]["effective_defaults"]["set_color_space"]
    refused = {int(step) for step, outcome in attempted.items() if not outcome["applied"]}
    sequence = golden.manifest["instruction_sequence"]
    built = []
    for raw in sequence["steps"]:
        if raw["call"].endswith("list_available_color_spaces") or raw["step"] in refused:
            continue
        args = raw["args"]
        if raw["call"].endswith("set_source") and "color" in args:
            # s5's uniform BaseColor in the sRGB space, stored as its working value (the facade's
            # rule, decision 107): the evaluator takes a stored colour as linear.
            assert args["color_space"] == "sRGB" and args["channel"] in SRGB8_CHANNELS, raw
            colour = [srgb_to_working(float(c)) for c in args["color"]]
            raw = dict(raw, args=dict(args, color=colour, color_space="Working"))
        built.append(raw)
    return golden, dict(golden.manifest, instruction_sequence=dict(sequence, steps=built))


def srgb_variants_written(exe: Path, tmp: Path) -> dict[str, Any]:
    """srgb-bitmap-variants-v2 rebuilt per texture set on the grid mesh and written by
    `WriteExport` at each step of `SRGB_VARIANT_STEPS`, every map of the step: compared byte for
    byte with Painter's files of r1, and of r2 wherever r2 equals r1 (decision 032). Returns the
    counts, the refused sets with their messages, the files whose r2 differs from r1
    (`unstable`), and the differing files or refusals."""
    golden, manifest = _variants_golden()
    by_step = {s["step"]: s for s in golden.manifest["instruction_sequence"]["steps"]}
    report: dict[str, Any] = {
        "files": 0,
        "comparisons": 0,
        "identical": 0,
        "refused": {},
        "unstable": [],
        "problems": [],
    }
    for texture_set in (*SRGB_VARIANT_SETS, *SRGB_VARIANT_REFUSED):
        spec_dir = tmp / texture_set / "spec"
        spec = _set_spec(manifest, texture_set, spec_dir, template_channels=True)
        for step in SRGB_VARIANT_STEPS:
            raw = by_step[step]
            config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                tmp / texture_set / f"out{step}", [texture_set]
            )
            result = write_export(exe, spec, spec_dir, config, tmp / texture_set / f"run{step}")
            where = f"{texture_set} step {step}"
            if "error" in result:
                report["refused"].setdefault(texture_set, result["message"])
                if texture_set not in SRGB_VARIANT_REFUSED:
                    report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                continue
            if texture_set in SRGB_VARIANT_REFUSED:
                report["problems"].append(f"{where}: written, expected a refusal")
                continue
            theirs_r1 = _painter_files(golden, "r1", step, texture_set)
            theirs_r2 = _painter_files(golden, "r2", step, texture_set)
            for written in result["written"]:
                rel = written["relativePath"]
                report["files"] += 1
                for recording, theirs in (("r1", theirs_r1), ("r2", theirs_r2)):
                    if recording == "r2" and theirs_r2.get(rel) != theirs_r1.get(rel):
                        report["unstable"].append(f"{where}: {rel}")
                        continue
                    report["comparisons"] += 1
                    if written["sha256"] == theirs.get(rel):
                        report["identical"] += 1
                    else:
                        report["problems"].append(f"{where}: {rel} differs from {recording}")
    return report


# srgb-bitmap-minification (decisions 174 item 6, 198): one export step of each kind (PNG 16,
# PNG 8, OpenEXR 32f; each was done twice, the repeats identical). s0-s3 the 8-bit srgb8-ramp and
# s4-s7 field A (16-bit) in sRGB on BaseColor, BilinearHQ then BilinearSharp at scales 2 and 4,
# rotation 0, Repeat. Field A's sets and the 8-bit ramp's at scale 2 (s0, s2: the sRGB8 texture
# read on level 0 only, decision 219) are compared; the ramp's at scale 4 (s1, s3) read its mip
# levels, which are not measured, and are refused.
SRGB_MINIFY_STEPS = (36, 38, 40)
SRGB_MINIFY_SETS = ("s0", "s2", "s4", "s5", "s6", "s7")
SRGB_MINIFY_REFUSED = ("s1", "s3")


def _minification_golden() -> tuple[Golden, dict[str, Any]]:
    """srgb-bitmap-minification and its sequence (every step builds the stack)."""
    golden = _semantics_golden("srgb-bitmap-minification")
    return golden, golden.manifest


def srgb_minification_written(exe: Path, tmp: Path) -> dict[str, Any]:
    """srgb-bitmap-minification rebuilt per texture set on the grid mesh and written by
    `WriteExport` at each step of `SRGB_MINIFY_STEPS`: the sets of `SRGB_MINIFY_SETS` compared byte
    for byte with Painter's files of r1 and r2 (the golden is stable), those of
    `SRGB_MINIFY_REFUSED` expected to be refused. Returns the counts, the refusal messages and the
    differing files or unexpected outcomes."""
    golden, manifest = _minification_golden()
    by_step = {s["step"]: s for s in manifest["instruction_sequence"]["steps"]}
    report: dict[str, Any] = {
        "files": 0,
        "comparisons": 0,
        "identical": 0,
        "refused": {},
        "problems": [],
    }
    for texture_set in (*SRGB_MINIFY_SETS, *SRGB_MINIFY_REFUSED):
        spec_dir = tmp / texture_set / "spec"
        spec = _set_spec(manifest, texture_set, spec_dir, template_channels=True)
        for step in SRGB_MINIFY_STEPS:
            raw = by_step[step]
            config = export_step(Step(raw["step"], raw["call"], raw["args"])).config(
                tmp / texture_set / f"out{step}", [texture_set]
            )
            result = write_export(exe, spec, spec_dir, config, tmp / texture_set / f"run{step}")
            where = f"{texture_set} step {step}"
            if "error" in result:
                report["refused"].setdefault(texture_set, result["message"])
                if texture_set not in SRGB_MINIFY_REFUSED:
                    report["problems"].append(f"{where}: {result['error']}: {result['message']}")
                continue
            if texture_set in SRGB_MINIFY_REFUSED:
                report["problems"].append(f"{where}: written, expected a refusal")
                continue
            for written in result["written"]:
                rel = written["relativePath"]
                report["files"] += 1
                for recording in ("r1", "r2"):
                    theirs = _painter_files(golden, recording, step, texture_set)
                    report["comparisons"] += 1
                    if written["sha256"] == theirs.get(rel):
                        report["identical"] += 1
                    else:
                        report["problems"].append(f"{where}: {rel} differs from {recording}")
    return report


# phase1.15_compositor-colour-fits items 3.1 and 4.1: the texture sets whose files the colour fits
# made byte-identical to Painter's (decisions 145, 152, 174, 190 and 203), each golden with its
# sequence and spec options as its comparison above builds them.
LIFTED_COLOUR_SETS: dict[str, tuple[str, ...]] = {
    "export-bit-depth": ("s4", "s5", "s7"),
    "export-ocio-encode-legacy": SRGB8_BITMAP_SETS,
    "srgb-bitmap-variants-v2": SRGB_VARIANT_SETS,
    "export-ocio-encode": OCIO_ENCODE_SETS,
    "srgb-bitmap-minification": SRGB_MINIFY_SETS,
    "export-l8-material": ("s0", "s1"),
}


def lifted_colour_spec(stem: str, texture_set: str, spec_dir: Path) -> dict[str, Any]:
    """The spec `WriteExport` evaluates for `texture_set` of `stem` (`LIFTED_COLOUR_SETS`), for the
    evaluator's `evaluate` case: its outputs are every channel of the stack, except on
    export-bit-depth and export-l8-material, whose comparisons write only the material channels
    BaseColor, Specular and Emissive (export-bit-depth's Opacity has neither a template base value
    nor a channel default and is not exported there)."""
    prepare, options = {
        "export-bit-depth": (_bit_depth_golden, {"template_channels": True}),
        "export-ocio-encode-legacy": (_legacy_bitmap_golden, {}),
        "srgb-bitmap-variants-v2": (_variants_golden, {"template_channels": True}),
        "export-ocio-encode": (_ocio_encode_golden, {"ocio": True}),
        "srgb-bitmap-minification": (_minification_golden, {"template_channels": True}),
        "export-l8-material": (_l8_material_golden, {"template_channels": True}),
    }[stem]
    _, manifest = prepare()
    spec = _set_spec(manifest, texture_set, spec_dir, **options)
    channels = [c["type"] for c in spec["channels"]]
    material_only = stem in ("export-bit-depth", "export-l8-material")
    exported = SRGB8_CHANNELS if material_only else channels
    spec["outputs"] = [c for c in channels if c in exported]
    return spec


# ── parity/semantics/export-processing.json ─────────────────────────────────

PYDOC = source(
    "A-PYDOC",
    "substance_painter.export: Full json_config dict possibilities, exportParameters parameters",
)
HELP = source("A-HELP-EXPORT", "Export settings: file type, bit depth, padding, dilation, size")
EXR = source("S-EXR", "OpenEXR file layout: header attributes, scanline chunks, PIZ compression")
LIBS = source("X-THIRDPARTY", "zlib deflate parameters; tinyexr SaveEXRImageToMemory")
D3D = source("X-D3D12", "Data conversion rules: FLOAT to UNORM")

GAP_FORMULA = (
    "Release gap (decision 090): no Tier 0 recording shows it; a configuration asking for it is "
    "refused with NotYetSupported before anything is written, naming recording R-090."
)

PADDING_ISLANDS_FORMULA = (
    "Written under exception EXC-007 (decision 223), not fitted: covered texels keep their "
    "evaluated values; the ring takes the straight-edge 8-neighbour mean of decisions 176 and "
    "206 (x wraps) and the gutter the jump flood of decision 197 (src/export/padding.h). "
    "Painter's ring across UV seams, at seam corners and at poles is not identified."
)


def _byte_residual(
    golden_id: str, fmt: str, recording: str, files: int, identical: int
) -> dict[str, Any]:
    """The re-encoded files of one format of a golden's recording as a residual counted in files:
    1 for a file whose bytes differ, 0 for an identical one."""
    differs = np.zeros((1, files), np.int64)
    differs[0, identical:] = 1
    diff = difference(np.zeros((1, files), np.int64), differs)
    return residual(golden_id, f"{fmt} files re-encoded", recording, "file (bytes identical)", diff)


def _processed_residuals(processed: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The cases of one processing (`<format> <depth>`) per golden and recording as byte
    residuals."""
    out = []
    for name, cases in sorted(processed["cases"].items()):
        golden_id, fmt, depth, recording = name.split(" ")
        if f"{fmt} {depth}" != kind:
            continue
        differs = np.zeros((1, cases), np.int64)
        differs[0, processed["identical"][name] :] = 1
        diff = difference(np.zeros((1, cases), np.int64), differs)
        label = f"{fmt} {depth} files from Painter's own values"
        out.append(residual(golden_id, label, recording, "file (bytes identical)", diff))
    return out


def _srgb8_residuals(processed: dict[str, Any]) -> list[dict[str, Any]]:
    """The sRGB8 material-channel cases of each PNG processing per golden and recording as byte
    residuals."""
    out = []
    for name, cases in sorted(processed["srgb8_cases"].items()):
        golden_id, fmt, depth, recording = name.split(" ")
        if fmt != "png":
            continue
        differs = np.zeros((1, cases), np.int64)
        differs[0, processed["srgb8_identical"][name] :] = 1
        diff = difference(np.zeros((1, cases), np.int64), differs)
        label = f"{fmt} {depth} sRGB8 material files from Painter's own values"
        out.append(residual(golden_id, label, recording, "file (bytes identical)", diff))
    return out


def publish(
    reencoded: dict[str, Any], exported: dict[str, Any], processed: dict[str, Any]
) -> dict[str, Any]:
    """The `export-processing.json` document of the three reports."""
    png = [
        _byte_residual(g, "png", rec, n, k)
        for (g, fmt, rec), (n, k) in reencoded["per_golden"].items()
        if fmt == "png"
    ]
    exr = [
        _byte_residual(g, "exr", rec, n, k)
        for (g, fmt, rec), (n, k) in reencoded["per_golden"].items()
        if fmt == "exr"
    ]
    written16 = [
        residual(g, key, rec, unit, d)
        for g, key, rec, unit, d in exported["residuals"]
        if unit == "16-bit code value"
    ]
    written32 = [
        residual(g, key, rec, unit, d)
        for g, key, rec, unit, d in exported["residuals"]
        if unit == "float32 value"
    ]
    entries = [
        entry(
            "png-encoding",
            "PNG files: chunks, row filters and compression of Painter's PNG export",
            "Signature; IHDR (8 or 16 bits; grey, grey and alpha, RGB or RGBA; not interlaced); "
            "pHYs 2835 x 2835 per metre; IDAT chunks of 8192 bytes (the last shorter) holding one "
            "zlib stream (level 6, window bits 15, memory level 8) of the filtered rows; IEND. "
            "Each row takes the filter whose bytes have the smallest sum of min(b, 256 - b), ties "
            "to the earlier; the row above the first is zero. 8-bit grey chooses among all five "
            "filters and compresses with Z_DEFAULT_STRATEGY; every other layout chooses among "
            "None, Sub and Paeth and compresses with Z_FILTERED (src/export/png_writer.h, "
            "decisions 089 and 103).",
            [PYDOC, LIBS],
            [
                parameter("filters", "None, Sub, Paeth; 8-bit grey: all five", "fitted"),
                parameter("zlib_level", 6, "fitted"),
                parameter("zlib_strategy", "Z_FILTERED; 8-bit grey: Z_DEFAULT_STRATEGY", "fitted"),
                parameter("idat_size", 8192, "fitted", "byte"),
                parameter("phys", 2835, "fitted", "pixel per metre"),
                parameter("files", reencoded["files"]["png"], "fitted"),
            ],
            png,
        ),
        entry(
            "exr-encoding",
            "OpenEXR files: header, channels and PIZ compression of Painter's OpenEXR export",
            "Single-part scanline file, version 2; attributes channels, compression (PIZ), "
            "dataWindow, displayWindow, lineOrder (increasing y), pixelAspectRatio 1, "
            "screenWindowCenter (0, 0), screenWindowWidth 1; FLOAT (32f) or HALF (16f) channels "
            "Y (grey), A, Y (grey and alpha), B, G, R (RGB) or A, B, G, R (RGBA); PIZ as OpenEXR "
            "writes it, its Huffman heap breaking frequency ties by symbol (tinyexr with that "
            "local change, src/export/exr_writer.h, decisions 089 and 103).",
            [EXR, LIBS],
            [
                parameter("compression", "PIZ", "fitted"),
                parameter("pixel_type", "FLOAT, HALF", "fitted"),
                parameter("files", reencoded["files"]["exr"], "fitted"),
            ],
            exr,
        ),
        entry(
            "png16-write-rule",
            "PNG 16: the written code of each exported value",
            "code = (j 65535 + 2^19 - 1) >> 20 with j = floor(clamp(v, 0, 1) 2^20) "
            "(arith::WriteUnorm), every channel as the evaluator reads it out; the files written "
            "by WriteExport equal Painter's byte for byte.",
            [PYDOC, D3D],
            [parameter("bits", 16, "public_documentation")],
            written16,
        ),
        entry(
            "exr32f-values",
            "OpenEXR 32f: the written value of each exported value",
            "The float32 value unchanged (a signed channel keeps its sign); the files written by "
            "WriteExport equal Painter's byte for byte.",
            [PYDOC, EXR],
            [parameter("bits", 32, "public_documentation")],
            written32,
        ),
        entry(
            "png8-write-rule",
            "PNG 8: the written code of each exported value",
            "code = (j 255 + 2^11 - 1) >> 12 with j = floor(clamp(v, 0, 1) 2^12) "
            "(arith::WriteUnorm at 8 bits) of the OpenEXR 32f value of every channel and mesh "
            "map, Height as v 0.5 + 0.5 (decision 103): Painter's own OpenEXR 32f file of each map "
            "of export-bit-depth, encoded so, gives its PNG 8 file byte for byte.",
            [PYDOC, D3D],
            [parameter("bits", 8, "public_documentation")],
            _processed_residuals(processed, "png 8"),
        ),
        entry(
            "png16-height-alpha-dithering",
            "PNG 16 from Painter's own values: Height signed, alpha layouts, dithering",
            "The PNG 16 write rule of each value, Height as v 0.5 + 0.5; L+A and RGB+A written "
            "as such, an alpha of 1 everywhere dropped (L, RGB); with dithering on, the bytes "
            "PNG 16 has without it (export-bit-depth, export-alpha-layouts, export-dither; "
            "decision 103).",
            [PYDOC, D3D],
            [parameter("bits", 16, "public_documentation")],
            _processed_residuals(processed, "png 16"),
        ),
        entry(
            "exr16f-values",
            "OpenEXR 16f: the written half of each exported value",
            "The float32 value rounded toward zero to a binary16 half (arith::HalfTowardZero; "
            "decision 103): Painter's own OpenEXR 32f file of each map of export-bit-depth, "
            "encoded so, gives its OpenEXR 16f file byte for byte.",
            [PYDOC, EXR],
            [parameter("bits", 16, "public_documentation")],
            _processed_residuals(processed, "exr 16f"),
        ),
        entry(
            "srgb8-material-channels",
            "sRGB8 material channels (BaseColor, Specular, Emissive) in PNG 8 and 16",
            "The UNORM write rule at the file's depth of the sRGB encode of the linear value: "
            "x <= 0.0031308 ? 12.92 x : fma(1.055, exp2(0.41666 log2 x), -0.055) in float32 with "
            "the recording GPU's log2 and exp2 (src/evaluator/hwmath.h; decisions 091 and 126); "
            "OpenEXR holds the linear value. Painter's own OpenEXR 32f file of each such map of "
            "export-bit-depth, encoded so, gives its PNG 8 and PNG 16 files byte for byte.",
            [PYDOC, D3D],
            [
                parameter("exponent", 0.41666, "fitted"),
                parameter("linear_threshold", 0.0031308, "fitted"),
            ],
            _srgb8_residuals(processed),
        ),
        entry(
            "padding-complete-coverage",
            "Padding infinite and passthrough on a texture set whose UV islands cover the tile",
            "Nothing changes: every texel holds its evaluated value (src/export/padding.h); the "
            "residuals of png16-write-rule and exr32f-values are on such sets (grid meshes).",
            [PYDOC, HELP],
            [parameter("padding", "infinite", "public_documentation")],
            written16 + written32,
        ),
    ]
    gaps = {
        "padding-islands": (
            "Padding infinite outside the UV islands of a texture set that does not cover the tile",
            "Not the nearest covered texel: on tier0/semantics/height-normal-bevelled-cube "
            "(Height) 12040 of the 12200 uncovered texels differ from it. Partial fit (decision "
            "090): an 8-neighbour copy dilation (first covered neighbour: right, left, up, down, "
            "then the diagonals; x wraps, y does not) is exact on the bevelled cube's virtual "
            "normals (12200 gutter texels) and misses 32 to 44 texels per sphere normal map at "
            "the poles; a document channel's one-texel ring around each island blends across the "
            "UV seam with unidentified weights (2344 ring texels on the cube, 2152 on the sphere). "
            "Passthrough on such sets is written as no operation: Painter's r1 and r2 agree "
            "inside the islands and differ outside them at up to every uncovered texel. Owner "
            "phase1.25_pilot-wand (decision 103). Decision 220 measured the best-known rule at up "
            "to 59150 PNG 16 codes from Painter on padding texels, already on the ring; decision "
            "223 writes the coverage-only rule under EXC-007 (Wand v1 only: covered texels exact, "
            "padding texels excepted and published).",
        ),
        "padding-dilation": (
            "Padding color, transparent and diffusion with dilationDistance",
            "Recorded (export-padding*, R-090 P5, P9), not fitted (decision 103); owner "
            "phase3.2_unreal-ue56-packed-preset.",
        ),
        "resize": (
            "Resize to a sizeLog2 other than the texture set's size",
            "Recorded (export-resize, R-090 P4), partly fitted (decision 103): an upscale is the "
            "evaluation at the target size; a downscale is a 2x2 box stored in the channel's "
            "format (UNORM16; L16F rounds half away from zero); sRGB8 channels, virtual normals "
            "after a downscale and BilinearHQ normal-channel magnification are not reproduced. "
            "Owner phase3.2_unreal-ue56-packed-preset.",
        ),
        "dithering-png8-exr": (
            "Dithering at PNG 8 bits, and dithering in OpenEXR",
            "PNG 8: deterministic within and across sessions, not a threshold matrix (decision "
            "103); OpenEXR: no recording compares it with dithering off. Owner "
            "phase3.2_unreal-ue56-packed-preset.",
        ),
    }
    formulas = {"padding-islands": PADDING_ISLANDS_FORMULA}
    for entry_id, (subject, notes) in gaps.items():
        formula = formulas.get(entry_id, GAP_FORMULA)
        entries.append(entry(entry_id, subject, formula, [PYDOC, HELP], [], [], notes, gap=True))
    corpus = sorted(
        {g for g, _, _ in reencoded["per_golden"]}
        | {f"tier0/{n}" for n in EXPORT_GOLDENS}
        | {name.split(" ")[0] for name in processed["cases"]}
    )
    return document(
        "export-processing",
        "The export's processing and encoders (src/export/encode.h, padding.h, png_writer.h, "
        "exr_writer.h; decisions 089, 090, 103 and 126): Painter's PNG and OpenEXR files "
        "re-encoded byte for byte, the recorded processing written by WriteExport and applied "
        "to Painter's own values byte-identical to Painter's files, and the processing not "
        "fitted yet.",
        corpus,
        entries,
        painter_build=str(current_envelope()["painter_build"]),
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python tests/export/encoders_tier0.py <uzp-export-tests.exe> <work-dir>",
            file=sys.stderr,
        )
        return 2
    if locate() is None:
        print("oracle_unavailable: no private oracle store on this machine", file=sys.stderr)
        return 2
    exe, work = Path(argv[0]), Path(argv[1])
    reencoded = reencode_painter_files(exe, work)
    exported = export_goldens(exe, work / "export", runs=2)
    processed = process_painter_files(exe, work / "process")
    PUBLISHED.write_text(
        json.dumps(publish(reencoded, exported, processed), indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{PUBLISHED}: re-encoded {dict(reencoded['identical'])} of {dict(reencoded['files'])}; "
        f"{exported['identical_to_painter']} of {exported['comparisons']} written files identical; "
        f"{len(exported['problems'])} problems"
    )
    ok = not reencoded["differing"] and not exported["problems"] and not processed["differing"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
