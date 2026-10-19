"""The durable record of spent held-out sets (decision 303 §3).

One committed file, `parity/reports/phase3/held-out-ledger.json`, maps each held-out pin (the
SHA-256 of a held-out case list) to the SHA-256 of the one candidate it was revealed to. It holds
hashes only and is written in one canonical form (sorted keys, two-space indent, LF), so a spend
shows as a one-line diff. A local report can be deleted, or written to another directory; the
ledger still refuses the held-out set to any other candidate.

Updates take an exclusive lock file next to the ledger and replace the file atomically, so two
certifications never lose each other's spend; a lock left by a run that died must be removed by
hand once no certification is running.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.parity.proc_cert.fingerprint import PROJECT_ROOT

LEDGER_SCHEMA = "uzpainter/parity/proc-cert-ledger/1"
DEFAULT_LEDGER = PROJECT_ROOT / "parity" / "reports" / "phase3" / "held-out-ledger.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LedgerError(Exception):
    """A ledger that is missing, malformed or locked by another certification."""


def ledger_problems(document: Any) -> list[str]:
    """Why `document` is not a ledger (also the repository guard's rule for the file)."""
    if not isinstance(document, dict) or set(document) != {"schema", "spent"}:
        return ["a ledger is an object with exactly schema and spent"]
    if document["schema"] != LEDGER_SCHEMA:
        return [f"schema is not {LEDGER_SCHEMA}"]
    spent = document["spent"]
    if not isinstance(spent, dict):
        return ["spent is not an object"]
    return [
        f"spent entry {pin!r}: a held-out pin mapped to a candidate SHA-256"
        for pin, candidate in spent.items()
        if not (_SHA256.match(pin) and isinstance(candidate, str) and _SHA256.match(candidate))
    ]


def render(spent: Mapping[str, str]) -> bytes:
    """The canonical bytes of a ledger."""
    document = {"schema": LEDGER_SCHEMA, "spent": dict(sorted(spent.items()))}
    return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.lock = self.path.with_name(self.path.name + ".lock")
        self.partial = self.path.with_name(self.path.name + ".partial")
        self.read()  # a missing or malformed ledger is refused before any work

    @classmethod
    def create(cls, path: Path) -> Ledger:
        """Write an empty ledger (a new store of spends; the project's is committed)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(render({}))
        return cls(path)

    def paths(self) -> tuple[Path, ...]:
        """The files a fence must cover: the ledger, its lock and its partial write."""
        return (self.path, self.lock, self.partial)

    def read(self) -> dict[str, str]:
        try:
            document = json.loads(self.path.read_bytes())
        except FileNotFoundError as error:
            raise LedgerError(f"no held-out ledger at {self.path}") from error
        except ValueError as error:
            raise LedgerError(f"{self.path} is not JSON: {error}") from error
        if problems := ledger_problems(document):
            raise LedgerError(f"{self.path}: " + "; ".join(problems))
        spent: dict[str, str] = document["spent"]
        return spent

    def spent_on(self, pin: str) -> str | None:
        return self.read().get(pin)

    def spend(self, pin: str, candidate: str) -> str:
        """Record `pin` as spent on `candidate` unless it already is spent; return the candidate
        it is spent on (the one given, or the earlier one)."""
        try:
            lock = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise LedgerError(
                f"{self.lock} exists: another certification is updating the ledger (remove it "
                "only when none is running)"
            ) from error
        try:
            spent = self.read()
            if pin in spent:
                return spent[pin]
            spent[pin] = candidate
            self.partial.write_bytes(render(spent))
            os.replace(self.partial, self.path)
            return candidate
        finally:
            os.close(lock)
            os.unlink(self.lock)
