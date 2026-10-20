## ADDED Requirements

### Requirement: Requirement-To-Typed-Operation Matrix
The capability manifest SHALL include a matrix row for every required operation naming its requirement ids, typed tool, conformance fixture and status, and MUST mark any operation without a typed tool, or one that would need `run_python`, as a gap.

#### Scenario: Operation without a typed tool
Given a build in which mesh reload has no registered typed tool
When the capability manifest is generated
Then the mesh-reload row has status `capability gap` and is listed in `uzpainter://capabilities`

### Requirement: Matrix Completeness Is Enforced By The Build
The build MUST fail when a required operation has no row, a row names an unregistered tool, or an `available` row has no conformance fixture id.

#### Scenario: Fixture id missing
Given an `available` row for `export` without a conformance fixture id
When the build runs its checks
Then the build fails and names the row
