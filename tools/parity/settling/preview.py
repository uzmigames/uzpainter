"""The preview settling report, `parity/reports/phase2/preview-settling.json` (task
phase2.3_realtime-preview items 2.2 and 4.1; `docs/architecture/07-preview-and-render-parity.md`
§8 Phase 2; decision 162).

`tests/preview/` tags each test that settles a case of the preview gate with
`@pytest.mark.preview_settling(<case>)`: the children's tests are tagged, never copied. A run with
`UZP_PREVIEW_SETTLING_REPORT=<path>` merges what it ran into the report at that path: one entry per
case and backend (pass or fail, run time, the timings the test measured, the exe's SHA-256 and the
date). The GPU cases run on DX12 workers; on Vulkan they are `pending` with decision 121 until a
Vulkan device exists. The diagnostic captures and `painter_iray` never touch a device, so their
backend is `cpu`, as their receipts say. A case that has not run is `not_run`, never a pass.

The file holds numbers, enums, identifiers, dates and SHA-256 digests only, and no oracle data;
the repository guard checks it with `report_problems` (`tools/parity/guard/guard.py`). It shares
`ReportError` and the atomic replacement of the supervisor's report (`report.py`, decision 150).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tools.parity.settling.report import ReportError

SCHEMA_ID = "uzpainter/preview-settling/1"
TASK = "phase2.3_realtime-preview"
REPORT = Path("parity") / "reports" / "phase2" / "preview-settling.json"
GPU_BACKENDS = ("dx12", "vulkan")
BACKENDS = (*GPU_BACKENDS, "cpu")

# The cases of the preview gate and the backends each one must pass on.
CASES: dict[str, tuple[str, ...]] = {
    # 3.1: painter_viewport rendered by a worker that owns no window.
    "viewport_capture_headless": GPU_BACKENDS,
    # 3.1: base_color, channel:<name> and mask:<uid> written without any window.
    "diagnostic_captures_headless": ("cpu",),
    # 3.3: painter_iray refused before any work and listed as a release gap.
    "painter_iray_unavailable": ("cpu",),
    # phase2.1 3.2: evaluation and export with the preview thread stalled.
    "preview_stall": GPU_BACKENDS,
    # phase2.1 3.3: the window opened, minimised, resized and closed during evaluation.
    "preview_window_lifecycle": GPU_BACKENDS,
    # 2.1: the wand v1 with the preview attached: evaluation, export and every capture mode.
    "wand_integration": GPU_BACKENDS,
    # 3.2: the wand v1 export with the window open, minimised and stalled.
    "wand_export_preview": GPU_BACKENDS,
}
VULKAN_DEVICE_DECISION = 121

_ID = r"^[a-z0-9][a-z0-9_]{0,63}$"
_NUMBER = {"type": "number", "minimum": 0}

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "task", "cases"],
    "properties": {
        "schema": {"const": SCHEMA_ID},
        "task": {"const": TASK},
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "backend", "result"],
                "properties": {
                    "id": {"enum": list(CASES)},
                    "backend": {"enum": list(BACKENDS)},
                    "result": {"enum": ["pass", "fail", "pending", "not_run"]},
                    "decision": {"type": "integer", "minimum": 1},
                    "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "exe_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
                    "seconds": _NUMBER,
                    "metrics": {
                        "type": "object",
                        "propertyNames": {"pattern": _ID},
                        "additionalProperties": _NUMBER,
                    },
                },
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA)


def report_problems(document: Any) -> list[str]:
    """Why `document` is not a preview settling report (empty when it is one)."""
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in _VALIDATOR.iter_errors(document)
    ]
    if problems:
        return problems
    keys = [(case["id"], case["backend"]) for case in document["cases"]]
    problems += [f"cases: {key} is listed twice" for key in {k for k in keys if keys.count(k) > 1}]
    problems += [
        f"cases: {case['id']} on {case['backend']} is not a backend the case runs on"
        for case in document["cases"]
        if case["backend"] not in CASES[case["id"]]
    ]
    problems += [
        f"cases: {case['id']} on {case['backend']} passed or failed without its date and exe"
        for case in document["cases"]
        if case["result"] in ("pass", "fail") and not {"date", "exe_sha256"} <= case.keys()
    ]
    return problems


def backend_of(case: str, gpu_backend: str) -> str:
    """The backend a run of `case` settles: `cpu` for a device-free case, else `gpu_backend`."""
    return "cpu" if CASES[case] == ("cpu",) else gpu_backend


def _placeholder(case: str, backend: str) -> dict[str, Any]:
    if backend == "vulkan":
        return {
            "id": case,
            "backend": backend,
            "result": "pending",
            "decision": VULKAN_DEVICE_DECISION,
        }
    return {"id": case, "backend": backend, "result": "not_run"}


def merge(existing: Mapping[str, Any] | None, cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The report `existing` with this run's entries replacing those of the same case and backend;
    every case still missing on a backend is listed as `pending` or `not_run`."""
    by_case: dict[tuple[str, str], dict[str, Any]] = {}
    if existing is not None:
        for case in existing.get("cases", []):
            if case["result"] in ("pass", "fail"):
                by_case[(case["id"], case["backend"])] = dict(case)
    for case in cases:
        by_case[(case["id"], case["backend"])] = dict(case)
    listed = [
        by_case.get((case, backend)) or _placeholder(case, backend)
        for case, backends in CASES.items()
        for backend in backends
    ]
    return {"schema": SCHEMA_ID, "task": TASK, "cases": listed}


def write(path: Path, cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Merges a run into the report at `path` (validated first, then replaced atomically)."""
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    document = merge(existing, cases)
    problems = report_problems(document)
    if problems:
        raise ReportError(f"{path.name}: refusing to write an invalid report: {problems[:5]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)
    return document
