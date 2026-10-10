# 10. D8 Project file: SQLite container with a canonical JSON manifest and zstd blobs

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Per-command autosave requires incremental transactional commits; .spp files reach 1.19 GB; AI inspectability must not depend on the container (05-resolution.md D8).

## Decision

.uzp is a SQLite database (rollback journal at rest, no uncheckpointed WAL in a portable file) storing the canonical JSON manifest per revision, content-addressed original resource bytes, per-chunk zstd payloads, authoritative raster planes, checkpoints and an optional regenerable cache. Every committed mutation is a revision; save names a checkpoint; compact/save_as use VACUUM INTO. inspect and export-bundle expose the manifest and a ZIP+JSON+PNG view. The size budget is ratified after a matched-content census (10 % is a candidate). See docs/architecture/09-project-file-format.md.

## Alternatives Considered

- ZIP64 + manifest with atomic archive rewrite (Claude round 1) - rejected: autosave cost scales with project size
- HDF5 like .spp - rejected
- Custom chunk container - rejected: parser and recovery burden

## Consequences

SQLite and zstd vendored; Phase 1 instrumentation produces the census and fault-injection evidence.
