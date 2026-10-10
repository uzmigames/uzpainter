"""Unit tests of the reusable vendoring checks on synthetic trees."""

from __future__ import annotations

from pathlib import Path

from tools.vendoring.checks import ConflictMarker, conflict_markers, manifest_problems
from tools.vendoring.citations import Citation, citation_holds
from tools.vendoring.closure import compute_closure
from tools.vendoring.hashing import git_blob_sha1, sha256_hex
from tools.vendoring.import_core import CandidateReport, select_newest
from tools.vendoring.manifest import Manifest, dumps, loads, verbatim_entry
from tools.vendoring.subset import denylisted, external_origin


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def test_git_blob_sha1_matches_git_hash_object() -> None:
    assert git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def test_conflict_markers_detected_and_lookalikes_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "bad.cpp": "int a;\n<<<<<<< HEAD\nint b;\n=======\nint c;\n>>>>>>> topic\n",
            "good.cpp": "// =======\n// <<<<<<<< not a marker\nint x = 0; // >>>>>>> \n",
        },
    )
    found = conflict_markers(tmp_path, ["bad.cpp", "good.cpp"])
    assert found == [
        ConflictMarker("bad.cpp", 2, "<<<<<<< HEAD"),
        ConflictMarker("bad.cpp", 4, "======="),
        ConflictMarker("bad.cpp", 6, ">>>>>>> topic"),
    ]


def test_denylist() -> None:
    denied = [
        "engine/asset/importers/mesh_importer.cpp",
        "engine/asset/formats/uzmesh_format.h",
        "engine/asset/formats/uztexture_format.cpp",
        "engine/renderer/raytracing/blas_manager.cpp",
        "engine/config/config.h",
        "engine/core/cvar.cpp",
        "engine/rhi/dx11/dx11_device.h",
        "engine/rhi/metal/metal_device.h",
        "engine/rhi/optimization/pso_cache.h",
    ]
    allowed = [
        "engine/asset/formats/uztexture_format.h",
        "engine/rhi/dx12/dx12_device.h",
        "engine/core/other.h",
        "engine/rhi/rhi_config.cpp",
    ]
    assert denylisted(denied + allowed) == denied


def test_closure_follows_includes_pairs_sources_and_applies_cuts(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "engine/a/a.h": '#include "b.h"\n#include <vector>\n',
            "engine/a/a.cpp": '#include "a.h"\n  #  include "cut.h"\n',
            "engine/a/b.h": "#pragma once\n",
            "engine/a/b.cpp": '#include "c.h"\n',
            "engine/c/c.h": "// via include dir\n",
            "engine/c/c.cpp": "",
            "engine/a/cut.h": "",
            "engine/f/fmt.h": "",
            "engine/f/fmt.cpp": "",
            "unrelated.h": "",
        },
    )
    result = compute_closure(
        tmp_path,
        ["engine/a/a.h", "engine/f/fmt.h"],
        include_dirs=[".", "engine/c"],
        cuts={("engine/a/a.cpp", "cut.h")},
        header_only={"engine/f/fmt.h"},
    )
    assert result.files == {
        "engine/a/a.h",
        "engine/a/a.cpp",
        "engine/a/b.h",
        "engine/a/b.cpp",
        "engine/c/c.h",
        "engine/c/c.cpp",
        "engine/f/fmt.h",
    }
    assert [(i.source, i.spelling, i.angled) for i in result.unresolved] == [
        ("engine/a/a.h", "vector", True)
    ]
    assert [(i.source, i.spelling) for i in result.cut] == [("engine/a/a.cpp", "cut.h")]


def test_external_origins() -> None:
    assert external_origin("vector") == "C/C++ standard library"
    assert external_origin("dxgi1_6.h") == "Windows SDK"
    assert external_origin("spdlog/spdlog.h") == "spdlog"
    assert external_origin("config.h") is None
    assert external_origin("renderer/scene.h") is None


def test_manifest_round_trip_and_problems(tmp_path: Path) -> None:
    folder = "thirdparty/core"
    data = b"int x;\n"
    entry = verbatim_entry("runtime/x.h", f"{folder}/x.h", "0" * 40, data)
    assert entry.upstream_sha256 == entry.vendored_sha256 == sha256_hex(data)
    manifest = Manifest("UzEngine", "runtime/", [entry])
    assert loads(dumps(manifest)) == manifest

    _write(tmp_path, {f"{folder}/x.h": "int x;\n", f"{folder}/LICENSE": "licence"})
    assert manifest_problems(tmp_path, folder, manifest) == []

    _write(tmp_path, {f"{folder}/x.h": "int y;\n", f"{folder}/stray.h": ""})
    problems = manifest_problems(tmp_path, folder, manifest)
    assert any("x.h: sha256" in p for p in problems)
    assert any("x.h: blob" in p for p in problems)
    assert f"{folder}/stray.h: not in the manifest" in problems


def test_candidate_with_conflict_marker_rejected_older_selected(tmp_path: Path) -> None:
    """Spec scenario: a candidate whose exported RHI file has a conflict marker is rejected and
    an older passing commit is considered."""
    trees = {
        "new": {"engine/rhi/rhi.h": "<<<<<<< HEAD\nint a;\n=======\nint b;\n>>>>>>> x\n"},
        "old": {"engine/rhi/rhi.h": "int a;\n"},
    }
    for commit, files in trees.items():
        _write(tmp_path / commit, files)

    def evaluate(commit: str) -> CandidateReport:
        report = CandidateReport(commit=commit)
        report.markers = conflict_markers(tmp_path / commit, ["engine/rhi/rhi.h"])
        return report

    selected, reports = select_newest(["new", "old"], evaluate)
    assert selected is not None and selected.commit == "old"
    assert [r.commit for r in reports] == ["new", "old"]
    assert not reports[0].passed


def test_citation_holds(tmp_path: Path) -> None:
    _write(tmp_path, {"f.cpp": "line1\nvoid Foo() {\n  return;\n}\n"})
    assert citation_holds(tmp_path, Citation("x", "f.cpp", 2, 3, r"void Foo\(\)", "foo"))
    assert not citation_holds(tmp_path, Citation("x", "f.cpp", 3, 4, r"void Foo\(\)", "foo"))
    assert not citation_holds(tmp_path, Citation("x", "f.cpp", 4, 9, r"\}", "range past end"))
    assert not citation_holds(tmp_path, Citation("x", "missing.cpp", 1, 1, r".", "missing"))
