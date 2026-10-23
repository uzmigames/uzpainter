"""Declared colour sessions within one refresh; the Legacy anchor never changes."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.parity.recorder.environment import ENVELOPE_FIELDS, UNKNOWN, envelope_sha256, file_sha256
from tools.parity.recorder.session import IdentityChanged, PainterIdentity, RecorderError

LEGACY = "legacy"
NON_COLOUR = tuple(f for f in ENVELOPE_FIELDS if f != "colour_configuration_sha256")


def declaration(manifest: Mapping[str, Any]) -> str:
    values = {
        str(s["value"]).replace("\\", "/")
        for s in manifest.get("applied_settings", [])
        if s.get("applied_by") == "environment_variable" and s.get("name") == "OCIO"
    }
    if len(values) > 1 or "" in values:
        raise RecorderError("a golden must name exactly one non-empty OCIO configuration")
    return "ocio:" + next(iter(values)) if values else LEGACY


def known(environment: Mapping[str, Any]) -> None:
    if any(not environment.get(f) or environment[f] == UNKNOWN for f in ENVELOPE_FIELDS):
        raise IdentityChanged("colour session has an unknown environment field")


def same_host(anchor: Mapping[str, Any], environment: Mapping[str, Any]) -> None:
    known(anchor)
    known(environment)
    if any(anchor[f] != environment[f] for f in NON_COLOUR):
        raise IdentityChanged("colour session changed the candidate build or host")


def matches(identity: PainterIdentity, colour: str) -> bool:
    state = identity.colour_management
    if colour == LEGACY:
        return state.get("mode") == "legacy" and not any(
            state.get(k) for k in ("OCIO", "PAINTER_ACE_CONFIG")
        )
    actual = str(state.get("OCIO") or "").replace("\\", "/")
    wanted = colour.removeprefix("ocio:")
    return (
        state.get("mode") == "ocio"
        and (actual == wanted or actual.endswith("/" + wanted))
        and not state.get("PAINTER_ACE_CONFIG")
    )


def bind(ledger: dict[str, Any], identity: PainterIdentity, colour: str) -> None:
    """Pin a declared session and its configuration bytes before recording any golden."""
    if not matches(identity, colour):
        raise RecorderError(f"the running Painter does not match declared colour {colour}")
    environment = identity.environment
    if environment is None:
        raise IdentityChanged("colour session has no environment")
    same_host(ledger["anchor_environment"], environment)
    config_hash = None
    if colour != LEGACY:
        path = Path(str(identity.colour_management["OCIO"]))
        try:
            config_hash = file_sha256(path)
        except OSError as error:
            raise RecorderError(f"cannot read declared OCIO configuration: {path}") from error
    slots = ledger.setdefault("colour_sessions", {})
    previous = slots.get(colour)
    if previous is not None and (
        envelope_sha256(previous["environment"]) != envelope_sha256(environment)
        or previous["configuration_sha256"] != config_hash
    ):
        raise IdentityChanged(f"declared colour session changed: {colour}")
    if previous is None:
        slots[colour] = {"environment": dict(environment), "configuration_sha256": config_hash}


def launch_environment(colour: str, executable: Path) -> dict[str, str | None]:
    settings: dict[str, str | None] = {"OCIO": None, "PAINTER_ACE_CONFIG": None}
    if colour != LEGACY:
        value = colour.removeprefix("ocio:")
        path = Path(value)
        if not path.is_absolute():
            path = executable.parent / path
        if not path.is_file():
            raise RecorderError(f"declared OCIO configuration does not exist: {path}")
        settings["OCIO"] = str(path.resolve())
    return settings
