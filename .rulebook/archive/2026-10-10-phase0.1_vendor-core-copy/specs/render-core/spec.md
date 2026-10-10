## ADDED Requirements

### Requirement: Copy from a clean commit object
The render core MUST be exported from a commit object on UzEngine's `main` branch identified by its full hash, never from a working tree, and the selected commit SHALL be the newest one that passes the conflict-marker, include-closure and behaviour re-verification checks.

#### Scenario: Working tree with uncommitted edits is not a source
Given a UzEngine checkout with uncommitted edits
When the render core is vendored
Then the files come from `git archive` of a selected commit hash and `ORIGIN.md` records that hash and the check evidence

#### Scenario: Candidate with conflict markers rejected
Given a candidate commit whose exported RHI file contains a conflict marker
When the selection checks run
Then the candidate is rejected and an older passing commit is considered

### Requirement: Verbatim files equal upstream
Every file copied without modification SHALL be byte-equal to the file at the selected commit, and `MANIFEST.json` MUST record its upstream path, vendored path, commit, blob SHA-1, upstream and vendored SHA-256, status and modification ids.

#### Scenario: Manifest hashes match the commit
Given the vendored folder and the selected commit
When the byte-equality test runs
Then every verbatim entry has equal upstream and vendored SHA-256 and a blob SHA-1 equal to the commit's tree entry

### Requirement: Only the declared subset is copied
The vendored folder MUST contain exactly the include closure of the declared subset and SHALL NOT contain any excluded path, including the glTF mesh-cook files that carry the 32/48-byte stride defect.

#### Scenario: Excluded mesh path absent
Given the exclusion list of `13-engine-integration.md` §2.4
When the vendored folder is scanned
Then no file under `asset/importers/`, `renderer/` or `asset/formats/uzmesh_format.*` is present

### Requirement: Licence and attribution travel with the copy
The copy MUST include UzEngine's `LICENSE` at the selected commit, and UzPainter's root `NOTICE` SHALL name the vendored UzEngine code, its copyright line and the selected commit, reproducing any upstream `NOTICE` attribution present at that commit.

#### Scenario: Attribution recorded
Given the selected commit has no `NOTICE` file
When the copy is imported
Then `thirdparty/uzengine-render-core/LICENSE` is present and the root `NOTICE` names UzEngine, "Copyright 2026 Uzmi Games" and the commit hash
