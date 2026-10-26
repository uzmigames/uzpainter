"""Exercise the generated replay worker on authored V2 evidence, without an oracle.

The plan comes from the authored command fixture solely to test native collection;
this does not exercise or replace the private materialization gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.python.capability_trace import SOURCE
from tests.python.conftest import FACADE_PRELUDE, runner
from tests.python.test_filter_observations_v2 import (
    FILTER_SOURCE,
    SINGLE,
    UNAVAILABLE,
)
from tests.python.test_filter_observations_v2 import (
    authored as authored,
)
from tests.python.test_filter_observations_v2 import (
    v2_project as v2_project,
)
from tests.python.test_pyapi_native import ok
from tools.parity import filter_context_replay as replay
from tools.parity.filter_observation_import import typed_json


def test_generated_replay_worker_collects_authored_v2_without_mutation(
    pyapi_runner: Path,
    tmp_path: Path,
    v2_project: dict[str, Any],  # noqa: F811
    authored: tuple[dict[str, Any], dict[str, Any]],  # noqa: F811
) -> None:
    summary = v2_project["summary"]
    plan = replay.ReplayPlan(
        config={"project_sha256": summary["project_sha256"]},
        project=v2_project["project"],
        entry={},
        project_uuid=summary["project_uuid"],
        entry_key=summary["entry_key"],
        revision=summary["revision"],
        filter_uid=summary["filter_uid"],
        materialization_sha256=replay.digest(summary),
    )
    execute = runner(pyapi_runner, tmp_path, FACADE_PRELUDE)
    assert ok(execute(replay.build_script(plan, SOURCE))) == {
        "status": "captured",
        "outputs": 6,
        "restrictions": 12,
        "old_handles_refused": 3,
    }
    actual = json.loads((tmp_path / "filter-context-actual.json").read_text(encoding="utf-8"))
    replay.validate_actual(plan, actual)

    _, record = authored
    for index, recording in enumerate(record["recordings"], 1):
        leaves = {
            output["call"][len(replay.SOURCE) :]: output["value"]
            for output in recording["outputs"]
            if output["output_id"].startswith(f"context/pre16-r{index}/")
            and output.get("call", "").startswith(replay.SOURCE)
            and output["args"]["selector"] == FILTER_SOURCE
            and "raised" not in output
        }
        for number, getter in replay.GETTERS.items():
            key = f"r{index}/s{number}/{getter}"
            assert typed_json(actual["readbacks"][key]) == typed_json(leaves[getter])
        for number, getter in replay.RESTRICTIONS.items():
            error_type, message = (SINGLE if number == 19 else UNAVAILABLE).split(": ", 1)
            assert actual["restrictions"][f"r{index}/s{number}/{getter}"] == {
                "value": None,
                "raised": {"type": error_type, "message": message},
            }
    assert replay.file_hash(plan.project) == summary["project_sha256"]
