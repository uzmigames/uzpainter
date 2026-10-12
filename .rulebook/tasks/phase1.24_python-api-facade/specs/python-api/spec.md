## ADDED Requirements

### Requirement: Pipeline Scripts Run Unchanged Through The Adapter
The Python API package SHALL run the Assets3D scripts `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py` byte-unchanged through the UzmiGames pipeline adapter. Unsupported API calls MUST fail explicitly before mutating the project; earlier successful calls in the script remain committed (a script is not one atomic transaction). The parity of the exported maps is not part of this requirement: it is accepted by `phase1.25_pilot-wand`.

#### Scenario: Wand v1 through the adapter
Given one UzPainter build, the wand v1 inputs and the three scripts with pinned SHA-256 values
When the adapter runs create, sync and export
Then create and sync complete with their JSON results, export runs its pinned bytes and either completes with its result or, while the 16-bit export of sRGB8 material channels is a release gap owned by `phase1.25_pilot-wand` item 2.6, fails with `NotYetSupported` before writing any map file (the script has already saved the project), and no script file was modified

### Requirement: API Probe Goldens Exact
Every output of the Tier 0 API probes (set→get readback, mask `None` rules, insertion rules, active-channel reset, event order) in the supported scope MUST equal its private Painter golden exactly. An output outside the supported scope MUST be listed with its kind and its existing owner (`parity/reports/phase1/python-api-facade.md` §3). The API MUST refuse an unsupported step with `NotYetSupported` before any change instead of returning a value. A known divergence that still returns a value MUST be listed as such, and its test MUST require it to still differ, so it is never waived silently.

#### Scenario: Probe suite in a local run
Given the `phase0.6_tier0-api-probes` goldens in the private store on the owner's machine (decision 028)
When the full probe suite runs locally against the build
Then every output in the supported scope equals its golden, and every other output is one the report lists with its owner

### Requirement: Parent Closes Only With All Children
The P1-PYAPI work package SHALL be accepted only when `phase1.19_pyapi-native-module`, `phase1.20_pyapi-facade`, `phase1.21_pyapi-dispatcher-lifecycle`, `phase1.22_pyapi-cli-capabilities` and `phase1.23_pyapi-pipeline-adapter` are all accepted.

#### Scenario: One child open
Given four accepted children and `phase1.23_pyapi-pipeline-adapter` still open
When acceptance of `phase1.24_python-api-facade` is requested
Then the parent stays open and the gate record names the open child
