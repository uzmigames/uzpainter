"""Acceptance-aware dependency check over the open rulebook tasks (decision 221).

`docs/dag.md` validates the nominal work-package graph. A task's acceptance can also wait on
conditions its checklist names outside that graph: unchecked "Prerequisites accepted" and
"Child accepted" lines, and notes saying an open item waits on another task. Those waits form
the acceptance graph; a cycle in it means none of its tasks can ever be accepted.

Coverage is bounded: only each open task's `.rulebook/tasks/<id>/tasks.md` is read. Proposals,
specs, decisions and `docs/` are not scanned, so every acceptance wait must be canonical in
tasks.md: an "accepted" prerequisite line or a structured `- Acceptance waits on:` line.

Edges, from each open task's tasks.md to another open task:

- an unchecked "Prerequisites accepted:", "Child accepted:" or "<task id> accepted" checklist
  line names the task ids it lists, up to the first ";" or sentence end (what follows there is
  an item-level or delivered-code input, not an acceptance);
- a structured line `- Acceptance waits on: <task id>[ item …], …` names the tasks the task's
  acceptance waits on outside its prerequisite lines;
- a free-text sentence "<…> waits on / wait for / waiting on <task id>" in an unchecked
  checklist line or in a note on an unchecked item, unless the sentence's subject before the
  wait names another task (then it describes that task's wait, not this one's).
  `decision 121` after the wait counts as `phase3.1_vulkan-compute-parity`, the task it
  deferred the Vulkan device cases to.

Archived tasks (`.rulebook/archive/<date>-<id>/`) are accepted, so edges to them are dropped.
A prerequisite or structured wait naming its own task is kept as a self-loop (a cycle); a
free-text wait naming its own task orders items inside the task and is not an edge.

Free-text waits are a safety net: they count as edges, so a cycle they close is found, and a
free-text wait on an open task that no canonical line of the same task names is a problem.

Problems reported: a cycle, including a self-loop; a prerequisite or structured wait naming no
known task, or a short reference (`phase3.1`) in one that does not resolve to exactly one task;
a free-text wait that is not canonical.

Run: `python -m tools.planning.acceptance_graph [--root PATH]`. Exit status 0 when no problem.
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

TASK_ID = re.compile(r"\bphase\d+(?:\.\d+)?_[a-z0-9]+(?:-[a-z0-9]+)*")
SHORT_ID = re.compile(r"\bphase\d+\.\d+\b(?!_)")
WAIT = re.compile(r"\b(?:waits?|waiting)\s+(?:on|for)\b", re.IGNORECASE)
STRUCTURED = re.compile(r"^- Acceptance waits on:\s*(.*)$")
CHECKBOX = re.compile(r"^- \[([ xX])\] (\d+\.\d+)\b")
# "Prerequisites accepted: <ids>", "Child accepted: <id>", "<id> accepted" (gate and parent items).
ACCEPTED = re.compile(r"\baccepted:|^- \[ \] \d+\.\d+ `?phase\S+?`? accepted\b")
NOTE = re.compile(r"^- (\d+\.\d+(?:-\d+\.\d+)?(?:,\s*\d+\.\d+(?:-\d+\.\d+)?)*)")
CLAUSE_END = re.compile(r"(?<=[.;])\s+")
# A decision that moved an obligation to a later task: a wait citing it waits on that task.
DECISION_TARGETS = {"121": "phase3.1_vulkan-compute-parity"}
DECISION_REF = re.compile(r"\bdecision (\d{3})\b")


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str  # "accepted" | "structured" | "free-text"
    where: str


def known_tasks(root: Path) -> tuple[set[str], set[str]]:
    open_ids = {p.parent.name for p in (root / ".rulebook" / "tasks").glob("*/tasks.md")}
    archived = {
        re.sub(r"^\d{4}-\d{2}-\d{2}-", "", p.name)
        for p in (root / ".rulebook" / "archive").iterdir()
        if p.is_dir()
    }
    return open_ids, archived


def resolve(text: str, every_id: set[str]) -> tuple[list[str], list[str]]:
    """Task ids named in `text`, and the short references that name no task or several."""
    ids = TASK_ID.findall(text)
    unresolved: list[str] = []
    for short in SHORT_ID.findall(text):
        matches = sorted(t for t in every_id if t.startswith(short + "_"))
        if len(matches) == 1:
            ids.append(matches[0])
        else:
            unresolved.append(
                f"{short} ({'ambiguous: ' + ', '.join(matches) if matches else 'no task'})"
            )
    for number in DECISION_REF.findall(text):
        if number in DECISION_TARGETS:
            ids.append(DECISION_TARGETS[number])
    return ids, unresolved


def item_states(lines: Sequence[str]) -> dict[str, bool]:
    """Item id -> checked, for every checklist line of a task."""
    return {m.group(2): m.group(1) != " " for line in lines if (m := CHECKBOX.match(line))}


def expand(items: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r",\s*", items):
        if "-" in part:
            first, last = part.split("-", 1)
            major, lo = first.split(".")
            last_major, hi = last.split(".")
            if major == last_major:
                out.extend(f"{major}.{n}" for n in range(int(lo), int(hi) + 1))
                continue
            out.extend((first, last))
        else:
            out.append(part)
    return out


def task_edges(task: str, text: str, every_id: set[str]) -> tuple[list[Edge], list[str]]:
    """The task's acceptance edges, and its prerequisite references that resolve to no task."""
    lines = text.splitlines()
    checked = item_states(lines)
    edges: list[Edge] = []
    problems: list[str] = []

    def formal(kind: str, listed: str, where: str) -> None:
        targets, unresolved = resolve(listed, every_id)
        edges.extend(Edge(task, t, kind, where) for t in targets)
        problems.extend(f"{where}: {ref} does not name exactly one task" for ref in unresolved)

    in_open_context = False
    for number, line in enumerate(lines, 1):
        where = f".rulebook/tasks/{task}/tasks.md:{number}"
        box = CHECKBOX.match(line)
        if box:
            in_open_context = box.group(1) == " "
            accepted = ACCEPTED.search(line) if in_open_context else None
            if accepted is not None:
                # The list ends at the first ";" or sentence end; what follows is item-level
                # ("for item 3.6 also …") or a delivered-code input, not an acceptance.
                listed = (
                    re.split(r";|\.\s", line[accepted.end() :], maxsplit=1)[0]
                    if accepted.group(0) == "accepted:"
                    else line[: accepted.end()]
                )
                formal("accepted", listed, where)
                continue
        elif (structured := STRUCTURED.match(line)) is not None:
            formal("structured", structured.group(1), where)
            in_open_context = False
            continue
        elif line.startswith("- "):
            note = NOTE.match(line)
            in_open_context = (
                any(not checked.get(item, False) for item in expand(note.group(1)))
                if note
                else False
            )
        elif not line.startswith("  "):
            in_open_context = False
        if not in_open_context:
            continue
        for clause in CLAUSE_END.split(line):
            wait = WAIT.search(clause)
            if wait is None:
                continue
            subjects = [t for t in resolve(clause[: wait.start()], every_id)[0] if t != task]
            if subjects:
                continue
            for target in resolve(clause[wait.end() :], every_id)[0]:
                if target != task:
                    edges.append(Edge(task, target, "free-text", where))
    return edges, problems


def find_cycles(nodes: set[str], edges: Sequence[Edge]) -> list[list[str]]:
    """One cycle per strongly connected component with a cycle: several nodes or a self-loop."""
    graph: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        graph[e.source].append(e.target)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for nxt in graph[node]:
            if nxt not in index:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            component: list[str] = []
            while True:
                top = stack.pop()
                on_stack.discard(top)
                component.append(top)
                if top == node:
                    break
            if len(component) > 1 or node in graph[node]:
                components.append(component)

    for node in sorted(nodes):
        if node not in index:
            visit(node)

    cycles: list[list[str]] = []
    for component in components:
        members = set(component)
        start = min(component)
        path = [start]
        seen = {start}
        while True:
            nxt = next(t for t in sorted(graph[path[-1]]) if t in members)
            if nxt in seen:
                cycles.append([*path[path.index(nxt) :], nxt])
                break
            path.append(nxt)
            seen.add(nxt)
    return cycles


def check(root: Path) -> tuple[list[str], list[Edge]]:
    open_ids, archived = known_tasks(root)
    every_id = open_ids | archived
    problems: list[str] = []
    edges: list[Edge] = []
    for task in sorted(open_ids):
        text = (root / ".rulebook" / "tasks" / task / "tasks.md").read_text(encoding="utf-8")
        edges_of_task, task_problems = task_edges(task, text, every_id)
        problems.extend(task_problems)
        canonical = {e.target for e in edges_of_task if e.kind != "free-text"}
        for edge in edges_of_task:
            if edge.target in archived:
                continue
            if edge.target not in open_ids:
                if edge.kind != "free-text":
                    problems.append(f"{edge.where}: {edge.target} names no known task")
                continue
            if edge.kind == "free-text" and edge.target not in canonical:
                problems.append(
                    f"{edge.where}: {task} waits on {edge.target} in free text only; record a "
                    "structured 'Acceptance waits on:' line, a prerequisite or a scope split"
                )
            edges.append(edge)
    problems = list(dict.fromkeys(problems))
    by_pair: dict[tuple[str, str], Edge] = {}
    for e in sorted(edges, key=lambda e: e.kind == "free-text"):
        by_pair.setdefault((e.source, e.target), e)
    for cycle in find_cycles(open_ids, edges):
        steps = "; ".join(
            f"{a} -> {b} ({by_pair[(a, b)].kind}, {by_pair[(a, b)].where})"
            for a, b in itertools.pairwise(cycle)
        )
        problems.append(f"acceptance cycle: {steps}")
    return problems, edges


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    problems, edges = check(args.root)
    kinds = {k: sum(e.kind == k for e in edges) for k in ("accepted", "structured", "free-text")}
    nodes = len(known_tasks(args.root)[0])
    print(
        f"acceptance graph (tasks.md of open tasks only): {nodes} open tasks, "
        f"{len(edges)} edges {kinds}"
    )
    for problem in problems:
        print(problem)
    print("no cycle" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
