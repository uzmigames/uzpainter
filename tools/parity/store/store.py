"""The private oracle store: a content-addressed folder on the owner's machine (`parity/STORE.md`).

Layout under the store root (`UZP_PARITY_STORE`, default `%LOCALAPPDATA%\\UzPainter\\parity-store`):

- `store.json`: layout marker (`uzpainter/parity/store/1`); a folder without it is not a store.
- `index.json`: the sorted SHA-256 of every stored blob (`uzpainter/parity/store-index/1`).
- `blobs/<first two hex digits>/<sha256>`: the bytes, named by their SHA-256, read-only.
- `corpora/<Painter build id>/<golden id>/<record id>.json`: one write-once entry per record.
- `inputs/<sha256>.json`: one write-once entry per stored authored input (a file a public
  manifest pins by hash, kept here so a job resolves it when its source path is gone).

A record id is unique per Painter build and golden; recording a different blob under an existing
id is refused. Any blob that is missing, unreadable or fails its hash resolves to
`oracle_unavailable`, never to a usable oracle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.parity.schemas import REPO_ROOT

STORE_ENV = "UZP_PARITY_STORE"
STORE_SCHEMA = "uzpainter/parity/store/1"
INDEX_SCHEMA = "uzpainter/parity/store-index/1"
ENTRY_SCHEMA = "uzpainter/parity/store-entry/1"
INPUT_SCHEMA = "uzpainter/parity/store-input/1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BUILD_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_RECORD_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_GOLDEN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
_CHUNK = 1 << 20


class StoreError(Exception):
    """A refused or impossible store operation."""


class Status(StrEnum):
    AVAILABLE = "available"
    ORACLE_UNAVAILABLE = "oracle_unavailable"


@dataclass(frozen=True)
class Resolution:
    """Where a blob named by a manifest stands in the store."""

    record_id: str
    sha256: str
    status: Status
    reason: str = ""
    path: Path | None = None


@dataclass(frozen=True)
class StoredRecord:
    painter_build_id: str
    golden_id: str
    record_id: str
    kind: str
    sha256: str
    size_bytes: int
    file_name: str

    def as_json(self) -> dict[str, Any]:
        return {"schema": ENTRY_SCHEMA, **self.__dict__}


def default_root(environ: Mapping[str, str] | None = None) -> Path | None:
    """`UZP_PARITY_STORE`, else `%LOCALAPPDATA%\\UzPainter\\parity-store`; None without either."""
    env = os.environ if environ is None else environ
    if configured := env.get(STORE_ENV):
        return Path(configured)
    if local := env.get("LOCALAPPDATA"):
        return Path(local) / "UzPainter" / "parity-store"
    return None


def inside_repository(path: Path) -> bool:
    return path.resolve().is_relative_to(REPO_ROOT)


def refuse_inside_repository(path: Path, what: str) -> None:
    """Private bytes never land in the repository tree (CONTRACT.md §6.4)."""
    if inside_repository(path):
        raise StoreError(f"{what} {path} is inside the repository {REPO_ROOT}; it must be outside")


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_json(path: Path, document: Any) -> None:
    """Replace `path` atomically with `document`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def refuse_snapshot_kind(kind: str) -> None:
    if kind.startswith("snapshot_"):
        raise StoreError("snapshot_* kinds require dedicated snapshot capture admission")


def publish_no_replace(staging: Path, target: Path) -> bool:
    """Publish complete bytes once; retain staging on collision or failure."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.rename(staging, target)
        else:
            os.link(staging, target)
    except OSError:
        if target.exists():
            return False
        raise
    return True


@contextmanager
def _index_lock(root: Path) -> Iterator[None]:
    """Persistent lock file; the OS releases its byte lock when a process exits."""
    with (root / ".index.lock").open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        if sys.platform == "win32":
            import msvcrt

            deadline = time.monotonic() + 30
            while True:
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise StoreError("store index lock timed out") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class OracleStore:
    """An initialised store root. Use `init` to create one and `open`/`locate` to reach it."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def init(cls, root: Path) -> OracleStore:
        """Create the layout (idempotent); refused inside the repository."""
        refuse_inside_repository(root, "store")
        marker = root / "store.json"
        if marker.exists():
            return cls.open(root)
        if root.exists() and any(root.iterdir()):
            raise StoreError(f"{root} is not empty and is not a store; refusing to initialise it")
        (root / "blobs").mkdir(parents=True, exist_ok=True)
        (root / "corpora").mkdir(exist_ok=True)
        _write_json(root / "index.json", {"schema": INDEX_SCHEMA, "sha256": []})
        _write_json(marker, {"schema": STORE_SCHEMA, "hash": "sha256"})
        return cls(root)

    @classmethod
    def open(cls, root: Path) -> OracleStore:
        refuse_inside_repository(root, "store")
        marker = root / "store.json"
        try:
            document = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise StoreError(f"{root} is not an initialised oracle store ({error})") from error
        if not isinstance(document, dict) or document.get("schema") != STORE_SCHEMA:
            raise StoreError(f"{marker} does not declare {STORE_SCHEMA}")
        return cls(root)

    # --- layout ------------------------------------------------------------------------------

    def blob_path(self, sha256: str) -> Path:
        if not _SHA256.match(sha256):
            raise StoreError(f"{sha256!r} is not a SHA-256")
        return self.root / "blobs" / sha256[:2] / sha256

    def entry_path(self, painter_build_id: str, golden_id: str, record_id: str) -> Path:
        if not _BUILD_DIR.match(painter_build_id):
            raise StoreError(
                f"Painter build id {painter_build_id!r} is not usable as a corpus directory name "
                f"({_BUILD_DIR.pattern})"
            )
        if not _GOLDEN_ID.match(golden_id):
            raise StoreError(f"golden id {golden_id!r} is not valid")
        if not _RECORD_ID.match(record_id):
            raise StoreError(f"record id {record_id!r} is not valid ({_RECORD_ID.pattern})")
        return self.root / "corpora" / painter_build_id / golden_id / f"{record_id}.json"

    def input_entry_path(self, sha256: str) -> Path:
        self.blob_path(sha256)  # refuses a name that is not a SHA-256
        return self.root / "inputs" / f"{sha256}.json"

    def index(self) -> set[str]:
        document = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
        return set(document["sha256"])

    def _add_to_index(self, sha256: str) -> None:
        with _index_lock(self.root):
            hashes = self.index()
            if sha256 not in hashes:
                hashes.add(sha256)
                _write_json(
                    self.root / "index.json", {"schema": INDEX_SCHEMA, "sha256": sorted(hashes)}
                )

    def staging_path(self) -> Path:
        return self.root / f".staging-{uuid.uuid4().hex}.partial"

    # --- records -----------------------------------------------------------------------------

    def entry(self, painter_build_id: str, golden_id: str, record_id: str) -> StoredRecord | None:
        path = self.entry_path(painter_build_id, golden_id, record_id)
        if not path.exists():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
        document.pop("schema")
        return StoredRecord(**document)

    def refuse_conflict(
        self, painter_build_id: str, golden_id: str, record_id: str, sha256: str
    ) -> None:
        """Records are write-once: a different blob under an existing record id is refused."""
        existing = self.entry(painter_build_id, golden_id, record_id)
        if existing is not None and existing.sha256 != sha256:
            raise StoreError(
                f"record {record_id} of {golden_id} (Painter build {painter_build_id}) already "
                f"holds {existing.sha256}; refusing to record {sha256} under the same id"
            )

    def put_blob(self, source: Path, sha256: str) -> int:
        """Copy `source` into the store under `sha256` (write-once); returns its size."""
        target = self.blob_path(sha256)
        if target.exists():
            found, size = sha256_file(target)
            if found != sha256:
                raise StoreError(f"stored blob {target} fails its hash (found {found})")
            self._add_to_index(sha256)
            return size
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.staging_path()
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while chunk := reader.read(_CHUNK):
                digest.update(chunk)
                writer.write(chunk)
                size += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if digest.hexdigest() != sha256:
            raise StoreError(f"{source} changed while it was stored (hash {digest.hexdigest()})")
        os.chmod(temporary, stat.S_IREAD)
        if not publish_no_replace(temporary, target):
            found, winner_size = sha256_file(target)
            if found != sha256 or winner_size != size:
                raise StoreError("concurrent stored blob fails its hash or size")
        self._add_to_index(sha256)
        return size

    def add_record(
        self,
        painter_build_id: str,
        golden_id: str,
        record_id: str,
        kind: str,
        source: Path,
        sha256: str,
        file_name: str,
    ) -> StoredRecord:
        """Store `source` (already hashed to `sha256`) and its write-once entry."""
        refuse_snapshot_kind(kind)
        path = self.entry_path(painter_build_id, golden_id, record_id)
        self.refuse_conflict(painter_build_id, golden_id, record_id, sha256)
        size = self.put_blob(source, sha256)
        record = StoredRecord(painter_build_id, golden_id, record_id, kind, sha256, size, file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(record.as_json(), indent=2) + "\n")
        except FileExistsError:
            self.refuse_conflict(painter_build_id, golden_id, record_id, sha256)
            return record
        os.chmod(path, stat.S_IREAD)
        return record

    def add_input(self, source: Path, sha256: str, source_path: str) -> int:
        """Store an authored input (already hashed to `sha256`) with a write-once entry naming
        the path a manifest pins it at; returns its size. Resolve it with `resolve`."""
        size = self.put_blob(source, sha256)
        path = self.input_entry_path(sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"schema": INPUT_SCHEMA, "sha256": sha256, "size_bytes": size, "path": source_path}
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, indent=2) + "\n")
        except FileExistsError:
            return size  # the same bytes, already stored
        os.chmod(path, stat.S_IREAD)
        return size

    # --- resolution --------------------------------------------------------------------------

    def resolve(self, record_id: str, sha256: str, size_bytes: int | None = None) -> Resolution:
        """Check a blob by re-hashing it; anything but a match is `oracle_unavailable`."""

        def unavailable(reason: str) -> Resolution:
            return Resolution(record_id, sha256, Status.ORACLE_UNAVAILABLE, reason)

        try:
            path = self.blob_path(sha256)
        except StoreError as error:
            return unavailable(str(error))
        if not path.is_file():
            return unavailable("blob missing from the store")
        try:
            found, size = sha256_file(path)
        except OSError as error:
            return unavailable(f"blob unreadable: {error}")
        if found != sha256:
            return unavailable(f"blob fails its hash (found {found})")
        if size_bytes is not None and size != size_bytes:
            return unavailable(f"blob has {size} bytes, the manifest names {size_bytes}")
        return Resolution(record_id, sha256, Status.AVAILABLE, path=path)

    def load(self, sha256: str, size_bytes: int | None = None) -> bytes | None:
        """The verified bytes of a blob, or None when the oracle is unavailable."""
        try:
            data = self.blob_path(sha256).read_bytes()
        except (OSError, StoreError):
            return None
        if hashlib.sha256(data).hexdigest() != sha256:
            return None
        if size_bytes is not None and len(data) != size_bytes:
            return None
        return data

    def check(self) -> list[str]:
        """Whole-store integrity: index, blobs and entries agree; every blob hashes to its name."""
        problems: list[str] = []
        indexed = self.index()
        on_disk: set[str] = set()
        for path in sorted((self.root / "blobs").glob("*/*")):
            name = path.name
            if not _SHA256.match(name) or path.parent.name != name[:2]:
                problems.append(f"stray file {path.relative_to(self.root).as_posix()}")
                continue
            on_disk.add(name)
            resolution = self.resolve(name, name)
            if resolution.status is not Status.AVAILABLE:
                problems.append(f"blob {name}: {resolution.reason}")
        problems.extend(
            f"index names {sha} but the blob is missing" for sha in sorted(indexed - on_disk)
        )
        problems.extend(f"blob {sha} is not in the index" for sha in sorted(on_disk - indexed))
        entries = [*(self.root / "corpora").rglob("*.json"), *(self.root / "inputs").glob("*.json")]
        for path in sorted(entries):
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("sha256") not in on_disk:
                problems.append(
                    f"entry {path.relative_to(self.root).as_posix()} names a missing blob"
                )
        from tools.parity.store.snapshot_capture import check_snapshot_captures

        problems.extend(check_snapshot_captures(self))
        return problems


def locate(environ: Mapping[str, str] | None = None) -> OracleStore | None:
    """The store of this machine, or None when there is none (hosted runners: no oracle).

    A configured root inside the repository is refused, never treated as absent.
    """
    root = default_root(environ)
    if root is None:
        return None
    refuse_inside_repository(root, "store")
    if not (root / "store.json").is_file():
        return None
    return OracleStore.open(root)


def resolve_oracle(store: OracleStore | None, ref: Mapping[str, Any]) -> Resolution:
    """Resolve one `private_records` entry of a public manifest; no store: `oracle_unavailable`."""
    if store is None:
        return Resolution(
            ref["record_id"], ref["sha256"], Status.ORACLE_UNAVAILABLE, "no private store here"
        )
    return store.resolve(ref["record_id"], ref["sha256"], ref["size_bytes"])


def load_oracle(store: OracleStore | None, ref: Mapping[str, Any]) -> bytes | None:
    """The verified oracle bytes a comparison needs, or None (the comparison is then
    `oracle_unavailable`, `tools.parity.verdict.evaluate`)."""
    if store is None:
        return None
    return store.load(ref["sha256"], ref["size_bytes"])
