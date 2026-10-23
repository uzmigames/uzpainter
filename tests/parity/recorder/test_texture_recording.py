"""Texture goldens against a fake Painter: session identity, state replay, readbacks, exports,
the two-recording rule and stale-capture refusal (task items 2.1-2.3, 2.6)."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import types
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.capture import StaleCaptureError
from tools.parity.recorder.job import EXPORT, Job, job_from_manifest, parse_output_map
from tools.parity.recorder.output import slug
from tools.parity.recorder.session import PainterSession, RecorderError, bootstrap_code
from tools.parity.recorder.texture import REOPEN_COUNT, record_texture_golden
from tools.parity.recorder.vocabulary import LIST_TEXTURES
from tools.parity.schemas import REPO_ROOT

MakeSession = Callable[[Any], PainterSession]


def record_of(run: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((run / "record.json").read_text(encoding="utf-8"))
    return record


def outputs(record: dict[str, Any], index: int, kind: str) -> list[dict[str, Any]]:
    return [o for o in record["recordings"][index]["outputs"] if o["kind"] == kind]


def test_session_records_painter_identity(
    fake: types.ModuleType, make_session: MakeSession
) -> None:
    session = make_session(fake.FakeWorld())
    identity = session.connect()
    assert identity.painter_build() == {
        "product": "Adobe Substance 3D Painter",
        "version": "12.1.0",
        "build_id": "12.1.0+js-api.1.1.20",
    }
    assert identity.colour_management["mode"] == "legacy"
    # Reconnecting to the same process keeps the session id; a new process gets a new one.
    assert session.connect().session_id == identity.session_id
    assert make_session(fake.FakeWorld()).connect().session_id != identity.session_id


def test_bootstrap_sends_only_the_painter_side_code() -> None:
    code = bootstrap_code("x = 1\n")
    assert "uzp_recorder['session_id'] = uzp_recorder_session_id" in code
    assert "substance_painter" not in code


def test_other_painter_versions_are_refused(
    fake: types.ModuleType, make_session: MakeSession
) -> None:
    world = fake.FakeWorld()
    world.version, world.version_info = "12.0.1", (12, 0, 1)
    with pytest.raises(RecorderError, match=r"must be Adobe Substance 3D Painter 12\.1\.0"):
        make_session(world).connect()


def test_an_open_project_is_never_touched(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    world.project_open = True
    with pytest.raises(RecorderError, match="already open"):
        record_texture_golden(make_session(world), sample_job, work, inbox)
    assert world.project_open and not inbox.exists() and not work.exists()


def test_sample_golden_is_recorded_twice(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    run = record_texture_golden(make_session(world), sample_job, work, inbox)
    record = record_of(run)
    assert [r["condition"] for r in record["recordings"]] == ["same_session", "after_save_reopen"]
    assert record["recordings"][0]["session_id"] == record["recordings"][1]["session_id"]
    first, second = outputs(record, 0, "exported_map"), outputs(record, 1, "exported_map")
    assert len(first) == len(second) == 1
    assert first[0]["storage_format"] == {
        "container": "png",
        "sample_type": "uint",
        "bits_per_channel": 16,
        "channels": 3,
        "encoding": "srgb",
    }
    assert first[0]["export_settings"]["encoding_basis"] == "source_channel_format"
    assert first[0]["export_settings"]["bitDepth"] == "16"
    assert first[0]["blob"] == second[0]["blob"]
    # The project was saved in the private work directory and closed afterwards.
    assert not world.project_open
    assert list(work.rglob("golden.spp"))


@pytest.mark.parametrize("count", [1, 2, 3])
def test_explicit_reopens_keep_all_recordings(
    count: int,
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    sample_job.manifest["applied_settings"].append(
        {"name": REOPEN_COUNT, "value": count, "applied_by": "recorder_api"}
    )
    world = fake.FakeWorld()
    record = record_of(record_texture_golden(make_session(world), sample_job, work, inbox))
    recordings = record["recordings"]
    assert [r["recording_id"] for r in recordings] == [f"r{i}" for i in range(1, count + 2)]
    assert [r["condition"] for r in recordings] == ["same_session"] + ["after_save_reopen"] * count
    assert all(outputs(record, i, "exported_map") for i in range(count + 1))
    assert not world.project_open


@pytest.mark.parametrize("value", [0, 4, -1, True, 2.0, "3", None])
def test_bad_reopen_count_is_refused_before_connection(
    value: Any,
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_job.manifest["applied_settings"].append(
        {"name": REOPEN_COUNT, "value": value, "applied_by": "recorder_api"}
    )
    session = make_session(fake.FakeWorld())
    monkeypatch.setattr(session, "connect", lambda: pytest.fail("must validate before connect"))
    with pytest.raises(RecorderError, match=r"recorder\.reopen_count"):
        record_texture_golden(session, sample_job, work, inbox)
    assert not inbox.exists() and not work.exists()


@pytest.mark.parametrize("duplicate", [False, True])
def test_reopen_setting_requires_unique_recorder_declaration(
    duplicate: bool,
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    setting = {
        "name": REOPEN_COUNT,
        "value": 3,
        "applied_by": "recorder_api" if duplicate else "painter_ui",
    }
    sample_job.manifest["applied_settings"].extend([setting] * (2 if duplicate else 1))
    with pytest.raises(RecorderError, match=r"recorder\.reopen_count"):
        record_texture_golden(make_session(fake.FakeWorld()), sample_job, work, inbox)
    assert not inbox.exists() and not work.exists()


def test_third_reopen_failure_does_not_publish_partial_record(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_job.manifest["applied_settings"].append(
        {"name": REOPEN_COUNT, "value": 3, "applied_by": "recorder_api"}
    )
    world = fake.FakeWorld()
    session = make_session(world)
    original = session.call
    opens = 0

    def call(operation: str, **kwargs: Any) -> Any:
        nonlocal opens
        if operation == "open_project":
            opens += 1
            if opens == 3:
                raise RecorderError("third reopen failed")
        return original(operation, **kwargs)

    monkeypatch.setattr(session, "call", call)
    with pytest.raises(RecorderError, match="third reopen failed"):
        record_texture_golden(session, sample_job, work, inbox)
    assert opens == 3 and not world.project_open and not inbox.exists()


def test_effective_defaults_and_readbacks_are_recorded(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    record = record_of(
        record_texture_golden(make_session(fake.FakeWorld()), sample_job, work, inbox)
    )
    defaults = record["key"]["effective_defaults"]
    assert defaults["insert_fill"]["5"]["per_channel"]["BaseColor"] == {
        "blending_mode": "Normal",
        "opacity": 1.0,
    }
    assert defaults["project.create"]["texture_sets"]["uzp_plane"]["resolution"] == [256, 256]
    assert record["key"]["project_settings"]["create"] == {
        "normal_map_format": "OpenGL",
        "default_texture_resolution": 256,
    }
    for index in (0, 1):
        readbacks = {
            (o["call"].rsplit(".", 1)[1], o["args"].get("node_step")): o["value"]
            for o in outputs(record, index, "api_readback")
        }
        assert readbacks[("get_blending_mode", 5)] == "Multiply"
        assert readbacks[("get_opacity", 5)] == 1.0
        assert readbacks[("active_channels", 2)] == ["BaseColor"]
        assert readbacks[("get_source", 5)] == {"uniform_color_working": [0.5, 0.25, 1.0]}


def renumbered(manifest: dict[str, Any], index: int, step: dict[str, Any]) -> Job:
    steps = manifest["instruction_sequence"]["steps"]
    steps.insert(index, step)
    for number, item in enumerate(steps, start=1):
        item["step"] = number
    return job_from_manifest(manifest)


def test_failing_instruction_aborts_the_recording(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    job = renumbered(
        copy.deepcopy(sample_job.manifest),
        7,
        {
            "step": 0,
            "call": "substance_painter.layerstack.FillLayerNode.active_channels",
            "args": {"node_step": 5, "channels": ["Roughness"]},
        },
    )
    world = fake.FakeWorld()
    with pytest.raises(RecorderError, match="apply_step"):
        record_texture_golden(make_session(world), job, work, inbox)
    assert not inbox.exists() and not world.project_open


def test_failing_readback_records_the_documented_error(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    job = renumbered(
        copy.deepcopy(sample_job.manifest),
        9,
        {
            "step": 0,
            "call": "substance_painter.layerstack.FillLayerNode.active_channels",
            "args": {"node_step": 2, "channels": ["Roughness"]},
        },
    )
    record = record_of(record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox))
    for index in (0, 1):
        (raised,) = [
            o
            for o in outputs(record, index, "api_readback")
            if o["args"] == {"node_step": 2, "channel": "BaseColor"}
        ]
        assert raised["value"] is None
        assert raised["raised"]["type"] == "RuntimeError"


def test_substance_source_properties_are_read_back(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    job = renumbered(
        copy.deepcopy(sample_job.manifest),
        9,
        {
            "step": 0,
            "call": "substance_painter.layerstack.FillLayerNode.set_source",
            "args": {
                "node_step": 2,
                "channel": "BaseColor",
                "resource": "resource://starter_assets/Grunge Map 001",
            },
        },
    )
    record = record_of(record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox))
    for index in (0, 1):
        (readback,) = [
            o
            for o in outputs(record, index, "api_readback")
            if o["args"] == {"node_step": 2, "channel": "BaseColor"}
        ]
        assert readback["value"]["substance_properties"] == {
            "scale": {"value": 1.5, "widget_type": "Slider", "label": "Scale"},
            "seed": {"value": 7, "widget_type": "RandomSeed", "label": "Random Seed"},
            "tint": {
                "value": [{"working": [0.25, 0.5, 1.0]}, 0.5],
                "widget_type": "Color",
                "label": "Tint",
            },
        }


def test_stale_export_is_refused_and_no_golden_is_written(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    def backdate(path: Path) -> None:
        old = path.stat().st_mtime_ns - 3_600_000_000_000
        os.utime(path, ns=(old, old))

    world = fake.FakeWorld(export_hook=backdate)
    with pytest.raises(StaleCaptureError, match="before the last applied instruction"):
        record_texture_golden(make_session(world), sample_job, work, inbox)
    assert not inbox.exists()
    assert not world.project_open


def test_extra_file_in_the_export_is_refused(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    def leftover(path: Path) -> None:
        (path.parent / "leftover.png").write_bytes(b"x")

    with pytest.raises(StaleCaptureError, match="unlisted"):
        record_texture_golden(
            make_session(fake.FakeWorld(export_hook=leftover)), sample_job, work, inbox
        )
    assert not inbox.exists()


def test_job_vocabulary_is_enforced(sample_job: Job) -> None:
    manifest = copy.deepcopy(sample_job.manifest)
    manifest["instruction_sequence"]["steps"][1]["call"] = (
        "substance_painter.layerstack.insert_paint"
    )
    with pytest.raises(RecorderError, match="not in the recorder vocabulary"):
        job_from_manifest(manifest)
    manifest = copy.deepcopy(sample_job.manifest)
    steps = manifest["instruction_sequence"]["steps"]
    steps[-1], steps[-2] = steps[-2], steps[-1]
    steps[-1]["step"], steps[-2]["step"] = len(steps), len(steps) - 1
    with pytest.raises(RecorderError, match="must precede the captures"):
        job_from_manifest(manifest)


def test_input_hash_mismatch_is_refused(sample_job: Job, tmp_path: Path) -> None:
    mesh = tmp_path / "parity" / "fixtures" / "meshes" / "plane.obj"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(
        (REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj").read_bytes() + b"#"
    )
    with pytest.raises(RecorderError, match="differs from the manifest"):
        job_from_manifest(sample_job.manifest, repo_root=tmp_path)


# ── Decision 087: step keying, map names with a slash, export probes ─────────


def with_steps(
    manifest: dict[str, Any], extra: list[dict[str, Any]], repo_root: Path = REPO_ROOT
) -> Job:
    steps = manifest["instruction_sequence"]["steps"]
    for item in extra:
        steps.append({**item, "step": len(steps) + 1})
    return job_from_manifest(manifest, repo_root=repo_root)


def test_a_map_exported_by_two_steps_is_keyed_by_step(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    manifest = copy.deepcopy(sample_job.manifest)
    export = copy.deepcopy(manifest["instruction_sequence"]["steps"][-1])
    job = with_steps(manifest, [export])
    assert job.maps_exported_twice == {"basecolor"}
    run = record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox)
    record = record_of(run)
    for index in (0, 1):
        ids = [o["output_id"] for o in outputs(record, index, "exported_map")]
        assert ids == ["uzp_plane/basecolor/step10", "uzp_plane/basecolor/step11"]
    published = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    record_ids = [r["record_id"] for r in published["private_records"]]
    assert "r1-uzp_plane-basecolor-step10" in record_ids
    assert "r2-uzp_plane-basecolor-step11" in record_ids
    assert len(record_ids) == len(set(record_ids))


def test_a_map_exported_once_keeps_its_record_id(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    assert sample_job.maps_exported_twice == frozenset()
    run = record_texture_golden(make_session(fake.FakeWorld()), sample_job, work, inbox)
    published = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    ids = {r["record_id"] for r in published["private_records"] if r["kind"] == "exported_map"}
    assert ids == {"r1-uzp_plane-basecolor", "r2-uzp_plane-basecolor"}


def test_a_virtual_map_name_with_a_slash_is_one_file() -> None:
    ior = parse_output_map("virtualMap/1/ior:L")
    assert (ior.map_type, ior.name, ior.stem) == ("virtualMap", "1/ior", "1_over_ior")
    assert ior.file_name == "$textureSet_1_over_ior"
    assert ior.preset_map()["channels"][0]["srcMapName"] == "1/ior"
    base = parse_output_map("documentMap/basecolor:RGB")
    assert (base.map_type, base.name, base.file_name) == (
        "documentMap",
        "basecolor",
        "$textureSet_basecolor",
    )
    assert parse_output_map("basecolor:RGB").map_type == "documentMap"


def recorded_manifests() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for root in (REPO_ROOT / "parity" / "manifests", REPO_ROOT / "parity" / "envelopes"):
        for path in sorted(root.rglob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("record_class") == "public_manifest" and data["private_records"]:
                found.append(data)
    return found


def test_every_recorded_manifest_keeps_its_record_ids() -> None:
    """Decision 087 changes an exported map's output id only for a map that two export steps
    of the golden name, or whose name holds a `/`. No golden recorded before the change has an
    output of such a map under the earlier id (two outputs under one id were refused, and the
    base-values goldens' repeated `defaultMap/white` is never written), so every record id
    already in a manifest is the id the recorder now gives. An export probe step (`probe`:
    true, the probe recorder's) is a readback that lists its files' hashes and writes no
    exported-map record, so only the capture exports are counted."""
    manifests = recorded_manifests()
    assert len(manifests) > 100
    for data in manifests:
        steps = [
            s
            for s in data["instruction_sequence"]["steps"]
            if s["call"] == EXPORT
            and "maps" in s.get("args", {})
            and s["args"].get("probe") is not True
        ]
        named = [{parse_output_map(str(m)).name for m in s["args"]["maps"]} for s in steps]
        counts = Counter(name for names in named for name in names)
        twice = {name for name, count in counts.items() if count > 1}
        slashed = {name for ns in named for name in ns if "/" in name}
        ids = [r["record_id"] for r in data["private_records"] if r["kind"] == "exported_map"]
        for name in twice | slashed:
            earlier = f"-{slug(name)}"
            assert not any(i.endswith(earlier) for i in ids), (data["golden_id"], name)


PROBE_CONFIG = {
    "exportShaderParams": False,
    "defaultExportPreset": "uzp_recorder",
    "exportPresets": [
        {
            "name": "uzp_recorder",
            "maps": [
                {
                    "fileName": "$textureSet_lum",
                    "channels": [
                        {
                            "destChannel": "L",
                            "srcChannel": "L",
                            "srcMapType": "documentMap",
                            "srcMapName": "basecolor",
                        }
                    ],
                }
            ],
        }
    ],
    "exportList": [{"rootPath": "uzp_plane"}],
    "exportParameters": [
        {
            "parameters": {
                "fileFormat": "png",
                "bitDepth": "16",
                "dithering": False,
                "paddingAlgorithm": "infinite",
            }
        }
    ],
}


def probe_manifest(
    sample_job: Job, root: Path, configs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """The sample manifest without its export, in a scratch repository root holding its mesh
    and one authored `recipe_json` input per probe configuration."""
    manifest = copy.deepcopy(sample_job.manifest)
    del manifest["instruction_sequence"]["steps"][-1]
    mesh = Path("parity/fixtures/meshes/plane.obj")
    (root / mesh).parent.mkdir(parents=True, exist_ok=True)
    (root / mesh).write_bytes((REPO_ROOT / mesh).read_bytes())
    for input_id, config in configs.items():
        path = Path(f"parity/fixtures/probes/{input_id}.json")
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(config).encode("utf-8")
        (root / path).write_bytes(data)
        manifest["inputs"].append(
            {
                "input_id": input_id,
                "kind": "recipe_json",
                "path": path.as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
            }
        )
    return manifest


def test_export_probes_record_the_dry_run_the_export_and_the_refusal(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    invalid = {**PROBE_CONFIG, "exportPathh": "x"}
    manifest = probe_manifest(sample_job, root, {"lum": PROBE_CONFIG, "typo": invalid})
    job = with_steps(
        manifest,
        [
            {"call": LIST_TEXTURES, "args": {"config": "lum"}},
            {"call": LIST_TEXTURES, "args": {"config": "typo"}},
        ],
        root,
    )
    assert not job.exports and [p.step for p in job.export_probes] == [10, 11]
    run = record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox)
    record = record_of(run)
    for index in (0, 1):
        by_id = {o["output_id"]: o for o in record["recordings"][index]["outputs"]}
        assert by_id["probe/s10/list"]["value"] == {"uzp_plane": ["uzp_plane_lum.png"]}
        assert by_id["probe/s10/list"]["args"] == {"config": "lum"}
        exported = by_id["probe/s10/export"]["value"]
        assert exported["status"] == "Success"
        assert exported["textures"] == {"uzp_plane": ["uzp_plane_lum.png"]}
        assert exported["directory"] == {"missing": [], "unlisted": []}
        blob = by_id["probe/s10/uzp_plane_lum.png"]
        assert blob["kind"] == "exported_map" and blob["texture_set"] == "uzp_plane"
        assert blob["storage_format"]["encoding"] == "undetermined"
        assert blob["export_settings"] == {
            "step": 10,
            "probe": True,
            "encoding_basis": "export_probe",
        }
        refused = by_id["probe/s11/list"]
        assert refused["value"] is None and refused["raised"]["type"] == "ValueError"
        assert "exportPathh" in refused["raised"]["message"]
        assert "probe/s11/export" not in by_id


def test_export_probes_are_checked_before_painter_is_touched(
    sample_job: Job, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    placed = {**PROBE_CONFIG, "exportPath": "C:/anywhere"}
    manifest = probe_manifest(sample_job, root, {"lum": PROBE_CONFIG, "placed": placed})
    with pytest.raises(RecorderError, match="sets `exportPath`"):
        with_steps(
            copy.deepcopy(manifest), [{"call": LIST_TEXTURES, "args": {"config": "placed"}}], root
        )
    with pytest.raises(RecorderError, match="takes only `config`, an input"):
        with_steps(
            copy.deepcopy(manifest), [{"call": LIST_TEXTURES, "args": {"config": "x"}}], root
        )
    probe = {"call": LIST_TEXTURES, "args": {"config": "lum"}}
    fill = copy.deepcopy(manifest["instruction_sequence"]["steps"][1])
    with pytest.raises(RecorderError, match="must precede the captures"):
        with_steps(copy.deepcopy(manifest), [probe, fill], root)


def test_a_bitmap_source_takes_its_colour_space(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    manifest = copy.deepcopy(sample_job.manifest)
    export = manifest["instruction_sequence"]["steps"].pop()
    imported = {
        "call": "substance_painter.resource.import_project_resource",
        "args": {"input": "plane", "usage": "TEXTURE"},
    }
    bitmap = {
        "call": "substance_painter.layerstack.FillLayerNode.set_source",
        "args": {"node_step": 2, "channel": "BaseColor", "resource_step": 10, "color_space": "Raw"},
    }
    job = with_steps(manifest, [imported, bitmap, export])
    record = record_of(record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox))
    for index in (0, 1):
        source = next(
            o["value"]
            for o in outputs(record, index, "api_readback")
            if o["call"].endswith("get_source") and o["args"]["node_step"] == 2
        )
        assert source["bitmap"]["color_space"] == "Raw"


def test_a_converted_virtual_map_exported_twice_is_one_file_per_step(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    """The output id grammar `<set>[/<stack>]/<stem>[/step<n>]`: `1/ior` exported by two steps
    is `<set>/1_over_ior/step<n>`, one file `<set>_1_over_ior` per step (no sub-folder), with
    no encoding claimed (decision 087)."""
    manifest = copy.deepcopy(sample_job.manifest)
    export = copy.deepcopy(manifest["instruction_sequence"]["steps"].pop())
    export["args"]["maps"] = ["virtualMap/1/ior:L"]
    job = with_steps(manifest, [export, copy.deepcopy(export)])
    run = record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox)
    record = record_of(run)
    for index in (0, 1):
        maps = outputs(record, index, "exported_map")
        assert [o["output_id"] for o in maps] == [
            "uzp_plane/1_over_ior/step10",
            "uzp_plane/1_over_ior/step11",
        ]
        assert {o["map"] for o in maps} == {"1/ior"}
        assert {o["storage_format"]["encoding"] for o in maps} == {"undetermined"}
        assert {o["export_settings"]["encoding_basis"] for o in maps} == {"converted_virtual_map"}
    files = sorted(p.name for p in work.rglob("*_1_over_ior.png"))
    assert files == ["uzp_plane_1_over_ior.png"] * 4
    published = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    record_ids = {r["record_id"] for r in published["private_records"]}
    assert "r2-uzp_plane-1_over_ior-step11" in record_ids


def with_project_name(sample_job: Job, *names: Any) -> Job:
    manifest = copy.deepcopy(sample_job.manifest)
    manifest["applied_settings"] += [
        {"name": "project.file_name", "value": name, "applied_by": "recorder_api"} for name in names
    ]
    return job_from_manifest(manifest)


def test_a_golden_may_name_the_file_its_project_is_saved_under(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    """Decision 093: r2's project is `golden.spp` unless the manifest names a file stem in
    `project.file_name` (a project name holding dots, for the `$project` wildcard)."""
    record_texture_golden(make_session(fake.FakeWorld()), sample_job, work / "a", inbox)
    job = with_project_name(sample_job, "golden.dotted")
    record_texture_golden(make_session(fake.FakeWorld()), job, work / "b", inbox)
    assert sorted(p.name for p in work.rglob("*.spp")) == ["golden.dotted.spp", "golden.spp"]


@pytest.mark.parametrize(
    "names",
    [("../golden",), ("a/b",), ("golden.",), ("Golden",), (3,), ("one", "two")],
)
def test_a_project_file_name_that_is_not_one_stem_is_refused_before_painter_is_touched(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    names: tuple[Any, ...],
) -> None:
    world = fake.FakeWorld()
    with pytest.raises(RecorderError, match="must be one file stem"):
        record_texture_golden(
            make_session(world), with_project_name(sample_job, *names), work, inbox
        )
    assert not world.project_open and not inbox.exists() and not work.exists()
