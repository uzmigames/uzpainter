# 418. AO_Mixed is computed on UV-islanded sets, without an AO channel and under OCIO: covered texels exact, padding under EXC-013

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase3.1_unreal-gltf-pbr-preset, phase3.2_unreal-ue56-packed-preset, phase3.2_uze-uzmat-preset
**Supersedes in part**: decision 411 §2 and §3 (the full-UV-coverage, AO-channel and legacy-only limits of AO_Mixed's scope)

## Context

Decision 411 fitted AO_Mixed exactly and computes it only in a scope that includes full UV
coverage, an L16 or L32F AO channel and legacy colour management. The glTF preset's ORM reads
AO_Mixed in R, so its export stayed refused on the three pilots (`phase3.1_unreal-gltf-pbr-preset`,
notes of 2026-11-09). The pilots are UV-islanded, are made under OCIO with Painter's substance
config (their Painter projects are created by the pipeline under `OCIO`), and use the default
project's channels, which hold no AO channel (`assets/templates/default.json`). Decisions 414 and
417 let production write islanded `infinite` files under EXC-013 and EXC-014, the receipt naming
them; no exception covers a refusal, so AO_Mixed itself had to be in scope.

Decision 411's operator is per texel: `a' = (1 + a) - 1`, `c = fma(S, al, 1) - al` (1 without a
layer), `v = a' c`, then `(v - 1) + 1` written at 8 bits. Coverage enters only if Painter reads its
inputs differently on covered texels of an islanded set. Evidence, counts only (no recorded value
is published here):

1. **R-314's islanded goldens** (decision 314; admitted 2026-10-23). The authored bevelled cube at
   256 px is UV-islanded: decision 408's coverage covers 53,336 of 65,536 texels, 2,296 of them
   with an uncovered neighbour. Each golden binds grey A (16-bit grey) as the AO mesh map and has
   one root fill whose AO source is the transposed hue-grid grey (16-bit grey, untagged) on an L16
   AO channel, Normal, opacity 1. The glTF preset's ORM R is AO_Mixed. On every covered texel it
   equals the operator, 0 differing of 53,336, in all eight exports: Legacy (the Alpha-blend
   template) and OCIO (no template), PNG 16 (`-predefined-`) and PNG 8 (`-predefined-padding-`),
   r1 and r2. The uncovered texels differ (11,795 of 12,200): they hold Painter's padding.
2. **`ao-mixed-islands-ocio`** (authored and recorded 2026-11-09 under the Assets3D Painter lock,
   one OCIO session, 18 private records, admitted; inbox run deleted). The bevelled cube, no
   template and no AO channel added, grey A as the AO mesh map, no layer; AO_Mixed and the AO mesh
   map at PNG 16 and PNG 8, `infinite`, each twice, r1 and r2. AO_Mixed equals the operator with
   `c = 1` on every texel, covered and uncovered (0 of 65,536 in each of the eight AO_Mixed
   exports); the PNG 16 mesh-map exports equal grey A.

The recorder refused the first attempt: a virtualMap whose source channel the stack lacks had no
encoding basis. `tools/parity/recorder/texture.py` now records it as `undetermined` with basis
`absent_source_channel`, as for a converted virtual map (decision 087).

## Decision

1. **Any UV coverage.** `AoMixedOn` no longer refuses a set whose UV islands leave the tile
   partly uncovered. Every texel takes the operator; on incomplete coverage the export pads the
   uncovered texels under `infinite` and the file is written under EXC-013 v1 (decision 414: every
   covered texel exact, the padding free; the receipt names it), like every other padded file.
   The other paddings stay refused on islanded sets (`PaddingRefusal`). Painter's own uncovered
   AO_Mixed is not modelled: with no AO layer it is the operator itself (item 2 of the context),
   with a fill it is padded; both fall under EXC-013.
2. **No AO channel.** A stack without an AO channel is in scope with `c = 1`, as with no AO layer.
   It is recorded under OCIO (item 2). Under legacy colour management it is admitted too: an empty
   L16 or L32F channel already gives `c = 1` there (decision 411's goldens), and Painter's AO_Mixed
   is the same under both colour managements on every pair recorded (R-314's ORM R is equal on
   every covered texel across Legacy and OCIO).
3. **OCIO with Painter's substance config** (`evaluator::PainterOcio`) is in scope for:
   - no AO channel, or an L16 or L32F AO channel with no AO layer;
   - exactly R-314's fill: one root fill in Normal at opacity 1 on an L16 AO channel, its AO source
     a 16-bit grey bitmap whose colour space resolves linear, under the identity UV projection.

   Under OCIO a uniform colour, an 8-bit bitmap, an L32F channel with a fill or another opacity is
   refused before writing: no OCIO recording shows how Painter chooses their colour space or
   operands. Any other OCIO configuration stays refused.
4. **Everything else of decision 411 §3 stays refused**: other templates, channel formats and
   colour managements, a missing or invalid AO mesh map, OpenEXR images, groups, several AO
   layers, masks, effects, other blend modes, sources and projections.
5. **Tests.** `tests/export/test_ao_mixed_islands.py` writes AO_Mixed through the production
   export (`WriteExport` over the cube's coverage, `infinite`) and compares every covered texel
   with r1 and r2: `ao-mixed-islands-ocio` at PNG 16 and PNG 8, and R-314's OCIO fill at PNG 16.
   `test_export_plan.py::test_ao_mixed_plans_in_its_scope_and_refuses_outside_it` plans the OCIO
   and no-AO-channel cases and refuses a non-Painter OCIO config. R-314's Legacy goldens use the
   Alpha-blend template, outside the scope; they are evidence for the operator only.

## Alternatives Considered

- **Lift coverage only.** Rejected: the pilots would stay refused on OCIO and the missing AO
  channel, and both are now recorded.
- **Lift every OCIO fill.** Rejected: only R-314's 16-bit grey bitmap at opacity 1 on L16 is
  recorded under OCIO; an 8-bit image or a uniform colour may take another colour space there.
- **Model Painter's uncovered AO_Mixed.** Not needed: EXC-013 leaves the padding free, and its
  exact form belongs to `phase4.1_export-island-padding-exact`.

## Consequences

- The glTF preset's ORM (and the Unreal packed ORM and UzEngine `<set>_orm`, where their own
  refusals allow) plans and writes AO_Mixed on islanded sets, without an AO channel and under OCIO
  in the scope above; a padded file relies on EXC-013 in its receipt.
- On the pilots (OCIO, the default template, a 16-bit grey AO mesh map at the set's resolution, no
  AO channel) AO_Mixed is in scope; whether a whole glTF export is written depends on the preset's
  other files.
