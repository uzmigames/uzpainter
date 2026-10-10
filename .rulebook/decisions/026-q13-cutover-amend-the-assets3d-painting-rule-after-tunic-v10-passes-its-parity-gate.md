# 26. Q13 Cutover: amend the Assets3D painting rule after Tunic v10 passes its parity gate

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

The Assets3D pipeline rule says painting is always done in Substance Painter. Owner question Q13 asked which gates authorise the cutover and when that rule is amended; the round-3 default kept the rule until the tunic recovery milestone passed Tier 1 and left the amendment to a later integration action. Owner answer of 2026-10-10 (docs/open-questions.md Q13).

## Decision

The Assets3D rule "painting is always in Substance" is amended after Tunic v10 passes its parity gate (G2, docs/roadmap.md). The full Assets3D cutover (P5-CUTOVER) still follows the release gate G5 and the owner's signature.

## Alternatives Considered

- Keep the rule until a later integration action after the tunic milestone (round-3 default) - replaced by the owner's answer

## Consequences

The amendment is an Assets3D action triggered by the G2 evidence; UzPainter's docs record only the trigger. Software certification never grants artistic, alpha or rig approval of existing assets.
