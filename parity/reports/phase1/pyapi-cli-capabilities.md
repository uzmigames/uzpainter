# `phase1.22_pyapi-cli-capabilities`: local run on the owner's machine

This task is a child of `phase1.24_python-api-facade` (P1-PYAPI; `docs/architecture/10-python-api.md` §1-§3, `01-overview.md` §4, `02-runtime-topology.md` §1; INT-01, ARC-03, OWN-01, OWN-04). Under decision 028 its Tier 0 comparisons run locally against the private oracle store. This report is its evidence for `phase1.24_python-api-facade`.

- Run on 2026-10-12, branch `wt/phase1.22-cli`, on main `eaa4685`, current envelope `painter-12.1.5_js-api.1.1.20`.
- Decisions 111 and 112. Implementation:
  - `src/python/run.{h,cpp}` and `capabilities.{h,cpp}` (`src/python/PYAPI.md` §7);
  - `tools/capabilities/` (statuses, `tier0-trace.json`, the `pending-evidence` status);
  - `tests/python/capability_trace.py`;
  - the facade fixes in `python/` (`python/FACADE.md` §3).

## Result

### `run` and `capabilities` (`tests/python/test_pyapi_cli.py`, items 3.1-3.4, every lane): 8 of 8 pass

These tests use the `UzPainter.exe` of a fresh `zig build painter`.

- **3.1.** `result = {"ok": 1, ...}` comes back in one `UZP_JSON:` line. The line carries both captured streams, the script arguments (including those after `--`) and `gpu_backend: dx12`. Exit status 0.
- **3.2.** A `ValueError("bad stack")` after one committed call is reported as a structured failure: the type, the message, the traceback, no result, and the last committed revision with its committed call. Exit status 1.
- **2.3.** Usage errors give exit status 2 and no JSON line: no script, an unknown backend, a missing value, a repeated option.
- **3.3** (recorded scope split, decision 111 §4). Under `--gpu-backend vulkan`, create, `save_as`, close and open succeed. `uzpainter.render.capture` raises `NotYetSupported` with the revision unchanged. The `gpu_backend_unavailable` assertion belongs to the first GPU call: phase2.1_supervisor-ipc-worker item 2.6 and phase2.2_preview-capture.
- **3.4.** The `capabilities` output validates against `capabilities.schema.json` and equals the generator's manifest. `uzpainter.capabilities.profile()` is `painter-12.1-api-0.3.7`, and `manifest()` and `entry()` read the same file.

### Conformance (`tests/python/test_capability_conformance.py`, items 2.6 and 3.5, every lane): 5 of 5 pass

- The manifest has 1 541 entries:

  | Package | supported | pending-evidence | release-gap | desktop-only-omitted |
  |---|---|---|---|---|
  | `substance_painter` | 289 | 316 | 334 | 15 |
  | `substance_painter_plugins` | — | 12 | — | — |
  | `uzpainter` | 179 | 328 | 68 | — |

- Every `supported` entry cites exactly the goldens whose compared replays exercised it. Every exercised symbol is `supported`. The check runs against the committed trace of 22 replays.
- Every public name of the three packages has an entry, and every symbol claimed to work exists.
- The 15 desktop-only members raise `UnsupportedInUzPainter`.
- Every release gap the Python API reaches is either absent or raises `NotYetSupported` with the revision unchanged. Compositor contexts are refused by the evaluator's support check (decisions 081, 082). Material layering cannot be requested by any documented call.

### Tier 0, traced (`test_pyapi_tier0.py`, `test_pyapi_facade_tier0.py`, `test_pyapi_lifecycle_tier0.py`; owner's machine): 22 of 22 pass

All 16 api-probe goldens and the colour readbacks of `export-ocio-encode-legacy` are compared exactly in both recordings, each replay under the capability trace (decision 112). This task adds:

| Golden | Exact | Excluded (reason) |
|---|---|---|
| `phase1-create-settings` | Readbacks (texture set resolution 512 under DirectX with `import_cameras`, the texture sets) and the events of every step. | The 16-bit BaseColor export (R-090, decision 103). |
| `phase1-delete-node` | Structure after two deletes, survivor name and identity, and Painter's `ValueError("This node is not valid")` for every deleted uid, in both recordings. Events of every step. | `s17/uid`: a uid's value is Painter's own allocation; the identity outputs compare what it resolves to. The BaseColor export. |
| `phase1-resource-update` | The returned identifiers, the mask fill's rebound source, the mask effects, and the events of every step. | `s14/uid`, `s15/uid` (as above). The BaseColor export. |
| `phase1-save-modes` | `file_path` and `needs_saving` of every step, now compared with the events. Recording 2 s17 is false after two renames that end on the saved name (decision 111 §6). | — |

### Affected suites (every lane): pass

- `tests/python/test_pyapi_native.py`, `test_pyapi_facade.py` and `test_pyapi_dispatcher.py` pass with the shared `run` host (the runner prints `UZP_JSON:` lines) and the facade fixes.
- `tests/capabilities` (28) passes with the fourth status.

## Recordings named (owner action)

- **P22-A**: `update_layer_stack_resource` on a resource bound as a mesh map (decision 111).
- **P22-B**: one api-probe exercising every Painter symbol marked `pending-evidence` (decision 112).
- **P22-C**: setters that restore a saved value, and renames separated by another edit, with `needs_saving()` (decision 111).
