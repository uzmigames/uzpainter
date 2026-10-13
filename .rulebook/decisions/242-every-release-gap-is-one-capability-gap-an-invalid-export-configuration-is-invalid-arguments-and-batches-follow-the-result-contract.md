# 242. Every release gap is one `capability_gap`, an invalid export configuration is `invalid_arguments`, and batches follow the result contract

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.5_mcp-transport-registry, phase2.6_mcp-typed-tool-families, phase2.3_supervisor-jobs, phase2.2_preview-capture

## Context

The practical end-to-end run (`parity/reports/phase2/practical-e2e.md`) drove UzPainter over MCP with the official SDK. It found four contract bugs in the MCP layer:

- **B4.** Release gaps came back under three codes. The registry's gate gave `capability_gap {tool, operations}`. The worker's typed tools and the export's own refusals gave `capability_gap {tool, type, reason}`. The evaluator's `NotYetSupported` (an OCIO bitmap sampling Session O does not record) reaches the worker's own tools as an API error of class `NotYetSupported`. It was `call_failed` in `export`, `capture`, `material_views` and `region_stats`, and `request_failed` in `evaluate_channel`, which gave evaluator failures the render layer's generic code instead of their API class (decision 082). `capture painter_iray` was `call_failed {type: PathTracerUnavailable}` (decision 148), although `PathTracerUnavailable` is a `NotYetSupported`.
- **B6.** `diffusion`, `color` or `transparent` padding with no `dilationDistance` failed `call_failed {type: RuntimeError}`. The plan compiler throws `core::ValueError`, and the worker's catch-all labels any other exception `RuntimeError`.
- **B11.** `capture channel:<name>` took only the export's documentMap name (`specularroughness`). `evaluate_channel` and `source_set` take ChannelType names (`SpecularRoughness`). `channel:SpecularRoughness` failed with "the documentMap spelling is not recorded (decision 085)", a `NotYetSupported` that B4's fix would have turned into a release gap.
- **B15.** `job_status` and `job_list` of a succeeded long job read `progress: 0.0`. The worker reports no event when a job ends, and the ledger row never took the terminal receipt's `progress: 1.0`, which `job_result` showed. `batch`'s reply had no receipt, no `revision` and no change lists, unlike every other reply (decision 158). `project_create` with no project open read a null `revision` beside `committed_revision` 1, although its precondition is resolved to 0.

The model panel was consulted in one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 One `capability_gap {tool, type, reason, operations}` from every layer; `painter_iray` included | AGREE | AGREE | AGREE |
| C2 `evaluate_channel` gives evaluator failures their API class | AGREE | AGREE | AGREE |
| C3 An invalid export configuration is `invalid_arguments`, decided by the plan, not by the JSON Schema | PARTLY | AGREE | AGREE |
| C4 `channel:<name>` takes ChannelType names and keeps the documentMap names | PARTLY | AGREE | AGREE |
| C5 The ledger takes the terminal receipt's progress and message | AGREE | AGREE | AGREE |
| C6 `batch` carries the result contract | PARTLY | PARTLY | AGREE |
| C7 A mutation with no project open is admitted on revision 0 | AGREE | AGREE | AGREE |

Refinements adopted:

- C3: translate only the configuration's own failures, before anything can be written (GPT, Kimi). A `core::ValueError` thrown later by the job, such as a stored mesh whose bytes no longer match their hash, is not the client's argument. So the worker compiles and checks the plan before the job starts, and only that step's `ValueError` becomes `invalid_arguments`.
- C4: a known channel always has a recorded documentMap name (the lower-cased member, `ambientOcclusion` for AO, `baseColor` for BaseColor), so a valid channel type is never refused as an invalid name or a release gap (GPT).
- C6: `revision` is the revision the batch's first call was admitted on, so a batch that starts with `project_create` reads 0, as C7 gives (Kimi). The receipt names the project the worker holds afterwards, as every receipt does (Kimi). The change lists gather only the calls on that project, so ids of two projects are never merged (GPT).

Refinements not adopted:

- GPT's classification by inheritance rather than by class name. The worker receives the API class as a name. `IsGapClass` lists the whole `NotYetSupported` subtree of `uzpainter.exception` (`src/python/errors.cpp`): `NotYetSupported`, `UnsupportedProcedural`, `ReleaseGap` and `PathTracerUnavailable`.
- Kimi's contract-version bump in `capabilities` and a follow-up giving `evaluate_channel`'s `ValueError` `invalid_arguments`. Neither is part of these fixes. The coordinator's changelog entry lists the observable changes.

## Decision

1. **Release gaps (B4; supersedes decision 158 §4's `{tool, operations}` and decision 148's `call_failed` for `painter_iray`).** Every release-gap refusal reaches the client as `capability_gap` with exactly `{tool, type, reason, operations}`, whichever layer raises it:
   - The registry's gate, for a tool-level or argument-value-level gap: `type: "NotYetSupported"` (the API's release-gap class), `reason` naming each gap operation with its manifest notes, `operations` the gap operations as before.
   - The worker (`Worker::Execute`, the one translation point): the native `core::NotYetSupported`, and an API error of class `NotYetSupported`, `UnsupportedProcedural`, `ReleaseGap` or `PathTracerUnavailable` from any worker tool, including `export`, `capture`, the diagnostics and `evaluate_channel`, and a failed transaction whose class is one of them. `type` is the class, `reason` the message, and `operations` the gap family's declared operations, or `[]` when the native code refused the call. `tools.h` `GapError`.
   - `UnsupportedInUzPainter` (decision 038) is not a release gap and stays `call_failed`.
2. **`evaluate_channel` (B4).** An evaluator failure carries its API class, as the export's, the capture's and the diagnostics' do: a release gap is `capability_gap`, any other class `call_failed {type}`. Device failures keep their render codes.
3. **Invalid export configuration (B6).** Before the job starts, `export` compiles and checks the plan of its configuration (`Worker::Export` `CheckConfiguration`). A `core::ValueError` of that step is `invalid_arguments {type: "ValueError"}`, for an export, a dry run and the `padding`, `file_format`, `bit_depth` and `size_log2` overrides alike. Nothing is written, and no job runs. A release gap the plan meets is `capability_gap` at the same point. The JSON Schema does not check it. A map's parameters resolve from the preset map and every matching rule in order, so "a rule that sets `diffusion` must set `dilationDistance`" would refuse valid configurations. The supervisor also cannot read the shipped presets. No default distance is invented, because Painter's documentation requires one.
4. **Capture channels (B11).** `channel:<name>` takes a ChannelType name exactly as `evaluate_channel` and `source_set` take it, or the export's documentMap name of a channel in any case (`specularroughness`, the old form). Its source is the documentMap the export records for the channel (`exporter::DocumentMapName`). Any other name raises `ValueError` "names no channel", naming both forms. A channel the stack lacks raises "has no channel <type>". The Python API's `render.capture` and the MCP tool share the parser.
5. **Result contract (B15, decision 158).**
   - A long job's ledger row takes its terminal receipt's `progress` and `message` (1.0 on success; the progress reached on failure or cancel). An interrupted job, which has no receipt, keeps the progress it last reported.
   - `batch`'s reply carries `revision` (the revision its first call was admitted on), `committed_revision`, `job_id: null`, the `changed`, `created`, `hidden`, `imported` and `skipped` lists of its calls on the project it ends on (deduplicated, first seen first), every call's `warnings`, and a receipt `{tool: batch, job_id: null, revision, project, project_uuid, texture_set: null, committed_revision}`. Each call's own body stays in `results`.
   - A mutating call admitted with no project open is admitted on revision 0, the precondition it is given, so `project_create` reads `revision 0 -> 1`. A read with no project open keeps `revision: null`.

## Alternatives Considered

- **A per-rule JSON Schema check for `dilationDistance`.** Rejected: it refuses valid configurations (C3).
- **Mapping every `core::ValueError` of the export job to `invalid_arguments`.** Rejected: later failures, such as a corrupt mesh, are not argument errors (panel refinement).
- **Mapping every worker `ValueError` to `invalid_arguments`.** Out of scope. Existing tests pin `call_failed` for the typed tools' contextual `ValueError`s.
- **`revision: 0` for every call with no project open.** Rejected: a read reads no revision. Null is "does not apply" (decision 158).

## Consequences

- A client detects every release gap by one code and one set of fields.
- Clients that keyed on `call_failed` with `PathTracerUnavailable`, on `request_failed` from `evaluate_channel`, or on `call_failed` for an invalid export configuration need the new codes.
- `channel:<name>` captures written before the change keep their meaning. `channel:basecolor` now records the source name `baseColor`.
- Tests: `tests/supervisor/test_registry.py` (`test_capability_gaps_name_the_tool_type_reason_and_operations`, `test_a_batch_reply_carries_the_result_contract`), `tests/supervisor/test_admission.py` (`test_a_mutation_with_no_project_open_is_admitted_on_revision_0`, `test_a_finished_long_job_reports_its_terminal_progress`), `tests/supervisor/test_typed_tools.py` (`test_every_release_gap_is_one_capability_gap`, `test_an_invalid_export_configuration_is_invalid_arguments`, `test_jobs_batches_and_creates_follow_the_result_contract`), `tests/supervisor/test_supervisor_gpu.py` (`test_an_evaluator_release_gap_is_a_capability_gap`), `tests/preview/test_preview_capture.py` (`test_channel_mode_takes_channel_types`, `test_worker_capture_tool`).
