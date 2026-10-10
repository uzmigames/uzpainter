# Baker — Curvature usage

## ADDED Requirements

### Requirement: Curvature Methods
The `Curvature` baker SHALL implement `CurvatureMethod` `FromMesh` and `FromNormalMap`, and its maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat pairs for both methods, a difference passing only through an owner-approved exception.

#### Scenario: From normal map
Given the bevelled cube with highs and its baked `Normal` map
When `Curvature` is baked with `FromNormalMap`
Then the map MUST equal the private Painter golden or cite an approved exception

### Requirement: Effective Curvature Normalisation Recorded
The effective curvature bounds actually used SHALL be recorded in the binding's `effective_normalization` and in the receipt, a re-bake or linked set MUST be able to reuse them, and the baker MUST NOT rescale silently.

#### Scenario: Re-bake with recorded bounds
Given a published curvature map whose `AutoMinMax` bounds were recorded
When the set is re-baked reusing the recorded bounds
Then the new map MUST be byte-identical to the first and the receipt MUST cite the same bounds
