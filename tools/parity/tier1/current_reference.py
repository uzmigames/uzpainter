"""A pilot's current reference against its retained historical golden, offline (decision 300 §7-8).

    python -m tools.parity.tier1.current_reference --migration <manifest.json> \
        --current <manifest-current.json> [--store <private store>]

Decision 300 item 7 gives each G2 pilot a pinned current round (`phase2/tier1/<pilot>-current`)
and keeps its approved reference unchanged: the Tunic's admitted migration golden and the Sash's
historical golden. "The current golden's maps are compared with them, and the result is
reported." This module is that comparison, Painter recording against Painter recording; it reads
two admitted manifests and the private store and prints one aggregate JSON report on stdout.

It is not `tools.parity.tier1.compare`: that step judges UzPainter against a golden of the same
job. Here the two goldens are different jobs by design (the current round runs on substitute or
recovered inputs), so their inputs and instructions are never required to match and never
substituted. Output equality does not prove historical input identity: the pilot's input
inventory is referenced by path and SHA-256 and every pinned input of both manifests is listed.

Checks, in order, each before anything that depends on it:

1. **Manifests.** Each is schema-valid (`golden-public.json`), Tier 1, with unique private record
   ids. The historical id is a known pilot's (`PILOTS`) and the current id is that pilot's
   `-current` id; equal or crossed ids are `invalid`. The id alone does not prove a side's role:
   the historical golden is a migration golden (`painter_project_migration`, decision 194) and
   the current one a pipeline-script golden (`uzmigames_pipeline_scripts`, decision 099).
2. **Store.** Every private record each manifest names is admitted (its write-once corpus entry
   under the manifest's Painter build names the same kind, SHA-256 and size) and its blob is
   present and matches its hash and size. Anything missing or failing is `oracle_unavailable`.
3. **Record and environment**, from the raw bytes (duplicates are found before anything is keyed
   by id): the record passes `record_problems`, names the manifest's golden, tier and build, and
   is the job of its own manifest (the key's inputs are the manifest's pins and its instruction
   hash is the manifest's sequence); the two sides' jobs are never required to match. It holds
   exactly `r1` and `r1-repeat` (`same_session`, one session id) and `r2`
   (`after_save_reopen`), no duplicate recording, output id or (texture set, map); the blobs its
   outputs name are exactly the manifest's other records; the one environment record is
   schema-valid, names the same build and, when the record embeds its `environment` (optional
   for back-filled goldens), equals it. Validation messages quote private values, so only a
   count and a schema-named path are reported.
4. **Maps.** Every exported map output of every recording is checked on its own: its blob,
   measured from the bytes (container, sample type, bits, channels; the stated encoding when the
   file states one) and decoded at native depth once per SHA-256, must agree with that output's
   recorded storage format and media type. Only the measured format and the decoded shape, depth
   and type are kept; the decoded values are released at once (a 4096 px 16-bit RGB map is
   400 MB as int64), and a pair whose bytes differ is decoded again when it is compared. The
   decoders cover PNG, OpenEXR and TGA8; the tests author PNG only, so real EXR and TGA exports
   are untested here.
5. **Stability, per side.** `r1` against `r1-repeat` (same session) and against `r2` (after save
   and reopen), in encoded bytes and in decoded values separately. Decision 300 item 7 requires
   byte-identical recordings, so a side whose bytes differ is unstable and the outcome `invalid`.
   Each fully verified side is classified even when the other side is unavailable.
6. **Envelope.** The two environment records must `match` (CONTRACT.md §6.5); otherwise the
   comparison is out of envelope and the outcome `invalid`.
7. **Structure, across sides.** `r1` maps paired by (texture set, map): a map on one side only, a
   different storage format or shape is a structural difference; with any, no value is compared.
8. **Equality.** Encoded bytes (SHA-256) and native decoded values, per map, reported apart.
   Identical values with other bytes are `different` (decision 300: only byte identity counts).

Outcome, exactly one: `identical` (every map byte-identical), `different`, `invalid` (a refused
manifest, pairing, record, map, stability or envelope) or `oracle_unavailable`. `invalid` wins
over `oracle_unavailable` when both are found. None of them approves a baseline, records an
exception, accepts a gate or completes an acceptance item: the changed baseline is the owner's
yes of decision 300 item 8. The report holds identifiers, hashes of the manifests, records and
environments, storage keys, shapes and counts; never a pixel, coordinate, map hash or readback.
Nothing is written anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator, FormatChecker

from tools.parity import tga
from tools.parity.fit.decode import Decoded, decode
from tools.parity.fit.stability import storage_key
from tools.parity.recorder.capture import (
    EXR_MAGIC,
    MEDIA_TYPES,
    PNG_SIGNATURE,
    StorageFormat,
    exr_format,
    png_format,
)
from tools.parity.recorder.environment import (
    ENVIRONMENT_KIND,
    MATCH,
    UNKNOWN,
    envelope_match,
    envelope_sha256,
    environment_bytes,
)
from tools.parity.recorder.job import canonical_json, sha256_bytes
from tools.parity.schemas import (
    REPO_ROOT,
    Schema,
    environment_problems,
    load_schema,
    record_problems,
)
from tools.parity.store.store import OracleStore, Status, StoreError, locate
from tools.parity.verdict import diagnose

REPORT_SCHEMA = "uzpainter/parity/current-reference-comparison/1"
IDENTICAL, DIFFERENT, INVALID, UNAVAILABLE = (
    "identical",
    "different",
    "invalid",
    "oracle_unavailable",
)
EXIT_CODES = {IDENTICAL: 0, DIFFERENT: 1, INVALID: 2, UNAVAILABLE: 3}
MIGRATION, CURRENT = "migration", "current"
SIDES = (MIGRATION, CURRENT)
R1, R1_REPEAT, R2 = "r1", "r1-repeat", "r2"
CONDITIONS = {R1: "same_session", R1_REPEAT: "same_session", R2: "after_save_reopen"}
RECORD_KIND = "private_oracle_record"
MAP_KIND = "exported_map"
KEPT_KINDS = frozenset({RECORD_KIND, ENVIRONMENT_KIND, MAP_KIND})

# Decision 300 item 7: the approved reference is a migration golden (decision 194's route) and the
# current round is recorded through the piece's committed scripts (decision 099).
HISTORICAL_INTERFACE = "painter_project_migration"
CURRENT_INTERFACE = "uzmigames_pipeline_scripts"

MapKey = tuple[str, str]  # (texture set, map name)


@dataclass(frozen=True)
class Pilot:
    name: str
    current_id: str
    inventory: str  # repository path of the pilot's input inventory


# The G2 pilots of decision 300 item 7: the retained historical golden id, its current round's id
# and the inventory naming every missing or substitute input.
PILOTS = {
    # `phase2/tier1/sash-v5` stays the original script golden's id (decision 260;
    # tests/parity/tier1/sash_v5), so the Sash's migration golden has an id of its own.
    "phase2/tier1/sash-v5-migration": Pilot(
        "sash-v5",
        "phase2/tier1/sash-v5-current",
        "parity/reports/phase2/sash-v5-input-inventory.md",
    ),
    "phase2/tier1/tunic-v10": Pilot(
        "tunic-v10",
        "phase2/tier1/tunic-v10-current",
        "parity/reports/phase2/tunic-v10-input-inventory.md",
    ),
}

CLAIMS = {
    "baseline_changed": False,
    "baseline_promotable": False,
    "exception_recorded": False,
    "gate_accepted": False,
    "acceptance_item_completed": False,
    "historical_input_identity_established": False,
    "owner_scope_decision": "required: decision 300 item 8",
}


@dataclass(frozen=True)
class Problem:
    severity: str  # INVALID or UNAVAILABLE
    side: str | None
    reason: str
    subject: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "side": self.side,
            "reason": self.reason,
            "subject": self.subject,
        }


@dataclass(frozen=True)
class MapInfo:
    output_id: str
    sha256: str
    storage: str  # storage_key of the recorded (and measured) format
    shape: tuple[int, ...]


@dataclass
class Side:
    name: str
    manifest_path: Path
    manifest: dict[str, Any] | None = None
    manifest_sha256: str | None = None
    record: dict[str, Any] | None = None
    environment: dict[str, Any] | None = None
    blobs: dict[str, bytes] = field(default_factory=dict)
    maps: dict[str, dict[MapKey, MapInfo]] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    def invalid(self, reason: str, subject: str = "") -> None:
        self.problems.append(Problem(INVALID, self.name, reason, subject))

    def unavailable(self, reason: str, subject: str = "") -> None:
        self.problems.append(Problem(UNAVAILABLE, self.name, reason, subject))

    @property
    def build(self) -> str:
        assert self.manifest is not None
        return str(self.manifest["software"]["painter"]["build_id"])

    def refs(self, kind: str) -> list[dict[str, Any]]:
        assert self.manifest is not None
        return [r for r in self.manifest["private_records"] if r["kind"] == kind]

    def record_sha256(self) -> str | None:
        refs = self.refs(RECORD_KIND) if self.manifest is not None else []
        return str(refs[0]["sha256"]) if len(refs) == 1 else None

    def environment_sha256(self) -> str | None:
        refs = self.refs(ENVIRONMENT_KIND) if self.manifest is not None else []
        return str(refs[0]["sha256"]) if len(refs) == 1 else None


def _repository_path(path: Path, repo_root: Path) -> str | None:
    """The repository-relative path, or None for a manifest outside the repository."""
    resolved = path.resolve()
    root = repo_root.resolve()
    return resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else None


# --- 1. manifests --------------------------------------------------------------------------------


@cache
def _schema_parts(schema: Schema) -> tuple[Draft202012Validator, frozenset[str]]:
    """The validator and every property name the schema itself declares."""
    document = load_schema(schema)
    names: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(str(k) for k in properties)
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(document)
    return Draft202012Validator(document, format_checker=FormatChecker()), frozenset(names)


def schema_summary(document: Any, schema: Schema) -> str | None:
    """None when `document` is valid; else a count and the first violation's path, cut at the
    first segment the schema does not name. Validator messages embed the document's values (a
    private record's readbacks), so no message is ever reported."""
    validator, names = _schema_parts(schema)
    errors = sorted(
        validator.iter_errors(document), key=lambda e: [str(p) for p in e.absolute_path]
    )
    if not errors:
        return None
    safe: list[str] = []
    for part in errors[0].absolute_path:
        if not isinstance(part, int) and part not in names:
            safe.append("*")
            break
        safe.append(str(part))
    return f"{len(errors)} violation(s); first at {'/'.join(safe) or '<root>'}"


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    names = [name for name, _ in pairs]
    if len(names) != len(set(names)):
        raise ValueError("a JSON object repeats a member")  # never names it: it may be private
    return dict(pairs)


def strict_loads(data: bytes) -> Any:
    """UTF-8 JSON whose objects never repeat a member (`json.loads` would keep the last one);
    ValueError otherwise (JSONDecodeError and UnicodeDecodeError are ValueErrors)."""
    return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_members)


def load_manifest(side: Side) -> None:
    try:
        data = side.manifest_path.read_bytes()
    except OSError:
        side.invalid("manifest_unreadable")
        return
    side.manifest_sha256 = hashlib.sha256(data).hexdigest()
    try:
        manifest = strict_loads(data)
    except ValueError:
        side.invalid("manifest_unparseable")
        return
    summary = schema_summary(manifest, Schema.GOLDEN_PUBLIC)
    if summary is not None:
        side.invalid("manifest_schema", summary)
        return
    if manifest["tier"] != "1":
        side.invalid("manifest_not_tier1", str(manifest["tier"]))
        return
    counts = Counter(str(r["record_id"]) for r in manifest["private_records"])
    for record_id, count in sorted(counts.items()):
        if count > 1:
            side.invalid("duplicate_private_record", record_id)
    if side.problems:
        return
    side.manifest = manifest


def pairing(migration: Mapping[str, Any], current: Mapping[str, Any]) -> list[Problem]:
    historical, candidate = str(migration["golden_id"]), str(current["golden_id"])
    if historical == candidate:
        return [Problem(INVALID, None, "equal_pilot_ids", historical)]
    pilot = PILOTS.get(historical)
    if pilot is None:
        return [Problem(INVALID, MIGRATION, "unknown_pilot", historical)]
    if candidate != pilot.current_id:
        return [
            Problem(INVALID, CURRENT, "wrong_current_pilot", f"{candidate} != {pilot.current_id}")
        ]
    problems = []
    for side, manifest, interface in (
        (MIGRATION, migration, HISTORICAL_INTERFACE),
        (CURRENT, current, CURRENT_INTERFACE),
    ):
        found = manifest["instruction_sequence"].get("interface")
        if found != interface:
            problems.append(Problem(INVALID, side, "wrong_interface", f"{found} != {interface}"))
    return problems


# --- 2. store ------------------------------------------------------------------------------------


def resolve(side: Side, store: OracleStore | None) -> None:
    """Every named record admitted and its blob verified; kept bytes for the kinds compared."""
    assert side.manifest is not None
    golden_id = str(side.manifest["golden_id"])
    for ref in side.manifest["private_records"]:
        record_id, sha = str(ref["record_id"]), str(ref["sha256"])
        size, kind = int(ref["size_bytes"]), str(ref["kind"])
        if store is None:
            side.unavailable("no_store", record_id)
            continue
        try:
            entry = store.entry(side.build, golden_id, record_id)
        except (StoreError, OSError, ValueError, TypeError, KeyError):
            side.unavailable("store_entry_unusable", record_id)
            continue
        if entry is None:
            side.unavailable("not_admitted", record_id)
            continue
        if (entry.kind, entry.sha256, entry.size_bytes) != (kind, sha, size):
            side.unavailable("admission_differs", record_id)  # not this blob's admission
            continue
        data = store.load(sha, size) if kind in KEPT_KINDS else None
        if data is not None:
            side.blobs[sha] = data
            continue
        resolution = store.resolve(record_id, sha, size)
        if resolution.status is not Status.AVAILABLE:
            missing = resolution.reason.startswith("blob missing")
            side.unavailable("blob_missing" if missing else "blob_corrupt", record_id)
        elif kind in KEPT_KINDS:  # verified now, but it failed to load a moment ago
            side.unavailable("blob_corrupt", record_id)


# --- 3. record and environment -------------------------------------------------------------------


def _duplicates(values: Sequence[Any]) -> list[Any]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def check_record(side: Side) -> None:
    assert side.manifest is not None
    records = side.refs(RECORD_KIND)
    if len(records) != 1:
        side.invalid("record_ref_count", str(len(records)))
        return
    data = side.blobs.get(str(records[0]["sha256"]))
    if data is None:
        return  # unavailable, already reported
    try:
        record = strict_loads(data)
    except ValueError:
        side.invalid("record_unparseable")
        return
    if not isinstance(record, dict):
        side.invalid("record_unparseable")
        return
    summary = schema_summary(record, Schema.GOLDEN_PRIVATE)
    if summary is not None:
        side.invalid("record_schema", summary)
        return
    problems = record_problems(record)
    if problems:  # cross-field rules, counted only: their messages quote recorded values
        side.invalid("record_rules", f"{len(problems)} violation(s)")
        return
    manifest = side.manifest
    # The record is the job of this side's own manifest (never compared with the other side's).
    pinned = [{"input_id": i["input_id"], "sha256": i.get("sha256")} for i in manifest["inputs"]]
    if record["key"]["inputs"] != pinned:
        side.invalid("record_inputs_differ_from_manifest")
    steps = sha256_bytes(canonical_json(manifest["instruction_sequence"]))
    if record["key"]["instruction_sequence_sha256"] != steps:
        side.invalid("record_instructions_differ_from_manifest")
    if record["golden_id"] != manifest["golden_id"]:
        side.invalid("record_golden_differs", str(record["golden_id"]))
    if record["tier"] != manifest["tier"]:
        side.invalid("record_tier_differs", str(record["tier"]))
    if record["key"]["painter_build"]["build_id"] != side.build:
        side.invalid("record_build_differs", str(record["key"]["painter_build"]["build_id"]))
    recordings = record["recordings"]
    ids = [str(r["recording_id"]) for r in recordings]
    for duplicate in _duplicates(ids):
        side.invalid("duplicate_recording", duplicate)
    for missing in sorted(set(CONDITIONS) - set(ids)):
        side.invalid("missing_recording", missing)
    for extra in sorted(set(ids) - set(CONDITIONS)):
        side.invalid("unexpected_recording", extra)
    sessions = {str(r["recording_id"]): r["session_id"] for r in recordings}
    if R1 in sessions and R1_REPEAT in sessions and sessions[R1] != sessions[R1_REPEAT]:
        side.invalid("repeat_not_same_session", R1_REPEAT)
    for recording in recordings:
        rid = str(recording["recording_id"])
        if rid in CONDITIONS and recording["condition"] != CONDITIONS[rid]:
            side.invalid("wrong_condition", f"{rid}: {recording['condition']}")
        outputs = recording["outputs"]
        for duplicate in _duplicates([str(o["output_id"]) for o in outputs]):
            side.invalid("duplicate_output", f"{rid}: {duplicate}")
        keys = [(str(o["texture_set"]), str(o["map"])) for o in outputs if o["kind"] == MAP_KIND]
        for texture_set, name in _duplicates(keys):
            side.invalid("duplicate_map", f"{rid}: {texture_set}/{name}")
    named = Counter(
        (str(o["kind"]), str(o["blob"]["sha256"]), int(o["blob"]["size_bytes"]))
        for r in recordings
        for o in r["outputs"]
        if "blob" in o
    )
    listed = Counter(
        (str(r["kind"]), str(r["sha256"]), int(r["size_bytes"]))
        for r in manifest["private_records"]
        if r["kind"] not in (RECORD_KIND, ENVIRONMENT_KIND)
    )
    if named != listed:
        side.invalid(
            "manifest_record_mismatch",
            f"{sum((named - listed).values())} unlisted, {sum((listed - named).values())} unnamed",
        )
    check_environment(side, record)
    if not any(p.severity == INVALID for p in side.problems):
        side.record = record


def check_environment(side: Side, record: Mapping[str, Any]) -> None:
    refs = side.refs(ENVIRONMENT_KIND)
    if len(refs) != 1:
        side.invalid("environment_ref_count", str(len(refs)))
        return
    data = side.blobs.get(str(refs[0]["sha256"]))
    if data is None:
        return  # unavailable, already reported
    try:
        environment = strict_loads(data)
    except ValueError:
        side.invalid("environment_unparseable")
        return
    problems = environment_problems(environment)
    if problems:  # counted only: the messages quote the record's values
        side.invalid("environment_schema", f"{len(problems)} violation(s)")
        return
    if environment["painter_build"] not in (UNKNOWN, side.build):
        side.invalid("environment_build_differs", str(environment["painter_build"]))
    embedded = record.get("environment")
    if embedded is not None and environment_bytes(embedded) != environment_bytes(environment):
        side.invalid("environment_differs_from_record")
    side.environment = environment


# --- 4. maps -------------------------------------------------------------------------------------


def measure(data: bytes, media_type: str) -> StorageFormat:
    """The storage format measured from the bytes, as the recorder measures an export."""
    if data.startswith(PNG_SIGNATURE):
        return png_format(data)
    if len(data) >= 4 and int.from_bytes(data[:4], "little", signed=True) == EXR_MAGIC:
        return exr_format(data)
    if media_type == MEDIA_TYPES["tga"]:
        header = tga.inspect(data)
        return StorageFormat("tga", "uint", 8, header.channels, None)
    raise ValueError("container not recognised")


def _agrees(measured: StorageFormat, recorded: Mapping[str, Any], media_type: str) -> bool:
    if (
        measured.container,
        measured.sample_type,
        measured.bits_per_channel,
        measured.channels,
    ) != (
        recorded["container"],
        recorded["sample_type"],
        recorded["bits_per_channel"],
        recorded["channels"],
    ):
        return False
    if MEDIA_TYPES.get(measured.container) != media_type:
        return False
    # A file that states its encoding must state the recorded one; a file that states none
    # carries the encoding its export settings gave (the recorder's `encoding_basis`).
    return measured.encoding is None or measured.encoding == recorded["encoding"]


@dataclass(frozen=True)
class Decoding:
    """What verification keeps of one native decoding: never the values (a 4096 px 16-bit RGB map
    is 400 MB as int64), only their shape, depth and type."""

    shape: tuple[int, ...]
    bits: int
    integer: bool


def _shape_agrees(decoded: Decoding, measured: StorageFormat) -> bool:
    return (
        len(decoded.shape) == 3
        and decoded.shape[2] == measured.channels
        and decoded.bits == measured.bits_per_channel
        and decoded.integer == (measured.sample_type == "uint")
    )


def verify_maps(side: Side) -> None:
    """Measure, decode and index every exported map of every recording."""
    assert side.record is not None
    measured: dict[tuple[str, str], tuple[StorageFormat, Decoding | None] | None] = {}
    for recording in side.record["recordings"]:
        rid = str(recording["recording_id"])
        maps: dict[MapKey, MapInfo] = {}
        for output in recording["outputs"]:
            if output["kind"] != MAP_KIND:
                continue
            blob, recorded = output["blob"], output["storage_format"]
            sha, media_type = str(blob["sha256"]), str(blob["media_type"])
            subject = f"{rid}: {output['output_id']}"
            data = side.blobs.get(sha)
            if data is None:
                continue  # unavailable, already reported
            if (sha, media_type) not in measured:
                measured[sha, media_type] = _measure_blob(data, media_type)
            shape = _verify_output(side, measured[sha, media_type], media_type, recorded, subject)
            if shape is not None:
                key = (str(output["texture_set"]), str(output["map"]))
                storage = storage_key(dict(recorded))
                maps[key] = MapInfo(str(output["output_id"]), sha, storage, shape)
        side.maps[rid] = maps
    if not any(
        o["kind"] == MAP_KIND
        for r in side.record["recordings"]
        for o in r["outputs"]
        if r["recording_id"] == R1
    ):
        side.invalid("no_exported_maps", R1)


def _measure_blob(data: bytes, media_type: str) -> tuple[StorageFormat, Decoding | None] | None:
    """One blob's measured format and a summary of its native decoding, once per SHA-256 and
    media type; the decoded values are released at once. None when it cannot be measured; no
    summary when it cannot be decoded."""
    try:
        found = measure(data, media_type)
    except Exception:
        return None
    try:
        decoded = decode(data)
    except Exception:
        return found, None
    shape = tuple(int(n) for n in decoded.values.shape)
    return found, Decoding(shape, decoded.bits, decoded.integer)


def _verify_output(
    side: Side,
    found: tuple[StorageFormat, Decoding | None] | None,
    media_type: str,
    recorded: Mapping[str, Any],
    subject: str,
) -> tuple[int, ...] | None:
    """Each output's own media type and recorded format against its blob's measurement; the
    decoded shape, or None when refused."""
    measured, decoded = found if found is not None else (None, None)
    if measured is None or decoded is None:
        side.invalid("map_undecodable", subject)
        return None
    if not _agrees(measured, recorded, media_type) or not _shape_agrees(decoded, measured):
        side.invalid("map_format_unverified", subject)
        return None
    return decoded.shape


# --- 5. stability --------------------------------------------------------------------------------


def values_equal(a: Decoded, b: Decoded) -> bool:
    """Native decoded values equal; a NaN equals only a NaN (CONTRACT.md §3.1)."""
    if a.values.shape != b.values.shape or a.integer != b.integer or a.bits != b.bits:
        return False
    return bool(np.array_equal(a.values, b.values, equal_nan=not a.integer))


def _decoder(blobs: Mapping[str, bytes]) -> Callable[[str], Decoded]:
    return lambda sha: decode(blobs[sha])


def stability(side: Side) -> dict[str, Any]:
    """`r1` against `r1-repeat` and `r2`, in bytes and in values; the side's classes."""
    first = side.maps[R1]
    load = _decoder(side.blobs)
    pairs: list[dict[str, Any]] = []
    unstable: dict[str, list[str]] = {"bytes": [], "values": []}
    for other_id, kind in ((R1_REPEAT, "same-session"), (R2, "save-reopen")):
        other = side.maps[other_id]
        structure = set(first) == set(other) and all(
            (first[k].storage, first[k].shape) == (other[k].storage, other[k].shape) for k in first
        )
        same_bytes = same_values = 0
        if structure:
            for key in sorted(first):
                if first[key].sha256 == other[key].sha256:
                    same_bytes += 1
                    same_values += 1
                elif values_equal(load(first[key].sha256), load(other[key].sha256)):
                    same_values += 1
        if not (structure and same_bytes == len(first)):
            unstable["bytes"].append(kind)
        if not (structure and same_values == len(first)):
            unstable["values"].append(kind)
        pairs.append(
            {
                "recording": other_id,
                "condition": CONDITIONS[other_id],
                "structure_equal": structure,
                "maps": len(first),
                "bytes_equal_maps": same_bytes,
                "values_equal_maps": same_values,
            }
        )

    def label(kinds: list[str]) -> str:
        return "stable" if not kinds else "-and-".join(kinds) + "-unstable"

    return {
        "class": label(unstable["bytes"]),
        "values_class": label(unstable["values"]),
        "pairs": pairs,
    }


# --- 7-8. structure and equality -----------------------------------------------------------------


def map_table(
    sides: Mapping[str, Side],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Per (texture set, map) of either side's recordings: availability, storage, shape, and the
    structural differences of the two `r1` exports."""
    keys = sorted({k for s in sides.values() for k in s.maps[R1]})
    rows: list[dict[str, Any]] = []
    structural: list[dict[str, str]] = []
    for key in keys:
        name = f"{key[0]}/{key[1]}"
        m, c = sides[MIGRATION].maps[R1].get(key), sides[CURRENT].maps[R1].get(key)
        row: dict[str, Any] = {
            "texture_set": key[0],
            "map": key[1],
            "availability": {
                s.name: {rid: key in s.maps[rid] for rid in CONDITIONS} for s in sides.values()
            },
            "storage": {MIGRATION: m.storage if m else None, CURRENT: c.storage if c else None},
            "shape": {
                MIGRATION: list(m.shape) if m else None,
                CURRENT: list(c.shape) if c else None,
            },
            "structural": None,
        }
        reason = (
            "missing_from_current"
            if c is None
            else "missing_from_migration"
            if m is None
            else "storage_format_differs"
            if m.storage != c.storage
            else "shape_differs"
            if m.shape != c.shape
            else None
        )
        if reason is not None:
            row["structural"] = reason
            structural.append({"map": name, "reason": reason})
        rows.append(row)
    return rows, structural


def equality(sides: Mapping[str, Side], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bytes and native values of each paired `r1` map (called only without structural
    differences)."""
    migration, current = sides[MIGRATION], sides[CURRENT]
    bytes_equal = values_equal_count = 0
    for row in rows:
        key = (row["texture_set"], row["map"])
        m, c = migration.maps[R1][key], current.maps[R1][key]
        same_bytes = m.sha256 == c.sha256
        row["bytes_equal"] = same_bytes
        if same_bytes:
            row.update(values_equal=True, differing_values=0, max_abs_diff=0)
        else:
            a, b = decode(migration.blobs[m.sha256]), decode(current.blobs[c.sha256])
            same = values_equal(a, b)
            stats = None if same else diagnose(a.values, b.values)
            row.update(
                values_equal=same,
                differing_values=0 if stats is None else stats.differing_count,
                max_abs_diff=0 if stats is None else _number(stats.max_abs_diff),
            )
        bytes_equal += same_bytes
        values_equal_count += bool(row["values_equal"])
    return {
        "status": "compared",
        "maps": len(rows),
        "bytes_equal_maps": bytes_equal,
        "values_equal_maps": values_equal_count,
    }


def _number(value: float) -> float | int | str:
    if not np.isfinite(value):
        return str(value)
    return int(value) if float(value).is_integer() else float(value)


# --- report --------------------------------------------------------------------------------------


def _inputs(manifest: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    if manifest is None:
        return None
    return [
        {"input_id": i["input_id"], "kind": i.get("kind"), "sha256": i.get("sha256")}
        for i in manifest["inputs"]
    ]


def _inventory(pilot: Pilot | None, repo_root: Path) -> dict[str, Any] | None:
    if pilot is None:
        return None
    path = repo_root / pilot.inventory
    sha = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {"path": pilot.inventory, "sha256": sha}


def _side_block(side: Side, repo_root: Path) -> dict[str, Any]:
    manifest = side.manifest
    return {
        "golden_id": manifest["golden_id"] if manifest else None,
        "interface": manifest["instruction_sequence"].get("interface") if manifest else None,
        "painter_build": side.build if manifest else None,
        "manifest_path": _repository_path(side.manifest_path, repo_root),
        "manifest_sha256": side.manifest_sha256,
        "record_sha256": side.record_sha256(),
        "environment_sha256": side.environment_sha256(),
        "envelope_sha256": envelope_sha256(side.environment) if side.environment else None,
        "recordings": (
            [
                {
                    "recording_id": r["recording_id"],
                    "condition": r["condition"],
                    "maps": len(side.maps.get(str(r["recording_id"]), {})),
                }
                for r in side.record["recordings"]
            ]
            if side.record
            else None
        ),
        "stability": None,
    }


def compare(
    migration_path: Path,
    current_path: Path,
    store: OracleStore | None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """The aggregate report of one pilot's current reference against its historical golden."""
    sides = {MIGRATION: Side(MIGRATION, migration_path), CURRENT: Side(CURRENT, current_path)}
    problems: list[Problem] = []
    for side in sides.values():
        load_manifest(side)
    migration, current = sides[MIGRATION], sides[CURRENT]
    pilot: Pilot | None = None
    if migration.manifest is not None and current.manifest is not None:
        problems += pairing(migration.manifest, current.manifest)
        if not problems:
            pilot = PILOTS[str(migration.manifest["golden_id"])]
    if pilot is not None:
        inventory = repo_root / pilot.inventory
        if not inventory.is_file():
            problems.append(Problem(INVALID, None, "inventory_missing", pilot.inventory))
    verified = pilot is not None and not problems
    if verified:
        for side in sides.values():
            resolve(side, store)
            if side.manifest is not None and not any(p.severity == INVALID for p in side.problems):
                check_record(side)
            if side.record is not None:
                verify_maps(side)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "record_class": "current_reference_comparison",
        "pilot": pilot.name if pilot else None,
        "outcome": INVALID,
        "problems": [],
        "claims": dict(CLAIMS),
        "inputs": {
            "inventory": _inventory(pilot, repo_root),
            MIGRATION: _inputs(migration.manifest),
            CURRENT: _inputs(current.manifest),
            "note": "output equality does not prove historical input identity",
        },
        "envelope_match": None,
        "sides": {name: _side_block(side, repo_root) for name, side in sides.items()},
        "maps": [],
        "structural": [],
        "equality": {"status": "not_compared"},
    }
    for side in sides.values():
        problems += side.problems
    # Each fully verified side is classified, and the environments are matched, even when the
    # other side is unavailable, so an unavailable blob never hides an invalid side.
    for name, side in sides.items():
        if verified and not side.problems and len(side.maps) == len(CONDITIONS):
            block = stability(side)
            report["sides"][name]["stability"] = block
            if block["class"] != "stable":
                problems.append(Problem(INVALID, name, "side_unstable", block["class"]))
    if verified and migration.environment is not None and current.environment is not None:
        match = envelope_match(migration.environment, current.environment)
        report["envelope_match"] = match
        if match != MATCH:
            problems.append(Problem(INVALID, None, "out_of_envelope", match))
    if verified and not problems:
        rows, structural = map_table(sides)
        report["maps"], report["structural"] = rows, structural
        if not structural:
            report["equality"] = equality(sides, rows)
    report["problems"] = [p.as_json() for p in problems]
    report["outcome"] = _outcome(problems, report)
    return report


def _outcome(problems: Sequence[Problem], report: Mapping[str, Any]) -> str:
    severities = {p.severity for p in problems}
    if INVALID in severities:
        return INVALID
    if UNAVAILABLE in severities:
        return UNAVAILABLE
    if report["structural"]:
        return DIFFERENT
    equal = report["equality"]
    if equal["status"] != "compared":
        return INVALID
    return IDENTICAL if equal["bytes_equal_maps"] == equal["maps"] else DIFFERENT


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.current_reference",
        description=(
            "Compare a pilot's current reference golden with its retained historical golden "
            "(decision 300 item 7). Prints one aggregate JSON report; writes nothing. Exit "
            "0 identical, 1 different, 2 invalid, 3 oracle_unavailable."
        ),
    )
    parser.add_argument("--migration", type=Path, required=True, help="historical manifest")
    parser.add_argument("--current", type=Path, required=True, help="the -current manifest")
    parser.add_argument("--store", type=Path, help="private store root (default: this machine's)")
    args = parser.parse_args(argv)
    try:
        store = OracleStore.open(args.store) if args.store is not None else locate()
    except StoreError:
        store = None
    report = compare(args.migration, args.current, store)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return EXIT_CODES[str(report["outcome"])]


if __name__ == "__main__":
    raise SystemExit(main())
