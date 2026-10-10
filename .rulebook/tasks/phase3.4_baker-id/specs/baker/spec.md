# Baker — ID usage

## ADDED Requirements

### Requirement: ID Colour Sources And Generators
The `ID` baker SHALL support `ColorSource` Vertex Color, Material Color, File ID and Mesh ID/Polygroup with `ColorGenerator` Random, Hue shift and Grayscale, and MUST record the effective palette in the receipt.

#### Scenario: Mesh ID with Random generator
Given the bevelled cube with highs split into named meshes
When `ID` is baked with `ColorSource` Mesh ID/Polygroup and `ColorGenerator` Random
Then the map MUST equal the private Painter golden label for label

### Requirement: ID Tier 2b Equality
ID maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat pairs with exact label equality and matching edge coverage; a difference MUST pass only through an owner-approved exception.

#### Scenario: Edge texel mismatch
Given an ID map whose labels match except on one edge texel
When the Tier 2b comparison runs
Then the map MUST be reported failed with the edge-coverage count unless an approved exception covers it
