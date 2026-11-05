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

### Requirement: Pilot Inputs Preserved Before Dependent Work
Before rebuilding or recording from recovered pilot inputs, the task SHALL publish one bounded inventory of identified sources, present/missing inputs and identity evidence, and SHALL preserve available or recovered bytes with verified hashes in the private store. It MUST reuse documented searches and MUST NOT repeat a sweep without a newly identified source. Public records MUST contain metadata and hashes only.

#### Scenario: Original inputs recovered
Given original pilot inputs recovered from an identified source
When the fixture is rebuilt
Then their hashes and provenance MUST be verified against the known references, the bytes MUST be preserved privately, and restoration alone MUST NOT require a new scope decision

### Requirement: Changed Pilot Reference Needs Explicit Owner Scope
Recreating, replacing or excluding a required reference SHALL require an explicit recorded owner scope decision before the changed baseline is used for acceptance. Any pending owner question MUST be reused rather than duplicated. Missing inputs or an unresolved choice MUST keep acceptance open; the checkpoint MUST NOT relax native output equality or the exception contract.

#### Scenario: Original inputs unavailable
Given the bounded inventory leaves an original input unavailable
When a regenerated or substitute input is proposed
Then the task MUST publish one owner decision package, retain the existing reference, and MUST NOT claim parity against a silently changed baseline

#### Scenario: Tunic mesh assumption contradicted by readback
Given decision 215 names the missing normalized OBJ and the rebuild fixture assumes the delivered FBX
When the rebuild input checkpoint is evaluated
Then mesh identity MUST remain unresolved until verified recovery or an explicit owner-authorized changed reference, and the admitted OCIO golden MUST remain preserved unchanged
