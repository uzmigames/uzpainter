## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.2_parity-contract

## 2. Children (each accepted before this parent closes)
- [x] 2.1 `phase1.1_docmodel-types-manifest` accepted
- [x] 2.2 `phase1.2_docmodel-transactions` accepted
- [x] 2.3 `phase1.2_docmodel-capability-manifest` accepted
- [x] 2.4 Expose the three parts as the `uzp_core` static library target in `build.zig`, with no dependency on the render layer or the GPU

## 3. Tests
- [x] 3.1 Integrated round trip: build a fixture document through transactions, serialise the manifest, reload it, and compare documents and digests
- [x] 3.2 Digest stability across two processes and two machines (hosted CPU lane and a local run on the owner's machine, decision 028) for the same fixture documents

## 4. Acceptance
- [x] 4.1 Acceptance (P1-DOCMODEL gate): round-trip tests green and digest stable; results recorded for the G1 gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
