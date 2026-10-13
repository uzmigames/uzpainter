"""The open rulebook tasks' acceptance graph has no cycle (decision 221)."""

from __future__ import annotations

from pathlib import Path

from tools.planning.acceptance_graph import check

REPO_ROOT = Path(__file__).resolve().parents[2]


def write_task(root: Path, task: str, text: str) -> None:
    folder = root / ".rulebook" / "tasks" / task
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(text, encoding="utf-8")


def test_repository_acceptance_graph_has_no_cycle() -> None:
    problems, _ = check(REPO_ROOT)
    assert problems == []


def test_a_free_text_wait_closing_a_loop_is_reported(tmp_path: Path) -> None:
    (tmp_path / ".rulebook" / "archive").mkdir(parents=True)
    write_task(
        tmp_path,
        "phase2.1_worker",
        "- [ ] 3.3 Device loss\n- 3.3: open. It waits on phase3.1_backend item 3.4.\n",
    )
    write_task(tmp_path, "phase3.1_backend", "- [ ] 1.1 Prerequisites accepted: phase2.1_worker\n")
    problems, _ = check(tmp_path)
    assert any("waits on phase3.1_backend in free text only" in p for p in problems)
    assert any(
        p.startswith("acceptance cycle: phase2.1_worker -> phase3.1_backend") for p in problems
    )


def test_a_structured_wait_and_an_item_level_input_are_told_apart(tmp_path: Path) -> None:
    (tmp_path / ".rulebook" / "archive").mkdir(parents=True)
    write_task(
        tmp_path,
        "phase5.2_package",
        "- [ ] 1.1 Prerequisites accepted: phase5.1_perf; items §2 of phase5.5_history done\n",
    )
    write_task(tmp_path, "phase5.5_history", "- [ ] 1.1 Prerequisites accepted: phase5.2_package\n")
    write_task(tmp_path, "phase5.1_perf", "- Acceptance waits on: phase5.5_history\n")
    problems, edges = check(tmp_path)
    assert {(e.source, e.target, e.kind) for e in edges} == {
        ("phase5.2_package", "phase5.1_perf", "accepted"),
        ("phase5.5_history", "phase5.2_package", "accepted"),
        ("phase5.1_perf", "phase5.5_history", "structured"),
    }
    assert len(problems) == 1 and problems[0].startswith("acceptance cycle:")


def test_a_task_requiring_its_own_acceptance_is_a_cycle(tmp_path: Path) -> None:
    (tmp_path / ".rulebook" / "archive").mkdir(parents=True)
    write_task(tmp_path, "phase2.4_worker", "- [ ] 1.1 Prerequisites accepted: phase2.4_worker\n")
    problems, _ = check(tmp_path)
    assert problems == [
        "acceptance cycle: phase2.4_worker -> phase2.4_worker "
        "(accepted, .rulebook/tasks/phase2.4_worker/tasks.md:1)"
    ]


def test_a_short_reference_must_name_exactly_one_task(tmp_path: Path) -> None:
    (tmp_path / ".rulebook" / "archive").mkdir(parents=True)
    write_task(tmp_path, "phase3.1_backend", "- [ ] 1.1 Prerequisites accepted: phase2.9\n")
    write_task(tmp_path, "phase3.1_seam", "- Acceptance waits on: phase3.1\n")
    problems, edges = check(tmp_path)
    assert edges == []
    assert problems == [
        ".rulebook/tasks/phase3.1_backend/tasks.md:1: phase2.9 (no task) "
        "does not name exactly one task",
        ".rulebook/tasks/phase3.1_seam/tasks.md:1: phase3.1 (ambiguous: phase3.1_backend, "
        "phase3.1_seam) does not name exactly one task",
    ]


# The decision-121 chain as main b44760c wrote it (lines copied from the task files), and the
# same tasks after the decision-221 split.
VULKAN = (
    "- [ ] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase2.10_pilot-tunic-recovery\n"
)
TUNIC = (
    "- [ ] 1.1 Prerequisites accepted: phase2.9_pilot-belt, phase2.2_recipe-and-diagnostics, "
    "phase2.8_mcp-server\n"
)
MCP = "- [ ] 1.1 Prerequisites accepted: phase2.4_supervisor-worker\n"
SUPERVISOR_BEFORE = (
    "- [ ] 1.2 Child accepted: phase2.1_supervisor-ipc-worker\n"
    "- [ ] 3.4 GPU stall, DX12 device removal and Vulkan device loss: recovery without "
    "duplicate commit\n"
    "- [ ] 4.1 DAG gate met\n"
    "- 3.4: open. GPU stall and DX12 device removal pass (368 and 401 ms recovery). The Vulkan "
    "device-loss and stall variants wait for phase3.1_vulkan-compute-parity items 2.2 and 3.4 "
    "(decision 121).\n"
    "- 4.1: open. It waits on the Vulkan device cases (decision 121), on the hosted CPU lane "
    "(the owner's push) and on the children's acceptance (G1).\n"
)
SUPERVISOR_AFTER = (
    "- [ ] 1.2 Child accepted: phase2.1_supervisor-ipc-worker\n"
    "- [x] 3.4 GPU stall and DX12 device removal: recovery without duplicate commit. The Vulkan "
    "device-loss and stall variants are acceptance obligations of `phase3.1_vulkan-compute-parity` "
    "items 3.4 and 4.1 (decisions 121, 221), not waived\n"
    "- [ ] 4.1 DAG gate met\n"
    "- 4.1: open. It was held by the Vulkan device cases (decision 121; split by decision 221 "
    "below), the hosted CPU lane (removed by decision 200) and the children's acceptance (G1).\n"
)


def write_chain(root: Path, supervisor: str) -> None:
    (root / ".rulebook" / "archive").mkdir(parents=True)
    for archived in (
        "phase1.4_render-core-layer",
        "phase2.9_pilot-belt",
        "phase2.2_recipe-and-diagnostics",
    ):
        (root / ".rulebook" / "archive" / f"2026-10-10-{archived}").mkdir()
    write_task(root, "phase3.1_vulkan-compute-parity", VULKAN)
    write_task(root, "phase2.10_pilot-tunic-recovery", TUNIC)
    write_task(root, "phase2.8_mcp-server", MCP)
    write_task(root, "phase2.4_supervisor-worker", supervisor)
    write_task(root, "phase2.1_supervisor-ipc-worker", "- [x] 3.3 Device removal on DX12\n")


def test_the_audited_decision_121_cycle_fails_and_the_split_passes(tmp_path: Path) -> None:
    write_chain(tmp_path / "before", SUPERVISOR_BEFORE)
    problems, _ = check(tmp_path / "before")
    assert (
        "acceptance cycle: phase2.10_pilot-tunic-recovery -> phase2.8_mcp-server "
        "(accepted, .rulebook/tasks/phase2.10_pilot-tunic-recovery/tasks.md:1); "
        "phase2.8_mcp-server -> phase2.4_supervisor-worker "
        "(accepted, .rulebook/tasks/phase2.8_mcp-server/tasks.md:1); "
        "phase2.4_supervisor-worker -> phase3.1_vulkan-compute-parity "
        "(free-text, .rulebook/tasks/phase2.4_supervisor-worker/tasks.md:4); "
        "phase3.1_vulkan-compute-parity -> phase2.10_pilot-tunic-recovery "
        "(accepted, .rulebook/tasks/phase3.1_vulkan-compute-parity/tasks.md:1)"
    ) in problems

    write_chain(tmp_path / "after", SUPERVISOR_AFTER)
    problems, _ = check(tmp_path / "after")
    assert problems == []
