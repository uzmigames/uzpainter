# 347. Bake evidence, receipt and publication: the used surface is the conservative UV coverage (open texel square meets a UV triangle), its seven classes are counted per usage, the neutral fallback is Normal-only and opt-in, and publication binds AO and Normal only, atomically on the revision the bake read

**Status**: accepted
**Date**: 2026-10-21
**Related Tasks**: phase3.3_baker-evidence-publication, phase3.5_embree-bakers

## Context

`06-baking.md` §4 names the evidence maps, the `BakeReceipt` fields, the seven used-surface classes and atomic publication per `(texture set, input revision)`. It leaves these forks open: what "conservative coverage" and "ring" mean on UzPainter's sampler, how a ring texel is classed when the map does not extend into it, what "fallback" is when no request field enables one, which maps a binding can hold, and what "input revision" is checked against. The pipeline's `used_surface_summary` (`A3D\Pipeline\painting\bake_normal_pair.py`, UzmiGames code) is the reference the section cites. No Painter behaviour is involved: these are UzPainter's own records, and nothing here claims parity.

No model panel ran: the coordinator fixed the scope (items 2.1-2.4, 3.1, 3.2; CPU only), and each fork below follows the section's text or the pipeline's rule.

## Decision

1. **The used surface.** A texel is in the used surface when its open square overlaps the interior of a low UV triangle with a nonzero UV area (separating axes with strict overlap: the two box axes and the three edge normals). A texel touched only along an edge or at a corner is not. Every texel the baker samples (class other than `Uncovered`) is in it, because a sample lies strictly inside its texel; the accounting checks this. `BakeResult::used_surface` holds it, computed after the cast; the canonical bytes do not change.
2. **The seven classes, per usage.** `hit_straight` and `hit_cage` (the texel classes), `miss` (centre misses and back-face hits: sampled, no front hit), `hidden` (the `Hidden` class: sampled and masked), `ring_extended` (a ring texel the compatible map was extended into: AO's dilation, recorded in `BakeResult::extension`), `ring_no_hit_neighbour` (a ring texel the compatible map holds no value for, as the pipeline's `ring_flat` is a ring texel not filled), `repaired` (always 0). A ring texel keeps its ring class whatever the hidden mask says: the baker casts no ray for it. A texel's part is the part of its first covered sub-sample (`BakeResult::texel_part`).
3. **The other counts.** `padding_texels`: texels outside the used surface. `changed_used_texels`: used texels whose compatible map differs from RAW, literally (a ring extension counts). `surface_modified`: a fallback or a repair; a ring extension is edge extension, not a modification (the pipeline's rule). `z_negative_texels`: Normal only, hit texels whose RAW blue code is below 32768; null for other usages.
4. **The neutral fallback.** `BakeRequest::neutral_fallback`, off by default, sets the used Normal texels without a hit to the flat tangent normal (codes 32768, 32768 or 32767 for DirectX, 65535); RAW is kept and `fallback_texels` counts them. It is refused (`NotYetSupported`) with any other usage: no neutral value is established for them. `fidelity_evidence` is `diagnostic_only` for a diagnostic bake or a repair, `contains_fallback` with a fallback texel, `used_surface_as_baked` otherwise.
5. **Evidence files.** Per usage under `cache/bake/<first 16 hex of SHA-256(set + "\n" + input revision)>/<Usage>/`: `map`, `raw` (none for Thickness), and the 8-bit masks `hit`, `coverage`, `miss`, `extension`. 8- and 16-bit maps are PNG through the export's encoder; float32 maps use the evidence container `UZPF32\0\0` + width, height, channels + the float bits, little-endian (an evidence format, never a binding). They are a pure function of the request and the result, so they regenerate byte for byte.
6. **The receipt.** Every §4 field, the record header and the baker's `parity_status`. Mesh hashes are content hashes of the bake meshes (the caller's `resource_hashes` name the files); a part lists the high meshes its rays may hit under `FilterMethod`; a distance-based cage is `{frontal, rear, relative}` from the request. `settings_hash` covers every output-determining setting, not the meshes, mask or thread count.
7. **Publication.** One document transaction. It requires `input_revision` to be the document's current revision in decimal (a stale bake is refused), the set's resolution to equal the output size (resampling is not established), Normal's format and tangent space to be the project's and a non-diagnostic result. Only AO (L16) and Normal (RGB16) are bound: the float maps have no established channel format (decisions 337 and 341), ID has no colour map and Thickness no per-texel value, so a bake with any of them is refused before mutation, naming the owner task. The maps and the receipt are staged and given resource entries; each binding's `baked.extra` holds the receipt's hash, the job id, the fidelity evidence and `parity_status`. Any refusal, failure or commit-sink error commits nothing.
8. **Exposure.** All of this is native. Python and MCP do not reach it; items 2.5-2.7 (jobs, facade, MCP) remain open, and when they expose publication the pending-evidence usages stay refused under decision 001.

## Alternatives Considered

- **Closed texel squares (edge contact counts).** Rejected: an island whose edge lies on a texel boundary would gain a ring of texels it does not overlap, as the pipeline's epsilon does; with open squares the bevelled cube's islands have no ring.
- **A ring texel with a hit neighbour but no dilation as `ring_extended`.** Rejected: the compatible map holds nothing there, so calling it extended would describe a value that does not exist.
- **Binding the float maps as RGB32F/L32F through OpenEXR.** Rejected: it chooses a channel format decisions 337 and 341 left to the Tier 2b goldens, and the bake tests would need the evaluator's arithmetic for the EXR writer.
- **Comparing only the bake's inputs (mesh and settings hashes) instead of the revision.** Not taken: the store holds no per-set input digest yet, and while a bake runs the project is busy (§6); an exact revision is the strict reading of "per input revision".

## Consequences

- New: `src/bake/bake_accounting.{h,cpp}`, `bake_receipt.{h,cpp}`, `bake_publication.{h,cpp}`, `tests/bake/receipt_bake_cases.h` (seven native cases).
- Changed: `bake_request.h` (`neutral_fallback`, `used_surface`, `texel_part`, `extension`, `fallback_texels`), `embree_baker.{h,cpp}` (the fallback check, the three per-texel records, `MatchedHighMeshes`), `build.zig` (appended: the new sources and the PNG encoder in `bake-feasibility-tests`), `06-baking.md` §4.
- The canonical bytes of every existing result are unchanged; a Normal bake with the fallback on differs in its `normal` map only.
- Parity stays `pending-evidence` for every usage; every Tier 2b item stays open.
