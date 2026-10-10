"""A golden's recordings from the private store, decoded on demand.

`load(store, manifest_path)` reads the public manifest, loads its private record
(`golden-record`) from the store and exposes every recording's outputs by `output_id`.
Exported maps are decoded at native depth the first time they are asked for. Nothing here is
written anywhere: recorded values stay in memory on the owner's machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.fit.decode import Decoded, decode
from tools.parity.schemas import load_json
from tools.parity.store.store import OracleStore, load_oracle


class OracleUnavailable(Exception):
    """A blob the manifest names is missing from the store or fails its hash."""


@dataclass
class Recording:
    recording_id: str
    condition: str
    outputs: dict[str, dict[str, Any]]


@dataclass
class Golden:
    golden_id: str
    manifest_path: Path
    manifest: dict[str, Any]
    record_sha256: str
    recordings: dict[str, Recording]
    store: OracleStore | None
    _decoded: dict[str, Decoded] = field(default_factory=dict)

    def output(self, recording: str, output_id: str) -> dict[str, Any]:
        return self.recordings[recording].outputs[output_id]

    def map(self, recording: str, output_id: str) -> Decoded:
        """The decoded exported map `output_id` (`<texture set>/<map>`) of one recording."""
        blob = self.output(recording, output_id)["blob"]
        sha = str(blob["sha256"])
        if sha not in self._decoded:
            data = load_oracle(self.store, {"sha256": sha, "size_bytes": blob["size_bytes"]})
            if data is None:
                raise OracleUnavailable(f"{self.golden_id}: blob {sha} unavailable")
            self._decoded[sha] = decode(data)
        return self._decoded[sha]

    def map_sha256(self, recording: str, output_id: str) -> str:
        return str(self.output(recording, output_id)["blob"]["sha256"])

    def maps(self, recording: str) -> list[str]:
        return sorted(
            k for k, o in self.recordings[recording].outputs.items() if o["kind"] == "exported_map"
        )


def load(store: OracleStore | None, manifest_path: Path) -> Golden:
    manifest = load_json(manifest_path)
    refs = {r["record_id"]: r for r in manifest["private_records"]}
    if "golden-record" not in refs:
        raise OracleUnavailable(f"{manifest_path}: no private record")
    data = load_oracle(store, refs["golden-record"])
    if data is None:
        raise OracleUnavailable(f"{manifest['golden_id']}: private record unavailable")
    record = json.loads(data.decode("utf-8"))
    recordings = {
        str(r["recording_id"]): Recording(
            str(r["recording_id"]),
            str(r["condition"]),
            {str(o["output_id"]): o for o in r["outputs"]},
        )
        for r in record["recordings"]
    }
    return Golden(
        str(manifest["golden_id"]),
        manifest_path,
        manifest,
        str(refs["golden-record"]["sha256"]),
        recordings,
        store,
    )
