# 316. The `.uztexture` normal derivative is a plan field with a negative-Z policy, `fail` by default, cooked in the export engine from the canonical PNG 16

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.1_uze-uztexture-writer, phase3.4_uzengine-preset, phase3.3_uze-consumer-fixture

## Context

Items 2.7 and 3.5 of `phase3.1_uze-uztexture-writer` need the negative-Z guard in the real export. A library check is not enough. The export must fail, or route the map to an RGB format, according to a plan option, and the receipt must record the choice (`08-export.md` §4). Decision 315 item 5 put the guard in `CookUzTexture` and left the plan option and its receipt record to `phase3.4_uzengine-preset`. No export output wrote a `.uztexture`, so nothing reached the guard.

## Decision

1. **Plan field.**
   - `PlannedFile::uztexture` (`src/export/plan.h` `UzTextureOutput`) requests a `.uztexture` normal derivative of one planned file, with `NegativeZPolicy` `fail` (the default) or `rgb`.
   - `RequestUzTextureNormal(plan, relativePath, policy)` sets it and recomputes the plan hash. plan.json lists it under the file, and the dry run (`FilesByStack`) lists the derivative after its file.
   - The field is the whole surface here. `CompilePlan` never sets it, and no configuration or preset key reaches it. Which preset maps get a derivative, and the policy a preset chooses, belong to `phase3.4_uzengine-preset`.
2. **Bound.**
   - The file is an RGB PNG 16 whose R, G and B read components 0, 1 and 2 of one normal source: the Normal channel, a virtual normal or `normal_base`.
   - Both sides are powers of two (decision 315 item 3).
   - The PNG 16 is the derivative's canonical 16-bit companion (EXP-10, `08-export.md` §4).
   - Any other file is refused with `NotYetSupported` naming `phase3.4_uzengine-preset`.
   - The derivative's path is the file's, with `.uztexture` for its extension. A path equal to another output's, ignoring case, is a `ValueError`.
3. **Cook.**
   - `EncodeExport` (`src/export/write.cpp`) cooks the derivative in step 2, in memory. Its source is the file's PNG samples as written, after padding and transfer (`EncodeFile`'s `samples`), with A = 65535. The file is evaluated once.
   - The guard counts the texels with B <= 32767 (Z < 0, `FindNegativeZ`).
   - With any such texel, under `fail`: an `export:` failure naming the canonical file, the count and the first texel. It is returned before any generation is claimed, so nothing is published and the previous generation stays selected.
   - With any such texel, under `rgb`: the map is stored as `Uncompressed_RGBA8`, whose B keeps Z's sign.
   - Otherwise: BC5.
   - Both stored formats use the Normal mip class of decision 315 (binding `normal`, linear, etcpak 2.1).
4. **Publication.** The derivative is written, flushed and verified right after its file in the same generation, so publication stays all-or-nothing.
5. **Receipt.**
   - The derivative is its own `files[]` entry: format `uztexture`, bit depth 8, linear.
   - It carries `uztexture` {source, binding, format (`BC5` or `RGBA8`), srgb, mips, encoder, negative_z {policy, texels, first, routed}}. The schema is `src/export/schema/receipt.schema.json` `$defs/uztexture_derivative`, an additive change under `uzpainter/export-receipt/1`.
   - A routed derivative also carries a `Normal` consumer gap. UzEngine's fixed G-buffer path reconstructs a non-negative Z from X and Y (`docs/analysis/reviews/assets3d-pipeline-astra-review.md` C09), so the routed sign survives only in a consumer that reads B. Accepting that binding belongs to `phase3.3_uze-consumer-fixture`.
6. **Linking.** Amends decision 315 item 1. `uzp_texture` (with etcpak's encoders) is linked into every binary that compiles the export sources: `UzPainter.exe`, `uzp-export-tests.exe` and `uzp-pyapi-tests.exe`. etcpak's BC encoders are therefore shipped. `NOTICE` already carries their licences.

## Consequences

- The guard is exercised through `PublishExport` on a synthetic negative-Z fixture (`tests/export/test_export_publication.py`). Under `fail` nothing is published. Under `rgb` the derivative is RGBA8, its decoded B is negative at the texel, and the receipt records the policy, the count and the format.
- Until `phase3.4_uzengine-preset` maps presets onto this field, only code that builds a plan can request a derivative (the native test driver's `publish --uztexture`).
