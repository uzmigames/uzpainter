# 19. D2 API scope: capability manifest with three statuses; brush strokes out of scope

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Supersedes decision 004, which stayed proposed until owner question Q5 (scope and milestone labelling) was answered. Painter's public Python API (545 documented anchors) must be mirrored for AI operation; UI-only members have no output effect, while js.evaluate reaches shader parameters and plugins execute code (05-resolution.md D2). Owner answer of 2026-10-10 (Q5): brush strokes are out of scope because Painter's Python API does not expose them, so no AI can use them in Painter either; milestones are named by proven scope.

## Decision

Every Painter symbol and UzPainter operation is classified supported / desktop-only-omitted (raises UnsupportedInUzPainter) / release-gap (raises NotYetSupported before mutation). Script context (active stack, selection, collapse, logical UI mode) is inert readable state. substance_painter_plugins supports non-UI modules. js.evaluate accepts a documented whitelist of alg.* calls with JSON arguments. The facade is written from python-doc only (decision 002). Brush strokes are out of scope: they are not a release gap, and no stroke engine is built anywhere; paint layers and paint effects remain layers that receive bitmaps and projections (LAY-12). Milestones are named by proven scope; the remaining gaps (arbitrary .sbsar, UV tiles, warp and UV-set projections, auto-unwrap, material layering, deferred export formats) stay visible in the capability manifest, and no "full replacement" claim is made while a required gap is open. See docs/architecture/10-python-api.md.

## Alternatives Considered

- Mirror all inventory rows including Qt UI - rejected: no output effect
- Mirror only the calls the pipeline makes today - rejected: fails the owner's same-functionality requirement
- Omit js and plugins entirely (Claude round 1) - rejected after Astra showed output-affecting uses
- Strokes as a release gap with a stroke engine (round-3 default) - rejected by the owner (Q5): the API does not expose strokes

## Consequences

No phase carries stroke work; the 'strokes per Q5' item in decision 016's Phase 4 scope resolves to out of scope. Release gaps stay visible until implemented and block any full-replacement claim.
