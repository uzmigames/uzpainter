## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.19_pyapi-native-module — phase1.3, phase1.8 and phase1.19 are archived; phase1.18_export-engine is still open (the facade's export runs over its children's code on main)

## 2. Implementation
- [x] 2.1 `python/substance_painter/` package skeleton with the documented modules, `__version__ = "0.3.7"`, `_version.py`, `application.version()` and `application.version_info()`; documented symbols only — `python/substance_painter/` re-exports from `python/uzpainter_facade/`; installed into `bin/python/` (`python313._pth`); `python/FACADE.md` §1
- [x] 2.2 Documented classes, enums and functions for the Phase 1 subset delegating to `uzpainter`, with Painter's documented signatures and errors — documented symbols of the Phase 1 subset plus those whose native counterpart raises NotYetSupported; others absent (decision 107 §1)
- [x] 2.3 Output-changing quirks: `active_channels` after `set_source` resets sources to the channel default; mask-stack `None` rules with `ValueError`; `set_source(None, …)` on a multichannel fill raises `EditionContextException`; `insert_*` position rules — plus Painter's insert defaults (per-channel blending, "Levels - Base color", "Compare mask"), dirty-on-edit `needs_saving` and group content effects dropped on save (decision 107 §5, §7)
- [x] 2.4 Desktop-only omissions raising `UnsupportedInUzPainter(symbol, reason, alternative)` — 15 symbols (`ui` Qt members, `Resource.show_in_ui`, `show_resources_in_ui`, `GraphicalUserInterfaceStarted`)
- [x] 2.5 Inert script context stored as state with readback (selection, selection type, collapsed groups, active stack, UI mode, application menu); `get_stack()` default resolves to the active stack
- [x] 2.6 `js.evaluate` parser for the documented `alg.*` whitelist with JSON-literal arguments, mapped to typed native calls; anything else raises `UnsupportedInUzPainter` before mutation; `alg.shaders.*` raises `NotYetSupported` until `uzpainter.render.shader` exists — `alg.mapexport.save*` also NotYetSupported until a JavaScript export golden exists (decision 107 §6)
- [x] 2.7 `colormanagement.Color` with the four colour-space families and the OCIO string form; implicit sRGB/Raw rule by channel — float32 sRGB decode; uniform colours stored as working values (decision 107 §2); the 70/255 residual is named (§3, recording P20-B)
- [x] 2.8 Colour-configuration profiles: preserve the project's declared mode, working space, input rules and display/view transform; pinned profiles with the linear-working/sRGB-I/O default; unsupported configuration fails before evaluation — Legacy (linear working, sRGB I/O) is the one pinned profile; OCIO and the compositor colour fits moved to phase1.14_compositor-core, `$colorSpace` to phase1.18 (decision 108)
- [x] 2.9 `layerstack.ScopedModification` batching invalidation without rollback
- [x] 2.10 `python/substance_painter_plugins/` with `start_plugin`, `close_plugin`, `path`, `load_startup_modules` for non-UI modules

## 3. Tests
- [x] 3.1 Facade quirk probes compared exactly with `phase0.6_tier0-api-probes` goldens in a local run on the owner's machine (decision 028; the local run report is the evidence): active-channel reset, mask `None` rules, insertion rules, `EditionContextException` — `tests/python/test_pyapi_facade_tier0.py` replays the six probes with the recorder's own Painter-side code: every output exact except the named exclusions of steps the native support check refuses (decision 081) and exported maps the export engine refuses or does not yet encode (phase1.18); report `parity/reports/phase1/pyapi-facade.md`
- [x] 3.2 Provenance test: every public facade symbol maps to a documentation anchor in the admitted inventory (`tools/capabilities/painter-api-inventory.json`); no underscore-private Painter symbol is exposed — 828 symbols; documented members added to `documented_symbols.json` and the inventory
- [x] 3.3 Each desktop-only symbol raises `UnsupportedInUzPainter` naming symbol, reason and alternative
- [x] 3.4 Each inert-state symbol reads back what was set and leaves exports byte-identical
- [x] 3.5 `js.evaluate`: each whitelisted expression maps to its typed call; a non-whitelisted expression and a non-literal argument raise `UnsupportedInUzPainter` with the revision unchanged
- [x] 3.6 Colour tests: implicit colour space per channel kind; an unsupported configuration (e.g. an unpinned OCIO config) fails before evaluation; the default profile round-trips through save/reopen — the OCIO case fails before evaluation; `export-ocio-encode-legacy` readbacks exact in the Tier 0 file (one named residual)
- [x] 3.7 (decision 106, from phase1.19 item 3.2) The Tier 0 API-probe readbacks that need a facade rule, compared exactly with the goldens in a local run: uniform colours read back in the working space (`fill-layer-readback` s5-s8, s30-s33), `SourceBitmap.list_available_color_spaces` (s43), Painter's resource ids (context and version) and the `.spp` file name; the native-owned readbacks are compared by `tests/python/test_pyapi_tier0.py` — `fill-layer-readback` and `textureset-project-readback` exact (maps excluded, phase1.18); contexts up to the session offset (decision 107 §4)
- [x] 3.7 `ScopedModification` raising inside the block keeps the calls already committed
- [x] 3.8 `substance_painter_plugins.load_startup_modules` loads a non-UI startup module and `close_plugin` unloads it

## 4. Acceptance
- [x] 4.1 Every §3 test green (hosted CPU lane where no GPU or private golden is needed, with the other tests skipped there with an explicit reason; a local run on the owner's machine otherwise, decision 028); results attached to `phase1.24_python-api-facade` — 9 of 9 in `test_pyapi_facade.py` (CPU, every lane); 9 of 9 in `test_pyapi_facade_tier0.py` (owner's machine, skips without a store); report `parity/reports/phase1/pyapi-facade.md` for phase1.24

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — `python/FACADE.md`, `docs/architecture/10-python-api.md` §4, decisions 107 and 108
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
