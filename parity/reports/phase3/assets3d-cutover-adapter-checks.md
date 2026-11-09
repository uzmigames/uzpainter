# `phase3.1_assets3d-cutover`: adapter checks on the pilots

Run on 2026-11-09 on the owner's machine, on `main`. The amendment is still a draft, unsigned
(`docs/analysis/assets3d-cutover/01-amendment-draft.md`), and nothing here authorizes a cutover.

**Result.** No pilot can run an accepted production round yet. The two UzPainter-side blockers are
removed:

- HEAD's `sync` is now in scope, because `Resource.retrieve` is `supported`.
- The gate preflight now reads real Assets3D v2 manifests.

What still blocks is Assets3D-side data that only Assets3D's own fronts and the owner can produce:

- No pilot piece manifest holds a confirmed upstream gate.
- Wand v1 has no v2 piece manifest at all.

Items 3.1, 3.5 and 3.6 stay open.

## 1. `Resource.retrieve` (blocker 1, removed)

| | |
|---|---|
| Golden | `tier0/api-probes/resource-retrieve-cached-url`, Legacy, recorded and admitted 2026-11-09 (Painter lock seq 2348/2349), inbox run deleted |
| What it records | The Assets3D `sync` flow: `mask_left_half` is imported and bound as a mask fill's source. Then, in `r1` and after save and reopen, `Resource.retrieve` is called on four ids: the import's URL, its versioned project query, an absent name, and a version the name does not hold. |
| Painter's answers | In the current context it returns the one resource held under that name and version, and `[]` for an absent name or version. A URL from the context before the reopen raises `ValueError`, which the `sync` catches and answers by importing again. |
| Facade | `Resource.retrieve` reproduces the three answers. Unversioned ids, ids outside a project context, and calls with no open project are unrecorded and raise `NotYetSupported`. New native `uzpainter.resource.resource_usage` returns the usage of the returned resource. |
| Comparison | `test_pyapi_observed_host_tier0.py::test_host_probe_equals_painter[resource-retrieve-cached-url]` is exact on both recordings, with no exclusion. |
| Manifest | `Resource.retrieve` moves from `release-gap` to `supported`, and `resource_usage` from `pending-evidence` to `supported`, both through `sync_tier_evidence` (decisions 112, 403). The only other change is that the golden is added to the evidence of the 275 entries it exercised. |
| Scope | `test_cutover.py::test_head_sync_is_in_scope_and_capture_is_refused`: Assets3D HEAD (`d61f0bd8`) `sync` names only `supported` symbols. |

The G2 manifest (`9f4d2abc…`) that the unsigned draft pins still lists `Resource.retrieve` as a
`release-gap`. HEAD's `sync` is in scope only of manifests built after commit `7b8ee87a`, for
example this run's ReleaseFast `capabilities.json` (`f2b681ac…cbdc7`).

## 2. `capture` (blocker 2, kept outside the scope)

`painter_layer_stack.py capture` calls the shim `display.save_viewport`, which is
`uzpainter.render.capture`. That entry is `pending-evidence` because the `painter_viewport` mode is
the preview pass rendered offscreen, which is never parity evidence. Render parity belongs to gate
G5 (`phase3.7_path-tracer`), and G2 made no render claim. So `capture` stays outside the cutover's
proven scope, and no evidence was fabricated for it. A production `capture` is refused before
anything runs, with `OutOfAmendedScope` naming Adobe Substance 3D Painter as the tool (same test
as §1).

## 3. Upstream gates (blocker 3, Assets3D-side)

Read-only, Assets3D `d61f0bd8`, `Creatures/Undead/Skeletal Mage/Models3D/`:

| Pilot | Piece manifest | Gates covering geometry, fit, low_uv or bake | Reviewer |
|---|---|---|---|
| Wand v1 (`11-Varinha-Madeira`) | **none**: no `manifests/` folder, not in `pieces-index.json`. The v1 `.blend`, `.spp` and maps are no longer in the tree; UzPainter resolves the pinned inputs from its private store | none | none |
| Sash v5 (`25-Faixa-Cintura/manifests/v5.json`, `fb6fe020…`) | schema 2 | `low-uv`, `bake`, `geometria-encaixe`: `pass`, `not-verified`; dependencies `not-verified`, on `/files/blend-v5` | producer only |
| Belt v5 (`23-Cinto/manifests/v5.json`, `64a4524d…`) | schema 2 | same as Sash v5 | producer only |
| Tunic v10 (`18-Tunica/manifests/v10.json`, `5c95b550…`) | schema 2 | `uv-producao` `fail`; `snapshot-v10` and `ref-match-atual` `pending`; all `not-verified` | `unidentified` |

**What verifies a gate in Assets3D.** No tool promotes a gate:

- `Pipeline/manifest/manifest.py` "generates manifests and indexes without promoting gates", and its `check` verifies file integrity only.
- `Pipeline/manifest/README.md` sets the rule: advancing needs an applicable PASS, the producer's inspection, and an independent confirmation with identity, session and evidence.
- `Docs/Colaboracao/Colaboracao.md` adds that another session confirms the gate, and that UV, bake and technical QA are Astra's role.
- `AGENTS.override.md` §3 (owner, 2026-11-03) says Claude does not build, repair, prove or review UV.

A legitimate verification of Wand v1 therefore needs Assets3D-side work, decided by the owner:

1. An Assets3D front pins the v1 low mesh in Assets3D and writes a v2 piece manifest whose `meshes.low` is that mesh.
2. The producer re-measures low UV, bake and low/high fidelity, in a private `blender -b` on saved files.
3. A different agent and session confirms each role. For low UV this cannot be a Claude session.

No UzPainter agent can do this under Assets3D's protocol, so none of it was attempted.

**Adapter-side findings, from reading the real manifests.**

- **Fixed.** `gate_contract.py` required `schema: 1`, but Assets3D's `manifest-schema-v2.json` fixes `$defs/manifest` `schema` to 2, and every real piece manifest holds 2. The preflight therefore refused every real manifest, whatever its gates. It now requires 2. Tests: `test_only_the_v2_piece_manifest_schema_is_read` and `test_the_manifest_schema_matches_the_assets3d_definition`. `MIGRATIONS.md` M11 is updated.
- **Open, needs a decision.** The preflight binds UzPainter's mesh import report to the bytes of `meshes.low.file`. The real manifests name the `.blend` there (`blend-v5`, `blend-v10`), and UzPainter imports OBJ, FBX or glTF, not `.blend`. Either Assets3D's manifests name the exported low mesh file, or the contract accepts a verified dependency from the `.blend` to the exported mesh. This is a contract change, so it was not made here.
- **Open, integration.** The pipeline's own `execute()` keeps only the reply's `data`, and its response file is written to a temporary folder that is then deleted. Each export's manifest blocks (M14) are in the adapter's reply, but nothing in Assets3D reads them into a piece manifest yet.

## 4. The Wand v1 round

- **Production round.** Not possible. Without a v2 piece manifest, no `--production-round` request can bind the four roles, so the preflight refuses before anything runs (QG-02, items 2.5 and 3.2). An accepted production round (item 3.1) needs §3 first.
- **The same round as a diagnostic import, with the production export.**
  `tests/parity/tier1/wand_v1/test_wand_manifest_blocks.py` passed once in 27 s
  (`UZP_TIER1_PRODUCTION=1`). It runs create and sync through the adapter with the pinned scripts,
  then sends the pinned `painter_export.py` through the client.
  - The export is conformant (no `non_conformant` in its receipt): generation `000001`, revision
    169, five maps.
  - The receipt relies on exactly EXC-013 and EXC-014.
  - The `export` block and its 9 files validate under the pinned Assets3D v2 definitions.
  - The recipe file (`painter-recipe`, SHA-256 `0bce4ff7…5fe4d`) is the `uzpainter/recipe/1` dump
    of revision 169, digest `5a1e45fa…2c06`. Its revision and profiles equal the receipt's
    (`painter-12.1-isolated-coverage-weights`, `painter-12.1-api-0.3.7`).
  - This validates both manifest blocks on one pilot's real export. It is not an accepted round.
- **The typed MCP rounds with Python disabled, on the production export:**
  - `test_mcp_round.py::test_wand_round_runs_through_typed_tools_with_python_disabled` passed in 41 s. It completes, and its maps are byte-identical to the Tier 1 run's.
  - `test_tunic_current_recipe_rebuilds_the_typed_round_from_its_dump` passed in 418 s, with
    outcome `pass`: equal recipe digests and identical exported files from all three typed
    sessions.
  - Both tests now require a completed export (the stale acceptance of a refusal is removed). They run on the ReleaseFast build, the Tunic with its GPU deadline in every typed session.

## 5. Items

| Item | State | Why |
|---|---|---|
| 3.1 | open | No accepted production round on any pilot (§3, §4) |
| 3.5 | open | Blocks validated on one pilot export (Wand v1, diagnostic import), not on the three pilots' accepted rounds |
| 3.6 | open | This report records the checks run so far; the pilot results it must hold (3.1, 3.5) do not exist yet |

## 6. What the owner must do to sign, and to unblock the rounds

1. **Signing (items 2.3, 4.1).** Read the draft's §1 and §2, approve or change §3, and choose the scope manifest. Signing on the G2 manifest `9f4d2abc…` keeps HEAD's `sync` outside. A manifest built after `7b8ee87a` puts it inside, and `02-amended-scope.json` would then be regenerated before signing. Then sign in your own words; decision 259 §6 applies. Decide the route-token gap (M8).
2. **Unblocking 3.1 and 3.5 (Assets3D side, your division of work).** Assign an Assets3D front, for example Astra plus an independent non-Claude reviewer, to:
   - write a v2 manifest for Wand v1 that pins its low mesh, or choose another pilot;
   - confirm the geometry/fit, low UV, bake and low/high-fidelity gates of each pilot with an independent reviewer;
   - decide how `meshes.low` relates to the mesh UzPainter imports (§3, second finding).

## 7. Commits and tests

- **UzPainter.**
  - `7b8ee87a`: `Resource.retrieve` and its golden.
  - `644ac7eb`: the MCP test fixes.
  - `442c5bd0`: the gate-schema fix.
  - This report and the Wand manifest-block test are in the commit after them.
- **Assets3D.** Nothing edited. The Painter lock was taken and released through `collab.py` (seq 2348/2349).
- **Tests, each run once.**
  - Recorder: `test_resource_retrieve_probe.py`, `test_raw_resource_identity.py` and `test_ocio16_raw_readout_control.py`, 72 passed.
  - Facade: the compared replay, 1 passed; `test_resource_retrieve.py`, 2 passed; `test_capability_conformance.py` with `tests/capabilities`, 49 passed.
  - Adapter: `test_cutover.py` and `test_gate_contract.py`, 86 passed;
    `test_assets3d_production_guard.py`, 12 passed.
  - Wand manifest blocks: 1 passed.
  - MCP: as listed in §4.
