# R-314 glTF preset observations

Date: 2026-10-23. Envelope: `painter-12.2.0+js-api.1.1.20-env-a981b586eae7`.
This report describes behavioural confirmation on the authored bevelled cube. It
contains no serialized preset readback, exported image, mesh or scene. Those
records remain in the private oracle store; public manifests pin their hashes.

## Evidence

The current envelope's `manifests/tier0/semantics/` contains:

| Golden | Private record SHA-256 | Outcome |
| --- | --- | --- |
| `export-presets-gltf-legacy` | `84e781acd971bbf87d35f774c78a07825e3fcec6f368f818979dc4b6c9417f89` | Starter-assets URL rejected |
| `export-presets-gltf-ocio` | `297c38c5eb65a557f79ff7233f08e886ee521a2e9314350a6a190197e1acbab2` | Starter-assets URL rejected |
| `export-presets-gltf-predefined-legacy` | `4ddfb774cf84f9631e0d64f467222ec9b6fb46988e31507eba4c6482411d77ce` | Pipeline export succeeds |
| `export-presets-gltf-predefined-ocio` | `4b665fe32a085ca75e70b0fae125f1db9f67cfadb20fc626fda20f81ce3784cd` | Pipeline export succeeds |
| `export-presets-gltf-predefined-padding-legacy` | `e729f2294b0d4acc019a2fa7b025c01df0821fa9dd9acf78ee00fcce4e4ce2fd` | Padding-only export succeeds |
| `export-presets-gltf-predefined-padding-ocio` | `4076be7a5e2026554c62512f14d258b188f7988a42e6e1430830dc2e5dfe6ec7` | Padding-only export succeeds |

Each has a same-session recording and a recording after full save/reopen. Legacy
and OCIO used separate launched processes. The Legacy environment matched the
promoted envelope; OCIO matched its non-colour host fields and the installed
configuration SHA-256
`15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4`.
The successful predefined captures record recorder fingerprint
`uzp-recorder/1+src.5b1d7522c0d41c99`. Recorder versions are recorded provenance,
not envelope identity fields (`tools/parity/recorder/environment.py`).

## Findings

1. `resource://starter_assets/glTF PBR Metal Roughness` is undefined. The
   predefined URL is `export-preset-generator://gltf`. Negative captures remain
   evidence of rejection, not successful preset exports.
2. The independently authored glTF layout needs one ORM image: occlusion in R,
   roughness in G and metallic in B. Base colour carries opacity in A; normal
   uses the OpenGL convention; emissive carries RGB. The separate white-R
   metallic-roughness and greyscale occlusion hypothesis was incorrect.
3. The documented predefined output-map capture identifies PNG8 defaults,
   dithering enabled only for normal. Calling without export parameters raises
   `ValueError` because padding cannot be resolved. Pipeline overrides produce
   four PNG16 files with dithering disabled. Default-parameter pixel capture
   therefore requires explicit padding. The padding-only follow-up confirms four
   PNG8 files in both colour sessions, all byte-identical across save/reopen.
4. All four pipeline PNG hashes repeat exactly across save/reopen within each
   colour session. Normal and ORM also match between Legacy and OCIO. Base colour
   differs in 57,400 components and emissive in 58,701, with maximum absolute
   16-bit code difference 270 for each. The sessions also differ in template and
   channel setup as declared by their requests; this is not an isolated OCIO
   transform experiment.
5. The export also writes `.gltf`, `.glb` and `.bin` scene files that are absent
   from its returned texture list. The recorder preserves them as fenced, hashed
   `exported_sidecar` blobs, validates glTF local buffers and GLB container
   structure, and makes no pixel-storage claim for them. Scene filenames change
   when the project is saved. They are not evidence that UzPainter's texture
   preset generates equivalent scenes.
6. Painter writes no SpecularWeight texture in this preset. Decision 023 still
   requires its explicit supplemental UzPainter export and receipt consumer gap.
   Its provenance is `defined`, not `confirmed` against Painter.

## Implementation and limits

The authored preset uses the confirmed four-map layout plus the explicit
SpecularWeight extension, with authored PNG8/no-dithering defaults overridable
by pipeline parameters. Its provenance remains `status: pending`: layout
confirmation is not decoded-output parity. Aliases use the observed predefined
URL; the disproved starter-assets URL no longer resolves to this preset.

`AO_Mixed`, unsupported infinite/islandnormal padding and unproved export paths
remain refused. Wand, belt and tunic output parity, the real Wand consumer run,
pilot prerequisites and parent acceptance remain open. The existing consumer
accepts one published ORM file bound to both occlusion and metallic-roughness;
its fixture tests remain authored CPU evidence, not Painter or Wand acceptance.

Validation: 57 recorder/sidecar tests and the final 29 preset, consumer and
padding-only request tests passed. The
private-layout test compares the independently authored layout with R-314 and
checks pipeline repeat hashes; it does not compare UzPainter output pixels to
Painter pixels. The coordinator's final rerun passed 29 tests after checking
SpecularWeight defaults; all 118 guard tests passed with the consumer schema's
resolved R-314 blocker removed and its remaining acceptance blockers retained.
Ruff, mypy and scoped diff whitespace checks passed.
