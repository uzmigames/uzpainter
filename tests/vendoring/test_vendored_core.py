"""Checks over `thirdparty/uzengine-render-core/` (phase0.1_vendor-core-copy, items 3.1-3.4)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.vendoring import git
from tools.vendoring.checks import (
    closure_problems,
    conflict_markers,
    denylist_violations,
    list_files,
    manifest_problems,
    upstream_blob_problems,
)
from tools.vendoring.hashing import git_blob_sha1
from tools.vendoring.import_core import check_tree
from tools.vendoring.manifest import Manifest, load
from tools.vendoring.subset import METADATA_FILES, VENDORED_DIR, expand_seeds

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED = REPO_ROOT / VENDORED_DIR
SELECTED_COMMIT = "380c142e481d56fe16b045f63315b42359e86a7d"
LICENSE_BLOB = "57ff3b22d0e71b46b74de4e5b2e0bbb57a75c633"
UPSTREAM_DIRS = ("runtime/engine", "runtime/platform")
UZENGINE_REPO = Path(os.environ.get("UZENGINE_REPO", r"E:\UzmiGames\UzEngine"))


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return load(VENDORED / "MANIFEST.json")


def _relative(manifest: Manifest) -> set[str]:
    prefix = f"{VENDORED_DIR}/"
    return {e.vendored_path.removeprefix(prefix) for e in manifest.files}


def test_manifest_is_the_declared_subset_from_one_commit(manifest: Manifest) -> None:
    assert len(manifest.files) == 97
    assert _relative(manifest) == set(expand_seeds(VENDORED))
    for entry in manifest.files:
        assert entry.upstream_commit == SELECTED_COMMIT
        assert entry.upstream_path == "runtime/" + entry.vendored_path.removeprefix(
            f"{VENDORED_DIR}/"
        )
        assert entry.status == "verbatim"
        assert entry.modifications == []


def test_byte_equality(manifest: Manifest) -> None:
    """3.1: vendored_sha256 == upstream_sha256 and the blob id of the bytes is recorded."""
    assert manifest_problems(REPO_ROOT, VENDORED_DIR, manifest) == []


def test_blob_ids_equal_upstream_tree(manifest: Manifest) -> None:
    """3.1: upstream_blob_sha1 equals the blob id in `git ls-tree` of the selected commit."""
    if not git.has_commit(UZENGINE_REPO, SELECTED_COMMIT):
        pytest.skip(
            f"UzEngine commit {SELECTED_COMMIT} not available at {UZENGINE_REPO} "
            "(set UZENGINE_REPO)"
        )
    tree = git.ls_tree_blobs(UZENGINE_REPO, SELECTED_COMMIT, UPSTREAM_DIRS)
    assert upstream_blob_problems(manifest, {SELECTED_COMMIT: tree}) == []


def test_selection_checks_hold_at_the_selected_commit(
    manifest: Manifest, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """2.2-2.4: re-run checks (a), (b) and (d) on a fresh `git archive` of the selected commit."""
    if not git.has_commit(UZENGINE_REPO, SELECTED_COMMIT):
        pytest.skip(
            f"UzEngine commit {SELECTED_COMMIT} not available at {UZENGINE_REPO} "
            "(set UZENGINE_REPO)"
        )
    export_root = tmp_path_factory.mktemp("uzengine-export")
    git.export(UZENGINE_REPO, SELECTED_COMMIT, UPSTREAM_DIRS, export_root)
    blobs = git.ls_tree_blobs(UZENGINE_REPO, SELECTED_COMMIT, UPSTREAM_DIRS)
    report = check_tree(SELECTED_COMMIT, export_root / "runtime", blobs)
    assert report.passed, report
    assert set(report.files) == _relative(manifest)


def test_include_closure_equals_manifest(manifest: Manifest) -> None:
    """3.2: the include closure recomputed on the vendored folder is exactly the manifest."""
    assert closure_problems(VENDORED, _relative(manifest)) == []


def test_no_denylisted_path() -> None:
    """3.3: no file matches a §2.4 exclusion."""
    assert denylist_violations(VENDORED) == []


def test_no_conflict_markers() -> None:
    """3.4: no merge-conflict marker anywhere in the folder."""
    assert conflict_markers(VENDORED, list_files(VENDORED)) == []


def test_licence_and_attribution() -> None:
    licence = (VENDORED / "LICENSE").read_bytes()
    assert git_blob_sha1(licence) == LICENSE_BLOB
    assert b"Copyright 2026 Uzmi Games" in licence
    notice = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "UzEngine" in notice
    assert "Copyright 2026 Uzmi Games" in notice
    assert SELECTED_COMMIT in notice
    origin = (VENDORED / "ORIGIN.md").read_text(encoding="utf-8")
    assert SELECTED_COMMIT in origin


def test_only_manifest_and_metadata_files(manifest: Manifest) -> None:
    listed = _relative(manifest)
    extra = [p for p in list_files(VENDORED) if p not in listed and p not in METADATA_FILES]
    assert extra == []
