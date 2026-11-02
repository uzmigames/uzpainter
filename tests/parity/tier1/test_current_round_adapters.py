"""The UzPainter-side rebuild of a current round (decision 300 item 7): the direct route (`Wand`
over `adapters/assets3d/layer_stack.py`) and the MCP route (`tests/parity/tier1/mcp_round.py`)
carry the sync's validated masks, typed options and pinned import closure, and a legacy job
rebuilds exactly as before. Nothing here starts UzPainter or Painter: the adapter's subprocess is
captured, the closed import loading runs in-process on stand-in scripts, and the MCP round runs
against a fake session.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from adapters.assets3d import layer_stack
from tests.adapters.assets3d import wand as wand_module
from tests.adapters.assets3d.wand import Wand
from tests.parity.recorder.test_script_run import (
    DECISION_EVIDENCE,
    RUN_PY,
    STAGE_REVIEW_EVIDENCE,
    current_manifest,
    make_assets,
    write,
)
from tests.parity.tier1 import mcp_round
from tools.parity.recorder.script_run import (
    SYNC_ARGS,
    load_script_job,
    stage_inputs,
    wand_manifest,
)
from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.store.store import STORE_ENV

OPTIONS = [
    "--resource-prefix",
    "v5f_",
    "--resource-group",
    "faixa25_v5",
    "--texture-set",
    "25-Faixa-Cintura",
]
CLOSURE_ORDER = ["decision-evidence-py", "stage-review-evidence-py", "production-run-py"]
PINNED_MARK = "decision-evidence-pinned+stage-review-pinned"


@pytest.fixture(autouse=True)
def no_private_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stand-in pins resolve under `assets`, never in a private store."""
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))


@pytest.fixture
def assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in Assets3D the Wand loads its job from."""
    root = make_assets(tmp_path / "assets3d")
    monkeypatch.setattr(wand_module, "ASSETS3D", root)
    return root


def manifest_file(tmp_path: Path, manifest: dict[str, Any], name: str) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def captured(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every command line the Wand starts, none of them run."""
    calls: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


# --- the direct route: the Wand's command lines ----------------------------------------------


def test_a_legacy_wand_keeps_its_command_lines(
    assets: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The masks list's first mask's folder, as the raw read gave it, no option and no
    `--import`: the sync and export command lines are the historical ones."""
    path = manifest_file(tmp_path, wand_manifest(assets), "legacy")
    wand = Wand(tmp_path / "UzPainter.exe", tmp_path / "work", path)
    calls = captured(monkeypatch)
    wand.sync("--dry-run")
    wand.export()
    legacy_masks = wand.staged[wand.job.sync.args["masks"][0]].parent
    head = [sys.executable, str(wand_module.ENTRY), "--diagnostic-import", *wand.pins()]
    script = str(wand.script("painter-layer-stack-py"))
    assert wand.masks == legacy_masks
    assert wand.imports() == []
    assert calls == [
        [
            *head,
            script,
            "sync",
            "--stack",
            str(wand.stack),
            "--masks",
            str(legacy_masks),
            "--state",
            str(wand.state),
            "--dry-run",
        ],
        [*head, script, "run", str(wand.script("painter-export-py"))],
    ]


def test_a_current_wand_passes_the_options_and_the_closure(
    assets: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mask folder's staged copy, the three options after `--state` in the recorder's order,
    and every call closes the script's imports to the pinned closure, dependencies first."""
    path = manifest_file(tmp_path, current_manifest(assets), "current")
    wand = Wand(tmp_path / "UzPainter.exe", tmp_path / "work", path)
    calls = captured(monkeypatch)
    wand.sync()
    wand.export()
    inputs = wand.job.inputs
    imports = [
        part
        for input_id in CLOSURE_ORDER
        for part in ("--import", f"{wand.staged[input_id]}={inputs[input_id].sha256}")
    ]
    head = [sys.executable, str(wand_module.ENTRY), "--diagnostic-import", *wand.pins(), *imports]
    script = str(wand.script("painter-layer-stack-py"))
    assert sorted(p.name for p in wand.masks.iterdir()) == sorted(
        m.name for m in wand.job.sync.masks
    )
    assert calls == [
        [
            *head,
            script,
            "sync",
            "--stack",
            str(wand.stack),
            "--masks",
            str(wand.masks),
            "--state",
            str(wand.state),
            *OPTIONS,
        ],
        [*head, script, "run", str(wand.script("painter-export-py"))],
    ]


@pytest.mark.parametrize(
    "path",
    sorted(
        p
        for p in (REPO_ROOT / "parity/envelopes").glob("*/*/phase*/tier1/*.json")
        if p.stem in ("wand-v1", "wand-v1-float", "wand-v1-normal-float")
    ),
    ids=lambda p: "/".join(p.parts[-5:]),
)
def test_historical_manifests_take_the_legacy_sync(path: Path) -> None:
    """Each historical Wand manifest's sync is the legacy shape (the masks lists, no option, no
    closure), so it rebuilds through the legacy command lines above."""
    steps = load_json(path)["instruction_sequence"]["steps"]
    syncs = [s["args"] for s in steps if "stack" in s["args"]]
    assert len(syncs) == 1 and set(syncs[0]) == SYNC_ARGS


# --- the direct route: the adapter's closed import loading -----------------------------------

SCRIPT = """'''Stand-in of painter_layer_stack.py importing run.py's closure at import time.'''
import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'AGENTS.md').exists())
CLIENT = ROOT / 'client.py'
MCP_PYTHON = Path(sys.executable)
sys.path.insert(0, str(ROOT / 'Pipeline/production'))
from run import MARK, locate  # noqa: E402


def execute(code, token=None):
    with open(ROOT / 'sent.log', 'a', encoding='utf-8') as log:
        log.write(code + chr(10))
    return {}


def main():
    __BEFORE__
    execute('probe')
    out = Path(sys.argv[-1])
    out.write_text(json.dumps({'mark': MARK, 'argv': sys.argv[1:]}), encoding='utf-8')
"""
SWALLOW = "try:\n        import unpinned_helper\n    except ImportError:\n        pass"


def adapter_tree(root: Path, before: str = "pass") -> dict[str, Path]:
    """The stand-in script and run.py's closure at their Assets3D paths under `root`."""
    write(root / "AGENTS.md", "stand-in\n")
    files = {
        "script": root / "Pipeline/painting/painter_layer_stack.py",
        "run": root / "Pipeline/production/run.py",
        "decision_evidence": root / "Pipeline/production/decision_evidence.py",
        "stage_review_evidence": root / "Pipeline/production/stage_review_evidence.py",
    }
    write(files["script"], SCRIPT.replace("__BEFORE__", before))
    write(files["run"], RUN_PY)
    write(files["decision_evidence"], DECISION_EVIDENCE)
    write(files["stage_review_evidence"], STAGE_REVIEW_EVIDENCE)
    return files


def pin(path: Path) -> str:
    return f"{path}={hashlib.sha256(path.read_bytes()).hexdigest()}"


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Decoys in `sys.modules`, a live helper first on `sys.path`, and the adapter's root set;
    what the process held before, to compare after."""
    monkeypatch.setenv(layer_stack.ROOT_ENV, str(tmp_path / "tree"))
    live = tmp_path / "live"
    write(live / "decision_evidence.py", "def build():\n    return 'LIVE'\n")
    write(live / "stage_review_evidence.py", "def collect():\n    return 'LIVE'\n")
    write(live / "unpinned_helper.py", "")
    monkeypatch.setattr(sys, "path", [str(live), *sys.path])
    decoy = types.ModuleType("run")
    monkeypatch.setitem(sys.modules, "run", decoy)
    for name in ("decision_evidence", "stage_review_evidence", "unpinned_helper"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    return {"decoy": decoy, "path": list(sys.path), "meta_path": list(sys.meta_path)}


def assert_restored(isolated: dict[str, Any]) -> None:
    assert sys.modules["run"] is isolated["decoy"]
    assert not {"decision_evidence", "stage_review_evidence", "unpinned_helper"} & set(sys.modules)
    assert sys.path == isolated["path"] and sys.meta_path == isolated["meta_path"]


def test_the_adapter_loads_the_pinned_closure_and_restores_the_process(
    tmp_path: Path, isolated: dict[str, Any]
) -> None:
    """run.py and its helpers come from their pinned bytes, never the live helper first on
    `sys.path` nor the decoy `run`; the process is as before afterwards."""
    files = adapter_tree(tmp_path / "tree")
    out = tmp_path / "out.json"
    order = ("decision_evidence", "stage_review_evidence", "run")
    imports = [part for name in order for part in ("--import", pin(files[name]))]
    assert layer_stack.run_script([*imports, str(files["script"]), "run", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "mark": PINNED_MARK,
        "argv": ["run", str(out)],
    }
    assert (tmp_path / "tree/sent.log").read_text(encoding="utf-8") == "probe\n"
    assert_restored(isolated)


@pytest.mark.parametrize(
    "order",
    [("run", "decision_evidence", "stage_review_evidence"), ("decision_evidence", "run")],
    ids=["run-before-its-helpers", "a-helper-left-out"],
)
def test_a_live_fallback_is_refused_before_the_script_runs(
    tmp_path: Path, isolated: dict[str, Any], order: tuple[str, ...]
) -> None:
    """run.py's absolute fallback finds no pinned helper loaded: the live helper on `sys.path` is
    refused, the script never runs, and the process is as before."""
    files = adapter_tree(tmp_path / "tree")
    imports = [part for name in order for part in ("--import", pin(files[name]))]
    with pytest.raises(layer_stack.Refused) as refused:
        layer_stack.run_script([*imports, str(files["script"]), "run", str(tmp_path / "o.json")])
    assert refused.value.reply["error"]["type"] == "UnpinnedImport"
    assert refused.value.reply["error"]["modules"] in (
        ["decision_evidence"],
        ["stage_review_evidence"],
    )
    assert not (tmp_path / "tree/sent.log").exists() and not (tmp_path / "o.json").exists()
    assert_restored(isolated)


def test_a_cached_helper_never_stands_in_for_a_pinned_one(
    tmp_path: Path, isolated: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Helpers already loaded under the pinned names: given in the wrong order, run.py's import
    of its helper is still refused instead of taking the cached one, and given in order, run.py
    takes the pinned ones; the cached modules are back afterwards."""
    cached = {}
    for name, function in (("decision_evidence", "build"), ("stage_review_evidence", "collect")):
        module = types.ModuleType(name)
        setattr(module, function, lambda: "CACHED")
        monkeypatch.setitem(sys.modules, name, module)
        cached[name] = module
    files = adapter_tree(tmp_path / "tree")
    out = tmp_path / "out.json"
    for order in (
        ("run", "decision_evidence", "stage_review_evidence"),
        ("decision_evidence", "stage_review_evidence", "run"),
    ):
        imports = [part for name in order for part in ("--import", pin(files[name]))]
        argv = [*imports, str(files["script"]), "run", str(out)]
        if order[0] == "run":
            with pytest.raises(layer_stack.Refused) as refused:
                layer_stack.run_script(argv)
            assert refused.value.reply["error"]["modules"] == ["decision_evidence"]
            assert not out.exists()
        else:
            assert layer_stack.run_script(argv) == 0
            assert json.loads(out.read_text(encoding="utf-8"))["mark"] == PINNED_MARK
        assert all(sys.modules[name] is module for name, module in cached.items())
        assert sys.modules["run"] is isolated["decoy"]
        assert sys.path == isolated["path"] and sys.meta_path == isolated["meta_path"]


def test_a_pinned_helper_is_its_module_while_it_executes(
    tmp_path: Path, isolated: dict[str, Any]
) -> None:
    """A dataclass under postponed annotations looks its module up in `sys.modules` when the
    class is made: the pinned helper is there while it executes."""
    files = adapter_tree(tmp_path / "tree")
    helper = DECISION_EVIDENCE.replace(
        "import hashlib\n",
        "from __future__ import annotations\n\nimport dataclasses\nimport hashlib\n\n\n"
        "@dataclasses.dataclass\nclass Evidence:\n    name: str\n",
    )
    assert helper != DECISION_EVIDENCE
    write(files["decision_evidence"], helper)
    out = tmp_path / "out.json"
    order = ("decision_evidence", "stage_review_evidence", "run")
    imports = [part for name in order for part in ("--import", pin(files[name]))]
    assert layer_stack.run_script([*imports, str(files["script"]), "run", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["mark"] == PINNED_MARK
    assert_restored(isolated)


def test_a_caught_unpinned_import_never_lets_a_painter_call_start(
    tmp_path: Path, isolated: dict[str, Any]
) -> None:
    """The script catches the refused import and goes on: its next `execute` is refused before
    the script's transport runs."""
    files = adapter_tree(tmp_path / "tree", SWALLOW)
    order = ("decision_evidence", "stage_review_evidence", "run")
    imports = [part for name in order for part in ("--import", pin(files[name]))]
    with pytest.raises(layer_stack.Refused) as refused:
        layer_stack.run_script([*imports, str(files["script"]), "run", str(tmp_path / "o.json")])
    assert refused.value.reply["error"]["modules"] == ["unpinned_helper"]
    assert not (tmp_path / "tree/sent.log").exists()
    assert_restored(isolated)


def test_an_import_whose_bytes_differ_is_refused_before_anything_runs(
    tmp_path: Path, isolated: dict[str, Any]
) -> None:
    files = adapter_tree(tmp_path / "tree")
    imports = ["--import", f"{files['decision_evidence']}={'0' * 64}"]
    with pytest.raises(layer_stack.Refused) as refused:
        layer_stack.run_script([*imports, str(files["script"]), "run", str(tmp_path / "o.json")])
    assert refused.value.reply["error"]["type"] == "PinMismatch"
    assert not (tmp_path / "tree/sent.log").exists()
    assert_restored(isolated)


def test_without_imports_the_script_imports_as_it_always_did(
    tmp_path: Path, isolated: dict[str, Any]
) -> None:
    """No `--import`: no import is refused or preloaded, and the script's own `sys.path` entry
    finds run.py and its helpers next to it, as before the closure existed."""
    files = adapter_tree(tmp_path / "tree")
    out = tmp_path / "out.json"
    del sys.modules["run"]  # the decoy would shadow run.py; the fixture puts it back
    try:
        assert layer_stack.run_script([str(files["script"]), "run", str(out)]) == 0
        assert sys.meta_path == isolated["meta_path"]
        assert sys.path[0] == str(tmp_path / "tree/Pipeline/production")
    finally:
        for name in ("run", "decision_evidence", "stage_review_evidence"):
            sys.modules.pop(name, None)
    assert json.loads(out.read_text(encoding="utf-8"))["mark"] == PINNED_MARK


# --- the MCP route -----------------------------------------------------------------------------


class FakeSession:
    """Replies to the round's typed calls; `sets` are the project's texture sets."""

    def __init__(self, sets: list[str]) -> None:
        self.sets = sets
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        if tool == "set_list":
            return {"result": {"texture_sets": [{"name": name} for name in self.sets]}}
        if tool == "export":
            return {"result": {"status": "committed", "files": []}}
        return {"result": {"status": "committed"}}


def round_of(
    manifest: dict[str, Any], assets: Path, tmp_path: Path, sets: list[str]
) -> tuple[FakeSession, mcp_round.Round, Any, dict[str, Path]]:
    job = load_script_job(manifest_file(tmp_path, manifest, "round"), assets)
    staged = stage_inputs(job, tmp_path / "round" / "assets")
    session = FakeSession(sets)
    log = mcp_round.Round(0, False)
    driver = mcp_round.Driver(cast(Any, session), log)
    with contextlib.suppress(mcp_round.RoundFailed):  # `log.outcome` says `failed`
        mcp_round.drive(driver, job, staged, tmp_path / "round")
    return session, log, job, staged


def arguments_of(session: FakeSession, tool: str) -> dict[str, Any]:
    return next(a for t, a in session.calls if t == tool)


def test_a_legacy_mcp_round_sends_the_historical_calls(assets: Path, tmp_path: Path) -> None:
    """`sync_stack` with only the stack and the masks list's folder, so the tool's defaults
    apply as before, and the mesh maps on the first texture set."""
    session, log, job, staged = round_of(wand_manifest(assets), assets, tmp_path, ["A", "B"])
    assert log.outcome == "completed"
    assert arguments_of(session, "sync_stack") == {
        "stack_json": str(staged[job.sync.args["stack"]]),
        "masks_dir": str(staged[job.sync.args["masks"][0]].parent),
    }
    assert arguments_of(session, "set_mesh_maps")["texture_set"] == "A"


def test_a_current_mcp_round_carries_the_options_on_the_create_scripts_set(
    assets: Path, tmp_path: Path
) -> None:
    """The three options under the tool's own names, and the mesh maps on the first set, which
    the sync's texture set names."""
    sets = ["25-Faixa-Cintura"]
    session, log, job, staged = round_of(current_manifest(assets), assets, tmp_path, sets)
    assert log.outcome == "completed"
    assert arguments_of(session, "sync_stack") == {
        "stack_json": str(staged[job.sync.args["stack"]]),
        "masks_dir": str(staged[job.sync.masks[0].input_id].parent),
        "resource_prefix": "v5f_",
        "resource_group": "faixa25_v5",
        "texture_set": "25-Faixa-Cintura",
    }
    assert arguments_of(session, "set_mesh_maps")["texture_set"] == "25-Faixa-Cintura"


@pytest.mark.parametrize(
    "sets",
    [
        [],
        ["11-Varinha-Madeira"],
        ["Other", "25-Faixa-Cintura"],
        ["25-Faixa-Cintura", "25-Faixa-Cintura"],
    ],
    ids=["no-set", "absent", "not-the-create-scripts-set", "ambiguous"],
)
def test_a_named_set_that_is_not_the_create_scripts_fails_before_the_first_set_edit(
    assets: Path, tmp_path: Path, sets: list[str]
) -> None:
    """A contract mismatch: the create script's mesh maps are never moved to another set."""
    session, log, _, _ = round_of(current_manifest(assets), assets, tmp_path, sets)
    assert log.outcome == "failed"
    assert [tool for tool, _ in session.calls] == ["project_create", "set_list"]


def test_a_legacy_mcp_round_refuses_a_project_without_a_set(assets: Path, tmp_path: Path) -> None:
    session, log, _, _ = round_of(wand_manifest(assets), assets, tmp_path, [])
    assert log.outcome == "failed"
    assert [tool for tool, _ in session.calls] == ["project_create", "set_list"]
