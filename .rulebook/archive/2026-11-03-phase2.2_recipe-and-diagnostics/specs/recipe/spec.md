## ADDED Requirements

### Requirement: Wand Rebuild From Dump Is Equal
The wand v1 project rebuilt from its recipe dump and referenced resources MUST export files byte-identical to the original and MUST produce the same recipe digest.

#### Scenario: Wand v1 rebuild
Given the wand v1 project and its recipe dump
When a new project is rebuilt from the dump and both are exported with the wand's export configuration
Then every exported file is byte-identical and both recipe digests are equal
