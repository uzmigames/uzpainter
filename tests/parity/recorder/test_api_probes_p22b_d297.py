"""P22-B API probes of decision 297 (phase1.24 item 3.4): the host modules (application, logging,
js, ui, event, resource, exception, async_utils, display and substance_painter_plugins). The
jobs live under the envelope's `requests/` or admitted `manifests/` root; each must validate,
load as an observed probe job, name the pending Painter symbols it exercises, and record both
`r1` and `r2` end to end against the fake Painter (`fake_probe_painter.py`).
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.probes import (
    CleanupFailed,
    ProbeSession,
    load_probe_job,
    manifest_symbol_problems,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, load_json, record_problems

ENVELOPE = REPO_ROOT / "parity" / "envelopes" / "painter-12.1.5_js-api.1.1.20"
REQUEST_DIR = ENVELOPE / "requests" / "tier0" / "api-probes"
MANIFEST_DIR = ENVELOPE / "manifests" / "tier0" / "api-probes"
INVENTORY = REPO_ROOT / "tools" / "capabilities" / "painter-api-inventory.json"
STEMS = [
    "p22b-host-application",
    "p22b-host-events",
    "p22b-host-plugins",
    "p22b-host-resources",
]
SOFTWARE = {
    "product": "Adobe Substance 3D Painter",
    "version": "12.1.5",
    "build_id": "12.1.5+js-api.1.1.20",
}
SP = "substance_painter."
PLUGINS = "substance_painter_plugins"
# The modules of decision 297's group.
MODULES = (
    "event",
    "resource",
    "ui",
    "logging",
    "application",
    "async_utils",
    "exception",
    "display",
    "js",
)
# Symbols decision 297 routes to another evidence route than a P22-B request, with the route.
G5 = "G5 owner scope decision"
BAKERS = "phase3.5_embree-bakers"
ROUTED = {
    f"{SP}event.BakingProcessAboutToStart": BAKERS,
    f"{SP}event.BakingProcessProgress": BAKERS,
    f"{SP}event.BakingProcessEnded": BAKERS,
    f"{SP}async_utils": BAKERS,
    f"{SP}async_utils.StopSource": BAKERS,
    f"{SP}async_utils.StopSource.request_stop": BAKERS,
    f"{SP}async_utils.StopSource.stop_requested": BAKERS,
    f"{PLUGINS}.load_startup_modules": G5,
    f"{PLUGINS}.close_all_plugins": G5,
    f"{SP}ui.ApplicationMenu": G5,
    **{
        f"{SP}ui.ApplicationMenu.{name}": G5
        for name in ("File", "Edit", "Mode", "Window", "Viewport", "Help")
    },
    f"{SP}exception.ServiceNotFoundError": G5,
    f"{SP}resource.AllResourcesFilter": G5,
    # `display` left this route in abd94980: the module is supported through its member
    # `display.set_environment_resource`, exercised exactly by p22b-host-resources.
}
# Decision 188's requests exercise these (decision 189 §2).
REQUESTED_BY_188 = {
    f"{SP}event.CameraPropertiesChanged",
    f"{SP}event.ShelfCrawlingStarted",
    f"{SP}event.ShelfCrawlingEnded",
    f"{SP}event.TextureStateEvent",
    f"{SP}resource.Resource.gui_name",
    f"{SP}resource.Resource.usages",
    f"{SP}resource.Shelf",
    *(f"{SP}resource.Shelf.{m}" for m in ("is_crawling", "name", "path", "refresh")),
    f"{SP}resource.Shelves",
    *(f"{SP}resource.Shelves.{m}" for m in ("add", "all", "exists")),
    f"{SP}resource.Usage.ENVIRONMENT",
}
# What a request reaches besides its calls and the members its arguments name: the events its
# connections receive, the classes a reload reports, the documented errors its probes provoke and
# the modules whose members it calls.
REACHED = {
    "p22b-host-application": {f"{SP}ui", f"{SP}logging", f"{SP}js"},
    "p22b-host-events": {
        f"{SP}event.DISPATCHER.connect_strong",
        f"{SP}event.TextureStateEventAction",
        *(f"{SP}event.TextureStateEventAction.{a}" for a in ("ADD", "UPDATE", "REMOVE")),
    },
    "p22b-host-plugins": {PLUGINS},
    "p22b-host-resources": {
        f"{SP}event.ReloadedResourceResult",
        f"{SP}event.ReloadedResourceError",
        f"{SP}exception",
        f"{SP}exception.ProjectError",
        f"{SP}exception.ResourceNotFoundError",
    },
}
PROBE_FAKE = "uzp_recorder_fake_probe_painter"


def probe_path(stem: str) -> Path:
    """Resolve the request or admitted manifest; never recreate an admitted request."""
    paths = [root / f"{stem}.json" for root in (REQUEST_DIR, MANIFEST_DIR)]
    existing = [path for path in paths if path.is_file()]
    assert len(existing) == 1, (stem, existing)
    return existing[0]


def steps_of(stem: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = load_json(probe_path(stem))["instruction_sequence"][
        "steps"
    ]
    return steps


def exercised() -> dict[str, set[str]]:
    """Each symbol a request exercises, with the requests: the calls it makes, the enum members,
    filters and event classes its arguments name, and what it reaches (`REACHED`)."""
    found: dict[str, set[str]] = {}

    def note(symbol: str, stem: str) -> None:
        found.setdefault(symbol, set()).add(stem)

    for stem in STEMS:
        for symbol in REACHED[stem]:
            note(symbol, stem)
        for step in steps_of(stem):
            call, args = step["call"], step.get("args", {})
            note(call, stem)
            if "severity" in args:
                note(f"{SP}logging.{args['severity']}", stem)
            if "mode" in args and call == f"{SP}ui.switch_to_mode":
                note(f"{SP}ui.UIMode", stem)
                note(f"{SP}ui.UIMode.{args['mode']}", stem)
            if "usage" in args:
                note(f"{SP}resource.Usage.{args['usage']}", stem)
            if "filter" in args:
                note(f"{SP}resource.{args['filter']}", stem)
            for name in args.get("events", []):
                note(f"{SP}event.{name}", stem)
    return found


def pending_of_the_group() -> set[str]:
    """The pending Painter symbols of the group that decision 188's requests do not exercise."""
    pending = set()
    for e in load_json(INVENTORY)["entries"]:
        parts = e["symbol"].split(".")
        mine = parts[0] == PLUGINS or (len(parts) > 1 and parts[1] in MODULES)
        notes = e.get("notes") or ""
        owned = "P22-B" in notes or "decision 297" in notes
        if e["status"] == "pending-evidence" and mine and owned:
            pending.add(e["symbol"])
    return pending - REQUESTED_BY_188


# --- requests --------------------------------------------------------------------------------


def test_the_requests_or_manifests_are_observed_probe_jobs() -> None:
    assert {
        p.stem for root in (REQUEST_DIR, MANIFEST_DIR) for p in root.glob("p22b-host-*.json")
    } == set(STEMS)
    for stem in STEMS:
        path = probe_path(stem)
        manifest = load_json(path)
        job = load_probe_job(path)  # validates against golden-public.json first
        assert job.golden_id == f"tier0/api-probes/{stem}"
        assert bool(manifest["private_records"]) == (path.parent == MANIFEST_DIR)
        assert manifest["software"]["painter"] == SOFTWARE
        assert manifest_symbol_problems(manifest) == []
        assert job.observed and not job.lifecycle and not job.exports
        assert not [s for s in manifest["applied_settings"] if s["name"] == "OCIO"]  # Legacy


def test_every_pending_symbol_of_the_group_is_requested_or_routed() -> None:
    pending = pending_of_the_group()
    covered = set(exercised())
    assert pending - covered - set(ROUTED) == set()
    assert set(ROUTED) <= pending and not set(ROUTED) & covered


def test_every_routed_symbol_names_its_route_in_the_manifest() -> None:
    notes = {e["symbol"]: e.get("notes") or "" for e in load_json(INVENTORY)["entries"]}
    owners = {BAKERS: BAKERS, G5: "G5's explicit owner scope decision"}
    for symbol, route in ROUTED.items():
        assert "decision 297" in notes[symbol], symbol
        assert owners.get(route, "phase2.1_preview-display-presets") in notes[symbol], symbol


def test_the_requests_name_the_symbols_they_exercise() -> None:
    pending = pending_of_the_group()
    for symbol, stems in exercised().items():
        if symbol not in pending:
            continue
        for stem in stems:
            description = load_json(probe_path(stem))["description"]
            assert symbol.rsplit(".", 1)[-1] in description, (stem, symbol)


def edited(stem: str, call: str, **changes: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = load_json(probe_path(stem))
    step = next(s for s in manifest["instruction_sequence"]["steps"] if s["call"] == call)
    step["args"].update(changes)
    return manifest


def test_a_plugin_call_names_a_probe_module_and_a_root_a_plain_folder() -> None:
    manifest = edited("p22b-host-plugins", f"{PLUGINS}.start_plugin", module="os")
    with pytest.raises(RecorderError, match="must name a probe plugin module"):
        probe_job_from_manifest(manifest)
    manifest = edited("p22b-host-plugins", f"{PLUGINS}.path", folder="../outside")
    with pytest.raises(RecorderError, match="must be a plain folder name"):
        probe_job_from_manifest(manifest)


# --- recording against the fake --------------------------------------------------------------


@pytest.fixture
def probe_fake(fake: types.ModuleType) -> types.ModuleType:
    """`fake_probe_painter.py`, loaded by path after `fake_painter.py` (which it extends)."""
    if PROBE_FAKE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PROBE_FAKE, Path(__file__).with_name("fake_probe_painter.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[PROBE_FAKE] = module
        spec.loader.exec_module(module)
    return sys.modules[PROBE_FAKE]


def fake_session(probe_fake: types.ModuleType, fake: types.ModuleType) -> tuple[Any, ProbeSession]:
    world = probe_fake.ProbeWorld()
    world.version, world.version_info = SOFTWARE["version"], (12, 1, 5)
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda s: None,
        allowed_builds=lambda: frozenset({SOFTWARE["build_id"]}),
    )
    return world, session


def record(
    probe_fake: types.ModuleType, fake: types.ModuleType, stem: str, tmp_path: Path
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    world, session = fake_session(probe_fake, fake)
    job = load_probe_job(probe_path(stem))
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    assert [r["condition"] for r in data["recordings"]] == ["same_session", "after_save_reopen"]
    first, second = (
        {o["output_id"]: o for o in recording["outputs"]} for recording in data["recordings"]
    )
    for recording in (first, second):
        assert {s.output_id for s in job.probe_steps} <= set(recording)
        assert not [k for k in recording if k.endswith("/pending")]
    return world, first, second


@pytest.fixture(autouse=True)
def legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCIO", raising=False)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)


@pytest.mark.parametrize("stem", STEMS)
def test_every_request_records_r1_and_r2(
    probe_fake: types.ModuleType, fake: types.ModuleType, stem: str, tmp_path: Path
) -> None:
    record(probe_fake, fake, stem, tmp_path)


def test_application_logging_js_and_ui_modes_read_back(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    world, first, second = record(probe_fake, fake, "p22b-host-application", tmp_path)
    for recording in (first, second):
        assert recording["s3/version"]["value"] == "12.1.5"
        assert recording["s4/version_info"]["value"] == [12, 1, 5]
        assert [
            recording[f"s{n}/{s}"]["value"]
            for n, s in zip(
                range(5, 11),
                ("INFO", "WARNING", "ERROR", "DBG_INFO", "DBG_WARNING", "DBG_ERROR"),
                strict=True,
            )
        ] == [0, 1, 2, 3, 4, 5]  # the fake's values
        for n in range(11, 20):
            logged = recording[f"s{n}/{'log' if n > 13 else ('info', 'warning', 'error')[n - 11]}"]
            assert logged["value"] is None and "raised" not in logged
        assert recording["s20/evaluate"]["value"] == "12.1.5"
        assert recording["s21/evaluate"]["value"] is True
        modes = [recording[f"s{n}/get_current_mode"]["value"] for n in (26, 28, 30, 32)]
        assert modes == ["Edition", "Baking", "Visualisation", "Edition"]
    assert len(world.log_lines) == 2 * 9
    assert ("uzp_probe" in {channel for _, channel, _ in world.log_lines}) is True


def test_strong_connections_texture_states_and_the_throttling_period(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    world, first, second = record(probe_fake, fake, "p22b-host-events", tmp_path)
    for recording in (first, second):
        assert recording["s6/connect_strong"]["value"] == {
            "connected_strong": [
                "EngineComputationsStatusChanged",
                "Event",
                "ProjectSaved",
                "TextureStateEvent",
            ]
        }
        updated = [e for e in recording["s7/events"]["value"] if e.get("connection") == "strong"]
        seen = [(e["event"], e["action_argument"], e["channel_type_argument"]) for e in updated]
        assert seen == [("TextureStateEvent", "UPDATE", "BaseColor")]
        assert updated[0]["tile_indices_argument"] == [0, 0]
        toggled = recording["s9/events"]["value"]
        assert {(e["event"], e.get("connection")) for e in toggled} == {
            ("EngineComputationsStatusChanged", None),
            ("EngineComputationsStatusChanged", "strong"),
        }
        assert recording["s15/set_cache_key_invalidation_throttling_period"]["raised"]["type"] == (
            "ValueError"
        )
        period = "cache_key_invalidation_throttling_period"
        # The period is global to the session: r2 starts with the 750 ms r1 set.
        before = 1000.0 if recording is first else 750.0
        assert recording[f"s14/{period}"]["value"] == {"timedelta_ms": before}
        assert recording[f"s16/{period}"]["value"] == {"timedelta_ms": before}
        assert recording[f"s18/{period}"]["value"] == {"timedelta_ms": 750.0}
        saved = [e["event"] for e in recording["s19/events"]["value"]]
        assert saved.count("ProjectSaved") == 2  # the weak and the strong connection
        closed = [e for e in recording["s20/events"]["value"] if e.get("connection") == "strong"]
        assert {e["action_argument"] for e in closed} == {"REMOVE"}
        opened = [e for e in recording["s21/events"]["value"] if e.get("connection") == "strong"]
        assert {e["action_argument"] for e in opened} == {"ADD"}
        assert all(e["dispatched"] == "TextureStateEvent" for e in opened)
        assert "uniform_color_working" in recording["s22/get_source"]["value"]
    assert world.throttling == datetime.timedelta(seconds=1)  # restored when the golden ended
    assert not any(callbacks for callbacks in world.listeners.values())  # all disconnected


def test_resources_reload_filters_errors_and_the_closed_project(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    world, first, second = record(probe_fake, fake, "p22b-host-resources", tmp_path)
    assert first["s6/import_project_resource"]["raised"]["type"] == "ValueError"  # GENERATOR
    assert "raised" not in first["s5/import_project_resource"]  # COLOR_LUT
    for recording in (first, second):
        listed = recording["s9/list_project_resources"]["value"]
        assert len(listed) == 3
        assert recording["s11/from_project"]["value"]["resource"]["name"] == (
            "uzp_missing_environment"
        )
        assert recording["s12/from_url"]["value"]["resource"]["name"] == "checker.image"
        assert recording["s13/from_url"]["raised"]["type"] == "ValueError"
        missing = recording["s14/set_environment_resource"]["raised"]
        assert missing["type"] == "ResourceNotFoundError"
        refreshed = [e["shelf_name_argument"] for e in recording["s17/events"]["value"]]
        assert sorted(set(refreshed)) == ["starter_assets", "uzp_probe_host_shelf", "your_assets"]
        assert recording["s18/remove"]["raised"]["type"] == "ProjectError"
        shelves = recording["s23/events"]["value"][0]["filter_argument"]
        assert shelves == "ShelvesListFilter"
        ended = recording["s24/events"]["value"][-1]
        assert ended["event"] == "ReloadResourcesEnded"
        if recording is first:  # r2 rewrites the same bytes again
            assert [e["error_msg"] for e in ended["resource_errors_argument"]] == [
                "the file is not a valid image"
            ]
        assert recording["s27/list_project_resources"]["raised"]["type"] == "ProjectError"
        assert "raised" not in recording["s28/remove"]
        assert recording["s29/exists"]["value"] is False
        assert recording["s30/rebind"]["value"]["found_by"] == {}
    assert world.shelves == {}


def test_plugins_run_their_hooks_and_leave_no_trace(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    path_before, modules_before = list(sys.path), set(sys.modules)
    world, first, second = record(probe_fake, fake, "p22b-host-plugins", tmp_path)
    root = {"run_relative": ["plugin-roots", "uzp-plugins"]}
    for recording in (first, second):
        assert recording["s3/path"]["value"] == {
            "probe_roots": [] if recording is first else [root]
        }
        assert recording["s4/path"]["value"] == {"probe_roots": [root]}
        assert "raised" not in recording["s5/update_sys_path"]
        folders = recording["s5/update_sys_path"]["value"]["probe_folders"]
        assert [f["run_relative"][-1] for f in folders] == ["plugins", "startup", "modules"]
        assert recording["s7/plugin_module_names"]["value"] == ["uzp_probe_plugin"]
        assert recording["s8/startup_module_names"]["value"] == ["uzp_probe_startup"]
        started = recording["s9/start_plugin"]["value"]
        hooks = ["uzp_probe_plugin.start_plugin"]
        imported = (
            ["uzp_probe_plugin.import", "uzp_probe_startup.import"] if recording is first else []
        )
        assert started["hooks"] == [*imported, *hooks]
        assert recording["s10/is_plugin_started"]["value"] is True
        assert recording["s11/plugins"]["value"]["uzp_probe_plugin"] == {
            "name_is_key": True,
            "module_is_key": False,
            "module_is_value": True,
        }
        assert recording["s12/reload_plugin"]["value"] == {
            "returned": {"is_the_loaded_module": True},
            "hooks": [
                "uzp_probe_plugin.close_plugin",
                "uzp_probe_plugin.reload_plugin",
                "uzp_probe_plugin.import",
                "uzp_probe_plugin.start_plugin",
            ],
        }
        assert recording["s14/close_plugin"]["value"]["hooks"] == ["uzp_probe_plugin.close_plugin"]
        assert recording["s15/is_plugin_started"]["value"] is False
        assert recording["s19/is_plugin_started"]["value"] is False
    plugins = world.modules[PLUGINS]
    assert plugins.path == [] and plugins.plugins == {}
    assert sys.path == path_before and set(sys.modules) <= modules_before | {PROBE_FAKE}
    assert "UZP_PROBE_PLUGIN_LOG" not in os.environ


# --- isolation and cleanup (SUP-016, SUP-017) -------------------------------------------------

SHELF = "uzp_probe_host_shelf"
HOOK_LOG = "UZP_PROBE_PLUGIN_LOG"
EVENT = "substance_painter.event"


def with_steps(stem: str, **changes: dict[str, Any]) -> dict[str, Any]:
    """The request with the arguments of the numbered steps (`s<n>=`) changed."""
    manifest: dict[str, Any] = load_json(probe_path(stem))
    for step in manifest["instruction_sequence"]["steps"]:
        step["args"].update(changes.get(f"s{step['step']}", {}))
    return manifest


def published(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "inbox").rglob("record.json"))


def attempt_recording(session: ProbeSession, manifest: dict[str, Any], tmp_path: Path) -> None:
    job = probe_job_from_manifest(manifest)
    record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")


def unchanged_host(world: Any, tmp_path: Path) -> None:
    """A run refused before any change: no project, connection or golden."""
    assert not world.project_open
    assert not any(world.listeners.values())
    assert published(tmp_path) == []


def test_an_existing_shelf_of_the_probe_name_refuses_the_run_untouched(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    world, session = fake_session(probe_fake, fake)
    owner = (tmp_path / "owner-shelf").as_posix()
    world.shelves[SHELF] = owner
    with pytest.raises(RecorderError, match=f"shelf named '{SHELF}' exists already"):
        attempt_recording(session, load_json(probe_path("p22b-host-resources")), tmp_path)
    assert world.shelves == {SHELF: owner} and world.crawling == set()
    assert not world.reloading
    unchanged_host(world, tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"s18": {"name": "owner_shelf"}},
        {"s23": {"shelves": ["owner_shelf"]}},
    ],
    ids=["remove", "shelves-filter"],
)
def test_a_shelf_the_run_did_not_add_is_never_removed_or_reloaded(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    changes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, session = fake_session(probe_fake, fake)
    owner = (tmp_path / "owner-shelf").as_posix()
    world.shelves["owner_shelf"] = owner
    resource = world.modules["substance_painter.resource"]
    reload_before, filters = resource.reload_modified_resources_async, []

    def reload(resource_filter: Any) -> Any:
        filters.append(type(resource_filter).__name__)
        return reload_before(resource_filter)

    monkeypatch.setattr(resource, "reload_modified_resources_async", reload)
    manifest = with_steps("p22b-host-resources", **changes)
    with pytest.raises(RecorderError, match="'owner_shelf' was not added by this probe run"):
        attempt_recording(session, manifest, tmp_path)
    assert "ShelvesListFilter" not in filters
    assert world.shelves == {"owner_shelf": owner}  # the run's own shelf was removed again
    assert published(tmp_path) == []


def test_a_shelf_replaced_under_the_run_name_is_kept_and_nothing_is_published(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another shelf takes the run's name after its add: the run never removes it, and the failed
    cleanup is added to the recording error, whose cause stays the original one."""
    world, session = fake_session(probe_fake, fake)
    shelves = world.modules["substance_painter.resource"].Shelves
    add_before, other = shelves.add, (tmp_path / "other-shelf").as_posix()

    def add(name: str, path: str) -> Any:
        added = add_before(name, path)
        world.shelves[name] = other
        return added

    monkeypatch.setattr(shelves, "add", staticmethod(add))
    with pytest.raises(CleanupFailed) as refused:
        attempt_recording(session, load_json(probe_path("p22b-host-resources")), tmp_path)
    message = str(refused.value)
    assert f"shelf '{SHELF}' is not the one this probe run added" in message
    assert f"probe_cleanup shelf/{SHELF}: ProbeGuardError" in message
    assert "ProbeGuardError" in str(refused.value.__cause__)
    assert world.shelves == {SHELF: other}
    assert published(tmp_path) == []


def owner_module(calls: list[str]) -> types.ModuleType:
    owner = types.ModuleType("uzp_probe_plugin")
    for hook in ("start_plugin", "close_plugin", "reload_plugin"):
        setattr(owner, hook, lambda hook=hook: calls.append(hook))
    return owner


def shadow_folder(tmp_path: Path) -> tuple[Path, Path]:
    """A folder with another `uzp_probe_plugin.py`, which leaves a marker when imported and
    when any of its hooks runs."""
    folder, marker = tmp_path / "owner-lib", tmp_path / "imported.marker"
    folder.mkdir()
    touch = f"open({marker.as_posix()!r}, 'a').close()"
    hooks = "".join(f"def {h}():\n    {touch}\n" for h in ("start_plugin", "close_plugin"))
    source = f"{touch}\n{hooks}def reload_plugin():\n    {touch}\n"
    (folder / "uzp_probe_plugin.py").write_text(source, encoding="utf-8")
    return folder, marker


def plugins_untouched(world: Any) -> None:
    plugins = world.modules[PLUGINS]
    assert plugins.path == [] and plugins.plugins == {}
    assert HOOK_LOG not in os.environ
    assert not [p for p in sys.path if "plugin-roots" in str(p)]


def test_an_imported_module_of_the_probe_name_refuses_the_run_untouched(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, session = fake_session(probe_fake, fake)
    calls: list[str] = []
    owner = owner_module(calls)
    monkeypatch.setitem(sys.modules, "uzp_probe_plugin", owner)
    with pytest.raises(RecorderError, match="'uzp_probe_plugin' is imported already"):
        attempt_recording(session, load_json(probe_path("p22b-host-plugins")), tmp_path)
    assert calls == [] and sys.modules["uzp_probe_plugin"] is owner
    plugins_untouched(world)
    unchanged_host(world, tmp_path)


def test_a_shadowing_module_on_the_path_refuses_the_run_untouched(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, session = fake_session(probe_fake, fake)
    folder, marker = shadow_folder(tmp_path)
    monkeypatch.syspath_prepend(str(folder))
    with pytest.raises(RecorderError, match="'uzp_probe_plugin' is importable from"):
        attempt_recording(session, load_json(probe_path("p22b-host-plugins")), tmp_path)
    assert not marker.exists() and "uzp_probe_plugin" not in sys.modules
    assert str(folder) in sys.path and (folder / "uzp_probe_plugin.py").is_file()
    plugins_untouched(world)
    unchanged_host(world, tmp_path)


def test_a_module_shadowed_during_the_run_is_never_imported_and_the_run_cleans_up(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A folder put ahead on `sys.path` after the preflight: the origin check refuses the start,
    the other module is never imported, and the run's own path entries leave again."""
    world, session = fake_session(probe_fake, fake)
    folder, marker = shadow_folder(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    plugins = world.modules[PLUGINS]
    update_before = plugins.update_sys_path

    def update_sys_path() -> None:
        update_before()
        sys.path.insert(0, str(folder))

    monkeypatch.setattr(plugins, "update_sys_path", update_sys_path)
    with pytest.raises(RecorderError, match="'uzp_probe_plugin' would import from"):
        attempt_recording(session, load_json(probe_path("p22b-host-plugins")), tmp_path)
    assert not marker.exists() and "uzp_probe_plugin" not in sys.modules
    assert sys.path[0] == str(folder)  # not the run's entry: it stays
    plugins_untouched(world)
    assert published(tmp_path) == []


def test_a_module_shadowed_between_start_and_reload_is_never_imported(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A folder put ahead on `sys.path` once the run's module is imported and started: the
    import system's fresh resolution, not the loaded module's cached spec, is checked, so no
    later step reloads the other file (SUP-028)."""
    world, session = fake_session(probe_fake, fake)
    folder, marker = shadow_folder(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    plugins = world.modules[PLUGINS]
    start_before, reload_before, reloads = plugins.start_plugin, plugins.reload_plugin, []

    def start_plugin(module: types.ModuleType) -> None:
        start_before(module)
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))

    def reload_plugin(module: types.ModuleType) -> types.ModuleType:
        reloads.append(module)
        reloaded: types.ModuleType = reload_before(module)
        return reloaded

    monkeypatch.setattr(plugins, "start_plugin", start_plugin)
    monkeypatch.setattr(plugins, "reload_plugin", reload_plugin)
    with pytest.raises(RecorderError, match="'uzp_probe_plugin' would import from"):
        attempt_recording(session, load_json(probe_path("p22b-host-plugins")), tmp_path)
    assert reloads == [] and not marker.exists()  # no foreign import and no foreign hook
    assert "uzp_probe_plugin" not in sys.modules and plugins.plugins == {}
    plugins_untouched(world)
    assert published(tmp_path) == []


@pytest.mark.parametrize("wrong_field", ["__file__", "__spec__"])
def test_discovery_never_claims_a_foreign_homonym(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wrong_field: str,
) -> None:
    world, session = fake_session(probe_fake, fake)
    plugins = world.modules[PLUGINS]
    discover_before = plugins.plugin_module_names
    foreign = types.ModuleType("uzp_probe_plugin")
    foreign_path = str(tmp_path / "foreign.py")

    def discover() -> Any:
        names = discover_before()
        staged = sys.modules["uzp_probe_plugin"]
        foreign.__file__ = staged.__file__
        foreign.__spec__ = staged.__spec__
        if wrong_field == "__file__":
            foreign.__file__ = foreign_path
        else:
            foreign.__spec__ = importlib.util.spec_from_file_location(
                "uzp_probe_plugin", foreign_path
            )
        sys.modules["uzp_probe_plugin"] = foreign
        return names

    monkeypatch.setattr(plugins, "plugin_module_names", discover)
    try:
        with pytest.raises(RecorderError, match="the discovered module 'uzp_probe_plugin'"):
            attempt_recording(session, load_json(probe_path("p22b-host-plugins")), tmp_path)
        assert sys.modules["uzp_probe_plugin"] is foreign
    finally:
        if sys.modules.get("uzp_probe_plugin") is foreign:
            del sys.modules["uzp_probe_plugin"]
    assert plugins.plugins == {} and plugins.path == []
    assert published(tmp_path) == []


def without_closes(stem: str) -> dict[str, Any]:
    """The plugin request with its two `close_plugin` steps read `is_plugin_started` instead, so
    both modules are still started when the golden ends."""
    manifest: dict[str, Any] = load_json(probe_path(stem))
    for step in manifest["instruction_sequence"]["steps"]:
        if step["call"] == f"{PLUGINS}.close_plugin":
            step["call"], step["args"] = (
                f"{PLUGINS}.is_plugin_started",
                {"module": step["args"]["module"]},
            )
    return manifest


def test_the_hooks_log_only_to_the_run_file_even_when_a_close_is_retried(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first cleanup cannot close one module, which stays pending; its close hook runs at the
    retry. An earlier log of the owner's never receives a line, and its setting is untouched."""
    sentinel = tmp_path / "owner.log"
    monkeypatch.setenv(HOOK_LOG, str(sentinel))
    world, session = fake_session(probe_fake, fake)
    plugins = world.modules[PLUGINS]
    close_before, refuse = plugins.close_plugin, [False]
    call_before = session.call

    def call(operation: str, **args: Any) -> Any:
        retry = args.pop("retry", False)
        refuse[0] = refuse[0] or (operation == "probe_cleanup" and not retry)
        return call_before(operation, **args)

    def close_plugin(module: types.ModuleType, gc_collect: bool = True) -> None:
        if refuse[0]:
            refuse[0] = False
            raise RuntimeError("the close was refused")
        close_before(module, gc_collect)

    monkeypatch.setattr(session, "call", call)
    monkeypatch.setattr(plugins, "close_plugin", close_plugin)
    with pytest.raises(CleanupFailed, match="probe_cleanup plugin/uzp_probe_plugin: RuntimeError"):
        attempt_recording(session, without_closes("p22b-host-plugins"), tmp_path)
    assert published(tmp_path) == []
    assert "uzp_probe_plugin" in plugins.plugins and "uzp_probe_startup" not in plugins.plugins
    retried = session.call("probe_cleanup", retry=True)
    assert retried["cleanup_failures"] == [] and plugins.plugins == {}
    assert "uzp_probe_plugin" not in sys.modules
    (log,) = (tmp_path / "work").rglob("hooks.log")
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines[-2:] == ["uzp_probe_startup.close_plugin", "uzp_probe_plugin.close_plugin"]
    assert not sentinel.exists() and os.environ[HOOK_LOG] == str(sentinel)
    assert plugins.path == [] and not [p for p in sys.path if "plugin-roots" in str(p)]


def watched_setter(world: Any, monkeypatch: pytest.MonkeyPatch, broken: list[bool]) -> list[Any]:
    """The fake's throttling setter, logging each period; while `broken[0]`, setting the period
    back to the fake's 1 s raises."""
    state = world.modules[EVENT].TextureStateEvent
    setter, periods = state.set_cache_key_invalidation_throttling_period, []

    def set_period(period: datetime.timedelta) -> None:
        periods.append(period)
        if broken[0] and period == datetime.timedelta(seconds=1):
            raise RuntimeError("the period could not be set")
        setter(period)

    monkeypatch.setattr(state, "set_cache_key_invalidation_throttling_period", set_period)
    return periods


def test_a_throttling_getter_that_raises_changes_nothing(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, session = fake_session(probe_fake, fake)
    periods = watched_setter(world, monkeypatch, [False])

    def unreadable() -> datetime.timedelta:
        raise RuntimeError("the period is unreadable")

    state = world.modules[EVENT].TextureStateEvent
    monkeypatch.setattr(state, "cache_key_invalidation_throttling_period", unreadable)
    with pytest.raises(RecorderError, match="could not be read before setting it"):
        attempt_recording(session, load_json(probe_path("p22b-host-events")), tmp_path)
    assert periods == [] and world.throttling == datetime.timedelta(seconds=1)
    assert published(tmp_path) == []


def test_a_failed_disconnect_still_restores_the_throttling_period(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, session = fake_session(probe_fake, fake)
    finishing = [False]
    call_before = session.call

    def call(operation: str, **args: Any) -> Any:
        finishing[0] = finishing[0] or operation == "probe_finish"
        return call_before(operation, **args)

    dispatcher = world.modules[EVENT].DISPATCHER
    disconnect_before = dispatcher.disconnect

    def disconnect(event_cls: type, callback: Any) -> None:
        if finishing[0]:
            raise RuntimeError("the dispatcher refused")
        disconnect_before(event_cls, callback)

    monkeypatch.setattr(session, "call", call)
    monkeypatch.setattr(dispatcher, "disconnect", disconnect)
    with pytest.raises(CleanupFailed, match="disconnect_strong/Event: RuntimeError"):
        attempt_recording(session, load_json(probe_path("p22b-host-events")), tmp_path)
    assert world.throttling == datetime.timedelta(seconds=1)  # restored after the failures
    assert published(tmp_path) == []


TRANSPORT_FAILURES: dict[str, Callable[[], Exception]] = {
    "os-error": lambda: OSError("the connection was reset"),
    "timeout": lambda: TimeoutError("no reply in 30 s"),
    "undecodable": lambda: json.JSONDecodeError("not JSON", "<html>", 0),
}


@pytest.mark.parametrize("failure", [*TRANSPORT_FAILURES, "malformed"])
@pytest.mark.parametrize("recording_fails", [False, True], ids=["recorded", "recording-failed"])
def test_a_transport_failure_at_the_first_cleanup_stage_still_runs_the_others(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    recording_fails: bool,
) -> None:
    """`probe_finish` never answers (the transport fails, or the reply is not the expected
    object): `close_project` and `probe_cleanup` still run, nothing is published, an earlier
    recording error stays the cause, and Painter keeps the snapshot to restore (SUP-028)."""
    world, session = fake_session(probe_fake, fake)
    call_before, calls = session.call, []

    def call(operation: str, **args: Any) -> Any:
        calls.append(operation)
        if operation != "probe_finish":
            return call_before(operation, **args)
        if failure == "malformed":
            return ["not", "an", "object"]
        raise TRANSPORT_FAILURES[failure]()

    if recording_fails:  # the host's save before r2 fails, after r1 set the period
        project = world.modules["substance_painter.project"]
        save_as_before = project.save_as

        def save_as(path: str, mode: Any) -> None:
            if path.endswith("probe.spp"):
                raise RuntimeError("disk full")
            save_as_before(path, mode)

        monkeypatch.setattr(project, "save_as", save_as)
    monkeypatch.setattr(session, "call", call)
    with pytest.raises(CleanupFailed, match="probe_finish: ") as refused:
        attempt_recording(session, load_json(probe_path("p22b-host-events")), tmp_path)
    finish = calls.index("probe_finish")
    assert calls[finish:] == ["probe_finish", "close_project", "probe_cleanup"]
    assert ("disk full" in str(refused.value.__cause__)) is recording_fails
    assert not world.project_open and published(tmp_path) == []
    assert world.throttling == datetime.timedelta(milliseconds=750)  # never restored
    finished = call_before("probe_finish")  # the snapshot was kept
    assert finished["throttling_restored"] == {"timedelta_ms": 1000.0}
    assert world.throttling == datetime.timedelta(seconds=1)


@pytest.mark.parametrize("recording_fails", [False, True], ids=["recorded", "recording-failed"])
def test_a_failed_restore_keeps_the_snapshot_and_publishes_nothing(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_fails: bool,
) -> None:
    world, session = fake_session(probe_fake, fake)
    broken = [True]
    watched_setter(world, monkeypatch, broken)
    if recording_fails:  # the host's save before r2 fails, after r1 set the period
        project = world.modules["substance_painter.project"]
        save_as_before = project.save_as

        def save_as(path: str, mode: Any) -> None:
            if path.endswith("probe.spp"):
                raise RuntimeError("disk full")
            save_as_before(path, mode)

        monkeypatch.setattr(project, "save_as", save_as)
    with pytest.raises(CleanupFailed) as refused:
        attempt_recording(session, load_json(probe_path("p22b-host-events")), tmp_path)
    message = str(refused.value)
    assert "probe_finish throttling: RuntimeError: the period could not be set" in message
    assert ("disk full" in message) is recording_fails
    assert ("disk full" in str(refused.value.__cause__)) is recording_fails
    assert world.throttling == datetime.timedelta(milliseconds=750)
    assert published(tmp_path) == []
    broken[0] = False  # the snapshot was kept: a later finish restores the period read first
    finished = session.call("probe_finish")
    assert finished["throttling_restored"] == {"timedelta_ms": 1000.0}
    assert finished["cleanup_failures"] == []
    assert world.throttling == datetime.timedelta(seconds=1)
