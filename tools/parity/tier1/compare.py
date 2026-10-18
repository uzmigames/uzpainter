"""The Tier 1 comparison step (phase1.25 item 2.5; decision 124; 14-parity-testing.md §4).

    report = compare(subject, resolved, store, runs, identity, register_entries)

One golden's private recordings against two UzPainter rebuilds of the same pinned job, reported as
`parity/schema/comparison-report.json` with its three results kept apart:

- **oracle stability**: each exported map of `r1` against the same map of every other recording
  (`r1-repeat`, `r2`); a map is stable when all of them are equal;
- **UzPainter repeatability**: the two rebuilds' files, byte for byte (the acceptance), with the
  decoded diagnostics next to them;
- **equality to Painter**: each map of the first rebuild against `r1` through
  `tools.parity.verdict.evaluate` (exact equality; a difference passes only through an
  owner-approved register entry; an unstable map is judged against `r1` as the exact target,
  decision 032).

Maps are paired by (texture set, map name), decoded at native depth (`tools.parity.fit.decode`)
and classified by their measured storage format (container, sample type, bits, channels,
encoding): a candidate whose measured format differs from the recorded one is a structural
difference before any value is compared. Structural differences (the export refused before
writing, a map on one side only, a storage format or shape that differs) fail in every tier and
are listed in `structural`. A refused export is listed once, as `candidate_export_refused`: it
wrote nothing and nothing is compared, so its maps are not listed again as missing (decision 255);
`missing_from_candidate` names a map that an export which wrote its files left out.

The golden's outcome, in this order: `oracle_unavailable` when the golden is not admitted, or its
private record or any of its blobs is missing (checked before anything is compared; nothing is
compared and it is never a pass); `stale` when the golden belongs to another envelope; `fail` on
any structural difference or failing map; `blocked` when a map is blocked (an unstable oracle
without an entry) or the recordings do not hold the same maps (Painter not reproducing its own
export's structure: the oracle is unstable, never `stable`); else `pass`.

Diagnostics per map (§4): max, mean and nearest-rank p99 |Δ|, differing count and percentage, and
the same per region of the asset's material masks (`material_regions`; regions may overlap, texels
outside every mask count in the whole-map numbers only, and a mask applies to maps of its own
resolution only). For the maps the caller names as
tangent-space normals: the angle between the oracle and candidate vectors (max and mean, over the
texels where both are finite and non-zero) and the candidate's non-finite and unnormalised texel
counts. A texel is unnormalised when its length differs from 1 by more than rounding a unit vector
to the stored values can produce: sqrt(3)/max for integer codes (n = 2c/max - 1), sqrt(3)·eps of
the stored type for float maps. A differing integer map's |Δ| image (a PNG at its stored depth)
goes into the private store only, so the guard's store-hash rule blocks it, and the report names
its SHA-256. Mean FLIP (NVIDIA's `flip-evaluator`, pinned at 1.7 by the dependency inventory,
`docs/licensing-and-clean-room.md` §3) is reported for each compared integer map of the equality
result, LDR on the stored codes scaled to [0, 1] (a grey map repeated to three channels, alpha
dropped), with the tool's identity in `flip_tool`. It is a diagnostic only: it never enters a
verdict. Without the pinned package (hosted runners), or for float maps, it is omitted.

Padding (decision 223): for a texture set whose UV triangles the subject names, each map is split
by the set's texel-centre coverage (`tools.parity.coverage`). The verdict receives the coverage
for an entry that bounds the covered texels only (an owner scope split; the one there was, EXC-007,
is withdrawn, decision 259, so every padding difference fails), and the map's `padding` block
publishes the covered and uncovered statistics and the uncovered ones within 1, 2, 4 and 8 texels
of coverage, whatever the verdict.

Nothing here writes into the repository except `write_report`: decoded values stay in memory, and
the report holds numbers and hashes only.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.coverage import BANDS, Triangles, coverage, distance_bands
from tools.parity.envelope.registry import current_envelope
from tools.parity.feasibility import png
from tools.parity.fit.decode import Decoded, decode
from tools.parity.fit.oracle import Golden, OracleUnavailable, load
from tools.parity.fit.stability import storage_key
from tools.parity.recorder.capture import measure_storage_format
from tools.parity.recorder.texture import UNDETERMINED
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import OracleStore
from tools.parity.verdict import (
    Comparison,
    Diagnostics,
    Outcome,
    ResolvedGolden,
    Verdict,
    diagnose,
    evaluate,
)

REPORT_SCHEMA = "uzpainter/parity/comparison-report/1"
FIRST = "r1"
EXPORT = "export"  # the output id of an export refused before writing
REFUSED = "candidate_export_refused"
MISSING_FROM_CANDIDATE = "missing_from_candidate"
MISSING_FROM_ORACLE = "missing_from_oracle"
FORMAT_DIFFERS = "storage_format_differs"
SHAPE_DIFFERS = "shape_differs"
FLIP_PACKAGE, FLIP_VERSION = "flip-evaluator", "1.7"
FLIP_WHEEL_SHA256 = "2081f715ea8190a5f58bc578b0cccd36a9a3f3cf78ad13fe6f86e5a75615bda7"
# What must be the same for a recorded golden to be the job the runs executed.
SAME_JOB = ("golden_id", "tier", "domain", "inputs", "instruction_sequence", "applied_settings")

MapKey = tuple[str, str]  # (texture set, map name)
Mask = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class CandidateRun:
    """One UzPainter rebuild: its exported files by (texture set, map name), or its refusal and
    the refusal's message (kept for the caller; the public report holds no message)."""

    files: Mapping[MapKey, Path] = field(default_factory=dict)
    refused: bool = False
    refusal: str = ""


@dataclass(frozen=True)
class RunIdentity:
    """The report's `run` block apart from the Painter build (14-parity-testing.md §8)."""

    hardware: str
    driver: str
    backend: str
    uzpainter_build_hash: str
    resource_hashes: tuple[str, ...]


@dataclass(frozen=True)
class Subject:
    """The job the runs executed (its public manifest, request or admitted), its material regions,
    the names of its maps that are tangent-space normals, and the UV triangles of its texture sets
    by name (the mesh material of each set; decision 223)."""

    manifest: Mapping[str, Any]
    manifest_sha256: str
    regions: Mapping[str, Mask] = field(default_factory=dict)
    normal_maps: frozenset[str] = frozenset()
    uv_triangles: Mapping[str, Triangles] = field(default_factory=dict)


def material_regions(stack: Mapping[str, Any], masks: Path) -> dict[str, Mask]:
    """The asset's material regions: the mask of each layer-stack group (`<masks>/<mask>.png`, as
    the sync command reads it), as the texels whose grey (first) channel is non-zero."""
    regions: dict[str, Mask] = {}
    for group in stack["groups"]:
        name = group.get("mask")
        if name:
            values = decode((masks / f"{name}.png").read_bytes()).values
            regions[str(name)] = values[..., 0] != 0
    return regions


def file_storage_format(path: Path) -> dict[str, Any]:
    """The measured storage format of an exported file, as the recorder measures Painter's."""
    measured = measure_storage_format(path)
    return measured.as_schema(measured.encoding or UNDETERMINED)


def _number(value: float) -> float:
    return int(value) if math.isfinite(value) and float(value).is_integer() else value


def stat_block(diagnostics: Diagnostics) -> dict[str, Any]:
    return {
        "abs_diff": {
            "max": _number(diagnostics.max_abs_diff),
            "mean": _number(diagnostics.mean_abs_diff),
            "p99": _number(diagnostics.p99_abs_diff),
        },
        "differing": {
            "count": diagnostics.differing_count,
            "percent": diagnostics.differing_percent,
            "total": diagnostics.total,
        },
    }


def region_diagnostics(
    oracle: npt.NDArray[Any], candidate: npt.NDArray[Any], regions: Mapping[str, Mask]
) -> dict[str, Diagnostics]:
    """Diagnostics over the texels of each non-empty region of the map's resolution (a mask
    covers the UV space at its own resolution only; it is never resampled)."""
    found: dict[str, Diagnostics] = {}
    for name, mask in sorted(regions.items()):
        if mask.shape == oracle.shape[:2] and mask.any():
            found[name] = diagnose(oracle[mask], candidate[mask])
    return found


def padding_block(
    oracle: npt.NDArray[Any], candidate: npt.NDArray[Any], covered: Mask
) -> dict[str, Any]:
    """The map split by coverage (decision 223): the covered texels, the uncovered ones and the
    uncovered ones within each band of `BANDS` texels of coverage."""
    distance = distance_bands(covered)
    uncovered = ~covered
    bands = []
    for band in BANDS:
        within = uncovered & (distance <= band)
        if within.any():
            stats = stat_block(diagnose(oracle[within], candidate[within]))
            bands.append({"within_texels": band, "texels": int(within.sum()), **stats})
    return {
        "covered_texels": int(covered.sum()),
        "uncovered_texels": int(uncovered.sum()),
        "covered": stat_block(diagnose(oracle[covered], candidate[covered])),
        "uncovered": (
            stat_block(diagnose(oracle[uncovered], candidate[uncovered]))
            if uncovered.any()
            else None
        ),
        "bands": bands,
    }


def _vectors(decoded: Decoded) -> npt.NDArray[np.float64]:
    values = decoded.values
    if values.ndim != 3 or values.shape[2] < 3:
        raise ValueError(f"a normal map has three channels, not shape {values.shape}")
    xyz = values[..., :3].astype(np.float64)
    if decoded.integer:
        scaled: npt.NDArray[np.float64] = 2.0 * xyz / decoded.maximum_code - 1.0
        return scaled
    return xyz


def unit_length_bound(decoded: Decoded) -> float:
    """The largest |length - 1| rounding a unit vector to the stored values can produce."""
    if decoded.integer:
        return math.sqrt(3.0) / decoded.maximum_code
    stored = np.float16 if decoded.bits == 16 else np.float32
    return math.sqrt(3.0) * float(np.finfo(stored).eps)


def normal_diagnostics(oracle: Decoded, candidate: Decoded) -> dict[str, float]:
    """Angular difference (degrees, atan2 of |a x b| and a . b, so equal vectors give 0) and the
    candidate's non-finite and unnormalised texel counts."""
    a, b = _vectors(oracle), _vectors(candidate)
    length = np.linalg.norm(b, axis=-1)
    finite = np.isfinite(b).all(axis=-1)
    unnormalised = finite & (np.abs(length - 1.0) > unit_length_bound(candidate))
    valid = finite & np.isfinite(a).all(axis=-1) & (np.abs(a).sum(-1) > 0) & (length > 0)
    max_deg = mean_deg = 0.0
    if valid.any():
        left, right = a[valid], b[valid]
        cross = np.linalg.norm(np.cross(left, right), axis=-1)
        angles = np.degrees(np.arctan2(cross, (left * right).sum(axis=-1)))
        max_deg, mean_deg = float(angles.max()), math.fsum(angles.tolist()) / angles.size
    return {
        "angular_max_deg": max_deg,
        "angular_mean_deg": mean_deg,
        "non_finite_count": float(np.count_nonzero(~finite)),
        "unnormalised_count": float(np.count_nonzero(unnormalised)),
    }


def flip_available() -> bool:
    """The pinned FLIP package is installed (the owner's machine; decision 050)."""
    try:
        return importlib.metadata.version(FLIP_PACKAGE) == FLIP_VERSION
    except importlib.metadata.PackageNotFoundError:
        return False


def _flip_rgb(decoded: Decoded) -> npt.NDArray[np.float32]:
    values: npt.NDArray[np.float32] = (decoded.values / decoded.maximum_code).astype(np.float32)
    return np.repeat(values[..., :1], 3, axis=2) if values.shape[2] < 3 else values[..., :3]


def flip_mean(oracle: Decoded, candidate: Decoded) -> float | None:
    """Mean FLIP error (LDR) of the candidate against the oracle; diagnostic only. None for float
    maps or without the pinned package."""
    if not (oracle.integer and candidate.integer) or not flip_available():
        return None
    import flip_evaluator

    _, mean, _ = flip_evaluator.evaluate(
        _flip_rgb(oracle), _flip_rgb(candidate), "LDR", applyMagma=False, computeMeanError=True
    )
    return float(mean)


def store_difference_map(
    store: OracleStore | None, oracle: Decoded, candidate: Decoded
) -> str | None:
    """|Δ| per channel at the stored integer depth, as a PNG in the private store; its SHA-256.
    None without a store or for float maps (no PNG holds them)."""
    if store is None or not (oracle.integer and candidate.integer) or oracle.bits not in (8, 16):
        return None
    delta = np.abs(oracle.values.astype(np.int64) - candidate.values.astype(np.int64))
    data = png.encode(delta, oracle.bits)
    sha256 = hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory(prefix="uzp-tier1-") as directory:
        path = Path(directory) / f"{sha256}.png"
        path.write_bytes(data)
        store.put_blob(path, sha256)
    return sha256


def map_entry(
    output_id: str,
    storage_format: Mapping[str, Any],
    whole: Diagnostics,
    regions: Mapping[str, Diagnostics],
    normal: Mapping[str, float] | None = None,
    difference_map: str | None = None,
    flip: float | None = None,
    padding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "output_id": output_id,
        "storage_format": dict(storage_format),
        **stat_block(whole),
        "regions": [{"region": name, **stat_block(d)} for name, d in regions.items()],
    }
    if normal is not None:
        entry["normal"] = {
            "angular_max_deg": normal["angular_max_deg"],
            "angular_mean_deg": normal["angular_mean_deg"],
            "non_finite_count": int(normal["non_finite_count"]),
            "unnormalised_count": int(normal["unnormalised_count"]),
        }
    if difference_map is not None:
        entry["private_difference_map_sha256"] = difference_map
    if flip is not None:
        entry["flip_mean"] = flip
    if padding is not None:
        entry["padding"] = dict(padding)
    return entry


def _name(key: MapKey) -> str:
    return f"{key[0]}/{key[1]}"


def _exported(golden: Golden, recording: str) -> dict[MapKey, str]:
    outputs = golden.recordings[recording].outputs
    return {
        (str(o["texture_set"]), str(o["map"])): output_id
        for output_id, o in outputs.items()
        if o["kind"] == "exported_map"
    }


def _preflight(golden: Golden) -> None:
    """Every blob the record names is read and decoded before anything is compared; a missing
    one raises `OracleUnavailable`."""
    if FIRST not in golden.recordings or not _exported(golden, FIRST):
        raise ValueError(
            f"{golden.golden_id}: a Tier 1 golden records its exported maps in {FIRST}"
        )
    for recording in golden.recordings:
        for output_id in _exported(golden, recording).values():
            golden.map(recording, output_id)


def _same_job(subject: Mapping[str, Any], recorded: Mapping[str, Any]) -> None:
    differing = [key for key in SAME_JOB if subject[key] != recorded[key]]
    if differing:
        raise ValueError(
            f"{recorded['golden_id']}: the admitted golden differs from the job the runs executed "
            f"in {differing}"
        )


def oracle_stability(
    golden: Golden, regions: Mapping[str, Mask]
) -> tuple[dict[MapKey, bool], list[dict[str, Any]], list[MapKey]]:
    """Per map of r1: stable when every other recording holds it equal, in the same storage format
    and shape; the diagnostics of each compared pair (`<set>/<map>@<recording>`); and the maps
    another recording holds that r1 does not (the union of every recording's maps less r1's)."""
    unpaired = sorted(
        {key for recording in golden.recordings for key in _exported(golden, recording)}
        - set(_exported(golden, FIRST))
    )
    stable: dict[MapKey, bool] = {}
    entries: list[dict[str, Any]] = []
    for key, output_id in sorted(_exported(golden, FIRST).items()):
        recorded = golden.output(FIRST, output_id)["storage_format"]
        first = golden.map(FIRST, output_id).values
        stable[key] = True
        for recording in sorted(set(golden.recordings) - {FIRST}):
            other_id = _exported(golden, recording).get(key)
            if other_id is None:
                stable[key] = False
                continue
            other_format = golden.output(recording, other_id)["storage_format"]
            other = golden.map(recording, other_id).values
            if storage_key(recorded) != storage_key(other_format) or first.shape != other.shape:
                stable[key] = False
                continue
            whole = diagnose(first, other)
            stable[key] = stable[key] and whole.differing_count == 0
            pair = region_diagnostics(first, other, regions)
            entries.append(map_entry(f"{_name(key)}@{recording}", recorded, whole, pair))
    return stable, entries, unpaired


def repeatability(runs: Sequence[CandidateRun], regions: Mapping[str, Mask]) -> dict[str, Any]:
    """The two rebuilds byte for byte; `not_measured` when either wrote no maps."""
    first, second = runs
    if first.refused or second.refused or not first.files or not second.files:
        return {"status": "not_measured", "maps": []}
    repeatable = set(first.files) == set(second.files)
    entries: list[dict[str, Any]] = []
    for key in sorted(set(first.files) & set(second.files)):
        left, right = first.files[key].read_bytes(), second.files[key].read_bytes()
        repeatable = repeatable and left == right
        stored = file_storage_format(first.files[key])
        if storage_key(stored) != storage_key(file_storage_format(second.files[key])):
            repeatable = False
            continue
        a, b = decode(left).values, decode(right).values
        if a.shape != b.shape:
            repeatable = False
            continue
        whole = diagnose(a, b)
        entries.append(map_entry(_name(key), stored, whole, region_diagnostics(a, b, regions)))
    return {"status": "repeatable" if repeatable else "not_repeatable", "maps": entries}


def _outcome(
    verdicts: Sequence[Verdict], structural: Sequence[Any], stale: bool, oracle_unpaired: bool
) -> Outcome:
    outcomes = {v.outcome for v in verdicts}
    if stale or Outcome.STALE in outcomes:
        return Outcome.STALE
    if structural or Outcome.FAIL in outcomes:
        return Outcome.FAIL
    if Outcome.BLOCKED in outcomes or oracle_unpaired:
        return Outcome.BLOCKED
    return Outcome.PASS


def equality(
    subject: Subject,
    resolved: ResolvedGolden,
    golden: Golden,
    stable: Mapping[MapKey, bool],
    oracle_unpaired: bool,
    run: CandidateRun,
    store: OracleStore | None,
    register_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The first rebuild's maps against r1, each judged by the contract. A refused export is one
    structural failure, with no map compared (decision 255)."""
    tier, domain = str(subject.manifest["tier"]), str(subject.manifest["domain"])
    if run.refused:
        return {
            "outcome": _outcome([], [REFUSED], resolved.stale, oracle_unpaired).value,
            "exceptions_relied_on": [],
            "maps": [],
            "structural": [{"output_id": EXPORT, "reason": REFUSED}],
        }
    first = _exported(golden, FIRST)
    structural: list[dict[str, str]] = [
        {"output_id": _name(key), "reason": MISSING_FROM_ORACLE}
        for key in sorted(set(run.files) - set(first))
    ]
    verdicts: list[Verdict] = []
    entries: list[dict[str, Any]] = []
    masks: dict[tuple[str, int, int], Mask] = {}
    for key, output_id in sorted(first.items()):
        path = run.files.get(key)
        if path is None:
            structural.append({"output_id": _name(key), "reason": MISSING_FROM_CANDIDATE})
            continue
        recorded = golden.output(FIRST, output_id)["storage_format"]
        if storage_key(file_storage_format(path)) != storage_key(recorded):
            structural.append({"output_id": _name(key), "reason": FORMAT_DIFFERS})
            continue
        oracle, candidate = golden.map(FIRST, output_id), decode(path.read_bytes())
        if oracle.values.shape != candidate.values.shape:
            structural.append({"output_id": _name(key), "reason": SHAPE_DIFFERS})
            continue
        regions = region_diagnostics(oracle.values, candidate.values, subject.regions)
        normal = normal_diagnostics(oracle, candidate) if key[1] in subject.normal_maps else None
        covered: Mask | None = None
        if key[0] in subject.uv_triangles:
            height, width = oracle.values.shape[:2]
            if (key[0], width, height) not in masks:
                masks[key[0], width, height] = coverage(subject.uv_triangles[key[0]], width, height)
            covered = masks[key[0], width, height]
        padding = (
            padding_block(oracle.values, candidate.values, covered)
            if covered is not None and covered.any()
            else None
        )
        verdict = evaluate(
            Comparison(
                tier,
                domain,
                oracle.values,
                candidate.values,
                extra_metrics={f"normal_{name}": value for name, value in (normal or {}).items()},
                region_metrics={name: d.metrics() for name, d in regions.items()},
                oracle_stable=stable[key],
                exact_target=not stable[key],
                envelope_id=resolved.envelope_id,
                covered=covered,
            ),
            register_entries,
        )
        verdicts.append(verdict)
        whole = verdict.diagnostics or diagnose(oracle.values, candidate.values)
        difference_map = (
            store_difference_map(store, oracle, candidate) if whole.differing_count else None
        )
        flip = flip_mean(oracle, candidate)
        entries.append(
            map_entry(_name(key), recorded, whole, regions, normal, difference_map, flip, padding)
        )
    outcome = _outcome(verdicts, structural, resolved.stale, oracle_unpaired)
    relied = sorted({pair for v in verdicts for pair in v.exceptions_relied_on})
    return {
        "outcome": outcome.value,
        "exceptions_relied_on": (
            []
            if outcome is Outcome.STALE
            else [{"exception_id": e, "version": version} for e, version in relied]
        ),
        "maps": entries,
        "structural": structural,
    }


def compare(
    subject: Subject,
    resolved: ResolvedGolden | None,
    store: OracleStore | None,
    runs: Sequence[CandidateRun],
    identity: RunIdentity,
    register_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The comparison report of one golden (`resolved`: `verdict.resolve_golden`, None when the
    golden is not admitted) against two rebuilds of its job."""
    if len(runs) != 2:
        raise ValueError("a Tier 1 comparison takes two rebuilds")
    manifest = subject.manifest
    golden: Golden | None = None
    if resolved is not None:
        _same_job(manifest, resolved.manifest)
        try:
            golden = load(store, resolved.manifest_path)
            _preflight(golden)
        except OracleUnavailable:
            golden = None
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "record_class": "comparison_report",
        "golden_id": manifest["golden_id"],
        "tier": manifest["tier"],
        "domain": manifest["domain"],
        "manifest_sha256": (
            hashlib.sha256(resolved.manifest_path.read_bytes()).hexdigest()
            if resolved is not None
            else subject.manifest_sha256
        ),
        "envelope_id": (
            resolved.envelope_id if resolved is not None else current_envelope()["envelope_id"]
        ),
        "run": {
            "hardware": identity.hardware,
            "driver": identity.driver,
            "backend": identity.backend,
            "uzpainter_build_hash": identity.uzpainter_build_hash,
            "painter_build_id": manifest["software"]["painter"]["build_id"],
            "resource_hashes": list(identity.resource_hashes),
        },
        "uzpainter_repeatability": repeatability(runs, subject.regions),
    }
    if golden is None or resolved is None:
        report["oracle_stability"] = {"status": "oracle_unavailable", "maps": []}
        report["equality_to_painter"] = {
            "outcome": Outcome.ORACLE_UNAVAILABLE.value,
            "exceptions_relied_on": [],
            "maps": [],
            "structural": [{"output_id": EXPORT, "reason": REFUSED}] if runs[0].refused else [],
        }
        return report
    stable, stability_maps, unpaired = oracle_stability(golden, subject.regions)
    report["oracle_stability"] = {
        "status": "stable" if all(stable.values()) and not unpaired else "unstable",
        "maps": stability_maps,
    }
    report["equality_to_painter"] = equality(
        subject, resolved, golden, stable, bool(unpaired), runs[0], store, register_entries
    )
    if any("flip_mean" in m for m in report["equality_to_painter"]["maps"]):
        report["flip_tool"] = {"version": FLIP_VERSION, "sha256": FLIP_WHEEL_SHA256}
    return report


def write_report(report: Mapping[str, Any], path: Path) -> None:
    """Validate the report against its schema and write it (numbers and hashes only)."""
    problems = validation_errors(report, Schema.COMPARISON_REPORT)
    if problems:
        raise ValueError(f"the comparison report is invalid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
