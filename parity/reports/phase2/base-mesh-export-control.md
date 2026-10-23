# Documented base-mesh export control

2026-10-23. The documented `substance_painter.export.export_mesh(path,
MeshExportOption.BaseMesh)` route exports the current undisplaced mesh. This
control establishes repeatability for three authored fixtures; it does not
recover original mesh-file bytes or establish Tunic input identity.

## Protocol and identity

The fixed request preceded capture: three authored meshes, OBJ and FBX, each
exported twice in one project and again after Full save, close and reopen.
The recorder checked edition readiness, busy state, Painter identity and the
current envelope before calls. Every export used a fresh destination. No pilot
project was opened, no retry was used and no golden was admitted.

- Envelope: `painter-12.2.0+js-api.1.1.20-env-a981b586eae7`.
- Colour mode: OCIO, Substance configuration SHA-256
  `8f384af9da9410394dbc6f1eb5395530c7532dbbac8cb59bc2e9ea3abc32ff10`.
- Project creation: texture resolution 256, mesh unit scale 1.
- Native inspector SHA-256:
  `957834bff2e80f63732cb5c8fa82c216b56ecb5c86079612e9a9aad1367b743b`.
- Private evidence: `UZP_ORACLE_WORK/mesh-export-qualification/run-_ddmbxhw/`,
  request, identity, 18 exports, native inspections and `report.json`.

| Fixture | Authored source SHA-256 |
| --- | --- |
| `grid2x2.obj` (plane) | `5b9df6c8bcc30a44ebe29ecde614f0cb846bf8c960c46d6e58a6a52d056b9819` |
| `sphere.obj` | `d263a715bce05810252aebbffec801645fb60a991d2311536935503c79640476` |
| `bevelled-cube.obj` | `97a84dcc86ed55ea2e1f88f1d632a0fb28e0110b5512219e91ab11553bdb3824` |

## Results

All 18 calls returned `Success`; all 18 files imported successfully. For each
mesh, OBJ file bytes repeated exactly in-session and after reopen. FBX file
bytes changed, while imported geometry repeated exactly in both comparisons.
UV and material hashes matched the authored source in all six mesh/format pairs.

| Format / fixture | Comparison with authored mesh |
| --- | --- |
| OBJ / plane | All native mesh hashes equal. |
| OBJ / bevelled cube | Oriented triangle attributes equal; position/index hashes differ because indexing changes. |
| OBJ / sphere | Corner positions equal; 144 normal components differ, maximum absolute difference `1.01327896e-6`. |
| FBX / plane | 12 position components differ, maximum `4.76837158e-7`; normals and UVs equal. |
| FBX / sphere | 1320 position components differ, maximum `4.76837158e-7`; 7592 normal components differ, maximum `5.36441803e-7`. |
| FBX / bevelled cube | Positions and UVs equal; 1116 normal components differ, maximum `2.38418579e-7`. |

Component diagnostics compare matching array indices, not a fitted spatial
correspondence. The oriented-triangle comparison permits cyclic rotation only:
reversed winding, changed position, normal or UV fail its authored self-checks.
Object transforms are not exposed by this inspector output; equality here must
not be extended to unmeasured transforms or other attributes.

## Recovery boundary

The route is usable for a separate controlled comparison of the effective mesh
in a preserved SPP and in a project created from a delivered mesh. Its measured
losses forbid treating an exported OBJ or FBX as the original normalized OBJ by
file identity. Even equal exported geometry would not establish original bytes
or authorize a changed baseline. Tunic's missing `normalized_low.obj`, nine
masks and item 2.8 remain unresolved.

The production helper preserves status and message without promoting warnings
or errors to success. Six unit cases verify the fixed BaseMesh option and
refusal before export when the project is unavailable or busy; the documented
symbol inventory and recorder provenance checks cover the added API route.
