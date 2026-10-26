"""Pure, closed settings evidence checks; not capture admission or PID attestation.

Call split_settings_outputs, validate its remaining record with the shared F core,
then call derive_effective_settings. Never import the runner from this module.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any

from tools.parity.filter_context_contract import (
    BOUNDARIES,
    CONDITIONS,
    ContextRefused,
    FContextEvidence,
    typed,
    validate_context_readback,
)
from tools.parity.filter_context_contract import (
    SCHEMA as CONTEXT_SCHEMA,
)
from tools.parity.tier0_semantics.source_substance_control import PLANE_SHA256

GOLDEN_ID = "tier0/api-probes/filter-context-settings-a"
SCHEMA = "uzpainter/parity/settings-panel-readback/1"
PROVENANCE_BASIS = "unitless-obj-internal-centimetres-v1"
PANEL = "Project Configuration"
PREFIX = (
    "QApplication.ProjectSettingsDialog.scroll_area.qt_scrollarea_viewport."
    "scroll_area_content.advanced_settings_section.content."
)
SELECTORS = {
    "tangent": (
        PREFIX + "perFragBinormalCheckBox",
        "CheckBox",
        "Compute tangent space per fragment",
    ),
    "workflow": (PREFIX + "useUvTilesGroupBox", "CheckBox", "Use UV Tile workflow"),
    "internal": (
        PREFIX + "physical_size_section.content.PhysicalSizeSettings.useMeshInternalUnit",
        "RadioButton",
        "Use mesh file's internal unit scale (recommended)",
    ),
    "custom": (
        PREFIX + "physical_size_section.content.PhysicalSizeSettings.useCustomUnit",
        "RadioButton",
        "Custom unit scale",
    ),
}
CONTEXT_ID = re.compile(r"context/([a-z0-9-]+)/[0-9]{4}-[A-Za-z_][A-Za-z0-9_]*")
HASH = re.compile(r"[0-9a-f]{64}")


class SettingsRefused(ContextRefused):
    """Closed settings evidence failed; messages contain no captured values."""


@dataclass(frozen=True)
class EffectiveSettingsEvidence:
    """Derived observations only; mutable raw copies are not authenticated capabilities."""

    tangent_space: str
    workflow: str
    effective_cm_per_unit: int
    provenance_basis: str
    panels: tuple[dict[str, Any], ...] = field(repr=False)


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise SettingsRefused("F_SETTINGS_" + code)


def _closed(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == keys, code)
    result: dict[str, Any] = value
    return result


def _positive(value: Any) -> bool:
    return type(value) is int and 0 < value < (1 << 63)


def _text(value: Any) -> bool:
    return type(value) is str and bool(value) and "\x00" not in value


def _hash(value: Any) -> bool:
    return type(value) is str and HASH.fullmatch(value) is not None


def _path(value: Any) -> str:
    _require(_text(value), "MESH_PATH")
    path = PureWindowsPath(value)
    _require(path.is_absolute() and ".." not in path.parts, "MESH_PATH")
    return str(path).casefold()


def _identity(value: Any) -> dict[str, Any]:
    identity = _closed(
        value, {"session_id", "pid", "started", "project_uuid", "main_hwnd"}, "IDENTITY_FIELDS"
    )
    _require(
        all(_text(identity[k]) for k in ("session_id", "started", "project_uuid"))
        and _positive(identity["pid"])
        and _positive(identity["main_hwnd"]),
        "IDENTITY_VALUE",
    )
    return identity


def _getter(outputs: list[dict[str, Any]], name: str) -> Any:
    rows = [
        row
        for row in outputs
        if row["call"] == "substance_painter.project." + name
        and row["args"] == {"selector": {}, "parameters": {}}
    ]
    _require(len(rows) == 1 and "raised" not in rows[0], "PROJECT_GETTER")
    return rows[0]["value"]


def _mesh(value: Any) -> dict[str, Any]:
    mesh = _closed(value, {"input_id", "resolved_path", "before", "after"}, "MESH_FIELDS")
    _require(mesh["input_id"] == "plane", "MESH_INPUT")
    _path(mesh["resolved_path"])
    _require(PureWindowsPath(mesh["resolved_path"]).suffix.casefold() == ".obj", "MESH_FORMAT")
    for side in ("before", "after"):
        pin = _closed(mesh[side], {"sha256", "size_bytes"}, "MESH_PIN_FIELDS")
        _require(pin["sha256"] == PLANE_SHA256 and _positive(pin["size_bytes"]), "MESH_PIN")
    _require(typed(mesh["before"]) == typed(mesh["after"]), "MESH_CHANGED")
    return mesh


def _pattern(value: Any) -> None:
    if type(value) is dict:
        unavailable = _closed(value, {"unavailable"}, "PATTERN_FIELDS")
        _require(_text(unavailable["unavailable"]), "PATTERN_UNAVAILABLE")
    else:
        _require(type(value) in (str, int, bool), "PATTERN_VALUE")


def _snapshot(value: Any, *, physical: bool, identity: dict[str, Any]) -> dict[str, Any]:
    keys = {"tree", "values", "dialog"} | ({"expanded_by_click"} if physical else set())
    snapshot = _closed(value, keys, "SNAPSHOT_FIELDS")
    if physical:
        _require(type(snapshot["expanded_by_click"]) is bool, "EXPANSION_STATE")
    dialog = _closed(snapshot["dialog"], {"hwnd", "pid"}, "DIALOG_FIELDS")
    _require(
        _positive(dialog["hwnd"])
        and dialog["hwnd"] != identity["main_hwnd"]
        and type(dialog["pid"]) is int
        and dialog["pid"] == identity["pid"],
        "DIALOG_IDENTITY",
    )
    _require(type(snapshot["tree"]) is list and bool(snapshot["tree"]), "TREE_MISSING")
    for row in snapshot["tree"]:
        base = {"control_type", "automation_id", "class_name", "text", "enabled", "box"}
        _require(type(row) is dict, "TREE_ROW")
        _closed(
            row, base | ({"children_error"} if "children_error" in row else set()), "TREE_FIELDS"
        )
        _require("children_error" not in row, "TREE_INCOMPLETE")
        _require(
            all(
                type(row[k]) is str for k in ("control_type", "automation_id", "class_name", "text")
            )
            and type(row["enabled"]) is bool
            and type(row["box"]) is list
            and len(row["box"]) == 4
            and all(type(n) is int for n in row["box"]),
            "TREE_VALUE",
        )
    _require(type(snapshot["values"]) is list and bool(snapshot["values"]), "VALUES_MISSING")
    for row in snapshot["values"]:
        _closed(
            row,
            {
                "label",
                "type",
                "automation_id",
                "enabled",
                "value",
                "toggle",
                "selected",
                "visible",
                "process_id",
            },
            "ROW_FIELDS",
        )
        _require(
            all(type(row[k]) is str for k in ("label", "type", "automation_id"))
            and type(row["enabled"]) is bool
            and type(row["visible"]) is bool
            and _positive(row["process_id"]),
            "ROW_VALUE",
        )
        for pattern in ("value", "toggle", "selected"):
            _pattern(row[pattern])
    return snapshot


def _selector(snapshot: dict[str, Any], name: str, pid: int) -> dict[str, Any]:
    automation_id, kind, label = SELECTORS[name]
    # Count the identity first; never hide duplicates by filtering ownership/visibility.
    rows = [r for r in snapshot["values"] if r["automation_id"] == automation_id]
    tree = [r for r in snapshot["tree"] if r["automation_id"] == automation_id]
    _require(len(rows) == len(tree) == 1, "SELECTOR_AMBIGUOUS")
    row: dict[str, Any] = rows[0]
    node = tree[0]
    _require(
        row["type"] == node["control_type"] == kind
        and row["label"] == node["text"] == label
        and row["enabled"] is node["enabled"]
        and row["visible"] is True
        and row["process_id"] == pid,
        "SELECTOR_IDENTITY",
    )
    return row


def _target(snapshot: dict[str, Any], name: str, pid: int) -> None:
    row = _selector(snapshot, name, pid)
    field_name = "toggle" if name in ("tangent", "workflow") else "selected"
    expected = 1 if name == "internal" else 0
    _require(type(row[field_name]) is int and row[field_name] == expected, "NON_TARGET_STATE")


def _panel(value: Any, outputs: list[dict[str, Any]]) -> dict[str, Any]:
    typed(value)
    panel = _closed(
        value,
        {"schema", "boundary", "condition", "binding", "mesh_import", "ui", "images"},
        "PANEL_FIELDS",
    )
    boundary = panel["boundary"]
    _require(type(boundary) is str and boundary in BOUNDARIES, "BOUNDARY")
    _require(panel["schema"] == SCHEMA and panel["condition"] == CONDITIONS[boundary], "SCHEMA")
    binding = _closed(
        panel["binding"],
        {
            "before",
            "after",
            "context_before_sha256",
            "context_after_sha256",
            "context_after_outputs",
        },
        "BINDING_FIELDS",
    )
    identity = _identity(binding["before"])
    _identity(binding["after"])
    _require(typed(binding["before"]) == typed(binding["after"]), "IDENTITY_CHANGED")
    frame = {
        "schema": CONTEXT_SCHEMA,
        "boundary": boundary,
        "condition": panel["condition"],
        "outputs": outputs,
    }
    validate_context_readback(frame)
    after = binding["context_after_outputs"]
    validate_context_readback({**frame, "outputs": after})
    digest = hashlib.sha256(typed(outputs)).hexdigest()
    _require(
        binding["context_before_sha256"] == digest
        and binding["context_after_sha256"] == hashlib.sha256(typed(after)).hexdigest()
        and typed(outputs) == typed(after),
        "CONTEXT_CHANGED",
    )
    _require(_getter(outputs, "get_uuid") == identity["project_uuid"], "PROJECT_UUID")
    _require(type(_getter(outputs, "needs_saving")) is bool, "NEEDS_SAVING")
    mesh = _mesh(panel["mesh_import"])
    _require(
        _path(_getter(outputs, "last_imported_mesh_path")) == _path(mesh["resolved_path"]),
        "IMPORTED_PATH",
    )
    ui = _closed(panel["ui"], {"configuration", "physical_size"}, "UI_FIELDS")
    configuration = _snapshot(ui["configuration"], physical=False, identity=identity)
    physical = _snapshot(ui["physical_size"], physical=True, identity=identity)
    _require(typed(configuration["dialog"]) == typed(physical["dialog"]), "DIALOG_CHANGED")
    for name in ("tangent", "workflow"):
        _target(configuration, name, identity["pid"])
        _target(physical, name, identity["pid"])
    for name in ("internal", "custom"):
        _target(physical, name, identity["pid"])
    _require(type(panel["images"]) is list and len(panel["images"]) == 2, "IMAGES_MISSING")
    for image, suffix in zip(
        panel["images"], ("configuration-image", "physical-size-image"), strict=True
    ):
        _closed(image, {"output_id", "hwnd", "pid"}, "IMAGE_FIELDS")
        _require(
            image["output_id"] == f"settings/{boundary}/{suffix}"
            and typed({k: image[k] for k in ("hwnd", "pid")}) == typed(configuration["dialog"]),
            "IMAGE_BINDING",
        )
    return panel


def split_settings_outputs(
    record: dict[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Remove exactly five validated adjacent panel/image triples; preserve all identities."""
    typed(record)
    _require(type(record) is dict and record.get("golden_id") == GOLDEN_ID, "GOLDEN")
    key = record.get("key", {})
    _require(type(key) is dict, "RECORD_KEY")
    _require(
        typed(key.get("inputs")) == typed([{"input_id": "plane", "sha256": PLANE_SHA256}]),
        "INPUT_KEY",
    )
    recordings = record.get("recordings")
    _require(type(recordings) is list and len(recordings) == 2, "RECORDINGS")
    result = deepcopy(record)
    panels: list[dict[str, Any]] = []
    for recording in result["recordings"]:
        _require(type(recording) is dict and type(recording.get("outputs")) is list, "RECORDING")
        outputs = recording["outputs"]
        kept: list[dict[str, Any]] = []
        index = 0
        while index < len(outputs):
            output = outputs[index]
            _require(type(output) is dict and type(output.get("output_id")) is str, "OUTPUT")
            match = CONTEXT_ID.fullmatch(output["output_id"])
            if match is None:
                _require(
                    not output["output_id"].startswith("settings/")
                    and output.get("kind")
                    not in ("settings_panel_readback", "settings_panel_evidence"),
                    "UNEXPECTED_SLOT",
                )
                kept.append(output)
                index += 1
                continue
            boundary = match.group(1)
            leaves = []
            while index < len(outputs):
                row = outputs[index]
                _require(type(row) is dict and type(row.get("output_id")) is str, "OUTPUT")
                found = CONTEXT_ID.fullmatch(row["output_id"])
                if found is None or found.group(1) != boundary:
                    break
                leaves.append(row)
                kept.append(row)
                index += 1
            _require(index + 2 < len(outputs), "SLOTS_MISSING")
            output = _closed(
                outputs[index], {"output_id", "kind", "panel", "values"}, "SLOT_FIELDS"
            )
            _require(
                output["output_id"] == f"settings/{boundary}/panel"
                and output["kind"] == "settings_panel_readback"
                and output["panel"] == PANEL,
                "SLOT_IDENTITY",
            )
            panel = _panel(output["values"], leaves)
            _require(
                panel["boundary"] == boundary
                and panel["condition"] == recording.get("condition")
                and panel["binding"]["before"]["session_id"] == recording.get("session_id"),
                "RECORDING_BINDING",
            )
            for position, image in enumerate(panel["images"], index + 1):
                screenshot = _closed(
                    outputs[position], {"output_id", "kind", "panel", "blob"}, "PNG_FIELDS"
                )
                blob = _closed(
                    screenshot["blob"], {"sha256", "size_bytes", "media_type"}, "PNG_BLOB_FIELDS"
                )
                _require(
                    screenshot["output_id"] == image["output_id"]
                    and screenshot["kind"] == "settings_panel_evidence"
                    and screenshot["panel"] == PANEL
                    and _hash(blob["sha256"])
                    and _positive(blob["size_bytes"])
                    and blob["media_type"] == "image/png",
                    "PNG_BINDING",
                )
            panels.append(panel)
            index += 3
        recording["outputs"] = kept
    _sequence(panels)
    return result, tuple(deepcopy(panels))


def _sequence(panels: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
    _require(tuple(p["boundary"] for p in panels) == BOUNDARIES, "BOUNDARY_SEQUENCE")
    first = panels[0]
    for panel in panels[1:]:
        _require(
            typed(panel["binding"]["before"]) == typed(first["binding"]["before"]),
            "SESSION_CHANGED",
        )
        _require(typed(panel["mesh_import"]) == typed(first["mesh_import"]), "IMPORT_CHANGED")


def derive_effective_settings(
    context: FContextEvidence,
    panels: tuple[dict[str, Any], ...],
    mesh_bytes: bytes,
) -> EffectiveSettingsEvidence:
    """Derive target settings after the caller validates the unchanged F recipe/lifecycle.

    The caller authenticates records, producer, import trace and PNG bytes separately.
    This function neither admits evidence nor changes historical F's missing settings.
    """
    _require(
        isinstance(context, FContextEvidence) and type(panels) is tuple and len(panels) == 5,
        "CONTEXT_EVIDENCE",
    )
    _require(len(context.contexts) == 5 and type(mesh_bytes) is bytes, "CONTEXT_EVIDENCE")
    _require(hashlib.sha256(mesh_bytes).hexdigest() == PLANE_SHA256, "MESH_BYTES")
    checked = []
    for frame, panel in zip(context.contexts, panels, strict=True):
        validate_context_readback(frame)
        checked.append(_panel(panel, frame["outputs"]))
        _require(
            panel["boundary"] == frame["boundary"] and panel["condition"] == frame["condition"],
            "CONTEXT_BOUNDARY",
        )
        _require(panel["mesh_import"]["before"]["size_bytes"] == len(mesh_bytes), "MESH_SIZE")
    _sequence(checked)
    return EffectiveSettingsEvidence(
        "PerVertex", "Default", 1, PROVENANCE_BASIS, tuple(deepcopy(checked))
    )
