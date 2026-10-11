# Tier 0 UI-only cases and the Phase 1 recording requests

Task `phase0.7_tier0-semantics-ui-cases`; decisions 029, 047 and 048. This report holds numbers and hashes only. Every export, readback and panel image is in the private store.

**Result (2026-10-11, Painter `12.1.5+js-api.1.1.20`, the current envelope, under the Assets3D Painter lock, Legacy colour management).** Ten goldens were recorded, each twice in one run: `r1` in the same session and `r2` after save and reopen. All ten were admitted with `uzpainter parity record` (`python -m tools.parity.store record --run`), and `verify` and the guard pass.

- Seven are UI-case goldens. In them, the operator of `tools/parity/recorder/texture_sheet.py` set every UI value through Painter's panels by Windows UI automation (`painter_ui.py`). Each value was read back after it was applied and read again after the reopen. A layer's mode was also read through the documented `Node.get_blending_mode`.
- Three are documented-API goldens that Phase 1 requested.

## 1. What Painter 12.1.5 exposes (decision 047)

| Case | Where | Values | API |
|---|---|---|---|
| Height-to-normal method | Texture Set Settings > Channels, per texture set | `Sharp` (default), `Smooth (Sobel)` | none |
| Height-to-normal strength | no such control in Texture Set Settings, Shader Settings (open-pbr, pbr-metal-rough-with-alpha-test), Project Configuration, Edit > Settings or a Height fill's Properties | — | — |
| Group Passthrough | Layers panel, the row's blending-mode menu, per channel of the channel selector | `Passthrough` (the row shows `Pthr`) | getter returns the runtime member `Passthrough` (25); the documented `PassThrough` does not exist |

The strength sweep is a height-amplitude sweep per method: opacity 1, 0.75, 0.5, 0.25 and 0.1, plus 2, 3 and 4 copies stacked in LinearDodge. It stands in for a strength setting that Painter does not have (decision 047).

## 2. Goldens

Manifests: `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier0/semantics-ui/` and `.../tier0/semantics/` (the last three rows). "Panel images" counts the private `settings_panel_evidence` blobs over both recordings.

| Golden | Private record (SHA-256) | Maps per recording | Panel images | r1 = r2 (maps) |
|---|---|---|---|---|
| `tier0/semantics-ui/height-normal-sharp-sphere` | `28a1fbfc270306376ee5c1e50738edf5646e11b8ad1fc91c3dbb1f4f8a6e3721` | 4 | 2 | 4/4 |
| `tier0/semantics-ui/height-normal-sobel-sphere` | `33cf373c58d97c9a5fa38174812199c753ea885ae876c38cfbf32bd6ea9bd488` | 4 | 2 | 4/4 |
| `tier0/semantics-ui/height-normal-sharp-bevelled-cube` | `0d52e0c85381894450da2cd728236b1d52678675e48abc443156cdf2fe67cd43` | 4 | 2 | 4/4 |
| `tier0/semantics-ui/height-normal-sobel-bevelled-cube` | `0836b799ac2138e36ae077fca8adaaa53f1862092aa71cce56786b59fb9da6c4` | 4 | 2 | 4/4 |
| `tier0/semantics-ui/height-normal-sharp-plane-strength` | `2fe57df3bd838b54ba1c3c39d9948c674260415b206a8b56ca68aa06b2c304ec` | 32 | 16 | 26/32 |
| `tier0/semantics-ui/height-normal-sobel-plane-strength` | `c427fce046ae6c0b2e751b9ba78c3e45ea0fd5adf64d8a6d48fc4a1431da20e8` | 32 | 16 | 26/32 |
| `tier0/semantics-ui/group-passthrough-masks` | `a0de2aa898ec4f7426ce63758e9a09132198176510c4f91936f6099becc61718` | 24 | 24 | 24/24 |
| `tier0/semantics/resample-uv-minify` | `65e85020f81558fcce07bc40e90128ca25522f270551d75acfc48280d7cb067b` | 32 | 0 | 32/32 |
| `tier0/semantics/resample-uv-impulse` | `d4e0d8c2bef7d5e80b1aaeba52ee7fee86a62fcb998bfa18baff5ebfab9b0395` | 32 | 0 | 32/32 |
| `tier0/semantics/group-coverage-order` | `a58ea909846c403fb0d2a99c679b0d4705730e16658063aef147c8eb6d7d5cc0` | 24 | 0 | 24/24 |

## 3. Stability and cross-checks

- **Save-reopen instability (decision 032: r1 is the exact target).** Both `plane-strength` goldens differ between r1 and r2 on s1 (opacity 0.75) and s4 (opacity 0.1). Every other set and every readback is equal.

  | Golden | Map | Max \|Δ\| | Differing values |
  |---|---|---|---|
  | Sharp | s1 Height (EXR 32f) | 2^-11 | 30 640 of 65 536 |
  | Sharp | s1 Normal_OpenGL | 31 codes | 42 242 of 196 608 |
  | Sharp | s4 Height | 2^-14 | 65 536 of 65 536 |
  | Sharp | s4 Normal_OpenGL | 10 codes | 22 350 of 196 608 |
  | Sobel | s1 Normal_OpenGL | 16 codes | 53 371 of 196 608 |
  | Sobel | s4 Normal_OpenGL | 6 codes | 24 753 of 196 608 |

  The Normal_DirectX maps differ in the same way. The opacity readback is equal in r1 and r2, so the instability is in Painter's evaluation after the reopen, not in the stored value the API reports.
- **Explicit Sharp = default.** On the sphere and the bevelled cube, every map of `height-normal-sharp-*` is byte-identical to the existing default-method golden `height-normal-*` of the same envelope. `plane-strength` s0 (opacity 1) equals `height-normal-plane-amplitudes` s0 on all four maps.
- **Sobel against Sharp.** Only the `Normal_OpenGL` and `Normal_DirectX` virtual maps differ. The Height and Normal channel exports are identical, so the method acts only in the virtual-map conversion.
- **Passthrough against Normal.** In `group-passthrough-masks`, the Normal controls s4 (no mask) and s7 (both masks) are byte-identical to `group-masks` s1 and s3 on all three channels. That recording was made in a different session. The Passthrough sets s0-s3 differ from Normal.
- **Stability report.** `parity/reports/phase0/tier0-stability.md` was regenerated by `python -m tools.parity.fit` with no fit re-run. It now covers every Tier 0 golden of the current envelope: 69 goldens, 59 stable and 10 unstable. The two `plane-strength` goldens are among the unstable ones. No `parity/semantics/` file changed. Before this run the report still described the 12.1.0 corpus.
- **Operator verification.** Every sheet value was shown by its widget and read again after the reopen: 1 or 8 method entries per height golden, and 12 Passthrough entries, each also read as `Passthrough` by `Node.get_blending_mode` in r1 and r2.

## 4. Reproduce

```
python -m tools.parity.tier0_semantics check
python -m tools.parity.recorder record <semantics-ui manifest> --operator ui     # Painter visible, no OCIO
python -m tools.parity.recorder record <tier0/semantics manifest>
python -m tools.parity.store record <manifest> --run <inbox run>
python -m tools.parity.store verify parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier0
python -m pytest tests/parity/test_tier0_semantics_ui.py tests/parity/recorder/test_texture_sheet.py
```
