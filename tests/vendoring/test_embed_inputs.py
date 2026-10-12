"""`#embed` targets are inputs of their object's cache key (decision 147, `EmbedInputs` in
`build.zig`).

Zig 0.15.2 hashes the files an object embeds only after the compile, so a shader saved while a
build compiled its embedder was recorded beside an object built from the old bytes, and every later
build reused that object. `build.zig` now puts a digest of each embedding source's targets in that
source's compile flags. These tests build `uzp-render-tests.exe` in a copy of the package with an
empty local cache (CPU only, no GPU run):

- every embedding source of the render layer is compiled with its digest define;
- a comment appended to one embedded shader changes the executable, which then holds the new bytes;
- reverting the shader gives back the byte-identical executable: the original key names the
  original object and link again (without the digest, the revert recompiles and relinks);
- a C++ file that embeds a file without going through `EmbedInputs.add` fails the build.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ZIG = shutil.which("zig")
SHADER = "src/render/shaders/mips.hlsl"
PROBE = b"// embed-cache probe (decision 147)\n"
EMBED_RE = re.compile(r'^[ \t]*#[ \t]*embed[ \t]+"([^"]+)"', re.MULTILINE)
DIGEST_RE = re.compile(r"-DUZP_EMBED_DIGEST=([0-9a-f]{32})")


@dataclass(frozen=True)
class Rebuilds:
    verbose_log: str
    original: bytes
    edited: bytes
    reverted: bytes


def _package_paths() -> list[str]:
    """The `.paths` of `build.zig.zon`: the files and folders that make up the package."""
    zon = (REPO_ROOT / "build.zig.zon").read_text(encoding="utf-8")
    block = re.search(r"\.paths\s*=\s*\.\{(.*?)\}", zon, re.DOTALL)
    assert block, "build.zig.zon has no .paths"
    return re.findall(r'"([^"]+)"', block.group(1))


def _copy(root: Path, rels: list[str]) -> None:
    for rel in rels:
        source = REPO_ROOT / rel
        if source.is_dir():
            shutil.copytree(source, root / rel, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, root / rel)


def _zig_build(root: Path, cache: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert ZIG is not None
    return subprocess.run(
        [ZIG, "build", *args, "--cache-dir", str(cache)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )


@pytest.fixture(scope="module")
def rebuilds(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Rebuilds]:
    """`zig build render-tests` of a package copy: fresh, after a shader edit, after its revert."""
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    work = tmp_path_factory.mktemp("embed-inputs")
    root = work / "uzpainter"
    _copy(root, [*_package_paths(), "tests/render"])
    exe = work / "out" / "bin" / "uzp-render-tests.exe"
    shader = root / SHADER
    text = shader.read_bytes()

    def build(*extra: str) -> tuple[str, bytes]:
        proc = _zig_build(
            root, work / "cache", "render-tests", "--prefix", str(work / "out"), *extra
        )
        assert proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]
        return proc.stdout + proc.stderr, exe.read_bytes()

    log, original = build("--verbose-cc")
    shader.write_bytes(text + PROBE)
    _, edited = build()
    shader.write_bytes(text)
    _, reverted = build()
    yield Rebuilds(verbose_log=log, original=original, edited=edited, reverted=reverted)
    shutil.rmtree(work, ignore_errors=True)


def _compile_lines(log: str, name: str) -> list[str]:
    """The `--verbose-cc` compiler invocations of `src/render/<name>`."""
    pattern = re.compile(rf"clang \S*[\\/]src[\\/]render[\\/]{re.escape(name)} ")
    return [line for line in log.splitlines() if pattern.search(line)]


def test_every_render_embedder_is_compiled_with_its_digest(rebuilds: Rebuilds) -> None:
    """Each source that embeds a file carries the digest define; the others do not."""
    sources = sorted((REPO_ROOT / "src" / "render").glob("*.cpp"))
    embedders = {p.name for p in sources if EMBED_RE.search(p.read_text(encoding="utf-8"))}
    assert "mips.cpp" in embedders
    for source in sources:
        lines = _compile_lines(rebuilds.verbose_log, source.name)
        assert lines, f"{source.name} was not compiled"
        for line in lines:
            assert bool(DIGEST_RE.search(line)) == (source.name in embedders), source.name


def test_a_shader_edit_changes_the_executable(rebuilds: Rebuilds) -> None:
    assert PROBE not in rebuilds.original
    assert PROBE in rebuilds.edited
    assert hashlib.sha256(rebuilds.edited).digest() != hashlib.sha256(rebuilds.original).digest()


def test_reverting_the_shader_gives_back_the_original_executable(rebuilds: Rebuilds) -> None:
    assert hashlib.sha256(rebuilds.reverted).digest() == hashlib.sha256(rebuilds.original).digest()


def test_an_embed_outside_the_tracked_sources_fails_the_build(tmp_path: Path) -> None:
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    root = tmp_path / "uzpainter"
    _copy(root, ["build.zig", "build.zig.zon", "src"])
    listed = _zig_build(root, tmp_path / "cache", "-l")
    assert listed.returncode == 0, listed.stderr[-4000:]
    (root / "src" / "untracked_embed.cpp").write_text(
        'static const char kShader[] = {\n#embed "render/shaders/mips.hlsl"\n};\n',
        encoding="utf-8",
    )
    refused = _zig_build(root, tmp_path / "cache", "-l")
    assert refused.returncode != 0
    assert (
        "src/untracked_embed.cpp uses #embed but is not compiled through EmbedInputs.add"
        in refused.stderr
    )
