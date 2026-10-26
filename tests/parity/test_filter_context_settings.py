"""Authored settings panels, never copied private observations or admission results."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.parity.test_filter_context_contract import lifecycle
from tests.parity.test_painter_filter_context import frames
from tools.parity import filter_context_settings as settings
from tools.parity.filter_context_contract import (
    BOUNDARIES,
    CONDITIONS,
    ContextRefused,
    FContextEvidence,
    require_effective_settings,
    typed,
    validate_context_sequence,
)
from tools.parity.tier0_semantics.source_substance_control import PLANE_SHA256

MESH = Path("parity/fixtures/meshes/plane.obj").read_bytes()
IMPORT_PATH = "C:/authored-input/plane.obj"
IDENTITY = {
    "session_id": "authored-settings-session",
    "pid": 41,
    "started": "authored-start",
    "project_uuid": "authored-project",
    "main_hwnd": 100,
}
DIALOG = {"hwnd": 200, "pid": 41}


def snapshot(*, physical: bool) -> dict[str, Any]:
    unavailable = {"unavailable": "NoPatternInterfaceError"}
    rows = []
    tree = []
    for name in settings.SELECTORS if physical else ("tangent", "workflow"):
        automation_id, kind, label = settings.SELECTORS[name]
        enabled = name != "workflow"
        rows.append(
            {
                "label": label,
                "type": kind,
                "automation_id": automation_id,
                "enabled": enabled,
                "value": deepcopy(unavailable),
                "toggle": 0 if kind == "CheckBox" else deepcopy(unavailable),
                "selected": (1 if name == "internal" else 0)
                if kind == "RadioButton"
                else deepcopy(unavailable),
                "visible": True,
                "process_id": 41,
            }
        )
        tree.append(
            {
                "control_type": kind,
                "automation_id": automation_id,
                "class_name": "Authored",
                "text": label,
                "enabled": enabled,
                "box": [10, 20, 100, 40],
            }
        )
    result: dict[str, Any] = {"tree": tree, "values": rows, "dialog": deepcopy(DIALOG)}
    if physical:
        result["expanded_by_click"] = True
    return result


def authored() -> tuple[dict[str, Any], FContextEvidence]:
    _, _, contexts = frames()
    recipe, trace = lifecycle()
    for frame in contexts:
        for output in frame["outputs"]:
            if output["call"].endswith("project.last_imported_mesh_path"):
                output["value"] = IMPORT_PATH
    context = validate_context_sequence(recipe, trace, contexts)
    recordings = [
        {"condition": condition, "session_id": IDENTITY["session_id"], "outputs": []}
        for condition in ("same_session", "after_save_reopen")
    ]
    pin = {"sha256": hashlib.sha256(MESH).hexdigest(), "size_bytes": len(MESH)}
    for frame in contexts:
        boundary = frame["boundary"]
        digest = hashlib.sha256(typed(frame["outputs"])).hexdigest()
        body = {
            "schema": settings.SCHEMA,
            "boundary": boundary,
            "condition": CONDITIONS[boundary],
            "binding": {
                "before": deepcopy(IDENTITY),
                "after": deepcopy(IDENTITY),
                "context_before_sha256": digest,
                "context_after_sha256": digest,
                "context_after_outputs": deepcopy(frame["outputs"]),
            },
            "mesh_import": {
                "input_id": "plane",
                "resolved_path": IMPORT_PATH,
                "before": deepcopy(pin),
                "after": deepcopy(pin),
            },
            "ui": {
                "configuration": snapshot(physical=False),
                "physical_size": snapshot(physical=True),
            },
            "images": [
                {"output_id": f"settings/{boundary}/{name}-image", **DIALOG}
                for name in ("configuration", "physical-size")
            ],
        }
        outputs = recordings[0 if frame["condition"] == "same_session" else 1]["outputs"]
        assert isinstance(outputs, list)
        outputs.extend(deepcopy(frame["outputs"]))
        outputs.append(
            {
                "output_id": f"settings/{boundary}/panel",
                "kind": "settings_panel_readback",
                "panel": settings.PANEL,
                "values": body,
            }
        )
        outputs.extend(
            {
                "output_id": image["output_id"],
                "kind": "settings_panel_evidence",
                "panel": settings.PANEL,
                "blob": {"sha256": "a" * 64, "size_bytes": 90, "media_type": "image/png"},
            }
            for image in body["images"]
        )
    return {
        "golden_id": settings.GOLDEN_ID,
        "key": {
            "inputs": [{"input_id": "plane", "sha256": PLANE_SHA256}],
            "project_settings": {"create": deepcopy(recipe["steps"][0]["args"])},
        },
        "recordings": recordings,
    }, context


def panel(record: dict[str, Any], boundary: str = "after-create") -> dict[str, Any]:
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            if output["output_id"] == f"settings/{boundary}/panel":
                result: dict[str, Any] = output["values"]
                return result
    raise AssertionError("authored panel absent")


def test_split_preserves_identity_authorship_context_and_copies_everything() -> None:
    record, context = authored()
    before = deepcopy(record)
    core, panels = settings.split_settings_outputs(record)
    assert typed(record) == typed(before)
    assert core["golden_id"] == record["golden_id"]
    assert core["key"] == record["key"]
    assert tuple(p["boundary"] for p in panels) == BOUNDARIES
    assert sum(len(r["outputs"]) for r in record["recordings"]) == (
        sum(len(r["outputs"]) for r in core["recordings"]) + 15
    )
    result = settings.derive_effective_settings(context, panels, MESH)
    assert (result.tangent_space, result.workflow, result.effective_cm_per_unit) == (
        "PerVertex",
        "Default",
        1,
    )
    assert result.provenance_basis == "unitless-obj-internal-centimetres-v1"
    assert not hasattr(result, "authored_settings")
    panels[0]["ui"]["configuration"]["values"][0]["toggle"] = 1
    core["key"]["project_settings"]["create"]["mesh"] = "changed"
    assert result.panels[0]["ui"]["configuration"]["values"][0]["toggle"] == 0
    assert typed(record) == typed(before)
    with pytest.raises(ContextRefused, match="F_EFFECTIVE_SETTINGS_UNVERIFIED"):
        require_effective_settings(context)


@pytest.mark.parametrize(
    "mutation",
    [
        "historical",
        "source-key",
        "missing-panel",
        "missing-image",
        "extra-slot",
        "reorder-images",
        "wrong-condition",
        "wrong-session",
        "swap-boundaries",
        "panel-extra",
        "body-extra",
        "image-extra",
        "image-type",
        "image-pid",
        "image-id",
        "blob-hash",
        "blob-bool-size",
        "context-separated",
        "new-kind-nonsettings-id",
        "panel-other-round",
    ],
)
def test_exact_slots_and_record_binding_refuse(mutation: str) -> None:
    record, _ = authored()
    outputs = record["recordings"][0]["outputs"]
    index = next(i for i, o in enumerate(outputs) if o["kind"] == "settings_panel_readback")
    body = outputs[index]["values"]
    if mutation == "historical":
        record["golden_id"] = "tier0/api-probes/filter-context-a"
    elif mutation == "source-key":
        record["key"]["inputs"][0]["sha256"] = "0" * 64
    elif mutation == "missing-panel":
        outputs.pop(index)
    elif mutation == "missing-image":
        outputs.pop(index + 1)
    elif mutation == "extra-slot":
        outputs.append(deepcopy(outputs[index]))
    elif mutation == "reorder-images":
        outputs[index + 1], outputs[index + 2] = outputs[index + 2], outputs[index + 1]
    elif mutation == "wrong-condition":
        body["condition"] = "after_save_reopen"
    elif mutation == "wrong-session":
        record["recordings"][0]["session_id"] = "another"
    elif mutation == "swap-boundaries":
        outputs[index]["output_id"] = "settings/pre16-r1/panel"
    elif mutation == "panel-extra":
        outputs[index]["compatible"] = True
    elif mutation == "body-extra":
        body["compatible"] = True
    elif mutation == "image-extra":
        outputs[index + 1]["compatible"] = True
    elif mutation == "image-type":
        outputs[index + 1]["blob"]["media_type"] = "image/jpeg"
    elif mutation == "image-pid":
        body["images"][0]["pid"] = 42
    elif mutation == "image-id":
        body["images"][0]["output_id"] = "unbound"
    elif mutation == "blob-hash":
        outputs[index + 1]["blob"]["sha256"] = "bad"
    elif mutation == "blob-bool-size":
        outputs[index + 1]["blob"]["size_bytes"] = True
    elif mutation == "context-separated":
        outputs.insert(index, {"output_id": "unrelated", "kind": "api_readback"})
    elif mutation == "new-kind-nonsettings-id":
        outputs.append({"output_id": "unrelated", "kind": "settings_panel_readback"})
    else:
        record["recordings"][1]["outputs"].extend(outputs[index : index + 3])
        del outputs[index : index + 3]
    with pytest.raises(ContextRefused):
        settings.split_settings_outputs(record)


@pytest.mark.parametrize(
    "mutation",
    [
        "identity-extra",
        "pid-bool",
        "main-hwnd-bool",
        "identity-after",
        "session-cross-boundary",
        "uuid",
        "digest-before",
        "digest-after",
        "after-value",
        "after-typed-value",
        "needs-saving",
        "mesh-input",
        "mesh-hash",
        "mesh-size",
        "mesh-after",
        "mesh-path",
        "mesh-relative",
        "mesh-format",
        "mesh-cross-boundary",
        "dialog-pid",
        "dialog-main",
        "dialog-after",
        "expansion-bool",
        "tree-error",
        "tree-duplicate",
        "row-duplicate-foreign",
        "row-extra",
        "selector-label",
        "selector-type",
        "selector-id",
        "selector-invisible",
        "selector-foreign",
        "tangent",
        "workflow",
        "internal",
        "custom",
        "bool-state",
        "unknown-state",
        "unavailable-state",
    ],
)
def test_closed_panel_context_and_target_refuse(mutation: str) -> None:
    record, _ = authored()
    body = panel(record)
    binding = body["binding"]
    mesh = body["mesh_import"]
    ui = body["ui"]["physical_size"]
    row = ui["values"][0]
    if mutation == "identity-extra":
        binding["before"]["success"] = True
    elif mutation == "pid-bool":
        binding["before"]["pid"] = True
    elif mutation == "main-hwnd-bool":
        binding["before"]["main_hwnd"] = True
    elif mutation == "identity-after":
        binding["after"]["started"] = "another-start"
    elif mutation == "session-cross-boundary":
        for side in ("before", "after"):
            panel(record, "pre16-r2")["binding"][side]["started"] = "another-start"
    elif mutation == "uuid":
        for side in ("before", "after"):
            binding[side]["project_uuid"] = "another-project"
    elif mutation in ("digest-before", "digest-after"):
        binding["context_" + mutation.split("-")[1] + "_sha256"] = "0" * 64
    elif mutation in ("after-value", "after-typed-value", "needs-saving"):
        output = next(
            o for o in binding["context_after_outputs"] if o["call"].endswith("needs_saving")
        )
        output["value"] = True if mutation == "after-value" else 0
        binding["context_after_sha256"] = hashlib.sha256(
            typed(binding["context_after_outputs"])
        ).hexdigest()
        if mutation == "needs-saving":
            original = next(
                o
                for o in record["recordings"][0]["outputs"]
                if o.get("call", "").endswith("needs_saving")
            )
            original["value"] = 0
            binding["context_before_sha256"] = binding["context_after_sha256"]
    elif mutation == "mesh-input":
        mesh["input_id"] = "other"
    elif mutation == "mesh-hash":
        mesh["before"]["sha256"] = "0" * 64
    elif mutation == "mesh-size":
        mesh["before"]["size_bytes"] = True
    elif mutation == "mesh-after":
        mesh["after"]["size_bytes"] += 1
    elif mutation in ("mesh-path", "mesh-relative", "mesh-format"):
        mesh["resolved_path"] = {
            "mesh-path": "C:/other/plane.obj",
            "mesh-relative": "plane.obj",
            "mesh-format": "C:/other/plane.fbx",
        }[mutation]
    elif mutation == "mesh-cross-boundary":
        last = panel(record, "pre16-r2")["mesh_import"]
        last["before"]["size_bytes"] += 1
        last["after"]["size_bytes"] += 1
    elif mutation == "dialog-pid":
        ui["dialog"]["pid"] = 42
    elif mutation == "dialog-main":
        ui["dialog"]["hwnd"] = IDENTITY["main_hwnd"]
    elif mutation == "dialog-after":
        ui["dialog"]["hwnd"] += 1
    elif mutation == "expansion-bool":
        ui["expanded_by_click"] = 1
    elif mutation == "tree-error":
        ui["tree"][0]["children_error"] = "authored inaccessible child"
    elif mutation == "tree-duplicate":
        ui["tree"].append(deepcopy(ui["tree"][0]))
    elif mutation == "row-duplicate-foreign":
        duplicate = deepcopy(row)
        duplicate["process_id"] = 42
        duplicate["visible"] = False
        ui["values"].append(duplicate)
    elif mutation == "row-extra":
        row["compatible"] = True
    elif mutation in ("selector-label", "selector-type", "selector-id"):
        row[
            {"selector-label": "label", "selector-type": "type", "selector-id": "automation_id"}[
                mutation
            ]
        ] = "other"
    elif mutation == "selector-invisible":
        row["visible"] = False
    elif mutation == "selector-foreign":
        row["process_id"] = 42
    elif mutation in ("tangent", "workflow", "internal", "custom"):
        index = list(settings.SELECTORS).index(mutation)
        field_name = "toggle" if index < 2 else "selected"
        ui["values"][index][field_name] = 0 if mutation == "internal" else 1
    else:
        row["toggle"] = {
            "bool-state": False,
            "unknown-state": 2,
            "unavailable-state": {"unavailable": "NoPatternInterfaceError"},
        }[mutation]
    with pytest.raises(ContextRefused):
        settings.split_settings_outputs(record)


def test_derivation_revalidates_mutable_panels_mesh_and_context() -> None:
    record, context = authored()
    _, panels = settings.split_settings_outputs(record)
    with pytest.raises(ContextRefused, match="MESH_BYTES"):
        settings.derive_effective_settings(context, panels, MESH + b"\n")
    with pytest.raises(ContextRefused):
        settings.derive_effective_settings(context, panels[:-1], MESH)
    altered = deepcopy(panels)
    for body in altered:
        for side in ("before", "after"):
            body["mesh_import"][side]["size_bytes"] += 1
    with pytest.raises(ContextRefused, match="MESH_SIZE"):
        settings.derive_effective_settings(context, altered, MESH)
    panels[0]["ui"]["physical_size"]["values"][2]["selected"] = 0
    with pytest.raises(ContextRefused):
        settings.derive_effective_settings(context, panels, MESH)


def test_nonsettings_outputs_are_retained_for_the_required_core_parser() -> None:
    record, _ = authored()
    operation = {"output_id": "s999/reload_mesh", "kind": "api_readback", "value": None}
    record["recordings"][0]["outputs"].append(operation)
    core, _ = settings.split_settings_outputs(record)
    assert core["recordings"][0]["outputs"][-1] == operation


def test_windows_mesh_path_spelling_is_normalized_without_filesystem_reads() -> None:
    record, context = authored()
    for boundary in BOUNDARIES:
        panel(record, boundary)["mesh_import"]["resolved_path"] = r"c:\AUTHORED-INPUT\plane.obj"
    _, panels = settings.split_settings_outputs(record)
    settings.derive_effective_settings(context, panels, MESH)
