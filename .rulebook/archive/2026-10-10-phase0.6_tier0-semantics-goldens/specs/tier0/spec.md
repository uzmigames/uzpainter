## ADDED Requirements

### Requirement: Tier 0 semantics goldens cover the settlement list
The Tier 0 semantics corpus MUST contain goldens for every item of `04-layer-stack-and-compositing.md` §9 — blend formulas and spaces, quantisation points, stack base values, mask precision, group `Normal`/`PassThrough` with masks, content-effect order, levels clamp, the `BilinearHQ` kernel, height→normal methods and strength, and the `AO_Mixed` operator — on UzmiGames-authored synthetic meshes.

#### Scenario: Coverage check
Given the public manifest `parity/manifests/phase0/tier0-semantics.json`
When each §9 item is looked up
Then at least one golden id covers it

#### Scenario: Quantisation experiment present
Given a channel storage format used by the templates
When the corpus is recorded
Then it contains the three-1/3-opacity-fills golden for that format

### Requirement: Recorded through the documented API at native depth
Each golden SHALL be produced by a UzmiGames instruction sequence using only Painter's documented Python API and exported through `export_project_textures` at 16 bit or float, and MUST be recorded at least twice (same session; after save/reopen).

#### Scenario: Two recordings per golden
Given a blend-sweep golden
When it is recorded
Then the manifest lists one recording from the same session and one after save/reopen, each with its SHA-256

### Requirement: Blobs private, hashes public
Recorded outputs MUST be stored only in the private store; the public manifest SHALL contain only authored inputs, instruction sequences, applied settings, software identities and the SHA-256 of each private record.

#### Scenario: Verify round trip
Given the public manifest and the owner's private store
When `uzpainter parity verify` runs
Then every listed hash resolves to a stored blob with a matching digest

#### Scenario: Recorded export not committed
Given a recorded 16-bit export of a golden
When it is staged for commit
Then the repository guard rejects it
