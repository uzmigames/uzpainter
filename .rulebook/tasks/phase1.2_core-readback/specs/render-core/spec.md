## ADDED Requirements

### Requirement: Readback returns exact native values
`TextureReadback` SHALL return texel values bit-identical to the GPU resource in its native format, with correct rows for any width.

#### Scenario: Unaligned width at 16 bit
Given an RGB16 texture 1023 texels wide filled with known values
When it is read back
Then every texel equals the uploaded value and no row is shifted

### Requirement: Readback drain releases every request
Draining the readback queue MUST complete or fail every outstanding request and SHALL release every staging buffer.

#### Scenario: Drain under load
Given a burst of concurrent readback requests
When the queue is drained
Then each request reaches a terminal state and no staging buffer remains allocated

### Requirement: Readback failure is explicit
A readback whose fence wait does not return `signaled` MUST fail with the wait result and SHALL NOT return stale data.

#### Scenario: Device removed before map
Given a pending readback and an injected device removal
When the request completes
Then it reports `device_removed` and no buffer contents are returned
