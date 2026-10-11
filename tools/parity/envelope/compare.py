"""Exact comparison of two recordings of one golden (study, canary and drift reports).

Exported maps are compared by blob SHA-256 first; when the bytes differ they are decoded at
native depth (`tools.parity.fit.decode`) and compared value for value with the statistics of
`tools.parity.fit.stats.difference` (max, mean, nearest-rank p99, differing values, texels).
Equal decoded values with different bytes count as equal and are flagged `bytes_differ`.
Readbacks and captures are compared as JSON after three normalisations, each of an environment
identity (a counter, a path or an installed file's version, never a value Painter computes),
stated here and reported next to the raw result (`other_outputs_differing_raw`):

- the resource-context counter Painter increments per opened project (`projectNN` in resource
  URLs, and as the value of a `context` field) becomes `project#` (as in
  `tools.parity.fit.stability`);
- the `?version=<sha1>` of a resource Painter ships (`resource://starter_assets...`) becomes
  `<installed>`: it names the asset file the installed build carries (an update may ship a new
  one); what the asset does is measured by the maps it produces. The version of a resource a
  golden imports (`resource://projectNN/...`) is kept;
- a path that runs through a recorder work directory (`<UTC stamp>-<session>` run directory)
  is cut to `<run>` plus what follows, because every run stages its throwaway project in a new
  directory.

Nothing here writes anything: decoded values stay in memory; results hold numbers and hashes.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.fit.decode import decode
from tools.parity.fit.stability import RESOURCE_CONTEXT, storage_key
from tools.parity.fit.stats import Difference, difference
from tools.parity.recorder.job import sha256_bytes
from tools.parity.recorder.output import READY_FILE, RECORD_FILE
from tools.parity.schemas import load_json
from tools.parity.store.store import OracleStore, load_oracle

RUN_DIRECTORY = re.compile(r"^.*?\d{8}T\d{12}Z-[a-z0-9._-]{1,12}")
SESSION_CONTEXT = re.compile(r"^project\d+$")
SHIPPED_VERSION = re.compile(r"(resource://starter_assets[^?]*\?version=)[0-9a-f]{40}")

EQUAL, DIFFERS, UNAVAILABLE = "equal", "differs", "unavailable"


class SourceUnavailable(Exception):
    """A record or blob cannot be read (missing from the inbox or the store, or bad hash)."""


@dataclass
class RecordSource:
    """A private record and a way to read the blobs it names."""

    record: dict[str, Any]
    record_sha256: str
    read_blob: Callable[[str, int], bytes | None]
    label: str

    def blob(self, sha256: str, size: int) -> bytes:
        data = self.read_blob(sha256, size)
        if data is None:
            raise SourceUnavailable(f"{self.label}: blob {sha256} unavailable")
        return data

    def recording(self, recording_id: str) -> dict[str, Any]:
        for recording in self.record["recordings"]:
            if recording["recording_id"] == recording_id:
                result: dict[str, Any] = recording
                return result
        raise KeyError(recording_id)

    def recording_ids(self) -> list[str]:
        return [str(r["recording_id"]) for r in self.record["recordings"]]


def run_source(run: Path) -> RecordSource:
    """A recorder run in the inbox (`record.json`, `blobs/<sha256>`, `READY`)."""
    if not (run / READY_FILE).is_file():
        raise SourceUnavailable(f"{run}: no READY marker")
    data = (run / RECORD_FILE).read_bytes()

    def read(sha256: str, size: int) -> bytes | None:
        path = run / "blobs" / sha256
        if not path.is_file():
            return None
        blob = path.read_bytes()
        return blob if len(blob) == size and sha256_bytes(blob) == sha256 else None

    return RecordSource(json.loads(data.decode("utf-8")), sha256_bytes(data), read, str(run))


def store_source(
    store: OracleStore | None, manifest_path: Path, record_id: str = "golden-record"
) -> RecordSource:
    """The private record a public manifest names, read from the private store."""
    manifest = load_json(manifest_path)
    refs = {r["record_id"]: r for r in manifest["private_records"]}
    if record_id not in refs:
        raise SourceUnavailable(f"{manifest_path}: no private record {record_id!r}")
    data = load_oracle(store, refs[record_id])
    if data is None:
        raise SourceUnavailable(f"{manifest['golden_id']}: private record unavailable")

    def read(sha256: str, size: int) -> bytes | None:
        return load_oracle(store, {"sha256": sha256, "size_bytes": size})

    return RecordSource(
        json.loads(data.decode("utf-8")), str(refs[record_id]["sha256"]), read, str(manifest_path)
    )


def normalise_text(value: str) -> str:
    value = RESOURCE_CONTEXT.sub(r"\1project#", value)
    value = SHIPPED_VERSION.sub(r"\1<installed>", value)
    return RUN_DIRECTORY.sub("<run>", value.replace("\\", "/"))


def normalised(value: Any) -> Any:
    if isinstance(value, str):
        return normalise_text(value)
    if isinstance(value, list):
        return [normalised(v) for v in value]
    if isinstance(value, dict):
        return {
            normalise_text(str(k)): (
                "project#"
                if k == "context" and isinstance(v, str) and SESSION_CONTEXT.match(v)
                else normalised(v)
            )
            for k, v in value.items()
        }
    return value


def difference_dict(diff: Difference) -> dict[str, Any]:
    result = diff.as_dict()
    for key in ("max", "mean", "p99"):
        if isinstance(result[key], float) and not math.isfinite(result[key]):
            result[key] = None
    return result


@dataclass
class OutputComparison:
    output_id: str
    kind: str
    status: str
    storage: str | None = None
    sha256: tuple[str, str] | None = None
    bytes_differ: bool = False
    equal_raw: bool | None = None
    difference: Difference | None = None
    reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "output_id": self.output_id,
            "kind": self.kind,
            "status": self.status,
        }
        if self.storage is not None:
            result["storage"] = self.storage
        if self.sha256 is not None:
            result["sha256"] = list(self.sha256)
        if self.bytes_differ:
            result["bytes_differ"] = True
        if self.equal_raw is not None:
            result["equal_raw"] = self.equal_raw
        if self.difference is not None:
            result["difference"] = difference_dict(self.difference)
        return result


@dataclass
class PairComparison:
    """One recording against another: every output both recorded, compared exactly."""

    left: str
    right: str
    category: str
    outputs: list[OutputComparison] = field(default_factory=list)
    unpaired: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(o.status == UNAVAILABLE for o in self.outputs):
            return UNAVAILABLE
        return DIFFERS if any(o.status == DIFFERS for o in self.outputs) else EQUAL

    def summary(self) -> dict[str, Any]:
        maps = [o for o in self.outputs if o.kind == "exported_map"]
        others = [o for o in self.outputs if o.kind != "exported_map"]
        differing = [o for o in maps if o.status == DIFFERS and o.difference is not None]
        result: dict[str, Any] = {
            "left": self.left,
            "right": self.right,
            "category": self.category,
            "status": self.status,
            "maps_compared": len(maps),
            "maps_differing": sum(o.status == DIFFERS for o in maps),
            "values_differing": sum(o.difference.differing for o in differing if o.difference),
            "values_compared_in_differing_maps": sum(
                o.difference.total for o in differing if o.difference
            ),
            "other_outputs_compared": len(others),
            "other_outputs_differing": sum(o.status == DIFFERS for o in others),
            "other_outputs_differing_raw": sum(o.equal_raw is False for o in others),
            "unpaired_outputs": len(self.unpaired),
        }
        worst = max(
            differing,
            key=lambda o: (o.difference.max if o.difference else 0.0, o.output_id),
            default=None,
        )
        if worst is not None and worst.difference is not None:
            result["worst_map"] = {
                "output_id": worst.output_id,
                "storage": worst.storage,
                **difference_dict(worst.difference),
            }
        return result

    def differing_outputs(self) -> list[dict[str, Any]]:
        return [o.as_json() for o in self.outputs if o.status != EQUAL]


def compare_map(
    output_id: str, a: dict[str, Any], b: dict[str, Any], left: RecordSource, right: RecordSource
) -> OutputComparison:
    storage = storage_key(a["storage_format"])
    pair = (str(a["blob"]["sha256"]), str(b["blob"]["sha256"]))
    result = OutputComparison(output_id, "exported_map", EQUAL, storage, pair)
    if storage != storage_key(b["storage_format"]):
        result.status, result.reason = DIFFERS, "storage formats differ"
        return result
    if pair[0] == pair[1]:
        return result
    try:
        first = decode(left.blob(pair[0], int(a["blob"]["size_bytes"])))
        second = decode(right.blob(pair[1], int(b["blob"]["size_bytes"])))
    except SourceUnavailable as error:
        result.status, result.reason = UNAVAILABLE, str(error)
        return result
    if first.values.shape != second.values.shape:
        result.status, result.reason = DIFFERS, "map shapes differ"
        return result
    result.difference = difference(first.values, second.values)
    result.bytes_differ = True
    result.status = EQUAL if result.difference.equal else DIFFERS
    return result


def compare_recordings(
    left: RecordSource, left_id: str, right: RecordSource, right_id: str, category: str
) -> PairComparison:
    a_outputs = {str(o["output_id"]): o for o in left.recording(left_id)["outputs"]}
    b_outputs = {str(o["output_id"]): o for o in right.recording(right_id)["outputs"]}
    pair = PairComparison(left_id, right_id, category)
    pair.unpaired = sorted(set(a_outputs) ^ set(b_outputs))
    for output_id in sorted(set(a_outputs) & set(b_outputs)):
        a, b = a_outputs[output_id], b_outputs[output_id]
        if a["kind"] == "exported_map" and b["kind"] == "exported_map":
            pair.outputs.append(compare_map(output_id, a, b, left, right))
            continue
        raw = a == b
        equal = raw or normalised(a) == normalised(b)
        pair.outputs.append(
            OutputComparison(output_id, str(a["kind"]), EQUAL if equal else DIFFERS, equal_raw=raw)
        )
    return pair
