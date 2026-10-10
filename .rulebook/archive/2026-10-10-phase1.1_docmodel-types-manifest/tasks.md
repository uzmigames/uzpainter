## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.2_parity-contract

## 2. Implementation
- [x] 2.1 Implement the project, texture-set, stack and channel types with their constraints (power-of-two resolution 128–8192, one channel per `ChannelType`, nine `ChannelFormat`s, single tile 1001)
- [x] 2.2 Implement the layer, effect and source model of `docs/architecture/04-layer-stack-and-compositing.md` §1, including paint-plane references by `plane_id`
- [x] 2.3 Implement resources (SHA-256 key, `ResourceMeta`, `resource://` and `uzasset://` forms) and mesh-map bindings with `imported`/`baked` provenance and the `invalid` flag
- [x] 2.4 Implement 64-bit persistent ids for nodes, sets, stacks, tiles and resources
- [x] 2.5 Implement model validation: `NodeType` insertion rules and acyclic anchor references (`ValueError` on cycles)
- [x] 2.6 Implement the canonical JSON writer/reader with unknown-key preservation and the SHA-256 digest, and author `manifest.schema.json`
- [x] 2.7 Implement the result-record header type shared by all receipts

## 3. Tests
- [x] 3.1 Round trip of fixture documents covering every node kind, effect kind, source kind and both mesh-map provenance kinds: equal documents, equal digests
- [x] 3.2 Digest independent of in-memory insertion order of maps and identical across two processes
- [x] 3.3 Schema: serialised manifests validate; invalid ones (two channels of one type, resolution 3000, unknown `ChannelFormat`) are rejected
- [x] 3.4 Unknown manifest keys survive a load/save cycle verbatim
- [x] 3.5 Insertion-rule violations (a compare mask in a content stack, a group inside a mask stack) raise; an anchor cycle raises `ValueError`
- [x] 3.6 Ids persist through the round trip and two nodes with the same name keep distinct ids

## 4. Acceptance
- [x] 4.1 All tests of this child green on the hosted CPU lane

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
