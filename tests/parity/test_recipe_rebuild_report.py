"""The rebuild-from-dump report (phase2.2_recipe-and-diagnostics item 2.2).

`tools.parity.recipe_rebuild` on synthetic dumps and files only: the outcome rules, the schema
and the writer's refusal of an invalid report. The Wand v1 run that writes the real report is
`recipe/wand_v1/`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recipe_rebuild import SCHEMA_ID, Side, report, write_report
from tools.parity.schemas import Schema, validation_errors

DIGEST = "a" * 64
OTHER = "b" * 64
MANIFEST = "c" * 64
BUILD = "d" * 64


def dump(digest: str = DIGEST) -> dict[str, Any]:
    return {
        "digest": digest,
        "revision": 7,
        "resource_hashes": {"f" * 64: {}, "e" * 64: {}},
        "compat_profile": "painter-12.1-api-0.3.7",
        "app_version": "0.1.0",
    }


def files(folder: Path, contents: dict[str, bytes]) -> dict[str, Path]:
    folder.mkdir()
    out = {}
    for name, data in contents.items():
        (folder / name).write_bytes(data)
        out[name] = folder / name
    return out


MAPS = {"w_BaseColor.png": b"base", "w_Height.png": b"height"}


def built(original: Side, rebuilt: Side) -> dict[str, Any]:
    document = report("phase1/tier1/wand-v1", MANIFEST, BUILD, original, rebuilt)
    assert validation_errors(document, Schema.RECIPE_REBUILD_REPORT) == []
    return document


def test_equal_digests_and_identical_files_pass(tmp_path: Path) -> None:
    a = files(tmp_path / "a", MAPS)
    b = files(tmp_path / "b", MAPS)
    document = built(Side(dump(), a), Side(dump(), b))
    assert document["schema"] == SCHEMA_ID
    assert document["resources"] == ["e" * 64, "f" * 64]
    assert document["original"]["export"]["files"][0]["name"] == "w_BaseColor.png"
    assert document["original"]["export"] == document["rebuilt"]["export"]
    assert document["equality"] == {
        "digests_equal": True,
        "files": "identical",
        "differing": [],
        "missing": [],
        "extra": [],
        "outcome": "pass",
    }


def test_a_differing_missing_or_extra_file_fails(tmp_path: Path) -> None:
    a = files(tmp_path / "a", MAPS)
    b = files(tmp_path / "b", {"w_BaseColor.png": b"base!", "w_Normal.png": b"n"})
    equality = built(Side(dump(), a), Side(dump(), b))["equality"]
    assert equality["files"] == "different" and equality["outcome"] == "fail"
    assert equality["differing"] == ["w_BaseColor.png"]
    assert equality["missing"] == ["w_Height.png"] and equality["extra"] == ["w_Normal.png"]


def test_another_digest_fails_even_with_identical_files(tmp_path: Path) -> None:
    a = files(tmp_path / "a", MAPS)
    b = files(tmp_path / "b", MAPS)
    equality = built(Side(dump(), a), Side(dump(OTHER), b))["equality"]
    assert equality["digests_equal"] is False and equality["outcome"] == "fail"


def test_both_exports_refused_alike_is_not_a_pass(tmp_path: Path) -> None:
    refused = Side(dump(), None, "NotYetSupported")
    document = built(refused, refused)
    assert document["original"]["export"] == {"status": "refused", "refusal": "NotYetSupported"}
    assert document["equality"]["files"] == "not_exported"
    assert document["equality"]["outcome"] == "export_refused"
    # One side refused, the other written: a failure.
    a = files(tmp_path / "a", MAPS)
    assert built(Side(dump(), a), refused)["equality"]["outcome"] == "fail"


def test_the_writer_refuses_an_invalid_report(tmp_path: Path) -> None:
    document = built(Side(dump(), None, "NotYetSupported"), Side(dump(), None, "NotYetSupported"))
    path = tmp_path / "phase2" / "recipe-rebuild-wand.json"
    write_report(document, path)
    assert json.loads(path.read_text(encoding="utf-8")) == document
    with pytest.raises(ValueError, match="invalid"):
        write_report({**document, "note": "free text"}, tmp_path / "bad.json")
    assert not (tmp_path / "bad.json").exists()
