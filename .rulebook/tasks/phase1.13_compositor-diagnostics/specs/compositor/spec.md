## ADDED Requirements

### Requirement: Isolation and contribution
`isolate(layer)` SHALL evaluate the stack with one node hidden and MUST restore the prior visibility state atomically; `contribution(layer)` SHALL equal the full evaluation minus the isolated one.

#### Scenario: Failure during isolation
Given a visible layer and an evaluation that fails during isolation
When `isolate(layer)` is called
Then the call fails and the layer's visibility is exactly as before

### Requirement: Material views and region statistics
`material_views(mask)` SHALL return per-channel values under a material mask for ID, BaseColor, Height, Normal, Roughness and Metallic, and `region_stats` MUST match an independent computation over the same map and mask.

#### Scenario: Injected leak
Given a two-material fixture with one texel of material A's Roughness inside material B's mask
When `material_views` runs for material B
Then the leaking texel is reported
