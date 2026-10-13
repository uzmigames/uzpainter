## ADDED Requirements

### Requirement: Belt v5 Maps Equal The Painter Goldens
Every Belt v5 map exported by UzPainter MUST equal the private Painter golden in native decoded values, unless an owner-approved exception in the register covers the difference.

#### Scenario: Belt v5 Tier 1
Given the Belt v5 stack JSON, resources and external mesh maps
When UzPainter rebuilds and exports the belt
Then each exported map equals the golden at native precision and two runs are byte-identical

### Requirement: Belt Round Completes Through MCP With Python Disabled
The complete Belt v5 round SHALL run through typed MCP tools against a supervisor started without `--allow-python`.

#### Scenario: Python-disabled round
Given a supervisor started without `--allow-python`
When the belt round (create, import, sync, save, export) runs through typed tools
Then it completes, `run_python` is never available, and the maps equal those of the Tier 1 run

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
