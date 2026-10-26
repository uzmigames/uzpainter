"""Read-only V2 facade replay, gated by a materialized native import.

The worker collects actual values before this module opens either oracle expectation.
SQLite checks establish the selected persisted entry; successful native getters still
have to validate its live inventory. This is comparison tooling, not an import gate.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.filter_observation_import import parse, typed_json
from tools.parity.schemas import REPO_ROOT

SCHEMA = "uzpainter/filter-context-replay/1"
REPORT_SCHEMA = "uzpainter/filter-context-replay-report/1"
OLD_GOLDEN = "tier0/api-probes/source-substance-booleans-filter"
F_GOLDEN = "tier0/api-probes/filter-context-settings-a"
SOURCE = "substance_painter.source.SourceSubstance."
GETTERS = {16: "get_parameters", 17: "resource_id", 18: "image_outputs"}
CONDITIONS = ("same_session", "after_save_reopen")
HASH = re.compile(r"[0-9a-f]{64}")
COUNTS = (
    "nonfinite_count",
    "fixed_point_mismatches",
    "upload_mismatches",
    "final_output_mismatches",
)


class ReplayRefused(ValueError):
    """Only a fixed code can escape private comparison work."""


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ReplayRefused(code)


def digest(value: Any) -> str:
    return hashlib.sha256(typed_json(value)).hexdigest()


def closed(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    require(type(value) is dict and set(value) == keys, code)
    result: dict[str, Any] = value
    return result


def positive(value: Any) -> bool:
    return type(value) is int and 0 < value < 1 << 63


def sha(value: Any) -> bool:
    return type(value) is str and HASH.fullmatch(value) is not None


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def private_path(value: Any, *, directory: bool = False) -> Path:
    require(type(value) is str and bool(value), "F_REPLAY_PRIVATE_PATH")
    path = Path(value)
    require(path.is_absolute(), "F_REPLAY_PRIVATE_PATH")
    for part in (path, *path.parents):
        require(not part.is_symlink() and not part.is_junction(), "F_REPLAY_PRIVATE_PATH")
    resolved = path.resolve(strict=True)
    require(not resolved.is_relative_to(REPO_ROOT.resolve()), "F_REPLAY_PRIVATE_PATH")
    require(resolved.is_dir() if directory else resolved.is_file(), "F_REPLAY_PRIVATE_PATH")
    return resolved


def resting(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal", ".compact", ".vacuum", ".lock"):
        require(not Path(str(path) + suffix).exists(), "F_REPLAY_PROJECT_NOT_CLOSED")


def decode_frame(data: bytes) -> dict[str, Any]:
    zstd = importlib.import_module("zstandard")
    size = zstd.frame_content_size(data)
    require(type(size) is int and 0 <= size <= 64 * 1024 * 1024, "F_REPLAY_STORED_FRAME")
    decoded = zstd.ZstdDecompressor().decompress(
        data, max_output_size=64 * 1024 * 1024, allow_extra_data=False
    )
    require(len(decoded) == size, "F_REPLAY_STORED_FRAME")
    return parse(decoded)


@dataclass(frozen=True, repr=False)
class ReplayPlan:
    config: dict[str, Any] = field(repr=False)
    project: Path = field(repr=False)
    entry: dict[str, Any] = field(repr=False)
    project_uuid: str = field(repr=False)
    entry_key: str
    revision: int
    filter_uid: int
    materialization_sha256: str


def validate_materialization(
    config: dict[str, Any],
    request: dict[str, Any],
    report: dict[str, Any],
    project_uuid: str,
    revision: int,
    named: int,
    operation: tuple[Any, ...],
    outcome: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Pure links checked before oracle reads; native getters remain mandatory afterwards."""
    closed(
        report,
        {"status", "entry_key", "revision", "replayed", "verified_after_reopen"},
        "F_REPLAY_IMPORT_REPORT",
    )
    require(
        report["status"] == "ok"
        and report["replayed"] is False
        and report["verified_after_reopen"] is True
        and sha(report["entry_key"])
        and positive(report["revision"]),
        "F_REPLAY_IMPORT_REPORT",
    )
    closed(request, {"schema", "manifest", "host", "expected_base_revision"}, "F_REPLAY_REQUEST")
    require(
        request["schema"] == "uzpainter/filter-observation-v2-import/1"
        and type(request["expected_base_revision"]) is int
        and request["expected_base_revision"] >= 0,
        "F_REPLAY_REQUEST",
    )
    require(
        revision == named == report["revision"] == request["expected_base_revision"] + 1,
        "F_REPLAY_SAVED_REVISION",
    )
    arguments = {
        "payload_sha256": digest(request),
        "project_uuid": project_uuid,
        "expected_base_revision": request["expected_base_revision"],
    }
    require(
        len(operation) == 3
        and operation[0] == project_uuid
        and operation[2] == revision
        and operation[1]
        == digest({"tool": "filter-observation-commit-v2", "arguments": arguments}),
        "F_REPLAY_OPERATION",
    )
    require(
        outcome.get("status") == "committed"
        and typed_json(outcome.get("returned")) == typed_json({"entry_key": report["entry_key"]}),
        "F_REPLAY_OPERATION_OUTCOME",
    )
    space = manifest["filter_source_observations"]
    require(space["schema"] == "uzpainter/filter-source-observations/2", "F_REPLAY_V2_REQUIRED")
    entry: dict[str, Any] = space["entries"][report["entry_key"]]
    require(
        entry["schema"] == "uzpainter/filter-source-observation/2"
        and digest(entry) == report["entry_key"]
        and entry["project_uuid"] == project_uuid,
        "F_REPLAY_ENTRY",
    )
    binding = entry["binding"]
    uid = binding["filter_uid"]
    require(
        positive(uid)
        and space["bindings"].get(str(uid)) == report["entry_key"]
        and list(space["bindings"].values()).count(report["entry_key"]) == 1,
        "F_REPLAY_BINDING",
    )
    capture = entry["capture"]
    require(
        typed_json(capture["host"]) == typed_json(request["host"])
        and typed_json(capture["filter"]["manifest"]) == typed_json(request["manifest"]),
        "F_REPLAY_CAPTURE_BINDING",
    )
    context = entry["context"]
    projection = {
        key: value for key, value in manifest.items() if key != "filter_source_observations"
    }
    require(
        typed_json(context["project"]) == typed_json(projection)
        and digest(context) == entry["context_sha256"],
        "F_REPLAY_CONTEXT",
    )
    proof = capture["migration"]["native_evidence"]
    require(
        proof["schema"] == "uzpainter/filter-frozen-host-native-proof/1"
        and proof["project_uuid"] == project_uuid
        and proof["binary_sha256"] == config["import_binary_sha256"]
        and proof["prospective_projection_sha256"] == digest(projection)
        and proof["inventory_sha256"] == digest(context["inventory"]),
        "F_REPLAY_NATIVE_PROOF",
    )
    require(
        all(type(proof[k]) is int and proof[k] == 0 for k in COUNTS)
        and type(proof["sample_count"]) is int
        and proof["sample_count"] == 128 * 128,
        "F_REPLAY_NATIVE_PROOF",
    )
    require(
        sha(proof["raster_sha256"])
        and proof["raster_sha256"] == proof["uploaded_sha256"] == proof["final_output_sha256"]
        and proof["signature_sha256"] == entry["host_snapshot"]["signature_sha256"]
        and typed_json(proof["plane_id"]) == typed_json(entry["host_snapshot"]["plane_id"]),
        "F_REPLAY_NATIVE_PROOF",
    )
    return entry


def prepare(config_path: Path) -> ReplayPlan:
    """Read only the configuration and original materialized project, never either oracle."""
    try:
        config = closed(
            parse(private_path(str(config_path)).read_bytes()),
            {
                "schema",
                "project",
                "project_sha256",
                "import_binary_sha256",
                "import_request",
                "import_report",
                "oracle_store",
                "f_manifest",
                "old_manifest",
            },
            "F_REPLAY_CONFIG",
        )
        require(
            config["schema"] == SCHEMA
            and sha(config["project_sha256"])
            and sha(config["import_binary_sha256"]),
            "F_REPLAY_CONFIG",
        )
        project = private_path(config["project"])
        resting(project)
        require(file_hash(project) == config["project_sha256"], "F_REPLAY_PROJECT_HASH")
        request = parse(private_path(config["import_request"]).read_bytes())
        report = parse(private_path(config["import_report"]).read_bytes())
        uri = project.as_uri() + "?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            require(db.execute("PRAGMA journal_mode").fetchone() == ("delete",), "F_REPLAY_JOURNAL")
            uuid = db.execute("SELECT value FROM meta WHERE key='project_uuid'").fetchone()[0]
            revision = db.execute(
                "SELECT revision FROM checkpoint WHERE name='current'"
            ).fetchone()[0]
            named = db.execute(
                "SELECT MAX(revision) FROM checkpoint WHERE name NOT IN ('current', 'previous')"
            ).fetchone()[0]
            args = {
                "payload_sha256": digest(request),
                "project_uuid": uuid,
                "expected_base_revision": request["expected_base_revision"],
            }
            key = "filter-observation-commit-v2:" + digest(args)
            row = db.execute(
                "SELECT project_uuid,request_hash,committed_revision,outcome FROM operation "
                "WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            require(row is not None, "F_REPLAY_OPERATION_MISSING")
            outcome = decode_frame(row[3])
            frame = db.execute(
                "SELECT manifest,manifest_sha256 FROM revision WHERE revision=?", (revision,)
            ).fetchone()
            manifest = decode_frame(frame[0])
            # Stored hash is over SaveManifest's raw JSON, which may contain formatting.
            zstd = importlib.import_module("zstandard")
            raw = zstd.ZstdDecompressor().decompress(
                frame[0], max_output_size=64 * 1024 * 1024, allow_extra_data=False
            )
            require(hashlib.sha256(raw).hexdigest() == frame[1], "F_REPLAY_MANIFEST_HASH")
            entry = validate_materialization(
                config, request, report, uuid, revision, named, row[:3], outcome, manifest
            )
        resting(project)
        require(file_hash(project) == config["project_sha256"], "F_REPLAY_PROJECT_CHANGED")
        return ReplayPlan(
            config,
            project,
            entry,
            uuid,
            report["entry_key"],
            revision,
            entry["binding"]["filter_uid"],
            digest(report),
        )
    except ReplayRefused:
        raise
    except Exception:
        raise ReplayRefused("F_REPLAY_MATERIALIZATION_INVALID") from None


def select_readbacks(
    manifest: dict[str, Any], record: dict[str, Any], golden: str
) -> dict[str, Any]:
    require(manifest["golden_id"] == record["golden_id"] == golden, "F_REPLAY_GOLDEN")
    recipe = manifest["instruction_sequence"]
    require(record["key"]["instruction_sequence_sha256"] == digest(recipe), "F_REPLAY_RECIPE")
    steps = {step["step"]: step for step in recipe["steps"]}
    require(len(steps) == len(recipe["steps"]), "F_REPLAY_STEPS")
    recordings = record["recordings"]
    require(len(recordings) == 2, "F_REPLAY_RECORDINGS")
    result = {}
    for index, condition in enumerate(CONDITIONS):
        recording = recordings[index]
        require(
            recording["recording_id"] == f"r{index + 1}" and recording["condition"] == condition,
            "F_REPLAY_RECORDINGS",
        )
        for number, getter in GETTERS.items():
            step = steps[number]
            require(
                step["call"] == SOURCE + getter
                and typed_json(step["args"]) == typed_json({"node_step": 6, "effect": True}),
                "F_REPLAY_STEPS",
            )
            matches = [o for o in recording["outputs"] if o["output_id"] == f"s{number}/{getter}"]
            require(len(matches) == 1, "F_REPLAY_OUTPUTS")
            output = matches[0]
            require(
                output["kind"] == "api_readback"
                and output["call"] == step["call"]
                and typed_json(output["args"]) == typed_json(step["args"])
                and "raised" not in output
                and "value" in output,
                "F_REPLAY_OUTPUTS",
            )
            result[f"r{index + 1}/s{number}/{getter}"] = output["value"]
    return result


def validate_actual(plan: ReplayPlan, actual: dict[str, Any]) -> None:
    closed(
        actual,
        {
            "schema",
            "entry_key",
            "revision",
            "project_sha256",
            "readbacks",
            "trace",
            "old_handles_refused",
            "unchanged",
        },
        "F_REPLAY_ACTUAL_SHAPE",
    )
    require(
        actual["schema"] == "uzpainter/filter-context-actual/1"
        and actual["entry_key"] == plan.entry_key
        and type(actual["revision"]) is int
        and actual["revision"] == plan.revision
        and actual["project_sha256"] == plan.config["project_sha256"]
        and actual["unchanged"] is True
        and type(actual["old_handles_refused"]) is int
        and actual["old_handles_refused"] == 3,
        "F_REPLAY_ACTUAL_BINDING",
    )
    keys = {f"r{r}/s{n}/{g}" for r in (1, 2) for n, g in GETTERS.items()}
    require(
        type(actual["readbacks"]) is dict
        and set(actual["readbacks"]) == keys
        and type(actual["trace"]) is dict
        and set(actual["trace"]) == keys,
        "F_REPLAY_ACTUAL_OUTPUTS",
    )
    require(
        all(
            type(v) is list and v and all(type(s) is str and s for s in v)
            for v in actual["trace"].values()
        ),
        "F_REPLAY_TRACE",
    )
    typed_json(actual["readbacks"])
    require(
        all(SOURCE + key.rsplit("/", 1)[1] in actual["trace"][key] for key in keys),
        "F_REPLAY_TRACE",
    )


def compare_readbacks(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    require(set(actual) == set(expected) and len(actual) == 6, "F_REPLAY_COMPARISON_SHAPE")
    for key in sorted(expected):
        require(typed_json(actual[key]) == typed_json(expected[key]), "F_REPLAY_DIFFERENT")


def compare(plan: ReplayPlan, actual_path: Path) -> dict[str, Any]:
    """Only successful native collection permits reading the independent F and old expectations."""
    try:
        actual = parse(private_path(str(actual_path)).read_bytes())
        validate_actual(plan, actual)
        resting(plan.project)
        require(
            file_hash(plan.project) == plan.config["project_sha256"], "F_REPLAY_PROJECT_CHANGED"
        )
        from tools.parity.filter_context_settings_validation import load_settings_capture
        from tools.parity.filter_observation_import import admitted_record
        from tools.parity.store.store import OracleStore
        from tools.parity.tier0_semantics.source_substance_control import booleans_filter_request

        store = OracleStore.open(private_path(plan.config["oracle_store"], directory=True))
        raw_f = Path(plan.config["f_manifest"]).read_bytes()
        require(
            hashlib.sha256(raw_f).hexdigest()
            == plan.entry["capture"]["filter"]["manifest"]["sha256"],
            "F_REPLAY_F_MANIFEST",
        )
        captured = load_settings_capture(raw_f, store)
        record_ref = next(
            r for r in captured.manifest["private_records"] if r["record_id"] == "golden-record"
        )
        require(
            record_ref["sha256"] == plan.entry["capture"]["filter"]["record"]["sha256"],
            "F_REPLAY_F_RECORD",
        )
        fresh = select_readbacks(captured.manifest, captured.record, F_GOLDEN)
        compare_readbacks(actual["readbacks"], fresh)

        old_manifest = parse(Path(plan.config["old_manifest"]).read_bytes())
        authored = booleans_filter_request()
        for field_name in (
            "golden_id",
            "instruction_sequence",
            "inputs",
            "applied_settings",
            "software",
        ):
            require(
                typed_json(old_manifest[field_name]) == typed_json(authored[field_name]),
                "F_REPLAY_OLD_RECIPE",
            )
        raw_old, job = admitted_record(store, old_manifest)
        old_sha = hashlib.sha256(raw_old).hexdigest()
        refs = [r for r in old_manifest["private_records"] if r["kind"] == "private_oracle_record"]
        require(
            len(refs) == 1
            and refs[0]["sha256"] == old_sha
            and refs[0]["size_bytes"] == len(raw_old),
            "F_REPLAY_OLD_RECORD",
        )
        require(old_sha != record_ref["sha256"], "F_REPLAY_INDEPENDENT_RECORD")
        old_record = parse(raw_old)
        require(
            typed_json(old_record["key"]["inputs"]) == typed_json(job.input_hashes())
            and typed_json(old_record["key"]["painter_build"])
            == typed_json(old_manifest["software"]["painter"]),
            "F_REPLAY_OLD_RECORD",
        )
        old = select_readbacks(old_manifest, old_record, OLD_GOLDEN)
        compare_readbacks(actual["readbacks"], old)
        require(
            file_hash(plan.project) == plan.config["project_sha256"], "F_REPLAY_PROJECT_CHANGED"
        )
        return {
            "schema": REPORT_SCHEMA,
            "status": "equal",
            "f_compared": 6,
            "old_compared": 6,
            "traced_outputs": 6,
            "old_handles_refused": 3,
            "unchanged": True,
            "entry_key": plan.entry_key,
            "project_sha256": plan.config["project_sha256"],
            "f_record_sha256": record_ref["sha256"],
            "old_record_sha256": old_sha,
            "actual_sha256": digest(actual["readbacks"]),
            "trace_sha256": digest(actual["trace"]),
        }
    except ReplayRefused:
        raise
    except Exception:
        raise ReplayRefused("F_REPLAY_COMPARISON_INVALID") from None


def recorder_source() -> str:
    text = (REPO_ROOT / "tools/parity/recorder/painter_probes.py").read_text(encoding="utf-8")
    names = {"describe", "resolve", "substance_source", "substance_read"}
    found = {
        n.name: ast.get_source_segment(text, n)
        for n in ast.parse(text).body
        if isinstance(n, ast.FunctionDef) and n.name in names
    }
    require(set(found) == names and all(found.values()), "F_REPLAY_SERIALIZERS")
    return "\n\n".join(str(found[name]) for name in sorted(names))


WORKER = r"""
def capture_actual():
    P = uzpainter.project
    if P.is_open():
        raise RuntimeError("F_REPLAY_PROJECT_ALREADY_OPEN")
    def checked_file():
        if hashlib.sha256(Path(PROJECT).read_bytes()).hexdigest() != PROJECT_SHA:
            raise RuntimeError("F_REPLAY_PROJECT_CHANGED")
    def fresh(step):
        if int(step) != 6:
            raise RuntimeError("F_REPLAY_NODE_STEP")
        node = resolve(FILTER_UID)
        if not isinstance(node, substance_painter.layerstack.FilterEffectNode):
            raise RuntimeError("F_REPLAY_FILTER_BINDING")
        return node
    globals()["fresh"] = fresh
    checked_file()
    values = {}
    refused = 0
    original = None
    _TRACE["start"]()
    try:
        _TRACE["mark"]("bookkeeping")
        for round_ in (1, 2):
            P.open(PROJECT)
            if P.revision() != REVISION or str(P.get_uuid()) != PROJECT_UUID:
                raise RuntimeError("F_REPLAY_PROJECT_BINDING")
            if original is not None:
                for getter in ("get_parameters", "resource_id", "image_outputs"):
                    try:
                        if getter == "get_parameters":
                            original.get_parameters()
                        else:
                            getattr(original, getter)
                    except Exception as error:
                        if type(error).__name__ != "UnsupportedProcedural":
                            raise RuntimeError("F_REPLAY_OLD_HANDLE") from None
                        refused += 1
                    else:
                        raise RuntimeError("F_REPLAY_OLD_HANDLE")
            getters = ((16, "get_parameters"), (17, "resource_id"), (18, "image_outputs"))
            for number, getter in getters:
                mark = f"r{round_}/s{number}/{getter}"
                _TRACE["mark"](mark)
                values[mark] = describe(substance_read(
                    SOURCE_PREFIX + getter, {"node_step": 6, "effect": True}))
                _TRACE["mark"]("bookkeeping")
            if original is None:
                original = fresh(6).get_source()
            if P.revision() != REVISION or P.needs_saving():
                raise RuntimeError("F_REPLAY_MUTATION")
            P.close()
            checked_file()
    finally:
        trace = _TRACE["stop"]()
        if P.is_open():
            P.close()
    selected = {key: trace.get(key, []) for key in values}
    if (len(values) != 6 or refused != 3 or not all(selected.values())
            or not all(SOURCE_PREFIX + key.rsplit("/", 1)[1] in names
                       for key, names in selected.items())):
        raise RuntimeError("F_REPLAY_CAPTURE_INCOMPLETE")
    Path(WORK, "filter-context-actual.json").write_text(json.dumps({
        "schema": "uzpainter/filter-context-actual/1", "entry_key": ENTRY_KEY,
        "revision": REVISION, "project_sha256": PROJECT_SHA, "readbacks": values,
        "trace": selected, "old_handles_refused": refused, "unchanged": True
    }, ensure_ascii=True), encoding="utf-8")
    return {"status": "captured", "outputs": 6, "old_handles_refused": 3}

try:
    result = capture_actual()
except BaseException:
    try:
        Path(WORK, "filter-context-private-error.txt").write_text(
            traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass
    result = {"status": "refused", "code": "F_REPLAY_EXECUTION"}
"""


def build_script(plan: ReplayPlan, trace_source: str) -> str:
    constants = {
        "PROJECT": str(plan.project),
        "PROJECT_SHA": plan.config["project_sha256"],
        "PROJECT_UUID": plan.project_uuid,
        "REVISION": plan.revision,
        "FILTER_UID": plan.filter_uid,
        "ENTRY_KEY": plan.entry_key,
        "SOURCE_PREFIX": SOURCE,
    }
    return (
        "import dataclasses, datetime, enum, hashlib, json, traceback\n"
        "from pathlib import Path\nfrom typing import Any\nimport substance_painter\n"
        + "\n".join(f"{key} = {value!r}" for key, value in constants.items())
        + "\n_TRACE = {'__name__': 'uzp_capability_trace'}\n"
        + f"exec(compile({trace_source!r}, 'capability_trace.py', 'exec'), _TRACE)\n"
        + recorder_source()
        + "\n"
        + WORKER
    )


def configured_path() -> Path | None:
    value = os.environ.get("UZP_FILTER_CONTEXT_REPLAY_CONFIG")
    return None if value is None else Path(value)
