# 2. License: Apache 2.0 with a strict clean-room policy toward Substance Painter

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Stated by the product owner (André) on 2026-10-10 during the architecture discussion. The discussion had left two routes open: Route A, a derivative port of Adobe's "ADOBE CONFIDENTIAL" GLSL shader library and shipping captured procedural outputs (highest parity, redistribution exposure); Route B, a clean-room reimplementation from public documentation and literature, calibrated numerically against Painter's outputs, shipping no Adobe content. The owner chose Route B.

## Decision

UzPainter is released under the Apache License 2.0. Nothing in the project may exceed what Substance Painter's license permits: no direct copying of Adobe code, shaders, assets or data. UzPainter only reproduces Substance Painter's behaviour, which does not infringe copyright in any form.

## Alternatives Considered

- Route A: derivative port of Adobe GLSL plus shipped captures — rejected by the owner (license exposure)
- Licensing the Substance Engine from Adobe — not pursued

## Consequences

Shaders, compositing, bakers and generators are implemented from public formulas and black-box measurements, never from Adobe source. Adobe assets (HDRIs, grunges, smart materials, captured procedural outputs) are never redistributed; Painter outputs may be used as local, private test oracles only. Mirroring the documented Python API shape (module, class and function names, signatures) is permitted; the compatibility facade is written from the documented interface, not from Adobe's shipped .py files. Every third-party dependency must be Apache-2.0-compatible and listed with its license. Parity residuals that the clean-room route cannot close are reported as documented gaps, not hidden.
