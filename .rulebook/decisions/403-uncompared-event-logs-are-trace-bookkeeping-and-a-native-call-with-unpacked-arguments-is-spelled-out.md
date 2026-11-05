# 403. Uncompared event logs are trace bookkeeping, and a native call with unpacked arguments is spelled out

**Status**: accepted
**Date**: 2026-11-05
**Related Tasks**: phase1.22_pyapi-cli-capabilities, phase1.24_python-api-facade

## Context

Gate G1 (`parity/reports/phase1/gate-g1.md` §8.3) left 51 Tier 0 replays failing in `check_trace`: their entries in `tools/capabilities/tier0-trace.json` predate the trace's instance-field reads (`7604e4e1`) and native accessor calls (`ae45b4bc`); `da88d8ba` had regenerated only some replays. Before the decision-112 regeneration, each changed symbol was audited.

1. **Added fields.** `BusyStatusChanged.busy`, `ProjectAboutToSave.file_path` and the export, engine, texture-state and shelf event fields are read by the recorder's event callback (`painter_probes.py` `event_callback`, `strong_callback`), whose log the observed and lifecycle replays compare step by step. `UVProjectionParams.uv_transformation` is read by the serialisation of `get_projection_parameters()` (inserted-node defaults, projection readbacks) and by the facade's `projection_to_native`, all compared. `uzpainter.textureset.Stack.get_channel`, `has_channel` and `Channel.format` are the facade's default colour space of a bitmap source (`channel_format_name`, `4ff6e769`), which the compared `set_source`/`get_source` readbacks hold.
2. **Not compared.** The facade replays of the R10, sRGB-decode and fill-channel-defaults probes leave out the `/events` and `/states` outputs (`test_pyapi_facade_tier0.py`), yet their `Dispatcher.connect` step connects the same callback. Its reads (`busy`, and `project.is_busy` and `is_in_edition_state` through `project_state()`) were credited to whichever step was marked when the dispatcher thread delivered them.
3. **Gone `set_source`.** `uzpainter.layerstack.FillLayerNode.set_source` and `FillEffectNode.set_source` stopped being credited when `5c3dd0e6` changed the facade's call to `native.set_source(*args)`. CPython 3.13 emits CALL but no C_RETURN for a bound method called through CALL_FUNCTION_EX (measured: `m(2)` reports C_RETURN, `m(*args)` does not). The call ran; the trace could not see it. `da88d8ba` had already dropped it from four replays for this reason.

## Decision

1. **Uncompared event logs are bookkeeping.** `capability_trace.bookkeeping(function, *args)` runs a function with its thread's calls attributed to `BOOKKEEPING`. The facade replays of `UNCOMPARED_EVENTS` (R10, decode and defaults probes) wrap the recorder's event callbacks with it. Bookkeeping is per thread, also for `BOOKKEEPING_CODE` (`own_project_identity`): calls the dispatcher thread makes meanwhile keep the marked output, instead of being swapped into bookkeeping.
2. **A native call whose return is evidence is spelled out.** The facade calls `native.set_source(channeltype, value, tag)` with the bitmap tag or None. The trace's docstring names the CALL_FUNCTION_EX blind spot.
3. **Regeneration.** The 51 replays and the three whose `set_source` credit `da88d8ba` had dropped (`facade/mask-stack`, `facade/export-ocio-encode`, `facade/export-ocio-encode-legacy`) were regenerated with `UZP_UPDATE_TIER0_TRACE=1`. The `any` entries follow the trace: 11 event fields promoted from `release-gap` to `supported` (their reads return Painter's values in compared logs, as `da88d8ba` found for the reload and shelf fields), evidence widened for `busy`, `uv_transformation`, the shelf fields, `set_source` and the `textureset` reads, and narrowed for `project.is_busy` and `is_in_edition_state` (9 goldens each, both still `supported` through other replays). No entry is downgraded.

## Alternatives Considered

- **Crediting the uncompared callbacks.** Rejected: decision 112 counts compared outputs only, and the decode and defaults goldens would cite fields no comparison holds.
- **Tracing CALL_FUNCTION_EX from the CALL event.** Rejected: without C_RETURN or C_RAISE the trace cannot tell a successful call from a raised one, and decision 112 counts only the former.
- **Accepting the gone `set_source`.** Rejected: the replay does exercise it, so its evidence would be wrong.

## Consequences

- A replay that leaves an output out while its harness keeps producing it wraps the producer with `bookkeeping`.
- `facade-events/phase1-reload-mesh` was not regenerated: it fails earlier, on the missing `LayerStacksModelDataChanged` events (gate-g1 §8.3).
