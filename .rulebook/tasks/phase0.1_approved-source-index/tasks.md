## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0_owner-decisions

## 2. Implementation
- [ ] 2.1 Create `docs/approved-sources.md` with the entry format (identifier, category, revision/hash, licence, cleared scope, reviewer) and the quarantine section
- [ ] 2.2 Enter the public specifications and papers of `docs/licensing-and-clean-room.md` §2 and `07-preview-and-render-parity.md` §3.1, including NVIDIA's MDL specification, the BSD-3 MDL SDK and NVIDIA FLIP
- [ ] 2.3 Enter the public Adobe documentation used (python-doc pages, public help pages) with URL or path and retrieval date; record the admitted/not-admitted decision for `javascript-doc`
- [ ] 2.4 Enter the UzmiGames files cited by the architecture (Assets3D pipeline files, UzEngine sources for reading) with path and revision/hash
- [ ] 2.5 Run the itemised provenance audit of every `docs/analysis/` file cited by a top-level or architecture doc: per file the exact revision hash, provenance and cleared scope, or quarantine
- [ ] 2.6 Write the quarantine list: the off-limits sources of `docs/licensing-and-clean-room.md` §2 and every uncleared historical revision
- [ ] 2.7 Citation audit of `docs/architecture/*.md`, `docs/prd.md`, `docs/roadmap.md`, `docs/dag.md`: every citation resolves to an approved entry; uncleared citations marked historical context or replaced

## 3. Tests
- [ ] 3.1 Citation check: every source path or title cited in `docs/architecture/*.md` matches an index entry, and no cited entry is on the quarantine list
- [ ] 3.2 Revision check: every cleared `docs/analysis/` entry names a revision hash that exists in the repository history and matches the audited file content

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-SOURCES): index published; every architecture doc cites only approved sources

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
