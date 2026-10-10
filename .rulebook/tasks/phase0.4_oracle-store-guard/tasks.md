## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.2_parity-contract, phase0.3_oracle-store-cli

## 2. Implementation
- [ ] 2.1 Guard hash rule: reject any staged or committed file whose SHA-256 is in the private store index
- [ ] 2.2 Guard schema rule: reject any JSON data file under `parity/` that does not validate against its public schema
- [ ] 2.3 Wire the guard as a pre-commit hook and as a CI check on every commit; hosted CI receives the hash index only, never blobs
- [ ] 2.4 Test fixtures: authored fixture image and authored expectation JSON committed; recorded PNG and recorded JSON readback kept outside the repository and hash-indexed

## 3. Tests
- [ ] 3.1 Guard blocks the recorded PNG
- [ ] 3.2 Guard blocks the recorded JSON readback, including a re-serialised copy that fails the public schema
- [ ] 3.3 Guard passes the authored fixture image and the authored expectation JSON
- [ ] 3.4 Guard runs in CI on a commit and fails the job when a blocked file is present

## 4. Acceptance
- [ ] 4.1 Acceptance (P0-STORE, second clause): guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
