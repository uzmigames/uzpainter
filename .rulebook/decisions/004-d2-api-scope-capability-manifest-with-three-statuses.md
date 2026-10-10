# 4. D2 API scope: capability manifest with three statuses

**Status**: superseded
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Painter's public Python API (545 documented anchors) must be mirrored for AI operation; UI-only members have no output effect, while js.evaluate reaches shader parameters and plugins execute code (05-resolution.md D2). Scope labelling of release gaps (strokes, UV tiles, warp projection, auto-unwrap) is owner question Q5.

## Decision

Every Painter symbol and UzPainter operation is classified supported / desktop-only-omitted (raises UnsupportedInUzPainter) / release-gap (raises NotYetSupported before mutation). Script context (active stack, selection, collapse, logical UI mode) is inert readable state. substance_painter_plugins supports non-UI modules. js.evaluate accepts a documented whitelist of alg.* calls with JSON arguments. The facade is written from python-doc only (decision 002). See docs/architecture/10-python-api.md.

## Alternatives Considered

- Mirror all inventory rows including Qt UI - rejected: no output effect
- Mirror only the calls the pipeline makes today - rejected: fails the owner's same-functionality requirement
- Omit js and plugins entirely (Claude round 1) - rejected after Astra showed output-affecting uses

## Consequences

Release gaps stay visible until implemented; the owner decides how milestones may be labelled (Q5). Status proposed until Q5 is answered.
