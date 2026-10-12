# Proposal: phase1.16_export-processing-encoders

## Why
Exported maps are compared on decoded pixels at native depth and must be byte-identical across runs: padding (including infinite padding), resize, dithering and bit-depth/colour encoding must match Painter's export behaviour, and the PNG writer must be deterministic at 16 bit (UzEngine's 8-bit-only PNG encoder is not used) (EXP-02, EXP-05, EXP-10, INT-13, NFR-02). Implements D7 (decision 009: Painter-compatible JSON compiled into a validated plan) with owner answer Q10 (decision 023) in `docs/architecture/08-export.md` §1–§6; Phase 1 covers the plan compiler, padding/resize/dither, PNG8/16, EXR, the PBR, Blender and inline presets, generation-directory publication and receipts, while the Unreal, glTF and UzEngine presets and the TGA/BMP/JPEG/DDS writers follow in P3-UNREAL and P3-UZE. Child of `phase1.18_export-engine` (P1-EXPORT), covering `docs/architecture/08-export.md` §3 (PNG and EXR rows).

## What Changes
- `src/export/padding.{h,cpp}`: `passthrough`, `color`, `transparent`, `diffusion`, `infinite` plus `dilationDistance`, as compute passes over the coverage mask on the dilation pass of `phase1.3_core-image-passes`, behaviour fitted to Painter in Tier 0.
- `src/export/resize.{h,cpp}`: `sizeLog2` scalar keeps aspect, `[w,h]` does not; filter fitted in Tier 0.
- `src/export/dither.{h,cpp}`: explicit per map; algorithm fitted in Tier 0.
- `src/export/encode.{h,cpp}`: bit depths `8`, `16`, `16f`, `32f` as the format allows; colour-managed channels sRGB-encoded, data channels linear; `$colorSpace` from the project's colour configuration; signed normals kept at authoring precision (EXP-10); mesh maps at native precision with their recorded normalisation (INT-13).
- `src/export/png_writer.{h,cpp}`: 8/16-bit PNG over vendored libpng + zlib with fixed zlib level and strategy; `src/export/exr_writer.{h,cpp}`: 16f/32f EXR via tinyexr lossless modes.
- Fits: `parity/semantics/export-processing.json` (padding, resize filter, dithering).

## Dependencies
- DAG input of the parent: `phase1.14_compositor-core`; uses `phase1.3_core-image-passes` (dilation, resampling) through the render layer.
- Sibling prerequisite: `phase1.15_export-plan-compiler`.
- Parent: `phase1.18_export-engine`.

## Acceptance
Tier 0 export goldens owned by this child are exact on decoded pixels at native depth (padding, dithering, resize, bit depth), and exports are byte-deterministic. Goldens are private and compared locally on the owner's machine (decision 028; the local run report is the evidence; hosted CI skips these tests with an explicit reason); only fitted operators, their public sources and residuals are published under `parity/semantics/` (`docs/architecture/14-parity-testing.md` §6).

## Impact
- Affected specs: `export`
- Affected code: `src/export/padding.*`, `src/export/resize.*`, `src/export/dither.*`, `src/export/encode.*`, `src/export/png_writer.*`, `src/export/exr_writer.*`, `thirdparty/libpng/`, `thirdparty/zlib/`, `thirdparty/tinyexr/`, `parity/semantics/export-processing.json`, `tests/export/`
- Breaking change: NO
- User benefit: Pixel-exact, byte-stable map files at 16 bit, so repeatability and parity checks are meaningful.
