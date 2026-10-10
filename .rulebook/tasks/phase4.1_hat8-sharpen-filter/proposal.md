# Proposal: phase4.1_hat8-sharpen-filter

## Why
LAY-04 (`docs/prd.md`) lists sharpen among the layer-mask operations, accepted by Tier 0 mask goldens; the DAG names Sharpen as a P4-HAT8 output because hat v8 uses it (`docs/dag.md`; `docs/architecture/14-parity-testing.md` §3, Tier 1 corpus "Hat v8 (SpecularWeight, Sharpen, 43 layers)"). The Sharpen filter family itself — kernel, parameter discovery, provenance and Tier 2a certification on layer content — is delivered by P3-PROC (`phase3.2_proc-filter-families`, `docs/architecture/05-procedural-content.md` §3 "Filters: Sharpen (hat v8)", §6). The Phase 0 Tier 0 mask corpus covers background, fill effect, levels, subtract, compare mask and colour selection, but not sharpen (`14-…` §3), so the mask-stack behaviour of Sharpen — mono-channel input, `channel=None` blending, its place in the ordered mask effects (`docs/architecture/04-layer-stack-and-compositing.md` §1, §2 step 5) — and hat v8's recorded uses are still unproven. Exact equality and the exception register apply (decision 017, Q1); the implementation stays clean-room (decision 002, CLR-01).

## What Changes
- **Sharpen in mask stacks**: the certified Sharpen family inserted as a filter effect in a mask stack — mono-channel evaluation of the current mask value, mask-stack blending with `channel=None`, documented insertion rules and errors — through the native `uzpainter` API, the `substance_painter` facade (documented symbols only) and the typed MCP stack family.
- **Tier 0 mask goldens for sharpen**: UzmiGames-authored synthetic fixtures (plane, sphere, bevelled cube) with sharpen over bitmap and levels mask content at a sweep of parameters, modes and opacities, recorded through Painter's documented API twice and stored privately; manifests `parity/manifests/tier0/mask-sharpen-*.json`.
- **Hat v8 parameter coverage**: every Sharpen instance of the hat v8 recipe (content and mask context) evaluated with its recorded parameters; if P3-PROC's Tier 2a matrix lacks hat v8's recorded parameter sets, they are added to it.
- **Capability manifest**: the Sharpen filter effect `supported` in the mask-stack context with its Tier 0 evidence id.

## Dependencies
- Parent DAG inputs: `phase3.7_fixtures-bracers-hat5`, `phase3.4_uzengine-preset` (this child needs only the first).
- Upstream used here: `phase3.3_procedural-families`, specifically `phase3.2_proc-filter-families` (certified Sharpen family).
- Parent: `phase4.2_coverage-hat-v8`. Independent of `phase4.1_hat8-specular-weight-export`.

## Acceptance
Part of the P4-HAT8 gate (equal maps). This child is accepted when the Tier 0 sharpen mask goldens are exact (or covered by an owner-approved exception), every hat v8 Sharpen instance evaluates equal to Painter with its recorded parameters, and the capability manifest lists Sharpen in mask stacks as `supported` with its evidence.

## Impact
- Affected specs: `procedural` (Sharpen in mask stacks)
- Affected code: mask-stack effect evaluation for filter effects; facade/native/MCP insertion of the filter in mask stacks; `parity/manifests/tier0/`; capability manifest
- Breaking change: NO
- User benefit: hat v8's sharpened masks reproduce exactly, and sharpen becomes a proven mask operation for all stacks
