## ADDED Requirements

### Requirement: Typed project model with persistent ids
The document model SHALL represent every element of `docs/architecture/03-project-model.md` §1 and `docs/architecture/04-layer-stack-and-compositing.md` §1 and MUST give every node, set, stack, tile and resource a 64-bit id that persists in the manifest.

#### Scenario: Same-named nodes
Given two fill layers both named `M_piping` in one stack
When the document is serialised and reloaded
Then both layers keep their distinct ids and names

### Requirement: Canonical manifest and digest
The manifest SHALL be written in a canonical JSON form whose SHA-256 digest is independent of in-memory ordering, MUST validate against `manifest.schema.json`, and SHALL preserve unknown keys verbatim.

#### Scenario: Unknown key preserved
Given a manifest containing a key unknown to this version
When it is loaded and saved again
Then the key and its value are present unchanged and the schema still validates

### Requirement: Model validation of structure
The model MUST reject a node inserted where the documented `NodeType` rules forbid it and SHALL raise `ValueError` on an anchor-reference cycle.

#### Scenario: Mask-only node in a content stack
Given a content stack
When a compare-mask effect is inserted into it
Then the insertion is rejected and the document is unchanged
