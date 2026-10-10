# Proposal: phase4.2_remaining-nodes

## Why
OWN-01 (`docs/prd.md`) requires every output-affecting Painter capability to be `supported` or an explicit gap, and G5 accepts a gap only through an owner scope decision. After Phase 3 the layer model of `docs/architecture/04-layer-stack-and-compositing.md` §1 still has documented node, effect and source kinds without an implementation: instance layers, anchors and anchor references (§2 steps 4, 6, 7), the compare-mask and colour-selection mask effects (LAY-04; Tier 0 mask ops of `docs/architecture/14-parity-testing.md` §3), the `Warp` and `UVSetToUVSet` projections (§5, release gaps until their goldens exist), vector and font sources (§1 `Source`), and paint layers and paint effects as receivers of bitmaps and projections (LAY-12; §1, owner decision 019 — brush strokes are out of scope and no stroke engine is built). `docs/architecture/10-python-api.md` §3 lists each of them as a `release-gap` raising `NotYetSupported`; `docs/architecture/11-mcp-server.md` §2 registers their typed tools as capability gaps until this node lands, and §7 requires Python-disabled conformance for "the later node, effect and source kinds and paint layers receiving bitmaps and projections" at release (INT-02, ARC-14). This is DAG node P4-NODES (`docs/dag.md`), implementing D3.

This task is the parent integration and acceptance task. The DAG task decomposition rule names its children; each owns an independently testable set of kinds with its own Tier 0 goldens.

## What Changes
- `phase4.1_nodes-instances-anchors`: instance layers (`layer_instantiate`), anchor effects, anchor reference sources with channel mapping, alpha matte and levels, and the acyclic anchor dependency graph.
- `phase4.1_nodes-mask-effects`: compare-mask and colour-selection effects in mask stacks, with their insertion rules.
- `phase4.1_nodes-projections`: the `Warp` and `UVSetToUVSet` projection modes (with the additional UV sets the mesh import records), and symmetry where the documented parameters apply to them.
- `phase4.1_nodes-vector-font-sources`: vector and font sources in fills and fill effects.
- `phase4.1_nodes-paint-layers`: paint layers and paint effects that receive whole bitmaps and projected bitmaps into their authoritative planes (no stroke engine).
- Parent integration: the Tier 0 corpus extended with the new kinds (`parity/manifests/`, private goldens recorded twice), the capability manifest regenerated with each new kind `supported` with tier evidence or kept as an explicit gap, and the requirement-to-typed-operation matrix rows for these families moved from `capability gap` to `available` with their Python-disabled conformance fixtures.

## Dependencies
- DAG inputs: `phase2.10_pilot-tunic-recovery` (P2-TUNIC).
- Children (mandatory; independent of each other): `phase4.1_nodes-instances-anchors`, `phase4.1_nodes-mask-effects`, `phase4.1_nodes-projections`, `phase4.1_nodes-vector-font-sources`, `phase4.1_nodes-paint-layers`.
- Child-level edge outside this node: `phase4.1_nodes-projections` and `phase4.1_nodes-paint-layers` reuse the 3D projection and symmetry kernels of `phase3.4_smart-projections`.
- Downstream: `phase4.5_uv-tiles` (P4-TILES), `phase4.6_gate-g4` (G4); `phase5.2_parity-report-mcp-conformance` consumes the conformance fixtures.

## Acceptance
DAG gate of P4-NODES: Tier 0 extended; manifest updated. In substance: every child task is accepted; the Tier 0 corpus contains exact goldens for instances, anchors and anchor references, compare mask, colour selection, warp and UV-set projections, vector and font sources, and paint layers and paint effects receiving bitmaps and projections, all passing in a local run on the owner's machine (decision 028; the local run report is the evidence) (any difference only through an owner-approved exception, decision 017); the capability manifest shows each of these kinds `supported` with its evidence or as an explicit gap, and no kind is silently a no-op (ARC-03).

## Impact
- Affected specs: `compositor` (remaining node, effect and source kinds)
- Affected code: document model and layer insertion rules, compositor kernels and evaluation graph, project store planes, `uzpainter`/`substance_painter` packages, MCP stack family, capability manifest and operation matrix, `parity/manifests/`, `parity/semantics/`
- Breaking change: NO
- User benefit: the documented Painter layer model is complete apart from listed gaps, so the coverage fixtures and later recipes need no workaround
