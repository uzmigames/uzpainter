"""`tools/native_input_coverage.py` `verify` and `freeze` check an all-present native input closure
of regular files, as `native_input_key.zig` walks it (decision 394).

Each case builds a small repository in pytest's `tmp_path`, writes an inventory whose digests the
helper's own rule computes, and points the helper's REPO there (CPU only, no build):

- an unchanged closure verifies and freezes, and a cache directory in any case is pruned;
- a file added under a root is a membership change: `verify` and `freeze` both exit 1;
- a `missing:` root or input is refused (exit 2) by both;
- a junction under a root is refused (exit 2) by both (Windows only: the build targets Windows).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools import native_input_coverage as coverage


def make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A repository with root `src` (two files and a `__PyCache__` dir) and its inventory."""
    repo = tmp_path / "repo"
    (repo / "src" / "sub").mkdir(parents=True)
    (repo / "src" / "a.c").write_bytes(b"int a;\n")
    (repo / "src" / "sub" / "b.h").write_bytes(b"#define B 1\n")
    (repo / "src" / "__PyCache__").mkdir()
    (repo / "src" / "__PyCache__" / "x.pyc").write_bytes(b"\0")
    for name in coverage.FREEZE_EXTRA:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(name.encode())
    monkeypatch.setattr(coverage, "REPO", repo)
    inputs = ["src/a.c", "src/sub/b.h"]
    inventory = tmp_path / "inventory.txt"
    write_inventory(inventory, ["src"], inputs, coverage.recomputed_digest(inputs))
    return repo, inventory


def write_inventory(inventory: Path, roots: list[str], inputs: list[str], digest: str) -> None:
    lines = [f"artifact keyed exe {digest}"]
    lines += [f"root {root}" for root in roots] + [f"input {path}" for path in inputs]
    inventory.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_unchanged_closure_verifies_and_freezes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, inventory = make_repo(tmp_path, monkeypatch)
    out = tmp_path / "freeze.json"
    assert coverage.verify(inventory) == 0
    assert coverage.freeze(inventory, out) == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert sorted(record["files"]) == sorted(["src/a.c", "src/sub/b.h", *coverage.FREEZE_EXTRA])


def test_new_file_under_a_root_is_a_membership_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, inventory = make_repo(tmp_path, monkeypatch)
    (repo / "src" / "sub" / "new.h").write_bytes(b"\n")
    out = tmp_path / "freeze.json"
    assert coverage.verify(inventory) == 1
    assert coverage.freeze(inventory, out) == 1
    assert not out.exists()


@pytest.mark.parametrize("kind", ["root", "input"])
def test_missing_entry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _, inventory = make_repo(tmp_path, monkeypatch)
    roots, inputs = ["src"], ["src/a.c", "src/sub/b.h"]
    if kind == "root":
        roots.append("missing:gone")
    else:
        inputs.append("missing:src/gone.h")
    write_inventory(
        inventory, roots, inputs, coverage.recomputed_digest(["src/a.c", "src/sub/b.h"])
    )
    assert coverage.verify(inventory) == 2
    assert coverage.freeze(inventory, tmp_path / "freeze.json") == 2


@pytest.mark.skipif(sys.platform != "win32", reason="junctions exist only on Windows")
def test_junction_under_a_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import _winapi

    repo, inventory = make_repo(tmp_path, monkeypatch)
    target = tmp_path / "outside"
    target.mkdir()
    _winapi.CreateJunction(str(target), str(repo / "src" / "linked"))
    assert coverage.verify(inventory) == 2
    assert coverage.freeze(inventory, tmp_path / "freeze.json") == 2
