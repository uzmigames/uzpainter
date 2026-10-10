## ADDED Requirements

### Requirement: Amendment Only After G2 And Owner Signature
The Assets3D rule "painting is always in Substance" MUST be amended only after G2 is accepted and the owner has signed the amendment text.

#### Scenario: Edit before G2 is refused
Given G2 is not yet accepted
When the cutover work reaches the amendment item
Then no Assets3D file is edited and the item stays open

### Requirement: Scoped Amendment Keeps Painter As Oracle
The amendment SHALL scope UzPainter's role to the capabilities with status `supported` in the capability manifest, SHALL state that Painter remains the oracle and the tool for out-of-scope work until G5, and MUST NOT call UzPainter a full replacement while a required gap is open.

#### Scenario: Release gap stays with Painter
Given the capability manifest lists UV tiles as `release-gap`
When the amendment text is drafted
Then UV-tile work is named as out of scope and remains in Painter

### Requirement: Assets3D Repository Protocol
Every edit in the Assets3D repository made by this work MUST follow that repository's own collaboration and lock protocol and SHALL require the owner's approval.

#### Scenario: Locked file
Given the Assets3D governance file is held under that repository's lock by another collaborator
When the amendment is ready to apply
Then the edit waits for the lock under that protocol and is not forced

### Requirement: Adapter Refuses Failed Upstream Gates
The Assets3D adapter SHALL refuse a paint round whose upstream manifest gates did not pass or whose mesh certificate has `fail`, before any mutation, and SHALL flag diagnostic imports.

#### Scenario: Failed certificate
Given a round whose mesh certificate status is `fail`
When the adapter is invoked
Then it returns a structured refusal and the project revision is unchanged

### Requirement: Adapter Enforces The Amended Scope
The Assets3D adapter MUST refuse an operation outside the amended scope with a structured error that names Painter as the tool for it.

#### Scenario: Out-of-scope operation
Given an adapter request for an operation whose capability status is `release-gap`
When the adapter evaluates the request
Then it is refused with the out-of-scope error and nothing is executed

### Requirement: Adapter Writes Manifest Blocks On The Pilots
The Assets3D adapter SHALL write the `exportacao` block per export and the `painter_recipe`-equivalent block, and its checks MUST pass on wand v1, belt v5 and tunic v10.

#### Scenario: Tunic v10 round through the adapter
Given tunic v10 and its passed upstream gates
When the adapter runs the paint round and the export
Then both manifest blocks are written with valid schema and the round completes
