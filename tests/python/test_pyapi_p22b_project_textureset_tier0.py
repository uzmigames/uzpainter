"""Exact P22B project and texture-set replays, including save/reopen readbacks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import Run
from tests.python.observed_replay import (
    check_observed_trace,
    compare_observed,
    observed_symbols,
    save_trace,
)
from tests.python.test_pyapi_facade_tier0 import replay

PROBES = (
    "p22b-project-mesh-unit-scale",
    "p22b-project-tangent-per-fragment",
    "p22b-project-tangent-per-vertex",
    "p22b-project-workflow-default",
    "p22b-textureset-channels",
    "p22b-textureset-texture-set",
    "p22b-textureset-user-channels",
)


@pytest.mark.parametrize("probe", PROBES)
def test_p22b_project_textureset_replay(facade: Run, tmp_path: Path, probe: str) -> None:
    def capture(body: str) -> dict[str, Any]:
        # The plain replay closes its project before returning; verify that cleanup.
        return facade(
            body
            + '\nresult["cleanup_failures"] = '
            + '["project remains open"] if uzpainter.project.is_open() else []\n'
        )

    replayed, golden, job = replay(capture, probe, tmp_path)
    differences = compare_observed(replayed, golden, job, tmp_path, {})
    differences.extend(f"cleanup: {failure}" for failure in replayed["cleanup_failures"])
    replay_id = f"facade/{probe}"
    save_trace(replay_id, golden, replayed, {}, differences)
    assert replayed["cleanup_failures"] == []
    assert not differences, "\n".join(differences)
    check_observed_trace(replay_id, golden["golden_id"], observed_symbols(replayed, golden, {}))
