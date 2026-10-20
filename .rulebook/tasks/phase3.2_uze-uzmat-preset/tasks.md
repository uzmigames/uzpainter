## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input), `phase3.1_uze-uztexture-writer`

## 2. Implementation
- [x] 2.1 `.uzmat` writer: `TextureSample → PBROutput` pins 0..6 and the inline scene-material block — `src/export/uzmat_writer.{h,cpp}`, independent byte writer; publication/preset integration remains open below
- [ ] 2.2 Preset `assets/export-presets/uzengine.json` with the seven outputs of the UzEngine preset table (`08-export.md` §4)
- [ ] 2.3 Canonical 16-bit/float maps written beside every cooked derivative (EXP-10)
- [ ] 2.4 Normal output in the convention settled by `phase0.9_normal-convention-fixture`, tagged `geometry_only` or `combined` with the relief round
- [ ] 2.5 Opacity in albedo alpha; receipt reports the SM5 route as unsupported for opacity
- [ ] 2.6 Receipt fields per file: engine format, colour space, bit depth, binding slot, normal tag, consumer gaps; manifest `exportacao` fields (INT-21)
- [ ] 2.7 SpecularWeight exported as `<set>_specularweight` and listed as a consumer gap with no engine slot
- [ ] 2.8 Provenance record `assets/export-presets/uzengine.provenance.json` with the `08-export.md` §4 fields
- [ ] 2.9 Preset resolvable by name in `defaultExportPreset`; dry run lists every output with its resolved format

## 3. Tests
- [ ] 3.1 Plan test: the dry run on wand v1 lists exactly the table's files with formats, colour spaces and bindings
- [x] 3.2 `.uzmat` test: pins 0..6 reference the matching `.uztexture` files and the inline block matches the file — `tests/export/test_uzmat_writer.py`, authored CPU fixtures, section 6
- [ ] 3.3 Canonical-map test: canonical maps equal, in decoded values, the same channels exported through the proven PNG route on wand v1
- [ ] 3.4 Receipt test: SpecularWeight and SM5 opacity gaps present; every file has hash, size, format and binding
- [ ] 3.5 Publication interruption test across the new file types: interrupting after each `.uztexture`/`.uzmat` write leaves the previous generation selected (EXP-06)
- [ ] 3.6 Provenance record validates against its schema on the local CPU lane (decision 200)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.4_uzengine-preset`: complete preset with explicit bindings, canonical maps, receipts and provenance

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Material writer evidence (2026-10-20)
- The writer follows approved `U-UZE-RUNTIME` commit `a703c95ada45002a774db9d9cf82b3b7964d09d6`. The seven pins are BaseColor, Metallic, Roughness, Normal, Emissive, Opacity and AO, fed by four texture samples. Height has no pin in that definition; the spec's earlier mention of height among pins 0..6 was corrected by source review and Claude/Codex consensus (SUP-091, ACK 95).
- The graph and inline block use one mounted delivery root, matching texture paths, explicit ORM and emissive multipliers of one. Normal remains encoded for the engine's downstream decode. Invalid UTF-8, traversal/device paths (including spaces before the extension), unsupported blend values and case-insensitive path matches across sRGB/linear slots are refused. Optional height and non-opaque SM5 opacity gaps are returned explicitly; no engine keys are invented.
- `zig build uzp-material-tests -j4`: Debug passed with warnings as errors, CPU only. `tests/export/test_uzmat_writer.py`: 40 passed, 0 skipped, 1.37 s; stable source/executable identities in `tmp/scratch/uzmat-audit/run2/{run.json,junit.xml}`. Executable SHA-256: `ef17469f6c7e7dd2a7d4ddafa78ac1e7718bdd580d38680d6b3b268058a29091`. Ruff check/format, mypy, source citation/revision audit and Zig formatting passed.
- Usage and limits: `src/export/EXPORT.md` section 5. These tests verify authored bytes and bindings, not real publication, Wand, Painter parity or engine rendering. The pinned shader reconstructs positive normal Z from XY even with an RGB texture; negative-Z render support and a height binding remain external consumer concerns. All other implementation, acceptance and prerequisite items remain open.
