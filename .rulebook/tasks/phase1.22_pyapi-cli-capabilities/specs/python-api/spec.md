## ADDED Requirements

### Requirement: Run Hosts A Script With A JSON Result
`UzPainter.exe run <script.py>` SHALL execute the script in the worker role of a single process and return the value assigned to `result` as JSON together with captured stdout and stderr.

#### Scenario: Script returns a result
Given a script that prints a line and assigns `result = {"maps": 4}`
When the operator runs `UzPainter.exe run script.py`
Then the output carries a `UZP_JSON:` line with the result, the captured stdout and stderr, and the exit code is 0

### Requirement: Script Failure Is Structured
An uncaught exception in a script run by `run` MUST produce a structured failure with the traceback and a non-zero exit code, and MUST NOT be reported as success.

#### Scenario: Script raises
Given a script that raises `ValueError("bad stack")` after one committed call
When the operator runs it
Then the output is a structured failure with the traceback and the last committed revision, and the exit code is non-zero

### Requirement: Supported Requires Evidence
A capability entry SHALL be `supported` only when it cites Tier 0 evidence: set→get readback through a freshly resolved handle, persistence after save and reopen, and a golden comparison for output-affecting symbols.

#### Scenario: Entry without evidence
Given a Phase 1 symbol marked `supported` without a Tier 0 evidence id
When the capability manifest is generated
Then generation fails naming that symbol

### Requirement: Manifest Matches Behaviour
Every public symbol of `uzpainter` and `substance_painter` MUST have a manifest entry; every `desktop-only-omitted` entry MUST raise `UnsupportedInUzPainter`, and every `release-gap` entry MUST raise `NotYetSupported` before any mutation.

#### Scenario: Gap symbol called
Given `substance_painter.baking` operations marked `release-gap` in Phase 1
When the conformance test calls one on an open project
Then `NotYetSupported` is raised and the revision is unchanged

#### Scenario: Symbol missing from the manifest
Given a new public function added to `uzpainter.layerstack` without a manifest entry
When the conformance test runs
Then it fails naming the unlisted symbol

### Requirement: Capabilities Printable
`uzpainter capabilities` SHALL print the shipped manifest, and `uzpainter.capabilities.profile()` MUST return `painter-12.1-api-0.3.7`.

#### Scenario: Agent reads capabilities
Given an installed build
When `uzpainter capabilities` runs
Then the printed manifest validates against `capabilities.schema.json`
