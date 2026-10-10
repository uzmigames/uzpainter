# Smart presets — 3D projections and symmetry

## ADDED Requirements

### Requirement: Projection Triplanar Physical Units
The `Triplanar` projection SHALL blend its three planar samples by the fitted normal-weighted rule with the documented hardness, and SHALL scale by the physical-size modes using the mesh's stored units; its decoded output MUST equal the Tier 0 triplanar goldens at native precision.

#### Scenario: Hardness sweep on the bevelled cube
Given the bevelled cube fixture and a bitmap fill with `Triplanar` projection at a recorded hardness and scale
When UzPainter evaluates and exports the channel at 16 bit
Then the decoded map MUST equal the private Painter golden, or the comparison MUST fail unless an owner-approved exception names it

### Requirement: Projection Planar Spherical Cylindrical
The `Planar`, `Spherical` and `Cylindrical` projections SHALL honour culling, crop and the 3D transform as documented, and MUST equal their Tier 0 goldens.

#### Scenario: Cylindrical projection with crop
Given the sphere fixture and a `Cylindrical` fill with a recorded crop and rotation
When the channel is evaluated
Then the output MUST equal the golden texel for texel

### Requirement: Projection Symmetry
Mirror and radial symmetry SHALL apply to the 3D projections with the documented parameters and MUST equal their Tier 0 goldens.

#### Scenario: Radial symmetry
Given a planar fill with radial symmetry enabled at a recorded count and axis
When the channel is evaluated on the plane fixture
Then the output MUST equal the golden

### Requirement: Projection Effective Units Recorded
The effective projection scale and the mesh units it used SHALL be written into every evaluation and export receipt, and the semantics of `projection_3d.scale` MUST come from the fitted Tier 0 result recorded in `parity/semantics/projections.json`, not from an assumed unit.

#### Scenario: Mesh authored in metres
Given a mesh whose source unit differs from Painter's centimetre unit and a `CustomPhysicalSize` triplanar fill
When the project is exported
Then the receipt MUST state the source unit, the scale to internal units and the effective projection scale, and the map MUST equal the golden

### Requirement: Projection Gaps Reported
`Warp` and `UVSetToUVSet` projections MUST be reported as release gaps in the capability manifest and a request for them MUST fail with a capability error before any mutation; no other projection SHALL be substituted.

#### Scenario: Warp requested
Given a fill layer
When a client sets its projection to `Warp`
Then the call MUST fail with a capability error, the revision MUST NOT advance, and the manifest MUST list `Warp` as a gap
