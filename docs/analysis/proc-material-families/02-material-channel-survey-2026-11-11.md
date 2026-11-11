# Material channel survey, 2026-11-11 (phase3.3_procedural-families item 2.16)

Painter `12.2.0+js-api.1.1.20`, Legacy colour management, one Painter session under the Assets3D Painter lock (seq 2382 to 2383). `python -m tools.parity.recorder.material_channel_survey --launch` ran it; `python -m tools.parity.fit.material_channel_survey` prints the counts below. This is a diagnostic survey, not an admitted golden. The survey and its exports are private (`%LOCALAPPDATA%/UzPainter/oracle-work/material-channel-survey/20261111T151331/`, `survey.json` SHA-256 `d4e4d376…`). No Painter pixel or parameter value is published here.

**Outcome: nothing is served yet, and the support check still refuses a material fill with an active channel other than Height (decision 432 §4).** The survey settles what step 1's codec must hold, and finds a candidate composition for every channel the two default fills activate. Each candidate misses no texel of this survey. Three things are still missing before any refusal can be lifted: the native implementation, a capture of each material through `assets snapshot` (which needs the codec first), and a golden recorded in that same session (decision 431).

## 1. Colour parameters (step 1)

- `SourceSubstance.get_parameters()` returns each colour parameter (`fabric_color`; `color`, `hand_tipped_color`) as a `colormanagement.Color`.
- On the material source, the colour is in `GenericColorSpace.sRGB`. On a split User0 source of the same resource, it is in `GenericColorSpace.Raw`. Both read the same `value` triple, so the colour space a source reports depends on the source's context.
- `set_parameters` takes only a `Color`. A list or a tuple raises `TypeError` ("expected value of type <Color>").
- A colour set in sRGB or Raw reads back in sRGB with the given `value`. A Working colour reads back in sRGB with its encoded value, and its `working` getter is not the triple that was set (`0.2499999850988388` for `0.25`). The codec therefore records what Painter reads back, never the requested triple.
- On leather grain, setting `color` also changed another parameter's readback (`others_unchanged` false). Felt's `fabric_color` did not. The capture already reads back the full effective state, so this needs no special case. The other parameter was not identified.

Consequence for the codec: a colour parameter is a typed value `{colour space, value triple}`, compared by value. It is not a scalar, so the existing scalar signatures and metadata keep their bytes. Because the space depends on the source's context, the capture (split sources, Raw) and the material source (sRGB) read the same state with different spaces. The codec must name which context it records. The fill's state must then be matched through the `value` triple, not the space. Recording a split readback as the material's own parameters would be wrong.

## 2. Channel composition of the default material fills (step 3)

Layout: the authored plane at 128 px, OpenGL. First the material fill alone, exported per channel as OpenEXR 32f with passthrough padding. Then, in the same Painter instance, the paired split User0 L32F / User1 RGB32F source of the same resource at every output (the snapshot capture's layout). Painter's defaults for the material fill are BilinearHQ filtering, Repeat wrapping, Auto resolution (read as 1024), UV Factors 1, opacity 1, Normal blending, Height LinearDodge and Normal NormalMapDetail. The template formats are BaseColor sRGB8, BaseMetalness and SpecularRoughness L8, Height L16F and Normal RGB16F.

x is the L32F view and (r, g, b) the RGB32F view of the output that `output_mapping` gives the channel. tz16 is binary16 rounding toward zero.

| Material | Channel | Candidate | Misses |
|---|---|---|---|
| felt | Height | tz16(2x - 1) (decision 416) | 0 of 16 384 |
| felt, leather grain | BaseColor | stored code round(255 v) of each view component, no transfer; one strictly increasing export per code | 0 of 49 152 components each |
| felt, leather grain | SpecularRoughness | ((x16 >> 4) 255 + 2047) >> 12, with x16 = 65535 x; export float32(code / 255) | 0 of 16 384 each (round(255 x) misses 387 and 302) |
| felt, leather grain | BaseMetalness | the same rule (a constant output) | 0 of 16 384 each |
| leather grain | Normal | (tz16 r, tz16(1 - g), tz16 b) | 0 of 16 384 per component |

- BaseColor's views hold binary16 values. Painter stores each one as the sRGB8 code round(255 v), with no decode and encode.
  - P413-D's split BaseColor does not follow this rule: two of its seven values give another code. Its views are 16-bit codes, not binary16 values.
  - The rule is therefore limited to binary16 views, and the export per code has not yet been compared with the evaluator's sRGB8 export.
- The L8 rule was chosen on these same texels: the shift of 4 and the constant 2047 are the only values that miss nothing (2048 misses 2). So it is a fit, not a held-out result.
  - The 16-bit view is truncated to 12 bits before the 8-bit store. This may be the recording GPU's filtered fetch of a UNORM16 texture under BilinearHQ, but nothing here separates that cause.
  - A held-out check needs more outputs: other materials, or these materials at other parameters.
- Normal flips green, and its other components are the view rounded toward zero. Only the empty stack is recorded, where NormalMapDetail over the flat base gives the material normal itself. Detail blending over another normal is not recorded.
- Every candidate is measured on one material fill over the empty stack of a new project, at 128 px on the plane. Nothing is recorded below the fill, at another resolution, on another mesh, under a mask or at another opacity.

## 3. Physical size (step 4)

- `MaterialPhysicalSize` cannot be set through `UVProjectionParams` with a `scale`. Painter raises `ValueError` ("Cannot set UV transformation size when using Material Physical size UV transformation scale mode"), and the survey's MaterialPhysicalSize export is therefore the Factors 2 state before it. How Painter sets that mode is not recorded.
- `CustomPhysicalSize` at [1, 1] and at [100, 100] gives exports that differ from Factors 1 and from each other. No size readback relates them to the mesh, and they are magnified through BilinearHQ, which the evaluator does not model.
- Both modes stay refused. Separating recording: the plane and a mesh of known size, each under `MaterialPhysicalSize` set without a scale and under `CustomPhysicalSize` at several sizes, with Nearest filtering. Each case would be exported beside the Factors scale the rule predicts, and the material's physical-size property read back.

## 4. Order of the remaining work

1. **Codec.** A typed colour value in the signature, the `/3` typed parameters and the `ProceduralRef` parameters (versioned, so scalar-only bytes stay unchanged), in the bridge's `scalar_parameters` and `described`, and in the facade's `get_parameters`/`set_parameters` (`Color` only).
2. **Destination capture.** A multi-output request with `usage` on the destination's own mesh and resolution (decision 429 §3 has `PROCEDURAL` and `GENERATOR` only).
3. **Same-session golden.** Capture felt and leather grain, then record in that same session a Tier 0 golden of each default material fill's channel exports, r1 and r2 (decision 431). It must also hold a held-out output for the L8 rule.
4. **Evaluator.** Implement §2's rules on the CPU and GPU lanes. Admit a material fill's BaseColor, BaseMetalness, SpecularRoughness and Normal only in the recorded configuration. Test the served snapshots byte-equal to that golden.

Burlap (`weave_2`) as a mask source stays refused under decision 431's seeded-source finding (item 2.15). Leather pattern (`grunge_leather_damaged`) as a split BaseColor/Height source stays refused under item 2.7.
