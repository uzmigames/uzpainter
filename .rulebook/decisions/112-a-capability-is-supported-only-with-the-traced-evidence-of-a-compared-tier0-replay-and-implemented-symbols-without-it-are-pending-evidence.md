# 112. A capability is supported only with the traced evidence of a compared Tier 0 replay, and implemented symbols without it are pending-evidence

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.22_pyapi-cli-capabilities, phase1.24_python-api-facade, phase1.2_docmodel-capability-manifest, phase1.14_compositor-core, phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle

## Context

Task phase1.22 populates the capability manifest (10-python-api §3; decisions 004, 019, 081 and 082). The rules:

- Every public symbol of `uzpainter` and `substance_painter` has an entry.
- `supported` requires Tier 0 evidence.
- `release-gap` raises `NotYetSupported` before any mutation.
- `desktop-only-omitted` raises `UnsupportedInUzPainter`.
- Decision 107 §1: an absent documented symbol is a release gap and raises `AttributeError`.

Measured facts:

- The packages have 1 173 public names: modules, functions, classes, methods, properties, fields, enum members and module objects, including the members a class inherits from a private base.
- 22 Tier 0 tests replay api-probe goldens through the facade or the native API and compare their outputs exactly, in both recordings. They cover 16 api-probes plus the colour readbacks of `export-ocio-encode-legacy`. This task adds the comparison of the three R10 probes recorded for it: `phase1-create-settings`, `phase1-delete-node` and `phase1-resource-update`. Its two facade fixes are in decision 111 §7.
- A `sys.monitoring` trace of those replays exercises 393 names.
- About 640 names are implemented and tested by UzPainter's own unit tests, but no compared replay exercises them. Examples: `application.version()`, `logging`, the inert selection and UI state, `TextureSet.from_name`, `Stack.get_channel`, most event classes, `substance_painter_plugins`, enum members proven only through the compositor's semantics goldens, `jobs.Job.wait`, `export.plan`, `sync_stack`.
- The remaining names are release gaps that refuse, absent symbols, or the 15 desktop-only members.

The model panel: cx/gpt-6-astra and xai/grok-4.5 answered. kimi/kimi-k3 returned HTTP 503 twice.

- **C7, mechanical evidence from a trace of the compared replays, checked both ways**: DISAGREE (GPT: a trace proves reachability, so incidental bookkeeping calls and partially exercised symbols would be upgraded), AGREE (Grok). Adopted with GPT's objections built in. Bookkeeping calls do not count. A field counts only when the caller gave it a value. Decorator wrappers are unwrapped. Code that several functions share is dropped. Refused calls never count.
- **C8, native symbols exercised through the facade count**: PARTLY, AGREE.
- **C9, implemented symbols without evidence**: DISAGREE (GPT: overloading `release-gap` contradicts §3; keeping working unproven calls needs an explicit contract amendment), PARTLY (Grok: use a new status rather than overload `release-gap`; update the schema and the agent contract in the same change). Both rejected the proposed overload. Making the calls raise would remove working, tested behaviour that the pipeline uses. Accepting unit tests as Tier 0 evidence was rejected by GPT.
- **C10, conformance per status**: PARTLY ×2. Include the new status; compositor contexts are refused by the evaluator's support check.
- **C11, every public name and alias has an entry**: AGREE ×2.

## Decision

1. **Evidence is traced, not written by hand.** The Tier 0 tests run their replays under `tests/python/capability_trace.py` (`sys.monitoring`). For each compared output, the trace records the public names exercised by calls that did not end in a UzPainter refusal: functions, methods, properties, constructors, enum members passed or returned, public-class instances returned with the fields the caller gave them, and public exceptions raised.
   - The replays' bookkeeping (recorder reset, node location) and the outputs on their named exclusion lists do not count.
   - The union per replay is committed in `tools/capabilities/tier0-trace.json`. The owner-machine Tier 0 tests fail when a replay exercises another set: `UZP_UPDATE_TIER0_TRACE=1` rewrites the file, and the manifest is updated with it.
2. **`supported` (context `any`)** cites exactly the goldens whose replays exercised the symbol. For a module or a class, a member counts.
   - Every exercised name is `supported`. `tests/python/test_capability_conformance.py` checks both directions against the committed trace, in every lane.
   - A native `uzpainter` symbol exercised through the facade's compared replay counts, UzPainter-only ones included.
3. **New status `pending-evidence`** (amends 10-python-api §3 and the schema). It marks a symbol that is implemented, works, and has no Tier 0 evidence yet.
   - It is never `supported`: agents must not treat it as parity-proven.
   - It is not a release gap: calling it does not raise.
   - Its notes say so and name the task that owns the evidence: phase1.24_python-api-facade.
   - Painter symbols are settled by recording **P22-B**. UzPainter-only symbols are settled by a compared replay that uses them.
   - Release (G5, roadmap) treats a `pending-evidence` entry as open, like a release gap.
4. **Statuses.**
   - Absent symbol: `release-gap` (decision 107 §1).
   - The 15 desktop-only members: `desktop-only-omitted`.
   - Exercised: `supported`.
   - Refused by the API: `release-gap`. This covers calls that raise `NotYetSupported` or `UnsupportedProcedural`, the nodes, projections and modes the support check refuses (their compositor context is a release gap), the `Settings` and `MeshReloadingSettings` fields that refuse a value, and the release gaps of §3.
   - Anything else: `pending-evidence`.
   - New entries: the module `substance_painter.levels`, `DISPATCHER.connect_strong`, every public `uzpainter` name, and the `mesh-map` context of `update_layer_stack_resource` (decision 111 §7).
5. **Conformance.**
   - Every public name has an entry. Every `supported`, `pending-evidence` or `desktop-only-omitted` symbol exists.
   - Desktop-only members raise `UnsupportedInUzPainter`.
   - A release gap is absent, or raises `NotYetSupported` with the revision unchanged. It is called with placeholder arguments, or through the call that uses it (a recipe per symbol and context).
   - Compositor contexts are refused by the evaluator's support check and tested there (`evaluator_test.cpp` `not-yet-supported`; decisions 081, 082).
   - `material-layering` cannot be requested by any documented call.

## Recordings this decision names (not recorded; owner action)

- **P22-B, pending Painter symbols.** One Tier 0 api-probe on the plane that calls every Painter symbol the manifest marks `pending-evidence` (its `pending-evidence` entries with a `substance_painter` name). Setters get set→get readbacks through freshly resolved handles. Readbacks are taken in the same session and after save and reopen, and every enum member is passed where its owner call takes it. Its replay then joins the traced Tier 0 tests.

## Alternatives Considered

- **Overloading `release-gap` with working symbols** (O3). Rejected by both panelists: the status would mean three behaviours.
- **Making every unproven symbol raise `NotYetSupported`** (O1). Rejected: it removes tested behaviour that phase1.19-1.21 shipped and the pipeline scripts use.
- **UzPainter's unit tests as Tier 0 evidence** (O2). Rejected: §3 asks for Painter-recorded evidence.
- **Hand-written evidence lists.** Rejected: they cannot be checked, and the trace can.

## Consequences

- `generate_capabilities.py`, `capabilities.schema.json` and `tools/capabilities/README.md` accept the fourth status. `tests/capabilities` lets an `any` entry be `supported` when it cites its own Tier 0 evidence.
- A task that implements or proves a symbol re-runs the traced Tier 0 tests, and the conformance test names every entry to update.
- phase1.24 owns P22-B and the evidence of the UzPainter-only symbols.
