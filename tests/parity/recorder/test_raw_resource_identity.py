"""Exercise real recorder branches against authored API doubles; never launch Painter."""

from __future__ import annotations

import ast
import enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.recorder.session import RecorderError
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


class Identifier:
    def __init__(self, context: str, name: str, version: str | None) -> None:
        self.context, self.name, self.version = context, name, version


def runtime() -> dict[str, Any]:
    path = Path("tools/parity/recorder/painter_probes.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"host_read", "p295_read", "resource_id", "describe", "uuid_record"}
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            body.append(node)
        elif isinstance(node, ast.Assign) and all(
            isinstance(t, ast.Name) and t.id.isupper() for t in node.targets
        ):
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            body.append(node)
    calls: list[tuple[str, str | None]] = []

    def from_project(name: str, version: str | None = None) -> Identifier:
        calls.append((name, version))
        return Identifier("current-project-context", name, version)

    namespace: dict[str, Any] = {
        "Any": Any,
        "enum": enum,
        "substance_painter": SimpleNamespace(
            resource=SimpleNamespace(ResourceID=Identifier, Resource=SimpleNamespace()),
            colormanagement=SimpleNamespace(Color=type("Color", (), {})),
            project=SimpleNamespace(get_uuid=lambda: "public-project"),
            textureset=SimpleNamespace(),
        ),
        "OWN_PROJECT_CREATION": {"uuid": "public-project"},
        "CURRENT": {"step": 32},
        "PROBE_RESOURCES": {4: Identifier("import-context", "public-input", "public-version")},
        "calls": calls,
    }
    Identifier.from_project = staticmethod(from_project)  # type: ignore[attr-defined]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)
    namespace["substance_painter"].resource.Resource.retrieve = lambda identifier: [
        SimpleNamespace(identifier=lambda: identifier)
    ]
    return namespace


def test_real_query_uses_import_identity_and_round_context() -> None:
    ns = runtime()
    query = ns["host_read"](control.RESOURCE_FROM_PROJECT, {"import_step": 4})
    assert ns["calls"] == [("public-input", "public-version")]
    assert query.context == "current-project-context"
    assert ns["host_read"](control.RESOURCE_RETRIEVE, {"resource_step": 32}) == [
        {"resource": {"context": query.context, "name": query.name, "version": query.version}}
    ]
    assert ns["p295_read"](control.PROJECT_UUID, {"owned_project": True}) == {
        "created_project_uuid": "public-project",
        "current_project_uuid": "public-project",
    }


@pytest.mark.parametrize("version", [None, "", 1])
def test_real_query_refuses_absent_or_untyped_version(version: Any) -> None:
    ns = runtime()
    ns["PROBE_RESOURCES"][4].version = version
    with pytest.raises(ValueError, match="imported name and version"):
        ns["host_read"](control.RESOURCE_FROM_PROJECT, {"import_step": 4})
    assert ns["calls"] == []


@pytest.mark.parametrize("count", [0, 2])
def test_real_retrieval_preserves_ambiguity_for_validator(count: int) -> None:
    ns = runtime()
    query = ns["host_read"](control.RESOURCE_FROM_PROJECT, {"import_step": 4})
    ns["substance_painter"].resource.Resource.retrieve = lambda _: [
        SimpleNamespace(identifier=lambda: query) for _ in range(count)
    ]
    assert len(ns["host_read"](control.RESOURCE_RETRIEVE, {"resource_step": 32})) == count


def test_real_owned_uuid_reads_current_project_independently() -> None:
    ns = runtime()
    ns["substance_painter"].project.get_uuid = lambda: "foreign-project"
    result = ns["p295_read"](control.PROJECT_UUID, {"owned_project": True})
    assert result["created_project_uuid"] != result["current_project_uuid"]
    with pytest.raises(ValueError):
        ns["p295_read"](control.PROJECT_UUID, {"owned_project": 1})


@pytest.mark.parametrize(
    "mutation",
    [
        "import_wrong",
        "import_later",
        "import_bool",
        "import_extra",
        "retrieve_wrong",
        "retrieve_later",
        "retrieve_bool",
        "retrieve_extra",
        "uuid_bool",
        "uuid_extra",
    ],
)
def test_public_recipe_refuses_wrong_identity_references(mutation: str) -> None:
    manifest = control.request("calibration-float")
    steps = manifest["instruction_sequence"]["steps"]
    by_call = {s["call"]: s for s in steps}
    if mutation.startswith("import_"):
        step = by_call[control.RESOURCE_FROM_PROJECT]
        step["args"]["import_step"] = {
            "import_wrong": 2,
            "import_later": step["step"] + 1,
            "import_bool": True,
            "import_extra": 4,
        }[mutation]
    elif mutation.startswith("retrieve_"):
        step = by_call[control.RESOURCE_RETRIEVE]
        step["args"]["resource_step"] = {
            "retrieve_wrong": 4,
            "retrieve_later": step["step"] + 1,
            "retrieve_bool": True,
            "retrieve_extra": step["step"] - 1,
        }[mutation]
    else:
        step = by_call[control.PROJECT_UUID]
        step["args"]["owned_project"] = 1 if mutation == "uuid_bool" else True
    if mutation.endswith("extra"):
        step["args"]["extra"] = True
    with pytest.raises(RecorderError):
        probe_job_from_manifest(manifest)
