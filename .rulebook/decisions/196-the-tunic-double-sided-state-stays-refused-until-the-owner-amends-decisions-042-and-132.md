# 196. The Tunic double-sided state stays refused until the owner amends decisions 042 and 132

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.10_pilot-tunic-recovery, phase3.5_path-tracer-materials, phase3.6_path-tracer-tier3-report

## Context

Decision 194 left a fork open: the Tunic v10's approved Painter state has the shader parameter "Double sided" on (`report.json` `/painting/effects_opacity_blending_state/doubleSided/value`), and the rebuild fixture pins it. Task phase2.10 items 2.3 and 3.3 ask for the rebuilt project to hold and read back that state. UzPainter refuses it:

- Decision 038 (owner): render parity covers only the fixed Assets3D pipeline; every other render setting is pinned.
- Decision 042: a setter accepts only a value the fixed pipeline uses and refuses every other value with `UnsupportedInUzPainter`; nothing is silently ignored. Item 5 makes the Tunic's "Double sided" an owner scope point. A panel was asked then to carve it out for renders and refused: the panel cannot widen 038.
- Decision 132 item 7: `render.shader.set_parameters` and MCP `shader_set` accept a known identifier only at its default value. `double_sided` defaults to false.

Measured on main `cf51b73`:

- The project file already stores `display.shader.{id, parameters}` through save and reopen. The setter rewrites every parameter to its default.
- No renderer reads the shader parameters. The preview viewport has no face culling: it hits both faces and turns the geometric normal toward the viewer (`src/preview/PREVIEW.md` step 1). Painter's realtime behaviour with double-sided on or off is unrecorded. The path tracer (`painter_iray`) refuses every capture.
- Exported maps do not depend on it (`exportShaderParams` false), and the Tunic's Tier 1 acceptance is on exported maps.
- `render.display.state().parity` checks only the environment. Each viewport receipt's `render_state_digest` hashes the full shader object.
- Painter's Python API cannot read the state back, so the migration golden does not record it (decision 194).

## Model panel (one round: cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

The alternatives were:

- (a) keep refusing;
- (b) store `double_sided` (booleans only) as project state that survives save and reopen and is reported by `shader_get`, while renders stay pinned, and report `parity: false` while it differs from the default;
- (c) honour it in the preview render.

The proposal put to the panel was (b).

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 (b) does not widen 038, so a panel may decide it | DISAGREE | PARTLY | DISAGREE |
| C2 reject (c): the culling rule would be invented | AGREE | AGREE | AGREE |
| C3 reject (a): it blocks the pilot for no parity gain | DISAGREE | PARTLY | DISAGREE |
| C4 `parity: false`, the receipt digest and the path tracer's refusal keep it from being silently ignored | DISAGREE | PARTLY | PARTLY |
| C5 the widening is exactly one boolean identifier, and setting merges into the stored set | PARTLY | PARTLY | PARTLY |
| C6 tests for (b) | PARTLY | PARTLY | PARTLY |
| Preferred | (a) | (b), only after the owner amends 042 and 132 | (a) |

All three reject the panel's authority for (b). 042 and 132 are owner-scoped setter contracts. Accepting `true` turns a required refusal into a stored value, even if no render changes. The changes would be the API's accept or refuse result, the stored parameters, the parity flag and the receipt digest. Kimi prefers (b) as the end state, but only as an owner amendment. Everyone rejects (c).

## Decision

1. **(a): keep refusing.** `shader_set {"parameters": {"double_sided": true}}` and `render.shader.set_parameters` still raise `UnsupportedInUzPainter` (decision 132 item 7). No code changes.
2. **Scope split in phase2.10.** The double-sided parts of 2.3 (the rebuild holds the state) and 3.3 (it reads back after save and reopen) wait on the owner. Everything else in those items is unaffected: the bindings, `replace_height` and the Height blend override. The rebuild fixture keeps pinning `double_sided: true` from the report, so the gap stays visible.
3. **(c) is rejected.** Painter's realtime double-sided behaviour is unrecorded. A culling rule would be invented, and 038 pins render settings.
4. **The owner's choices:**
   - Amend 042 item 5 and 132 item 7 to adopt (b) as specified below, with no change to 038's render scope.
   - Or drop the double-sided pin from the Tunic rebuild fixture and from items 2.3 and 3.3.
   - Or amend 038 so that renders honour the state. That would also need a Painter recording of its realtime and Iray behaviour.
5. **(b) as specified for an owner amendment.** This adds the panel's conditions to the proposal.
   - `double_sided` accepts true or false only. Any other type is a `ValueError`. The other 18 identifiers stay default-only.
   - A set merges into the stored parameters instead of resetting them, and this is documented.
   - `render.display.state().parity` is true only when the environment is the preset's and every stored parameter equals its default. An explicit false keeps parity.
   - A non-parity state is refused as render-parity evidence (phase2.2).
   - Viewport receipts change their `render_state_digest` when the state is true.
   - Tests cover: storage, the merge, save and reopen, the parity flag both ways, a non-boolean refused, other parameters still refused, the MCP `shader_set` accepting and `shader_get` reading back, and exports byte-identical with the state true.

## Alternatives Considered

- **(b) by panel decision.** Rejected 2 to 1, with the third member asking for owner sign-off. The panel cannot change an owner-scoped setter contract. Decision 042 already refused a carve-out on this same parameter.
- **(c) honour it in the preview.** Rejected 3 to 0: an invented culling rule, and outside 038.

## Consequences

The Tunic's Tier 1 export path is not affected: the maps do not depend on the state. Only the double-sided parts of phase2.10's 2.3 and 3.3 stay open, and the owner owns them. They are listed among the owner actions in the task's notes. Decision 042 item 5's Tier 3 exclusion of the Tunic production render is unchanged.

## Amendment (2026-10-19, SUP-030): option (b) adopted

**Authority.** On 2026-10-19 the owner delegated routine technical decisions to the supervisors, Codex and Claude, in his own words: "e pra vc tomar as desicoes junto com o claude, para de me perguntar" ("and you are to take the decisions together with Claude, stop asking me"). The Codex supervisor's joint finding SUP-030 (`tmp/claude-supervision.json`) proposed adopting item 5's option (b) under that delegation. Claude reviewed it against decisions 038, 042 and 132 and found no technical conflict. This amendment is the supervisors' joint decision under the delegation. It is not a new owner answer to item 4. It approves no parity exception, claims no render parity and widens no render setting of decision 038.

**What changes.** Items 1 and 2 are replaced. Option (b) is adopted with every condition of item 5. It amends decision 042 item 5 and decision 132 item 7 for `double_sided` only.

1. **`double_sided` is project state.** `render.shader.set_parameters` and MCP `shader_set` accept `double_sided` true or false. A value of any other type, `1` and `0` included, is a `ValueError`. Over MCP it is `invalid_arguments {type: ValueError}`, as decision 242 made an invalid export configuration.
2. **The other 18 identifiers stay default-only.** Any other value raises `UnsupportedInUzPainter`, as decision 132 item 7 says.
3. **Validation comes first.** Every given parameter is checked before anything changes. One refused or malformed value refuses the whole call, and nothing is stored.
4. **A set merges.** A set merges the given parameters into the stored ones, so setting another identifier keeps a stored `double_sided`. Before this amendment, a set reset every parameter to its default. A default-only identifier is stored as its default value.
5. **Save, reopen and the getters agree.** The project file already stores `display.shader.parameters`. `shader.parameters()`, `shader_get`, `render.display.state()` and `display_get` read the stored value, before and after save and reopen.
6. **Parity.** `render.display.state().parity` is true only when the environment is the active preset's standard environment and every stored shader parameter equals its default. A stored `double_sided` true is a non-parity state. An explicit false keeps parity.
7. **The receipt digest changes.** A `painter_viewport` capture's `render_state_digest` already hashes the full shader object (`src/python/capture.cpp`), so it changes when the state is true. The pixels do not change: no renderer reads the shader parameters, and the preview still has no face culling.
8. **A non-parity state is rejected as render evidence.** Reporting `parity: false` is not enough. A Tier 3 comparison (`tools/parity/verdict.py`, `Comparison.candidate_display_state`) takes the display state of the revision its candidate render captured. A state whose `parity` is not true, or a missing state, is `fail` with the reason "rejected as render evidence", before anything is compared and whatever the register holds. A parity state is admitted, and it still passes only through a covering register entry (`parity/CONTRACT.md` §4.1).
9. **Exports are unchanged.** Exported maps do not depend on the state (`exportShaderParams` false). They stay byte-identical with it true and false.

**What does not change.** Decision 038's render scope stays: every render setting is pinned, and no render honours the state. No culling rule is invented (item 3, option (c), stays rejected). Every unrecorded-render refusal stays: `painter_iray` raises `PathTracerUnavailable` before any work, and decision 042 item 5's Tier 3 exclusion of the Tunic v10 production render stands. The rebuild fixture keeps pinning `double_sided: true`. No historical pilot baseline changes.

**Consequences.** The double-sided parts of phase2.10 items 2.3 (the rebuild holds the state) and 3.3 (it reads back after save and reopen) no longer wait on the owner. They stay open on that task's other blockers: the lost masks, the mesh and `infinite` padding. Tests:
- `tests/python/test_display_presets.py`: the strict boolean, validation before any change, the merge, save and reopen, parity false and true with the render standard's own HDRI, rejection of the non-parity state as render evidence, and byte-identical exports.
- `tests/supervisor/test_supervisor_mcp.py`: the same through MCP.
- `tests/parity/test_verdict.py`: the Tier 3 rejection.
- `tests/preview/test_preview_capture.py`: the receipt digest changes and the pixels do not.
