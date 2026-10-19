# `phase1.15_compositor-colour-fits`: acceptance run on the owner's machine

Items 3.1 and 4.1 (decision 028): every colour fit this task lifted is compared against both recordings on the CPU, and evaluated on the DX12 store as well as the CPU store. Numbers and test names only; every recorded Painter output stays in the private store. Run on 2026-10-19 in the worktree of branch `wt/t-1.15`; the exact tree is under "Tested tree" below. This task's last changes were:
- the decision 219 refusal names this task;
- P20-A's maps are evaluated on DX12 (`test_fill_channel_defaults_gpu_equals_cpu`).

**Result: every lifted case is exact over the stable comparison domain.** On the CPU every fitted output equals Painter's r1, and equals r2 wherever Painter's r2 equals its r1. Three named r2 exceptions, all on set s5 (BaseColor in a group masked by grey A, where Painter itself is unstable after save and reopen):
- `test_ocio_encode_equals_painter_files` leaves out 5 unstable r2 comparisons (decision 032);
- `test_srgb_variants_equal_painter_files` leaves out 3 (decision 032);
- `test_srgb8_bitmap_equals_painter_files` judges its 3 Legacy r2 comparisons through EXC-006.

r1 is exact in all 11. On DX12 every channel the export writes is byte-identical to the CPU store. Every case that stays unrecorded is refused, and each refusal names this task.

**Not yet accepted.** These focused runs are not the full suite. The task's acceptance (item 4.1) and its archive wait for the next coordinated full suite to be green. The first full suite stands at 6 failed, 2 876 passed, 4 skipped, 1 xfail, and the export publisher is still pending (SUP-020).

## Tested tree

- **Commit.** The batches ran on the working tree of `E:\UzmiGames\UzPainter-wt\t-1.15` (since removed). It was branch `wt/t-1.15`, created at `main` 39d8d7be6b7b2e1462027d0dacd357ce71d2326a, with the uncommitted changes listed below. Those changes were committed afterwards, at 18:34:58, as bd1439bd3aeffc0eee1e8293893e01fe08f322c2 (tree b1c3d59391d9d890bd6e4ef95f9c4b708541f63c). That object survives only in the reflog of `wt/t-1.15`.
- **Rebase.** bd1439b was then rebased onto cc55850 as 18cea94 and squashed onto `main` as e698b8c. Both have tree 7e2a42e819fd44a6dc75d950e6663ea8b1136efb.
  - No test ran on 18cea94 or e698b8c.
  - Between 39d8d7b and cc55850, `main` changed nothing under `src/`, `python/`, `build.zig`, `tests/export/`, `tests/evaluator/` or `tests/python/`.
  - It did change, among others, `pyproject.toml`, `tools/capabilities/painter-api-inventory.json`, `parity/schema/golden-*.json` and the recorder.
- **Local patch at build time.** The binaries were built at 17:46 local time with `zig build evaluator-tests export-tests pyapi-tests -j4 --prefix <scratchpad>/t115/prebuild`, exit code 0 (empty `build2.log`). The only source change against 39d8d7b was the `evaluate.cpp` message edit of bd1439b. All three binaries contain its new string, "(phase1.15_compositor-colour-fits item 2.7, decision 219)".
- **Edits after the builds and runs.** These are known from the agent's session record, not from the logs:
  - `tests/evaluator/test_compositor_sources_projection.py` was edited until 17:51, before both batches.
  - The `LIFTED_COLOUR_SETS` comment in `tests/export/encoders_tier0.py` (comment only), `src/evaluator/EVALUATOR.md`, this report and `tasks.md` were edited after the CPU and DX12 batches.
  - `tools/capabilities/compositor-capabilities.json` was edited at 18:32:36, after those batches and 7 s before the capabilities run.
  - So the tree each batch ran on is bd1439b minus those later edits. No intermediate state was committed.
- **What the logs do not record.** The pytest logs record no commit. They give only the root directory `E:\UzmiGames\UzPainter-wt\t-1.15`. The identity above is rebuilt from git's reflog, the binaries and the session record. Nothing hashed the tree at run time.
- **Preserved files.** They are in the session scratchpad `t115/` (`C:\Users\Bolado\AppData\Local\Temp\claude\e--UzmiGames-UzPainter\06e8fc50-d3c2-4df6-bf29-0b84e80e4915\scratchpad\t115\`). The copies the tests ran from, under `bt-cpu/`, `bt-facade/` and `bt-gpu/`, have the same SHA-256 as `prebuild/bin/`:

| File | SHA-256 |
|---|---|
| `prebuild/bin/uzp-evaluator-tests.exe` (42 209 280 bytes) | `ccccb9c32670a34bf30da0a4f33be1757751cc3239d644069dcccd023528591e` |
| `prebuild/bin/uzp-export-tests.exe` (66 183 680 bytes) | `8b0dd70e3d070c3f494fb63f23da504a672b1b61d94636cfd814f7b480064ac6` |
| `prebuild/bin/uzp-pyapi-tests.exe` (97 710 592 bytes) | `7c6ed0953b6e8016fc2f9eecea2e061237343e7faea202ae3458276974031087` |
| `cpu-batch.log` | `3328973c8d6e7ccf773b8494ccb9cde7aa253daa3c5f8aab2cc2fc85dffabad7` |
| `dx12-batch.log` | `fa935c042e77f436e8d3be6da86ed9a18e2eb754beded2e7088649adb81d9cb4` |
| `facade-p20a.log` | `987f6dfee92b7a335c3cbb6d1eda19be3508b242f3201b91165e8edf23dbd21e` |
| `caps.log` | `b5fa3f99f14f1af976bf34c54017def3c6ae10ceb580d6b03cdabbc826b6c8c5` |

The scratchpad is temporary. Once it is gone, the commit SHAs and the hashes above are what remain.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200. The RTX 4090-gated cases `bilinear-hardware` and `srgb8-hardware` ran; they did not skip. |
| Backend | DX12 (`uzp-evaluator-tests` `gpu` store); CPU store for the export comparisons |
| Build | Zig 0.15.2; `zig build evaluator-tests export-tests pyapi-tests -j4`, exit 0 (`-Werror`) |
| Oracle | `C:\Users\Bolado\AppData\Local\UzPainter\parity-store`, envelope `painter-12.1.5_js-api.1.1.20`, recordings `r1` and `r2` |
| GPU exclusivity | Started after the 14:49 full-gate pytest ended (18:07), with no other `tests/evaluator`, `tests/preview`, `union_run`, `uzp-evaluator-tests` or `UzPainter.exe` process running |

## CPU: every fitted output against Painter (31 passed, exit 0, 1 633 s)

| Fit | Decision | Test | Result |
|---|---|---|---|
| 16-bit grey and 8-bit colour sRGB at 1:1; L8 material channels | 145, 204, 208 | `test_srgb8_material_channels_equal_painter_files`, `test_l8_material_channels_equal_painter_files`, `test_srgb8_material_channels_are_written_encoded`, `test_l8_material_channels_are_written_encoded` | byte-identical; `export-l8-material` 288 of 288 comparisons |
| Legacy twin s3 to s5 | 145, 152 | `test_srgb8_bitmap_equals_painter_files` | 9 files: 15 of 15 compared byte-identical (r1 and r2 of s3 and s4, r1 of s5). Exception: s5's 3 r2 BaseColor files (steps 46, 47, 48) are judged through EXC-006 (pass) |
| sRGB variants (s0, s2 to s8) and Painter's sRGB refusals | 174 | `test_srgb_variants_equal_painter_files`, `test_bitmap_spaces_offered_and_refused_as_painter` | 192 files: 381 of 381 compared byte-identical. Exception: 3 unstable r2 comparisons left out (s5 BaseColor, steps 78 PNG 16, 80 PNG 8, 82 OpenEXR 32f); their r1 is exact. Refusals as Painter's |
| OCIO evaluator and export | 190 | `test_ocio_encode_equals_painter_files`, `test_painter_ocio_png16_differs_from_legacy_on_74_values`, `test_ocio_png16_differs_from_legacy_where_painter_does` | 128 files: 251 of 251 compared byte-identical; 48 of 48 probe names. Exception: 5 unstable r2 comparisons left out (s5 BaseColor, steps 46, 47, 48 and probes 50, 51); their r1 is exact |
| Facade under OCIO | 202, 240 | `test_facade_ocio_uniform_decode_equals_painter[part1..4]`, `test_colour_rule_readbacks_equal_painter[export-ocio-encode, export-ocio-encode-legacy]`, `test_colour_rules_implicit_space_conversions_and_the_pinned_profile`, `test_every_path_stores_a_uniform_colour_as_painter`, `test_create_takes_colour_management_from_the_environment_at_the_call` | every readback equal |
| sRGB minification: 16-bit (s4 to s7), 8-bit on level 0 (s0, s2) | 203, 219 | `test_srgb_minification_equals_painter_files` | 24 of 24 comparisons; s1 and s3 refused, naming this task |
| Legacy sRGB decode (P20-B); fill channel defaults (P20-A) | 214, 218, 224, 226, 249 | `test_facade_legacy_uniform_decode_equals_painter[part1..4]`, `test_facade_fill_channel_defaults_equal_painter` (1 passed, 13.6 s) | every readback and the four exact maps equal; Normal refused (decision 249) |
| `phase1-reload-resources` s9 and s12 | 214 | `test_observed_probe_events_equal_painter[*]` (7 probes) | equal |

### The r2 exceptions and what approves them

| Golden | Test | r2 comparisons not held exact | Basis |
|---|---|---|---|
| `export-ocio-encode` | `test_ocio_encode_equals_painter_files` | 5: s5 step 46 `s5_basecolor.png`, step 47 `s5_basecolor.png`, step 48 `s5_basecolor.exr`, probe 50 and probe 51 `s5_basecolor_sRGB.png` | decision 032 (owner, 2026-10-11): for an unstable golden, r1 is the exact target |
| `srgb-bitmap-variants-v2` | `test_srgb_variants_equal_painter_files` | 3: s5 step 78 `s5_basecolor.png`, step 80 `s5_basecolor.png`, step 82 `s5_basecolor.exr` | decision 032; the instability is recorded in `parity/reports/phase0/tier0-stability.md` |
| `export-ocio-encode-legacy` | `test_srgb8_bitmap_equals_painter_files` | 3: s5 steps 46, 47 and 48, judged through the register | EXC-006 (`parity/exceptions.json`): `approved_by: owner` under decision 032's standing approval, flagged for the owner's review |

Decision 032 also asks for a register entry in `parity/exceptions.json` for each unstable golden. `export-ocio-encode` and `srgb-bitmap-variants-v2` have none. EXC-006 covers only `export-ocio-encode-legacy`, and its notes say the OCIO twin needs its own evidence and a new version of the entry if it is unstable. Their 8 r2 comparisons are left out by the tests rather than judged through the register, and that stays open.

## DX12: GPU = CPU on every lifted case (37 passed, exit 0, 291 s)

| Case | Test | Result |
|---|---|---|
| Every lifted texture set, as `WriteExport` evaluates it, every channel the export writes | `test_lifted_colour_fits_gpu_equals_cpu` | 30 of 30 sets byte-identical: `export-bit-depth` s4, s5, s7; `export-ocio-encode-legacy` s3, s4, s5; `srgb-bitmap-variants-v2` s0, s2 to s8; `export-ocio-encode` s0 to s7; `srgb-bitmap-minification` s0, s2, s4 to s7; `export-l8-material` s0, s1 |
| P20-A's BaseColor, BaseMetalness, Height and SpecularRoughness | `test_fill_channel_defaults_gpu_equals_cpu` (new) | GPU = CPU byte for byte, and the CPU raster's 16-bit export equals Painter's map on all 65 536 texels, r1 and r2 |
| Random projection stacks: sRGB, 16-bit sRGB minified, 8-bit level-0 sRGB8, L8 material, colour on L8/L16F, Normal | `test_projection_kernel_equals_cpu` (`projection-gpu-vs-cpu`) | bit for bit; on both stores a rotated Normal map and a grey one fail with `unsupported_source`; OCIO cache-key twin passes |
| The GPU's linear filter; the sRGB8 decode and store tables | `test_bilinear_filter_equals_the_gpu`, `test_srgb8_tables_equal_the_recording_gpu` | equal on the recording GPU |
| CPU native cases | `test_sources_on_the_cpu`, `test_order_case_stores_bitmaps_on_srgb8` | pass |
| Refusals before any mutation | `test_compositor_core.py::test_excluded_features_raise_not_yet_supported_before_any_mutation` | pass |

P20-A is an API probe, so no semantics spec exists for it. The new test builds the texture set the way the facade builds it, from the recorded sequence:
- the default source of every active channel (`DEFAULT_SOURCES`, decision 214);
- Painter's Height `LinearDodge` and Normal `NormalMapDetail` blending (decision 115);
- sRGB for the grey bitmap on BaseColor.

The CPU comparison against Painter's maps shows that this spec is the facade's project. Without the default blending, Height missed all 65 536 texels.

## What stays refused, and where

Each refusal names `phase1.15_compositor-colour-fits`:

| Case | Refused by |
|---|---|
| A bitmap colour space outside the recorded ones; sRGB on a non-sRGB8 channel that is not an L8 material channel; OCIO bitmap uses Session O does not record | the support check, before any change (`support.cpp`; OCIO by PNG header, decision 240) |
| Under OCIO, facade uniform components outside the measured table, other spaces, unrecorded listings and defaults | the facade, before any change (decision 202) |
| 8-bit sRGB minification that reads a mip level (item 2.7, decision 219) | evaluation (`evaluate.cpp`); this message now names the task, before it named only decision 219 |
| A colour or resampled sRGB bitmap on an L8 material channel (decision 208); the other one-channel colour uses (item 2.9, decision 218); the Normal uses of decision 249 (item 2.9) | evaluation |

Under decision 240 (C5), the image-dependent Legacy checks stay at evaluation. An export, capture or diagnostic that meets one fails before it writes anything.

## Reproduce

```
zig build evaluator-tests export-tests pyapi-tests -j4
python -m pytest -p no:cacheprovider -rA <the node ids above>
```
