# 420. A UzEngine material without an Emissive channel binds the black emissive derivative cook-uzengine cooks, with no canonical file

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase3.2_uze-uzmat-preset, phase3.3_uze-png-cook-cli, phase3.4_uzengine-preset
**Extends**: decision 380 §6 (the cook's missing emissive) to the native UzEngine preset

## Context

The `.uzmat` binds four textures: albedo, normal, ORM and emissive (`src/export/uzmat_writer.h`,
U-UZE-RUNTIME a703c95). The native preset skipped the whole `.uzmat` when one of the four was not
written (`src/export/plan.cpp` `AttachUzEngine`). The pilots are made on the default template,
whose channels are BaseColor, BaseMetalness, Height, Normal and SpecularRoughness. They have no
Emissive channel, so `<set>_emissive` is skipped as absent, and so is the `.uzmat`. The task's
spec requires `<set>.uzmat` on wand v1, with pins 0..6 bound to that generation's albedo, normal,
ORM and emissive textures.

Decision 380 §6 already settles this case for `cook-uzengine`: without `--emissive` the emissive
texture is black, "which is what the preset cooks for a black emissive channel". The `.uzmat`
then binds four textures, and the receipt marks the emissive `synthesized`. The cook writes no
canonical files at all, so 380 is silent about a canonical map for a synthesized texture.

## Decision

1. **Synthesized, as the cook does.** On a stack whose emissive map is skipped as absent (the
   stack has no Emissive channel), the native UzEngine preset cooks the preset's emissive target
   (binding `emissive`, BC7 sRGB, colour mips) from (0, 0, 0) with alpha 1. The size is the albedo
   canonical's. The cook is the one `cook-uzengine` runs without `--emissive`
   (`CookUzEngineDerivative`), so equal inputs give equal bytes: the generation's emissive
   `.uztexture` and `.uzmat` equal the cook's on the same generation's canonical maps.
2. **Listed and bound.** The plan carries it on the material (`synthesizedEmissive`). The dry run
   and `list_project_textures` list it right before the `.uzmat`. The `.uzmat` binds it, and the
   publication writes it right before the `.uzmat` (fault point `kill_after_synthesized`).
3. **No canonical file.** A canonical PNG 16 would claim an authored source that does not exist.
   No canonical or delivered PNG is written for the synthesized texture. This is the one
   exception to "canonical maps beside every derivative" (EXP-10), and it is stated in the
   receipt: the file's `uztexture` block holds `synthesized` ("black (0, 0, 0): the stack has no
   Emissive channel (decision 420)") with `source` and `delivery` null. The file entry has no
   channels and lists its hash, size and engine format like every derivative. The manifest block
   lists it as an open item. The receipt schema admits null `source` and `delivery` only with
   `synthesized`.
4. **Only for an absent channel.** An emissive map filtered out of a stack that has the channel is
   not synthesized: the `.uzmat` stays skipped and names it. The other three textures are never
   synthesized.

## Alternatives Considered

- **Leave the `.uzmat` skipped.** Rejected: no pilot would get a UzEngine material, and the cook
  and the native preset would deliver different files for the same set.
- **Write the `.uzmat` without an emissive sample.** Rejected: whether an unconnected Emissive pin
  is valid in the pinned engine is not verified, and nothing about it may be guessed.
- **Write a black canonical PNG 16 too.** Rejected (coordinator): it would present a constant the
  export made up as an authored map.

## Consequences

- `phase3.2_uze-uzmat-preset`: the full shipped preset writes the `.uzmat` on the pilots.
  `src/export/{plan,write,publish,receipt,fault}` and `schema/receipt.schema.json`. Tests:
  `tests/export/test_uze_preset.py`
  (`test_a_stack_without_emissive_binds_a_synthesized_black_emissive`,
  `test_synthesized_emissive_is_the_cooks_black_and_bound`,
  `test_interrupting_the_synthesized_emissive_write_keeps_the_previous_generation`).
- Whether UzEngine renders the black emissive as no emission stays with
  `phase3.3_uze-consumer-fixture`.
