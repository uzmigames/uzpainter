"""Tier 0 goldens of the current envelope (`phase0.7_tier0-semantics-ui-cases`, items 3.1-3.3).

The UI cases (`tier0/semantics-ui/`): the height-to-normal method of each texture set and the
group `Passthrough` mode, set through Painter's UI and named in each manifest's settings sheet
(decisions 029, 047); and the documented-API recordings Phase 1 analyses requested
(`tier0/semantics/resample-uv-minify`, `-impulse`, `group-coverage-order`; decision 048) and,
recorded with task `phase0.9_render-reference-capture`'s Painter session, `blend-component-hue`,
`blend-normal-opacity` and `coverage-srgb8-ties` (decision 067); phase1.12's height-to-normal
requests (decision 077, two with UI-set Sobel sets) and phase1.9's texture-unit validation
recordings (decision 078); phase1.15's export recordings R-085 and R-086 (decision 087). Store
and guard checks that need the owner's private store skip, saying so, without one (decision 028).
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.guard.guard import Snapshot, load_index, run_guard, worktree_snapshot
from tools.parity.recorder.capture import decode_png
from tools.parity.recorder.job import load_job
from tools.parity.recorder.texture_sheet import texture_sheet
from tools.parity.recorder.vocabulary import LIST_TEXTURES
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.manifest import verify
from tools.parity.store.store import Status, load_oracle, locate
from tools.parity.tier0_semantics import fixtures
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR, MESH_SETS
from tools.parity.tier0_semantics.current import (
    AMPLITUDES,
    ANISOTROPIC_CHANNELS,
    CONVERTED_MAPS,
    FLAT_CASES,
    GROUP_MASKS,
    HEIGHT_METHODS,
    HEIGHT_RESOLUTIONS,
    LOD_BOUNDARY_CHANNELS,
    LOD_CHANNELS,
    NORMAL_CHANNELS,
    NORMAL_OPACITIES,
    PASSTHROUGH,
    ROTATION_CHANNELS,
    SEMANTICS_DIR,
    SOBEL_RESOLUTION,
    TIE_CHANNELS,
    TIE_MULTI,
    UI_DIR,
    api_goldens,
    export_goldens,
    request_goldens,
    ui_goldens,
    validation_goldens,
)

ENVELOPE_ROOT = manifest_root(current_envelope())


def ui_paths() -> list[Path]:
    return sorted((ENVELOPE_ROOT / UI_DIR).glob("*.json"))


def api_paths() -> list[Path]:
    return [ENVELOPE_ROOT / SEMANTICS_DIR / f"{g.name}.json" for g in api_goldens()]


def needs_store() -> Any:
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")
    return store


def test_the_ui_corpus_is_committed() -> None:
    assert [p.stem for p in ui_paths()] == sorted(g.name for g in ui_goldens())
    assert all(p.is_file() for p in api_paths())


def output_key(record_id: str) -> str:
    """A record id without its recording; an export probe's file only by its probe step, since
    the file name is the observation and may depend on the condition (`$project` names the
    unsaved project in r1 and the saved one in r2; decision 087)."""
    probe = re.match(r"probe-s\d+-", record_id)
    return (
        probe.group(0) + "file"
        if probe and not record_id.endswith(("-list", "-export"))
        else record_id
    )


@pytest.mark.parametrize("path", [*ui_paths(), *api_paths()], ids=lambda p: p.stem)
def test_manifest_validates_and_lists_two_recordings(path: Path) -> None:
    """Item 3.1: schema, the current envelope's build, and `r1`/`r2` of every exported map."""
    manifest = load_json(path)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["software"]["painter"]["build_id"] == current_envelope()["painter_build"]
    records = manifest["private_records"]
    assert any(r["kind"] == "private_oracle_record" for r in records)
    r1 = sorted(output_key(r["record_id"][3:]) for r in records if r["record_id"][:3] == "r1-")
    r2 = sorted(output_key(r["record_id"][3:]) for r in records if r["record_id"][:3] == "r2-")
    assert r1 and r1 == r2, "both recordings carry the same outputs"
    kinds = {r["kind"] for r in records}
    assert "exported_map" in kinds
    if texture_sheet(load_job(path)):
        assert "settings_panel_evidence" in kinds, "each UI value has private panel evidence"


@pytest.mark.parametrize("path", ui_paths(), ids=lambda p: p.stem)
def test_every_ui_set_value_is_named_in_the_settings_sheet(path: Path) -> None:
    """Item 3.1: each UI-set setting is in `applied_settings` (`operator_settings_sheet`)."""
    job = load_job(path)
    sheet = texture_sheet(job)
    assert sheet, "a UI-case golden names its UI-set values"
    if path.stem.startswith("height-normal-"):
        method = HEIGHT_METHODS[path.stem.split("-")[2]]
        create = job.state_steps[0].args["mesh"]
        assert sorted(str(e.texture_set) for e in sheet) == sorted(MESH_SETS[create])
        assert {e.value for e in sheet} == {method}
        if path.stem.endswith("-plane-strength"):
            assert len(AMPLITUDES) == len(MESH_SETS["grid4x2"]) == 8
    else:
        groups = [s.step for s in job.state_steps if s.call.endswith("insert_group")]
        passthrough = groups[: len(GROUP_MASKS)]
        assert {(e.node_step, e.channel) for e in sheet} == {
            (g, c) for g in passthrough for c in ("User0", "User1", "User2")
        }
        assert {e.value for e in sheet} == {PASSTHROUGH}


def test_every_manifest_hash_resolves_in_the_store() -> None:
    """Item 3.2: `uzpainter parity verify` over every manifest (owner's machine)."""
    store = needs_store()
    for path in [*ui_paths(), *api_paths()]:
        results = verify(store, load_json(path))
        assert results and all(r.status == Status.AVAILABLE for r in results), path.stem


def stored_record(store: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    ref = next(r for r in manifest["private_records"] if r["kind"] == "private_oracle_record")
    data = load_oracle(store, ref)
    assert data is not None
    record: dict[str, Any] = json.loads(data)
    return record


def sheet_paths() -> list[Path]:
    """Every manifest of this module whose settings sheet names UI-set values."""
    return [p for p in [*ui_paths(), *api_paths()] if texture_sheet(load_job(p))]


@pytest.mark.parametrize("path", sheet_paths(), ids=lambda p: p.stem)
def test_stored_records_hold_the_verified_sheet_in_both_recordings(path: Path) -> None:
    """Item 4.1: every UI-set value was verified when applied (r1) and after the reopen (r2);
    a layer's mode also through the documented `Node.get_blending_mode`."""
    store = needs_store()
    manifest = load_json(path)
    sheet = texture_sheet(load_job(path))
    record = stored_record(store, manifest)
    assert [r["condition"] for r in record["recordings"]] == ["same_session", "after_save_reopen"]
    for recording in record["recordings"]:
        outputs = recording["outputs"]
        (entries,) = [o["entries"] for o in outputs if o["kind"] == "operator_recorded_settings"]
        assert {(e["panel"], e["setting"], e["value"]) for e in entries} == {
            (e.panel, e.name.split("/", 1)[1], e.value) for e in sheet
        }
        assert sum(o["kind"] == "settings_panel_evidence" for o in outputs) == len(sheet)
        modes = {
            (o["args"]["node_step"], o["args"]["channel"]): o["value"]
            for o in outputs
            if o["kind"] == "api_readback" and o["call"].endswith("get_blending_mode")
        }
        for entry in sheet:
            if entry.node_step is not None:
                assert modes[(entry.node_step, entry.channel)] == entry.value


def test_the_ui_corpus_passes_the_guard() -> None:
    """Item 3.3: only manifests and authored fixtures are committed."""
    snapshot = worktree_snapshot(
        REPO_ROOT,
        (
            (ENVELOPE_ROOT / UI_DIR).relative_to(REPO_ROOT).as_posix(),
            (ENVELOPE_ROOT / SEMANTICS_DIR).relative_to(REPO_ROOT).as_posix(),
            FIXTURE_DIR,
        ),
    )
    assert snapshot.checked
    store = locate()
    index = None if store is None else load_index(store.root / "index.json")
    assert [str(f) for f in run_guard(REPO_ROOT, snapshot, index)] == []


@pytest.mark.parametrize("kind", ["settings_panel_evidence", "exported_map"])
def test_a_panel_image_or_export_placed_in_the_repository_is_rejected(kind: str) -> None:
    """Item 3.3: a stored panel image or export staged in the repository is blocked by hash."""
    store = needs_store()
    index = load_index(store.root / "index.json")
    ref = next(r for p in ui_paths() for r in load_json(p)["private_records"] if r["kind"] == kind)
    data = load_oracle(store, ref)
    assert data is not None
    path = f"{FIXTURE_DIR}/bitmaps/recorded-{kind}.png"
    findings = run_guard(REPO_ROOT, Snapshot((path,), (path,), lambda _: data), index)
    assert any(f.rule == "store-hash" for f in findings)


def png_rows(data: bytes) -> list[list[tuple[int, int, int]]]:
    """Rows of a filter-0 RGB16 PNG written by `fixtures.png16`."""
    chunks: dict[str, bytes] = {}
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        name = data[offset + 4 : offset + 8].decode("ascii")
        chunks[name] = chunks.get(name, b"") + data[offset + 8 : offset + 8 + length]
        offset += length + 12
    width, height = struct.unpack(">II", chunks["IHDR"][:8])
    raw = zlib.decompress(chunks["IDAT"])
    stride = 1 + width * 6
    return [
        [
            struct.unpack(">HHH", raw[y * stride + 1 + x * 6 : y * stride + 7 + x * 6])
            for x in range(width)
        ]
        for y in range(height)
    ]


def test_impulse_fixture_matches_the_request() -> None:
    """compositor-resample-gaps.md section 3: R impulses on 0, G impulses on 16384, B step."""
    rows = png_rows((REPO_ROOT / FIXTURE_DIR / "bitmaps" / "impulse64.png").read_bytes())
    assert len(rows) == len(rows[0]) == 64
    for y, row in enumerate(rows):
        for x, (r, g, b) in enumerate(row):
            hit = (x, y) in fixtures.IMPULSE_TEXELS
            assert (r, g, b) == (65535 if hit else 0, 49152 if hit else 16384, 65535 * (x < 32))


def bitmap(name: str) -> list[list[tuple[int, ...]]]:
    image = decode_png(REPO_ROOT / FIXTURE_DIR / "bitmaps" / f"{name}.png")
    texels = [tuple(texel) for texel in image.pixels]
    return [texels[y * image.width : (y + 1) * image.width] for y in range(image.height)]


def test_hue_grid_follows_the_recorded_layout() -> None:
    """Decision 067: per row group r the centre 3855 (r + 1); sectors x chromas x middle
    positions, then the six tie types at every chroma, then grey; the transposed and grey
    fixtures are exact transforms of it."""
    grid = bitmap("hue-grid")
    transposed, grey = bitmap("hue-grid-transposed"), bitmap("hue-grid-grey")
    flipped_grey = bitmap("hue-grid-transposed-grey")
    for y in range(256):
        for x in range(256):
            assert transposed[x][y] == grid[y][x]
            assert grey[y][x] == grid[y][x][:1] and flipped_grey[x][y] == grid[y][x][:1]
    for r in range(16):
        centre = 3855 * (r + 1)

        def case(t: int, r: int = r) -> tuple[int, ...]:
            return grid[16 * r + t // 256][t % 256]

        t = 0
        for top, middle in fixtures.HUE_SECTORS:
            for d in fixtures.HUE_CHROMAS:
                for u in (0, 1, d // 4, d // 2, 3 * d // 4, d - 1, d):
                    texel = case(t)
                    low = centre - d // 2
                    assert (texel[top], texel[middle], min(texel)) == (low + d, low + u, low)
                    t += 1
        for (a, b), pair_is_max in fixtures.HUE_TIES:
            for d in fixtures.HUE_CHROMAS:
                texel = case(t)
                assert texel[a] == texel[b] and max(texel) - min(texel) == d
                assert (texel[a] == max(texel)) == pair_is_max
                t += 1
        assert t == fixtures.HUE_GREY and case(t) == (centre,) * 3
        for t in range(fixtures.HUE_GREY + 1, 4096):
            assert 0 < max(case(t)) - min(case(t)) <= fixtures.HUE_MAX_CHROMA


def opacities(name: str) -> dict[tuple[str, str], float]:
    """(texture set, channel) -> the opacity of the last fill that sets one there."""
    steps = load_json(ENVELOPE_ROOT / SEMANTICS_DIR / f"{name}.json")["instruction_sequence"]
    by_step = {s["step"]: s for s in steps["steps"]}
    found: dict[tuple[str, str], float] = {}
    for step in steps["steps"]:
        if not step["call"].endswith("set_opacity"):
            continue
        node = step["args"]["node_step"]
        while "texture_set" not in by_step[node]["args"]:
            args = by_step[node]["args"]
            node = args.get("above_step") or args.get("inside_step")
        found[(by_step[node]["args"]["texture_set"], step["args"]["channel"])] = step["args"][
            "opacity"
        ]
    return found


def test_coverage_ties_put_row_zero_on_every_8_bit_tie() -> None:
    """Decision 067: User0-User7 opacities (2k + 1)/510 for k = 64..127, the row 0 coverage
    on the tie (k + 1/2)/255; User8 and User9 the opacities with several tied rows."""
    found = opacities("coverage-srgb8-ties")
    ks = []
    for i, texture_set in enumerate(MESH_SETS["grid4x2"]):
        for j in range(8):
            value = found[(texture_set, f"User{j}")]
            k = round(value * 255.0 - 0.5)
            assert abs(value * 255.0 - (k + 0.5)) < 1e-9
            ks.append(k)
        assert found[(texture_set, "User8")] == found[(texture_set, "User9")] == TIE_MULTI[i]
    assert ks == list(range(64, 128))
    assert dict(TIE_CHANNELS)["User9"] == "RGB32F"
    assert {f for c, f in TIE_CHANNELS if c != "User9"} == {"sRGB8"}


def test_normal_opacity_sets_follow_the_request() -> None:
    """compositor-blend-gaps.md section 5: s0-s2 at 0.1, 1/3, 0.7, 0.99 per format; s3-s5 the
    flat-normal cases at 0.5 (and flat under flat at 1)."""
    found = opacities("blend-normal-opacity")
    sets = MESH_SETS["grid4x2"]
    for index in range(3):
        for i, (channel, _) in enumerate(NORMAL_CHANNELS):
            assert found[(sets[index], channel)] == NORMAL_OPACITIES[i % 4]
            assert found[(sets[index + 3], channel)] == FLAT_CASES[i % 4][2]
    assert not any(key[0] in sets[6:] for key in found)


def test_the_8_bit_normal_copy_holds_the_nearest_8_bit_codes() -> None:
    """Decision 077: normal-a-8bit is round(c / 257) of each 16-bit code of normal-a."""
    wide = decode_png(REPO_ROOT / FIXTURE_DIR / "bitmaps" / "normal-a.png")
    narrow = decode_png(REPO_ROOT / FIXTURE_DIR / "bitmaps" / "normal-a-8bit.png")
    assert (narrow.width, narrow.height) == (wide.width, wide.height) == (256, 256)
    for low, high in zip(narrow.pixels, wide.pixels, strict=True):
        assert tuple(low) == tuple(round(c / 257) for c in high)


def manifest_of(name: str) -> dict[str, Any]:
    data: dict[str, Any] = load_json(ENVELOPE_ROOT / SEMANTICS_DIR / f"{name}.json")
    return data


def test_the_resolution_goldens_change_only_the_resolution() -> None:
    """Decision 077: plane-amplitudes' sequence at 512, 1024, 2048 px; Sobel on s0 at 1024."""
    base = load_json(
        REPO_ROOT / "parity/manifests/tier0/semantics/height-normal-plane-amplitudes.json"
    )
    steps = base["instruction_sequence"]["steps"]
    for name, resolution in (
        *((f"height-normal-resolution-{r}", r) for r in HEIGHT_RESOLUTIONS),
        (f"height-normal-resolution-{SOBEL_RESOLUTION}-sobel", SOBEL_RESOLUTION),
    ):
        manifest = manifest_of(name)
        recorded = manifest["instruction_sequence"]["steps"]
        assert recorded[0]["args"]["default_texture_resolution"] == resolution
        assert recorded[1:] == steps[1:]
        assert {
            k: v for k, v in recorded[0]["args"].items() if k != "default_texture_resolution"
        } == {k: v for k, v in steps[0]["args"].items() if k != "default_texture_resolution"}
        sheet = texture_sheet(load_job(ENVELOPE_ROOT / SEMANTICS_DIR / f"{name}.json"))
        expected = {("s0", HEIGHT_METHODS["sobel"])} if name.endswith("-sobel") else set()
        assert {(str(e.texture_set), e.value) for e in sheet} == expected


def test_the_height_normal_requests_follow_decision_077() -> None:
    """Formats, the mesh map binding and the Sobel sets of the requested goldens; their domains
    stay outside EXC-003's `tier0/height-normal/method`."""
    for golden in request_goldens():
        manifest = manifest_of(golden.name)
        assert manifest["domain"] != "tier0/height-normal/method"
        create = manifest["instruction_sequence"]["steps"][0]["args"]
        directx = golden.name.endswith("-directx")
        assert create["normal_map_format"] == ("DirectX" if directx else "OpenGL")
        settings = {s["name"]: s["value"] for s in manifest["applied_settings"]}
        assert settings["project.normal_map_format"] == create["normal_map_format"]
        assert settings["texture_set.resolution"] == create["default_texture_resolution"]
    for name, sobel in (
        ("height-normal-mesh-map", ["s4", "s5", "s6", "s7"]),
        ("height-normal-mesh-map-directx", []),
    ):
        steps = manifest_of(name)["instruction_sequence"]["steps"]
        (bind,) = [s for s in steps if s["call"].endswith("set_mesh_map_resource")]
        imported = {
            s["step"]: s["args"]["input"]
            for s in steps
            if s["call"].endswith("import_project_resource")
        }
        assert bind["args"] == {
            "usage": "Normal",
            "resource_step": next(k for k, v in imported.items() if v == "normal-b"),
        }
        sheet = texture_sheet(load_job(ENVELOPE_ROOT / SEMANTICS_DIR / f"{name}.json"))
        assert sorted(str(e.texture_set) for e in sheet) == sobel


def test_the_lod_boundary_scales_sit_on_integer_lods() -> None:
    """Decision 078: BilinearSharp reaches LOD k at 4 * 2^(k + 1.5), BilinearHQ at 12 * 2^k
    (footprint scale / 4 texels of pattern64 at 256 px)."""
    scales = [scale[0] for scale, _, _ in LOD_BOUNDARY_CHANNELS]
    for k in (0, 1, 2):
        assert 4.0 * 2.0 ** (k + 1.5) in scales and 12.0 * 2.0**k in scales
    assert len(LOD_BOUNDARY_CHANNELS) == 10
    for plan in (ANISOTROPIC_CHANNELS, LOD_CHANNELS, LOD_BOUNDARY_CHANNELS):
        assert [0.0, 0.0] in [offset for _, _, offset in plan], "a zero-offset twin"
    axis_aligned = [r for _, r, _ in ROTATION_CHANNELS if r % 90.0 == 0.0 and r]
    assert axis_aligned == [90.0, 180.0, 270.0]
    for golden in validation_goldens():
        steps = manifest_of(golden.name)["instruction_sequence"]["steps"]
        assert sum(s["call"].endswith("set_projection_parameters") for s in steps) == 4 * len(
            [s for s in steps if s["call"].endswith("add_channel")]
        )


def test_the_export_recordings_follow_decision_087() -> None:
    """R-086: each export step repeated once in the same session (outputs keyed by step), the
    twin only in OpenEXR 32f; R-085: every probe step names a hash-pinned recipe_json input,
    the generator's configuration without exportPath."""
    names = [g.name for g in export_goldens()]
    for name in ("ao-mixed-opacity", "virtual-maps-converted"):
        for twin, (file_format, depth) in ((name, ("png", 16)), (f"{name}-float", ("exr", "32f"))):
            steps = manifest_of(twin)["instruction_sequence"]["steps"]
            exports = [s["args"] for s in steps if s["call"].endswith("export_project_textures")]
            assert len(exports) == 2 and exports[0] == exports[1]
            assert (exports[0]["file_format"], exports[0]["bit_depth"]) == (file_format, depth)
            job = load_job(ENVELOPE_ROOT / SEMANTICS_DIR / f"{twin}.json")
            assert job.maps_exported_twice == {m.name for m in job.exports[0].maps}
            ids = {r["record_id"] for r in manifest_of(twin)["private_records"]}
            for step in (e.step for e in job.exports):
                assert any(i.startswith("r1-") and i.endswith(f"-step{step}") for i in ids)
        plain, float_twin = (
            manifest_of(n)["instruction_sequence"]["steps"] for n in (name, f"{name}-float")
        )
        assert [s for s in plain if "file_format" not in s["args"]] == [
            s for s in float_twin if "file_format" not in s["args"]
        ]
    assert "virtualMap/1/ior:L" in CONVERTED_MAPS and len(CONVERTED_MAPS) == 10
    probes = fixtures.export_probes()
    for name in names:
        if not name.startswith("export-probes-"):
            continue
        manifest = manifest_of(name)
        inputs = {i["input_id"]: i for i in manifest["inputs"]}
        steps = [s for s in manifest["instruction_sequence"]["steps"] if s["call"] == LIST_TEXTURES]
        group = name.removeprefix("export-probes-")
        assert [s["args"]["config"] for s in steps] == [f"probe-{group}-{p}" for p in probes[group]]
        for step in steps:
            item = inputs[step["args"]["config"]]
            assert item["kind"] == "recipe_json"
            data = (REPO_ROOT / item["path"]).read_bytes()
            config = json.loads(data)
            assert "exportPath" not in config
            assert config == probes[group][item["input_id"].removeprefix(f"probe-{group}-")]
