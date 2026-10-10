## ADDED Requirements

### Requirement: Own executable build
UzPainter MUST build `UzPainter.exe` from its own `build.zig` under the Zig release pinned in `build.zig.zon`, linking the vendored render core and libc++ statically, with no build step referring to a UzEngine checkout.

#### Scenario: Executable built from the repository alone
Given the UzPainter repository on a build machine without UzEngine
When the executable target is built
Then `UzPainter.exe` is produced and the link map shows the vendored render core linked statically

### Requirement: DX12 hardware slice
`UzPainter.exe selftest` MUST create a DX12 device on the hardware adapter with the Agility SDK, compile a compute kernel from HLSL to DXIL and to SPIR-V, dispatch it, read its 16-bit output back, write and re-decode a 16-bit PNG equal to the expected values, and run an Embree intersection; any failing stage SHALL make `selftest` exit non-zero with the stage and reason.

#### Scenario: Slice green on the owner's machine
Given the owner's machine with its GPU and driver
When `selftest` runs
Then every hardware-slice stage passes and the report records adapter, driver, OS build, Zig and DXC versions

#### Scenario: Missing Agility runtime
Given an output folder without `D3D12\D3D12Core.dll`
When `selftest` runs
Then the device stage fails with an explicit reason and the process exits non-zero

### Requirement: Measured DLL closure
The build MUST compute the DLL import closure of every binary in the output folder and compare it with the allowlist of `13-engine-integration.md` §5; an unlisted DLL or a shipped system DLL SHALL fail the check.

#### Scenario: Unlisted DLL detected
Given a binary in the output folder that imports a DLL not on the allowlist
When the closure check runs
Then it fails and names the DLL and the importing binary

### Requirement: Clean-machine start
The output folder SHALL start on a clean Windows 10/11 x64 machine without the Windows SDK, Vulkan SDK, Python or Painter installed.

#### Scenario: Start without SDKs
Given a clean Windows 10/11 x64 machine
When `UzPainter.exe selftest` is started from the copied output folder
Then the process starts, its imports resolve and the non-GPU stages run
