"""Fixtures for the approved-source index checks: the real repository and throw-away git repos."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


class Sandbox:
    """A temporary git repository shaped like UzPainter (`docs/analysis`, `docs/architecture`)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        run_git(root, "init", "-q")
        run_git(root, "config", "user.email", "test@example.invalid")
        run_git(root, "config", "user.name", "Test")
        run_git(root, "config", "core.autocrlf", "false")

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def commit(self, message: str = "commit") -> str:
        run_git(self.root, "add", "-A")
        run_git(self.root, "commit", "-q", "-m", message)
        return run_git(self.root, "rev-parse", "HEAD")

    def blob(self, rel: str, commit: str = "HEAD") -> str:
        return run_git(self.root, "rev-parse", f"{commit}:{rel}")


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


IndexBuilder = Callable[..., str]


@pytest.fixture
def build_index() -> IndexBuilder:
    """Render a minimal index with the given approved rows, clearances and quarantine rows."""

    def render(
        approved: list[tuple[str, str]] | None = None,
        cleared: list[tuple[str, str, str]] | None = None,
        quarantined: list[tuple[str, str]] | None = None,
        quarantined_analyses: list[str] | None = None,
        uncleared: list[tuple[str, str]] | None = None,
    ) -> str:
        lines = ["# Index", "", "## Approved sources", "", "### A. Public", ""]
        lines += [
            "| ID | Source | Category | Revision / hash | Licence | Cleared scope | Cited as "
            "| Reviewer |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for entry_id, keys in approved or []:
            lines.append(f"| {entry_id} | src | Paper | ed. | — | scope | {keys} | tester |")
        lines += ["", "### D. Historical analyses", ""]
        lines += [
            "| ID | Path | Blob | Commit | Provenance | Cleared scope | Excluded from scope "
            "| Reviewer |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for n, (path, blob, commit) in enumerate(cleared or []):
            lines.append(f"| H-{n} | `{path}` | `{blob}` | `{commit}` | p | s | — | tester |")
        lines += ["", "## Quarantine", "", "### Q1. Off-limits", ""]
        lines += ["| ID | Source | Reason | Matches |", "|---|---|---|---|"]
        for entry_id, keys in quarantined or []:
            lines.append(f"| {entry_id} | src | reason | {keys} |")
        lines += ["", "### Q2. Uncleared analyses", "", "| ID | Path | Reason |", "|---|---|---|"]
        for n, path in enumerate(quarantined_analyses or []):
            lines.append(f"| QH-{n} | `{path}` | not audited |")
        lines += ["", "### Q3. Uncleared revisions", "", "| Path | Uncleared blobs |", "|---|---|"]
        for path, blob in uncleared or []:
            lines.append(f"| `{path}` | `{blob}` |")
        return "\n".join(lines) + "\n"

    return render
