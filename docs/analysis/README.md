# Analyses, reviews and the architecture discussion

Source-cited analyses written before the architecture (2026-10-09/10), the independent technical reviews by Astra (GPT-based, run through Codex), the responses that corrected the analyses, and the architecture discussion that produced the final `docs/` set. These files are historical evidence: the build contract is `docs/`.

Clean-room note (decision 002, `docs/licensing-and-clean-room.md`): some of these files cite Adobe's shipped shader library, shader sources or `.py` sources as evidence. Those citations identify files that are off-limits for implementation. The sanitisation pass that removed descriptions of their internals is complete and itemised in `clean-room-redactions.md` (102 redactions by file and category, plus the borderline passages kept and why; its scope is every file here except `architecture-discussion/05-resolution.md`). These files are still not implementation inputs until an itemised clean-room provenance audit approves their exact revision in the approved-source index (`docs/approved-sources.md`, work package `P0-SOURCES`). Do not use descriptions derived from off-limits implementation files, including descriptions repeated by an intermediary. Do not open the cited Adobe files; use the public API documentation and Painter's observable outputs instead.

## Analyses

| Folder | Files | Topic |
|---|---|---|
| `substance-parity/` | `01-python-api-inventory.md` (API symbol inventory from the public docs), `02-layer-stack-model.md`, `03-baking.md`, `04-export.md`, `05-project-and-spp.md`, `06-mcp-tools-inventory.md` (community bridge, incl. §9 known defects), `07-parity-matrix.md` (147 rows), `08-review-response.md` | What Painter 12.1.0 exposes and how the community bridge used it |
| `assets3d-pipeline/` | `01-pipeline-overview.md` … `07-lessons-and-pitfalls.md`, `08-requirements-for-uzpainter.md` (the requirement source of `docs/prd.md`), `09-review-response.md` | How Painter is used today in Assets3D and the derived requirements |
| `uzengine-renderer/` | `01-module-map.md` … `09-gaps-and-risks.md`, `10-review-response.md` | What UzEngine provides and lacks for a texturing tool |
| `technology-options/` | `01-python-embedding-and-packaging.md`, `02-texture-compression-and-containers.md`, `03-project-container-format.md`, `04-mcp-server-options.md`, `05-review-response.md` | Python embedding, compression, containers, MCP |

## Clean-room record

| File | Content |
|---|---|
| `clean-room-redactions.md` | Record of the sanitisation pass of 2026-10-10: redaction categories, per-file counts, every redaction with its location, and the borderline passages kept with the reason |

## Reviews (Astra)

| File | Scope |
|---|---|
| `reviews/substance-parity-astra-review.md` | 20 findings, 81 fact validations, 140 matrix dispositions |
| `reviews/assets3d-pipeline-astra-review.md` | 15 findings, 67 sample claims, requirement re-classification, 20 questions |
| `reviews/uzengine-renderer-astra-review.md` | 20 findings, 48 ledger claims (3 blockers: parity contract, baseline, stride defect) |
| `reviews/technology-options-astra-review.md` | 32 findings, 10 missing options |
| `reviews/docs-set-astra-review.md` | Final review of the `docs/` set: 24 document verdicts, 23 findings (3 blockers: F01 preset provenance, F02 storage-document internals, F03 recorded oracle data shown as public), licence audit, remaining disagreements |
| `reviews/docs-set-astra-verification.md` | Verification of the round-4 corrections: 21 findings closed, R01 (idempotency after pruning) and R02 (fixed-name export delivery) partial, new N01 (migration exclusions), N02 (revert raster binding), N03 (MCP acceptance by milestone), N04 (Phase 2 capture modes); all corrected in the architecture docs, PRD, roadmap and DAG |

## Review responses

| File | Answers |
|---|---|
| `substance-parity/08-review-response.md` | `reviews/substance-parity-astra-review.md` |
| `assets3d-pipeline/09-review-response.md` | `reviews/assets3d-pipeline-astra-review.md` |
| `uzengine-renderer/10-review-response.md` | `reviews/uzengine-renderer-astra-review.md` |
| `technology-options/05-review-response.md` | `reviews/technology-options-astra-review.md` |

Each response gives a per-finding disposition and the corrections applied to its analyses. The findings of `reviews/docs-set-astra-review.md` are dispositioned in `architecture-discussion/06-round4-changes.md`.

## Architecture discussion

| File | Author | Content |
|---|---|---|
| `architecture-discussion/01-claude-proposal.md` | Claude | Round 1 independent proposal, D1–D14 |
| `architecture-discussion/02-astra-position.md` | Astra | Round 1 independent position, D1–D14 |
| `architecture-discussion/03-claude-reconciliation.md` | Claude | Round 2 reconciliation of 01 with 02 |
| `architecture-discussion/04-astra-critique.md` | Astra | Round 2 critique of 01 |
| `architecture-discussion/05-resolution.md` | Claude | Round 3 resolution: final table, crossings settled, disagreements answered, owner questions, facts from the responses, owner decision 002 applied. Parts are superseded by the owner's answers of 2026-10-10 (header note) |
| `architecture-discussion/06-round4-changes.md` | Claude | Round 4 change record: the owner's answers of 2026-10-10 and the docs-set review findings applied to the final set |

## Decision records

`.rulebook/decisions/001-…` output parity (acceptance); `002-…` Apache-2.0 and clean room (owner, 2026-10-10); `003`–`016` the D1–D14 outcomes; `017`–`027` the owner's answers of 2026-10-10 (`docs/open-questions.md` maps each question to its decision). `004`, `008` and `014` are superseded by `019` (D2), `018` (D6) and `021` (D12); every other decision is accepted.
