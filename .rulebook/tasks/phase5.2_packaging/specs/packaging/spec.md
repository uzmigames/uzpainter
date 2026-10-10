## ADDED Requirements

### Requirement: Offline One-Folder Distribution
The release SHALL be one folder for Windows 10/11 x64 that runs on a clean, offline machine without Python, Painter, Blender, the Vulkan SDK or the Windows SDK, and MUST NOT write into its install folder.

#### Scenario: Clean machine run
Given a clean offline Windows 11 x64 machine with a DX12 GPU and the release folder copied to it
When `UzPainter.exe selftest` runs and then a wand v1 export runs through `UzPainter.exe run`
Then the hardware slice passes on DX12, the export bytes equal those of the frozen build, and shader cache, logs and ledger are written under the user's local app-data folder only

### Requirement: Measured DLL Closure
The shipped binaries' DLL import closure SHALL be computed from their import tables and MUST equal the allowlist; system DLLs, `vulkan-1.dll` and the excluded components of 13 §5 MUST NOT be shipped.

#### Scenario: Unexpected DLL
Given a shipped binary that imports a DLL missing from the allowlist
When the closure check runs
Then packaging fails and names the binary and the DLL

#### Scenario: Vulkan loader missing
Given a clean machine without a usable system Vulkan loader
When the release starts with `--gpu-backend vulkan`
Then the Vulkan backend reports unavailable explicitly and the DX12 backend still runs

### Requirement: Complete Licence Closure
Every dependency in the release closure SHALL be recorded in the dependency lock with licence, notices, package hash, selected features and distribution role; no entry MAY remain "not confirmed"; `LICENSE`, `NOTICE` (including the UzEngine attribution and selected commit) and `LICENSES\` MUST be complete.

#### Scenario: Unconfirmed dependency
Given the lock lists `dxil.dll` with redistribution "not confirmed"
When the release inventory check runs
Then packaging fails and names the entry

### Requirement: No Adobe Content Or Oracle Data In The Release
The release folder MUST contain no Adobe binary, asset, preset, capture or documentation text and no file whose hash appears in the private oracle store index; every shipped preset and asset MUST carry a valid provenance record.

#### Scenario: Shipped preset without provenance
Given an export preset in `assets\export-presets\` without its `.provenance.json`
When the release scan runs
Then packaging fails and names the preset

### Requirement: Same Build As The Parity Report
The package verification record MUST name the same build hash and dependency lock as the final parity report; any change after freeze MUST reopen both.

#### Scenario: Mismatched lock
Given the parity report names lock L and the package was built with lock L2
When the build identity check runs
Then the package verification fails
