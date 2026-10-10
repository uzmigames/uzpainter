## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [x] 2.1 Author the synthetic meshes (plane, sphere, bevelled cube) with UVs and the bitmap inputs (16-bit gradients, height ramps, AO mesh-map bitmap) with provenance; describe them in `parity/manifests/phase0/tier0-semantics.json`
- [x] 2.2 Instruction sequences and goldens for the 32 `BlendingMode` members: value and opacity sweeps per channel storage format, plus asymmetric stacks for evaluation order (31 members on fills; `PassThrough`, a group mode not settable through the 12.1.0 API, — moved to `phase0.7_tier0-semantics-ui-cases` (owner answer to q1, 2026-10-10))
- [x] 2.3 Instruction sequences and goldens for quantisation points: three 1/3-opacity fills per channel format, and uniform-colour ramps per documented colour space
- [x] 2.4 Goldens for stack base values per template (empty-project export)
- [x] 2.5 Goldens for mask precision with the 16-bit gradient mask, and for group `Normal`/`PassThrough` with masks on the group and on children (mask precision and group `Normal` with masks recorded; group `PassThrough` — moved to `phase0.7_tier0-semantics-ui-cases` (owner answer to q1, 2026-10-10))
- [x] 2.6 Goldens for content-effect order (fill effect, levels, filter permutations) and for the levels clamp at and beyond the range ends
- [x] 2.7 Goldens for `BilinearHQ` resampling of the authored bitmap at non-1:1 scales
- [x] 2.8 Goldens for both height→normal methods over the height ramps with a strength sweep, and for `AO_Mixed` with the authored AO mesh map and an AO-channel sweep (default method and strength on plane, sphere and bevelled cube, and `AO_Mixed`, recorded; second method and strength sweep — moved to `phase0.7_tier0-semantics-ui-cases` (owner answer to q1, 2026-10-10))
- [x] 2.9 Record every golden at least twice (same session; after save/reopen) through `export_project_textures` at 16 bit or float; admit the records with `uzpainter parity record` and write their hashes, settings and software identities into the public manifest

## 3. Tests
- [x] 3.1 Manifest test: `parity/manifests/phase0/tier0-semantics.json` validates against `parity/schema/golden-public.json` and lists at least two recordings per golden
- [x] 3.2 Store test: `uzpainter parity verify` passes for every hash of the manifest on the owner's machine
- [x] 3.3 Coverage test: every item of `04-layer-stack-and-compositing.md` §9 maps to at least one golden id in the manifest
- [x] 3.4 Guard test: no recorded export or readback is committed; the guard passes on the repository

## 4. Acceptance
- [x] 4.1 Child acceptance (contributes to P0-TIER0): every §9 item has goldens recorded ≥ 2× through the documented API at native depth; blobs private, hashes public; verify passes (48 goldens recorded twice and admitted, verify and guard pass; the three UI-only cases — moved to `phase0.7_tier0-semantics-ui-cases` (owner answer to q1, 2026-10-10))

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
