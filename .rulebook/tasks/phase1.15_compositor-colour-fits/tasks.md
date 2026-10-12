## 1. Prerequisites
- [ ] 1.1 Prerequisite accepted: phase1.14_compositor-core

## 2. Implementation
- [ ] 2.1 (decision 130, from phase1.14_compositor-core item 2.9; decisions 108 §4 and 117) Record P20-A (fill channel defaults) and P20-B (dense sRGB decode), the recordings of decision 107, then fit the facade's colour tables to them exactly: `DEFAULT_SOURCES` (`python/uzpainter_facade/nodes.py`), `default_bitmap_space`, `available_bitmap_spaces` and the float32 sRGB decode (`colour.py`)
  - Acceptance: every P20-A and P20-B output equal to its golden, both recordings; the `NotYetSupported` refusals naming P20-A and the exclusion `readback/get_source/29/BaseColor` of `export-ocio-encode-legacy` removed, their tests turned into exact comparisons; `phase1-reload-resources` recording 1 s9 and s12 exact in `test_pyapi_lifecycle_tier0.py`.
  - Blocked only by the two recordings (owner action); `parity/reports/phase1/python-api-facade.md` §3 names this item as the owner.
- [ ] 2.2 (decisions 108 §2 and 130) Fit the sRGB bitmap uses other than a 16-bit colour bitmap sampled 1:1 onto an sRGB8 channel (as a mask source, on another channel format, 8-bit or grey, resampled) and the Working and Linear bitmap colour spaces: measure first what `export-ocio-encode-legacy` records, and name the recording that settles each variant it does not determine; lift `evaluator:unsupported_source` / `NotYetSupported` (`support.cpp`, `dag.cpp`, `evaluate.cpp`) only for the variants made exact
- [ ] 2.3 (decisions 101, 108 §2 and 130) Fit OCIO colour management against the Session O goldens (`export-ocio-encode`, `export-presets-ocio`) and lift its refusal (evaluator and facade) and the `compositor:ocio` release gap
- [ ] 2.4 (decisions 108 and 130) R5 Legacy twin s5 (the masked group of `export-ocio-encode-legacy`, unstable in the oracle): exact against r1 (decision 032), r2 only through the exception register

## 3. Tests
- [ ] 3.1 Every fitted output exact against both recordings on CPU and DX12; the refusals of what stays unrecorded still fire before any mutation and name this task

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact for every lifted case (decision 028); `compositor:ocio` and `compositor:srgb-unrecorded` registered `supported` only for what is exact

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
