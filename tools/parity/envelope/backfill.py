"""Back-fill environment records for goldens recorded before they existed (task item 2.3).

For every manifest that names a private record but no `oracle_environment_record`, an
environment record with `basis: backfilled` is written to the private store and its hash
appended to the manifest's `private_records` (the store's own `record` operation). Fields:

- `painter_build`: the manifest's build (the recorder refused any other build, so it is known);
- `colour_configuration_sha256`: computed from the record's colour-management readback when it
  names no configuration file (Legacy mode); `unknown` when it names one (its content at
  recording time cannot be known) or the record cannot be read;
- `gpu_model`, `driver_version`, `os_build`: what the owner states with `--known field=value`,
  else `unknown`; `recorder_version`: `unknown`; Tier 3: `operator_id` `unknown`.

Nothing else of the manifest changes and no recorded output is touched or rewritten; the run
checks that the manifest differs from before only by the appended reference.
"""

from __future__ import annotations

import copy
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.parity.envelope.compare import SourceUnavailable, store_source
from tools.parity.recorder.environment import (
    BACKFILLED,
    ENVIRONMENT_KIND,
    ENVIRONMENT_RECORD_ID,
    HOST_FIELDS,
    UNKNOWN,
    colour_configuration_sha256,
    environment_bytes,
    environment_record,
)
from tools.parity.schemas import environment_problems, load_json
from tools.parity.store.store import OracleStore

PRIVATE_RECORD = "private_oracle_record"


class BackfillError(Exception):
    """A back-fill is refused; the manifest is left as it was."""


def needs_backfill(manifest: Mapping[str, Any], prefix: str = "") -> bool:
    kinds = {r["kind"] for r in manifest["private_records"]}
    ids = {r["record_id"] for r in manifest["private_records"]}
    return (
        f"{prefix}golden-record" in ids
        and ENVIRONMENT_KIND not in kinds
        and PRIVATE_RECORD in kinds
    )


def backfilled_environment(
    manifest: Mapping[str, Any],
    record: Mapping[str, Any] | None,
    known: Mapping[str, str],
) -> dict[str, Any]:
    unknown_fields = set(known) - set(HOST_FIELDS)
    if unknown_fields:
        raise BackfillError(
            f"--known accepts only {list(HOST_FIELDS)}, not {sorted(unknown_fields)}"
        )
    colour: str = UNKNOWN
    if record is not None:
        management = record["key"]["project_settings"].get("colour_management")
        if isinstance(management, dict) and not any(
            management.get(v) for v in ("OCIO", "PAINTER_ACE_CONFIG")
        ):
            colour = colour_configuration_sha256(management)
    environment = environment_record(
        painter_build=str(manifest["software"]["painter"]["build_id"]),
        colour_management=None,
        host={f: known.get(f, UNKNOWN) for f in HOST_FIELDS},
        operator_id=UNKNOWN if manifest["tier"] == "3" else None,
        basis=BACKFILLED,
        version=UNKNOWN,
    )
    environment["colour_configuration_sha256"] = colour
    problems = environment_problems(environment)
    if problems:
        raise BackfillError(f"{manifest['golden_id']}: back-filled record invalid: {problems}")
    return environment


def backfill_manifest(
    store: OracleStore,
    manifest_path: Path,
    known: Mapping[str, str],
    prefix: str = "",
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Back-fill one manifest; returns the environment record written (None when not needed)."""
    from tools.parity.store.manifest import load_manifest, record_file

    manifest = load_manifest(manifest_path)
    if not needs_backfill(manifest, prefix):
        return None
    try:
        record: dict[str, Any] | None = store_source(
            store, manifest_path, f"{prefix}golden-record"
        ).record
    except (SourceUnavailable, OSError, ValueError):
        record = None
    if record is not None and "environment" in record:
        raise BackfillError(
            f"{manifest_path}: its record carries an environment but the manifest names none"
        )
    environment = backfilled_environment(manifest, record, known)
    if dry_run:
        return environment
    before = copy.deepcopy(manifest)
    with tempfile.TemporaryDirectory(prefix="uzp-backfill-") as directory:
        source = Path(directory) / "oracle-environment.json"
        source.write_bytes(environment_bytes(environment))
        updated = record_file(
            store, manifest_path, prefix + ENVIRONMENT_RECORD_ID, ENVIRONMENT_KIND, source
        )
    added = updated["private_records"][len(before["private_records"]) :]
    if (
        updated["private_records"][: len(before["private_records"])] != before["private_records"]
        or [a["record_id"] for a in added] != [prefix + ENVIRONMENT_RECORD_ID]
        or {k: v for k, v in updated.items() if k != "private_records"}
        != {k: v for k, v in before.items() if k != "private_records"}
    ):
        raise BackfillError(
            f"{manifest_path}: the back-fill changed more than one appended reference"
        )
    return environment


def backfill(
    store: OracleStore,
    manifests: list[Path],
    known: Mapping[str, str],
    prefix: str = "",
    dry_run: bool = False,
) -> list[tuple[Path, dict[str, Any]]]:
    unknown_fields = set(known) - set(HOST_FIELDS)
    if unknown_fields:
        raise BackfillError(
            f"--known accepts only {list(HOST_FIELDS)}, not {sorted(unknown_fields)}"
        )
    done: list[tuple[Path, dict[str, Any]]] = []
    for path in manifests:
        environment = backfill_manifest(store, path, known, prefix, dry_run)
        if environment is not None:
            done.append((path, environment))
    return done


def manifest_environment(
    store: OracleStore | None, manifest_path: Path, prefix: str = ""
) -> dict[str, Any] | None:
    """The environment record a manifest names (recorded in the record, or back-filled)."""
    import json

    from tools.parity.store.store import load_oracle

    manifest = load_json(manifest_path)
    refs = {r["record_id"]: r for r in manifest["private_records"]}
    ref = refs.get(prefix + ENVIRONMENT_RECORD_ID)
    if ref is None:
        return None
    data = load_oracle(store, ref)
    if data is None:
        return None
    result: dict[str, Any] = json.loads(data.decode("utf-8"))
    return result
