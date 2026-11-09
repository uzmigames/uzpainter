"""Wand v1's manifest blocks on its production export (task phase3.1_assets3d-cutover item 3.5 on
one pilot; `MIGRATIONS.md` M14), opt-in.

The Wand v1 round is rebuilt as `test_wand_production.py` does (create and sync through the
pipeline adapter, the pinned scripts byte-unchanged), then its pinned `painter_export.py` is sent
through the adapter's client itself, whose reply carries every export's manifest (the pipeline's
own `execute()` keeps only the reply's `data`). The export is the production export, a conformant
generation under EXC-013 and EXC-014 (decisions 414, 417); the round is a diagnostic import, never
an accepted production round: Wand v1 has no Assets3D v2 piece manifest whose gates a production
request could bind (item 3.1). Each export's `export` block (v2's `exportacao`) and every file it
names must validate under the pinned Assets3D v2 definitions, and its recipe file must be the dump
of the exported revision.

It runs only when `UZP_TIER1_PRODUCTION=1` (a GPU rebuild), on the owner's machine, with the same
inputs and skips as `test_wand_v1.py`. Nothing private is printed: hashes and counts only.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.adapters.assets3d.test_cutover import validator
from tests.parity.tier1.wand_v1.runner import GOLDEN_ID, built, receipt_of
from tests.parity.tier1.wand_v1.test_wand_v1 import painter  # noqa: F401  (the fixture)
from tests.parity.tier1.wand_v1.test_wand_v1 import pytestmark as wand_marks
from tools.parity.verdict import resolve_golden

PRODUCTION_ENV = "UZP_TIER1_PRODUCTION"
REPORT_ENV = "UZP_MANIFEST_BLOCKS_REPORT"  # repository-relative path of the summary to write

pytestmark = [
    *wand_marks,
    pytest.mark.skipif(
        os.environ.get(PRODUCTION_ENV) != "1",
        reason=f"opt-in GPU run: set {PRODUCTION_ENV}=1 (decision 417)",
    ),
]


def checked_blocks(export: dict[str, Any], root: Path) -> dict[str, Any]:
    """The checks of one export's manifest; a summary of hashes and counts."""
    manifest = export["manifest"]
    assert manifest is not None, export.get("manifest_unavailable")
    block, files = manifest["manifest_export"], manifest["manifest_files"]
    validator("export").validate(block)
    for entry in files.values():
        validator("file").validate(entry)
    named = set(block["sources"]) | set(block["outputs"]) | set(block["maps"])
    named |= {source["file"] for source in block["evidence"]}
    assert named <= set(files), sorted(named - set(files))
    assert {"file": "painter-recipe"} in block["evidence"]
    entry = files["painter-recipe"]
    data = (root / entry["path"]).read_bytes()
    assert entry["role"] == "recipe" and entry["bytes"] == len(data)
    assert entry["sha256"] == {
        "algorithm": "sha256",
        "value": hashlib.sha256(data).hexdigest(),
        "verification": "verified",
    }
    dump = json.loads(data)
    recipe = manifest["painter_recipe"]
    assert dump["schema"] == recipe["schema"] == "uzpainter/recipe/1"
    assert dump["digest"] == recipe["digest"]
    assert dump["revision"] == recipe["revision"] == export["revision"] == int(entry["revision"])
    receipt = json.loads(Path(export["receipt"]).read_text(encoding="utf-8"))
    assert "non_conformant" not in receipt
    for key in ("revision", "evaluator_profile", "compat_profile"):
        assert dump[key] == receipt[key], key
    return {
        "generation": export["generation"],
        "outputs": len(block["outputs"]),
        "files": len(files),
        "recipe_sha256": entry["sha256"]["value"],
        "recipe_digest": dump["digest"],
        "revision": dump["revision"],
        "evaluator_profile": dump["evaluator_profile"],
        "compat_profile": dump["compat_profile"],
        "exceptions_relied_on": sorted(
            {str(e["exception_id"]) for e in receipt.get("exceptions_relied_on") or []}
        ),
    }


def test_wand_production_export_carries_both_manifest_blocks(
    painter: Path,  # noqa: F811  (the fixture)
    tmp_path: Path,
) -> None:
    resolved = resolve_golden(GOLDEN_ID)
    assert resolved is not None
    wand = built(painter, tmp_path / "run", resolved.manifest_path)
    script = wand.job.inputs["painter-export-py"].data
    assert script is not None
    call = wand.execute_python(script.decode("utf-8"), "painter-export.json")
    assert call.status == 0, call.stderr[-2000:]
    reply = call.document()
    assert reply["diagnostic"] == "diagnostic-import"  # never an accepted production round
    assert reply["exports"], "the round exported nothing"
    summaries = [checked_blocks(export, wand.root) for export in reply["exports"]]
    published = receipt_of(wand)
    assert summaries[-1]["revision"] == published["revision"]
    assert summaries[-1]["outputs"] == 5, summaries
    assert summaries[-1]["exceptions_relied_on"] == ["EXC-013", "EXC-014"], summaries
    print("WAND_MANIFEST_BLOCKS:", json.dumps(summaries, sort_keys=True))
    if os.environ.get(REPORT_ENV):
        path = Path(__file__).resolve().parents[4] / os.environ[REPORT_ENV]
        path.write_text(json.dumps(summaries, indent=1, sort_keys=True) + "\n", encoding="utf-8")
