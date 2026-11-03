"""Check the native input key's inputs against historical full Zig manifests (decision 394).

python -m tools.native_input_coverage [INVENTORY]
python -m tools.native_input_coverage freeze INVENTORY OUT
python -m tools.native_input_coverage verify INVENTORY

`verify` recomputes each artifact's digest from the current bytes of the inputs the inventory lists,
by decision 394's rule, and re-walks each listed root: exit 0 when every digest equals the one the
inventory pinned at configure time and no root gained or lost a file, so the native input closure
is unchanged since that configure.

`freeze` first re-walks each listed root as `verify` does and refuses (exit 1) when a root gained or
lost a file, then records the SHA-256 of every file the inventory lists as an input, plus the build
files that compute the key (FREEZE_EXTRA), with one aggregate, in the JSON file OUT. Two records of
the same inventory compare a window's whole native input closure, vendored and #embed targets
included, before and after a run; a record taken after the run proves membership only through its
own re-walk at that moment.

Both subcommands refuse (exit 2) an inventory that names a `missing:` root or input, and a root
that holds a symbolic link, junction, other reparse point or non-regular file: the closure they
check is all present and made of regular files, as native_input_key.zig walks it.

INVENTORY is the file `zig build -Dnative-input-inventory=<file>` writes. Each historical manifest
below was written after a full compile, so it names every repository file its artifact read; every
such file must be an input of that artifact in the inventory. The manifests are audit evidence
only, never a source of the key, and each is checked against its pinned SHA-256 and path count
before it is read. Without INVENTORY, only the repository paths of each manifest are counted.
Exit 0 when every manifest path is covered, 1 otherwise, 2 on a malformed inventory or an
unusable manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Artifact name -> (its last full-compile manifest under .zig-cache/h, that file's SHA-256, the
# count of repository paths it names). The cache is mutable and a manifest's name is not its
# content hash, so each file is pinned by content and count before it is read (decision 394).
MANIFESTS = {
    "UzPainter": (
        "68dbe13f0f5720b27d8b3c1acc484ec5",
        "5cf142c37fa21638c48ad3b128cbe78da2337a73efe3714d0590a8ee7d0b9d5f",
        647,
    ),
    "uzp-pyapi-tests": (
        "0f874365da750759bc05768465b81ace",
        "74c43f53b64733aaf0ea68f414bbfdcdc1d208ae5f8414215f141d95c81153a1",
        529,
    ),
    "uzp-export-tests": (
        "0e237afcf1cdc97d0e67104df7e8cbf6",
        "d8447e75c3cdecbd60f20c3b064a53626426eccff7604d246186df0938535ab9",
        259,
    ),
    "uzp-evaluator-tests": (
        "96b651a3e572c1a2aa04f56a0035489e",
        "a03a39e45e5b1860d9899f3068b80994a90dbe44c46aa3842d3507a7ff410d0b",
        197,
    ),
    "uzp_store": (
        "1ff900d3c6d1b4fbdb3fb6cf5aaab4d2",
        "369d71dd3a2a21240fc31e92657dce97c3a7e371cfa79efeb8faa71e3a9e31ea",
        66,
    ),
    "uzp_texture": (
        "c9139cc3f6adeaee1de7d97b95eea587",
        "c84b1fa0d3bfb98dc76a56ed3d1d9cb87fd16dab69ed2c86e7dcaf27ad578e0c",
        13,
    ),
    "uzp_mesh": (
        "45018c3ab6d5d224cddfef19d585168a",
        "2af1ccf1c0ab4e5e419c2aac020105edf8d522e5f4e53998d33f90cff4c92f79",
        42,
    ),
    "uzp_core": (
        "4b295394dd60490dc58ad87b37ec01da",
        "dc64dee3cad6fc56c240ee224f0328d9bf1d6a99385019eff486f1393b043ed1",
        28,
    ),
    "uzp_gltf": (
        "458dd680f2ba964a6fd9a6b9bfee04cb",
        "2c9278e8ca4987601dbd96d1dadcd8385dc040d141da47a515dfaebfd646fce9",
        10,
    ),
    "uzrendercore": (
        "b5657fb35c0f392bb3309b99a8e329bd",
        "9185ecfec74a15f1f571535733f853a3fd0a3a67e4bf16bf488af7560a747b00",
        128,
    ),
}
NOT_NATIVE = frozenset({"build.zig"})  # read by the build runner, not by a compile
# Files that compute the key rather than feed a compile: frozen beside the inventory's inputs.
FREEZE_EXTRA = (
    "build.zig",
    "build.zig.zon",
    "native_input_key.zig",
    "tools/native_input_coverage.py",
)
ARTIFACT = re.compile(r"artifact (\S+) (exe|lib) ([0-9a-f]{64})")
KEY_TAG = b"uzp-native-input-key-v1\0"  # native_input_key.zig's digest version tag
# Directories native_input_key.zig skips inside a root.
CACHE_DIRS = frozenset(
    {"__pycache__", ".zig-cache", "zig-cache", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)


class Malformed(Exception):
    """The inventory or a manifest cannot be read as decision 394 defines it."""


def repository_paths(manifest: Path, sha256: str, count: int) -> set[str]:
    """The repository-relative paths (`/` separators) that a Zig 0.15.2 manifest names, refused
    unless the file has its pinned content and names exactly the pinned count of paths.

    A manifest line is `size inode mtime hash prefix path`; prefix 0 is an absolute path."""
    data = manifest.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise Malformed(f"{manifest} is not the pinned manifest (SHA-256 differs)")
    root = str(REPO).replace("\\", "/").lower() + "/"
    paths: set[str] = set()
    for line in data.decode("utf-8", errors="replace").splitlines():
        fields = line.split(" ", 5)
        if len(fields) != 6 or fields[4] != "0":
            continue
        path = fields[5].replace("\\", "/")
        if path.lower().startswith(root):
            paths.add(path[len(root) :])
    if len(paths) != count:
        raise Malformed(f"{manifest} names {len(paths)} repository paths, not the pinned {count}")
    return paths


def inventory_inputs(inventory: Path) -> tuple[dict[str, set[str]], Counter[str]]:
    """Each artifact's inputs (lower-cased: Windows paths) and the count of artifacts per kind.

    Every line is `artifact <name> <exe|lib> <64 hex>`, `root <path>` or `input <path>`; an
    unknown, empty or orphan line, a repeated artifact or a repeated input is refused."""
    inputs: dict[str, set[str]] = {}
    kinds: Counter[str] = Counter()
    current: set[str] | None = None
    for number, line in enumerate(inventory.read_text(encoding="utf-8").splitlines(), 1):
        kind, _, rest = line.partition(" ")
        where = f"{inventory}:{number}"
        if kind == "artifact":
            match = ARTIFACT.fullmatch(line)
            if match is None:
                raise Malformed(f"{where}: malformed artifact line")
            name = match.group(1)
            if name in inputs:
                raise Malformed(f"{where}: artifact {name} appears twice")
            current = inputs[name] = set()
            kinds[match.group(2)] += 1
        elif kind in ("root", "input"):
            if current is None or not rest:
                raise Malformed(f"{where}: {kind} line without an artifact or a path")
            if kind == "input":
                if rest.lower() in current:
                    raise Malformed(f"{where}: input {rest} appears twice")
                current.add(rest.lower())
        else:
            raise Malformed(f"{where}: unknown line kind {kind!r}")
    if not inputs:
        raise Malformed(f"{inventory}: no artifact")
    return inputs, kinds


def freeze(inventory: Path, out: Path) -> int:
    """Write OUT: the SHA-256 of each inventory input and of FREEZE_EXTRA, and their aggregate;
    refused (exit 1) when a root's membership differs from the inventory, and (exit 2) on a
    malformed inventory, a missing root or input, or a link under a root."""
    try:
        blocks = artifact_blocks(inventory)
        moved = [
            (name, path)
            for name, _, roots, inputs in blocks
            for path in membership_changes(roots, inputs)
        ]
        if moved:
            for name, path in moved:
                print(f"{name}: root membership differs: {path}")
            print("refused: the inventory no longer lists every file under its roots")
            return 1
        data = inventory.read_bytes()
        listed: set[str] = set(FREEZE_EXTRA)
        for _, _, _, inputs in blocks:
            listed.update(inputs)
        files: dict[str, str] = {}
        for path in sorted(listed):
            file = REPO / path
            if not file.is_file():
                raise Malformed(f"{path} is not a file")
            files[path] = hashlib.sha256(file.read_bytes()).hexdigest()
    except Malformed as error:
        print(f"refused: {error}")
        return 2
    lines = "".join(f"{path}\0{sha}\n" for path, sha in files.items())
    aggregate = hashlib.sha256(lines.encode()).hexdigest()
    record = {
        "inventory_sha256": hashlib.sha256(data).hexdigest(),
        "aggregate": aggregate,
        "count": len(files),
        "files": files,
    }
    out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(f"{len(files)} files, aggregate {aggregate}")
    return 0


def artifact_blocks(inventory: Path) -> list[tuple[str, str, list[str], list[str]]]:
    """(name, pinned digest, roots, inputs in digest order) per artifact, paths as written;
    refused when a root or input is `missing:`."""
    inventory_inputs(inventory)  # the same validation as the coverage check
    blocks: list[tuple[str, str, list[str], list[str]]] = []
    for number, line in enumerate(inventory.read_text(encoding="utf-8").splitlines(), 1):
        kind, _, rest = line.partition(" ")
        if rest.startswith("missing:"):
            raise Malformed(
                f"{inventory}:{number}: the {kind} {rest} was missing at configure time"
            )
        if kind == "artifact":
            match = ARTIFACT.fullmatch(line)
            assert match is not None  # validated above
            blocks.append((match.group(1), match.group(3), [], []))
        elif kind == "root":
            blocks[-1][2].append(rest)
        elif kind == "input":
            blocks[-1][3].append(rest)
    return blocks


def recomputed_digest(inputs: list[str]) -> str:
    """Decision 394's digest of these inputs from their current bytes."""
    key = hashlib.sha256(KEY_TAG)
    for path in inputs:
        file = REPO / path
        if not file.is_file():
            raise Malformed(f"{path} is not a file any more")
        key.update(path.encode() + b"\0" + hashlib.sha256(file.read_bytes()).digest())
    return key.hexdigest()


def is_link(entry: os.DirEntry[str]) -> bool:
    """A symbolic link, a junction or any other Windows reparse point."""
    if entry.is_symlink() or entry.is_junction():
        return True
    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def root_files(root: str) -> set[str]:
    """The regular files under ROOT now, as native_input_key.zig enumerates them: a link or a
    non-regular entry is refused, and a cache directory (any case) is pruned unvisited."""
    base = REPO / root
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        raise Malformed(f"the root {root}/ is not a directory")
    found: set[str] = set()
    pending = [base]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                relative = Path(entry.path).relative_to(REPO).as_posix()
                if is_link(entry):
                    raise Malformed(f"{relative} is a link or reparse point under a root")
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in CACHE_DIRS:
                        pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    found.add(relative)
                else:
                    raise Malformed(f"{relative} is not a regular file or directory")
    return found


def membership_changes(roots: list[str], inputs: list[str]) -> list[str]:
    """The files that entered or left ROOTS since the configure that listed INPUTS."""
    listed = set(inputs)
    return sorted(
        path
        for root in roots
        for path in root_files(root) ^ {p for p in listed if p.startswith(f"{root}/")}
    )


def verify(inventory: Path) -> int:
    try:
        blocks = artifact_blocks(inventory)
        changed = 0
        for name, pinned, roots, inputs in blocks:
            digest = recomputed_digest(inputs)
            moved = membership_changes(roots, inputs)
            ok = digest == pinned and not moved
            changed += not ok
            print(f"{name}: {'unchanged' if ok else 'CHANGED'} ({len(inputs)} inputs)")
            for path in moved:
                print(f"  root membership differs: {path}")
    except Malformed as error:
        print(f"refused: {error}")
        return 2
    print(f"{len(blocks) - changed} of {len(blocks)} artifacts unchanged since the configure")
    return 1 if changed else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["verify"]:
        if len(argv) != 2:
            print("usage: python -m tools.native_input_coverage verify INVENTORY")
            return 2
        return verify(Path(argv[1]))
    if argv[:1] == ["freeze"]:
        if len(argv) != 3:
            print("usage: python -m tools.native_input_coverage freeze INVENTORY OUT")
            return 2
        return freeze(Path(argv[1]), Path(argv[2]))
    try:
        inventory = inventory_inputs(Path(argv[0])) if argv else None
        if inventory is not None:
            inputs, kinds = inventory
            print(f"{sum(kinds.values())} artifacts: {kinds['exe']} exe, {kinds['lib']} lib")
        uncovered = 0
        for artifact, (digest, sha256, count) in MANIFESTS.items():
            manifest = REPO / ".zig-cache" / "h" / f"{digest}.txt"
            if not manifest.is_file():
                raise Malformed(f"{artifact}: manifest {digest} is absent")
            paths = repository_paths(manifest, sha256, count)
            if inventory is None:
                print(f"{artifact} {digest[:8]}: {len(paths)} repository paths")
                continue
            have = inputs.get(artifact)
            if have is None:
                print(f"{artifact}: not in the inventory")
                uncovered += 1
                continue
            missing = sorted(p for p in paths if p not in NOT_NATIVE and p.lower() not in have)
            uncovered += len(missing)
            print(f"{artifact} {digest[:8]}: {len(paths)} paths, {len(missing)} not inputs")
            for path in missing:
                print(f"  missing {path}")
    except Malformed as error:
        print(f"refused: {error}")
        return 2
    return 1 if uncovered else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
