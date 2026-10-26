"""Closed F boundary/lifecycle refusals; authored values, no imported expected observations."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from tests.parity.test_painter_filter_context import frames
from tools.parity.filter_context_contract import (
    A_RECIPE_SHA256,
    NODE,
    ContextRefused,
    parse_context_readback,
    require_effective_settings,
    typed,
    validate_census,
    validate_context_readback,
    validate_context_sequence,
)
from tools.parity.recorder.filter_context import step_trace
from tools.parity.tier0_semantics.source_substance_control import booleans_filter_request


def lifecycle() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    recipe = booleans_filter_request()["instruction_sequence"]
    trace: list[dict[str, Any]] = []
    for step in recipe["steps"][:6]:
        trace.append(step_trace("same_session", step, {"value": None}))
        if step["step"] == 1:
            trace.append({"kind": "context", "boundary": "after-create"})
    trace.append({"kind": "context", "boundary": "after-setup6"})
    for index, condition in enumerate(("same_session", "after_save_reopen"), 1):
        if index == 2:
            trace += [
                {"kind": event, "outcome": {"value": None}}
                for event in ("save", "close", "open", "rebind")
            ]
            trace.append({"kind": "context", "boundary": "after-reopen"})
        for step in recipe["steps"][6:]:
            if step["step"] == 16:
                trace.append({"kind": "context", "boundary": f"pre16-r{index}"})
            outcome: dict[str, Any] = {"value": None}
            if step["step"] >= 19:
                outcome["raised"] = {"type": "ValueError", "message": "authored documented refusal"}
            trace.append(step_trace(condition, step, outcome))
    return recipe, trace


def test_closed_trace_preserves_expected_refusals_but_never_authenticates_missing_settings() -> (
    None
):
    _, _, contexts = frames()
    recipe, trace = lifecycle()
    assert hashlib.sha256(typed(recipe)).hexdigest() == A_RECIPE_SHA256
    evidence = validate_context_sequence(recipe, trace, contexts)
    assert evidence.initial_paint_uid == 10
    with pytest.raises(
        ContextRefused,
        match="F_EFFECTIVE_SETTINGS_UNVERIFIED: tangent_space, workflow, mesh_unit_scale",
    ):
        require_effective_settings(evidence)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-baseline",
        "setup-again",
        "missing-probe",
        "before-insert",
        "missing-rebind",
        "paint-operation",
        "failed-create",
    ],
)
def test_lifecycle_changes_are_refused(mutation: str) -> None:
    _, _, contexts = frames()
    recipe, trace = lifecycle()
    if mutation == "missing-baseline":
        trace.pop(1)
    elif mutation == "setup-again":
        trace.insert(9, deepcopy(trace[0]))
    elif mutation == "missing-probe":
        trace.pop(next(i for i, event in enumerate(trace) if event.get("step") == 7))
    elif mutation == "before-insert":
        first_probe = next(i for i, event in enumerate(trace) if event.get("step") == 8)
        trace.insert(6, trace.pop(first_probe))
    elif mutation == "missing-rebind":
        trace = [event for event in trace if event["kind"] != "rebind"]
    elif mutation == "paint-operation":
        trace.insert(3, {"kind": "painting", "outcome": {"value": None}})
    else:
        trace[0]["outcome"] = {
            "value": None,
            "raised": {"type": "ValueError", "message": "failed create"},
        }
    with pytest.raises(ContextRefused):
        validate_context_sequence(recipe, trace, contexts)


@pytest.mark.parametrize(
    "mutation",
    [
        "recipe-template",
        "role-uid",
        "paint-uid",
        "same-wrapper-claim",
        "boundary-order",
        "project-uuid",
    ],
)
def test_context_binding_changes_are_refused(mutation: str) -> None:
    _, _, contexts = frames()
    recipe, trace = lifecycle()
    if mutation == "recipe-template":
        recipe["steps"][0]["args"]["template"] = "invented"
    elif mutation == "boundary-order":
        contexts[2], contexts[3] = contexts[3], contexts[2]
    else:
        frame = contexts[3]
        if mutation == "same-wrapper-claim":
            frame["fresh_handles"] = True
        else:
            for row in frame["outputs"]:
                selector = row["args"]["selector"]
                if (
                    mutation == "role-uid"
                    and row["call"] == NODE + "uid"
                    and selector == {"role": "host"}
                ):
                    row["value"] = 999
                if (
                    mutation == "paint-uid"
                    and row["call"] == NODE + "uid"
                    and selector.get("path") == [["Root", 1]]
                ):
                    row["value"] = 999
                if mutation == "project-uuid" and row["call"].endswith("project.get_uuid"):
                    row["value"] = "another-project"
    with pytest.raises(ContextRefused):
        validate_context_sequence(recipe, trace, contexts)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "unknown-call",
        "bad-args",
        "duplicate",
        "missing",
        "bool-uid",
        "missing-input-source",
    ],
)
def test_closed_leaf_inventory_refuses_gaps_and_invented_getters(mutation: str) -> None:
    _, _, contexts = frames()
    frame = contexts[1]
    row = frame["outputs"][0]
    if mutation == "extra":
        row["accepted"] = True
    elif mutation == "unknown-call":
        row["call"] = "substance_painter.project.get_effective_settings"
    elif mutation == "bad-args":
        row["args"]["override"] = True
    elif mutation == "duplicate":
        frame["outputs"].append(deepcopy(row))
    elif mutation == "bool-uid":
        next(row for row in frame["outputs"] if row["call"] == NODE + "uid")["value"] = True
    elif mutation == "missing-input-source":
        next(row for row in frame["outputs"] if row["call"].endswith(".image_inputs"))["value"] = [
            "input-a"
        ]
    else:
        frame["outputs"].pop()
    with pytest.raises(ContextRefused):
        validate_census(frame)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "1e999", "1e-999", "9223372036854775808"])
def test_parser_rejects_unrepresentable_numbers(token: str) -> None:
    with pytest.raises(ContextRefused):
        parse_context_readback(('{"schema":' + token + "}").encode())


def test_parser_rejects_duplicate_keys_and_keeps_signed_zero() -> None:
    _, _, contexts = frames()
    data = json.dumps(contexts[1]).encode()
    assert parse_context_readback(data) == contexts[1]
    with pytest.raises(ContextRefused, match="duplicate"):
        parse_context_readback(b'{"schema":"x",' + data[1:])
    assert typed(-0.0) != typed(0.0) and typed(1) != typed(1.0)


def test_structure_validation_does_not_require_unrelated_round_values_equal() -> None:
    _, _, contexts = frames()
    recipe, trace = lifecycle()
    for row in contexts[4]["outputs"]:
        if row["call"].endswith(".get_parameters"):
            row["value"]["authored_variation"] = 2
    validate_context_sequence(recipe, trace, contexts)


def test_unknown_boundary_cannot_claim_effective_settings() -> None:
    _, _, contexts = frames()
    contexts[0]["boundary"] = "effective-settings"
    with pytest.raises(ContextRefused):
        validate_context_readback(contexts[0])


def test_coherent_role_replacement_is_refused_across_lifecycle() -> None:
    _, _, contexts = frames()
    recipe, trace = lifecycle()
    for row in contexts[3]["outputs"]:
        if row["call"] == NODE + "uid" and row["value"] in (20, 30):
            row["value"] += 100
        parameters = row["args"]["parameters"]
        if parameters.get("uid") in (20, 30):
            parameters["uid"] += 100
    validate_census(contexts[3])
    with pytest.raises(ContextRefused, match="UIDs changed"):
        validate_context_sequence(recipe, trace, contexts)


def test_role_lookup_descriptor_must_match_census() -> None:
    _, _, contexts = frames()
    row = next(
        row
        for row in contexts[1]["outputs"]
        if row["call"].endswith(".get_node_by_uid") and row["args"]["selector"] == {"role": "host"}
    )
    row["value"]["name"] = "contradiction"
    with pytest.raises(ContextRefused, match="role lookup"):
        validate_census(contexts[1])


def test_coherent_paint_rename_is_refused() -> None:
    _, _, contexts = frames()
    recipe, trace = lifecycle()
    for row in contexts[3]["outputs"]:
        if row["args"]["selector"].get("path") == [["Root", 1]]:
            if row["call"] == NODE + "get_name":
                row["value"] = "renamed"
            elif row["call"].endswith(".get_node_by_uid"):
                row["value"]["name"] = "renamed"
        if row["call"].endswith(".get_root_layer_nodes"):
            row["value"][1]["name"] = "renamed"
    validate_census(contexts[3])
    with pytest.raises(ContextRefused, match="Paint name"):
        validate_context_sequence(recipe, trace, contexts)


@pytest.mark.parametrize(
    "target,method,value",
    [
        (
            "host",
            "get_geometry_mask",
            {"class": "GeometryMaskMeshParams", "inclusion_list": True, "meshes": []},
        ),
        (
            "paint",
            "get_geometry_mask",
            {"class": "GeometryMaskMeshParams", "inclusion_list": False, "meshes": ["mesh"]},
        ),
        ("host", "get_blending_mode", "Multiply"),
        ("host", "get_opacity", 0.5),
        ("host", "get_opacity", True),
        ("filter", "get_opacity", "1"),
        ("filter", "get_opacity", -0.1),
        ("filter", "get_opacity", 1.1),
        ("filter", "get_opacity", float("nan")),
        ("filter", "get_blending_mode", "invented"),
        ("filter", "active_channels", []),
        ("filter", "active_channels", ["User0", "User0"]),
        ("filter", "active_channels", ["invented"]),
        ("host", "is_symmetry_enabled", True),
    ],
)
def test_non_neutral_or_invalid_domain_refused(target: str, method: str, value: Any) -> None:
    _, _, contexts = frames()
    path = {"host": [["Root", 0]], "paint": [["Root", 1]], "filter": [["Root", 0], ["Content", 0]]}[
        target
    ]
    row = next(
        row
        for row in contexts[1]["outputs"]
        if row["call"].endswith("." + method) and row["args"]["selector"].get("path") == path
    )
    row.pop("raised", None)
    row["value"] = value
    with pytest.raises(ContextRefused):
        validate_census(contexts[1])


@pytest.mark.parametrize(
    "method", ["is_symmetry_enabled", "get_symmetry_parameters", "get_opacity"]
)
def test_unavailable_required_state_is_not_defaulted(method: str) -> None:
    _, _, contexts = frames()
    row = next(
        row
        for row in contexts[1]["outputs"]
        if row["call"].endswith("." + method)
        and row["args"]["selector"].get("path") == [["Root", 0]]
    )
    row["value"] = None
    row["raised"] = {"type": "RuntimeError", "message": "unavailable"}
    with pytest.raises(ContextRefused):
        validate_census(contexts[1])


def test_nonapplicable_paint_blend_exception_remains_observation() -> None:
    _, _, contexts = frames()
    row = next(
        row
        for row in contexts[1]["outputs"]
        if row["call"] == NODE + "get_opacity"
        and row["args"]["selector"].get("path") == [["Root", 1]]
    )
    row["value"] = None
    row["raised"] = {"type": "ValueError", "message": "not applicable"}
    validate_census(contexts[1])
    assert row["value"] is None and row["raised"]["type"] == "ValueError"


@pytest.mark.parametrize(
    "getter,value",
    [
        ("format", "invented"),
        ("format", 32),
        ("bit_depth", True),
        ("bit_depth", 16),
        ("is_color", 1),
        ("is_floating", 1),
        ("is_floating", False),
        ("label", None),
    ],
)
def test_channel_getter_types_and_format_must_agree(getter: str, value: Any) -> None:
    _, _, contexts = frames()
    row = next(row for row in contexts[1]["outputs"] if row["call"].endswith("Channel." + getter))
    row["value"] = value
    with pytest.raises(ContextRefused, match="channel getter"):
        validate_census(contexts[1])
