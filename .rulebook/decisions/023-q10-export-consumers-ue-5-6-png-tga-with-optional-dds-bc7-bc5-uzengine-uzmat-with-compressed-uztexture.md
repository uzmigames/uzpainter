# 23. Q10 Export consumers: UE 5.6 PNG/TGA with optional DDS BC7/BC5; UzEngine .uzmat with compressed .uztexture

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Owner question Q10 asked for the Unreal version and importer, the UzEngine material reader, how channel omissions are reported and what is expected of DDS. D7 (decision 009) defines the export plan and presets. Owner answer of 2026-10-10 (docs/open-questions.md Q10).

## Decision

The Unreal preset targets UE 5.6 with PNG/TGA by default and optional DDS BC7 (BaseColor, ORM, Emissive) and BC5 (Normal). The UzEngine preset writes .uzmat materials with compressed .uztexture maps. SpecularWeight is exported and reported in the export receipt as a consumer gap wherever the consumer has no binding for it. Each preset is validated by an external consumer fixture (Unreal and glTF fixtures; UzEngine's own executable), never by consumer code linked into UzPainter (decision 021). See docs/architecture/08-export.md.

## Alternatives Considered

- DDS as the Unreal default - rejected: BC pass-through through Unreal cooking is not documented
- Omitting SpecularWeight silently - rejected: consumer gaps are reported

## Consequences

Phase 3 consumer fixtures load each preset and the receipts list the gaps; lossless canonical maps remain the authoring reference, and lossy derivatives are checked against them under a separate contract.
