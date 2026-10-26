"""Authored V2 observed Filter through the native API and the facade (decision 363, item 2.6j).

`uzp-export-tests filter-observation-v2-fixture` imports the authored F capture into an original
authored H store through the real command (authored F pins through the test-only access, compiled H
policy) and leaves that V2 project in the work folder. The three Filter getters must then return
the authored observations, and everything else must keep the established Filter errors (steps
19-24 of the booleans probe) without changing the project. The expected values come from the
authored record's pre16 Filter source leaves, never from the getters under test. This is authored
evidence only: no Painter, no private data, no materialized original H.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.parity.test_filter_context_settings_validation import authored as authored
from tests.parity.test_filter_context_settings_validation import png_bytes
from tests.python.conftest import Run
from tests.python.test_pyapi_native import ok

PREFIX = "FILTER_OBSERVATION_V2_FIXTURE: "
SOURCE = "substance_painter.source.SourceSubstance."
FILTER_SOURCE = {"role": "filter", "source": True}
SINGLE = "EditionContextException: Only valid in single channel context"
UNAVAILABLE = "ValueError: Resolution property is not available on a FilterEffectNode."


def typed(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def authored_filter(record: dict[str, Any]) -> dict[str, Any]:
    """The authored record's pre16 Filter source leaves (equal in both rounds), as the getters must
    return them: typed parameters, the identity's parts and URL, and the image outputs."""
    rounds = []
    for index, recording in enumerate(record["recordings"]):
        boundary = f"context/pre16-r{index + 1}/"
        rounds.append(
            {
                output["call"][len(SOURCE) :]: output["value"]
                for output in recording["outputs"]
                if output["output_id"].startswith(boundary)
                and output.get("call", "").startswith(SOURCE)
                and output["args"]["selector"] == FILTER_SOURCE
                and "raised" not in output
            }
        )
    assert len(rounds) == 2 and typed(rounds[0]) == typed(rounds[1])
    leaves = rounds[0]
    identity = leaves["resource_id"]
    resource = identity["resource_id"]["resource"]
    return {
        "parameters": {
            name: [type(value).__name__, repr(value)]
            for name, value in leaves["get_parameters"].items()
        },
        "resource_id": [
            resource["context"],
            resource["name"],
            resource["version"],
            identity["url"],
        ],
        "image_outputs": list(leaves["image_outputs"]),
    }


@pytest.fixture
def v2_project(
    export_tests: Path,
    tmp_path: Path,
    authored: tuple[dict[str, Any], dict[str, Any]],  # noqa: F811
) -> dict[str, Any]:
    _, record = authored
    (tmp_path / "destination-record.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "destination-panel.png").write_bytes(png_bytes())
    result = subprocess.run(
        [str(export_tests), "filter-observation-v2-fixture", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summaries = [
        line[len(PREFIX) :] for line in result.stdout.splitlines() if line.startswith(PREFIX)
    ]
    assert len(summaries) == 1, result.stdout
    summary: dict[str, Any] = json.loads(summaries[0])
    assert summary["checks"] == 3 and summary["project"] == "cli-h-a.uzp", summary
    project = tmp_path / summary["project"]
    assert hashlib.sha256(project.read_bytes()).hexdigest() == summary["project_sha256"]
    return {"summary": summary, "project": project, "expected": authored_filter(record)}


SCRIPT = """
P = uzpainter.project
P.open(WORK + "/cli-h-a.uzp")

def nodes():
    host = ls.get_root_layer_nodes(ts.get_active_stack())[0]
    return host, host.content_effects()[0]

def typed(values):
    return {name: [type(value).__name__, repr(value)] for name, value in values.items()}

def identity(handle):
    rid = handle.resource_id if FACADE else handle.resource_id()
    return [type(rid).__name__, rid.context, rid.name, rid.version, rid.url()]

def observed(handle):
    return {
        "parameters": typed(handle.get_parameters()),
        "resource_id": identity(handle),
        "image_outputs": list(handle.image_outputs),
    }

def state():
    return [P.revision(), P.needs_saving()]

if FACADE:
    modes, override = source.ResolutionMode, source.ResolutionOverride
    custom = modes.Custom
else:
    modes, override = source._ResolutionMode, source._ResolutionOverride
    custom = modes.Manual

host, filter_ = nodes()
handle = filter_.get_source()
out = {"first": observed(handle), "start": state()}

# The booleans probe's steps 19-24 in recipe order, then the other refused operations; each
# refusal is followed by the project's revision and unsaved state.
operations = [
    ("s19 active_output", getattr, (handle, "active_output")),
    ("s20 resolution", getattr, (handle, "resolution")),
    ("s21 resolution Custom", setattr, (handle, "resolution", override(custom, (128, 128), 0))),
    ("s22 resolution", getattr, (handle, "resolution")),
    ("s23 resolution Auto", setattr, (handle, "resolution", override(modes.Auto, (128, 128), 0))),
    ("s24 resolution", getattr, (handle, "resolution")),
    ("active_output set", setattr, (handle, "active_output", "output")),
    ("set_parameters", handle.set_parameters, ({"integer": 1},)),
    ("set_unknown", handle.set_parameters, ({"unknown": 1},)),
    ("image_inputs", getattr, (handle, "image_inputs")),
]
out["operations"] = {name: [raises(call, *args), state()] for name, call, args in operations}
out["unchanged"] = observed(handle) == out["first"]

# After close and reopen, the old handle refuses; a fresh one serves the observation.
P.close()
P.open(WORK + "/cli-h-a.uzp")
out["old_after_reopen"] = raises(handle.get_parameters)
host, filter_ = nodes()
out["fresh_after_reopen"] = observed(filter_.get_source()) == out["first"]
out["reopened_state"] = state()
P.close()
result = out
"""


@pytest.mark.parametrize("api", ["run", "facade"])
def test_v2_observed_filter_serves_the_authored_observations_and_keeps_its_restrictions(
    api: str, request: pytest.FixtureRequest, v2_project: dict[str, Any]
) -> None:
    execute: Run = request.getfixturevalue(api)
    out: dict[str, Any] = ok(execute(f"FACADE = {api == 'facade'!r}\n" + SCRIPT))
    expected = v2_project["expected"]
    first = out["first"]
    assert first["parameters"] == expected["parameters"], first
    assert first["resource_id"][0] in {"_ObservedResourceID", "ObservedResourceID"}, first
    assert first["resource_id"][1:] == expected["resource_id"], first
    assert first["image_outputs"] == expected["image_outputs"], first

    start = out["start"]
    assert start == [v2_project["summary"]["revision"], False], start
    messages = out["operations"]
    for name in ("s19 active_output", "active_output set"):
        assert messages[name][0] == SINGLE, (name, messages[name])
    for name in (
        "s20 resolution",
        "s21 resolution Custom",
        "s22 resolution",
        "s23 resolution Auto",
        "s24 resolution",
    ):
        assert messages[name][0] == UNAVAILABLE, (name, messages[name])
    assert messages["set_parameters"][0].startswith("UnsupportedProcedural:"), messages
    assert messages["set_unknown"][0].startswith("ValueError: unknown procedural parameter"), (
        messages
    )
    assert messages["image_inputs"][0].startswith("UnsupportedProcedural:"), messages
    for name, (_, after) in messages.items():
        assert after == start, (name, after)
    assert out["unchanged"] is True

    assert out["old_after_reopen"].startswith("UnsupportedProcedural:"), out["old_after_reopen"]
    assert out["fresh_after_reopen"] is True
    assert out["reopened_state"] == start
    project: Path = v2_project["project"]
    assert (
        hashlib.sha256(project.read_bytes()).hexdigest() == v2_project["summary"]["project_sha256"]
    )
