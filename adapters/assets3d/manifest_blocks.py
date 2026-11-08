"""The Assets3D manifest blocks of each conformant export (task phase3.1_assets3d-cutover item 2.7,
`MIGRATIONS.md` M14; INT-20, INT-21).

- **`exportacao` (INT-21).** Assets3D manifest schema v2 renamed it `$defs/export`. The export's
  receipt already carries it as `manifest_export` (decision 097), and the runner rebases its
  `manifest_files` under the Assets3D root (M6). This module adds the recipe below to it: one
  `files` entry and one `evidence` source.
- **`painter_recipe`-equivalent (INT-20).** The recipe dump of the exact revision the export
  evaluated (`uzpainter/recipe/1`: every output-determining field with its effective defaults,
  `evaluator_profile`, `compat_profile`, `app_version`, `resource_hashes` and the digest that is
  its content identity; `src/uzp_core/MANIFEST.md` §8). It is read with `UzPainter.exe inspect
  <project> --revision N --recipe`, which needs no GPU and no project lock, checked against the
  export's receipt and written to `<exportPath>/uzpainter-recipes/<generation>.recipe.json`, beside
  the published generations that are never changed. The manifest names it as file
  `painter-recipe` (role `recipe`, verified SHA-256 and bytes) and the export block cites it.

An export whose recipe cannot be read, checked or written gets no manifest, with the reason, as an
export whose paths cannot be rebased (M6): the export itself stands, and nothing partial reaches
an Assets3D manifest. A file already written for the generation is never replaced: other bytes
there refuse.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.assets3d.runner import under_root

RECIPE_SCHEMA = "uzpainter/recipe/1"
RECIPE_KEY = "painter-recipe"
RECIPE_FOLDER = "uzpainter-recipes"
SHA256 = re.compile(r"[0-9a-f]{64}")


class BlockError(ValueError):
    """The recipe block of an export cannot be produced; the reason names why."""


def recipe_file(export: dict[str, Any]) -> Path:
    """`<exportPath>/uzpainter-recipes/<generation>.recipe.json` (the generation's folder is
    `<exportPath>/generations/<generation>`)."""
    name = f"{export['generation']}.recipe.json"
    return Path(export["directory"]).parent.parent / RECIPE_FOLDER / name


def recipe_bytes(dump: dict[str, Any]) -> bytes:
    return (json.dumps(dump, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def check_dump(dump: Any, export: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """The dump, when it is the recipe of the revision the receipt describes."""
    if not isinstance(dump, dict) or dump.get("schema") != RECIPE_SCHEMA:
        raise BlockError(f"inspect did not return a {RECIPE_SCHEMA} dump")
    if not isinstance(dump.get("recipe"), dict):
        raise BlockError("the recipe dump has no recipe body")
    if not isinstance(dump.get("digest"), str) or SHA256.fullmatch(dump["digest"]) is None:
        raise BlockError("the recipe dump has no SHA-256 digest")
    revision = export["revision"]
    if type(dump.get("revision")) is not int or dump["revision"] != revision:
        raise BlockError(f"the dump is of revision {dump.get('revision')}, the export {revision}")
    for key in ("revision", "evaluator_profile", "compat_profile"):
        if dump.get(key) != receipt.get(key):
            raise BlockError(
                f"the dump's {key} {dump.get(key)!r} differs from the receipt's "
                f"{receipt.get(key)!r}"
            )
    return dump


def write_once(path: Path, data: bytes) -> None:
    """`data` at `path` through a staging file; bytes already there must be the same."""
    if path.exists():
        if path.read_bytes() != data:
            raise BlockError(f"{path} already holds another recipe: never replaced")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".staging")
    staging.write_bytes(data)
    os.replace(staging, path)


def with_recipe(export: dict[str, Any], dump: dict[str, Any], root: str) -> dict[str, Any]:
    """A copy of the export's manifest with the recipe block, after its file is written."""
    manifest: dict[str, Any] = copy.deepcopy(export["manifest"])
    files = manifest["manifest_files"]
    block = manifest["manifest_export"]
    if RECIPE_KEY in files:
        raise BlockError(f"the receipt already names a file `{RECIPE_KEY}`")
    path = recipe_file(export)
    relative = under_root(str(path), root)
    if relative is None:
        raise BlockError(f"{path} lies outside the Assets3D root {root}")
    data = recipe_bytes(dump)
    write_once(path, data)
    files[RECIPE_KEY] = {
        "path": relative,
        "role": "recipe",
        "sha256": {
            "algorithm": "sha256",
            "value": hashlib.sha256(data).hexdigest(),
            "verification": "verified",
        },
        "bytes": len(data),
        "revision": str(dump["revision"]),
    }
    block["evidence"] = [*block["evidence"], {"file": RECIPE_KEY}]
    manifest["painter_recipe"] = {
        "schema": dump["schema"],
        "file": RECIPE_KEY,
        "path": str(path),
        "digest": dump["digest"],
        "revision": dump["revision"],
        "evaluator_profile": dump.get("evaluator_profile"),
        "compat_profile": dump.get("compat_profile"),
        "app_version": dump.get("app_version"),
    }
    return manifest


def add_recipes(
    exports: list[dict[str, Any]],
    inspect: Callable[[str, int], Any],
    root: str | None,
) -> None:
    """Gives every export that has a manifest its recipe block, or no manifest and the reason."""
    for export in exports:
        if export.get("manifest") is None:
            continue
        try:
            if root is None:
                raise BlockError("no Assets3D root is known")
            project = export.get("project_path")
            if not project:
                raise BlockError("the export names no project file to read the recipe from")
            receipt = json.loads(Path(export["receipt"]).read_text(encoding="utf-8"))
            dump = check_dump(inspect(project, export["revision"]), export, receipt)
            export["manifest"] = with_recipe(export, dump, root)
        except (BlockError, OSError, ValueError, KeyError, TypeError) as error:
            export["manifest"] = None
            export["manifest_unavailable"] = f"no painter_recipe block: {error}"
