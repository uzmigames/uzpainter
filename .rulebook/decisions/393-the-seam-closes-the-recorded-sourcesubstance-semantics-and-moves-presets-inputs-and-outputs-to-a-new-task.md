# 393. The seam closes on the recorded SourceSubstance semantics and moves presets, image inputs and output mapping to a new task

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase3.1_proc-backend-seam, phase3.2_source-substance-presets-inputs, phase3.3_procedural-families

## Context

The owner wants in-flight tasks finished (2026-11-02). Each clause of `phase3.1_proc-backend-seam` items 2.6, 3.2 and 1.1 was checked against the evidence in the task notes, the decisions and the admitted manifests.

Item 2.6 covers the `SourceSubstance` semantics of `05-procedural-content.md` §7. These clauses have evidence:

| Clause | Evidence |
| --- | --- |
| `get_parameters`, `set_parameters` | Exact, traced compared replay of both recordings of three probes, 138 operations (decisions 112, 361) |
| Booleans as int | Booleans probe fill steps exact; Painter's refusal text equal |
| Unservable value refuses before mutation | Authored facade test, revision unchanged (`test_pyapi_substance_sources.py`). This is authored, not recorded, evidence. |
| `get_properties`, `get_preset_list`, `image_inputs` (list), `image_outputs`, `active_output`, `resource_id` | Same traced replay; capability entries supported |
| `resolution`: ResolutionOverride constraints | 46 readbacks equal both recordings |
| `resolution`: Filter restriction | Steps 19-24 equal both recordings (12/12) |
| `resolution`: Auto follows the texture set | Native `RequestFor` rule |
| Filter source getters | Steps 16-18 equal both recordings (6/6; decision 392, item 2.6j) |
| Mesh maps bound by usage, loud failure on a missing or invalid map | Native `BindMeshMaps` (decision 329); its loud-failure test is ticked in `phase3.2_proc-generator-families` 3.2 |

These clauses have no implementation and no recording, and stay release-gap in the capability manifest:
- `apply_preset`;
- `get_source`, `set_source`, `reset_source` and `remove_source` on image inputs (bitmap, colour, anchor);
- `output_mapping`;
- `mask_output`.

Every recorded source has zero presets, zero image inputs and one output. Implementing them needs three things:
- recorder operations, in files owned by another front while a pinned recording batch runs;
- a two-recording probe on an asset that has presets, image inputs and several outputs;
- a native extension of the snapshot capture domain, which today refuses presets, image inputs and multiple outputs.

Under the clean-room rule, none of this can be guessed.

Item 3.2 names four goldens: set->get readback, booleans as int, ResolutionOverride errors and the Filter restriction. All four are exact against both recordings. They were re-run on 2026-11-02 at 91c892a1: 11 passed, none skipped. The private strict Filter replay passed the same day.

Item 1.1 names `phase0.6_procedural-feasibility`, which is archived, and `phase2.10_pilot-tunic-recovery`, which is open on the Tunic's own fixture, rebuild and Tier 1 parity. None of this task's deliverables reads the Tunic's inputs or parity. Decisions 326 and 344 set the precedent for this kind of prerequisite split.

The four 9router models (gpt-6-astra, gpt-6.1-sol, grok-4.6, kimi-k3) gave GO on the split. Their conditions: name the moved clauses, keep them release-gap, keep the authored/recorded distinction, cite the mesh-map evidence, and make the gate wait on the new task.

## Decision

1. **Item 2.6 is checked as a recorded scope split.** Its note lists the evidenced clauses above. It names `apply_preset`, the image-input `get_source`/`set_source`/`reset_source`/`remove_source`, `output_mapping` and `mask_output` as moved. Nothing claims they are done.
2. **The moved clauses belong to `phase3.2_source-substance-presets-inputs`.** That task's prerequisite is this task. It owns the recorder operations, the recording, the capture-domain extension and the traced replay. The capability entries of the moved methods stay release-gap until that replay.
3. **The parent gate waits.** `phase3.3_procedural-families` lists the new task as a mandatory child, so §7 is complete only when that task is accepted.
4. **Item 3.2 is checked on its own evidence.**
5. **Item 1.1 is checked as a recorded prerequisite split.** The note names `phase2.10_pilot-tunic-recovery` as not accepted. Nothing claims it is.

## Consequences

`phase3.2_proc-snapshot-backend` 1.1 and the new task can proceed once this task's acceptance holds. If preset or input work later changes a shared component, the fix lands in the new task, not by reopening this one.
