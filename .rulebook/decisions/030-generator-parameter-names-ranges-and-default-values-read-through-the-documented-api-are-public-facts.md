# 30. Generator parameter names, ranges and default values read through the documented API are public facts

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase0.6_procedural-feasibility

## Context

Owner, 2026-10-10, answering the procedural-feasibility question about the prototypes hard-coding generator defaults read via the Property API.

## Decision

Parameter names, ranges and default values of Painter generators, filters and materials, as read through the documented Property API, may appear in UzPainter's public code and documents. They are observed factual data, not Adobe expression. Recorded output images and structure readbacks remain private.

## Consequences

Prototypes and procedural families may hard-code documented-API defaults with a provenance note; no copying of .sbsar graphs, structure readbacks or outputs into the public tree.
