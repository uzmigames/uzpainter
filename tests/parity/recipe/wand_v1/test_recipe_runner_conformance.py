"""The Wand v1 rebuild-from-dump runner refuses a diagnostic export (phase2.2_recipe-and-diagnostics
item 3.1): an export whose receipt is marked `non_conformant`, as `--diagnostic-measure-export`
writes when `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT` is inherited from the environment, stops the
run on either side, and a conformant pair still gives its report. Nothing here starts UzPainter:
a stand-in wand writes each export's files, `current.json` and receipt the way the export does.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.adapters.assets3d.wand import Call
from tests.parity.recipe.wand_v1 import runner
from tests.parity.tier1.wand_v1.runner import REFUSAL, RunError
from tools.parity.recipe_rebuild import Side

MESSAGE = "the export's receipt is marked non_conformant"
ARGS = "painter-export-args"


class StandIn:
    """The parts of `Wand` the runner uses. `plan` holds, per export in order, `True` for a
    receipt marked `non_conformant`, `False` for a conformant one, or `None` for a refusal."""

    def __init__(self, work: Path, plan: list[bool | None]) -> None:
        self.work = work
        self.plan = plan
        self.exports: list[bool] = []  # each export's `diagnostic` argument
        self.probes: list[str] = []
        work.mkdir()
        arguments = work / "export-arguments.json"
        arguments.write_text(json.dumps({"out": str(work / "original" / "out")}), "utf-8")
        self.redirects = {ARGS: str(arguments)}
        self.job = SimpleNamespace(export=SimpleNamespace(hard_coded_args=ARGS))
        self.session = work / "session.json"
        self.session.write_text(json.dumps({"project": str(work / "wand.spp")}), "utf-8")

    def argument(self, step: str, key: str) -> Path:
        assert (step, key) == ("export", "out")
        return Path(json.loads(Path(self.redirects[ARGS]).read_text("utf-8"))[key])

    def export(self, diagnostic: bool = False) -> Call:
        self.exports.append(diagnostic)
        marked = self.plan[len(self.exports) - 1]
        if marked is None:
            return Call(1, "", f"{REFUSAL}: infinite padding on UV islands")
        out = self.argument("export", "out")
        out.mkdir(parents=True)
        image = out / "T_Wand_BaseColor.png"
        image.write_bytes(b"map")
        receipt: dict[str, Any] = {"files": [image.name]}
        if marked:
            receipt["non_conformant"] = True
        (out / "receipt.json").write_text(json.dumps(receipt), "utf-8")
        (out / "current.json").write_text(json.dumps({"receipt": "receipt.json"}), "utf-8")
        result = {"status": "ExportStatus.Success", "files": {"('Wand', '')": [str(image)]}}
        return Call(0, json.dumps(result), "")

    def probe(self, name: str, body: str) -> dict[str, Any]:
        self.probes.append(name)
        if name == "rebuild":
            return {"file": str(self.work / "rebuilt" / "wand.spp")}
        return {"digest": name}


def scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plan: list[bool | None]
) -> tuple[StandIn, list[tuple[Side, Side]]]:
    """A stand-in wand for `plan` in `runner.run`, and the sides each report was built from."""
    wand = StandIn(tmp_path / "work", plan)
    sides: list[tuple[Side, Side]] = []

    def report(*arguments: Any) -> dict[str, Any]:
        sides.append((arguments[3], arguments[4]))
        return {"report": True}

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", "utf-8")
    monkeypatch.setattr(runner, "job_manifest", lambda: manifest)
    monkeypatch.setattr(runner, "built", lambda painter, work, job: wand)
    monkeypatch.setattr(runner, "resources", lambda painter, project, work: work / "resources")
    monkeypatch.setattr(runner, "report", report)
    return wand, sides


@pytest.fixture
def painter(tmp_path: Path) -> Path:
    executable = tmp_path / "UzPainter.exe"
    executable.write_bytes(b"exe")
    return executable


def test_non_conformant_first_export_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, painter: Path
) -> None:
    wand, sides = scenario(tmp_path, monkeypatch, [True, False])
    with pytest.raises(RunError) as raised:
        runner.run(painter, wand.work)
    assert str(raised.value) == MESSAGE
    assert wand.exports == [False]
    assert wand.probes == []
    assert sides == []


def test_non_conformant_second_export_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, painter: Path
) -> None:
    wand, sides = scenario(tmp_path, monkeypatch, [False, True])
    with pytest.raises(RunError) as raised:
        runner.run(painter, wand.work)
    assert str(raised.value) == MESSAGE
    assert wand.exports == [False, False]
    assert wand.probes == ["dump-original", "rebuild"]
    assert sides == []


def test_conformant_pair_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, painter: Path
) -> None:
    wand, sides = scenario(tmp_path, monkeypatch, [False, False])
    result = runner.run(painter, wand.work)
    assert result.report == {"report": True}
    assert result.refusals == ()
    assert wand.exports == [False, False]
    assert wand.probes == ["dump-original", "rebuild", "dump-rebuilt"]
    ((original, rebuilt),) = sides
    assert original.files == {
        "T_Wand_BaseColor.png": wand.work / "original" / "out" / "T_Wand_BaseColor.png"
    }
    assert rebuilt.files == {
        "T_Wand_BaseColor.png": wand.work / "rebuilt" / "out" / "T_Wand_BaseColor.png"
    }


def test_refused_export_keeps_its_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, painter: Path
) -> None:
    wand, sides = scenario(tmp_path, monkeypatch, [None, False])
    result = runner.run(painter, wand.work)
    assert result.refusals == (f"{REFUSAL}: infinite padding on UV islands",)
    ((original, rebuilt),) = sides
    assert original.files is None
    assert rebuilt.files is not None
