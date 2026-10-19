## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase5.2_packaging, phase5.4_parity-report (gates §3 onward; the §2 sanitisation items do not depend on the build and land before the release build is frozen in phase5.1_performance-budgets, otherwise phase5.2_packaging and phase5.4_parity-report reopen)

## 2. Sanitisation of the release tree (before the release build is frozen; normal edits, no authorization needed)
- [x] 2.1 This task edits `docs/analysis/` files as sanitisation targets and reads `docs/analysis/clean-room-redactions.md` as a scan list; it uses none of them as implementation inputs. Paraphrase the description column of `docs/analysis/substance-parity/01-python-api-inventory.md` in UzmiGames' own words, keeping module, symbol, signature and enum columns; no verbatim Adobe docstring sentence remains (done 2026-10-19, decision 304: 525 description cells and three prose lines rewritten; `tools/capabilities/painter-api-inventory.json` justification text checked too)
- [ ] 2.2 Update the file's entry in `docs/approved-sources.md` to the new revision through the itemised provenance audit (owner of the index: phase0.1_approved-source-index)
- [ ] 2.3 Scan the release tree for Adobe-derived content (documentation text, shader-library or MDL text, `.py` source text, Adobe binary signatures) and fix every finding at its source before the freeze

## 3. Recreated history
- [ ] 3.1 Record the released tree hash and confirm it is the tree of the build hash and dependency lock used by phase5.2_packaging and phase5.4_parity-report
- [ ] 3.2 Owner keeps a private backup bundle of the existing private history (never published)
- [ ] 3.3 Owner authorization for recreating the history and for the force push recorded (explicit, at execution time, naming the repository, the refs to publish and the released tree hash; decision 027) — destructive git operations; nothing in §3.4 onward starts without it
- [ ] 3.4 Build the recreated history in a separate clone outside the project tree from the sanitised released tree; final tree equals the released tree
- [ ] 3.5 Scan every blob reachable from every ref to be published: private-record guard (store-index hash match and public-schema validation), redaction markers and passages listed in `docs/analysis/clean-room-redactions.md`, Adobe file signatures, oracle-blob hashes from the private store index, off-limits and Adobe-derived content; zero findings
- [ ] 3.6 Verify tree equality between the recreated final commit and the released tree
- [ ] 3.7 Inspect the remote for refs a force push does not rewrite (pull-request refs, other branches, tags); if any would expose old history, raise it to the owner with `rulebook_task ask` before publication
- [ ] 3.8 Write the verification record `parity/reports/phase5/clean-history-verification.json`

## 4. Publication step (at the moment the repository is made public)
- [ ] 4.1 Force push of the verified history (under the authorization recorded in §3) to `uzmigames/uzpainter` for every published branch and tag, with the repository still private
- [ ] 4.2 Post-push verification on a fresh clone of the remote: every reachable blob re-scanned with zero findings and tree equality re-checked; result appended to the verification record

## 5. Tests
- [ ] 5.1 Scanner self-test in a temporary repository outside the project tree, with seeds taken from the private store and the redaction list and never committed: a redacted passage, an Adobe binary signature, a blob whose hash is in the private store index and a recorded JSON readback are each detected; independently authored files pass
- [ ] 5.2 Tree-equality check detects a one-byte difference and a missing file
- [x] 5.3 Inventory check: no description cell of the paraphrased inventory matches the documented Adobe text it replaced (compared on the owner's machine against the public documentation pages, result recorded as pass/fail only) — pass on 2026-10-19: `tests/sources/test_doc_overlap.py` against the local Painter 12.1 python-doc and javascript-doc (decision 304; skips where they are absent)

## 6. Acceptance
- [ ] 6.1 DAG gate met: no commit carries pre-sanitisation text or private oracle bytes; tree equality verified; the repository is not made public before this item passes (the visibility switch is done in phase5.6_gate-g5 after the owner signs)

## 7. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 7.1 Update or create documentation covering the implementation
- [ ] 7.2 Write tests covering the new behavior
- [ ] 7.3 Run tests and confirm they pass
