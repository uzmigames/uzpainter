"""The pinned wheel closure of the official MCP Python SDK, installed into `Lib\\site-packages\\`
beside `UzPainter.exe` (`docs/architecture/11-mcp-server.md`, `13-engine-integration.md` §5;
`docs/licensing-and-clean-room.md` §3; task `phase0.7_toolchain-cpython`).

The embeddable CPython package has no pip, so the closure is vendored as wheels: every wheel the
root requirement `ROOT_REQUIREMENT` needs on CPython 3.13 for Windows x64 (resolved once with
`RESOLVE_COMMAND`, then pinned here) is taken from PyPI by URL and SHA-256 and kept byte-equal in
`thirdparty/python-wheels/` with `MANIFEST.json` and `ORIGIN.md`. `zig build painter` unpacks the
wheels into `zig-out/bin/Lib/site-packages/` (`build.zig`, `installWheels`).

    python -m tools.vendoring.wheels import [--cache <dir>]
    python -m tools.vendoring.wheels check [--site-packages <dir>]

`import` downloads the pinned wheels (or reuses the cache), checks hash, metadata, licence files
and the closure, then writes the folder; `check` re-checks the folder and, with
`--site-packages`, that an installed `Lib\\site-packages\\` holds exactly the wheels' files
(their `RECORD` hashes).
"""

from __future__ import annotations

import argparse
import base64
import csv
import email
import email.message
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tools.vendoring.hashing import sha256_hex
from tools.vendoring.thirdparty import default_cache

FOLDER = "thirdparty/python-wheels"
METADATA_FILES = frozenset({"MANIFEST.json", "ORIGIN.md"})
ROOT_REQUIREMENT = "mcp==2.3.0"
PYPI_FILES = "https://files.pythonhosted.org/packages/"
RETRIEVED = "2026-10-10"
RESOLVE_COMMAND = (
    "python -m pip download mcp==2.3.0 --only-binary=:all: --platform win_amd64 "
    "--python-version 3.13 --implementation cp --abi cp313 --abi abi3 --abi none -d <dir>"
)
IMPORTER = (
    "Rulebook task `phase0.7_toolchain-cpython`, run with `python -m tools.vendoring.wheels "
    "import` for UzmiGames"
)
# The embedded interpreter the closure is resolved for (`thirdparty/cpython/`), as environment
# markers (PEP 508).
TARGET_ENVIRONMENT: dict[str, str] = {
    "implementation_name": "cpython",
    "implementation_version": "3.13.16",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "platform_release": "10",
    "platform_system": "Windows",
    "platform_version": "10.0.26200",
    "python_full_version": "3.13.16",
    "python_version": "3.13",
    "sys_platform": "win32",
}
# Wheel content not installed into site-packages: console scripts (`<name>.data/scripts/`), and
# the top-level folders below with the reason. `build.zig` (`wheel_folders_not_installed`) removes
# the same folders after unpacking.
SKIPPED_DATA_SCHEME = "scripts"
NOT_INSTALLED: dict[str, str] = {
    "pythonwin": (
        "Pythonwin, pywin32's GUI IDE: `Pythonwin.exe`, `win32ui.pyd`, `win32uiole.pyd` and "
        "`dde.pyd` import the MFC runtime `mfc140u.dll`, which is not shipped (measured with "
        "`tools.toolchain.dll_closure`), so they could not load on a clean machine; the MCP SDK "
        "does not use them"
    ),
    "adodbapi": (
        "pywin32's ADO database package, the one LGPL-2.1 component of the closure; the MCP SDK "
        "does not use it"
    ),
}

RB_NATIVE_NOTICES = (
    "RB-WHEEL-NATIVE-NOTICES: a native extension may contain statically linked third-party "
    "code (Rust crates, C libraries) that its wheel does not enumerate; those notices are "
    "collected for the release `NOTICE` (`phase5.2_packaging`) before a release"
)


@dataclass(frozen=True)
class Wheel:
    """One pinned wheel: its PyPI file, hash, licence and the licence and notice files it
    carries in `<dist-info>/licenses/`."""

    filename: str
    pypi_dir: str
    sha256: str
    licence: str
    licence_files: tuple[str, ...]
    notes: tuple[str, ...] = ()
    release_blocker: str | None = None

    @property
    def project(self) -> str:
        return self.filename.split("-")[0]

    @property
    def version(self) -> str:
        return self.filename.split("-")[1]

    @property
    def url(self) -> str:
        return f"{PYPI_FILES}{self.pypi_dir}{self.filename}"

    @property
    def dist_info(self) -> str:
        return f"{self.project}-{self.version}.dist-info"

    @property
    def native(self) -> bool:
        return not self.filename.endswith("-none-any.whl")


WHEELS: tuple[Wheel, ...] = (
    Wheel(
        "annotated_types-0.8.0-py3-none-any.whl",
        "99/91/8acff4f5e50511b911bbccb72b8628a49c68ce14148cd9f6431094859a90/",
        "f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "anyio-4.15.1-py3-none-any.whl",
        "12/b8/4bd346e22b28902df4d651910f5242c28d84e4a5c2435ca5c3f797ed7e2e/",
        "6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "attrs-26.1.0-py3-none-any.whl",
        "64/b4/17d4b0b2a2dc85a6df63d1157e028ed19f90d4cd97c36717afef2bc2f395/",
        "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "cffi-2.1.1-cp313-cp313-win_amd64.whl",
        "60/a6/8b149b2c3f2e11aaa1618ef64500b45f50f22c57a977a4dff1aff1f91042/",
        "1aa5645c30469b09530c4ebca77ebf8f17618293c58f8549cb1a543a50236e7d",
        licence="MIT-0",
        licence_files=("LICENSE",),
        release_blocker=RB_NATIVE_NOTICES,
    ),
    Wheel(
        "click-8.5.0-py3-none-any.whl",
        "58/50/6c0d534c5f134586a8e1ba4e330569e32f057e33372ae556463212fb4cd3/",
        "255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360",
        licence="BSD-3-Clause",
        licence_files=("LICENSE.txt",),
    ),
    Wheel(
        "cryptography-50.0.2-cp311-abi3-win_amd64.whl",
        "9a/4f/adfc442765721292fff86d314ce385d3249d22db42295c0dd057727b60f3/",
        "7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c",
        licence="Apache-2.0 OR BSD-3-Clause",
        licence_files=("LICENSE", "LICENSE.APACHE", "LICENSE.BSD"),
        notes=(
            (
                "Stable-ABI wheel (`cp311-abi3`): its extension imports `python3.dll` of the "
                "embeddable package. cryptography's installation documentation states that its "
                "wheels statically link OpenSSL."
            ),
        ),
        release_blocker=RB_NATIVE_NOTICES,
    ),
    Wheel(
        "h11-0.16.0-py3-none-any.whl",
        "04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/",
        "63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86",
        licence="MIT",
        licence_files=("LICENSE.txt",),
    ),
    Wheel(
        "httpcore2-2.13.1-py3-none-any.whl",
        "09/ba/a4568248771ce81957bfb7cc600264a40fbcda092391ee1c415c50be4bea/",
        "e1e05d4f25f7d7d496bfb96748f6f4b67657b03da069b3a68c36069f3db73d0a",
        licence="BSD-3-Clause",
        licence_files=("LICENSE.md",),
    ),
    Wheel(
        "httpx2-2.13.1-py3-none-any.whl",
        "d8/9c/6fe8931fd9f381042a9e4c7d5a7b4cbf7016b252bec0c99a49fce42c3326/",
        "6dff50fabc270ee5fd25d845d0b078ed20564579744d6d962850975996d2f9a4",
        licence="BSD-3-Clause",
        licence_files=("LICENSE.md",),
    ),
    Wheel(
        "idna-3.20-py3-none-any.whl",
        "58/a2/bb081bab032533a855d44de1d56f8e8426114ff1ba5d1f07a438a0a654f8/",
        "ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c",
        licence="BSD-3-Clause",
        licence_files=("LICENSE.md",),
    ),
    Wheel(
        "jsonschema-4.26.0-py3-none-any.whl",
        "69/90/f63fb5873511e014207a475e2bb4e8b2e570d655b00ac19a9a0ca0a385ee/",
        "d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce",
        licence="MIT",
        licence_files=("COPYING",),
    ),
    Wheel(
        "jsonschema_specifications-2025.9.1-py3-none-any.whl",
        "41/45/1a4ed80516f02155c51f51e8cedb3c1902296743db0bbc66608a0db2814f/",
        "98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe",
        licence="MIT",
        licence_files=("COPYING",),
    ),
    Wheel(
        "mcp-2.3.0-py3-none-any.whl",
        "20/d7/4a2878f128df729db3ca04e71bfce26405cc2e0c9ebe19c592feeb4c61b9/",
        "dd0c44c089d16453e8ae31a3877a0054d7a2314caaa81f5e0541b9b1734b2377",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "mcp_types-2.3.0-py3-none-any.whl",
        "ce/48/32583066b155bb5d4507e7887dc88ee23118cc4de8e2a12870c49719e2a8/",
        "968efdbdaedfab06adae40d378a34395f1090c5921d4be3c9cde283aaf76d91d",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "opentelemetry_api-1.45.1-py3-none-any.whl",
        "1e/41/f7dcf80b81ee8e71c1a2b59f14208bc723edbd89ed027a73b175abf6348e/",
        "b31553efa588ae44bc306f863c785c5333a9ecc091248c6ee68b4b6c87fdedfb",
        licence="Apache-2.0",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "pycparser-3.11-py3-none-any.whl",
        "90/11/0e6f11117525ff0eec40ebac3d313376f102df93ca44ad9e893ee85e4f89/",
        "51d5a8ba2be0bbe440b99d2112604c95bbbc3c2748a64260186c541e1729cd80",
        licence="BSD-3-Clause",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "pydantic-2.14.0-py3-none-any.whl",
        "2d/eb/9146591cc819d040475bf7f2be786710c7f7eb8083693bf859728da2ca9c/",
        "15fab1bea6f1dc5003b54fc2ecab230c1fd1dbade2acd4addc52d81e32416d4b",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "pydantic_core-2.50.0-cp313-cp313-win_amd64.whl",
        "5e/50/dbdb3ba6699d494e59db2f145aeb97990e28d1503bc9f7bdd57eb4c15677/",
        "4f96ccd9368ecbf6685d8f6981584ab72b4f0ffd20685e747737e7e340277b8d",
        licence="MIT",
        licence_files=("LICENSE",),
        release_blocker=RB_NATIVE_NOTICES,
    ),
    Wheel(
        "pyjwt-2.15.1-py3-none-any.whl",
        "50/ca/44de4e75f8aadc457f0634be3b542815078ded46dca30efb960edeecad6e/",
        "42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193",
        licence="MIT",
        licence_files=("AUTHORS.rst", "LICENSE"),
    ),
    Wheel(
        "python_multipart-0.0.32-py3-none-any.whl",
        "e1/04/e8135ebd1ad02c56ec633277529b2602ff99ff634be76cdba5744cf554fd/",
        "ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23",
        licence="Apache-2.0",
        licence_files=("LICENSE.txt",),
    ),
    Wheel(
        "pywin32-312-cp313-cp313-win_amd64.whl",
        "ba/db/36a78e3403099d31d9746d13fdcde5accc43c1155f375a34d15983a479a7/",
        "c53e878d15a1c44788082bfe712a905433473aa38f86375b7cf8b45e3acbaaf9",
        licence=(
            "PSF (metadata); per component: BSD-3-Clause-style (`win32/License.txt`, "
            "`com/License.txt`, `pythonwin/License.txt`), PSF "
            "(`pythonwin/pywin/idle/LICENSE.txt`), Scintilla's HPND-style licence, MIT "
            "(MAPIStubLibrary), LGPL-2.1 (`adodbapi`)"
        ),
        licence_files=(
            "adodbapi/license.txt",
            "com/License.txt",
            "com/win32comext/mapi/src/MAPIStubLibrary/LICENSE",
            "isapi/README.txt",
            "pythonwin/License.txt",
            "pythonwin/Scintilla/License.txt",
            "pythonwin/pywin/idle/LICENSE.txt",
            "win32/License.txt",
        ),
        notes=(
            (
                '`mcp` requires it on Windows (`pywin32>=311; sys_platform == "win32"`); its '
                "`pywin32.pth` adds `win32`, `win32\\lib` and `Pythonwin` to `sys.path` and "
                "loads `pywin32_system32`, so the interpreter imports `site` "
                "(`src/python/python313._pth`)."
            ),
            (
                "`pythonwin/` and `adodbapi/` are not installed (`NOT_INSTALLED`), so no "
                "LGPL-2.1 code and no binary needing the MFC runtime ships; their licence texts "
                "stay in the installed `dist-info/licenses/`."
            ),
        ),
    ),
    Wheel(
        "referencing-0.37.0-py3-none-any.whl",
        "2c/58/ca301544e1fa93ed4f80d724bf5b194f6e4b945841c5bfd555878eea9fcb/",
        "381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231",
        licence="MIT",
        licence_files=("COPYING",),
    ),
    Wheel(
        "rpds_py-2026.9.1-cp313-cp313-win_amd64.whl",
        "31/9c/ba5a9569d719bfdd6ce863df4133ac6a1658cf1b07cc3534c31db729fbbc/",
        "3e93b2cd69a9830be33e03945cd7cda940a0a8bfcfbff41d6144f0cb0d3d8bd9",
        licence="MIT",
        licence_files=("LICENSE",),
        release_blocker=RB_NATIVE_NOTICES,
    ),
    Wheel(
        "sse_starlette-3.5.0-py3-none-any.whl",
        "be/e4/cdda14023c316d71493bc54fdffc3dd006631b88866145c9d3cc33e0f1df/",
        "3e6e1070df3f0f5d9cea81496de92dbb72f6721871d99748ece67441dd8b7997",
        licence="BSD-3-Clause",
        licence_files=("AUTHORS", "LICENSE"),
    ),
    Wheel(
        "starlette-1.7.0-py3-none-any.whl",
        "4e/d6/1ec1b290f9e0fb067899b61e1d37a30c923068bad260b216dbe37a7d2967/",
        "67f8e99895493dd2911a03f11314af6ceebeae4e704bb9f43dfc6a9db151c93e",
        licence="BSD-3-Clause",
        licence_files=("LICENSE.md",),
    ),
    Wheel(
        "truststore-0.10.4-py3-none-any.whl",
        "19/97/56608b2249fe206a67cd573bc93cd9896e1efb9e98bce9c163bcdc704b88/",
        "adaeaecf1cbb5f4de3b1959b42d41f6fab57b2b1666adb59e89cb0b53361d981",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "typing_extensions-4.16.0-py3-none-any.whl",
        "49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/",
        "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
        licence="PSF-2.0",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "typing_inspection-0.4.4-py3-none-any.whl",
        "67/81/4add07e5172b7ac40d8ed5ff580409a7801a4fe26d529bdd915401dabfbe/",
        "65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147",
        licence="MIT",
        licence_files=("LICENSE",),
    ),
    Wheel(
        "uvicorn-0.54.0-py3-none-any.whl",
        "38/0c/b54a4fdd7f90a3af8b02ebc9ce6712c2c208b7926a2f7bad95c33ebbe943/",
        "505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf",
        licence="BSD-3-Clause",
        licence_files=("LICENSE.md",),
    ),
)
WHEEL_BY_FILENAME = {w.filename: w for w in WHEELS}


# ---------------------------------------------------------------------------------------------
# Wheel contents


def metadata(data: bytes, wheel: Wheel) -> email.message.Message:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return email.message_from_bytes(zf.read(f"{wheel.dist_info}/METADATA"))


def wheel_problems(wheel: Wheel, data: bytes) -> list[str]:
    """One wheel's bytes against its pin: hash, name and version in `METADATA`, licence and
    notice files present and not empty, and no installation scheme other than the skipped
    scripts."""
    digest = sha256_hex(data)
    if digest != wheel.sha256:
        return [f"{wheel.filename}: sha256 {digest} != pinned {wheel.sha256}"]
    problems: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        meta = email.message_from_bytes(zf.read(f"{wheel.dist_info}/METADATA"))
        for licence_file in wheel.licence_files:
            path = f"{wheel.dist_info}/licenses/{licence_file}"
            if path not in names or not zf.read(path).strip():
                problems.append(f"{wheel.filename}: licence file {path} missing or empty")
    if canonicalize_name(str(meta["Name"])) != canonicalize_name(wheel.project):
        problems.append(f"{wheel.filename}: METADATA names {meta['Name']}")
    if str(meta["Version"]) != wheel.version:
        problems.append(f"{wheel.filename}: METADATA version {meta['Version']}")
    data_dir = f"{wheel.project}-{wheel.version}.data/"
    schemes = {n[len(data_dir) :].split("/", 1)[0] for n in names if n.startswith(data_dir)}
    problems += [
        f"{wheel.filename}: installation scheme {data_dir}{s}/ is not supported by the install"
        for s in sorted(schemes - {SKIPPED_DATA_SCHEME})
    ]
    return problems


def closure_problems(metadatas: Sequence[email.message.Message]) -> list[str]:
    """The pinned wheels against the requirements they declare for `TARGET_ENVIRONMENT`,
    starting from `ROOT_REQUIREMENT`: every requirement reached (with the extras requested)
    must be pinned at a version its specifier allows, and every pinned wheel must be reached."""
    by_project = {canonicalize_name(str(m["Name"])): m for m in metadatas}
    problems: list[str] = []
    reached: dict[str, set[str]] = {}
    pending: list[tuple[Requirement, str]] = [(Requirement(ROOT_REQUIREMENT), "the root")]
    while pending:
        requirement, required_by = pending.pop()
        name = canonicalize_name(requirement.name)
        meta = by_project.get(name)
        if meta is None:
            problems.append(f"{requirement} (required by {required_by}) is not pinned")
            continue
        version = str(meta["Version"])
        if not requirement.specifier.contains(version, prereleases=True):
            problems.append(f"{requirement} (required by {required_by}) is pinned at {version}")
        done = reached.setdefault(name, set())
        for extra in sorted(({""} | set(requirement.extras)) - done):
            done.add(extra)
            label = f"{meta['Name']}[{extra}]" if extra else str(meta["Name"])
            for line in cast(list[str], meta.get_all("Requires-Dist") or []):
                dependency = Requirement(line)
                marker = dependency.marker
                if extra == "":
                    wanted = marker is None or marker.evaluate({**TARGET_ENVIRONMENT, "extra": ""})
                else:
                    wanted = (
                        marker is not None
                        and marker.evaluate({**TARGET_ENVIRONMENT, "extra": extra})
                        and not marker.evaluate({**TARGET_ENVIRONMENT, "extra": ""})
                    )
                if wanted:
                    pending.append((dependency, label))
    problems += [
        f"{project} is pinned but no requirement of the closure needs it"
        for project in sorted(set(by_project) - set(reached))
    ]
    return problems


def installed_files(wheel: Wheel, data: bytes) -> dict[str, tuple[str, int]]:
    """The files the wheel installs into site-packages, from its `RECORD`:
    `path -> (urlsafe base64 SHA-256 without padding, size)`. `RECORD` lists itself without a
    hash; its entry carries the hash of its bytes in the wheel. Console scripts and the
    `NOT_INSTALLED` folders are left out."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        record_bytes = zf.read(f"{wheel.dist_info}/RECORD")
    record = record_bytes.decode("utf-8")
    skipped = (
        f"{wheel.project}-{wheel.version}.data/{SKIPPED_DATA_SCHEME}/",
        *(f"{folder}/" for folder in NOT_INSTALLED),
    )
    files: dict[str, tuple[str, int]] = {}
    for row in csv.reader(io.StringIO(record)):
        if not row:
            continue
        path, digest, size = row
        if not digest or path.startswith(skipped):
            continue
        algorithm, _, value = digest.partition("=")
        if algorithm != "sha256":
            raise ValueError(f"{wheel.filename}: RECORD hash {algorithm} for {path}")
        files[path] = (value, int(size))
    files[f"{wheel.dist_info}/RECORD"] = (record_digest(record_bytes), len(record_bytes))
    return files


def record_digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def site_packages_problems(site_packages: Path, wheels: Mapping[str, bytes]) -> list[str]:
    """An installed `Lib\\site-packages\\` against the wheels: every file of every `RECORD`
    present with its hash and size, and no other file (`__pycache__` folders excepted)."""
    expected: dict[str, tuple[str, int]] = {}
    for wheel in WHEELS:
        expected.update(installed_files(wheel, wheels[wheel.filename]))
    problems: list[str] = []
    for path, (digest, size) in sorted(expected.items()):
        target = site_packages / path
        if not target.is_file():
            problems.append(f"{path}: not installed")
            continue
        content = target.read_bytes()
        if len(content) != size or record_digest(content) != digest:
            problems.append(f"{path}: differs from the wheel's RECORD")
    for target in sorted(p for p in site_packages.rglob("*") if p.is_file()):
        rel = target.relative_to(site_packages).as_posix()
        if rel not in expected and "__pycache__" not in rel.split("/"):
            problems.append(f"{rel}: installed but in no pinned wheel")
    return problems


# ---------------------------------------------------------------------------------------------
# Folder, manifest, ORIGIN.md


def fetch(wheel: Wheel, cache: Path) -> bytes:
    """The pinned wheel from `cache`, downloaded if absent. Raises `ValueError` on a hash
    mismatch."""
    path = cache / wheel.filename
    if path.is_file() and sha256_hex(path.read_bytes()) == wheel.sha256:
        return path.read_bytes()
    request = urllib.request.Request(wheel.url, headers={"User-Agent": "uzpainter-vendoring"})
    with urllib.request.urlopen(request, timeout=300) as response:
        data = cast(bytes, response.read())
    digest = sha256_hex(data)
    if digest != wheel.sha256:
        raise ValueError(f"{wheel.url} hashes to {digest}, pinned {wheel.sha256}")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def manifest() -> dict[str, object]:
    return {
        "root_requirement": ROOT_REQUIREMENT,
        "target_environment": TARGET_ENVIRONMENT,
        "resolve_command": RESOLVE_COMMAND,
        "wheels": [
            {
                "filename": w.filename,
                "project": w.project,
                "version": w.version,
                "url": w.url,
                "sha256": w.sha256,
                "native": w.native,
                "licence": w.licence,
                "licence_files": [f"{w.dist_info}/licenses/{f}" for f in w.licence_files],
                "release_blocker": w.release_blocker,
            }
            for w in WHEELS
        ],
    }


def render_origin(sizes: Mapping[str, int]) -> str:
    blockers = sorted({w.release_blocker for w in WHEELS if w.release_blocker})
    lines = [
        "# Origin of the MCP SDK wheel closure",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Upstream | https://github.com/modelcontextprotocol/python-sdk (the official MCP "
        "Python SDK) and PyPI |",
        f"| Root requirement | `{ROOT_REQUIREMENT}` |",
        "| Target | CPython 3.13.16, Windows x64 (`thirdparty/cpython/`): "
        + ", ".join(f"`{k}` = `{v}`" for k, v in TARGET_ENVIRONMENT.items())
        + " |",
        f"| Resolved with | `{RESOLVE_COMMAND}` (pip is unsupported in the embeddable package; "
        "the resolution is pinned below and re-checked by `closure_problems`) |",
        f"| Retrieved | {RETRIEVED} |",
        f"| Importer | {IMPORTER} |",
        "| Distribution role | shipped: unpacked into `Lib\\site-packages\\` beside "
        "`UzPainter.exe` by `zig build painter`, without console scripts "
        "(`<name>.data/scripts/`) and without "
        + "; ".join(f"`{folder}/` ({why})" for folder, why in NOT_INSTALLED.items())
        + "; the wheels themselves are build inputs |",
        "",
        "Every wheel is byte-equal to the PyPI file at its URL (`MANIFEST.json`, "
        "`tools/vendoring/wheels.py`). Licence and notice files are the ones each wheel carries "
        "in `<dist-info>/licenses/`; they are installed with the wheel.",
        "",
        "## Licence inventory",
        "",
    ]
    if blockers:
        for blocker in blockers:
            names = ", ".join(f"`{w.project}`" for w in WHEELS if w.release_blocker == blocker)
            lines.append(f"- Status: **release blocker** — {blocker} (wheels: {names})")
    lines.append(
        "- Every other wheel: confirmed against the pinned file (licence metadata, licence and "
        "notice files, hash)."
    )
    lines += [
        "",
        f"## Wheels ({len(WHEELS)})",
        "",
        "| Wheel | Bytes | Licence | Licence and notice files | SHA-256 | Native |",
        "|---|---|---|---|---|---|",
    ]
    for w in WHEELS:
        files = ", ".join(f"`{f}`" for f in w.licence_files)
        lines.append(
            f"| [`{w.filename}`]({w.url}) | {sizes[w.filename]:,} | {w.licence} | {files} | "
            f"`{w.sha256}` | {'yes' if w.native else 'no'} |"
        )
    notes = [(w, n) for w in WHEELS for n in w.notes]
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- `{w.project}`: {n}" for w, n in notes]
    return "\n".join([*lines, ""])


def folder_problems(repo_root: Path) -> list[str]:
    root = repo_root / FOLDER
    problems: list[str] = []
    datas: dict[str, bytes] = {}
    for wheel in WHEELS:
        path = root / wheel.filename
        if not path.is_file():
            problems.append(f"{FOLDER}/{wheel.filename}: missing")
            continue
        datas[wheel.filename] = path.read_bytes()
        problems += wheel_problems(wheel, datas[wheel.filename])
    listed = set(WHEEL_BY_FILENAME) | METADATA_FILES
    problems += [
        f"{FOLDER}/{p.name}: not a pinned wheel"
        for p in sorted(root.iterdir())
        if p.name not in listed
    ]
    if problems:
        return problems
    problems += closure_problems([metadata(datas[w.filename], w) for w in WHEELS])
    recorded = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if recorded != manifest():
        problems.append(f"{FOLDER}/MANIFEST.json differs from the pinned table")
    sizes = {name: len(data) for name, data in datas.items()}
    if (root / "ORIGIN.md").read_text(encoding="utf-8") != render_origin(sizes):
        problems.append(f"{FOLDER}/ORIGIN.md is not current")
    return problems


def read_wheels(repo_root: Path) -> dict[str, bytes]:
    return {w.filename: (repo_root / FOLDER / w.filename).read_bytes() for w in WHEELS}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.vendoring.wheels")
    parser.add_argument("action", choices=("import", "check"))
    parser.add_argument("--cache", type=Path, default=default_cache())
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--site-packages", type=Path)
    args = parser.parse_args(argv)
    root = args.repo_root / FOLDER
    if args.action == "import":
        datas = {w.filename: fetch(w, args.cache) for w in WHEELS}
        problems = [p for w in WHEELS for p in wheel_problems(w, datas[w.filename])]
        problems += closure_problems([metadata(datas[w.filename], w) for w in WHEELS])
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        root.mkdir(parents=True, exist_ok=True)
        for name, data in datas.items():
            (root / name).write_bytes(data)
        (root / "MANIFEST.json").write_bytes((json.dumps(manifest(), indent=2) + "\n").encode())
        sizes = {name: len(data) for name, data in datas.items()}
        (root / "ORIGIN.md").write_bytes(render_origin(sizes).encode("utf-8"))
        print(f"{FOLDER}: {len(WHEELS)} wheels imported")
        return 0
    problems = folder_problems(args.repo_root)
    if not problems and args.site_packages is not None:
        problems = site_packages_problems(args.site_packages, read_wheels(args.repo_root))
    print("\n".join(problems) if problems else f"{FOLDER}: {len(WHEELS)} wheels verified")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
