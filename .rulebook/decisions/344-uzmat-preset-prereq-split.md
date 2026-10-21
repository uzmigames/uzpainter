# 344. phase3.2_uze-uzmat-preset checks its prerequisite item 1.1 on a recorded scope split: phase2.10's open work is the Tunic's own inputs and parity, and phase3.1_uze-uztexture-writer is archived

Date: 2026-10-21. Status: accepted. Routine technical choice, delegated by the owner. It applies decision 343's reasoning (decision 326's rule) to this task's prerequisite only.
Related: decisions 326 and 343, phase2.10_pilot-tunic-recovery, phase3.1_uze-uztexture-writer, phase3.4_uzengine-preset.

## Context

- **Item 1.1** reads "Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input), `phase3.1_uze-uztexture-writer`".
- **phase3.1_uze-uztexture-writer** is archived (`.rulebook/archive/2026-10-21-phase3.1_uze-uztexture-writer/`, decision 343). This task's derivatives use its BC encoder, mips and `.uztexture` writer unchanged.
- **phase2.10 is open.** Its open items are the Tunic v10 pilot's own work: the fixture manifest, the input inventory and its preservation (decisions 194 and 215), the rebuild through the typed MCP tools, dump-and-rebuild, Tier 1 equality and its report. The UzEngine preset reads no Tunic input and claims no Tunic parity. Its outputs are UzPainter's own formats (`uzengine.provenance.json`, layout `consumer`).

## Decision

1. **Item 1.1 is checked as a recorded scope split.** Its note names phase2.10 as not accepted and lists its open items. Nothing claims phase2.10 is accepted.
2. **Nothing else changes.** Every other open item keeps its own blocker: `AO_Mixed` (decision 131) for every plan that writes `$textureSet_orm`, the island rule (decision 245) and `infinite` padding on islands (decision 259) on wand v1, and the unrecorded SpecularWeight base value for a published `<set>_specularweight`. The child acceptance (4.1) stays open.

## Consequences

- If Tunic work later changes the export, the fix lands under phase2.10 or a new task. This item is not reopened for it.
