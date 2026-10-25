"""`UzPainter.exe assets bind-snapshot`: explicit binds of stored synthetic snapshots.

The snapshots are authored test values written by `uzp-export-tests snapshot-bind`, not Painter
data; these tests establish the product bind route only, no Painter parity.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import PLANE
from tests.python.test_assets3d_production_guard import painter as painter

Fixture = dict[str, Any]


def run_script(exe: Path, work: Path, body: str) -> Any:
    """Runs `body` with `UzPainter.exe run` (the documented facade); returns its `result`."""
    script = work / "script.py"
    out = work / "result.json"
    script.write_text(
        "import json\nfrom substance_painter import layerstack as ls, project, source,"
        " textureset as ts\nCT = ts.ChannelType\n"
        f"PLANE = {PLANE.as_posix()!r}\nWORK = {work.as_posix()!r}\n"
        f"{body}\nwith open({out.as_posix()!r}, 'w') as handle:\n    json.dump(result, handle)\n",
        encoding="utf-8",
    )
    process = subprocess.run(
        [str(exe), "run", str(script)], capture_output=True, text=True, timeout=300, check=False
    )
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture
def fixture(painter: Path, export_tests: Path, tmp_path: Path) -> Fixture:  # noqa: F811
    # The positive target goes through the public API, as a real capture project would.
    target = run_script(
        painter,
        tmp_path,
        "project.create(PLANE, settings=project.Settings(default_texture_resolution=128))\n"
        "stack = ts.get_active_stack()\n"
        "stack.add_channel(CT.User0, ts.ChannelFormat.L32F)\n"
        "stack.add_channel(CT.User1, ts.ChannelFormat.L32F)\n"
        "stack.add_channel(CT.User2, ts.ChannelFormat.L16F)\n"
        "node = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))\n"
        "node.set_name('bind target')\n"
        "node.active_channels = {CT.User0, CT.User2}\n"
        "project.save_as(WORK + '/bind.uzp')\nresult = node.uid()\nproject.close()",
    )
    process = subprocess.run(
        [str(export_tests), "snapshot-bind", str(tmp_path / "bind.uzp")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    line = next(x for x in process.stdout.splitlines() if x.startswith("BIND_FIXTURE:"))
    report: Fixture = json.loads(line.removeprefix("BIND_FIXTURE:"))
    report["project"] = tmp_path / "bind.uzp"
    report["target"] = target
    return report


def bind(exe: Path, fixture: Fixture, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    path = fixture["project"].parent / "bind.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    process = subprocess.run(
        [str(exe), "assets", "bind-snapshot", str(fixture["project"]), "--request", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    lines = [x for x in process.stdout.splitlines() if x.startswith("UZP_JSON:")]
    assert len(lines) == 1, process.stdout + process.stderr
    return process.returncode, json.loads(lines[0].removeprefix("UZP_JSON:"))


def request(fixture: Fixture, flag: int, override: Any = None, **changes: Any) -> dict[str, Any]:
    value = {
        "signature_sha256": fixture["signatures"][f"flag{flag}"],
        "node": fixture["target"],
        "channel": "User0",
        "resolution_override": override,
    }
    value.update(changes)
    return value


def auto(size: int, offset: int) -> dict[str, Any]:
    return {"mode": "Auto", "value": [size, size], "log2_offset": offset}


READ_SOURCE = """
project.open(WORK + '/bind.uzp')
value = ls.get_root_layer_nodes(ts.get_active_stack())[0].get_source(CT.User0)
try:
    read = value.resolution
    resolution = [read.mode.name, list(read.value), read.log2_offset]
except Exception as error:
    resolution = type(error).__name__
try:
    outputs = value.image_outputs
except Exception as error:
    outputs = type(error).__name__
result = {
    "parameters": value.get_parameters(),
    "active_output": value.active_output,
    "outputs": outputs,
    "resolution": resolution,
}
project.close()
"""


def test_usage(painter: Path) -> None:  # noqa: F811
    process = subprocess.run(
        [str(painter), "assets", "bind-snapshot"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 2
    assert "bind-snapshot <file.uzp> --request <bind.json>" in process.stderr


def test_bind_reopen_getters_and_rebinding(painter: Path, fixture: Fixture) -> None:  # noqa: F811
    work = fixture["project"].parent
    code, first = bind(painter, fixture, request(fixture, 0))
    assert code == 0, first
    assert first["status"] == "ok" and first["verified_after_reopen"] is True
    assert run_script(painter, work, READ_SOURCE) == {
        "parameters": {"amount": 0.5, "flag": 0},
        "active_output": "scalar",
        "outputs": ["scalar", "aux"],
        # Without an override the facade does not guess the asset's default resolution.
        "resolution": "UnsupportedProcedural",
    }
    before = hashlib.sha256(fixture["project"].read_bytes()).hexdigest()
    code, again = bind(painter, fixture, request(fixture, 0))
    assert (code, again["status"], again["revision"]) == (0, "unchanged", first["revision"])
    assert hashlib.sha256(fixture["project"].read_bytes()).hexdigest() == before

    # 0 -> 1 -> 0: each bind is a new operation of its own base revision, never a replay.
    code, second = bind(painter, fixture, request(fixture, 1))
    assert code == 0 and second["revision"] > first["revision"], second
    read = run_script(painter, work, READ_SOURCE)
    assert read["parameters"] == {"amount": 0.5, "flag": 1}
    # The second snapshot is a legacy entry without recorded metadata: it still binds.
    assert read["outputs"] == "UnsupportedProcedural"
    code, third = bind(painter, fixture, request(fixture, 0))
    assert code == 0 and third["status"] == "ok" and third["revision"] > second["revision"], third
    assert run_script(painter, work, READ_SOURCE)["parameters"] == {"amount": 0.5, "flag": 0}

    # An explicit Auto override whose nominal value is not 128 but whose effective size is the
    # set's 128 is a different complete reference: it binds and is kept as given.
    code, nominal = bind(painter, fixture, request(fixture, 0, auto(256, 0)))
    assert code == 0 and nominal["revision"] > third["revision"], nominal
    assert run_script(painter, work, READ_SOURCE)["resolution"] == ["Auto", [256, 256], 0]
    code, same = bind(painter, fixture, request(fixture, 0, auto(256, 0)))
    assert (code, same["status"], same["revision"]) == (0, "unchanged", nominal["revision"])
    # Explicit absence is a change again.
    code, absent = bind(painter, fixture, request(fixture, 0))
    assert code == 0 and absent["revision"] > nominal["revision"], absent
    assert run_script(painter, work, READ_SOURCE)["resolution"] == "UnsupportedProcedural"


REFUSALS: list[tuple[str, dict[str, Any], str]] = [
    ("unknown hash", {"signature_sha256": "0" * 64}, "holds no snapshot"),
    ("corrupt hash", {"signature_sha256": "ABC"}, "lowercase SHA-256"),
    ("missing override", {"resolution_override": "drop"}, "exactly signature_sha256"),
    ("extra member", {"extra": 1}, "exactly signature_sha256"),
    ("string node", {"node": "1"}, "node must be an integer"),
    ("missing node", {"node": 999999}, "does not exist"),
    ("content effect", {"node": "content_effect"}, "is an effect"),
    ("mask effect", {"node": "mask_effect"}, "is an effect"),
    ("inactive host fill", {"node": "host"}, "not an active User L32F channel"),
    ("inactive User1", {"channel": "User1"}, "not an active User L32F channel"),
    ("L16F User2", {"channel": "User2"}, "not an active User L32F channel"),
    ("BaseColor", {"channel": "BaseColor"}, "not an active User L32F channel"),
    ("unknown channel", {"channel": "Nope"}, "channel must name"),
    (
        "bad mode",
        {"resolution_override": {"mode": "Big", "value": [128, 128], "log2_offset": 0}},
        "resolution mode",
    ),
    (
        "no offset",
        {"resolution_override": {"mode": "Auto", "value": [128, 128]}},
        "null or exactly",
    ),
    (
        "three sizes",
        {"resolution_override": {"mode": "Auto", "value": [128, 128, 1], "log2_offset": 0}},
        "two integers",
    ),
    ("effective 256", {"resolution_override": auto(128, 1)}, "not the snapshot's signature"),
    (
        "Custom 256",
        {"resolution_override": {"mode": "Custom", "value": [256, 256], "log2_offset": 0}},
        "not the snapshot's signature",
    ),
    (
        "Asset mode",
        {"resolution_override": {"mode": "Asset", "value": [128, 128], "log2_offset": 0}},
        "Asset/Document",
    ),
]


def test_refusals_leave_the_project_untouched(painter: Path, fixture: Fixture) -> None:  # noqa: F811
    code, bound = bind(painter, fixture, request(fixture, 0))
    assert code == 0, bound
    before = hashlib.sha256(fixture["project"].read_bytes()).hexdigest()
    for name, changes, message in REFUSALS:
        value = request(fixture, 1)
        for key, change in changes.items():
            if change == "drop":
                del value[key]
            elif isinstance(change, str) and change in fixture and key == "node":
                value[key] = fixture[change]
            else:
                value[key] = change
        code, report = bind(painter, fixture, value)
        assert (code, report["status"]) == (3, "refused"), (name, report)
        assert message in report["error"], (name, report)
        assert hashlib.sha256(fixture["project"].read_bytes()).hexdigest() == before, name
    code, unchanged = bind(painter, fixture, request(fixture, 0))
    assert (code, unchanged["status"], unchanged["revision"]) == (0, "unchanged", bound["revision"])
