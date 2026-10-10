## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase0.9_normal-convention-fixture

## 2. Children (each accepted before this parent closes)
- [ ] 2.1 `phase1.4_mesh-importers` accepted
- [ ] 2.2 `phase1.5_mesh-tangents-certificate` accepted
- [ ] 2.3 `phase1.6_mesh-reload` accepted

## 3. Tests
- [ ] 3.1 Run the complete `docs/architecture/12-mesh-import.md` §9 fixture set on one build: mirrored UVs, hard edges, negative OBJ indices, n-gons, duplicate material names, instances/transforms, units, multi-set body, coincident opposite faces
- [ ] 3.2 Run the reload/rename/split fixtures (bindings preserved or deliberately rejected)
- [ ] 3.3 Re-run the normal-convention fixture with the production loader and tangents: Painter hemisphere bake (private oracle) vs UzPainter in tangent space, and the same map shaded in UzEngine's own executable as an external consumer on the self-hosted runner

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-MESH gate): `12-…` §9 fixtures pass; results recorded in `parity/reports/phase1/` for the G1 gate record (certificate and reload fixtures)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
