# `phase1.16_export-processing-encoders`: local run on the owner's machine and recording request R-090

This task is a child of `phase1.18_export-engine` (P1-EXPORT; `docs/architecture/08-export.md` §3, §5; EXP-02, EXP-05, EXP-10, INT-13, NFR-02). Under decision 028 its Tier 0 comparisons run locally against the private oracle store, and this report is their evidence.

Run on 2026-10-11/12, branch `wt/phase1.16-encoders`, with main merged up to the phase1.15 close (decisions 087, 091 and 092; current envelope `painter-12.1.5_js-api.1.1.20`). Decisions 089 and 090. Implementation: `src/export/` (`src/export/EXPORT.md` §4).

**Result.**

- **PNG and OpenEXR writers.** They produce Painter's bytes. Every distinct exported file of the current envelope was decoded at native depth and encoded again by UzPainter's writers, and the result is byte-identical:
  - 1027 PNG files of 1027 (grey, RGB and RGBA; 8 and 16 bits);
  - 267 OpenEXR 32f files of 267 (Y; B, G, R; A, B, G, R).
- **End to end.** `WriteExport` wrote every export step of the three height-normal plane goldens. That is 40 steps and 80 files, written in two processes. The results:
  - the files are exactly the dry run's;
  - the two processes wrote identical bytes;
  - the files are byte-identical to Painter's in 148 of 148 comparisons (r1, and r2 wherever r2 equals r1).
- **Refused before writing** (decision 090), because no recording or no fit decides them yet:
  - processing: PNG 8 values, OpenEXR 16f, dithering, resize;
  - padding: `color`, `transparent` and `diffusion`, and `infinite` on islanded texture sets;
  - layouts and channels: L+A, sRGB8 material channels, sRGB8 channels in OpenEXR, RGB+A;
  - mesh maps other than `normal_base`.

  Recording request R-090 (§5) covers them.

The refused remainder of items 2.2-2.6, 3.1-3.4 and 4.1 is a scope split to `phase1.18_export-engine` item 6.1 (decision 090, §6).

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200; the export tests evaluate on the CPU store |
| Build | Zig 0.15.2, Debug (with Zig's undefined-behaviour sanitizer); `zig build export-tests` and `zig build painter` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` on UzPainter's sources (tinyexr's translation unit with the third-party flags) |
| Libraries | zlib 1.3.2 (`uncompr.c` added), tinyexr v3.2.0 with one recorded local change (`thirdparty/tinyexr/ORIGIN.md`) |
| Oracle | current envelope `painter-12.1.5_js-api.1.1.20`; r1 is the exact target where r1 and r2 differ (decision 032) |
| Commands | `python -m pytest tests/export`; `python tests/export/encoders_tier0.py <uzp-export-tests.exe> <work>` regenerates `parity/semantics/export-processing.json`, and `test_published_export_processing_reproduces` requires the file to equal it |

## 1. The encodings Painter writes (decision 089)

All numbers below are measured on Painter's own files (in memory, never stored outside the private store).

**PNG.** Chunks:

- IHDR (not interlaced);
- pHYs: 2835 pixels per metre on both axes, unit metre;
- IDAT: every chunk exactly 8192 bytes except the last;
- IEND.

The zlib header is `78 9C`. The decoded samples re-encode to every file with one procedure:

- per row, the filter among None, Sub and Paeth only whose filtered bytes have the smallest sum of min(b, 256 - b), ties to the earlier;
- the row above the first row is zero;
- one zlib stream at level 6, window bits 15, memory level 8 and strategy Z_FILTERED.

It holds with Python's zlib 1.3.1 (984 files before the R-085 merge) and in C++ with the vendored zlib 1.3.2 (1027 files after it, the RGBA and 8-bit files included).

Rejected along the way: the libpng default filter set (None, Sub, Up, Average, Paeth). It chose Up where Painter chose Sub and missed 845 of the 984 files.

**OpenEXR.**

- Layout: single-part scanline files, version field 2.
- Attributes: channels, compression (PIZ), dataWindow, displayWindow, lineOrder (increasing y), pixelAspectRatio 1, screenWindowCenter (0, 0) and screenWindowWidth 1, in that order.
- Channels: FLOAT `Y`, `B G R` or `A B G R`.

Re-encoding results:

| Encoder | Identical files |
|---|---|
| OpenEXR 3.4.8 (Python binding), PIZ chunks only (its header adds a `type` attribute) | 216 of 216 |
| tinyexr v3.2.0, upstream | 20 of 216 |
| tinyexr v3.2.0 with OpenEXR's Huffman heap tie-break `(*a == *b && a > b)` | 216 of 216, whole file |

That tie-break (decision 089) is the only change. Without it tinyexr's PIZ table depends on the C++ library's heap algorithm. With it, after the R-085 merge, 267 of 267 files are identical.

## 2. Tests

### Hosted CPU lane (`tests/export/test_export_encoders.py`)

| Test | Item | Checks |
|---|---|---|
| `test_encoders_round_trip_and_repeat_across_processes` | 3.5, 3.6 | Synthetic PNG 16 and 8 and OpenEXR 32f images (grey, RGB, RGBA; ramps, runs, noise, signed zero, subnormals, infinities, NaN payloads; 1x1 and odd sizes). Decoded bit for bit by spng, tinyexr, the repository's own PNG decoder and OpenEXR's binding when installed. Encoded twice, and in two processes, with identical bytes. |
| `test_written_files_equal_the_dry_run_in_two_processes` | 3.5 | `WriteExport` writes exactly the dry run's files, sub-folder included, with the reported sizes and SHA-256; two processes write identical bytes (PNG 16 RGB and L, OpenEXR 32f L). |
| `test_written_values_follow_the_write_rules` | 2.5 | An L16 channel holding all 65536 codes comes back code for code through PNG 16; the OpenEXR file is a FLOAT `Y` image. |
| `test_unrecorded_processing_is_refused_before_writing` (8 cases) | 2.2-2.5 | PNG 8, OpenEXR 16f, dithering, two resizes and the three dilation paddings raise NotYetSupported naming R-090; nothing is written. |
| `test_alpha_layouts_are_refused_before_writing` | 2.5 | RGB+A is refused (decision 090); nothing is written. |
| `test_unfitted_srgb8_exports_are_refused` (2 cases) | 2.5 | BaseColor (sRGB8 material channel) and an sRGB8 User channel in OpenEXR are refused; nothing is written. |
| `test_padding_on_islands` | 2.2 | On the sphere: `infinite` is refused; `passthrough` writes every texel's evaluated value; a virtualMap source with `passthrough` is refused; without a mesh the export fails; nothing is written in the refusals. |

`tests/vendoring` covers the local-change record (`test_apply_local_changes`, `test_local_changes_are_recorded_in_origin`). The provenance test recomputes tinyexr's vendored header as the archive member with the change applied.

### Tier 0 (owner's machine)

| Test | Item | Result |
|---|---|---|
| `test_painter_files_reencode_byte_for_byte` | 2.6, 3.4 | 1027/1027 PNG and 267/267 OpenEXR identical |
| `test_written_goldens_equal_painter_files` | 3.1 (complete coverage), 3.3 (infinite padding without dithering), 3.4 (PNG 16, OpenEXR 32f), 3.5 | 40 steps, 80 files, 148/148 comparisons identical, 0 problems |
| `test_published_export_processing_reproduces` | 2.7 | `parity/semantics/export-processing.json` valid and equal to its re-derivation |

The goldens written end to end:

- `tier0/semantics/height-normal-plane-amplitudes` (s0-s3);
- `tier0/semantics-ui/height-normal-sharp-plane-strength` (s0-s7);
- `tier0/semantics-ui/height-normal-sobel-plane-strength` (s0-s7).

Each was written with both of its export steps: PNG 16 `Normal_OpenGL` and `Normal_DirectX`, and OpenEXR 32f `height` and `normal`.

## 3. Padding on islanded meshes (decision 090)

These measurements use `tier0/semantics/height-normal-bevelled-cube` and `-sphere` and their Sharp and Sobel twins. r1 equals r2 bit for bit on every map.

**`infinite` is not the nearest covered texel.** With the texel-centre coverage, Euclidean nearest-texel dilation misses on the Height map:

- 12040 of the bevelled cube's 12200 uncovered texels;
- 2581 of the sphere's 4096.

**A partial fit** (reference implementation in private scratch only). It is an iterative 8-neighbour copy dilation:

- each uncovered texel copies its first covered neighbour, in the order right, left, up, down, then the diagonals;
- x wraps around the tile, y does not;
- values are copied exactly.

| Map | Texels | Differing |
|---|---|---|
| Cube `Normal_OpenGL` / `Normal_DirectX` (3 goldens) | 12200 gutter | 0 |
| Sphere normals, Sharp | 4096 | 32 |
| Sphere normals, Sobel | 4096 | 44 |
| Cube Height beyond the ring, with Painter's ring values injected | 9856 | 0 |
| Sphere Height beyond the ring, with the ring injected | 1944 | 35 |
| Height ring: one texel around each island, cube / sphere | 2344 / 2152 | no model |

The sphere's misses sit in the pole wedges. The Height ring blends the value across the UV seam (the 3D-adjacent triangle on the other island) with the island's own value. The weights vary per edge and along it, for example 0.7595 / 0.2405. These models were tried and rejected: bilinear seam sampling, UV-space blends, coverage fractions, pull-push mip filling, a least-squares seam solver and nearest-in-3D. The best simple model (the nearest texel across the seam) gets 475 of the cube's 2344 ring texels.

**`passthrough`.** Inside the islands r1 equals r2. Outside them Painter's exports of layer content are session state: r1 and r2 differ at 431934 of 431934 uncovered texels on `leather-damaged/rounded-cube`, 423117 on `position/rounded-cube` and 11267 of 21824 on `metal-edge-wear/sphere`. On exported bakes the outside is the baker's own dilation followed by zeros, stable between recordings.

## 4. sRGB8 channels

- Every sRGB8 User-channel PNG 16 export of the current envelope is the linear operand, which is what the evaluator reads out: about 400 maps. On `blend-inputs` User2 and User3 cover all 256 codes.
- BaseColor exports are sRGB-encoded. The evaluator's template constants of the material colours (BaseColor, Specular) already hold export values.
- The rule for the other material channels is not recorded.
- So WriteExport writes sRGB8 User channels and refuses sRGB8 material channels (decision 090).
- No recording exports an sRGB8 channel to OpenEXR.

## 5. Recording request R-090 (for the agent that owns Painter)

These probes use the documented API through the recorder, Legacy colour management and the current envelope's build. Each golden is recorded as r1 (same session) and r2 (after save and reopen). Each export step is also repeated once in the same session, so that run-to-run noise (dithering) is measured. The recorder already keys outputs by step (decision 087). Goldens are added to `tools/parity/tier0_semantics/current.py` (`api_goldens`) as decision 077 did.

Unless stated, a probe uses the following:

- **Projects.**
  - `grid2x2` (s0-s3, every UV tile covered), OpenGL, 256 px.
  - Channels BaseColor sRGB8, SpecularRoughness L16, Height L16F and Normal RGB16F, plus Opacity L8 where named.
  - One fill per set:
    - s0: BaseColor and SpecularRoughness from `field-a` (16-bit RGB, Raw);
    - s1: the same from `grey-a`;
    - s2: uniform (0.8, 0.3, 0.1) and 0.37;
    - s3: Height from `field-a` at opacity 0.5.
- **Maps.** `documentMap/basecolor:RGB`, `specularroughness:L` and `height:L`, named `$textureSet_<map>` by the recorder.
- **Parameters.** `{"fileFormat": "png", "bitDepth": "16", "dithering": false, "paddingAlgorithm": "infinite"}`.

Each probe changes one thing:

| Probe | Change | Decides |
|---|---|---|
| P1 PNG 8 | `bitDepth` "8" | The 8-bit write rule of 16-bit, float and sRGB8 channels; the 8-bit filter choice and compression (decision 089's procedure at 8 bits) |
| P2 OpenEXR 16f | `fileFormat` "exr", `bitDepth` "16f"; Height also from a uniform 0.1 + 2^-13 (not a half) | Float-to-half rounding; the 16f header (pixel type HALF) |
| P3 dithering | `dithering` true, at PNG 8 and at PNG 16 | The dithering algorithm and whether it is deterministic within and across sessions |
| P4 resize | `sizeLog2` 7, 9, [8, 7] and [7, 8] on 256 px sets; s1 also with an impulse bitmap (one white texel at (100, 37)) | The resize filter, its edges, and up- against down-sampling |
| P5 padding on islands | On `bevelled-cube` and `sphere` (the meshes of `tier0/semantics/height-normal-bevelled-cube` and `-sphere`), one set each, Height and BaseColor from `field-a`: `paddingAlgorithm` `infinite`, `passthrough`, then `color`, `transparent` and `diffusion` with `dilationDistance` 0, 2 and 8; PNG 16 and OpenEXR 32f | The seam-following `infinite` operator; what `passthrough` writes outside the islands; the three dilation modes and the distance |
| P6 alpha layouts | Maps `$textureSet_la` (L from specularroughness, A from documentMap `opacity` with an L8 ramp fill) and `$textureSet_rgba` (RGB from user0, A from opacity); PNG 16 and OpenEXR 32f; on `grid2x2`, and on `bevelled-cube` with `infinite` and `transparent` (`dilationDistance` 2) padding | The colour type and channel names of L+A (RGB+A is recorded by R-085 P6/P7); alpha outside the islands |
| P7 mesh maps | Import `field-a` and bind it as the Position mesh map; import `grey-a` and bind it as Curvature and as AO. Export `meshMap/position:RGB`, `meshMap/curvature:L` and `meshMap/ambient_occlusion:L` as PNG 16 and OpenEXR 32f, padding `passthrough` and `infinite` | Mesh maps at native precision and their normalisation (INT-13) |
| P8 sizeLog2 range | `sizeLog2` 6 and 14 | Accepted (and written at that size) or the error text |
| P9 seam | A UzmiGames mesh of two quads sharing one 3D edge, mapped to two UV islands with different scales, offsets and a 90-degree rotation; resolutions 256 and 1024; Height and User0 (RGB16) from constant fills differing per side, then from `field-a`; `infinite` padding; PNG 16 and OpenEXR 32f; one island touching the tile's left border to probe the x wrap | The one-texel ring that blends across the UV seam; the copy order and the wrap (decision 090's partial fit) |
| P10 sRGB8 channels | Specular, Emissive and User0 (all sRGB8) filled from `field-a`, exported as PNG 16 and OpenEXR 32f; the same channels empty | Which sRGB8 channels are sRGB-encoded on export, in which formats, and their empty-channel constants |

## 6. Scope split to phase1.18_export-engine item 6.1

- **2.2 Padding.** Done: `passthrough` everywhere, `infinite` on complete coverage. Open: `color`, `transparent` and `diffusion`, which have no recording; and `infinite` on islands, partially fitted, where the ring needs R-090 P5 and P9.
- **2.3 Resize, 2.4 dithering.** No recording; refused until R-090 P3 and P4.
- **2.5 Encoding.** Open parts:
  - 8-bit and half-float rules (P1, P2);
  - mesh maps at native precision (P7);
  - sRGB8 material channels: recorded, fit pending, P10;
  - RGB+A: recorded; it needs the plan's alpha sources (R-091, phase1.15's close) before it can be written;
  - the luma of an empty sRGB8 channel (an evaluator refusal phase1.15 assigned here, part of the same sRGB8 material fit).
- **2.6 Writers.** PNG 8 and 16 and OpenEXR 32f encode Painter's bytes. OpenEXR 16f has no recording (P2).
- **3.1-3.4, 4.1.** Exact for every recorded case written today. Their dilation, dithering-on, resize, 8-bit and 16f parts wait for R-090.
- **3.5 Determinism (checked).** Byte determinism holds for PNG 8, PNG 16 and OpenEXR across runs and processes. The PNG 8 part is shown by the writer round trip; WriteExport itself refuses PNG 8 values until P1.
