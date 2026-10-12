"""The Assets3D adapter's host-side parts without UzPainter (task phase1.23 items 2.1-2.5, 5.2;
decision 113): the manifest rebase, the fixed-name verification, the redirects, the result
normalisation, the pins, the capability gate and the client's usage errors. Every lane.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d import client, layer_stack, runner


def receipt_of(files: dict[str, bytes], generation: str = "000002") -> dict[str, Any]:
    return {
        "generation": generation,
        "files": [
            {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ],
        "manifest_files": {
            "export-plan": {"path": "plan.json", "role": "configuration"},
            "project": {"path": "wand.spp", "role": "painter-project"},
            "mesh": {"path": "wand_low.obj", "role": "source"},
            "wand-png": {"path": "files/sub/wand.png", "role": "map"},
        },
        "manifest_export": {"sources": ["project", "mesh"], "outputs": ["wand-png"]},
    }


def fixed_copy(
    folder: Path, files: dict[str, bytes], journal: dict[str, Any] | None = None
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    entry = {
        "generation": "000002",
        "files": sorted(files),
        "copied": sorted(files),
        "obsolete": [],
    }
    (folder / runner.JOURNAL).write_text(json.dumps({**entry, **(journal or {})}), encoding="utf-8")


def test_under_root_names_paths_inside_the_root_only(tmp_path: Path) -> None:
    root = tmp_path / "Assets3D"
    assert runner.under_root(str(root / "a" / "b c.png"), str(root)) == "a/b c.png"
    assert runner.under_root(str(root / "a" / ".." / "b.png"), str(root)) == "b.png"
    if os.name == "nt":  # Windows paths compare without case
        assert runner.under_root(str(root).upper() + "\\x.png", str(root)) == "x.png"
    assert runner.under_root(str(root), str(root)) is None
    assert runner.under_root(str(tmp_path / "Assets3D-other" / "x.png"), str(root)) is None
    assert runner.under_root(str(tmp_path / "x.png"), str(root)) is None


def test_the_manifest_is_rebased_under_the_root(tmp_path: Path) -> None:
    """Generation-relative paths take the generation's folder; project and mesh their own."""
    root = tmp_path / "A3D"
    generation = root / "out" / "generations" / "000002"
    manifest, reason = runner.rebase_manifest(
        receipt_of({"wand.png": b"x"}),
        str(generation),
        str(root / "Models" / "wand.spp"),
        str(root / "_tmp" / "wand_low.obj"),
        str(root),
    )
    assert reason is None and manifest is not None
    assert {k: v["path"] for k, v in manifest["manifest_files"].items()} == {
        "export-plan": "out/generations/000002/plan.json",
        "project": "Models/wand.spp",
        "mesh": "_tmp/wand_low.obj",
        "wand-png": "out/generations/000002/files/sub/wand.png",
    }
    assert manifest["manifest_files"]["wand-png"]["role"] == "map"
    assert manifest["manifest_export"]["outputs"] == ["wand-png"]


@pytest.mark.parametrize(
    ("project", "mesh", "root", "reason"),
    [
        ("inside", "outside", "root", "`mesh`"),
        ("inside", None, "root", "`mesh` has no path"),
        ("inside", "inside", None, "UZP_ASSETS3D_ROOT"),
    ],
)
def test_a_manifest_that_cannot_be_rebased_is_null_with_its_reason(
    tmp_path: Path, project: str, mesh: str | None, root: str | None, reason: str
) -> None:
    base = tmp_path / "A3D"
    paths = {"inside": str(base / "x"), "outside": str(tmp_path / "y")}
    manifest, why = runner.rebase_manifest(
        receipt_of({"wand.png": b"x"}),
        str(base / "g"),
        paths[project],
        None if mesh is None else paths[mesh],
        None if root is None else str(base),
    )
    assert manifest is None and why is not None and reason in why


def test_an_export_without_files_has_no_manifest(tmp_path: Path) -> None:
    receipt = {**receipt_of({}), "manifest_export": None}
    assert runner.rebase_manifest(receipt, str(tmp_path), None, None, str(tmp_path))[0] is None


def test_a_complete_fixed_name_copy_verifies(tmp_path: Path) -> None:
    files = {"wand.png": b"png", "sub/wand_n.png": b"normal"}
    fixed_copy(tmp_path, files)
    assert runner.verify_fixed_names(str(tmp_path), "000002", receipt_of(files)) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"generation": "000001"}, "names generation 000001"),
        ({"copied": ["wand.png"]}, "incomplete"),
        ({"obsolete": ["old.png"]}, "obsolete"),
        ({"files": ["wand.png"]}, "other files"),
    ],
)
def test_an_inconsistent_journal_fails(
    tmp_path: Path, change: dict[str, Any], problem: str
) -> None:
    files = {"wand.png": b"png", "sub/wand_n.png": b"normal"}
    fixed_copy(tmp_path, files, change)
    found = runner.verify_fixed_names(str(tmp_path), "000002", receipt_of(files))
    assert any(problem in p for p in found), found


def test_a_changed_or_missing_fixed_name_fails(tmp_path: Path) -> None:
    files = {"wand.png": b"png", "sub/wand_n.png": b"normal"}
    fixed_copy(tmp_path, files)
    (tmp_path / "wand.png").write_bytes(b"PNG")
    (tmp_path / "sub" / "wand_n.png").unlink()
    found = runner.verify_fixed_names(str(tmp_path), "000002", receipt_of(files))
    assert len(found) == 2 and "differs" in found[0] and "missing" in found[1]
    (tmp_path / runner.JOURNAL).unlink()
    assert "fixed-names.journal.json" in runner.verify_fixed_names(str(tmp_path), "000002", {})[0]


def test_redirects_map_exactly_their_paths(tmp_path: Path) -> None:
    hard, copy, other = tmp_path / "args.json", tmp_path / "copy.json", tmp_path / "other.json"
    copy.write_text("copy", encoding="utf-8")
    other.write_text("other", encoding="utf-8")
    opened = runner.redirected_open({str(hard).upper(): str(copy)})
    with opened(str(hard), encoding="utf-8") as file:
        assert file.read() == "copy"
    with opened(other, encoding="utf-8") as file:
        assert file.read() == "other"


def test_results_are_normalised_as_the_bridge_does() -> None:
    assert runner.normalised({"p": Path("a"), "t": (1, 2), "s": {3}}) == {
        "p": str(Path("a")),
        "t": [1, 2],
        "s": "{3}",
    }
    assert runner.normalised(None) is None


def test_session_files_are_replaced_atomically(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "session.json"
    runner.write_atomically(target, "{}")
    runner.write_atomically(target, '{"project": "x"}')
    assert target.read_text(encoding="utf-8") == '{"project": "x"}'
    assert sorted(p.name for p in target.parent.iterdir()) == ["session.json"]


def test_pins_refuse_changed_bytes(tmp_path: Path) -> None:
    script = tmp_path / "painter_layer_stack.py"
    script.write_bytes(b"def main(): pass\n")
    good = hashlib.sha256(b"def main(): pass\n").hexdigest()
    layer_stack.check_pins({script.resolve(): good}, script.resolve(), script.read_bytes())
    with pytest.raises(layer_stack.Refused) as refused:
        layer_stack.check_pins({script.resolve(): "0" * 64}, script.resolve(), script.read_bytes())
    assert refused.value.reply["error"]["type"] == "PinMismatch"


def test_the_entry_refuses_before_running_a_changed_script(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "painter_layer_stack.py"
    script.write_text("raise SystemExit('must not run')\n", encoding="utf-8")
    assert layer_stack.main(["--pin", f"{script}={'0' * 64}", str(script), "run", "x.py"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "PinMismatch"


def gate_statuses(status: str) -> dict[tuple[str, str], str]:
    return {
        ("substance_painter.layerstack.insert_smart_mask", "any"): status,
        ("substance_painter.resource.search", "any"): "supported",
    }


@pytest.mark.parametrize("status", ["release-gap", "pending-evidence", "absent"])
def test_smart_is_gated_until_its_capabilities_are_supported(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    monkeypatch.setattr(layer_stack, "capability_statuses", lambda: gate_statuses(status))
    with pytest.raises(layer_stack.Refused) as refused:
        layer_stack.check_gate(["smart", "--config", "c.json"])
    error = refused.value.reply["error"]
    assert error["type"] == "NotYetSupported" and error["capability"] == "smart presets"
    assert error["missing"] == [
        {
            "symbol": "substance_painter.layerstack.insert_smart_mask",
            "context": "any",
            "status": status,
        }
    ]


def test_the_gate_opens_once_supported_and_never_gates_other_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(layer_stack, "capability_statuses", lambda: gate_statuses("supported"))
    layer_stack.check_gate(["smart", "--config", "c.json"])

    def unread() -> dict[tuple[str, str], str]:
        raise AssertionError("only gated commands read the manifest")

    monkeypatch.setattr(layer_stack, "capability_statuses", unread)
    for command in (["sync", "--stack", "s"], ["capture", "--out", "o"], ["run", "f.py"]):
        layer_stack.check_gate(command)


def test_the_client_serves_execute_python_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"code": "result = 1"}), encoding="utf-8")
    assert client.main(["client.py", "create_project", str(args)]) == client.USAGE
    args.write_text(json.dumps({"source": "result = 1"}), encoding="utf-8")
    assert client.main(["client.py", "execute_python", str(args)]) == client.USAGE
    capsys.readouterr()


def test_a_missing_uzpainter_is_a_host_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(client.PAINTER_ENV, str(tmp_path / "absent" / "UzPainter.exe"))
    monkeypatch.setenv("SP_MCP_CLIENT_OUTPUT_DIR", str(tmp_path / "out"))
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"code": "result = 1"}), encoding="utf-8")
    assert client.main(["client.py", "execute_python", str(args)]) == client.HOST_ERROR
    reply = json.loads(capsys.readouterr().out)
    assert reply["success"] is False and reply["error"]["type"] == "HostError"
    saved = json.loads(
        (tmp_path / "out" / "painter-last-response.json").read_text(encoding="utf-8")
    )
    assert saved == reply


def test_one_call_at_a_time_holds_the_session(tmp_path: Path) -> None:
    session = tmp_path / "s" / "session.json"
    with client.session_lock(session):
        assert (tmp_path / "s" / "session.json.lock").is_file()
    with client.session_lock(session):  # released
        pass


@pytest.mark.parametrize("final_project", ["original", "different", "closed"])
def test_an_export_keeps_the_sources_it_was_started_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_project: str
) -> None:
    """Each export's manifest names the project and mesh the export was started from (the
    publication's `project_path` and `mesh_path`), whatever project is open when the run ends:
    the same one, another one, or none."""
    from types import SimpleNamespace

    root = tmp_path / "assets"
    generation = root / "exports" / "generations" / "000001"
    generation.mkdir(parents=True)
    receipt = {
        "manifest_export": {"sources": ["project", "mesh"], "outputs": []},
        "manifest_files": {
            "project": {"path": "A.spp", "sha256": "hash-of-A"},
            "mesh": {"path": "A.obj", "sha256": "hash-of-A-mesh"},
        },
    }
    receipt_file = generation / "receipt.json"
    receipt_file.write_text(json.dumps(receipt), encoding="utf-8")
    publication = {
        "fixed_names": [],
        "receipt": str(receipt_file),
        "directory": str(generation),
        "generation": "000001",
        "receipt_sha256": "receipt-hash",
        "plan_hash": "plan-hash",
        "revision": 1,
        "project_path": str(root / "A.spp"),
        "mesh_path": str(root / "A.obj"),
    }
    current = "B" if final_project == "different" else "A"
    host = SimpleNamespace(
        jobs=SimpleNamespace(
            list=lambda: [
                SimpleNamespace(kind="export", status="succeeded", wait=lambda: publication)
            ]
        ),
        project=SimpleNamespace(
            is_open=lambda: final_project != "closed",
            file_path=lambda: root / f"{current}.spp",
            last_imported_mesh_path=lambda: root / f"{current}.obj",
        ),
    )
    monkeypatch.setenv(runner.ROOT_ENV, str(root))
    (result,) = runner.exports_of_run(host)
    assert result["manifest"] is not None, result["manifest_unavailable"]
    files = result["manifest"]["manifest_files"]
    assert files["project"] == {"path": "A.spp", "sha256": "hash-of-A"}
    assert files["mesh"] == {"path": "A.obj", "sha256": "hash-of-A-mesh"}
