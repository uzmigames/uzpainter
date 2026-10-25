"""OCIO sessions against the current envelope (decision 309).

The registry's envelope hash covers the five envelope fields of a Legacy session (no `OCIO`, no
`PAINTER_ACE_CONFIG`), so `envelope check` reports `other_environment` for every OCIO session:
the colour configuration hash is one of the five fields. An OCIO golden is recorded only in a
session running the configuration its manifest names (decisions 068 and 099); this module says
when such a session is the current envelope's OCIO identity, from the private store alone:

- anchors: the environment records of the current envelope's admitted goldens whose envelope
  hash is the registry's (or one the canary proved equivalent). Their four non-colour fields are
  the host the canary vouches for (decision 034 (d));
- references: the environment records of the current envelope's admitted goldens whose
  manifest names the same `OCIO` configuration. They must agree on one envelope hash, and their
  non-colour fields must be an anchor's.

The session is admitted (`ocio_reference`) when its build is the current build, its non-colour
fields are an anchor's and its five-field envelope hash is the references'. A host field that
differs is `other_environment` (the Legacy check and canary come first); a colour configuration
that differs is `other_environment` too. No reference, references that disagree or were recorded
under another host, an anchor-less envelope or an unreadable environment record refuse the
check: the first OCIO identity of an envelope needs its own decision. The registry is read,
never changed. A request that names no `OCIO` keeps `refresh.detect`'s answer unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.parity.envelope.refresh import CURRENT_OUTCOME, OTHER_ENVIRONMENT, Detection
from tools.parity.envelope.registry import manifest_root
from tools.parity.recorder.environment import (
    ENVELOPE_FIELDS,
    ENVIRONMENT_RECORD_ID,
    UNKNOWN,
    envelope_sha256,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.store.store import OracleStore, StoreError, load_oracle

OCIO_REFERENCE = "ocio_reference"
COLOUR_FIELD = "colour_configuration_sha256"
HOST_FIELDS = tuple(f for f in ENVELOPE_FIELDS if f != COLOUR_FIELD)


def named_ocio(manifest: Mapping[str, Any]) -> str | None:
    """The `OCIO` configuration a manifest names (applied by environment variable), or None."""
    values = {
        str(setting["value"])
        for setting in manifest.get("applied_settings", [])
        if setting.get("applied_by") == "environment_variable" and setting.get("name") == "OCIO"
    }
    if len(values) > 1:
        raise RecorderError(f"{manifest.get('golden_id')}: names several OCIO {sorted(values)}")
    return next(iter(values), None)


def host_of(environment: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(environment.get(f, UNKNOWN)) for f in HOST_FIELDS)


def ocio_identities(
    current: Mapping[str, Any],
    store: OracleStore | None,
    configuration: str,
    repo_root: Path = REPO_ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(anchors, references) of the current envelope for `configuration`, read from the store."""
    if store is None:
        raise RecorderError("no private store here: the OCIO check reads its environment records")
    known = {current["envelope_sha256"], *current["equivalent_envelopes"]}
    record_id = f"{current['record_prefix']}{ENVIRONMENT_RECORD_ID}"
    anchors: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    for path in sorted(manifest_root(current, repo_root).rglob("*.json")):
        manifest = load_json(path)
        if not isinstance(manifest, dict):
            continue
        refs = [r for r in manifest.get("private_records", []) if r["record_id"] == record_id]
        if not refs:
            continue
        data = load_oracle(store, refs[0])
        if data is None:
            raise RecorderError(f"{path.as_posix()}: its environment record is unreadable")
        environment: dict[str, Any] = json.loads(data.decode("utf-8"))
        if named_ocio(manifest) == configuration:
            references.append(environment)
        elif envelope_sha256(environment) in known:
            anchors.append(environment)
    return anchors, references


def ocio_reference_state(
    running: Mapping[str, Any],
    anchors: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    configuration: str,
) -> tuple[str, str]:
    """(state, reason) of an OCIO session: `ocio_reference` or `other_environment`. Raises
    `RecorderError` when the current envelope gives no single OCIO identity to compare with."""
    hosts = {host_of(a) for a in anchors}
    if not hosts:
        raise RecorderError("no admitted golden of the current envelope carries its identity")
    if not references:
        raise RecorderError(
            f"no admitted golden of the current envelope names OCIO {configuration}: the first "
            "OCIO identity of an envelope needs its own decision"
        )
    hashes = {envelope_sha256(r) for r in references}
    if len(hashes) > 1:
        raise RecorderError(
            f"the {len(references)} admitted goldens naming OCIO {configuration} disagree on "
            f"{len(hashes)} envelope identities"
        )
    if host_of(references[0]) not in hosts:
        raise RecorderError(
            f"the admitted goldens naming OCIO {configuration} were recorded under other host "
            "fields than the current envelope's"
        )
    if host_of(running) not in hosts:
        differing = ", ".join(
            f for i, f in enumerate(HOST_FIELDS) if host_of(running)[i] not in {h[i] for h in hosts}
        )
        return OTHER_ENVIRONMENT, (
            f"host fields differ from the current envelope's ({differing or 'their combination'}):"
            " run the Legacy envelope check and canary first (decision 034 (d))"
        )
    if envelope_sha256(running) != next(iter(hashes)):
        return OTHER_ENVIRONMENT, (
            f"{COLOUR_FIELD} differs from that of the {len(references)} admitted goldens naming "
            f"OCIO {configuration}"
        )
    return OCIO_REFERENCE, (
        f"the five envelope fields equal those of the {len(references)} admitted goldens naming "
        f"OCIO {configuration}, and the host fields equal the current envelope's"
    )


def detect_for_colour(
    found: Detection,
    configuration: str | None,
    store: OracleStore | None,
    repo_root: Path = REPO_ROOT,
) -> tuple[str, str]:
    """(state, reason) of the running Painter for a recording that needs `configuration`
    (None: Legacy, `refresh.detect`'s state unchanged)."""
    if configuration is None or found.state not in (CURRENT_OUTCOME, OTHER_ENVIRONMENT):
        return found.state, ""
    assert found.identity.environment is not None
    anchors, references = ocio_identities(found.current, store, configuration, repo_root)
    return ocio_reference_state(found.identity.environment, anchors, references, configuration)


def recorded_request_environment_matches(
    environment: Mapping[str, Any],
    manifest: Mapping[str, Any],
    current: Mapping[str, Any],
    store: OracleStore | None,
    repo_root: Path = REPO_ROOT,
) -> bool:
    """Apply decision 309 offline to a recorded request, without relabelling its envelope."""
    if environment.get("basis") != "recorded" or any(
        type(environment.get(field)) is not str or environment[field] in ("", UNKNOWN)
        for field in ENVELOPE_FIELDS
    ):
        return False
    if environment["painter_build"] != current["painter_build"]:
        return False
    try:
        configuration = named_ocio(manifest)
        if configuration is None:
            return envelope_sha256(environment) in {
                current["envelope_sha256"],
                *current["equivalent_envelopes"],
            }
        if store is None:
            return False
        anchors, references = ocio_identities(current, store, configuration, repo_root)
        state, _ = ocio_reference_state(environment, anchors, references, configuration)
        return state == OCIO_REFERENCE
    except (RecorderError, StoreError, OSError, ValueError, KeyError, TypeError):
        # Recorded paths, configuration names and host details must not enter caller errors.
        return False
