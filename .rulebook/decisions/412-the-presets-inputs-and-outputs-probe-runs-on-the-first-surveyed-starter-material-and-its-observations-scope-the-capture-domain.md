# 412. The presets, inputs and outputs probe runs on the first surveyed starter material, and its observations scope the capture domain

**Status**: accepted (item 5 applied by the coordinator, 2026-11-08)
**Date**: 2026-11-08
**Related Tasks**: phase3.2_source-substance-presets-inputs, phase3.3_procedural-families, phase4.1_nodes-instances-anchors

## Context

Decision 393 moved `apply_preset`, the image-input `get_source`/`set_source`/`reset_source`/`remove_source`, `output_mapping` and `mask_output` to `phase3.2_source-substance-presets-inputs`. Every earlier recording ran on a source with zero presets, zero image inputs and one output. Item 2.2 asks for a probe on a starter asset "chosen at record time" that has presets, image inputs and several outputs. Item 2.3 asks for a decision on the snapshot capture domain.

Measured facts (Painter `12.2.0+js-api.1.1.20`, Legacy, under the shared Painter lock, 2026-11-08):

- **Survey.** `tools/parity/recorder/substance_survey.py` (Painter side `painter_survey.py`) bound each result of the documented searches `s:starterassets u:substance` (953, as a fill's material source) and `s:starterassets u:procedural` (276, as a BaseColor source) on a throwaway plane project and read only the lengths of `get_preset_list()`, `image_inputs`, `image_outputs` and `output_mapping`. No call raised, except `output_mapping` on every split-mode procedural source (`EditionContextException`). Eight materials qualify. The first in URL order is `resource://starter_assets/inflate_shrinkwrap/inflate_shrinkwrap?version=a0b1718de23d379fb35250414e364bb8f8fbf50c.sbsar`: 3 presets, 1 image input, 2 outputs, 2 mapped channels. The survey file is private (oracle work root).
- **Probe `source-substance-presets-inputs`** (93 steps; r1 same session, r2 after save and reopen; admitted, golden record `64efeda399b2`). Observations, both recordings unless noted:
  - The material source's getters read; `active_output` raises `EditionContextException` ("Only valid in single channel context"). On the split source of the same resource, `output_mapping` and `mask_output` raise `EditionContextException` ("Only valid in multi channel context") and `active_output` reads.
  - `output_mapping` iterates channel keys to `str` output identifiers. The default maps two channels. Assigning back is a no-op, swapping exchanges the values, and assigning a channel outside the default mapping adds a key.
  - The default `mask_output` is an identifier that `image_outputs` does not list. Assigning it back raises `ValueError` ("Invalid output name ..."); assigning a listed output is read back.
  - `apply_preset` of the first preset changes `get_parameters` and returns None. A name the asset does not have raises `ValueError` ("Preset name '...' not found in preset list (case sensitive search)."), although the documentation says nothing is done.
  - `get_source` of the unplugged input raises `ValueError` (an alias URL scheme). `set_source` with a `Color` returns a `SourceUniformColor` in working space; with the imported bitmap, a `SourceBitmap` whose colour space reads `Data`. `reset_source` brings back the unplugged state. `remove_source` leaves a uniform black colour.
  - r2 only: `set_source` with the bitmap's `ResourceID` held from r1 raises `ValueError` ("resource not found"). The identifier names the closed project instance (decision 107 §4); the recorder cannot re-import in a probe step, so a bitmap plugged after reopen is not observed.
- **Probe `source-substance-input-anchor`** (13 steps, admitted, golden record `27c8faa1fdc7`): `set_source` with an anchor point returns a `SourceReference` (`KeepAlpha`, `BaseColor`); `reset_source` brings back the unplugged state.

## Decision

1. **Asset selection.** The probe names the first starter material, in URL order, whose source lists at least one preset, at least one image input and at least two outputs in the survey run in the same Painter session as the recording. Only the resource identity is authored. The preset, the input and the outputs are chosen in Painter by their index in the lists Painter returns; the only authored values are the `grey-a` fixture, one working-space colour and one missing preset name.
2. **Recorder operations** (item 2.1, `painter_probes.py`, documented symbols added to `documented_symbols.json`): `FillLayerNode.set_material_source` (`resource_url`), `SourceSubstance.apply_preset` (`preset_index` or `preset_name`), `get_source`/`set_source`/`reset_source`/`remove_source` (`input_index`; `color`, `resource_step` or `anchor_step`), and `output_mapping`/`mask_output` as getters or as edits (`roundtrip`: true, `swap` or `output_index`). Sources are selected with `material: true` for a fill's material source. An image input's source is serialised by class, with a `SourceReference` read through its documented getters.
3. **Capture domain** (item 2.3). The snapshot signature (05 §4) is extended only as these observations require; exact-signature serving stays the only rule:
   - **Multiple outputs.** A material fill source holds one reference with an explicit channel-to-output mapping and a mask output identifier. Each mapped channel is served by the snapshot whose signature has that output id; a channel whose output has no snapshot of the exact signature is unavailable. One capture records every listed output of the state.
   - **Presets.** No getter reports an applied preset, so the signature's `preset` names the preset whose application produced the captured state, and the captured state is reached by Painter's own `apply_preset` in the capture. UzPainter's `apply_preset` sets the parameters recorded after that application (a new metadata observation) and the `preset`; any later edit of a source with a preset refuses before mutation until a recording observes it. A missing name raises Painter's recorded `ValueError`.
   - **Image inputs.** The signature's `inputs` names each plugged input: a bitmap by the SHA-256 of its file bytes and its colour space, a uniform colour by its working-space value. An unplugged input is absent. A source with an anchor reference stays outside the domain.
   - The default `mask_output`, the unplugged `get_source` error and the refusals of each context are served from the recorded metadata of the snapshot of the current exact signature, as `/2` and `/3` serve presets and properties.
4. **Evidence.** The capability entries of the moved methods stay `release-gap` until the compared, traced replay of both recordings (decision 112) passes over a project-private capture of this asset.
5. **The anchor clause moves to `phase4.1_nodes-instances-anchors`** (applied 2026-11-08 by the coordinator, under the owner's rule to close through scope splits). Anchor reference sources are that task's scope (its item 2.4 covers `reference` sources in fills and in image inputs; anchor effects and reference sources are release gaps it owns) and are not implemented here. `set_source` of an image input with an anchor point, and every readback that depends on it, are owned by that task, with `source-substance-input-anchor` steps 8-13 as its recorded evidence. This task keeps that golden's steps 6 and 7 (`image_inputs` and the unplugged `get_source` error of a fresh material source), which do not depend on the anchor. Until that task implements reference sources, `set_source` with an anchor point keeps refusing before mutation.

## Alternatives Considered

- **Choosing the asset by name without a survey.** Rejected: the asset's lists would be assumed, not observed.
- **A selection step inside the golden.** Rejected: the snapshot capture needs the exact versioned URL before recording, and both goldens must name the same resource.
- **Serving a preset as plain parameters with no `preset` in the signature.** Rejected: nothing observed shows that a preset changes only the parameters `get_parameters` returns.
- **Treating the r2 "resource not found" as a recorder fault and re-recording.** Rejected: it is what Painter does with that identifier; a bitmap plugged after reopen needs a new probe with its own import.

## Consequences

- `phase3.2_source-substance-presets-inputs` items 2.1 and 2.2 are done; item 2.3 has its decision but no implementation. The native extension (signature inputs, preset field and metadata, multi-output material references, the bridge's capture of every output), the capture of this asset, the facade methods and the traced replay remain.
- `phase4.1_nodes-instances-anchors` owns the anchor-input clause and its recorded observation (`source-substance-input-anchor` steps 8-13), noted in its item 2.4.
