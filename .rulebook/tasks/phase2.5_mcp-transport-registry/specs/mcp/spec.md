## ADDED Requirements

### Requirement: Loopback HTTP With Origin And Token
In HTTP mode the server SHALL bind only to a loopback address unless `--allow-remote` is given and MUST reject requests with an invalid Origin or a missing or wrong bearer token.

#### Scenario: Request without token
Given a server started with `--mcp-http 127.0.0.1:7777`
When a client calls a tool without the bearer token
Then the request is rejected and no tool runs

### Requirement: Inputs Validated Before Admission
The server MUST validate every tool input against its schema (numeric bounds, enums, object references) before the call is admitted.

#### Scenario: Out-of-range resolution
Given an open project
When `set_resolution` is called with a value outside 128–8192
Then the call fails with a validation error and nothing reaches the worker

### Requirement: Paths Confined To Roots
Every path argument SHALL be canonicalised and MUST lie under the root of its operation; results MUST NOT reference paths outside the roots.

#### Scenario: Escape through a relative path
Given `--roots export=E:\Exports`
When `export` is called with `output_dir` `E:\Exports\..\Windows`
Then the call fails before mutation and the error does not echo the resolved outside path

### Requirement: run_python Only By Opt-In
`run_python` SHALL be registered only when the supervisor starts with `--allow-python` and MUST be absent from the tool list otherwise.

#### Scenario: Default start
Given a supervisor started without `--allow-python`
When a client lists tools
Then `run_python` is not listed and a direct call is rejected

### Requirement: Generated Key And Precondition Are Returned
When a mutating call omits both `idempotency_key` and `expected_revision`, the supervisor SHALL generate the key, resolve the precondition once before submission and return both in every receipt; a call that supplies a key MUST supply its original `expected_revision`.

#### Scenario: Call without key
Given an open project at revision 12
When `layer_set` is called without key and precondition
Then the receipt carries a generated key and `expected_revision` 12 for retries
