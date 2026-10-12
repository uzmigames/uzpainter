# `phase1.19_pyapi-native-module`: local run on the owner's machine

This task is a child of `phase1.24_python-api-facade` (P1-PYAPI; `docs/architecture/10-python-api.md` §1, §5, §7; INT-01, INT-10, LAY-01, LAY-06, LAY-07, LAY-08, QG-03, ARC-11, OWN-04). Under decision 028 its Tier 0 comparison runs locally against the private oracle store. This report is its evidence, attached to `phase1.24_python-api-facade` (decision 106 §4).

Run on 2026-10-12, branch `wt/phase1.19-pyapi-native`, on main `3504057`, current envelope `painter-12.1.5_js-api.1.1.20`. Decisions 105 and 106. Implementation: `src/python/` (`src/python/PYAPI.md`).

**Result.**

- **Native module.** `uzpainter` is linked statically into `UzPainter.exe` on the embedded CPython 3.13.16. `UzPainter.exe selftest --no-gpu` passes its four CPython stages with the new module.
- **`tests/python/test_pyapi_native.py`:** 14 of 14 pass, on the CPU, in every lane.

  | Item | What passed |
  |---|---|
  | 3.1 | Every Phase 1 setter: set → get → `save_as` → `close` → `open` → get, through freshly resolved handles, with equal values. |
  | 3.3 | `AttributeError` on an unknown attribute, with the revision unchanged; `ValueError` on a deleted node's handle; 11 later-phase calls raising `NotYetSupported` naming their owner, with the revision and save state unchanged. |
  | 3.4 | Failed calls change nothing. A script raising after two calls keeps both, and its report names revision 3. A raising `Transaction` commits nothing; a clean one commits one revision listing its created ids. Results list `created`, `modified`, `hidden`, `imported` and `skipped`. A thread waiting on another thread's `Transaction` gets `StaleRevisionError`. |
  | 3.5 | An ambiguous name fails before any change, listing both candidate ids. A named insert repeated is a no-op. Ids survive save/reopen. |
  | 3.6 | `sync_stack` rebuilds only the titled group, keeps `A*` visible and hides `C`, which is not deleted. C's resources survive. The JSON file is unchanged. A second sync skips the stored images. |
  | 3.7 | Replacing a mask resource keeps the node's uid; only that binding changes. |
  | 3.8 | A second Python thread runs while the command thread waits on an export job at 1024²; the job succeeds and publishes. |

- **`tests/python/test_pyapi_tier0.py` (item 3.2):** 2 of 2 pass.
  - **`fill-layer-readback`:** 23 native-owned outputs equal the golden exactly in both recordings (`same_session`, `after_save_reopen`). They cover the template channels and formats, names, visibility, node type, active channels, source mode, blending modes, opacities (float32: 0.8500000238418579), bitmap colour space, projection mode and UV parameters, the sub-layer and root structure, and uid identity.
  - **`textureset-project-readback`:** 8 outputs equal the golden in both recordings: template, resolution, the three mesh-map bindings by resource name, `needs_saving`, the file stem, and `name()` ("Untitled" before saving).
  - **Exclusion:** Painter's empty default paint layer "Layer 1" is removed from the structure readback after the test asserts it is exactly that empty layer (decision 105 §4, `phase4.1_nodes-paint-layers` item 2.8).
  - **Facade-shaped readbacks** are `phase1.20_pyapi-facade` item 3.7: working-space colours, available colour spaces, Painter's resource ids, the `.spp` name.
- **Other affected tests:**
  - `tests/vendoring/test_vendor_check.py` and `test_render_core_integration.py`: 31 of 31 pass. `build.zig` changed: `UzPainter.exe` takes zlib and spng from `uzp_mesh`.
  - `tests/capabilities` inventory test: pass.

**Open.** Item 1.1: `phase1.18_export-engine` has not been accepted. Its children's code, which the native export uses, is on main (decision 106 §3).

**Recordings.** None needed: every comparison uses recordings already in the private store.
