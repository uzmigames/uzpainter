# Proposal: phase1.15_compositor-colour-fits

## Why
Decision 130 moves the compositor's colour fits out of `phase1.14_compositor-core`, so that phase1.14 can close on its union run. These fits are blocked by recordings: decisions 108 §2 and §4, and item 2.9 from decision 117. Each case is refused before any mutation today, and nothing claims it is supported. This task gives each refusal an open owner with a checklist item.

## What Changes
- **P20-A and P20-B** (decision 107; phase1.14 item 2.9). Record the fill channel defaults probe and the dense sRGB decode probe, then fit the facade's colour tables to them exactly:
  - `DEFAULT_SOURCES` in `python/uzpainter_facade/nodes.py`;
  - `default_bitmap_space`, `available_bitmap_spaces` and the float32 sRGB decode in `colour.py`.
- **sRGB bitmap variants** (decision 108 §2). Today only a 16-bit colour bitmap sampled 1:1 onto an sRGB8 channel is fitted (`src/evaluator/sources.h`). This item covers the other uses:
  - as a mask source;
  - on a channel that is not sRGB8;
  - an 8-bit or grey bitmap;
  - a resampled bitmap;
  - the Working and Linear bitmap colour spaces.

  First measure what `export-ocio-encode-legacy` records. Name the recording that settles each variant it does not determine.
- **OCIO colour management** (decisions 101, 108 §2), after the Session O goldens `export-ocio-encode` and `export-presets-ocio`.
- **R5 Legacy twin s5**: the masked group of `export-ocio-encode-legacy`, which is unstable in the oracle (decision 032).
- **Lifting the refusals.** Lift each refusal only when its fit is exact:
  - `evaluator:unsupported_source` and `NotYetSupported` in `src/evaluator/support.cpp`, `dag.cpp` and `evaluate.cpp`;
  - the facade's P20-A refusals;
  - the capability entries `compositor:ocio` and `compositor:srgb-unrecorded`.

## Dependencies
- `phase1.14_compositor-core`: the evaluator, its sources and the support boundary.
- Recordings, all owner actions: P20-A, P20-B, Session O, and any sRGB-variant recording that item 2.2 names.

## Acceptance
- Every output of each recording above equals its golden, against both recordings, on CPU and DX12 (decision 028).
- Each refusal is lifted only for what is exact. What stays unrecorded stays refused, with this task named as its owner.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/sources.*`, `support.cpp`, `dag.cpp`, `evaluate.cpp`, `python/uzpainter_facade/colour.py`, `nodes.py`, `tools/capabilities/compositor-capabilities.json`, `tests/evaluator/`, `tests/python/`
- Breaking change: NO
- User benefit: bitmaps in every colour space and OCIO projects composite as in Painter.
