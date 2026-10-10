## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.2_parity-contract

## 2. Children
- [ ] 2.1 Child accepted: phase0.3_oracle-store-cli (store, `parity fetch/verify/record`, self-hosted GPU runner)
- [ ] 2.2 Child accepted: phase0.4_oracle-store-guard (pre-commit and CI content guard)

## 3. Integration tests
- [ ] 3.1 On the owner's machine: record an authored sample with `parity record`, delete the local copy, `parity fetch` it by manifest and `parity verify` the hash
- [ ] 3.2 On the same commit: the guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-STORE): fetch/verify round trip on the owner's machine; guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
