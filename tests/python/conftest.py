"""Shared fixtures of the native Python API tests (`src/python/`, phase1.19_pyapi-native-module).

`uzp-pyapi-tests.exe` (tests/python/pyapi_runner.cpp) is built once per test session with
`zig build pyapi-tests` into a temporary prefix, beside the embedded CPython it runs. Each test
writes a script, runs it in a fresh process and reads its report: `{status, result, stdout,
stderr, error?, last_committed_revision, committed}`. CPU only: no test here needs a GPU.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANE = REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj"
PROBE_IMAGES = REPO_ROOT / "parity" / "fixtures" / "api-probes"

# Prepended to every script: the modules, the plane fixture and helpers.
PRELUDE = f"""
import json, os, sys, threading, time
import uzpainter
from uzpainter import (colormanagement as cm, exception, export, jobs, layerstack as ls, levels,
                       project, resource, source, textureset as ts)
PLANE = {str(PLANE.as_posix())!r}
IMAGES = {str(PROBE_IMAGES.as_posix())!r}
CT = ts.ChannelType
WORK = sys.argv[1]

def create(resolution=256):
    project.create(PLANE, project.Settings(default_texture_resolution=resolution))
    return ts.get_active_stack()

def top(stack):
    return ls.InsertPosition.from_textureset_stack(stack)

def raises(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except BaseException as error:
        return type(error).__name__ + ": " + str(error)
    return None
"""

Run = Callable[[str], dict[str, Any]]


@pytest.fixture(scope="session")
def pyapi_runner(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-pyapi-tests.exe` of a fresh `zig build pyapi-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-pyapi-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("pyapi-tests")
    build = subprocess.run(
        [zig, "build", "pyapi-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-pyapi-tests.exe"


@pytest.fixture
def run(pyapi_runner: Path, tmp_path: Path) -> Run:
    """Runs a script body (after PRELUDE) with the test's temporary folder as `WORK`; returns its
    report. A report whose status is not "ok" carries the script's error and traceback."""

    def go(body: str) -> dict[str, Any]:
        script = tmp_path / "script.py"
        script.write_text(PRELUDE + textwrap.dedent(body), encoding="utf-8")
        process = subprocess.run(
            [str(pyapi_runner), str(script), str(tmp_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        lines = [line for line in process.stdout.splitlines() if line.startswith("{")]
        assert lines, f"exit {process.returncode}: {process.stdout}\n{process.stderr}"
        report: dict[str, Any] = json.loads(lines[-1])
        assert process.returncode == (0 if report["status"] == "ok" else 1)
        return report

    return go
