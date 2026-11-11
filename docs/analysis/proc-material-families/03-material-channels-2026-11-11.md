# Material channels: codec, destination capture and channel rules, 2026-11-11 (phase3.3_procedural-families item 2.16)

Painter `12.2.0+js-api.1.1.20`, Legacy colour management, under the Assets3D Painter lock (seq 2384 to 2385). This note follows `02-material-channel-survey-2026-11-11.md` §4. Counts only: every capture and export is private (`%LOCALAPPDATA%/UzPainter/snapshot-recordings/`, the survey under the recorder's private work root), and no Painter pixel or parameter value is published.

**Outcome: steps 1, 2 and 4 are implemented; step 3, the same-session golden, is not recorded. The support check still refuses a material fill's channels other than Height, now naming the missing golden. Item 2.16 is not ticked.**

## 1. What is implemented

- **Codec (step 1).** A colour parameter is the seam's tagged colour `{type, working_space, components, alpha}` (`procedural/seam.h` `ParamJson`), as Painter reads it back in the source's context. Metadata holding a colour is schema `/5`, which also records the space the material source reads each colour in. Scalar entries keep `/1` to `/4` and their bytes. Commit `5fc9f43a`.
- **Destination capture (step 2).** The multi-output request with `"usage": "MATERIAL"` captures on the destination's own mesh and texture set resolution. Each stored signature must equal the destination's own request (`SnapshotSetRequest`) in its view.
- **Channel rules (step 4).** The provider composes each active channel of a material fill, on the CPU and DX12 lanes (`docs/procedural-snapshots.md` "Material sources"):
  - BaseMetalness and SpecularRoughness: ((k >> 4) 255 + 2047) >> 12 of k = round(65535 x);
  - BaseColor: round(255 v) of the binary16 view;
  - Normal: (tz16 r, tz16(1 - g), tz16 b), composed as Normal over the empty stack;
  - Height: unchanged (decision 416).
  - The support check's layout gate admits only the fill alone over the empty stack, at opacity 1 in Painter's default modes, with no mask or effect. It is checked on every edit of the stack.
- **Authored evidence.** `tests/procedural/test_material_channel_rules.py` exports an authored capture through both lanes. The lanes are byte-equal, and every channel equals its rule.

## 2. The captures (first session, 16:12 to 16:15)

`tests/python/capture_material_channels_session.py`, then with one destination project:

| Capture | Snapshots | `assets snapshot` |
|---|---|---|
| felt, defaults | 26 (13 outputs x 2 views) | ok, verified after reopen |
| felt, first preset | 26 | ok, verified after reopen |
| leather grain, defaults | 20 (10 outputs x 2 views) | ok, verified after reopen |
| leather grain, first preset | 20 | `host_error` `std::bad_alloc` after its 20 transactions and its save |

- The 92 snapshots of that project load, and each is served (`uzp-procedural-tests snapshot-served`, 92 rows, no failure).
- Saving and reopening a copy of the project with `UzPainter.exe` succeeds.
- The step that raised is not identified. The command now reports the step of a host error (`stage`), and the session script captures each material into its own project.
- The goldens were not recorded, because the session stopped at that capture.

## 3. Painter stopped starting cleanly

Four later launches failed:

- Painter exited before its remote endpoint answered.
- Painter dropped the connection during the first capture's bridge.
- Painter dropped the connection while the session waited for its shelf crawl.
- Painter exited during a 90 s idle wait before any call.

Painter's log ends at its startup crawl or at the Substance 3D Assets web panel. Two runs end with `"Uncaught exception : bad allocation"` from Painter itself. A 60 s idle launch with no call stayed up once. Painter 12.2.0 is unchanged (no update), and the machine had 80 GB of free memory and 22 GB of free VRAM. This is outside UzPainter. The lock was released (seq 2385) so that nothing is held while blocked.

## 4. Diagnostic: the captures against the survey's instance

The survey (15:13) and the first session (16:12) are two Painter sessions. Under decision 431 §2 this comparison gates nothing. It is reported only.

| Material | Comparison | Differs |
|---|---|---|
| felt | split views of `basecolor`, `metallic`, `roughness`, `height` | 0 texels each |
| leather grain | split views of `basecolor`, `metallic`, `roughness`, `normal` | 0 texels each |
| felt | rules on the capture vs the survey's material fill exports: BaseColor codes, BaseMetalness, Height, SpecularRoughness | 0 each |
| leather grain | the same for BaseColor codes, BaseMetalness, Normal, SpecularRoughness | 0 each |

- So these two materials gave the same outputs in two Painter sessions. This is unlike the seeded grunges of decision 431, which differed by a few texels.
- The rules, as implemented, reproduce the survey's material fills from a capture made in another session.

## 5. The L8 views are not all exact 16-bit values

- Felt's roughness L32F views are exactly float32(k / 65535) on every texel.
- Leather grain's are not:
  - defaults: 4 238 of 16 384 texels are 1 to 252 float32 ulps from k / 65535, at most 0.0029 of a code;
  - first preset: 5 341 texels are 1 ulp from it.
- The survey's rule rounds x to its 16-bit code first, so it holds on both. The provider therefore takes k = round(65535 x) and admits views within 1/64 of a code, the measured domain with margin.
- A first implementation that required exact k / 65535 refused leather grain. It was corrected before any golden.
- On exact views the rule equals the tile store's L8 write `WriteUnorm(x, 8)` for all 65 536 codes.

## 6. Remaining (item 2.16)

1. Record the four requests `material-channels-felt`, `-leather-grain`, `-felt-preset` and `-leather-grain-preset` (committed under the envelope's `requests/tier0/api-probes/`) in the session that captures their destination projects. Admit them, and delete their inbox runs.
2. Pin the projects and receipts in `tests/procedural/test_material_channels_served.py`. Lift the support check's same-session refusal for the recorded configuration, and run that test: every map byte-equal to r1 and r2 on both lanes, and single-field changes refused.
3. Identify leather grain's colour side effect with `material_channel_survey.colour_values` (run by the same script) before admitting any colour edit.

Physical size, burlap's mask use and leather pattern's split use stay refused (survey §3, items 2.15 and 2.7).
