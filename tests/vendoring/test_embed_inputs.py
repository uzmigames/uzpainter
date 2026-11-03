"""`#embed` targets are inputs of their object's cache key (decision 147, `EmbedInputs` in
`build.zig`).

Zig 0.15.2 hashes the files an object embeds only after the compile, so a shader saved while a
build compiled its embedder was recorded beside an object built from the old bytes, and every later
build reused that object. `build.zig` now puts a digest of each embedding source's targets in that
source's compile flags. These tests build a tiny authored package in pytest's `tmp_path`, with an
empty local cache (CPU only, no GPU run): a static library of `src/embeds.c`, which embeds
`src/blob.txt`, and `src/plain.c`, which embeds nothing. Its `build.zig` is `FIXTURE_BUILD` followed
by the `EmbedInputs` struct cut out of the live `build.zig`, so the production code is what runs:

- the embedding source is compiled with its digest define, the other source without it;
- a line appended to the embedded file changes the library, which then holds the new bytes;
- reverting the embedded file gives back the byte-identical library: the original key names the
  original object and archive again (without the digest, the revert recompiles and relinks);
- a C file that embeds a file without going through `EmbedInputs.add` fails the build.

The C sources live only in this module: `EmbedInputs.check` scans `tests/` for `#embed`, so an
authored `.c` fixture here would fail the repository's own build.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ZIG = shutil.which("zig")
STRUCT_BEGIN = "\nconst EmbedInputs = struct {\n"
STRUCT_END = "\n};\n"
STRUCT_FUNCTIONS = ("add", "check", "targets", "digestFlag", "readSource", "embedTarget")
BLOB = b"embed-inputs fixture blob\n"
PROBE = b"// embed-cache probe (decision 147)\n"
DIGEST_RE = re.compile(r"-DUZP_EMBED_DIGEST=([0-9a-f]{32})")
REFUSAL = "src/untracked.c uses #embed but is not compiled through EmbedInputs.add"

FIXTURE_BUILD = """\
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    var embed_inputs: EmbedInputs = .{ .b = b };
    defer embed_inputs.check();
    const mod = b.createModule(.{ .target = target, .optimize = optimize });
    embed_inputs.add(mod, "src", &.{ "embeds.c", "plain.c" }, &.{"-std=c23"});
    const lib = b.addLibrary(.{ .linkage = .static, .name = "embed_probe", .root_module = mod });
    b.installArtifact(lib);
}
"""

SOURCES = {
    "src/embeds.c": b'const unsigned char embed_probe_blob[] = {\n#embed "blob.txt"\n};\n',
    "src/plain.c": b"int embed_probe_plain(void) { return 0; }\n",
    "src/blob.txt": BLOB,
}


@dataclass(frozen=True)
class Rebuilds:
    verbose_log: str
    original: bytes
    edited: bytes
    reverted: bytes


def _embed_inputs_struct() -> str:
    """The top-level `const EmbedInputs = struct { ... };` of the live `build.zig`, verbatim."""
    text = (REPO_ROOT / "build.zig").read_text(encoding="utf-8")
    assert text.count(STRUCT_BEGIN) == 1, "build.zig must declare `const EmbedInputs` exactly once"
    start = text.index(STRUCT_BEGIN) + 1
    end = text.find(STRUCT_END, start)
    assert end != -1, "the EmbedInputs struct has no top-level `};`"
    block = text[start : end + len(STRUCT_END)]
    for name in STRUCT_FUNCTIONS:
        assert len(re.findall(rf"^    fn {name}\(", block, re.MULTILINE)) == 1, name
    return block


def _package(root: Path) -> None:
    """The authored fixture package under `root`."""
    (root / "src").mkdir(parents=True)
    (root / "build.zig").write_bytes((FIXTURE_BUILD + "\n" + _embed_inputs_struct()).encode())
    for rel, data in SOURCES.items():
        (root / rel).write_bytes(data)


def _zig_build(root: Path, cache: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert ZIG is not None
    return subprocess.run(
        [ZIG, "build", *args, "--cache-dir", str(cache)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )


@pytest.fixture(scope="module")
def rebuilds(tmp_path_factory: pytest.TempPathFactory) -> Rebuilds:
    """`zig build` of the fixture: fresh, after an edit of the embedded file, after its revert."""
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    work = tmp_path_factory.mktemp("embed-inputs")
    root = work / "package"
    _package(root)
    blob = root / "src" / "blob.txt"

    def build(*extra: str) -> tuple[str, bytes]:
        proc = _zig_build(root, work / "cache", "--prefix", str(work / "out"), *extra)
        assert proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]
        (lib,) = (work / "out" / "lib").glob("*embed_probe*")
        return proc.stdout + proc.stderr, lib.read_bytes()

    log, original = build("--verbose-cc")
    blob.write_bytes(BLOB + PROBE)
    _, edited = build()
    blob.write_bytes(BLOB)
    _, reverted = build()
    return Rebuilds(verbose_log=log, original=original, edited=edited, reverted=reverted)


def _compile_lines(log: str, name: str) -> list[str]:
    """The `--verbose-cc` compiler invocations of `src/<name>`."""
    pattern = re.compile(rf"clang (?:\S*[\\/])?src[\\/]{re.escape(name)} ")
    return [line for line in log.splitlines() if pattern.search(line)]


def test_only_the_embedding_source_is_compiled_with_its_digest(rebuilds: Rebuilds) -> None:
    for name, embeds in (("embeds.c", True), ("plain.c", False)):
        lines = _compile_lines(rebuilds.verbose_log, name)
        assert lines, f"{name} was not compiled"
        for line in lines:
            assert bool(DIGEST_RE.search(line)) == embeds, name


def test_an_embedded_file_edit_changes_the_library(rebuilds: Rebuilds) -> None:
    assert PROBE not in rebuilds.original
    assert PROBE in rebuilds.edited
    assert hashlib.sha256(rebuilds.edited).digest() != hashlib.sha256(rebuilds.original).digest()


def test_reverting_the_embedded_file_gives_back_the_original_library(rebuilds: Rebuilds) -> None:
    assert hashlib.sha256(rebuilds.reverted).digest() == hashlib.sha256(rebuilds.original).digest()


def test_an_embed_outside_the_tracked_sources_fails_the_build(tmp_path: Path) -> None:
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    root = tmp_path / "package"
    _package(root)
    listed = _zig_build(root, tmp_path / "cache", "-l")
    assert listed.returncode == 0, listed.stderr[-4000:]
    (root / "src" / "untracked.c").write_bytes(
        b'const unsigned char untracked_blob[] = {\n#embed "blob.txt"\n};\n'
    )
    refused = _zig_build(root, tmp_path / "cache", "-l")
    assert refused.returncode != 0
    assert REFUSAL in refused.stderr
