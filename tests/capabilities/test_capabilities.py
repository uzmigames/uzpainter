"""Capability manifest generator (phase1.2_docmodel-capability-manifest, items 3.1-3.5).

`tools/capabilities/generate_capabilities.py` turns the documented Painter symbol inventory and
the UzPainter additions into `capabilities.json` (docs/architecture/10-python-api.md §3). These
tests run on the CPU lane; the python-doc comparison runs where Painter's public
documentation is available, the build-step comparison where `zig` is on PATH.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tools.capabilities.generate_capabilities import (
    ADDITIONS_PATH,
    INVENTORY_PATH,
    GenerationError,
    generate,
    render,
)
from tools.parity.recorder.provenance import documented_symbols, inventory_symbols

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "tools" / "capabilities" / "generate_capabilities.py"
SCHEMA_PATH = REPO_ROOT / "tools" / "capabilities" / "capabilities.schema.json"
PROJECT_H = REPO_ROOT / "src" / "uzp_core" / "types" / "project.h"
PYTHON_DOC_ENV = "UZP_PAINTER_PYTHON_DOC"
DEFAULT_OBJECTS_INV = Path(
    r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\python-doc\objects.inv"
)
TIER0_GOLDEN = "tier0/api-probes/fill-layer-readback"

# The release gaps named in docs/architecture/10-python-api.md §3 (item 3.4).
RELEASE_GAPS = {
    ("substance_painter.layerstack.PaintLayerNode", "bitmap-or-projection-content"),
    ("substance_painter.layerstack.PaintEffectNode", "bitmap-or-projection-content"),
    ("substance_painter.layerstack.ProjectionMode.Warp", "any"),
    ("substance_painter.layerstack.WarpProjectionParams", "any"),
    ("substance_painter.layerstack.ProjectionMode.UVSetToUVSet", "any"),
    ("substance_painter.layerstack.UVSetToUVSetProjectionParams", "any"),
    ("substance_painter.project.ProjectWorkflow.UVTile", "any"),
    ("substance_painter.project.ProjectWorkflow.TextureSetPerUVTile", "any"),
    ("substance_painter.project.AutoUnwrapSettings", "any"),
    ("substance_painter.source.SourceVectorial", "any"),
    ("substance_painter.source.SourceFont", "any"),
    ("substance_painter.textureset.TextureSet", "material-layering"),
    ("substance_painter.export.export_mesh", "file-format:usd"),
    ("substance_painter.export.export_project_textures", "file-format:tiff"),
    ("substance_painter.export.export_project_textures", "file-format:psd"),
    ("substance_painter.export.export_project_textures", "file-format:webp"),
    ("substance_painter.export.export_project_textures", "file-format:j2k"),
    ("substance_painter.source.SourceSubstance", "arbitrary-sbsar"),
    ("substance_painter.baking.bake_async", "cage-mode:automatic"),
}

# The desktop-only members named in docs/architecture/10-python-api.md §3.
DESKTOP_ONLY = {
    "substance_painter.ui.show_main_window",
    "substance_painter.ui.get_main_window",
    "substance_painter.ui.get_layout",
    "substance_painter.ui.get_layout_mode",
    "substance_painter.ui.set_layout",
    "substance_painter.ui.reset_layout",
    "substance_painter.ui.add_dock_widget",
    "substance_painter.ui.add_menu",
    "substance_painter.ui.add_toolbar",
    "substance_painter.ui.add_plugins_toolbar_widget",
    "substance_painter.ui.add_action",
    "substance_painter.ui.delete_ui_element",
    "substance_painter.resource.Resource.show_in_ui",
    "substance_painter.resource.show_resources_in_ui",
    "substance_painter.event.GraphicalUserInterfaceStarted",
}


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return generate()


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def inventory_entry(inventory: dict[str, Any], symbol: str, context: str = "any") -> dict[str, Any]:
    entries = [e for e in inventory["entries"] if (e["symbol"], e["context"]) == (symbol, context)]
    assert len(entries) == 1, (symbol, context)
    entry: dict[str, Any] = entries[0]
    return entry


def generation_error(tmp_path: Path, inventory: dict[str, Any]) -> str:
    with pytest.raises(GenerationError) as error:
        generate(inventory_path=write(tmp_path / "inventory.json", inventory))
    return str(error.value)


# ── 3.1 Determinism ────────────────────────────────────────────────────────────────────────


def test_two_generations_are_byte_identical(tmp_path: Path) -> None:
    outputs = []
    for name in ("first.json", "second.json"):
        out = tmp_path / name
        proc = subprocess.run(
            [sys.executable, "-I", str(GENERATOR), "--output", str(out)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    assert outputs[0] == render(generate())


def test_entries_are_sorted_and_unique(manifest: dict[str, Any]) -> None:
    keys = [(e["symbol"], e["context"]) for e in manifest["entries"]]
    assert keys == sorted(set(keys))


def test_zig_build_step_emits_the_generated_manifest(tmp_path: Path) -> None:
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH")
    build = subprocess.run(
        [zig, "build", "capabilities", "--prefix", str(tmp_path), f"-Dpython={sys.executable}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    assert (tmp_path / "bin" / "capabilities.json").read_bytes() == render(generate())


# ── 3.2 Schema ─────────────────────────────────────────────────────────────────────────────


def test_every_entry_validates_against_the_schema(manifest: dict[str, Any]) -> None:
    schema = load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert [e.message for e in validator.iter_errors(manifest)] == []
    assert len(manifest["entries"]) > 700


def test_schema_rejects_an_unsupported_claim(manifest: dict[str, Any]) -> None:
    validator = Draft202012Validator(load(SCHEMA_PATH))
    bad = copy.deepcopy(manifest)
    entry = next(e for e in bad["entries"] if not e["tier_evidence"])
    entry["status"] = "supported"
    entry["since"] = "0.1.0"
    assert not validator.is_valid(bad)


def test_compat_profile_is_the_document_model_profile(manifest: dict[str, Any]) -> None:
    match = re.search(r'kCompatProfile = "([^"]+)"', PROJECT_H.read_text(encoding="utf-8"))
    assert match is not None
    assert manifest["compat_profile"] == match.group(1)


# ── 3.3 Statuses require evidence ──────────────────────────────────────────────────────────


def test_supported_entry_without_tier_evidence_fails_naming_it(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    entry = inventory_entry(inventory, "substance_painter.layerstack.Node.set_opacity")
    entry.update(status="supported", since="0.1.0", tier_evidence=[])
    message = generation_error(tmp_path, inventory)
    assert "substance_painter.layerstack.Node.set_opacity" in message
    assert "tier_evidence" in message


def test_supported_entry_with_tier0_evidence_is_generated(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    entry = inventory_entry(inventory, "substance_painter.layerstack.Node.set_opacity")
    entry.update(status="supported", since="0.1.0", tier_evidence=[TIER0_GOLDEN])
    result = generate(inventory_path=write(tmp_path / "inventory.json", inventory))
    symbol = "substance_painter.layerstack.Node.set_opacity"
    (generated,) = [e for e in result["entries"] if e["symbol"] == symbol]
    assert generated["status"] == "supported"
    assert generated["tier_evidence"] == [TIER0_GOLDEN]
    assert Draft202012Validator(load(SCHEMA_PATH)).is_valid(result)


def test_supported_entry_naming_an_unknown_golden_fails(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    entry = inventory_entry(inventory, "substance_painter.layerstack.Node.set_opacity")
    entry.update(status="supported", since="0.1.0", tier_evidence=["tier0/api-probes/missing"])
    assert "names no Tier 0 public manifest" in generation_error(tmp_path, inventory)


def test_pending_evidence_entry_without_owner_fails_naming_it(tmp_path: Path) -> None:
    """Decision 112: an implemented symbol without Tier 0 evidence names who settles it."""
    inventory = load(INVENTORY_PATH)
    entry = next(e for e in inventory["entries"] if e["status"] == "pending-evidence")
    entry["notes"] = "Implemented, without Tier 0 evidence yet."
    message = generation_error(tmp_path, inventory)
    assert entry["symbol"] in message
    assert "owns its evidence" in message


def test_desktop_only_entry_without_justification_fails_naming_it(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    del inventory_entry(inventory, "substance_painter.ui.add_menu")["justification"]
    message = generation_error(tmp_path, inventory)
    assert "substance_painter.ui.add_menu" in message
    assert "justification" in message


def test_desktop_only_entries_are_the_documented_list(manifest: dict[str, Any]) -> None:
    omitted = [e for e in manifest["entries"] if e["status"] == "desktop-only-omitted"]
    assert {e["symbol"] for e in omitted} == DESKTOP_ONLY
    assert all(
        e["notes"] and "changes no texture, render or script-visible state" in e["notes"]
        for e in omitted
    )


# ── 3.4 Release gaps ───────────────────────────────────────────────────────────────────────


def test_listed_release_gaps_are_present(manifest: dict[str, Any]) -> None:
    status = {(e["symbol"], e["context"]): e for e in manifest["entries"]}
    for key in sorted(RELEASE_GAPS):
        assert key in status, key
        assert status[key]["status"] == "release-gap", key
        assert status[key]["notes"] and "Release gap" in status[key]["notes"], key


def test_dropping_a_release_gap_fails_generation(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    usd = ("substance_painter.export.export_mesh", "file-format:usd")
    inventory["entries"] = [e for e in inventory["entries"] if (e["symbol"], e["context"]) != usd]
    assert "file-format:usd" in generation_error(tmp_path, inventory)


# ── 3.5 Documented symbols only, no brush strokes ──────────────────────────────────────────


def test_every_painter_entry_cites_its_documentation_anchor(manifest: dict[str, Any]) -> None:
    anchor = re.compile(r"^python-doc/[A-Za-z0-9_/]+\.html(#([A-Za-z0-9_.-]+))?$")
    for entry in manifest["entries"]:
        if not entry["symbol"].startswith("substance_painter"):
            continue
        fragments = [m.group(2) for m in map(anchor.match, entry["evidence"]) if m]
        assert fragments, entry["symbol"]
        target = (fragments[0] or entry["symbol"]).removeprefix("module-")
        assert entry["symbol"] == target or entry["symbol"].startswith(target + ".")


def test_entry_without_documentation_anchor_fails(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    inventory_entry(inventory, "substance_painter.project.open")["evidence"] = ["T0-probes"]
    message = generation_error(tmp_path, inventory)
    assert "substance_painter.project.open" in message
    assert "documentation anchor" in message


def test_anchor_of_another_symbol_fails(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    inventory_entry(inventory, "substance_painter.project.open")["evidence"] = [
        "python-doc/substance_painter/project.html#substance_painter.project.close"
    ]
    assert "substance_painter.project.open" in generation_error(tmp_path, inventory)


def test_no_brush_stroke_symbol_exists(manifest: dict[str, Any]) -> None:
    assert [e["symbol"] for e in manifest["entries"] if "stroke" in e["symbol"].lower()] == []


def test_brush_stroke_symbol_fails_generation(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    inventory["entries"].append(
        {
            "symbol": "substance_painter.layerstack.PaintLayerNode.add_stroke",
            "context": "any",
            "status": "release-gap",
            "evidence": [
                "python-doc/substance_painter/layerstack/layereffect/paint.html"
                "#substance_painter.layerstack.PaintLayerNode"
            ],
        }
    )
    assert "out of scope" in generation_error(tmp_path, inventory)


def test_inventory_lists_painter_symbols_only(tmp_path: Path) -> None:
    inventory = load(INVENTORY_PATH)
    inventory["entries"].append(
        {
            "symbol": "uzpainter.jobs.list",
            "context": "mask-stack",
            "status": "release-gap",
            "evidence": ["python-doc/substance_painter/index.html"],
        }
    )
    assert "documented Painter symbols only" in generation_error(tmp_path, inventory)


def test_additions_cite_existing_architecture_sections(tmp_path: Path) -> None:
    additions = load(ADDITIONS_PATH)
    additions["entries"][0]["evidence"] = ["docs/architecture/10-python-api.md#no-such-section"]
    with pytest.raises(GenerationError, match="existing sections"):
        generate(additions_path=write(tmp_path / "additions.json", additions))


def test_inventory_covers_every_recorded_documented_symbol() -> None:
    """Every symbol of documented_symbols.json (enum members included) has a status."""
    inventory = load(INVENTORY_PATH)
    anchors = {e["symbol"]: e["evidence"] for e in inventory["entries"] if e["context"] == "any"}
    for symbol, documented in documented_symbols().items():
        assert symbol in anchors, symbol
        owner = documented["documented_as"]
        page = f"python-doc/{documented['page']}"
        expected = page if "/" in owner else f"{page}#{owner}"
        assert any(e == expected or e.startswith(page + "#") for e in anchors[symbol]), symbol


def test_inventory_matches_the_python_doc_inventory() -> None:
    """Every Python object of Painter 12.1.0's python-doc has an entry, and every anchor exists.

    Runs where the public documentation is available: `UZP_PAINTER_PYTHON_DOC` names its
    `objects.inv`, or Painter is installed at the default location (the owner's machine).
    """
    objects_inv = Path(os.environ.get(PYTHON_DOC_ENV, DEFAULT_OBJECTS_INV))
    if not objects_inv.is_file():
        pytest.skip(f"python-doc inventory not available ({objects_inv})")
    documented = inventory_symbols(objects_inv)
    python_objects = {name for name in documented if "/" not in name and name.startswith("sub")}
    inventory = load(INVENTORY_PATH)
    listed = {e["symbol"] for e in inventory["entries"] if e["context"] == "any"}
    assert sorted(python_objects - listed) == []
    for entry in inventory["entries"]:
        anchors = [e for e in entry["evidence"] if e.startswith("python-doc/")]
        assert anchors, entry["symbol"]
        for anchor in anchors:
            page, _, fragment = anchor.removeprefix("python-doc/").partition("#")
            name = fragment.removeprefix("module-") if fragment else page.removesuffix(".html")
            assert documented.get(name) == page, (entry["symbol"], anchor)


# ── Compositor registrations (phase1.14_compositor-core item 2.8, decision 081) ────────────

COMPOSITOR_PATH = REPO_ROOT / "tools" / "capabilities" / "compositor-capabilities.json"
RULEBOOK = REPO_ROOT / ".rulebook"
# Every Phase 1 node kind, source, projection, sampling mode and blend mode the compositor
# registers (the documented members of these enums and classes).
COMPOSITOR_FAMILIES = {
    "BlendingMode": ("substance_painter.layerstack.BlendingMode.", 32),
    "ProjectionMode": ("substance_painter.layerstack.ProjectionMode.", 8),
    "FilteringMode": ("substance_painter.layerstack.FilteringMode.", 3),
    "UVWrapMode": ("substance_painter.layerstack.UVWrapMode.", 4),
    "ScaleMode": ("substance_painter.layerstack.ScaleMode.", 3),
}
COMPOSITOR_NODES = {
    "substance_painter.layerstack.FillLayerNode",
    "substance_painter.layerstack.GroupLayerNode",
    "substance_painter.layerstack.InstanceLayerNode",
    "substance_painter.layerstack.PaintLayerNode",
    "substance_painter.layerstack.FillEffectNode",
    "substance_painter.layerstack.LevelsEffectNode",
    "substance_painter.layerstack.FilterEffectNode",
    "substance_painter.layerstack.GeneratorEffectNode",
    "substance_painter.layerstack.PaintEffectNode",
    "substance_painter.layerstack.CompareMaskEffectNode",
    "substance_painter.layerstack.ColorSelectionEffectNode",
    "substance_painter.layerstack.AnchorPointEffectNode",
    "substance_painter.layerstack.GeometryMaskMeshParams",
    "substance_painter.layerstack.GeometryMaskUVTilesParams",
    "substance_painter.source.SourceUniformColor",
    "substance_painter.source.SourceBitmap",
    "substance_painter.source.SourceSubstance",
    "substance_painter.source.SourceVectorial",
    "substance_painter.source.SourceFont",
    "substance_painter.source.SourceReference",
}


def compositor_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in manifest["entries"] if e["context"].split(":")[0] == "compositor"]


def test_compositor_registers_every_phase1_kind(manifest: dict[str, Any]) -> None:
    """2.8: every node kind, source, projection, sampling mode and blend mode has a compositor
    entry (supported with Tier 0 evidence, or a release gap); the API context is supported only
    with Tier 0 evidence of its own (phase1.22, decision 112)."""
    entries = compositor_entries(manifest)
    symbols = {e["symbol"] for e in entries}
    assert symbols >= COMPOSITOR_NODES
    inventory = {e["symbol"] for e in load(INVENTORY_PATH)["entries"] if e["context"] == "any"}
    for prefix, count in COMPOSITOR_FAMILIES.values():
        members = {
            s for s in inventory if s.startswith(prefix) and s.count(".") == prefix.count(".")
        }
        assert len(members) == count, prefix
        assert members <= symbols, sorted(members - symbols)
    api = {e["symbol"]: e for e in manifest["entries"] if e["context"] == "any"}
    for symbol in symbols:
        entry = api.get(symbol)
        assert entry is None or entry["status"] != "supported" or entry["tier_evidence"], symbol


def test_compositor_entries_state_evidence_or_owner(manifest: dict[str, Any]) -> None:
    """2.8: a supported compositor entry names current-envelope goldens and `since`; a release
    gap names an owner task that exists in the rulebook (open or archived)."""
    archived = {p.name.split("-", 3)[-1] for p in (RULEBOOK / "archive").iterdir()}
    open_tasks = {p.name for p in (RULEBOOK / "tasks").iterdir() if p.is_dir()}
    owner = re.compile(r"\bphase[0-9]+\.[0-9]+_[a-z0-9-]+\b")
    for entry in compositor_entries(manifest):
        assert entry["notes"], entry["symbol"]
        if entry["status"] == "supported":
            assert entry["tier_evidence"] and entry["since"], entry["symbol"]
            continue
        assert entry["status"] == "release-gap", entry["symbol"]
        tasks = owner.findall(entry["notes"])
        assert tasks, entry["symbol"]
        assert all(t in open_tasks or t in archived for t in tasks), (entry["symbol"], tasks)


def test_tier_evidence_resolves_through_the_current_envelope(tmp_path: Path) -> None:
    """Decision 037: goldens recorded only under the current envelope are valid evidence."""
    golden = "tier0/semantics/group-coverage-order"
    assert not (
        REPO_ROOT / "parity" / "manifests" / "tier0" / "semantics" / "group-coverage-order.json"
    ).exists()
    inventory = load(INVENTORY_PATH)
    entry = inventory_entry(inventory, "substance_painter.layerstack.Node.set_opacity")
    entry.update(status="supported", since="0.1.0", tier_evidence=[golden])
    result = generate(inventory_path=write(tmp_path / "inventory.json", inventory))
    assert any(e["tier_evidence"] == [golden] for e in result["entries"])


def test_compositor_gap_without_owner_fails(tmp_path: Path) -> None:
    compositor = load(COMPOSITOR_PATH)
    gap = next(e for e in compositor["entries"] if e["status"] == "release-gap")
    gap["notes"] = "Outside the Phase 1 subset."
    with pytest.raises(GenerationError, match="owner task"):
        generate(compositor_path=write(tmp_path / "compositor.json", compositor))


def test_compositor_entry_outside_its_context_fails(tmp_path: Path) -> None:
    compositor = load(COMPOSITOR_PATH)
    compositor["entries"][0]["context"] = "mask-stack"
    with pytest.raises(GenerationError, match="compositor:<case>"):
        generate(compositor_path=write(tmp_path / "compositor.json", compositor))
