## ADDED Requirements

### Requirement: Engine thread owns the GPU device
Only the engine thread SHALL touch the RHI device of the selected backend; other threads MUST submit requests to its queue and receive results through futures.

#### Scenario: Request from another thread
Given a compute request created on the Python command thread
When it is submitted
Then the engine thread executes it against the named revision snapshot and the caller receives the result through a future

### Requirement: Deadline-bounded GPU waits
Every GPU wait MUST carry a deadline and SHALL return `signaled`, `timeout` or `device_lost`; a device removal SHALL be reported as `device_removed {backend, reason}`.

#### Scenario: Stalled fence
Given a fence that is never signalled
When the engine thread waits on it with the default deadline
Then the wait returns `timeout` after the deadline and the request fails explicitly

#### Scenario: Injected device removal
Given a DX12 device removed with `ID3D12Device5::RemoveDevice`
When the engine thread executes its next request
Then the request fails with `device_removed {backend: dx12, reason}`

### Requirement: Generated kernels compiled and cached by content
Kernels SHALL be compiled from HLSL to DXIL and to SPIR-V through the vendored DXC compiler with `precise` arithmetic, and SHALL be cached under a key covering source, includes, defines, target and DXC version.

#### Scenario: Cache key sensitivity
Given a kernel already compiled and cached
When one of source, include, define, target or DXC version changes
Then the cache misses and the kernel is recompiled, while an unchanged key hits

### Requirement: Capability query and admission budget
The render layer SHALL report formats, usages, ray-query support, descriptor capacities and the VRAM budget of the active backend and MUST derive the tile admission budget from them.

#### Scenario: Budget derived at startup
Given a worker starting on the DX12 hardware adapter
When the capability query runs
Then the report contains the VRAM budget and the derived tile admission budget used by the evaluator
