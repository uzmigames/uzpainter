## ADDED Requirements

### Requirement: Remaining Nodes Integration Acceptance
The remaining-nodes work package MUST close only when its five child tasks are accepted and the extended Tier 0 corpus passes in a local run on the owner's machine (decision 028).

#### Scenario: A failed child keeps the parent open
Given `phase4.1_nodes-vector-font-sources` is not accepted
When the parent acceptance item is evaluated
Then the parent task stays open whatever the other children's results are

### Requirement: Tier 0 Extended to the New Kinds
The Tier 0 corpus SHALL contain exact goldens for instances, anchors and anchor references, compare mask, colour selection, warp and UV-set projections, vector and font sources, and paint layers and paint effects receiving bitmaps and projections, and every one SHALL pass exactly or through an owner-approved exception.

#### Scenario: Mixed recipe equal to Painter
Given a recipe combining an instance, an anchor reference, a compare mask, a warp projection, a font source and a paint layer with a projected bitmap
When it is rebuilt in UzPainter and exported at 16 bit
Then every exported channel equals the private Painter golden exactly

### Requirement: Capability Manifest Updated for the New Kinds
The capability manifest MUST list each new kind as `supported` with its tier evidence or as an explicit `release-gap`, and an unsupported kind SHALL raise `NotYetSupported` before any mutation.

#### Scenario: Remaining gap stays explicit
Given a projection mode whose golden is not yet exact
When the capability manifest is regenerated and an agent requests that mode
Then the manifest lists it as `release-gap` and the request raises `NotYetSupported` without changing the project revision

### Requirement: Typed MCP Access Without Python
Every new kind SHALL be reachable through the typed MCP stack family with Python disabled, and its operation-matrix row MUST name a passing conformance fixture.

#### Scenario: Instance created over MCP with Python disabled
Given the supervisor started without `--allow-python`
When an agent calls `layer_instantiate` and then `layer_list`
Then the instance exists with its source reference and the conformance fixture for that row passes
