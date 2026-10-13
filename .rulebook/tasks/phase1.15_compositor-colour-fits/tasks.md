## 1. Prerequisites
- [x] 1.1 Prerequisite accepted: phase1.14_compositor-core (archived 2026-10-12)

## 2. Implementation
- [ ] 2.1 (decision 130, from phase1.14_compositor-core item 2.9; decisions 108 §4 and 117) Record P20-A (fill channel defaults) and P20-B (dense sRGB decode), the recordings of decision 107, then fit the facade's colour tables to them exactly: `DEFAULT_SOURCES` (`python/uzpainter_facade/nodes.py`), `default_bitmap_space`, `available_bitmap_spaces` and the float32 sRGB decode (`colour.py`)
  - Acceptance: every P20-A and P20-B output equal to its golden, both recordings; the `NotYetSupported` refusals naming P20-A and the exclusion `readback/get_source/29/BaseColor` of `export-ocio-encode-legacy` removed, their tests turned into exact comparisons; `phase1-reload-resources` recording 1 s9 and s12 exact in `test_pyapi_lifecycle_tier0.py`.
  - Blocked only by the two recordings (owner action); `parity/reports/phase1/python-api-facade.md` §3 names this item as the owner.
- [x] 2.2 (decisions 108 §2 and 130) Fit the sRGB bitmap uses other than a 16-bit colour bitmap sampled 1:1 onto an sRGB8 channel (as a mask source, on another channel format, 8-bit or grey, resampled) and the Working and Linear bitmap colour spaces: measure first what `export-ocio-encode-legacy` records, and name the recording that settles each variant it does not determine; lift `evaluator:unsupported_source` / `NotYetSupported` (`support.cpp`, `dag.cpp`, `evaluate.cpp`) only for the variants made exact
  - Fitted (decision 145): a 16-bit grey and an 8-bit colour sRGB bitmap at 1:1 on an sRGB8 channel, exact byte for byte against `export-ocio-encode-legacy` s3 (8-bit ramp, PNG 16, PNG 8, OpenEXR 32f) and `export-bit-depth` s4, s5, s7 (16-bit grey), r1 and r2; refusal lifted in `evaluate.cpp`.
  - Done (decision 174), against `srgb-bitmap-variants-v2` (decisions 156, 166, 167): each sRGB texel is decoded to float32 before the projection samples it (8-bit: the GPU's sRGB8 decode; 16-bit: its contracted float32 shader decode). Nearest ties take the upper row. Working and Legacy Linear read as Raw, and Legacy sRGB as sRGB.
    - Byte for byte, through `WriteExport` at PNG 16, PNG 8 and OpenEXR 32f, every map: 192 files and 381 of 381 comparisons (r1, and r2 where stable; s5's unstable BaseColor r2 left out, r1 exact). This covers s0 (8-bit grey at 1:1), s2 (BilinearHQ magnification, 16- and 8-bit), s3 (Nearest at scale 2), s4, s5 and s6-s8 (`test_srgb_variants_equal_painter_files`).
    - s4 and s5: Painter refuses sRGB on the six non-sRGB8 user channel formats and on a mask source. The facade lists Raw, Data and DataSigned there and raises the same `ValueError: Invalid colorspace 'standard sRGB'` before any change (`test_bitmap_spaces_offered_and_refused_as_painter`).
    - s1 (BilinearHQ minification at 30 degrees) stays refused for every bitmap (decisions 061, 084).
  - Split to 2.5: bilinear minification of an sRGB bitmap, which no golden records.
- [x] 2.3 (decisions 101, 108 §2 and 130) Fit OCIO colour management against the Session O goldens (`export-ocio-encode`, `export-presets-ocio`) and lift its refusal (evaluator and facade) and the `compositor:ocio` release gap
  - Done for the evaluator and the export (decision 190). OCIO with Painter's substance config (`evaluator::PainterOcio`, config SHA-256 `15059d4b…`) is admitted. Every source Session O records evaluates: uniform colours, an 8-bit colour bitmap in sRGB on an sRGB8 channel at 1:1, and a 16-bit grey mask source at 1:1. An 8-bit colour bitmap in Raw reads each code as float32(c / 255) rounded toward zero to a binary16 (`OcioRawDecoded`; c / 255 misses 4 of 256 codes).
  - The PNG 16 of an sRGB-encoded channel writes the measured 257-entry table (`OcioSrgbPng16Code`): no analytic encode reproduces it. `$colorSpace` is `sRGB` or `Raw`.
  - `export-ocio-encode` (every map of steps 46-49 and the probes 50-51): 128 files, 251 of 251 comparisons byte-identical (r1, and r2 where stable; s5's unstable BaseColor r2 left out, r1 exact), 48 of 48 probe names (`test_ocio_encode_equals_painter_files`). `compositor:ocio` is `supported`.
  - Split to 2.6: the facade keeps refusing OCIO. Its uniform working values differ from Painter's readbacks on all six recorded components, and its listing lacks the eleven OCIO spaces.
  - Split to `phase3.3_unreal-gltf-presets` 3.5: per-preset pixel parity of `export-presets-ocio`, as for its Legacy twin.
- [x] 2.4 (decisions 108 and 130) R5 Legacy twin s5 (the masked group of `export-ocio-encode-legacy`, unstable in the oracle): exact against r1 (decision 032), r2 only through the exception register
  - Done (decision 152): s5's BaseColor (the 8-bit sRGB ramp in a group masked by grey A) is written byte for byte as r1 at PNG 16, PNG 8 and OpenEXR 32f, with no evaluator change (the export tests' spec loader now reads masks). r2 differs from r1 on 15 947 values per file and is judged through EXC-006 (`parity/exceptions.json`, decision 032's standing approval, flagged for the owner's review); `test_srgb8_bitmap_equals_painter_files`.
- [ ] 2.5 (decision 174, split from 2.2) Bilinear minification of an sRGB bitmap: record a Tier 0 set of the 8-bit ramp and field A in sRGB on BaseColor at BilinearHQ and BilinearSharp, scales 2 and 4, rotation 0, Repeat (owner action at Painter), then fit the decoded texels' mip chain through the texture unit and lift `compositor:srgb-unrecorded`
  - Refused until then with `evaluator:unsupported_source` ("bilinear minification of an sRGB bitmap is not recorded").
- [ ] 2.6 (decision 190, split from 2.3) The facade under OCIO with Painter's substance config: fit the working value of a uniform colour in the sRGB space as Painter reads it back under OCIO, and the eleven-space bitmap listing (`export-ocio-encode` readbacks: 1e-7 to 7e-6 relative from the Legacy float32 rule on every recorded component). Then lift `colour.require_supported_configuration`'s OCIO refusal and `compositor:ocio-unrecorded` where exact. This unblocks the Wand pilot (phase1.25), which runs under OCIO.
  - Recording that settles it (owner action at Painter): P20-B's OCIO twin, the dense uniform sRGB decode readbacks in a Session O window.
  - Refused until then: the facade raises `NotYetSupported` on an OCIO project before any evaluation.

## 3. Tests
- [ ] 3.1 Every fitted output exact against both recordings on CPU and DX12; the refusals of what stays unrecorded still fire before any mutation and name this task

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact for every lifted case (decision 028); `compositor:ocio` and `compositor:srgb-unrecorded` registered `supported` only for what is exact

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
