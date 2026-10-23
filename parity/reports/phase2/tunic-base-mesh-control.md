# Tunic effective base-mesh comparison

2026-10-23. Four documented BaseMesh OBJ exports completed successfully. Each
project repeated exactly, but the preserved SPP and the project created from
the delivered FBX did not export equal geometry. This control does not recover
the missing normalized input or authorize a replacement baseline.

## Fixed protocol

The request was written before Painter launch. Private copies of the pinned
SPP and FBX were used; original hashes were rechecked after the run. The SPP
copy was opened without saving. A separate project was created from the FBX
with explicit texture resolution 256 and mesh unit scale 1. Each project was
exported twice to fresh OBJ destinations with
`substance_painter.export.export_mesh(path, MeshExportOption.BaseMesh)`.
There were no retries, fitted transformations or adjusted import settings.

Edition readiness, busy state, process/build identity and the current envelope
were checked. Documented project readbacks recorded the file path, last
imported mesh path and scene bounding box. The installed project documentation
provides creation `Settings`, but no getter for current project settings;
historical SPP mesh unit scale and projection settings remain unknown. The
explicit FBX scale 1 is a control hypothesis, not a claim about those settings.

- Envelope: `painter-12.2.0+js-api.1.1.20-env-a981b586eae7`.
- Recorded colour-configuration fingerprint:
  `8f384af9da9410394dbc6f1eb5395530c7532dbbac8cb59bc2e9ea3abc32ff10`.
- Installed Substance OCIO configuration file SHA-256:
  `15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4`.
- Native inspector SHA-256:
  `957834bff2e80f63732cb5c8fa82c216b56ecb5c86079612e9a9aad1367b743b`.
- Private evidence: `UZP_ORACLE_WORK/tunic-base-mesh-control/run-fdv1llk3/`.
- Request SHA-256:
  `b8d9294cd9fa4d7e63c2f254f1a5aa5f74f9f61a633c283372fcf8243e9bdf66`.
- Report SHA-256:
  `1cf179b02bc47689ad82ebe61bd9c1ee3a6dcc17a847d1acd24eab1c58a46dfe`.

| Input | SHA-256 |
| --- | --- |
| Preserved Tunic SPP | `c43db46a2f2d4d935fa33cd62956ce7b4d097f00b45c93798ef9f498b27153a6` |
| Delivered Tunic FBX | `ad7ef061e244a52f51a5f99af7df028ac4e7f7f80d5f0b68fee06dc374230e0a` |

## Results

All four export calls returned `Success`; all four native imports succeeded.
Both origins produced 33000 corners and 11000 triangles. Within each origin,
repeat OBJ bytes, native hashes, ordered corners and oriented triangle
multisets were identical.

| Origin | OBJ SHA-256, identical across both exports |
| --- | --- |
| SPP | `fc6f6da5274c2befd9bd9e6988a9041690fe381de3af98993f40e46de2a9e471` |
| FBX project | `5990bc071c686e3dd9ac69fe3e73ba14f932a306046ac80d92a770e4d0d43a23` |

Across origins, the triangulation hash matched; position, corner-normal, UV
and material hashes differed. Ordered corners, corner multisets and oriented
triangle multisets differed. Object names and materials differed; secondary
UV-set lists compared equal. That last result establishes no additional UV
coverage beyond what the inspector exposes.

| Ordered-corner field | Differing components | Maximum absolute difference |
| --- | ---: | ---: |
| Position | 99000 | `156.0961835384369` |
| Normal | 96952 | `6.496906280517578e-05` |
| UV0 | 8 | `9.5367431640625e-07` |

Component metrics compare equal array indices, not fitted correspondence.
The oriented-triangle comparison permits cyclic rotation only and retains
winding and corner attributes. Object transforms are not separately exposed
by the inspector.

The documented scene bounding-box dimensions differ by approximately a factor
of 100, without asserting an exact relation or applying a correction. Raw
dimensions remain in the private readbacks. The SPP still reports
`normalized_low.obj` as its last imported mesh. No missing source bytes were
recovered.

## Boundary

The explicit FBX import does not reproduce the SPP's effective base mesh.
Unknown historical settings prevent attributing every difference to a specific
cause. Neither repeatability nor matching triangle counts establishes source
identity. No geometry, project bytes or oracle output is included here; full
exports, readbacks and inspections remain private. No golden or replacement
baseline was admitted. Missing normalized input, nine masks and item 2.8 remain
unresolved. Painter was closed after capture.
