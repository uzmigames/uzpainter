## ADDED Requirements

### Requirement: Vendored render core builds standalone
The vendored render core MUST compile as a static library in UzPainter's own build without any UzEngine checkout, artifact, `runtime.lib`, submodule, pin or patch queue.

#### Scenario: Build on a machine without UzEngine
Given a clean machine with the UzPainter repository and no UzEngine checkout
When `build.zig` builds the vendored static library
Then the build succeeds

#### Scenario: Engine path is rejected
Given a build change that adds an include path into a UzEngine checkout
When the vendoring check runs
Then the check fails and names the external path

### Requirement: Vendored copy is attributed and traceable
The vendored copy MUST carry UzEngine's `LICENSE`, an `ORIGIN.md` naming the source commit for attribution only, a `MANIFEST.json` entry per file, a `MODIFICATIONS.md` entry per local change, and an entry in UzPainter's root `NOTICE`.

#### Scenario: Unrecorded drift fails
Given a vendored file whose hash differs from its manifest entry with no modification log entry
When the vendoring check runs
Then the check fails
