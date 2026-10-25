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


@pytest.mark.parametrize("count", [0, 1, 2])
def test_resource_requires_one_fresh_exact_identity(count: int) -> None:
    tree = ast.parse(PAINTER_PROBES.read_text())
    function = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "uniquely_searched_resource"
    )
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
    namespace: dict[str, Any] = {
        "Any": Any,
        "substance_painter": SimpleNamespace(resource=SimpleNamespace(search=search)),
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(PAINTER_PROBES), "exec"),
        namespace,
    )
    if count == 1:
        assert namespace[function.name](selection_args()) is identifier
    else:
        with pytest.raises(ValueError, match="one versioned exact match"):
            namespace[function.name](selection_args())
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
