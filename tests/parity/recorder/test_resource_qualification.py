"""Decision 300: the Export resource qualification without Painter: the disposable bitmaps and
their pins, the run against a stand-in for Painter and its operator (fresh process for condition
B, sources deleted, a moved copy reopened), the verdicts, the public report, and how the UI
operator routes the export prompt."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder import resource_qualification as rq
from tools.parity.recorder.__main__ import main
from tools.parity.recorder.painter_ui import EXPORT_RESOURCE_ITEM, UiOperator, menu_label
from tools.parity.recorder.session import PainterIdentity, RecorderError

OCIO = r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\ocio\substance\config.ocio"


def test_every_disposable_bitmap_matches_its_pins() -> None:
    assert rq.fixtures(write=False) == []
    assert len({c.case_id for c in rq.CASES}) == len(rq.CASES) == 13
    assert {c.format_class for c in rq.CASES} == {"png", "tga", "exr", "jpeg"}
    assert [c.case_id for c in rq.CASES if not c.committed] == ["png16-grey-2048"]


def test_each_bitmap_states_the_form_it_is_declared_with() -> None:
    for case in rq.CASES:
        fields = rq.measure(rq.original_bytes(case))
        declared = (case.format_class, case.width, case.height, case.channels, case.bits)
        assert (fields["container"], fields["width"], fields["height"]) == declared[:3]
        assert (fields["channels"], fields["bits"]) == declared[3:]
        if case.format_class == "png":
            assert fields["srgb"] == (case.colour in ("srgb-chunk", "blender"))
            gama = {"gamma-1.0": 100000, "blender": 45455}.get(case.colour)
            assert fields["gama"] == gama
    pilot = {c.case_id: c.binding for c in rq.CASES if c.pilot_like}
    assert pilot == {
        "png16-rgb-blender": "normal-mesh-map",
        "png16-grey-pillow": "mask",
        "png16-grey-2048": "mask",
        "png8-rgb-pillow": "basecolor",
    }


def test_resource_names_take_the_sync_form() -> None:
    case = rq.CASES[0]
    assert case.resource_name == f"uzp_rq_png8_rgb_srgb_{case.sha1[:6]}"


class Painter:
    """What a Painter process holds across restarts: the saved projects' embedded resources."""

    def __init__(self) -> None:
        self.saved: dict[str, dict[str, bytes]] = {}
        self.processes = 0


class FakeSession:
    """A stand-in for one Painter process behind the recorder's session."""

    def __init__(self, painter: Painter) -> None:
        painter.processes += 1
        self.painter = painter
        self.session_id = f"process-{painter.processes}"
        self.identity: PainterIdentity | None = None
        self.resources: dict[str, bytes] = {}  # url -> bytes embedded in the open project
        self.calls: list[str] = []
        self.open = False

    def connect(self) -> PainterIdentity:
        self.identity = PainterIdentity(
            "12.1.5", (12, 1, 5), "1.1.20", self.session_id, {"mode": "ocio", "OCIO": OCIO}
        )
        return self.identity

    def wait_ready(self) -> None:
        return None

    def wait_closed(self) -> None:
        return None

    def url(self, name: str, data: bytes) -> str:
        return (
            f"resource://project{self.session_id}/{name}?version={hashlib.sha1(data).hexdigest()}"
        )

    def identity_of(self, url: str) -> dict[str, Any]:
        name, version = url.split("/")[-1].split("?version=")
        location = "PROJECT"
        return {
            "url": url,
            "name": name,
            "version": version,
            "location": location,
            "gui_name": name,
        }

    def call(self, operation: str, **args: Any) -> Any:
        self.calls.append(operation)
        if operation == "apply_step":
            self.open = True
            return {}
        if operation == "rq_import":
            data = Path(args["path"]).read_bytes()
            url = self.url(args["name"], data)
            self.resources[url] = data
            return self.identity_of(url)
        if operation == "save_as":
            Path(args["path"]).write_bytes(b"spp")
            self.painter.saved[Path(args["path"]).name] = dict(self.resources)
            return {}
        if operation == "close_project":
            self.open, self.resources = False, {}
            return {}
        if operation == "open_project":
            embedded = self.painter.saved["rq300.spp"]
            self.resources = {
                self.url(self.identity_of(u)["name"], d): d for u, d in embedded.items()
            }
            return {}
        if operation == "rq_project_resources":
            found: dict[str, Any] = {n: [] for n in args["names"]}
            for url in self.resources:
                identity = self.identity_of(url)
                found[identity["name"]].append({"listed_url": url, "retrieved": [identity]})
            return found
        if operation == "rq_show":
            self.shown = args["url"]
            return self.identity_of(args["url"])
        raise AssertionError(operation)


Behaviour = Callable[[str, bytes, Path], str]


class FakeOperator:
    """Writes what `behaviour` decides for each export: the condition, the resource's embedded
    bytes and the target folder."""

    def __init__(self, behaviour: Behaviour) -> None:
        self.behaviour = behaviour
        self.sessions: list[FakeSession] = []
        self.log: list[dict[str, Any]] = []

    def tell(self, message: str) -> None:
        return None

    def ask(self, question: str) -> str:
        if question == rq.IMAGE_PROMPT:
            return "assets.png"
        session = self.sessions[-1]
        target = Path(question.split("into the folder ", 1)[1].split(". Enter", 1)[0])
        condition = target.parent.parent.name
        return self.behaviour(condition, session.resources[session.shown], target)


def run(tmp_path: Path, behaviour: Behaviour, same_process: bool = False) -> dict[str, Any]:
    painter = Painter()
    operator = FakeOperator(behaviour)
    first = FakeSession(painter)
    operator.sessions.append(first)

    def restart(old: Any) -> Any:
        fresh = old if same_process else FakeSession(painter)
        fresh.connect()
        operator.sessions.append(fresh)
        return fresh

    directory = rq.record_qualification(
        first,  # type: ignore[arg-type]
        operator,
        tmp_path / "work",
        restart,
        now=lambda: datetime(2026, 10, 19, tzinfo=UTC),
        export_timeout_s=0.0,
    )
    evidence = json.loads((directory / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["sources_removed"] is True
    assert not any((directory / "sources").iterdir())
    assert (directory / "moved" / "rq300-moved.spp").is_file()
    assert first.calls.count("rq_show") == len(rq.CASES)
    analysis = json.loads((directory / "analysis.json").read_text(encoding="utf-8"))
    assert analysis == rq.analyse(directory)
    return {"directory": directory, "evidence": evidence, "analysis": analysis}


def exact(condition: str, data: bytes, target: Path) -> str:
    (target / "exported.bin").write_bytes(data)
    return "Export resource..."


def test_identical_bytes_in_both_conditions_qualify(tmp_path: Path) -> None:
    result = run(tmp_path, exact)
    outcome = result["analysis"]["outcome"]
    assert outcome["verdict"] == "EXACT" and outcome["pilot_forms_exact"] is True
    assert len(outcome["qualified_forms"]) == len(rq.CASES)
    row = result["analysis"]["cases"]["png16-grey-pillow"]
    assert row["version_is_sha1"] and row["version_stable"]
    assert row[rq.CONDITION_B]["status"] == rq.EXACT
    report = rq.report_markdown(result["analysis"], result["evidence"])
    assert "**Verdict: EXACT**" in report and str(tmp_path) not in report
    assert rq.CASES[0].sha256 in report


def test_a_re_encoded_export_is_never_an_original(tmp_path: Path) -> None:
    def re_encode(condition: str, data: bytes, target: Path) -> str:
        (target / "exported.bin").write_bytes(data + b"\0")
        return "Export resource"

    outcome = run(tmp_path, re_encode)["analysis"]["outcome"]
    assert outcome["verdict"] == "RE_ENCODED" and outcome["exact_cases"] == []


def test_an_export_that_needs_its_source_is_source_dependent(tmp_path: Path) -> None:
    def only_with_source(condition: str, data: bytes, target: Path) -> str:
        if condition == rq.CONDITION_A:
            (target / "exported.bin").write_bytes(data)
        return "Export resource"

    result = run(tmp_path, only_with_source)
    assert result["analysis"]["outcome"]["verdict"] == "SOURCE_DEPENDENT"
    row = result["analysis"]["cases"]["jpeg-rgb-srgb"]
    assert row[rq.CONDITION_B]["status"] == rq.NO_FILE


def test_a_missing_menu_item_is_unavailable(tmp_path: Path) -> None:
    outcome = run(tmp_path, lambda c, d, t: "Absent")["analysis"]["outcome"]
    assert outcome["verdict"] == "UNAVAILABLE"


def test_some_exact_forms_are_partial(tmp_path: Path) -> None:
    def png_only(condition: str, data: bytes, target: Path) -> str:
        (target / "exported.bin").write_bytes(data if data.startswith(b"\x89PNG") else b"x")
        return "Export resource"

    outcome = run(tmp_path, png_only)["analysis"]["outcome"]
    assert outcome["verdict"] == "PARTIAL"
    assert outcome["exact_format_classes"] == ["png"] and outcome["pilot_forms_exact"]
    assert all(form.startswith("png/") for form in outcome["qualified_forms"])


def test_two_files_or_an_old_file_is_not_an_export(tmp_path: Path) -> None:
    def two(condition: str, data: bytes, target: Path) -> str:
        (target / "a.bin").write_bytes(data)
        (target / "b.txt").write_bytes(b"sidecar")
        return "Export resource"

    result = run(tmp_path, two)
    assert result["analysis"]["cases"]["png8-rgb-srgb"][rq.CONDITION_A]["status"] == (
        rq.MULTIPLE_FILES
    )


def test_condition_b_in_the_same_process_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecorderError, match="freshly started"):
        run(tmp_path, exact, same_process=True)
    evidence = next((tmp_path / "work").rglob("evidence.json"))
    assert json.loads(evidence.read_text(encoding="utf-8"))["conditions"][rq.CONDITION_A]


def test_a_failed_step_is_inconclusive(tmp_path: Path) -> None:
    def refuse(condition: str, data: bytes, target: Path) -> str:
        raise RecorderError("the Assets window shows 0 visible items")

    result = run(tmp_path, refuse)
    assert result["analysis"]["outcome"]["verdict"] == "INCONCLUSIVE"
    entry = result["evidence"]["conditions"][rq.CONDITION_A]["png8-rgb-srgb"]
    assert entry["error"]["message"].startswith("the Assets window")


def test_a_legacy_session_is_refused(tmp_path: Path) -> None:
    session = FakeSession(Painter())
    session.connect = lambda: PainterIdentity(  # type: ignore[method-assign]
        "12.1.5", (12, 1, 5), "1.1.20", "p", {"mode": "legacy"}
    )
    with pytest.raises(RecorderError, match="OCIO"):
        rq.record_qualification(
            session,  # type: ignore[arg-type]
            FakeOperator(exact),
            tmp_path,
            lambda s: s,
        )


def test_the_export_menu_item_is_matched_by_its_label() -> None:
    for label in ("Export resource...", "&Export resources", "Export Resource…"):
        assert EXPORT_RESOURCE_ITEM.match(menu_label(label)), label
    for label in ("Export", "Export to library", "Reimport resource"):
        assert not EXPORT_RESOURCE_ITEM.match(menu_label(label)), label


class FakeUi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def export_resource(self, gui_name: str, target: Path, evidence: dict[str, Any]) -> str:
        self.calls.append((gui_name, target))
        evidence["menu"] = [{"text": "Export resource...", "enabled": True}]
        return "Export resource..."


def test_the_ui_operator_answers_the_export_prompt(tmp_path: Path) -> None:
    ui = FakeUi()
    operator = UiOperator(ui, tmp_path)  # type: ignore[arg-type]
    target = tmp_path / "exports" / "out"
    question = rq.EXPORT_PROMPT.format(gui_name="uzp_rq_x_abcdef", target=target)
    assert operator.ask(question) == "Export resource..."
    assert ui.calls == [("uzp_rq_x_abcdef", target)]
    evidence = json.loads(next(tmp_path.glob("export-*.json")).read_text(encoding="utf-8"))
    assert evidence["menu"][0]["enabled"] is True
    assert operator.log[-1]["action"] == "export_resource"


def test_the_command_needs_a_fresh_painter_for_condition_b(capsys: Any) -> None:
    assert main(["resource-export-qual", "--operator", "ui"]) == 2
    assert "--launch" in capsys.readouterr().out
