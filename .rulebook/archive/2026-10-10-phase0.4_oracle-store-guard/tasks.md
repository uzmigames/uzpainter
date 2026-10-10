## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.2_parity-contract, phase0.3_oracle-store-cli

## 2. Implementation
- [x] 2.1 Guard hash rule: reject any staged or committed file whose SHA-256 is in the private store index
- [x] 2.2 Guard schema rule: reject any JSON data file under `parity/` that does not validate against its public schema
- [x] 2.3 Wire the guard as a pre-commit hook and as a CI check on every commit; hosted CI receives the hash index only, never blobs (decision 028: hosted CI receives no index at all and runs the content and schema rules; `--index FILE` takes an index without blobs; `parity/GUARD.md` §5)
- [x] 2.4 Test fixtures: authored fixture image and authored expectation JSON committed; recorded PNG and recorded JSON readback kept outside the repository and hash-indexed

## 3. Tests
- [x] 3.1 Guard blocks the recorded PNG
- [x] 3.2 Guard blocks the recorded JSON readback, including a re-serialised copy that fails the public schema
- [x] 3.3 Guard passes the authored fixture image and the authored expectation JSON
- [x] 3.4 Guard runs in CI on a commit and fails the job when a blocked file is present

## 4. Acceptance
- [x] 4.1 Acceptance (P0-STORE, second clause): guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
