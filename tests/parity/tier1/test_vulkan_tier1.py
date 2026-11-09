"""The three pilots' Tier 1 on Vulkan, byte-equal to DX12 (phase3.1_vulkan-compute-parity item 3.6).

For each pilot (Wand v1, Sash v5, Tunic v10 current round), on one `zig build painter
-Doptimize=ReleaseFast` of the current tree, so the DX12 outputs compared are that build's:

1. **Tier 1 on Vulkan.** The pilot's own Tier 1 runner (`wand_v1/runner.py`
   `reopened_compared`) with every `UzPainter.exe run` on Vulkan (`UZP_ASSETS3D_GPU_BACKEND`,
   the adapter client's `--gpu-backend`): two rebuilds, the first one saved, reopened and exported
   again, compared with the private golden. The export mode and exception policy are the DX12 Tier
   1 runs': every export the diagnostic measure export (decision 286), each receipt
   `non_conformant`, naming only decisions 245's and 259's refusals and the backend `vulkan`; the
   verdict relies at most on the pilot's own owner exception (EXC-010, decision 395; EXC-012,
   decision 399; EXC-011 version 3, decision 410), whose terms are unchanged.
2. **Byte equality with DX12, strict.** One more rebuild on DX12 (create and sync on DX12), its
   project saved; that saved project is exported on DX12 and then, in a fresh process reopening
   the same file, on Vulkan. Every exported file must be byte-identical across the DX12 export,
   the Vulkan export of the same project and both Vulkan Tier 1 rebuilds. No exception applies
   here (`tools/parity/cross_backend.py`): the same-project pair is compared at native depth and by
   bytes, and the cross-backend report must pass.

Reports, when `UZP_VULKAN_TIER1_REPORTS` names a repository-relative directory: the Vulkan Tier 1
report `tier1-<pilot>-vulkan.json` (the comparison-report schema; its run identity names the
backend `vulkan`) and the same-project cross-backend report `cross-backend-tier1-<pilot>.json`
(hashes and counts only). Each pilot is one parameter (`-k wand`, `-k sash`, `-k tunic`); hosted
CI has neither the asset repository nor the private store and skips with the reason.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d.client import GPU_BACKEND_ENV, GPU_DEADLINE_ENV
from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT
from tests.parity.tier1.sash_v5 import runner as sash_runner
from tests.parity.tier1.sash_v5.runner import painter_ocio
from tests.parity.tier1.tunic_recipe import GPU_DEADLINE_MS
from tests.parity.tier1.wand_v1 import runner
from tools.parity import cross_backend
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import CandidateRun, MapKey, write_report
from tools.parity.verdict import resolve_golden

REPORTS_ENV = "UZP_VULKAN_TIER1_REPORTS"  # repository-relative directory of the reports
VULKAN = "vulkan"
# The project's canonical recipe digest (`uzpainter.project.dump_recipe()`, P2-RECIPE): its
# content's identity. The file's bytes are not one: every `run` reopens the project and closes it
# natively, which rewrites the file without changing its committed content.
DIGEST = "import uzpainter\nresult = uzpainter.project.dump_recipe()['digest']\n"


@dataclass(frozen=True)
class Pilot:
    """A pilot's golden, the one owner exception its DX12 Tier 1 relies on, and whether its
    rebuilds run under Painter's OCIO configuration and with the Tunic's 4096 px deadline."""

    golden_id: str
    exception: Mapping[str, Any]
    ocio: bool
    deadline: bool


PILOTS = {
    "wand-v1": Pilot(runner.GOLDEN_ID, {"exception_id": "EXC-010", "version": 1}, False, False),
    "sash-v5": Pilot(sash_runner.GOLDEN_ID, {"exception_id": "EXC-012", "version": 1}, True, False),
    "tunic-v10": Pilot(
        "phase2/tier1/tunic-v10-current", {"exception_id": "EXC-011", "version": 3}, True, True
    ),
}

pytestmark = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(os.environ.get("UZP_NO_GPU") == "1", reason="UZP_NO_GPU=1"),
]


@dataclass(frozen=True)
class SameProject:
    """The DX12-built project saved, then exported on DX12 and on Vulkan from that one file:
    each export's files by map key and receipt, the saved project's identity, and per backend the
    project's recipe digest read in that backend's process just before its export."""

    dx12: CandidateRun
    vulkan: CandidateRun
    receipts: Mapping[str, Mapping[str, Any]]
    project: runner.Project
    digests: Mapping[str, str]


@dataclass(frozen=True)
class Evidence:
    report: dict[str, Any]
    runs: tuple[CandidateRun, CandidateRun]
    reopen: runner.Reopen | None
    same: SameProject
    painter: Path


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter -Doptimize=ReleaseFast` install (a Debug
    2048 px export outlasts the adapter's 600 s per call, decision 223)."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "-Doptimize=ReleaseFast", "--prefix", str(prefix)],
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


@pytest.fixture(scope="module", params=sorted(PILOTS))
def pilot(request: pytest.FixtureRequest) -> str:
    name: str = request.param
    if resolve_golden(PILOTS[name].golden_id) is None:
        pytest.skip(f"{PILOTS[name].golden_id} is not admitted")
    return name


@pytest.fixture(scope="module")
def evidence(pilot: str, painter: Path, tmp_path_factory: pytest.TempPathFactory) -> Evidence:
    """One run per pilot for both tests: the Vulkan Tier 1, then the DX12 rebuild whose saved
    project is exported on both backends."""
    spec = PILOTS[pilot]
    resolved = resolve_golden(spec.golden_id)
    assert resolved is not None
    work = tmp_path_factory.mktemp(pilot)
    with pytest.MonkeyPatch.context() as patch:
        if spec.ocio:
            patch.setenv("OCIO", str(painter_ocio()))
        if spec.deadline:
            patch.setenv(GPU_DEADLINE_ENV, str(GPU_DEADLINE_MS))
        patch.setenv(GPU_BACKEND_ENV, VULKAN)
        report, runs, reopen = runner.reopened_compared(
            painter, work / "vulkan", spec.golden_id, resolved.manifest_path, diagnostic=True
        )
        patch.delenv(GPU_BACKEND_ENV)
        same = same_project(painter, work / "dx12", resolved.manifest_path)
    return Evidence(report, runs, reopen, same, painter)


def same_project(painter: Path, work: Path, manifest: Path) -> SameProject:
    """A rebuild on DX12 (create and sync), its project saved, then the saved file exported in
    the measure mode on DX12 and on Vulkan, each in a fresh process; each export's files copied
    with their hashes before the next runs, each receipt checked (`runner.checked_receipt`: the
    backend, `non_conformant`, decided refusals only). The project's recipe digest is read in each
    backend's process before its export and once more after both: all three must be equal."""
    wand = runner.built(painter, work, manifest)
    saving = wand.probe("save", runner.SAVE)
    if saving["after"]["needs_saving"]:
        raise runner.RunError(f"the project still needs saving after project.save(): {saving}")
    project = runner.project_of(saving["after"])
    runs: dict[str, CandidateRun] = {}
    receipts: dict[str, Mapping[str, Any]] = {}
    digests: dict[str, str] = {}
    for backend in ("dx12", VULKAN):
        wand.env[GPU_BACKEND_ENV] = backend
        digests[backend] = str(wand.probe(f"digest-{backend}", DIGEST))
        exported = runner.checked_export(wand, diagnostic=True)
        if exported.refused:
            raise runner.RunError(f"the {backend} export was refused: {exported.refusal}")
        runs[backend], _ = runner.preserved(exported, work / f"{backend}-export")
        receipts[backend] = runner.receipt_of(wand)
    after = str(wand.probe("digest-after", DIGEST))
    if len({*digests.values(), after}) != 1:
        raise runner.RunError(f"the project's recipe digest changed: {digests}, after {after}")
    if runner.project_of(wand.probe("reopened", runner.IDENTITY)) != project:
        raise runner.RunError("the exports did not reopen the saved project")
    return SameProject(runs["dx12"], runs[VULKAN], receipts, project, digests)


def bundle(same: SameProject, backend: str, painter_sha256: str, folder: Path) -> Path:
    """The `tools.parity.cross_backend` bundle of `backend`'s export of the saved project, written
    in `folder`. `project_sha256` is the project's recipe digest read before that export
    (`DIGEST`); the build is `UzPainter.exe`'s SHA-256; the
    revision, profile, resources, adapter and driver are the export receipt's."""
    receipt = same.receipts[backend]
    files = (same.dx12 if backend == "dx12" else same.vulkan).files
    document = {
        "backend": receipt["backend"],
        "project_uuid": same.project.uuid,
        "revision": receipt["revision"],
        "project_sha256": same.digests[backend],
        "evaluator_profile": receipt["evaluator_profile"],
        "build_sha256": painter_sha256,
        "resource_hashes": {h: h for h in receipt["resource_hashes"]},
        "adapter": receipt["adapter"],
        "driver": receipt["driver"],
        "files": [
            {
                "texture_set": key[0],
                "map": key[1],
                "path": str(path),
                "sha256": runner.sha256_of(path),
            }
            for key, path in sorted(files.items())
        ],
    }
    path = folder / f"{backend}-bundle.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def normal_kinds(evidence: Evidence) -> dict[MapKey, str]:
    """The tangent-space normal maps among the compared files (the Tier 1 report's normal
    outputs, by file name), compared as normals by the cross-backend tool."""
    ids = {m["output_id"] for m in evidence.report["equality_to_painter"]["maps"] if "normal" in m}
    return {key: "normal" for key in evidence.same.dx12.files if f"{key[0]}/{key[1]}" in ids}


def bytes_of(run: CandidateRun) -> dict[MapKey, str]:
    return {key: runner.sha256_of(path) for key, path in run.files.items()}


def reports_dir() -> Path | None:
    folder = os.environ.get(REPORTS_ENV)
    return REPO_ROOT / folder if folder else None


def test_vulkan_tier1_maps_equal_painter_under_the_pilots_exception(
    pilot: str, evidence: Evidence
) -> None:
    """Item 3.6, golden half: the pilot's Tier 1 on Vulkan passes on the DX12 run's terms. Every
    map compared, no structural item, outcome `pass` relying at most on the pilot's own exception,
    the two Vulkan rebuilds byte-identical, and the first one's saved and reopened project
    exporting its first bytes again; the report's run identity names Vulkan."""
    report = evidence.report
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    assert report["run"]["backend"] == VULKAN
    if folder := reports_dir():
        write_report(report, folder / f"tier1-{pilot}-vulkan.json")
    assert not any(r.refused for r in evidence.runs), [r.refusal for r in evidence.runs]
    equality = report["equality_to_painter"]
    assert equality["structural"] == []
    assert len(equality["maps"]) == 5 and all("padding" in m for m in equality["maps"]), equality
    assert equality["outcome"] == "pass", equality
    assert equality["exceptions_relied_on"] in ([], [dict(PILOTS[pilot].exception)])
    assert report["uzpainter_repeatability"]["status"] == "repeatable"
    reopen = evidence.reopen
    assert reopen is not None and reopen.first, "the first Vulkan export wrote no file"
    assert reopen.equal, reopen


def test_vulkan_maps_byte_equal_dx12(pilot: str, evidence: Evidence, tmp_path: Path) -> None:
    """Item 3.6, DX12 half, strict: the saved DX12-built project exports the same bytes on DX12
    and on Vulkan (the cross-backend tool: decoded values at native depth and file bytes, no
    exception), and those bytes are every Vulkan Tier 1 rebuild's, file for file."""
    same = evidence.same
    assert same.receipts["dx12"]["backend"] == "dx12"
    assert same.receipts[VULKAN]["backend"] == VULKAN
    painter_sha256 = runner.sha256_of(evidence.painter)
    kinds = normal_kinds(evidence)
    assert kinds, "no normal map among the compared files"
    report = cross_backend.compare(
        bundle(same, "dx12", painter_sha256, tmp_path),
        bundle(same, VULKAN, painter_sha256, tmp_path),
        kinds=kinds,
    )
    assert cross_backend.report_problems(report) == []
    if folder := reports_dir():
        cross_backend.write_report(folder / f"cross-backend-tier1-{pilot}.json", report)
    assert report["structural"] == [], report["structural"]
    assert len(report["maps"]) == 5
    assert report["outcome"] == "pass", [
        (m["output_id"], m["differing"], m["bytes_equal"]) for m in report["maps"]
    ]
    expected = bytes_of(same.dx12)
    assert bytes_of(same.vulkan) == expected
    for run in evidence.runs:
        assert bytes_of(run) == expected
