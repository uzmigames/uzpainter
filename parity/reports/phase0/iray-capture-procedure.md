# Iray capture procedure `iray-capture/1`

Task `phase0.6_render-reference-procedure` (child of `phase0.9_render-reference-capture`, P0-FEAS-RENDER in `docs/dag.md`). It qualifies the capture procedure of `docs/architecture/07-preview-and-render-parity.md` §2.2 and answers every "not confirmed" row of §2.1 and the bump-or-displacement question of §3.3. Decisions 002 (clean room), 018 (Iray is the render-parity target) and 022 apply. This report holds statuses, answers and SHA-256 hashes only. No Painter pixels are in it; probe renders and panel images stay on the owner's machine.

**Status (2026-10-10).** The procedure, the probe and the analyses are implemented and tested against the fake Painter. Answers that public documentation settles are recorded. The probe session and the qualification run need the owner at Painter's panels (rulebook question on this task), so the rows marked `pending_probe` stay open until then. `iray-capture/1` is not qualified until every row is settled and the qualification run has passed (§4).

## 1. Answers

The table below is generated from the JSON block that follows it. `python -m tools.parity.render_procedure answers` checks the block, and `--merge <probe directory>` folds a finished probe in. Statuses:

- `documented`: settled by public documentation (A-PYDOC, A-JSDOC, A-HELP-*).
- `confirmed_by_probe`: settled by the black-box probe (A-OBSERVE).
- `uncontrolled`: the setting can be neither fixed nor read. Every reference manifest names it in `uncontrolled_settings`, and every exception that relies on the reference names it too (07 §4).
- `pending_probe`: still open.

Evidence is a SHA-256: of the documentation page as retrieved, or of the private probe file.

<!-- answers-table:begin -->
| Row (07 §2.1, §3.3) | Status | Evidence |
|---|---|---|
| `colour_lut`: Colour LUT: where Iray applies it in the display chain | `pending_probe` | A-HELP-GUIDE color-profile, A-PYDOC display.html |
| `display_view_transform`: Colour-management mode: the selected display/view transform | `documented` | A-HELP-GUIDE color-management, A-PYDOC display.html, A-PYDOC objects.inv |
| `iray_settings`: Min Sample, Max Sample, Max Time, Caustic Sampler, Firefly Filter, override resolution: persistence and readback | `pending_probe` | A-PYDOC objects.inv, A-JSDOC alg.display.html, A-HELP-IRAYSET |
| `readiness`: Convergence state (Status, Iterations, Rendering time): programmatic readiness | `documented` | A-PYDOC objects.inv, A-JSDOC alg.display.html, A-HELP-IRAYSET |
| `viewer_mdl_settings`: Environment exposure and rotation, dome, ground (Viewer and MDL) | `pending_probe` | A-HELP-VIEWER, A-PYDOC objects.inv |
| `display_settings`: Which display settings shared with the viewport change the Iray image | `pending_probe` | A-HELP-IRAY, A-HELP-GUIDE post-processing |
| `default_mdl_parameters`: Default-MDL material parameters per material instance | `pending_probe` | A-HELP-VIEWER |
| `denoiser`: Denoiser: does it affect the saved render, can it be disabled | `pending_probe` | A-HELP-IRAYSET |
| `random_seed`: Random seed: are repeated renders bit-identical | `pending_probe` | A-PYDOC objects.inv |
| `save_render`: Save Render: format, bit depth, display transform baked in | `pending_probe` | A-HELP-IRAYSET |
| `stale_frame`: Save Render: stale-frame behaviour | `pending_probe` | A-HELP-IRAYSET |
| `height`: Height applied as bump or displacement (§3.3) | `pending_probe` | A-HELP-VIEWER |
| `camera_projection`: Camera conventions behind silhouette verification (§2.2 step 5) | `pending_probe` | A-PYDOC display.html |
| `pixel_route`: Pixel route: Save Render or the external 1:1 observation fallback | `pending_probe` | A-HELP-IRAYSET |
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
      "status": "pending_probe",
      "answer": "Documentation: the colour profile is a 3D LUT stored as a 2D float texture, applied after tone mapping, and the help page names only the viewport's Material mode, not Iray. The probe sets an all-magenta LUT through the documented API (render D) to see whether Iray's view and its saved render contain it.",
      "evidence": [
        {
          "source": "A-HELP-GUIDE color-profile",
          "sha256": "73b682cb18cd9a98721d1bb4222d61a3c7aae89782c558996185384103eb55f7"
        },
        {
          "source": "A-PYDOC display.html",
          "sha256": "488d5c6a3c66826ea5f52a401d663213dd1272fd7ccc73be9570c4771eeea42c"
        }
      ]
    },
    "display_view_transform": {
      "status": "documented",
      "answer": "Legacy projects (the analytic fixture profile) have no view transform: the display transform is the documented tone mapping, recorded by API. In colour-managed projects the display transform is chosen in a viewport drop-down that is not saved with the project (it depends on the monitor) and has no Python or JavaScript API: the recorder can neither fix nor read it, so the operator sets and reads it, and a colour-managed sheet must name it as an operator setting with a panel image.",
      "evidence": [
        {
          "source": "A-HELP-GUIDE color-management",
          "sha256": "e6761c1de5f9f94ef787d4cf742d5bc18a8bbb643d94eca70c22823b97d584ca"
        },
        {
          "source": "A-PYDOC display.html",
          "sha256": "488d5c6a3c66826ea5f52a401d663213dd1272fd7ccc73be9570c4771eeea42c"
        },
        {
          "source": "A-PYDOC objects.inv",
          "sha256": "e7d6388ff97f20ff09b0c31a8dabbb536eb418eab7146e9845278a1ff1426522"
        }
      ]
    },
    "iray_settings": {
      "status": "pending_probe",
      "answer": "No Python or JavaScript API symbol reads or sets them (documentation scan): they are operator-applied and operator-read in the Iray Settings panel. Whether they are saved with the project or carried into a new project is answered by the probe's persistence form.",
      "evidence": [
        {
          "source": "A-PYDOC objects.inv",
          "sha256": "e7d6388ff97f20ff09b0c31a8dabbb536eb418eab7146e9845278a1ff1426522"
        },
        {
          "source": "A-JSDOC alg.display.html",
          "sha256": "70006bbf0a7601e69af8c88e836aa6af74c48a814846ac6c9c659c707aa66299"
        },
        {
          "source": "A-HELP-IRAYSET",
          "sha256": "41023bb8bd49a131d042f729ddb4ce67594dfecb4072daf673039de4c08a7c0b"
        }
      ]
    },
    "readiness": {
      "status": "documented",
      "answer": "There is no programmatic readiness check: neither API exposes Status, Iterations or Rendering time (documentation scan). Readiness is read by the operator in the Iray information section and gated by the recorder: it refuses the capture unless Status is Done, Iterations equals the sample count and Rendering time is below Max Time, and the panel image is kept as private evidence.",
      "evidence": [
        {
          "source": "A-PYDOC objects.inv",
          "sha256": "e7d6388ff97f20ff09b0c31a8dabbb536eb418eab7146e9845278a1ff1426522"
        },
        {
          "source": "A-JSDOC alg.display.html",
          "sha256": "70006bbf0a7601e69af8c88e836aa6af74c48a814846ac6c9c659c707aa66299"
        },
        {
          "source": "A-HELP-IRAYSET",
          "sha256": "41023bb8bd49a131d042f729ddb4ce67594dfecb4072daf673039de4c08a7c0b"
        }
      ]
    },
    "viewer_mdl_settings": {
      "status": "pending_probe",
      "answer": "Not in either API (documentation scan): operator-applied and operator-read. Persistence is answered by the probe's persistence form.",
      "evidence": [
        {
          "source": "A-HELP-VIEWER",
          "sha256": "a73231c61002c96b50fbbe483608b63c4f5ec16067b100e1284883979d9c420a"
        },
        {
          "source": "A-PYDOC objects.inv",
          "sha256": "e7d6388ff97f20ff09b0c31a8dabbb536eb418eab7146e9845278a1ff1426522"
        }
      ]
    },
    "display_settings": {
      "status": "pending_probe",
      "answer": "The help page says Iray shares the viewport's camera, post effects, tone mapping, colour LUT and colour management. The probe measures which of tone mapping (render C), the colour LUT (D) and a post effect (E, Vignette) change the saved image.",
      "evidence": [
        {
          "source": "A-HELP-IRAY",
          "sha256": "ec502a0ac21b089b3dd6b00d192f0ea9b900f8d57b68f52011cbc5af5f7f4ac2"
        },
        {
          "source": "A-HELP-GUIDE post-processing",
          "sha256": "c0a5e5919902a37aacbfd0404d9b1d1b9d67048543dc848e6143a24ed6d2741b"
        }
      ]
    },
    "default_mdl_parameters": {
      "status": "pending_probe",
      "answer": "Names documented (Emissive Intensity, Refraction, IOR, Scattering, Absorption, Absorption Color), per material instance, not in either API. The probe records their defaults on a new project and whether they persist.",
      "evidence": [
        {
          "source": "A-HELP-VIEWER",
          "sha256": "a73231c61002c96b50fbbe483608b63c4f5ec16067b100e1284883979d9c420a"
        }
      ]
    },
    "denoiser": {
      "status": "pending_probe",
      "answer": "No denoiser control is documented. The probe tests the 2-sample render I against the 64-sample render A: pixel-independent residual means no denoiser.",
      "evidence": [
        {
          "source": "A-HELP-IRAYSET",
          "sha256": "41023bb8bd49a131d042f729ddb4ce67594dfecb4072daf673039de4c08a7c0b"
        }
      ]
    },
    "random_seed": {
      "status": "pending_probe",
      "answer": "The seed is neither documented nor exposed by either API, so it is uncontrolled. The probe measures whether two renders of the same state in one session are bit-identical; session-separated repeatability is measured by the references (07 §4).",
      "evidence": [
        {
          "source": "A-PYDOC objects.inv",
          "sha256": "e7d6388ff97f20ff09b0c31a8dabbb536eb418eab7146e9845278a1ff1426522"
        }
      ]
    },
    "save_render": {
      "status": "pending_probe",
      "answer": "The help page says only that Save Render exports the current render, even unfinished. The probe records the file types offered, measures the saved PNG (and OpenEXR when offered) and compares Linear and ACES renders to see whether the display transform is baked in.",
      "evidence": [
        {
          "source": "A-HELP-IRAYSET",
          "sha256": "41023bb8bd49a131d042f729ddb4ce67594dfecb4072daf673039de4c08a7c0b"
        }
      ]
    },
    "stale_frame": {
      "status": "pending_probe",
      "answer": "The probe saves right after a settings change (F) and after convergence (G) and compares both with the previous frame (A).",
      "evidence": [
        {
          "source": "A-HELP-IRAYSET",
          "sha256": "41023bb8bd49a131d042f729ddb4ce67594dfecb4072daf673039de4c08a7c0b"
        }
      ]
    },
    "height": {
      "status": "pending_probe",
      "answer": "Not documented. The probe renders the sphere with a stripe height map (J): a moved outline means displacement, shading changes inside an unchanged outline mean bump.",
      "evidence": [
        {
          "source": "A-HELP-VIEWER",
          "sha256": "a73231c61002c96b50fbbe483608b63c4f5ec16067b100e1284883979d9c420a"
        }
      ]
    },
    "camera_projection": {
      "status": "pending_probe",
      "answer": "python-doc documents position, Euler rotation in degrees and field of view in scene space, but not the axis conventions or the Euler order. The probe checks the unrotated projection (A) and finds the Euler order from a rotated camera (H).",
      "evidence": [
        {
          "source": "A-PYDOC display.html",
          "sha256": "488d5c6a3c66826ea5f52a401d663213dd1272fd7ccc73be9570c4771eeea42c"
        }
      ]
    },
    "pixel_route": {
      "status": "pending_probe",
      "answer": "Save Render is the route unless the probe finds it unusable (stale frame, unknown encoding, wrong resolution or silhouette); then the external 1:1 observation fallback is needed.",
      "evidence": [
        {
          "source": "A-HELP-IRAYSET",
          "sha256": "41023bb8bd49a131d042f729ddb4ce67594dfecb4072daf673039de4c08a7c0b"
        }
      ]
    }
  },
  "uncontrolled": []
}
```
<!-- answers:end -->

Two documentation findings settle rows on their own:

- **Python and JavaScript API scan.** The python-doc inventory has 625 objects, and its only render symbols are camera, environment, colour LUT and tone mapping. The javascript-doc `alg.*` namespaces add environment and colour LUT only. Neither API exposes Iray samples, time limits, caustics, fireflies, resolution override, convergence status, denoiser, seed, viewer/dome/ground settings, MDL parameters, post effects or Save Render. All of those are therefore operator-applied and operator-read, or `uncontrolled`. `alg.ui.clickButton` needs internal widget names, which are not documented, so it is not used.
- **Colour management.** The help page states that the display transform of a colour-managed project is chosen per monitor and is not saved with the project. The analytic fixtures use Legacy colour management, where the display transform is the documented tone mapping.

## 2. The procedure `iray-capture/1` (07 §2.2 steps 1–7)

**Settings sheet.** The sheet is the reference's public manifest (`golden-public.json`, `applied_settings`):

- Operator settings are named `<panel>/<setting>` with `applied_by: operator_settings_sheet`. Required: `Iray Settings/Min Sample` = `Max Sample` = S, `Max Time` (unit `s`, `min` or `h`), `Width` and `Height` (square).
- Recorder settings with `applied_by: recorder_api`:
  - `capture.procedure` = `iray-capture/1`;
  - `capture.route` = `save_render`;
  - `capture.encoding`, required when the saved file states no encoding;
  - `capture.camera_rotation_order`, required when the camera rotation is not zero; its value is the Euler order the probe confirmed.
- `uncontrolled_settings` lists every row this report marks `uncontrolled`.

The recorder refuses a sheet that lacks the procedure version or names another route. Example: `parity/manifests/tier3/render-procedure/qualification-sphere.json`.

1. **Documented state.** The recorder (`python -m tools.parity.recorder iray <manifest> --condition separate_session`) creates the throwaway project from the authored inputs and applies the documented settings: camera, environment, tone mapping. It reads back every documented render setting plus `project.get_scene_bounding_box()`, projects the expected silhouette from the read-back camera, and switches to Iray mode (`ui.UIMode.Visualisation`). The readback is part of the reference key.
2. **Operator form.** For each sheet setting, the operator applies it in the panel and types the value the panel shows. Any value that differs from the sheet refuses the reference. The operator also gives one screenshot of each panel. Entries and images are private outputs (`operator_recorded_settings`, `settings_panel_evidence`).
3. **Readiness gate.** Min Sample = Max Sample = S, and Max Time well above the time S samples take. Because neither API exposes readiness, the operator reads the Iray information section. The capture is refused unless Status reads `Done`, Iterations equals S (k·S for the k run) and Rendering time is below Max Time.
4. **Pixels.** The route is Save Render at the override resolution, saved to the path the recorder names. The format and encoding are those the probe confirms (`save_render`, `pixel_route`). If the probe finds Save Render unusable, the route becomes external 1:1 observation of the displayed frame, overlays excluded, recorded as display-referred 8-bit. That route needs its own implementation and procedure version before use, and the recorder refuses it today.
5. **Current-frame verification.** The recorder writes a fence file after the readiness report, then asks for Save Render. A capture is accepted only if all of the following hold; otherwise the reference is refused and nothing is staged:
   - the file is the only file of a fresh directory;
   - it was written after the fence (same filesystem clock);
   - it has the override resolution;
   - its silhouette matches the fixture projected from the read-back camera.

   The projection lives in `tools/parity/render_procedure/projection.py`. The image background must be one value, no object pixel may hold that value, and a 2-pixel band around the outline is not judged. Painter's scene bounding box must equal the mesh file's, otherwise the fixture was moved or rescaled.
6. **Repeats.** Each reference is recorded in two separate Painter sessions (`separate_session`, a restart in between) and once at k·S with **k = 4** (`--condition k_times_samples --k 4`). The reference key must be identical across all three, or assembly is refused. With k = 4, the k·S image has half the Monte-Carlo standard deviation of the S image, so the S-versus-4S difference estimates Iray's error at S within a factor √(5/4) (07 §4 step 1b).
7. **Storage.** The recorder writes the run to the private oracle inbox, and `python -m tools.parity.store record <manifest> --run <run>` admits it into the store (`parity/STORE.md`). The repository receives only the public manifest with SHA-256 hashes, and `python -m tools.parity.guard` must pass.

## 3. Probe session (answers the `pending_probe` rows)

`python -m tools.parity.recorder iray-probe` runs one operator-assisted Painter session (`tools/parity/recorder/iray_probe.py`). It stages the sphere and the sky-patch environment from `parity/fixtures/render-procedure/`, plus two probe-only inputs it generates: an all-magenta colour-profile LUT and a stripe height map.

The probe sheet: S = 64 samples, 256×256 override resolution, Max Time 10 min, Caustic Sampler and Firefly Filter off, Infinite Sphere dome, exposure 0, rotation 0, Linear tone mapping. The probe saves twelve renders with Save Render, each checked against its own fence:

| Render | What it answers |
|---|---|
| A, B | Same state, saved twice in one session: repeatability (`random_seed`) |
| A, C (PNG, and EXR when offered) | Linear vs ACES tone mapping: format, bit depth, display transform baked in (`save_render`) |
| D | All-magenta colour-profile LUT (`colour_lut`) |
| E | Vignette post effect (`display_settings`) |
| F, G | Rotation 90: F saved at once, G once Done (`stale_frame`) |
| H | Rotated camera: Euler order of `display.Camera.rotation` (`camera_projection`) |
| I | 2 samples: residual correlation against A (`denoiser`) |
| J | Stripe height map (`height`) |

It also records:

- the default-MDL parameters (`default_mdl_parameters`);
- a persistence form: distinct values are applied, the project is saved, closed and reopened, then a new project is created, and the panels are read each time (`iray_settings`, `viewer_mdl_settings`).

The decision rules are in `tools/parity/render_procedure/analysis.py`. Evidence goes to `UZP_ORACLE_WORK\iray-probe\<run>\`, outside the repository, with `probe.json` listing every file by SHA-256. Probe outputs are not goldens and are not admitted to the store. They stay on the owner's machine, and only their hashes enter this report through `answers --merge`.

## 4. Qualification run

The qualification run follows the probe in the same Painter session (no project open):

```
python -m tools.parity.recorder iray parity/manifests/tier3/render-procedure/qualification-sphere.json --condition separate_session
```

It runs steps 1–5 end to end on the analytic sphere at 1200×1200 with S = 256. It passes when the reference is staged with `current_frame_verified`. The run only stages; it does not admit, and the golden needs the two further references of step 6 (task `phase0.7_render-reference-captures`).

The readiness refusal (Status not Done, Iterations below S, time at Max Time) and the current-frame refusals are covered by the fake-Painter tests:

- `tests/parity/recorder/test_iray.py`: stale file, shifted frame, render from another camera, moved fixture, unconfirmed Euler order;
- `tests/parity/recorder/test_iray_probe.py`.

## 5. Decisions and assumptions

- **JavaScript API.** It is consulted only through its admitted documentation (A-JSDOC; coordinator ruling of 2026-10-10 on the shipped `python-doc` and `javascript-doc` HTML). It adds nothing for Iray. The Assets3D render adapter and Painter's undocumented UI objects are not used.
- **Camera conventions.** Y-up, the camera looks along local −Z, and the field of view spans the square image; these are hypotheses until the probe confirms them. Rotations other than zero need the confirmed Euler order in the sheet. Only Perspective cameras and square renders are qualified.
- **Probe fixtures.** The probe uses authored fixtures only (Apache-2.0, generated by `tools/parity/render_procedure/fixtures.py`). No Adobe environment, LUT or material is used.
- **Where the answers live.** The answers sit in this Markdown file because the repository guard rejects JSON data under `parity/` without a schema rule (`parity/GUARD.md` §2).
