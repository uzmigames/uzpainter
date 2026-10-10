"""Content hashes recorded in `MANIFEST.json` (`13-engine-integration.md` §3.3)."""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes) -> str:
    """SHA-256 of `data` as lower-case hex."""
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    """The object id git gives `data` as a blob (`git hash-object`), without running git."""
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()
