<!-- OVERRIDE:START -->
# Project-Specific Overrides

Add your custom rules and team conventions here.
This file is never overwritten by `rulebook init` or `rulebook update`.

## Task ids (overrides the `phase<N>_<kebab-name>` example in `.rulebook/specs/rulebook.md`)

Task ids are `phase<N>.<M>_<kebab-name>`, where `<M>` is the dependency level inside phase `<N>` (1 + the highest level of its same-phase prerequisites); tasks with the same `<N>.<M>` can run in parallel; children come before their parent; the phase gate is the last level. Example: `phase0.1_approved-source-index`. Index: `docs/task-index.md`; rule source: `docs/dag.md` (Task decomposition rule).
<!-- OVERRIDE:END -->
