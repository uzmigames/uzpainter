# 244. MCP `project_close` keeps every commit, and `discard: true` returns a saved project to its last save

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.6_mcp-typed-tool-families, phase2.8_mcp-server, phase1.21_pyapi-dispatcher-lifecycle

## Context

Bug B10 of the practical end-to-end run (`parity/reports/phase2/practical-e2e.md`) is a design question. Over MCP, `project_open p.uzp` → `layer_set {name: "x"}` → `project_close` → `project_open p.uzp` shows the layer named "x". `inspect` shows the current revision (21) above the last save (`save-20`). Painter's documented close loses unsaved data ("Any unsaved data will be lost").

Measured facts:

- **Store design** (09 §4). Every committed mutation is one SQLite transaction with its idempotency record, so the file at rest always holds the last committed revision. `save()` only names a checkpoint. `needs_saving()` is current ≠ last named checkpoint. History is append-only.
- **Decision 105.** Native `close()` keeps the autosaved current revision. Painter's discard belongs to the facade.
- **Decision 109.** The facade's `substance_painter.project.close()` reverts a saved, dirty project to its last named checkpoint and saves it before closing (`discard_unsaved`). What Painter's reopened file shows is still unrecorded (P21-G).
- **MCP `project_close {discard?}`** kept every commit. On a saved project, `discard` changed nothing; it was needed only to close an untitled project, which closing deletes. Yet the requirement-to-tool matrix (decision 182) lists `project_close` as the tool covering `substance_painter.project.close`.

Before deciding, the fork went to the model panel (`cx/gpt-6-astra`, `kimi/kimi-k3`, `xai/grok-4.5`, one round) with four options:

- **A.** Keep the status quo.
- **B.** Discard by default, as Painter does.
- **C.** Keep by default, and give `discard: true` one meaning, "drop what was not saved", on both kinds of project.
- **D.** Refuse to close a dirty project without `discard`.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1. A different close default on MCP, the typed surface, does not by itself break output parity; the facade already discards | PARTLY | AGREE | PARTLY |
| C2. For agents, dropping work silently on close (B) is the more dangerous failure | PARTLY | AGREE | AGREE |
| C3. Under A, the matrix entry claiming Painter's close is wrong | AGREE | AGREE | AGREE |
| C4. C is the best option | PARTLY | PARTLY | AGREE |
| C5. D is worse than C | DISAGREE | AGREE | PARTLY |
| C6. The discard path must be exactly the facade's until P21-G is recorded | PARTLY | AGREE | AGREE |
| Recommended option | C | C | C |

Notes from the panel:

- GPT and Grok: the split between surfaces is a real product bug for pipelines that translate Painter calls into MCP calls. Hence C3 is unanimous.
- Kimi: a client that passes `discard: true` defensively on every close now drops work it used to keep. The change is correct by design but not free.
- GPT: D's "no gain" is too strong, since forcing a choice has value, but C is still preferable. GPT also asks for the discard path to share the facade's tested operations, for crash and retry safety, for the lease question and for a change notice.

## Decision

Option C, unanimous.

1. **`project_close` without `discard` keeps every commit**, unchanged. A saved project's file holds the last committed revision, saved or not. Nothing an agent did is lost by closing.
2. **`project_close {discard: true}` drops what was not saved, as Painter's close does.**
   - A saved project whose current revision is not its last named checkpoint gets one revert to that checkpoint, which is then saved, and then it closes. The file reopens as it was saved, with current = last save. The dropped revisions stay in the history, revertible until compaction collapses them.
   - The native `Session::DiscardUnsaved()` makes the same two native calls as the facade's `discard_unsaved` (`revert(named)`, then `save(Incremental)`). It does nothing for a project with nothing unsaved or without a named checkpoint.
   - An untitled project is deleted, as before; closing one still needs `discard: true`.
3. **Painter's `project.close` maps to `project_close {discard: true}`.** The tool and argument descriptions say so. The matrix keeps its tool-level entry, now true with that argument.
4. **The claim stays exactly the facade's.** What Painter's reopened file holds after a close without saving is recording P21-G. It settles both surfaces together.

## Alternatives Considered

- **A, status quo.** Rejected. Painter's close semantics stayed unreachable over MCP, and the matrix entry overclaimed (C3, unanimous).
- **B, discard by default.** Rejected. An agent that forgets `project_save` would lose visible work with no error (C2).
- **D, refuse a dirty close.** Rejected. It breaks clients that close without saving on purpose, and C already makes discarding explicit.

## Consequences

- One changed result: `discard: true` on a saved, dirty project, which was a no-op there, now returns the project to its last save.
- **Crash and retry.** A worker killed between the revert and the save leaves the file at the saved content with `needs_saving()` true. Repeating the same call reverts again (to the content the file already holds), saves and closes. The supervisor never replays the interrupted call by itself (02 §5).
- **Lease (open, for the HTTP lease work).** `project_close` is not a mutating tool, like `project_save`, so in HTTP mode it needs no lease. With `discard: true` a client without the lease can now drop another client's unsaved revisions. They stay recoverable by `project_revert`. Making `project_close` and `project_save` need the lease is left to the lease work (B8 group), since it changes every HTTP client's close.
- Tests: `tests/supervisor/test_typed_tools.py::test_close_keeps_every_commit_and_discard_returns_to_the_last_save` reproduces B10. The facade's own discard stays covered by `tests/python/test_pyapi_dispatcher.py::test_close_discards_what_was_not_saved`.
