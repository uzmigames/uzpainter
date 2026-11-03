# Normal with an empty Height: frozen predictions

Date: 2026-11-03. Status: one authored request, not yet recorded. There is no reference or
production change, and refusals 245 (§1 and §2) and 090 stay. Task: phase1.25_pilot-wand,
item 2.7. This note is written before any Painter data, on Codex root's GO for source
preparation only (no capture, no native prediction run).

## Why

Decision 245 §2 refuses a virtual normal on a UV-islanded set whose Height has no layer: its
premise (the stencil reads 0 everywhere) is contradicted by R-092, where Painter's other virtual
maps read an empty channel as a non-base constant. It names the recording that would lift the
refusal: the Tier 0 sphere with no Height layer, a Normal channel fill and a bound 16-bit Normal
mesh map, exporting `Normal_OpenGL` at PNG 16 and OpenEXR 32f under `infinite` and
`passthrough`, recorded r1 and r2. No existing golden is that case: `export-padding-normal-combine`
sets Height on both sets and exports only `infinite`, and decision 293 excludes it.

## The probe

One API probe request (`tools/parity/tier0_semantics/normal_empty_height.py`) under the current
envelope's `requests/tier0/api-probes/`, `export-padding-normal-empty-height`:

| Pin | SHA-256 |
| --- | --- |
| Request bytes, as committed (LF) | `bb2ea0297ebfcfd6ad1e3b48d41f8d18e0201c9fd2a55f2c3a74ebf33cff844a` |
| Request, canonical JSON | `c384d9290da406a8e0dd632dd8ac245867a17005f38644e0fe40df41f3381d06` |
| Instruction sequence, canonical JSON | `343e75b5174ba515e1eccf24e6622b80eeab994a6ed400d362929a475feae559` |
| `sphere`, `parity/fixtures/tier0-semantics/meshes/sphere.obj` | `d263a715bce05810252aebbffec801645fb60a991d2311536935503c79640476` |
| `normal-a`, `parity/fixtures/tier0-semantics/bitmaps/normal-a.png` | `4f8b9665b5c3d6ed7dff89b2b66c0ceeb138d67e453c871e9fb07e8fe0ac2c4d` |
| `normal-b`, `parity/fixtures/tier0-semantics/bitmaps/normal-b.png` | `d6b52db099f6bd551a57632524cc66a9e8bda8c0867fbd31fdbcafa7a19aacea` |

The sphere has one set, `uzp_sphere`, with incomplete coverage (the pole rows are half covered).
Both bitmaps are 256 x 256 16-bit RGB, n * 0.5 + 0.5. The coverage counts used below, 59,264
interior and 2,176 edge texels (61,440 covered) at 256 px, come from decision 245's earlier
evidence and the native authored coverage of this mesh; a Painter export carries no coverage
mask, so they are not read from the recording.

Legacy colour management, 256 px, OpenGL. The steps:

1. `project.create`, then the guarded one-shot initial Paint cleanup at step 2
   (`painter_probes.remove_initial_paint`): the owned create's UUID, exactly one `PaintLayer`
   root, deleted, no root left. A fresh project's Paint layer has a Height channel, so without
   this step a Normal-only fill would sit over a Height layer.
2. Import normal-a and normal-b; bind normal-b as the Normal mesh map.
3. One fill, only Normal active, named, visible, Normal blend at opacity 1, no geometry mask,
   UV projection with identity Nearest Repeat parameters (decision 249's admitted 1:1 Nearest
   case), its Normal source normal-a. No step adds a Height layer, sets a Height source or
   activates the Height channel; only the control export below reads Height.
4. Getters, run in r1 (`same_session`) and again in r2 (`after_save_reopen`) through fresh
   handles, with no setter or cleanup replayed: the full root tree, the fill's name, visibility,
   blend, opacity, geometry mask, mask, content effects, source mode, active channels and
   projection, the owned project UUID, both resource joins (`from_project`, `retrieve`), the
   fill's source and the Normal mesh map.
5. Captures in both recordings, each done twice in a row and keyed by step, no dithering:
   `Normal_OpenGL` at PNG 16 and OpenEXR 32f with `infinite` and `passthrough`, and an OpenEXR
   32f `infinite` control of `documentMap/height`, `documentMap/normal` and `meshMap/normal_base`.

## Void rules (declared before capture)

### Enforced now by the state gate

`normal_empty_height.py` refuses, rather than reports. The caller verifies that the manifest is
the committed request and passes the identities from the verified import receipt and the r1
cleanup outcome; the functions check what they are given.

- `validate_cleanup`: the receipt names the created UUID before and after, one `PaintLayer` with
  a positive integer uid before, and an integer root count of 0 after, with no other field.
- `validate_observed_state`, per recording:
  - the root tree is exactly the one authored `FillLayer` with no mask, no content effect and no
    mask effect;
  - every authored getter equals its literal and none raised;
  - each `from_project` resource has a non-empty string context, name and version, the name and
    version those of its import receipt, and `retrieve` returns exactly it;
  - the fill's source joins normal-a and names a non-empty string colour space; the Normal mesh
    map joins normal-b;
  - the owned project UUID is the created one;
  - the single texture set is `uzp_sphere` at 256 px with Normal and Height channels, each
    described with a non-empty format, a positive integer bit depth and boolean flags. Their
    values are measured, not pinned here.
- `validate_pair`: the cleanup receipt holds, there is one recording per condition, and r1 and r2
  measure the same channels and source colour space.

### For the later pixel gate (not implemented here)

A separate checker, reviewed before it runs, applies these. It derives the covered and uncovered
texels from a fixed mask built from the pinned mesh and its raster contract, never by
classifying texels by their exported values.

- The covered texel count of that mask is 61,440.
- `documentMap/normal`: the bits the native export engine writes for normal-a on the measured
  Normal channel format under decision 249's admitted 1:1 Nearest rule (decode/import, channel
  storage and composition, readout, then the OpenEXR 32f writer). It is not a raw code / 65535
  equality with the bitmap.
- `meshMap/normal_base`: decision 079 F1's codes of normal-b written as float32 UNORM by the
  OpenEXR 32f writer, a separate rule. In this OpenGL project no green flip applies; the flip is
  only a convention difference.
- `documentMap/height` is an observation: a signed float32 file read as written, with no PNG
  remap and no assumption that an empty channel is 0. It is not proof of the Height value the
  virtual normal reads internally.

## Frozen predictions

- **Stability.** Covered texels: r1 = r2 = the same-session repeat, in both formats and both
  paddings, and Painter's covered texels the same under `infinite` and `passthrough`.
  Uncovered texels under `infinite`: stable, by decision 293's rule. Uncovered texels under
  `passthrough`: counts only; they predict and decide nothing (decision 245: 37,095 of 37,214
  changed between r1 and r2 without a mesh map).
- **Fixed prediction (H0).** The native `uzp-export-tests export-diagnostic` output (decision
  308's path) under `infinite`, in both formats, computed with the virtual normal's Height flat,
  so that the Normal channel and the bound mesh map alone make the normal. Every covered texel,
  edge included, is predicted to equal it. The native prediction is `infinite` only: the
  diagnostic still refuses a virtual Normal under `passthrough` (`src/export/guards.cpp`
  255-286), and no guard changes. Painter's covered `passthrough` texels are compared with
  Painter's covered `infinite` ones, then with the native `infinite` prediction.

## Outcomes, declared before capture

| Outcome | Reading |
| --- | --- |
| Interior and edge equal the fixed prediction, r1 = r2 | consistent with H0 on this case; not proof that Painter's empty Height is internally constant. Lifting decision 245 §2 needs its own review |
| Interior equal, edge differs | the complete fixed prediction is refuted on the edge; that does not by itself show a non-flat Height, since another composition or numeric assumption may be what fails. §2 stays |
| Interior differs | void for this comparison: diagnose the preconditions and the model. When every state readback passed, this is not read as a wrong stack |
| Covered `passthrough` differs from covered `infinite` | reported; the native prediction is not applied to `passthrough` |

## Before capture

Capture, the pixel checker and the native prediction run each need their own review and GO.
Nothing here claims that the Wand is unblocked, and no tolerance, fit or admission follows from
this note.
