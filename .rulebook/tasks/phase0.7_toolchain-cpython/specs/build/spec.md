## ADDED Requirements

### Requirement: Embedded CPython boundary qualified
`selftest` MUST start the embedded CPython 3.13 interpreter, import the statically linked `uzpainter` module, round-trip a 16-bit buffer byte for byte, and carry exceptions across the boundary in both directions with type and message preserved.

#### Scenario: Boundary green on the owner's machine
Given the Zig-built `UzPainter.exe` with the vendored CPython embeddable package
When `selftest` runs its CPython stages
Then the interpreter starts, `uzpainter` imports, every 16-bit value survives the round trip and both exception directions keep type and message

### Requirement: Isolated interpreter
The embedded interpreter SHALL load modules only from its vendored `python313.zip` and `Lib\site-packages\`, and MUST ignore `PYTHONPATH`, the user site-packages and any installed Python.

#### Scenario: Conflicting user module ignored
Given `PYTHONPATH` pointing to a folder with a module named `mcp`
When the embedded interpreter imports `mcp`
Then the vendored MCP SDK is imported

### Requirement: Vendored MCP SDK importable and inventoried
The pinned official MCP SDK wheel closure MUST import in the embedded interpreter, and every wheel SHALL have its licence, notices and SHA-256 recorded in the dependency inventory.

#### Scenario: Native wheel loads
Given the pinned closure including native `cp313-win_amd64` wheels
When `selftest` imports the MCP SDK
Then the import succeeds and each wheel's recorded SHA-256 matches the file

### Requirement: Fallback and toolchain decision procedure
When a CPython stage fails, the Python-facing layer MUST be rebuilt as a separate DLL with a C ABI under the same Zig and the stages rerun; a toolchain change SHALL be made only on recorded evidence that both routes fail or that `python313.dll` cannot be used from a Zig-built executable, and only after the owner updates decision 021.

#### Scenario: Direct route fails, fallback passes
Given the direct embedding fails the exception stage
When the C-ABI fallback DLL is built and the stages rerun
Then the stages pass, the report records the fallback route and the toolchain stays Zig

#### Scenario: Both routes fail
Given both the direct route and the C-ABI fallback fail
When the evidence is recorded
Then the failing `selftest` output is attached and the toolchain change waits for the owner's update of decision 021
