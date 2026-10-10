"""`MANIFEST.json` of the vendored render core (`13-engine-integration.md` §3.3)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from tools.vendoring.hashing import git_blob_sha1, sha256_hex

Status = Literal["verbatim", "modified"]


@dataclass(frozen=True)
class ManifestEntry:
    """One vendored file. Paths are `/`-separated; `vendored_path` is relative to the
    UzPainter repository root, `upstream_path` to the UzEngine repository root."""

    upstream_path: str
    vendored_path: str
    upstream_commit: str
    upstream_blob_sha1: str
    upstream_sha256: str
    vendored_sha256: str
    status: Status
    modifications: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    """The whole manifest: the upstream repository it came from and one entry per file."""

    upstream_repository: str
    upstream_root: str
    files: list[ManifestEntry]

    def by_vendored_path(self) -> dict[str, ManifestEntry]:
        return {entry.vendored_path: entry for entry in self.files}


def verbatim_entry(
    upstream_path: str, vendored_path: str, commit: str, data: bytes
) -> ManifestEntry:
    """Entry for a file copied byte for byte from `commit`."""
    digest = sha256_hex(data)
    return ManifestEntry(
        upstream_path=upstream_path,
        vendored_path=vendored_path,
        upstream_commit=commit,
        upstream_blob_sha1=git_blob_sha1(data),
        upstream_sha256=digest,
        vendored_sha256=digest,
        status="verbatim",
        modifications=[],
    )


def dumps(manifest: Manifest) -> str:
    """Serialise with sorted entries, two-space indent and a final newline."""
    files = sorted(manifest.files, key=lambda e: e.vendored_path)
    payload = {
        "upstream_repository": manifest.upstream_repository,
        "upstream_root": manifest.upstream_root,
        "files": [asdict(entry) for entry in files],
    }
    return json.dumps(payload, indent=2) + "\n"


def loads(text: str) -> Manifest:
    """Parse a manifest; raise `ValueError` on a missing or mistyped field."""
    raw = cast(dict[str, Any], json.loads(text))
    entries: list[ManifestEntry] = []
    for item in cast(list[dict[str, Any]], raw["files"]):
        status = item["status"]
        if status not in ("verbatim", "modified"):
            raise ValueError(f"bad status {status!r} for {item.get('vendored_path')}")
        modifications = item["modifications"]
        if not isinstance(modifications, list) or not all(
            isinstance(m, str) for m in modifications
        ):
            raise ValueError(f"bad modifications for {item.get('vendored_path')}")
        entries.append(
            ManifestEntry(
                upstream_path=str(item["upstream_path"]),
                vendored_path=str(item["vendored_path"]),
                upstream_commit=str(item["upstream_commit"]),
                upstream_blob_sha1=str(item["upstream_blob_sha1"]),
                upstream_sha256=str(item["upstream_sha256"]),
                vendored_sha256=str(item["vendored_sha256"]),
                status=status,
                modifications=[str(m) for m in modifications],
            )
        )
    return Manifest(
        upstream_repository=str(raw["upstream_repository"]),
        upstream_root=str(raw["upstream_root"]),
        files=entries,
    )


def load(path: Path) -> Manifest:
    return loads(path.read_text(encoding="utf-8"))


def save(path: Path, manifest: Manifest) -> None:
    path.write_bytes(dumps(manifest).encode("utf-8"))
