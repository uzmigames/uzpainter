## ADDED Requirements

### Requirement: UV-Set-to-UV-Set Projection Equal to Painter
The `UVSetToUVSet` projection SHALL resample content from a recorded secondary UV set into the texturing UV set with output equal to the Tier 0 goldens.

#### Scenario: Second UV set projected
Given a UzmiGames-authored mesh with two UV sets and a bitmap fill using `UVSetToUVSet` from the second set
When BaseColor is exported at 16 bit
Then the decoded values equal the private Painter golden exactly

### Requirement: Warp Projection Equal to Painter
The `Warp` projection SHALL evaluate the documented warp parameters with output equal to the Tier 0 goldens.

#### Scenario: Warp sweep on the bevelled cube
Given a bitmap fill with `Warp` projection and a recorded parameter set on the bevelled cube
When the affected channels are exported at 16 bit
Then the decoded values equal the private Painter golden exactly

### Requirement: Secondary UV Sets Preserved at Import
Mesh import MUST keep every recorded UV set as data, include it in the mesh hashes and certificate, and leave the texturing UV set and single-UV meshes unchanged.

#### Scenario: Single-UV mesh unaffected
Given a mesh with one UV set certified in Phase 1
When it is imported by this build
Then its hashes and certificate are identical to the Phase 1 values

### Requirement: Unproven Projection Combinations Stay Gaps
A projection mode or symmetry combination without an exact golden or approved exception MUST be listed as a `release-gap` and SHALL raise `NotYetSupported` before mutation.

#### Scenario: Unproven symmetry combination
Given a symmetry combination with `Warp` that has no exact golden
When an agent requests it through `fill_set`
Then the call raises `NotYetSupported` and the project revision is unchanged
