"""Tests of phase2.3_realtime-preview: the preview's settling scenarios on the wand v1
(`docs/architecture/07-preview-and-render-parity.md` §8 Phase 2; decision 162).

The wand v1 is rebuilt once per module through the Assets3D pipeline adapter (`create` and `sync`
of `tests/adapters/assets3d/wand.py`, CPU only); each worker then opens its own copy of the saved
project. A worker without a preview gives the baseline; workers with the preview window attached
(`--preview`, Debug build with the stall hook, decision 120) must give the same bytes:

- 2.1: evaluation of every wand channel on the worker's GPU, the wand's export, and captures in
  every Phase 2 mode. The wand is an OCIO project with Painter's substance config
  (`painter_create.py` sets `OCIO`, decision 207), so the window draws it and `painter_viewport`
  renders it; the same worker then closes it and renders the OCIO fixture, in the window and in a
  capture. The export is the pipeline's `painter_export.py` configuration. While `infinite`
  padding on UV islands is a gap (`export-processing.json` `padding-islands`, phase1.25_pilot-wand
  item 2.7) it runs with `passthrough` padding and without its Normal map: a virtualMap outside
  the UV islands under `passthrough` is unrecorded (R-090, decision 090), so the export refuses
  it.
- 3.2: the export with the window minimised and the preview thread stalled by the test hook.
  Nothing waits on the preview thread: the stalled run completes while the preview holds its
  frame. The export times are recorded in the settling report, with no threshold (decision 162).
- 3.3: `painter_iray` is a release gap in the manifest `UzPainter.exe capabilities` prints (what
  `uzpainter://capabilities` publishes, phase2.6_mcp-typed-tool-families item 2.9) and is
  refused by the worker's `capture` before any work.

Local run on the owner's machine (decision 028): it needs a DX12 adapter and a desktop session
(the windows open on a private desktop nobody sees, decision 252), and the UzmiGames asset
repository at `E:\\UzmiGames\\Assets3D` (or `UZP_TEST_ASSETS3D`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.adapters.assets3d.wand import ASSETS3D, Wand
from tests.desktop import PrivateDesktop
from tests.preview.conftest import JSON_PREFIX, NO_GPU, OCIO_CONFIG, ocio_bundle
from tests.preview.conftest import PreviewSettling as Settling
from tests.preview.test_preview_window import (
    INSERT_FILL,
    SW_MINIMIZE,
    status,
    user32,
    wait_for,
    windows_of,
)
from tests.supervisor.conftest import Pipe
from tools.parity.fit.decode import decode

REPO_ROOT = Path(__file__).resolve().parents[2]
SEMANTICS = REPO_ROOT / "parity" / "semantics" / "export-processing.json"

pytestmark = [
    pytest.mark.skipif(
        NO_GPU, reason="UZP_NO_GPU=1: needs a DX12 adapter and a desktop session (decision 028)"
    ),
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
]

WORKER = ("--gpu-backend", "dx12", "--allow-python", "--test-faults")
# One export of the wand on the Debug worker's CPU evaluator takes about 7.5 minutes, 6.6 of them
# its BaseColor (measured 2026-10-12), so the full scenarios run longer than an agent's 10-minute
# test budget: they belong to the coordinator's batch. `UZP_PREVIEW_WAND_QUICK=1` leaves BaseColor
# out of the export and the captures, and the wand's `painter_viewport` capture (it evaluates every
# wand map on that CPU evaluator, about 11 minutes, measured 2026-10-13), to check the scenarios in
# a few minutes; a quick run is never settling evidence (decision 162).
QUICK = os.environ.get("UZP_PREVIEW_WAND_QUICK") == "1"
TEXTURE_SET = "11-Varinha-Madeira"
OCIO_DISPLAY = "OCIO, Painter's substance config, Default - sRGB (decision 042)"
CHANNELS = ("BaseColor", "BaseMetalness", "SpecularRoughness", "Height", "Normal")
GEM = "Gema"  # a group of the wand's stack with a bitmap mask

# painter_export.py's configuration (Assets3D Pipeline/retopology/wand11-v1), writing the maps
# __MAPS__ under __OUT__ with the padding __PADDING__.
EXPORT = """
import os
import substance_painter.export as ex, substance_painter.textureset as ts
doc = lambda name, src: {"fileName": "wand_" + name, "channels": [
    {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": src}
    for c in ("RGB" if name == "BaseColor" else "L")]}
maps = [doc("BaseColor", "basecolor"), doc("Roughness", "roughness"), doc("Metallic", "metallic"),
        doc("Height", "height"),
        {"fileName": "wand_Normal", "channels": [
            {"destChannel": c, "srcChannel": c, "srcMapType": "virtualMap",
             "srcMapName": "Normal_OpenGL"} for c in "RGB"]}]
cfg = {"exportShaderParams": False, "exportPath": __OUT__, "defaultExportPreset": "v6",
       "exportPresets": [{"name": "v6",
                          "maps": [m for m in maps if m["fileName"][5:] in __MAPS__]}],
       "exportList": [{"rootPath": s.name()} for s in ts.all_texture_sets()],
       "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "16", "sizeLog2": 11,
                                            "paddingAlgorithm": __PADDING__,
                                            "dithering": False}}]}
r = ex.export_project_textures(cfg)
result = {os.path.basename(p): p for v in r.textures.values() for p in v}
"""


def padding() -> str:
    """The pipeline's `infinite` padding once its UV-island case is fitted, else `passthrough`."""
    entries = json.loads(SEMANTICS.read_text(encoding="utf-8"))["entries"]
    (islands,) = [e for e in entries if e["entry_id"] == "padding-islands"]
    return "passthrough" if islands["status"] == "gap" else "infinite"


def exported_maps() -> list[str]:
    """The pipeline's five maps; without `infinite` padding not the Normal map (a virtualMap
    outside the UV islands under `passthrough` is unrecorded, R-090), and in a quick run not
    BaseColor."""
    maps = ["BaseColor", "Roughness", "Metallic", "Height", "Normal"]
    if padding() != "infinite":
        maps.remove("Normal")
    if QUICK:
        maps.remove("BaseColor")
    return maps


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(files: dict[str, str]) -> dict[str, str]:
    return {name: sha256(path) for name, path in files.items()}


def viewport(pipe: Pipe, path: str, revision: int) -> None:
    """A `painter_viewport` capture of the open project's `revision` on the worker's DX12 device,
    under Painter's substance config."""
    reply = pipe.call("capture", {"mode": "painter_viewport", "path": path, "size": [96, 64]})
    assert "error" not in reply, reply
    receipt = reply["result"]
    assert receipt["revision"] == revision and receipt["backend"] == "dx12"
    assert receipt["display_configuration"]["config_sha256"] == OCIO_CONFIG
    assert sha256(receipt["files"]["png"]) == receipt["hashes"]["png"]


@pytest.fixture(scope="module")
def wand_project(painter: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The wand v1 project after the pipeline's `create` and `sync`, saved by the adapter."""
    assert not (QUICK and os.environ.get("UZP_PREVIEW_SETTLING_REPORT")), (
        "a quick run is never settling evidence: unset UZP_PREVIEW_WAND_QUICK"
    )
    wand = Wand(painter, tmp_path_factory.mktemp("wand"))
    for call in (wand.create(), wand.sync()):
        assert call.status == 0, call.stdout + call.stderr
    project = wand.argument("create", "dst")
    assert project.is_file()
    return project


class Session:
    """One worker on its own copy of the wand; on `desktop`, nobody sees its window."""

    def __init__(
        self,
        painter: Path,
        root: Path,
        project: Path,
        *extra: str,
        desktop: PrivateDesktop | None = None,
    ) -> None:
        root.mkdir(parents=True)
        copy = root / project.name
        shutil.copyfile(project, copy)
        self.root = root
        self.pipe = Pipe(painter, root, *WORKER, *extra, desktop=desktop)
        if self.pipe.handshake["gpu_status"] != "ready":
            self.pipe.close()
            pytest.skip("no DX12 device on this machine")
        opened = self.pipe.call("project_open", {"path": str(copy)})
        assert "error" not in opened, opened
        self.revision = opened["result"]["revision"]
        self.exports = 0

    def evaluate(self) -> dict[str, str]:
        """Every wand channel evaluated on the worker's GPU: its texels' SHA-256."""
        found = {}
        for channel in CHANNELS:
            reply = self.pipe.call("evaluate_channel", {"channel": channel})
            assert "error" not in reply, reply
            result = reply["result"]
            assert result["revision"] == self.revision
            assert sha256(result["payload"]["path"]) == result["payload"]["sha256"]
            found[channel] = result["payload"]["sha256"]
        return found

    def export(self) -> tuple[dict[str, str], float]:
        """The exported files by name, and the export's wall-clock seconds."""
        self.exports += 1
        code = (
            EXPORT.replace("__OUT__", repr(str(self.root / f"export-{self.exports}")))
            .replace("__PADDING__", repr(padding()))
            .replace("__MAPS__", repr(exported_maps()))
        )
        started = time.monotonic()
        reply = self.pipe.call(
            "run_python",
            {"code": code},
            expected_revision=self.revision,
            idempotency_key=f"export-{self.exports}",
        )
        seconds = time.monotonic() - started
        assert "error" not in reply and reply["result"]["status"] == "ok", reply
        assert reply.get("committed_revision", self.revision) == self.revision
        files: dict[str, str] = reply["result"]["result"]
        assert sorted(files) == sorted(f"wand_{m}.png" for m in exported_maps())
        return files, seconds

    def capture(self, mode: str, path: str, **extra: Any) -> dict[str, Any]:
        reply = self.pipe.call("capture", {"mode": mode, "path": path, **extra})
        assert "error" not in reply, reply
        receipt: dict[str, Any] = reply["result"]
        assert receipt["revision"] == self.revision and receipt["size"] == [2048, 2048]
        assert receipt["backend"] == "cpu" and receipt["adapter"] is None
        assert sha256(receipt["files"]["png"]) == receipt["hashes"]["png"]
        return receipt

    def refusal(
        self, mode: str, path: str, code: str = "call_failed", **extra: Any
    ) -> tuple[str, str]:
        reply = self.pipe.call("capture", {"mode": mode, "path": path, **extra})
        assert reply["error"]["code"] == code, reply
        return reply["error"]["details"]["type"], reply["error"]["message"]

    def gem(self) -> int:
        nodes = self.pipe.call("snapshot_layer_tree")["result"]["nodes"]
        (uid,) = [n["uid"] for n in nodes if n["name"] == GEM and n["params"].get("mask")]
        return int(uid)

    def close(self) -> None:
        if self.pipe.process.poll() is None:
            self.pipe.process.kill()
        self.pipe.close()


@pytest.fixture(scope="module")
def baseline(
    painter: Path, wand_project: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[dict[str, Any]]:
    """The wand's evaluation and export in a worker without a preview."""
    session = Session(painter, tmp_path_factory.mktemp("baseline") / "w", wand_project)
    try:
        evaluated = session.evaluate()
        files, seconds = session.export()
        yield {
            "evaluated": evaluated,
            "exported": hashes(files),
            "export_s": seconds,
            "revision": session.revision,
        }
    finally:
        session.close()


@pytest.mark.preview_settling("wand_integration")
def test_wand_v1_with_the_preview_attached(
    painter: Path,
    tmp_path: Path,
    wand_project: Path,
    baseline: dict[str, Any],
    preview_settling: Settling,
    desktop: PrivateDesktop,
) -> None:
    """2.1: a worker with the preview window open evaluates every wand channel and exports the
    wand's maps with the bytes of a worker without a preview; its `base_color` and
    `channel:roughness` captures hold the decoded values of the exported maps, and the gem's
    `mask:<uid>` is written. It refuses `painter_iray` before any work. The window draws the OCIO
    wand with the four maps the preview's own evaluation published (decision 248), and
    `painter_viewport` renders it. Closing the wand clears the window; the OCIO fixture opened next
    is drawn and rendered."""
    session = Session(painter, tmp_path / "preview", wand_project, "--preview", desktop=desktop)
    try:
        pipe = session.pipe
        wait_for(lambda: status(pipe)["window_open"])
        assert len(windows_of(pipe.process.pid, desktop)) == 1
        evaluated = session.evaluate()
        files, seconds = session.export()
        assert (evaluated, hashes(files), session.revision) == (
            baseline["evaluated"],
            baseline["exported"],
            baseline["revision"],
        )

        sources = {"rough": ("channel:roughness", "wand_Roughness.png")}
        if not QUICK:
            sources["base"] = ("base_color", "wand_BaseColor.png")
        for name, (mode, exported) in sources.items():
            receipt = session.capture(mode, f"caps/{name}.png", texture_set=TEXTURE_SET)
            captured = np.asarray(decode(Path(receipt["files"]["png"]).read_bytes()).values)
            expected = np.asarray(decode(Path(files[exported]).read_bytes()).values)
            assert np.array_equal(captured, expected), name
        session.capture(f"mask:{session.gem()}", "caps/gem.png")
        kind, message = session.refusal("painter_iray", "../../outside.png", "capability_gap")
        assert kind == "PathTracerUnavailable" and "P3-PATHTRACER" in message, message

        shown = wait_for(lambda: (s := status(pipe))["revision_shown"] == session.revision and s)
        # The wand binds an AO mesh map: the viewport's Occlusion slot (decision 257).
        slots = ("BaseColor", "Metalness", "Roughness", "Normal", "Occlusion")
        assert sorted(shown["maps_shown"]) == sorted(f"{TEXTURE_SET}/{s}" for s in slots), shown
        assert shown["display"] == OCIO_DISPLAY and shown["last_error"] == "", shown
        if not QUICK:
            viewport(pipe, "caps/vp.png", session.revision)

        assert "error" not in pipe.call("project_close")
        wait_for(lambda: status(pipe)["revision_shown"] == -1)
        bundle = ocio_bundle(painter, tmp_path / "fixture")
        revision = pipe.call("project_open", {"path": str(bundle)})["result"]["revision"]
        wait_for(lambda: status(pipe)["revision_shown"] == revision)
        viewport(pipe, "ocio/vp.png", revision)
        preview_settling.metric("baseline_export_s", baseline["export_s"])
        preview_settling.metric("open_export_s", seconds)
    finally:
        session.close()


@pytest.mark.preview_settling("wand_export_preview")
def test_wand_v1_export_with_the_preview_minimised_and_stalled(
    painter: Path,
    tmp_path: Path,
    wand_project: Path,
    baseline: dict[str, Any],
    preview_settling: Settling,
    desktop: PrivateDesktop,
) -> None:
    """3.2: with the window minimised and then the preview thread stalled by the test hook while
    it holds its frame, the wand's evaluation and export run to the end with the baseline's bytes
    while no frame is taken (nothing waits on the preview thread); a commit made then is still
    evaluated and published by the preview's own thread (decision 248), and frames are taken again
    after the resume. An export with the window open is the integration test's; the export times
    go to the settling report."""
    session = Session(painter, tmp_path / "preview", wand_project, "--preview", desktop=desktop)
    try:
        pipe = session.pipe
        (hwnd,) = wait_for(lambda: windows_of(pipe.process.pid, desktop))
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        assert session.evaluate() == baseline["evaluated"]
        wait_for(lambda: status(pipe)["frames_taken"] >= 1)

        assert pipe.call("test_fault", {"fault": "preview_stall"})["result"] == {
            "armed": "preview_stall"
        }
        wait_for(lambda: status(pipe)["stalled"])
        held = status(pipe)
        stalled_evaluation = session.evaluate()
        files, seconds = session.export()
        revision = pipe.call("project_inspect")["result"]["revision"]
        fill = pipe.call(
            "run_python",
            {"code": INSERT_FILL},
            expected_revision=session.revision,
            idempotency_key="fill",
        )
        assert "error" not in fill and "committed_revision" in fill, fill
        wait_for(lambda: status(pipe)["frames_published"] > held["frames_published"])
        during = status(pipe)
        assert during["stalled"] and during["frames_taken"] == held["frames_taken"]
        assert pipe.call("test_fault", {"fault": "preview_resume"})["result"] == {
            "armed": "preview_resume"
        }
        wait_for(lambda: status(pipe)["frames_taken"] > held["frames_taken"])

        assert stalled_evaluation == baseline["evaluated"]
        assert hashes(files) == baseline["exported"]
        assert revision == baseline["revision"]
        preview_settling.metric("baseline_export_s", baseline["export_s"])
        preview_settling.metric("stalled_export_s", seconds)
    finally:
        session.close()


@pytest.mark.preview_settling("painter_iray_unavailable")
def test_painter_iray_is_an_unavailable_capability(painter: Path) -> None:
    """3.3: the manifest `UzPainter.exe capabilities` prints, the one `uzpainter://capabilities`
    will publish, lists `capture` mode `painter_iray` as a release gap until P3-PATHTRACER and
    names its exception; the worker's refusal is checked on the wand in the tests above."""
    process = subprocess.run(
        [str(painter), "capabilities"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    (line,) = [x for x in process.stdout.splitlines() if x.startswith(JSON_PREFIX)]
    manifest = json.loads(line[len(JSON_PREFIX) :])
    (iray,) = [
        e
        for e in manifest["entries"]
        if (e["symbol"], e["context"]) == ("uzpainter.render.capture", "mode:painter_iray")
    ]
    assert iray["status"] == "release-gap" and "P3-PATHTRACER" in iray["notes"]
    assert "PathTracerUnavailable" in iray["notes"]
    (viewport,) = [
        e
        for e in manifest["entries"]
        if (e["symbol"], e["context"]) == ("uzpainter.render.capture", "any")
    ]
    assert "never parity evidence" in viewport["notes"]
