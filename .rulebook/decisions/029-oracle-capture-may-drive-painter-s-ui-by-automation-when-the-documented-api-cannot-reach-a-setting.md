# 29. Oracle capture may drive Painter's UI by automation when the documented API cannot reach a setting

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase0.6_render-reference-procedure

## Context

Owner, 2026-10-10, answering the Iray capture question: "vc tem acesso ao substance e pode fazer isso sozinho". The Assets3D collaboration protocol forbids mouse/keyboard/focus control of the shared Painter to protect sessions people are watching; the owner's authorization applies to UzPainter oracle sessions only.

## Decision

When a Painter setting needed for an oracle capture is exposed only in Painter's UI panels (e.g. Iray samples, time, denoiser, seed, viewer, post effects, Save Render), an agent may operate Painter's UI through Windows UI automation and screenshots instead of an owner-operated session. This is black-box observation of Painter's behaviour, not access to Adobe code.

## Consequences

Conditions: hold the Assets3D Painter lock; only when no other Painter process runs; throwaway projects from authored fixtures only; never touch Assets3D projects; screenshots and readbacks of Painter's UI are private oracle data (never committed); every UI-operated value is recorded in the operator-recorded settings sheet with how it was set and verified; UI-automation tooling is a dev-only dependency, never shipped.
