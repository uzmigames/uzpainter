"""Vendor the render core's third-party libraries from their own upstream packages
(`13-engine-integration.md` §2.5, `tools/vendoring/thirdparty.py`).

Usage:
    python -m tools.vendoring.import_thirdparty --uzengine E:/UzmiGames/UzEngine --staging <dir>
        [--cache <dir>] [--library <name>]... [--repo-root .] [--dry-run]

For each library: download the pinned archive into the cache (or reuse it) and check its SHA-256,
extract it into a fresh folder under `--staging` (outside both repositories), select the files
of the table, byte-compare the package with UzEngine's copy at the selected commit (read from the
commit's blobs, never from a working tree) and fail if a difference has no recorded cause. Then
copy the selected files into `thirdparty/<folder>/` and write `MANIFEST.json` and `ORIGIN.md`.
A folder that already holds exactly the selected bytes only gets its metadata rewritten; any
other existing content is an error. Evidence is written to `<staging>/thirdparty-evidence.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from tools.vendoring import git
from tools.vendoring.checks import list_files
from tools.vendoring.thirdparty import (
    LIBRARIES,
    LIBRARY_BY_NAME,
    METADATA_FILES,
    UZENGINE_COMMIT,
    ComparedFile,
    Library,
    LibraryManifest,
    build_manifest,
    compare,
    default_cache,
    dumps_manifest,
    fetch,
    render_origin,
    select_files,
    unexplained,
)


def extract(archive: Path, dest: Path) -> None:
    """Unpack a `.tar.gz` or zip archive into the empty folder `dest` (path-safe)."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(archive, mode="r:*") as tf:
            tf.extractall(dest, filter="data")


def uzengine_copy(uzengine: Path, lib: Library) -> dict[str, tuple[str, bytes]]:
    """UzEngine's files of `lib` at the selected commit: `path -> (blob id, bytes)`."""
    blobs = git.ls_tree_blobs(uzengine, UZENGINE_COMMIT, (lib.uzengine_dir,))
    contents = git.read_blobs(uzengine, sorted(set(blobs.values())))
    prefix = lib.uzengine_dir + "/"
    return {
        path.removeprefix(prefix): (oid, contents[oid])
        for path, oid in blobs.items()
        if path.startswith(prefix)
    }


def stage(
    lib: Library, archive: Path, staging: Path, uzengine: Path
) -> tuple[dict[str, bytes], list[ComparedFile]]:
    """Extract, select and compare one library. Returns the selected bytes and the comparison."""
    staging.mkdir(parents=True, exist_ok=True)
    extracted = Path(tempfile.mkdtemp(prefix=f"{lib.folder}-", dir=staging))
    extract(archive, extracted)
    root = extracted / lib.archive_root if lib.archive_root else extracted
    names = list_files(root)
    selected = select_files(lib, names, root)
    data = {path: (root / path).read_bytes() for path in selected}
    copy = uzengine_copy(uzengine, lib)
    name_set = set(names)
    upstream = {path: (root / path).read_bytes() for path in copy if path in name_set}
    return data, compare(copy, upstream)


def write_folder(repo_root: Path, lib: Library, data: Mapping[str, bytes]) -> str:
    """Copy the selected files into `thirdparty/<folder>/`. Returns `"written"` or, if the folder
    already holds exactly these bytes, `"unchanged"`; raises `FileExistsError` otherwise."""
    dest = repo_root / lib.path
    existing = [p for p in list_files(dest) if p not in METADATA_FILES] if dest.exists() else []
    if existing:
        same = set(existing) == set(data) and all(
            (dest / p).read_bytes() == data[p] for p in existing
        )
        if not same:
            raise FileExistsError(f"{dest} holds other content; remove it to re-import")
        return "unchanged"
    for path, content in data.items():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return "written"


def write_metadata(repo_root: Path, lib: Library, manifest: LibraryManifest) -> None:
    dest = repo_root / lib.path
    (dest / "MANIFEST.json").write_bytes(dumps_manifest(manifest).encode("utf-8"))
    (dest / "ORIGIN.md").write_bytes(render_origin(lib, manifest).encode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--uzengine", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=default_cache())
    parser.add_argument("--library", action="append", choices=sorted(LIBRARY_BY_NAME))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    libs = [LIBRARY_BY_NAME[n] for n in args.library] if args.library else list(LIBRARIES)
    if not git.has_commit(args.uzengine, UZENGINE_COMMIT):
        print(f"UzEngine commit {UZENGINE_COMMIT} not found in {args.uzengine}", file=sys.stderr)
        return 1

    problems: list[str] = []
    staged: list[tuple[Library, dict[str, bytes], LibraryManifest]] = []
    evidence: dict[str, object] = {}
    for lib in libs:
        archive = fetch(lib, args.cache)
        data, compared = stage(lib, archive, args.staging, args.uzengine)
        problems += unexplained(lib, compared)
        manifest = build_manifest(lib, data, compared)
        staged.append((lib, data, manifest))
        evidence[lib.name] = {
            "archive": str(archive),
            "files": len(data),
            "comparison": {
                result: [c.path for c in compared if c.result == result]
                for result in ("identical", "line-endings", "different", "uzengine-only")
            },
            "not_in_uzengine": manifest.not_in_uzengine,
        }
    evidence["problems"] = problems
    args.staging.mkdir(parents=True, exist_ok=True)
    (args.staging / "thirdparty-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2))
    if problems:
        return 1
    if not args.dry_run:
        for lib, data, manifest in staged:
            state = write_folder(args.repo_root, lib, data)
            write_metadata(args.repo_root, lib, manifest)
            print(f"{lib.path}: {state}, metadata written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
