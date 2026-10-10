# Procedural — frozen snapshots

## ADDED Requirements

### Requirement: Exact Signature Snapshot Serving
`SnapshotBackend` SHALL serve a snapshot only for a request whose full signature matches exactly and MUST return `unavailable` otherwise, without resampling or parameter extrapolation.

#### Scenario: Exact match
Given a project with a snapshot recorded for a generator at 2048 with seed 7
When the same generator is evaluated at 2048 with seed 7 and identical inputs
Then the raster MUST be byte-equal to the recorded snapshot

#### Scenario: Resolution differs
Given the same snapshot
When the generator is evaluated at 4096
Then `SnapshotBackend` MUST report `unavailable` and MUST NOT resample the snapshot

### Requirement: Snapshots Are Project-Private
Snapshots MUST be embedded only in the `.uzp` of the project they were recorded for, MUST NOT be shipped with UzPainter and MUST NOT be copied into another project.

#### Scenario: Copy to another project
Given two projects and a snapshot in the first
When a layer using the snapshot is copied into the second project
Then the snapshot MUST NOT be copied and evaluation in the second project MUST raise `UnsupportedProcedural` unless another backend serves it

### Requirement: Snapshots Do Not Make Assets Editable
Changing any parameter of a snapshot-served source SHALL change its signature, and the request MUST then be served by another backend or raise `UnsupportedProcedural`.

#### Scenario: Parameter edit
Given a snapshot-served source with no certified family
When one parameter is changed
Then evaluation MUST raise `UnsupportedProcedural` before the mutation commits
