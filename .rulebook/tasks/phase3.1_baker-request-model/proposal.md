# Proposal: phase3.1_baker-request-model

## Why
BAK-03 (native high-poly bake with Painter's settings: highs per set, cage/distance, match by name, subsampling, dilation, backface, units), BAK-05 and NFR-02 (`docs/prd.md`) need one request model and one deterministic CPU ray-cast core that every baker shares. This child of P3-BAKER (`phase3.5_embree-bakers`, DAG task decomposition rule) implements `docs/architecture/06-baking.md` §1–§3 (D5; owner decision 022: CPU baking needs no GPU) and the parameter half of the MCP Baking family (`docs/architecture/11-mcp-server.md` §2).

## What Changes
- `IBaker { caps(); bake(const BakeRequest&) }`, `Capabilities` (usages, max resolution, determinism class), `BakeRequest` (one texture set, enabled usages, settings, input revision) and `JobHandle` (`06-baking.md` §1).
- `EmbreeBaker` on Embree 4.x from upstream (Apache-2.0), vendored under `thirdparty/` with its `LICENSE`/`NOTICE` and an `ORIGIN.md`, pinned version and build configuration (ISA set, internal tasking or TBB, no fast-math); an unqualified Windows/CPU/ISA configuration receives an explicit capability error.
- Determinism: fixed per-texel sample addressing (Hammersley by texel index and sample id), fixed reduction order, tile partitioning independent of thread count; the same sample sequences are exposed for the later `GpuBaker` (P4-DXR).
- Shared ray-cast core used by every usage: per-texel straight hit, cage hit, centre miss and hidden classification; match by name with `FilterMethod` and the `_low`/`_high`/`_ignorebf` suffixes; `LowAsHigh`; cage (custom file, distance-based frontal/rear absolute or relative to the bounding box; `Automatic` reported as a release gap); `IgnoreBackface`; `SubSampling` as explicit coverage accumulation; `DilationWidth` with optional `ApplyDiffusion` applied to the baked map only, RAW kept; distances in the project unit rule (`12-mesh-import.md` §3) recorded with the map.
- Parameter model mirroring Painter's dynamic `Property` model: `BakingParameters.common()` (common + detail), `baker(usage)`, `set({Property: value})`, `Property.{value,name,short_name,label,widget_type,enum_values,enum_value,properties}`; key names, labels, widget types, enum labels and ranges from the Phase 0 discovery capture and Adobe's public mesh-map settings pages; enum integers from `enum_values()` labels.
- `assets/defaults/baking.json`, authored by UzmiGames: each entry records its provenance (public page, or the hash of the private observation it must equal); checked against the private defaults capture on the self-hosted runner.
- Linked groups: `set_linked_group`, `set_linked_group_common_parameters`, `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*`; a settings change is one transaction across every linked set; `bake_settings {common, detail, per_baker}` persisted in the project manifest (`03-project-model.md`).
- MCP Baking family parameter tools: `bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_capture_preset`, `bake_apply_preset`.

## Dependencies
- Prerequisites: `phase2.10_pilot-tunic-recovery` (DAG input of P3-BAKER).
- Parent: `phase3.5_embree-bakers`. Unblocks `phase3.2_baker-normal`, `phase3.3_baker-evidence-publication` and every per-usage baker child.

## Acceptance
Baking defaults and property metadata equal the Tier 0 API-probe goldens exactly; `assets/defaults/baking.json` matches the private capture; the ray-cast core is repeatable across thread counts on one build and configuration; linked-set changes are atomic. Contributes to the P3-BAKER gate (Tier 2b published).

## Impact
- Affected specs: baker
- Affected code: bake subsystem core, `uzpainter.baking` / `substance_painter.baking` parameter API, MCP Baking tools, project manifest `bake_settings`, `thirdparty/` (Embree), `assets/defaults/baking.json`
- Breaking change: NO
- User benefit: Painter-compatible bake settings and a deterministic CPU bake core
