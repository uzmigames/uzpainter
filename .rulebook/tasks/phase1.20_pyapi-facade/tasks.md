## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.19_pyapi-native-module

## 2. Implementation
- [ ] 2.1 `python/substance_painter/` package skeleton with the documented modules, `__version__ = "0.3.7"`, `_version.py`, `application.version()` and `application.version_info()`; documented symbols only
- [ ] 2.2 Documented classes, enums and functions for the Phase 1 subset delegating to `uzpainter`, with Painter's documented signatures and errors
- [ ] 2.3 Output-changing quirks: `active_channels` after `set_source` resets sources to the channel default; mask-stack `None` rules with `ValueError`; `set_source(None, …)` on a multichannel fill raises `EditionContextException`; `insert_*` position rules
- [ ] 2.4 Desktop-only omissions raising `UnsupportedInUzPainter(symbol, reason, alternative)`
- [ ] 2.5 Inert script context stored as state with readback (selection, selection type, collapsed groups, active stack, UI mode, application menu); `get_stack()` default resolves to the active stack
- [ ] 2.6 `js.evaluate` parser for the documented `alg.*` whitelist with JSON-literal arguments, mapped to typed native calls; anything else raises `UnsupportedInUzPainter` before mutation; `alg.shaders.*` raises `NotYetSupported` until `uzpainter.render.shader` exists
- [ ] 2.7 `colormanagement.Color` with the four colour-space families and the OCIO string form; implicit sRGB/Raw rule by channel
- [ ] 2.8 Colour-configuration profiles: preserve the project's declared mode, working space, input rules and display/view transform; pinned profiles with the linear-working/sRGB-I/O default; unsupported configuration fails before evaluation
- [ ] 2.9 `layerstack.ScopedModification` batching invalidation without rollback
- [ ] 2.10 `python/substance_painter_plugins/` with `start_plugin`, `close_plugin`, `path`, `load_startup_modules` for non-UI modules

## 3. Tests
- [ ] 3.1 Facade quirk probes compared exactly with `phase0.6_tier0-api-probes` goldens on the self-hosted GPU runner: active-channel reset, mask `None` rules, insertion rules, `EditionContextException`
- [ ] 3.2 Provenance test: every public facade symbol maps to a documentation anchor in the admitted inventory (`tools/capabilities/painter-api-inventory.json`); no underscore-private Painter symbol is exposed
- [ ] 3.3 Each desktop-only symbol raises `UnsupportedInUzPainter` naming symbol, reason and alternative
- [ ] 3.4 Each inert-state symbol reads back what was set and leaves exports byte-identical
- [ ] 3.5 `js.evaluate`: each whitelisted expression maps to its typed call; a non-whitelisted expression and a non-literal argument raise `UnsupportedInUzPainter` with the revision unchanged
- [ ] 3.6 Colour tests: implicit colour space per channel kind; an unsupported configuration (e.g. an unpinned OCIO config) fails before evaluation; the default profile round-trips through save/reopen
- [ ] 3.7 `ScopedModification` raising inside the block keeps the calls already committed
- [ ] 3.8 `substance_painter_plugins.load_startup_modules` loads a non-UI startup module and `close_plugin` unloads it

## 4. Acceptance
- [ ] 4.1 Every §3 test green (hosted CPU lane where no GPU or private golden is needed, self-hosted GPU runner otherwise); results attached to `phase1.24_python-api-facade`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
