## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle, phase1.22_pyapi-cli-capabilities (all archived on main at `481e285`)

## 2. Implementation
- [x] 2.1 Adapter entry point in `adapters/assets3d/` replacing `painter_mcp_client.py execute_python` with `UzPainter.exe run`, absolute paths unchanged (`layer_stack.py` runs `painter_layer_stack.py` from its bytes with only `CLIENT`/`MCP_PYTHON` rebound; `client.py` is the drop-in client; `runner.py` runs in `UzPainter.exe run`; the session carried between calls; decision 113, MIGRATIONS M1, M2, M4)
- [x] 2.2 Result contract preserved: `result` returned as JSON with captured stdout and stderr; uncaught exception returned as a structured failure with the traceback (the bridge's `{"params": {}}` namespace and `default=str`; exits 0/1/2/3 mapped explicitly)
- [x] 2.3 Private-call shim `_substance_painter.display.save_viewport(path, w, h, _)` injected only into adapter-run scripts, calling `uzpainter.render.capture(mode=painter_viewport)`, raising an explicit capability error while that mode is unavailable (MIGRATIONS M3; `smart` refused before any call by the capability gate, M5)
- [x] 2.4 `adapters/assets3d/MIGRATIONS.md` listing the transport change and each shim (M1-M7, plus what is not adapted with its owner)
- [x] 2.5 Fixture runner pinning the SHA-256 of `painter_create.py`, `painter_layer_stack.py` and `painter_export.py` and refusing to run a changed script (`tests/adapters/assets3d/wand.py`: pins and inputs from the committed R9 request manifest via the recorder's loader; the entry's `--pin` refuses before anything runs)

## 3. Tests
- [x] 3.1 Wand v1 fixture: `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py` run through the adapter in a local run on the owner's machine (decision 028) with pinned hashes and return their JSON results — recorded scope split (decision 113 §7): create and sync return their JSON results; the pinned export runs and returns the export engine's explicit `NotYetSupported` (16-bit sRGB8 BaseColor, R-090, decision 103) while `srgb8-material-channels` is a gap; the test turns to the five-map result by itself when phase1.25_pilot-wand item 2.6 closes it
- [x] 3.2 An adapter-run script that raises returns a structured failure with traceback and a non-zero exit code
- [x] 3.3 Shim isolation: `_substance_painter` is importable inside adapter-run scripts only; a plain `run` script and the facade expose no such symbol
- [x] 3.4 Shim in Phase 1: `painter_layer_stack.py capture` fails with an explicit capability error naming `painter_viewport`, and `smart` fails with an explicit capability error naming the missing smart-preset capability; the revision is unchanged in both cases
- [x] 3.5 LAY-06 through the scripts: running `painter_create.py` twice creates no duplicate node; an ambiguous name fails before mutation; ids survive save/reopen — recorded scope split (decision 113 §7): repeated `sync` leaves one group of the title with the same 13 layers and imports nothing again; uids read back unchanged across calls (reopen) and a save. Create run twice onto its existing `dst` hits `save_as` onto an existing file, unrecorded in Painter: recording P23-A, owner phase1.24_python-api-facade. The three scripts make no name-addressed call that can match two nodes; the ambiguity rule stays tested at the API level (`tests/python/test_pyapi_native.py`, `test_pyapi_facade.py`)
- [x] 3.6 LAY-07 through `sync`: only the addressed group is rebuilt, other root groups hidden (not deleted) unless `--keep-visible` matches, unrelated roots and resources survive

## 4. Acceptance
- [x] 4.1 Every §3 test green in a local run on the owner's machine (decision 028); the local run report with script hashes, as evidence, attached to `phase1.24_python-api-facade` (`parity/reports/phase1/pyapi-pipeline-adapter.md`; 3.1 and 3.5 as the recorded scope splits of decision 113 §7)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation (`adapters/assets3d/MIGRATIONS.md`, `docs/architecture/10-python-api.md` §2, the local run report)
- [x] 5.2 Write tests covering the new behavior (`tests/adapters/assets3d/`: 10 over `UzPainter.exe` on the wand v1 inputs, 24 host-side on every lane)
- [x] 5.3 Run tests and confirm they pass (`tests/adapters`: 34 of 34 after merging main; ruff, mypy strict on the whole repository and the guard pass)
