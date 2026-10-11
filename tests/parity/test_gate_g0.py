"""G0 "Contract frozen" gate record (phase0.10_gate-g0, `docs/dag.md` G0).

The record `parity/reports/phase0/gate-g0.md` names every joined item, which must be archived;
every Phase 0 task still open must be one the record exempts with its source (decision 033 for
the Iray leg, the owner's answer to q1 of `phase0.6_tier0-semantics-goldens` for the UI cases);
every evidence path the record cites exists. The store and guard checks the record reports are
run by `python -m tools.parity.store verify` and `python -m tools.parity.guard`.
"""

from __future__ import annotations

import re
from pathlib import Path

from tools.parity.schemas import REPO_ROOT

RECORD = REPO_ROOT / "parity" / "reports" / "phase0" / "gate-g0.md"
TASKS = REPO_ROOT / ".rulebook" / "tasks"
ARCHIVE = REPO_ROOT / ".rulebook" / "archive"
GATE = "phase0.10_gate-g0"
JOINED = (
    "phase0.1_approved-source-index",
    "phase0.8_tier0-goldens",
    "phase0.8_toolchain-slice",
    "phase0.6_procedural-feasibility",
    "phase0.9_oracle-envelope",
    "phase0.9_normal-convention-fixture",
)
INDIRECT = (
    "phase0_owner-decisions",
    "phase0.2_parity-contract",
    "phase0.3_painter-oracle-recorder",
    "phase0.5_private-oracle-store",
    "phase0.5_vendor-render-core",
)


def archived() -> set[str]:
    return {re.sub(r"^\d{4}-\d{2}-\d{2}-", "", p.name) for p in ARCHIVE.iterdir() if p.is_dir()}


def open_phase0() -> set[str]:
    return {p.name for p in TASKS.iterdir() if p.is_dir() and p.name.startswith("phase0")}


def record_section(title: str) -> str:
    text = RECORD.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"section {title!r} missing from {RECORD.name}"
    return match.group(1)


def test_joined_and_indirect_items_are_archived_and_named() -> None:
    text = RECORD.read_text(encoding="utf-8")
    done = archived()
    for task in JOINED + INDIRECT:
        assert task in done, f"{task} is not archived"
        assert f"`{task}`" in text, f"{task} is not named in the gate record"


def test_every_open_phase0_task_is_exempted_with_its_source() -> None:
    section = record_section("5. Phase 0 tasks not archived (roadmap rule 3 exemptions)")
    exempt = {}
    for row in section.splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        named = re.match(r"`(phase0[^`]*)`", cells[0]) if len(cells) == 3 else None
        if named:
            exempt[named.group(1)] = cells[2]
    assert exempt, "no exemption listed"
    for task in open_phase0() - {GATE}:
        assert task in exempt, f"{task} is open but not exempted by the gate record"
        assert "decision 033" in exempt[task] or "owner answer" in exempt[task]


def test_cited_evidence_paths_exist() -> None:
    text = RECORD.read_text(encoding="utf-8")
    cited = set(re.findall(r"\| `([\w./-]+\.(?:md|json))`", text))
    assert len(cited) >= 20
    for path in sorted(cited):
        assert (REPO_ROOT / Path(path)).is_file(), f"cited evidence {path} does not exist"
