"""Painter's asynchronous host in the facade (task phase1.21_pyapi-dispatcher-lifecycle, items
3.2-3.7 and the behaviour of 2.1-2.9; decisions 109 and 110).

Each test runs a script in `uzp-pyapi-tests.exe` (conftest.py, `facade` fixture). The runner drains
the dispatcher after the script returned, so deliveries that outlive the script land before the
process ends; their handlers write to the test's folder. CPU only: every lane runs these. The
comparisons with Painter's private goldens are `test_pyapi_lifecycle_tier0.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.python.conftest import REPO_ROOT, Run

MESHES = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes"
GRIDS = (
    f"GRID2 = {(MESHES / 'grid2x2.obj').as_posix()!r}\n"
    f"GRID4 = {(MESHES / 'grid4x2.obj').as_posix()!r}\n"
)


def ok(report: dict[str, Any]) -> Any:
    """The `result` of a script that ran to its end."""
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"]


# Prepended to the scripts below: a log of every delivery with the state its handler reads.
LOG = """
import threading, time
from substance_painter import event as ev
MAIN = threading.get_ident()
LOG = []
HANDLERS = {}

def state():
    return [project.is_open(), project.is_in_edition_state(), project.is_busy()]

def listen(*names):
    for name in names:
        def handler(e, name=name):
            entry = [name, state(), threading.get_ident() == uzpainter.event.dispatcher_thread_id()]
            for field in ("busy", "file_path", "engine_computations_enabled", "shelf_name"):
                if hasattr(e, field):
                    entry.append(os.path.basename(getattr(e, field)) if field == "file_path"
                                 else getattr(e, field))
            LOG.append(entry)
        HANDLERS[name] = handler
        ev.DISPATCHER.connect(getattr(ev, name), handler)

LIFECYCLE = ["ProjectCreated", "ProjectOpened", "ProjectEditionEntered", "ProjectEditionLeft",
             "ProjectAboutToSave", "ProjectSaved", "ProjectAboutToClose", "ProjectClosed",
             "BusyStatusChanged"]
"""


# ── 2.2 The 27 documented classes and the dispatcher ───────────────────────────────────────────

CLASSES = """
import gc
names = ["Event", "GraphicalUserInterfaceStarted", "ExportTexturesAboutToStart",
         "ExportTexturesEnded", "ProjectOpened", "ProjectCreated", "ProjectAboutToClose",
         "ProjectClosed", "ProjectAboutToSave", "ProjectSaved", "ProjectEditionEntered",
         "ProjectEditionLeft", "BusyStatusChanged", "TextureStateEvent", "TextureStateEventAction",
         "ShelfCrawlingStarted", "ShelfCrawlingEnded", "BakingProcessAboutToStart",
         "BakingProcessProgress", "BakingProcessEnded", "LayerStacksModelDataChanged",
         "EngineComputationsStatusChanged", "CameraPropertiesChanged", "ReloadResourcesStarted",
         "ReloadResourcesEnded", "ReloadedResourceResult", "ReloadedResourceError"]
calls = []
for name in names:
    cls = getattr(ev, name)
    sp.event.DISPATCHER.connect(cls, print)
    sp.event.DISPATCHER.disconnect(cls, print)

class Owner:
    def __init__(self, tag):
        self.tag = tag
    def on(self, e):
        calls.append(self.tag)

weak, strong = Owner("weak"), Owner("strong")
ev.DISPATCHER.connect(ev.LayerStacksModelDataChanged, weak.on)
ev.DISPATCHER.connect_strong(ev.LayerStacksModelDataChanged, strong.on)
gone = lambda e: calls.append("collected")
ev.DISPATCHER.connect(ev.LayerStacksModelDataChanged, gone)
dropped = lambda e: calls.append("disconnected")
ev.DISPATCHER.connect(ev.LayerStacksModelDataChanged, dropped)
ev.DISPATCHER.disconnect(ev.LayerStacksModelDataChanged, dropped)
del gone, strong
gc.collect()
stack = create()
ls.insert_fill(top(stack))
first = sorted(calls)
del weak
gc.collect()
calls.clear()
ls.insert_fill(top(stack))
second = sorted(calls)

def boom(e):
    raise RuntimeError("handler error")
ev.DISPATCHER.connect(ev.LayerStacksModelDataChanged, boom)
calls.clear()
Keep = Owner("after the failing handler")
ev.DISPATCHER.connect(ev.LayerStacksModelDataChanged, Keep.on)
ls.insert_fill(top(stack))
result = {"count": len(names), "first": first, "second": second, "third": sorted(calls),
          "gui": raises(ev.GraphicalUserInterfaceStarted),
          "throttle": raises(ev.TextureStateEvent.cache_key_invalidation_throttling_period),
          "short": raises(ev.TextureStateEvent.set_cache_key_invalidation_throttling_period,
                          __import__("datetime").timedelta(milliseconds=100)),
          "busy_field": ev.BusyStatusChanged(True).busy,
          "save_field": ev.ProjectAboutToSave("x.spp").file_path}
"""


def test_the_27_classes_connect_weakly_strongly_and_disconnect(facade: Run) -> None:
    """Items 2.2 and 3.7: every documented class is connectable; `disconnect` stops delivery; a
    weakly connected handler whose owner is collected is not called; `connect_strong` keeps it
    alive; a failing handler does not stop the others."""
    report = facade(LOG + CLASSES)
    result = ok(report)
    assert result["count"] == 27
    assert result["first"] == ["strong", "weak"]
    assert result["second"] == ["strong"]
    assert result["third"] == ["after the failing handler", "strong"]
    assert "RuntimeError: handler error" in report["stderr"]
    assert result["gui"].startswith("UnsupportedInUzPainter")
    assert result["throttle"].startswith("NotYetSupported")
    assert result["short"].startswith("ValueError")
    assert result["busy_field"] is True
    assert result["save_field"] == "x.spp"


# ── 2.3, 2.4, 3.2 Lifecycle order and readiness ─────────────────────────────────────────────────

LIFECYCLE = """
listen(*LIFECYCLE)
before = {"edition": project.is_in_edition_state(), "busy": project.is_busy()}
create()
after_create = state()
project.save_as(WORK + "/lifecycle.spp", project.ProjectSaveMode.Full)
project.close()
project.open(WORK + "/lifecycle.spp")
project.save(project.ProjectSaveMode.Full)
project.close()
result = {"before": before, "after_create": after_create, "log": LOG}
"""

# (event, [is_open, in_edition, busy], on the dispatcher thread, argument): Tier 0
# `lifecycle-events`, both recordings of each cycle.
CREATE = [
    ["BusyStatusChanged", [False, False, True], True, True],
    ["BusyStatusChanged", [True, False, False], True, False],
    ["ProjectCreated", [True, False, False], True],
    ["ProjectEditionEntered", [True, True, False], True],
]
SAVE = [
    ["ProjectAboutToSave", [True, True, False], True, "lifecycle.spp"],
    ["ProjectSaved", [True, True, False], True],
]
CLOSE = [
    ["ProjectEditionLeft", [True, False, False], True],
    ["BusyStatusChanged", [True, False, True], True, True],
    ["ProjectAboutToClose", [True, False, True], True],
    ["ProjectClosed", [False, False, True], True],
    ["BusyStatusChanged", [False, False, False], True, False],
]
OPEN = [*CREATE[:2], ["ProjectOpened", [True, False, False], True], CREATE[3]]


def test_lifecycle_events_in_painter_order_with_the_states_handlers_read(facade: Run) -> None:
    """Items 2.3, 2.4 and 3.2: `is_in_edition_state()` is false until `ProjectEditionEntered`,
    `is_busy()` is true while loading, and every event arrives on the dispatcher thread in the
    recorded order, before the call returns."""
    result = ok(facade(LOG + LIFECYCLE))
    assert result["before"] == {"edition": False, "busy": False}
    assert result["after_create"] == [True, True, False]
    assert result["log"] == CREATE + SAVE + CLOSE + OPEN + SAVE + CLOSE


DISCARD = """
stack = create()
fill = ls.insert_fill(top(stack))
fill.set_name("saved")
project.save_as(WORK + "/discard.spp")
fill.set_name("not saved")
project.close()
project.open(WORK + "/discard.spp")
names = [n.get_name() for n in ls.get_root_layer_nodes(ts.get_active_stack())]
needs = project.needs_saving()
project.close()
result = {"names": names, "needs_saving": needs}
"""


def test_close_discards_what_was_not_saved(facade: Run) -> None:
    """Painter's discard-on-close (handed over by phase1.20): reopening shows the last save and
    nothing to save."""
    result = ok(facade(DISCARD))
    assert result["names"] == ["saved"]
    assert result["needs_saving"] is False


# ── 3.3 A handler outlives the script ───────────────────────────────────────────────────────────

OUTLIVES = """
listen("ProjectEditionEntered")
project.create(GRID2, settings=project.Settings(default_texture_resolution=256))
opened_on_dispatcher = LOG[-1][2]

def entered(e):
    with open(WORK + "/entered.json", "w") as out:
        json.dump({"thread": threading.get_ident(),
                   "returned": os.path.exists(WORK + "/returned"),
                   "edition": project.is_in_edition_state(),
                   "sets": [t.name() for t in ts.all_texture_sets()]}, out)

def loaded(status):
    with open(WORK + "/loaded.json", "w") as out:
        json.dump({"thread": threading.get_ident(), "status": status.name,
                   "returned": os.path.exists(WORK + "/returned")}, out)

ev.DISPATCHER.connect_strong(ev.ProjectEditionEntered, entered)
gate = threading.Event()
uzpainter.event.post(gate.wait)  # the dispatcher waits for the gate: the script returns first
threading.Timer(1.0, gate.set).start()
project.reload_mesh(GRID4, project.MeshReloadingSettings(import_cameras=False), loaded)
result = {"main": MAIN, "dispatcher": uzpainter.event.dispatcher_thread_id(),
          "opened_on_dispatcher": opened_on_dispatcher}
with open(WORK + "/returned", "w") as out:
    out.write("returned")
"""


def test_a_handler_still_receives_edition_entered_after_the_script_returned(
    facade: Run, tmp_path: Path
) -> None:
    """Item 3.3 (and 2.1, 2.7): the script connects a handler, starts a reload and returns; the
    handler and the reload callback still run, on the dispatcher thread, after it returned."""
    result = ok(facade(GRIDS + LOG + OUTLIVES))
    entered = json.loads((tmp_path / "entered.json").read_text(encoding="utf-8"))
    loaded = json.loads((tmp_path / "loaded.json").read_text(encoding="utf-8"))
    assert result["opened_on_dispatcher"] is True
    assert result["dispatcher"] not in (0, result["main"])
    assert entered["thread"] == loaded["thread"] == result["dispatcher"]
    assert entered["returned"] is True and loaded["returned"] is True
    assert entered["edition"] is True
    assert len(entered["sets"]) == 8
    assert loaded["status"] == "SUCCESS"


# ── 3.4 No Python under the document lock ───────────────────────────────────────────────────────

LOCK = """
stack = create()
fill = ls.insert_fill(top(stack))
fill.set_name("before")
project.save_as(WORK + "/lock.spp")
project.close()
SEEN = {}

def reads_and_edits(e):
    node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
    SEEN["name"] = node.get_name()
    SEEN["sets"] = [t.name() for t in ts.all_texture_sets()]
    with uzpainter.Transaction("handler"):  # waits for the document lock: free while we run
        uzpainter.layerstack.get_node_by_uid(node.uid()).set_name("set by the handler")
    SEEN["thread"] = threading.get_ident() == uzpainter.event.dispatcher_thread_id()

ev.DISPATCHER.connect(ev.ProjectEditionEntered, reads_and_edits)
project.open(WORK + "/lock.spp")
result = {"seen": SEEN,
          "after": [n.get_name() for n in ls.get_root_layer_nodes(ts.get_active_stack())]}
"""


def test_a_handler_calling_back_into_the_api_observes_the_committed_state(facade: Run) -> None:
    """Item 3.4: a handler that reads the stack and commits a native Transaction while the
    script's `open` waits for it does not deadlock and sees the committed state."""
    result = ok(facade(LOG + LOCK))
    assert result["seen"] == {"name": "before", "sets": ["uzp_plane"], "thread": True}
    assert result["after"] == ["set by the handler"]


# ── 2.5 execute_when_not_busy ───────────────────────────────────────────────────────────────────

WHEN_NOT_BUSY = """
listen("BusyStatusChanged", "ProjectEditionEntered", "ProjectEditionLeft")
stack = create()
LOG.clear()
CURRENT = ["idle call"]

def callback(tag):
    def run():
        LOG.append(["callback " + tag, state(), CURRENT[0],
                    threading.get_ident() == uzpainter.event.dispatcher_thread_id()])
    return run

project.execute_when_not_busy(callback("idle"))
CURRENT[0] = None

def queue_while_busy(e):
    if e.busy:  # busy now: the callback waits for BusyStatusChanged(False)
        project.execute_when_not_busy(callback("busy"))
ev.DISPATCHER.connect(ev.BusyStatusChanged, queue_while_busy)
done = threading.Event()
project.reload_mesh(PLANE, project.MeshReloadingSettings(), lambda status: done.set())
done.wait(60)
result = {"log": LOG}
"""


def test_execute_when_not_busy_runs_now_or_right_after_busy_clears(facade: Run) -> None:
    """Item 2.5: idle, the callback runs on the dispatcher thread before the call returns (Tier 0
    `phase1-execute-when-not-busy` s8); busy, it runs once `BusyStatusChanged(False)` is
    delivered and before `ProjectEditionEntered` (second recording, s10)."""
    result = ok(facade(LOG + WHEN_NOT_BUSY))
    assert result["log"] == [
        ["callback idle", [True, True, False], "idle call", True],
        ["ProjectEditionLeft", [True, False, False], True],
        ["BusyStatusChanged", [True, False, True], True, True],
        ["BusyStatusChanged", [True, False, False], True, False],
        ["callback busy", [True, False, False], None, True],
        ["ProjectEditionEntered", [True, True, False], True],
    ]


# ── 2.7, 3.6 Mesh reload callback ───────────────────────────────────────────────────────────────

RELOAD = """
create_settings = project.Settings(default_texture_resolution=256)
project.create(GRID2, settings=create_settings)
listen("BusyStatusChanged", "ProjectEditionEntered", "ProjectEditionLeft")
fill = ls.insert_fill(top(ts.get_active_stack()))
fill.set_name("kept")
statuses = []
done = threading.Event()

def loaded(status):
    statuses.append([status.name, status.value, state(),
                     threading.get_ident() == uzpainter.event.dispatcher_thread_id()])
    done.set()

project.reload_mesh(GRID4, project.MeshReloadingSettings(import_cameras=False), loaded)
done.wait(60)
success = list(LOG)
LOG.clear()
done.clear()
project.reload_mesh(WORK + "/absent.obj", project.MeshReloadingSettings(), loaded)
done.wait(60)
failure = list(LOG)
result = {"statuses": statuses, "success": success, "failure": failure,
          "sets": [t.name() for t in ts.all_texture_sets()],
          "kept": ls.get_node_by_uid(fill.uid()).get_name(),
          "mesh": os.path.basename(project.last_imported_mesh_path()),
          "bad_settings": raises(project.reload_mesh, GRID4, None, loaded),
          "gaps": raises(project.reload_mesh, GRID4,
                         project.MeshReloadingSettings(auto_unwrap_settings=object()), loaded)}
"""


def test_reload_mesh_calls_back_on_the_dispatcher_thread_for_success_and_failure(
    facade: Run,
) -> None:
    """Items 2.7 and 3.6: the callback receives `ReloadMeshStatus` on the dispatcher thread after
    the reload is committed, with Tier 0 `phase1-reload-mesh`'s events; a missing file gives
    only `ERROR`."""
    result = ok(facade(GRIDS + LOG + RELOAD))
    assert result["statuses"] == [
        ["SUCCESS", 0, [True, True, False], True],
        ["ERROR", 2, [True, True, False], True],
    ]
    assert result["success"] == [
        ["ProjectEditionLeft", [True, False, False], True],
        ["BusyStatusChanged", [True, False, True], True, True],
        ["BusyStatusChanged", [True, False, False], True, False],
        ["ProjectEditionEntered", [True, True, False], True],
    ]
    assert result["failure"] == []
    assert result["sets"] == ["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"]
    assert result["kept"] == "kept"
    assert result["mesh"] == "grid4x2.obj"
    assert result["bad_settings"].startswith("TypeError")
    assert result["gaps"].startswith("NotYetSupported")


# ── 2.6, 3.5 Engine computations ────────────────────────────────────────────────────────────────

ENGINE = """
listen("EngineComputationsStatusChanged", "BusyStatusChanged", "ExportTexturesAboutToStart",
       "ExportTexturesEnded")
stack = create()
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.Height}
fill.set_source(CT.Height, cm.Color(0.4, 0.4, 0.4, "Raw"))
LOG.clear()
CONFIG = {
    "exportShaderParams": False, "defaultExportPreset": "p",
    "exportPresets": [{"name": "p", "maps": [{"fileName": "$textureSet_height", "channels": [
        {"destChannel": "L", "srcChannel": "L", "srcMapType": "documentMap",
         "srcMapName": "height"}]}]}],
    "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "16",
                                         "dithering": False, "paddingAlgorithm": "infinite"}}],
    "exportPath": WORK + "/deferred",
    "exportList": [{"rootPath": "uzp_plane"}],
}
OUT = {}
BUSY_AT_ENABLE = []

def on_status(e):
    BUSY_AT_ENABLE.append([e.engine_computations_enabled, project.is_busy()])
ev.DISPATCHER.connect(ev.EngineComputationsStatusChanged, on_status)

sp.application.enable_engine_computations(False)
disabled = sp.application.engine_computations_status()
def export_now():
    OUT["result"] = sp.export.export_project_textures(CONFIG)
worker = threading.Thread(target=export_now)
worker.start()
deadline = time.monotonic() + 30
while not project.is_busy() and time.monotonic() < deadline:
    time.sleep(0.001)
time.sleep(0.5)
def pngs():
    folder = WORK + "/deferred"
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.endswith(".png"))

deferred = {"busy": project.is_busy(), "job": uzpainter.jobs.list()[-1].status, "files": pngs(),
            "save": raises(project.save_as, WORK + "/busy.spp")}
sp.application.enable_engine_computations(True)
worker.join(120)
with sp.application.disable_engine_computations():
    inside = sp.application.engine_computations_status()
result = {"disabled": disabled, "deferred": deferred, "busy_at_enable": BUSY_AT_ENABLE,
          "after": {"busy": project.is_busy(), "status": OUT["result"].status.name,
                    "files": pngs()},
          "inside": inside, "enabled": sp.application.engine_computations_status(),
          "log": [entry[0] + ("" if len(entry) < 4 else f"({entry[3]})") for entry in LOG]}
"""


def test_disabled_computations_defer_an_export_until_reenabled(facade: Run) -> None:
    """Items 2.6 and 3.5: with computations disabled an export request is deferred (its job stays
    queued, no file is written), `engine_computations_status` reports disabled, and re-enabling
    fires `EngineComputationsStatusChanged` with `is_busy()` true until the backlog drains."""
    result = ok(facade(LOG + ENGINE))
    assert result["disabled"] is False
    assert result["deferred"]["busy"] is True
    assert result["deferred"]["job"] == "queued"
    assert result["deferred"]["files"] == []
    assert result["deferred"]["save"].startswith("ProjectError")
    assert result["busy_at_enable"][:2] == [[False, False], [True, True]]
    assert result["after"] == {
        "busy": False,
        "status": "Success",
        "files": ["uzp_plane_height.png"],
    }
    assert result["inside"] is False and result["enabled"] is True
    assert result["log"] == [
        "EngineComputationsStatusChanged(False)",
        "BusyStatusChanged(True)",
        "ExportTexturesAboutToStart",
        "EngineComputationsStatusChanged(True)",
        "ExportTexturesEnded",
        "BusyStatusChanged(False)",
        "EngineComputationsStatusChanged(False)",
        "EngineComputationsStatusChanged(True)",
    ]


# ── 2.8 Resource reload and shelf crawling ──────────────────────────────────────────────────────

RESOURCES = """
import shutil
listen("LayerStacksModelDataChanged")
STARTED = []
ENDED = threading.Event()

def started(e):
    # Inside the delivery the reload runs, deterministically: a second one is refused.
    STARTED.append([type(e.filter).__name__, project.is_busy(),
                    resource.is_reload_modified_resources_running(),
                    resource.reload_modified_resources_async(resource.ProjectFilter())])

def ended(e):
    OUT.update(filter=type(e.filter).__name__,
               reloaded=[[r.old_resource_id.version, r.new_resource_id.version]
                         for r in e.reloaded_resources],
               errors=[r.error_msg for r in e.resource_errors])
    ENDED.set()

OUT = {}
ev.DISPATCHER.connect(ev.ReloadResourcesStarted, started)
ev.DISPATCHER.connect(ev.ReloadResourcesEnded, ended)
stack = create()
image = WORK + "/checker.png"
shutil.copyfile(IMAGES + "/checker-16.png", image)
res = resource.import_project_resource(image, resource.Usage.TEXTURE)
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor}
fill.set_source(CT.BaseColor, res.identifier())
bound = fill.get_source(CT.BaseColor).resource_id.version
shutil.copyfile(IMAGES + "/ao-white.png", image)
first = resource.reload_modified_resources_async(resource.ResourcesUsedByProjectFilter())
ENDED.wait(60)
used = dict(OUT)
OUT.clear(); ENDED.clear()
resource.reload_modified_resources_async(resource.ProjectFilter())
ENDED.wait(60)
nothing = dict(OUT)
result = {"started": STARTED, "first": first, "used": used, "nothing": nothing, "bound": bound,
          "still_bound": fill.get_source(CT.BaseColor).resource_id.version,
          "versions": sorted(r.version for r in resource.list_project_resources()
                             if r.name == "checker"),
          "bad_filter": raises(resource.reload_modified_resources_async, object()),
          "structure_events": [entry[0] for entry in LOG]}

CRAWL = []
CRAWLED = threading.Event()
def crawl(e):
    CRAWL.append([type(e).__name__, e.shelf_name, resource.Shelf(e.shelf_name).is_crawling()])
    if type(e).__name__ == "ShelfCrawlingEnded":
        CRAWLED.set()
ev.DISPATCHER.connect(ev.ShelfCrawlingStarted, crawl)
ev.DISPATCHER.connect(ev.ShelfCrawlingEnded, crawl)
shelf = resource.Shelves.add("uzp-shelf", IMAGES)
shelf.refresh()
CRAWLED.wait(60)
result["crawl"] = CRAWL
result["shelves"] = {"exists": resource.Shelves.exists("uzp-shelf"),
                     "all": [s.name() for s in resource.Shelves.all()],
                     "path": os.path.samefile(shelf.path(), IMAGES),
                     "bad_name": raises(resource.Shelves.add, "Bad Name", IMAGES),
                     "application": raises(resource.Shelves.application_shelf),
                     "resources": raises(shelf.resources),
                     "remove_open": raises(resource.Shelves.remove, "uzp-shelf")}
"""


def test_resource_reload_and_shelf_crawling_events(facade: Run) -> None:
    """Item 2.8: `ReloadResourcesStarted` before the call returns, `ReloadResourcesEnded` with the
    new version once reloaded and the binding unchanged (Tier 0 `phase1-reload-resources`, first
    recording); a second reload while one runs returns False; script-defined shelves crawl between
    `ShelfCrawlingStarted` and `ShelfCrawlingEnded`."""
    result = ok(facade(LOG + RESOURCES))
    assert result["started"] == [
        ["ResourcesUsedByProjectFilter", False, True, False],
        ["ProjectFilter", False, True, False],
    ]
    assert result["first"] is True
    old, new = result["used"]["reloaded"][0]
    assert result["used"]["filter"] == "ResourcesUsedByProjectFilter"
    assert old == result["bound"] and new != old and result["used"]["errors"] == []
    assert result["nothing"] == {"filter": "ProjectFilter", "reloaded": [], "errors": []}
    assert result["still_bound"] == result["bound"]
    assert result["versions"] == sorted([old, new])
    assert result["bad_filter"].startswith("ValueError")
    assert result["structure_events"] == ["LayerStacksModelDataChanged"]
    assert result["crawl"] == [
        ["ShelfCrawlingStarted", "uzp-shelf", True],
        ["ShelfCrawlingEnded", "uzp-shelf", False],
    ]
    shelves = result["shelves"]
    assert shelves["exists"] is True and shelves["all"] == ["uzp-shelf"] and shelves["path"]
    assert shelves["bad_name"].startswith("ValueError")
    assert shelves["application"].startswith("NotYetSupported")
    assert shelves["resources"].startswith("NotYetSupported")
    assert shelves["remove_open"].startswith("ProjectError")


# ── 2.9 async_utils, the create gaps and the native dispatcher ──────────────────────────────────

MISC = """
stop = sp.async_utils.StopSource()
before = stop.stop_requested()
requested = stop.request_stop()
order = []
for i in range(5):
    uzpainter.event.post(lambda i=i: order.append(i))
uzpainter.event.flush()
result = {"stop": [before, requested, stop.stop_requested()], "order": order,
          "mesh_maps": raises(project.create, PLANE,
                              mesh_map_file_paths=[IMAGES + "/ao-white.png"]),
          "template": raises(project.create, PLANE, template_file_path="x.spt"),
          "export_path": raises(project.create, PLANE,
                                settings=project.Settings(export_path=WORK)),
          "no_project_edition": project.is_in_edition_state()}
"""


def test_stop_source_create_gaps_and_dispatcher_order(facade: Run) -> None:
    """Item 2.9 and the `create` arguments phase1.20 handed over: `StopSource`, the release gaps
    named with their recordings, and the native dispatcher's queue order."""
    result = ok(facade(MISC))
    assert result["stop"] == [False, True, True]
    assert result["order"] == [0, 1, 2, 3, 4]
    assert "P21-A" in result["mesh_maps"] and result["mesh_maps"].startswith("NotYetSupported")
    assert result["template"].startswith("NotYetSupported")
    assert "P21-B" in result["export_path"]
    assert result["no_project_edition"] is False
