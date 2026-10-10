"""Shared fixtures: `uzp-normal-prototype.exe`, built once per session, and its bakes."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.parity.normal_convention.cases import FIXTURE_DIR
from tools.parity.normal_convention.fixtures import pairs
from tools.parity.normal_convention.prototype import PrototypeBake, build_prototype, run_prototype


@pytest.fixture(scope="session")
def prototype_exe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("zig") is None:
        pytest.skip("zig is not on PATH; uzp-normal-prototype.exe cannot be built")
    return build_prototype(tmp_path_factory.mktemp("normal-prototype"))


@pytest.fixture(scope="session")
def prototype_bakes(
    prototype_exe: Path, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, PrototypeBake]:
    out = tmp_path_factory.mktemp("normal-bakes")
    return {pair: run_prototype(prototype_exe, pair, FIXTURE_DIR, out) for pair in pairs()}
