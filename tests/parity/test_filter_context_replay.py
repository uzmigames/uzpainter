"""Authored structural and sequencing checks; no oracle fixture or native runtime."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.parity import filter_context_replay as replay


def materialization() -> list[Any]:
    projection = {"authored": "synthetic"}
    context = {"project": projection, "inventory": {"authored": []}}
    request = {
        "schema": "uzpainter/filter-observation-v2-import/1",
        "manifest": {},
        "host": {},
        "expected_base_revision": 7,
    }
    proof = {
        "schema": "uzpainter/filter-frozen-host-native-proof/1",
        "project_uuid": "authored",
        "binary_sha256": "a" * 64,
        "prospective_projection_sha256": replay.digest(projection),
        "inventory_sha256": replay.digest(context["inventory"]),
        "sample_count": 16384,
        "raster_sha256": "b" * 64,
        "uploaded_sha256": "b" * 64,
        "final_output_sha256": "b" * 64,
        "signature_sha256": "c" * 64,
        "plane_id": 1,
        **dict.fromkeys(replay.COUNTS, 0),
    }
    entry = {
        "schema": "uzpainter/filter-source-observation/2",
        "project_uuid": "authored",
        "binding": {"filter_uid": 9},
        "capture": {
            "host": {},
            "filter": {"manifest": {}},
            "migration": {"native_evidence": proof},
        },
        "context": context,
        "context_sha256": replay.digest(context),
        "host_snapshot": {"signature_sha256": "c" * 64, "plane_id": 1},
    }
    key = replay.digest(entry)
    manifest = {
        **projection,
        "filter_source_observations": {
            "schema": "uzpainter/filter-source-observations/2",
            "entries": {key: entry},
            "bindings": {"9": key},
        },
    }
    report = {
        "status": "ok",
        "entry_key": key,
        "revision": 8,
        "replayed": False,
        "verified_after_reopen": True,
    }
    args = {
        "payload_sha256": replay.digest(request),
        "project_uuid": "authored",
        "expected_base_revision": 7,
    }
    operation = (
        "authored",
        replay.digest({"tool": "filter-observation-commit-v2", "arguments": args}),
        8,
    )
    return [
        {"import_binary_sha256": "a" * 64},
        request,
        report,
        "authored",
        8,
        8,
        operation,
        {"status": "committed", "returned": {"entry_key": key}},
        manifest,
    ]


def test_structural_materialization_accepts_authored_links() -> None:
    args = materialization()
    assert replay.validate_materialization(*args)["binding"]["filter_uid"] == 9


@pytest.mark.parametrize("case", ["named", "revision", "replayed", "reopen", "binary", "operation"])
def test_structural_gate_refuses_broken_links(case: str) -> None:
    args = materialization()
    if case == "named":
        args[5] = 7
    elif case == "revision":
        args[4] = 9
    elif case == "replayed":
        args[2]["replayed"] = True
    elif case == "reopen":
        args[2]["verified_after_reopen"] = False
    elif case == "binary":
        args[0]["import_binary_sha256"] = "d" * 64
    else:
        args[6] = ("authored", "d" * 64, 8)
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_"):
        replay.validate_materialization(*args)


@pytest.mark.parametrize("case", ["boolean_count", "mismatch", "raster", "projection", "binding"])
def test_structural_gate_refuses_rehashed_invalid_entry(case: str) -> None:
    args = materialization()
    space = args[8]["filter_source_observations"]
    entry = next(iter(space["entries"].values()))
    proof = entry["capture"]["migration"]["native_evidence"]
    if case == "boolean_count":
        proof["nonfinite_count"] = False
    elif case == "mismatch":
        proof["upload_mismatches"] = 1
    elif case == "raster":
        proof["uploaded_sha256"] = "d" * 64
    elif case == "projection":
        proof["prospective_projection_sha256"] = "d" * 64
    key = replay.digest(entry)
    space["entries"] = {key: entry}
    space["bindings"] = {} if case == "binding" else {"9": key}
    args[2]["entry_key"] = key
    args[7]["returned"]["entry_key"] = key
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_"):
        replay.validate_materialization(*args)


def recordings() -> tuple[dict[str, Any], dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {"step": n, "call": replay.SOURCE + g, "args": {"node_step": 6, "effect": True}}
        for n, g in replay.GETTERS.items()
    ]
    manifest = {"golden_id": replay.OLD_GOLDEN, "instruction_sequence": {"steps": steps}}
    record = {
        "golden_id": replay.OLD_GOLDEN,
        "key": {"instruction_sequence_sha256": replay.digest(manifest["instruction_sequence"])},
        "recordings": [
            {
                "recording_id": f"r{i}",
                "condition": condition,
                "outputs": [
                    {
                        "output_id": f"s{s['step']}/{replay.GETTERS[s['step']]}",
                        "kind": "api_readback",
                        "call": s["call"],
                        "args": deepcopy(s["args"]),
                        "value": {"authored": i},
                    }
                    for s in steps
                ],
            }
            for i, condition in enumerate(replay.CONDITIONS, 1)
        ],
    }
    return manifest, record


def test_selects_six_outputs_without_reading_restriction_errors() -> None:
    manifest, record = recordings()
    record["recordings"][0]["outputs"].append({"output_id": "s19/resolution", "raised": "expected"})
    assert len(replay.select_readbacks(manifest, record, replay.OLD_GOLDEN)) == 6


@pytest.mark.parametrize("case", ["condition", "raised", "duplicate", "node", "duplicate_step"])
def test_recorded_selection_refuses_ambiguous_or_wrong_outputs(case: str) -> None:
    manifest, record = recordings()
    first = record["recordings"][0]
    if case == "condition":
        first["condition"] = "wrong"
    elif case == "raised":
        first["outputs"][0]["raised"] = "private synthetic error"
    elif case == "duplicate":
        first["outputs"].append(deepcopy(first["outputs"][0]))
    else:
        steps = manifest["instruction_sequence"]["steps"]
        if case == "node":
            steps[0]["args"]["node_step"] = 7
        else:
            steps.append(deepcopy(steps[0]))
        record["key"]["instruction_sequence_sha256"] = replay.digest(
            manifest["instruction_sequence"]
        )
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_"):
        replay.select_readbacks(manifest, record, replay.OLD_GOLDEN)


@pytest.mark.parametrize(("left", "right"), [(0, 0.0), (0.0, -0.0), (False, 0)])
def test_comparison_preserves_json_types(left: Any, right: Any) -> None:
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_DIFFERENT$"):
        replay.compare_readbacks(dict.fromkeys("abcdef", left), dict.fromkeys("abcdef", right))


def test_invalid_actual_never_opens_expectations(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = replay.ReplayPlan({}, Path("authored"), {}, "authored", "a" * 64, 8, 9, "b" * 64)
    monkeypatch.setattr(replay, "private_path", lambda value: Path("authored"))
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"{}")
    monkeypatch.setattr(
        replay, "file_hash", lambda path: pytest.fail("project/oracle read too early")
    )
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_ACTUAL_SHAPE$"):
        replay.compare(plan, Path("authored"))


@pytest.mark.parametrize(
    "case", ["valid", "empty_trace", "bookkeeping", "missing_output", "boolean_count", "revision"]
)
def test_actual_requires_six_traced_outputs_and_stale_refusals(case: str) -> None:
    plan = replay.ReplayPlan(
        {"project_sha256": "a" * 64}, Path("authored"), {}, "authored", "b" * 64, 8, 9, "c" * 64
    )
    keys = [f"r{r}/s{n}/{g}" for r in (1, 2) for n, g in replay.GETTERS.items()]
    actual: dict[str, Any] = {
        "schema": "uzpainter/filter-context-actual/1",
        "entry_key": plan.entry_key,
        "revision": 8,
        "project_sha256": "a" * 64,
        "unchanged": True,
        "old_handles_refused": 3,
        "readbacks": dict.fromkeys(keys, None),
        "restrictions": {
            f"r{r}/s{n}/{g}": {"value": None}
            for r in (1, 2)
            for n, g in replay.RESTRICTIONS.items()
        },
        "trace": {key: [replay.SOURCE + key.rsplit("/", 1)[1]] for key in keys},
    }
    if case == "valid":
        replay.validate_actual(plan, actual)
        return
    if case == "empty_trace":
        actual["trace"][keys[0]] = []
    elif case == "bookkeeping":
        actual["trace"][keys[0]] = ["substance_painter.layerstack.get_node_by_uid"]
    elif case == "missing_output":
        actual["readbacks"].pop(keys[0])
    elif case == "boolean_count":
        actual["old_handles_refused"] = True
    else:
        actual["revision"] = 7
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_"):
        replay.validate_actual(plan, actual)


def test_worker_has_no_save_copy_or_oracle_reads() -> None:
    tree = ast.parse(replay.WORKER)
    calls = [n.func for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert not any(
        isinstance(n, ast.Attribute) and n.attr in {"save", "save_as", "copy", "copy2"}
        for n in calls
    )
    assert "oracle" not in replay.WORKER
    functions = {
        n.name for n in ast.parse(replay.recorder_source()).body if isinstance(n, ast.FunctionDef)
    }
    assert functions == {
        "describe",
        "resolve",
        "substance_source",
        "substance_read",
        "substance_edit",
        "class_name",
    }


def test_only_absent_configuration_can_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UZP_FILTER_CONTEXT_REPLAY_CONFIG", raising=False)
    assert replay.configured_path() is None
    monkeypatch.setenv("UZP_FILTER_CONTEXT_REPLAY_CONFIG", "")
    assert replay.configured_path() is not None


def restriction_recordings() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, record = recordings()
    steps = replay.restriction_steps()
    manifest["instruction_sequence"]["steps"].extend(deepcopy(steps))
    record["key"]["instruction_sequence_sha256"] = replay.digest(manifest["instruction_sequence"])
    for recording in record["recordings"]:
        for step in steps:
            recording["outputs"].append(
                {
                    "output_id": f"s{step['step']}/{replay.RESTRICTIONS[step['step']]}",
                    "kind": "api_readback",
                    "call": step["call"],
                    "args": {k: v for k, v in step["args"].items() if k not in {"probe", "wait"}},
                    "value": None,
                    "raised": {"type": "AuthoredError", "message": "synthetic refusal"},
                }
            )
    return manifest, record


def test_restriction_recipe_removes_scheduler_flags_only_from_readback_args() -> None:
    manifest, record = restriction_recordings()
    assert manifest["instruction_sequence"]["steps"][5]["args"]["probe"] is True
    outcomes = replay.select_restrictions(manifest, record, replay.OLD_GOLDEN)
    assert len(outcomes) == 12
    replay.compare_restrictions(outcomes, deepcopy(outcomes))


@pytest.mark.parametrize("case", ["success", "type", "message", "signed_zero", "missing"])
def test_restrictions_require_exact_outcomes_in_both_rounds(case: str) -> None:
    manifest, record = restriction_recordings()
    expected = replay.select_restrictions(manifest, record, replay.OLD_GOLDEN)
    actual = deepcopy(expected)
    key = "r2/s23/resolution"
    if case == "success":
        actual[key] = {"value": None}
    elif case == "type":
        actual[key]["raised"]["type"] = "DifferentError"
    elif case == "message":
        actual[key]["raised"]["message"] = "different private synthetic message"
    elif case == "signed_zero":
        expected[key] = {"value": 0.0}
        actual[key] = {"value": -0.0}
    else:
        actual.pop(key)
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_RESTRICTION_") as error:
        replay.compare_restrictions(actual, expected)
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "case", ["duplicate", "wrong_args", "wrong_call", "recipe", "mixed_outcome"]
)
def test_restriction_receipts_cannot_hide_wrong_operation(case: str) -> None:
    manifest, record = restriction_recordings()
    outputs = record["recordings"][1]["outputs"]
    if case == "duplicate":
        outputs.append(deepcopy(outputs[-1]))
    elif case == "wrong_args":
        outputs[-1]["args"]["node_step"] = 7
    elif case == "wrong_call":
        outputs[-1]["call"] = replay.SOURCE + "get_parameters"
    elif case == "mixed_outcome":
        outputs[-1]["value"] = "unexpected value beside refusal"
    else:
        manifest["instruction_sequence"]["steps"][-1]["args"]["effect"] = False
        record["key"]["instruction_sequence_sha256"] = replay.digest(
            manifest["instruction_sequence"]
        )
    with pytest.raises(replay.ReplayRefused, match=r"^F_REPLAY_RESTRICTION_"):
        replay.select_restrictions(manifest, record, replay.OLD_GOLDEN)


@pytest.mark.parametrize("mutation", ["none", "revision", "dirty", "untracked"])
def test_worker_checks_atomicity_after_each_refusal(mutation: str) -> None:
    state: dict[str, Any] = {"revision": 8, "dirty": False, "calls": [], "parameters": 0}

    class Project:
        @staticmethod
        def revision() -> int:
            return int(state["revision"])

        @staticmethod
        def needs_saving() -> bool:
            return bool(state["dirty"])

    def read(call: str, args: dict[str, Any]) -> None:
        state["calls"].append(("read", call, args))
        raise ValueError("authored read refusal")

    def edit(call: str, args: dict[str, Any]) -> None:
        state["calls"].append(("edit", call, args))
        if mutation == "revision":
            state["revision"] += 1
        elif mutation == "dirty":
            state["dirty"] = True
        elif mutation == "untracked":
            state["parameters"] = 1
        raise ValueError("authored edit refusal")

    node = next(
        n
        for n in ast.parse(replay.WORKER).body
        if isinstance(n, ast.FunctionDef) and n.name == "capture_restrictions"
    )
    namespace: dict[str, Any] = {
        "REVISION": 8,
        "substance_read": read,
        "substance_edit": edit,
        "describe": lambda v: v,
        "restriction_state": lambda p: (p.revision(), p.needs_saving(), state["parameters"]),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "authored_worker", "exec"), namespace)
    if mutation != "none":
        with pytest.raises(RuntimeError, match=r"^F_REPLAY_MUTATION$"):
            namespace["capture_restrictions"](Project, replay.restriction_steps())
        # First setter is step21; abort before the subsequent read can hide its mutation.
        assert len(state["calls"]) == 3
    else:
        result = namespace["capture_restrictions"](Project, replay.restriction_steps())
        assert len(result) == 6
        assert [c[0] for c in state["calls"]] == ["read", "read", "edit", "read", "edit", "read"]
        assert all("probe" not in c[2] and "wait" not in c[2] for c in state["calls"])
        assert result["s21/resolution"] == {
            "value": None,
            "raised": {"type": "ValueError", "message": "authored edit refusal"},
        }
