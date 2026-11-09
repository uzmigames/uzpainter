# 416. Material sources serve Height from the multi-output capture; unfit masks and split template-channel stores move to phase3.3

**Status**: accepted (coordinator scope split under the owner's throughput rule, 2026-11-09)
**Date**: 2026-11-09
**Related Tasks**: phase3.2_source-substance-presets-inputs, phase3.3_procedural-families, phase3.2_proc-material-families

## Context

Decision 413 kept material channels unrecorded until P413-A and P413-B were fitted. P413-A fitted the unmasked material Height exactly, but not the masked Height or the split BaseColor fill (item 2.4 note of 2026-11-09). The separating recordings P413-C, P413-D and P413-E were recorded and admitted on 2026-11-09 (Legacy, Painter lock seq 2344/2345; `tools/parity/tier0_semantics/source_substance_separation.py`; diagnostic `python -m tools.parity.fit.material_channels`).

Measured facts, Painter `12.2.0+js-api.1.1.20`:

- **Unmasked Height.** In P413-A, every unmasked configuration gives `tz16(float32(2x - 1))` on every texel, in r1 and r2. `x` is the L32F view of the output `output_mapping` gives Height, and `tz16` is binary16 rounding toward zero. These are 8 configurations plus `material-only`. This is the evaluator's existing Height bitmap rule (`RangeValue`, then the L16F store). BaseColor and Normal are untouched: Height is the material fill's only active channel.
- **Masks (P413-C).** These are non-constant outputs with r1, r2 and r3.
  - A `mask_output` equal to the output mapped to Height leaves Height unchanged in all three recordings (`masked-by-height`, `masked-by-normal-swap`).
  - Another mask output gives, in r1, `tz16(float32(H16 * tz16(R)))` exactly. `H16` is the unmasked Height and `R` the red component of the mask output's RGB32F view.
  - r2 and r3 are equal to each other and lower than r1. They fit `tz16(H16 * M16 * k)` with `k` in [0.999154, 0.999204), and nothing models that factor.
  - The save/reopen divergence is deterministic and stable after the first reopen.
- **Split stores (P413-D).** Here r1 equals r2.
  - Split Height is the material Height rule on the active output's L32F view.
  - Split BaseColor is monotone in the RGB32F view, but it is neither a float32 sRGB decode nor an 8-bit nearest store of that view (7 values). It cannot be derived from the captured float views.
- **Mapping contexts (P413-E).** Here r1 equals r2.
  - On a split source (BaseColor, Height, User0/User1), the `output_mapping` property returns an `OutputMapping`. Iterating it, `len` and subscription each raise `EditionContextException("Only valid in multi channel context")`.
  - On a material source, iteration gives the mapped channels and subscription gives the `str` output. An unmapped channel raises `ValueError("output not found")`.
- **The presets probe.** `source-substance-presets-inputs` r1 ends with `mask_output` set to `height` while Height is mapped to `normal` (s89): a fitted r1, an unfitted r2. Its r2 starts from that state.
- **Missing metadata.** The capture's metadata records no default resolution of the material source (s17 reads Auto 1024).

## Decision

1. **Implemented exact scope** (item 2.4).
   - `FillLayerNode.set_material_source(ResourceID)` binds the project's own decision-413 capture of that resource. The resource is identified by the observed URL. The capture must hold exactly one recorded default parameter set with no preset and no plugged input; otherwise the call refuses.
   - The facade's `SourceSubstance` of a material implements:
     - `get_parameters`, `get_properties`, `get_preset_list`, `image_inputs`, `image_outputs` and `resource_id` from the snapshot of the current exact signature;
     - `active_output` with Painter's single-context refusal;
     - `apply_preset`, with Painter's missing-name `ValueError`;
     - the image-input `get_source`/`set_source` (working colour, bitmap read back as Data)/`reset_source`/`remove_source`, where an unplugged input reads Painter's `SourceBitmap` whose `resource_id` raises the recorded error;
     - `output_mapping` as an `OutputMapping` (iteration, `len`, subscription, item assignment of a listed output);
     - `mask_output` (the recorded default; assigning the default back raises `ValueError("Invalid output name …")`).
   - On split sources, `output_mapping` and `mask_output` reproduce P413-B/E.
   - The evaluator composes a material fill's Height as above. The plugged inputs are stored in the reference (`ProceduralRef.input_sources`, written only when non-empty) and enter the signature.
2. **Refused before mutation** (structured `NotYetSupported`, naming the owner):
   - a mask output other than Height's output (the support check, `phase3.3_procedural-families item 2.7`);
   - a split source of a Substance resource on a template or User RGB channel (unchanged: split sources stay User L32F through `assets bind-snapshot`);
   - `set_parameters`, the `resolution` setter and `active_output` assignment on a material;
   - assigning a whole mapping, an unlisted output or a `mask_output` on a split source;
   - an image-input colour outside the working space, an anchor reference (`phase4.1_nodes-instances-anchors`), and any input or output name that is not listed.

   The material's `resolution` getter raises `UnsupportedProcedural`, because no default resolution is recorded. No exception is created or widened. P413-C's r2 needs an owner decision-032 exception or a reopen model; neither is assumed.
3. **Scope split.** These move to the new item 2.7 of `phase3.3_procedural-families`:
   - the masked Height of a mask output other than Height's (P413-C r2/r3);
   - the split template-channel stores (BaseColor and any non-User-L32F split channel of a Substance resource, P413-D);
   - the presets probe's r2;
   - the material's default resolution.
4. **Evidence.** `tests/python/test_material_source_replay.py` replays these goldens over the private capture project and compares them exactly, with the decision-112 trace, excluding only listed outputs with their reasons:
   - `source-substance-channels-material-only`;
   - the 8 unmasked P413-A state goldens (the split BaseColor fill's outputs and BaseColor export excluded);
   - `source-substance-masked-by-height` and `-masked-by-normal-swap` (r1, r2 and r3);
   - `source-substance-presets-inputs` r1, up to s88;
   - `source-substance-mapping-access` on its material steps.

   Capability entries become `supported` only where the trace shows them.

## Alternatives Considered

- **Implementing the masked Height with the r1 model.** Rejected: r2 and r3 differ, and decision 032 needs the owner's approval in `parity/exceptions.json`.
- **Deriving the split BaseColor from the RGB32F view.** Rejected: no float32 sRGB decode or 8-bit store of the view reproduces the 7 recorded values.
- **Waiting for the masked and split fits before implementing anything.** Rejected under the owner's throughput rule: the unmasked material scope is exact now.

## Consequences

- `phase3.2_source-substance-presets-inputs` item 2.4 closes on the narrowed scope, and items 3.1 and 4.1 are judged on it.
- `phase3.3_procedural-families` item 2.7 owns the refused states, the presets probe's r2 and the default resolution.
