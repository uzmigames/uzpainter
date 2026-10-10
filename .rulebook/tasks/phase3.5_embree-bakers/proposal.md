# Proposal: phase3.5_embree-bakers

## Why
OWN-05 and BAK-02…BAK-07 (`docs/prd.md`) require UzPainter to bake mesh maps from high-poly meshes the way Painter does: Painter's parameter names, evidence that never alters the compatible map, receipts with surface accounting and atomic publication. This is DAG node P3-BAKER (`docs/dag.md`), implementing D5 in `docs/architecture/06-baking.md` (owner decision 022: CPU baking needs no GPU). The node bundles ten bakers plus their shared request model and publication path, so under the DAG task decomposition rule it is split into child tasks; this parent task is the integration and acceptance task and closes only when every mandatory child passes.

## What Changes
- Integrates the child tasks into one native bake subsystem: `IBaker` with the `EmbreeBaker` v1 reference backend, the ten `MeshMapUsage` bakers (`Normal`, `WorldSpaceNormal`, `ID`, `AO`, `Curvature`, `Position`, `Thickness`, `Height`, `BentNormals`, `Opacity`), the Painter-shaped parameter model, evidence receipts, atomic publication, linked sets and facade events (`06-baking.md` §1–§6).
- Publishes the Tier 2b report (`docs/architecture/14-parity-testing.md` §3) under `parity/reports/phase3/`: numbers and hashes only, the Painter CPU backend recorded per golden, hit/coverage evidence compared before maps, every exception from `parity/exceptions.json` it relied on listed; oracle blobs stay in `UZP_PARITY_STORE`.
- Verifies MCP cancellation during a native bake (`docs/architecture/11-mcp-server.md` §3, P3-BAKER item): `bake_start` then `job_cancel`; the final receipt says whether work stopped before or after commit.
- Regenerates the capability manifest so every baker usage is `supported` or an explicit release gap (for example the `Automatic` cage mode, `06-baking.md` §3).

## Dependencies
- DAG inputs: `phase2.10_pilot-tunic-recovery` (P2-TUNIC).
- Mandatory children: `phase3.1_baker-request-model`, `phase3.2_baker-normal`, `phase3.3_baker-evidence-publication`, `phase3.4_baker-ao`, `phase3.4_baker-world-space-normal`, `phase3.4_baker-id`, `phase3.4_baker-curvature`, `phase3.4_baker-position`, `phase3.4_baker-thickness`, `phase3.4_baker-height`, `phase3.4_baker-bent-normals`, `phase3.4_baker-opacity`.
- Downstream (DAG): `phase3.7_fixtures-bracers-hat5` (P3-BRACERS), `phase4.3_dxr-baker` (P4-DXR).

## Acceptance
DAG gate for P3-BAKER: Tier 2b published; MCP cancellation during a native bake passes. The parent closes only when all mandatory children pass (DAG task decomposition rule). Tier 2b equality is exact; an unreachable channel is a release gap or an owner-approved exception (`06-baking.md` §7, decision 017).

## Impact
- Affected specs: baker
- Affected code: native bake subsystem (`IBaker`, `EmbreeBaker`), `uzpainter.baking` and the `substance_painter.baking` facade, MCP Baking family, project mesh-map bindings, `assets/defaults/baking.json`, `parity/reports/phase3/`
- Breaking change: NO
- User benefit: high-poly bakes inside UzPainter with Painter's settings and auditable evidence, without Painter or a GPU
