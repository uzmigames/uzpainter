# Proposal: phase4.1_nodes-mask-effects

## Why
LAY-04 (`docs/prd.md`) requires layer masks with ordered typed effects; Phase 1 (`phase1.14_compositor-core`) delivered background, bitmap fill effect, levels, subtraction and sharpen, while the compare-mask and colour-selection effects of `docs/architecture/04-layer-stack-and-compositing.md` §1 (`Effect` kinds `compare_mask` with `CompareMaskParams`, `color_selection` with `ColorSelectionParams`) remain to be implemented. Both are part of the Tier 0 mask-operation corpus of `docs/architecture/14-parity-testing.md` §3, and the insertion rules of `04-…` §1 allow them only in mask stacks, which are mono-channel. OWN-01 requires each to be `supported` or an explicit gap; `docs/architecture/11-mcp-server.md` §2 keeps their `effect_insert` kinds as capability gaps until implemented. Child of P4-NODES (`phase4.2_remaining-nodes`) per the DAG task decomposition rule, implementing D3.

## What Changes
- **Effect kinds**: `compare_mask` and `color_selection` in the document model with their documented parameters mirrored from Painter's public layer-stack API pages; insertion allowed only in mask stacks, anywhere else raising the documented error before mutation.
- **Kernels**: mono-channel mask kernels evaluated in mask-stack order with their own mode and opacity (`04-…` §2 step 5), reading the inputs their documented parameters name (for colour selection, the bound mesh map by usage, failing loudly when it is missing or `invalid`, `03-project-model.md` §4); semantics fitted from Tier 0 goldens and recorded in `parity/semantics/mask-effects.json` (numbers only).
- **API**: both kinds in `effect_insert`/`effect_set` for `uzpainter`, the `substance_painter` facade (documented symbols only, CLR-03) and the MCP stack family, with set→get readback and recipe-dump entries.
- **Capability manifest and operation matrix**: entries with Tier 0 evidence and Python-disabled conformance fixtures.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Delivered upstream and used here: `phase1.14_compositor-core` (mask stacks, mask kernels), `phase1.24_python-api-facade`, `phase2.8_mcp-server`; for colour selection, mesh-map bindings from `phase1.3_document-model` (imported maps) or `phase3.5_embree-bakers` (baked ID maps).
- Parent: `phase4.2_remaining-nodes`. Independent of the other children.

## Acceptance
Part of the P4-NODES gate (Tier 0 extended; manifest updated). This child is accepted when the Tier 0 goldens for compare mask and colour selection (parameter sweeps on the plane, sphere and bevelled cube; ordering with the Phase 1 mask effects; mode and opacity in the mask stack; insertion-rule probes) are exact in a local run on the owner's machine (decision 028; the local run report is the evidence) or covered by an owner-approved exception, and both kinds appear in the capability manifest with their evidence.

## Impact
- Affected specs: `compositor` (compare mask and colour selection)
- Affected code: document model effect kinds and insertion rules, mask kernels, `uzpainter`/`substance_painter` packages, MCP `effect_insert`/`effect_set`, capability manifest, `parity/semantics/mask-effects.json`
- Breaking change: NO
- User benefit: mask recipes that select by colour or compare masks evaluate as in Painter
