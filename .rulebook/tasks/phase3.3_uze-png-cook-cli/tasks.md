## 1. Prerequisites
- [x] 1.1 `phase3.2_uze-uzmat-preset` preset, writers and receipts delivered and used as they are (its own acceptance stays open on `AO_Mixed`, decision 131; this verb evaluates no project and does not read `AO_Mixed`)

## 2. Implementation
- [x] 2.1 Shared cook: `CookUzEngineDerivative` and `WriteUzEngineMaterial` extracted from `src/export/write.cpp` (`write.h`), used by `EncodeExport` and the verb; the receipt's UzEngine gap texts moved to `receipt.h` (decision 380)
- [x] 2.2 Verb `cook-uzengine` in `src/export/cook_uzengine.cpp` (`cli.h`), dispatched by `src/main.cpp` and `uzp-export-tests.exe`; targets read from the shipped `uzengine` preset
- [x] 2.3 Input contract and refusals (decision 380): bit depth 8/16, colour type, tRNS, sizes, power of two, alpha only on the albedo, grey maps, stated normal convention, negative Z, set name; missing alpha = opacity 1, missing emissive = black
- [x] 2.4 Receipt on stdout: inputs with file and decoded hashes, files with sha256, format, colour space, mips, filter, encoder and settings, consumer gaps, opacity source

## 3. Tests
- [x] 3.1 `tests/export/test_uze_png_cook.py::test_canonical_maps_of_a_native_export_cook_to_its_bytes`: a native export's canonical PNG 16 maps cook to its five `.uztexture` files and `.uzmat` byte for byte
- [x] 3.2 `test_equal_decoded_inputs_give_equal_bytes`, `test_runs_are_deterministic`, `test_three_png_set_cooks_with_its_receipt`, `test_albedo_alpha_masks_the_material_and_height_is_bc4`
- [x] 3.3 `test_contract_violations_are_refused_and_write_nothing` (10 cases), `test_unsafe_set_names_are_refused` (6), `test_usage_errors_exit_2` (7)

## 4. Docs and review
- [x] 4.1 `src/export/EXPORT.md` §5 (UzEngine PNG cook), `docs/architecture/08-export.md` §4, `src/export/cli.h`, usage in `src/main.cpp`
- [x] 4.2 External review of the frozen diff (decision 367 item 6): `cx/gpt-6-astra` found the blend decided from alpha values instead of the file's alpha channel (native rule: layout), `cx/gpt-6.1-sol` found trailing chunks unread; both fixed in `bc71ae9c` with a test each. `xai/grok-4.6` and `kimi/kimi-k3` streamed past the 180 s deadline twice without a verdict

## 5. Acceptance
- [ ] 5.1 Child acceptance reported to `phase3.4_uzengine-preset`; that UzEngine loads the files stays with `phase3.3_uze-consumer-fixture`

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [x] 6.1 Update or create documentation covering the implementation
- [x] 6.2 Write tests covering the new behavior
- [x] 6.3 Run tests and confirm they pass

## 7. Evidence (2026-11-02, front D)
- `python -m pytest tests/export/test_uze_png_cook.py` plus the four `test_uze_preset.py` nodes the refactor touches (receipt gaps, `.uzmat`, canonical cook, SpecularWeight gap): 32 passed, CPU only, one `zig build export-tests` by the fixture. Ruff and mypy clean on the test file.
- Not covered: `UzPainter.exe` itself was not built here (its dispatch is two lines calling the same `RunCookUzEngineCommand`); no Painter export was cooked, so the Assets3D files are proven by the decoded-input definition, not by a Painter sample.
- After the review fixes: `python -m pytest tests/export/test_uze_png_cook.py`: 29 passed (rebuilt by the fixture), ruff and mypy clean.
- `proposal.md` and `.metadata.json` are not written: the scaffolding guard (`.claude/hooks/protect-task-scaffolding.sh`) allows them only through `rulebook_task`, whose id check refuses the `phase<N>.<M>_` form (AGENTS.override.md), and the `rulebook` CLI does not start (missing `dist/index.js`). The proposal text is in decision 380.
