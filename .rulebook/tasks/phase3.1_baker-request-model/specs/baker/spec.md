# Baker — request model and ray-cast core

## ADDED Requirements

### Requirement: Painter-Shaped Bake Parameters
The bake parameter API SHALL expose `BakingParameters.common()`, `baker(usage)`, `set({Property: value})` and `Property.{value,name,short_name,label,widget_type,enum_values,enum_value,properties}` with key names, labels, widget types, enum labels and ranges equal to the Tier 0 discovery goldens, and enum integers MUST come from `enum_values()` labels.

#### Scenario: Property metadata probe
Given a fresh project with one texture set
When the probe reads `baker(MeshMapUsage.AO).keys()` and each property's `label()`, `widget_type()` and `enum_values()`
Then every value MUST equal the Tier 0 API-probe golden exactly

### Requirement: Authored Defaults With Provenance
`assets/defaults/baking.json` MUST be authored by UzmiGames with a provenance entry per key (public page or hash of the private observation), and every value MUST equal the private Painter 12.1.0 defaults capture on the self-hosted runner.

#### Scenario: Default drift
Given an entry of `assets/defaults/baking.json` whose value differs from the private capture it cites
When the defaults check runs on the owner's machine
Then the check MUST fail and name the key and the cited hash

### Requirement: Deterministic CPU Ray-Cast Core
`EmbreeBaker` SHALL use Hammersley sample addressing by texel index and sample id, a fixed reduction order and thread-count-independent tile partitioning, so one build and configuration MUST produce identical bytes regardless of thread count; an unqualified CPU/ISA configuration MUST receive an explicit capability error.

#### Scenario: Thread-count independence
Given the bevelled cube with highs and a fixed `BakeRequest`
When it is baked with 1 thread and with all hardware threads
Then the RAW maps and hit classifications MUST be byte-identical

#### Scenario: Unqualified ISA
Given a CPU configuration absent from the qualified Embree ISA set
When a bake is requested
Then the request MUST fail with a capability error before any work and nothing is bound

### Requirement: Shared Bake Semantics
The ray-cast core SHALL implement name matching with the three suffixes and `FilterMethod`, `LowAsHigh`, custom and distance-based cages, `IgnoreBackface`, `SubSampling` coverage accumulation and `DilationWidth`/`ApplyDiffusion` applied to the baked map only with RAW kept; the `Automatic` cage MUST be reported as a release gap until established against Painter.

#### Scenario: Dilation keeps RAW
Given a bake with `DilationWidth` 8
When the bake completes
Then the RAW map MUST contain no dilated texels and the baked map MUST differ from RAW only outside the used surface

#### Scenario: Automatic cage requested
Given `CageMode` set to `Automatic`
When a bake is requested
Then the request MUST raise an explicit capability error naming the release gap

### Requirement: Linked Set Settings Transaction
A settings change on a linked group SHALL apply as one transaction across every linked texture set.

#### Scenario: Failure on one linked set
Given two texture sets in one linked group
When `set_linked_group_common_parameters` fails validation for one set
Then neither set's bake settings MUST change and the revision MUST NOT advance
