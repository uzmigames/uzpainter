# 107. The facade reproduces Painter's recorded quirks and colour rules over the native API and names every unrecorded case

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.20_pyapi-facade, phase1.19_pyapi-native-module, phase1.21_pyapi-dispatcher-lifecycle, phase1.22_pyapi-cli-capabilities, phase1.24_python-api-facade, phase1.18_export-engine, phase1.14_compositor-core

## Context

Task phase1.20 builds `substance_painter`, the pure-Python facade over the native `uzpainter` module (`python/`, `python/FACADE.md`). Several behaviours had to be fixed where the architecture (10 §3-§4) leaves a choice.

Measured facts. They come from the private goldens of the current envelope, Painter 12.1.5 in Legacy colour management, both recordings unless noted.

- **The active-channel reset.**
  - `active-channel-reset` and `-superset`: assigning `active_channels` after `set_source` reads BaseColor back as working (0.8, 0.8, 0.8) and Height as 0.
  - `-order-control`: without the assignment, both values are kept.
  - `set-source-none-multichannel` s17-s19: `set_source` on an inactive channel activates it and keeps the other sources.
  - No golden records the default of any other channel.
- **Effective defaults of inserted nodes.**
  - Active channels are empty.
  - Height blends `LinearDodge` and Normal `NormalMapDetail`. The other channels blend Normal at opacity 1.
  - A mask fill's source is None.
  - A content-stack levels effect is named "Levels - Base color", affects BaseColor and holds RGB parameters.
  - A compare mask is named "Compare mask".
  - The native insert gives Normal blending everywhere.
- **Uniform colours.**
  - A readback returns them in the working space, which is linear sRGB under Legacy.
  - A colour without a space is sRGB on BaseColor (an sRGB8 channel) and Raw on the data channels (`export-ocio-encode-legacy` readbacks).
  - The float32 formula `((f32(v) + 0.055f) / 1.055f) ^ 2.4f` (power of float32 operands, one rounding) reproduces 6 of 7 recorded components bit-exactly. Painter reads 70/255 as 0.061246056, the formula gives 0.061246071: 2 ulp.
  - Multiplying by the reciprocal, exp2/log2, the measured GPU pow tables and double precision throughout each match 3 or fewer.
- **Resource ids.**
  - The version is the SHA-1 of the imported file plus `.image` (4 fixtures).
  - The context `project<N>` counts the projects of the Painter session: project0 in a fresh session, +1 at each create or open.
  - A binding made with an older identifier reads that context back until the project is reloaded (`textureset-project-readback` s11 after reopen).
- **Saving.**
  - Painter reports `needs_saving()` true after re-binding the same mesh map (`textureset-project-readback` s12 after reopen). The native store makes no revision for a no-op.
  - A group's content fill effect is gone after save and reopen (`insert-positions` identity/s12).
- **Bitmap colour spaces.**
  - BaseColor: sRGB by default; `[Raw, Working, sRGB, Linear(Legacy), sRGB(Legacy)]` available.
  - Mask: Data by default; `[Raw, Data, DataSigned]` available.
- **`js.evaluate`.** No golden records a JavaScript export, and the Assets3D pipeline never calls `js.evaluate`.

The model panel (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5) could not be consulted: the 9router proxy refused every connection on two attempts (WinError 10061). The brief asks for a decision anyway. This one follows the measured facts. The claims the panel was asked are in the scratch dossier, C1-C8.

## Decision

1. **Surface.**
   - The facade defines the documented symbols of the Phase 1 subset. It also defines the documented symbols whose native counterpart raises `NotYetSupported` or `UnsupportedProcedural`.
   - Any other documented symbol is absent and raises `AttributeError`, so `hasattr` detection works. phase1.22's capability manifest lists those symbols as release gaps.
   - Modules re-export from `uzpainter_facade` only, so no private name is reachable. The one exception is `_version`, which 10 §4 requires.
   - The provenance test checks every public module and class member against the inventory. Members the inventory lacked are added to `documented_symbols.json` and the inventory with their python-doc owners: enum members, constructor parameters, `Color.value_raw`/`color_space` and the logging severities.
2. **Colour storage.**
   - The facade stores every uniform colour as `Color(working, "Working")`, with the working value computed in float32 under the implicit-space rule. The native evaluator therefore receives the linear value Painter composites.
   - Legacy is the one pinned profile: linear working space, sRGB I/O. Any other declared mode raises `NotYetSupported` when a project is opened and before every export. The facade rewrites no declared setting.
3. **The 70/255 residual.** The float32 formula stays. `readback/get_source/29/BaseColor` of `export-ocio-encode-legacy` is a named exclusion that the test requires to still differ. Recording **P20-B** (below) settles it.
4. **Resource ids.**
   - Contexts are numbered per interpreter session. Tier 0 compares them up to one constant session offset, which is not part of the instruction sequence.
   - Versions are SHA-1 + `.image`, kept in the project Metadata context `uzpainter.facade` and written in the import's native transaction.
   - Bound contexts are remembered for the session.
5. **Defaults and reset.**
   - Assigning `active_channels` resets every channel of the new set to its default, inside one native transaction.
   - The recorded defaults (BaseColor 0.8, Height 0) are explicit native sources. A new fill already holds them.
   - A channel whose default is unrecorded loses its native source. `get_source` on it, and an export of a fill that has it active, raise `NotYetSupported` naming recording **P20-A**.
   - New fills, fill effects and groups get Painter's per-channel blending.
   - The native API keeps LAY-01 and its own insert defaults. The facade is the layer that reproduces Painter.
6. **`js.evaluate`.**
   - The whole whitelist is parsed: version, `isOpen`, `name`, `saveAndClose` and the documented identifier lists map to native calls.
   - `alg.shaders.*` raises `NotYetSupported` (phase2.3).
   - `alg.mapexport.save*` raises `NotYetSupported` until a golden of a JavaScript export exists.
   - Everything else raises `UnsupportedInUzPainter` before any change.
7. **Inert state and saving.**
   - Selection, selection type and UI mode are facade memory per open project, cleared on create, open and close.
   - Any facade edit call marks the project unsaved until the next save.
   - A save drops group content effects first.
8. **Tier 0 harness.**
   - The recorder's own Painter-side code (`painter_side.py`, `painter_probes.py`) runs inside UzPainter's interpreter against the facade. It replays every api-probe as the recorder records it, and compares readbacks, raised errors, effective defaults and exported maps exactly.
   - Outputs that cannot be equal yet are listed with their owner:
     - steps the native support check refuses: content-stack fill effects, mask-stack levels and compare masks (decision 081);
     - exported maps the export engine refuses or does not yet encode: the 16-bit sRGB8 BaseColor (phase1.18 item 6.1), and Height's (h + 1) / 2 PNG rule, fixed on the unmerged phase1.18 branch.

## Recordings this decision names (not recorded; owner action)

- **P20-A, fill channel defaults.** A Tier 0 api-probe on the plane, Legacy and default template. It inserts a fill, assigns every template channel, and reads `get_source` and its `.working` for each channel. It binds `checker-16.png` and `mask-left-half.png` (grey) on every channel and in a mask, and reads `get_color_space` and `list_available_color_spaces`. It exports every channel (PNG 16, infinite padding).
- **P20-B, dense sRGB decode.** `set_source(BaseColor, Color(c/255, c/255, c/255, sRGB))` for all 256 codes and 64 seeded random floats, each read back through `get_source(...).get_color().working`. Both recordings.

## Alternatives Considered

- **Every documented symbol present, raising `NotYetSupported` from a table.** Rejected: it hides absent features from `hasattr`, and the table would duplicate phase1.22's manifest.
- **Storing colours as given and converting in the evaluator.** Rejected: it changes native code that decision 105 keeps "as given", and the facade would still need the readback conversion.
- **A lookup table fitted to the 70/255 point.** Rejected: one point does not fix a rule. P20-B does.
- **Removing the source of every reset channel.** Rejected: BaseColor and Height would then contribute nothing, against the goldens.
- **Driving the recorder host over a transport.** Rejected: the in-process replay runs the same Painter-side code without Painter.

## Consequences

- phase1.21 builds the lifecycle, events and discard-on-close on this package.
- phase1.22 records the absent symbols as release gaps.
- When phase1.18 merges, the Height map exclusions are dropped. When R-090 is fitted, the BaseColor ones are dropped.
- When P20-A and P20-B are recorded, `DEFAULT_SOURCES`, `default_bitmap_space`, `available_bitmap_spaces` and the sRGB decode are fitted and their exclusions and refusals removed. Owner: phase1.14_compositor-core (decision 108).

*Clean-room note (2026-10-19, decision 304): the uniform-colour readback line, which followed the documentation's wording, was rephrased for clean-room hygiene; the recorded reasoning is unchanged.*
