"""Decision 202 part 5 (`tools/parity/ocio_srgb_part5.py`): the request for the pinned Tunic
stack's OCIO decode, the recorder's `color_from` resolution, and the qualifier's refusals.

The committed request holds references only. Synthetic stacks stand in for the private one, so
no test here reads or prints a private colour value; only the regeneration check reads the pinned
stack, and it is skipped on a machine without the private store.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tools.parity import ocio_srgb_part5 as part5
from tools.parity import ocio_srgb_table
from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import batch
from tools.parity.recorder.job import Step
from tools.parity.recorder.probes import (
    COLOR_FROM,
    ProbeSession,
    check_color_from,
    color_from_component,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.store import locate

STACK = part5.STACK_INPUT
PROBE_FAKE = "uzp_recorder_fake_probe_painter"
OCIO_CONFIG = "C:/Painter/resources/ocio/substance/config.ocio"
SET, GET = part5.SET_SOURCE, part5.GET_SOURCE


def f32(value: float) -> float:
    return float(struct.unpack("<f", struct.pack("<f", value))[0])


def committed() -> dict[str, Any]:
    manifest: dict[str, Any] = load_json(part5.request_path())
    return manifest


# --- the committed request ------------------------------------------------------------------


def test_the_request_holds_references_to_the_pinned_stack_only() -> None:
    manifest = committed()
    template = part5.current_template()
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["golden_id"] == part5.GOLDEN_ID and manifest["tier"] == "0"
    assert manifest["private_records"] == [] and manifest["expectations"] == []
    assert manifest["software"]["painter"]["build_id"] == current_envelope()["painter_build"]
    assert manifest["inputs"] == [*template["inputs"], part5.stack_item()]
    assert manifest["applied_settings"] == template["applied_settings"]
    steps = manifest["instruction_sequence"]["steps"]
    shape = [(s["call"], s["args"]) for s in template["instruction_sequence"]["steps"]]
    assert [(s["call"], s["args"]) for s in steps[:4]] == shape[:4]
    assert (steps[-1]["call"], steps[-1]["args"]) == shape[-1]
    assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))
    body = steps[4:-1]
    assert len(body) == 2 * part5.DOMAIN_INPUTS
    references = []
    for set_step, get_step in zip(body[::2], body[1::2], strict=True):
        assert set_step["call"] == SET and get_step["call"] == GET
        reference = set_step["args"].pop(COLOR_FROM)
        assert set_step["args"] == {
            "node_step": 3,
            "channel": "BaseColor",
            "color_space": "sRGB",
            "probe": True,
        }
        assert get_step["args"] == {"node_step": 3, "channel": "BaseColor"}
        assert reference[0] == STACK and all(type(i) is int for i in reference[1:])
        references.append(tuple(reference))
    assert len(set(references)) == part5.DOMAIN_INPUTS
    fresh = committed()["instruction_sequence"]["steps"]  # the loop above popped color_from
    assert all("color" not in s["args"] for s in fresh)
    assert all(COLOR_FROM in s["args"] for s in fresh if s["call"] == SET)


def test_the_request_does_not_load_without_the_pinned_stack() -> None:
    with pytest.raises(RecorderError, match="needs --assets-root"):
        probe_job_from_manifest(committed())


def test_the_batch_records_the_request_with_the_assets_root() -> None:
    path = part5.request_path()
    relative = path.relative_to(path.parents[2]).as_posix()
    item = batch.Item(batch.Request(path, relative, committed()), kind=batch.PROBE)
    command = batch.command(item, relative, "manifests")
    assert command[-2:] == ["--assets-root", batch.ASSETS]


def test_the_request_regenerates_from_the_pinned_stack(tmp_path: Path) -> None:
    store = locate()
    if store is None or not store.blob_path(part5.STACK_SHA256).is_file():
        pytest.skip("the pinned Tunic stack is private: no store copy on this machine")
    assert part5.generate(tmp_path) == part5.request_path().read_text(encoding="utf-8")


# --- the frozen baseline --------------------------------------------------------------------


def baseline_table() -> dict[int, int]:
    """Decision 202's 449 entries: the codes and the first 193 other recorded components,
    whatever later entries join the table."""
    source = ocio_srgb_table.load_source()
    baseline = {
        ocio_srgb_table._bits(c / 255): ocio_srgb_table._exact_f32(w)
        for c, w in enumerate(source.CODES)
    }
    for x, w in source.RECORDED[:193]:
        baseline[ocio_srgb_table._bits(x)] = ocio_srgb_table._exact_f32(w)
    return baseline


def test_the_449_baseline_entries_are_preserved() -> None:
    """The 449 entries stay exactly as frozen, whatever later entries join the table."""
    baseline = baseline_table()
    assert len(baseline) == part5.BASELINE_ENTRIES
    assert part5.pairs_digest(baseline) == part5.BASELINE_SHA256
    table = ocio_srgb_table.entries()
    assert {k: table[k] for k in baseline} == baseline


# --- color_from -----------------------------------------------------------------------------


def write_stack(directory: Path, layers: Any, raw: str | None = None) -> tuple[Path, str]:
    path = directory / "stack.json"
    path.write_text(raw if raw is not None else json.dumps({"layers": layers}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def colour_manifest(sha256: str, kind: str = "recipe_json") -> dict[str, Any]:
    item = {"input_id": STACK, "kind": kind, "path": "stack.json", "sha256": sha256}
    return {"inputs": [item]}


def set_step(reference: Any, **changes: Any) -> Step:
    args = {"node_step": 3, "channel": "BaseColor", COLOR_FROM: reference, "color_space": "sRGB"}
    return Step(5, SET, args | changes)


def test_color_from_reads_the_pinned_component(tmp_path: Path) -> None:
    path, sha = write_stack(tmp_path, [{"base": [0.25, 0.5, 0.75]}, {"base": [204, 51, 26]}])
    manifest, inputs = colour_manifest(sha), {STACK: path}
    assert check_color_from(set_step([STACK, 0, 2]), manifest, inputs) == 0.75
    assert check_color_from(set_step([STACK, 1, 1]), manifest, inputs) == 51 / 255
    assert (
        check_color_from(Step(6, GET, {"node_step": 3, "channel": "BaseColor"}), manifest, inputs)
        is None
    )


@pytest.mark.parametrize(
    ("reference", "match"),
    [
        ("tunic-stack", r"is \[input, layer, component\]"),
        ([STACK, 0], r"is \[input, layer, component\]"),
        ([[STACK], 0, 0], r"is \[input, layer, component\]"),
        ([{"a": 1}, 0, 0], r"is \[input, layer, component\]"),
        (["other", 0, 0], r"is \[input, layer, component\]"),
        ([STACK, True, 0], r"is \[input, layer, component\]"),
        ([STACK, -1, 0], r"is \[input, layer, component\]"),
        ([STACK, 0, 3], r"is \[input, layer, component\]"),
        ([STACK, 0, 1.0], r"is \[input, layer, component\]"),
        ([STACK, 9, 0], "has no layer 9"),
    ],
)
def test_color_from_refuses_a_malformed_reference(
    tmp_path: Path, reference: Any, match: str
) -> None:
    path, sha = write_stack(tmp_path, [{"base": [0.25, 0.5, 0.75]}])
    with pytest.raises(RecorderError, match=match):
        check_color_from(set_step(reference), colour_manifest(sha), {STACK: path})


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ('[{"base": [0.1, 0.2, 0.3]}]', "has no layer"),
        ('{"layers": {"0": {"base": [0.1, 0.2, 0.3]}}}', "has no layer"),
        ('{"layers": ["x"]}', "no uniform base"),
        ('{"layers": [{"base": [0.1, 0.2]}]}', "no uniform base"),
        ('{"layers": [{"base": [0.1, "0.2", 0.3]}]}', "no uniform base"),
        ('{"layers": [{"base": [0.1, true, 0.3]}]}', "no uniform base"),
        ('{"layers": [{"base": [0.1, 0.2, 0.3], "base_tex": "T"}]}', "no uniform base"),
        ('{"layers": [{"base": [0.1, NaN, 0.3]}]}', "non-finite"),
        ('{"layers": [{"base": [0.1, Infinity, 0.3]}]}', "non-finite"),
        ('{"layers": [{"base": [0.1, -0.2, 0.3]}]}', "outside"),
        ('{"layers": [{"base": [10, 300, 30]}]}', "outside"),
    ],
)
def test_color_from_refuses_a_stack_without_a_finite_uniform_base(
    tmp_path: Path, raw: str, match: str
) -> None:
    path, sha = write_stack(tmp_path, None, raw)
    with pytest.raises(RecorderError, match=match):
        check_color_from(set_step([STACK, 0, 0]), colour_manifest(sha), {STACK: path})


@pytest.mark.parametrize(
    ("step", "match"),
    [
        (
            Step(
                5,
                "substance_painter.layerstack.FillLayerNode.set_uniform_color",
                {COLOR_FROM: [STACK, 0, 0]},
            ),
            "is a set_source",
        ),
        (set_step([STACK, 0, 0], color=[0.1, 0.1, 0.1]), "is a set_source"),
        (set_step([STACK, 0, 0], color_space="Raw"), "sets an sRGB BaseColor"),
        (set_step([STACK, 0, 0], channel="Height"), "sets an sRGB BaseColor"),
    ],
)
def test_color_from_is_a_basecolor_srgb_set_source_only(
    tmp_path: Path, step: Step, match: str
) -> None:
    path, sha = write_stack(tmp_path, [{"base": [0.25, 0.5, 0.75]}])
    with pytest.raises(RecorderError, match=match):
        check_color_from(step, colour_manifest(sha), {STACK: path})


def test_color_from_refuses_another_kind_or_unpinned_bytes(tmp_path: Path) -> None:
    path, sha = write_stack(tmp_path, [{"base": [0.25, 0.5, 0.75]}])
    with pytest.raises(RecorderError, match=r"is \[input, layer, component\]"):
        check_color_from(set_step([STACK, 0, 0]), colour_manifest(sha, "mesh"), {STACK: path})
    with pytest.raises(RecorderError, match="differs from the pin"):
        check_color_from(set_step([STACK, 0, 0]), colour_manifest("0" * 64), {STACK: path})


# --- end to end against the fake Painter ----------------------------------------------------


@pytest.fixture
def probe_fake(fake: types.ModuleType) -> types.ModuleType:
    if PROBE_FAKE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PROBE_FAKE, Path(__file__).with_name("fake_probe_painter.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[PROBE_FAKE] = module
        spec.loader.exec_module(module)
    return sys.modules[PROBE_FAKE]


def test_painter_receives_the_grey_and_the_record_keeps_the_reference(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    plane = "parity/fixtures/meshes/plane.obj"
    (root / plane).parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / plane, root / plane)
    path, sha = write_stack(root, [{"base": [0.25, 0.5, 0.75]}, {"base": [0.75, 0.2, 0.25]}])
    item = {
        "input_id": STACK,
        "kind": "recipe_json",
        "path": "stack.json",
        "sha256": sha,
        "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
    }
    document = json.loads(path.read_bytes())
    manifest = part5.build_request(part5.references(document), item, part5.current_template())
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    job = probe_job_from_manifest(json.loads(json.dumps(manifest)), root)
    software = manifest["software"]["painter"]
    world = probe_fake.ProbeWorld()
    world.version, world.version_info = software["version"], (12, 2, 0)
    formats = {"BaseColor": "sRGB8", "Height": "L16F", "Normal": "RGB16F"}
    world.default_channels = {
        fake.ChannelType[name]: fake.ChannelFormat[formats.get(name, "L8")]
        for name in ("BaseColor", "BaseMetalness", "Height", "Normal", "SpecularRoughness")
    }
    monkeypatch.setenv("OCIO", OCIO_CONFIG)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda s: None,
        allowed_builds=lambda: frozenset({software["build_id"]}),
    )
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    record = json.loads((run / "record.json").read_text(encoding="utf-8"))
    steps = manifest["instruction_sequence"]["steps"]
    for recording_id in ("r1", "r2"):
        found = part5.outputs(record, recording_id)
        for step in (s for s in steps if COLOR_FROM in s["args"]):
            args = {k: v for k, v in step["args"].items() if k != "probe"}
            x = check_color_from(Step(step["step"], step["call"], args), manifest, {STACK: path})
            assert x is not None
            set_out = found[f"s{step['step']}/set_source"]
            assert set_out["args"][COLOR_FROM] == step["args"][COLOR_FROM]
            assert "color" not in set_out["args"]
            expected = fake.Color(x, x, x, fake.GenericColorSpace.sRGB).working
            got = found[f"s{step['step'] + 1}/get_source"]["value"]["uniform_color_working"]
            assert got == list(expected)


# --- the qualifier --------------------------------------------------------------------------

# 0.5 is a component of the 449-entry baseline; 0.625, 0.75 and 0.125 lie outside the table.
SYNTHETIC = [
    {"id": "a", "name": "A", "base": [0.625, 0.5, 0.75]},
    {"id": "b", "name": "B", "base": [0.75, 0.125, 0.625]},
]


@pytest.fixture
def synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """A synthetic stack and part-5 manifest, with the frozen digests re-pinned to its domain,
    against the invariant 449-entry baseline (not the live table, which grows): 0.5 is a
    baseline component (the control), the others are taken as new."""
    path, sha = write_stack(tmp_path, SYNTHETIC)
    document = json.loads(path.read_bytes())
    item = {
        "input_id": STACK,
        "kind": "recipe_json",
        "path": "stack.json",
        "sha256": sha,
        "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
    }
    refs = part5.references(document)
    manifest = part5.build_request(refs, item, part5.current_template())
    table = baseline_table()
    keys = [r.key for r in refs]
    control = [k for k in keys if k in table]
    new = [k for k in keys if k not in table]
    assert len(control) == 1 and control[0] == part5.f32_bits(0.5)
    monkeypatch.setattr(part5, "DOMAIN_INPUTS", len(keys))
    monkeypatch.setattr(part5, "NEW", len(new))
    monkeypatch.setattr(part5, "DOMAIN_SHA256", part5.keys_digest(keys))
    monkeypatch.setattr(part5, "CONTROL_SHA256", part5.keys_digest(control))
    monkeypatch.setattr(part5, "NEW_SHA256", part5.keys_digest(new))
    working = {
        k: struct.unpack(
            "<I", struct.pack("<f", f32(struct.unpack("<f", struct.pack("<I", k))[0] / 4))
        )[0]
        for k in new
    }
    working[control[0]] = table[control[0]]
    yield {"document": document, "manifest": manifest, "table": table, "working": working}


def bits_float(bits: int) -> float:
    return float(struct.unpack("<f", struct.pack("<I", bits))[0])


def synthetic_record(data: dict[str, Any]) -> dict[str, Any]:
    steps = data["manifest"]["instruction_sequence"]["steps"]
    kinds = {STACK: "recipe_json"}
    recordings = []
    for recording_id, condition in (("r1", "same_session"), ("r2", "after_save_reopen")):
        outs = []
        for index, step in enumerate(steps):
            if COLOR_FROM not in step["args"]:
                continue
            following = steps[index + 1]
            outs.append(part5.expected_output(step, "set_source") | {"value": None})
            reference = step["args"][COLOR_FROM]
            key = part5.f32_bits(color_from_component(reference, kinds, {STACK: data["document"]}))
            w = bits_float(data["working"][key])
            outs.append(
                part5.expected_output(following, "get_source")
                | {"value": {"uniform_color_working": [w, w, w]}}
            )
        recordings.append({"recording_id": recording_id, "condition": condition, "outputs": outs})
    return {"recordings": recordings}


def test_the_qualifier_derives_the_new_pairs(synthetic: dict[str, Any]) -> None:
    record = synthetic_record(synthetic)
    pairs = part5.record_pairs(synthetic["manifest"], record, synthetic["document"])
    assert pairs == synthetic["working"]
    before = part5.checked_mapping(pairs, synthetic["table"])  # the table of 449
    assert set(before) == set(pairs) - {part5.f32_bits(0.5)}
    extended = synthetic["table"] | before  # after the extension: the same pairs still qualify
    assert len(extended) == part5.BASELINE_ENTRIES + len(before)
    assert part5.checked_mapping(pairs, extended) == before


def first_output(record: dict[str, Any], recording: int, suffix: str) -> dict[str, Any]:
    outs = record["recordings"][recording]["outputs"]
    found: dict[str, Any] = next(o for o in outs if o["output_id"].endswith(suffix))
    return found


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (
            lambda r: first_output(r, 1, "/get_source")["value"][
                "uniform_color_working"
            ].__setitem__(0, 0.125),
            "no grey|differ",
        ),
        (
            lambda r: first_output(r, 0, "/get_source")["value"].__setitem__(
                "uniform_color_working", [0.1, 0.1, 0.1]
            ),
            "not a float32",
        ),
        (
            lambda r: first_output(r, 0, "/get_source")["value"].__setitem__(
                "uniform_color_working", [float("inf")] * 3
            ),
            "not a finite",
        ),
        (
            lambda r: first_output(r, 0, "/get_source")["value"].__setitem__(
                "uniform_color_working", [1, 1, 1]
            ),
            "not a finite",
        ),
        (
            lambda r: first_output(r, 0, "/set_source").__setitem__(
                "raised", {"type": "ValueError"}
            ),
            "is not the request's",
        ),
        (
            lambda r: first_output(r, 0, "/set_source")["args"].__setitem__("node_step", 4),
            "is not the request's",
        ),
        (
            lambda r: first_output(r, 0, "/set_source")["args"].__setitem__("color_space", "Raw"),
            "is not the request's",
        ),
        (
            lambda r: first_output(r, 0, "/get_source").__setitem__("call", SET),
            "is not the request's",
        ),
        (
            lambda r: first_output(r, 0, "/get_source").__setitem__("kind", "exported_map"),
            "is not the request's",
        ),
        (
            lambda r: r["recordings"][0]["outputs"].append(dict(r["recordings"][0]["outputs"][0])),
            "repeats",
        ),
        (lambda r: r["recordings"].pop(), "not r1 and r2"),
        (lambda r: r["recordings"][1].__setitem__("condition", "same_session"), "not r1 and r2"),
        (lambda r: r["recordings"][1]["outputs"].pop(), "is not the request's"),
    ],
)
def test_the_qualifier_refuses_a_record_that_is_not_the_request(
    synthetic: dict[str, Any], edit: Any, match: str
) -> None:
    record = synthetic_record(synthetic)
    edit(record)
    with pytest.raises(RecorderError, match=match):
        part5.record_pairs(synthetic["manifest"], record, synthetic["document"])


def test_the_qualifier_refuses_a_control_or_baseline_that_moved(synthetic: dict[str, Any]) -> None:
    pairs = dict(synthetic["working"])
    control = part5.f32_bits(0.5)
    with pytest.raises(RecorderError, match="control does not reproduce"):
        part5.checked_mapping(pairs | {control: pairs[control] + 1}, synthetic["table"])
    moved = dict(synthetic["table"])
    first = next(k for k in moved if k != control)
    moved[first] += 1
    with pytest.raises(RecorderError, match="not the 449-entry baseline"):
        part5.checked_mapping(pairs, moved)
    new = next(k for k in pairs if k != control)
    with pytest.raises(RecorderError, match="another value for a new input"):
        part5.checked_mapping(pairs, synthetic["table"] | {new: pairs[new] + 1})
    with pytest.raises(RecorderError, match="not the frozen domain"):
        part5.checked_mapping({k: v for k, v in pairs.items() if k != new}, synthetic["table"])


def supplement_of(data: dict[str, Any], working_of: Any) -> dict[str, Any]:
    layers = []
    for index, layer in enumerate(data["document"]["layers"]):
        working = [bits_float(working_of(part5.f32_bits(c))) for c in layer["base"]]
        layers.append(
            {
                "type": "FillLayer",
                "uid": 100 + index,
                "name": layer["name"],
                "active_channels": ["BaseColor"],
                "sources": {"BaseColor": {"source": {"uniform_color_working": working}}},
            }
        )
    state = {
        "output_id": "create/state",
        "value": {
            "texture_sets": {
                "S": {"stacks": {"": {"layers": [{"type": "GroupLayer", "sub_layers": layers}]}}}
            }
        },
    }
    report = {
        "output_id": "script/s2",
        "value": {
            "layers": [
                {"id": layer["id"], "uid": 100 + i}
                for i, layer in enumerate(data["document"]["layers"])
            ]
        },
    }
    return {
        "recordings": [
            {"recording_id": "r1", "outputs": [report, state]},
            {"recording_id": "r2", "outputs": [json.loads(json.dumps(state))]},
        ]
    }


def test_the_supplement_cross_check(synthetic: dict[str, Any]) -> None:
    working = synthetic["working"]
    assert (
        part5.supplement_pairs(supplement_of(synthetic, working.__getitem__), synthetic["document"])
        == working
    )
    other = supplement_of(synthetic, lambda k: working[k] + 1)
    assert part5.supplement_pairs(other, synthetic["document"]) != working
    split = supplement_of(synthetic, working.__getitem__)
    split["recordings"][1]["outputs"][0]["value"]["texture_sets"]["S"]["stacks"][""]["layers"][0][
        "sub_layers"
    ][0]["sources"]["BaseColor"]["source"]["uniform_color_working"][1] = 0.0
    with pytest.raises(RecorderError, match="r1 and r2 differ"):
        part5.supplement_pairs(split, synthetic["document"])


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), 1, True, "0.5", 0.1])
def test_a_readback_is_a_finite_float32(value: Any) -> None:
    with pytest.raises(RecorderError):
        part5.exact_f32_bits(value, "x")
