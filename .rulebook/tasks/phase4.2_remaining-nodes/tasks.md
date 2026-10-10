## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery`

## 2. Children (mandatory; independent of each other)
- [ ] 2.1 Child accepted: `phase4.1_nodes-instances-anchors`
- [ ] 2.2 Child accepted: `phase4.1_nodes-mask-effects`
- [ ] 2.3 Child accepted: `phase4.1_nodes-projections`
- [ ] 2.4 Child accepted: `phase4.1_nodes-vector-font-sources`
- [ ] 2.5 Child accepted: `phase4.1_nodes-paint-layers`

## 3. Integration
- [ ] 3.1 Tier 0 corpus manifests under `parity/manifests/` list every new kind's goldens (recorded twice, blobs private, hashes public) and their fitted semantics under `parity/semantics/`
- [ ] 3.2 Regenerate the capability manifest: each new kind `supported` with tier evidence or an explicit `release-gap`; nothing silently a no-op
- [ ] 3.3 Requirement-to-typed-operation matrix: the stack-family rows for these kinds move to `available`, each naming its Python-disabled conformance fixture

## 4. Tests
- [ ] 4.1 Full extended Tier 0 corpus (Phase 1–3 goldens plus the new kinds) passes on the self-hosted GPU runner
- [ ] 4.2 A mixed recipe combining an instance, an anchor reference, a compare mask, a warp projection, a font source and a paint layer with a projected bitmap exports equal to its Painter golden and survives save/reopen
- [ ] 4.3 Python-disabled MCP conformance fixtures for the new kinds pass

## 5. Acceptance
- [ ] 5.1 DAG gate P4-NODES met: Tier 0 extended; manifest updated

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
