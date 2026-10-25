"""Copy diagnostic evidence to a new private ZIP; never run, move or delete source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.schemas import REPO_ROOT

CHUNK_SIZE = 1024 * 1024
INDEX = "evidence-index.json"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def private_path(path: Path, repo_root: Path) -> Path:
    absolute = path.absolute()
    for part in (absolute, *absolute.parents):
        require(not part.is_symlink() and not part.is_junction(), "links are not evidence")
    return ensure_outside_repository(absolute, repo_root)


def fingerprint(stream: IO[bytes]) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    while data := stream.read(CHUNK_SIZE):
        digest.update(data)
        size += len(data)
    return digest.hexdigest(), size


def file_fingerprint(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        return fingerprint(stream)


def inventory(roots: Sequence[Path], repo_root: Path) -> list[tuple[Path, str]]:
    files = []
    for index, root in enumerate(roots):
        require(root.exists(), "source missing")
        paths = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in paths:
            checked = private_path(path, repo_root)
            if checked.is_dir():
                continue
            require(stat.S_ISREG(checked.stat().st_mode), "source is not a regular file")
            relative = checked.relative_to(root) if root.is_dir() else Path(root.name)
            files.append((checked, f"source-{index:04d}/{relative.as_posix()}"))
    require(bool(files), "no evidence files")
    return files


def preserve(
    sources: Sequence[Path],
    output: Path,
    *,
    expected_sha256: Sequence[str] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Verify before/after copying and ZIP roundtrip. An interrupted partial ZIP is retained.

    Callers must supply quiescent files. Pre/post inventories and hashes detect changes;
    this copier does not create an atomic database or application snapshot.
    """
    roots = [private_path(path, repo_root) for path in sources]
    destination = private_path(output, repo_root)
    require(bool(roots) and len(set(roots)) == len(roots), "duplicate or absent sources")
    require(destination.parent.is_dir(), "destination parent must already exist")
    require(not destination.exists(), "destination already exists")
    for root in roots:
        require(
            destination != root and not destination.is_relative_to(root),
            "destination overlaps source",
        )
    files = inventory(roots, repo_root)
    before = {path: file_fingerprint(path) for path, _ in files}
    if expected_sha256 is not None:
        require(len(expected_sha256) == len(roots), "one expected hash required per source")
        for root, expected_digest in zip(roots, expected_sha256, strict=True):
            require(root.is_file() and before[root][0] == expected_digest, "source hash differs")
    records = []
    # Exclusive creation is the no-overwrite boundary, including a concurrent destination.
    with destination.open("xb") as archive_stream:
        with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_STORED) as archive:
            for path, member in files:
                digest, size = hashlib.sha256(), 0
                with (
                    path.open("rb") as source,
                    archive.open(member, "w", force_zip64=True) as target,
                ):
                    while data := source.read(CHUNK_SIZE):
                        require(target.write(data) == len(data), "short archive write")
                        digest.update(data)
                        size += len(data)
                require((digest.hexdigest(), size) == before[path], "source changed while copying")
                records.append(
                    {
                        "source": str(path),
                        "member": member,
                        "sha256": digest.hexdigest(),
                        "size_bytes": size,
                    }
                )
            require(inventory(roots, repo_root) == files, "source inventory changed")
            require(
                all(file_fingerprint(path) == before[path] for path, _ in files), "source changed"
            )
            index = {"schema": "uzpainter/diagnostic-evidence/1", "files": records}
            archive.writestr(INDEX, json.dumps(index, sort_keys=True, ensure_ascii=True) + "\n")
        archive_stream.flush()
    with zipfile.ZipFile(destination, "r") as archive:
        require(
            set(archive.namelist()) == {INDEX, *(member for _, member in files)},
            "archive inventory differs",
        )
        for path, member in files:
            with archive.open(member) as stream:
                require(fingerprint(stream) == before[path], "archive roundtrip differs")
        require(json.loads(archive.read(INDEX)) == index, "archive index differs")
    return {
        "status": "complete",
        "files": len(records),
        "source_bytes": sum(record["size_bytes"] for record in records),
        "archive_sha256": file_fingerprint(destination)[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--source-sha256", action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = preserve(args.source, args.output, expected_sha256=args.source_sha256)
    except Exception:
        print('{"status":"refused"}')
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
