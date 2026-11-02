# Proposal: phase3.2_source-substance-presets-inputs

## Why
Decision 393 closes `phase3.1_proc-backend-seam` item 2.6 on a recorded scope split. Some `SourceSubstance` semantics of `docs/architecture/05-procedural-content.md` §7 have no recording, so they move here: `apply_preset`, image-input source plugging (`get_source`/`set_source`/`reset_source`/`remove_source` with bitmap, colour and anchor sources), `output_mapping` and `mask_output`. Every recorded source has zero presets, zero image inputs and one output. The snapshot capture domain refuses presets, image inputs and multiple outputs. Under the clean-room rule, behaviour comes only from recorded observations of Painter.

## What Changes
- Recorder operations for the moved methods, using the documented public API only. They are coordinated with the recorder owners and never added while a pinned recording batch runs.
- A Tier 0 API probe, recorded twice (same session and after save/reopen) and admitted. It runs on a starter asset chosen at record time that has presets, image inputs and several outputs.
- A native extension of the snapshot capture domain to preset and image-input signatures and to multiple outputs, with exact-signature serving only (05 §4).
- Native and facade implementation of the moved methods from the recorded observations. A capability entry leaves release-gap only after a traced compared replay (decision 112).

## Dependencies
- Prerequisites: `phase3.1_proc-backend-seam`.
- Parent: `phase3.3_procedural-families`; its gate requires this task.

## Acceptance
The moved §7 methods equal both recordings and evaluate from project-private snapshots. No behaviour is guessed, and unrecorded cases keep refusing before mutation.

## Impact
- Affected specs: procedural
- Affected code: recorder probe operations, snapshot capture domain, `SourceSubstance` native module and facade
- Breaking change: NO
- User benefit: presets, image inputs and multi-output sources work as in Painter
