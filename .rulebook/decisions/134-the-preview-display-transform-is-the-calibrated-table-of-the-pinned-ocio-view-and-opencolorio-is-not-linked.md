# 134. The preview's display transform is the calibrated table of the pinned OCIO view, and OpenColorIO is not linked

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.1_preview-viewport-window, phase2.2_preview-capture, phase2.1_preview-display-presets

## Context

Item 2.3 of `phase2.1_preview-viewport-window` asks for the display transform "shared with captures: OCIO with Painter's substance config pinned by hash and the view `Default - sRGB`"; its proposal says the transform goes "through OpenColorIO". Decision 042 made that the only display configuration. Legacy `Linear`, Legacy `ACES`, ACE mode and every other OCIO view fail before rendering, naming decision 038.

Measured facts:
- Phase 0 validation (`parity/reports/phase0/iray-capture-procedure.md`, `Render-Standard-Validation.json`): Painter's `Default/sRGB` view equals the IEC 61966-2-1 sRGB transfer function within 0.0015 of an 8-bit code. Its config is `resources/ocio/substance/config.ocio`, SHA-256 `15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4`, re-hashed identical on 12.1.5.
- `parity/semantics/iray.json` entry `display-encoding` (calibrated) gives the Save Render code as `round(65535 encode(binary16(clamp(L, 0, 1))))`. Its residual is at most one 16-bit code on held-out Iray references, which is Iray noise.
- The config file is Adobe's. It is never shipped or committed (`docs/licensing-and-clean-room.md` §3 lists OpenColorIO "if linked", with UzmiGames- or user-supplied configs only). OpenColorIO 2.x is not vendored. Linking it means building it and its dependencies (yaml-cpp, pystring, expat, Imath, minizip-ng) under the Zig build. It would also need Painter's config file at run time on the user's machine.
- A project records its colour management as `{mode, config_hash}`. Painter does not save the view; a fresh session shows `Default - sRGB`.

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-12, one round):
- C1, the calibrated table without OpenColorIO, the configuration identified by `{mode, config hash, view}`: AGREE x1, PARTLY x2. The task text must be amended in a decision. NaN, infinity and the binary16 conversion must be specified so that GPU = CPU holds. Captures may share the table, but a capture never becomes parity evidence through it.
- C2, every other configuration fails before rendering with `unsupported_configuration` naming decision 038, with no fallback: AGREE x3. The error must name which part differs, and no stale image may stay on screen.
- C3, a different config hash fails and re-opens decision 042: AGREE x2, PARTLY x1. Linking OpenColorIO can also be re-opened by a later capture requirement, not only by a second view or config.
- C4, the environment is the project's resource, and a missing one fails with no substitute (RES-03): AGREE x3.

## Decision

1. **Transform.** The display transform of `painter_viewport`, and of its captures (`phase2.2_preview-capture`), is the calibrated model of the pinned view. It is a table of the 65 536 binary16 bit patterns, with entry `round(65535 encode(clamp(L, 0, 1)))` computed in double, where `encode` is the IEC 61966-2-1 encoding (`src/preview/display_transform.h`).
   - The GPU rounds the linear value to binary16 (nearest, ties to even) and looks up the same table. GPU and CPU codes are therefore equal by construction, and the tests check it pixel by pixel.
   - NaN, -0, negative values and -infinity map to 0. Values above 1 and +infinity map to 65535.
   - OpenColorIO is not linked, and Painter's config file is never read. The table is not a parity claim (decision 018).
2. **Identity.** The supported configuration is `{mode "ocio", config SHA-256 15059d4b…, view "Default - sRGB"}`. The project gives the mode and hash. The view is a render parameter, defaulting to `Default - sRGB`. Any other value fails before any GPU work with `unsupported_configuration: <what differs> is pinned out of the display transform (decision 038)`. The cases are Legacy with tone mapping `Linear` or `ACES`, ACE mode, another mode, OCIO without a hash or with another hash, and another view. The error names the differing part. The preview then shows that message in place of an image and clears the last one.
3. **Re-opening.** A Painter build whose config hash differs fails the identity check, so the table is never silently reused. Decision 042's re-open clause then applies. Linking OpenColorIO is re-opened when a second view or config enters the scope, or when a capture requirement needs OpenColorIO's own processing.
4. **Environment.** The preview lights with the project's environment resource: its bytes come from the project store and are verified by SHA-256. A missing resource fails explicitly with no substitute (RES-03). So does a project that names no environment. Both are shown as the preview's message.

## Alternatives Considered

- Vendor OpenColorIO 2.x and load Painter's config from the user's install at run time (rejected for this task: a large dependency tree for one pinned view whose behaviour a public specification and a calibrated fit already give, and a run-time dependency on an Adobe file)
- Use a UzmiGames-authored OCIO config equivalent to the view (rejected: it would be a second config with its own hash, which decision 042 does not admit)

## Consequences

Item 2.3 is checked with this realisation, and the task's proposal keeps "OCIO with Painter's substance config pinned by hash and the view `Default - sRGB`" as the identity. `docs/architecture/07-preview-and-render-parity.md` §3.4 records the realisation. `phase2.2_preview-capture` reuses `DisplayTable` for `painter_viewport` captures. Every project UzPainter creates today is Legacy, because `project.create` takes no colour-management settings. Such a project is shown as the unsupported configuration until a project carries the OCIO identity.
