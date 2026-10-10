## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle, phase1.22_pyapi-cli-capabilities

## 2. Implementation
- [ ] 2.1 Adapter entry point in `adapters/assets3d/` replacing `painter_mcp_client.py execute_python` with `UzPainter.exe run`, absolute paths unchanged
- [ ] 2.2 Result contract preserved: `result` returned as JSON with captured stdout and stderr; uncaught exception returned as a structured failure with the traceback
- [ ] 2.3 Private-call shim `_substance_painter.display.save_viewport(path, w, h, _)` injected only into adapter-run scripts, calling `uzpainter.render.capture(mode=painter_viewport)`, raising an explicit capability error while that mode is unavailable
- [ ] 2.4 `adapters/assets3d/MIGRATIONS.md` listing the transport change and each shim
- [ ] 2.5 Fixture runner pinning the SHA-256 of `painter_create.py`, `painter_layer_stack.py` and `painter_export.py` and refusing to run a changed script

## 3. Tests
- [ ] 3.1 Wand v1 fixture: `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py` run through the adapter in a local run on the owner's machine (decision 028) with pinned hashes and return their JSON results
- [ ] 3.2 An adapter-run script that raises returns a structured failure with traceback and a non-zero exit code
- [ ] 3.3 Shim isolation: `_substance_painter` is importable inside adapter-run scripts only; a plain `run` script and the facade expose no such symbol
- [ ] 3.4 Shim in Phase 1: `painter_layer_stack.py capture` fails with an explicit capability error naming `painter_viewport`, and `smart` fails with an explicit capability error naming the missing smart-preset capability; the revision is unchanged in both cases
- [ ] 3.5 LAY-06 through the scripts: running `painter_create.py` twice creates no duplicate node; an ambiguous name fails before mutation; ids survive save/reopen
- [ ] 3.6 LAY-07 through `sync`: only the addressed group is rebuilt, other root groups hidden (not deleted) unless `--keep-visible` matches, unrelated roots and resources survive

## 4. Acceptance
- [ ] 4.1 Every §3 test green in a local run on the owner's machine (decision 028); the local run report with script hashes, as evidence, attached to `phase1.24_python-api-facade`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
