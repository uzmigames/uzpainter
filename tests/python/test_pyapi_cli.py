"""`UzPainter.exe run` and `UzPainter.exe capabilities` (task phase1.22_pyapi-cli-capabilities items
3.1-3.4; decisions 111 and 112).

`UzPainter.exe` comes from a fresh `zig build painter` install, so the shipped `capabilities.json`,
the embedded interpreter and `python/` are beside it. CPU only: no Phase 1 Python call uses the
GPU, so `run` creates no device (decision 111).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.python.conftest import JSON_PREFIX, PLANE, REPO_ROOT
from tools.capabilities.generate_capabilities import generate

SCHEMA = REPO_ROOT / "tools" / "capabilities" / "capabilities.schema.json"


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "UzPainter.exe"


def cli(exe: Path, *args: str) -> tuple[int, list[Any], str]:
    """Exit status, the `UZP_JSON:` documents printed, and the standard error."""
    process = subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    lines = process.stdout.splitlines()
    documents = [
        json.loads(line[len(JSON_PREFIX) :]) for line in lines if line.startswith(JSON_PREFIX)
    ]
    assert all(line.startswith(JSON_PREFIX) for line in lines), process.stdout
    return process.returncode, documents, process.stderr


def script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "script.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


def test_run_returns_the_result_with_both_streams(painter: Path, tmp_path: Path) -> None:
    """3.1: `result` as JSON, stdout and stderr captured, the arguments passed, exit status 0."""
    path = script(
        tmp_path,
        """
        import sys
        print("to stdout")
        print("to stderr", file=sys.stderr)
        result = {"ok": 1, "argv": sys.argv[1:]}
        """,
    )
    status, documents, _ = cli(painter, "run", path, "a", "--", "--gpu-backend", "b")
    assert status == 0
    (report,) = documents
    assert report["status"] == "ok"
    assert report["result"] == {"ok": 1, "argv": ["a", "--gpu-backend", "b"]}
    assert report["stdout"] == "to stdout\n"
    assert report["stderr"] == "to stderr\n"
    assert report["gpu_backend"] == "dx12"
    assert "error" not in report


def test_run_reports_a_raising_script_as_a_structured_failure(
    painter: Path, tmp_path: Path
) -> None:
    """3.2: a `ValueError` after one committed call: the traceback, the call kept and its revision,
    no result, a non-zero exit status."""
    path = script(
        tmp_path,
        f"""
        import uzpainter
        from uzpainter import layerstack as ls, project, textureset as ts
        project.create({str(PLANE.as_posix())!r})
        ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
        print(project.revision())
        raise ValueError("bad stack")
        """,
    )
    status, documents, _ = cli(painter, "run", path)
    assert status == 1
    (report,) = documents
    assert report["status"] == "failed"
    assert report["result"] is None
    assert report["error"]["type"] == "ValueError"
    assert report["error"]["message"] == "bad stack"
    assert "ValueError: bad stack" in report["error"]["traceback"]
    revision = int(report["stdout"])
    assert report["last_committed_revision"] == revision
    assert [c["revision"] for c in report["committed"]][-1] == revision


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--gpu-backend", "metal", "x.py"],
        ["--gpu-backend"],
        ["x.py", "--gpu-backend", "dx12", "--gpu-backend", "dx12"],
    ],
)
def test_run_usage_errors(painter: Path, args: list[str]) -> None:
    """2.3: a usage error is exit status 2 with no JSON line."""
    status, documents, err = cli(painter, "run", *args)
    assert status == 2
    assert documents == []
    assert "usage: UzPainter.exe run" in err


def test_run_with_an_unavailable_backend(painter: Path, tmp_path: Path) -> None:
    """3.3 (scope split, decision 111): under `--gpu-backend vulkan`, which this build cannot serve,
    the host still runs the script and project create, save and reopen succeed; the GPU calls of
    the API are release gaps and refuse before any change. The `gpu_backend_unavailable` refusal
    itself comes with the first Python call that uses the GPU (phase2.1_supervisor-ipc-worker
    item 2.6, phase2.2_preview-capture)."""
    path = script(
        tmp_path,
        f"""
        import sys, uzpainter
        from uzpainter import project
        project.create({str(PLANE.as_posix())!r})
        project.save_as(sys.argv[1] + "/vulkan.uzp")
        project.close()
        project.open(sys.argv[1] + "/vulkan.uzp")
        before = project.revision()
        try:
            uzpainter.render.capture()
            refused = None
        except uzpainter.NotYetSupported as error:
            refused = str(error)
        result = {{"refused": refused, "same": project.revision() == before,
                  "open": project.is_open(), "path": project.file_path()}}
        """,
    )
    status, documents, _ = cli(painter, "run", path, str(tmp_path), "--gpu-backend", "vulkan")
    assert status == 0
    (report,) = documents
    assert report["gpu_backend"] == "vulkan"
    result = report["result"]
    assert result["refused"] and "release gap" in result["refused"]
    assert result["same"] and result["open"]
    assert Path(result["path"]).name == "vulkan.uzp"


def test_capabilities_prints_the_shipped_manifest(painter: Path, tmp_path: Path) -> None:
    """3.4: `capabilities` prints the manifest, which validates against the schema and is the
    generator's; `uzpainter.capabilities` reads the same file and names the profile."""
    status, documents, _ = cli(painter, "capabilities")
    assert status == 0
    (manifest,) = documents
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert [e.message for e in validator.iter_errors(manifest)] == []
    assert manifest == generate()
    path = script(
        tmp_path,
        """
        from uzpainter import capabilities
        manifest = capabilities.manifest()
        result = {"profile": capabilities.profile(), "compat": manifest["compat_profile"],
                  "entries": len(manifest["entries"]),
                  "entry": capabilities.entry("uzpainter.capabilities.profile"),
                  "none": capabilities.entry("uzpainter.no_such_symbol")}
        """,
    )
    status, documents, _ = cli(painter, "run", path)
    assert status == 0
    result = documents[0]["result"]
    assert result["profile"] == result["compat"] == "painter-12.1-api-0.3.7"
    assert result["entries"] == len(manifest["entries"])
    assert result["entry"]["symbol"] == "uzpainter.capabilities.profile"
    assert result["none"] is None
    assert cli(painter, "capabilities", "extra")[0] == 2


def test_inspect_prints_the_recipe_dump_of_a_project_open_elsewhere(
    painter: Path, tmp_path: Path
) -> None:
    """phase2.1_recipe-dump-manifest-blocks 2.3, 3.3: while a script holds the project open (its
    lock taken), `UzPainter.exe inspect <file> --recipe` prints exactly what
    `uzpainter.project.dump_recipe()` returns for that revision, and the report's digest is the
    dump's; the script's lock is untouched and it commits afterwards. No GPU is used."""
    path = script(
        tmp_path,
        f"""
        import json, subprocess, sys
        import uzpainter
        from uzpainter import project, layerstack as ls, textureset as ts, colormanagement as cm
        exe, work = sys.argv[1], sys.argv[2]
        project.create({str(PLANE.as_posix())!r}, project.Settings(default_texture_resolution=256))
        fill = ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
        fill.set_source(ts.ChannelType.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
        project.save_as(work + "/open.uzp")
        dump = project.dump_recipe()
        def inspect(*flags):
            done = subprocess.run([exe, "inspect", work + "/open.uzp", *flags],
                                  capture_output=True, text=True, encoding="utf-8")
            return done.returncode, done.stdout, done.stderr
        recipe = inspect("--recipe")
        report = inspect()
        fill.set_opacity(0.5, ts.ChannelType.Height)
        printed = json.loads(recipe[1]) if recipe[0] == 0 else recipe[2]
        result = {{"dump": dump, "recipe": [recipe[0], printed],
                   "report": json.loads(report[1])["recipe_digest"], "after": project.revision()}}
        """,
    )
    status, documents, stderr = cli(painter, "run", path, "--", str(painter), str(tmp_path))
    assert status == 0, stderr
    [report] = documents
    result = report["result"]
    assert result["recipe"][0] == 0, result["recipe"][1]
    assert result["recipe"][1] == result["dump"]
    assert result["report"] == {"available": True, "digest": result["dump"]["digest"]}
    assert result["after"] == result["dump"]["revision"] + 1
