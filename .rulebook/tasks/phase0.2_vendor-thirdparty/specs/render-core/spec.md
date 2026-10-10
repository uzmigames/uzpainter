## ADDED Requirements

### Requirement: Third-party libraries from their own upstream
Every third-party library used by the vendored render core MUST be vendored under `thirdparty/<library>/` from its own upstream release at the version UzEngine's tree uses at the selected commit, and SHALL NOT be copied out of a UzEngine tree.

#### Scenario: Library fetched from upstream
Given the selected UzEngine commit lists VMA at a given version
When the third-party libraries are vendored
Then `thirdparty/vma/` holds that upstream release with its licence file and an `ORIGIN.md` naming the upstream URL, version and archive SHA-256

#### Scenario: No include resolves into UzEngine
Given the vendored render core's include closure
When the build resolves third-party headers
Then every header resolves under `thirdparty/<library>/` or the Windows SDK and none resolves to a UzEngine checkout

### Requirement: Differences from UzEngine's copy are recorded
Each upstream package SHALL be byte-compared with UzEngine's copy at the selected commit, and a UzEngine patch MUST be applied only when the build needs it and then be logged as a local modification.

#### Scenario: Differing file recorded
Given an upstream file that differs from UzEngine's copy
When the comparison runs
Then the library's `ORIGIN.md` names the file and the cause of the difference

#### Scenario: Unneeded patch not applied
Given a UzEngine patch under `thirdparty/<lib>/patches/` that the build does not need
When the library is vendored
Then the patch is not applied and no modification entry is created for it

### Requirement: Licence inventory confirmed
For each vendored library the licence, notices, package hash, selected features and distribution role MUST be confirmed against the pinned package, and an entry that cannot be confirmed SHALL be recorded as a release blocker.

#### Scenario: Unconfirmed redistribution blocks release
Given the DXC package's `LICENSE-MS.txt` does not state whether `dxil.dll` may be redistributed
When the inventory is recorded
Then the entry is marked as a named release blocker rather than as confirmed
