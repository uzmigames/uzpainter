# 90. Export processing writes only what the recordings decide and refuses the rest before writing, until recording R-090

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.16_export-processing-encoders, phase1.18_export-engine, phase1.15_export-plan-compiler

## Context

Task phase1.16 asks for the five padding algorithms with `dilationDistance`, resize (`sizeLog2`), dithering, and bit depth and colour encoding (8 and 16 PNG, 16f and 32f OpenEXR), all fitted to Tier 0 (`docs/architecture/08-export.md` §3). Measured on the current envelope (Painter 12.1.5):

- **Recorded exports.** Every recorded export uses one of three combinations, always without dithering and at the texture set's size:
  - PNG 16 with `infinite` padding (113 steps);
  - PNG 16 with `passthrough` padding (22 steps);
  - OpenEXR 32f with `infinite` padding (40 steps).

  R-085's probes add RGBA files at PNG 16 and OpenEXR 32f and four 8-bit PNG files. Nothing records `color`, `transparent` or `diffusion` padding, dithering, resize, OpenEXR 16f, the L+A layout, or an exported imported mesh map other than `normal_base`.
- **End to end.** On grid meshes the UV islands cover every tile. There, `WriteExport` writes the 40 export steps of three goldens as 148 files, byte-identical to Painter's (r1, and r2 where it equals r1). They are exactly the dry run's files, identical across two processes.
- **`infinite` on islanded meshes** (bevelled cube, sphere: 6 goldens, r1 = r2 everywhere).
  - Nearest-texel dilation misses 12040 of the cube's 12200 gutter texels.
  - A fit found an 8-neighbour copy dilation: each uncovered texel copies its first covered neighbour, in the order right, left, up, down, then the diagonals; x wraps and y does not.
    - On the cube's virtual normal maps it is exact.
    - On the spheres it misses 32 to 44 texels per normal map, at the poles.
  - For a document channel (Height), the seeds also include a one-texel ring around each island. Its values blend the value across the UV seam with the island's own value, with weights that vary per edge and along it. The mechanism is not identified: six candidate models were rejected with numbers.
- **`passthrough`.** Inside the islands Painter's r1 and r2 agree. Outside them, the procedural goldens differ between r1 and r2 at up to every uncovered texel (431934 of 431934), so they hold session state. Baked maps exported with `passthrough` keep the baker's own dilation and then zeros.
- **sRGB8 channels.**
  - User channels: every sRGB8 User-channel PNG export (about 400 maps) is the linear operand.
  - BaseColor exports are sRGB-encoded, and the evaluator's template constants of the material colours are already export values (phase1.15's probe fit).

The model panel was consulted twice under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C5 Refuse everything unrecorded with NotYetSupported naming R-090; write no code for it; leave the items open | AGREE x3 |
| C6 Implement the unrecorded paths now from documentation and common practice, marked unverified | DISAGREE x3 |
| D1 Refuse `infinite` on islanded sets until the ring is fitted exactly; publish the partial fit as a `gap` with its numbers; keep the reference implementation private | AGREE x2, PARTLY x1 (also exact coverage, ties and propagation) |
| D2 Ship the partial fit as `calibrated` | DISAGREE x3 |
| D3 Support `passthrough` on islanded sets as no operation, with the parity contract on covered texels (Painter's outside is unstable) | PARTLY x2 (refuse the stable baked case unless reproduced), DISAGREE x1 |
| D4 Refuse `passthrough` on islanded sets too | AGREE x1, DISAGREE x2 |
| D5 R-090 gets a dedicated seam probe and the sphere pole wedge | AGREE x3 (add resolutions, other channel types, UDIM and border wrap) |

## Decision

1. **Written today** (`src/export/encode.h`, `padding.h`, `write.h`):
   - formats: PNG 16 and OpenEXR 32f, grey or RGB;
   - values: the evaluator's read-out, UNORM-written at 16 bits, raw float32 in OpenEXR;
   - no dithering, at the texture set's size;
   - padding: `infinite` and `passthrough` on complete coverage (no change), and `passthrough` on incomplete coverage as no operation.

   sRGB8 User channels are written linear.
2. **Refused before anything is written**, with `core::NotYetSupported` naming recording R-090:
   - PNG 8; OpenEXR 16f; the L+A layout; an sRGB8 channel in OpenEXR; dithering; resize;
   - the `color`, `transparent` and `diffusion` paddings;
   - `infinite` on incomplete coverage;
   - `passthrough` on incomplete coverage for a file that reads a meshMap or virtualMap source;
   - mesh maps other than `normal_base`, and `sizeLog2` outside 7..13 (the plan's former phase1.16 refusals).

   No processing code is written for these.
3. **Recorded but not fitted here**, refused naming this decision:
   - the export encoding of sRGB8 material channels (BaseColor and the others), which is entangled with the evaluator's template constants (owner: the plan and evaluator side, phase1.15's close);
   - the RGB+A layout (R-085 P6/P7: an alpha of 1 everywhere is dropped), until the plan resolves its alpha sources.

   The writers already encode RGBA, and 8-bit PNG, byte-identically to Painter.
4. **The partial `infinite` fit** is published in `parity/semantics/export-processing.json` as a `gap` with its numbers. Its reference implementation stays in private scratch.
5. **Recording R-090** (`parity/reports/phase1/export-processing-encoders.md` §5) specifies one probe per open behaviour. The seam probe isolates the ring, and the sphere pole wedge is included.
6. **Scope split** (the speed rules of 2026-10-12, decision 069's pattern). Items 2.2-2.6, 3.1-3.4 and 4.1 of phase1.16 are checked for what is exact. The refused remainder moves to `phase1.18_export-engine` item 6.1, which fits it from R-090. Nothing refused is claimed as supported.

## Alternatives Considered

- **Implementing resize, dithering, 8-bit and half-float rules from common practice.** Rejected by the panel: these are unverifiable guesses.
- **Shipping the partial `infinite` fit.** Rejected: it would accept a residual.
- **Refusing `passthrough` on islands outright.** Rejected by the panel majority: Painter itself gives no exact target outside the islands for layer content.

## Consequences

- The Assets3D pipeline presets export PNG 16 on full-coverage sets, and their mesh-map-free maps work.
- Their BaseColor waits for the sRGB8 material-channel fit.
- Islanded meshes with `infinite` padding wait for R-090.
- R-090 must be recorded by the agent that owns Painter.
