## ADDED Requirements

### Requirement: Pipeline Scripts Run Unchanged Through The Adapter
The Python API package SHALL run the Assets3D scripts `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py` byte-unchanged through the UzmiGames pipeline adapter, and script paths needing capabilities not yet delivered MUST fail explicitly before mutation.

#### Scenario: Wand v1 end to end
Given one UzPainter build, the wand v1 inputs and the three scripts with pinned SHA-256 values
When the adapter runs create, sync and export
Then every script completes with its JSON result and no script file was modified

### Requirement: API Probe Goldens Exact
Every Tier 0 API probe (set→get readback, mask `None` rules, insertion rules, active-channel reset, event order) MUST match its private Painter golden exactly.

#### Scenario: Probe suite in a local run
Given the `phase0.6_tier0-api-probes` goldens in the private store on the owner's machine (decision 028)
When the full probe suite runs locally against the build
Then every probe result equals its golden and the comparison report lists zero differences

### Requirement: Parent Closes Only With All Children
The P1-PYAPI work package SHALL be accepted only when `phase1.19_pyapi-native-module`, `phase1.20_pyapi-facade`, `phase1.21_pyapi-dispatcher-lifecycle`, `phase1.22_pyapi-cli-capabilities` and `phase1.23_pyapi-pipeline-adapter` are all accepted.

#### Scenario: One child open
Given four accepted children and `phase1.23_pyapi-pipeline-adapter` still open
When acceptance of `phase1.24_python-api-facade` is requested
Then the parent stays open and the gate record names the open child
