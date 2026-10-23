"""Backend-scoped export evidence from the existing exact Painter facade replay."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.python.capability_trace import exercised
from tests.python.conftest import FACADE_PRELUDE, JSON_PREFIX, REPO_ROOT
from tests.python.test_pyapi_cli import painter  # noqa: F401
from tests.python.test_pyapi_facade_tier0 import CONDITIONS, compare
from tools.capabilities.generate_capabilities import generate

TRACE = REPO_ROOT / "tools/capabilities/backend-tier0-trace.json"
PROBE = "active-channel-order-control"
GOLDEN = f"tier0/api-probes/{PROBE}"
SYMBOLS = [
    "substance_painter.export.export_project_textures",
    "uzpainter.export.export_project_textures",
]
SCOPE = (
    "Uniform BaseColor (Working) and Height (Raw), plane 256x256, PNG16, infinite "
    "padding without dithering, same session and after save/reopen; "
    "phase3.1_vulkan-compute-parity item 2.10. No other export configuration or capture is claimed."
)


@pytest.mark.skipif(os.environ.get("UZP_NO_GPU") == "1", reason="Vulkan Tier 0 hardware replay")
def test_vulkan_export_equals_painter(painter: Path, tmp_path: Path) -> None:  # noqa: F811
    reports: list[dict[str, Any]] = []

    def run(body: str) -> dict[str, Any]:
        script = tmp_path / "backend-replay.py"
        script.write_text(FACADE_PRELUDE + body, encoding="utf-8")
        process = subprocess.run(
            [str(painter), "run", str(script), str(tmp_path), "--gpu-backend", "vulkan"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        lines = [line for line in process.stdout.splitlines() if line.startswith(JSON_PREFIX)]
        assert process.returncode == 0 and lines, process.stdout + process.stderr
        report: dict[str, Any] = json.loads(lines[-1][len(JSON_PREFIX) :])
        assert report["status"] == "ok" and report["gpu_backend"] == "vulkan", report
        reports.append(report)
        return report

    # The original comparison covers readbacks, identities, defaults and every native-depth texel.
    assert compare(PROBE, run, tmp_path) == []
    [report] = reports
    replayed = report["result"]
    symbols = exercised(replayed["trace"])
    assert set(SYMBOLS) <= set(symbols)
    receipts: set[Path] = set()
    for condition in CONDITIONS:
        files = replayed[condition]["files"]
        assert len(files) == 2
        for exported in files.values():
            assert isinstance(exported, list) and len(exported) == 1
            image = Path(exported[0])
            delivery = next(
                parent for parent in image.parents if (parent / "current.json").is_file()
            )
            current = json.loads((delivery / "current.json").read_text(encoding="utf-8"))
            receipt_path = delivery / current["receipt"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            assert receipt["backend"] == "vulkan", receipt
            assert receipt["adapter"] and receipt["adapter"] != "unknown", receipt
            assert receipt["driver"] and receipt["driver"] != "unknown", receipt
            assert any(
                entry["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
                for entry in receipt["files"]
            )
            receipts.add(receipt_path)
    assert len(receipts) == 4
    entry = {
        "replay": f"facade-backend/vulkan/{PROBE}",
        "golden": GOLDEN,
        "backend": "vulkan",
        "scope": SCOPE,
        "symbols": [symbol for symbol in symbols if symbol in SYMBOLS],
    }
    document = {"schema": "uzpainter/backend-tier0-trace/1", "replays": [entry]}
    if os.environ.get("UZP_UPDATE_BACKEND_TIER0_TRACE") == "1":
        TRACE.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        assert json.loads(TRACE.read_text(encoding="utf-8")) == document


def test_backend_manifest_matches_compared_export_trace() -> None:
    document = json.loads(TRACE.read_text(encoding="utf-8"))
    assert document["schema"] == "uzpainter/backend-tier0-trace/1"
    [trace] = document["replays"]
    assert trace == {
        "replay": f"facade-backend/vulkan/{PROBE}",
        "golden": GOLDEN,
        "backend": "vulkan",
        "scope": SCOPE,
        "symbols": SYMBOLS,
    }
    manifest = generate()
    entries = [entry for entry in manifest["entries"] if entry["context"] == "backend:vulkan"]
    assert sorted(entry["symbol"] for entry in entries) == trace["symbols"]
    for entry in entries:
        assert entry["status"] == "supported"
        assert entry["tier_evidence"] == [trace["golden"]]
        assert entry["notes"] == trace["scope"]
