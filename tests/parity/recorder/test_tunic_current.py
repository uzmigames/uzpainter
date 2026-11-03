"""The Tunic v10 current-round request (`tunic_current.py`; decision 300 items 7-8), over a
stand-in asset repository that is a git repository (the sync scripts and the report are read as
raw blobs of one commit), a temporary private store holding stand-in preserved masks and Normal,
and producer records in their producers' real shapes (front U3's export records, front U4's AO
and masks records, each r1 and its repeat, with their outputs beside them): authored fixtures,
never real evidence. The export configuration is the repository's pinned file, except where a
recording through the fake Painter needs a preset it can export."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.parity.recorder.test_sash_current import blob, git, hexes, out, png, sha256
from tests.parity.recorder.test_script_run import (  # noqa: F401  (`painter` is a fixture)
    CLOSURE,
    CURRENT_LAYER_STACK,
    LAYER_STACK_PATH,
    NATIVE_LAYER_STACK,
    painter,
    write,
)
from tools.parity.recorder import session as session_module
from tools.parity.recorder import tunic, tunic_current
from tools.parity.recorder.sash_current import Blob
from tools.parity.recorder.script_run import (
    CONFIG_EXPORT,
    NATIVE_CREATE,
    RUN_SCRIPT,
    MissingInputs,
    NativeJob,
    ScriptSession,
    pipeline_job_from_manifest,
    record_script_golden,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.recorder.tunic_current import (
    AO_OUTPUT,
    INPUTS_SCHEMA,
    MASKS,
    PRESERVED_ROLE,
    RECEIPTS,
    Pins,
    current_request,
)
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors
from tools.parity.store.store import STORE_ENV, OracleStore, Status
from tools.parity.tier1 import tunic_ao, tunic_masks
from tools.parity.tier1 import tunic_ao_blender as ao_side
from tools.parity.tier1 import tunic_low_blender as low_side
from tools.parity.tier1.tunic_ao import LowPins

BUILD = "12.2.0+js-api.1.1.20"
RES = 8  # the stand-in resolution (the real pin is 4096)
SUBSTITUTES = tunic_masks.SUBSTITUTES
DISCARDED = tunic_masks.DISCARDED
PRESERVED = sorted(tunic.RECOVERED)
MTL = "# Blender 5.2 MTL File: 'stand-in'\nnewmtl DefaultMaterial\n"
Files = dict[str, dict[str, str]]
Change = Callable[[dict[str, Any]], None]


@pytest.fixture(autouse=True)
def no_private_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No machine store: every test passes its own."""
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))


def obj_text(library: str = low_side.MTL_NAME) -> str:
    return f"# Blender 5.2\nmtllib {library}\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nf 1 2 3\n"


def preserved_png(name: str) -> bytes:
    return png(RES, 16, 0, 100 + PRESERVED.index(name))


def normal_png() -> bytes:
    return png(RES, 16, 2, 200)


def substitute_png(name: str) -> bytes:
    return png(RES, 16, 0, 30 + SUBSTITUTES.index(name))


def discarded_png(name: str) -> bytes:
    return png(RES, 16, 0, 60 + DISCARDED.index(name))


def sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def resource(name: str, data: bytes) -> str:
    return f"resource://project8/{name}?version={sha1(data)}.image"


def stand_in_report() -> dict[str, Any]:
    """A report in the committed report's shape: the recipe (F03 and C07 both binding M_piping),
    the F03 override to the v9 piping, and each preserved file's recorded version."""
    others = sorted(
        (set(SUBSTITUTES) | set(PRESERVED)) - {"M_lining", "M_piping", "M_piping_lining_v9"}
    )
    recipe = {
        "title": "stand-in tunic recipe",
        "groups": [{"key": "lining", "name": "Forro", "mask": "M_lining"}],
        "layers": [
            *(
                {"id": f"L{i:02d}", "group": "lining", "name": f"L{i:02d} {n}", "mask": n}
                for i, n in enumerate(others)
            ),
            {"id": "C07", "group": "lining", "name": "C07 Piping", "mask": "M_piping"},
            {"id": "F03", "group": "lining", "name": "F03 Lining piping", "mask": "M_piping"},
        ],
    }
    v9 = preserved_png("M_piping_lining_v9")
    return {
        "painting_v10": {
            "painter_stack_recipe": recipe,
            "source_recovery": {
                "layer_specific_masks": {
                    "recipe_override_before_sync": {
                        "layer_id": "F03",
                        "mask": "M_piping_lining_v9",
                    },
                    "bindings": [
                        {
                            "layer_id": "F03",
                            "recorded_original_resource": resource("v9_M_piping", v9),
                        }
                    ],
                }
            },
            "mask_resources": [
                {
                    "mask": name,
                    "sha256": sha256(preserved_png(name)),
                    "resource": resource(name, preserved_png(name)),
                }
                for name in PRESERVED
                if name != "M_piping_lining_v9"
            ],
            "short_panel_recipe": {"input_mask_sha256": {"M_piping": sha256(v9)}},
        },
        "painting": {
            "effects_opacity_blending_state": {
                "mesh_maps": {"MeshMapUsage.Normal": resource(NORMAL_NAME, normal_png())}
            }
        },
    }


NORMAL_NAME = "Tunic_v6_HighNormal"


@dataclass
class Round:
    assets: Path
    store: OracleStore
    pins: Pins
    files: Files
    folders: dict[str, Path]
    initial: set[str]  # the store's index before the request: the preserved files only


def dump(path: Path, record: Mapping[str, Any]) -> str:
    data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write(path, data)
    return sha256(data)


def apply(changes: Mapping[str, Change], role: str, record: dict[str, Any]) -> dict[str, Any]:
    if role in changes:
        changes[role](record)
    return record


def build(
    tmp_path: Path,
    *,
    changes: Mapping[str, Change] | None = None,
    masks_both: Change | None = None,
    report_change: Change | None = None,
    layer_stack: str = CURRENT_LAYER_STACK,
    substitutes: Mapping[str, bytes] | None = None,
    obj: str | None = None,
    mtl: str = MTL,
) -> Round:
    """The stand-in round: Assets3D committed once, the store with the preserved files, and the
    six producer records in dependency order, each linked to the bytes of the ones before it.
    `changes` edit one record (by role) before it is written; `masks_both` edits both masks
    records alike, so the producer's comparison still agrees."""
    changes = changes or {}
    report = stand_in_report()
    if report_change is not None:
        report_change(report)
    assets = tmp_path / "assets3d"
    write(assets / "AGENTS.md", "stand-in asset repository\n")
    write(assets / LAYER_STACK_PATH, layer_stack)
    for _, path, text in CLOSURE:
        write(assets / path, text)
    write(assets / tunic.TUNIC_REPORT, json.dumps(report, indent=2))
    git(assets, "init", "-q")
    git(assets, "add", "-A")
    git(assets, "commit", "-q", "-m", "stand-in")
    commit = git(assets, "rev-parse", "HEAD").decode("ascii").strip()
    blobs = tuple(
        Blob(b.input_id, b.kind, b.path, sha256(blob(assets, commit, b.path)))
        for b in tunic_current.BLOBS
    )
    try:
        stack = sha256(tunic.stack_bytes(tunic.working_copy(report)))
    except (KeyError, RecorderError):
        stack = hexes("no working copy")

    store = OracleStore.init(tmp_path / "store")
    recovered = {name: preserved_png(name) for name in PRESERVED} | {"Normal": normal_png()}
    for name, data in recovered.items():
        file = tmp_path / "recovered" / f"{name}.png"
        write(file, data)
        store.add_input(file, sha256(data), f"recovered/{name}")
    initial = store.index()

    work = tmp_path / "oracle-work"
    folders = {
        role: work / role.replace("-record", "-r1").replace("-repeat", "-r1-repeat")
        for role in RECEIPTS
    }
    names = {"low": "export-record.json", "ao": "ao-record.json", "masks": "masks-record.json"}
    record_files = {role: folders[role] / names[role.split("-")[0]] for role in RECEIPTS}
    shas: dict[str, str] = {}

    # Front U3's export: the OBJ and MTL beside both records; the other files by stand-in hash.
    low_bytes = {
        low_side.OBJ_NAME: (obj or obj_text()).encode("utf-8"),
        low_side.MTL_NAME: mtl.encode(),
    }
    outputs = {name: {"sha256": hexes(name), "size_bytes": 1} for name in tunic_ao.LOW_FILES}
    outputs |= {name: out(data) for name, data in low_bytes.items()}
    outputs[low_side.REPORT_NAME] = {"sha256": hexes("report"), "size_bytes": 1}
    digests = {name: hexes(f"digest {name}") for name in (*ao_side.LOW_DIGESTS, "highnormal")}
    blender_side = hexes("tunic low blender side")
    low = {
        "schema": tunic_current.LOW_SCHEMA,
        "kind": "export",
        "status": "exported",
        "label": "authored pytest fixture",
        "blender": {"sha256": hexes("blender")},
        "script": {"blender_side_sha256": blender_side},
        "source": {"sha256": tunic_current.PINS.blend},
        "options": {"stand-in": True},
        "conventions": {"stand-in": True},
        "remap": low_side.REMAP,
        "selection": {"stand-in": True},
        "mesh": {"digests": digests},
        "lining": {"stand-in": True},
        "normal": {"stand-in": True},
        "obj_deviation": {"positions": 0.0},
        "outputs": outputs,
    }
    for role in ("low-record", "low-repeat"):
        for name, data in low_bytes.items():
            write(folders[role] / name, data)
        record = copy.deepcopy(low)
        if role == "low-repeat":
            record["expect"] = {"reproduced": True, "problems": []}
        shas[role] = dump(record_files[role], apply(changes, role, record))
    low_pins = LowPins(
        record_sha256=shas["low-record"],
        repeat_sha256=shas["low-repeat"],
        low_npz_sha256=hexes("low.npz"),
        highnormal_sha256=hexes(low_side.HIGHNORMAL),
        blender_side_sha256=blender_side,
    )
    low_inputs = {
        "record": "C:/oracle-work/low-r1/export-record.json",
        "record_sha256": low_pins.record_sha256,
        "repeat": "C:/oracle-work/low-r1-repeat/export-record.json",
        "repeat_sha256": low_pins.repeat_sha256,
        "digests": digests,
        "outputs": {name: outputs[name]["sha256"] for name in tunic_ao.LOW_FILES},
    }

    # Front U4's AO: `donor/ao.npy` beside both records.
    ao_npy = b"stand-in ao.npy"
    ao = {
        "schema": tunic_current.AO_SCHEMA,
        "kind": "ao",
        "status": "baked",
        "label": "authored pytest fixture",
        "blender": {"sha256": hexes("blender")},
        "scripts": {"stand-in": True},
        "donor": {"stand-in": True},
        "source": {"sha256": tunic_current.PINS.blend},
        "gpu": {"stand-in": True},
        "low_inputs": low_inputs,
        "control": {"record": "C:/x", "record_sha256": hexes("control"), "outcome": "x"},
        "ao": {"bake": {"digest": hexes("ao digest")}},
        "outputs": {AO_OUTPUT: out(ao_npy), ao_side.AO_REPORT: out(b"report")},
    }
    for role in ("ao-record", "ao-repeat"):
        write(folders[role] / AO_OUTPUT, ao_npy)
        record = copy.deepcopy(ao)
        if role == "ao-repeat":
            record["expect"] = {
                "of_record_sha256": shas["ao-record"],
                "reproduced": True,
                "problems": [],
            }
        shas[role] = dump(record_files[role], apply(changes, role, record))

    # Front U4's masks: the 16 donor masks beside both records.
    masks = {name: (substitutes or {}).get(name, substitute_png(name)) for name in SUBSTITUTES}
    masks |= {name: discarded_png(name) for name in DISCARDED}
    pins = Pins(
        snapshot=commit,
        blobs=blobs,
        stack=stack,
        low=low_pins,
        preserved=tuple(
            (name, image, sha256(preserved_png(name)))
            for name, (image, _) in sorted(tunic.RECOVERED.items())
        ),
        normal=(tunic.NORMAL[0], sha256(normal_png())),
        resolution=RES,
    )
    base: dict[str, Any] = {
        "schema": tunic_current.MASKS_SCHEMA,
        "kind": "masks",
        "piece": "tunic-v10",
        "helper": {"path": "tools/parity/tier1/tunic_masks.py", "sha256": hexes("u4")},
        "donor": tunic_masks.DONOR.as_json(tunic_masks.SNAPSHOT),
        "runtime": dict(tunic_masks.RUNTIME),
        "code": {"tools/parity/tier1/tunic_masks.py": hexes("u4")},
        "children": {"fields": {"argv": ["fields"]}, "masks": {"argv": ["masks"]}},
        "receipts": {
            "low_record": low_pins.record_sha256,
            "low_repeat": low_pins.repeat_sha256,
            "ao_record": shas["ao-record"],
            "ao_repeat": shas["ao-repeat"],
            "ao_npy": sha256(ao_npy),
            "ao_repeat_npy": sha256(ao_npy),
        },
        "integrity": {"stand-in": True},
        "host": {"platform": "stand-in"},
        "parameters": {
            "recipe": None,
            "resolution": RES,
            "png": {"bit_depth": 16, "colour_type": 0},
            "python_hash_seed": "0",
        },
        "budgets": {"stand-in": True},
        "low_inputs": low_inputs,
        "ao_inputs": {
            "record": "C:/x",
            "record_sha256": shas["ao-record"],
            "repeat": "C:/y",
            "repeat_sha256": shas["ao-repeat"],
            "ao_sha256": sha256(ao_npy),
            "digest": hexes("ao digest"),
        },
        "staged": {"stand-in": True},
        "fields": {"stand-in": True},
        "masks_report": {"stand-in": True},
        "substitutes": [
            {
                "name": name,
                "file": f"donor-masks/{name}.png",
                **out(masks[name]),
                "role": "current-round substitute",
                "shape": [RES, RES],
            }
            for name in SUBSTITUTES
        ],
        "discarded": [
            {
                "name": name,
                "file": f"donor-masks/{name}.png",
                **out(masks[name]),
                "role": "discarded-never-bound",
            }
            for name in DISCARDED
        ],
        "preserved": [
            {"name": name, "packed_image": image, "sha256": sha, "role": PRESERVED_ROLE}
            for name, image, sha in pins.preserved
        ],
        "stack_masks": sorted([*SUBSTITUTES, *tunic.RECOVERED]),
        "substitute": dict(tunic_masks.SUBSTITUTE),
        "run_specific": tunic_masks.RUN_SPECIFIC,
    }
    if masks_both is not None:
        masks_both(base)
    for role in ("masks-record", "masks-repeat"):
        for name, data in masks.items():
            write(folders[role] / "donor-masks" / f"{name}.png", data)
        record = {**copy.deepcopy(base), "run_dir": str(folders[role])}
        if role == "masks-record":
            record |= {"status": "produced", "repeat": {"result": "not-a-repeat", "note": "x"}}
        else:
            record |= {
                "status": "reproduced",
                "repeat": {
                    "of_record": str(record_files["masks-record"]),
                    "of_record_sha256": shas["masks-record"],
                    "result": "byte-identical",
                    "problems": [],
                },
            }
        shas[role] = dump(record_files[role], apply(changes, role, record))
    files = {role: {"sha256": shas[role], "file": str(record_files[role])} for role in RECEIPTS}
    return Round(assets, store, pins, files, folders, initial)


def request(r: Round, **overrides: Any) -> dict[str, Any]:
    files = overrides.pop("files", r.files)
    pins = overrides.pop("pins", r.pins)
    return current_request(r.assets, r.store, files, pins, **overrides)


def setting(value: Any, *path: str) -> Change:
    def change(record: dict[str, Any]) -> None:
        target: Any = record
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


def entry(key: str, name: str, field: str, value: Any) -> Change:
    """`record[key]`'s entry `name` gets `field` = `value`."""

    def change(record: dict[str, Any]) -> None:
        next(e for e in record[key] if e["name"] == name)[field] = value

    return change


# --- a complete round ---------------------------------------------------------------------------


def test_a_complete_round_is_stored_and_loads_as_a_native_job(tmp_path: Path) -> None:
    """Every input resolves and is stored; the request is the three-step native job (create,
    the sync with its options, closure and F03 override, the pinned config export) over the 17
    masks by folder; it is marked as technical preparation; and its job loads from the store."""
    r = build(tmp_path)
    manifest = request(r)

    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["golden_id"] == "phase2/tier1/tunic-v10-current"
    description = manifest["description"]
    for text in ("technical preparation", "not parity", "owner's yes", "promotes and admits"):
        assert text in description
    steps = manifest["instruction_sequence"]["steps"]
    assert [s["call"] for s in steps] == [NATIVE_CREATE, RUN_SCRIPT, CONFIG_EXPORT]
    assert steps[0]["args"] == {
        "mesh": "tunic-mesh",
        "mesh_material_library": "tunic-mesh-mtl",
        "normal": "tunic-normal",
        "texture_set": "DefaultMaterial",
        "normal_name": "Tunic_v6_HighNormal",
        "normal_group": "tunica18_v10c_mesh_maps",
        "normal_map_format": "OpenGL",
        "tangent_space_mode": "PerFragment",
        "project_workflow": "Default",
        "default_texture_resolution": 4096,
        "import_cameras": False,
        "mesh_unit_scale": 1.0,
    }
    assert steps[1]["args"] == {
        "script": "painter-layer-stack-py",
        "command": "sync",
        "stack": "tunic-stack",
        "mask_folder": MASKS,
        "imports": ["production-run-py"],
        "import_closure": ["decision-evidence-py", "stage-review-evidence-py"],
        "resource_prefix": "v10c_",
        "resource_group": "tunica18_v10c",
        "texture_set": "DefaultMaterial",
        "recipe": "tunic-report",
        "recipe_keys": ["painting_v10", "painter_stack_recipe"],
        "override_layer": "F03",
        "override_mask": "M_piping_lining_v9",
    }
    assert steps[2]["args"] == {"config": "tunic-v10-export-config"}

    items = {i["input_id"]: i for i in manifest["inputs"]}
    masks = {i: v for i, v in items.items() if v["kind"] == "mask"}
    assert sorted(masks) == sorted(f"mask-{n.lower()}" for n in (*SUBSTITUTES, *PRESERVED))
    discarded = {sha256(discarded_png(name)) for name in DISCARDED}
    for name in (*SUBSTITUTES, *PRESERVED):
        item = masks[f"mask-{name.lower()}"]
        assert item["assets3d_path"] == f"{MASKS}/{name}.png"
        assert item["sha256"] not in discarded  # a discarded donor output is never bound
        note = item["provenance"]["note"]
        if name in SUBSTITUTES:
            assert item["sha256"] == sha256(substitute_png(name))
            assert note.startswith(f"Current-round substitute, not the historical {name}")
            for role in ("masks-record", "masks-repeat", "low-record", "ao-record", "ao-repeat"):
                assert r.files[role]["sha256"] in note, role
        else:
            assert item["sha256"] == sha256(preserved_png(name))
            assert note.startswith("Preserved, never regenerated")
    for input_id in ("tunic-mesh", "tunic-mesh-mtl"):
        note = items[input_id]["provenance"]["note"]
        assert note.startswith("Current-round substitute")
        assert r.files["low-record"]["sha256"] in note and r.files["low-repeat"]["sha256"] in note
    assert items["tunic-stack"]["sha256"] == r.pins.stack
    assert items["tunic-normal"]["sha256"] == r.pins.normal[1]
    config = items["tunic-v10-export-config"]
    assert (config["path"], config["sha256"]) == (tunic.EXPORT_CONFIG, Pins().export_config)
    for item in items.values():
        if "assets3d_path" in item:
            assert r.store.resolve(item["input_id"], item["sha256"]).status is Status.AVAILABLE
    for role in RECEIPTS:
        assert r.store.resolve(role, r.files[role]["sha256"]).status is Status.AVAILABLE
    assert r.store.load(sha256(b"stand-in ao.npy")) == b"stand-in ao.npy"

    job = pipeline_job_from_manifest(manifest, r.assets, r.store)
    assert isinstance(job, NativeJob)
    assert job.create.settings == tunic_current.SETTINGS
    assert sorted(m.name for m in job.sync.masks) == sorted(
        f"{n}.png" for n in (*SUBSTITUTES, *PRESERVED)
    )
    assert job.create.normal.file.is_relative_to(r.store.root)


# A configuration the fake Painter can export (it needs an inline preset): one map.
STAND_IN_CONFIG: dict[str, Any] = {
    "exportShaderParams": False,
    "defaultExportPreset": "stand-in",
    "exportPresets": [
        {
            "name": "stand-in",
            "maps": [
                {
                    "fileName": "$textureSet_Displacement_Raw",
                    "channels": [
                        {
                            "destChannel": "L",
                            "srcChannel": "L",
                            "srcMapType": "documentMap",
                            "srcMapName": "height",
                        }
                    ],
                }
            ],
        }
    ],
    "exportList": [{"rootPath": "DefaultMaterial"}],
    "exportParameters": [
        {
            "parameters": {
                "fileFormat": "png",
                "bitDepth": "16",
                "sizeLog2": 12,
                "paddingAlgorithm": "infinite",
                "dithering": False,
            }
        }
    ],
}


def test_the_request_records_through_the_fake_painter(
    tmp_path: Path,
    painter: tuple[Any, ScriptSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a stand-in repository config the fake can export: r1, r1-repeat and r2, the native
    create binding the Normal alone and the sync with the round's options."""
    r = build(tmp_path, layer_stack=NATIVE_LAYER_STACK)  # a sync that builds the stack's tree
    repo = tmp_path / "repo"
    data = json.dumps(STAND_IN_CONFIG).encode("utf-8")
    write(repo / tunic.EXPORT_CONFIG, data)
    pins = dataclasses.replace(r.pins, export_config=sha256(data))
    manifest = request(r, pins=pins, repo_root=repo)
    job = pipeline_job_from_manifest(manifest, r.assets, r.store, repo)
    assert isinstance(job, NativeJob)

    world, session = painter
    world.version, world.version_info = "12.2.0", (12, 2, 0)  # the request's Painter
    world.texture_set = world.imported_texture_set = "DefaultMaterial"
    world.default_tree_layer = "Layer 1"  # a created project's default root layer
    monkeypatch.setattr(session_module, "envelope_builds", lambda: frozenset({BUILD}))
    run = record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    assert [x["recording_id"] for x in data["recordings"]] == ["r1", "r1-repeat", "r2"]
    outputs = {o["output_id"]: o for o in data["recordings"][0]["outputs"]}
    created = outputs["create/s1"]["value"]
    assert created["requested_normal"] == {"name": NORMAL_NAME, "group": "tunica18_v10c_mesh_maps"}
    assert [k for k, v in created["mesh_maps"].items() if v is not None] == ["Normal"]
    synced = outputs["script/s2"]["value"]
    assert synced["options"] == {
        "prefix": "v10c_",
        "group": "tunica18_v10c",
        "texture_set": "DefaultMaterial",
    }
    assert synced["imported"] == sorted([*SUBSTITUTES, *PRESERVED])


def test_the_command_writes_the_request_once_it_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    r = build(tmp_path)
    monkeypatch.setattr(tunic_current, "PINS", r.pins)
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"schema": INPUTS_SCHEMA, "files": r.files}), encoding="utf-8")
    target = tmp_path / "out" / "tunic-v10-current.json"
    command = ["request", "--assets-root", str(r.assets), "--out", str(target)]
    assert (
        tunic_current.main([*command, "--store", str(r.store.root), "--inputs", str(inputs)]) == 0
    )
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == request(r)  # the same request again, from the store
    assert "wrote" in capsys.readouterr().out


# --- absent roles -------------------------------------------------------------------------------


@pytest.mark.parametrize("role", RECEIPTS)
def test_each_absent_receipt_is_named_and_nothing_is_stored(tmp_path: Path, role: str) -> None:
    r = build(tmp_path)
    given = {k: v for k, v in r.files.items() if k != role}
    with pytest.raises(MissingInputs) as refused:
        request(r, files=given)
    assert refused.value.missing == [role]
    assert r.store.index() == r.initial


def test_without_an_inputs_file_every_receipt_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    r = build(tmp_path)
    with pytest.raises(MissingInputs) as refused:
        request(r, files=None)
    assert refused.value.missing == sorted(RECEIPTS)
    monkeypatch.setattr(tunic_current, "PINS", r.pins)
    target = tmp_path / "out.json"
    command = ["request", "--assets-root", str(r.assets), "--out", str(target)]
    assert tunic_current.main([*command, "--store", str(r.store.root)]) == 2
    printed = capsys.readouterr().err
    assert json.loads(printed[printed.index("{") :])["missing"] == sorted(RECEIPTS)
    assert not target.exists() and r.store.index() == r.initial


def test_absent_preserved_files_and_scripts_are_named(tmp_path: Path) -> None:
    """A preserved mask or the Normal the store does not hold, and a script absent at the
    snapshot, are each named; nothing is stored."""
    r = build(tmp_path)
    pins = dataclasses.replace(
        r.pins,
        preserved=tuple(
            (n, i, hexes("gone") if n == "M_band" else s) for n, i, s in r.pins.preserved
        ),
        normal=(r.pins.normal[0], hexes("gone normal")),
        blobs=tuple(
            dataclasses.replace(b, path="Pipeline/production/gone.py")
            if b.input_id == "production-run-py"
            else b
            for b in r.pins.blobs
        ),
    )
    with pytest.raises(MissingInputs) as refused:
        request(r, pins=pins)
    assert refused.value.missing == sorted(
        [
            f"Pipeline/production/gone.py@{r.pins.snapshot[:8]}",
            "M_band",
            "tunic-normal",
        ]
    )
    assert r.store.index() == r.initial


@pytest.mark.parametrize(
    ("role", "where"),
    [
        ("low-obj", ("low-record", low_side.OBJ_NAME)),
        ("ao-npy", ("ao-record", AO_OUTPUT)),
        ("M_pores", ("masks-repeat", "donor-masks/M_pores.png")),
    ],
)
def test_an_output_held_nowhere_is_named(tmp_path: Path, role: str, where: tuple[str, str]) -> None:
    """An output its records name but neither the store nor any run directory holds."""
    r = build(tmp_path)
    receipt, name = where
    pair = receipt.replace("-repeat", "-record") if receipt.endswith("-repeat") else receipt
    for folder in (r.folders[pair], r.folders[pair.replace("-record", "-repeat")]):
        (folder / name).unlink()
    with pytest.raises(MissingInputs) as refused:
        request(r)
    assert refused.value.missing == [role]
    assert r.store.index() == r.initial


# --- refusals: receipts, links, outputs and the job ---------------------------------------------

DISCARDED_BAND = {"M_pores": discarded_png("M_band")}
CASES: list[tuple[dict[str, Any], str]] = [
    # front U3's export records
    ({"changes": {"low-record": setting("other/1", "schema")}}, r"`low-record` `schema`"),
    (
        {"changes": {"low-repeat": setting({"reproduced": False, "problems": ["x"]}, "expect")}},
        r"`low-repeat` `expect` is",
    ),
    ({"changes": {"low-record": setting({}, "expect")}}, r"`low-record` is itself a repeat"),
    (
        {"changes": {"low-repeat": setting({"co": hexes("other")}, "mesh", "digests")}},
        r"`low-repeat` does not reproduce its first run: mesh",
    ),
    ({"changes": {"low-record": setting({}, "remap")}}, r"`low-record` `remap`"),
    # front U4's AO records
    ({"changes": {"ao-record": setting("other/1", "schema")}}, r"`ao-record` `schema`"),
    (
        {"changes": {"ao-repeat": setting("refused", "status")}},
        r"`ao-repeat` `status` is 'refused'",
    ),
    (
        {"changes": {"ao-repeat": setting(False, "expect", "reproduced")}},
        r"`ao-repeat` `expect` is",
    ),
    (
        {"changes": {"ao-repeat": setting(hexes("other r1"), "expect", "of_record_sha256")}},
        r"`ao-repeat` `expect` is",
    ),
    (
        {"changes": {"ao-repeat": setting(hexes("other"), "ao", "bake", "digest")}},
        r"`ao-repeat` does not reproduce its first run: ao",
    ),
    (
        {"changes": {"ao-record": setting(hexes("x"), "low_inputs", "record_sha256")}},
        r"`ao-record` `low_inputs.record_sha256`",
    ),
    # front U4's masks records
    ({"changes": {"masks-record": setting("other/1", "schema")}}, r"`masks-record` `schema`"),
    (
        {"changes": {"masks-repeat": setting("not-reproduced", "status")}},
        r"`masks-repeat` `status` is 'not-reproduced', not 'reproduced'",
    ),
    (
        {"changes": {"masks-repeat": setting("refused", "status")}},
        r"`masks-repeat` `status` is 'refused', not 'reproduced'",
    ),
    (
        {"changes": {"masks-record": setting("reproduced", "status")}},
        r"`masks-record` `status` is 'reproduced', not 'produced'",
    ),
    (
        {"changes": {"masks-repeat": setting("differs", "repeat", "result")}},
        r"`masks-repeat` `repeat.result`",
    ),
    (
        {"changes": {"masks-repeat": setting(hexes("other r1"), "repeat", "of_record_sha256")}},
        r"`masks-repeat` `repeat.of_record_sha256`",
    ),
    (  # the repeat says reproduced, but its comparison with r1 does not hold
        {"changes": {"masks-repeat": entry("substitutes", "M_pores", "size_bytes", 7)}},
        r"`masks-repeat` does not reproduce its first run: substitutes",
    ),
    (
        {"masks_both": setting(hexes("x"), "ao_inputs", "ao_sha256")},
        r"`masks-record` `ao_inputs.ao_sha256`",
    ),
    (
        {"masks_both": setting({"low.npz": hexes("x")}, "low_inputs", "outputs")},
        r"`masks-record` `low_inputs.outputs`",
    ),
    (
        {"masks_both": setting(hexes("x"), "receipts", "ao_record")},
        r"`masks-record` `receipts.ao_record`",
    ),
    (
        {"masks_both": setting(4096, "parameters", "resolution")},
        r"`masks-record` `parameters.resolution` is 4096",
    ),
    ({"masks_both": setting(hexes("x"), "donor", "sha256")}, r"`masks-record` `donor`"),
    # the mask sets: substitutes, discarded, preserved
    (
        {"masks_both": entry("substitutes", "M_pores", "name", "M_band")},
        r"`masks-record` `substitutes` must be",
    ),
    (
        {"masks_both": entry("discarded", "M_band", "role", "current-round substitute")},
        r"`masks-record discarded M_band` `role`",
    ),
    (
        {"masks_both": entry("substitutes", "M_pores", "file", "donor-masks/M_band.png")},
        r"`masks-record substitutes M_pores` `file`",
    ),
    (
        {"substitutes": DISCARDED_BAND},
        r"`masks-record` would bind the discarded M_band as M_pores",
    ),
    (
        {"masks_both": entry("preserved", "M_band", "sha256", hexes("other band"))},
        r"`masks-record` `preserved`",
    ),
    (
        {
            "report_change": lambda report: report["painting_v10"]["mask_resources"][0].update(
                sha256=hexes("other band")
            )
        },
        r"`M_band`: sha256 [0-9a-f]{64} / version [0-9a-f]{40} disagree with the report's",
    ),
    (
        {
            "report_change": setting(
                "resource://p/x?version=" + "0" * 40 + ".image",
                "painting",
                "effects_opacity_blending_state",
                "mesh_maps",
                "MeshMapUsage.Normal",
            )
        },
        r"`tunic-normal`: sha256 .* disagree with the report's",
    ),
    (
        {
            "report_change": setting(
                "M_piping",
                "painting_v10",
                "source_recovery",
                "layer_specific_masks",
                "recipe_override_before_sync",
                "mask",
            )
        },
        r"the report's override is .*, not F03 -> M_piping_lining_v9",
    ),
    # the outputs' forms
    ({"substitutes": {"M_pores": png(RES, 8, 0, 1)}}, r"`M_pores` is a 8x8 PNG of depth 8"),
    ({"substitutes": {"M_fiber": png(4, 16, 0, 1)}}, r"`M_fiber` is a 4x4 PNG"),
    ({"mtl": MTL + "newmtl Other\n"}, r"`low-mtl`: MTL materials are"),
    ({"obj": obj_text("other.mtl")}, r"the low OBJ names the material library 'other.mtl'"),
]


@pytest.mark.parametrize(("variant", "refusal"), CASES)
def test_a_wrong_receipt_link_or_output_refuses_and_stores_nothing(
    tmp_path: Path, variant: dict[str, Any], refusal: str
) -> None:
    r = build(tmp_path, **variant)
    with pytest.raises(RecorderError, match=refusal):
        request(r)
    assert r.store.index() == r.initial


@pytest.mark.parametrize(
    ("role", "name"),
    [
        ("masks-repeat", "donor-masks/M_pores.png"),
        ("masks-record", "donor-masks/M_lining.png"),
        ("low-repeat", low_side.OBJ_NAME),
        ("ao-repeat", AO_OUTPUT),
    ],
)
def test_a_status_only_receipt_with_an_altered_output_refuses(
    tmp_path: Path, role: str, name: str
) -> None:
    """The records all agree and say reproduced, but a file beside one of them was changed
    afterwards: every copy is re-hashed, so the request refuses."""
    r = build(tmp_path)
    file = r.folders[role] / name
    file.write_bytes(file.read_bytes() + b"tampered")
    with pytest.raises(RecorderError, match=r"has other bytes than its record's"):
        request(r)
    assert r.store.index() == r.initial


def test_a_tampered_output_hash_in_both_records_refuses(tmp_path: Path) -> None:
    """Both masks records name another hash for M_pores than its file holds."""
    r = build(tmp_path, masks_both=entry("substitutes", "M_pores", "sha256", hexes("forged")))
    with pytest.raises(RecorderError, match=r"`M_pores`: .* has other bytes than its record's"):
        request(r)
    assert r.store.index() == r.initial


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (
            lambda p: dataclasses.replace(
                p, low=dataclasses.replace(p.low, record_sha256="1" * 64)
            ),
            r"`low-record` is [0-9a-f]{64}, not front U3's accepted 1{64}",
        ),
        (
            lambda p: dataclasses.replace(
                p, low=dataclasses.replace(p.low, low_npz_sha256="2" * 64)
            ),
            r"`low-record` `outputs.low.npz.sha256`",
        ),
        (lambda p: dataclasses.replace(p, stack="3" * 64), r"the stack working copy is"),
        (lambda p: dataclasses.replace(p, export_config="4" * 64), r"not the pinned 4{64}"),
    ],
)
def test_other_pins_refuse(tmp_path: Path, change: Callable[[Pins], Pins], refusal: str) -> None:
    r = build(tmp_path)
    with pytest.raises(RecorderError, match=refusal):
        request(r, pins=change(r.pins))
    assert r.store.index() == r.initial


def test_the_inputs_file_names_receipts_only_by_their_bytes(tmp_path: Path) -> None:
    """A discarded mask or a product is no role; a receipt's file must be its pinned bytes; the
    inputs file must be of its schema."""
    r = build(tmp_path)
    with pytest.raises(RecorderError, match=r"unknown roles \['M_band', 'low-obj'\]"):
        request(
            r,
            files={**r.files, "M_band": r.files["masks-record"], "low-obj": r.files["low-record"]},
        )
    forged = {**r.files, "masks-repeat": {**r.files["masks-repeat"], "sha256": hexes("forged")}}
    with pytest.raises(RecorderError, match=r"`masks-repeat`: .* is not the bytes"):
        request(r, files=forged)
    assert r.store.index() == r.initial
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"schema": "other/1", "files": r.files}), encoding="utf-8")
    with pytest.raises(RecorderError, match=rf"not a {INPUTS_SCHEMA} file"):
        tunic_current.load_inputs(inputs)


def test_a_request_whose_job_does_not_load_is_refused(tmp_path: Path) -> None:
    """Every receipt holds, but the pinned sync defines no --texture-set option: the native job
    refuses to load, so no request is returned."""
    text = CURRENT_LAYER_STACK.replace("    s.add_argument('--texture-set')\n", "")
    assert text != CURRENT_LAYER_STACK
    r = build(tmp_path, layer_stack=text)
    with pytest.raises(RecorderError, match=r"defines no --texture-set option"):
        request(r)


# --- the real pins ------------------------------------------------------------------------------


def test_the_default_pins_are_the_contracts() -> None:
    """The preserved pins are `tunic.RECOVERED` and `tunic.NORMAL`; the 9 substitutes and the 8
    preserved make the 17 stack masks; the repository's export configuration is at its pin; the
    sync's four scripts are the Sash round's."""
    pins = Pins()
    assert {n: (i, s) for n, i, s in pins.preserved} == tunic.RECOVERED
    assert pins.normal == tunic.NORMAL and pins.resolution == 4096
    assert tunic_masks.stack_set_problems() == []
    assert hashlib.sha256((REPO_ROOT / tunic.EXPORT_CONFIG).read_bytes()).hexdigest() == (
        pins.export_config
    )
    assert [b.input_id for b in pins.blobs] == [
        "painter-layer-stack-py",
        "production-run-py",
        "decision-evidence-py",
        "stage-review-evidence-py",
        "tunic-report",
    ]
    assert pins.low == tunic_ao.LOW_PINS
