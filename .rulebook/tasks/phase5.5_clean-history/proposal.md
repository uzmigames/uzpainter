# Proposal: phase5.5_clean-history

## Why
P5-HISTORY in `docs/dag.md` (critical path), implementing decision 027 and the first publication release criterion of `docs/licensing-and-clean-room.md` §5 (with §1.1 and §1.5): the private repository `uzmigames/uzpainter` (first commit `6d7c297`) contains pre-sanitisation analysis text, so before it is made public its history is recreated clean and published by a force push at that moment, only under the owner's explicit authorisation; nobody rewrites history before that moment. The tree to be published must also carry no Adobe documentation text: the Substance API inventory `docs/analysis/substance-parity/01-python-api-inventory.md` currently copies Adobe docstrings verbatim in its description column. Requirements: LIC-03, CLR-04, CLR-05 and release criterion 8 of `docs/prd.md` §18. Gate rule (`docs/dag.md`): the clean-history item is verified against the same released tree as `phase5.2_packaging` and `phase5.4_parity-report`, and the repository is not made public before this item passes.

## What Changes
- Scope note: this task edits `docs/analysis/` files as sanitisation targets and reads `docs/analysis/clean-room-redactions.md` as a scan list; it uses none of them as implementation inputs.
- Description column of `docs/analysis/substance-parity/01-python-api-inventory.md` paraphrased in UzmiGames' own words; module, symbol, signature and enum columns kept (documented API shape is allowed, licensing §1.4); no sentence of Adobe documentation text remains. The file is edited as a sanitisation target, not used as an implementation input; its entry in `docs/approved-sources.md` is updated to the new revision through the provenance audit of `phase0.1_approved-source-index`.
- Scan of the release tree for Adobe-derived content (Adobe documentation text, shader-library or MDL text, `.py` source text, Adobe binary signatures `.spp`/`.spexp`/`.spt`/`.spsm`/`.spmsk`/`.sbsar`) before the release build is frozen.
- Recreated history of `uzmigames/uzpainter` built in a separate clone outside the project tree from the sanitised released tree; the final tree equals the released tree (the tree of the build hash shared by `phase5.2_packaging` and `phase5.4_parity-report`). The existing private history is kept by the owner as a private backup bundle, never published.
- Scan of every blob reachable from every ref to be published (branches and tags), not only the final tree: the private-record guard of `phase0.5_private-oracle-store` (hash match against the private store index and public-schema validation), redaction markers and the passages listed in `docs/analysis/clean-room-redactions.md` (used as the scan list), Adobe file signatures, oracle-blob hashes from the private store index, and off-limits or Adobe-derived content.
- Check of remote refs that a force push does not rewrite (for example pull-request refs) and of other branches and tags; any such ref exposing old history is reported to the owner before publication.
- Verification record `parity/reports/phase5/clean-history-verification.json`: refs to publish, commit and blob counts scanned, scanner identities and versions, findings (zero required), released tree hash, recreated tree hash, verifier, date.
- Owner's explicit authorisation recorded at execution time, before the history is recreated, covering both destructive git operations: recreating the history and the force push (decision 027). The paraphrase and the blob scans are normal edits and reads and need no authorisation.
- At the moment the repository is made public: the force push of the verified history (repository still private until then), then a post-push verification on a fresh clone of the remote. The visibility switch to public belongs to `phase5.6_gate-g5` after the owner signs.

## Dependencies
- DAG inputs: `phase5.2_packaging` (P5-PACKAGE) and `phase5.4_parity-report` (P5-REPORT), which fix the released tree, build hash and dependency lock.
- Sanitisation items (paraphrase, tree scan) do not depend on the build and must land before the release build is frozen (`phase5.1_performance-budgets`); a later change to the tree reopens `phase5.2_packaging` and `phase5.4_parity-report` (gate rule).
- Uses: the private-record guard and store index (`phase0.5_private-oracle-store`), the approved-source index (`phase0.1_approved-source-index`).
- Consumer: `phase5.6_gate-g5` (G5).

## Acceptance
DAG gate: no commit carries pre-sanitisation text or private oracle bytes; tree equality verified; the repository is not made public before this item passes. In addition: the inventory's description column contains no verbatim Adobe documentation text; every blob reachable from the published refs passes every scan; the owner's authorisation covering history recreation and the force push is recorded before the history is recreated; the post-push verification on a fresh clone repeats the scan and tree equality with zero findings.

## Impact
- Affected specs: `history` (clean publication history)
- Affected code: none in the product; release tooling (history recreation and blob scanners), `docs/analysis/substance-parity/01-python-api-inventory.md`, `docs/approved-sources.md`
- Breaking change: NO (the private history is replaced only at publication, under owner authorisation; a private backup bundle keeps it)
- User benefit: the repository can be made public without exposing pre-sanitisation text, Adobe text or private oracle data
