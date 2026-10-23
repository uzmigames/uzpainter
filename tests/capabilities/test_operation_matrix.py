"""The requirement-to-typed-operation matrix of the capability manifest (task
phase2.7_mcp-operation-matrix items 3.1-3.3; decision 182; `docs/architecture/11-mcp-server.md` §2).

`tools/capabilities/generate_capabilities.py` writes `operation_matrix` from
`operation-matrix.json` and the build's registered MCP tools (`mcp-tools.json`, kept equal to a live
worker's listing by tests/supervisor/test_operation_matrix.py). These tests run on the hosted CPU
lane: no executable, no GPU.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tools.capabilities.generate_capabilities import (
    ADDITIONS_PATH,
    MATRIX_PATH,
    REQUIRED_OPERATIONS,
    TOOLS_PATH,
    GenerationError,
    generate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "tools" / "capabilities" / "capabilities.schema.json"

# The INT-02 operations of docs/prd.md, one per call the pipeline makes today.
INT_02 = {
    "status",
    "project.inspect",
    "project.create",
    "project.open",
    "project.close",
    "project.save",
    "project.save_as",
    "texture_set.list",
    "resource.import",
    "texture_set.mesh_maps",
    "stack.sync",
    "stack.smart_material",
    "stack.procedural",
    "layer.get",
    "layer.set",
    "resource.replace",
    "diagnostics.snapshot",
    "project.recipe",
    "export.preset",
    "export.config",
    "render.capture",
    "mesh.reload",
    "bake.start",
    "job.status",
    "diagnostics.isolate_layer",
}
# Tools registered with their schemas whose native implementation is not in this build.
GAP_TOOLS = {
    "resource_search",
    "assets_search",
    "layer_instantiate",
    "procedural_set",
    "anchor_list",
    "smart_material_insert",
    "smart_mask_insert",
    "smart_export",
    "apply_smart",
}


@pytest.fixture(scope="module")
def matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = generate()["operation_matrix"]
    return rows


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def generated(
    tmp_path: Path,
    rows: dict[str, Any] | None = None,
    tools: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
    additions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    arguments: dict[str, Path] = {}
    if additions is not None:
        arguments["additions_path"] = write(tmp_path / "additions.json", additions)
    if rows is not None:
        arguments["matrix_path"] = write(tmp_path / "matrix.json", rows)
    if tools is not None:
        arguments["tools_path"] = write(tmp_path / "tools.json", tools)
    if inventory is not None:
        arguments["inventory_path"] = write(tmp_path / "inventory.json", inventory)
    result: list[dict[str, Any]] = generate(**arguments)["operation_matrix"]
    return result


def failure(tmp_path: Path, **inputs: dict[str, Any]) -> str:
    with pytest.raises(GenerationError) as error:
        generated(tmp_path, **inputs)
    return str(error.value)


def row_of(document: dict[str, Any], operation: str) -> dict[str, Any]:
    [row] = [row for row in document["rows"] if row["operation"] == operation]
    found: dict[str, Any] = row
    return found


# ── 3.1 Completeness ───────────────────────────────────────────────────────────────────────


def test_one_row_per_required_operation(matrix: list[dict[str, Any]]) -> None:
    """3.1: every INT-02 operation and every ARC-14 family operation has exactly one row, in the
    order of `REQUIRED_OPERATIONS`, citing the requirement that requires it; the matrix validates
    against the manifest schema."""
    assert [row["operation"] for row in matrix] == [op for op, _ in REQUIRED_OPERATIONS]
    assert {op for op, requirement in REQUIRED_OPERATIONS if requirement == "INT-02"} == INT_02
    required = dict(REQUIRED_OPERATIONS)
    for row in matrix:
        assert required[row["operation"]] in row["requirements"], row
    validator = Draft202012Validator(load(SCHEMA_PATH))
    assert [error.message for error in validator.iter_errors(generate())] == []


def test_every_fixture_is_a_collectable_test(matrix: list[dict[str, Any]]) -> None:
    """3.1: each fixture id names a test pytest collects."""
    fixtures = sorted({row["fixture"] for row in matrix if row["fixture"]})
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *fixtures,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    for fixture in fixtures:
        assert fixture in collected.stdout, fixture


# ── 3.2 The build check ────────────────────────────────────────────────────────────────────


def test_a_removed_row_fails_naming_its_operation(tmp_path: Path) -> None:
    """3.2: a required operation without a row fails generation."""
    rows = load(MATRIX_PATH)
    rows["rows"] = [row for row in rows["rows"] if row["operation"] != "mesh.reload"]
    assert "required operation 'mesh.reload' (INT-02) has no operation matrix row" in failure(
        tmp_path, rows=rows
    )


def test_an_unregistered_tool_fails_naming_the_row(tmp_path: Path) -> None:
    """3.2: a row naming a tool the build does not register fails generation."""
    tools = load(TOOLS_PATH)
    tools["tools"] = [tool for tool in tools["tools"] if tool["name"] != "mesh_reload"]
    message = failure(tmp_path, tools=tools)
    assert "row 'mesh.reload'" in message and "does not register" in message


def test_an_available_row_without_its_fixture_fails(tmp_path: Path) -> None:
    """3.2 (the spec's scenario): an available export row without a conformance fixture id fails
    generation and names the row."""
    rows = load(MATRIX_PATH)
    row_of(rows, "export.preset")["fixture"] = None
    message = failure(tmp_path, rows=rows)
    assert "row 'export.preset'" in message and "conformance fixture" in message


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("fixture", "tests/supervisor/test_typed_tools.py::test_absent", "is not a test"),
        ("requirements", ["INT-02", "XYZ-99"], "not requirements of docs/prd.md"),
        ("requirements", ["PRJ-08"], "does not cite INT-02"),
        ("arguments", {"/kind": "fill"}, "does not gate the argument value"),
        ("operation", "mesh.repair", "is not a required operation"),
        ("tool", "run_python", "names the task that owns the operation"),
    ],
)
def test_a_malformed_row_fails_naming_it(
    tmp_path: Path, field: str, value: Any, expected: str
) -> None:
    """3.2: a fixture its file does not define, an unknown or missing requirement, an argument
    value the tool does not gate, an operation outside the list and a gap row without its owner
    each fail generation."""
    rows = load(MATRIX_PATH)
    row_of(rows, "mesh.reload")[field] = value
    assert expected in failure(tmp_path, rows=rows)


def test_a_repeated_row_fails(tmp_path: Path) -> None:
    rows = load(MATRIX_PATH)
    rows["rows"].append(copy.deepcopy(row_of(rows, "status")))
    assert "row 'status' is listed twice" in failure(tmp_path, rows=rows)


# ── 3.3 Statuses ───────────────────────────────────────────────────────────────────────────


def test_an_operation_without_a_typed_tool_is_a_capability_gap(tmp_path: Path) -> None:
    """3.3 (the spec's scenario): in a build that registers no mesh-reload tool, its row names no
    tool and is a capability gap."""
    rows = load(MATRIX_PATH)
    row = row_of(rows, "mesh.reload")
    row.update(tool=None, fixture=None, notes="Owner phase2.7_mcp-operation-matrix (example).")
    tools = load(TOOLS_PATH)
    tools["tools"] = [tool for tool in tools["tools"] if tool["name"] != "mesh_reload"]
    [reload] = [r for r in generated(tmp_path, rows=rows, tools=tools) if r["tool"] is None]
    assert reload["operation"] == "mesh.reload" and reload["status"] == "capability gap"


def test_families_not_in_the_build_are_capability_gaps(matrix: list[dict[str, Any]]) -> None:
    """3.3: every row of a gap family, of a gated argument value that is a release gap and of an
    export format or capture mode the manifest lists as a gap (or does not list) is a capability
    gap naming its owner; no row is satisfied by `run_python`."""
    rows = {row["operation"]: row for row in matrix}
    for row in matrix:
        assert row["tool"] != "run_python", row
        if row["tool"] in GAP_TOOLS:
            assert row["status"] == "capability gap" and row["gaps"], row
        if row["status"] != "available":
            assert row["notes"] and "phase" in row["notes"], row
    for operation in ("effect.insert_paint", "projection.triplanar", "export.format.tiff"):
        assert rows[operation]["status"] == "capability gap", operation
    assert rows["export.format.dds"]["gaps"] == [
        {
            "symbol": "substance_painter.export.export_project_textures",
            "context": "file-format:dds",
            "status": "unlisted",
        }
    ]
    assert rows["layer.insert_fill"]["status"] == rows["export.format.png"]["status"] == "available"
    assert rows["layer.insert_paint"]["status"] == "available"  # empty paint layers (decision 348)
    assert rows["bake.start"]["status"] == "available"  # the native bake job (decision 355)


def test_a_python_only_operation_needs_python(tmp_path: Path) -> None:
    """3.3: a row reachable only through `run_python` is `needs Python`, a gap, never available."""
    rows = load(MATRIX_PATH)
    row = row_of(rows, "mesh.reload")
    row.update(tool="run_python", notes="Owner phase3.1_example until its typed tool exists.")
    [reload] = [r for r in generated(tmp_path, rows=rows) if r["operation"] == "mesh.reload"]
    assert reload["status"] == "needs Python"


def test_the_status_follows_the_manifest(tmp_path: Path) -> None:
    """3.3: the status is derived. Once the paint effect leaves the release gaps, its row is
    available, and the build then requires a conformance fixture for it."""
    # `effect_insert` of kind `paint` creates a `uzpainter.layerstack.PaintEffectNode`.
    additions = load(ADDITIONS_PATH)
    [entry] = [
        e
        for e in additions["entries"]
        if (e["symbol"], e["context"]) == ("uzpainter.layerstack.PaintEffectNode", "any")
    ]
    entry.update(
        status="pending-evidence",
        notes="Implemented, without Tier 0 evidence yet: evidence owned by "
        "phase4.1_nodes-paint-layers.",
    )
    message = failure(tmp_path, additions=additions)
    assert "row 'effect.insert_paint'" in message and "conformance fixture" in message
    rows = load(MATRIX_PATH)
    row_of(rows, "effect.insert_paint")["fixture"] = row_of(rows, "layer.insert_paint")["fixture"]
    paint = {
        r["operation"]: r
        for r in generated(tmp_path, rows=rows, additions=additions)
        if r["operation"] in ("layer.insert_paint", "effect.insert_paint")
    }
    assert [r["status"] for r in paint.values()] == ["available", "available"]
    assert paint["effect.insert_paint"]["gaps"] == []
