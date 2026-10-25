"""Fresh exact resource selection, without importing Painter or contacting its process."""

from __future__ import annotations

import ast
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tools.parity.recorder import probes as recorder
from tools.parity.recorder.job import Step
from tools.parity.recorder.probes import (
    PAINTER_PROBES,
    check_input_arg,
    manifest_symbol_problems,
    probe_job_from_manifest,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.recorder.vocabulary import INSERT_FILTER
from tools.parity.schemas import Schema, validation_errors
from tools.parity.tier0_semantics import filter_observation_control as control


def selection_args() -> dict[str, Any]:
    return {
        "inside_step": 3,
        "node_stack": "Content",
        "search": "s:synthetic u:filter n:filter=",
        "require_unique": True,
        "resource_context": "synthetic",
        "resource_name": "filter",
    }


def selection_functions(search: Mock) -> dict[str, Any]:
    tree = ast.parse(PAINTER_PROBES.read_text())
    names = {
        "unique_resource_candidates",
        "unique_resource_status",
        "unique_resource_selection_diagnostic",
        "uniquely_searched_resource",
        "complete_resource_identity",
        "uniquely_gui_searched_resource",
        "verify_resource_binding",
    }
    functions: list[ast.stmt] = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    assert len(functions) == len(names)
    namespace: dict[str, Any] = {
        "Any": Any,
        "substance_painter": SimpleNamespace(
            resource=SimpleNamespace(
                search=search, Usage=SimpleNamespace(FILTER="FILTER", PROCEDURAL="PROCEDURAL")
            )
        ),
        "resource_id_value": lambda identifier: {
            "context": identifier.context,
            "name": identifier.name,
            "version": identifier.version,
            "url": identifier.url(),
        },
    }
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(PAINTER_PROBES), "exec"), namespace
    )
    return namespace


def gui_args() -> dict[str, Any]:
    args = selection_args()
    del args["resource_name"]
    return {
        **args,
        "resource_selection": "gui_name",
        "resource_gui_name": "Synthetic Filter",
        "resource_usage": "FILTER",
    }


def gui_resource(**identity_changes: Any) -> Any:
    identity = {
        "context": "synthetic",
        "name": "internal/filter",
        "version": "synthetic-version",
        "url": lambda: "resource://synthetic/internal/filter?version=synthetic-version",
    }
    identity.update(identity_changes)
    identifier = SimpleNamespace(**identity)
    return SimpleNamespace(
        identifier=lambda: identifier,
        gui_name=lambda: "Synthetic Filter",
        usages=lambda: ["FILTER"],
    )


@pytest.mark.parametrize("count", [0, 1, 2])
def test_gui_selection_requires_one_total_result(count: int) -> None:
    resource = gui_resource()
    search = Mock(return_value=[resource] * count)
    functions = selection_functions(search)
    if count == 1:
        identifier, observed = functions["uniquely_gui_searched_resource"](gui_args())
        assert identifier is resource.identifier()
        assert observed == functions["resource_id_value"](identifier)
    else:
        with pytest.raises(ValueError, match=f"^gui_resource_selection:search_count={count}$"):
            functions["uniquely_gui_searched_resource"](gui_args())
    search.assert_called_once_with(gui_args()["search"])


def test_gui_selection_refuses_two_results_even_when_only_one_matches() -> None:
    search = Mock(return_value=[gui_resource(), gui_resource(context="other")])
    with pytest.raises(ValueError, match=r"^gui_resource_selection:search_count=2$"):
        selection_functions(search)["uniquely_gui_searched_resource"](gui_args())


@pytest.mark.parametrize("field", ["url", "context", "name", "version"])
@pytest.mark.parametrize("value", [None, "", 1])
def test_gui_selection_refuses_incomplete_identity(field: str, value: Any) -> None:
    resource = gui_resource(**{field: (lambda: value) if field == "url" else value})
    search = Mock(return_value=[resource])
    with pytest.raises(ValueError, match=r"^gui_resource_selection:invalid_identity$"):
        selection_functions(search)["uniquely_gui_searched_resource"](gui_args())


@pytest.mark.parametrize("field", ["context", "gui_name", "usages"])
def test_gui_selection_requires_exact_metadata(field: str) -> None:
    resource = gui_resource(context="Synthetic" if field == "context" else "synthetic")
    if field == "gui_name":
        resource.gui_name = lambda: "synthetic filter"
    if field == "usages":
        resource.usages = lambda: ["PROCEDURAL"]
    with pytest.raises(ValueError, match=r"^gui_resource_selection:metadata_mismatch$"):
        selection_functions(Mock(return_value=[resource]))["uniquely_gui_searched_resource"](
            gui_args()
        )


@pytest.mark.parametrize(
    "change",
    [
        {"require_unique": 1},
        {"resource_selection": "GUI_NAME"},
        {"resource_name": "filter"},
        {"resource_context": ""},
        {"resource_gui_name": None},
        {"resource_gui_name": 1},
        {"resource_usage": "filter"},
        {"resource_usage": "PROCEDURAL"},
        {"resource_url": "synthetic"},
        {"search": []},
    ],
)
def test_gui_selection_rejects_invalid_or_mixed_recipe(change: dict[str, Any]) -> None:
    args = {**gui_args(), **change}
    with pytest.raises(RecorderError, match="unique resource"):
        check_input_arg(Step(4, INSERT_FILTER, args), {})
    search = Mock()
    with pytest.raises(ValueError, match=r"^gui_resource_selection:invalid_recipe$"):
        selection_functions(search)["uniquely_gui_searched_resource"](args)
    search.assert_not_called()


def test_gui_selection_preflight_accepts_closed_recipe() -> None:
    check_input_arg(Step(4, INSERT_FILTER, gui_args()), {})


@pytest.mark.parametrize("field", ["url", "context", "name", "version"])
def test_binding_rejects_any_identity_drift_without_disclosing_values(field: str) -> None:
    functions = selection_functions(Mock())
    selected = functions["complete_resource_identity"](gui_resource().identifier())
    changed = gui_resource(
        **{field: (lambda: "private-change") if field == "url" else "private-change"}
    )
    with pytest.raises(ValueError) as caught:
        functions["verify_resource_binding"](changed.identifier(), selected)
    assert str(caught.value) == "gui_resource_selection:bound_identity_mismatch"


@pytest.mark.parametrize("gui_mode", [False, True])
@pytest.mark.parametrize("filter_effect", [False, True])
@pytest.mark.parametrize("mismatch", [False, True])
def test_binding_dispatch_checks_selected_identity_after_mutation(
    gui_mode: bool, filter_effect: bool, mismatch: bool
) -> None:
    resource = gui_resource(name="filter")
    functions = selection_functions(Mock(return_value=[resource]))
    tree = ast.parse(PAINTER_PROBES.read_text())
    dispatch = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(item, ast.Name)
            and item.id == ("INSERT_FILTER_EFFECT" if filter_effect else "SET_SOURCE")
            for item in ast.walk(node)
        )
    )
    for node in ast.walk(dispatch):
        if isinstance(node, ast.Name) and node.id.isupper():
            functions[node.id] = node.id
    bound = resource.identifier()

    def mutate(*args: Any) -> Any:
        if mismatch:
            bound.version = "private-replaced-version"
        return effect if filter_effect else None

    effect = SimpleNamespace(get_source=lambda *args: SimpleNamespace(resource_id=bound))
    target_node = SimpleNamespace(set_source=Mock(side_effect=mutate), get_source=effect.get_source)
    functions["substance_painter"].layerstack = SimpleNamespace(
        insert_filter_effect=Mock(side_effect=mutate)
    )
    functions.update(
        fresh=lambda _: target_node,
        channel_arg=lambda _: "User0",
        insert_position=lambda _: "synthetic-position",
    )
    exec(
        compile(ast.Module(body=[dispatch], type_ignores=[]), str(PAINTER_PROBES), "exec"),
        functions,
    )
    args = gui_args() if gui_mode else selection_args()
    if not filter_effect:
        del args["inside_step"], args["node_stack"]
        args.update(node_step=3, channel="User0")
        if gui_mode:
            args["resource_usage"] = "PROCEDURAL"
            resource.usages = lambda: ["PROCEDURAL"]
    call = "INSERT_FILTER_EFFECT" if filter_effect else "SET_SOURCE"
    invocation = (call, args) if filter_effect else (4, call, args, {})
    if mismatch:
        with pytest.raises(ValueError, match=r"^gui_resource_selection:bound_identity_mismatch$"):
            functions[dispatch.name](*invocation)
    else:
        assert functions[dispatch.name](*invocation) is (effect if filter_effect else None)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_resource_requires_one_fresh_exact_identity(count: int) -> None:
    identifier = SimpleNamespace(
        context="synthetic",
        name="filter",
        version="fresh-version",
        url=lambda: "resource://synthetic/filter?version=fresh-version",
    )
    irrelevant = SimpleNamespace(
        context="other", name="filter", version="old", url=lambda: "unused"
    )
    search = Mock(
        return_value=[SimpleNamespace(identifier=lambda: identifier)] * count
        + [SimpleNamespace(identifier=lambda: irrelevant)]
    )
    namespace = selection_functions(search)
    if count == 1:
        assert namespace["uniquely_searched_resource"](selection_args()) is identifier
    else:
        with pytest.raises(ValueError, match=f"^unique_resource_selection:match_count={count}$"):
            namespace["uniquely_searched_resource"](selection_args())
    search.assert_called_once_with(selection_args()["search"])


@pytest.mark.parametrize(
    "version,url,reason",
    [
        (None, "private-url-marker", "missing_version"),
        ("", "private-url-marker", "missing_version"),
        ("private-version-marker", "", "missing_url"),
    ],
)
def test_unique_selection_refusals_never_include_identity(
    version: Any, url: str, reason: str
) -> None:
    identifier = SimpleNamespace(
        context="synthetic", name="filter", version=version, url=lambda: url
    )
    search = Mock(return_value=[SimpleNamespace(identifier=lambda: identifier)])
    functions = selection_functions(search)
    with pytest.raises(ValueError) as caught:
        functions["uniquely_searched_resource"](selection_args())
    assert str(caught.value) == "unique_resource_selection:" + reason
    assert "private-" not in str(caught.value)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_read_only_resource_diagnostic_returns_counts_only(count: int) -> None:
    identifier = SimpleNamespace(
        context="synthetic",
        name="filter",
        version="private-version-marker",
        url=lambda: "private-url-marker",
    )
    search = Mock(return_value=[SimpleNamespace(identifier=lambda: identifier)] * count)
    functions = selection_functions(search)
    result = functions["unique_resource_selection_diagnostic"](selection_args())
    assert result == {
        "search_count": count,
        "match_count": count,
        "missing_version": False if count == 1 else None,
        "missing_url": False if count == 1 else None,
        "refusal": None if count == 1 else "match_count",
    }
    assert "private-" not in str(result)
    search.assert_called_once_with(selection_args()["search"])


@pytest.mark.parametrize(
    "change",
    [
        {"require_unique": 1},
        {"resource_context": ""},
        {"resource_name": None},
        {"inside_step": True},
        {"node_stack": "Mask"},
        {"resource_url": "invented"},
    ],
)
def test_unique_selection_preflight_rejects_changes(change: dict[str, Any]) -> None:
    with pytest.raises(RecorderError, match="unique resource"):
        check_input_arg(Step(4, INSERT_FILTER, {**selection_args(), **change}), {})


def test_unique_selection_preflight_accepts_closed_contract() -> None:
    check_input_arg(Step(4, INSERT_FILTER, selection_args()), {})


def test_observation_recipe_is_documented_and_closed() -> None:
    manifest = control.request()
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest_symbol_problems(manifest) == []
    job = probe_job_from_manifest(manifest)
    assert not job.exports
    assert manifest["private_records"] == manifest["expectations"] == []
    assert len(job.inputs) == 1
    assert not any("symmetry" in s.call for s in (*job.state_steps, *job.probe_steps))
    assert len([s for s in job.probe_steps if s.call.endswith(".image_inputs")]) == 2
    assert len([s for s in job.state_steps if s.args.get("require_unique") is True]) == 2


def test_unique_recipe_waits_for_catalog_before_project_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock()
    session.wait_catalog_ready.side_effect = RuntimeError("synthetic catalog barrier")
    monkeypatch.setattr(recorder, "require_colour_management", Mock())
    from pathlib import Path

    with pytest.raises(RuntimeError, match="synthetic catalog barrier"):
        recorder.record_api_probe(
            session,
            probe_job_from_manifest(control.request()),
            Path("unused"),
            Path("unused"),
            Mock(),
            "",
        )
    session.wait_catalog_ready.assert_called_once_with()
    session.call.assert_not_called()
