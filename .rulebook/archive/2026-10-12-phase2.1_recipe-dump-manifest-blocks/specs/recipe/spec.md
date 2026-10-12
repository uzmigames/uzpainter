## ADDED Requirements

### Requirement: Deterministic Recipe Dump
`dump_recipe()` SHALL return every output-determining field of the project with a SHA-256 digest of its canonical JSON, and the digest MUST change only when output-determining state changes.

#### Scenario: Save and reopen
Given a project whose recipe digest is D
When the project is saved, closed and reopened in a new session
Then `dump_recipe()` returns digest D again

#### Scenario: Inert state changed
Given a project whose recipe digest is D
When only the layer selection changes
Then the digest is still D

### Requirement: Inspect Without Opening
`uzpainter inspect <file.uzp>` SHALL print the same recipe JSON as `dump_recipe()` for that revision without a GPU and without taking the project lock.

#### Scenario: Inspect a locked project
Given a project open in a worker
When `uzpainter inspect` runs on its file
Then it prints the recipe of the last committed revision and the worker's lock is untouched

### Requirement: Rebuild From Dump Reproduces Exports
A project rebuilt from a recipe dump and its referenced resources MUST export maps identical to the original's.

#### Scenario: Synthetic rebuild
Given a synthetic project and its dump
When a new project is rebuilt from the dump and both export with the same configuration
Then every exported file is byte-identical

### Requirement: Export Receipts Carry The exportacao Block
Every export receipt SHALL contain the `exportacao` block with `fontes`, `saidas`, `momento`, `preset`, `mapas`, `comparacao`, `evidencias` and `pendencias`.

#### Scenario: Export receipt
Given a completed export
When its receipt is validated against the schema
Then the `exportacao` block is present and valid
