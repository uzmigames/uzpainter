"""Real client/runner/host coverage, called with the native guard suite's painter fixture."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d import client, gate_contract
from tests.python.conftest import PLANE
from tests.python.test_pyapi_cli import cli, script


def write_json(path: Path, value: Any) -> str:
    raw = json.dumps(value).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def request_for(root: Path, mesh: Path, report: dict[str, Any]) -> Path:
    """Authored prerequisites; no real asset or owner approval is represented."""
    proof = root / "proof.json"
    write_json(proof, {"inspection": True, "low_high_fidelity": {"pass": True}})
    manifest: dict[str, Any] = {
        "schema": 1,
        "type": "piece-manifest",
        "files": {},
        "meshes": {"low": {"file": "mesh"}},
        "gates": {"technical": {}, "visual": {}, "user": {}},
        "invalidations": [],
    }
    for key, path in (("mesh", mesh), ("proof", proof)):
        raw = path.read_bytes()
        manifest["files"][key] = {
            "path": path.name,
            "bytes": len(raw),
            "sha256": {
                "algorithm": "sha256",
                "verification": "verified",
                "value": hashlib.sha256(raw).hexdigest(),
            },
        }
    requirements: dict[str, list[str]] = {}
    for role, stages in gate_contract.ROLES.items():
        requirements[role] = []
        for reviewer in ("producer", "independent"):
            key = role + "-" + reviewer
            refs = [{"file": "proof", "selector": "/inspection"}]
            if role == "low_high_fidelity":
                refs.append({"file": "proof", "selector": "/low_high_fidelity"})
            manifest["gates"]["technical"][key] = {
                "state": "pass",
                "applicability": "confirmed",
                "stages": sorted(stages),
                "scope": role,
                "moment": "2026-10-25T12:00:00Z",
                "reviewer": {
                    "role": reviewer,
                    "agent": reviewer,
                    "session": reviewer + "-session",
                    "model": "authored-fixture",
                },
                "evidence": refs,
                "dependencies": [
                    {"target": "/meshes/low", "verification": "equal", "evidence": refs}
                ],
            }
            requirements[role].append("/gates/technical/" + key)
    request = {
        "schema": gate_contract.SCHEMA,
        "root": str(root),
        "requirements": requirements,
        "manifest": {
            "path": "manifest.json",
            "sha256": write_json(root / "manifest.json", manifest),
        },
        "import_report": {
            "path": "import.json",
            "sha256": write_json(root / "import.json", report),
        },
    }
    path = root / "request.json"
    write_json(path, request)
    return path


def diagnostic_session(
    painter: Path,
    root: Path,
    mesh: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], Path, int]:
    """Create/save through the actual adapter and return its unmodified native import report."""
    store = root / "diagnostic.uzp"
    for key, value in {
        client.PAINTER_ENV: str(painter),
        client.IMPORT_DIAGNOSTIC_ENV: "1",
        client.SESSION_ENV: str(root / "session.json"),
        client.SCRATCH_ENV: str(root),
        "UZP_ASSETS3D_ROOT": str(root),
    }.items():
        monkeypatch.setenv(key, value)
    for key in (client.PRODUCTION_ENV, client.DIAGNOSTIC_ENV, "UZP_ASSETS3D_OPEN_REDIRECTS"):
        monkeypatch.delenv(key, raising=False)
    reply, status = client.execute_python(f"""
import uzpainter
from substance_painter import project
project.create({str(mesh)!r})
project.save_as({str(store)!r})
result = {{
    "report": uzpainter.project.dump_recipe()["recipe"]["mesh"]["import_report"],
    "revision": uzpainter.project.revision(),
    "guard": uzpainter._assets3d_production_status(),
}}
""")
    assert status == client.OK, reply
    assert reply["diagnostic"] == "diagnostic-import" and "production_guard" not in reply
    assert reply["data"]["guard"]["mode"] == "absent"
    report: dict[str, Any] = reply["data"]["report"]
    revision: int = reply["data"]["revision"]
    assert report["source"]["sha256"] == hashlib.sha256(mesh.read_bytes()).hexdigest()
    assert report["source"]["size"] == len(mesh.read_bytes())
    return report, store, revision


def persisted_state(store: Path) -> tuple[bytes, int]:
    """Read the closed store's actual current revision without opening a native session."""
    connection = sqlite3.connect(store.as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT revision FROM checkpoint WHERE name = 'current'"
        ).fetchone()
        assert row is not None
        revision = int(row[0])
    finally:
        connection.close()
    return store.read_bytes(), revision


def check_refused_round(
    painter: Path,
    root: Path,
    mesh: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failed_gate: bool,
) -> None:
    """A real saved session exists, but failed prerequisites never launch or restore it."""
    report, store, revision = diagnostic_session(painter, root, mesh, monkeypatch)
    if failed_gate:
        assert report["certificate"]["status"] in {"pass", "warn"}
    else:
        assert report["certificate"]["status"] == "fail"
        assert report["certificate"]["corners"]["zero_normals"] > 0
    request_path = request_for(root, mesh, report)
    if failed_gate:
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["gates"]["technical"]["bake-producer"]["state"] = "fail"
        request = json.loads(request_path.read_bytes())
        request["manifest"]["sha256"] = write_json(manifest_path, manifest)
        write_json(request_path, request)
    assert json.loads((root / "import.json").read_bytes()) == report
    monkeypatch.delenv(client.IMPORT_DIAGNOSTIC_ENV)
    monkeypatch.setenv(client.PRODUCTION_ENV, str(request_path))
    before = persisted_state(store)
    assert before[1] == revision
    files = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    calls: list[list[str]] = []
    original_run = client.run_painter

    def observed_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return original_run(argv)

    monkeypatch.setattr(client, "run_painter", observed_run)
    sentinel = root / "script-executed.txt"
    match = "upstream gate" if failed_gate else "mesh certificate is fail"
    with pytest.raises(client.HostError, match=match):
        client.execute_python(f"""
from pathlib import Path
from uzpainter import project
Path({str(sentinel)!r}).write_text("script ran", encoding="utf-8")
project.Metadata("must-not-run").set("mutation", True)
project.save()
""")
    assert calls == []  # Not even a capability probe: no runner, restore, script or save.
    assert not sentinel.exists()
    assert persisted_state(store) == before
    assert {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()} == files


def check_warn_diagnostic_round(
    painter: Path,
    root: Path,
    mesh: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely warned import can run only here as an explicitly marked diagnostic."""
    report, store, revision = diagnostic_session(painter, root, mesh, monkeypatch)
    assert report["certificate"]["status"] == "warn"
    assert report["certificate"]["faces"]["ngons_triangulated"] > 0
    assert persisted_state(store)[1] == revision
    sentinel = root / "diagnostic-executed.txt"
    reply, status = client.execute_python(f"""
from pathlib import Path
from uzpainter import project
Path({str(sentinel)!r}).write_text("diagnostic ran", encoding="utf-8")
before = project.revision()
project.Metadata("diagnostic-proof").set("ran", True)
project.save()
result = {{"before": before, "after": project.revision(),
          "report": project.dump_recipe()["recipe"]["mesh"]["import_report"]}}
""")
    assert status == client.OK, reply
    assert reply["diagnostic"] == "diagnostic-import" and "production_guard" not in reply
    assert reply["data"]["report"] == report
    assert reply["data"]["before"] == revision
    assert reply["data"]["after"] == revision + 1
    assert persisted_state(store)[1] == revision + 1
    assert sentinel.read_text(encoding="utf-8") == "diagnostic ran"
    assert not list(root.glob("uzp-a3d-*"))


def check_production_round(painter: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create, carried same-mesh reload and refused wrong-mesh reload without a commit/write."""
    mesh = tmp_path / "low.obj"
    mesh.write_bytes(PLANE.read_bytes())
    seed = script(
        tmp_path,
        f"""
        import uzpainter
        from substance_painter import project
        project.create({str(mesh)!r})
        result = uzpainter.project.dump_recipe()["recipe"]["mesh"]["import_report"]
        project.close()
    """,
    )
    status, documents, stderr = cli(painter, "run", seed)
    assert status == 0 and len(documents) == 1, (documents, stderr)
    report = documents[0]["result"]
    assert report["certificate"]["status"] in {"pass", "warn"}
    request = request_for(tmp_path, mesh, report)
    session = tmp_path / "session.json"
    store = tmp_path / "admitted.uzp"
    for key, value in {
        client.PAINTER_ENV: str(painter),
        client.PRODUCTION_ENV: str(request),
        client.SESSION_ENV: str(session),
        client.SCRATCH_ENV: str(tmp_path),
        "UZP_ASSETS3D_ROOT": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    for key in (client.IMPORT_DIAGNOSTIC_ENV, client.DIAGNOSTIC_ENV, "UZP_ASSETS3D_OPEN_REDIRECTS"):
        monkeypatch.delenv(key, raising=False)
    reply, status = client.execute_python(f"""
import uzpainter
from substance_painter import project
project.create({str(mesh)!r})
project.save_as({str(store)!r})
result = {{"revision": uzpainter.project.revision(), "open": project.is_open()}}
""")
    assert status == client.OK, reply
    assert reply["data"]["open"] is True
    assert reply["production_guard"]["mode"] == "armed" and "diagnostic" not in reply
    revision = reply["data"]["revision"]
    reply, status = client.execute_python(f"""
from uzpainter import project
before = project.revision()
reload = project.reload_mesh({str(mesh)!r})
project.save()
result = {{"before": before, "after": project.revision(), "reload_status": reload.status}}
""")
    assert status == client.OK, reply
    assert reply["data"]["before"] == revision
    assert reply["data"]["reload_status"] in {"committed", "no_op"}
    assert reply["data"]["after"] == revision + (reply["data"]["reload_status"] == "committed")
    assert reply["production_guard"]["mode"] == "armed" and "diagnostic" not in reply
    before = store.read_bytes()
    revision = reply["data"]["after"]
    wrong = tmp_path / "wrong.obj"
    wrong.write_bytes(mesh.read_bytes() + b"\n# different admitted-source bytes\n")
    reply, status = client.execute_python(f"""
import uzpainter
from uzpainter import project
before = project.revision()
try:
    project.reload_mesh({str(wrong)!r})
    refusal = None
except uzpainter.Assets3DProductionError as error:
    refusal = str(error)
result = {{"refusal": refusal, "before": before, "after": project.revision()}}
""")
    assert status == client.OK, reply
    assert "not the admitted source" in reply["data"]["refusal"]
    assert reply["data"]["before"] == reply["data"]["after"] == revision
    assert store.read_bytes() == before
    assert (
        reply["production_guard"]["request_sha256"]
        == hashlib.sha256(request.read_bytes()).hexdigest()
    )
    assert not list(tmp_path.glob("uzp-a3d-*"))
