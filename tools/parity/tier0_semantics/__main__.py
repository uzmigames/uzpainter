r"""Write or check the Tier 0 semantics fixtures and public manifests.

    python -m tools.parity.tier0_semantics write    # (re)write fixtures and manifests
    python -m tools.parity.tier0_semantics check    # exit 1 if any file differs from the corpus
    python -m tools.parity.tier0_semantics list     # manifest paths, one per line

Besides the 12.1.0 corpus (`corpus.py`, `parity/manifests/tier0/semantics/`) every command covers
the goldens first recorded under the current envelope (`current.py`: its `tier0/semantics-ui/`
and new `tier0/semantics/` manifests) and the requested goldens prepared before their Painter
session (`recording_requests.py`: the envelope's `requests/tier0/semantics/`). `write` keeps
the `private_records` a manifest already has (filled by `uzpainter parity record`) and refuses to
change the authored part of a manifest that has records: a recorded golden is immutable, so a
changed golden needs a new name.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics.corpus import (
    FIXTURES,
    MANIFEST_DIR,
    TEMPLATES,
    goldens,
    manifest,
    sha256,
)
from tools.parity.tier0_semantics.current import planned_current, ui_manifest_dir
from tools.parity.tier0_semantics.recording_requests import (
    REQUEST_FIXTURES,
    planned_requests,
    preserved_request_dir,
    preserved_request_paths,
    request_catalog_problems,
    request_dir,
)


def manifest_text(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def planned(root: Path = REPO_ROOT) -> tuple[dict[Path, bytes], dict[Path, dict[str, Any]]]:
    """Fixture bytes and manifests (without private records) the corpus defines."""
    files: dict[Path, bytes] = {}
    hashes: dict[str, str] = {}
    for name, (_, path, generate) in FIXTURES.items():
        if generate is None:
            hashes[name] = sha256((root / path).read_bytes())
        else:
            data = generate()
            files[root / path] = data
            hashes[name] = sha256(data)
    for name, (_, path, generate) in REQUEST_FIXTURES.items():
        data = generate()
        files[root / path] = data
        hashes[name] = sha256(data)
    manifests = {
        root / MANIFEST_DIR / f"{g.name}.json": manifest(g, hashes) for g in goldens(TEMPLATES)
    }
    return files, manifests | planned_current(hashes, root) | planned_requests(hashes, root)


def authored(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k != "private_records"}


def problems(root: Path = REPO_ROOT) -> list[str]:
    files, manifests = planned(root)
    found: list[str] = request_catalog_problems(root)
    for path, blob in files.items():
        if not path.is_file() or path.read_bytes() != blob:
            found.append(f"{path.relative_to(root).as_posix()}: differs from the generator")
    for path, planned_manifest in manifests.items():
        if not path.is_file():
            found.append(f"{path.relative_to(root).as_posix()}: missing")
            continue
        current = json.loads(path.read_text(encoding="utf-8"))
        if authored(current) != authored(planned_manifest):
            found.append(f"{path.relative_to(root).as_posix()}: authored part differs")
    extra = sorted(set((root / MANIFEST_DIR).glob("*.json")) - set(manifests))
    extra += sorted(set(ui_manifest_dir(root).glob("*.json")) - set(manifests))
    extra += sorted(set(request_dir(root).glob("*.json")) - set(manifests))
    extra += sorted(set(preserved_request_dir(root).glob("*.json")) - set(manifests))
    found += [f"{p.relative_to(root).as_posix()}: not in the corpus" for p in extra]
    return found


def write(root: Path = REPO_ROOT) -> list[str]:
    files, manifests = planned(root)
    refused: list[str] = []
    for path, data in manifests.items():
        if path.is_file():
            current = json.loads(path.read_text(encoding="utf-8"))
            if current["private_records"] and authored(current) != authored(data):
                refused.append(f"{path.relative_to(root).as_posix()}: recorded golden changed")
            if path in preserved_request_paths(root, path.stem) and current != data:
                refused.append(f"{path.relative_to(root).as_posix()}: preserved request changed")
    if refused:
        return refused
    for path, blob in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != blob:
            path.write_bytes(blob)
    for path, data in manifests.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            data = {
                **data,
                "private_records": json.loads(path.read_text("utf-8"))["private_records"],
            }
        text = manifest_text(data)
        if not path.is_file() or path.read_bytes() != text.encode("utf-8"):
            path.write_text(text, encoding="utf-8", newline="\n")
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.tier0_semantics")
    parser.add_argument("command", choices=["write", "check", "list"])
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "list":
        print("\n".join(p.relative_to(REPO_ROOT).as_posix() for p in sorted(planned()[1])))
        return 0
    found = write() if args.command == "write" else problems()
    print("\n".join(found) or f"tier0 semantics: {args.command} ok")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
