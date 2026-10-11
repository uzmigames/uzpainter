# Iray capture procedure `iray-capture/1`

Task `phase0.6_render-reference-procedure` (child of `phase0.9_render-reference-capture`, P0-FEAS-RENDER in `docs/dag.md`). It qualifies the capture procedure of `docs/architecture/07-preview-and-render-parity.md` §2.2 for the fixed render pipeline and answers every "not confirmed" row of §2.1 and the bump-or-displacement question of §3.3. Decisions 002 (clean room), 018 (Iray is the render-parity target), 022, 029 (UI automation), 038 (fixed pipeline) and 039 (pixel route and automation) apply. This report holds statuses, answers, numbers and SHA-256 hashes only. No Painter pixels are in it: probe renders, panel images and readbacks stay in the private work directory on the owner's machine.

**Status (2026-10-11).** Qualified. The probe session and the qualification run were made on Painter `12.1.5+js-api.1.1.20` (the current envelope, decision 037), Windows 11, RTX 4090. The UI operator `tools/parity/recorder/painter_ui.py` operated the panels under the Assets3D Painter lock. Every row is settled. The only `uncontrolled` row is the random seed.

**Scope change (decision 038, 2026-10-11).** The owner fixed the render pipeline ("nao tem a necessidade do uzpainter ter todas as configuracoes de render do substance, nossa pipe de render e sempre fixa"). The procedure covers only the Assets3D render comparison standard: `E:\UzmiGames\Assets3D\Pipeline\render\Render-Comparison-Standard.json` (approved source `U-A3D-RENDERSTD-2`, `docs/approved-sources.md`; file SHA-256 `2ec4281f7a1414c836eb59aec4fa895db0706c2fc9c4e19433325939a6525be5`), summarised in `docs/analysis/assets3d-pipeline/06-review-render-standard.md` §2. That means the v2 top-level block, the `ref_match` v3 preset and the `base_color` diagnostic. Every other Iray or display setting is pinned to the standard's value or to Painter's default and is not a supported variable. The first version of this report planned open-ended probes: colour-profile LUT placement, tone-mapping and post-effect sweeps, the Viewer/MDL parameter sweep, and setting persistence across projects. Those probes were dropped. Their rows are answered `not_required` with the pinned value, or settled for the pinned values only.

**Prior Assets3D evidence** (referenced by path and hash, not copied):

- `Render-Comparison.md` (`cf34ec2c8c2fb8dc041be000887f03d5c57b673dd762f77ecfd7ccd22ec36925`): the OCIO selection is not saved with the project; `display.save_viewport` returned a stale camera in 12.1; Iray pauses the layer engine; the custom clear colour is not serialised.
- `Render-Standard-Validation.json` (`3de3c4af0bf7c7d3d3e1aa201c98c19618da30a1882b6ce4c97cd1f4d964ee91`): Painter's Default/sRGB view equals the sRGB transfer function within 0.0015 of an 8-bit code. Its config is `resources/ocio/substance/config.ocio`, SHA-256 `15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4`; re-hashed identical on 12.1.5.
- `painter_render_standard.py` (approved source `U-A3D-RENDERPY-2`; file SHA-256 `1ac9fd73ffaa55580cadfdb220b3997e0204a67d2f13ec881805ede410ca4238`): which widgets the standard touches.

## 1. Answers

The table below is generated from the JSON block that follows it. `python -m tools.parity.render_procedure answers` checks the block, and `--merge <probe directory>` folds a finished probe in. Statuses:

- `documented`: settled by public documentation (A-PYDOC, A-JSDOC, A-HELP-*).
- `confirmed_by_probe`: settled by the black-box probe (A-OBSERVE), for the pinned values of the fixed pipeline.
- `uncontrolled`: the setting can be neither fixed nor read. Every reference manifest names it in `uncontrolled_settings`, and every exception that relies on the reference names it too (07 §4).
- `not_required`: not a variable of the fixed pipeline (decision 038). The entry names the pinned value, which every capture applies and reads back.
- `pending_probe`: still open.

Evidence is a SHA-256. For documentation it is the hash of the page as retrieved. For the probe it is the hash of a private probe file (`probe:<name>`), which `probe.json` lists with its hash. `presets` records whether the `ref_match` preset and the `base_color` diagnostic apply and verify.

<!-- answers-table:begin -->
| Row (07 §2.1, §3.3) | Status | Evidence |
|---|---|---|
| `colour_lut`: Colour LUT: where Iray applies it in the display chain | `not_required` | probe:probe.json, probe:panel/v2/display-settings |
| `display_view_transform`: Colour-management mode: the selected display/view transform | `confirmed_by_probe` | probe:probe.json, probe:render/A, probe:panel/v2/viewport-display-transform |
| `iray_settings`: Min Sample, Max Sample, Max Time, Caustic Sampler, Firefly Filter, override resolution: persistence and readback | `confirmed_by_probe` | probe:probe.json, probe:panel/v2/iray-settings, probe:render/A |
| `readiness`: Convergence state (Status, Iterations, Rendering time): programmatic readiness | `confirmed_by_probe` | probe:probe.json, probe:panel/v2/iray-settings |
| `viewer_mdl_settings`: Environment exposure and rotation, dome, ground (Viewer and MDL) | `confirmed_by_probe` | probe:probe.json, probe:panel/v2/display-settings |
| `display_settings`: Which display settings shared with the viewport change the Iray image | `not_required` | probe:probe.json, probe:panel/v2/display-settings |
| `default_mdl_parameters`: Default-MDL material parameters per material instance | `not_required` | probe:panel/defaults/shader-settings, probe:panel/height/shader-settings |
| `denoiser`: Denoiser: does it affect the saved render, can it be disabled | `confirmed_by_probe` | probe:render/A, probe:render/I, probe:panel/defaults/iray-settings |
| `random_seed`: Random seed: are repeated renders bit-identical | `uncontrolled` | probe:render/A, probe:render/B |
| `save_render`: Save Render: format, bit depth, display transform baked in | `confirmed_by_probe` | probe:render/A, probe:render/A_exr |
| `stale_frame`: Save Render: stale-frame behaviour | `confirmed_by_probe` | probe:render/A, probe:render/F, probe:render/G, probe:probe.json |
| `height`: Height applied as bump or displacement (§3.3) | `confirmed_by_probe` | probe:render/A, probe:render/J, probe:panel/height/shader-settings |
| `camera_projection`: Camera conventions behind silhouette verification (§2.2 step 5) | `confirmed_by_probe` | probe:render/A, probe:render/H, probe:probe.json |
| `pixel_route`: Pixel route: Save Render or the external 1:1 observation fallback | `confirmed_by_probe` | probe:render/A, probe:render/F, probe:render/G, probe:view/V |
<!-- answers-table:end -->

<!-- answers:begin -->
```json
{
  "schema": "uzpainter/parity/iray-capture-answers/1",
  "task": "phase0.6_render-reference-procedure",
  "procedure_version": "iray-capture/1",
  "sources": {
    "A-PYDOC objects.inv": "Painter 12.1.0 python-doc Sphinx inventory, 625 objects scanned for Iray, sample, time, denoiser, seed, status, post-effect and capture symbols: only camera, environment, colour LUT and tone mapping exist (display module)",
    "A-PYDOC display.html": "python-doc substance_painter.display",
    "A-PYDOC project.html": "python-doc substance_painter.project",
    "A-PYDOC ui.html": "python-doc substance_painter.ui",
    "A-JSDOC alg.display.html": "javascript-doc alg.display: environment and colour LUT only; no other alg namespace names Iray, samples, time, denoiser, seed or render status",
    "A-HELP-IRAYSET": "https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/iray-renderer/iray-settings (retrieved 2026-10-10)",
    "A-HELP-IRAY": "https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/iray-renderer/iray-renderer (retrieved 2026-10-10)",
    "A-HELP-VIEWER": "https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/iray-renderer/viewer-and-mdl-settings (retrieved 2026-10-10)",
    "A-HELP-GUIDE color-profile": "https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/post-processing/color-profile (retrieved 2026-10-10)",
    "A-HELP-GUIDE post-processing": "https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/post-processing/post-processing (retrieved 2026-10-10)",
    "A-HELP-GUIDE color-management": "https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/color-management/color-management (retrieved 2026-10-10)"
  },
  "rows": {
    "colour_lut": {
      "status": "not_required",
      "answer": "Fixed pipeline (decision 038): no colour profile and no LUT. Activate Color Profile is applied off and read back (False).",
      "evidence": [
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        },
        {
          "source": "probe:panel/v2/display-settings",
          "sha256": "8ab62f2b276a1e440e7c6811f38fd2d8f3567be065bde516e6965fb072a49458"
        }
      ],
      "details": {
        "pinned": {
          "Display Settings/Activate Color Profile": false,
          "color_lut_url": null
        }
      }
    },
    "display_view_transform": {
      "status": "confirmed_by_probe",
      "answer": "Colour management 'ocio' (OCIO = Painter's substance config). The viewport's display-transform selector is drawn over the viewport, outside the UI Automation tree and both APIs, so automation cannot set it: a fresh Painter session shows Default - sRGB (panel image), and every capture verifies it through the background, which must read 89,89,89 (read [89, 89, 89]).",
      "evidence": [
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        },
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:panel/v2/viewport-display-transform",
          "sha256": "2c1fbf7025c038d9cba6c12c823d259323f7c639564cc1690831781455c47a73"
        }
      ],
      "details": {
        "pinned": "Default - sRGB",
        "background": [
          89,
          89,
          89
        ]
      }
    },
    "iray_settings": {
      "status": "confirmed_by_probe",
      "answer": "No API reads or sets them; the UI operator applies each pinned value and reads it back from the widget ({'Iray Settings/Min Sample': 256, 'Iray Settings/Max Sample': 256, 'Iray Settings/Max Time': 3600, 'Iray Settings/Caustic Sampler': False, 'Iray Settings/Firefly Filter': False, 'Iray Settings/Override viewport resolution': True, 'Iray Settings/Width': 1200, 'Iray Settings/Height': 1200}); the saved render is 1200x1200. Persistence is not relied on: every capture re-applies and re-reads the sheet. Caustic Sampler and the resolution override beyond the pinned values are not required (decision 038).",
      "evidence": [
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        },
        {
          "source": "probe:panel/v2/iray-settings",
          "sha256": "66c4446019141e0426ab662621b398b6cd89da9e0a59326e56c14ccb1928cf0f"
        },
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        }
      ],
      "details": {
        "pinned": {
          "Iray Settings/Min Sample": 256,
          "Iray Settings/Max Sample": 256,
          "Iray Settings/Max Time": 3600,
          "Iray Settings/Caustic Sampler": false,
          "Iray Settings/Firefly Filter": false,
          "Iray Settings/Override viewport resolution": true,
          "Iray Settings/Width": 1200,
          "Iray Settings/Height": 1200
        }
      }
    },
    "readiness": {
      "status": "confirmed_by_probe",
      "answer": "No API exposes it; the UI operator reads Status, Iterations and Rendering time from Iray's information section ({'status': 'Done', 'iterations': 256, 'rendering_time_s': 1.0, 'max_time_s': 3600.0}), and the recorder gates the capture on Done, Iterations = S and a time below Max Time.",
      "evidence": [
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        },
        {
          "source": "probe:panel/v2/iray-settings",
          "sha256": "66c4446019141e0426ab662621b398b6cd89da9e0a59326e56c14ccb1928cf0f"
        }
      ],
      "details": {
        "convergence": {
          "status": "Done",
          "iterations": 256,
          "rendering_time_s": 1.0,
          "max_time_s": 3600.0
        }
      }
    },
    "viewer_mdl_settings": {
      "status": "confirmed_by_probe",
      "answer": "Not in the APIs; the UI operator applies each pinned environment and dome value and reads it back ({'Display Settings/View mode': 'Material', 'Display Settings/Override environment map color space': True, 'Display Settings/Environment map color space': 'Linear', 'Display Settings/Environment Exposure': 0.0, 'Display Settings/Environment Rotation': 0.0, 'Display Settings/Environment Alignment': 'World', 'Display Settings/Dome': 'Infinite sphere', 'Display Settings/Clear color': True, 'Display Settings/Clear color value': '595959', 'Display Settings/Ground': False, 'Display Settings/Activate Post Effects': False, 'Display Settings/Activate Color Profile': False, 'Display Settings/Activate Subsurface Scattering': False}). The MDL settings sweep is not required (decision 038).",
      "evidence": [
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        },
        {
          "source": "probe:panel/v2/display-settings",
          "sha256": "8ab62f2b276a1e440e7c6811f38fd2d8f3567be065bde516e6965fb072a49458"
        }
      ],
      "details": {
        "pinned": {
          "Display Settings/View mode": "Material",
          "Display Settings/Override environment map color space": true,
          "Display Settings/Environment map color space": "Linear",
          "Display Settings/Environment Exposure": 0.0,
          "Display Settings/Environment Rotation": 0.0,
          "Display Settings/Environment Alignment": "World",
          "Display Settings/Dome": "Infinite sphere",
          "Display Settings/Clear color": true,
          "Display Settings/Clear color value": "595959",
          "Display Settings/Ground": false,
          "Display Settings/Activate Post Effects": false,
          "Display Settings/Activate Color Profile": false,
          "Display Settings/Activate Subsurface Scattering": false
        }
      }
    },
    "display_settings": {
      "status": "not_required",
      "answer": "Fixed pipeline (decision 038): post effects, colour profile and display SSS off, applied and read back; tone mapping does not apply to a colour-managed project (set_tone_mapping raises).",
      "evidence": [
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        },
        {
          "source": "probe:panel/v2/display-settings",
          "sha256": "8ab62f2b276a1e440e7c6811f38fd2d8f3567be065bde516e6965fb072a49458"
        }
      ],
      "details": {
        "pinned": {
          "Display Settings/Activate Post Effects": false,
          "Display Settings/Activate Color Profile": false,
          "Display Settings/Activate Subsurface Scattering": false
        }
      }
    },
    "default_mdl_parameters": {
      "status": "not_required",
      "answer": "Fixed pipeline (decision 038): the material is the default shader instance of a new project, left at Painter's defaults (panel image); its parameters are not a variable.",
      "evidence": [
        {
          "source": "probe:panel/defaults/shader-settings",
          "sha256": "9e934960aaf7b568c4163c6f97245ec7cd6af15e099ca32f11ad3c9b1288a534"
        },
        {
          "source": "probe:panel/height/shader-settings",
          "sha256": "9e934960aaf7b568c4163c6f97245ec7cd6af15e099ca32f11ad3c9b1288a534"
        }
      ],
      "details": {
        "pinned": "Painter's default shader instance"
      }
    },
    "denoiser": {
      "status": "confirmed_by_probe",
      "answer": "no denoiser acts on the saved render (lag-1 correlation 0.047, residual sd 0.0908); the Renderer Settings panel has no denoiser control (panel image).",
      "evidence": [
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:render/I",
          "sha256": "6d125c4e7495ab82cc4ae08ba345fb0e781fa7ae4734f9d1fefe9ec72442f78f"
        },
        {
          "source": "probe:panel/defaults/iray-settings",
          "sha256": "105a81c6aabd904ee2701581f3aee291a03ef24501015fb76eaa7d0bc074a442"
        }
      ],
      "details": {
        "correlation": 0.04682842446848588,
        "residual_sd": 0.09084856082379394
      }
    },
    "random_seed": {
      "status": "uncontrolled",
      "answer": "Iray's seed is neither documented nor settable. Two renders of the same state in one session are not bit-identical ({'max_abs': 0.0025635156786450453, 'mean_abs': 9.703678272000532e-07, 'differing': 5173, 'pixels': 1440000}). Session-separated repeatability is measured by the references (07 §4 step 1a).",
      "evidence": [
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:render/B",
          "sha256": "0ab853313bee38ce370fd1d27f27205819d71f003b63105fb0b52f9b9ee086ad"
        }
      ],
      "details": {
        "bit_identical_same_session": false,
        "repeat": {
          "max_abs": 0.0025635156786450453,
          "mean_abs": 9.703678272000532e-07,
          "differing": 5173,
          "pixels": 1440000
        }
      }
    },
    "save_render": {
      "status": "confirmed_by_probe",
      "answer": "Save Render offers 'BMP (*.bmp), EXR (*.exr), HDR (*.hdr), J2K (*.j2k *.j2c), JNG (*.jng), JP2 (*.jp2), JPEG (*.jpg *.jif *.jpeg *.jpe), PGM (*.pgm), PNG (*.png), PSD (*.psd *.psb), TARGA (*.tga *.targa), TIFF (*.tif *.tiff), WebP (*.webp)'; other dialog options: 'none'. PNG: 16-bit, 4 channels, colour chunk: none; its background in 8-bit codes [89, 89, 89] equals the standard's display value 89,89,89 (linear 0.1 through Default - sRGB): the display transform is baked in. OpenEXR: float, 32-bit, 4 channels.",
      "evidence": [
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:render/A_exr",
          "sha256": "ad4a98e4c953a1876f96fc3239316faf36fd2b3a9d7b96a3d23400df193c38a8"
        }
      ],
      "details": {
        "png": {
          "bits_per_channel": 16,
          "channels": 4,
          "colour_chunk": null,
          "background": [
            89,
            89,
            89
          ],
          "display_referred": true
        },
        "exr": {
          "sample_type": "float",
          "bits_per_channel": 32,
          "channels": 4
        }
      }
    },
    "stale_frame": {
      "status": "confirmed_by_probe",
      "answer": "Save Render right after a camera change (Status 'Done') saved a frame of the new settings, not the previous frame.",
      "evidence": [
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:render/F",
          "sha256": "c99e2dfcbbeab0ef88e1df2860cf9ef9f21a07fc62fdec2b57b816d5abf9cdb1"
        },
        {
          "source": "probe:render/G",
          "sha256": "6dce03b8c17febd1899b181adec112c6ab44f86c0ce3a27af3cd1dae42517ef2"
        },
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        }
      ],
      "details": {
        "outcome": "current_frame",
        "to_previous": {
          "max_abs": 0.8063477531090257,
          "mean_abs": 0.015110200391224127,
          "differing": 209307,
          "pixels": 1440000
        },
        "to_converged": {
          "max_abs": 0.805783169298848,
          "mean_abs": 0.011064973339097929,
          "differing": 197893,
          "pixels": 1440000
        }
      }
    },
    "height": {
      "status": "confirmed_by_probe",
      "answer": "With the shader at Painter's defaults (panel image), Iray applies a painted height as bump (shading changes inside an unchanged outline); outline pixels changed: 0.",
      "evidence": [
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:render/J",
          "sha256": "19b853fcc5f39f97bea8f372e7aaec61eafd8dc04eacd1a422bbf06a86050cc5"
        },
        {
          "source": "probe:panel/height/shader-settings",
          "sha256": "9e934960aaf7b568c4163c6f97245ec7cd6af15e099ca32f11ad3c9b1288a534"
        }
      ],
      "details": {
        "outline_changed": 0,
        "interior_shading_changed": true
      }
    },
    "camera_projection": {
      "status": "confirmed_by_probe",
      "answer": "Unrotated camera: 0 silhouette mismatches. Rotated camera [-15.0, 25.0, 10.0]: Euler orders without mismatch ['ZYX'] (scores {'XYZ': 204444, 'XZY': 115063, 'YXZ': 153040, 'YZX': 133983, 'ZXY': 48636, 'ZYX': 0}).",
      "evidence": [
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:render/H",
          "sha256": "6b5c15fa4e46d53adfb80cfb48627c0433ce04dcd011380072c241fa8a6c451c"
        },
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        }
      ],
      "details": {
        "unrotated_mismatches": 0,
        "order_scores": {
          "XYZ": 204444,
          "XZY": 115063,
          "YXZ": 153040,
          "YZX": 133983,
          "ZXY": 48636,
          "ZYX": 0
        },
        "confirmed_orders": [
          "ZYX"
        ],
        "background_uniform": true
      }
    },
    "pixel_route": {
      "status": "confirmed_by_probe",
      "answer": "Save Render (PNG, display-referred, at the override resolution). The live view of the viewport is [1523, 1174] pixels for a 1200x1200 render: it is scaled, so an external observation is not 1:1 at this size.",
      "evidence": [
        {
          "source": "probe:render/A",
          "sha256": "4d4fa7d149807f92639df1387d9b5e1a43e5fc9a164994740290ed42c28e35f9"
        },
        {
          "source": "probe:render/F",
          "sha256": "c99e2dfcbbeab0ef88e1df2860cf9ef9f21a07fc62fdec2b57b816d5abf9cdb1"
        },
        {
          "source": "probe:render/G",
          "sha256": "6dce03b8c17febd1899b181adec112c6ab44f86c0ce3a27af3cd1dae42517ef2"
        },
        {
          "source": "probe:view/V",
          "sha256": "1e8d0229f4abad9ad74abb3b56e0c09942a7f3a27b644e5d609eea7107ed17b5"
        }
      ],
      "details": {
        "route": "save_render",
        "live_view": [
          1523,
          1174
        ],
        "live_view_one_to_one": false
      }
    }
  },
  "uncontrolled": [
    "random_seed"
  ],
  "probe": {
    "probe_json_sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3",
    "painter_build": {
      "product": "Adobe Substance 3D Painter",
      "version": "12.1.5",
      "build_id": "12.1.5+js-api.1.1.20"
    },
    "session_id": "3051381f14704ed6b9df75f7cb811f91",
    "finished_at": "2026-10-11T09:47:05.456654+00:00"
  },
  "presets": {
    "ref_match": {
      "applied_and_verified": true,
      "background": [
        141,
        142,
        148
      ],
      "readback": {
        "Display Settings/Clear color value": "8D8E94",
        "Display Settings/Environment Rotation": "180",
        "Display Settings/Environment map color space": "Linear",
        "Display Settings/Dome": "Infinite sphere"
      },
      "environment_url": "resource://session/TOS-RefMatch-Skeletal-Mage?version=9448e92f252b3abe147ef955a8b41e3ac86b18d1.image",
      "evidence": [
        {
          "source": "probe:render/R",
          "sha256": "bd5bbf7ec2bce57ee22a14011a56c007b5e0d7885741580b1ebe69eab153ce35"
        },
        {
          "source": "probe:panel/ref_match/display-settings",
          "sha256": "0791890d9192a4e9caa898ba1fbb80dc51795f2154db8f4cdced2274cca7f4d7"
        },
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        }
      ]
    },
    "base_color": {
      "applied_and_verified": true,
      "readback": {
        "Display Settings/Environment Opacity": 0.0,
        "Display Settings/Environment Blur": 0.0,
        "Display Settings/Shadows": false,
        "Display Settings/View mode": "Base color"
      },
      "live_view": [
        1063,
        1174
      ],
      "evidence": [
        {
          "source": "probe:view/BC",
          "sha256": "e66c6447d139b8bc34187575c45c2a5c92dfa2bf7b1ecaeab66d5727c9dd612d"
        },
        {
          "source": "probe:panel/base_color/display-settings",
          "sha256": "fc2b04cca6633249e35df2232b7184863fb1ac5efc2946f433d3ae1423782a15"
        },
        {
          "source": "probe:probe.json",
          "sha256": "78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3"
        }
      ]
    }
  }
}
```
<!-- answers:end -->

Findings behind the answers (probe run `20261011T094244968281Z-3051381f1470`, `probe.json` `78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3`):

- **APIs.** Painter's Python and JavaScript APIs expose camera, environment, colour LUT and tone mapping only (python-doc inventory scan, 625 objects). Everything else in the fixed pipeline is reached through the panels by the UI operator.
- **Colour management.** A project created through `project.create` while `OCIO` names Painter's substance config is OCIO-managed. In that mode `display.set_tone_mapping` raises, so the instruction sequence has no tone-mapping step. The viewport's display-transform selector shows Default - sRGB in a fresh session. It is in neither API nor the UI Automation tree.
- **Save Render.** It offers BMP, EXR, HDR, J2K, JNG, JP2, JPEG, PGM, PNG, PSD, TGA, TIFF and WebP, with no other options.
  - PNG: 16-bit RGBA, no colour chunk, written at exactly 1200x1200. The background reads 89,89,89 in 8-bit codes, so the image is display-referred.
  - EXR: float32 RGBA and display-referred too. Its background is 0.349, and the PNG equals the EXR clamped to [0, 1] and quantised, within one 16-bit code. So no scene-linear image is available.
- **Iray state.**
  - Min = Max Sample = 256 converges in about 1 s at 1200x1200 on the RTX 4090.
  - Min Sample overrides Max Time: with Max Time 1 s at 8000x8000, Iray ran 256 iterations in 90 s and then read Done.
  - Raising the sample count continues the accumulation instead of restarting it.
- **Stale frame.** A save made right after a camera change held a frame of the new settings, not of the previous one. The frame was unfinished: its mean difference from the converged frame was 0.011. That is why the readiness gate and the fence are required.
- **Seed and denoiser.** Two renders of one state in one session are not bit-identical: max 0.0026 of full scale, 5173 of 1,440,000 pixels differ. The 2-sample residual is white noise (lag-1 correlation 0.047), so no denoiser acts. The panel has no denoiser control.
- **Height.** With the shader at Painter's defaults (displacement enabled, scale 0), a painted height changes shading inside an unchanged outline: it is applied as bump. Those defaults were read back under OCIO on 2026-10-11 (displacement enabled, source Height, scale unit Normalized, amount 0, tessellation Uniform with count 1; record `shader-defaults.json` `0cd1b76de6e5cbc97112e01783873ca4bfe08dceadce84855f82e17bf87c0da6`, `iray-references.md` §5).
- **Camera.** The unrotated silhouette matches the projection with 0 mismatches. The rotated camera identifies the Euler order `ZYX`: the Z rotation applies first, then Y, then X, which is `Rx·Ry·Rz` as the Assets3D standard states. The other orders had 48,636 to 204,444 mismatches.
- **Live view.** The viewport was 1523x1174 pixels for a 1200x1200 render. The live view is therefore scaled, and the display-transform overlay is drawn inside it.
- **Presets.**
  - `ref_match`: the session-resource HDRI, clear colour `8D8E94` and rotation 180 were applied and read back. The render's background read 141,142,148.
  - `base_color`: environment opacity 0, blur 0, shadows off and view mode Base color were applied in Edition mode. Painter disables the lighting controls in Iray mode and in the Base color view, so the view mode is set last.

## 2. The procedure `iray-capture/1` (07 §2.2 steps 1–7)

**Painter.** Start Painter with `--enable-remote-scripting` and `OCIO` naming `<Painter>\resources\ocio\substance\config.ocio`, with no project open and under the Assets3D Painter lock. Each reference needs a fresh Painter session; the display transform is not saved and is checked as Painter's fresh-session default.

**Settings sheet.** The sheet is the reference's public manifest (`golden-public.json`, `applied_settings`). The qualification job is `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier3/render-procedure/qualification-sphere.json`.

- **Operator settings** are named `<panel>/<setting>` with `applied_by: operator_settings_sheet`. These are the v2 values that act on Iray:
  - `Iray Settings/` Min Sample = Max Sample = 256, Max Time 3600 s, Caustic Sampler off, Firefly Filter off, Override viewport resolution on, Width = Height = 1200;
  - `Display Settings/` View mode Material, Override environment map color space on, Environment map color space Linear, Environment Exposure 0, Environment Rotation 0, Environment Alignment World, Dome Infinite sphere, Clear color on, Clear color value `595959`, Ground off, Activate Post Effects off, Activate Color Profile off, Activate Subsurface Scattering off.
- **Viewport-only values.** Environment opacity 0, blur 0 and shadows off act only on the realtime viewport, and Painter disables them in Iray mode. They belong to the `base_color` diagnostic, not to an Iray sheet.
- **Recorder settings** (`applied_by: recorder_api`):
  - `capture.procedure` = `iray-capture/1`;
  - `capture.route` = `save_render`;
  - `capture.encoding` = `display_referred`;
  - `capture.bits_per_channel` = 16;
  - `capture.background_srgb8` = `89,89,89`;
  - `capture.display_transform` = `Default - sRGB`;
  - `capture.camera_rotation_order` = `ZYX`, required when the camera rotation is not zero.
- `uncontrolled_settings` lists `random_seed`.
- **Environment.** The instruction sequence names Studio White Soft by its resource URL (`set_environment_resource` with `resource_url`). The installed EXR hashes `c2bb3294099b130bfa0f4bdae677efac544ba97ad3afd579a2563333e748c2c3`, the hash the standard names. The `ref_match` preset imports its HDRI as a session resource (`resource.import_session_resource`), and the recorder verifies the file against the standard's hash `77eeed8de580113581d50258e0ab3dd055aa29fa7d5ab614f2599ce036e0841d`.

**Steps.**

1. **Documented state.** Run `python -m tools.parity.recorder iray <manifest> --condition separate_session --operator ui --operator-id <id>`. The recorder:
   - creates the throwaway project from the authored inputs;
   - applies the camera and the environment;
   - reads back every documented render setting, the colour-management mode and `project.get_scene_bounding_box()`;
   - projects the expected silhouette from the read-back camera;
   - switches to Iray mode.
2. **Operator form.** The UI operator applies each sheet setting and reads the widget back after commit. A value that differs refuses the reference. It keeps an image of each panel and of the display-transform selector as private evidence (`operator_recorded_settings`, `settings_panel_evidence`). `--operator console` lets a person do the same at the console.
3. **Readiness gate.** The operator reads Iray's information section once Status reads Done with every iteration run, on two reads 3 s apart. The capture is refused unless Status is `Done`, Iterations equals S (k·S for the k run) and Rendering time is below Max Time.
4. **Pixels.** Save Render writes a 16-bit PNG into a fresh directory at the path the recorder names (decision 039).
5. **Current-frame verification.** The recorder writes a fence file before Save Render. The capture is accepted only if all of the following hold; otherwise the reference is refused and nothing is staged:
   - the file is the only file of the directory and was written after the fence;
   - it is 1200x1200 and 16-bit;
   - its silhouette matches the fixture projected from the read-back camera (one uniform background value, no object pixel holding it, a 2-pixel band not judged, Painter's scene bounding box equal to the mesh file's);
   - its background reads `capture.background_srgb8` in 8-bit codes. This canary catches a wrong display transform, a wrong clear colour or a wrong frame.
6. **Repeats.** Each reference is recorded in two separate Painter sessions and once at k·S with **k = 4** (`--condition k_times_samples --k 4`). The reference key must be identical across all three, or assembly is refused. Raising the samples continues Iray's accumulation, so the k·S reference is recorded in its own session like the others.
7. **Storage.** The recorder writes the run to the private oracle inbox, and `python -m tools.parity.store record <manifest> --run <run>` admits it (`parity/STORE.md`). The repository receives only the public manifest with SHA-256 hashes, and `python -m tools.parity.guard` must pass.

**How the UI operator works** (`painter_ui.py`, decision 029):

- **Reading.** It runs out of process. It reads Painter's widgets through Microsoft UI Automation, where each automation id is the Qt object-name path.
- **Acting.** It uses real input. To set a field it double-clicks it, replaces the text and presses Enter. It clicks toggles, group boxes and combo-box items, and types the clear colour's hex value in the colour picker. UI Automation's Toggle and SetValue patterns change Painter 12.1.5's widgets without applying the setting, and SetFocus does not reliably reach its fields, so neither is used.
- **Save Render.** The native Save Render dialog is driven through UI Automation patterns (file type, name, Save).
- **Images.** Panel images and the live view are taken with `PrintWindow`.
- **Map from sheet names to widgets.** Iray Settings → the Renderer Settings dock (`irayParametersView`); Viewer and MDL Settings → Display Settings (`displaySettings`). The table `CONTROLS` names each widget.
- **Safety.** A prompt or widget it does not know stops the run. Painter is brought to the foreground before every mouse or keyboard action.

## 3. Probe session

Run `python -m tools.parity.recorder iray-probe --operator ui --ref-match-hdri <TOS-RefMatch-Skeletal-Mage.exr>` (`tools/parity/recorder/iray_probe.py`). It runs the fixed pipeline on the authored sphere (`parity/fixtures/render-procedure/sphere.obj`) at 1200x1200 and 256 samples. Every render is checked against its own fence:

| Render | What it answers |
|---|---|
| defaults, v2 sheet | Panel images of Painter's defaults; every v2 value applied and read back (`iray_settings`, `viewer_mdl_settings`, `display_settings`, `colour_lut`, `default_mdl_parameters`) |
| A (PNG and EXR), live view V | Format, bit depth, display-referred output, live-view size (`save_render`, `display_view_transform`, `pixel_route`) |
| A, B | Same state saved twice in one session (`random_seed`) |
| F, G | Field of view 41: F saved at once, G once Done (`stale_frame`) |
| H | Rotated camera: Euler order of `display.Camera.rotation` (`camera_projection`) |
| I | 2 samples: residual correlation against A (`denoiser`) |
| J | Stripe height map in a fill layer, shader at its defaults (`height`) |
| R | `ref_match`: session HDRI, clear colour 141,142,148, rotation 180 |
| BC | `base_color`: Edition mode, Base color view, live view |

The decision rules are in `tools/parity/render_procedure/analysis.py`. Evidence goes to `UZP_ORACLE_WORK\iray-probe\<run>\`, outside the repository, with `probe.json` listing every file by SHA-256 and the UI operator's action log. Probe outputs are not goldens and are not admitted to the store. Only their hashes and numbers enter this report, through `answers --merge`.

## 4. Qualification run (task item 3.1)

The run was `python -m tools.parity.recorder iray parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier3/render-procedure/qualification-sphere.json --condition separate_session --operator ui`, in a fresh Painter session on 2026-10-11. It passed: the reference was staged with `current_frame_verified`.

- Staged record `iray-staging/tier3__render-procedure__qualification-sphere/s-2e84a21a97c3/staged.json` (`3d9ef1c6fc0b59014e2d9c0d6668f055e8cde16e4a7382b8fabcf894e71d271f`).
- Render: Save Render 16-bit RGBA PNG, 1200x1200, display-referred, SHA-256 `63f1394ada0966781e3252c1b935b4de26d7f5789d9e0db144c58d5adab74121`.
- Convergence: Done, 256 of 256 iterations in 1 s against Max Time 3600 s.
- Evidence: panel images of Iray Settings, Display Settings and the viewport display-transform selector.
- Key: colour management `ocio`; environment `resource://starter_assets/Studio White Soft?version=022c26ec30cd5575037b74f697993c1d73f52865.image`; `uncontrolled_settings` `random_seed`.

The run only stages. The golden needs the other two references of step 6 (task `phase0.7_render-reference-captures`).

Live readiness refusals, same session, private files under `UZP_ORACLE_WORK\iray-readiness-refusal\20261011T095439Z\`:

- `refusal-rendering.json` (`28ee48a971f80af4280fa1c5a151d4f4285109cd7c5ec4bcd7062c44c44cc3ff`): the gate read Status `Rendering` with Iterations 1 of 300 right after a camera change, and refused the capture.
- `refusal.json` (`b83f876a35dba9d0f6c1c2aca5e16bd35dd246929ad08dbc2e61f5c0746f4a8a`): with Max Time 1 s, Iray ran 256 iterations in 90 s. The gate refused because the rendering time was not below Max Time.

The fake-Painter tests cover the remaining refusals:

- `tests/parity/recorder/test_iray.py`: stale file, shifted frame, render from another camera, moved fixture, unconfirmed Euler order, wrong background, wrong bit depth;
- `tests/parity/recorder/test_iray_probe.py`;
- `tests/parity/recorder/test_painter_ui.py`.

## 5. Decisions and assumptions

- **JavaScript API.** It is consulted only through its admitted documentation (A-JSDOC; coordinator ruling of 2026-10-10 on the shipped `python-doc` and `javascript-doc` HTML), and it adds nothing for Iray. The Assets3D render adapter and Painter's in-process Qt objects are not used (decision 039).
- **Pixel route** (decision 039; model panel AGREE x2, PARTLY x1). The route is Save Render. The external live view is not 1:1 at the owner's window size and carries the selector overlay.
- **Display transform** (decision 039; model panel AGREE x1, PARTLY x1, DISAGREE x1). It cannot be set or read through any interface. Its identity is verified by three pieces of evidence, not read: a fresh session, the selector image of every capture, and the background canary. The canary checks one neutral level, linear 0.1.
- **Camera conventions.** Y-up; the camera looks along local −Z; the field of view spans the square image; the Euler order is `ZYX`. Only Perspective cameras and square renders are qualified.
- **Fixtures.** The probe uses UzmiGames-authored fixtures (Apache-2.0, `tools/parity/render_procedure/fixtures.py`) and the two environments the standard names. Studio White Soft is a Painter starter asset that is only referenced by URL on the owner's machine and never copied. The ref_match HDRI is Assets3D's own file.
- **Residual risks** (not probed, outside the fixed pipeline's use):
  - Stale-frame behaviour was measured for a camera change only. The procedure makes every change before the readiness gate.
  - The canary would not catch a different display transform that maps linear 0.1 to 89.
- **Where the answers live.** The answers sit in this Markdown file because the repository guard rejects JSON data under `parity/` without a schema rule (`parity/GUARD.md` §2).
