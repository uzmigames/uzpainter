"""Recorder jobs resolve Assets3D inputs by path and SHA-256 (decision 099), and the Wand kernel
probe's request (`wand_kernel_probe.py`) is current and loads as a kernel export job."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import ASSETS3D_LICENCE, job_from_manifest, load_job
from tools.parity.recorder.session import RecorderError
from tools.parity.tier0_semantics import wand_kernel_probe as probe

ASSETS3D = Path(r"E:\UzmiGames\Assets3D")


def manifest(sha: str) -> dict[str, Any]:
    request = probe.request()
    (mesh,) = [r for r in request["inputs"] if r["input_id"] == probe.MESH]
    mesh.update(assets3d_path="meshes/wand.obj", sha256=sha)
    return request


def test_an_assets3d_input_resolves_under_the_root_when_its_hash_matches(tmp_path: Path) -> None:
    data = b"o wand\nv 0 0 0\n"
    (tmp_path / "meshes").mkdir()
    (tmp_path / "meshes" / "wand.obj").write_bytes(data)
    job = job_from_manifest(manifest(hashlib.sha256(data).hexdigest()), assets_root=tmp_path)
    assert job.inputs[probe.MESH] == tmp_path / "meshes" / "wand.obj"
    assert len(job.exports) == 4


def test_an_assets3d_input_with_another_hash_is_refused(tmp_path: Path) -> None:
    (tmp_path / "meshes").mkdir()
    (tmp_path / "meshes" / "wand.obj").write_bytes(b"changed")
    with pytest.raises(RecorderError, match="not the pinned one"):
        job_from_manifest(manifest("0" * 64), assets_root=tmp_path)


def test_a_repository_input_is_never_resolved_as_an_assets3d_one(tmp_path: Path) -> None:
    request = manifest("0" * 64)
    (mesh,) = [r for r in request["inputs"] if r["input_id"] == probe.MESH]
    mesh["provenance"] = {"origin": "uzmigames_authored", "licence": "Apache-2.0"}
    with pytest.raises(RecorderError, match="not an Assets3D input"):
        job_from_manifest(request, assets_root=tmp_path)


def test_without_a_root_a_texture_job_refuses_its_assets3d_mesh() -> None:
    with pytest.raises(RecorderError, match="`mesh` must name an input with a path"):
        job_from_manifest(manifest("0" * 64))


def test_the_wand_kernel_request_is_current() -> None:
    stored = json.loads(probe.request_path().read_text(encoding="utf-8"))
    assert stored == probe.request()
    (mesh,) = [r for r in stored["inputs"] if r["input_id"] == probe.MESH]
    assert mesh["provenance"]["licence"] == ASSETS3D_LICENCE and "path" not in mesh
    create = stored["instruction_sequence"]["steps"][0]["args"]
    assert create["mesh"] == probe.MESH and create["default_texture_resolution"] == 2048


@pytest.mark.skipif(
    not (ASSETS3D / "AGENTS.md").is_file(), reason=f"the asset repository is not at {ASSETS3D}"
)
def test_the_wand_kernel_request_loads_with_the_asset_repository() -> None:
    job = load_job(probe.request_path(), assets_root=ASSETS3D)
    (mesh,) = [r for r in probe.request()["inputs"] if r["input_id"] == probe.MESH]
    assert hashlib.sha256(job.inputs[probe.MESH].read_bytes()).hexdigest() == mesh["sha256"]
    assert len(job.inputs) == 9 and len(job.exports) == 4
