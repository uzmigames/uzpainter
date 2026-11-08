"""The cutover adapter checks without UzPainter (task phase3.1_assets3d-cutover items 2.6, 2.7,
3.4, 3.5 on synthetic fixtures; `MIGRATIONS.md` M13, M14): the amended-scope refusal of a
production round, which names Painter as the tool for what it refuses, and the manifest blocks of
an export (Assets3D v2 `export`, the renamed `exportacao`, and the `painter_recipe`-equivalent
recipe file). Synthetic only: nothing here runs a pilot or certifies an Assets3D piece. Every lane.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from adapters.assets3d import client, layer_stack, manifest_blocks, scope

REPO_ROOT = Path(__file__).resolve().parents[3]
RECEIPT_SCHEMA = REPO_ROOT / "src" / "export" / "schema" / "receipt.schema.json"

STATUSES = {
    "substance_painter": "supported",
    "substance_painter.project": "supported",
    "substance_painter.project.create": "supported",
    "substance_painter.project.save": "supported",
    "substance_painter.layerstack": "supported",
    "substance_painter.layerstack.insert_fill": "supported",
    "substance_painter.layerstack.InsertPosition": "supported",
    "substance_painter.layerstack.InsertPosition.from_textureset_stack": "supported",
    "substance_painter.layerstack.insert_smart_mask": "release-gap",
    "substance_painter.textureset": "supported",
    "substance_painter.textureset.ChannelType": "supported",
    "substance_painter.textureset.get_active_stack": "supported",
    "substance_painter.resource": "supported",
    "substance_painter.resource.search": "release-gap",
    "substance_painter.ui": "supported",
    "substance_painter.ui.show_main_window": "desktop-only-omitted",
    "uzpainter": "supported",
    "uzpainter.project": "supported",
    "uzpainter.project.revision": "supported",
    "uzpainter.project.dump_recipe": "pending-evidence",
    "uzpainter.render": "pending-evidence",
    "uzpainter.render.capture": "pending-evidence",
}


def shipped(folder: Path, statuses: dict[str, str] = STATUSES) -> Path:
    """A fake `UzPainter.exe` with a capability manifest beside it; the path of the executable."""
    folder.mkdir(parents=True, exist_ok=True)
    entries = [
        {"symbol": symbol, "context": "any", "status": status}
        for symbol, status in statuses.items()
    ]
    entries.append(
        {"symbol": "uzpainter.render.capture", "context": "mode:painter_iray", "status": "x"}
    )
    manifest = {"schema": "uzpainter/capabilities/1", "entries": entries}
    (folder / scope.MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")
    exe = folder / "UzPainter.exe"
    exe.write_bytes(b"")
    return exe


# ── Amended scope (2.6, 3.4) ─────────────────────────────────────────────────────────────────────


def test_references_resolve_through_every_import_form() -> None:
    code = """
import json
import substance_painter.layerstack as ls, substance_painter.textureset as ts
import substance_painter
from substance_painter.project import create as make
from uzpainter import project
stack = ts.get_active_stack()
ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))
substance_painter.project.save()
CT = ts.ChannelType.__members__
make("mesh.obj"); project.revision(); json.dumps({})
node = ls.insert_fill(None); node.set_name("method calls are not read statically")
"""
    assert scope.referenced(code) == [
        "substance_painter",
        "substance_painter.layerstack",
        "substance_painter.layerstack.InsertPosition.from_textureset_stack",
        "substance_painter.layerstack.insert_fill",
        "substance_painter.project.create",
        "substance_painter.project.save",
        "substance_painter.textureset",
        "substance_painter.textureset.ChannelType.__members__",
        "substance_painter.textureset.get_active_stack",
        "uzpainter.project",
        "uzpainter.project.revision",
    ]
    assert scope.outside(code, STATUSES) == []


@pytest.mark.parametrize(
    ("code", "symbol", "status"),
    [
        (
            "import substance_painter.layerstack as ls\nls.insert_smart_mask(None, None)\n",
            "substance_painter.layerstack.insert_smart_mask",
            "release-gap",
        ),
        (
            "from substance_painter.resource import search\n",
            "substance_painter.resource.search",
            "release-gap",
        ),
        (
            "import uzpainter\nresult = uzpainter.project.dump_recipe()\n",
            "uzpainter.project.dump_recipe",
            "pending-evidence",
        ),
        (
            "import substance_painter.ui as ui\nui.show_main_window()\n",
            "substance_painter.ui.show_main_window",
            "desktop-only-omitted",
        ),
        (
            "import uzpainter\nuzpainter._assets3d_production_status()\n",
            "uzpainter._assets3d_production_status",
            "absent",
        ),
        (
            "import substance_painter.textureset as ts\nts.ChannelType.Unlisted\n",
            "substance_painter.textureset.ChannelType.Unlisted",
            "absent",
        ),
        (
            "from substance_painter.layerstack import *\n",
            "substance_painter.layerstack.*",
            "absent",
        ),
        (
            "import _substance_painter.display as display\ndisplay.save_viewport('p', 1, 1, 0)\n",
            "uzpainter.render.capture",
            "pending-evidence",
        ),
    ],
)
def test_anything_but_supported_is_outside_the_amended_scope(
    code: str, symbol: str, status: str
) -> None:
    assert scope.outside(code, STATUSES) == [{"symbol": symbol, "context": "any", "status": status}]


def test_a_branch_never_taken_is_refused_all_the_same() -> None:
    """Nothing of a refused round runs, so the reading cannot depend on the data: the pipeline's
    sync code names `Resource.retrieve` only for masks with a cached url, and is still refused."""
    code = "import substance_painter.resource as rs\nif False:\n    rs.search('x')\n"
    assert scope.outside(code, STATUSES)[0]["symbol"] == "substance_painter.resource.search"


def test_a_release_gap_refusal_names_painter_as_the_tool(tmp_path: Path) -> None:
    """Item 3.4: an operation on a `release-gap` capability is refused with the structured
    out-of-scope error, which names Painter as the tool for it and the manifest it read."""
    exe = shipped(tmp_path)
    code = "import substance_painter.layerstack as ls\nls.insert_smart_mask(None, None)\n"
    with pytest.raises(scope.OutOfAmendedScope) as refused:
        scope.check_code(code, exe, "smart")
    error = refused.value.error
    assert error["type"] == "OutOfAmendedScope" and error["schema"] == scope.SCHEMA
    assert error["tool"] == scope.PAINTER == "Adobe Substance 3D Painter"
    assert error["operation"] == "smart"
    assert error["outside"] == [
        {
            "symbol": "substance_painter.layerstack.insert_smart_mask",
            "context": "any",
            "status": "release-gap",
        }
    ]
    raw = (tmp_path / scope.MANIFEST_FILE).read_bytes()
    assert error["capabilities_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (
        "Adobe Substance 3D Painter" in error["message"] and "before anything" in error["message"]
    )
    assert scope.check_code("import uzpainter\nuzpainter.project.revision()\n", exe) == (
        hashlib.sha256(raw).hexdigest()
    )


@pytest.mark.parametrize("manifest", [None, "not json", {"schema": "other"}])
def test_without_a_readable_manifest_nothing_is_in_scope(tmp_path: Path, manifest: Any) -> None:
    exe = tmp_path / "UzPainter.exe"
    exe.write_bytes(b"")
    if manifest is not None:
        text = manifest if isinstance(manifest, str) else json.dumps(manifest)
        (tmp_path / scope.MANIFEST_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(scope.OutOfAmendedScope) as refused:
        scope.check_code("result = 1\n", exe)
    assert refused.value.error["capabilities_sha256"] is None
    assert refused.value.error["tool"] == scope.PAINTER


def test_unparsable_code_is_refused(tmp_path: Path) -> None:
    with pytest.raises(scope.OutOfAmendedScope) as refused:
        scope.check_code("def (\n", shipped(tmp_path))
    assert refused.value.error["outside"][0]["status"] == "absent"


def production_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> Path:
    """The client in a production call whose prerequisites and host probe already passed (their
    own tests: `test_gate_contract.py`): only the scope check is left before the launch."""
    exe = shipped(tmp_path / "bin")
    session = tmp_path / "session.json"
    monkeypatch.setattr(client, "execution_policy", lambda: {"request_sha256": "r"})
    monkeypatch.setattr(client, "require_production_runtime", lambda painter: None)
    monkeypatch.setattr(client, "painter_exe", lambda: exe)
    monkeypatch.setattr(client, "run_painter", lambda argv: calls.append(argv))
    monkeypatch.setenv(client.SESSION_ENV, str(session))
    monkeypatch.setenv(client.SCRATCH_ENV, str(tmp_path))
    monkeypatch.delenv(client.DIAGNOSTIC_ENV, raising=False)
    return session


def test_a_production_call_out_of_scope_never_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused before the session lock, the transport files or `UzPainter.exe run`: the project
    and the session cannot change."""
    calls: list[list[str]] = []
    session = production_client(tmp_path, monkeypatch, calls)
    code = "import substance_painter.resource as rs\nrs.search('Dirt')\n"
    with pytest.raises(scope.OutOfAmendedScope):
        client.execute_python(code)
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"code": code}), encoding="utf-8")
    assert client.main(["client.py", "execute_python", str(args)]) == client.FAILED
    reply = json.loads(capsys.readouterr().out)
    assert reply["success"] is False and reply["data"] is None
    assert reply["error"]["type"] == "OutOfAmendedScope"
    assert reply["error"]["tool"] == scope.PAINTER
    assert calls == []
    assert not session.exists() and not session.with_name(session.name + ".lock").exists()
    assert not list(tmp_path.glob("uzp-a3d-*"))


def test_a_diagnostic_import_is_not_scope_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The amended scope governs production rounds; a diagnostic import stays possible, flagged
    (QG-02), and meets the facade's own refusals where it reaches them."""
    monkeypatch.setattr(client, "execution_policy", lambda: None)
    monkeypatch.setattr(client, "painter_exe", lambda: tmp_path / "UzPainter.exe")
    monkeypatch.delenv(client.DIAGNOSTIC_ENV, raising=False)
    monkeypatch.setattr(
        scope, "check_code", lambda *a: pytest.fail("a diagnostic import is not scope-checked")
    )

    class Launched(Exception):
        pass

    def session_lock(session: Path) -> Any:
        raise Launched

    monkeypatch.setattr(client, "session_lock", session_lock)
    with pytest.raises(Launched):
        client.execute_python("import substance_painter.resource as rs\nrs.search('x')\n")


def test_smart_in_a_production_round_is_outside_the_amended_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client, "painter_exe", lambda: shipped(tmp_path))
    with pytest.raises(scope.OutOfAmendedScope) as refused:
        layer_stack.check_gate(["smart", "--config", "c.json"], production=True)
    error = refused.value.error
    assert error["tool"] == scope.PAINTER and "smart presets" in error["operation"]
    assert [m["symbol"] for m in error["outside"]] == [
        "substance_painter.layerstack.insert_smart_mask",
        "substance_painter.resource.search",
    ]
    layer_stack.check_gate(["sync", "--stack", "s"], production=True)  # the client checks it


def test_the_entry_prints_the_scope_refusal_before_the_script_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "painter_layer_stack.py"
    script.write_text("raise AssertionError('the script must not load')\n", encoding="utf-8")
    exe = shipped(tmp_path / "bin")
    monkeypatch.setattr(client, "painter_exe", lambda: exe)
    monkeypatch.setattr(client, "execution_policy", lambda: {"request_sha256": "r"})
    monkeypatch.setattr(client, "require_production_runtime", lambda painter: None)
    status = layer_stack.main(
        ["--production-round", str(tmp_path / "r.json"), str(script), "smart"]
    )
    assert status == client.FAILED
    reply = json.loads(capsys.readouterr().out)
    assert reply["error"]["type"] == "OutOfAmendedScope"
    assert reply["error"]["tool"] == scope.PAINTER


# ── Manifest blocks (2.7, 3.5) ───────────────────────────────────────────────────────────────────


RECIPE = {
    "schema": "uzpainter/recipe/1",
    "revision": 7,
    "evaluator_profile": "evaluator-profile-1",
    "compat_profile": "painter-12.1-api-0.3.7",
    "app_version": "0.1.0",
    "resource_hashes": ["a" * 64],
    "recipe": {"texture_sets": [], "settings": {"template": "pbr-metal-rough"}},
    "rebuild": {},
    "digest": "b" * 64,
}


def conformant_export(root: Path, generation: str = "000003") -> dict[str, Any]:
    """A rebased export entry as the runner reports it, with its receipt on disk."""
    directory = root / "Piece" / "Export" / "generations" / generation
    directory.mkdir(parents=True)
    receipt = {
        "revision": 7,
        "evaluator_profile": "evaluator-profile-1",
        "compat_profile": "painter-12.1-api-0.3.7",
        "app_version": "0.1.0",
    }
    (directory / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    sha = {"algorithm": "sha256", "value": "c" * 64, "verification": "verified"}
    return {
        "generation": generation,
        "directory": str(directory),
        "receipt": str(directory / "receipt.json"),
        "revision": 7,
        "project_path": str(root / "Piece" / "piece.uzp"),
        "manifest": {
            "manifest_files": {
                "export-plan": {
                    "path": f"Piece/Export/generations/{generation}/plan.json",
                    "role": "configuration",
                    "sha256": sha,
                    "bytes": 10,
                },
                "project": {
                    "path": "Piece/piece.uzp",
                    "role": "painter-project",
                    "sha256": {
                        "algorithm": "sha256",
                        "value": None,
                        "verification": "not-verified",
                    },
                    "bytes": None,
                    "revision": "7",
                },
                "piece_basecolor-png": {
                    "path": f"Piece/Export/generations/{generation}/files/piece_BaseColor.png",
                    "role": "map",
                    "sha256": sha,
                    "bytes": 20,
                },
            },
            "manifest_export": {
                "sources": ["project"],
                "outputs": ["piece_basecolor-png"],
                "moment": "2026-11-08T12:00:00Z",
                "preset": {"file": "export-plan", "selector": "/files/0/preset"},
                "maps": {
                    "piece_basecolor-png": {
                        "resolution": [512, 512],
                        "bit_depth": 8,
                        "color_space": "sRGB",
                    }
                },
                "comparison": {
                    "result": "pending",
                    "report": None,
                    "tolerance": None,
                    "differences": [],
                },
                "evidence": [{"file": "export-plan"}],
                "open_items": [],
            },
        },
        "manifest_unavailable": None,
    }


def validator(definition: str) -> jsonschema.Draft202012Validator:
    """The pinned copy of an Assets3D v2 definition (the receipt schema's `$defs`, decision 097)."""
    defs = json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8"))["$defs"]
    return jsonschema.Draft202012Validator({"$defs": defs, "$ref": f"#/$defs/{definition}"})


def test_an_export_gets_both_blocks_valid_under_the_assets3d_schema(tmp_path: Path) -> None:
    """Item 3.5 on a synthetic export: the `export` block (v2's `exportacao`) and every file it
    names validate under the pinned Assets3D definitions, and the recipe file it cites holds the
    dump of the exported revision with its verified hash."""
    export = conformant_export(tmp_path)
    asked: list[tuple[str, int]] = []

    def inspect(project: str, revision: int) -> dict[str, Any]:
        asked.append((project, revision))
        return dict(RECIPE)

    manifest_blocks.add_recipes([export], inspect, str(tmp_path))
    assert asked == [(str(tmp_path / "Piece" / "piece.uzp"), 7)]
    manifest = export["manifest"]
    assert manifest is not None, export["manifest_unavailable"]
    block, files = manifest["manifest_export"], manifest["manifest_files"]
    validator("export").validate(block)
    for entry in files.values():
        validator("file").validate(entry)
    keys = set(block["sources"]) | set(block["outputs"]) | set(block["maps"])
    keys |= {source["file"] for source in block["evidence"]}
    assert keys <= set(files)
    assert block["evidence"] == [{"file": "export-plan"}, {"file": "painter-recipe"}]
    entry = files["painter-recipe"]
    assert entry["path"] == "Piece/Export/uzpainter-recipes/000003.recipe.json"
    assert entry["role"] == "recipe" and entry["revision"] == "7"
    data = (tmp_path / entry["path"]).read_bytes()
    assert entry["sha256"]["value"] == hashlib.sha256(data).hexdigest()
    assert entry["sha256"]["verification"] == "verified" and entry["bytes"] == len(data)
    assert json.loads(data) == RECIPE
    assert manifest["painter_recipe"] == {
        "schema": "uzpainter/recipe/1",
        "file": "painter-recipe",
        "path": str(tmp_path / entry["path"]),
        "digest": "b" * 64,
        "revision": 7,
        "evaluator_profile": "evaluator-profile-1",
        "compat_profile": "painter-12.1-api-0.3.7",
        "app_version": "0.1.0",
    }
    again = conformant_export(tmp_path / "again")
    (tmp_path / "again" / entry["path"]).parent.mkdir(parents=True)
    (tmp_path / "again" / entry["path"]).write_bytes(data)  # the same bytes: kept, not refused
    manifest_blocks.add_recipes([again], inspect, str(tmp_path / "again"))
    assert again["manifest"] is not None, again["manifest_unavailable"]


def failing(reason: str) -> Any:
    def inspect(project: str, revision: int) -> Any:
        raise manifest_blocks.BlockError(reason)

    return inspect


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("inspect fails", "UzPainter.exe inspect exited 1"),
        ("other revision", "revision 6"),
        ("other evaluator", "evaluator_profile"),
        ("not a dump", "uzpainter/recipe/1"),
        ("no digest", "digest"),
        ("no project", "no project file"),
        ("other bytes", "never replaced"),
        ("outside the root", "outside the Assets3D root"),
    ],
)
def test_an_export_without_a_checked_recipe_gets_no_manifest(
    tmp_path: Path, change: str, reason: str
) -> None:
    """Nothing partial reaches a manifest: the export stands, its manifest is null with the reason,
    and no recipe file other than one already there is written."""
    root = tmp_path / "root"
    export = conformant_export(root)
    dump = dict(RECIPE)
    inspect: Any = lambda project, revision: dict(dump)  # noqa: E731
    base = str(root)
    if change == "inspect fails":
        inspect = failing("UzPainter.exe inspect exited 1: no such revision")
    elif change == "other revision":
        dump["revision"] = 6
    elif change == "other evaluator":
        dump["evaluator_profile"] = "another"
    elif change == "not a dump":
        dump["schema"] = "uzpainter/inspect/1"
    elif change == "no digest":
        dump["digest"] = None
    elif change == "no project":
        export["project_path"] = None
    elif change == "other bytes":
        target = manifest_blocks.recipe_file(export)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"{}\n")
    elif change == "outside the root":
        base = str(tmp_path / "elsewhere")
    manifest_blocks.add_recipes([export], inspect, base)
    assert export["manifest"] is None
    assert reason in export["manifest_unavailable"]
    written = manifest_blocks.recipe_file(export)
    assert not written.exists() or written.read_bytes() == b"{}\n"


def test_an_export_without_a_manifest_is_left_as_it_is(tmp_path: Path) -> None:
    """A diagnostic measure export or an unrebased one has no manifest: no recipe is read."""
    export = conformant_export(tmp_path)
    export["manifest"], export["manifest_unavailable"] = None, "not conformant"
    manifest_blocks.add_recipes([export], failing("never asked"), str(tmp_path))
    assert export["manifest_unavailable"] == "not conformant"
    assert not manifest_blocks.recipe_file(export).parent.exists()


def test_the_client_reads_the_recipe_of_the_exported_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    calls: list[list[str]] = []

    def run(argv: list[str]) -> Any:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps(RECIPE), stderr="")

    monkeypatch.setattr(client, "run_painter", run)
    exe = tmp_path / "UzPainter.exe"
    assert client.inspect_recipe(exe, "C:/p/piece.uzp", 7) == RECIPE
    assert calls == [[str(exe), "inspect", "C:/p/piece.uzp", "--revision", "7", "--recipe"]]
    monkeypatch.setattr(
        client,
        "run_painter",
        lambda argv: SimpleNamespace(returncode=1, stdout="", stderr="ValueError: no revision 7"),
    )
    with pytest.raises(manifest_blocks.BlockError, match="no revision 7"):
        client.inspect_recipe(exe, "C:/p/piece.uzp", 7)


# ── Amendment scope derivation (2.1) ─────────────────────────────────────────────────────────────


def test_the_amended_scope_lists_supported_symbols_by_module() -> None:
    from tools.capabilities.amended_scope import derive

    manifest = {
        "schema": "uzpainter/capabilities/1",
        "compat_profile": "painter-12.1-api-0.3.7",
        "entries": [
            {"symbol": "substance_painter.export", "context": "any", "status": "supported"},
            {
                "symbol": "substance_painter.export.export_project_textures",
                "context": "any",
                "status": "supported",
            },
            {
                "symbol": "substance_painter.export.export_project_textures",
                "context": "file-format:tiff",
                "status": "release-gap",
            },
            {
                "symbol": "substance_painter.export.export_mesh",
                "context": "any",
                "status": "release-gap",
            },
            {"symbol": "uzpainter.Result", "context": "any", "status": "pending-evidence"},
        ],
        "operation_matrix": [
            {
                "tool": "export",
                "operation": "export.png",
                "status": "available",
                "gaps": [],
                "notes": None,
            },
            {
                "tool": "export",
                "operation": "export.format.tiff",
                "status": "capability gap",
                "gaps": [
                    {
                        "symbol": "substance_painter.export.export_project_textures",
                        "context": "file-format:tiff",
                        "status": "release-gap",
                    }
                ],
                "notes": "Not in v1.",
            },
        ],
    }
    raw = json.dumps(manifest).encode()
    scope_doc = derive(raw, "capabilities.json")
    assert scope_doc["manifest"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert scope_doc["modules"]["substance_painter.export"] == {
        "in_scope_count": 2,
        "outside_by_status": {"release-gap": 1},
        "in_scope": [
            "substance_painter.export",
            "substance_painter.export.export_project_textures",
        ],
    }
    assert scope_doc["modules"]["uzpainter"]["outside_by_status"] == {"pending-evidence": 1}
    assert scope_doc["operation_matrix"]["available"] == ["export: export.png"]
    assert scope_doc["operation_matrix"]["capability_gap"][0]["operation"] == "export.format.tiff"
    assert scope_doc["refused_contexts_of_in_scope_symbols"] == [
        {
            "symbol": "substance_painter.export.export_project_textures",
            "context": "file-format:tiff",
            "status": "release-gap",
        }
    ]
