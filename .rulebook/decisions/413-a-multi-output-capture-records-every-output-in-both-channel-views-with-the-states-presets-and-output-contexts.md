# 413. A multi-output capture records every output in both channel views with the state's presets and output contexts, and material-channel consumption waits on its own recording

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase3.2_source-substance-presets-inputs, phase3.3_procedural-families

## Context

Decision 412 §3 sets the capture domain of `phase3.2_source-substance-presets-inputs` item 2.3: one snapshot per output, `preset` in the signature reached by Painter's own `apply_preset`, image inputs by bitmap hash and colour space or working colour, and the default `mask_output`, the unplugged `get_source` error and each context's refusals served from recorded metadata. It does not say how a capture reaches a state, which channel view stores an output that is not grey, or where the preset parameters and the contexts are observed.

Measured facts:

- The existing capture (`python/uzpainter_snapshot/`) exports one split source through two paired channels, User0 L32F and User1 RGB32F, and requires every RGB component to equal the L32F value. The recorded `inflate_shrinkwrap` lists two outputs, and one of them is a normal map, which is not grey, so that rule cannot hold for it.
- `apply_preset` changes `get_parameters` (s29-s30), and in recording 2 it is applied again on a source that already holds that preset and a removed input. No getter reports a preset.
- After `remove_source`, `get_source` reads a `SourceUniformColor` (s63).
- No admitted golden exports a channel of a material fill, and none records how Painter composes a material output into BaseColor, Height or Normal, or how a `mask_output` acts.

The capture this decision specifies was run on 2026-11-08 (Painter `12.2.0+js-api.1.1.20`, Legacy, under the shared Painter lock, seq 2340/2341), on UzPainter's own plane project, for the five states the probe reaches: the defaults, the first preset, and that preset with the first image input set to the authored colour, to `grey-a`, and removed. It added 20 snapshots (5 states x 2 outputs x 2 views), each verified after save and reopen. It observed three things that correct what decision 412 assumed:

- **Unplugged input.** `get_source` of an unplugged input does not raise. It returns a `SourceBitmap` whose `resource_id` raises the alias-scheme `ValueError`, and whose colour space reads. The probe's recorder serialised that bitmap, so its step records the same `ValueError`.
- **Context of `output_mapping`.** On the capture's split fill, which activates User0 and User1, `output_mapping` returns an `OutputMapping` and `mask_output` raises `EditionContextException`. On the probe's split fill, which activates BaseColor only, both raise (s25-s26). The refusal therefore depends on more than split versus material mode.
- **Active channels of a material fill.** After `set_material_source` and the state's edits, the material fill activates Height only, while its default `output_mapping` maps Height and Normal.

## Decision

1. **Request.** `assets snapshot` keeps the two-field request unchanged. A request of exactly `resource`, `parameters`, `preset` and `inputs` is a multi-output capture of a Substance resource (a material need not carry the `PROCEDURAL` usage). The parameters are set, then the preset (null, or a name; it excludes parameter overrides) is applied by Painter's `apply_preset`, then each named input is plugged with a working-space `Color`, a bitmap file imported as a project texture (staged privately), or Painter's own `remove_source`. Unnamed inputs must read back unplugged.
2. **Every output, both views.** Each listed output is selected in turn (`active_output` on both paired sources) and exported twice through User0 L32F and User1 RGB32F. Each output gives two snapshots, one per channel view (1 and 3 channels), each the exact float32 export of that channel; repeats must be bit-identical. Neither view is derived from the other, so no conversion between an RGB output and a mono channel is inferred.
3. **Signature.** `preset` is the requested preset. `inputs` holds each plugged input as Painter reads it back, `{"bitmap_sha256", "colour_space"}` or `{"working_colour": [r, g, b]}` (numbers by value). A requested colour must read back unchanged, and a bitmap must read back as the staged file's import. An unplugged input is absent. A removed input and a uniform colour of the same working value have one signature, and the project keeps the first one recorded (snapshots are immutable).
4. **Metadata `/4`.** Beside the `/2` and `/3` members (all required in a multi-output capture):
   - `preset_parameters`: each preset applied by Painter to the captured state, with the parameters it gave. The captured parameters are then set back, and the full readback must equal the captured one.
   - `input_sources`: each input's source as read back. It is what `get_source` raised, a uniform colour's working value, a plugged bitmap by file hash and colour space, or an unplugged input's bitmap with its raised `resource_id` and its colour space.
   - `contexts`: the outcomes of `output_mapping` and `mask_output` on the capture's split sources, and a material fill of the same resource and state (inserted, read and deleted again): its `output_mapping`, `mask_output`, active channels and `active_output` outcome. The material source must read the same parameters and input sources as the split ones.
   
   The split outcomes belong to the capture's two-channel split fill only and are never served for another split configuration.
5. **Consumption stays unrecorded.** This capture records source outputs and observations only. Serving a material output to a template channel (BaseColor, Height, Normal), a `mask_output`, or a split source on a non-User channel needs Painter's own channel exports of those configurations. A material fill activates Height, so even the probe's default material fill consumes an output. Until recording **P413-A** is admitted and fitted, the evaluator keeps refusing these states before mutation. Until recording **P413-B** is admitted, the split-context refusals of `output_mapping` and `mask_output` are not generalised beyond the configurations recorded.

## Recordings this decision names (not recorded)

- **P413-A, material and split channel exports.** For each state the `source-substance-presets-inputs` replay reaches: Painter's BaseColor, Height and Normal exports (float, passthrough padding) of the material fill with its recorded mapping, active channels and mask output, and of the split BaseColor source. They are captured beside the source snapshots, so that the consumption of each view by each channel can be fitted exactly or refused.
- **P413-B, split-context refusals.** `output_mapping` and `mask_output` read on split fills that activate one channel and several channels, of User and template types, in both recordings, to find which configurations raise.

## Alternatives Considered

- **One RGB view per output.** Rejected: a mono channel's view of an RGB output would then be inferred.
- **Reaching a preset state by setting its parameters.** Rejected by decision 412 §3: the captured state is Painter's `apply_preset`.
- **Hard-coding the context refusals.** Rejected: the capture shows that they depend on the fill's configuration.
- **Evaluating material channels from the source views now.** Rejected: no golden records how Painter composes them, so it would be a guess.

## Consequences

- Item 2.3 is implemented:
  - the bridge;
  - the native ingest (`ReadMultiOutputCapture`, `ReceiptMultiOutputMetadata`);
  - the signature's plugged inputs and the `/4` codec;
  - authored tests (`tests/procedural/test_snapshot_bridge.py`, `uzp-procedural-tests snapshot-multi-output`).
- The capture procedure is `tests/python/capture_source_substance_presets.py`, run explicitly on the owner's machine. Its project is a private derived artifact in the oracle store: `source-substance-presets-inputs-project`, SHA-256 `b34c843e68c1823aad086df139daa279ce23ce4d3a28859915ed2c4a2e7122ed`, 237 568 bytes.
- Items 2.4 and 3.1 build on these snapshots. The probe's material fill activates Height and its split fill activates BaseColor, so no exact implementation can commit either fill until P413-A is fitted. The split-context refusals also wait on P413-B.
