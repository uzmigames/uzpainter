"""App-local Visual C++ runtime (`thirdparty/vc-runtime/`, phase0.6_toolchain-hardware-slice,
owner answer to q1): every file pinned by SHA-256 and Authenticode signer, metadata current, the
release blocker recorded."""

from __future__ import annotations

import sys
from pathlib import Path

from tools.vendoring.vcruntime import FILES, FOLDER, folder_problems

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_folder_matches_the_pinned_files() -> None:
    """Hashes, metadata and (on Windows, which checks Authenticode) the Microsoft signer."""
    assert folder_problems(REPO_ROOT, check_signature=sys.platform == "win32") == []
    assert {f.name for f in FILES} == {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}


def test_release_blocker_and_bytes_kept() -> None:
    origin = (REPO_ROOT / FOLDER / "ORIGIN.md").read_text(encoding="utf-8")
    assert "**release blocker** — RB-VCRT-TERMS" in origin
    inventory = (REPO_ROOT / "docs" / "licensing-and-clean-room.md").read_text(encoding="utf-8")
    assert "RB-VCRT-TERMS" in inventory and f"{FOLDER}/" in inventory
    lines = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert f"/{FOLDER}/** -text" in lines
