## ADDED Requirements

### Requirement: Published History Carries No Pre-Sanitisation Or Oracle Content
Every blob reachable from every ref to be published MUST pass the private-record guard, the redaction-list scan, the Adobe-signature scan, the oracle-hash scan and the off-limits-content scan with zero findings before the repository is made public.

#### Scenario: Redacted passage in an old blob
Given a candidate history in which one intermediate commit still contains a passage listed in the redaction record
When the blob scan runs over all refs to be published
Then the scan reports the commit and blob and the history is not published

#### Scenario: Oracle blob in history
Given a candidate history containing a PNG whose SHA-256 is in the private store index
When the blob scan runs
Then the private-record guard flags it and verification fails

### Requirement: Recreated Tree Equals The Released Tree
The final commit of the recreated history SHALL have exactly the tree of the released build used by packaging verification and the final parity report.

#### Scenario: Tree mismatch
Given a recreated history whose final tree differs from the released tree by one file
When tree equality is verified
Then verification fails and names the differing path

### Requirement: History Rewrite Only With Recorded Owner Authorisation
The history MUST be recreated, and the private history replaced by force push, only after the owner's explicit authorisation covering both operations is recorded at execution time; the force push MUST happen only at the moment the repository is made public.

#### Scenario: No authorisation on record
Given a sanitised released tree and no recorded owner authorisation
When the history-recreation step is reached
Then no history is recreated, no force push is executed and the task stays open

#### Scenario: Sanitisation needs no authorisation
Given no recorded owner authorisation
When the API inventory is paraphrased and the release tree is scanned
Then both proceed as normal edits and reads

### Requirement: No Adobe Documentation Text In The Published Tree
The published tree MUST NOT contain Adobe documentation text; the API inventory SHALL keep symbol names, signatures and enum members and MUST describe them in UzmiGames' own words.

#### Scenario: Inventory description check
Given the paraphrased API inventory
When its description cells are compared with the public documentation pages on the owner's machine
Then no cell reproduces a documentation sentence verbatim
