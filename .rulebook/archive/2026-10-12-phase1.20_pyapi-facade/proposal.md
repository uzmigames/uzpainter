# Proposal: phase1.20_pyapi-facade

## Why
Child of `phase1.24_python-api-facade` (P1-PYAPI in `docs/dag.md`), implementing D9 (decision 011) and D2 (decision 004, amended by decision 019) as specified in `docs/architecture/10-python-api.md` §0, §1, §3 and §4. The Assets3D scripts were written against Painter's `substance_painter` package; to run them unchanged UzPainter needs a pure-Python facade that has Painter's documented shape and reproduces Painter's observable quirks that change output, because a replayed instruction sequence depends on them. The facade must hold documented symbols only (clean-room rule, decision 002), make omitted desktop symbols raise instead of silently succeeding, and keep inert UI state as state. Requirements: OWN-04, ARC-03, ARC-13, PRJ-05, LAY-01, INT-01 (`docs/prd.md`).

## What Changes
- `python/substance_painter/`: the compatibility facade, pure Python over `uzpainter`, written from Painter's public API documentation as admitted by `docs/approved-sources.md` (never from Adobe's shipped `.py` sources); documented symbols only, so a private name is absent like any unknown attribute; `__version__ = "0.3.7"` and `_version.py` report the API level; `application.version()` returns the UzPainter version string and `application.version_info()` the tuple.
- `python/substance_painter_plugins/`: `start_plugin`, `close_plugin`, `path`, `load_startup_modules` for non-UI `startup/` and `plugins/` modules.
- Output-changing quirks (ARC-13), each backed by a Tier 0 golden from `phase0.6_tier0-api-probes`: assigning `active_channels` after `set_source` resets the fill's sources to the channel default; mask-stack contexts require `None` for channel and source mode (a channel argument raises `ValueError`); `set_source(None, …)` on a multichannel fill raises `EditionContextException`; `insert_*` position rules raise as Painter. The native API's no-reset behaviour stays documented side by side (LAY-01).
- Desktop-only omissions: the Qt members of `ui` (`show_main_window`, `get_main_window`, layouts, docks, menus, toolbars, actions, `delete_ui_element`), `Resource.show_in_ui`, `show_resources_in_ui` and `GraphicalUserInterfaceStarted` raise `uzpainter.UnsupportedInUzPainter(symbol, reason, alternative)`.
- Inert script context kept as state, never an error: `layerstack.get/set_selected_nodes`, `get/set_selection_type`, `GroupLayerNode.is_collapsed/set_collapsed`, `textureset.get/set_active_stack`, `ui.get_current_mode/switch_to_mode/UIMode`, `ui.ApplicationMenu`; readback returns what was set and only `get_stack()`'s default reads the active stack, as in Painter.
- `js.evaluate(code)`: the documented whitelist of `alg.*` calls with JSON-literal arguments (`alg.version.painter`, `alg.project.isOpen()`, `alg.project.name()`, `alg.shaders.instances()`, `alg.shaders.parameters(id)`, `alg.shaders.setParameters(id, params)`, `alg.shaders.updateShaderInstance(id)`, `alg.mapexport.*`, `alg.project.saveAndClose()`) parsed into typed native calls; any other expression raises `UnsupportedInUzPainter` before mutation; `alg.shaders.*` raises `NotYetSupported` until `uzpainter.render.shader` lands with `phase2.3_realtime-preview`.
- Colour (10 §4): `colormanagement.Color(r, g, b, color_space)` with `GenericColorSpace`, `LegacyColorSpace`, `DataColorSpace`, `NormalColorSpace` and the OCIO string form; a colour without a space is sRGB on colour-managed channels and Raw otherwise; the project's declared colour-management mode, working space, input rules and display/view transform are preserved; colour-configuration profiles are pinned, with linear working space and sRGB I/O (the Assets3D contract, PRJ-05) as the named default profile; an unsupported configuration fails explicitly before evaluation, and recording `OCIO` or `PAINTER_ACE_CONFIG` does not make it supported.
- Documented mutation and error behaviour delegated to the native module (one call = one transaction; `layerstack.ScopedModification` groups calls and batches invalidation but rolls nothing back).

## Dependencies
- Parent: `phase1.24_python-api-facade` (integration and acceptance of P1-PYAPI).
- Prerequisites: `phase1.3_document-model`, `phase1.18_export-engine`, `phase1.8_project-store` (DAG inputs of P1-PYAPI) and the sibling `phase1.19_pyapi-native-module`.
- Followed by the siblings `phase1.21_pyapi-dispatcher-lifecycle` (events, lifecycle and computation state inside this package), `phase1.22_pyapi-cli-capabilities` and `phase1.23_pyapi-pipeline-adapter`.

## Acceptance
- The Tier 0 API-probe goldens owned by the facade (mask `None` rules, insertion rules, active-channel reset, `EditionContextException` on `set_source(None, …)`) are exact.
- A provenance test proves every facade symbol has a public documentation anchor and no private symbol exists; each desktop-only symbol raises `UnsupportedInUzPainter`; each inert-state symbol reads back what was set.
- `js.evaluate` accepts exactly the whitelist and rejects everything else before mutation; an unsupported colour configuration fails before evaluation.

## Impact
- Affected specs: `python-api` (facade shape, quirks, omissions, colour)
- Affected code: `python/substance_painter/`, `python/substance_painter_plugins/`, `tests/python/`
- Breaking change: NO
- User benefit: Painter scripts run against UzPainter with the behaviour their outputs depend on
