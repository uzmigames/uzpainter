# 95. Shipped export presets resolve inline first, then by id or Painter alias, and presets whose layout no recording confirms are refused until R-095

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.17_export-presets, phase1.18_export-engine, phase1.15_export-plan-compiler

## Context

Task phase1.17 ships three presets: one answering to Painter's `PBR Metallic Roughness`, one answering to `Blender (Principled BSDF)` (the Assets3D pipeline uses `resource://starter_assets/Blender (Principled BSDF)?version=13120355637414252359`), and the Assets3D inline five-map preset. Each is written by hand from cited sources and carries a provenance record. Adobe preset files and readbacks of them are never a source (`docs/licensing-and-clean-room.md` §1.7, §6).

Measured on 2026-10-12:

- **Public documentation.** Adobe's "Default Output templates" help page gives one-line descriptions of the two Painter presets. It names no maps, channels, file names or parameters.
- **Recordings.** The private store holds no export through either Painter preset.
- **UzmiGames' own observations.**
  - Blender preset: the file names Painter wrote on an OCIO project (the Assets3D hat report and the delivered `Textures` folders): `<set>_BaseColor_sRGB`, `_Normal_Raw`, `_Metallic_Raw`, `_Roughness_Raw`, `_Emission_sRGB`, `_Alpha_Raw` and `_Displacement_Raw`.
  - PBR preset: an MCP changelog line saying an export wrote Base Color, Roughness, Metallic, Normal and Height files.
- **Hypotheses.** The channels of each map, the normal convention, the naming prefix and each preset's own parameters come from the consumers' public specifications: Blender's Principled BSDF inputs and glTF 2.0's metallic-roughness model.
- **The five-map preset** is the pipeline's script, `painter_export.py`. The plan compiler already reproduces its semantics. Its BaseColor is an sRGB8 channel whose export encoding is not fitted (decision 090), so every export writing BaseColor is already refused.

The model panel was consulted once under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 Write the two Painter-named presets as hand-written hypotheses with per-decision sources. Refuse any export or dry run through them with `NotYetSupported` naming R-095 until a recording confirms the layout. | AGREE x3. GPT: R-095 must also confirm the preset's parameters, since layout alone is not output parity. |
| C2 The five-map preset is not gated by R-095: the pipeline script is its own source. Its BaseColor is refused by the existing R-090 refusal before any write. | AGREE x3. GPT: no partial four-map output; the whole export refuses. |
| C3 Resolution order: an inline preset of that name, then a shipped id, then the alias table (Painter names and `resource://starter_assets/<name>` URLs). A bare Painter name is a documented UzPainter extension. | AGREE x2, PARTLY x1. GPT: do not accept any `?version`; accept only recorded versions. |

## Decision

1. **Files.**
   - `assets/export-presets/<id>.json` is one documented `exportPresets[]` entry `{name, maps}`, whose `name` is the UzPainter id.
   - `<id>.provenance.json` follows `src/export/preset-provenance.schema.json` (`uzpainter/export-preset-provenance/1`). It holds:
     - sources, each with page, section, facts and the SHA-256 of the UzmiGames files it cites;
     - private records (SHA-256 only);
     - one packing entry per map, with its source and status (`defined`, `confirmed` or `hypothesis`);
     - parity: layout `pipeline`, `confirmed` or `unconfirmed`; status `exact` or `pending`; the pending recordings with their owners; and the tests;
     - `reviewer`, null until the owner reviews.
   - Both files are installed beside the executables.
2. **Shipped.**

   | Id | Answers to | Maps | Parameters | Layout |
   |---|---|---|---|---|
   | `assets3d-inline-five-map` | (its own id) | BaseColor, Roughness, Metallic, Height, Normal (`Normal_OpenGL`) | PNG 16, `infinite`, no dithering; size left to the set | `pipeline` |
   | `blender-principled-bsdf` | `Blender (Principled BSDF)` | BaseColor, Normal (`Normal_OpenGL`), Metallic, Roughness, Emission, Alpha (opacity), Displacement (height), each `$textureSet_<map>(_$colorSpace)` | none of its own | `unconfirmed` |
   | `pbr-metallic-roughness` | `PBR Metallic Roughness` | BaseColor, Roughness, Metallic, Normal (`Normal_OpenGL`), Height, each `$textureSet_<map>` | none of its own | `unconfirmed` |

3. **Resolution** (`src/export/preset_aliases.h`; `ParseConfig`). A preset reference is resolved in this order:
   1. An inline preset of that name.
   2. Otherwise a shipped id.
   3. Otherwise a Painter name of the alias table.
   4. Otherwise `resource://starter_assets/<Painter name>`, with no query or with a recorded `?version=`. Recorded today: the Blender preset's version seen in Assets3D.

   The shipped preset joins `exportPresets` under its id, and the reference becomes that id. Painter names are internal aliases only (CLR-06).

   Refusals:
   - An unrecorded query is `NotYetSupported` naming R-095.
   - An inline preset named like the resolved id is a `ValueError`, because it would shadow the shipped preset.
   - Any other `resource://` or `export-preset-generator://` reference is `NotYetSupported`.

   A bare Painter name that no inline preset defines is a UzPainter extension. Painter itself resolves shelf presets by URL.
4. **Unconfirmed layouts are refused** before anything is planned or written. The refusal is `NotYetSupported`, naming the preset's pending recordings (R-095). No export runs through a hypothesis.
5. **The five-map preset runs.** Every file it writes goes through the export's own refusals. While BaseColor's encoding is unfitted, an export that writes BaseColor is refused before writing. The refusal names recording R-090 and `phase1.18_export-engine` item 6.1. This adds the recording's name to decision 090's sRGB8 refusal message. With an `outputMaps` filter that leaves BaseColor out, the export writes.

## Alternatives Considered

- **Exporting through the hand-written Painter-named layouts, marked unverified.** Rejected by the panel: a guessed layout is not output parity.
- **Not writing the two Painter-named presets until R-095.** Rejected: item 2.1 asks for them. As provenance-backed hypotheses they are what R-095 confirms or corrects, and the refusal keeps them inert.
- **Accepting any `?version`.** Rejected (GPT's point): a different version of the shelf preset may differ.

## Consequences

- `defaultExportPreset: "Blender (Principled BSDF)"` and its pipeline URL reach the shipped preset and are refused naming R-095. They are not reported as unknown.
- The Assets3D five-map preset plans exactly what the pipeline's inline configuration plans. Its Normal map equals Painter's files on the recorded plane goldens.
- R-095 (the local run report `parity/reports/phase1/export-presets.md` §3) must be recorded by the agent that owns Painter.
