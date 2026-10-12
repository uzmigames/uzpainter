# 111. UzPainter.exe run hosts a script in one process with one JSON report line and exit codes 0 to 3

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.22_pyapi-cli-capabilities, phase1.23_pyapi-pipeline-adapter, phase1.24_python-api-facade, phase2.1_supervisor-ipc-worker, phase2.2_preview-capture, phase1.21_pyapi-dispatcher-lifecycle

## Context

Task phase1.22 adds `UzPainter.exe run <script.py>` (01-overview §4, 02-runtime-topology §1, 10-python-api §2), which the pipeline adapter (phase1.23) calls in place of Painter's `execute_python`. The architecture fixes the contract (`result` as JSON with the captured stdout and stderr; an uncaught exception as a structured failure with its traceback) but leaves open the command line, the output framing, the meaning of exit code 3 and what `--gpu-backend` does when no Phase 1 Python call uses the GPU.

Measured facts:

- The native test runner (`uzp-pyapi-tests.exe`, phase1.19) already ran one script and printed the `RunScript` report as a JSON line. It drained the event dispatcher only after printing, so the output of events delivered after the script returned leaked to the process's stdout.
- The existing CLI verbs use 0 (success), 1 (failure or refusal) and 2 (usage). Nothing uses 3. UzEngine uses 3 for a lost device.
- Phase 1 Python calls use no GPU. The export, the only evaluating call, runs the CPU evaluator, which equals the GPU evaluator bit for bit. The GPU calls (`uzpainter.render.capture`, `render.shader.*`, `render.display.*`) are release gaps of phase2.3.
- `render::CreateDevice(vulkan)` fails at once in this build (DX12 only). `CreateDevice(dx12)` creates a real device, and the machine allows one GPU job at a time.
- `phase1-save-modes`, recording 2: the node's saved name is "uzp save probe y". Then s15 renames it to "x", s16 back to "y", and s17 `needs_saving()` is **false**. In recording 1 the same two renames end on a new name, and s17 is true. `textureset-project-readback` s12 after reopen: re-binding the same mesh map gives **true**. Decision 107 §7 ("any edit call marks the project unsaved") gives true at r2 s17.

The model panel: cx/gpt-6-astra and xai/grok-4.5 answered. kimi/kimi-k3 returned HTTP 503 twice.

- **C1, the command line**: PARTLY, AGREE. GPT: a host option taken anywhere steals script arguments; add `--`.
- **C2, one report line, drain after printing**: PARTLY ×2. Keep the capture on through the drain, so late deliveries belong to the report.
- **C3, exit codes**: AGREE ×2.
- **C4, lazy device, release gap before backend, 3.3 as a scope split**: PARTLY ×2. Agreed on laziness and order. The `gpu_backend_unavailable` assertion must stay explicitly open, not be counted as done.
- **C5, capabilities verb and module**: AGREE ×2. The new accessors need entries too.
- **C6, rename merge**: PARTLY ×2. Keep it narrow and tied to the recording; other restore patterns are unrecorded.

## Decision

1. **Command line.** `UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan] [-- args...]`.
   - `--gpu-backend <name>` is the process's backend wherever it appears before `--`. It is dx12 by default and is never passed to the script.
   - Everything after `--` goes to the script as given.
   - A second `--gpu-backend`, an unknown backend or no script is a usage error.
2. **Output.** Exactly one line `UZP_JSON:{...}` on stdout: `RunScript`'s report (`status`, `result`, `stdout`, `stderr`, `error {type, message, traceback}`, `last_committed_revision`, `committed`) plus `gpu_backend`.
   - The script's output stays captured until the event dispatcher has drained. Events and callbacks of operations the script started belong to the run: their output and commits are in the report.
   - The host then closes a project left open and ends the process without finalizing the interpreter.
   - `uzp-pyapi-tests.exe` is a thin `main` over the same host function, so every Python API test exercises the shipped host.
3. **Exit codes.**
   - 0: the script ran to its end and `result` is JSON.
   - 1: a structured failure: the script raised, could not be read, or `result` is not JSON.
   - 2: a usage error. A message goes to stderr and no JSON line is printed.
   - 3: a host failure outside the script. The interpreter did not start, or the shipped `capabilities.json` is missing or unreadable for `capabilities`. It is reported as `UZP_JSON:{"status": "host_error", "error": {...}}`.
   - A failure never exits 0.
4. **GPU backend.** The host checks and reports the backend but creates no device, because no Phase 1 Python call needs one. The first GPU call creates it lazily.
   - A GPU call that is a release gap raises `NotYetSupported` before the backend is consulted: a feature that does not exist is not a backend problem.
   - Task item 3.3 is checked as a **recorded scope split**. Under `--gpu-backend vulkan` the test proves that the host runs, that create, save and reopen succeed, and that the GPU calls refuse before any change.
   - The `gpu_backend_unavailable` refusal itself is tested with the first Python call that uses the GPU: phase2.1_supervisor-ipc-worker item 2.6 for the backend policy, phase2.2_preview-capture for `render.capture`.
5. **`capabilities`.** `UzPainter.exe capabilities` prints the shipped `capabilities.json` as one `UZP_JSON:` line. `uzpainter.capabilities` offers `profile()` (`"painter-12.1-api-0.3.7"`), `manifest()` and `entry(symbol, context="any")`, all reading the same file beside the executable. The pyapi-tests install ships the file too.
6. **Facade save state (refines decision 107 §7).** Consecutive `set_name` calls on one node, with no other edit between them, form one edit, as Painter's recording shows.
   - When such a run ends on the name it started from, and the project needed no saving before the run, `needs_saving()` is false again.
   - Every other edit call keeps decision 107's rule. Re-binding the same mesh map stays unsaved.
   - The rule covers renames only, as recorded. Whether other setters that restore a saved value behave the same is unrecorded (recording **P22-C**).
7. **Facade fixes from the R10 recordings** (decision 112 compares `phase1-create-settings`, `-delete-node` and `-resource-update`):
   - `get_node_by_uid` of a deleted node raises Painter's `ValueError("This node is not valid")`.
   - `update_layer_stack_resource` returns the replaced identifiers, as documented and recorded, not nodes.
   - Replacing a resource bound as a mesh map raises `NotYetSupported` before any change, until recording **P22-A**.

## Recordings this decision names (not recorded; owner action)

- **P22-A, mesh-map update.** On the plane: import two images, bind the first as the AO mesh map and in a fill, call `update_layer_stack_resource(first, second)`, then read back `get_mesh_map_resource(AO)`, the fill's source and the returned list. Both recordings.
- **P22-C, restored values.** After a save: `set_opacity(0.5)` then back to the saved value, `set_visible(False)` then True, `set_blending_mode` there and back, and two renames separated by another edit. Read `needs_saving()` after each.

## Alternatives Considered

- **Report printed before the drain** (the old runner). Rejected by the panel: late output leaked outside the report.
- **Creating the device at start, as the worker does.** Rejected: every pipeline script would take the machine's GPU slot for nothing.
- **`gpu_backend_unavailable` before `NotYetSupported`.** Rejected: an agent would switch backends to reach a feature that does not exist.
- **Content comparison for `needs_saving()`.** Rejected: no native call compares documents, and nothing records Painter comparing values.

## Consequences

- phase1.23 calls `run` and reads the `UZP_JSON:` line and the exit status.
- phase2.1 and phase2.2 own the `gpu_backend_unavailable` assertion of item 3.3.
- Recordings P22-A and P22-C settle the two named gaps.
