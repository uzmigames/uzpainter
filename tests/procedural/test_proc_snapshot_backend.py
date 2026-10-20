"""Tests of phase3.2_proc-snapshot-backend (`src/procedural/snapshot_backend.h`,
`src/store/snapshots.h`, decision 327): frozen project-private procedural snapshots.

The `snapshot` case of `uzp-procedural-tests.exe` (`tests/procedural/procedural_test.cpp`) runs on
the CPU: it records synthetic snapshots (authored byte patterns, never Painter output) into a
stored project and checks the signature (2.1), exact-signature serving (2.2), each field mismatch
(3.2), the `.uzp` planes through save/reopen, `inspect --verify` and `export-bundle` (2.3, 3.3)
and the refusal of a copy into another project (2.4, 3.4). The shipped-folder check reads the
repository only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_snapshot_case(exe: Path, work: Path) -> set[str]:
    """Run the `snapshot` case; return its passed checks. Fails on any failed check."""
    proc = subprocess.run(
        [str(exe), "snapshot", str(work)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, proc.stdout + proc.stderr
    return {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}


def test_snapshot_backend(procedural_tests: Path, tmp_path: Path) -> None:
    """2.1-2.4 and 3.2-3.4 on stored projects, CPU only."""
    passed = run_snapshot_case(procedural_tests, tmp_path)
    assert len(passed) == 54, sorted(passed)
    # 3.2: every field of the signature changed in turn is unavailable.
    mismatches = [check for check in passed if check.endswith("(3.2)")]
    assert len(mismatches) == 27, sorted(mismatches)
    for field in (
        "a parameter value",
        "the seed",
        "a larger resolution (no resampling)",
        "the colour space",
        "an image-input hash",
        "the project's normal map format",
    ):
        assert f"unavailable, the seam refuses and evaluates nothing: {field} (3.2)" in passed
    for check in (
        # 2.1
        "the signature is canonical JSON and its hash is the SHA-256 of that text (2.1)",
        # 2.2
        "SnapshotBackend.status is unavailable: a snapshot certifies no asset (2.2, decision 222)",
        "the exact signature is served, byte for byte (2.2)",
        "a parameter edit of the snapshot-served source raises UnsupportedProcedural before the "
        "mutation commits",
        # 2.3
        "two snapshots are recorded in one commit as raster planes with their own plane ids (2.3)",
        "export-bundle writes both snapshot planes (PNG for u16, EXR for half) (2.3)",
        "the imported bundle holds both snapshots bit-exact (2.3)",
        # 3.3
        "save and reopen keep both snapshots bit-exact (3.3)",
        "inspect --verify passes and lists both snapshots with their plane ids (3.3)",
        # 3.4
        "committing project A's snapshot entries into project B is refused; B is unchanged (3.4)",
        "project B's snapshot backend refuses an entry recorded for project A (3.4)",
        "a bundle carrying another project's snapshot entry is refused on import and leaves no "
        "file (3.4)",
        "the layer's procedural copied into project B raises UnsupportedProcedural there: no "
        "snapshot came along (3.4)",
    ):
        assert check in passed, check


def _shipped_asset_folders() -> list[Path]:
    """The asset folders build.zig installs beside the executables (`*_dir = "assets/..."`)."""
    text = (REPO_ROOT / "build.zig").read_text(encoding="utf-8")
    folders = re.findall(r'^const \w+_dir = "(assets/[^"]+)";', text, flags=re.MULTILINE)
    assert len(folders) >= 4, f"build.zig names the asset folders {folders}"
    return [REPO_ROOT / folder for folder in folders]


def test_no_snapshot_in_shipped_asset_folders() -> None:
    """2.4: snapshots are project-private and never ship. No installed asset folder holds a
    project file, an export bundle or a snapshot entry (`procedural_snapshots`)."""
    offenders = []
    for folder in _shipped_asset_folders():
        assert folder.is_dir(), folder
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(REPO_ROOT).as_posix()
            if path.suffix.lower() == ".uzp" or path.name == "bundle.json":
                offenders.append(f"{name}: a project file or export bundle")
            elif b"procedural_snapshots" in path.read_bytes():
                offenders.append(f"{name}: holds a procedural snapshot entry")
    assert not offenders, offenders
