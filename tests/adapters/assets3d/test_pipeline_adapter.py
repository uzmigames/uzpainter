"""The Assets3D pipeline adapter over `UzPainter.exe` (task phase1.23 items 3.1-3.6; decision 113).

The three pipeline scripts run byte-unchanged (their pins from the committed R9 request manifest)
through `adapters/assets3d/layer_stack.py` on the wand v1 inputs (`wand.py`). Local run on the
owner's machine (decision 028): it needs the UzmiGames asset repository at `E:\\UzmiGames\\Assets3D`
(or `UZP_TEST_ASSETS3D`) and `zig` for a fresh `zig build painter`. CPU only, except the
pipeline's `capture`, which renders `painter_viewport` on DX12 (skipped under `UZP_NO_GPU=1`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import textwrap
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from adapters.assets3d import client
from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT, Wand

SEMANTICS = REPO_ROOT / "parity" / "semantics" / "export-processing.json"
PROBE_IMAGE = REPO_ROOT / "parity" / "fixtures" / "api-probes" / "checker-16.png"
# Assets3D manifest `$defs/path` (the receipt schema's copy).
A3D_PATH = re.compile(r"^(?!/)(?!.*[\\:])(?!.*(?:^|/)\.\.?(/|$))[^/]+(?:/[^/]+)*$")

pytestmark = pytest.mark.skipif(
    not (ASSETS3D / "AGENTS.md").is_file(),
    reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
)


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "UzPainter.exe"


@pytest.fixture
def wand(painter: Path, tmp_path: Path) -> Wand:
    return Wand(painter, tmp_path)


@pytest.fixture
def created(wand: Wand) -> Wand:
    call = wand.create()
    assert call.status == 0, call.stdout + call.stderr
    return wand


@pytest.fixture
def adapter_env(wand: Wand, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The wand's environment for in-process client calls."""
    for key in ("UZPAINTER_EXE", "UZP_ASSETS3D_SESSION", "UZP_ASSETS3D_ROOT"):
        monkeypatch.setenv(key, wand.env[key])
    monkeypatch.delenv("UZP_ASSETS3D_OPEN_REDIRECTS", raising=False)
    yield


def production_state(wand: Wand) -> dict[str, Any]:
    """What the wand's pinned production arguments name in Assets3D: the run must leave it as it
    is."""
    found: dict[str, Any] = {}
    for step in (wand.job.create, wand.job.export):
        arguments = step.arguments or {}
        for key in ("dst", "out"):
            if key in arguments:
                path = Path(arguments[key])
                found[key] = (
                    sorted((p.name, p.stat().st_mtime_ns) for p in path.iterdir())
                    if path.is_dir()
                    else (path.stat().st_mtime_ns if path.exists() else None)
                )
    return found


def export_gaps() -> list[str]:
    """The export-processing entries the wand's five-map export needs that are still gaps: its
    BaseColor at PNG 16 (decision 126) and `infinite` padding on its UV islands (phase1.25 item
    2.7)."""
    entries = json.loads(SEMANTICS.read_text(encoding="utf-8"))["entries"]
    needed = {"srgb8-material-channels", "padding-islands"}
    return [e["entry_id"] for e in entries if e["entry_id"] in needed and e["status"] == "gap"]


def revision(wand: Wand) -> Any:
    return wand.probe("revision", "import uzpainter\nresult = uzpainter.project.revision()\n")


ROOTS = """
import substance_painter.layerstack as ls, substance_painter.textureset as ts
import substance_painter.resource as rs
stack = ts.get_active_stack()
def tree(node):
    out = {"name": node.get_name(), "uid": node.uid(), "visible": node.is_visible()}
    if hasattr(node, "sub_layers"):
        out["children"] = [tree(n) for n in node.sub_layers()]
    return out
result = {"roots": [tree(n) for n in ls.get_root_layer_nodes(stack)],
          "resources": sorted(r.name for r in rs.list_project_resources())}
"""


def roots(wand: Wand) -> dict[str, Any]:
    found: dict[str, Any] = wand.probe("roots", ROOTS)
    return found


def count(nodes: list[dict[str, Any]]) -> int:
    return sum(1 + count(n.get("children", [])) for n in nodes)


# ── 3.1 The wand v1 fixture ─────────────────────────────────────────────────────────────────────


def test_wand_create_sync_and_export_run_unchanged(wand: Wand) -> None:
    """3.1: create and sync return their JSON results through the adapter; export runs its pinned
    bytes and returns its result, or, while a processing it needs is a gap (`export_gaps`: owner
    phase1.25_pilot-wand items 2.6 and 2.7), the export's explicit refusal."""
    before = production_state(wand)
    create = wand.create()
    assert create.status == 0, create.stdout + create.stderr
    created = create.document()["data"]
    dst = wand.argument("create", "dst")
    assert Path(created["file"]).resolve() == dst.resolve()
    assert created["sets"] == ["11-Varinha-Madeira"]
    assert sorted(created["maps"]) == ["AO", "Normal"]
    assert created["needs_saving"] is False
    assert created["res"] == "Resolution(2048, 2048)"

    sync = wand.sync()
    assert sync.status == 0, sync.stdout + sync.stderr
    synced = sync.document("SYNC_DONE")
    assert Path(synced["project"]).resolve() == dst.resolve()
    assert synced["layers"] == 13
    masks = sorted(PurePosixPath(name).stem for name in wand.job.sync.args["mask_files"])
    assert len(masks) == 14 and sorted(synced["imported"]) == masks
    assert synced["hidden"] == []
    state = json.loads(wand.state.read_text(encoding="utf-8"))
    assert sorted(state) == sorted(synced["imported"])

    export = wand.export()
    out = wand.argument("export", "out")
    if export_gaps():
        assert export.status == 1
        assert "NotYetSupported" in export.stderr and "R-090" in export.stderr, export.stderr
        if export_gaps() == ["padding-islands"]:
            assert "do not cover the whole tile" in export.stderr, export.stderr
        assert not out.exists() or not any(out.iterdir())  # refused before writing
    else:
        assert export.status == 0, export.stdout + export.stderr
        exported = export.document()
        assert exported["status"] == "ExportStatus.Success"
        assert len(next(iter(exported["files"].values()))) == 5
    assert production_state(wand) == before  # nothing written under the Assets3D root


def test_a_changed_script_is_refused_before_anything_runs(wand: Wand, tmp_path: Path) -> None:
    """2.5: a pinned script whose bytes differ is refused; nothing reaches UzPainter."""
    changed = tmp_path / "painter_create.py"
    changed.write_bytes(wand.script("painter-create-py").read_bytes() + b"\n")
    pin = wand.job.inputs["painter-create-py"].sha256
    pins = [*wand.pins(), "--pin", f"{changed}={pin}"]
    call = wand.call("run", str(changed), pins=pins)
    assert call.status == 1
    refusal = json.loads(call.stdout)
    assert refusal["success"] is False and refusal["error"]["type"] == "PinMismatch"
    assert not wand.session.exists()


# ── 3.2 Structured failures ─────────────────────────────────────────────────────────────────────


def test_a_raising_script_is_a_structured_failure(created: Wand, adapter_env: None) -> None:
    """3.2: the reply carries the error and its traceback; the exit status is 1, and the layer
    stack script's own transport turns it into its usual failure (after its route guard's probe,
    which needs the saved project `created` leaves open)."""
    reply, status = client.execute_python("print('before')\nx = 1\nraise ValueError('boom')\n")
    assert status == client.FAILED
    assert reply["success"] is False and reply["data"] is None
    assert reply["error"]["type"] == "ValueError" and reply["error"]["message"] == "boom"
    assert 'File "<uzpainter-assets3d-adapter>", line 3' in reply["error"]["traceback"]
    assert "raise ValueError('boom')" in reply["error"]["traceback"]
    assert reply["stdout"] == "before\n"

    path = created.work / "raises.py"
    path.write_text("raise RuntimeError('from the script')\n", encoding="utf-8")
    call = created.run_file(path)
    assert call.status == 1
    assert "Painter MCP call failed" in call.stderr and "from the script" in call.stderr


def test_a_result_is_returned_as_the_bridge_returns_it(adapter_env: None) -> None:
    """3.2: `result` as JSON with both streams; a non-JSON value as its str(), as the bridge."""
    reply, status = client.execute_python(
        "import sys\nprint('out')\nprint('err', file=sys.stderr)\n"
        "result = {'n': 1, 'path': __import__('pathlib').PurePosixPath('a/b'), 'params': params}\n"
    )
    assert status == client.OK
    assert reply["success"] is True
    assert reply["data"] == {"n": 1, "path": "a/b", "params": {}}
    assert (reply["stdout"], reply["stderr"]) == ("out\n", "err\n")
    assert reply["session"] is None and reply["exports"] == [] and reply["redirects"] == {}


# ── 3.3 Shim isolation ──────────────────────────────────────────────────────────────────────────


def test_the_shim_is_visible_to_adapter_run_scripts_only(
    created: Wand, painter: Path, tmp_path: Path
) -> None:
    """3.3: `_substance_painter` imports inside an adapter-run script; a plain `run` script and
    the facade expose no such symbol, and the capability manifest names none."""
    inside = created.probe(
        "shim",
        "import _substance_painter.display as display\n"
        "result = {'name': display.__name__, 'callable': callable(display.save_viewport)}\n",
    )
    assert inside == {"name": "_substance_painter.display", "callable": True}

    plain = tmp_path / "plain.py"
    plain.write_text(
        textwrap.dedent(
            """
            import importlib, pkgutil, sys
            import substance_painter
            for info in pkgutil.iter_modules(substance_painter.__path__):
                importlib.import_module("substance_painter." + info.name)
            try:
                import _substance_painter
                found = True
            except ModuleNotFoundError:
                found = False
            facade = sorted(
                name for name, module in sys.modules.items()
                if name.startswith(("substance_painter", "uzpainter_facade"))
                for attr in dir(module) if "_substance_painter" in attr
            )
            result = {"importable": found, "facade": facade,
                      "loaded": sorted(m for m in sys.modules if m.startswith("_substance"))}
            """
        ),
        encoding="utf-8",
    )
    process = subprocess.run(
        [str(painter), "run", str(plain)], capture_output=True, text=True, timeout=600, check=False
    )
    report = client.report_line(process.stdout)
    assert process.returncode == 0 and report is not None, process.stdout + process.stderr
    assert report["result"] == {"importable": False, "facade": [], "loaded": []}
    manifest = json.loads((painter.parent / "capabilities.json").read_text(encoding="utf-8"))
    assert not [e for e in manifest["entries"] if e["symbol"].startswith("_substance_painter")]


# ── 3.4 Missing capabilities in Phase 1; the capture shim (phase2.2 item 3.6) ───────────────────


@pytest.mark.skipif(
    os.environ.get("UZP_NO_GPU") == "1",
    reason="UZP_NO_GPU=1: painter_viewport needs a DX12 adapter",
)
def test_capture_on_the_ocio_wand_runs_lit_by_the_default_environment(created: Wand) -> None:
    """phase2.2 3.6 (decisions 148, 207, 212): `capture` reaches the shim, which calls
    `uzpainter.render.capture(mode="painter_viewport")`. `painter_create.py` sets `OCIO` to
    Painter's substance config before `create`, so the wand project is in the pinned display
    configuration (decisions 038, 134). A created project names no environment, so the capture is
    lit by the installation's default, the shipped `studio-small-09.exr`, and its receipt says
    so: a non-parity preview, never parity evidence. It reads the committed revision and changes
    nothing. (The Legacy refusal is `tests/preview/test_preview_capture.py`'s.)"""
    before = revision(created)
    out = created.work / "capture.png"
    call = created.call("capture", "--out", str(out), "--size", "640", "480")
    assert call.status == 0, call.stdout + call.stderr
    assert "CAPTURE_DONE" in call.stdout and out.is_file() and out.with_suffix(".exr").is_file()
    receipt = json.loads(out.with_suffix(".receipt.json").read_text(encoding="utf-8"))
    provenance = REPO_ROOT / "assets" / "environments" / "studio-small-09.provenance.json"
    shipped = json.loads(provenance.read_text(encoding="utf-8"))["sha256"]
    assert receipt["mode"] == "painter_viewport" and receipt["size"] == [640, 480]
    assert receipt["environment"]["sha256"] == shipped
    assert receipt["environment"]["default"] is True
    assert receipt["revision"] == before
    assert revision(created) == before


# The pipeline's `capture` subcommand code (CAPTURE_CODE of painter_layer_stack.py), after a
# native open of the OCIO fixture in the same call: the facade, and so the adapter's session
# restore, refuses an OCIO project until phase1.15 (decision 148), so the pipeline's own
# subcommand cannot be run on one; this runs the call it makes through the shim.
SHIM_CAPTURE = """
import os
import uzpainter
uzpainter.project.open(__BUNDLE__)
import _substance_painter.display as display
path = __PATH__
if os.path.exists(path): os.remove(path)
display.save_viewport(path, 64, 48, False)
result = {"saved": os.path.exists(path), "path": path, "revision": uzpainter.project.revision()}
"""


def test_the_shim_writes_the_viewport_under_uzpainter_run(
    painter: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """phase2.2 3.6 (decision 148): through the runner under `UzPainter.exe run`, on an OCIO
    project, `_substance_painter.display.save_viewport(path, w, h, _)` writes the committed
    revision's `painter_viewport` capture at the size asked, with its receipt."""
    from tests.preview.conftest import ocio_bundle

    bundle = ocio_bundle(painter, tmp_path / "fixture")
    (tmp_path / "assets").mkdir()
    monkeypatch.setenv("UZPAINTER_EXE", str(painter))
    monkeypatch.setenv("UZP_ASSETS3D_SESSION", str(tmp_path / "session.json"))
    monkeypatch.setenv("UZP_ASSETS3D_ROOT", str(tmp_path / "assets"))
    monkeypatch.delenv("UZP_ASSETS3D_OPEN_REDIRECTS", raising=False)
    out = tmp_path / "shots" / "capture.png"
    out.parent.mkdir()
    code = SHIM_CAPTURE.replace("__BUNDLE__", repr(str(bundle))).replace("__PATH__", repr(str(out)))
    reply, status = client.execute_python(code)
    assert status == client.OK, reply
    assert reply["data"]["saved"] is True and reply["data"]["path"] == str(out)
    receipt = json.loads(out.with_suffix(".receipt.json").read_text(encoding="utf-8"))
    assert receipt["mode"] == "painter_viewport" and receipt["size"] == [64, 48]
    assert receipt["revision"] == reply["data"]["revision"] and receipt["backend"] == "dx12"
    data = out.read_bytes()
    assert hashlib.sha256(data).hexdigest() == receipt["hashes"]["png"]
    assert data[16:24] == (64).to_bytes(4, "big") + (48).to_bytes(4, "big")  # IHDR size


def test_smart_is_refused_naming_smart_presets(created: Wand) -> None:
    """3.4: `smart` is refused before any call reaches UzPainter, naming the smart presets of
    phase3.6; the project's revision and the session are unchanged."""
    before = revision(created)
    session = created.session.read_text(encoding="utf-8")
    config = created.work / "smart.json"
    config.write_text(
        json.dumps(
            {
                "layers": [
                    {
                        "name": "dirt",
                        "color": [90, 70, 50],
                        "mask": {"type": "smart_mask", "name": "Dirt"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    call = created.call("smart", "--config", str(config))
    assert call.status == 1
    refusal = json.loads(call.stdout)
    assert refusal["error"]["type"] == "NotYetSupported"
    assert refusal["error"]["capability"] == "smart presets"
    assert refusal["error"]["owner"] == "phase3.6_smart-presets-projections"
    assert {m["symbol"] for m in refusal["error"]["missing"]} == {
        "substance_painter.layerstack.insert_smart_mask",
        "substance_painter.resource.search",
    }
    assert created.session.read_text(encoding="utf-8") == session
    assert revision(created) == before


# ── 3.5 LAY-06 through the scripts ──────────────────────────────────────────────────────────────


def test_sync_repeated_creates_no_duplicate_and_ids_survive_reopen(created: Wand) -> None:
    """3.5: the layer uids `sync` reports read back unchanged in the next call (a fresh process
    reopening the saved project) and after a save; repeating `sync` leaves one group of the
    title with the same 13 layers and reuses every imported image."""
    first = created.sync()
    assert first.status == 0, first.stdout + first.stderr
    title = json.loads(created.staged["wand-stack"].read_text(encoding="utf-8"))["title"]
    data = json.loads(created.state.read_text(encoding="utf-8"))
    tree = roots(created)
    group = next(n for n in tree["roots"] if n["name"] == title)
    assert count(group["children"]) == 13 + 4

    created.probe(
        "save", "import substance_painter.project as p\np.save()\nresult = p.needs_saving()\n"
    )
    after_save = roots(created)
    assert after_save["roots"] == tree["roots"]

    second = created.sync()
    assert second.status == 0, second.stdout + second.stderr
    synced = second.document("SYNC_DONE")
    assert synced["imported"] == [] and synced["layers"] == 13
    assert json.loads(created.state.read_text(encoding="utf-8")) == data
    again = roots(created)
    titled = [n for n in again["roots"] if n["name"] == title]
    assert len(titled) == 1 and count(titled[0]["children"]) == 13 + 4
    assert titled[0]["uid"] != group["uid"]  # rebuilt, the earlier group deleted
    assert again["resources"] == tree["resources"]  # no image imported twice


# ── 3.6 LAY-07 through sync ─────────────────────────────────────────────────────────────────────


UNRELATED = f"""
import substance_painter.layerstack as ls, substance_painter.textureset as ts
import substance_painter.resource as rs
CT = ts.ChannelType
stack = ts.get_active_stack()
def group(name):
    g = ls.insert_group(ls.InsertPosition.from_textureset_stack(stack)); g.set_name(name)
    f = ls.insert_fill(ls.InsertPosition.inside_node(g, ls.NodeStack.Substack))
    f.set_name(name + " fill")
    return g, f
metal, _ = group("metal")
extra, fill = group("extra")
r = rs.import_project_resource({str(PROBE_IMAGE)!r}, rs.Usage.TEXTURE, "extra_only", "probe")
fill.active_channels = {{CT.BaseColor}}
fill.set_source(CT.BaseColor, r.identifier())
result = {{"extra_fill": fill.uid()}}
"""

SOURCE = """
import substance_painter.layerstack as ls, substance_painter.textureset as ts
node = ls.get_node_by_uid(__UID__)
result = node.get_source(ts.ChannelType.BaseColor).resource_id.name
"""

SHOW = """
import substance_painter.layerstack as ls, substance_painter.textureset as ts
for n in ls.get_root_layer_nodes(ts.get_active_stack()):
    n.set_visible(True)
result = None
"""


def test_sync_rebuilds_only_its_group_and_keeps_unrelated_content(created: Wand) -> None:
    """3.6: `sync` rebuilds only the stack's group; `metal` and `extra` are hidden, not deleted,
    with their content and the resource only `extra` uses; `--keep-visible` keeps `metal` shown."""
    first = created.sync()
    assert first.status == 0, first.stdout + first.stderr
    fill = created.probe("unrelated", UNRELATED)["extra_fill"]
    title = json.loads(created.staged["wand-stack"].read_text(encoding="utf-8"))["title"]
    before = {n["name"]: n for n in roots(created)["roots"]}
    assert {"metal", "extra", title} <= set(before)

    second = created.sync()
    assert second.status == 0, second.stdout + second.stderr
    assert sorted(second.document("SYNC_DONE")["hidden"]) == ["extra", "metal"]
    after = roots(created)
    by_name = {n["name"]: n for n in after["roots"]}
    for name in ("metal", "extra"):
        assert by_name[name]["visible"] is False
        assert {**by_name[name], "visible": True} == before[name]  # same nodes, same content
    assert by_name[title]["uid"] != before[title]["uid"] and by_name[title]["visible"] is True
    assert "extra_only" in after["resources"]
    assert created.probe("source", SOURCE.replace("__UID__", str(fill))) == "extra_only"

    created.probe("show", SHOW)
    kept = created.sync("--keep-visible", "met")
    assert kept.status == 0, kept.stdout + kept.stderr
    assert kept.document("SYNC_DONE")["hidden"] == ["extra"]
    shown = {n["name"]: n["visible"] for n in roots(created)["roots"]}
    assert shown["metal"] is True and shown["extra"] is False


# ── The native composite builds the script's document (decision 115) ─────────────────────────


NATIVE_SYNC = """
import uzpainter
nls, nts, nsrc = uzpainter.layerstack, uzpainter.textureset, uzpainter.source
stack = nts.get_active_stack()
channels = sorted(stack.all_channels(), key=lambda c: c.name)


def source(node, channel):
    s = node.get_source(channel)
    if s is None:
        return None
    if isinstance(s, nsrc.SourceBitmap):
        return ["bitmap", s.resource_id().url().rsplit("version=", 1)[1], s.get_color_space()]
    c = s.get_color()
    return ["uniform", list(c.value_raw), c.color_space]


def projection(node):
    p = node.get_projection_parameters()
    t = p.uv_transformation
    return [node.get_projection_mode().name, p.filtering_mode.name, p.uv_wrapping_mode.name,
            t.scale_mode.name, list(t.scale), t.rotation, list(t.offset)]


def document(node):
    mask = node.is_in_mask_stack()
    out = {"name": node.get_name(), "type": type(node).__name__, "visible": node.is_visible()}
    if node.has_blending():
        out["blending"] = (
            [node.get_blending_mode().name, node.get_opacity()] if mask else
            {c.name: [node.get_blending_mode(c).name, node.get_opacity(c)] for c in channels})
    if isinstance(node, (nls.FillLayerNode, nls.FillEffectNode)):
        out["projection"] = projection(node)
        if mask:
            out["source"] = source(node, None)
        else:
            out["active"] = sorted(c.name for c in node.active_channels)
            out["sources"] = {c.name: source(node, c) for c in channels}
    if isinstance(node, nls.LayerNode):
        out["content"] = [document(e) for e in node.content_effects()]
        out["mask"] = ([node.get_mask_background().name, node.is_mask_enabled(),
                        [document(e) for e in node.mask_effects()]] if node.has_mask() else None)
    if isinstance(node, nls.GroupLayerNode):
        out["children"] = [document(x) for x in node.sub_layers()]
    return out


def titled():
    return [n for n in nls.get_root_layer_nodes(stack) if n.get_name() == __TITLE__]


(script_root,) = titled()
script = document(script_root)
r = nls.sync_stack(__STACK__, __MASKS__)
(native_root,) = titled()
result = {"script": script, "native": document(native_root),
          "rebuilt": native_root.uid() != script_root.uid(), "status": r.status}
"""


def test_native_sync_stack_builds_the_document_the_script_builds(created: Wand) -> None:
    """Decisions 115, 207 and 212: on the OCIO wand (`painter_create.py` sets `OCIO`),
    `uzpainter.layerstack.sync_stack` on the wand's stack JSON builds the same group as
    `painter_layer_stack.py sync` through the facade: the tree, every node's blending on every
    channel (Height LinearDodge from Painter's insert defaults), opacity, active channels, every
    source (uniform colours with their space, each sRGB base colour as Painter's measured OCIO
    decode from the one table both read, decision 202; bitmaps by content and colour space),
    projections and masks. Only the uids differ (a rebuild) and the names the two give the
    imported images (bitmaps are compared by content)."""
    first = created.sync()
    assert first.status == 0, first.stdout + first.stderr
    stack_json = created.staged["wand-stack"]
    title = json.loads(stack_json.read_text(encoding="utf-8"))["title"]
    masks = created.staged[created.job.sync.args["masks"][0]].parent
    body = (
        NATIVE_SYNC.replace("__TITLE__", repr(title))
        .replace("__STACK__", repr(str(stack_json)))
        .replace("__MASKS__", repr(str(masks)))
    )
    result = created.probe("native-sync", body)
    assert result["status"] == "committed" and result["rebuilt"] is True
    assert result["native"] == result["script"]
    heights = {
        layer["name"]: layer["blending"]["Height"][0]
        for group in result["script"]["children"]
        for layer in group["children"]
    }
    assert set(heights.values()) == {"LinearDodge"}


# ── The consumers' route and the manifest (decisions 097, 113) ──────────────────────────────────


EXPORT = """
import os
import substance_painter.export as ex, substance_painter.textureset as ts
cfg = {"exportShaderParams": False, "exportPath": __OUT__, "defaultExportPreset": "p",
       "exportPresets": [{"name": "p", "maps": [{"fileName": "probe_Roughness", "channels": [
           {"destChannel": "L", "srcChannel": "L", "srcMapType": "documentMap",
            "srcMapName": "roughness"}]}]}],
       "exportList": [{"rootPath": s.name()} for s in ts.all_texture_sets()],
       "exportParameters": [{"parameters": {
           "fileFormat": "png", "bitDepth": "8", "dithering": False,
           "paddingAlgorithm": "passthrough"}}]}
r = ex.export_project_textures(cfg)
result = {"status": str(r.status), "files": {str(k): v for k, v in r.textures.items()}}
"""


def test_exports_are_verified_and_their_manifest_rebased(
    created: Wand, adapter_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fixed-name copy the consumers read is verified against its receipt in the run, and
    the receipt's manifest files are named under the Assets3D root (here the mirror)."""
    out = created.root / "_tmp" / "claude" / "varinha11-v1" / "probe-export"
    reply, status = client.execute_python(EXPORT.replace("__OUT__", repr(str(out))))
    assert status == client.OK, reply["error"]
    (export,) = reply["exports"]
    assert [c["verified"] for c in export["fixed_names"]] == [True]
    assert Path(export["fixed_names"][0]["directory"]).resolve() == out.resolve()
    files = export["manifest"]["manifest_files"]
    assert all(A3D_PATH.match(f["path"]) for f in files.values())
    generation = f"_tmp/claude/varinha11-v1/probe-export/generations/{export['generation']}"
    assert files["export-plan"]["path"] == f"{generation}/plan.json"
    assert files["probe_roughness-png"]["path"] == f"{generation}/files/probe_Roughness.png"
    dst = created.argument("create", "dst")
    assert files["project"]["path"] == dst.relative_to(created.root).as_posix()
    assert files["mesh"]["path"] == "_tmp/claude/varinha11-v1/paint/11-Varinha-Madeira-v1_low.obj"
    assert export["manifest"]["manifest_export"]["outputs"] == ["probe_roughness-png"]

    monkeypatch.setenv("UZP_ASSETS3D_ROOT", str(tmp_path / "elsewhere"))
    reply, status = client.execute_python(EXPORT.replace("__OUT__", repr(str(out))))
    assert status == client.OK, reply
    (export,) = reply["exports"]
    assert (
        export["manifest"] is None and "outside the Assets3D root" in export["manifest_unavailable"]
    )
    assert os.path.isfile(out / "probe_Roughness.png")


AFTER_EXPORT = {
    "different": "import substance_painter.project as p\np.save_as(__OTHER__)\n",
    "closed": "import substance_painter.project as p\np.close()\n",
}


@pytest.mark.parametrize("then", sorted(AFTER_EXPORT))
def test_an_export_keeps_its_sources_when_the_run_ends_on_another_project(
    created: Wand, adapter_env: None, then: str
) -> None:
    """The manifest of an export names the project and mesh it was exported from, also when the
    script then saves the project under another name or closes it (the export job records its
    sources when it is queued)."""
    out = created.root / "_tmp" / "claude" / "varinha11-v1" / "probe-export"
    other = created.root / "_tmp" / "claude" / "varinha11-v1" / "other.spp"
    code = EXPORT.replace("__OUT__", repr(str(out))) + AFTER_EXPORT[then].replace(
        "__OTHER__", repr(str(other))
    )
    reply, status = client.execute_python(code)
    assert status == client.OK, reply["error"]
    (export,) = reply["exports"]
    assert export["manifest"] is not None, export["manifest_unavailable"]
    files = export["manifest"]["manifest_files"]
    dst = created.argument("create", "dst")
    assert files["project"]["path"] == dst.relative_to(created.root).as_posix()
    assert files["mesh"]["path"] == "_tmp/claude/varinha11-v1/paint/11-Varinha-Madeira-v1_low.obj"


RELATIVE_SOURCES = (
    """
import os
import substance_painter.project as p
p.close()
os.chdir(__PAINT__)
p.create("11-Varinha-Madeira-v1_low.obj")
p.save_as("relative.spp")
"""
    + EXPORT
    + """
os.chdir(__ELSEWHERE__)
p.close()
"""
)


def test_an_export_names_relative_sources_against_the_directory_they_were_named_in(
    created: Wand, adapter_env: None, tmp_path: Path
) -> None:
    """A project created from a relative mesh path and saved under a relative path, exported,
    then left from another working directory: the manifest names both sources where they were
    when the calls named them (the export job records absolute paths), not under the final
    directory."""
    paint = created.root / "_tmp" / "claude" / "varinha11-v1" / "paint"
    out = created.root / "_tmp" / "claude" / "varinha11-v1" / "probe-export"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    code = (
        RELATIVE_SOURCES.replace("__PAINT__", repr(str(paint)))
        .replace("__ELSEWHERE__", repr(str(elsewhere)))
        .replace("__OUT__", repr(str(out)))
    )
    reply, status = client.execute_python(code)
    assert status == client.OK, reply["error"]
    (export,) = reply["exports"]
    assert export["manifest"] is not None, export["manifest_unavailable"]
    files = export["manifest"]["manifest_files"]
    assert files["project"]["path"] == "_tmp/claude/varinha11-v1/paint/relative.spp"
    assert files["mesh"]["path"] == "_tmp/claude/varinha11-v1/paint/11-Varinha-Madeira-v1_low.obj"


SAVED_RELATIVE = """
import os
import substance_painter.project as p
p.close()
os.chdir(__PAINT__)
p.create("11-Varinha-Madeira-v1_low.obj")
p.save_as("relative.spp")
os.chdir(__ELSEWHERE__)
result = str(p.get_uuid())
"""

CARRIED = """
import uzpainter
import substance_painter.project as p
result = {"uuid": str(p.get_uuid()), "path": uzpainter.project.absolute_file_path()}
"""


def test_a_project_saved_under_a_relative_path_is_reopened_where_it_was_saved(
    created: Wand, adapter_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 118 (Codex audit): a call changes directory, saves the project under a relative
    path and moves on; the next call, run from another directory that holds another project of
    the same name, reopens exactly the project the first call saved."""
    paint = created.root / "_tmp" / "claude" / "varinha11-v1" / "paint"
    first, second, elsewhere = tmp_path / "first", tmp_path / "second", tmp_path / "elsewhere"
    for folder in (first, second, elsewhere):
        folder.mkdir()
    shutil.copyfile(created.argument("create", "dst"), second / "relative.spp")  # the homonym
    monkeypatch.chdir(first)
    code = SAVED_RELATIVE.replace("__PAINT__", repr(str(paint))).replace(
        "__ELSEWHERE__", repr(str(elsewhere))
    )
    reply, status = client.execute_python(code)
    assert status == client.OK, reply["error"]
    saved = paint / "relative.spp"
    assert Path(reply["session"]["project"]) == saved  # native paths use `/` (generic form)
    monkeypatch.chdir(second)
    carried, status = client.execute_python(CARRIED)
    assert status == client.OK, carried["error"]
    assert carried["data"]["uuid"] == reply["data"]
    assert Path(carried["data"]["path"]) == saved


OPENED_BUNDLE = """
import os
import uzpainter
import substance_painter.project as p
p.close()
os.chdir(__PARENT__)
p.open("bundle")
os.chdir(__ELSEWHERE__)
result = {"uuid": str(p.get_uuid()), "path": uzpainter.project.absolute_file_path()}
"""


def test_a_project_opened_from_a_bundle_directory_is_reopened_from_its_store_file(
    created: Wand, adapter_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 118 (Codex audit): a call opens a bundle directory by a relative path, which imports
    it into the adjacent `bundle.uzp`; the next call, from another directory, reopens that store
    file (importing the directory again would fail: the `.uzp` exists)."""
    parent, first, second, elsewhere = (
        tmp_path / name for name in ("bundles", "first", "second", "elsewhere")
    )
    for folder in (parent, first, second, elsewhere):
        folder.mkdir()
    exported = subprocess.run(
        [
            created.env["UZPAINTER_EXE"],
            "export-bundle",
            str(created.argument("create", "dst")),
            str(parent / "bundle"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert exported.returncode == 0, exported.stdout + exported.stderr
    monkeypatch.chdir(first)
    code = OPENED_BUNDLE.replace("__PARENT__", repr(str(parent))).replace(
        "__ELSEWHERE__", repr(str(elsewhere))
    )
    reply, status = client.execute_python(code)
    assert status == client.OK, reply["error"]
    store = parent / "bundle.uzp"
    assert Path(reply["data"]["path"]) == store
    assert Path(reply["session"]["project"]) == store  # native paths use `/` (generic form)
    monkeypatch.chdir(second)
    carried, status = client.execute_python(CARRIED)
    assert status == client.OK, carried["error"]
    assert carried["data"]["uuid"] == reply["data"]["uuid"]
    assert Path(carried["data"]["path"]) == store


RELATIVE_REOPEN = (
    """
import os
import substance_painter.project as p
p.close()
os.chdir(__PAINT__)
p.create("11-Varinha-Madeira-v1_low.obj")
p.save_as("relative.spp")
p.close()
os.chdir(__ELSEWHERE__)
p.open(os.path.join(__PAINT__, "relative.spp"))
"""
    + EXPORT
)

RELOADED_ELSEWHERE = (
    """
import uzpainter
before = uzpainter.project.revision()
uzpainter.project.reload_mesh(__COPY__)
if __REVERT__:
    uzpainter.project.revert(before)
"""
    + EXPORT
)


def test_a_reopened_project_names_the_mesh_it_was_created_from(
    created: Wand, adapter_env: None, tmp_path: Path
) -> None:
    """A project created from a relative mesh path, saved, closed and reopened from another
    working directory names its mesh where it was imported from: the project records the
    mesh's absolute source, so nothing is resolved against the directory it is reopened in."""
    paint = created.root / "_tmp" / "claude" / "varinha11-v1" / "paint"
    out = created.root / "_tmp" / "claude" / "varinha11-v1" / "probe-export"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    code = (
        RELATIVE_REOPEN.replace("__PAINT__", repr(str(paint)))
        .replace("__ELSEWHERE__", repr(str(elsewhere)))
        .replace("__OUT__", repr(str(out)))
    )
    reply, status = client.execute_python(code)
    assert status == client.OK, reply["error"]
    (export,) = reply["exports"]
    assert export["manifest"] is not None, export["manifest_unavailable"]
    files = export["manifest"]["manifest_files"]
    assert files["project"]["path"] == "_tmp/claude/varinha11-v1/paint/relative.spp"
    assert files["mesh"]["path"] == "_tmp/claude/varinha11-v1/paint/11-Varinha-Madeira-v1_low.obj"


@pytest.mark.parametrize("revert", [False, True])
def test_a_mesh_reloaded_from_another_folder_is_named_where_it_was_reloaded_from(
    created: Wand, adapter_env: None, revert: bool
) -> None:
    """Reloading identical mesh bytes from another folder keeps one catalog entry for them, but
    the project's current mesh source is the new path, and the export's manifest names it. A
    revert to the revision before the reload brings back the first path: the export reads the
    source of the revision it exports."""
    paint = created.root / "_tmp" / "claude" / "varinha11-v1" / "paint"
    copy = (
        created.root
        / "_tmp"
        / "claude"
        / "varinha11-v1"
        / "copy"
        / paint.joinpath("11-Varinha-Madeira-v1_low.obj").name
    )
    copy.parent.mkdir(parents=True)
    copy.write_bytes((paint / copy.name).read_bytes())
    out = created.root / "_tmp" / "claude" / "varinha11-v1" / "probe-export"
    code = (
        RELOADED_ELSEWHERE.replace("__COPY__", repr(str(copy)))
        .replace("__REVERT__", repr(revert))
        .replace("__OUT__", repr(str(out)))
    )
    reply, status = client.execute_python(code)
    assert status == client.OK, reply["error"]
    (export,) = reply["exports"]
    assert export["manifest"] is not None, export["manifest_unavailable"]
    files = export["manifest"]["manifest_files"]
    folder = "paint" if revert else "copy"
    assert (
        files["mesh"]["path"] == f"_tmp/claude/varinha11-v1/{folder}/11-Varinha-Madeira-v1_low.obj"
    )
