# 419. AO_Mixed without an AO channel is recorded under Legacy; without an AO mesh map under OCIO it is 1

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase3.1_unreal-gltf-pbr-preset, phase3.2_unreal-ue56-packed-preset
**Amends**: decision 418 item 2 (its Legacy half, admitted by inference, is now recorded) and item 3 (one more OCIO case)

## Context

Decision 418 item 2 admitted a stack without an AO channel (`c = 1`) under legacy colour
management by inference from its OCIO recording; the clean-room rule admits recorded behaviour
only. Decision 418 also left the Tunic's glTF ORM refused: the Tunic binds no AO mesh map, and
no recording showed Painter's AO_Mixed without one. Two recordings close both (counts only; no
recorded value is published beyond the constant below):

1. **`ao-mixed-islands-legacy`** (recorded 2026-11-09 under the Assets3D Painter lock, one Legacy
   session, 18 private records, admitted; inbox run deleted). The Legacy twin of
   `ao-mixed-islands-ocio`: the bevelled cube, no template and no AO channel, grey A as the AO mesh
   map, no layer; AO_Mixed and the AO mesh map at PNG 16 and PNG 8, `infinite`, each twice, r1 and
   r2. Every AO_Mixed file is byte-identical to the OCIO twin's file of the same step (and to its
   own AO mesh-map export), so it equals the operator with `c = 1` on every texel, as decision 418
   found under OCIO. The production export equals it on every covered texel at PNG 16 and PNG 8,
   r1 and r2 (`tests/export/test_ao_mixed_islands.py`, legacy cases).
2. **`phase3/tier1/tunic-v10-gltf`** (recorded the same day under the same lock, one OCIO
   session, 20 private records, admitted). Painter's own glTF PBR Metal Roughness export of the
   Tunic v10 current round: OCIO with Painter's substance config, no template, no AO channel (the
   project's channels are BaseColor, BaseMetalness, Height, Normal and SpecularRoughness), no AO
   mesh map bound (the native create binds the Normal only). Painter writes the ORM file, and its
   R (AO_Mixed) is 65535 on every one of the 16,777,216 texels in r1, r1-repeat and r2: the
   operator with both operands 1 (`a' = (1 + 1) - 1 = 1`, `c = 1`).

## Decision

1. **Decision 418 item 2 is recorded.** A stack without an AO channel is in scope with `c = 1`
   under legacy colour management on the recording above, no longer by inference.
2. **No AO mesh map, under OCIO.** Under OCIO with Painter's substance config, a set with no AO
   mesh map bound and no AO channel is in scope: AO_Mixed is 1 on every texel (the operator with
   `a = 1` and `c = 1`), written like any other AO_Mixed (8 bits, padded under `infinite` with
   EXC-013 on incomplete coverage). `src/export/virtual_maps.cpp` (`AoMixedFill`, `AoMixedOn`).
3. **Still refused.** No AO mesh map under legacy colour management, no AO mesh map with an AO
   channel (with or without a layer), and an invalid AO mesh map: none is recorded. Every other
   refusal of decisions 411 and 418 stays.
4. **Tests.** `test_export_plan.py::test_ao_mixed_plans_in_its_scope_and_refuses_outside_it`
   plans the OCIO no-mesh-map case and refuses it with an AO channel;
   `test_ao_mixed_islands.py::test_ao_mixed_without_an_ao_mesh_map_or_channel_under_ocio` checks
   the Tunic golden's R and writes the cube without its mesh map.

## Alternatives Considered

- **Keep the Tunic's ORM refused.** Rejected: its behaviour is now recorded, and a refusal of a
  recorded, exactly reproducible case would leave the glTF preset's Tunic export unwritten for no
  reason.
- **Admit no AO mesh map in every case (`a = 1`).** Rejected: only the OCIO case without an AO
  channel is recorded; with an AO channel or under Legacy the operand Painter takes is not
  observed.

## Consequences

- The glTF preset's ORM (and the Unreal packed ORM, where its own refusals allow) is written on
  the Tunic; the whole glTF export of the Tunic plans (baseColor, ORM, normal).
- `phase3.1_unreal-gltf-pbr-preset` item 3.1 can compare all three pilots.
