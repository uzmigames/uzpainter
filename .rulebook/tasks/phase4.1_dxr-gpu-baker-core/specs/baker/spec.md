## ADDED Requirements

### Requirement: GPU Baker Shares The Embree Sample Sequences
`GpuBaker` MUST use the same per-texel sample addressing (Hammersley by texel index and sample id) and the same reduction order as `EmbreeBaker` for the same `BakeRequest`.

#### Scenario: Sample dump matches Embree
Given one AO `BakeRequest` on the analytic sphere
When `GpuBaker` and `EmbreeBaker` dump the sample index and direction of every texel
Then the two dumps are identical

### Requirement: Acceleration Structures With Explicit Strides
`GpuBaker` SHALL build its acceleration structures from the high-poly and cage streams with their real vertex strides and per-geometry opacity flags, and MUST NOT use a fixed-stride path.

#### Scenario: Non-default stride
Given a high-poly stream whose vertex stride differs from 48 bytes
When the acceleration structure is built and a normal bake runs on the analytic plane
Then every texel hits the expected surface

### Requirement: GPU Bake Receipts Conserve Accounting
Every `GpuBaker` receipt SHALL name its backend and MUST satisfy the same disjoint-class conservation identity as the Embree receipts.

#### Scenario: Bevelled cube accounting
Given the bevelled cube with highs and a known expected count per class
When `GpuBaker` bakes it
Then the receipt's seven used-surface classes equal the expected counts and sum to `coverage.conservative_texels`

### Requirement: GPU Baker Capability Errors Before Work
`GpuBaker` MUST report a missing device feature as an explicit capability error before any work and SHALL NOT fall back silently to another backend.

#### Scenario: Missing ray query
Given a device without ray-query support
When a `GpuBaker` bake is requested
Then the job fails before dispatch with the missing feature named and nothing is published
