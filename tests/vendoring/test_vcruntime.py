"""App-local Visual C++ runtime (`thirdparty/vc-runtime/`, phase0.6_toolchain-hardware-slice,
owner answer to q1): every file pinned by SHA-256 and Authenticode signer, metadata current, the
release blocker recorded."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.vendoring.vcruntime import FILES, FOLDER, SIGNER, folder_problems, signature

REPO_ROOT = Path(__file__).resolve().parents[2]
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Authenticode is a Windows check")


def test_folder_matches_the_pinned_files() -> None:
    """Hashes, metadata and (on Windows, which checks Authenticode) the Microsoft signer."""
    assert folder_problems(REPO_ROOT, check_signature=sys.platform == "win32") == []
    assert {f.name for f in FILES} == {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}


@windows_only
def test_signature_ignores_the_parent_module_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PowerShell 7 parent (hosted CI's default shell) exports a `PSModulePath` whose
    `Microsoft.PowerShell.Security` Windows PowerShell cannot load; inheriting it made
    `Get-AuthenticodeSignature` fail with an empty verdict."""
    module = tmp_path / "Modules" / "Microsoft.PowerShell.Security"
    module.mkdir(parents=True)
    (module / "Microsoft.PowerShell.Security.psd1").write_text(
        "@{ ModuleVersion = '7.0.0.0'; RootModule = 'missing.psm1'; "
        "CmdletsToExport = 'Get-AuthenticodeSignature' }\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PSModulePath", str(tmp_path / "Modules"))
    status, subject, thumbprint = signature(REPO_ROOT / FOLDER / FILES[0].name)
    assert (status, subject, thumbprint) == ("Valid", SIGNER, FILES[0].thumbprint)


@windows_only
def test_signature_tool_failure_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="did not run \\(powershell exit 1\\)"):
        signature(tmp_path / "absent.dll")


def test_release_blocker_and_bytes_kept() -> None:
    origin = (REPO_ROOT / FOLDER / "ORIGIN.md").read_text(encoding="utf-8")
    assert "**release blocker** — RB-VCRT-TERMS" in origin
    inventory = (REPO_ROOT / "docs" / "licensing-and-clean-room.md").read_text(encoding="utf-8")
    assert "RB-VCRT-TERMS" in inventory and f"{FOLDER}/" in inventory
    lines = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert f"/{FOLDER}/** -text" in lines
