# 99. Requested goldens are staged under the envelope's requests root, and the Wand Tier 1 golden runs the pinned pipeline scripts

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.16_export-processing-encoders, phase1.17_export-presets, phase1.22_pyapi-cli-capabilities, phase1.23_pyapi-pipeline-adapter, phase1.25_pilot-wand

## Context

Decision 100 prepares the Phase 1 recordings for one Painter session, but the prepared manifests cannot be recorded yet. Four facts constrain where those manifests can live and what form they take:

- **Every manifest must name records.** The tests and tools that read the current envelope's `manifests/` require each manifest to name its private records: the Tier 0 gate, the envelope refresh and the store verify all do. Earlier batches committed manifests only together with their records.
- **JSON fixtures need a declaring manifest.** The guard rejects any JSON under `parity/` that no path rule covers. A JSON fixture passes only when a manifest declares it.
- **R9 (Wand v1, Tier 1) must run three UzmiGames pipeline scripts byte-unchanged, pinned by SHA-256.**
  - `painter_create.py` and `painter_export.py` read their arguments from a hard-coded Assets3D path. Those arguments point at the delivered production `.spp`.
  - `painter_layer_stack.py sync` sends its Painter-side code through the community MCP bridge, which the recorder must never use.
  - The recorder must not edit Assets3D.
- **The schema has no form for a script run.** Schema `golden-public/1` allowed only `substance_painter.*` calls under the interface `substance_painter_documented_python_api`.

## Decision

**Model panel (one round): GPT, Kimi, Grok.**

- **C1, the staging root:** 3 AGREE.
- **C2, R9 as a reserved pseudo-call inside the old schema:** GPT DISAGREE, Kimi PARTLY, Grok PARTLY (a semantic hack, debt).
- **C3, how the scripts are adapted:** 2 AGREE, GPT PARTLY (document the args interception as an adaptation).
- **C4, golden ids under existing families:** 2 AGREE, GPT PARTLY.

C2 was decided against the pseudo-call, by weight of evidence: the schema is extended explicitly.

1. **Requested goldens.** Unrecorded manifests live under `parity/envelopes/<envelope>/requests/`, with the same relative paths as `manifests/`.
   - **Guard rule.** A JSON there must be a valid public manifest with `private_records` empty, and its inputs count as declared inputs.
   - **Recording and admission.** The recorder records from the request path. `python -m tools.parity.store record <manifests path> --run <run>` creates the admitted manifest. The request file is then deleted.
2. **Golden ids** stay in the existing families: `tier0/semantics/export-*`, `tier0/api-probes/phase1-*` and `phase1/tier1/wand-v1`. Admission then reuses the existing tests and generators.
3. **Schema `golden-public/1` extended**, backward compatible:
   - **Interface.** `instruction_sequence.interface` may be `uzmigames_pipeline_scripts`. Its steps all have the call `uzmigames.pipeline.run_script`. Under the old interface, calls must still be `substance_painter.*`. The scripts' own Painter calls are pinned with the scripts' bytes, not checked symbol by symbol. The sync code's `delete_node` is documented and probed by R10.
   - **Input kind.** The input kind `pipeline_script` is added.
   - **Outside inputs.** An input kept outside this repository is named by SHA-256 with `assets3d_path`, relative to the Assets3D root, and never with `path`. Its licence is `LicenseRef-UzmiGames-Assets3D`, which is allowed only with `assets3d_path`.
4. **R9 execution: two adaptations, both documented.**
   - **(a) Repointed arguments.** The recorder hash-checks and stages every input in its work directory. It writes repointed copies of the two args files there:
     - mesh, normal and AO point at the staged copies;
     - `dst` points at a work `.spp`;
     - `out` points at a fresh export directory.

     It executes the pinned bytes of each Painter-side script in a fresh namespace whose `open` maps exactly the hard-coded args path to the copy.
   - **(b) Transport swap for `sync`.** The pinned module is compiled from its hashed bytes with its real path. Only its `execute(code)` transport is replaced by the recorder's documented remote control. The Painter-side code the script builds is byte-identical.
5. **Colour management is enforced in both directions.** A texture golden that names no `OCIO` is refused in a session that is not Legacy. A manifest that names `OCIO` was already refused outside that configuration. The two sessions of decision 100 cannot be mixed up.

## Alternatives Considered

- **Commit under `manifests/` and teach every test and tool to skip unrecorded manifests:** rejected. It touches the gate, the refresh, the canary and store verify, and it weakens "every admitted manifest names its records".
- **Keep the manifests uncommitted in a scratch folder:** rejected. The Painter session needs reviewed, committed jobs, and JSON fixtures need a declaring manifest.
- **A reserved `substance_painter.remote_scripting.run_file` call inside the old schema:** rejected (panel C2). It names a symbol that does not exist under a "documented symbol" contract.
- **Edit the `_tmp` args files in Assets3D, as the plan suggested:** rejected. Assets3D is read-only for this work.

## Consequences

### Positive
- 24 requested goldens (decision 100: 15 Tier 0 export goldens, 8 R10 API probes, the Wand Tier 1 golden) are committed, reviewable and recordable without further code.
- The UzPainter pipeline adapter (phase1.23) and the Tier 1 runner (phase1.25) can reuse the same pinned inputs and the same two adaptations.

### Negative
- The args-path interception is an adaptation beyond the transport swap. It is listed in the manifest description and in `parity/RECORDER.md`.
- The licence label of the Assets3D inputs is an owner-only confirmation.

## Follow-ups
- Owner: confirm the `LicenseRef-UzmiGames-Assets3D` label for Assets3D inputs that are named by hash only.
- After admission, delete each request file and move its golden into the corpus generators.
