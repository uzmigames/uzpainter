# `phase1.15_compositor-colour-fits`: acceptance run on the owner's machine

Items 3.1 and 4.1 (decision 028): every colour fit this task lifted is compared against both recordings on the CPU, and evaluated on the DX12 store as well as the CPU store. Numbers and test names only; every recorded Painter output stays in the private store. Run on 2026-10-19 on branch `wt/t-1.15` (base `main` 39d8d7b), with this task's last changes:
- the decision 219 refusal names this task;
- P20-A's maps are evaluated on DX12 (`test_fill_channel_defaults_gpu_equals_cpu`).

**Result: every lifted case is exact.** Every fitted output equals Painter's, r1 and r2, on the CPU. On DX12 every channel the export writes is byte-identical to the CPU store. Every case that stays unrecorded is refused, and each refusal names this task.

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
| Legacy twin s3 to s5 (s5's r2 through EXC-006) | 145, 152 | `test_srgb8_bitmap_equals_painter_files` | byte-identical |
| sRGB variants (s0, s2 to s8) and Painter's sRGB refusals | 174 | `test_srgb_variants_equal_painter_files`, `test_bitmap_spaces_offered_and_refused_as_painter` | 381 of 381 comparisons; refusals as Painter's |
| OCIO evaluator and export | 190 | `test_ocio_encode_equals_painter_files`, `test_painter_ocio_png16_differs_from_legacy_on_74_values`, `test_ocio_png16_differs_from_legacy_where_painter_does` | 251 of 251 comparisons, 48 of 48 probe names |
| Facade under OCIO | 202, 240 | `test_facade_ocio_uniform_decode_equals_painter[part1..4]`, `test_colour_rule_readbacks_equal_painter[export-ocio-encode, export-ocio-encode-legacy]`, `test_colour_rules_implicit_space_conversions_and_the_pinned_profile`, `test_every_path_stores_a_uniform_colour_as_painter`, `test_create_takes_colour_management_from_the_environment_at_the_call` | every readback equal |
| sRGB minification: 16-bit (s4 to s7), 8-bit on level 0 (s0, s2) | 203, 219 | `test_srgb_minification_equals_painter_files` | 24 of 24 comparisons; s1 and s3 refused, naming this task |
| Legacy sRGB decode (P20-B); fill channel defaults (P20-A) | 214, 218, 224, 226, 249 | `test_facade_legacy_uniform_decode_equals_painter[part1..4]`, `test_facade_fill_channel_defaults_equal_painter` (1 passed, 13.6 s) | every readback and the four exact maps equal; Normal refused (decision 249) |
| `phase1-reload-resources` s9 and s12 | 214 | `test_observed_probe_events_equal_painter[*]` (7 probes) | equal |

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
