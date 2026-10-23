"""Shared fixtures of the preview tests (task phase2.1_preview-viewport-window):
`uzp-preview-tests.exe` (`tests/preview/preview_test.cpp`), built once per test session with
`zig build preview-tests` into a temporary prefix, and `UzPainter.exe` with its worker pipes
(`painter` and `pipes` of tests/supervisor/conftest.py: the Debug build, whose worker carries the
test-only preview stall hook). `ocio_bundle` makes the OCIO project the capture tests of
phase2.2_preview-capture render (decision 148).

Settling evidence (task phase2.3_realtime-preview, decision 162): a test that settles a case of the
preview gate carries `@pytest.mark.preview_settling(<case>, ...)`. With
`UZP_PREVIEW_SETTLING_REPORT=<path>` the run merges each tagged test's result, run time and the
timings it gave `preview_settling.metric` into that report (`tools/parity/settling/preview.py`).
Worker GPU cases select `UZP_PREVIEW_BACKEND=dx12|vulkan` (DX12 by default). An explicitly
selected backend must be ready; an unavailable device fails that hardware lane."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import textwrap
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.desktop import PrivateDesktop
from tests.supervisor.conftest import Pipe, painter, pipes  # noqa: F401  (fixtures)
from tools.parity.settling import preview as settling_report

REPO_ROOT = Path(__file__).resolve().parents[2]
EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
BACKEND = os.environ.get("UZP_PREVIEW_BACKEND", "dx12")
if BACKEND not in {"dx12", "vulkan"}:
    raise ValueError(f"unsupported UZP_PREVIEW_BACKEND: {BACKEND}")
GOLDENS = REPO_ROOT / "tests" / "preview" / "viewport-goldens.json"
# The render-reference sphere: seen whole by the fit camera (the plane fixture lies edge-on).
SPHERE = REPO_ROOT / "parity" / "fixtures" / "render-procedure" / "sphere.obj"
ENVIRONMENT = REPO_ROOT / "assets" / "environments" / "studio-small-09.exr"
JSON_PREFIX = "UZP_JSON:"
# Painter's substance config (decisions 042, 134): the only display configuration of the viewport.
OCIO_CONFIG = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
LEGACY_COLOUR = b'"color_management":{"config_hash":"","io_rules":[],"mode":"","working_space":""}'
OCIO_COLOUR = (
    b'"color_management":{"config_hash":"'
    + OCIO_CONFIG.encode()
    + b'","io_rules":[],"mode":"ocio","working_space":"ACEScg"}'
)


@pytest.fixture(scope="session")
def preview_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-preview-tests.exe` of a fresh `zig build preview-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-preview-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("preview-tests")
    build = subprocess.run(
        [zig, "build", "preview-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-preview-tests.exe"


def run_case(exe: Path, case: str, *args: str, gpu: bool = False) -> tuple[set[str], str]:
    """Runs one case; returns its passed checks and its output. Fails on any failed check."""
    if gpu and NO_GPU:
        pytest.skip(
            f"UZP_NO_GPU=1: `{case}` needs a DX12 hardware adapter; run it locally on the "
            "owner's machine (decision 028)"
        )
    proc = subprocess.run(
        [str(exe), case, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no DX12 adapter for `{case}`: {output.strip()}")
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    return passed, output


def require_gpu(pipe: Pipe) -> None:
    """Verify the worker uses the requested device; explicit hardware lanes never skip."""
    assert pipe.handshake["gpu_backend"] == BACKEND, pipe.handshake
    if pipe.handshake["gpu_status"] != "ready":
        if "UZP_PREVIEW_BACKEND" in os.environ:
            pytest.fail(f"requested {BACKEND} device unavailable: {pipe.handshake}")
        pytest.skip(f"no {BACKEND} device on this machine")


def run_report(exe: Path, script: Path, *args: str) -> dict[str, Any]:
    """`UzPainter.exe run <script> <args>`: its `UZP_JSON:` report (the status is checked by the
    caller)."""
    process = subprocess.run(
        [str(exe), "run", str(script), "--gpu-backend", BACKEND, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    lines = [line for line in process.stdout.splitlines() if line.startswith(JSON_PREFIX)]
    assert lines, f"exit {process.returncode}: {process.stdout}\n{process.stderr}"
    report: dict[str, Any] = json.loads(lines[-1][len(JSON_PREFIX) :])
    assert process.returncode == (0 if report["status"] == "ok" else 1), process.stderr
    return report


def ocio_bundle(exe: Path, folder: Path, mesh: Path = SPHERE) -> Path:
    """An OCIO project bundle of `mesh` (the sphere fixture) with the shipped environment and no
    layer.

    The native `project.create` here makes a Legacy project (no `ocio_config_hash`, decision
    207), so the bundle is a Legacy project's `export-bundle` whose manifest declares OCIO
    with Painter's substance config, re-hashed: what `painter_viewport` renders today (decision
    148). `project.open(<bundle>)` imports it as `<bundle>.uzp`.
    """
    folder.mkdir(parents=True, exist_ok=True)
    legacy = folder / "legacy.uzp"
    script = folder / "make-legacy.py"
    script.write_text(
        textwrap.dedent(
            f"""
            from uzpainter import display, project, resource
            project.create({mesh.as_posix()!r}, project.Settings(default_texture_resolution=256))
            env = resource.import_project_resource({ENVIRONMENT.as_posix()!r},
                                                   resource.Usage.ENVIRONMENT, "studio")
            display.set_environment_resource(env.identifier())
            project.save_as({legacy.as_posix()!r})
            result = True
            """
        ),
        encoding="utf-8",
    )
    assert run_report(exe, script)["status"] == "ok"
    bundle = folder / "ocio"
    exported = subprocess.run(
        [str(exe), "export-bundle", str(legacy), str(bundle)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert exported.returncode == 0, exported.stdout + exported.stderr
    manifest = (bundle / "manifest.json").read_bytes()
    assert manifest.count(LEGACY_COLOUR) == 1, manifest[:400]
    patched = manifest.replace(LEGACY_COLOUR, OCIO_COLOUR)
    (bundle / "manifest.json").write_bytes(patched)
    index = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    index["manifest_sha256"] = hashlib.sha256(patched).hexdigest()
    (bundle / "bundle.json").write_text(json.dumps(index), encoding="utf-8")
    return bundle


# --- settling evidence (decision 162) --------------------------------------------------------

_calls: dict[str, tuple[tuple[str, ...], str, float, str | None]] = {}
_metrics: dict[str, dict[str, float]] = {}
_exe_hashes: dict[Path, str] = {}


class PreviewSettling:
    """A tagged test's handle on the report: the timings it measured itself."""

    def __init__(self, nodeid: str) -> None:
        self._nodeid = nodeid

    def metric(self, name: str, value: float) -> None:
        _metrics.setdefault(self._nodeid, {})[name] = round(value, 3)


@pytest.fixture
def preview_settling(request: pytest.FixtureRequest) -> PreviewSettling:
    return PreviewSettling(request.node.nodeid)


@pytest.fixture
def desktop() -> Iterator[PrivateDesktop]:
    """A desktop nobody sees, where a test's preview windows open (decision 252); what still runs
    on it when the test ends is ended."""
    made = PrivateDesktop()
    yield made
    made.close()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "preview_settling(*cases): the test settles these preview gate cases (decision 162)",
    )


def _exe_sha256(item: pytest.Item) -> str | None:
    exe = getattr(item, "funcargs", {}).get("painter")
    if not isinstance(exe, Path) or not exe.is_file():
        return None
    if exe not in _exe_hashes:
        _exe_hashes[exe] = hashlib.sha256(exe.read_bytes()).hexdigest()
    return _exe_hashes[exe]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    marker = item.get_closest_marker("preview_settling")
    if marker is not None and report.when == "call":
        cases = tuple(marker.args)
        _calls[item.nodeid] = (cases, report.outcome, report.duration, _exe_sha256(item))
    return report


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    target = os.environ.get("UZP_PREVIEW_SETTLING_REPORT")
    if not target or not _calls:
        return
    # A case settled by several tests passes only if every one of them passed.
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for nodeid, (cases, outcome, seconds, exe_sha256) in _calls.items():
        if outcome == "skipped" or exe_sha256 is None:
            continue
        for case in cases:
            backend = settling_report.backend_of(case, BACKEND)
            entry = entries.setdefault(
                (case, backend),
                {
                    "id": case,
                    "backend": backend,
                    "result": "pass",
                    "seconds": 0.0,
                    "date": datetime.date.today().isoformat(),
                    "exe_sha256": exe_sha256,
                },
            )
            if outcome != "passed":
                entry["result"] = "fail"
            entry["seconds"] = round(entry["seconds"] + seconds, 3)
            if nodeid in _metrics:
                entry.setdefault("metrics", {}).update(_metrics[nodeid])
    settling_report.write(Path(target), entries.values())
