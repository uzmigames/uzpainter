## ADDED Requirements

### Requirement: Configuration compiled into a typed plan
Painter's export configuration SHALL be accepted verbatim and compiled into a typed plan before any GPU work; every parameter MUST be defined after resolution or the configuration SHALL be rejected as invalid.

#### Scenario: Unresolved parameter
Given a configuration whose map has no `bitDepth` from its preset or any matching rule
When it is compiled
Then compilation fails naming the map and the missing parameter and nothing is written

### Requirement: Unknown identifiers and formats refused early
An unknown map identifier MUST be rejected with the valid alternatives, and a format that is not supported in this build SHALL raise before anything is written.

#### Scenario: Pipeline typo
Given a configuration naming `Mixed_AO`
When it is compiled
Then it is rejected and the error lists `AO_Mixed`

### Requirement: Dry run equals the export
`list_project_textures` and `uzpainter.export.plan` SHALL return exactly the files the export would write.

#### Scenario: Dry run then export
Given a configuration over two texture sets
When the dry run is taken and the export is executed
Then the written files equal the dry-run list
