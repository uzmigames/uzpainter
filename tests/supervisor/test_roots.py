"""Path roots (python/uzpainter_supervisor/roots.py; task phase2.5_mcp-transport-registry items
2.7 and 3.4; decision 158).

Pure Python on real folders: absolute, relative, `file:///`, `\\\\?\\` and reparse-point paths
outside their root are refused without echoing them; the Windows path forms are normalised.
"""

from __future__ import annotations

import _winapi
import os
from pathlib import Path

import pytest

from python.uzpainter_supervisor.roots import OUTSIDE, PathRefused, Roots, RootsError


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path, Roots]:
    root = (tmp_path / "Root").resolve()
    outside = (tmp_path / "Outside").resolve()
    (root / "sub").mkdir(parents=True)
    outside.mkdir()
    return root, outside, Roots.parse(f"project={root};export={root / 'sub'}")


def refused(roots: Roots, value: str, kind: str = "project") -> PathRefused:
    with pytest.raises(PathRefused) as caught:
        roots.canonical(value, kind, "/path")
    error = caught.value
    assert value not in str(error) and value not in error.reason
    assert error.pointer == "/path" and error.root == kind
    return error


def test_parse_refuses_malformed_roots(tmp_path: Path) -> None:
    for text in (
        "",
        "project",
        "bogus=" + str(tmp_path),
        f"project={tmp_path};project={tmp_path}",
        "project=relative\\dir",
        f"project={tmp_path / 'missing'}",
    ):
        with pytest.raises(RootsError):
            Roots.parse(text)
    roots = Roots.parse(f" mesh = {tmp_path} ; bake_mesh={tmp_path};resource={tmp_path};")
    assert set(roots.roots) == {"mesh", "bake_mesh", "resource"}


def test_paths_inside_are_normalised(layout: tuple[Path, Path, Roots]) -> None:
    root, _, roots = layout
    expected = str(root / "sub" / "a.uzp")
    for form in (
        expected,
        str(root / "sub" / "a.uzp").replace("\\", "/"),
        str(root / "sub" / "a.uzp").upper(),
        "sub\\a.uzp",
        "sub/./x/../a.uzp",
        "\\\\?\\" + expected,
        Path(expected).as_uri(),
        "file:///" + expected.replace("\\", "/"),
    ):
        assert roots.canonical(form, "project", "/path").lower() == expected.lower(), form
    assert roots.canonical(".", "project", "/path") == str(root)


def test_paths_outside_are_refused_without_echo(layout: tuple[Path, Path, Roots]) -> None:
    root, outside, roots = layout
    refused(roots, str(outside / "a.uzp"))
    refused(roots, "..\\Outside\\a.uzp")
    refused(roots, "sub\\..\\..\\Outside\\a.uzp")
    refused(roots, Path(outside / "a.uzp").as_uri())
    refused(roots, "\\\\?\\" + str(outside / "a.uzp"))
    refused(roots, str(root) + "-sibling\\a.uzp")  # a prefix of the name is not inside
    refused(roots, "\\\\some-host\\share\\a.uzp")  # never looked up: another share
    refused(roots, "Z:a.uzp" if not str(root).upper().startswith("Z:") else "Y:a.uzp")
    refused(roots, "a.uzp", "mesh").reason.startswith("no mesh root")
    refused(roots, str(root / "a.uzp"), "export")  # the export root is root/sub


def test_a_reparse_point_out_of_the_root_is_refused(layout: tuple[Path, Path, Roots]) -> None:
    """A junction inside the root that points outside resolves outside: refused."""
    root, outside, roots = layout
    junction = root / "link"
    _winapi.CreateJunction(str(outside), str(junction))
    try:
        assert junction.is_dir()
        error = refused(roots, "link\\a.uzp")
        assert error.reason == "the path resolves outside the project root"
        refused(roots, str(junction / "a.uzp"))
        inner = root / "inner"
        _winapi.CreateJunction(str(root / "sub"), str(inner))
        try:
            assert (
                roots.canonical("inner\\a.uzp", "project", "/path").lower()
                == str(root / "sub" / "a.uzp").lower()
            )
        finally:
            os.rmdir(inner)
    finally:
        os.rmdir(junction)


def test_scrub_replaces_path_fields_outside_the_roots(layout: tuple[Path, Path, Roots]) -> None:
    root, outside, roots = layout
    value = {
        "path": str(outside / "x"),
        "directory": str(root / "d"),
        "files": [{"path": Path(outside / "f").as_uri(), "relative_path": "f"}],
        "name": str(outside / "not a path field"),
        "receipt": {"project": str(outside / "p.uzp")},
        "count": 3,
    }
    assert roots.scrub(value) == {
        "path": OUTSIDE,
        "directory": str(root / "d"),
        "files": [{"path": OUTSIDE, "relative_path": "f"}],
        "name": str(outside / "not a path field"),
        "receipt": {"project": OUTSIDE},
        "count": 3,
    }
