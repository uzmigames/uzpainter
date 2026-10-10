# 9. D7 Export: Painter-compatible JSON compiled into a validated plan; Unreal ORM and UzEngine presets

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

The pipeline exports through Painter's JSON configuration; the owner requires Unreal ORM and UzEngine presets, preferably compressed; UzEngine's cooker defaults and shader paths have route-specific hazards (05-resolution.md D7).

## Decision

Accept Painter's export dictionary verbatim and compile it into a typed plan validated before any GPU work (unknown identifiers such as Mixed_AO rejected); PNG 8/16 via the memory encoder, EXR, TGA/BMP/JPEG, DDS BC1/3/4/5/7, .uztexture plus .uzmat; presets defined from the documented list_output_maps output and public template descriptions (no .spexp parsing); UzEngine preset albedo BC7 sRGB with opacity in alpha, normal BC5 with negative-Z check, ORM BC7 linear, height BC4 with explicit metadata, SpecularWeight exported and reported as a consumer gap; canonical lossless maps kept; receipts with hashes and manifest fields; atomic publication; same-build byte determinism. See docs/architecture/08-export.md.

## Alternatives Considered

- A new simpler export API only - rejected: breaks pipeline scripts
- Filename-driven engine cooking - rejected: BC7 sRGB default for height/thickness

## Consequences

Tier 0 fits for padding, dithering, resize and virtual maps; consumer fixtures for UzEngine, Unreal and glTF in Phase 3.
