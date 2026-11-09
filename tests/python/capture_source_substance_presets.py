"""Owner-machine capture of the decision-412 starter material into a private snapshot project.

Not collected by default (no `test_` prefix). Run it explicitly, with the Assets3D Painter lock
held, no Painter running, and Legacy colour management (no `OCIO`, no `PAINTER_ACE_CONFIG`):

    python -m pytest tests/python/capture_source_substance_presets.py -s

It builds `UzPainter.exe` into pytest's temporary folder, creates UzPainter's own plane project
(the shipped full-UV plane, 128 px, OpenGL), starts Painter with `--enable-remote-scripting`, and
runs one multi-output `assets snapshot` (decision 413) per state the
`source-substance-presets-inputs` probe reaches: the defaults, the first preset, and that preset
with the first image input set to the authored colour, to the `grey-a` fixture, and removed. The
preset and input names are read from Painter's own lists in the first capture's receipt; nothing
about the asset is authored beyond its URL (decision 412 §1). The resulting project is copied into
the private oracle store by hash; the printed summary holds hashes only. Requests, receipts and
exports stay under `%LOCALAPPDATA%/UzPainter/snapshot-recordings/`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.store.store import locate
from tools.parity.tier0_semantics.source_substance_presets import INPUT_COLOR, RESOURCE_URL

ROOT = Path(__file__).resolve().parents[2]
PLANE = ROOT / "parity/fixtures/meshes/plane.obj"
GREY_A = ROOT / "parity/fixtures/tier0-semantics/bitmaps/grey-a.png"


def run(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def report_of(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    lines = [line for line in result.stdout.splitlines() if line.startswith("UZP_JSON:")]
    assert len(lines) == 1, result.stdout + result.stderr
    report: dict[str, Any] = json.loads(lines[0].removeprefix("UZP_JSON:"))
    return report


def test_capture(tmp_path_factory: pytest.TempPathFactory) -> None:
    if os.environ.get("OCIO") or os.environ.get("PAINTER_ACE_CONFIG"):
        pytest.fail("the capture runs Painter under Legacy colour management", pytrace=False)
    store = locate()
    if store is None:
        pytest.skip("oracle_unavailable: no private store on this machine")
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH")
    prefix = tmp_path_factory.mktemp("painter")
    build = run([zig, "build", "painter", "--prefix", str(prefix)], 3600)
    assert build.returncode == 0, build.stdout + build.stderr
    exe = prefix / "bin" / "UzPainter.exe"
    work = tmp_path_factory.mktemp("capture")
    project = work / "source-substance-presets-inputs.uzp"
    script = work / "create.py"
    script.write_text(
        "from substance_painter import project\n"
        f"project.create({str(PLANE)!r}, "
        "settings=project.Settings(default_texture_resolution=128, "
        "normal_map_format=project.NormalMapFormat.OpenGL))\n"
        f"project.save_as({str(project)!r})\nproject.close()\n",
        encoding="utf-8",
    )
    created = run([str(exe), "run", str(script)], 300)
    assert created.returncode == 0, created.stdout + created.stderr

    def capture(name: str, preset: str | None, inputs: dict[str, Any]) -> dict[str, Any]:
        request = work / f"{name}.json"
        body = {"resource": RESOURCE_URL, "parameters": {}, "preset": preset, "inputs": inputs}
        request.write_text(json.dumps(body), encoding="utf-8")
        result = run(
            [str(exe), "assets", "snapshot", str(project), "--request", str(request)], 1800
        )
        report = report_of(result)
        assert result.returncode == 0 and report["status"] == "ok", f"{name}: {report}"
        receipt = Path(report["receipt"])
        return {
            "report": report,
            "receipt": json.loads(receipt.read_text(encoding="utf-8")),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest(),
        }

    launcher = PainterLauncher()
    launcher.start({"OCIO": None, "PAINTER_ACE_CONFIG": None})
    try:
        captured = {"defaults": capture("defaults", None, {})}
        source = captured["defaults"]["receipt"]["readback"]["sources"][0]
        preset = source["presets"][0]
        image_input = source["inputs"][0]
        captured["preset"] = capture("preset", preset, {})
        captured["preset-color"] = capture(
            "preset-color", preset, {image_input: {"color": INPUT_COLOR}}
        )
        bitmap = {image_input: {"bitmap": str(GREY_A)}}
        captured["preset-bitmap"] = capture("preset-bitmap", preset, bitmap)
        captured["preset-removed"] = capture(
            "preset-removed", preset, {image_input: {"remove": True}}
        )
    finally:
        launcher.stop()
    digest = hashlib.sha256(project.read_bytes()).hexdigest()
    size = store.put_blob(project, digest)
    summary = {
        "project": {
            "record_id": "source-substance-presets-inputs-project",
            "sha256": digest,
            "size_bytes": size,
        },
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "states": {
            name: {
                "signatures": item["report"]["signatures"],
                "request_sha256": item["request_sha256"],
                "receipt_sha256": item["receipt_sha256"],
                "revision": item["report"]["revision"],
            }
            for name, item in captured.items()
        },
    }
    print("UZP_CAPTURE_SUMMARY:" + json.dumps(summary, sort_keys=True))
