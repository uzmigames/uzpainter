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
from tools.parity.store.store import OracleStore, Status, locate

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


def _byte_residual(
    golden_id: str, fmt: str, recording: str, files: int, identical: int
) -> dict[str, Any]:
    """The re-encoded files of one format of a golden's recording as a residual counted in files:
    1 for a file whose bytes differ, 0 for an identical one."""
    differs = np.zeros((1, files), np.int64)
    differs[0, identical:] = 1
    diff = difference(np.zeros((1, files), np.int64), differs)
    return residual(golden_id, f"{fmt} files re-encoded", recording, "file (bytes identical)", diff)


def publish(reencoded: dict[str, Any], exported: dict[str, Any]) -> dict[str, Any]:
    """The `export-processing.json` document of the two reports."""
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
            "Signature; IHDR (8 or 16 bits; grey, RGB or RGBA; not interlaced); pHYs 2835 x 2835 "
            "per metre; "
            "IDAT chunks of 8192 bytes (the last shorter) holding one zlib stream (level 6, window "
            "bits 15, memory level 8, strategy Z_FILTERED) of the filtered rows; IEND. Each row "
            "takes, among None, Sub and Paeth only, the filter whose bytes have the smallest sum "
            "of min(b, 256 - b), ties to the earlier; the row above the first is zero "
            "(src/export/png_writer.h, decision 089).",
            [PYDOC, LIBS],
            [
                parameter("filters", "None, Sub, Paeth", "fitted"),
                parameter("zlib_level", 6, "fitted"),
                parameter("zlib_strategy", "Z_FILTERED", "fitted"),
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
            "screenWindowCenter (0, 0), screenWindowWidth 1; FLOAT channels Y (grey), B, G, R "
            "(RGB) or A, B, G, R (RGBA); PIZ as OpenEXR writes it, its Huffman heap breaking "
            "frequency ties by symbol "
            "(tinyexr with that local change, src/export/exr_writer.h, decision 089).",
            [EXR, LIBS],
            [
                parameter("compression", "PIZ", "fitted"),
                parameter("pixel_type", "FLOAT", "fitted"),
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
            "inside the islands and differ outside them at up to every uncovered texel.",
        ),
        "padding-dilation": (
            "Padding color, transparent and diffusion with dilationDistance",
            None,
        ),
        "resize": ("Resize to a sizeLog2 other than the texture set's size", None),
        "dithering": ("Dithering on", None),
        "png-8": ("PNG at 8 bits per sample", None),
        "exr-16f": ("OpenEXR at 16-bit half float", None),
        "alpha-layouts": (
            "The L+A and RGB+A layouts (an alpha channel) in PNG and OpenEXR",
            "RGB+A is recorded (R-085 P6, P7: an alpha of 1 everywhere is dropped) and its files "
            "re-encode byte for byte; it is written once the plan resolves its alpha sources.",
        ),
        "srgb8-material-channels": (
            "sRGB8 material channels (BaseColor and the other material colours) in PNG and any "
            "sRGB8 channel in OpenEXR",
            "sRGB8 User channels are exported linear (their decoded operand); BaseColor is "
            "exported sRGB-encoded and the evaluator's template constants of material colours are "
            "already export values: recorded, not fitted here.",
        ),
    }
    for entry_id, (subject, notes) in gaps.items():
        entries.append(
            entry(entry_id, subject, GAP_FORMULA, [PYDOC, HELP], [], [], notes, gap=True)
        )
    corpus = sorted(
        {g for g, _, _ in reencoded["per_golden"]} | {f"tier0/{n}" for n in EXPORT_GOLDENS}
    )
    return document(
        "export-processing",
        "The export's processing and encoders (src/export/encode.h, padding.h, png_writer.h, "
        "exr_writer.h; decisions 089 and 090): Painter's PNG and OpenEXR files re-encoded byte "
        "for byte, the recorded processing written by WriteExport byte-identical to Painter's "
        "files, and the processing no recording covers yet.",
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
    PUBLISHED.write_text(
        json.dumps(publish(reencoded, exported), indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{PUBLISHED}: re-encoded {dict(reencoded['identical'])} of {dict(reencoded['files'])}; "
        f"{exported['identical_to_painter']} of {exported['comparisons']} written files identical; "
        f"{len(exported['problems'])} problems"
    )
    ok = not reencoded["differing"] and not exported["problems"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
