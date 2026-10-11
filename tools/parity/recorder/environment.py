"""Oracle environment record (decisions 034 (a) and 037; task phase0.9_oracle-envelope 2.1-2.2).

Every recorder run carries the environment its golden was recorded under:

- `painter_build`: the build string of the documented API (`PainterIdentity.build_id`);
- `gpu_model`, `driver_version`: every display adapter the host reports (Windows CIM class
  `Win32_VideoController`, properties `Name` and `DriverVersion`), sorted by name and joined
  with ` | ` when there are several, since the documented API does not say which one Painter uses;
- `os_build`: `<major>.<minor>.<build>.<UBR>` from the host's registry
  (`HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion`);
- `colour_configuration_sha256`: SHA-256 of the colour-management readback (the documented
  `OCIO` / `PAINTER_ACE_CONFIG` selection the painter side reports) together with the SHA-256 of
  each configuration file it names, read on the host;
- `recorder_version`: `RECORDER_VERSION` plus a digest of the recorder sources;
- `operator_id`: Iray references only (Tier 3).

Nothing here touches Painter internals: the host fields come from the operating system, the
Painter fields from the documented readbacks the session already makes. A field that cannot be
known is the string `unknown`, never a guess. The full record is private (`golden-private.json`
`environment`); the public manifest names its SHA-256 as an `oracle_environment_record`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from functools import cache
from pathlib import Path
from typing import Any

ENVIRONMENT_SCHEMA = "uzpainter/parity/oracle-environment/1"
RECORDER_VERSION = "uzp-recorder/1"
UNKNOWN = "unknown"
RECORDED = "recorded"
BACKFILLED = "backfilled"
ENVIRONMENT_RECORD_ID = "oracle-environment"
ENVIRONMENT_KIND = "oracle_environment_record"

# Fields that define the oracle environment: two recordings are in the same envelope when these
# are equal and known. `recorder_version`, `operator_id` and `basis` are provenance: recorded,
# never part of the match.
ENVELOPE_FIELDS = (
    "painter_build",
    "gpu_model",
    "driver_version",
    "os_build",
    "colour_configuration_sha256",
)
HOST_FIELDS = ("gpu_model", "driver_version", "os_build")

HostEnvironment = Callable[[], dict[str, str]]

RECORDER_DIR = Path(__file__).resolve().parent
VIDEO_CONTROLLERS = (
    "Get-CimInstance -ClassName Win32_VideoController | "
    "Select-Object Name, DriverVersion | ConvertTo-Json -Compress"
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def video_controllers(
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    """(gpu_model, driver_version) of every display adapter, or `unknown` for each."""
    if sys.platform != "win32":
        return UNKNOWN, UNKNOWN
    try:
        done = run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", VIDEO_CONTROLLERS],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        data = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return UNKNOWN, UNKNOWN
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    adapters = sorted(
        (
            str(item.get("Name") or UNKNOWN).strip(),
            str(item.get("DriverVersion") or UNKNOWN).strip(),
        )
        for item in items
        if isinstance(item, dict)
    )
    if not adapters:
        return UNKNOWN, UNKNOWN
    return " | ".join(a[0] for a in adapters), " | ".join(a[1] for a in adapters)


def os_build() -> str:
    """`<major>.<minor>.<build>.<UBR>` of the running Windows, or `unknown`."""
    if sys.platform != "win32":
        return UNKNOWN
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        ) as key:
            major = winreg.QueryValueEx(key, "CurrentMajorVersionNumber")[0]
            minor = winreg.QueryValueEx(key, "CurrentMinorVersionNumber")[0]
            build = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
            ubr = winreg.QueryValueEx(key, "UBR")[0]
    except OSError:
        return UNKNOWN
    return f"{major}.{minor}.{build}.{ubr}"


def capture_host_environment() -> dict[str, str]:
    """The host fields, read now (the study and the canary read them at every session start)."""
    gpu, driver = video_controllers()
    return {"gpu_model": gpu, "driver_version": driver, "os_build": os_build()}


@cache
def cached_host_environment() -> dict[str, str]:
    """The host fields, read once per host process (the default of a recorder session)."""
    return capture_host_environment()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def colour_configuration_sha256(colour_management: Mapping[str, Any]) -> str:
    """SHA-256 of the colour-management readback and of each configuration file it names."""
    files: dict[str, str] = {}
    for variable in ("OCIO", "PAINTER_ACE_CONFIG"):
        value = colour_management.get(variable)
        if value:
            path = Path(str(value))
            try:
                files[variable] = file_sha256(path) if path.is_file() else "unreadable"
            except OSError:
                files[variable] = "unreadable"
    return sha256_hex(canonical({"colour_management": dict(colour_management), "files": files}))


@cache
def recorder_version() -> str:
    """`RECORDER_VERSION+src.<digest>`: the digest covers every recorder source (line endings
    normalised), so a code change of the recorder is visible in the record."""
    digest = hashlib.sha256()
    sources = [*sorted(RECORDER_DIR.glob("*.py")), RECORDER_DIR / "documented_symbols.json"]
    for path in sources:
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return f"{RECORDER_VERSION}+src.{digest.hexdigest()[:16]}"


def environment_record(
    *,
    painter_build: str,
    colour_management: Mapping[str, Any] | None,
    host: Mapping[str, str],
    operator_id: str | None = None,
    basis: str = RECORDED,
    version: str | None = None,
) -> dict[str, Any]:
    """The environment record of one recorder session (`golden-private.json` `environment`)."""
    record: dict[str, Any] = {
        "schema": ENVIRONMENT_SCHEMA,
        "basis": basis,
        "painter_build": painter_build,
        "gpu_model": str(host.get("gpu_model") or UNKNOWN),
        "driver_version": str(host.get("driver_version") or UNKNOWN),
        "os_build": str(host.get("os_build") or UNKNOWN),
        "colour_configuration_sha256": (
            UNKNOWN if colour_management is None else colour_configuration_sha256(colour_management)
        ),
        "recorder_version": version if version is not None else recorder_version(),
    }
    if operator_id is not None:
        record["operator_id"] = operator_id
    return record


def environment_bytes(environment: Mapping[str, Any]) -> bytes:
    """The bytes the store keeps for an environment record; their SHA-256 is its public hash."""
    return canonical(dict(environment))


def environment_sha256(environment: Mapping[str, Any]) -> str:
    return sha256_hex(environment_bytes(environment))


def envelope_sha256(environment: Mapping[str, Any]) -> str:
    """SHA-256 of the envelope fields only (what must match for oracle-side comparisons)."""
    return sha256_hex(canonical({k: environment.get(k, UNKNOWN) for k in ENVELOPE_FIELDS}))


MATCH, DIFFERS, UNKNOWN_MATCH = "match", "differs", "unknown"


def envelope_match(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> str:
    """`match` when every envelope field is known and equal, `differs` when a known field
    differs (always for a different Painter build), else `unknown`."""
    if a is None or b is None:
        return UNKNOWN_MATCH
    unknown = False
    for field in ENVELOPE_FIELDS:
        left, right = a.get(field, UNKNOWN), b.get(field, UNKNOWN)
        if left == UNKNOWN or right == UNKNOWN:
            unknown = True
        elif left != right:
            return DIFFERS
    return UNKNOWN_MATCH if unknown else MATCH
