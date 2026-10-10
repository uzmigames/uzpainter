## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.4_supervisor-worker, phase2.6_mcp-typed-tool-families

## 2. Implementation
- [ ] 2.1 Matrix row model `{operation, requirement ids, tool, conformance fixture id, status}` with statuses `available`, `capability gap`, `needs Python` (reported as a gap)
- [ ] 2.2 Rows for every INT-02 operation and every ARC-14 operation family, generated with the capability manifest at build time
- [ ] 2.3 Publication in `capabilities.json` and the `uzpainter://capabilities` resource
- [ ] 2.4 Build check: missing row, unregistered tool or available row without a fixture id fails the build

## 3. Tests
- [ ] 3.1 Completeness test: one row per INT-02 operation
- [ ] 3.2 Negative tests of the build check (row removed, tool unregistered, fixture id missing)
- [ ] 3.3 Status test: operations of families not in the build show `capability gap`; no row resolves to `run_python`

## 4. Acceptance
- [ ] 4.1 Every §3 test green and the matrix visible in `uzpainter://capabilities`; results attached to `phase2.8_mcp-server`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
