"""Installed snapshot command preflight: no Painter process is needed or contacted."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_snapshot_usage_and_fixed_shipped_bridge(painter_bin: Path) -> None:
    result = subprocess.run(
        [str(painter_bin / "UzPainter.exe"), "assets", "snapshot"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "--request" in result.stderr
    assert (painter_bin / "python/uzpainter_snapshot/painter_side.py").is_file()
    assert (painter_bin / "assets/snapshot/plane.obj").read_bytes() == (
        ROOT / "parity/fixtures/meshes/plane.obj"
    ).read_bytes()


@pytest.mark.parametrize("changed_mesh", [False, True])
def test_snapshot_preflight_preserves_project(
    painter_bin: Path,
    tmp_path: Path,
    changed_mesh: bool,
) -> None:
    exe = painter_bin / "UzPainter.exe"
    mesh = tmp_path / "authored plane.obj"
    mesh.write_bytes(
        (ROOT / "parity/fixtures/meshes/plane.obj").read_bytes()
        + (b"\n# authored changed mesh identity\n" if changed_mesh else b"")
    )
    project = tmp_path / "private project.uzp"
    script = tmp_path / "create.py"
    script.write_text(
        "from substance_painter import project\n"
        f"project.create({str(mesh)!r}, "
        "settings=project.Settings(default_texture_resolution=128))\n"
        f"project.save_as({str(project)!r})\nproject.close()\n",
        encoding="utf-8",
    )
    created = subprocess.run(
        [str(exe), "run", str(script)], capture_output=True, text=True, timeout=120, check=False
    )
    assert created.returncode == 0, created.stdout + created.stderr
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"resource": "resource://authored/unpinned", "parameters": {}}))
    before = hashlib.sha256(project.read_bytes()).hexdigest()
    result = subprocess.run(
        [str(exe), "assets", "snapshot", str(project), "--request", str(request)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    report = json.loads(result.stdout.removeprefix("UZP_JSON:"))
    assert ("exact shipped full-UV plane" if changed_mesh else "versioned ResourceID") in report[
        "error"
    ]
    assert hashlib.sha256(project.read_bytes()).hexdigest() == before
