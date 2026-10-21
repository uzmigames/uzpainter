# 343. phase3.1_uze-uztexture-writer closes on a recorded scope split: its only open items are a prerequisite and a parent report, and phase2.10's open work is the Tunic's own input recovery and parity

Date: 2026-10-21. Status: accepted. Routine technical choice, delegated by the owner ("atualiza e arquive as tasks finalizadas e foque em terminar as tasks q ja tao mais avancadas"). It applies decision 326's rule.
Related: decision 326, phase2.10_pilot-tunic-recovery, phase3.4_uzengine-preset.

## Context

- **Done.** Every deliverable item of phase3.1_uze-uztexture-writer is checked: 2.1 to 2.8, 3.1 to 3.7 and 5.1 to 5.3. These cover the vendored etcpak BC encoders, deterministic mips for colour, normal and masked albedo, the `.uztexture` writer, the negative-Z normal guard, the test-only decoder and reader, and the lossy-derivative report.
- **Tested.** Its tests passed in the green coordinated full suite at `1103f00c` (3781 passed). No writer source has changed since.
- **Still open, item 1.1:** "Prerequisites accepted: phase2.10_pilot-tunic-recovery (parent input)".
- **Still open, item 4.1:** "Child acceptance met and reported to phase3.4_uzengine-preset".
- **Why phase2.10 is open.** Its open items are the Tunic v10 pilot's own inputs and parity: the input inventory and its preservation (decisions 194 and 215), the rebuild through the typed MCP tools, Tier 1 equality, and dump-and-rebuild. The `.uztexture` writer does not read the Tunic's maps or their parity.

## Decision

1. **Item 1.1 is checked as a recorded scope split.** Its note names phase2.10 as not accepted and lists its open items. Nothing claims phase2.10 is accepted.
2. **Item 4.1 is checked once the report is made.** The report is a note in phase3.4_uzengine-preset item 2.1, citing the evidence. That item, and phase3.4's own equality items such as 4.2 (byte-identical `.uzmat`, `.uztexture` and canonical maps over two runs), stay open in phase3.4.
3. **The task is archived** under `.rulebook/archive/2026-10-21-phase3.1_uze-uztexture-writer/`.

## Consequences

- If later Tunic work changes the writer, the fix lands under phase2.10 or a new task. This task is not reopened for it.
