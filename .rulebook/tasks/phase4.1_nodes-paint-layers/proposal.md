# Proposal: phase4.1_nodes-paint-layers

## Why
LAY-12 (`docs/prd.md`) requires paint layers and paint effects driven through the API as layers that receive bitmaps and projections, accepted by Tier 0 goldens in Phase 4. Owner decision 019 (Q5, `docs/open-questions.md`) puts brush strokes out of scope — Painter's Python API exposes none — so no stroke engine is built anywhere and no stroke tool exists (`docs/architecture/11-mcp-server.md` §2). `docs/architecture/04-layer-stack-and-compositing.md` §1 gives paint layers and paint effects one authoritative raster plane per active channel, written only by typed bitmap operations: a whole bitmap in UV space at the plane's resolution, or a bitmap projected with the modes of §5. `docs/architecture/09-project-file-format.md` §1 stores those planes with persistent `plane_id`s and copy-on-write chunk versions, and `docs/architecture/10-python-api.md` §3 lists this capability as a `release-gap` until Phase 4. The DAG corpus migration assumption (`docs/dag.md`) lets existing paint content of the corpus fixtures (P3-BRACERS, P4-HAT8, P4-BODY) be imported as bitmaps when the documented export route preserves the required output. Child of P4-NODES (`phase4.2_remaining-nodes`) per the DAG task decomposition rule, implementing D3.

## What Changes
- **Paint layer and paint effect kinds**: `paint` layers in the hierarchy and `paint` effects in content stacks (per channel) and mask stacks (mono-channel), with the documented insertion rules and the documented `substance_painter` symbols for creating them (CLR-03).
- **Whole-bitmap operation**: writes a resource bitmap into the plane of each addressed channel at the plane's resolution and format, colour space handled as for bitmap sources (`04-…` §4); a new copy-on-write plane version per operation, one transaction.
- **Projected-bitmap operation**: rasterises a bitmap through any projection mode the compositor supports (UV, and the 3D modes and symmetry of `phase3.4_smart-projections`; `Warp`/`UVSetToUVSet` once `phase4.1_nodes-projections` is accepted) into the plane; a mode still a gap raises `NotYetSupported` before mutation.
- **Evaluation**: plane content blended with the node's per-channel mode and opacity, mask and content effects exactly like other layers (`04-…` §2); an empty plane reads as the plane's empty value.
- **Migration route**: a paint layer's content exported from Painter through the documented export API is imported with the whole-bitmap operation when that route preserves the required output; a fixture whose paint content cannot be reproduced through documented routes is recorded `not_migratable` with the reason and keeps its gate blocked unless an owner scope decision covers it (roadmap rule 7).
- **API**: the native `uzpainter` paint-content operations and the typed MCP tool `paint_set {uid, channel|None, bitmap | projected_bitmap {resource, projection}}` in the stack family; recipe dump lists planes with their content versions; no stroke symbol anywhere.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Child-level prerequisite: `phase3.4_smart-projections` (projection kernels used to rasterise projected bitmaps).
- Delivered upstream and used here: `phase1.8_project-store` (planes, chunk versions), `phase1.14_compositor-core`, `phase2.8_mcp-server`.
- Parent: `phase4.2_remaining-nodes`. Consumers of the migration route: `phase4.2_coverage-hat-v8`, `phase4.1_coverage-body-v6b` (no DAG edge; they use it when it is available). Hat v5 is not a consumer: `phase3.7_fixtures-bracers-hat5` precedes this node in the DAG and handles hat v5 paint content by the corpus migration rule in Phase 3 (bitmap import when the documented export route preserves the output, else `not_migratable`, which blocks G3 until an owner scope decision), without depending on paint layers.

## Acceptance
Part of the P4-NODES gate (Tier 0 extended; manifest updated). This child is accepted when the Tier 0 goldens for paint layers and paint effects receiving bitmaps and projections (empty paint layer and paint effect semantics; whole bitmaps in content and mask stacks; projected bitmaps per supported mode; blending, masks and content effects over paint content) are exact on the self-hosted GPU runner or covered by an owner-approved exception; every golden that Painter's documented routes cannot produce is recorded `not_migratable` and reported, not passed; planes never alias after save, reopen, revert and compaction; and no stroke operation exists in any API.

## Impact
- Affected specs: `compositor` (paint layers and paint effects)
- Affected code: document model (paint kinds, planes), project store plane versions, compositor evaluation, projection rasterisation into planes, `uzpainter`/`substance_painter` packages, MCP stack family (`paint_set`), recipe dump, capability manifest
- Breaking change: NO
- User benefit: paint content needed by the coverage fixtures can be migrated and authored by agents without a stroke engine
