# 106. The native API compares its own Tier 0 readbacks and hands the facade-shaped ones to phase1.20

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.24_python-api-facade, phase1.18_export-engine

## Context

Item 3.2 of phase1.19 asks that "Tier 0 API-probe readbacks owned by the native API" be compared exactly with the `phase0.6_tier0-api-probes` goldens in a local run (decision 028).

The goldens record what Painter's documented API returns:

- The probes `active-channel-reset`, `active-channel-reset-superset`, `active-channel-order-control`, `set-source-none-multichannel`, `mask-stack` and `insert-positions` record facade quirks: the active-channel reset, the `None` channel rules, `EditionContextException`, and the insertion errors. Phase1.20 item 3.1 compares them. The native API keeps sources when active channels change (LAY-01), so these probes are not its readbacks.
- `fill-layer-readback` and `textureset-project-readback` hold readbacks the native API can give directly:
  - the template's channels;
  - names, visibility and node types;
  - active channels and the source mode;
  - blending modes and opacities;
  - the bitmap colour space;
  - the projection mode and UV parameters;
  - the stack structure and uid identity;
  - resolutions and mesh-map bindings;
  - `needs_saving`, the file name and the project name.
- The same two probes also hold readbacks that need facade rules:
  - uniform colours, read back converted to the working space;
  - `list_available_color_spaces`;
  - Painter's own resource ids (context and version are Painter-internal);
  - the `.spp` file name.
- Item 1.1 lists `phase1.18_export-engine` as a prerequisite. Phase1.18 is still open in another worktree, but every piece the native export uses is on main: plan, writers, publication and receipts.
- Item 4.1 asks that the results be attached to `phase1.24_python-api-facade`.

The model panel could not be consulted: the 9router proxy refused every connection.

## Decision

1. **Native-owned readbacks.** `tests/python/test_pyapi_tier0.py` replays the state steps of `fill-layer-readback` and `textureset-project-readback` through the native API. It compares every native-owned readback exactly with both recordings (`same_session`, `after_save_reopen`) of the private record.
   - Result on the owner's machine: 23 of 23 and 8 of 8 outputs per recording are equal.
   - One difference is structural: Painter's empty "Layer 1" paint layer, excluded under decision 105 and owned by `phase4.1_nodes-paint-layers` item 2.8.
   - Where no private store exists the test skips, naming why.
2. **Facade-shaped readbacks.** The readbacks that need a facade rule are a scope split to `phase1.20_pyapi-facade` item 3.7. They are not claimed by phase1.19.
3. **Prerequisite.** Item 1.1 stays unchecked: `phase1.18_export-engine` has not been accepted. The native export is built on its children's code on main and is exercised end to end by `tests/python/test_pyapi_native.py`. When phase1.18 is accepted, item 1.1 is checked with no change to this task's code.
4. **Results for phase1.24.** The tests run in the hosted lane: `python -m pytest` builds `uzp-pyapi-tests.exe` with the pinned Zig and uses no GPU. The Tier 0 comparison runs only on the owner's machine. The local run report `parity/reports/phase1/pyapi-native-module.md` is the evidence attached to `phase1.24_python-api-facade`.

## Consequences

`phase1.20_pyapi-facade` item 3.7 compares the facade-shaped readbacks. `phase4.1_nodes-paint-layers` item 2.8 adds the default paint layer and drops its exclusion from the Tier 0 test.
