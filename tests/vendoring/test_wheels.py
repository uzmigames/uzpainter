"""The pinned MCP SDK wheel closure (`thirdparty/python-wheels/`, `tools/vendoring/wheels.py`;
phase0.7_toolchain-cpython, items 2.4 and 3.5).

The folder checks need nothing; the comparison with PyPI's published hashes needs the network
(skipped with the reason when offline or `UZP_OFFLINE=1`). The unit tests run on synthetic wheels.
"""

from __future__ import annotations

import base64
import email.message
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

import tools.vendoring.wheels as wheels_module
from tools.vendoring.wheels import (
    FOLDER,
    NOT_INSTALLED,
    WHEELS,
    Wheel,
    closure_problems,
    folder_problems,
    installed_files,
    site_packages_problems,
    wheel_problems,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _wheel(
    name: str,
    version: str,
    requires: tuple[str, ...] = (),
    files: dict[str, bytes] | None = None,
    licence: bytes = b"MIT licence text\n",
) -> tuple[Wheel, bytes]:
    """A synthetic wheel with METADATA, a licence file, `files` and a matching RECORD."""
    dist_info = f"{name}-{version}.dist-info"
    meta = [f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"]
    meta += [f"Requires-Dist: {r}\n" for r in requires]
    content = {
        f"{name}/__init__.py": b"",
        **(files or {}),
        f"{dist_info}/METADATA": "".join(meta).encode(),
        f"{dist_info}/licenses/LICENSE": licence,
    }
    record = "".join(
        f"{path},sha256="
        f"{base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},"
        f"{len(data)}\n"
        for path, data in content.items()
    )
    record += f"{dist_info}/RECORD,,\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for path, data in content.items():
            zf.writestr(path, data)
        zf.writestr(f"{dist_info}/RECORD", record)
    data = buffer.getvalue()
    filename = f"{name}-{version}-py3-none-any.whl"
    digest = hashlib.sha256(data).hexdigest()
    return Wheel(filename, "00/00/", digest, "MIT", ("LICENSE",)), data


def _metadata(wheel: Wheel, data: bytes) -> email.message.Message:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return email.message_from_bytes(zf.read(f"{wheel.dist_info}/METADATA"))


# ---------------------------------------------------------------------------------------------
# Unit tests (synthetic wheels)


def test_wheel_problems_detect_hash_and_licence() -> None:
    wheel, data = _wheel("mcp", "2.3.0")
    assert wheel_problems(wheel, data) == []
    tampered = data + b"\0"
    assert "sha256" in wheel_problems(wheel, tampered)[0]
    empty, empty_data = _wheel("mcp", "2.3.0", licence=b"  \n")
    assert wheel_problems(empty, empty_data) == [
        f"{empty.filename}: licence file mcp-2.3.0.dist-info/licenses/LICENSE missing or empty"
    ]


def test_wheel_problems_reject_unsupported_install_scheme() -> None:
    wheel, data = _wheel("tool", "1.0", files={"tool-1.0.data/purelib/x.py": b""})
    assert wheel_problems(wheel, data) == [
        f"{wheel.filename}: installation scheme tool-1.0.data/purelib/ is not supported by the "
        "install"
    ]
    scripts, scripts_data = _wheel("tool", "1.0", files={"tool-1.0.data/scripts/run.py": b""})
    assert wheel_problems(scripts, scripts_data) == []


def test_closure_problems_follow_markers_and_extras() -> None:
    root = _wheel(
        "mcp",
        "2.3.0",
        (
            "anyio>=4.9",
            "pyjwt[crypto]>=2.10",
            'pywin32>=311; sys_platform == "win32"',
            'uvloop; sys_platform != "win32"',
            'rich; extra == "rich"',
        ),
    )
    anyio = _wheel("anyio", "4.15.1")
    pyjwt = _wheel("pyjwt", "2.15.1", ('cryptography>=3.4; extra == "crypto"',))
    pywin32 = _wheel("pywin32", "312")
    cryptography = _wheel("cryptography", "50.0.2")
    complete = [root, anyio, pyjwt, pywin32, cryptography]
    assert closure_problems([_metadata(w, d) for w, d in complete]) == []
    # A missing requirement reached only through an extra, a version outside the specifier and
    # a pinned wheel nothing needs.
    old_anyio = _wheel("anyio", "4.0.0")
    unneeded = _wheel("rich", "14.0.0")
    broken = [root, old_anyio, pyjwt, pywin32, unneeded]
    assert sorted(closure_problems([_metadata(w, d) for w, d in broken])) == [
        "anyio>=4.9 (required by mcp) is pinned at 4.0.0",
        'cryptography>=3.4; extra == "crypto" (required by pyjwt[crypto]) is not pinned',
        "rich is pinned but no requirement of the closure needs it",
    ]


def test_site_packages_problems_detect_extra_missing_and_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel, data = _wheel("mcp", "2.3.0", files={"mcp/server.py": b"print('x')\n"})
    site = tmp_path / "site-packages"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(site)
    files = installed_files(wheel, data)
    assert set(files) == {
        "mcp/__init__.py",
        "mcp/server.py",
        "mcp-2.3.0.dist-info/METADATA",
        "mcp-2.3.0.dist-info/licenses/LICENSE",
        "mcp-2.3.0.dist-info/RECORD",
    }
    monkeypatch.setattr(wheels_module, "WHEELS", (wheel,))
    assert site_packages_problems(site, {wheel.filename: data}) == []
    (site / "mcp" / "__pycache__").mkdir()
    (site / "mcp" / "__pycache__" / "server.cpython-313.pyc").write_bytes(b"cache")
    assert site_packages_problems(site, {wheel.filename: data}) == []
    (site / "mcp" / "server.py").write_bytes(b"print('y')\n")
    (site / "mcp" / "extra.py").write_bytes(b"")
    (site / "mcp" / "__init__.py").unlink()
    assert site_packages_problems(site, {wheel.filename: data}) == [
        "mcp/__init__.py: not installed",
        "mcp/server.py: differs from the wheel's RECORD",
        "mcp/extra.py: installed but in no pinned wheel",
    ]


# ---------------------------------------------------------------------------------------------
# 3.5 The vendored closure


def test_folder_matches_pins() -> None:
    """3.5: every wheel in the folder is pinned, hashes to its recorded SHA-256, names itself in
    METADATA and carries its recorded licence and notice files; the closure is complete and
    minimal for CPython 3.13 on Windows x64; MANIFEST.json and ORIGIN.md are current."""
    assert folder_problems(REPO_ROOT) == []


def test_every_wheel_in_the_inventory() -> None:
    """3.5: the dependency inventory (`docs/licensing-and-clean-room.md` §3) lists every wheel
    with its version and licence; `ORIGIN.md` records its licence files and SHA-256."""
    inventory = (REPO_ROOT / "docs" / "licensing-and-clean-room.md").read_text(encoding="utf-8")
    row = next(line for line in inventory.splitlines() if f"`{FOLDER}/`" in line)
    origin = (REPO_ROOT / FOLDER / "ORIGIN.md").read_text(encoding="utf-8")
    for wheel in WHEELS:
        assert f"{wheel.project} {wheel.version} (" in row, wheel.filename
        if len(wheel.licence) < 40:
            assert f"{wheel.project} {wheel.version} ({wheel.licence})" in row, wheel.filename
        line = next(line for line in origin.splitlines() if f"[`{wheel.filename}`]" in line)
        assert f"`{wheel.sha256}`" in line
        for licence_file in wheel.licence_files:
            assert f"`{licence_file}`" in line
    for blocker in {w.release_blocker.split(":", 1)[0] for w in WHEELS if w.release_blocker}:
        assert re.fullmatch(r"RB-[A-Z-]+", blocker)
        assert blocker in row and f"**release blocker** — {blocker}" in origin
    manifest = json.loads((REPO_ROOT / FOLDER / "MANIFEST.json").read_text(encoding="utf-8"))
    assert [w["sha256"] for w in manifest["wheels"]] == [w.sha256 for w in WHEELS]


def test_build_leaves_out_the_same_folders() -> None:
    """`build.zig` removes exactly the wheel folders `NOT_INSTALLED` names."""
    script = (REPO_ROOT / "build.zig").read_text(encoding="utf-8")
    match = re.search(r"const wheel_folders_not_installed = \[_\]\[\]const u8\{([^}]*)\}", script)
    assert match is not None
    assert re.findall(r'"([^"]+)"', match.group(1)) == list(NOT_INSTALLED)


def test_gitattributes_keeps_wheel_bytes() -> None:
    lines = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert f"/{FOLDER}/** -text" in lines


def test_pins_match_pypi() -> None:
    """Each pinned URL and SHA-256 is the one PyPI publishes for that file."""
    if os.environ.get("UZP_OFFLINE") == "1":
        pytest.skip("UZP_OFFLINE=1: PyPI is not consulted")
    for wheel in WHEELS:
        project = wheel.project.replace("_", "-")
        url = f"https://pypi.org/pypi/{project}/{wheel.version}/json"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                release = cast(dict[str, Any], json.load(response))
        except (urllib.error.URLError, TimeoutError) as error:
            pytest.skip(f"PyPI not reachable: {error}")
        published = {f["filename"]: f for f in release["urls"]}
        assert wheel.filename in published, wheel.filename
        assert published[wheel.filename]["digests"]["sha256"] == wheel.sha256
        assert published[wheel.filename]["url"] == wheel.url
