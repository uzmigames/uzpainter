"""The current-reference comparator on authored goldens (decision 300 items 7-8).

Every "recorded" map here is a 4x4 PNG this test encodes itself and admits to a temporary private
store, with an authored record, environment and manifest. Nothing comes from Painter, no golden
is written into the repository and nothing here claims parity or changes a baseline: real
current references do not exist yet.

Test limit: only PNG is authored. The comparator's OpenEXR and TGA8 paths (measurement and native
decoding) are not exercised by real or authored EXR or TGA exports here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from tools.parity.feasibility import png
from tools.parity.recorder.capture import MEDIA_TYPES
from tools.parity.recorder.environment import environment_bytes
from tools.parity.recorder.job import canonical_json, sha256_bytes
from tools.parity.recorder.texture import UNDETERMINED
from tools.parity.schemas import REPO_ROOT, Schema, load_json, record_problems, validation_errors
from tools.parity.store.store import OracleStore
from tools.parity.tier1 import current_reference
from tools.parity.tier1.current_reference import (
    DIFFERENT,
    IDENTICAL,
    INVALID,
    UNAVAILABLE,
    compare,
    main,
    measure,
)

BUILD = "12.2.0+js-api.1.1.20"
TUNIC, TUNIC_CURRENT = "phase2/tier1/tunic-v10", "phase2/tier1/tunic-v10-current"
SASH, SASH_CURRENT = "phase2/tier1/sash-v5-migration", "phase2/tier1/sash-v5-current"
SASH_SCRIPT = "phase2/tier1/sash-v5"  # the original script golden (decision 260), never a pilot
SET = "DefaultMaterial"
MANIFESTS = REPO_ROOT / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests"
# Public manifests whose inputs and steps the authored goldens borrow: a migration golden for the
# historical side and a pipeline-script golden for the current side (decision 300 item 7).
TEMPLATE = MANIFESTS / "phase2/tier1/tunic-v10.json"
SCRIPT_TEMPLATE = MANIFESTS / "phase1/tier1/wand-v1.json"
ENVIRONMENT: dict[str, Any] = {
    "schema": "uzpainter/parity/oracle-environment/1",
    "basis": "recorded",
    "painter_build": BUILD,
    "gpu_model": "Synthetic GPU",
    "driver_version": "1.0.0",
    "os_build": "10.0.1.1",
    "colour_configuration_sha256": "a" * 64,
    "recorder_version": "uzp-recorder/test",
}
CONDITIONS = {"r1": "same_session", "r1-repeat": "same_session", "r2": "after_save_reopen"}

Maps = dict[str, bytes]  # map name -> encoded file
Mutate = Callable[[dict[str, Any]], None]


def png_bytes(
    values: npt.NDArray[Any],
    depth: int = 16,
    *,
    level: int = 9,
    extra: tuple[tuple[bytes, bytes], ...] = (),
) -> bytes:
    """A PNG of `values`, recompressed at `level`, with `extra` chunks after IHDR."""
    chunks = png.chunks(png.encode(values, depth))
    body = {kind: data for kind, data in chunks}
    raw = zlib.decompress(body[b"IDAT"])

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    return (
        png.SIGNATURE
        + chunk(b"IHDR", body[b"IHDR"])
        + b"".join(chunk(k, d) for k, d in extra)
        + chunk(b"IDAT", zlib.compress(raw, level))
        + chunk(b"IEND", b"")
    )


SRGB = ((b"sRGB", b"\x00"),)
LINEAR = ((b"gAMA", struct.pack(">I", 100000)),)


def colour(shift: int = 0, size: int = 4) -> npt.NDArray[np.uint16]:
    codes = (np.arange(size * size * 3, dtype=np.int64).reshape(size, size, 3) * 1000) % 60000
    return (codes + shift).astype(np.uint16)


def standard_maps() -> Maps:
    return {
        "BaseColor": png_bytes(colour(), extra=SRGB),
        "Roughness": png_bytes(colour()[..., :1] + 7, extra=LINEAR),
    }


def three(maps: Maps) -> dict[str, Maps]:
    return {rid: dict(maps) for rid in CONDITIONS}


def storage_format(data: bytes) -> dict[str, Any]:
    measured = measure(data, MEDIA_TYPES["png"])
    return measured.as_schema(measured.encoding or UNDETERMINED)


def admit(
    store: OracleStore, tmp: Path, golden_id: str, record_id: str, kind: str, data: bytes
) -> dict[str, Any]:
    sha = hashlib.sha256(data).hexdigest()
    source = tmp / "authored" / sha
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    store.add_record(BUILD, golden_id, record_id, kind, source, sha, sha)
    return {"record_id": record_id, "kind": kind, "sha256": sha, "size_bytes": len(data)}


def author(
    tmp: Path,
    store: OracleStore,
    golden_id: str,
    recordings: dict[str, Maps],
    *,
    environment: dict[str, Any] | None = None,
    mutate: Mutate | None = None,
    formats: dict[str, dict[str, Any]] | None = None,
    template: Path | None = None,
    valid: bool = True,
    record_text: Callable[[str], str] | None = None,
    environment_data: bytes | None = None,
) -> Path:
    """Admit an authored golden of `recordings` (id -> maps) and write its public manifest; the
    record's key binds the template's inputs and steps, as the recorder writes it."""
    environment = dict(ENVIRONMENT if environment is None else environment)
    if template is None:
        template = SCRIPT_TEMPLATE if golden_id.endswith("-current") else TEMPLATE
    manifest = load_json(template)
    outputs_of: dict[str, list[dict[str, Any]]] = {}
    for rid, maps in recordings.items():
        outputs_of[rid] = [
            {
                "output_id": f"export/{name}",
                "kind": "exported_map",
                "texture_set": SET,
                "map": name,
                "blob": {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                    "media_type": "image/png",
                },
                "storage_format": (formats or {}).get(name) or storage_format(data),
                "export_settings": {},
            }
            for name, data in maps.items()
        ]
    record: dict[str, Any] = {
        "schema": "uzpainter/parity/golden-private/1",
        "record_class": "private_oracle_record",
        "golden_id": golden_id,
        "tier": "1",
        "key": {
            "inputs": [
                {"input_id": i["input_id"], "sha256": i["sha256"]} for i in manifest["inputs"]
            ],
            "instruction_sequence_sha256": sha256_bytes(
                canonical_json(manifest["instruction_sequence"])
            ),
            "effective_defaults": {},
            "painter_build": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.2.0",
                "build_id": BUILD,
            },
            "project_settings": {},
            "resource_hashes": [],
            "bake_backend": None,
            "render_state": None,
        },
        "environment": environment,
        "recordings": [
            {
                "recording_id": rid,
                "condition": CONDITIONS.get(rid, "same_session"),
                "session_id": "synthetic-session",
                "recorded_at": "2026-11-02T12:00:00Z",
                "outputs": outputs,
            }
            for rid, outputs in outputs_of.items()
        ],
    }
    if mutate is not None:
        mutate(record)
    assert (record_problems(record) == []) is valid
    blobs = {
        o["blob"]["sha256"]: recordings[r["recording_id"]][o["map"]]
        for r in record["recordings"]
        if r["recording_id"] in recordings
        for o in r["outputs"]
        if "blob" in o and o.get("map") in recordings[r["recording_id"]]
    }
    refs = [
        admit(
            store,
            tmp,
            golden_id,
            "golden-record",
            "private_oracle_record",
            (record_text or str)(json.dumps(record)).encode(),
        )
    ]
    seen: set[str] = set()
    for r in record["recordings"]:
        for index, o in enumerate(r["outputs"]):
            if "blob" not in o:
                continue
            record_id = f"{r['recording_id']}-{index}-export"
            while record_id in seen:  # a duplicated recording still gets unique manifest ids
                record_id += "-again"
            seen.add(record_id)
            refs.append(
                admit(store, tmp, golden_id, record_id, o["kind"], blobs[o["blob"]["sha256"]])
            )
    refs.append(
        admit(
            store,
            tmp,
            golden_id,
            "oracle-environment",
            "oracle_environment_record",
            environment_data or environment_bytes(environment),
        )
    )
    manifest["golden_id"] = golden_id
    manifest["private_records"] = refs
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    path = tmp / "manifests" / f"{golden_id.replace('/', '__')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path: Path) -> OracleStore:
    return OracleStore.init(tmp_path / "store")


def pair(
    tmp: Path,
    store: OracleStore,
    current: dict[str, Maps] | None = None,
    migration: dict[str, Maps] | None = None,
    **current_options: Any,
) -> tuple[Path, Path]:
    historical = author(tmp, store, TUNIC, migration or three(standard_maps()))
    candidate = author(
        tmp, store, TUNIC_CURRENT, current or three(standard_maps()), **current_options
    )
    return historical, candidate


def reasons(report: dict[str, Any]) -> set[str]:
    return {p["reason"] for p in report["problems"]}


def blob_file(store: OracleStore, manifest: Path, record_id: str) -> Path:
    ref = next(r for r in load_json(manifest)["private_records"] if r["record_id"] == record_id)
    path = store.blob_path(ref["sha256"])
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    return path


# --- outcomes ------------------------------------------------------------------------------------


def test_three_identical_recordings_on_both_sides_are_identical(
    tmp_path: Path, store: OracleStore
) -> None:
    historical, candidate = pair(tmp_path, store)
    report = compare(historical, candidate, store)
    assert report["outcome"] == IDENTICAL, report["problems"]
    assert report["pilot"] == "tunic-v10"
    assert report["envelope_match"] == "match"
    assert report["equality"] == {
        "status": "compared",
        "maps": 2,
        "bytes_equal_maps": 2,
        "values_equal_maps": 2,
    }
    for name, path in (("migration", historical), ("current", candidate)):
        side = report["sides"][name]
        assert side["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        refs = {r["kind"]: r["sha256"] for r in load_json(path)["private_records"]}
        assert side["record_sha256"] == refs["private_oracle_record"]
        assert side["environment_sha256"] == refs["oracle_environment_record"]
        assert len(side["envelope_sha256"]) == 64
        assert side["stability"]["class"] == side["stability"]["values_class"] == "stable"
        assert [p["bytes_equal_maps"] for p in side["stability"]["pairs"]] == [2, 2]
    assert (
        report["inputs"]["inventory"]["path"]
        == "parity/reports/phase2/tunic-v10-input-inventory.md"
    )
    assert report["inputs"]["inventory"]["sha256"] is not None


def test_one_code_difference_is_different(tmp_path: Path, store: OracleStore) -> None:
    shifted = colour()
    shifted[2, 1, 0] += 1
    maps = {**standard_maps(), "BaseColor": png_bytes(shifted, extra=SRGB)}
    report = compare(*pair(tmp_path, store, three(maps)), store)
    assert report["outcome"] == DIFFERENT
    row = next(m for m in report["maps"] if m["map"] == "BaseColor")
    assert (row["bytes_equal"], row["values_equal"]) == (False, False)
    assert (row["differing_values"], row["max_abs_diff"]) == (1, 1)
    assert report["equality"]["values_equal_maps"] == 1


def test_byte_different_but_pixel_identical_png_is_different(
    tmp_path: Path, store: OracleStore
) -> None:
    maps = {**standard_maps(), "BaseColor": png_bytes(colour(), extra=SRGB, level=1)}
    assert maps["BaseColor"] != standard_maps()["BaseColor"]
    report = compare(*pair(tmp_path, store, three(maps)), store)
    assert report["outcome"] == DIFFERENT
    row = next(m for m in report["maps"] if m["map"] == "BaseColor")
    assert (row["bytes_equal"], row["values_equal"], row["differing_values"]) == (False, True, 0)
    assert report["equality"]["bytes_equal_maps"] == 1
    assert report["equality"]["values_equal_maps"] == 2


def test_r1_repeat_instability_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    recordings = three(standard_maps())
    recordings["r1-repeat"]["BaseColor"] = png_bytes(colour(shift=1), extra=SRGB)
    report = compare(*pair(tmp_path, store, recordings), store)
    assert report["outcome"] == INVALID
    assert "side_unstable" in reasons(report)
    assert report["sides"]["current"]["stability"]["class"] == "same-session-unstable"
    assert report["sides"]["migration"]["stability"]["class"] == "stable"
    assert report["equality"] == {"status": "not_compared"}


def test_r2_instability_is_invalid_and_bytes_and_values_are_classified_apart(
    tmp_path: Path, store: OracleStore
) -> None:
    recordings = three(standard_maps())
    recordings["r2"]["BaseColor"] = png_bytes(colour(), extra=SRGB, level=1)  # same values
    report = compare(*pair(tmp_path, store, migration=recordings), store)
    assert report["outcome"] == INVALID
    stability = report["sides"]["migration"]["stability"]
    assert stability["class"] == "save-reopen-unstable"
    assert stability["values_class"] == "stable"


def test_envelope_mismatch_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    environment = {**ENVIRONMENT, "driver_version": "2.0.0"}
    report = compare(*pair(tmp_path, store, environment=environment), store)
    assert report["outcome"] == INVALID
    assert report["envelope_match"] == "differs"
    assert "out_of_envelope" in reasons(report)


# --- recordings and blobs ------------------------------------------------------------------------


def drop_recording(rid: str) -> Mutate:
    def mutate(record: dict[str, Any]) -> None:
        record["recordings"] = [r for r in record["recordings"] if r["recording_id"] != rid]

    return mutate


def test_missing_recording_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    report = compare(*pair(tmp_path, store, mutate=drop_recording("r1-repeat")), store)
    assert report["outcome"] == INVALID
    assert {
        "severity": INVALID,
        "side": "current",
        "reason": "missing_recording",
        "subject": "r1-repeat",
    } in report["problems"]


def test_wrong_condition_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    def mutate(record: dict[str, Any]) -> None:
        record["recordings"][1]["condition"] = "after_save_reopen"

    report = compare(*pair(tmp_path, store, mutate=mutate), store)
    assert report["outcome"] == INVALID
    assert "wrong_condition" in reasons(report)


def test_missing_blob_is_oracle_unavailable(tmp_path: Path, store: OracleStore) -> None:
    historical, candidate = pair(
        tmp_path, store, three({**standard_maps(), "Height": png_bytes(colour(5))})
    )
    blob_file(store, candidate, "r2-2-export").unlink()
    report = compare(historical, candidate, store)
    assert report["outcome"] == UNAVAILABLE
    assert reasons(report) == {"blob_missing"}
    assert report["equality"] == {"status": "not_compared"}


def test_corrupt_blob_is_oracle_unavailable(tmp_path: Path, store: OracleStore) -> None:
    historical, candidate = pair(tmp_path, store)
    path = blob_file(store, historical, "r1-0-export")
    path.write_bytes(path.read_bytes()[:-1] + b"\x00")
    report = compare(historical, candidate, store)
    assert report["outcome"] == UNAVAILABLE
    assert reasons(report) == {"blob_corrupt"}


def test_unadmitted_record_and_no_store_are_oracle_unavailable(
    tmp_path: Path, store: OracleStore
) -> None:
    historical, candidate = pair(tmp_path, store)
    entry = store.entry_path(BUILD, TUNIC_CURRENT, "r1-0-export")
    os.chmod(entry, stat.S_IREAD | stat.S_IWRITE)
    entry.unlink()
    assert reasons(compare(historical, candidate, store)) == {"not_admitted"}
    report = compare(historical, candidate, None)
    assert report["outcome"] == UNAVAILABLE
    assert reasons(report) == {"no_store"}


def test_undecodable_blob_with_a_valid_hash_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    broken = standard_maps()["BaseColor"][:-20]  # truncated stream, admitted under its own hash
    maps = {**standard_maps(), "BaseColor": broken}
    formats = {"BaseColor": storage_format(standard_maps()["BaseColor"])}
    report = compare(*pair(tmp_path, store, three(maps), formats=formats), store)
    assert report["outcome"] == INVALID
    assert "map_undecodable" in reasons(report)


def test_a_recorded_format_the_bytes_do_not_have_is_invalid(
    tmp_path: Path, store: OracleStore
) -> None:
    claimed = {**storage_format(standard_maps()["BaseColor"]), "bits_per_channel": 8}
    report = compare(*pair(tmp_path, store, formats={"BaseColor": claimed}), store)
    assert report["outcome"] == INVALID
    assert "map_format_unverified" in reasons(report)


# --- maps ----------------------------------------------------------------------------------------


def test_missing_map_is_a_structural_difference(tmp_path: Path, store: OracleStore) -> None:
    maps = standard_maps()
    del maps["Roughness"]
    report = compare(*pair(tmp_path, store, three(maps)), store)
    assert report["outcome"] == DIFFERENT
    assert report["structural"] == [{"map": f"{SET}/Roughness", "reason": "missing_from_current"}]
    assert report["equality"] == {"status": "not_compared"}
    row = next(m for m in report["maps"] if m["map"] == "Roughness")
    assert row["availability"]["current"] == {"r1": False, "r1-repeat": False, "r2": False}
    assert "bytes_equal" not in row


def test_extra_map_is_a_structural_difference(tmp_path: Path, store: OracleStore) -> None:
    maps = {**standard_maps(), "Height": png_bytes(colour(3)[..., :1])}
    report = compare(*pair(tmp_path, store, three(maps)), store)
    assert report["outcome"] == DIFFERENT
    assert report["structural"] == [{"map": f"{SET}/Height", "reason": "missing_from_migration"}]


def test_a_map_missing_from_one_recording_makes_its_side_unstable(
    tmp_path: Path, store: OracleStore
) -> None:
    recordings = three(standard_maps())
    del recordings["r2"]["Roughness"]
    report = compare(*pair(tmp_path, store, recordings), store)
    assert report["outcome"] == INVALID
    pairs = report["sides"]["current"]["stability"]["pairs"]
    assert [p["structure_equal"] for p in pairs] == [True, False]


def duplicate_map(record: dict[str, Any]) -> None:
    first = copy.deepcopy(record["recordings"][0]["outputs"][0])
    first["output_id"] = "export/BaseColor-again"
    record["recordings"][0]["outputs"].append(first)


def duplicate_output(record: dict[str, Any]) -> None:
    second = record["recordings"][0]["outputs"][1]
    second["output_id"] = record["recordings"][0]["outputs"][0]["output_id"]


def duplicate_recording(record: dict[str, Any]) -> None:
    record["recordings"].append(copy.deepcopy(record["recordings"][0]))


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (duplicate_map, "duplicate_map"),
        (duplicate_output, "duplicate_output"),
        (duplicate_recording, "duplicate_recording"),
    ],
)
def test_duplicates_in_the_raw_record_are_invalid(
    tmp_path: Path, store: OracleStore, mutate: Mutate, reason: str
) -> None:
    report = compare(*pair(tmp_path, store, mutate=mutate), store)
    assert report["outcome"] == INVALID
    assert reason in reasons(report)
    assert report["maps"] == []


@pytest.mark.parametrize(
    ("current", "reason"),
    [
        (png_bytes(colour(size=8), extra=SRGB), "shape_differs"),
        (png_bytes(colour()[..., :1], extra=SRGB), "storage_format_differs"),  # channels
        (png_bytes(colour() >> 8, 8, extra=SRGB), "storage_format_differs"),  # precision
        (png_bytes(colour(), extra=LINEAR), "storage_format_differs"),  # encoding
    ],
    ids=["dimension", "channels", "precision", "encoding"],
)
def test_format_and_shape_mismatches_are_structural(
    tmp_path: Path, store: OracleStore, current: bytes, reason: str
) -> None:
    maps = {**standard_maps(), "BaseColor": current}
    report = compare(*pair(tmp_path, store, three(maps)), store)
    assert report["outcome"] == DIFFERENT
    assert report["structural"] == [{"map": f"{SET}/BaseColor", "reason": reason}]
    assert report["equality"] == {"status": "not_compared"}


# --- pilots --------------------------------------------------------------------------------------


def test_wrong_and_equal_pilot_ids_are_invalid(tmp_path: Path, store: OracleStore) -> None:
    tunic = author(tmp_path, store, TUNIC, three(standard_maps()))
    tunic_current = author(tmp_path, store, TUNIC_CURRENT, three(standard_maps()))
    sash_current = author(tmp_path, store, SASH_CURRENT, three(standard_maps()))
    sash = author(tmp_path, store, SASH, three(standard_maps()))
    cases = [
        (tunic, sash_current, "wrong_current_pilot"),
        (sash, tunic_current, "wrong_current_pilot"),
        (tunic_current, tunic, "unknown_pilot"),
        (tunic, tunic, "equal_pilot_ids"),
    ]
    for historical, candidate, reason in cases:
        report = compare(historical, candidate, store)
        assert report["outcome"] == INVALID
        assert reasons(report) == {reason}
        assert report["pilot"] is None
        assert report["sides"]["current"]["record_sha256"] is not None  # named, never loaded
        assert report["sides"]["current"]["recordings"] is None
    assert compare(sash, sash_current, store)["outcome"] == IDENTICAL


# --- what a run touches and what the report holds ------------------------------------------------


def snapshot(*roots: Path) -> dict[str, tuple[str, int]]:
    found = {}
    for root in roots:
        paths = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in paths:
            found[str(path)] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
    return found


def test_inputs_store_and_manifests_are_unchanged_after_a_run(
    tmp_path: Path, store: OracleStore, capsys: pytest.CaptureFixture[str]
) -> None:
    historical, candidate = pair(tmp_path, store)
    inventory = REPO_ROOT / "parity/reports/phase2/tunic-v10-input-inventory.md"
    before = snapshot(tmp_path, inventory, TEMPLATE)
    reports_before = sorted(p.name for p in (REPO_ROOT / "parity/reports/phase2").iterdir())
    code = main(
        ["--migration", str(historical), "--current", str(candidate), "--store", str(store.root)]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == IDENTICAL
    assert snapshot(tmp_path, inventory, TEMPLATE) == before
    assert sorted(p.name for p in (REPO_ROOT / "parity/reports/phase2").iterdir()) == reports_before


def walk(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [value, *(x for v in value.values() for x in walk(v))]
    if isinstance(value, list):
        return [value, *(x for v in value for x in walk(v))]
    return [value]


def test_the_report_holds_aggregates_only_and_cannot_promote_a_baseline(
    tmp_path: Path, store: OracleStore, capsys: pytest.CaptureFixture[str]
) -> None:
    shifted = colour()
    shifted[0, 0, 0] += 3
    maps = {**standard_maps(), "BaseColor": png_bytes(shifted, extra=SRGB)}
    historical, candidate = pair(tmp_path, store, three(maps))
    code = main(
        ["--migration", str(historical), "--current", str(candidate), "--store", str(store.root)]
    )
    out = capsys.readouterr().out
    report = json.loads(out)
    assert code == 1 and report["outcome"] == DIFFERENT
    assert report["outcome"] in {IDENTICAL, DIFFERENT, INVALID, UNAVAILABLE}
    # No map blob hash, store path, pixel or coordinate reaches the report.
    for path in (historical, candidate):
        for ref in load_json(path)["private_records"]:
            if ref["kind"] == "exported_map":
                assert ref["sha256"] not in out
    assert str(store.root) not in out and str(tmp_path) not in out
    lists = [v for v in walk(report) if isinstance(v, list)]
    assert all(len(v) <= 3 for v in lists if v and all(isinstance(x, int) for x in v))  # shapes
    allowed = {"differing_values", "max_abs_diff", "maps", "bytes_equal_maps", "values_equal_maps"}
    for node in walk(report):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    assert key in allowed, key
    # It promotes nothing, whatever the outcome.
    claims = report["claims"]
    assert {k: v for k, v in claims.items() if k != "owner_scope_decision"} == dict.fromkeys(
        claims.keys() - {"owner_scope_decision"}, False
    )
    assert claims["owner_scope_decision"] == "required: decision 300 item 8"
    identical = compare(*pair(tmp_path / "again", OracleStore.init(tmp_path / "store2")), None)
    assert identical["claims"] == report["claims"]
    public = [n for n in dir(current_reference) if not n.startswith("_")]
    assert not [
        n for n in public if any(w in n.lower() for w in ("write", "promote", "admit", "approve"))
    ]


# --- review findings: per-output metadata, private messages, own-job binding, roles, sessions ---


def r2_claims(**changes: Any) -> Mutate:
    """r2's BaseColor shares r1's blob but its own metadata claims something else."""

    def mutate(record: dict[str, Any]) -> None:
        output = record["recordings"][2]["outputs"][0]
        for name, value in changes.items():
            target = output["blob"] if name == "media_type" else output["storage_format"]
            target[name] = value

    return mutate


@pytest.mark.parametrize(
    "changes",
    [{"bits_per_channel": 8}, {"encoding": "linear"}, {"media_type": "image/x-tga"}],
    ids=["bits", "encoding", "media-type"],
)
def test_a_shared_blob_is_verified_against_each_outputs_own_metadata(
    tmp_path: Path, store: OracleStore, changes: dict[str, Any]
) -> None:
    report = compare(*pair(tmp_path, store, mutate=r2_claims(**changes)), store)
    assert report["outcome"] == INVALID
    assert {
        "severity": INVALID,
        "side": "current",
        "reason": "map_format_unverified",
        "subject": "r2: export/BaseColor",
    } in report["problems"]
    assert reasons(report) == {"map_format_unverified"}


SENTINEL = "PRIVATE-SENTINEL-4f19c2"


def plant_sentinel(record: dict[str, Any]) -> None:
    outputs = record["recordings"][0]["outputs"]
    outputs.append(
        {"output_id": "migration/state", "kind": "api_readback", SENTINEL: {"value": SENTINEL}}
    )
    outputs[0]["blob"]["size_bytes"] = SENTINEL


def test_record_validation_never_reports_private_values(
    tmp_path: Path, store: OracleStore, capsys: pytest.CaptureFixture[str]
) -> None:
    historical, candidate = pair(tmp_path, store, mutate=plant_sentinel, valid=False)
    report = compare(historical, candidate, store)
    assert report["outcome"] == INVALID
    assert reasons(report) == {"record_schema"}
    assert SENTINEL not in json.dumps(report)
    code = main(
        ["--migration", str(historical), "--current", str(candidate), "--store", str(store.root)]
    )
    out = capsys.readouterr()
    assert code == 2
    assert SENTINEL not in out.out and SENTINEL not in out.err


def edit_manifest(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    manifest = load_json(path)
    change(manifest)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def repin_input(manifest: dict[str, Any]) -> None:
    manifest["inputs"][0]["sha256"] = "c" * 64


def change_step(manifest: dict[str, Any]) -> None:
    manifest["instruction_sequence"]["steps"][1]["args"]["config"] = "tunic-v10-project"


@pytest.mark.parametrize(
    ("side", "change", "reason"),
    [
        ("migration", repin_input, "record_inputs_differ_from_manifest"),
        ("migration", change_step, "record_instructions_differ_from_manifest"),
        ("current", repin_input, "record_inputs_differ_from_manifest"),
    ],
)
def test_each_side_is_bound_to_its_own_manifests_job(
    tmp_path: Path,
    store: OracleStore,
    side: str,
    change: Callable[[dict[str, Any]], None],
    reason: str,
) -> None:
    historical, candidate = pair(tmp_path, store)
    edit_manifest(historical if side == "migration" else candidate, change)  # refs kept
    report = compare(historical, candidate, store)
    assert report["outcome"] == INVALID
    assert {(p["side"], p["reason"]) for p in report["problems"]} == {(side, reason)}
    assert report["equality"] == {"status": "not_compared"}
    assert report["maps"] == []


def test_the_two_sides_jobs_differ_and_are_never_required_to_match(
    tmp_path: Path, store: OracleStore
) -> None:
    historical, candidate = pair(tmp_path, store)
    migration, current = load_json(historical), load_json(candidate)
    assert migration["inputs"] != current["inputs"]
    assert migration["instruction_sequence"] != current["instruction_sequence"]
    report = compare(historical, candidate, store)
    assert report["outcome"] == IDENTICAL
    assert report["claims"]["historical_input_identity_established"] is False
    assert report["sides"]["migration"]["interface"] == "painter_project_migration"
    assert report["sides"]["current"]["interface"] == "uzmigames_pipeline_scripts"


def test_a_side_with_the_wrong_interface_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    report = compare(*pair(tmp_path, store, template=TEMPLATE), store)
    assert report["outcome"] == INVALID
    assert {(p["side"], p["reason"]) for p in report["problems"]} == {
        ("current", "wrong_interface")
    }


def test_r1_repeat_from_another_session_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    def mutate(record: dict[str, Any]) -> None:
        record["recordings"][1]["session_id"] = "another-session"

    report = compare(*pair(tmp_path, store, mutate=mutate), store)
    assert report["outcome"] == INVALID
    assert reasons(report) == {"repeat_not_same_session"}


def test_a_record_without_an_embedded_environment_is_accepted(
    tmp_path: Path, store: OracleStore
) -> None:
    def mutate(record: dict[str, Any]) -> None:
        del record["environment"]  # optional for back-filled goldens (golden-private.json)

    report = compare(*pair(tmp_path, store, mutate=mutate), store)
    assert report["outcome"] == IDENTICAL, report["problems"]


# --- panel findings: repeated JSON members, masking, admission, canonical environment -----------


def repeat_tier(text: str) -> str:
    assert text.count('"tier": "1"') == 1
    return text.replace('"tier": "1"', '"tier": "2", "tier": "1"')  # json.loads keeps the last


def test_a_repeated_json_member_in_a_record_is_invalid(tmp_path: Path, store: OracleStore) -> None:
    report = compare(*pair(tmp_path, store, record_text=repeat_tier), store)
    assert report["outcome"] == INVALID
    assert {(p["side"], p["reason"]) for p in report["problems"]} == {
        ("current", "record_unparseable")
    }


def test_a_repeated_json_member_in_a_manifest_is_invalid(
    tmp_path: Path, store: OracleStore
) -> None:
    historical, candidate = pair(tmp_path, store)
    text = candidate.read_text(encoding="utf-8")
    candidate.write_text(text.replace('"tier": "1"', '"tier": "2", "tier": "1"', 1), "utf-8")
    report = compare(historical, candidate, store)
    assert report["outcome"] == INVALID
    assert reasons(report) == {"manifest_unparseable"}


def test_an_unavailable_side_never_hides_an_unstable_one(
    tmp_path: Path, store: OracleStore
) -> None:
    unstable = three(standard_maps())
    unstable["r2"]["BaseColor"] = png_bytes(colour(shift=2), extra=SRGB)
    historical = author(tmp_path, store, TUNIC, unstable)
    extra = three({**standard_maps(), "Height": png_bytes(colour(9))})
    candidate = author(tmp_path, store, TUNIC_CURRENT, extra)
    blob_file(store, candidate, "r1-2-export").unlink()
    report = compare(historical, candidate, store)
    assert report["outcome"] == INVALID
    assert {(p["side"], p["reason"]) for p in report["problems"]} == {
        ("current", "blob_missing"),
        ("migration", "side_unstable"),
    }
    assert report["sides"]["migration"]["stability"]["class"] == "save-reopen-unstable"
    assert report["sides"]["current"]["stability"] is None
    assert report["equality"] == {"status": "not_compared"}


def test_an_admission_naming_another_blob_is_oracle_unavailable(
    tmp_path: Path, store: OracleStore
) -> None:
    historical, candidate = pair(tmp_path, store)
    entry = store.entry_path(BUILD, TUNIC_CURRENT, "r1-0-export")
    os.chmod(entry, stat.S_IREAD | stat.S_IWRITE)
    document = load_json(entry)
    document["size_bytes"] += 1
    entry.write_text(json.dumps(document), encoding="utf-8")
    report = compare(historical, candidate, store)
    assert report["outcome"] == UNAVAILABLE
    assert reasons(report) == {"admission_differs"}


def test_an_equivalent_environment_serialisation_is_accepted(
    tmp_path: Path, store: OracleStore
) -> None:
    spaced = json.dumps(dict(reversed(list(ENVIRONMENT.items()))), indent=2).encode()
    assert spaced != environment_bytes(ENVIRONMENT)
    report = compare(*pair(tmp_path, store, environment_data=spaced), store)
    assert report["outcome"] == IDENTICAL, report["problems"]


def test_the_original_sash_script_id_cannot_masquerade_as_the_migration(tmp_path: Path) -> None:
    for template in (TEMPLATE, SCRIPT_TEMPLATE):  # migration-shaped or script-shaped
        root = tmp_path / template.stem
        store = OracleStore.init(root / "store")
        script = author(root, store, SASH_SCRIPT, three(standard_maps()), template=template)
        candidate = author(root, store, SASH_CURRENT, three(standard_maps()))
        report = compare(script, candidate, store)
        assert report["outcome"] == INVALID
        assert {(p["side"], p["reason"]) for p in report["problems"]} == {
            ("migration", "unknown_pilot")
        }
        assert report["pilot"] is None
        assert report["equality"] == {"status": "not_compared"}
    assert SASH_SCRIPT not in current_reference.PILOTS
