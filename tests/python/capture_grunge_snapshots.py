"""Owner-machine capture of grunge and generator snapshots on the destination's own mesh
(decision 428: grunges and the three grunge-reading generators are served only from project-private
snapshots of the user's own Painter).

Not collected by default (no `test_` prefix). Run it explicitly, with the Assets3D Painter lock
held, no Painter running, and Legacy colour management (no `OCIO`, no `PAINTER_ACE_CONFIG`):

    python -m pytest tests/python/capture_grunge_snapshots.py -s

It builds `UzPainter.exe` into pytest's temporary folder and creates UzPainter's own project on the
authored plane (`parity/fixtures/meshes/plane.obj`) at 256 px, OpenGL, with four authored 16-bit
fixture bitmaps bound as its AO, Curvature, Position and World Space Normal mesh maps. It starts
Painter with `--enable-remote-scripting` and runs one `assets snapshot` with `usage` per capture
in `CAPTURES`: fixed and seeded grunges as fill sources, and the Dirt, Metal Edge Wear and Mask
Builder - Legacy generators in a mask, reading those mesh maps. The project is copied into the
private oracle store by hash; the printed summary holds hashes only. Requests, receipts and
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

from tools.parity.proc_generators.requests import GENERATOR_URLS
from tools.parity.proc_grunges.requests import GRUNGE_URLS
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.store.store import locate

ROOT = Path(__file__).resolve().parents[2]
PLANE = ROOT / "parity/fixtures/meshes/plane.obj"
BITMAPS = ROOT / "parity/fixtures/tier0-semantics/bitmaps"
RESOLUTION = 256
# Authored 256 px 16-bit fixtures bound as the destination's mesh maps, by usage.
MESH_MAPS = {
    "AO": BITMAPS / "grey-a.png",
    "Curvature": BITMAPS / "half-steps-grey.png",
    "Position": BITMAPS / "field-a.png",
    "WorldSpaceNormal": BITMAPS / "field-b.png",
}
# name -> (usage, resource URL, parameter overrides)
CAPTURES: dict[str, tuple[str, str, dict[str, Any]]] = {
    "rock": ("PROCEDURAL", GRUNGE_URLS["rock"], {}),
    "dirt-large": ("PROCEDURAL", GRUNGE_URLS["dirt-large"], {}),
    "dirt-a-seed-1": ("PROCEDURAL", GRUNGE_URLS["dirt-a"], {"$randomseed": 1}),
    "dirt-a-seed-2": ("PROCEDURAL", GRUNGE_URLS["dirt-a"], {"$randomseed": 2}),
    "dirt": ("GENERATOR", GENERATOR_URLS["Dirt"], {}),
    "dirt-seed-2": ("GENERATOR", GENERATOR_URLS["Dirt"], {"$randomseed": 2}),
    "metal-edge-wear": ("GENERATOR", GENERATOR_URLS["Metal Edge Wear"], {}),
    "mask-builder-legacy": ("GENERATOR", GENERATOR_URLS["Mask Builder - Legacy"], {}),
}


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


def create_script(project: Path) -> str:
    binds = "".join(
        f"identifier = resource.import_project_resource({str(path)!r}, "
        "resource.Usage.TEXTURE).identifier()\n"
        f"textureset.all_texture_sets()[0].set_mesh_map_resource("
        f"textureset.MeshMapUsage.{usage}, identifier)\n"
        for usage, path in MESH_MAPS.items()
    )
    return (
        "from substance_painter import project, resource, textureset\n"
        f"project.create({str(PLANE)!r}, "
        f"settings=project.Settings(default_texture_resolution={RESOLUTION}, "
        "normal_map_format=project.NormalMapFormat.OpenGL))\n"
        + binds
        + f"project.save_as({str(project)!r})\nproject.close()\n"
    )


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
    project = work / "grunge-snapshots.uzp"
    script = work / "create.py"
    script.write_text(create_script(project), encoding="utf-8")
    created = run([str(exe), "run", str(script)], 300)
    assert created.returncode == 0, created.stdout + created.stderr

    def capture(name: str, usage: str, resource: str, parameters: dict[str, Any]) -> dict[str, Any]:
        request = work / f"{name}.json"
        body = {"resource": resource, "parameters": parameters, "usage": usage}
        request.write_text(json.dumps(body), encoding="utf-8")
        result = run(
            [str(exe), "assets", "snapshot", str(project), "--request", str(request)], 1800
        )
        report = report_of(result)
        assert result.returncode == 0 and report["status"] == "ok", f"{name}: {report}"
        receipt = Path(report["receipt"])
        return {
            "report": report,
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "receipt_size": receipt.stat().st_size,
            "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest(),
        }

    launcher = PainterLauncher()
    launcher.start({"OCIO": None, "PAINTER_ACE_CONFIG": None})
    try:
        captured = {
            name: capture(name, usage, resource, parameters)
            for name, (usage, resource, parameters) in CAPTURES.items()
        }
    finally:
        launcher.stop()
    digest = hashlib.sha256(project.read_bytes()).hexdigest()
    size = store.put_blob(project, digest)
    summary = {
        "project": {"record_id": "grunge-snapshots-project", "sha256": digest, "size_bytes": size},
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "captures": {
            name: {
                "signature_sha256": item["report"]["signature_sha256"],
                "request_sha256": item["request_sha256"],
                "receipt": [item["receipt_sha256"], item["receipt_size"]],
                "revision": item["report"]["revision"],
            }
            for name, item in captured.items()
        },
    }
    print("UZP_CAPTURE_SUMMARY:" + json.dumps(summary, sort_keys=True))
