"""Exports use the worker's operational GPU and retain CPU mode without one (phase3.1)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from tests.supervisor.conftest import NO_GPU, Mcp, run_script
from tests.supervisor.test_supervisor_gpu import BACKEND, gpu_session
from tests.supervisor.test_supervisor_jobs import EXPORT_CONFIG
from tools.parity.feasibility import png

pytestmark = pytest.mark.skipif(NO_GPU, reason="UZP_NO_GPU=1: hardware export (decision 028)")


def delivery_files(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def export_to(session: Mcp, path: Path) -> dict[str, Any]:
    reply = session.call(
        "export", {"config": {**EXPORT_CONFIG, "exportPath": path.as_posix()}, "wait": True}
    )
    assert "result" in reply, reply
    result = reply["result"]
    assert isinstance(result, dict)
    return result


def test_gpu_export_records_real_backend_and_matches_cpu(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    session, revision = gpu_session(painter, tmp_path, sessions, "--allow-python")
    mask = Path(__file__).resolve().parents[2] / "parity/fixtures/api-probes/mask-left-half.png"
    setup = session.call(
        "run_python",
        {
            "code": f"""
from uzpainter import colormanagement as cm, layerstack as ls, project, resource, textureset as ts
stack = ts.get_active_stack()
mask = resource.import_project_resource({mask.as_posix()!r}, resource.Usage.TEXTURE)
layer = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
layer.active_channels = {{ts.ChannelType.Height}}
layer.set_source(ts.ChannelType.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
layer.add_mask(ls.MaskBackground.Black)
fill = ls.insert_fill(ls.InsertPosition.inside_node(layer, ls.NodeStack.Mask))
fill.set_source(None, mask.identifier())
project.save()
result = True
"""
        },
    )
    assert "error" not in setup, setup
    revision = session.call("project_inspect")["result"]["revision"]
    first = export_to(session, tmp_path / "gpu")
    receipt = json.loads(Path(first["receipt"]).read_text(encoding="utf-8"))
    assert receipt["backend"] == BACKEND
    assert receipt["adapter"] and receipt["adapter"] != "unknown"
    assert receipt["driver"] and receipt["driver"] != "unknown"
    assert first["revision"] == revision
    assert len(set(png.decode(Path(first["files"][0]["path"]).read_bytes()).ravel())) > 1
    repeated = export_to(session, tmp_path / "gpu-repeat")
    assert [f["sha256"] for f in repeated["files"]] == [f["sha256"] for f in first["files"]]
    assert "error" not in session.call("project_close")
    # Explicit unavailable-device fixture: same saved project/revision, CPU receipt.
    cpu_path = tmp_path / "cpu"
    config = {**EXPORT_CONFIG, "exportPath": cpu_path.as_posix()}
    cpu = run_script(
        painter,
        tmp_path,
        f"""
        import json
        from uzpainter import project, export
        project.open({(tmp_path / "plane.uzp").as_posix()!r})
        result = export.start(json.loads({json.dumps(config)!r})).wait()
        """,
        gpu_unavailable=True,
    )
    cpu_receipt = json.loads(Path(cpu["receipt"]).read_text(encoding="utf-8"))
    assert cpu_receipt["backend"] == "cpu"
    assert cpu_receipt["adapter"] is None and cpu_receipt["driver"] is None
    assert cpu["revision"] == revision
    assert [f["sha256"] for f in cpu["files"]] == [f["sha256"] for f in first["files"]]


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "fault,code", [("remove_device", "device_removed"), ("gpu_stall", "timeout")]
)
def test_export_gpu_fault_publishes_nothing_and_recovers(
    painter: Path, tmp_path: Path, sessions: list[Mcp], existing: bool, fault: str, code: str
) -> None:
    session, revision = gpu_session(painter, tmp_path, sessions, "--gpu-deadline-ms", "3000")
    output = tmp_path / "delivery"
    if existing:
        export_to(session, output)
    before = delivery_files(output)
    old = session.status()["worker_pid"]
    assert session.call("test_fault", {"fault": fault})["result"] == {"armed": fault}
    failed = session.call(
        "export", {"config": {**EXPORT_CONFIG, "exportPath": output.as_posix()}, "wait": True}
    )
    assert "error" in failed and "result" not in failed, failed
    assert failed["error"]["code"] == code, failed
    assert failed["error"]["details"]["backend"] == BACKEND, failed
    assert failed["receipt"]["job"]["committed"] is None, failed
    assert delivery_files(output) == before
    assert output.exists() == existing
    inspected = session.call("project_inspect")
    assert inspected["result"]["revision"] == revision, inspected
    status = session.status()
    assert status["worker_pid"] != old and status["gpu_backend"] == BACKEND, status
    assert status["gpu_status"] == "ready", status
    recovery = status["recoveries"][-1]
    assert recovery["cause"] == "device_fault" and recovery["fault_code"] == code, recovery
    recovered = export_to(session, output)
    assert recovered["generation"] == ("000002" if existing else "000001")


def test_gpu_export_deadline_bounds_publication_lock_wait(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    session, revision = gpu_session(painter, tmp_path, sessions, "--gpu-deadline-ms", "1000")
    output = tmp_path / "locked"
    output.mkdir()
    # An existing writable handle prevents PublicationLock's exclusive CreateFileW.
    with (output / "publication.lock").open("wb"):
        start = time.monotonic()
        failed = session.call(
            "export",
            {
                "config": {**EXPORT_CONFIG, "exportPath": output.as_posix()},
                "wait": True,
            },
        )
        assert time.monotonic() - start < 5.0, failed
        assert failed["error"]["code"] == "timeout", failed
        assert failed["error"]["details"]["backend"] == BACKEND, failed
        assert failed["receipt"]["job"]["committed"] is None, failed
        assert not (output / "generations").exists()
        assert not (output / "current.json").exists()
    assert session.call("project_inspect")["result"]["revision"] == revision
    assert session.status()["gpu_status"] == "ready"


def test_catching_gpu_export_error_in_python_still_restarts_failed_worker(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    session, revision = gpu_session(painter, tmp_path, sessions, "--allow-python")
    output = tmp_path / "caught"
    config = {**EXPORT_CONFIG, "exportPath": output.as_posix()}
    old = session.status()["worker_pid"]
    assert session.call("test_fault", {"fault": "remove_device"})["result"] == {
        "armed": "remove_device"
    }
    caught = session.call(
        "run_python",
        {
            "code": f"""
import json
from uzpainter import export
try:
    export.start(json.loads({json.dumps(config)!r})).wait()
except RuntimeError as error:
    result = {{"caught": str(error)}}
else:
    raise AssertionError("the injected device loss did not fail")
"""
        },
    )
    assert "result" in caught, caught
    report = caught["result"]
    assert report["status"] == "ok" and "device_removed" in report["result"]["caught"], caught
    assert not output.exists()
    deadline = time.monotonic() + 30
    status = session.status()
    while status["worker_pid"] == old or not status["recoveries"]:
        assert time.monotonic() < deadline, status
        time.sleep(0.05)
        status = session.status()
    assert session.call("project_inspect")["result"]["revision"] == revision
    assert status["worker_pid"] != old and status["gpu_status"] == "ready", status
    assert status["recoveries"][-1]["cause"] == "device_fault", status


def test_background_gpu_export_fault_restarts_idle_worker(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    session, revision = gpu_session(
        painter, tmp_path, sessions, "--allow-python", "--gpu-deadline-ms", "3000"
    )
    output = tmp_path / "background"
    config = {**EXPORT_CONFIG, "exportPath": output.as_posix()}
    old = session.status()["worker_pid"]
    assert session.call("test_fault", {"fault": "gpu_stall"})["result"] == {"armed": "gpu_stall"}
    started = session.call(
        "run_python",
        {
            "code": f"""
import json
from uzpainter import export
background_export = export.start(json.loads({json.dumps(config)!r}))
result = True
"""
        },
    )
    assert started["result"]["status"] == "ok", started
    assert started["result"]["result"] is True, started
    status = session.status()
    assert status["worker_pid"] == old and not status["recoveries"], status
    deadline = time.monotonic() + 30
    # supervisor_status stays local: no request may wake the worker command loop.
    while status["worker_pid"] == old or not status["recoveries"]:
        assert time.monotonic() < deadline, status
        time.sleep(0.05)
        status = session.status()
    assert status["gpu_status"] == "ready", status
    assert status["recoveries"][-1]["cause"] == "device_fault", status
    assert not output.exists()
    assert session.call("project_inspect")["result"]["revision"] == revision
