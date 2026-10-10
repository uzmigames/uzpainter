"""Third-party libraries of the render core (phase0.2_vendor-thirdparty, items 2.6-2.8, 3.1-3.3).

Unit tests run on synthetic data. The checks over `thirdparty/<library>/` need, respectively,
nothing (folder, manifest, `ORIGIN.md`, includes), the UzEngine repository (comparison rerun;
skipped with a reason if absent, set `UZENGINE_REPO`) and the pinned upstream archives (cached
under `UZP_THIRDPARTY_CACHE` or the local app-data folder, downloaded on first use; skipped with
a reason when offline or `UZP_OFFLINE=1`).
"""

from __future__ import annotations

import io
import os
import re
import tarfile
import urllib.error
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from tools.vendoring import git
from tools.vendoring.checks import list_files
from tools.vendoring.hashing import sha256_hex
from tools.vendoring.import_thirdparty import extract, uzengine_copy
from tools.vendoring.thirdparty import (
    LIBRARIES,
    LIBRARY_BY_NAME,
    UZENGINE_COMMIT,
    ComparedFile,
    Library,
    VendoredFile,
    application_include_problems,
    build_manifest,
    classify,
    compare,
    default_cache,
    dumps_manifest,
    fetch,
    folder_problems,
    include_problems,
    load_manifest,
    loads_manifest,
    read_archive,
    render_origin,
    select_files,
    to_lf,
    unexplained,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UZENGINE_REPO = Path(os.environ.get("UZENGINE_REPO", r"E:\UzmiGames\UzEngine"))
IDS = [lib.folder for lib in LIBRARIES]


def _write(root: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _lib(**changes: object) -> Library:
    return replace(LIBRARY_BY_NAME["volk"], **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# Unit tests


def test_classify() -> None:
    up = b"a\r\nb\r\n"
    up_sha, up_lf = sha256_hex(up), sha256_hex(to_lf(up))
    assert classify(up, up_sha, up_lf) == "identical"
    assert classify(b"a\nb\n", up_sha, up_lf) == "line-endings"
    assert classify(b"a\nc\n", up_sha, up_lf) == "different"
    assert classify(b"x", None, None) == "uzengine-only"


def test_compare_and_unexplained() -> None:
    upstream = {"same.h": b"1\n", "crlf.h": b"2\r\n", "patched.h": b"3\n"}
    uzengine = {
        "same.h": ("b1", b"1\n"),
        "crlf.h": ("b2", b"2\n"),
        "patched.h": ("b3", b"4\n"),
        "extra.patch": ("b4", b"p"),
    }
    compared = compare(uzengine, upstream)
    assert [(c.path, c.result) for c in compared] == [
        ("crlf.h", "line-endings"),
        ("extra.patch", "uzengine-only"),
        ("patched.h", "different"),
        ("same.h", "identical"),
    ]
    lib = _lib(differences={"patched.h": "cause", "gone.h": "stale"})
    assert unexplained(lib, compared) == [
        "volk: extra.patch differs from upstream without a recorded cause",
        "volk: recorded cause for gone.h, which does not differ",
    ]
    explained = _lib(differences={"patched.h": "cause", "extra.patch": "cause"})
    assert unexplained(explained, compared) == []


def test_select_files_patterns_closure_and_licences(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "LICENSE": b"l",
            "pub/a/A.hpp": b'#include "../b/B.hpp"\n#include <system.h>\n',
            "pub/a/A.cpp": b"",
            "pub/b/B.hpp": b"",
            "pub/b/B.cpp": b"",
            "pub/c/Unused.hpp": b"",
        },
    )
    names = list_files(tmp_path)
    lib = _lib(
        select=("LICENSE",),
        licence_files=("LICENSE",),
        sources=(),
        header_closure=("pub/a/A.hpp",),
        include_dirs=("pub",),
    )
    assert select_files(lib, names, tmp_path) == ["LICENSE", "pub/a/A.hpp", "pub/b/B.hpp"]
    with pytest.raises(ValueError, match="matches no archive file"):
        select_files(_lib(select=("nothing/*",)), names, tmp_path)
    with pytest.raises(ValueError, match="not selected"):
        select_files(_lib(select=("pub/*",), licence_files=("LICENSE",)), names, tmp_path)


def test_read_archive_tar_and_zip(tmp_path: Path) -> None:
    files = {"root-1/LICENSE": b"lic", "root-1/inc/x.h": b"x", "other/y.h": b"y"}
    tar_path = tmp_path / "a.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    zip_path = tmp_path / "a.nupkg"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    for archive in (tar_path, zip_path):
        assert read_archive(archive, "root-1/") == {"LICENSE": b"lic", "inc/x.h": b"x"}
        assert read_archive(archive, "root-1/", {"inc/x.h"}) == {"inc/x.h": b"x"}


def test_fetch_checks_the_pinned_hash(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pkg.tar.gz"
    _write(tmp_path / "src", {"pkg.tar.gz": b"package bytes"})
    cache = tmp_path / "cache"
    good = _lib(
        archive_url=source.as_uri(),
        archive_name="pkg.tar.gz",
        archive_sha256=sha256_hex(b"package bytes"),
    )
    assert fetch(good, cache).read_bytes() == b"package bytes"
    bad = replace(good, archive_sha256="0" * 64, archive_name="other.tar.gz")
    with pytest.raises(ValueError, match="pinned"):
        fetch(bad, cache)
    assert not (cache / "other.tar.gz").exists()


def test_manifest_roundtrip() -> None:
    lib = LIBRARY_BY_NAME["Tracy"]
    compared = [ComparedFile("LICENSE", "b" * 40, "s" * 64, "t" * 64, "identical")]
    manifest = build_manifest(lib, {"LICENSE": b"lic", "extra.h": b"e"}, compared)
    assert manifest.files == [
        VendoredFile("LICENSE", sha256_hex(b"lic"), 3),
        VendoredFile("extra.h", sha256_hex(b"e"), 1),
    ]
    assert manifest.not_in_uzengine == ["extra.h"]
    assert loads_manifest(dumps_manifest(manifest)) == manifest


# ---------------------------------------------------------------------------------------------
# 3.1 Provenance


@pytest.mark.parametrize("lib", LIBRARIES, ids=IDS)
def test_folder_licence_and_origin(lib: Library) -> None:
    """Licence files present, every file hashed in MANIFEST.json, ORIGIN.md current."""
    manifest = load_manifest(REPO_ROOT, lib)
    assert folder_problems(REPO_ROOT, lib, manifest) == []
    assert lib.licence_files
    origin = (REPO_ROOT / lib.path / "ORIGIN.md").read_text(encoding="utf-8")
    assert origin == render_origin(lib, manifest)
    for field in (lib.upstream, lib.version, lib.archive_url, lib.archive_sha256, "Retrieved"):
        assert field in origin


@pytest.fixture(scope="module")
def archives() -> dict[str, Path]:
    if os.environ.get("UZP_OFFLINE") == "1":
        pytest.skip("UZP_OFFLINE=1: upstream archives not fetched")
    cache = default_cache()
    try:
        return {lib.name: fetch(lib, cache) for lib in LIBRARIES}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"upstream archives not available in {cache} and not downloadable: {exc}")


@pytest.mark.parametrize("lib", LIBRARIES, ids=IDS)
def test_archive_hash_and_selection_reproduce(
    lib: Library, archives: dict[str, Path], tmp_path: Path
) -> None:
    """The archive SHA-256 recomputes to ORIGIN.md's value, the selection rule reproduces the
    vendored file list, and every vendored file equals its archive member byte for byte."""
    archive = archives[lib.name]
    digest = sha256_hex(archive.read_bytes())
    manifest = load_manifest(REPO_ROOT, lib)
    assert digest == lib.archive_sha256 == manifest.archive_sha256
    assert f"`{digest}`" in (REPO_ROOT / lib.path / "ORIGIN.md").read_text(encoding="utf-8")
    extract(archive, tmp_path)
    root = tmp_path / lib.archive_root if lib.archive_root else tmp_path
    selected = select_files(lib, list_files(root), root)
    assert selected == [f.path for f in manifest.files]
    members = read_archive(archive, lib.archive_root, set(selected))
    for path in selected:
        assert (REPO_ROOT / lib.path / path).read_bytes() == members[path], path


# ---------------------------------------------------------------------------------------------
# 3.2 Include check


def test_every_include_resolves_inside_the_repository() -> None:
    """Every third-party include reached from the core subset resolves under
    `thirdparty/<library>/` (the library its origin names); the rest are standard, Windows SDK
    or inactive-branch headers; no include directory leaves `thirdparty/`."""
    assert include_problems(REPO_ROOT / "thirdparty") == []


def test_application_includes_resolve_inside_the_repository() -> None:
    """The third-party code compiled into `UzPainter.exe` only (zlib, spng, the Embree headers;
    phase0.6_toolchain-hardware-slice) resolves its includes inside its own folders; the rest are
    standard, Windows or inactive-branch headers."""
    assert application_include_problems(REPO_ROOT / "thirdparty") == []


# ---------------------------------------------------------------------------------------------
# 3.3 Comparison with UzEngine's copy


def _require_uzengine() -> None:
    if not git.has_commit(UZENGINE_REPO, UZENGINE_COMMIT):
        pytest.skip(
            f"UzEngine commit {UZENGINE_COMMIT} not available at {UZENGINE_REPO} "
            "(set UZENGINE_REPO)"
        )


@pytest.mark.parametrize("lib", LIBRARIES, ids=IDS)
def test_comparison_reproduces_recorded_result(lib: Library) -> None:
    """Rerunning the byte comparison against UzEngine's blobs at the selected commit gives the
    recorded per-file results, and every difference has its recorded cause."""
    _require_uzengine()
    manifest = load_manifest(REPO_ROOT, lib)
    assert manifest.uzengine_commit == UZENGINE_COMMIT
    copy = uzengine_copy(UZENGINE_REPO, lib)
    assert sorted(copy) == [c.path for c in manifest.comparison]
    for recorded in manifest.comparison:
        blob, data = copy[recorded.path]
        assert blob == recorded.uzengine_blob, recorded.path
        rerun = classify(data, recorded.upstream_sha256, recorded.upstream_lf_sha256)
        assert rerun == recorded.result, recorded.path
    assert unexplained(lib, manifest.comparison) == []
    assert manifest.not_in_uzengine == sorted({f.path for f in manifest.files} - set(copy))


@pytest.mark.parametrize("lib", LIBRARIES, ids=IDS)
def test_comparison_upstream_hashes_match_archive(lib: Library, archives: dict[str, Path]) -> None:
    """The recorded upstream side of the comparison is the pinned archive's."""
    manifest = load_manifest(REPO_ROOT, lib)
    members = read_archive(
        archives[lib.name], lib.archive_root, {c.path for c in manifest.comparison}
    )
    for c in manifest.comparison:
        data = members.get(c.path)
        if data is None:
            assert c.upstream_sha256 is None and c.result == "uzengine-only", c.path
        else:
            assert c.upstream_sha256 == sha256_hex(data), c.path
            assert c.upstream_lf_sha256 == sha256_hex(to_lf(data)), c.path


def test_unneeded_tracy_patch_not_applied() -> None:
    """UzEngine's Tracy patch touches only the `TRACY_ENABLE` branch: the upstream file is
    vendored unpatched and no modification log exists for Tracy."""
    tracy = LIBRARY_BY_NAME["Tracy"]
    manifest = load_manifest(REPO_ROOT, tracy)
    results = {c.path: c.result for c in manifest.comparison}
    assert results["public/tracy/TracyD3D12.hpp"] == "different"
    assert results["patches/0001-fix-getdesc-abi-directx-headers.patch"] == "uzengine-only"
    lines = (REPO_ROOT / tracy.path / "public/tracy/TracyD3D12.hpp").read_text().splitlines()
    assert "queue->GetDesc().Type" in lines[121] and "queue->GetDesc().Type" in lines[136]
    assert lines[3] == "#ifndef TRACY_ENABLE" and lines[32] == "#else"
    assert not (REPO_ROOT / tracy.path / "MODIFICATIONS.md").exists()
    assert not (REPO_ROOT / tracy.path / "patches").exists()


# ---------------------------------------------------------------------------------------------
# 2.8 Licence inventory, layout


def test_licence_inventory_status() -> None:
    """DXC's `dxil.dll` and the Agility SDK distribution terms are named release blockers,
    recorded in each ORIGIN.md and in the inventory of `docs/licensing-and-clean-room.md`."""
    blocked = {lib.name for lib in LIBRARIES if lib.release_blocker}
    assert blocked == {"DXC", "Agility SDK"}
    inventory = (REPO_ROOT / "docs" / "licensing-and-clean-room.md").read_text(encoding="utf-8")
    for lib in LIBRARIES:
        origin = (REPO_ROOT / lib.path / "ORIGIN.md").read_text(encoding="utf-8")
        if lib.release_blocker:
            blocker_id = lib.release_blocker.split(":", 1)[0]
            assert re.fullmatch(r"RB-[A-Z-]+", blocker_id)
            assert f"**release blocker** — {blocker_id}" in origin
            assert blocker_id in inventory
        else:
            assert "Status: confirmed against the pinned package" in origin
        assert f"thirdparty/{lib.folder}/" in inventory


def test_agility_sdk_version_matches_directx_headers() -> None:
    pattern = re.compile(r"#define\s+D3D12_SDK_VERSION\s+\(\s*(\d+)\s*\)")
    versions = set()
    for path in (
        "thirdparty/directx-headers/include/directx/d3d12.h",
        "thirdparty/agility/build/native/include/d3d12.h",
    ):
        match = pattern.search((REPO_ROOT / path).read_text(encoding="utf-8"))
        assert match is not None, path
        versions.add(match.group(1))
    assert versions == {"619"}


def test_gitattributes_keeps_vendored_bytes() -> None:
    lines = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for lib in LIBRARIES:
        assert f"/{lib.path}/** -text" in lines
