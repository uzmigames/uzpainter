## ADDED Requirements

### Requirement: Tunic v10 Maps Equal The Painter Goldens
Every Tunic v10 map exported by UzPainter MUST equal the private Painter golden in native decoded values, unless an owner-approved exception in the register covers the difference.

#### Scenario: Tunic v10 Tier 1
Given the Tunic v10 stack JSON, resources, binding overrides and external mesh maps
When UzPainter rebuilds and exports the tunic
Then each exported map equals the golden at native precision

### Requirement: Per-Layer Bindings By Content Hash
Same-named resources bound to different layers SHALL resolve by content hash, and migration differences MUST be explicit per-layer overrides, never a global filename replacement.

#### Scenario: C07 and F03 piping masks
Given layers C07 and F03 that both reference a mask historically named `M_piping`
When the tunic is rebuilt
Then C07 binds `Source_v10_M_piping` and F03 binds `Source_v9_M_piping`, each by its own hash

### Requirement: Tunic Dump-And-Rebuild Is Equal
The rebuilt Tunic v10 dumped and rebuilt from its recipe and resources MUST export byte-identical files.

#### Scenario: Tunic rebuild
Given the rebuilt Tunic v10 project and its recipe dump
When a new project is rebuilt from the dump and both export with the same configuration
Then every exported file is byte-identical and the digests are equal
