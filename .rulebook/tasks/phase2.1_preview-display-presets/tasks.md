## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand

## 2. Implementation
- [ ] 2.1 Display preset schema and serialisation, separate from presentation snapshots; display configuration pinned to OCIO (Painter's substance config by hash, view `Default - sRGB`) by decision 038
- [ ] 2.2 Common comparison standard and `ref_match` preset implemented from `Render-Comparison-Standard.json`
- [ ] 2.3 Environment storage as bytes plus SHA-256 and explicit missing-environment error
- [ ] 2.4 CC0 environments under UzPainter names in `assets/` with `<name>.provenance.json` records
- [ ] 2.5 Camera model and conversion to and from the Blender convention per the standard's `coordinate_contract`
- [ ] 2.6 Native display and shader API, documented `substance_painter.display` symbols, worker handlers for `display_*`, `shader_*`, `camera_*`; setters accept the fixed pipeline's values and reject every other value with an unsupported-value error; colour LUT pinned to none and shader parameters pinned to the default `open-pbr` instance by decision 038 (decision 042)

## 3. Tests
- [ ] 3.1 Preset round-trip (serialise, load, compare) and `ref_match` values against the pipeline standard
- [ ] 3.2 Missing environment hash fails explicitly with no substitute
- [ ] 3.3 Camera conversion fixture: round trip and agreement with the coordinate contract on known cameras
- [ ] 3.4 `get_tone_mapping` and `set_tone_mapping` on a colour-managed project raise `RuntimeError`. Tone mapping is pinned to not applicable (OCIO `Default - sRGB`) by decision 038, so on a Legacy project they raise the unsupported-configuration error instead of round-tripping. A colour LUT, display value or shader parameter outside the fixed pipeline raises the unsupported-value error and leaves the state unchanged
- [ ] 3.5 Provenance records of shipped environments validate against the provenance schema

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.3_realtime-preview`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
