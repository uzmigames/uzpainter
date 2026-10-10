# Proposal: phase0.7_tier0-semantics-ui-cases

## Why
`phase0.6_tier0-semantics-goldens` recorded every `docs/architecture/04-layer-stack-and-compositing.md` §9 item that Painter 12.1.0's documented API can reach. Three cases remain that it cannot set:
- the second height→normal method, a project setting with no documented Python or JavaScript setter or getter;
- the height→normal strength, which has no documented setter;
- the group `PassThrough` blend mode: the python-doc lists `BlendingMode.PassThrough`, but the 12.1.0 runtime has no such member and a new group defaults to `Normal`.

The owner chose a follow-up child task for them (answer to q1 of `phase0.6_tier0-semantics-goldens`, 2026-10-10). Decision 029 allows an agent to set Painter settings that are reachable only in the UI through Windows UI automation. The agent must hold the Painter lock and record every UI-operated value in the operator-recorded settings sheet. PRD LAY-04, LAY-05, ARC-04.

## What Changes
- An operator step for texture goldens in the recorder (`tools/parity/recorder/`), like the Iray settings sheet (`parity/RECORDER.md` §4). Each UI-set value is named `<panel>/<setting>` with `applied_by: operator_settings_sheet`. How it was set and how it was verified is recorded privately as `operator_recorded_settings` and `settings_panel_evidence`. UI automation follows decision 029 and is a dev-only dependency.
- Goldens on the authored fixtures of `parity/fixtures/tier0-semantics/` (height ramps on the plane, sphere and bevelled cube):
  - height→normal with each project-setting method;
  - a height→normal strength sweep (default plus at least three values) for each method;
  - a group in `PassThrough` mode, set through the UI, with and without masks on the group and on a child, on the same stack as the `group-masks` golden.
- Each golden is recorded at least twice (same session; after save/reopen) through `export_project_textures` at 16 bit or float and admitted into the private store. Only hashes, authored inputs, instruction sequences, settings-sheet names and values, and software identities enter the public manifests under `parity/manifests/tier0/semantics-ui/`.

## Dependencies
- Prerequisite: `phase0.6_tier0-semantics-goldens` (fixtures, corpus generator, recorder vocabulary).
- This task is not a prerequisite of `phase0.8_tier0-goldens` or `phase0.10_gate-g0` (owner answer, 2026-10-10). Until it closes, the three cases are release gaps in the capability manifest.

## Acceptance
Both height→normal methods with a strength sweep, and the group `PassThrough` mode with masks, have goldens recorded at least twice. Every UI-set value is in the settings sheet and verified by readback or panel evidence. Blobs are private and hashes are public, and `uzpainter parity verify` and the repository guard pass.

## Impact
- Affected specs: tier0
- Affected code: `tools/parity/recorder/` (operator step for texture goldens), `tools/parity/tier0_semantics/`, `parity/manifests/tier0/semantics-ui/`
- Breaking change: NO
- User benefit: the last three Tier 0 compositing cases are observed on Painter's own outputs
