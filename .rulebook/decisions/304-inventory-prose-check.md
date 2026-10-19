# 304. The API inventory's prose is UzmiGames' own wording, checked against the local public documentation by a deterministic overlap test (six-word runs, whole short cells, 60% four-word coverage); scope is the inventory the task names plus the capability inventory's notes

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase5.5_clean-history

## Context

Items 2.1 and 5.3 of `phase5.5_clean-history` require the description column of `docs/analysis/substance-parity/01-python-api-inventory.md` to be rewritten in UzmiGames' own words, with no verbatim Adobe docstring sentence left. Item 5.3 adds a check on the owner's machine against the public documentation pages, recorded as pass or fail only. The task's section 2 permits this sanitisation before the build freeze, without owner authorisation (supervisor note SUP-014).

The task defines no checker, and several choices were open:
- what counts as a copy;
- which text is compared;
- how far beyond the named file the edit goes.

A model panel (GPT-6 Astra, Kimi K3) reviewed the proposal on 2026-10-19:
- both agreed on the scope (claims 3 and 4);
- both rated the thresholds "partly": a sound regression gate, but not proof of independent authorship;
- GPT-6 Astra warned that excluding every code span is a bypass;
- both warned that a test which skips without the documentation protects nothing.

## Decision

1. **Wording.** All 525 description cells that came from docstrings were rewritten, along with three prose lines: the conventions bullet and cross-cutting facts 3 and 7. These columns are unchanged: Symbol, Kind, and Signature / fields / members. Module, symbol, signature, parameter and enum-member names are also kept. Our own notes stay as they were: inherited members, redaction markers and HTML-signature notes. Deprecation markers keep their version and name the replacement as code.
2. **Checker.** `tools/sources/doc_overlap.py` (`python -m tools.sources.doc_overlap`) reads the python-doc and javascript-doc HTML of the local install at run time. Words are normalised to lower-case `[a-z0-9]` runs. A code span is skipped only when it reads as code: one token, or code punctuation. A span of plain words is checked as prose. A cell fails if any of these holds:
   - it holds a run of 6 or more words that occurs in the documentation;
   - it has 3 to 5 words and the whole cell occurs in one page;
   - it has 8 or more words and at least 60% of them lie inside 4-word documentation phrases.
3. **Calibration.** The rules flag 487 cells of the pre-sanitisation inventory and none of the rewritten one. Lowering the run to 5 words flags only generic domain phrases such as "description of the UV Tile". The output names the documentation compared against: its page count and the SHA-256 of the normalised pages. Painter updates move this documentation.
4. **Test.** `tests/sources/test_doc_overlap.py` asserts zero findings on the checked files and runs the detection self-tests. Each self-test cuts its span out of the local pages at run time, so the repository holds no Adobe text:
   - a verbatim span;
   - a sentence with every fifth word replaced;
   - a whole short cell;
   - prose wrapped in backticks.

   Independent wording and identifier spans pass. Without the documentation the tests skip with the reason, like the other python-doc tests. Item 5.3's pass or fail is therefore valid only on a machine where the tests ran rather than skipped, which is the owner's machine.
5. **Scope.**
   - Checked: the inventory named by the task, and the `notes` and `justification` text of `tools/capabilities/painter-api-inventory.json`. One justification shared a 6-word run and was reworded.
   - Not checked here: `tools/parity/recorder/documented_symbols.json` has no per-symbol prose, so it is out of scope.
   - Left to item 2.3, the release-tree scan: other `docs/analysis/` files that the checker shows still quote documentation text. These are the substance-parity analyses 02 to 08 and the substance-parity review.
   - Not done: the inventory's index entry stays quarantined (QH-SP-INVENTORY). Admitting a revision is item 2.2's itemised provenance audit.

## Limits

- The check catches copying and close paraphrase of the compared pages. It does not prove independent authorship, and it does not cover 1- and 2-word cells or Adobe's web pages.
- Adobe's web pages carry the same API text as the shipped python-doc.
- No parity rule, product behaviour or git history changes.
