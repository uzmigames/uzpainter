# 40. Moved Assets3D sources keep their audited rows; a changed revision gets its own row

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: none (Assets3D path migration)

## Context

On 2026-10-11 Assets3D moved and renamed its documentation and tools in four commits (`f49fe67` reorganization: `Docs/Pipeline/<Stage>` → `Pipeline/<stage>`, `Docs/Pipeline/Licoes` → `Docs/Lessons`, `Docs/Biblioteca` → `Docs/Library`; `3d8fbfe` English translation; `d974c81` and `8568207` Portuguese identifiers and file names → English). About 800 citations in UzPainter's docs named the old paths. The old→new map comes from git rename detection, with Assets3D's own move map (`Docs/analysis/project-reorganization/phase1-map.json`, `id-map.json`) where detection has no pair (`Docs/Pipeline/Aprendizados.md` → `Docs/Lessons/README.md`; `Docs/Library/Receitas` → `Docs/Library/Recipes`). The two sources agree on every lesson id cited.

`docs/approved-sources.md` pins each Assets3D source by path, commit and blob, and says "a later revision is a different source and needs its own entry". It also clears `docs/analysis/` files by exact blob. Of the 11 Assets3D rows with moved paths, 5 are byte-identical at the new path. The other 6 changed: three lesson cards were translated, the render standard JSON was translated and two of its paths changed, `painter_render_standard.py` changed two docstring paths, and `painter_layer_stack.py` changed a path and gained a `spec` layer key that sets `SpecularWeight`. Architecture doc 07 belongs to a concurrent task and still cites two of the changed rows by their old path.

## Decision

1. Paths are rewritten to Assets3D's committed HEAD (`8568207`). Uncommitted Assets3D work is not followed.
2. Byte-identical rows keep their row, object and reviewer. Path, commit (the last commit that touched the new path) and `Cited as` move to the new path.
3. Changed rows keep the audited row as it was (old path, commit, blob and `Cited as`), so old citations still resolve. Each new revision gets its own row (`<ID>-2`): path, commit and blob at HEAD, `Cited as` set to the new path, reviewer "Claude audit 2026-10-11". The reviewer audited the whole delta from the audited blob and read each new lesson card in full. None contains Adobe content.
4. Cleared analyses edited by the path rewrite get new clearances. Their Section D rows move to the new blob and to the commit that holds it, and the old blob goes to Section Q3. This takes two commits, because a row cannot name the commit that contains it. The citation check fails only between those two commits.
5. Decision records get the path rewrite plus a short note that gives the name used when the decision was recorded. Archived tasks (`.rulebook/archive/**`) are records of their time and are not rewritten.

## Alternatives Considered

- Add the new path to `Cited as` on rows still pinned to the old blob. Rejected by the panel: docs citing the new path would point at content that was never audited.
- Re-pin the changed rows in place under the 2026-10-10 reviewer stamp. Rejected: this records a clearance that never happened, and one delta adds behaviour.
- Rewrite decision records with no note. Rejected 2 to 1: it hides what the record cited when it was written.

## Consequences

The index keeps both revisions of the 6 changed sources. The 2026-10-10 rows stay valid for doc 07's old citations until that doc moves to the new paths. Then they can be retired by a later decision. The next Assets3D rename needs the same procedure. Model panel 2026-10-11 (gpt-6-astra, kimi-k3, grok-4.5): point 2 agreed 3-0; point 3 agreed 2, partly 1; point 4 agreed 1, partly 2; notes in decision records favoured 2 of 3; point 5 (archives untouched) agreed 2, disagreed 1.
