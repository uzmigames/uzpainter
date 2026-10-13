"""P1-MESH integration (phase1.7_mesh-loader; `docs/architecture/12-mesh-import.md` §9).

The §9 fixtures are the tests of the three children (`test_mesh_import.py`,
`test_mesh_certificate.py`, `test_mesh_reload.py`); `parity/reports/phase1/mesh-loader.md` maps
each fixture to its test and records the normal-convention run across Painter, UzPainter and
UzEngine. This file adds the build half of the requirement "UzEngine only as an external
consumer": every compile and link of `zig build mesh-tests` (the mesh library, its native tests
and the normal-convention bake) takes its include and library paths from the repository, the Zig
toolchain or the Windows SDK, never from a UzEngine checkout. It applies the `build-path` rule of
`tools/vendoring/vendor_check.py`, whose own build covers the render-core and painter steps.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tools.vendoring.vendor_check import build_path_violations, windows_sdk_roots, zig_toolchain

if TYPE_CHECKING:
    from tests.conftest import FreshBuild

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mesh_build_references_no_uzengine_artifact(fresh_verbose_build: FreshBuild) -> None:
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; the mesh build cannot be inspected")
    # The session's build from an empty cache (`tests/conftest.py`): every compile and link of
    # `mesh-tests` is run and printed.
    log = fresh_verbose_build.log
    for source in ("mesh_import.cpp", "tangents.cpp", "reload.cpp", "normal_bake.cpp"):
        assert source in log, f"{source} was not compiled in the inspected build"
    env_repo = os.environ.get("UZENGINE_REPO")
    known = [Path(env_repo).resolve()] if env_repo else []
    allowed, denied = zig_toolchain(zig)
    violations = build_path_violations(
        log, REPO_ROOT, REPO_ROOT, [*allowed, *windows_sdk_roots()], denied, known
    )
    assert violations == [], "\n".join(str(v) for v in violations)
