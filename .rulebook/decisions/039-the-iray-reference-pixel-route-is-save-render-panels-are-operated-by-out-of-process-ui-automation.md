# 39. The Iray reference pixel route is Save Render; panels are operated by out-of-process UI automation

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.6_render-reference-procedure

## Context

The phase0.6 probe (Painter 12.1.5, fixed pipeline of decision 038, standard `U-A3D-RENDERSTD-2` and adapter `U-A3D-RENDERPY-2` in `docs/approved-sources.md`; `parity/reports/phase0/iray-capture-procedure.md`) measured: Save Render writes a 16-bit RGBA PNG (and a float32 EXR) that is display-referred (background 89,89,89 = clear colour linear 0.1 through Default - sRGB), at exactly the 1200x1200 override resolution; a save right after a camera change held a frame of the new settings; the viewport live view is scaled (1523x1174 for a 1200x1200 render) and carries the display-transform overlay. Assets3D captures with a Qt screen grab because `display.save_viewport` returned a stale camera, a different function. Assets3D also drives the panels in process through PySide6; doc 07 §2.1 keeps the recorder off Painter's undocumented live UI objects without an owner decision, and decision 029 allows Windows UI automation. The viewport's display-transform selector is in neither API nor the UI Automation tree. Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11): pixel route AGREE x2, PARTLY x1 (verify a complete RGBA16 decode at the override size); automation route AGREE x3; display-transform verification AGREE x1, PARTLY x1, DISAGREE x1 (the background checks one neutral value, so keep selector evidence on every capture and state the verification strength); seed `uncontrolled` with the noise floor from repeats AGREE x2, PARTLY x1; base_color as a live-view diagnostic only AGREE x3.

## Decision

1. The qualified procedure `iray-capture/1` uses Save Render as its pixel route: a 16-bit PNG, display-referred, at the override resolution, refused unless it decodes at that size and bit depth, is the only file newer than the fence, and its silhouette matches the fixture projected from the read-back camera. The external live-view observation is not a reference route.
2. Painter's panels are operated out of process through Microsoft UI Automation with real mouse and keyboard input (`tools/parity/recorder/painter_ui.py`), within decision 029; every value is read back from its widget after commit. In-process Qt widget access is not used.
3. The display transform is pinned to Painter's fresh-session default, Default - sRGB, with three checks on every reference: a fresh Painter session (references are separate-session by procedure), an image of the selector kept as private evidence, and the background canary (the render's background must read the sheet's `capture.background_srgb8`). The manifest states that the transform identity is verified by this evidence, not read from an interface.
4. Iray's seed stays `uncontrolled`; the noise floor comes from the procedure's repeats (07 §4), not from bit-identical renders.
5. The `base_color` diagnostic is a realtime live-view capture, labelled diagnostic, never an Iray reference.

## Alternatives Considered

- External 1:1 observation of the displayed frame (rejected: scaled at the owner's window size, overlays in the frame, no exact resolution)
- In-process Qt automation like the Assets3D adapter (rejected: undocumented live UI objects, doc 07 §2.1)
- Reading the display transform by OCR of the selector (rejected: adds an unvalidated reader; the selector image is kept as evidence instead)

## Consequences

Every reference manifest of the fixed pipeline carries `capture.bits_per_channel` 16, `capture.background_srgb8` and `capture.display_transform`; the recorder refuses a capture that fails any of them. A change of Painter's fresh-session display transform would make the background canary or the selector evidence fail and re-opens the procedure.
