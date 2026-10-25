"""Observed Filter sources (decision 362, phase3.1 item 2.6h).

The test-only importer `uzp-export-tests filter-observation-import` takes one closed payload
(`uzpainter/filter-observation-import/2`): here a synthetic, authored receipt with placeholder
values (no Painter record), built from the real core serializations of the target project
(`filter-observation-base`) and of the effects fixture's host and Filter, never a canned path.
The three Filter getters then return the receipt's raw typed values through the handle's lease;
everything else refuses, before any change.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.export.conftest import export_tests as export_tests
from tests.parity.test_filter_observation_import import (
    install_authored_envelope,
    receipt,
    synthetic_inputs,
)
from tests.python.conftest import Run
from tests.python.test_pyapi_native import ok
from tools.parity import filter_observation_import as importer

HASH_PARAMETERS = {"seed": 3, "gain": -0.0}  # the synthetic receipt's public placeholder values


def tool(exe: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(exe), *args], capture_output=True, text=True, timeout=120, check=False
    )


def base(exe: Path, project: Path, out: Path) -> dict[str, Any]:
    process = tool(exe, "filter-observation-base", str(project), str(out))
    assert process.returncode == 0, process.stdout + process.stderr
    result: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return result


def ids(target: dict[str, Any]) -> tuple[int, int]:
    """The texture set uzp_plane and its one stack (holding the control's User0 L32F channel)."""
    (texture_set,) = [s for s in target["projection"]["texture_sets"] if s["name"] == "uzp_plane"]
    (stack,) = texture_set["stacks"]
    return int(texture_set["id"]), int(stack["id"])


@pytest.fixture
def observed_project(
    run: Run,
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """A project built as the authored control's base (plane at 256, OpenGL, Painter's OCIO
    config, an explicit User0 L32F channel, no layer), its native base, and the payload that the
    shared builder (tools/parity/filter_observation_import.build_payload, the same one as for
    admitted captures) derives from the synthetic receipt of tests/parity for that base."""
    script = (
        "project.create(PLANE, settings=project.Settings("
        "normal_map_format=project.NormalMapFormat.OpenGL, default_texture_resolution=256, "
        f"ocio_config_hash={PAINTER_OCIO_CONFIG_SHA256!r}))\n"
        """stack = ts.get_active_stack()
stack.add_channel(CT.User0, ts.ChannelFormat.L32F)
# The V1 domain holds the imported host Fill alone: the created project's default layer goes.
for node in ls.get_root_layer_nodes(stack):
    ls.delete_node(node)
# A context value the getter test edits and restores (outside the stack).
project.Metadata("uzpainter.test").set("edit", 0)
project.save_as(WORK + "/observed.uzp")
project.close()
result = True
"""
    )
    ok(run(script))
    observed = tmp_path / "observed.uzp"
    target = base(export_tests, observed, tmp_path / "base.json")
    store = install_authored_envelope(monkeypatch)
    manifest, record, _ = synthetic_inputs()
    data = receipt(manifest, record)
    texture_set, stack = ids(target)
    built = importer.build_payload(
        manifest, data, target, texture_set=texture_set, stack=stack, store=store
    )
    # One JSON round trip: no shared Python objects between payload members.
    document = json.loads(json.dumps(built))
    return {"target": target, "payload": document, "path": observed}


def test_the_base_export_fails_when_it_cannot_write(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    observed_project: dict[str, Any],
) -> None:
    """An output path whose folder does not exist gives a non-zero exit and no success line; the
    project is unchanged."""
    unwritable = tmp_path / "no-such-folder" / "base.json"
    process = tool(
        export_tests, "filter-observation-base", str(observed_project["path"]), str(unwritable)
    )
    assert process.returncode != 0, process.stdout + process.stderr
    assert "observation base: projection" not in process.stdout, process.stdout
    assert not unwritable.exists()
    after = base(export_tests, observed_project["path"], tmp_path / "after.json")
    assert after["projection_sha256"] == observed_project["target"]["projection_sha256"]


def set_reference_parameters(p: dict[str, Any], parameters: dict[str, Any]) -> None:
    """The Filter reference's parameters, coherently in filter_state, host_state and the expected
    projection (descriptors and readbacks unchanged)."""
    p["filter_state"]["procedural"]["params"] = parameters
    p["host_state"]["content_effects"][0]["procedural"]["params"] = parameters
    for texture_set in p["expected_projection"]["texture_sets"]:
        for stack in texture_set["stacks"]:
            for layer in stack["root_layers"]:
                layer["content_effects"][0]["procedural"]["params"] = parameters


def test_the_importer_refuses_a_payload_that_does_not_hold(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    observed_project: dict[str, Any],
) -> None:
    """Each check of the closed importer refuses before anything is committed (the base projection
    is unchanged)."""
    good: dict[str, Any] = observed_project["payload"]

    def unknown(p: dict[str, Any]) -> None:
        p["extra"] = 1

    def recipe_hash(p: dict[str, Any]) -> None:
        p["recipe"]["body"]["applied_settings"] = ["changed"]

    def unpaired(p: dict[str, Any]) -> None:
        p["readbacks"]["after_save_reopen"]["parameters"] = {**HASH_PARAMETERS, "gain": 0.0}

    def disagree(p: dict[str, Any]) -> None:
        for block in p["readbacks"].values():
            block["parameters"] = {**HASH_PARAMETERS, "seed": 4}

    def projection(p: dict[str, Any]) -> None:
        p["expected_projection"]["next_id"] += 1

    def base_hash(p: dict[str, Any]) -> None:
        p["target"]["preimport_projection_sha256"] = "0" * 64

    def filter_state(p: dict[str, Any]) -> None:
        p["filter_state"]["name"] = "another"

    def reference(p: dict[str, Any]) -> None:
        # A coherent projection whose Filter reference disagrees with the descriptor by value:
        # only the shared lookup before the commit catches it.
        set_reference_parameters(p, {**HASH_PARAMETERS, "seed": 5})

    expected = {
        "unknown member": (unknown, "unknown member"),
        "recipe hash": (recipe_hash, "recipe.sha256"),
        "unpaired readbacks": (unpaired, "paired readbacks differ"),
        "readback disagreement": (disagree, "readbacks.parameters"),
        "projection": (projection, "expected_projection"),
        "base": (base_hash, "pre-import base"),
        "filter state": (filter_state, "filter_state"),
        "descriptor and reference disagree": (reference, "does not resolve"),
    }
    before = observed_project["target"]["projection_sha256"]
    for case, (change, text) in expected.items():
        broken = copy.deepcopy(good)
        change(broken)
        path = tmp_path / f"{case.replace(' ', '-')}.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        process = tool(
            export_tests, "filter-observation-import", str(observed_project["path"]), str(path)
        )
        output = process.stdout + process.stderr
        assert process.returncode != 0 and text in output, (case, output)
        after = base(export_tests, observed_project["path"], tmp_path / "after.json")
        assert after["projection_sha256"] == before, case


SCRIPT = """
P = uzpainter.project
P.open(WORK + "/observed.uzp")

def nodes():
    host = ls.get_root_layer_nodes(ts.get_active_stack())[0]
    return host, host.content_effects()[0]

def typed(values):
    return {name: [type(value).__name__, repr(value)] for name, value in values.items()}

def identity(source):
    rid = source.resource_id if FACADE else source.resource_id()
    return [type(rid).__name__, rid.context, rid.name, rid.version, rid.url()]

def observed(source):
    return {
        "parameters": typed(source.get_parameters()),
        "resource_id": identity(source),
        "image_outputs": list(source.image_outputs),
    }

host, filter_ = nodes()
source = filter_.get_source()
out = {"first": observed(source)}

# Everything else refuses before any change (the Filter's established errors first).
revision = P.revision()
out["refusals"] = {
    "set_parameters": raises(source.set_parameters, {"seed": 3}),
    "set_parameters_type": raises(source.set_parameters, {"gain": [1]}),
    # Per-parameter types from the bound descriptor's raw typed parameters (never the core ref).
    "set_bool_for_int": raises(source.set_parameters, {"seed": True}),
    "set_int_for_double": raises(source.set_parameters, {"gain": 2}),
    "set_unknown": raises(source.set_parameters, {"unknown": 1}),
    "active_output_get": raises(getattr, source, "active_output"),
    "active_output_set": raises(setattr, source, "active_output", "output"),
    "resolution_get": raises(getattr, source, "resolution"),
    "image_inputs": raises(getattr, source, "image_inputs"),
    "host_parameters": raises(host.get_source(ts.ChannelType.User0).get_parameters),
    "dump_recipe": raises(P.dump_recipe),
}
out["unchanged"] = P.revision() == revision

# The upstream edit is a project metadata value seeded in the base ("edit": 0): it is part of the
# context and outside the stack (an edit of the stack itself is refused by the support gate while
# it holds a non-executable observed host).
M = P.Metadata("uzpainter.test")
# Inside one native Transaction the getters read its working copy: a pending edit refuses,
# restoring the exact value in the same transaction serves, and a deliberate exception rolls the
# whole transaction back, the pre-existing handle serving again.
class Deliberate(Exception):
    pass
pending = {}
def in_transaction():
    with uzpainter.Transaction("observation working copy"):
        M.set("edit", 1)
        pending["stale"] = raises(source.get_parameters)
        M.set("edit", 0)
        pending["restored"] = typed(source.get_parameters()) == out["first"]["parameters"]
        M.set("edit", 2)
        raise Deliberate("rollback")
revision = P.revision()
pending["raised"] = raises(in_transaction)
pending["rolled_back"] = P.revision() == revision and M.get("edit") == 0
pending["after"] = observed(source) == out["first"]
out["transaction"] = pending

# An upstream edit makes the entry stale: the getters refuse, saving still works, and the same
# open project restored to the exact context serves the observation again.
M.set("edit", 1)
out["stale"] = raises(source.get_parameters)
# A handle created while the entry is stale still captures its lease (structural binding), so it
# serves the observation once the exact context is restored.
created_stale = nodes()[1].get_source()
out["created_stale"] = raises(created_stale.get_parameters)
P.save()
out["saved_stale"] = True
M.set("edit", 0)
out["restored"] = observed(source)["parameters"] == out["first"]["parameters"]
out["created_stale_restored"] = observed(created_stale) == out["first"]
P.save()

# After close and reopen, the old handle refuses; a fresh one serves the observation.
P.close()
P.open(WORK + "/observed.uzp")
out["old_after_reopen"] = raises(source.get_parameters)
host, filter_ = nodes()
out["fresh_after_reopen"] = observed(filter_.get_source()) == out["first"]
P.close()
result = out
"""


@pytest.mark.parametrize("api", ["run", "facade"])
def test_observed_filter_getters_return_the_receipt_and_refuse_everything_else(
    api: str,
    request: pytest.FixtureRequest,
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    observed_project: dict[str, Any],
) -> None:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(observed_project["payload"]), encoding="utf-8")
    imported = tool(
        export_tests, "filter-observation-import", str(observed_project["path"]), str(path)
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr

    execute: Run = request.getfixturevalue(api)
    out: dict[str, Any] = ok(execute(f"FACADE = {api == 'facade'!r}\n" + SCRIPT))
    first = out["first"]
    # The synthetic receipt's public placeholder values (tests/parity), typed.
    assert first["parameters"] == {"gain": ["float", "-0.0"], "seed": ["int", "3"]}, first
    assert first["resource_id"][1:] == [
        "starter_assets",
        "synthetic/internal/filter",
        "synthetic-v1",
        "resource://synthetic/filter?version=synthetic-v1",
    ], first
    assert first["resource_id"][0] in {"_ObservedResourceID", "ObservedResourceID"}, first
    assert first["image_outputs"] == [], first  # observed empty for the Filter

    refusals = out["refusals"]
    assert refusals["set_parameters"].startswith("UnsupportedProcedural:"), refusals
    assert refusals["set_parameters_type"].startswith("TypeError:"), refusals
    assert refusals["set_bool_for_int"] == (
        "TypeError: Bad value for property 'seed': expected value of type <int32> but got <bool>."
    ), refusals
    assert (
        refusals["set_int_for_double"] == "TypeError: procedural parameter type mismatch: gain"
    ), refusals
    assert refusals["set_unknown"].startswith("ValueError: unknown procedural parameter"), refusals
    # The established Filter errors of source-substance-booleans-filter (steps 19-24) come first.
    single = "EditionContextException: Only valid in single channel context"
    assert refusals["active_output_get"] == single, refusals
    assert refusals["active_output_set"] == single, refusals
    unavailable = "ValueError: Resolution property is not available on a FilterEffectNode."
    assert refusals["resolution_get"] == unavailable, refusals
    assert refusals["image_inputs"].startswith("UnsupportedProcedural:"), refusals
    assert refusals["host_parameters"].startswith("UnsupportedProcedural:"), refusals
    assert "decision 362" in refusals["dump_recipe"], refusals
    assert out["unchanged"] is True

    transaction = out["transaction"]
    assert transaction["stale"].startswith("UnsupportedProcedural:"), transaction
    assert transaction["restored"] is True, transaction
    assert transaction["raised"] == "Deliberate: rollback", transaction
    assert transaction["rolled_back"] is True and transaction["after"] is True, transaction
    assert out["stale"].startswith("UnsupportedProcedural:"), out["stale"]
    assert out["created_stale"].startswith("UnsupportedProcedural:"), out["created_stale"]
    assert out["saved_stale"] is True
    assert out["restored"] is True
    assert out["created_stale_restored"] is True
    assert out["old_after_reopen"].startswith("UnsupportedProcedural:"), out["old_after_reopen"]
    assert out["fresh_after_reopen"] is True
