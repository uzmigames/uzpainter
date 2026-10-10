## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.2_parity-contract

## 2. Implementation
- [ ] 2.1 Recorder session module: connect to Painter 12.1.0 started with `--enable-remote-scripting`, record the Painter build id and the software identities the public schema requires
- [ ] 2.2 State recording through the documented Python API (project creation settings, instruction sequence replay, `Property` readback, effective defaults), written from `python-doc` only
- [ ] 2.3 Texture capture through `export_project_textures` at 16 bit or float with readiness (evaluation finished) and current-output verification
- [ ] 2.4 Iray capture path per `07-preview-and-render-parity.md` §2.2: apply and read back documented settings, switch to Iray mode, settings sheet, convergence check, Save Render, current-frame verification
- [ ] 2.5 Operator form for settings the API does not expose, storing entered values and an image of each settings panel as private evidence
- [ ] 2.6 Two-recording rule: each golden recorded twice (same session; after save/reopen) and both records kept
- [ ] 2.7 Output writer: private records per `parity/schema/golden-private.json` to a private directory outside the repository, public manifest with SHA-256 per `golden-public.json`

## 3. Tests
- [ ] 3.1 Provenance test over `tools/parity/recorder/*.py`: every `substance_painter` symbol used appears in `python-doc`; no underscore/private attribute access; no import of the community MCP bridge
- [ ] 3.2 Output test: records validate against `golden-private.json`, manifests against `golden-public.json`, and no record is written inside the repository tree
- [ ] 3.3 End-to-end Tier 0 sample on the owner's machine: authored fixture, instruction sequence, export and readback recorded twice with hashes in the public manifest

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-RECORDER): a Tier 0 sample recorded end to end; no bridge code path; no private interface

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
