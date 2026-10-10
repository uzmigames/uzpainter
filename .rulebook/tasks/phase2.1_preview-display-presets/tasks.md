## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand

## 2. Implementation
- [ ] 2.1 Display preset schema and serialisation, separate from presentation snapshots
- [ ] 2.2 Common comparison standard and `ref_match` preset implemented from `Render-Comparison-Standard.json`
- [ ] 2.3 Environment storage as bytes plus SHA-256 and explicit missing-environment error
- [ ] 2.4 CC0 environments under UzPainter names in `assets/` with `<name>.provenance.json` records
- [ ] 2.5 Camera model and conversion to and from the Blender convention per the standard's `coordinate_contract`
- [ ] 2.6 Native display and shader API, documented `substance_painter.display` symbols, worker handlers for `display_*`, `shader_*`, `camera_*`

## 3. Tests
- [ ] 3.1 Preset round-trip (serialise, load, compare) and `ref_match` values against the pipeline standard
- [ ] 3.2 Missing environment hash fails explicitly with no substitute
- [ ] 3.3 Camera conversion fixture: round trip and agreement with the coordinate contract on known cameras
- [ ] 3.4 `set_tone_mapping` on a colour-managed project raises `RuntimeError`; on a Legacy project it round-trips through set → get → save → reopen → get
- [ ] 3.5 Provenance records of shipped environments validate against the provenance schema

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.3_realtime-preview`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
