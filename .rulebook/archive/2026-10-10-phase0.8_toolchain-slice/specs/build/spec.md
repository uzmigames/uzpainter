## ADDED Requirements

### Requirement: Hardware qualification slice
`UzPainter.exe selftest` MUST pass the DX12 hardware-adapter slice on the owner's machine before G0, from UzPainter's own build.

#### Scenario: Hardware slice green
Given the owner's machine with its DX12 hardware adapter
When `UzPainter.exe selftest` runs
Then the DX12 device, kernel compilation, readback to 16-bit PNG and Embree checks all pass

### Requirement: Probes reported without failing the gate
`selftest` MUST report the Vulkan, ray-query and WARP probes with supported capabilities, executed checks and explicit unsupported reasons, and a probe failure MUST NOT fail G0.

#### Scenario: WARP unsupported does not fail the gate
Given a WARP probe that fails a compute check
When the toolchain acceptance is evaluated
Then the WARP path is recorded as unsupported with its reason and the acceptance can still pass

### Requirement: CPython boundary qualified or fallback chosen
The toolchain MUST qualify the embedded CPython boundary directly or through the C-ABI DLL fallback, and MUST record any toolchain change with its failing selftest output.

#### Scenario: Fallback chosen on direct failure
Given the direct pybind11 boundary fails its exception round trip under Zig
When the fallback is applied and selftest reruns
Then the C-ABI fallback is recorded as the chosen boundary if it passes
