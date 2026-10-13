"""`UzPainter.exe run` and `UzPainter.exe capabilities` (task phase1.22_pyapi-cli-capabilities items
3.1-3.4; decisions 111 and 112), and the command line fixes of the practical end-to-end run
(parity/reports/phase2/practical-e2e.md B2, B3, B14 and B16).

`UzPainter.exe` comes from a fresh `zig build painter` install, so the shipped `capabilities.json`,
the embedded interpreter and `python/` are beside it. CPU only: no Phase 1 Python call uses the
GPU, so `run` creates no device (decision 111).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.python.conftest import JSON_PREFIX, PLANE, REPO_ROOT
from tools.capabilities.generate_capabilities import generate

SCHEMA = REPO_ROOT / "tools" / "capabilities" / "capabilities.schema.json"
NON_ASCII = "ação ☃ 日本"  # outside every ANSI code page
# The verbs whose own usage text names their options; `--help` names every one of them.
VERB_USAGES = [
    REPO_ROOT / "src" / name
    for name in (
        "selftest/harness.cpp",
        "store/cli.cpp",
        "export/cli.cpp",
        "python/run.cpp",
        "python/capabilities.cpp",
        "preview/cli.cpp",
        "supervisor/worker.cpp",
    )
]
SUPERVISOR_MAIN = REPO_ROOT / "python" / "uzpainter_supervisor" / "main.py"


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


def test_run_passes_non_ascii_arguments(painter: Path, tmp_path: Path) -> None:
    """practical-e2e B3: an argument outside the ANSI code page reaches `sys.argv` as given. It
    used to abort the process (`UnicodeDecodeError`, exit status 0xC0000409, no report)."""
    path = script(tmp_path, "import sys\nresult = sys.argv[1:]\n")
    status, documents, stderr = cli(painter, "run", path, "ação ☃", NON_ASCII)
    assert status == 0, stderr
    (report,) = documents
    assert report["status"] == "ok"
    assert report["result"] == ["ação ☃", NON_ASCII]


def test_run_reports_a_host_failure_instead_of_crashing(painter: Path, tmp_path: Path) -> None:
    """practical-e2e B3: a failure of the host around the script, here output it cannot encode
    as UTF-8 (a lone surrogate), is the documented host failure: exit status 3 and one
    `host_error` report, never an uncaught exception that ends the process without one."""
    path = script(tmp_path, 'print("\\udc80")\nresult = 1\n')
    status, documents, _ = cli(painter, "run", path)
    assert status == 3
    (report,) = documents
    assert report["status"] == "host_error"
    assert report["error"]["type"] == "HostError" and report["error"]["message"]
    assert report["gpu_backend"] == "dx12"


def test_cli_verbs_take_non_ascii_paths(painter: Path, tmp_path: Path) -> None:
    """practical-e2e B2: `run`, `inspect`, `export-bundle` and `export` open paths outside the ANSI
    code page. The arguments used to arrive mangled (`ação ☃ 日本` became `a��o ? ??`), so the
    script and the project were not found."""
    folder = tmp_path / NON_ASCII
    folder.mkdir()
    source = folder / "script ☃.py"
    body = f"""
        import sys
        from uzpainter import project
        settings = project.Settings(default_texture_resolution=256)
        project.create({str(PLANE.as_posix())!r}, settings)
        project.save_as(sys.argv[1])
        result = project.file_path()
        """
    source.write_text(textwrap.dedent(body), encoding="utf-8")
    saved = folder / "projeto ☃.uzp"
    status, documents, stderr = cli(painter, "run", str(source), str(saved))
    assert status == 0, stderr
    (report,) = documents
    assert report["status"] == "ok", report
    reported = Path(report["result"])
    assert (reported.parent.name, reported.name) == (NON_ASCII, saved.name) and saved.is_file()

    def verb(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(painter), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
            check=False,
        )

    inspected = verb("inspect", str(saved))
    assert inspected.returncode == 0, inspected.stderr
    assert Path(json.loads(inspected.stdout)["file"]) == saved
    bundle = folder / "pacote ☃"
    bundled = verb("export-bundle", str(saved), str(bundle))
    assert bundled.returncode == 0, bundled.stderr
    assert json.loads(bundled.stdout)["target"] == str(bundle)
    assert bundle.is_dir() and any(bundle.iterdir())
    delivery = folder / "saída ☃"
    delivery.mkdir()
    recovered = verb("export", "--recover", str(delivery), "--fixed-names", str(folder))
    assert recovered.returncode == 0, recovered.stderr
    [fixed] = json.loads(recovered.stdout)["fixed_names"]
    assert Path(fixed["directory"]) == folder


def test_run_ctrl_break_interrupts_the_script(painter: Path, tmp_path: Path) -> None:
    """practical-e2e B14: Ctrl+Break during a script raises KeyboardInterrupt in it, a structured
    failure (exit status 1 and its report, not 0xC000013A). The host then closes the project the
    script left open, as after any run: its lock is gone."""
    ready = tmp_path / "ready"
    saved = tmp_path / "open.uzp"
    path = script(
        tmp_path,
        f"""
        import pathlib, time
        from uzpainter import project
        project.create({str(PLANE.as_posix())!r}, project.Settings(default_texture_resolution=256))
        project.save_as({str(saved.as_posix())!r})
        pathlib.Path({str(ready.as_posix())!r}).write_text("ready")
        while True:
            time.sleep(0.05)
        """,
    )
    process = subprocess.Popen(
        [str(painter), "run", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        deadline = time.monotonic() + 300
        while not ready.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)
        assert Path(f"{saved}.lock").exists()
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        out, err = process.communicate(timeout=120)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 1, (hex(process.returncode & 0xFFFFFFFF), err)
    lines = out.decode("utf-8").splitlines()
    (report,) = [json.loads(line[len(JSON_PREFIX) :]) for line in lines]
    assert report["status"] == "failed"
    assert report["error"]["type"] == "KeyboardInterrupt"
    assert not Path(f"{saved}.lock").exists()


def usage_flags(path: Path) -> set[str]:
    """The options a verb's own usage text names (the string literal from `usage: UzPainter.exe`
    to the end of its statement)."""
    text = path.read_text(encoding="utf-8")
    start = text.index('"usage: UzPainter.exe')
    return set(re.findall(r"--[a-z][a-z0-9-]*", text[start : text.index(";", start)]))


def test_help_prints_every_verb_and_option(painter: Path) -> None:
    """practical-e2e B16: `--help` prints the usage on stdout with exit status 0. It names every
    verb, every option a verb's own usage names and every option the supervisor parses
    (`--preview`, `--mcp-http`, `--token`, `--roots` and `--ledger` were missing). An unknown
    command stays a usage error: the usage on stderr, exit status 2."""
    shown = subprocess.run(
        [str(painter), "--help"], capture_output=True, text=True, timeout=60, check=False
    )
    assert shown.returncode == 0, shown.stderr
    usage = shown.stdout
    for verb in ("selftest", "inspect", "export-bundle", "store-census", "export", "run"):
        assert f"UzPainter.exe {verb} " in usage, verb
    for verb in ("capabilities", "--preview", "--mcp", "--worker", "--help"):
        assert f"UzPainter.exe {verb}" in usage, verb
    supervisor = set(
        re.findall(r'add_argument\("(--[a-z-]+)"', SUPERVISOR_MAIN.read_text(encoding="utf-8"))
    )
    assert {"--preview", "--mcp-http", "--token", "--roots", "--ledger"} <= supervisor
    options = supervisor.union(*(usage_flags(path) for path in VERB_USAGES))
    assert sorted(option for option in options if option not in usage) == []
    unknown = subprocess.run(
        [str(painter), "--no-such-verb"], capture_output=True, text=True, timeout=60, check=False
    )
    assert unknown.returncode == 2
    assert unknown.stdout == "" and unknown.stderr == usage


def test_run_with_an_unavailable_backend(painter: Path, tmp_path: Path) -> None:
    """3.3 (decision 111): under `--gpu-backend vulkan`, which this build cannot serve, the host
    still runs the script and project create, save and reopen succeed. The first Python call that
    uses the GPU, a `painter_viewport` capture (phase2.2_preview-capture, decision 148), creates
    its device on that backend and raises `gpu_backend_unavailable` before anything is written,
    with the revision unchanged. It needs an OCIO project (the bundle of tests/preview/conftest.py):
    on a Legacy one the display configuration is refused first."""
    from tests.preview.conftest import ocio_bundle

    bundle = ocio_bundle(painter, tmp_path / "fixture")
    path = script(
        tmp_path,
        f"""
        import os, sys, uzpainter
        from uzpainter import project
        project.create({str(PLANE.as_posix())!r})
        project.save_as(sys.argv[1] + "/vulkan.uzp")
        project.close()
        project.open(sys.argv[1] + "/vulkan.uzp")
        reopened = project.file_path()
        project.close()
        project.open({str(bundle)!r})
        before = project.revision()
        try:
            uzpainter.render.capture(sys.argv[1] + "/vp.png", "painter_viewport", size=(8, 8))
            refused = None
        except RuntimeError as error:
            refused = str(error)
        result = {{"refused": refused, "same": project.revision() == before,
                  "open": project.is_open(), "path": reopened,
                  "written": os.path.exists(sys.argv[1] + "/vp.png")}}
        """,
    )
    status, documents, _ = cli(painter, "run", path, str(tmp_path), "--gpu-backend", "vulkan")
    assert status == 0
    (report,) = documents
    assert report["gpu_backend"] == "vulkan"
    result = report["result"]
    assert result["refused"] and result["refused"].startswith("gpu_backend_unavailable"), result
    assert "vulkan" in result["refused"]
    assert result["same"] and result["open"] and not result["written"]
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
