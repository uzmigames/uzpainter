"""A header-only edit re-keys exactly the native artifacts that can read it (decision 394,
`native_input_key.zig`).

Zig 0.15.2 keys an executable or a static library on a whole-entry manifest that, after a relink,
lists the header dependencies of only the objects recompiled in that run, so a later edit to a
header that only reused objects include served the old binary. `stampAll` gives every artifact a
generated C stamp carrying a SHA-256 of every file under its source and include roots. These tests
build the authored fixture `native_input_key_fixture/` (a static library `l` with lib/src and
lib/include, an executable `keyed` with app/ and lib/include that links it) with a copy of the
repository's helper, in pytest's `tmp_path` (CPU only). What compiled is read from `--verbose-cc`;
the objects, stamps and binaries from the fixture's own `.zig-cache/o`:

- a fresh build compiles every source and both stamps; an unchanged build compiles nothing and
  leaves every object path and hash as it was;
- editing lib2.c recompiles it and the library stamp only; lib1.obj is reused, the library relinks;
- editing only h3.h recompiles lib1.c and the library stamp, changes only the library digest, and
  relinks the library and the executable, which prints the new value; the executable stamp, app,
  b and lib2 objects keep their paths and hashes;
- editing only h1.h, then only h2, recompiles its one reader and the executable stamp;
- two final unchanged builds are hits;
- the executable's Zig manifest lists its current stamp with the stamp's content hash;
- the configurations the key does not cover fail at configure time with a clear message.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "native_input_key_fixture"
HELPER = REPO_ROOT / "native_input_key.zig"
ZIG = shutil.which("zig")
# The authored fixture, copied file by file (never a cache or output folder beside them).
FIXTURE_FILES = (
    "build.zig",
    "app/app.c",
    "app/b.c",
    "app/h1.h",
    "app/h2",
    "lib/include/lib.h",
    "lib/src/h3.h",
    "lib/src/lib1.c",
    "lib/src/lib2.c",
)
INVENTORY = "inventory.txt"
EXE = "keyed.exe" if os.name == "nt" else "keyed"
STAMPS = {"keyed": "keyed-native-inputs.c", "l": "l-native-inputs.c"}
SOURCES = frozenset({"app.c", "b.c", "lib1.c", "lib2.c", *STAMPS.values()})
LIBRARIES = frozenset({"l.lib", "libl.a"})
OBJECT_SUFFIXES = (".obj", ".o")
INPUTS = {
    "keyed": ["app/app.c", "app/b.c", "app/h1.h", "app/h2", "lib/include/lib.h"],
    "l": ["lib/include/lib.h", "lib/src/h3.h", "lib/src/lib1.c", "lib/src/lib2.c"],
}
# Each step's edit (file, old text, new text), applied before its build.
EDITS = {
    "lib2": ("lib/src/lib2.c", b"LIB2_VALUE 20", b"LIB2_VALUE 21"),
    "h3": ("lib/src/h3.h", b"H3_VALUE 3", b"H3_VALUE 33"),
    "h1": ("app/h1.h", b"H1_VALUE 1", b"H1_VALUE 11"),
    "h2": ("app/h2", b"H2_VALUE 2", b"H2_VALUE 22"),
}
STEPS = ("fresh", "unchanged", "lib2", "h3", "h1", "h2", "final1", "final2")
CLANG_RE = re.compile(r"(?:^|\s)\"?clang\"?\s")
# std/Build/Cache.zig:135: the key of the SipHash128(1,3) file hashes in Zig's manifests.
CACHE_KEY = bytes.fromhex("3352a284cf17565701bbcde477d6f060")
MASK64 = (1 << 64) - 1
STAMP_DECLARATION = "typedef int uzp_native_input_key;\n"


@dataclass(frozen=True)
class Build:
    log: str
    compiled: frozenset[str]
    # `.zig-cache`-relative path -> SHA-256 of every object, stamp source, library and executable.
    cache: dict[str, str]
    output: str
    digests: dict[str, str]
    inputs: dict[str, list[str]]
    # The digest of each artifact computed here from the fixture files and the decision 394 rule.
    expected: dict[str, str]


@dataclass(frozen=True)
class History:
    root: Path
    builds: dict[str, Build]


def _copy_fixture(root: Path) -> None:
    """The authored fixture files and a copy of the helper, nothing else of the checkout."""
    for rel in FIXTURE_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE / rel, root / rel)
    shutil.copyfile(HELPER, root / "native_input_key.zig")


def _zig_build(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert ZIG is not None
    return subprocess.run(
        [ZIG, "build", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )


def _compiled(log: str) -> frozenset[str]:
    """The fixture sources and stamps that `--verbose-cc` shows compiled."""
    names: set[str] = set()
    for line in log.splitlines():
        if not CLANG_RE.search(line):
            continue
        for token in line.split():
            name = re.split(r"[\\/]", token.strip('"'))[-1]
            if name in SOURCES:
                names.add(name)
    return frozenset(names)


def _tracked(name: str) -> bool:
    stem, suffix = os.path.splitext(name)
    objects = {os.path.splitext(source)[0] for source in SOURCES}
    return (
        name in SOURCES
        or name in LIBRARIES
        or name == EXE
        or (suffix in OBJECT_SUFFIXES and stem in objects)
    )


def _cache_files(root: Path) -> dict[str, str]:
    cache = root / ".zig-cache"
    return {
        path.relative_to(cache).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((cache / "o").glob("*/*"))
        if path.is_file() and _tracked(path.name)
    }


def _inventory(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    digests: dict[str, str] = {}
    inputs: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        kind, _, rest = line.partition(" ")
        if kind == "artifact":
            current, _, digest = rest.split(" ")
            digests[current] = digest
            inputs[current] = []
        elif kind == "input":
            inputs[current].append(rest)
    return digests, inputs


def _digest(root: Path, inputs: list[str]) -> str:
    """Decision 394: SHA-256 of the tag, then each input in path order as path, NUL, SHA-256."""
    hasher = hashlib.sha256(b"uzp-native-input-key-v1\0")
    for rel in sorted(set(inputs), key=lambda path: path.encode()):
        hasher.update(rel.encode() + b"\0" + hashlib.sha256((root / rel).read_bytes()).digest())
    return hasher.hexdigest()


def _stamp_bytes(digest: str) -> bytes:
    return f"/* UzPainter native input key v1: {digest} */\n{STAMP_DECLARATION}".encode()


def _edit(root: Path, rel: str, old: bytes, new: bytes) -> None:
    path = root / rel
    data = path.read_bytes()
    assert data.count(old) == 1, rel
    path.write_bytes(data.replace(old, new))


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory) -> History:
    """`zig build` of the fixture copy at each step, each with `--verbose-cc` and the inventory."""
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    root = tmp_path_factory.mktemp("native-input-key") / "fixture"
    _copy_fixture(root)
    builds: dict[str, Build] = {}
    for step in STEPS:
        if step in EDITS:
            _edit(root, *EDITS[step])
        proc = _zig_build(root, f"-Dinventory={INVENTORY}", "--verbose-cc")
        log = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"{step}: {log[-6000:]}"
        run = subprocess.run(
            [str(root / "zig-out" / "bin" / EXE)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        digests, inputs = _inventory((root / INVENTORY).read_text(encoding="utf-8"))
        builds[step] = Build(
            log=log,
            compiled=_compiled(log),
            cache=_cache_files(root),
            output=run.stdout.strip(),
            digests=digests,
            inputs=inputs,
            expected={name: _digest(root, rels) for name, rels in INPUTS.items()},
        )
    return History(root=root, builds=builds)


def _named(build: Build, name: str) -> dict[str, str]:
    """The cache files called `name` (an object: its stem with any object suffix)."""
    names = {name} if "." in name else {name + suffix for suffix in OBJECT_SUFFIXES}
    return {path: sha for path, sha in build.cache.items() if path.rsplit("/", 1)[-1] in names}


def _kept(before: Build, after: Build, *names: str) -> None:
    for name in names:
        assert _named(before, name), f"{name} is not in the cache"
        assert _named(after, name) == _named(before, name), f"{name} changed path or hash"


def _added(before: Build, after: Build, name: str) -> set[str]:
    return set(_named(after, name)) - set(_named(before, name))


def _relinked(before: Build, after: Build) -> set[str]:
    """`l` and/or `keyed` when a new library or executable output appeared in the cache."""
    linked = {"l"} if any(_added(before, after, lib) for lib in LIBRARIES) else set()
    return linked | ({"keyed"} if _added(before, after, EXE) else set())


def _step(history: History, step: str) -> tuple[Build, Build]:
    return history.builds[STEPS[STEPS.index(step) - 1]], history.builds[step]


def test_fresh_build_compiles_every_source_and_both_stamps(history: History) -> None:
    fresh = history.builds["fresh"]
    assert fresh.compiled == SOURCES, fresh.log[-6000:]
    assert fresh.output == "h1=1 h2=2 h3=3 lib2=20"


@pytest.mark.parametrize("step", STEPS)
def test_each_digest_follows_the_rule_and_is_in_its_stamp(history: History, step: str) -> None:
    """The inventory lists the expected inputs and digests; the cache holds each exact stamp."""
    build = history.builds[step]
    assert build.inputs == INPUTS
    assert build.digests == build.expected
    for artifact, stamp in STAMPS.items():
        current = [
            path
            for path in _named(build, stamp)
            if (history.root / ".zig-cache" / path).read_bytes()
            == _stamp_bytes(build.digests[artifact])
        ]
        assert len(current) == 1, (artifact, current)


@pytest.mark.parametrize("step", ["unchanged", "final1", "final2"])
def test_an_unchanged_build_compiles_nothing_and_keeps_every_object(
    history: History, step: str
) -> None:
    before, after = _step(history, step)
    assert after.compiled == frozenset(), after.log[-6000:]
    assert after.cache == before.cache
    assert after.digests == before.digests
    assert after.output == before.output


def test_a_library_source_edit_recompiles_it_with_the_library_stamp(history: History) -> None:
    before, after = _step(history, "lib2")
    assert after.compiled == {"lib2.c", STAMPS["l"]}, after.log[-6000:]
    assert after.digests["l"] != before.digests["l"]
    assert after.digests["keyed"] == before.digests["keyed"]
    _kept(before, after, "lib1", "app", "b", "keyed-native-inputs", STAMPS["keyed"])
    assert _added(before, after, "lib2")
    assert _relinked(before, after) == {"l", "keyed"}
    assert after.output == "h1=1 h2=2 h3=3 lib2=21"


def test_a_private_library_header_edit_rekeys_only_the_library(history: History) -> None:
    before, after = _step(history, "h3")
    assert after.compiled == {"lib1.c", STAMPS["l"]}, after.log[-6000:]
    assert after.digests["l"] != before.digests["l"]
    assert after.digests["keyed"] == before.digests["keyed"]
    _kept(before, after, "keyed-native-inputs", STAMPS["keyed"], "app", "b", "lib2")
    assert _added(before, after, "lib1")
    assert _added(before, after, "l-native-inputs")
    assert _relinked(before, after) == {"l", "keyed"}
    assert after.output == "h1=1 h2=2 h3=33 lib2=21"


@pytest.mark.parametrize(
    ("step", "source", "kept", "output"),
    [
        ("h1", "app.c", "b", "h1=11 h2=2 h3=33 lib2=21"),
        ("h2", "b.c", "app", "h1=11 h2=22 h3=33 lib2=21"),
    ],
)
def test_an_executable_header_edit_recompiles_its_one_reader(
    history: History, step: str, source: str, kept: str, output: str
) -> None:
    before, after = _step(history, step)
    assert after.compiled == {source, STAMPS["keyed"]}, after.log[-6000:]
    assert after.digests["keyed"] != before.digests["keyed"]
    assert after.digests["l"] == before.digests["l"]
    _kept(before, after, kept, "lib1", "lib2", "l-native-inputs", STAMPS["l"])
    library = {lib: _named(before, lib) for lib in LIBRARIES}
    assert any(library.values()), "the library is not in the cache"
    assert {lib: _named(after, lib) for lib in LIBRARIES} == library
    assert _added(before, after, os.path.splitext(source)[0])
    assert _relinked(before, after) == {"keyed"}
    assert after.output == output


def _siphash128_13(data: bytes) -> str:
    """SipHash128(1,3) as std.crypto.auth.siphash keyed with `CACHE_KEY`, little-endian hex."""

    def rotl(x: int, b: int) -> int:
        return ((x << b) | (x >> (64 - b))) & MASK64

    def rounds(v: list[int], n: int) -> None:
        for _ in range(n):
            v[0] = (v[0] + v[1]) & MASK64
            v[1] = rotl(v[1], 13) ^ v[0]
            v[0] = rotl(v[0], 32)
            v[2] = (v[2] + v[3]) & MASK64
            v[3] = rotl(v[3], 16) ^ v[2]
            v[0] = (v[0] + v[3]) & MASK64
            v[3] = rotl(v[3], 21) ^ v[0]
            v[2] = (v[2] + v[1]) & MASK64
            v[1] = rotl(v[1], 17) ^ v[2]
            v[2] = rotl(v[2], 32)

    k0 = int.from_bytes(CACHE_KEY[:8], "little")
    k1 = int.from_bytes(CACHE_KEY[8:], "little")
    v = [
        k0 ^ 0x736F6D6570736575,
        k1 ^ 0x646F72616E646F6D ^ 0xEE,
        k0 ^ 0x6C7967656E657261,
        k1 ^ 0x7465646279746573,
    ]
    end = len(data) - len(data) % 8
    for i in range(0, end, 8):
        m = int.from_bytes(data[i : i + 8], "little")
        v[3] ^= m
        rounds(v, 1)
        v[0] ^= m
    last = ((len(data) & 0xFF) << 56) | int.from_bytes(data[end:], "little")
    v[3] ^= last
    rounds(v, 1)
    v[0] ^= last
    v[2] ^= 0xEE
    rounds(v, 3)
    b1 = v[0] ^ v[1] ^ v[2] ^ v[3]
    v[1] ^= 0xDD
    rounds(v, 3)
    b2 = v[0] ^ v[1] ^ v[2] ^ v[3]
    return (b1.to_bytes(8, "little") + b2.to_bytes(8, "little")).hex()


def _manifest_lines(path: Path) -> dict[str, str]:
    """`/`-separated path -> content hash, per file line ("size inode mtime hash prefix path")."""
    lines: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(" ", 5)
        if len(parts) == 6 and re.fullmatch(r"[0-9a-f]{32}", parts[3]):
            lines[parts[5].replace("\\", "/")] = parts[3]
    return lines


def test_the_executable_manifest_lists_its_stamp_with_its_content_hash(history: History) -> None:
    final = history.builds["final2"]
    stamp_bytes = _stamp_bytes(final.digests["keyed"])
    cache = history.root / ".zig-cache"
    (stamp,) = [
        p for p in _named(final, STAMPS["keyed"]) if (cache / p).read_bytes() == stamp_bytes
    ]
    app_hash = _siphash128_13((history.root / "app" / "app.c").read_bytes())
    found = False
    for manifest in sorted((cache / "h").glob("*.txt")):
        lines = _manifest_lines(manifest)
        app = [h for p, h in lines.items() if p == "app/app.c" or p.endswith("/app/app.c")]
        has_b = any(p == "app/b.c" or p.endswith("/app/b.c") for p in lines)
        stamps = [h for p, h in lines.items() if p.endswith(STAMPS["keyed"])]
        if not (app and has_b and stamps):
            continue  # not an executable entry: an object's manifest names one source
        assert app == [app_hash], f"SipHash128(1,3) disagrees with {manifest.name} on app/app.c"
        found = found or any(
            p.endswith(stamp) and h == _siphash128_13(stamp_bytes) for p, h in lines.items()
        )
    assert found, f"no executable manifest lists {stamp} with its content hash"


@pytest.fixture(scope="module")
def refusal_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One fixture copy for the configure-only refusal cases (its build runner is built once)."""
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    root = tmp_path_factory.mktemp("native-input-key-refusals") / "fixture"
    _copy_fixture(root)
    return root


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ["-Drefuse=include_dir_flag"],
            "native input key: l compiles lib/src/lib1.c with the path-bearing flag -Iextra, "
            "which the key does not cover (decision 394)",
        ),
        (
            ["-Drefuse=include_file_flag"],
            "native input key: l compiles lib/src/lib1.c with the path-bearing flag -include, "
            "which the key does not cover (decision 394)",
        ),
        (
            ["-Dinventory=app/inventory.txt"],
            "native input key: the inventory app/inventory.txt lies under the input root app of "
            "keyed (decision 394)",
        ),
        (
            ["-Drefuse=build_root_source"],
            "native input key: keyed has the build root itself as a root (decision 394)",
        ),
        (
            ["-Drefuse=zig_out_root"],
            "native input key: keyed has a root in an output directory: zig-out/include",
        ),
        (
            ["-Drefuse=zig_cache_root"],
            "native input key: keyed has a root in an output directory: .zig-cache/include",
        ),
        (["-Drefuse=generated_root"], "native input key: keyed has a generated "),
        (
            ["-Drefuse=cwd_relative_root"],
            "native input key: keyed has an include directory outside the build root: outside",
        ),
        (
            ["-Drefuse=shared_root_module"],
            "native input key: twin and keyed share a root module; each artifact needs its own "
            "for its stamp (decision 394)",
        ),
    ],
)
def test_an_uncovered_configuration_fails_with_a_clear_message(
    refusal_root: Path, args: list[str], message: str
) -> None:
    proc = _zig_build(refusal_root, "-l", *args)
    assert proc.returncode != 0, proc.stdout[-4000:]
    # The helper's own diagnostic (std.process.fatal), not some later or generic failure.
    assert f"error: {message}" in proc.stderr, proc.stderr[-4000:]
    assert not (refusal_root / "app" / "inventory.txt").exists()
