"""P22-B, layer stack, levels and colour (phase1.24 item 3.4, decision 296): the probe vocabulary,
its fake-Painter support and the six requests that exercise the pending Painter symbols of
`layerstack`, `levels` and `colormanagement`. `test_api_probes_phase1.py` validates and records
every request end to end; the tests here check what each one exercises and what it records
against the fake (`fake_probe_painter.py`, whose rules are its own, not Painter's).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import load_job
from tools.parity.recorder.probes import (
    EDIT_CALLS,
    GETTER_CALLS,
    ProbeSession,
    load_probe_job,
    record_probe_golden,
)
from tools.parity.recorder.provenance import documented_symbols
from tools.parity.schemas import REPO_ROOT, load_json, record_problems

REQUESTS = (
    REPO_ROOT
    / "parity"
    / "envelopes"
    / "painter-12.1.5_js-api.1.1.20"
    / "requests"
    / "tier0"
    / "api-probes"
)
MANIFESTS = REQUESTS.parents[2] / "manifests" / "tier0" / "api-probes"
INVENTORY = REPO_ROOT / "tools" / "capabilities" / "painter-api-inventory.json"
LS = "substance_painter.layerstack."
BUILD = "12.1.5+js-api.1.1.20"
PROBE_FAKE = "uzp_recorder_fake_probe_painter"

# The vocabulary decision 296 adds.
NEW_CALLS = {
    LS + "GroupLayerNode.set_collapsed",
    LS + "GroupLayerNode.is_collapsed",
    LS + "FillEffectNode.reset_source",
    LS + "FillEffectNode.set_symmetry_enabled",
    LS + "FillLayerNode.is_symmetry_enabled",
    LS + "FillEffectNode.is_symmetry_enabled",
    LS + "FillLayerNode.get_material_source",
    LS + "FillEffectNode.get_material_source",
    LS + "instantiate",
    LS + "insert_filter_effect",
    LS + "insert_generator_effect",
    LS + "InstanceLayerNode.instance_source",
    LS + "LayerNode.instances",
    LS + "Node.get_parent",
    LS + "Node.get_next_sibling",
    LS + "Node.get_previous_sibling",
    LS + "Node.get_texture_set",
    LS + "EffectNode",
    LS + "get_selected_nodes",
    LS + "set_selected_nodes",
    LS + "get_selection_type",
    LS + "set_selection_type",
    LS + "ScopedModification",
    "substance_painter.levels.LevelsParamsMono",
    "substance_painter.levels.LevelsParamsRGB",
    "substance_painter.colormanagement.Color.sRGB",
    "substance_painter.colormanagement.Color.value",
}

LAYER, MASK = "phase1-blending-modes-layer", "phase1-blending-modes-mask"
NAVIGATION, KINDS = "phase1-layer-navigation", "phase1-layer-node-kinds"
LEVELS, COLOUR = "phase1-levels-params", "phase1-color-srgb-value"

# Decision 296: the request that exercises each pending symbol of the four modules.
BLENDING_PENDING = [
    "Color",
    "ColorBurn",
    "ColorDodge",
    "Darken",
    "Difference",
    "Disable",
    "Divide",
    "Exclusion",
    "HardLight",
    "InverseDivide",
    "InverseSubtract",
    "Lighten",
    "LinearBurn",
    "LinearLight",
    "NormalMapCombine",
    "NormalMapInverseDetail",
    "Overlay",
    "PassThrough",
    "PinLight",
    "Replace",
    "Saturation",
    "SignedAddition",
    "SoftLight",
    "Subtract",
    "Tint",
    "Value",
    "VividLight",
]
LEVELS_FIELDS = ("clamp", "gamma", "input_max", "input_min", "output_max", "output_min")
REQUESTED: dict[str, str] = {
    **{f"{LS}BlendingMode.{name}": LAYER for name in BLENDING_PENDING},
    LS + "EffectNode": NAVIGATION,
    LS + "FillEffectNode.get_material_source": NAVIGATION,
    LS + "FillEffectNode.is_symmetry_enabled": NAVIGATION,
    LS + "FillEffectNode.reset_source": NAVIGATION,
    LS + "FillEffectNode.set_symmetry_enabled": NAVIGATION,
    LS + "FillLayerNode.get_material_source": NAVIGATION,
    LS + "FillLayerNode.is_symmetry_enabled": NAVIGATION,
    LS + "FilteringMode.BilinearSharp": NAVIGATION,
    LS + "GroupLayerNode.is_collapsed": NAVIGATION,
    LS + "GroupLayerNode.set_collapsed": NAVIGATION,
    LS + "InstanceLayerNode.instance_source": KINDS,
    LS + "LayerNode.instances": NAVIGATION,
    LS + "LevelsEffectNode.get_parameters": LEVELS,
    LS + "Node.get_next_sibling": NAVIGATION,
    LS + "Node.get_parent": NAVIGATION,
    LS + "Node.get_previous_sibling": NAVIGATION,
    LS + "Node.get_texture_set": NAVIGATION,
    LS + "NodeType.FilterEffect": KINDS,
    LS + "NodeType.GeneratorEffect": KINDS,
    LS + "NodeType.InstanceLayer": KINDS,
    LS + "NodeType.PaintEffect": KINDS,
    LS + "ProjectionMode.Fill": NAVIGATION,
    LS + "ScopedModification": NAVIGATION,
    LS + "SelectionType": NAVIGATION,
    **{
        f"{LS}SelectionType.{name}": NAVIGATION
        for name in ("Content", "Mask", "GeometryMask", "Properties")
    },
    LS + "get_selected_nodes": NAVIGATION,
    LS + "get_selection_type": NAVIGATION,
    LS + "set_selected_nodes": NAVIGATION,
    LS + "set_selection_type": NAVIGATION,
    "substance_painter.levels": LEVELS,
    **{
        f"substance_painter.levels.{kind}": LEVELS
        for kind in ("LevelsParamsMono", "LevelsParamsRGB")
    },
    **{
        f"substance_painter.levels.{kind}.{field}": LEVELS
        for kind in ("LevelsParamsMono", "LevelsParamsRGB")
        for field in LEVELS_FIELDS
    },
    "substance_painter.colormanagement.Color.sRGB": COLOUR,
    "substance_painter.colormanagement.Color.value": COLOUR,
}
# Decision 296 §2: no P22-B request; `properties.Property` is read by the recorded
# `tier0/defaults-templates/baking-defaults`, replayed once `BakingParameters` is implemented.
ROUTED = {
    "substance_painter.properties",
    "substance_painter.properties.Property",
    *(
        f"substance_painter.properties.Property.{name}"
        for name in (
            "enum_value",
            "enum_values",
            "label",
            "name",
            "properties",
            "short_name",
            "value",
            "widget_type",
        )
    ),
    # Demoted by 92f9ca13 when the trace began crediting the receiver's class: no P22-B request
    # sets a fill effect's projection; its evidence owner is the gap register
    # (phase5.3_parity-report-capability-gaps, inventory note).
    LS + "FillEffectNode.set_projection_parameters",
}
# Decision 189: exercised by decision 188's requests.
DECISION_188 = {
    LS + name
    for name in (
        "BlendingMode.Multiply",
        "FilteringMode.Nearest",
        "FillLayerNode.reset_source",
        "FillLayerNode.set_symmetry_enabled",
        "LayerNode.enable_mask",
        "LayerNode.remove_mask",
        "LayerNode.set_mask_background",
        "LevelsEffectNode",
        "LevelsEffectNode.affected_channel",
        "LevelsEffectNode.set_parameters",
        "NodeType.AnchorPointEffect",
        "NodeType.ColorSelectionEffect",
        "NodeType.CompareMaskEffect",
        "NodeType.LevelsEffect",
        "NodeType.PaintLayer",
    )
}
MODULES = ("layerstack", "levels", "properties", "colormanagement")
EFFECT_SOURCE_OWNER = "phase3.1_proc-backend-seam"
# Item 2.6c made these implemented-but-uncompared. Existing capture routes remain
# owned by 2.6; neither route establishes the full getter contract or Tier 0 parity.
EFFECT_SOURCE_ROUTES = {
    LS + "GeneratorEffectNode.get_source": (
        REQUESTS.parents[2]
        / "manifests/phase0/procedural-feasibility/position--sphere--defaults.json"
    ),
    LS + "FilterEffectNode.get_source": (
        REPO_ROOT
        / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7"
        / "manifests/tier0/api-probes/source-substance-booleans-filter.json"
    ),
}


def manifest(stem: str) -> dict[str, Any]:
    request = REQUESTS / f"{stem}.json"
    data: dict[str, Any] = load_json(request if request.is_file() else MANIFESTS / f"{stem}.json")
    return data


def steps(stem: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = manifest(stem)["instruction_sequence"]["steps"]
    return found


def documented_members(owner: str) -> list[str]:
    prefix = owner + "."
    return [s[len(prefix) :] for s in documented_symbols() if s.startswith(prefix)]


# --- what the requests exercise ---------------------------------------------------------------


def test_the_new_vocabulary_is_documented_and_every_call_is_requested() -> None:
    assert NEW_CALLS <= EDIT_CALLS | GETTER_CALLS
    assert set(documented_symbols()) >= NEW_CALLS
    used = {s["call"] for stem in set(REQUESTED.values()) for s in steps(stem)}
    assert used >= NEW_CALLS


def test_every_pending_symbol_of_the_group_is_requested_routed_or_already_requested() -> None:
    entries = json.loads(INVENTORY.read_text(encoding="utf-8"))["entries"]
    pending = {
        e["symbol"]
        for e in entries
        if e["status"] == "pending-evidence"
        and e["symbol"].split(".")[:2] in [["substance_painter", m] for m in MODULES]
    }
    assert pending <= set(REQUESTED) | ROUTED | DECISION_188 | set(EFFECT_SOURCE_ROUTES), sorted(
        pending - set(REQUESTED) - ROUTED - DECISION_188 - set(EFFECT_SOURCE_ROUTES)
    )
    assert not set(REQUESTED) & ROUTED


@pytest.mark.parametrize("symbol", EFFECT_SOURCE_ROUTES)
def test_effect_source_routes_keep_their_pending_owner_and_exercise_the_getter(symbol: str) -> None:
    entries = json.loads(INVENTORY.read_text(encoding="utf-8"))["entries"]
    entry = next(e for e in entries if e["symbol"] == symbol)
    assert entry["status"] == "pending-evidence"
    assert EFFECT_SOURCE_OWNER in entry["notes"]
    owner = (REPO_ROOT / ".rulebook/tasks" / EFFECT_SOURCE_OWNER / "tasks.md").read_text(
        encoding="utf-8"
    )
    assert "2.6c Stored generator/filter effect sources" in owner
    assert symbol.removeprefix(LS) in owner
    assert not set(EFFECT_SOURCE_ROUTES) & (set(REQUESTED) | ROUTED | DECISION_188)
    path = EFFECT_SOURCE_ROUTES[symbol]
    if symbol == LS + "GeneratorEffectNode.get_source":
        job = load_job(path)
        inserted = {s.step for s in job.state_steps if s.call == LS + "insert_generator_effect"}
        assert inserted
        assert any(
            spec["call"] == symbol and spec["args"]["node_step"] in inserted
            for spec in job.readback_specs()
        )
    else:
        data = load_json(path)
        sequence = data["instruction_sequence"]["steps"]
        inserted = {s["step"] for s in sequence if s["call"] == LS + "insert_filter_effect"}
        assert inserted
        assert any(
            s["call"] == "substance_painter.source.SourceSubstance.get_parameters"
            and s["args"].get("effect") is True
            and s["args"]["node_step"] in inserted
            for s in sequence
        )


def test_each_requested_symbol_is_named_by_its_request() -> None:
    """A call is a step of its request; an enum member is passed by one; a class, a module, a
    field or a returned enum member is named in the request's description."""
    for symbol, stem in REQUESTED.items():
        data = manifest(stem)
        calls = {s["call"] for s in steps(stem)}
        values = {json.dumps(v) for s in steps(stem) for v in s["args"].values()}
        short = symbol.rsplit(".", 1)[1]
        owner = symbol.rsplit(".", 2)[-2]
        named = short in data["description"] or owner in data["description"]
        assert symbol in calls or json.dumps(short) in values or named, symbol


@pytest.mark.parametrize(("stem", "channel"), [(LAYER, "BaseColor"), (MASK, None)])
def test_every_blending_mode_member_is_set_then_read_back(stem: str, channel: str | None) -> None:
    sequence = steps(stem)
    sets = [
        (i, s)
        for i, s in enumerate(sequence)
        if s["call"] == LS + "Node.set_blending_mode" and s["args"].get("channel") == channel
    ]
    swept = [s["args"]["blending_mode"] for _, s in sets]
    assert sorted(set(swept)) == sorted(documented_members(LS + "BlendingMode"))
    for index, step in sets:
        following = sequence[index + 1]
        assert step["args"]["probe"] is True
        assert following["call"] == LS + "Node.get_blending_mode"
        assert following["args"].get("channel") == channel
        assert following["args"]["node_step"] == step["args"]["node_step"]


def test_levels_parameters_are_built_with_every_field_away_from_its_default() -> None:
    built = [s for s in steps(LEVELS) if s["call"].startswith("substance_painter.levels.")]
    assert {s["call"].rsplit(".", 1)[1] for s in built} == {"LevelsParamsMono", "LevelsParamsRGB"}
    for step in built:
        args = step["args"]
        assert set(args) == {"node_step", "probe", *LEVELS_FIELDS}
        assert args["clamp"] is True and args["gamma"] not in (1.0, [1.0, 1.0, 1.0])
        rgb = step["call"].endswith("RGB")
        for field in ("input_min", "input_max", "output_min", "output_max", "gamma"):
            assert isinstance(args[field], list) == rgb


# --- recording against the fake ---------------------------------------------------------------


@pytest.fixture
def probe_fake(fake: types.ModuleType) -> types.ModuleType:
    """`fake_probe_painter.py`, loaded by path after `fake_painter.py` (which it extends)."""
    if PROBE_FAKE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PROBE_FAKE, Path(__file__).with_name("fake_probe_painter.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[PROBE_FAKE] = module
        spec.loader.exec_module(module)
    return sys.modules[PROBE_FAKE]


def recorded(
    probe_fake: types.ModuleType, fake: types.ModuleType, stem: str, tmp_path: Path
) -> list[dict[str, Any]]:
    """`r1` and `r2` of one request recorded against a fake Painter of the request's build."""
    world = probe_fake.ProbeWorld()
    world.version, world.version_info = "12.1.5", (12, 1, 5)
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda s: None,
        allowed_builds=lambda: frozenset({BUILD}),
    )
    request = REQUESTS / f"{stem}.json"
    job = load_probe_job(request if request.is_file() else MANIFESTS / f"{stem}.json")
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    return [{o["output_id"]: o for o in r["outputs"]} for r in data["recordings"]]


@pytest.mark.parametrize("stem", [LAYER, MASK])
def test_blending_modes_read_back_what_was_set(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path, stem: str
) -> None:
    sets = [s for s in steps(stem) if s["call"] == LS + "Node.set_blending_mode"]
    for recording in recorded(probe_fake, fake, stem, tmp_path):
        for step in sets:
            mode = step["args"]["blending_mode"]
            outcome = recording[f"s{step['step']}/set_blending_mode"]
            readback = recording[f"s{step['step'] + 1}/get_blending_mode"]
            if mode == "PassThrough":  # the fake has no such member (its rule)
                assert outcome["raised"]["type"] == "AttributeError"
            else:
                assert "raised" not in outcome and readback["value"] == mode


def by_call(recording: dict[str, Any], call: str) -> list[Any]:
    return [o for o in recording.values() if o.get("call") == call and "raised" not in o]


def test_navigation_records_the_tree_collapse_symmetry_and_sources(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    for recording in recorded(probe_fake, fake, NAVIGATION, tmp_path):
        parents = [o["value"] for o in by_call(recording, LS + "Node.get_parent")]
        assert parents[0] is None and parents[1]["name"] == "uzp group"
        effect = {o["args"]["node_step"]: o["value"] for o in by_call(recording, LS + "EffectNode")}
        assert sorted(step for step, is_effect in effect.items() if is_effect) == [14, 17, 19]
        assert {o["value"] for o in by_call(recording, LS + "Node.get_texture_set")} == {
            "uzp_plane"
        }
        assert [o["value"] for o in by_call(recording, LS + "GroupLayerNode.is_collapsed")][1:] == [
            True,
            False,
        ]
        symmetry = [
            o["value"] for o in by_call(recording, LS + "FillEffectNode.is_symmetry_enabled")
        ]
        assert symmetry[1:3] == [True, False]
        material = [
            o
            for o in recording.values()
            if o.get("call", "").endswith("get_material_source") and "raised" in o
        ]
        assert len(material) == 4
        assert recording["s81/get_projection_mode"]["value"] == "Fill"
        filtering = [
            o["value"]["filtering_mode"]
            for o in by_call(recording, LS + "FillLayerNode.get_projection_parameters")
        ]
        assert filtering == ["BilinearHQ", "BilinearSharp", "Nearest"]


def test_navigation_records_the_selection_and_the_scoped_modification(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    recordings = recorded(probe_fake, fake, NAVIGATION, tmp_path)
    for recording in recordings:
        selected = [
            [node["name"] for node in o["value"]]
            for o in by_call(recording, LS + "get_selected_nodes")
        ]
        # The scoped rename of r1 is saved, so r2 lists fill 1 under its new name.
        fill1 = "uzp fill 1" if recording is recordings[0] else "uzp fill 1 scoped"
        assert selected[1:4] == [
            [fill1, "uzp fill 2"],
            ["uzp content fill", "uzp levels"],
            ["uzp fill 3"],
        ]
        kinds = [o["value"] for o in by_call(recording, LS + "get_selection_type")]
        assert kinds == ["Content", "Mask", "GeometryMask", "GeometryMask"]
        properties = [o for o in recording.values() if o.get("call") == LS + "set_selection_type"]
        assert properties[-1]["raised"]["type"] == "ValueError"  # not an instance (fake's rule)
        scoped = by_call(recording, LS + "ScopedModification")[0]["value"]
        assert scoped["inside"]["set_name"] is None
        for call in ("set_selected_nodes", "set_selection_type"):
            assert scoped["inside"][call]["raised"]["type"] == "RuntimeError"
        assert scoped["get_name_after"] == "uzp fill 1 scoped"
        assert by_call(recording, LS + "Node.get_opacity")[0]["value"] == 0.25


def test_node_kinds_record_paint_filter_generator_and_instances(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = recorded(probe_fake, fake, KINDS, tmp_path)
    for index, recording in enumerate((first, second)):
        types_read = [o["value"] for o in by_call(recording, LS + "Node.get_type")]
        assert types_read == [
            "PaintEffect",
            "FilterEffect",
            "GeneratorEffect",
            "FillLayer",
            "InstanceLayer",
        ]
        source = by_call(recording, LS + "InstanceLayerNode.instance_source")[0]["value"]
        assert source == {"name": "uzp fill", "node_type": "FillLayer"}
        # Step 17 instantiates in both recordings and r1's instance is saved with the project, so
        # the instances accumulate by design (SUP-013, decision 296 item 4): s16 holds r1 = 0,
        # r2 = 1 (the saved instance found again right after reopen, before the second
        # instantiate), and s20 holds r1 = 1, r2 = 2.
        instances = [o["value"] for o in by_call(recording, LS + "LayerNode.instances")]
        assert [len(found) for found in instances] == [index, index + 1]
        assert {i["node_type"] for found in instances for i in found} <= {"InstanceLayer"}
        assert by_call(recording, LS + "get_selection_type")[0]["value"] == "Properties"
    saved = by_call(first, LS + "LayerNode.instances")[1]["value"]
    assert by_call(second, LS + "LayerNode.instances")[0]["value"] == saved


def test_an_instance_keeps_its_source_across_save_and_reopen(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """SUP-013: the fake saves the instance-source relation and remaps it to the reloaded nodes'
    uids, checked directly after one reopen (no second instantiate to hide a loss)."""
    world = probe_fake.ProbeWorld()
    with fake.installed(world):
        layerstack = world.modules[LS.rstrip(".")]
        project = world.modules["substance_painter.project"]
        mesh = REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj"
        project.create(mesh_file_path=str(mesh), settings=project.Settings())
        stack = world.modules["substance_painter.textureset"].get_active_stack()
        fill = layerstack.insert_fill(layerstack.InsertPosition.from_textureset_stack(stack))
        fill.set_name("uzp fill")
        instance = layerstack.instantiate(layerstack.InsertPosition.below_node(fill), fill)
        path = (tmp_path / "instance.spp").as_posix()
        project.save_as(path, project.ProjectSaveMode.Full)
        project.close()
        project.open(path)
        roots = layerstack.get_root_layer_nodes(stack)
        assert [n.get_type().name for n in roots] == ["FillLayer", "InstanceLayer"]
        assert roots[1].uid() != instance.uid()  # the fake renumbers on reopen
        assert roots[1].instance_source().get_name() == "uzp fill"
        assert [n.uid() for n in roots[0].instances()] == [roots[1].uid()]


def test_levels_record_the_class_and_every_field(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    built = [s for s in steps(LEVELS) if s["call"].startswith("substance_painter.levels.")]
    for recording in recorded(probe_fake, fake, LEVELS, tmp_path):
        for step in built:
            kind = step["call"].rsplit(".", 1)[1]
            value = recording[f"s{step['step']}/{kind}"]["value"]
            assert value["class"] == kind
            assert {f: value[f] for f in LEVELS_FIELDS} == {
                f: step["args"][f] for f in LEVELS_FIELDS
            }
            readback = recording[f"s{step['step'] + 1}/get_parameters"]["value"]
            assert readback["clamp"] is True


def test_colour_conversions_are_recorded(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    srgb, value = (
        "substance_painter.colormanagement.Color.sRGB",
        ("substance_painter.colormanagement.Color.value"),
    )
    sequence = steps(COLOUR)
    for recording in recorded(probe_fake, fake, COLOUR, tmp_path):
        for step in sequence:
            output = recording.get(f"s{step['step']}/{step['call'].rsplit('.', 1)[1]}")
            if step["call"] not in (srgb, value):
                continue
            assert output is not None
            args = step["args"]
            spaceless = "node_step" not in args and "color_space" not in args
            if spaceless and (step["call"] == srgb):
                assert output["raised"]["type"] == "RuntimeError"  # documented: no colour space
            else:
                assert "raised" not in output, step
        assigned = [s for s in sequence if s["call"] == srgb and "node_step" in s["args"]]
        for step in (s for s in assigned if "value" in s["args"]):
            reread = recording[f"s{step['step'] + 2}/sRGB"]["value"]
            assert reread == pytest.approx(step["args"]["value"])
