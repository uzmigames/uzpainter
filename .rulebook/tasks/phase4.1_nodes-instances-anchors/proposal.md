# Proposal: phase4.1_nodes-instances-anchors

## Why
`docs/architecture/04-layer-stack-and-compositing.md` §1 defines instance layers (`kind = instance`, `instance_source`), anchor effects (`kind = anchor`) and reference sources (`reference {anchor uid, channel_mapping | referenced_channel, alpha_matte, levels}`); §2 fixes their evaluation: an anchor publishes the current content under its name (step 4), an instance evaluates the source layer's subtree in the instance's position (step 6), and anchor references form a dependency graph that must be acyclic, raising `ValueError` on cycles as documented (step 7). The insertion rules of §1 allow instances only in the hierarchy. OWN-01 (`docs/prd.md`) requires each kind to be `supported` or an explicit gap; `docs/architecture/11-mcp-server.md` §2 registers `layer_instantiate` and `anchor_list` as capability gaps until this lands, and ARC-13 requires the facade to reproduce Painter's output-changing quirks. Child of P4-NODES (`phase4.2_remaining-nodes`) per the DAG task decomposition rule, implementing D3.

## What Changes
- **Instance layers**: creation from a source layer through the documented API, insertion only in the hierarchy, evaluation of the source subtree at the instance's position with the instance's own blending, mask and geometry mask; edits to the source propagate; source deletion handled as Painter documents it (Tier 0 probe).
- **Anchor effects**: an anchor publishes the layer's current content under its name at its position in the content-effect list.
- **Reference sources**: `reference` sources in fills, fill effects, generator image inputs and masks reading an anchor with channel mapping or a referenced channel, alpha matte and levels, as documented; semantics fitted from Tier 0 goldens and recorded in `parity/semantics/anchors.json`.
- **Dependency graph**: anchor references and instances join the evaluation DAG (`04-…` §7); invalidation follows the referenced anchor's subtree hash; a cycle raises `ValueError` before mutation.
- **API**: `layer_instantiate`, `anchor_list` and reference sources through `source_set` in `uzpainter`, the `substance_painter` facade (documented symbols only, CLR-03) and the MCP stack family; set→get readback; recipe dump records instance sources and anchor references by uid.
- **Capability manifest and operation matrix**: entries with Tier 0 evidence and Python-disabled conformance fixtures.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Delivered upstream and used here: `phase1.14_compositor-core` (evaluation DAG, cache, content effects), `phase1.24_python-api-facade`, `phase2.8_mcp-server`; generator image inputs from `phase3.3_procedural-families`.
- Parent: `phase4.2_remaining-nodes`. Independent of the other children.

## Acceptance
Part of the P4-NODES gate (Tier 0 extended; manifest updated). This child is accepted when the Tier 0 goldens for instances (same and different blending, masked instance, edited source), anchors and reference sources (channel mapping, referenced channel, alpha matte, levels; references in masks and generator inputs) and the cycle and insertion probes are exact in a local run on the owner's machine (decision 028; the local run report is the evidence) or covered by an owner-approved exception, and the kinds appear in the capability manifest with their evidence.

## Impact
- Affected specs: `compositor` (instances and anchors)
- Affected code: document model (instance layers, anchor effects, reference sources), evaluation DAG and invalidation, `uzpainter`/`substance_painter` packages, MCP `layer_instantiate`, `anchor_list`, `source_set`, recipe dump, capability manifest, `parity/semantics/anchors.json`
- Breaking change: NO
- User benefit: stacks that reuse content through instances and anchors evaluate as in Painter
