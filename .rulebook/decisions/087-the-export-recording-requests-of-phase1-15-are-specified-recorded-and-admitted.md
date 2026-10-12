# 87. The export recording requests of phase1.15 are specified, recorded and admitted

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.15_export-plan-compiler

## Context

`phase1.15_export-plan-compiler` left items 3.5, 3.6 and 4.1 open on recordings only the agent holding the Assets3D Painter lock may make (`parity/reports/phase1/export-plan-compiler.md` §4, decisions 085 and 086):

- **R-085:** probes P1-P13 of export behaviour the documentation leaves open.
- **R-086a:** an AO_Mixed opacity sweep with every export repeated in the same session, and an OpenEXR 32f twin.
- **R-086b:** the ten converted virtual maps at PNG 16 and OpenEXR 32f.

The recorder could not record them as it stood:

- It keyed outputs by texture set and map, so a map exported twice gave duplicate record ids.
- It wrote `1/ior` into a sub-folder.
- It refused any file whose encoding no single channel gives.
- It had no way to pass a literal `json_config`, and the public schema forbids nested objects in step arguments.

Some points the request leaves open:

- P9's layered set: the documented API has no call that adds a stack.
- The P13 pairing method, the twin's AO channel, and the exact sequences.

The model panel was consulted under the owner's delegation on 2026-10-11. kimi/kimi-k3 answered HTTP 503 in both rounds, so the verdicts are from cx/gpt-6-astra and xai/grok-4.5.

| Claim | Verdicts |
|---|---|
| C1: key a map by step only when two steps export it; every other id is unchanged | PARTLY x2: prove it from the recorded ids and check uniqueness after slugging (done, see 1) |
| C2: `1/ior` written `1_over_ior` in the file name and output id; `map` keeps `1/ior` | AGREE x1, PARTLY x1 |
| C3: a file with no single source channel recorded `linear` with basis `file_codes` | DISAGREE x2: that is a false colour claim; add `undetermined` |
| C4: R-086a reading; the twin exports both maps as EXR 32f | PARTLY x2: compare A/B within each recording, apart from r1/r2 |
| C5: R-086b, one fill per set with only the listed channels, Working uniforms | PARTLY x2: state the base values and the reading |
| C6: probe capture; mismatches are observations | PARTLY x2: confined file reads, separate list/export/inventory results; nested config violates the schema |
| C7: the partition, one variant per probe step | AGREE x1, PARTLY x1 |
| C8: P9's layered set left open; colliding maps get different sources | AGREE x1, PARTLY x1: add non-colliding controls |
| C9: P5 Raw through `SourceBitmap.set_color_space`; P6 grey A in the L8 channel; P12 fresh project; P13 distinct values plus direct controls | PARTLY x2 |
| C10: r1 is the target when r1 != r2 (decision 032) | DISAGREE x1, PARTLY x1: report the instability explicitly; the policy itself is not this task's |
| R1 (round 2): `undetermined` encoding enum value | PARTLY x1, DISAGREE x1. Grok preferred omitting the field, but its round-1 counter-proposal was this value, and both models rejected `linear` |
| R2: config as an authored `recipe_json` input; envelope manifests declare JSON fixtures in the guard | PARTLY x2: no mutation, path confinement, inventory (done) |
| R3: id grammar `<set>[/<stack>]/<stem>[/step<n>]` | AGREE x1, PARTLY x1: test `1/ior` twice (done) |
| R4: controls, fresh-project wording, isolated aliases | PARTLY x2: case-only collisions depend on the filesystem (NTFS, case-insensitive) |
| R5: policy unchanged, divergences reported, A/B compared apart | AGREE x2 |

## Decision

1. **Recorder** (commit `e741a6e`).
   - Step keying:
     - A map that two export steps of a golden name gets the output id `<set>[/<stack>]/<stem>/step<n>`.
     - Every other id is unchanged. A test over every recorded manifest proves that no earlier id changes. The base-values goldens repeat `defaultMap/white`, but Painter never writes it.
   - A `/` in a map name is written `_over_` in the file name and the output id. The `map` field keeps `1/ior`.
   - Undetermined encoding:
     - A file that states no encoding and derives from no single channel is recorded `encoding: undetermined`, with basis `converted_virtual_map` or `export_probe`.
     - That covers the converted virtual maps and every probe file.
     - The value is new in `golden-private.json`'s enum.
   - Export probes:
     - The probe step is `export.list_project_textures`, with `config` naming an authored `recipe_json` input (hash-pinned).
     - The recorder injects a fresh `exportPath` per probe and recording.
     - It records:
       - the dry run, or its error;
       - then, when the dry run succeeds, the export, or its error;
       - the directory inventory (missing, unlisted);
       - every file present, as a blob.
     - A path outside the directory is recorded relative to it and never read. A file older than the fence, or a link, refuses the golden.
   - Bitmap sources take an optional `color_space`, set with the documented `SourceBitmap.set_color_space`.
   - The vocabulary gains the OpenPBR coat, fuzz and subsurface channels.
   - The guard counts an envelope's manifests as declarers of `parity/fixtures/` JSON.
2. **Ten goldens** (`tools/parity/tier0_semantics/current.py`, `export_goldens`). Probe configurations are in `fixtures.export_probes`, written to `parity/fixtures/tier0-semantics/export-probes/`. Legacy colour management, documented API only.
   - `ao-mixed-opacity` and `-float`, grid4x2, with grey A as the AO mesh map and AO L16:
     - s0-s3: grey B in Normal at 0.25, 0.5, 0.75 and 0.9;
     - s4: uniform 0.3 at 0.5;
     - s5: grey B at 0.5 inside a group (Normal, 1);
     - s6: two grey B fills at 0.5;
     - s7: empty.
     - Steps A and B both export AO_Mixed and the AO channel, as PNG 16 in the first golden and EXR 32f in the twin.
   - `virtual-maps-converted` and `-float`, grid4x2, no template. One fill per set with only the listed channels active, Normal at 1, uniforms in Working:
     - s0: BaseColor field A, SpecularRoughness grey A, BaseMetalness 0;
     - s1: the same with BaseMetalness 1;
     - s2: BaseMetalness grey B, SpecularRoughness grey A;
     - s3: BaseColor (0.8, 0.3, 0.1), SpecularRoughness 0, BaseMetalness 0.5;
     - s4: SpecularRoughness 1;
     - s5-s7: empty.
     - All ten maps go in one step, and the step is repeated.
   - `export-probes-naming`: P0 control, P1-P4, P9; 14 probes. P9's layered-set case is not recorded and stays open.
   - `export-probes-channels`: P5-P8, P12; 7 probes. BaseColor is field A in Raw.
   - `export-probes-config`: P0, P10, P11; 4 probes.
   - `export-probes-aliases-coat`, `-fuzz` and `-subsurface`: P13 on the OpenPBR templates, 14 probes each. Each template channel in s0 gets a distinct uniform. There is one probe per legacy name and one direct control per channel.
3. **Recorded and admitted.** Painter `12.1.5+js-api.1.1.20` (current envelope), one session, r1 (same session) and r2 (after save and reopen). Admitted with `store record --run`; `store verify` exits 0.

| Golden | Maps | r1 = r2 | Private record (SHA-256) |
|---|---|---|---|
| `ao-mixed-opacity` | 32 | 18/32 | `55ee183309f382fe7aef1ec9e3a230e5644c44a5113db30cff9e6cd13984a2d9` |
| `ao-mixed-opacity-float` | 32 | 18/32 | `6bbebe93586be1a4f6bab2c984ac41d85b6693aba38904858ec77ca1427a3394` |
| `virtual-maps-converted` | 160 | 160/160 | `c9053b1c43bf7c87453b9943cf24e608716c0501b0cacf0e672c461889ba341b` |
| `virtual-maps-converted-float` | 160 | 160/160 | `457341b312a963102761657a78264d0f378f127b323397ca4e78d08514e6b2c5` |
| `export-probes-naming` | 33 | 29/33 | `abc8d949d437bd095160f8eb1d85ba4fa275083f34d4cb24fa282ca17b54dbe9` |
| `export-probes-channels` | 8 | 8/8 | `a0e13b57528ca107153d771f310b0e26af6d2b6052979312f69cc58c8a208085` |
| `export-probes-config` | 6 | 6/6 | `2d52ac6714ce75635fc5cfd05bb4c8ad8c32d98f2c847f6f088ed2022fab035f` |
| `export-probes-aliases-coat` | 14 | 14/14 | `c592680acca97753e23e26e5e553ee57d0455a21f50378ae3d12aac117e2ad7e` |
| `export-probes-aliases-fuzz` | 18 | 18/18 | `a8766bf19b634061ae90e0ef2e0be8a61f2c8ccf8a1c69e5ed459100278b8194` |
| `export-probes-aliases-subsurface` | 16 | 16/16 | `28b0f2f44f256a6d3a8c38c5e5e012289712f1fcbf2441643c7f18d27ff8eb8a` |

4. **Stability.**
   - **Step A = step B in every recording of every golden.** Painter shows no run-to-run noise within one session.
   - **AO_Mixed changes across save and reopen.** r1 and r2 differ on s0-s3, s5 and s6, by 9 to 39 values, each exactly one 8-bit step: 257 codes in PNG 16, 1/255 in EXR 32f. AO_Mixed therefore holds the 8-bit lattice before encoding.
   - **The AO channel changes too, on s3 only** (opacity 0.9): 2560 values, 1 code of 16 bits.
   - **The divergence is deterministic.** A second, freshly started Painter process reproduced both recordings of both AO goldens output for output. r1 is the exact target (decision 032), and no exception is added.
   - **Equivalent stacks give equal outputs.** s1 = s5 (0.5, and 0.5 inside a group) and s2 = s6 (0.75, and two 0.5 fills) are byte-equal in every recording.
   - **`export-probes-naming` differs only on P1 `$project`.** It names the project `Untitled` in r1 and `golden` in r2, a condition-dependent value, not noise.
   - `tier0-stability.md` was regenerated with no fit re-run: 97 goldens, 82 stable.
5. **Observations for phase1.15** (numbers in the records, kept private; the outcomes are stated here).
   - Wildcards and groups (P1-P3):
     - `$mesh` is the mesh file stem, `$project` the project name and `$sceneMaterial` the texture set.
     - An empty `$udim` or `$colorSpace` outside a group expands to an empty string.
     - Group parentheses are kept literally: `(_v2)`, `()`, `(_`.
   - `uvTiles` (P4):
     - The `[[0,0]]` filter exports s0, and the `[[1,0]]` filter exports nothing for s0.
     - A rule filtered on `[[0,0]]` applies: those files are 8-bit.
   - P5-P7:
     - P5's srcChannel L of BaseColor writes an L file.
     - P6 writes 3 channels on s0 and 4 on the empty s1.
     - P7's absent Opacity alpha writes RGB.
   - P8 black-only maps are listed, but the export writes nothing (status Success).
   - P9 collisions:
     - Two maps of one name are written `name` and `name_1`.
     - Case-only names are both reported, but NTFS holds one file. The inventory records the other as missing.
   - P10: undocumented keys are accepted silently.
   - P11: an integer `bitDepth` raises `ValueError` ("Expected a string value").
   - P12: the unbound curvature map is listed, then the export raises `ValueError`.
   - P13: the dry run lists every legacy name. The export raises `ValueError` unless the template has the channel:
     - `coatopacity` = CoatWeight;
     - `sheencolor`, `sheenroughness` and `sheenopacity` = FuzzColor, FuzzRoughness and FuzzWeight;
     - `translucency` = SubsurfaceWeight;
     - `scatteringcolor` = SubsurfaceColor;
     - `absorptioncolor` and `specularedgecolor` raise on all three templates.
   - So `list_project_textures` is not a faithful dry run of these refusals.

## Alternatives Considered

- `encoding: linear` with an explanatory basis was rejected by both models. Omitting the field would need a schema change that is no smaller, and refusing would lose the observation.
- The config as a nested step argument is impossible: the public schema forbids it so that no slot can carry a readback. A string argument is limited to 256 characters.
- The P9 layered set through Painter's UI (decision 029) is out of this request's documented-API route. It stays open.
- Exporting only AO_Mixed in the twin was rejected: the AO channel's float value is needed by the fit.

## Consequences

- phase1.15 (or its follow-up) can lift the refusals of decision 085 that these probes now settle, fit AO_Mixed on an 8-bit lattice against the sweep, and plan the converted maps against exact goldens, with its own task files unchanged here.
- The AO_Mixed save-and-reopen divergence is a recorded, deterministic r1/r2 difference.
- P9's layered-set case and the converted maps' encodings (to be determined against the EXR twins) remain open.
