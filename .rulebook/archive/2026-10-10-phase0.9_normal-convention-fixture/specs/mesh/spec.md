## ADDED Requirements

### Requirement: Normal convention settled by fixture
The normal-convention fixture MUST settle, with recorded evidence, the OpenGL (+Y) convention and which MikkTSpace frame mode (`PerVertex` or `PerFragment`) equals Painter's baked tangent-space normal.

#### Scenario: Frame mode verdict
Given the hemisphere fixture baked in Painter and computed by the UzPainter prototype in both frame modes
When both maps are compared with the Painter oracle in tangent space at native depth
Then `parity/semantics/tangent-frame.json` records the frame mode that equals Painter, or the residual of each mode if neither does

#### Scenario: Green channel direction
Given a fixture region tilted toward +Y in tangent space
When the OpenGL map is exported
Then the green channel encodes +Y and the DirectX conversion inverts it

### Requirement: External consumer convention recorded
The fixture MUST record the green-channel convention of UzEngine's own executable shading the same map, as an external consumer, without linking UzEngine code.

#### Scenario: Consumer shading recorded
Given the hemisphere normal map
When UzEngine's executable shades it in the consumer fixture
Then the observed green-channel convention is recorded in the normal-convention report
