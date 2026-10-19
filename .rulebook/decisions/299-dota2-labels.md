# 299. Dota 2's user-channel labels: UzPainter keeps its generic or empty labels and never copies Painter's label text (question q1, option a)

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.24_python-api-facade

## Context

Dota 2 is the only template shipped with Painter that labels channels: its User0-User3 carry Painter's own text. UzPainter never reads, parses or copies a `.spt` file (clean room, decision 116 §4). Its four labels read "", and `test_pyapi_facade_tier0.py` (`project-templates`) requires them to differ from Painter's. A label changes no texture: the texture sets, resolution, channels and formats of all 26 shipped templates are exact, as created and after save and reopen.

Decision 117 made the labels question q1 in `.rulebook/tasks/phase1.24_python-api-facade/.metadata.json`, with two options:
- (a) ship generic labels;
- (b) ship Painter's label text after the owner's licence review.

Item 3.1 of phase1.24 waited on it.

On 2026-10-19 the owner delegated the decision to the supervisors, Codex and Claude, in direct reply to this question: "e pra vc tomar as desicoes junto com o claude, para de me perguntar" ("and you are to take the decisions together with Claude, stop asking me").

## Decision

1. **Option (a).** UzPainter keeps its generic or empty labels for Dota 2's User0-User3 and never copies Painter's label text.
2. **The difference stays visible.** Report `parity/reports/phase1/python-api-facade.md` §3 lists it as a deliberate non-pixel metadata difference, with this decision as its owner and reason. `project-templates` keeps requiring that Painter's labels are set on exactly those four channels and that UzPainter's differ.
3. **The exact behaviour stays required.** Texture sets, resolution, channels and formats remain compared exactly.

## Limits

- This is the supervisors' technical choice under the owner's delegation. It is not a licence review.
- It is not the owner personally approving the copying of Adobe text, and it does not make Painter's label text shippable. Option (b) would still need the owner's own licence review.
- It is not a parity exception under decision 032 and adds nothing to `parity/exceptions.json`: a label is metadata, not a texture or a render.

## Alternatives Considered

- **(b) Ship Painter's label text.** Rejected: it would copy Adobe text, which the clean-room rules (`docs/licensing-and-clean-room.md`) forbid without the owner's own licence review, and the delegation does not cover that review.

## Consequences

- phase1.24 item 3.1 no longer waits on q1. It stays open on its own evidence: report §4 records 26 traced replays, and `tools/capabilities/tier0-trace.json` now holds 36, which have not been run together on one build.
- Items 3.4 (P22-B) and 4.1 no longer cite q1.
- No code or test changes.
