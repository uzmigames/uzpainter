# Project manifest and document model (`src/uzp_core/`)

Task `phase1.1_docmodel-types-manifest` (P1-DOCMODEL). Implements the document part of D3 in
`docs/architecture/03-project-model.md` §1-§5 and `04-layer-stack-and-compositing.md` §1, and the
manifest of `09-project-file-format.md` §1 and §5. The manifest is the public schema of the `.uzp`
file: `uzpainter inspect` prints it and every revision stores it. The recipe digest is the SHA-256
of the output-determining part of it (§8).

## 1. Layout

| Path | Content |
|---|---|
| `types/enums.h` | Enumerations and their manifest spellings (documented Painter member names; lower-case kinds of `04-…` §1) |
| `types/ids.h` | Persistent 64-bit ids |
| `types/layers.h` | Layers, effects, masks, sources, projections, paint planes, smart-preset provenance |
| `types/project.h` | Project, settings, mesh reference, texture sets, UV tiles, mesh-map bindings, bake settings, stacks, channels, resources, display state, versions |
| `types/resource_url.h` | `resource://project/<name>?version=<sha256>` and `uzasset://<family>/<id>@<version>` |
| `types/receipt.h` | Result-record header of every export, capture, bake and dump receipt (ARC-11) |
| `types/validation.h` | Model validation, documented insertion rules, anchor/instance cycle check |
| `types/errors.h` | `ValueError` (model rule violated; Python `ValueError`) and `ManifestError` (unreadable manifest) |
| `manifest/json.h` | JSON values, strict parser, canonical writer |
| `manifest/sha256.h` | SHA-256 (FIPS 180-4) |
| `manifest/manifest.h` | Project ⇄ manifest, `SaveManifest`, `LoadManifest`, `ManifestDigest` |
| `manifest/recipe.h` | The recipe dump and digest, and the project a dump rebuilds (§8) |
| `schema/manifest.schema.json` | JSON Schema (draft 2020-12) of the manifest |
| `schema/recipe.schema.json` | JSON Schema of the recipe dump |
| `document/`, `transaction/`, `operation/`, `naming/` | Revisions, transactions, operation records, name addressing (`TRANSACTIONS.md`) |

## 2. Canonical form and digest

`SaveManifest` validates the project and writes UTF-8 JSON with no insignificant whitespace,
object keys sorted by their UTF-8 bytes, integers in decimal, other numbers in the shortest
round-trip form laid out like Python's `repr` (`1.0`, `0.0001`, `1e-05`, `1e+16`) and strings
escaped only where JSON requires it. The bytes equal Python's
`json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
(`tools/parity/recorder/job.py`, `canonical_json`), so the digest is the same in both languages
and independent of the order in which maps were filled. Unordered collections are written in a
fixed order: maps by key, `active_channels` by name, UV tiles by UDIM, resource entries by name.
Lists with meaning keep their order: texture sets (mesh material order), stacks, root layers and
sub-layers (top first, as Painter lists them), effects (stack order).

The parser rejects duplicate keys, invalid UTF-8, lone surrogates, non-finite numbers and integers
outside the signed 64-bit range, so a manifest that loads has exactly one canonical form.

## 3. Identity

Every node (layer or effect), texture set, stack, UV tile and resource entry has an id from the
project counter `next_id`, written to the manifest and kept on reload; ids are 1..2^63-1, unique
across the project and below `next_id`. Names are never identity: two layers named `M_piping`
keep distinct ids. Paint planes are referenced by `plane_id` (`09-…` §1), and no plane is bound to
two nodes.

## 4. Top-level keys

`schema` (`uzpainter/manifest/1`), `versions` (`format_version` semver, `app_version`,
`evaluator_profile`, `compat_profile` = `painter-12.1-api-0.3.7`, `painter_reference`), `next_id`,
`settings`, `mesh`, `texture_sets`, `resources` (SHA-256 → named entries sharing the bytes),
`display`, `export_defaults`, `metadata` (context → object). The schema lists every key; nodes in
a mask stack use mono-channel forms (`blending` is one `{mode, opacity}`, a fill has one `source`,
a paint node one `plane`), nodes in a content stack the per-channel forms.

A reader refuses a `format_version` of a newer major (`ManifestError`) and reads older or newer
minors. Keys this version does not know are kept at every level (`extra` members) and written back
unchanged.

## 5. Validation

`Validate` (run by `SaveManifest`, `LoadManifest` and `InsertNode`) throws `ValueError` for:
duplicate or out-of-range ids; resolutions that are not powers of two in 128-8192; a Default
workflow set without exactly the tile 1001; duplicate texture-set or stack names; per-node
channels that the stack does not have; opacities outside 0..1; payloads that do not match the node
kind; compare mask or colour selection effects outside mask stacks; per-channel forms in mask
stacks and mono forms in content stacks; smart-material provenance on anything but a group and
smart-mask provenance on anything but a mask effect; bindings to resources that are not stored;
malformed hashes and asset URLs; an instance of a layer of another stack; a reference to anything
but an anchor point of the same texture set; and any cycle of anchor references and instances
(`anchor reference cycle: …`). An effect may use an anchor that precedes it in the same list.

`InsertNode` applies the documented insertion positions: layers at the top of a stack, beside a
layer or inside a group's sub-stack; effects beside an effect or inside a layer's content or mask
stack (the mask must exist); compare mask and colour selection effects only in mask stacks. A
rejected insertion throws `ValueError` and leaves the project unchanged. New nodes get structural
defaults only; Painter's default parameter values for new nodes are Tier 0 observations and are
applied by the operations that create nodes, not by this model.

## 6. Known limits

`ChannelType` lists all 85 documented members (OpenPBR, user `User0`-`User31`, legacy and
legacy-alias names), each recorded with its documentation page in
`tools/parity/recorder/documented_symbols.json` (approved source A-PYDOC). A manifest naming another
channel type is refused with `ManifestError`, never misread.

## 7. Library and tests

`zig build uzp-core` builds the document model as the static library `uzp_core.lib` from
`src/uzp_core/` alone: it includes only its own headers and C++ standard headers and links no
render layer, render core, system library or GPU API (checked by
`tests/uzp_core/test_transactions.py`), so it builds and its tests run on the hosted CPU lane.
Both native test executables link it. The capability manifest generator is the separate
`zig build capabilities` step (`tools/capabilities/`).

`zig build uzp-core-tests` builds `uzp-core-tests.exe` (`tests/uzp_core/uzp_core_test.cpp`; own
code compiled with `-Wall -Wextra -Werror`). `python -m pytest tests/uzp_core` builds it, runs its
native cases and checks: a fixture covering every node, effect and source kind and both mesh-map
provenances round-trips (`tests/uzp_core/fixtures/every-kind.manifest.json`, digest pinned in the
test); the digest is the same for maps filled in either order, in two processes and in Python;
the schema accepts serialised manifests and rejects two channels of one type, resolution 3000, an
unknown `ChannelFormat` and a compare mask in a content stack; unknown keys survive; insertion
rules and anchor cycles raise; ids persist and same-named nodes keep distinct ids. No GPU is used.

## 8. Recipe dump (`manifest/recipe.h`)

Task `phase2.1_recipe-dump-manifest-blocks` (decision 122; `03-project-model.md` §5, §7; SAV-03,
SAV-04, INT-20, ARC-11). `DumpRecipe(project, revision, host)` returns
`{schema: uzpainter/recipe/1, revision, evaluator_profile, compat_profile, app_version,
resource_hashes, recipe, rebuild, digest}`.

- **The id-less document.** The manifest of the revision without ids, `next_id`, the version
  bookkeeping and the keys this version does not know (it reads none of them). A reference
  source's `anchor` and an instance layer's `instance_source` become JSON pointers into the node's
  texture set (`/stacks/0/root_layers/2/content_effects/1`). A paint node's planes become their
  content, `{chunk_root}` of the bound version (null when none is bound). Each stack channel gets
  `base`, the float32 backdrop the evaluator reads from the project's template (the one implicit
  default), and `settings.template` is always stated. `resources` lists the hashes the document
  references (the mesh and the files it reads beside it, mesh maps, source and procedural
  bindings), each `{mime, size}`; `resource_catalog` keeps every stored entry without its id.
- **`recipe`, the body.** The document's output-determining keys: everything evaluation, export
  (file names included: `$textureSet`, `$sceneMaterial`, `$mesh` read the set name,
  `original_name` and the import report) or the mesh's derivation reads. `digest` is the SHA-256
  of its canonical JSON (§2), so the same in C++ and Python.
- **`rebuild`, outside the digest.** `{<pointer into the document>: value}` for what only a rebuild
  needs: `display`, `export_defaults`, `metadata`, `painter_reference`, `resource_catalog`,
  `mesh.source`, the settings `default_resolution`, `mesh_unit_scale`, `import_cameras` and
  `auto_unwrap`, a set's `description` and `bake_settings`, a mesh map's `invalid_report` and its
  provenance but for `kind` and `declared_convention`, a channel's `label`, a node's `collapsed` and
  `preset_ref`.
- **Header.** ARC-11, outside the digest: the revision moves on inert commits, the app version and
  the compatibility profile do not change the output.
- **Rebuild.** `ProjectFromRecipe(dump, host)` checks the schema, the digest and the header (every
  key, `kCompatProfile`, the body's evaluator profile and hashes), puts the `rebuild` values in
  place (refusing a pointer to output-determining state or to a place the body lacks), gives fresh
  ids, resolves the pointers and validates. A channel `base` other than the host's (another build's
  template data) is a `ValueError`; paint plane content is `NotYetSupported`
  (phase4.1_nodes-paint-layers item 2.7). The rebuilt project's body and the rebuild values it
  holds must equal the dump's, so its digest is the dump's.

Tests: `tests/uzp_core/test_recipe.py` (native cases `recipe_dump_fields`,
`recipe_digest_invariance`, `recipe_rebuild`; the schema on the every-kind fixture; the digest
recomputed in Python; the rebuild through the command line).
