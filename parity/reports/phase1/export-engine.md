# `phase1.18_export-engine`: local run on the owner's machine (P1-EXPORT)

This task is the parent of the export children (P1-EXPORT; `docs/architecture/08-export.md` §1–§5; EXP-01…EXP-06, EXP-09, EXP-10, INT-13, INT-21, QG-03, NFR-02, ARC-11). Under decision 028 its Tier 0 comparisons run locally against the private oracle store, and this report is their evidence for the G1 gate record (numbers and hashes only).

Run on 2026-10-12, branch `wt/phase1.18-engine`, with main merged through decision 101 (the R-090 recordings) and envelope `painter-12.1.5_js-api.1.1.20`. Decisions 103 (processing fits and scope splits) and 104 (the end-to-end export). Implementation: `src/export/` (`src/export/EXPORT.md` §4, §7).

## Result

| Gate element | Result |
|---|---|
| Painter's files re-encoded by UzPainter's writers | 1826 of 1826 PNG and 823 of 823 OpenEXR distinct files byte-identical (`test_painter_files_reencode_byte_for_byte`) |
| Processing applied to Painter's own values (R-090) | 384 of 384 `export-bit-depth` cases (PNG 8, PNG 16, OpenEXR 16f; channels, Height, mesh maps), 4 of 4 `export-alpha-layouts` files, 20 of 20 dithered PNG 16 files byte-identical (`test_processing_reproduces_painter_files`) |
| Goldens written end to end by `WriteExport` | 40 steps, 80 files, 148 of 148 comparisons byte-identical to Painter (r1, and r2 wherever r2 equals r1) (`test_written_goldens_equal_painter_files`) |
| Published semantics | `parity/semantics/export-processing.json` re-derived on this machine (`test_published_export_processing_reproduces`) |
| Byte determinism (item 3.2) | `UzPainter.exe export` of one `.uzp` project in two processes: files and plans byte-identical, receipts equal except `generation` and `moment` (`test_project_export_is_deterministic_across_processes`) |
| Publication interruption (item 3.3) | phase1.17's suite over the same `PublishExport` (`tests/export/test_export_publication.py`): every interruption point leaves one complete generation visible |

The plan compiler's Tier 0 evidence (dry runs of every exporting golden, the R-085 and R-091 probes, the virtual-map goldens) is `parity/reports/phase1/export-plan-compiler.md`. AO_Mixed and the converted virtual maps are still refused there (R-092, phase1.15). The presets' evidence is `parity/reports/phase1/export-presets.md`.

## What item 6.1 adds (decision 103)

- **PNG writer.** 8-bit grey takes the least-cost row filter among all five filters and compresses with `Z_DEFAULT_STRATEGY`. Every other layout takes it among None, Sub and Paeth and compresses with `Z_FILTERED`. 76 of 76 8-bit grey files and 1773 of 1773 others follow this rule. The phase1.16 three-filter rule missed 32 of the 8-bit grey streams; that was the cause of the two red encoder tests.
- **OpenEXR writer.** HALF channels (16f) and the grey and alpha layout `A, Y`.
- **Values.**
  - PNG 8 is the UNORM write rule at 8 bits.
  - OpenEXR 16f rounds toward zero to a half.
  - Height is written to PNG as v × 0.5 + 0.5.
  - An all-opaque alpha is dropped, and the receipt records the written layout.
  - Dithering changes nothing at PNG 16.
  - The AO, Curvature and Position mesh maps pass through.
- **Evaluator read-out on `export-bit-depth`.** It equals Painter's OpenEXR 32f for the User channels, Height, SpecularRoughness and Normal. The virtual normals and normal_base are exact at PNG 8, PNG 16 and OpenEXR 16f.

## Refused before writing, with owners (decision 103)

| Behaviour | Fit state | Owner |
|---|---|---|
| sRGB8 material channels (BaseColor, Specular, Emissive) | PNG 8 exact (UNORM8 of the IEC encoding of the linear value). PNG 16 misses by up to one code on about 70 of 258 values. The template constants are export values in the evaluator | `phase1.25_pilot-wand` 2.6 |
| `infinite` padding on islanded sets | decision 090's partial fit; seam ring open | `phase1.25_pilot-wand` 2.7 |
| Dithering at PNG 8, dithering in OpenEXR | PNG 8 deterministic, not a threshold matrix; OpenEXR has no off twin | `phase3.2_unreal-ue56-packed-preset` 2.9 |
| Resize | Upscale is the evaluation at the target size. Downscale is a 2×2 box stored in the channel format (UNORM16; L16F half away from zero). Open: sRGB8, normals after a downscale, and BilinearHQ normal magnification | `phase3.2_unreal-ue56-packed-preset` 2.9 |
| `color`, `transparent`, `diffusion` paddings | not fitted | `phase3.2_unreal-ue56-packed-preset` 2.9 |
| Per-preset parity (item 6.2) | R-095 not recorded (`export-presets-legacy` crashed Painter) | `phase3.3_unreal-gltf-presets` 3.5 |

## Recordings this task needed

- **Used:** R-090 as admitted on main (decision 101): `export-bit-depth`, `export-dither`, `export-resize`, `export-alpha-layouts`, `export-padding`, `export-padding-bevelled-cube`, `export-padding-sphere`, `export-padding-seam-256/-1024`, `export-padding-seam-field-256/-1024`, `export-ocio-encode-legacy`.
- **Not recorded:** R-095 (`export-presets-legacy` crashed Painter; `export-presets-ocio`), `export-ocio-encode`.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200; the export evaluates on the CPU store |
| Build | Zig 0.15.2 Debug; `zig build export-tests` with `-Wall -Wextra -Werror -ffp-contract=off` on UzPainter's sources |
| Commands | `python -m pytest tests/export/test_export_engine.py tests/export/test_export_encoders.py tests/export/test_export_publication.py`; `python tests/export/encoders_tier0.py <uzp-export-tests.exe> <work>` regenerates `parity/semantics/export-processing.json` |
