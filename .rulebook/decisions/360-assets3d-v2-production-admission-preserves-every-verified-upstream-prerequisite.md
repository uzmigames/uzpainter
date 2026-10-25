# 360. Assets3D v2 production admission preserves every verified upstream prerequisite

**Status**: accepted
**Date**: 2026-10-25
**Related Tasks**: phase3.1_assets3d-cutover

## Context

Technical implementation policy accepted by the coordinating Codex under the owner's delegation to continue implementation. Sources: QG-02/QG-05; decisions 026 and 097; Assets3D/Pipeline/manifest/README.md (v2). This records neither an owner signature nor a gate exception.

## Decision

Implement LOCAL adapter admission against Assets3D v2. Every required current upstream gate must be pass with applicability confirmed, current evidence/dependencies and independent confirmation. A pending/fail/reopened/not-verified gate cannot be hidden by another pass. Preserve explicit geometry/fit, low_uv, bake and low-plus-normal fidelity roles; free-form gate names or generic stage tags cannot silently discharge missing fidelity evidence. Missing or ambiguous proof refuses production before mutation; explicitly marked diagnostic imports remain possible. A mesh certificate fail refuses production. Schema-v2 export naming follows existing decision 097. G2, owner signature, scoped governance amendment and Assets3D repository protocol remain unchanged.

## Alternatives Considered

- Accept historical pass with unverified applicability: rejected by QG-02/QG-05.
- Require only one passing gate per stage and ignore pending gates or fidelity: rejected; weakens existing prerequisites.

## Consequences

Implement and test the local refusal/admission boundary without editing Assets3D. Real pilots remain production-refused until their evidence is verified under the external protocol. Do not mark G2 or cutover accepted from software tests.
