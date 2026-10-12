# 93. The export recording requests R-091 and R-092 are specified, recorded and admitted

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_export-plan-compiler, phase1.16_export-processing-encoders, phase1.18_export-engine

## Context

Decision 091 §7 requested recording R-091: the export cases the plan still refuses. Decision 092 §5 requested R-092: AO_Mixed's operands, the converted maps on other templates and at fractional coverage, and View_2D's view state. Only the agent holding the Assets3D Painter lock may record them.

Measured constraints:

- The documented API (Painter 12.1.5 python-doc inventory) has no call that renames a texture set and none that adds a stack. None of the 26 shipped templates has two stacks (template capture).
- The recorder saved every r2 project as `golden.spp`, so `$project` could never hold dots.
- AO_Mixed's best model (decision 092) misses r1 at 11 distinct (mesh map code a, channel code C, opacity) cases. They come from the recorded maps, where a is grey A's code at texel x and C is grey B's code at texel y:
  - at opacity 0.5: (127, 0), (240, 33 + 34k) for k = 0-6, and (224, 254);
  - at opacity 0.75: (254, 0) and (143, 173).

The model panel was consulted once under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5). kimi answered HTTP 503 three times, so the verdicts are from GPT and Grok.

| Claim | Verdicts |
|---|---|
| C1 R-091 probe groups (naming, mixes, keys, alpha, dotted) | PARTLY x2: colliding maps need distinct payloads; mixed valid/error exports and fixed-name entries in both orders; a black-only control beside white (adopted) |
| C2 `project.file_name`, default `golden` | AGREE x1, PARTLY x1: a stem only, never a path (adopted, validated before Painter is touched) |
| C3 the layered-set collision stays open | AGREE x2 |
| C4 the renamed set through the UI operator, read back through `name()`/`original_name` | PARTLY x2: gate on the API readback and record nothing forged; probe the new and the old root separately (adopted) |
| C5 AO_Mixed isolation on grid6x4 with an EXR twin | PARTLY x2: add PNG 8 for Painter's own 8-bit write; check that the codes are sampled as authored (adopted: the `-8bit` twin, constant-fixture tests) |
| C6 converted maps at fractional coverage | PARTLY x2: name the ten maps; define every set; use spare sets for duplicates and deeper stacks (adopted) |
| C7 three other templates | PARTLY x2: an explicit channel plan per template and a group set; export the native channels (adopted) |
| C8 View_2D view state | PARTLY x2: a repeated default golden and a PNG 16 baseline; lights and sampling stay unprobed (adopted) |
| C9 stability policy unchanged | AGREE x1, PARTLY x1: r1 step A is the target (adopted) |

## Decision

1. **Recorder** (commit `172263d`):
   - A manifest may name r2's project file stem in the setting `project.file_name` (`applied_by: recorder_api`). The default is `golden.spp`, so no recorded golden changes.
   - The UI operator's sheet gains `Texture Set List/Name (<texture set>)`. The operator renames the set with a guarded double click and Enter. The name is read back through the documented `TextureSet.name` and `original_name` (a string at runtime) before r1 and after the reopen. Any other value refuses the golden.
   - `ChannelType` Diffuse, Specular and Glossiness join the vocabulary.
2. **Goldens** (`tools/parity/tier0_semantics/current.py`: `r091_goldens`, `r092_goldens`, `export_probes_renamed`). New fixtures: `grey-<code>.png` (constant greys for code 0, 33, 127, 143, 173, 224, 240, 254, 255), `grid2x2.dotted.obj`, and the probe recipes under `export-probes/r091-*/`. `sky-patch.exr` is reused.
3. **Recorded and admitted.** Painter `12.1.5+js-api.1.1.20` (current envelope), Legacy colour management, one Painter session, r1 (same session) and r2 (after save and reopen). Admitted with `store record --run`; `store verify` exits 0. Manifests are under `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier0/`.

| Golden | Maps | r1 = r2 | r1 != r2 on | Private record (SHA-256) |
|---|---|---|---|---|
| `semantics/export-probes-r091-naming` | 26 | 26/26 | - | `c808f4163d521acdb2dd438f18cb02339070550f99f8fead3471afc85d0d5c99` |
| `semantics/export-probes-r091-mixes` | 16 | 16/16 | - | `bc7a45a7f83366d02081faedf182563d0cfff8dbe586fd51c7300875a1f38a16` |
| `semantics/export-probes-r091-keys` | 14 | 14/14 | - | `7fce248a45d37e3b26f6d25b9f4ab09f6003843f2e5660e659c529013fcc5329` |
| `semantics/export-probes-r091-alpha` | 16 | 8/16 | s1, s2 files | `e3201cc07c7af358e642cd2fa0d86db070f380df104330a40a1d023168070cd6` |
| `semantics/export-probes-r091-dotted` | 8 | 4/8 | `$project` names | `27aba56c882b5f442b5960080b2cd07a951d656a56a7c9de54af019b21e1fd82` |
| `semantics-ui/export-probes-r091-renamed` | 4 | 4/4 | - | `44d2ded94a2a9ffda819803d712660240774ff563d2649821e27e4e2836e5103` |
| `semantics/ao-mixed-isolation` | 144 | 126/144 | AO_Mixed of s0, s3, s7, s10, s14-s17, s19 | `ea55579c6118e32fec32013afd313b98c61e525c4ea2ece0471efe76d7d28dcf` |
| `semantics/ao-mixed-isolation-float` | 144 | 126/144 | the same | `b5022aa6544fcc64d22cfe02ec722577a824ab98ae83e395d9f1a2c035aff94f` |
| `semantics/ao-mixed-isolation-8bit` | 144 | 126/144 | the same | `e4c03ede8f7340d9ff009d96d42fe1404d9eb4dfd56419bdc8f901ea7539da59` |
| `semantics/virtual-maps-coverage` | 624 | 352/624 | s1-s7, s17, s18, s20-s23 | `f9a45e3430ba8c19cf98f09dd2e794c47ab3d8b93b5a6302d0cb1a621e86e13a` |
| `semantics/virtual-maps-coverage-float` | 624 | 352/624 | the same | `5efabbe70a3f72f02cbb363cd516386e3535e9be1d13b8c0af30d71f23f829d6` |
| `semantics/virtual-maps-template-pbr-metallic-roughness-alpha-blend` | 208 | 134/208 | s1, s2, s5 | `91b6016d933aa39f7d16da7c73125d418622d22be417f1c9a3dd1b3eca5b693e` |
| `semantics/virtual-maps-template-pbr-metallic-roughness-alpha-blend-float` | 208 | 134/208 | s1, s2, s5 | `83b32f9cfd2f69946d5f1aa968e910288c4fa2ac17691300dd56349111dc4d9b` |
| `semantics/virtual-maps-template-openpbr-coat` | 208 | 134/208 | s1, s2, s5 | `07d438f1f6b8f7ae9ec07e38fae3e8f99f4e32374403bb87b2b635729e35dbf5` |
| `semantics/virtual-maps-template-openpbr-coat-float` | 208 | 134/208 | s1, s2, s5 | `69d2641ef886073df0ba4951a30c4bd735ec6dac6089cf5aebb8494d0f81f5e7` |
| `semantics/virtual-maps-template-pbr-specular-glossiness` | 64 | 40/64 | s1, s2, s5 | `22f30e2d9c1a954416f3472bcefa0559613a494ec6e68c5ba0fc3577b72da542` |
| `semantics/virtual-maps-template-pbr-specular-glossiness-float` | 64 | 40/64 | s1, s2, s5 | `69c11e5575479990072d0a6c36489ee38aff630f3baf27d2db96576290408d6e` |
| `semantics/view-2d-state-default` | 24 | 24/24 | - | `43f83cfd3d3b537f41a6dad0d6426eb88f698c9b0b7c88919162a4008dacbbb5` |
| `semantics/view-2d-state-default-repeat` | 24 | 24/24 | - | `53e250d8e55bd08c821bcda5ad73d7148931beea1149560d3d6d11449ae62210` |
| `semantics/view-2d-state-tone-linear` | 16 | 16/16 | - | `1da6c49dd3a1c5bfa64d4bd7e236e3cd69b97e493dc29d8165031b3387c3095c` |
| `semantics/view-2d-state-tone-aces` | 16 | 16/16 | - | `6f0e89798667be4e4db9893e61781b85e30e7b3bbb73763f4268353a57c9832e` |
| `semantics/view-2d-state-environment` | 16 | 16/16 | - | `bb78cefdf5b01263f1d94849ae37a8ac0b60b5acf1a858d00d186ce0a085c64e` |
| `semantics/view-2d-state-camera` | 16 | 16/16 | - | `70bff4024ed135fd36f670453ff7b072623e9dcdd430e8d0d93c1b2e777eccfb` |

4. **Stability.**
   - Step A equals step B in every recording of every golden.
   - All differences between r1 and r2 are deterministic. A first pass in the same process (separate projects) reproduced all 22 API goldens output for output. A freshly started Painter process reproduced both recordings of `ao-mixed-isolation`, its float twin, `virtual-maps-coverage`, `view-2d-state-default` and `export-probes-r091-alpha`.
   - r1 is the exact target (decision 032), and no exception is added.
   - The r1/r2 differences are at fractional coverage (opacity below 1, masks, groups) and on AO_Mixed. In the dotted golden, `$project` is `Untitled` in r1.
   - `tier0-stability.md` was regenerated with no fit re-run: 120 goldens, 92 stable.
5. **Observations for phase1.15 and its follow-ups** (numbers in the records, kept private; outcomes stated here).
   - **Groups and stray `)`.**
     - A group holding a non-empty wildcard is kept with its parentheses, its empty wildcards expanding to nothing: `$textureSet(_$udim$mesh)` gives `s0(_grid2x2)`, and `(_$mesh_$colorSpace)` gives `(_grid2x2_)`.
     - A group whose wildcards are all empty is dropped, and a stray `)` is literal: `$textureSet_x)` gives `s0_x)`, and `$textureSet(_$udim))` gives `s0)`.
   - **Collisions.**
     - Three equal paths are written `name`, `name_1` and `name_2`.
     - Equal paths across exportList entries, including one root listed twice, get `_1` in entry order.
     - With case-only names, NTFS keeps the first file's name and the last-written content. The reversed order writes `s0_a` holding the RGB map.
     - The layered-set case stays open, unrecorded. It would be settled by a project with two verified stacks, built only through a qualified route.
   - **Mixes.**
     - Every map whose sources are only `defaultMap` black and/or white is listed and not written, white alone included.
     - An absent source at R beside present G and B writes RGB.
     - Absent RGB with a present A writes RGBA.
     - All sources absent: the export raises `ValueError` ("Error during the export (see logs).").
     - A map whose own export raises (an unbound curvature map, or `sheencolor` without a Fuzz channel) beside a written map, in either order: the export succeeds, writes only the written map and raises nothing.
   - **Keys.** Undocumented keys in a channel, an exportList entry, a filter, the parameters object, an exportParameters entry and a preset are all accepted silently.
   - **srcChannel A.** At partial coverage (opacity 0.5, masked) the file is RGBA. At full coverage it is RGB. On the empty set it is RGBA.
   - **Dotted names.**
     - `$mesh` of `grid2x2.dotted.obj` is `grid2x2.dotted` (the stem before the last dot).
     - `$project` of `golden.dotted.spp` is `golden` (the name before the first dot).
   - **Renamed set.**
     - `$textureSet` is the new name, and `$sceneMaterial` is the original name (`renamed0_s0_c`).
     - An export root naming the original name raises `ValueError` ("provided rootPath "s0" does not exist").
   - **AO_Mixed.**
     - PNG 8, PNG 16 / 257 and EXR × 255 are equal on every texel: Painter's AO_Mixed is its 8-bit write.
     - The misses depend on operand values, not on texel position:
       - the constant mesh map 240 under grey B at 0.5 misses every texel of the seven missed rows;
       - with the roles swapped, the misses move to the transposed texels;
       - a uniform channel misses where its constant-bitmap twin does.
     - At a = 1 (mesh map 255), r1 is the model at both opacities. With no layer, and at opacity 1, there are no misses.
   - **PNG 8 encoding** (`ao-mixed-isolation-8bit`, 40 distinct 8-bit grey files).
     - Painter's row filter is the smallest sum of min(b, 256 - b) over all five PNG filters, ties to the earlier, on 40 of 40 files. Up is the most frequent filter.
     - zlib level 6 with Z_FILTERED reproduces 32 of the 40 IDAT streams from Painter's own filtered rows.
     - The phase1.16 encoder (decision 089: None, Sub and Paeth only) re-encodes 39 of these files differently. Its PNG16 and OpenEXR 32f files, those of these goldens included, stay byte-identical (1301 PNG and 557 EXR files).
   - **Converted maps.** On `PBR - Specular Glossiness` Painter writes only View_2D of the ten, beside the native channels.
   - **View_2D.**
     - It depends on the environment. Tone mapping (Linear, ACES) and the 3D camera leave it unchanged, and a second project in the same session reproduces it.
     - Sets with identical uniform inputs are equal. Sets with identical bitmap inputs (s4, s5) differ.
     - Lights and sampling have no documented setter and stay unprobed.

## Alternatives Considered

- **Leaving the renamed set open.** Rejected: the UI rename was qualified live, and its documented readback gates it.
- **Adding a stack through the UI.** Rejected for now: it needs a material-layering shader change and a stack-creation path that was never qualified.
- **Recording only PNG 16 and EXR for AO_Mixed.** Rejected: the PNG 8 twin shows Painter's own 8-bit write.

## Consequences

- Phase1.15's follow-up can lift these refusals of decision 091 on recorded evidence: mixed groups, stray `)`, third and cross-entry collisions, the reversed case-only order, `defaultMap`-only maps, absent mixes, mixed error exports, undocumented keys, srcChannel A at partial coverage, dotted names and a renamed set's `$sceneMaterial`.
- The AO_Mixed fit (decision 092) can now be judged on isolated operands. The converted-map lift (decision 092 §2) has its coverage and template recordings, and still needs the evaluator's channel coverage.
- Phase1.16's PNG encoder is not exact on Painter's 8-bit grey PNGs. `tests/export/test_export_encoders.py` (`test_painter_files_reencode_byte_for_byte`, `test_published_export_processing_reproduces`) fails on those 39 files until the encoder (`src/export/png_writer`, not touched here) takes the five-filter rule and the remaining zlib cases are explained.
- `tests/export/tier0.py` counts View_2D's refusal ("Painter's 2D view render", decision 092) as a release gap beside R-090 and R-092.
- Still open: the layered-set collision, and View_2D's light and sampling state.
