"""The Assets3D adapter's host-side parts without UzPainter (task phase1.23 items 2.1-2.5, 5.2;
decision 113): the manifest rebase, the fixed-name verification, the redirects, the result
normalisation, the pins, the capability gate and the client's usage errors, and how the client
starts UzPainter without a window or an error dialog (decision 252). Every lane.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
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
    assert (
        layer_stack.main(
            ["--diagnostic-import", "--pin", f"{script}={'0' * 64}", str(script), "run", "x.py"]
        )
        == 1
    )
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
    monkeypatch.setenv(client.IMPORT_DIAGNOSTIC_ENV, "1")
    monkeypatch.delenv(client.PRODUCTION_ENV, raising=False)
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


# The child's error mode, the processes on its console and whether that console has a window.
CHILD_REPORT = (
    "import ctypes, json; k = ctypes.windll.kernel32; p = (ctypes.c_ulong * 8)(); "
    "print(json.dumps([k.GetErrorMode(), k.GetConsoleProcessList(p, 8), "
    "bool(k.GetConsoleWindow())]))"
)
IMAGE_SUBSYSTEM_WINDOWS_GUI = 2


def test_uzpainter_is_started_without_a_window_or_an_error_dialog() -> None:
    """The child inherits the no-dialog error mode, which the client then takes back, and has a
    console of its own without a window (`CREATE_NO_WINDOW`, every standard handle redirected)."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    saved = kernel32.SetErrorMode(0)
    try:
        done = client.run_painter([sys.executable, "-I", "-c", CHILD_REPORT])
        assert kernel32.GetErrorMode() == 0
    finally:
        kernel32.SetErrorMode(saved)
    assert done.returncode == 0, done.stderr
    mode, console_processes, console_window = json.loads(done.stdout)
    assert mode & client.NO_ERROR_DIALOGS == client.NO_ERROR_DIALOGS
    assert (console_processes, console_window) == (1, False)


def test_the_layer_stack_script_starts_the_client_where_windows_gives_no_console() -> None:
    """The script's own `execute()` starts the client without creation flags, so the adapter hands
    it `pythonw.exe`, a GUI-subsystem program, which Windows never gives a console."""
    if not Path(sys.executable).with_name("pythonw.exe").is_file():
        pytest.skip(f"no pythonw.exe beside {sys.executable}")
    image = client.windowless_python().read_bytes()[:4096]
    header = int.from_bytes(image[0x3C:0x40], "little")
    assert int.from_bytes(image[header + 0x5C : header + 0x5E], "little") == (
        IMAGE_SUBSYSTEM_WINDOWS_GUI
    )


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


def fake_session_modules(
    monkeypatch: pytest.MonkeyPatch, file_path: str, absolute_file_path: str, opened: list[Path]
) -> None:
    """The modules `session_left_open` and `restore_session` import, as fakes: the facade's
    `file_path()` returns the path as the script named it, the native `absolute_file_path()` the
    path resolved when it was named, and `open` resolves its argument as the filesystem does."""
    import sys
    from types import ModuleType, SimpleNamespace

    def open_project(path: str) -> None:
        resolved = Path(path).resolve()
        resolved.read_bytes()  # a missing file raises, as the native open does
        opened.append(resolved)

    stack = SimpleNamespace(
        material=lambda: SimpleNamespace(name=lambda: "Material"), name=lambda: ""
    )
    project: Any = ModuleType("substance_painter.project")
    project.is_open = lambda: True
    project.file_path = lambda: file_path
    project.needs_saving = lambda: False
    project.open = open_project
    textureset: Any = ModuleType("substance_painter.textureset")
    textureset.get_active_stack = lambda: stack
    textureset.set_active_stack = lambda value: None
    textureset.Stack = SimpleNamespace(from_name=lambda *args: stack)
    painter: Any = ModuleType("substance_painter")
    painter.project, painter.textureset = project, textureset
    state: Any = ModuleType("uzpainter_facade.state")
    state.SESSION = SimpleNamespace(projects=1)
    native: Any = ModuleType("uzpainter")
    native.project = SimpleNamespace(
        needs_saving=lambda: False, absolute_file_path=lambda: absolute_file_path
    )
    for name, module in {
        "substance_painter": painter,
        "substance_painter.project": project,
        "substance_painter.textureset": textureset,
        "uzpainter_facade.state": state,
        "uzpainter": native,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize("homonym", [False, True])
def test_a_project_saved_under_a_relative_path_is_carried_where_it_was_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, homonym: bool
) -> None:
    """Decision 118 (Codex audit): a script that changes directory and saves `A.uzp` leaves the
    project's absolute path in the session, and the next call, run in the client's directory,
    reopens that project: not a same-named file there, and not a failure when there is none."""
    work, elsewhere, client_dir = tmp_path / "work", tmp_path / "elsewhere", tmp_path / "client"
    for folder in (work, elsewhere, client_dir):
        folder.mkdir()
    intended = work / "A.uzp"
    intended.write_text("intended project", encoding="utf-8")
    if homonym:
        (client_dir / "A.uzp").write_text("different project", encoding="utf-8")
        (elsewhere / "A.uzp").write_text("different project", encoding="utf-8")
    opened: list[Path] = []
    fake_session_modules(monkeypatch, "A.uzp", str(intended), opened)
    monkeypatch.chdir(elsewhere)  # the script moved on after saving in `work`
    carried = runner.session_left_open()
    assert carried is not None and carried["project"] == str(intended)
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(carried), encoding="utf-8")
    monkeypatch.chdir(client_dir)  # each call inherits the client's directory
    assert runner.restore_session(session_file) == carried
    assert opened == [intended]


def test_a_session_naming_a_relative_path_is_emptied_before_anything_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session file that names a relative project path (written before decision 118) is not
    resolved under the client's directory, where a same-named file may be another project: the
    call fails before opening anything and the session is emptied."""
    (tmp_path / "A.uzp").write_text("different project", encoding="utf-8")
    opened: list[Path] = []
    fake_session_modules(monkeypatch, "A.uzp", "A.uzp", opened)
    monkeypatch.chdir(tmp_path)
    session_file = tmp_path / "session.json"
    carried = {"project": "A.uzp", "project_index": 1, "needs_saving": False}
    session_file.write_text(json.dumps({**carried, "active_stack": ["Material", ""]}), "utf-8")
    with pytest.raises(runner.AdapterSessionError, match="relative path; the session was emptied"):
        runner.restore_session(session_file)
    assert opened == []
    assert json.loads(session_file.read_text(encoding="utf-8")) == {}


def test_a_project_opened_from_a_bundle_is_carried_as_its_store_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 118 (Codex audit): a bundle directory opens as the `.uzp` it is imported into, and
    importing it again fails because that file exists. The session carries what the native
    `absolute_file_path()` names, the store file, so the next call reopens it instead of
    re-importing the directory."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle.json").write_text("{}", encoding="utf-8")
    store = tmp_path / "bundle.uzp"
    store.write_text("imported project", encoding="utf-8")
    opened: list[Path] = []
    fake_session_modules(monkeypatch, "bundle.uzp", str(store), opened)
    monkeypatch.chdir(tmp_path)
    carried = runner.session_left_open()
    assert carried is not None and carried["project"] == str(store)
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(carried), encoding="utf-8")
    client_dir = tmp_path / "client"
    client_dir.mkdir()
    monkeypatch.chdir(client_dir)
    assert runner.restore_session(session_file) == carried
    assert opened == [store]


def test_the_diagnostic_measure_export_is_passed_only_when_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Decision 286: `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT=1` alone passes
    `--diagnostic-measure-export` to `UzPainter.exe run` (before `--`, so it is the host's flag,
    not the script's), and the reply then carries the run's `diagnostic`; unset, nothing is
    passed; any other value is a host error before UzPainter runs."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str]) -> Any:
        calls.append(argv)
        host: dict[str, Any] = {"status": "ok", "result": None, "stdout": "", "stderr": ""}
        if client.DIAGNOSTIC_FLAG in argv:
            host["diagnostic"] = "diagnostic-measure"
        return type("Done", (), {"returncode": 0, "stdout": client.JSON_PREFIX + json.dumps(host)})

    monkeypatch.setattr(client, "run_painter", fake_run)
    monkeypatch.setattr(client, "painter_exe", lambda: tmp_path / "UzPainter.exe")
    monkeypatch.setenv(client.SESSION_ENV, str(tmp_path / "session.json"))
    monkeypatch.setenv(client.SCRATCH_ENV, str(tmp_path))
    monkeypatch.setenv(client.IMPORT_DIAGNOSTIC_ENV, "1")
    monkeypatch.delenv(client.PRODUCTION_ENV, raising=False)
    monkeypatch.delenv(client.DIAGNOSTIC_ENV, raising=False)
    reply, status = client.execute_python("result = None")
    assert status == client.OK and reply["diagnostic"] == "diagnostic-import"
    assert client.DIAGNOSTIC_FLAG not in calls[-1]
    monkeypatch.setenv(client.DIAGNOSTIC_ENV, "1")
    reply, status = client.execute_python("result = None")
    assert status == client.OK and reply["diagnostic"] == "diagnostic-measure"
    assert calls[-1].index(client.DIAGNOSTIC_FLAG) < calls[-1].index("--")
    monkeypatch.setenv(client.DIAGNOSTIC_ENV, "yes")
    with pytest.raises(client.HostError, match="must be 1 or unset"):
        client.execute_python("result = None")
    assert len(calls) == 2


def test_a_non_conformant_export_gets_no_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 286: an export whose receipt says `non_conformant` (the diagnostic measure export)
    is reported without a manifest, so nothing of it reaches an Assets3D manifest, although its
    paths lie under the root."""
    from types import SimpleNamespace

    root = tmp_path / "assets"
    generation = root / "exports" / "generations" / "000001"
    generation.mkdir(parents=True)
    receipt = {
        "manifest_export": {"sources": ["project"], "outputs": []},
        "manifest_files": {"project": {"path": "A.spp", "sha256": "hash-of-A"}},
        "non_conformant": {"mode": "diagnostic-measure", "decision": "286", "bypassed": []},
    }
    (generation / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    publication = {
        "fixed_names": [],
        "receipt": str(generation / "receipt.json"),
        "directory": str(generation),
        "generation": "000001",
        "receipt_sha256": "receipt-hash",
        "plan_hash": "plan-hash",
        "revision": 1,
        "project_path": str(root / "A.spp"),
        "mesh_path": None,
    }
    job = SimpleNamespace(kind="export", status="succeeded", wait=lambda: publication)
    host = SimpleNamespace(jobs=SimpleNamespace(list=lambda: [job]))
    monkeypatch.setenv(runner.ROOT_ENV, str(root))
    (result,) = runner.exports_of_run(host)
    assert result["manifest"] is None
    assert result["manifest_unavailable"] == runner.NON_CONFORMANT
