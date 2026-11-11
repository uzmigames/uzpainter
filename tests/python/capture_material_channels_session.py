"""Owner-machine capture and recording of one Painter session for item 2.16 of
`phase3.3_procedural-families` (decision 431: a composite over a snapshot is compared with a
recording made in the Painter session that captured it).

Not collected by default (no `test_` prefix). Run it explicitly, with the Assets3D Painter lock and
the native lock held, no Painter running, and Legacy colour management:

    python -m pytest tests/python/capture_material_channels_session.py -s

It builds `UzPainter.exe`, creates one UzPainter project per material on the authored plane at
128 px, OpenGL, and starts Painter with `--enable-remote-scripting`. In that one Painter session it
captures, with `assets snapshot` and the `MATERIAL` usage, felt and leather grain at their defaults
and at their first preset (named in Painter's own preset list, read from the defaults capture's
private receipt), each material into its own project, then records the Tier 0 requests
`material-channels-*` (`tools/parity/tier0_semantics/material_channels.py`) into the oracle inbox,
and reads which parameters a colour edit changes, by value (`material_channel_survey.colour_values`,
private). Each project is copied into the private oracle store by hash (records
`material-channels-<family>-project`). The printed summary holds hashes, signatures and inbox run
paths only. Admit each run with `python -m tools.parity.store record <manifest> --run <run>`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.material_channel_survey import colour_values
from tools.parity.recorder.material_survey import MATERIAL_URLS
from tools.parity.recorder.output import work_root
from tools.parity.recorder.session import REMOTE_HOST, REMOTE_PORT, HttpTransport, PainterSession
from tools.parity.store.store import locate
from tools.parity.tier0_semantics.material_channels import requests

ROOT = Path(__file__).resolve().parents[2]
PLANE = ROOT / "parity/fixtures/meshes/plane.obj"
RESOLUTION = 128
RECORD_ID = "material-channels-{family}-project"
STARTUP_IDLE_S = 90


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


def test_capture_and_record_in_one_session(tmp_path_factory: pytest.TempPathFactory) -> None:
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
    projects = {family: work / f"material-channels-{family}.uzp" for family in MATERIAL_URLS}
    for family, project in projects.items():
        script = work / f"create-{family}.py"
        script.write_text(
            "from substance_painter import project\n"
            f"project.create({str(PLANE)!r}, "
            f"settings=project.Settings(default_texture_resolution={RESOLUTION}, "
            "normal_map_format=project.NormalMapFormat.OpenGL))\n"
            f"project.save_as({str(project)!r})\nproject.close()\n",
            encoding="utf-8",
        )
        created = run([str(exe), "run", str(script)], 300)
        assert created.returncode == 0, created.stdout + created.stderr
    root = manifest_root(current_envelope()).parent / "requests/tier0/api-probes"

    def capture(name: str, project: Path, resource: str, preset: str | None) -> dict[str, Any]:
        request = work / f"{name}.json"
        body: dict[str, Any] = {
            "resource": resource,
            "parameters": {},
            "preset": preset,
            "inputs": {},
            "usage": "MATERIAL",
        }
        request.write_text(json.dumps(body), encoding="utf-8")
        result = run(
            [str(exe), "assets", "snapshot", str(project), "--request", str(request)], 1800
        )
        report = report_of(result)
        assert result.returncode == 0 and report["status"] == "ok", f"{name}: {report}"
        receipt = Path(report["receipt"])
        return {
            "report": report,
            "receipt": receipt,
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest(),
        }

    captured: dict[str, dict[str, Any]] = {}
    runs: dict[str, list[str]] = {}
    launcher = PainterLauncher()
    launcher.start({"OCIO": None, "PAINTER_ACE_CONFIG": None})
    try:
        # Painter's startup shelf crawl ends before any capture asks for a refresh (as in
        # capture_grunge_snapshots.capture_session). On 2026-11-11 Painter raised an uncaught
        # "bad allocation" when called during its startup crawl; it is left idle first.
        time.sleep(STARTUP_IDLE_S)
        session = PainterSession(HttpTransport(REMOTE_HOST, REMOTE_PORT))
        session.connect()
        session.wait_catalog_ready(600)
        for family, url in MATERIAL_URLS.items():
            captured[family] = capture(family, projects[family], url, None)
            receipt = json.loads(captured[family]["receipt"].read_text(encoding="utf-8"))
            presets = receipt["readback"]["sources"][0]["presets"]
            assert presets, f"{family}: no preset to hold out"
            captured[family + "-preset"] = capture(
                family + "-preset", projects[family], url, presets[0]
            )
        for name in requests():
            recorded = run(
                [
                    sys.executable,
                    "-m",
                    "tools.parity.recorder",
                    "record",
                    str(root / f"{name}.json"),
                ],
                3000,
            )
            assert recorded.returncode == 0, f"{name}: " + recorded.stdout + recorded.stderr
            runs[name] = [x for x in recorded.stdout.splitlines() if "recorded: " in x]
        values = colour_values(session)
    finally:
        launcher.stop()
    private = work_root() / "material-channels-session"
    private.mkdir(parents=True, exist_ok=True)
    data = json.dumps(values, indent=1, sort_keys=True).encode("utf-8")
    (private / "colour-values.json").write_bytes(data)
    stored: dict[str, Any] = {}
    for family, project in projects.items():
        digest = hashlib.sha256(project.read_bytes()).hexdigest()
        size = store.put_blob(project, digest)
        stored[family] = {
            "record_id": RECORD_ID.format(family=family),
            "sha256": digest,
            "size_bytes": size,
        }
    summary = {
        "projects": stored,
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "captures": {
            name: {
                "signatures": item["report"]["signatures"],
                "request_sha256": item["request_sha256"],
                "receipt": [item["receipt_sha256"], item["receipt"].stat().st_size],
                "revision": item["report"]["revision"],
            }
            for name, item in captured.items()
        },
        "recorded": runs,
        "colour_values": {
            "private": str(private / "colour-values.json"),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    print("UZP_CAPTURE_SUMMARY:" + json.dumps(summary, sort_keys=True))
