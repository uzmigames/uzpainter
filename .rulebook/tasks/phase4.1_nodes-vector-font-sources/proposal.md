# Proposal: phase4.1_nodes-vector-font-sources

## Why
`docs/architecture/04-layer-stack-and-compositing.md` §1 defines `vector {sha256, params}` and `font {sha256, params}` as `Source` kinds of fills and fill effects, and `docs/architecture/10-python-api.md` §3 lists vector and font sources as a `release-gap` that raises `NotYetSupported` until implemented. OWN-01 (`docs/prd.md`) requires every output-affecting Painter capability to be `supported` or an explicit gap, CLR-01 requires behaviour implemented from public documentation and black-box calibration, RES-01/RES-02 require embedded, content-addressed resources, and LIC-02 requires every new third-party dependency to have a confirmed Apache-2.0-compatible licence. Child of P4-NODES (`phase4.2_remaining-nodes`) per the DAG task decomposition rule, implementing D3.

## What Changes
- **Document model**: `vector` and `font` sources on fills and fill effects (per channel and in mask stacks as documented), their documented parameters mirrored from Painter's public `source` API page, the vector file or font file embedded as a content-addressed resource (`03-project-model.md` §3).
- **Rasterisation**: vector and font sources rasterised into the source's UV space at the evaluation resolution, then sampled through the existing projection and filtering path (`04-…` §4–§5); rasteriser libraries vendored from upstream with confirmed licences, `ORIGIN.md`, `NOTICE` and `LICENSES/` entries (`docs/licensing-and-clean-room.md` §3); coverage, antialiasing and colour handling fitted from Tier 0 goldens and recorded in `parity/semantics/vector-font-sources.json`.
- **API**: `source_set` with the vector and font kinds in `uzpainter`, the `substance_painter` facade (documented symbols only, CLR-03) and the MCP stack family; set→get readback; recipe dump lists the source resources and parameters.
- **Capability manifest**: vector and font sources `supported` with Tier 0 evidence, or explicit gaps for any parameter whose golden is not exact.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Delivered upstream and used here: `phase1.14_compositor-core` (sources, projections, sampling), `phase1.24_python-api-facade`, `phase2.8_mcp-server` (stack family).
- Parent: `phase4.2_remaining-nodes`. Independent of the other children.

## Acceptance
Part of the P4-NODES gate (Tier 0 extended; manifest updated). This child is accepted when the Tier 0 goldens for vector and font sources (a UzmiGames-authored vector file and an openly licensed font on the plane and sphere fixtures, in a content stack and in a mask stack, across the documented parameters) are exact on the self-hosted GPU runner or covered by an owner-approved exception; source parameters read back exactly after save/reopen; and the dependency inventory lists every new library with its licence.

## Impact
- Affected specs: `compositor` (vector and font sources)
- Affected code: document model sources, rasterisation passes, resource import, `uzpainter`/`substance_painter` packages, MCP `source_set`, capability manifest, `thirdparty/`, `NOTICE`, `LICENSES/`, `parity/semantics/`
- Breaking change: NO
- User benefit: logos, decals and text can be placed through fills exactly as Painter places them
