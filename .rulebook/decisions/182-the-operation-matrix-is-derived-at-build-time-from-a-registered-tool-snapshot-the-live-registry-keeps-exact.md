# 182. The operation matrix is derived at build time from a registered-tool snapshot that the live registry keeps exact

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.7_mcp-operation-matrix, phase2.6_mcp-typed-tool-families, phase2.8_mcp-server, phase5.2_parity-report-mcp-conformance

## Context

INT-02 and ARC-14 require a requirement-to-typed-operation matrix. It is generated with the capability manifest and published in `capabilities.json` and `uzpainter://capabilities` (11 §2). The build must fail on a missing row, a row naming an unregistered tool, or an `available` row without a conformance fixture id. The spec's scenario: in a build where mesh reload has no registered typed tool, its row is `capability gap`.

The generator (`tools/capabilities/generate_capabilities.py`) is a standard-library script. `zig build` runs it before `UzPainter.exe` is linked, and the hosted CPU lane runs it too. The tool registry is in C++: about 60 worker tools, each declaring its manifest operations and per-value `x-uzpainter-capability` maps (decision 164). The supervisor's 12 tools are in Python (decision 165). At run time the supervisor refuses a call with `capability_gap` when one of its operations is a release gap or missing from the manifest.

The model panel's votes (one round):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 The build reads a committed snapshot of the registered tools that a live test keeps exact; it does not run the executable or parse C++ | AGREE | AGREE | AGREE |
| C2 A row's status is derived from the tool, the argument values and the extra operations it names, against the manifest being generated (fail closed) | PARTLY | PARTLY | AGREE |
| C3 The generator fixes the list of required operations; fixture ids are pytest node ids checked at generation | PARTLY | AGREE | PARTLY |
| C4 One row per texture file format; future engine presets add their rows with their own tasks | PARTLY | AGREE | AGREE |

Refinements adopted:

- C1: the snapshot holds each tool's operations, contexts, per-value maps and opt-in option, not only the names. It also covers the HTTP-only lease tools (GPT).
- C2: a gap row names the task that owns it, or generation fails (Kimi). Value-specific gaps appear as their own rows (a paint layer, each 3D projection, the material source, a geometry mask, the UV-tile workflows), so an omitted argument value cannot hide a required gap (GPT). The other gated values stay visible in the `capabilities` tool's `value_gaps`.
- C3: a test collects every fixture id with pytest, beyond the generator's file-and-function check (GPT, Grok). Every row cites the requirements it serves from `docs/prd.md`, not only INT-02 or ARC-14 (GPT).
- C4: the preset path and the inline-configuration path of INT-02 are separate rows: `export.preset` and `export.config` (GPT).

## Decision

1. **Registered tools.**
   - `tools/capabilities/mcp-tools.json` lists every tool the build registers, one per line: `{name, served_by, opt_in, operations, values}`.
   - `served_by` is `worker` or `supervisor`. `opt_in` is the option that registers the tool: `--allow-python` for `run_python`, `--mcp-http` for the lease tools, otherwise null. `values` maps each JSON pointer of an `x-uzpainter-capability` property to its value map.
   - The Debug-only `--test-faults` tools and the `--preview` tool `preview_status` are left out.
   - `tests/supervisor/test_operation_matrix.py::test_the_registered_tools_are_the_snapshot` compares it with a real worker's `tools/list`, with and without `--allow-python`, and with `SUPERVISOR_TOOLS`. Any difference fails. `UZP_UPDATE_MCP_TOOLS=1` rewrites the file.
2. **Rows.**
   - `tools/capabilities/operation-matrix.json` holds the rows: `{operation, requirements, tool, arguments?, operations?, fixture, notes?}`.
   - `arguments` gives argument values by JSON pointer (for example `{"/kind": "paint"}`). `operations` names other manifest operations that the native tool checks itself, such as `export_project_textures` with `file-format:tiff` or `uzpainter.render.capture` with `mode:painter_iray`.
   - The required operations are `REQUIRED_OPERATIONS` in the generator: 25 INT-02 operations and 81 operations of the ARC-14 families of 11 §7, 106 in all. An operation leaves the list only together with those sections.
3. **Derived status.**
   - A row with no tool is `capability gap`. A row whose tool is `run_python` is `needs Python`, also a gap.
   - Otherwise the row is `capability gap` when one of its operations is a release gap or is missing from the manifest being generated. Its operations are the tool's own, those of the argument values it names, and its extra operations. Missing operations are reported with status `unlisted`.
   - `supported` and `pending-evidence` count as reachable, the same rule as the runtime gate.
   - Output row: `{operation, requirements, tool, fixture, status, gaps, notes}`, in the order of `REQUIRED_OPERATIONS`, as `operation_matrix` in `capabilities.json`. `uzpainter://capabilities` publishes it unchanged.
4. **Build check.** Generation fails, naming the row, on any of these:
   - a required operation without a row, or a row outside the list or repeated;
   - a requirement id that is not in `docs/prd.md`, or a row that does not cite the requirement that requires it;
   - a tool that is not in `mcp-tools.json`, or an argument value that its tool does not gate;
   - an `available` row without a fixture, or a fixture that is not `tests/<file>.py::test_<name>` defined in that file;
   - a gap row whose notes name no owner task.
5. **Fixtures.**
   - Every fixture is a test that runs with Python disabled.
   - Rows whose existing tests run with `--allow-python` get new Python-disabled fixtures in `tests/supervisor/test_operation_matrix.py`: an export with an inline configuration to OpenEXR, `isolate_layer`, and the display, shader and camera tools.
   - The fixture of the compare-mask and colour-selection rows found a mismatch. `effect_insert`'s value map names the facade inserts (`substance_painter.layerstack.insert_compare_mask_effect`, `supported` by Tier 0 readback). But the typed tool performs the native insert, `uzpainter.layerstack.insert_*_effect`, which is a release gap, and the evaluator's support check refuses it before mutation (phase4.1_nodes-mask-effects). Both rows list the native operation in `operations`, so they are gaps, and their fixture asserts the refusal. The value map itself is phase2.6's to correct: until then the `capabilities` tool shows those two values as available.
6. **Export targets.**
   - One row per texture file format of the export configuration. PNG and OpenEXR are available.
   - TGA, BMP, JPEG and DDS are gaps owned by phase3.2_unreal-ue56-packed-preset. The manifest has no entry for them, so they show as `unlisted`.
   - TIFF, PSD, WebP and JPEG 2000 are release gaps of 10 §3.
   - Engine presets add their rows with their own tasks.

## Alternatives Considered

- **Run UzPainter.exe in the build to list its tools.** Rejected: the manifest is generated before the executable is linked, and the hosted CPU lane has no worker.
- **Parse the C++ registration.** Rejected: it is fragile, and it cannot see the per-value maps the schema builders compose.
- **Hand-written statuses.** Rejected: a row could claim `available` while its operation is a release gap.

## Consequences

- A task that adds, removes or re-gates a tool updates `mcp-tools.json` (`UZP_UPDATE_MCP_TOOLS=1`) and its matrix row in the same change. A task that implements a gap gives its row a Python-disabled fixture.
- phase5.2_parity-report-mcp-conformance reads the matrix to run full conformance at release. phase2.9_pilot-belt reads it for the Python-disabled round.
