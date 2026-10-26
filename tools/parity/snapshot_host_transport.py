"""Offline H artifact transport of a retained snapshot recording (decision 363, REV364).

A snapshot recording is the private work directory `UzPainter.exe assets snapshot` leaves under
`%LOCALAPPDATA%/UzPainter/snapshot-recordings/<pid>-<stamp>/` (`src/procedural/snapshot_cli.cpp`
`RunSnapshotCommand`; `python/uzpainter_snapshot/bridge.py` `record` and `main`). This module maps
it to the capture/2 `host` section `VerifyHostCapture` resolves (`docs/filter-observations-v2.md`
"H capture"): the original receipt bytes (never re-serialized), the request, and the two scalar
and two RGB exports in round order, each a closed `kind, sha256, size_bytes` reference, with the
private SHA-256 -> path map kept beside it and never printed.

It also relates the receipt's recorder pins to one approved repository revision: the installed
`bridge.py` and `painter_side.py` are copied from the working tree, whose line endings follow
checkout (`core.autocrlf`), so each pin must equal that revision's blob or its explicit CRLF form.

Nothing here admits evidence, imports into a project, decodes pixels or talks to Painter: store
admission of snapshot recordings is a separate contract question, and the native verifier still
decides acceptance.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from python.uzpainter_snapshot import bridge

REPO = Path(__file__).resolve().parents[2]
RECEIPT_SCHEMA = "uzpainter/procedural-capture/1"
RECORDER_SOURCES = {
    "bridge_sha256": "python/uzpainter_snapshot/bridge.py",
    "painter_side_sha256": "python/uzpainter_snapshot/painter_side.py",
}
ROUNDS = (1, 2)
EXPORT_NAMES = ("user0.exr", "user1.exr")
# Exactly what the CLI writes before and the bridge after the capture (no log file is written).
ROOT_ENTRIES = frozenset(
    {"context.json", "request.json", "mesh.obj", "capture.json", *(f"export{i}" for i in ROUNDS)}
)
CONTEXT_KEYS = frozenset(
    {"project_uuid", "revision", "settings", "mesh_path", "bridge_sha256", "painter_side_sha256"}
)
RECEIPT_KEYS = frozenset(
    {
        "schema",
        "recorder",
        "identity",
        "resource",
        "readback",
        "exports",
        "project_uuid",
        "revision",
        "signature",
        "files",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

Variant = Literal["lf", "crlf"]


class TransportRefused(ValueError):
    """A value-free reason for refusing a recording or a recorder pin."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise TransportRefused(reason)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise TransportRefused("non-finite JSON number")


def _finite_float(token: str) -> float:
    """A JSON number token that is a finite double, and zero only when the token is zero: an
    exponent overflow (`1e309`) or underflow (`1e-999`) would otherwise become infinity or 0.0."""
    value = float(token)
    require(math.isfinite(value), "non-finite JSON number")
    require(value != 0.0 or Decimal(token).is_zero(), "floating-point underflow")
    return value


def parse_object(data: bytes, what: str) -> dict[str, Any]:
    """Strict JSON object: UTF-8, no duplicate keys, no NaN, infinities, overflow or underflow."""
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_no_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TransportRefused(f"{what} is not JSON") from None
    require(type(value) is dict, f"{what} is not an object")
    return cast(dict[str, Any], value)


def closed(value: Any, keys: frozenset[str] | set[str], what: str) -> dict[str, Any]:
    require(type(value) is dict and set(value) == set(keys), f"{what} members differ")
    return cast(dict[str, Any], value)


def lowercase_sha256(value: Any) -> bool:
    return type(value) is str and _SHA256.match(value) is not None


# --- recorder pin provenance ---------------------------------------------------------------------


@dataclass(frozen=True)
class RecorderProvenance:
    """The approved revision both recorder pins name, and which line endings each copy had."""

    revision: str
    variants: dict[str, Variant]


def _git_blob(revision: str, path: str, repo: Path) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=repo, capture_output=True, check=False
    )
    require(result.returncode == 0, "the approved revision lacks a recorder source")
    return result.stdout


def recorder_pin_provenance(
    recorder: Any, approved_revision: str, repo: Path = REPO
) -> RecorderProvenance:
    """Both pins must equal the approved revision's blob of their own source, as committed (LF)
    or with every LF written as CRLF; nothing else is accepted, and no other file is consulted."""
    pins = closed(recorder, set(RECORDER_SOURCES), "receipt.recorder")
    require(all(lowercase_sha256(pin) for pin in pins.values()), "recorder pin is not a SHA-256")
    require(_COMMIT.match(approved_revision) is not None, "approved revision is not a commit id")
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{approved_revision}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    require(
        resolved.returncode == 0 and resolved.stdout.strip() == approved_revision,
        "approved revision is not a commit of this repository",
    )
    variants: dict[str, Variant] = {}
    for key, path in RECORDER_SOURCES.items():
        blob = _git_blob(approved_revision, path, repo)
        require(b"\r" not in blob, "a recorder source is committed with CR bytes")
        forms: dict[Variant, str] = {
            "lf": sha256(blob),
            "crlf": sha256(blob.replace(b"\n", b"\r\n")),
        }
        matched = [variant for variant, digest in forms.items() if digest == pins[key]]
        require(len(matched) == 1, "a recorder pin is not the approved revision's source")
        variants[key] = matched[0]
    return RecorderProvenance(approved_revision, variants)


# --- the recording -------------------------------------------------------------------------------


@dataclass(frozen=True)
class HostTransport:
    """The capture/2 `host` section and the private paths of the bytes it names."""

    section: dict[str, Any]
    paths: dict[str, Path] = field(repr=False)
    recorder: dict[str, str]
    source_fingerprints: dict[Path, tuple[str, int]] = field(repr=False)


def _regular_file(path: Path, what: str) -> bytes:
    require(not path.is_symlink() and not path.is_junction(), f"{what} is a link")
    require(path.is_file(), f"{what} is not a regular file")
    return path.read_bytes()


def _entries(directory: Path, expected: frozenset[str] | set[str], what: str) -> None:
    require(not directory.is_symlink() and not directory.is_junction(), f"{what} is a link")
    require(directory.is_dir(), f"{what} is not a directory")
    require({p.name for p in directory.iterdir()} == set(expected), f"{what} entries differ")


def _ref(kind: str, data: bytes) -> dict[str, Any]:
    return {"kind": kind, "sha256": sha256(data), "size_bytes": len(data)}


def _check_exports(receipt: dict[str, Any], recorded_root: Path) -> None:
    """The bridge's two `Success` rounds of its own raw export configuration into
    `<recorded_root>/export1` and `export2`, each reporting exactly its two files."""
    exports = receipt["exports"]
    require(type(exports) is list and len(exports) == len(ROUNDS), "receipt.exports rounds differ")
    for index, entry in zip(ROUNDS, exports, strict=True):
        round_ = closed(entry, {"config", "result"}, "receipt export round")
        config = round_["config"]
        require(type(config) is dict and type(config.get("exportPath")) is str, "export config")
        require(
            Path(config["exportPath"]) == recorded_root / f"export{index}",
            "export round is not this recording's directory",
        )
        require(
            bridge.canonical_state(config)
            == bridge.canonical_state(bridge.export_config(Path(config["exportPath"]))),
            "export config is not the bridge's",
        )
        result = round_["result"]
        require(type(result) is dict and result.get("status") == "Success", "export round failed")
        files = result.get("files")
        require(type(files) is list and all(type(p) is str for p in files), "export result files")
        expected = {Path(config["exportPath"]) / name for name in EXPORT_NAMES}
        require(
            len(files) == len(expected) and {Path(p) for p in files} == expected,
            "export result names other files",
        )


def host_transport(work: Path) -> HostTransport:
    """Map one retained recording to its capture/2 `host` section, checking every join the
    producer guarantees: the exact layout, the context and receipt identity and recorder pins,
    the receipt's `files` hashes against the actual exports, the request against the receipt's
    resource and the readback's effective parameters (the bridge's own checks), and the
    signature the bridge derived."""
    _entries(work, ROOT_ENTRIES, "recording")
    for index in ROUNDS:
        _entries(work / f"export{index}", set(EXPORT_NAMES), f"export{index}")
    receipt_bytes = _regular_file(work / "capture.json", "receipt")
    request_bytes = _regular_file(work / "request.json", "request")
    context_bytes = _regular_file(work / "context.json", "context")
    mesh_bytes = _regular_file(work / "mesh.obj", "mesh")
    exports = {
        f"export{i}/{name}": _regular_file(work / f"export{i}" / name, f"export{i}/{name}")
        for i in ROUNDS
        for name in EXPORT_NAMES
    }

    context = closed(parse_object(context_bytes, "context"), CONTEXT_KEYS, "context")
    receipt = closed(parse_object(receipt_bytes, "receipt"), RECEIPT_KEYS, "receipt")
    require(receipt["schema"] == RECEIPT_SCHEMA, "receipt schema differs")
    for key in ("project_uuid", "revision"):
        require(
            type(receipt[key]) is type(context[key]) and receipt[key] == context[key],
            f"receipt {key} differs from the context",
        )
    require(type(receipt["revision"]) is int and receipt["revision"] >= 0, "receipt revision")
    recorder = closed(receipt["recorder"], set(RECORDER_SOURCES), "receipt.recorder")
    require(
        all(lowercase_sha256(recorder[k]) and recorder[k] == context[k] for k in RECORDER_SOURCES),
        "receipt recorder pins differ from the context",
    )
    # The directory the recording was made in: the CLI writes the mesh at its root, and every
    # export round must lie under this one root. A retained recording may since have moved (its
    # unique `<pid>-<stamp>` name is kept), so `work` itself is matched by name only.
    mesh = context["mesh_path"]
    require(type(mesh) is str, "context mesh is not this recording's")
    recorded_root = Path(mesh).parent
    require(
        Path(mesh).name == "mesh.obj"
        and recorded_root.is_absolute()
        and recorded_root.name == work.name,
        "context mesh is not this recording's",
    )

    files = closed(receipt["files"], set(exports), "receipt.files")
    require(
        all(
            lowercase_sha256(files[name]) and files[name] == sha256(exports[name]) for name in files
        ),
        "receipt files differ from the exports",
    )
    _check_exports(receipt, recorded_root)

    identity = receipt["identity"]
    require(
        type(identity) is dict
        and identity.get("project_open") is False
        and not identity.get("OCIO")
        and not identity.get("PAINTER_ACE_CONFIG"),
        "receipt identity is not the bridge's Legacy capture identity",
    )
    requested = parse_object(request_bytes, "request")
    try:
        request = bridge.capture_request(requested)
        source = bridge.validate_readback(deepcopy(receipt["readback"]), request)
    except (ValueError, KeyError, TypeError):
        raise TransportRefused("request or readback outside the bridge's capture domain") from None
    require(
        receipt["resource"] == request["resource"] == source["resource"],
        "receipt resource differs from the request",
    )
    signature = receipt["signature"]
    require(type(signature) is dict, "receipt signature")
    pin = sha256(source["resource"].encode("utf-8"))
    require(
        signature.get("asset") == "uzasset://snapshot/" + pin
        and bridge.canonical_state(signature.get("params"))
        == bridge.canonical_state(source["parameters"])
        and bridge.canonical_state(signature.get("settings"))
        == bridge.canonical_state(context["settings"]),
        "receipt signature is not the one the bridge derived",
    )

    paths = {
        sha256(receipt_bytes): work / "capture.json",
        sha256(request_bytes): work / "request.json",
    }
    for name, data in exports.items():
        paths[sha256(data)] = work / name
    section = {
        "protocol": "paired-scalar-rgb",
        "receipt": _ref("snapshot_receipt", receipt_bytes),
        "request": _ref("snapshot_request", request_bytes),
        "environment": None,
        "environment_binding": None,
        "scalar_exports": [
            _ref("snapshot_scalar_export", exports[f"export{i}/user0.exr"]) for i in ROUNDS
        ],
        "rgb_exports": [
            _ref("snapshot_rgb_export", exports[f"export{i}/user1.exr"]) for i in ROUNDS
        ],
    }
    source_bytes = {
        work / "capture.json": receipt_bytes,
        work / "request.json": request_bytes,
        work / "context.json": context_bytes,
        work / "mesh.obj": mesh_bytes,
        **{work / name: data for name, data in exports.items()},
    }
    fingerprints = {path: (sha256(data), len(data)) for path, data in source_bytes.items()}
    return HostTransport(section, paths, dict(recorder), fingerprints)
