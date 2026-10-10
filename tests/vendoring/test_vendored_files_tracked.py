"""Every file a vendored MANIFEST.json pins must be committable: none may match `.gitignore`.

A `*.py[cod]` ignore rule once hid CPython's `.pyd` extension modules, so the hosted CI
checkout lacked `_socket.pyd` while every local test (which reads the disk) passed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIRDPARTY = REPO_ROOT / "thirdparty"


def _manifest_paths(manifest: Path) -> list[str]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    library = manifest.parent.relative_to(REPO_ROOT).as_posix()
    paths: list[str] = []
    for entry in data.get("files", []):
        if "vendored_path" in entry:
            paths.append(str(entry["vendored_path"]))
        else:
            paths.append(f"{library}/{entry['path']}")
    for wheel in data.get("wheels", []):
        paths.append(f"{library}/{wheel['filename']}")
    return paths


def _all_vendored_paths() -> list[str]:
    paths: list[str] = []
    for manifest in sorted(THIRDPARTY.glob("*/MANIFEST.json")):
        paths.extend(_manifest_paths(manifest))
    return paths


def test_manifests_pin_files() -> None:
    assert len(_all_vendored_paths()) > 0


def test_no_vendored_file_is_gitignored() -> None:
    paths = _all_vendored_paths()
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        input="\n".join(paths) + "\n",
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # Exit 1 means no path is ignored; exit 0 lists the ignored ones; anything else is an error.
    assert result.returncode in (0, 1), result.stderr
    ignored = [line for line in result.stdout.splitlines() if line]
    assert ignored == [], f"vendored files matched .gitignore: {ignored[:10]}"
