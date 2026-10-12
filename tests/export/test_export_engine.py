"""Tests of phase1.18_export-engine (P1-EXPORT, `docs/architecture/08-export.md` §1-§5;
`src/export/project_export.h`, `src/export/cli.h`; decisions 103 and 104).

`uzp-export-tests.exe` runs `UzPainter.exe export` (`cli`) on a `.uzp` project the project store
creates from a CPU spec (`project`): the end-to-end export of a saved project, its determinism
across processes (item 3.2) and its refusals before anything is written. The publication's
interruption suite is `tests/export/test_export_publication.py` (item 3.3); the Tier 0 goldens of
the processing are `tests/export/test_export_encoders.py`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tests.export.test_export_encoders import config, files_under, spec

IDENTITY = ("--app-version", "0.0.0-test", "--build", "uzp-export-tests")


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
        check=False,
    )


def project_file(exe: Path, tmp: Path) -> Path:
    """The `.uzp` project of `spec` (the grid mesh, the ramp bitmap) created by the store."""
    out = tmp / "fixture.uzp"
    proc = run(exe, "project", str(spec(tmp / "spec")), str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out


def export_project(
    exe: Path, project: Path, cfg: dict[str, Any], tmp: Path, *identity: str
) -> subprocess.CompletedProcess[str]:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return run(exe, "cli", str(project), "--config", str(tmp / "config.json"), *identity)


def without_moments(receipt: dict[str, Any]) -> dict[str, Any]:
    """The receipt without what names the run: its generation and the moments (top level and
    Assets3D block)."""
    out = {k: v for k, v in receipt.items() if k not in ("moment", "generation")}
    if isinstance(out.get("manifest_export"), dict):
        out["manifest_export"] = {k: v for k, v in out["manifest_export"].items() if k != "moment"}
    return out


def test_project_export_is_deterministic_across_processes(
    export_tests: Path, tmp_path: Path
) -> None:
    """3.2: the same project file and configuration exported by two processes into one exportPath
    publish generations whose files and plans are byte-identical and whose receipts differ only in
    their generation and `moment`; every hash the receipt records (files, plan, resources) is
    equal."""
    project = project_file(export_tests, tmp_path)
    out = tmp_path / "out"
    published = []
    for run_id in ("a", "b"):
        proc = export_project(
            export_tests, project, config(out), tmp_path / f"run-{run_id}", *IDENTITY
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        result = json.loads(proc.stdout)
        generation = Path(result["receipt"]).parent
        assert sorted(f["path"] for f in result["files"]) == [
            "maps/s0_Roughness.png",
            "s0_Height.exr",
            "s0_User0.png",
        ]
        receipt = json.loads((generation / "receipt.json").read_text(encoding="utf-8"))
        assert {f["path"]: f["sha256"] for f in receipt["files"]} == {
            f["path"]: f["sha256"] for f in result["files"]
        }
        assert receipt["app_version"] == "0.0.0-test" and receipt["build"] == "uzp-export-tests"
        published.append(
            (
                files_under(generation / "files"),
                (generation / "plan.json").read_bytes(),
                without_moments(receipt),
            )
        )
    (files_a, plan_a, receipt_a), (files_b, plan_b, receipt_b) = published
    assert files_a == files_b
    assert plan_a == plan_b
    assert receipt_a == receipt_b


def test_project_export_refusals_write_nothing(export_tests: Path, tmp_path: Path) -> None:
    """Item 4.1, the engine's refusals: an unfitted processing (resize) and an invalid
    configuration exit 1 naming NotYetSupported or ValueError, and nothing exists under
    exportPath; a usage error exits 2."""
    project = project_file(export_tests, tmp_path)
    out = tmp_path / "resize"
    proc = export_project(
        export_tests, project, config(out, sizeLog2=7), tmp_path / "run-resize", *IDENTITY
    )
    assert proc.returncode == 1 and "NotYetSupported" in proc.stderr, proc.stderr
    assert "resizing 256x256 to 128x128" in proc.stderr
    assert files_under(out) == {}

    out = tmp_path / "invalid"
    cfg = config(out, root="s9")
    proc = export_project(export_tests, project, cfg, tmp_path / "run-invalid", *IDENTITY)
    assert proc.returncode == 1 and "ValueError" in proc.stderr, proc.stderr
    assert files_under(out) == {}

    proc = export_project(export_tests, project, config(tmp_path / "x"), tmp_path / "run-usage")
    assert proc.returncode == 2 and "usage:" in proc.stderr, proc.stderr


def test_a_second_export_publishes_a_new_generation(export_tests: Path, tmp_path: Path) -> None:
    """The scenario of the spec's acceptance: exporting again publishes generation 2 and moves
    `current.json` to it; generation 1 stays complete."""
    project = project_file(export_tests, tmp_path)
    out = tmp_path / "out"
    generations = []
    for run_id in ("first", "second"):
        proc = export_project(export_tests, project, config(out), tmp_path / run_id, *IDENTITY)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        generations.append(json.loads(proc.stdout)["generation"])
    assert generations[0] != generations[1]
    pointer = json.loads((out / "current.json").read_text(encoding="utf-8"))
    assert pointer["generation"] == generations[1]
    assert sorted(p.name for p in (out / "generations").iterdir()) == sorted(generations)
