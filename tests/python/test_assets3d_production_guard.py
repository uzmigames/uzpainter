"""The native Assets3D production guard (phase3.1_assets3d-cutover QG-02/M11, decision 360).

Every case drives a fresh `UzPainter.exe` (`zig build painter -j4`). The admitted report comes from
a genuine native import of the same bytes, a run without the guard
(`project.dump_recipe()["recipe"]["mesh"]["import_report"]`), never from a computed copy. No GPU
is used.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import PLANE
from tests.python.test_pyapi_cli import cli, script
from tools.parity.schemas import REPO_ROOT

# An authored quad whose normals are zero: its certificate is `fail` (12-mesh-import.md §4).
ZERO_NORMAL_OBJ = """o authored_zero_normals
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0.1 0.1
vt 0.9 0.1
vt 0.9 0.9
vt 0.1 0.9
vn 0 0 0
usemtl authored
f 1/1/1 2/2/1 3/3/1 4/4/1
"""
# A second authored mesh with valid normals: not the admitted source.
OTHER_OBJ = """o authored_other
v 0 0 0
v 2 0 0
v 2 2 0
v 0 2 0
vt 0.1 0.1
vt 0.9 0.1
vt 0.9 0.9
vt 0.1 0.9
vn 0 0 1
usemtl authored
f 1/1/1 2/2/1 3/3/1 4/4/1
"""


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter -j4` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "-j4", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "UzPainter.exe"


def admitted_report(painter: Path, tmp_path: Path, mesh: Path) -> dict[str, Any]:
    """The genuine native import report of `mesh`, from a run without the guard."""
    path = script(
        tmp_path,
        f"""
        import uzpainter
        from uzpainter import project
        status = uzpainter._assets3d_production_status()
        project.create({mesh.as_posix()!r})
        report = project.dump_recipe()["recipe"]["mesh"]["import_report"]
        project.close()
        result = {{"status": status, "report": report}}
        """,
    )
    status, [document], stderr = cli(painter, "run", path)
    assert status == 0, stderr + json.dumps(document)
    assert document["result"]["status"] == {
        "schema": "uzpainter/assets3d-production-status/1",
        "mode": "absent",
        "policy_installed": False,
        "request_sha256": None,
        "source_sha256": None,
    }
    report: dict[str, Any] = document["result"]["report"]
    return report


def pin(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def policy(tmp_path: Path, mesh: Path, report: dict[str, Any]) -> tuple[str, Path]:
    """An authored policy for `mesh`; returns its JSON and the pinned request file."""
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"authored": "production round"}), encoding="utf-8")
    report_file = tmp_path / "import-report.json"
    report_file.write_text(json.dumps(report), encoding="utf-8")
    data = mesh.read_bytes()
    document = {
        "schema": "uzpainter/assets3d-native-policy/1",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_size": len(data),
        "import_report": report,
        "request_sha256": pin(request)["sha256"],
        "pins": [pin(request), pin(report_file), pin(mesh)],
    }
    return json.dumps(document), request


def production(painter: Path, tmp_path: Path, body: str, *args: str) -> dict[str, Any]:
    path = script(tmp_path, "import uzpainter\nfrom uzpainter import project\n" + body)
    status, [document], stderr = cli(
        painter, "run", path, "--assets3d-production-required", "--", *args
    )
    assert status == 0, stderr + json.dumps(document)
    result: dict[str, Any] = document["result"]
    return result


def test_runtime_capability_and_flag_usage(painter: Path, tmp_path: Path) -> None:
    status, documents, _ = cli(painter, "capabilities", "--runtime")
    assert (status, documents) == (
        0,
        [{"schema": "uzpainter/runtime-capabilities/1", "assets3d_production_guard": 1}],
    )
    status, documents, stderr = cli(painter, "capabilities", "--other")
    assert (status, documents) == (2, []) and "usage: UzPainter.exe capabilities" in stderr
    path = script(tmp_path, "result = True\n")
    for args in (
        ("--assets3d-production-required", "--diagnostic-measure-export"),
        ("--assets3d-production-required", "--assets3d-production-required"),
    ):
        status, documents, stderr = cli(painter, "run", path, *args)
        assert (status, documents) == (2, []), stderr


def test_genuine_admitted_round_and_refusals(painter: Path, tmp_path: Path) -> None:
    report = admitted_report(painter, tmp_path, PLANE)
    assert report["certificate"]["status"] != "fail"
    text, request = policy(tmp_path, PLANE, report)
    other = tmp_path / "other.obj"
    other.write_text(OTHER_OBJ, encoding="utf-8")
    empty_bundle = tmp_path / "bundle-dir"
    empty_bundle.mkdir()
    result = production(
        painter,
        tmp_path,
        f"""
import sys
plane, other, bundle, work = sys.argv[1:5]
def refused(call, *args):
    try:
        call(*args)
    except uzpainter.Assets3DProductionError as error:
        return str(error)
    return None
out = {{"required": uzpainter._assets3d_production_status()}}
out["create_uninstalled"] = refused(project.create, plane)
out["open_after_refusal"] = project.is_open()
out["bad_policy"] = refused(uzpainter._assets3d_install_production_policy, '{{"schema": "other"}}')
uzpainter._assets3d_install_production_policy({text!r})
out["armed"] = uzpainter._assets3d_production_status()
out["reinstall"] = refused(uzpainter._assets3d_install_production_policy, {text!r})
out["create_other"] = refused(project.create, other)
out["open_after_other"] = project.is_open()
project.create(plane)
before = project.revision()
from uzpainter import layerstack as ls, textureset as ts
ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
out["mutated"] = project.revision() == before + 1
project.save_as(work + "/admitted.uzp")
out["revert"] = refused(project.revert, before)
project.close()
project.open(work + "/admitted.uzp")
out["reopened"] = project.is_open()
project.close()
out["bundle_open"] = refused(project.open, bundle)
out["after"] = uzpainter._assets3d_production_status()
result = out
""",
        str(PLANE),
        str(other),
        str(empty_bundle),
        str(tmp_path),
    )
    assert result["required"]["mode"] == "required" and not result["required"]["policy_installed"]
    assert "no production policy is installed" in result["create_uninstalled"]
    assert result["open_after_refusal"] is False
    assert "policy schema" in result["bad_policy"]
    assert result["armed"]["mode"] == "armed" and result["armed"]["policy_installed"] is True
    assert result["armed"]["request_sha256"] == pin(request)["sha256"]
    assert result["armed"]["source_sha256"] == hashlib.sha256(PLANE.read_bytes()).hexdigest()
    assert "cannot be replaced" in result["reinstall"]
    assert "not the admitted source" in result["create_other"]
    assert result["open_after_other"] is False
    assert result["mutated"] is True
    assert "revert() is refused in production" in result["revert"]
    assert result["reopened"] is True
    assert "bundle directory" in result["bundle_open"]
    assert result["after"] == result["armed"]


def test_certificate_fail_refuses_before_any_store(painter: Path, tmp_path: Path) -> None:
    mesh = tmp_path / "zero-normals.obj"
    mesh.write_text(ZERO_NORMAL_OBJ, encoding="utf-8")
    report = admitted_report(painter, tmp_path, mesh)
    assert report["certificate"]["status"] == "fail"
    text, _ = policy(tmp_path, mesh, report)
    result = production(
        painter,
        tmp_path,
        f"""
import sys
uzpainter._assets3d_install_production_policy({text!r})
try:
    project.create(sys.argv[1])
    outcome = None
except uzpainter.Assets3DProductionError as error:
    outcome = str(error)
result = {{"refusal": outcome, "open": project.is_open()}}
""",
        str(mesh),
    )
    assert "certificate is fail" in result["refusal"] and result["open"] is False


def test_changed_pin_refuses_the_next_boundary(painter: Path, tmp_path: Path) -> None:
    report = admitted_report(painter, tmp_path, PLANE)
    text, request = policy(tmp_path, PLANE, report)
    result = production(
        painter,
        tmp_path,
        f"""
import sys
from pathlib import Path
uzpainter._assets3d_install_production_policy({text!r})
project.create(sys.argv[1])
revision = project.revision()
Path(sys.argv[2]).write_text("changed after the preflight", encoding="utf-8")
from uzpainter import layerstack as ls, textureset as ts
try:
    ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
    outcome = None
except uzpainter.Assets3DProductionError as error:
    outcome = str(error)
result = {{"refusal": outcome, "unchanged": project.revision() == revision}}
project.close()
""",
        str(PLANE),
        str(request),
    )
    assert "changed since the preflight" in result["refusal"] and result["unchanged"] is True


def test_runs_without_the_flag_are_unchanged(painter: Path, tmp_path: Path) -> None:
    """Outside production the guard is absent: no policy arms it and every route works."""
    path = script(
        tmp_path,
        f"""
        import uzpainter
        from uzpainter import project
        try:
            uzpainter._assets3d_install_production_policy("{{}}")
            install = None
        except uzpainter.Assets3DProductionError as error:
            install = str(error)
        project.create({PLANE.as_posix()!r})
        before = project.revision()
        from uzpainter import layerstack as ls, textureset as ts
        ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
        project.revert(before)
        result = {{"install": install, "reverted": project.revision() == before + 2,
                   "status": uzpainter._assets3d_production_status()["mode"]}}
        project.close()
        """,
    )
    status, [document], stderr = cli(painter, "run", path)
    assert status == 0, stderr + json.dumps(document)
    result = document["result"]
    assert result["status"] == "absent" and result["reverted"] is True
    assert "policy" in result["install"]


def test_reload_rebuild_and_report_routes(painter: Path, tmp_path: Path) -> None:
    """Reload of another mesh, rebuild of another project and a policy whose report differs from
    the genuine import are refused before anything is staged or a store exists."""
    report = admitted_report(painter, tmp_path, PLANE)
    other = tmp_path / "other.obj"
    other.write_text(OTHER_OBJ, encoding="utf-8")
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / (hashlib.sha256(other.read_bytes()).hexdigest() + ".obj")).write_bytes(
        other.read_bytes()
    )
    path = script(
        tmp_path,
        f"""
        from uzpainter import project
        project.create({other.as_posix()!r})
        dump = project.dump_recipe()
        project.close()
        result = dump
        """,
    )
    status, [document], stderr = cli(painter, "run", path)
    assert status == 0, stderr + json.dumps(document)
    other_dump = tmp_path / "other-recipe.json"
    other_dump.write_text(json.dumps(document["result"]), encoding="utf-8")
    text, _ = policy(tmp_path, PLANE, report)
    result = production(
        painter,
        tmp_path,
        f"""
import sys
plane, other, dump, resources = sys.argv[1:5]
def refused(call, *args):
    try:
        call(*args)
    except uzpainter.Assets3DProductionError as error:
        return str(error)
    return None
uzpainter._assets3d_install_production_policy({text!r})
project.create(plane)
revision = project.revision()
out = {{"reload": refused(project.reload_mesh, other), "unchanged": project.revision() == revision}}
from uzpainter import layerstack as ls, textureset as ts
with uzpainter.Transaction("admitted transaction"):
    ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
out["transaction"] = project.revision() == revision + 1
project.close()
out["rebuild"] = refused(project.rebuild_from_recipe, dump, resources)
out["open_after_rebuild"] = project.is_open()
result = out
""",
        str(PLANE),
        str(other),
        str(other_dump),
        str(resources),
    )
    assert "not the admitted source" in result["reload"] and result["unchanged"] is True
    assert result["transaction"] is True
    assert "refused" in result["rebuild"] and result["open_after_rebuild"] is False
    altered = dict(report, authored_difference=1)
    altered_text, _ = policy(tmp_path, PLANE, altered)
    result = production(
        painter,
        tmp_path,
        f"""
import sys
uzpainter._assets3d_install_production_policy({altered_text!r})
try:
    project.create(sys.argv[1])
    outcome = None
except uzpainter.Assets3DProductionError as error:
    outcome = str(error)
result = {{"refusal": outcome, "open": project.is_open()}}
""",
        str(PLANE),
    )
    assert "differs from the admitted report" in result["refusal"] and result["open"] is False


def test_refused_open_leaves_the_file_untouched(painter: Path, tmp_path: Path) -> None:
    """A stored project whose mesh is not admitted is refused under the lock, read-only, before
    the store's cleanup or its read-write connection: same bytes, same folder listing."""
    report = admitted_report(painter, tmp_path, PLANE)
    other = tmp_path / "other.obj"
    other.write_text(OTHER_OBJ, encoding="utf-8")
    stored = tmp_path / "stored"
    stored.mkdir()
    path = script(
        tmp_path,
        f"""
        from uzpainter import project
        project.create({other.as_posix()!r})
        project.save_as({(stored / "other.uzp").as_posix()!r})
        project.close()
        result = True
        """,
    )
    status, _, stderr = cli(painter, "run", path)
    assert status == 0, stderr
    target = stored / "other.uzp"
    before = (
        hashlib.sha256(target.read_bytes()).hexdigest(),
        sorted(p.name for p in stored.iterdir()),
    )
    text, _ = policy(tmp_path, PLANE, report)
    result = production(
        painter,
        tmp_path,
        f"""
import sys
uzpainter._assets3d_install_production_policy({text!r})
try:
    project.open(sys.argv[1])
    outcome = None
except uzpainter.Assets3DProductionError as error:
    outcome = str(error)
result = {{"refusal": outcome, "open": project.is_open()}}
""",
        str(target),
    )
    assert "not the admitted source" in result["refusal"] and result["open"] is False
    after = (
        hashlib.sha256(target.read_bytes()).hexdigest(),
        sorted(p.name for p in stored.iterdir()),
    )
    assert after == before


def test_same_mesh_reload_and_changed_pin_save_as(painter: Path, tmp_path: Path) -> None:
    """A production reload of the admitted mesh repeats the admitted import request (no explicit
    scale stays none) and is admitted; a pin changed afterwards refuses save_as before any folder
    is made, with the revision unchanged."""
    report = admitted_report(painter, tmp_path, PLANE)
    assert report["units"]["requested_mesh_unit_scale"] is None
    text, request = policy(tmp_path, PLANE, report)
    destination = tmp_path / "destination"
    result = production(
        painter,
        tmp_path,
        f"""
import sys
from pathlib import Path
plane, request, destination = sys.argv[1:4]
uzpainter._assets3d_install_production_policy({text!r})
project.create(plane)
revision = project.revision()
project.reload_mesh(plane)
out = {{"reloaded": project.revision() >= revision}}
revision = project.revision()
Path(request).write_text("changed after the preflight", encoding="utf-8")
try:
    project.save_as(destination + "/admitted.uzp")
    out["save_as"] = None
except uzpainter.Assets3DProductionError as error:
    out["save_as"] = str(error)
out["unchanged"] = project.revision() == revision
project.close()
result = out
""",
        str(PLANE),
        str(request),
        str(destination),
    )
    assert result["reloaded"] is True
    assert "changed since the preflight" in result["save_as"] and result["unchanged"] is True
    assert not destination.exists()


def test_adapter_production_round_against_the_native_guard(
    painter: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The router agent's real client -> runner -> host round on this build
    (tests/adapters/assets3d/production_round.py): create, same-mesh reload, refused wrong mesh."""
    from tests.adapters.assets3d.production_round import check_production_round

    check_production_round(painter, tmp_path, monkeypatch)


def test_adapter_failed_upstream_gate_never_launches_or_mutates(
    painter: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.adapters.assets3d.production_round import check_refused_round

    mesh = tmp_path / "low.obj"
    mesh.write_bytes(PLANE.read_bytes())
    check_refused_round(painter, tmp_path, mesh, monkeypatch, failed_gate=True)


def test_adapter_genuine_failed_certificate_never_launches_or_mutates(
    painter: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.adapters.assets3d.production_round import check_refused_round

    mesh = tmp_path / "zero-normals.obj"
    mesh.write_text(ZERO_NORMAL_OBJ, encoding="utf-8")
    check_refused_round(painter, tmp_path, mesh, monkeypatch, failed_gate=False)


def test_adapter_genuine_warn_import_proceeds_flagged_diagnostic(
    painter: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.adapters.assets3d.production_round import check_warn_diagnostic_round

    # Existing valid quad: fan triangulation is a warning, not a fabricated report status.
    mesh = tmp_path / "warn-quad.obj"
    mesh.write_text(OTHER_OBJ, encoding="utf-8")
    check_warn_diagnostic_round(painter, tmp_path, mesh, monkeypatch)
