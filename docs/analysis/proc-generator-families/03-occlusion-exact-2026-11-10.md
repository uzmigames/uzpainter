# Ambient Occlusion: the single invert is a 16-bit invert, 2026-11-10 (phase3.2_proc-generator-families items 2.5 to 2.7, 3.1)

Follows `02-calibration-2026-11-09.md` §2. Numbers only below: every map is a private oracle in the owner's store.

## 1. The recording GPU's 16-bit UNORM fetch

`python -m tools.parity.vk_sampler_probe.unorm16 measure tmp/scratch` (`tools/parity/vk_sampler_probe/unorm16.py`, through `vkprobe.cpp`). This is how the reciprocal, root and texture-unit tables were measured: synthetic textures only, through Vulkan (the API Painter 12 renders with), on the recording GPU (RTX 4090, driver 617.14, the driver of the 2026-11-09 and 2026-11-10 recordings).

- An R16G16B16A16_UNORM texture holds every code k once per channel: R k, G 65535 - k, B k ^ 0x5555, A 40503 k mod 65536.
- It is fetched three ways: `Load`, nearest `SampleLevel` and linear `SampleLevel` at the texel centre.
- All 12 fetch-channel pairs agree on all 65 536 codes.
- Every value is float32(k / 65535) correctly rounded. For comparison, truncation would agree on 32 897 codes and k x float32(1 / 65535) on 65 024.

The table is stored as `src/evaluator/tables/hw-unorm16.zlib`: hwmath.h's delta form, with every delta 0. `unorm16.fetch` reads it back.

**The fetch is not the source of the residual.** The 2026-11-09 premise, a fetch that differs from correct rounding on about one code in six, is refuted by this measurement.

## 2. Painter's single invert, refitted on the calibration set

The calibration set holds the 18 single-invert cases. Over them Painter's output y is a function of the AO code k: 65 534 codes, 94 767 244 compared texels, never two outputs for one code.

Two observations locate the residual:

1. Reading x = 1 - y back (exact for k >= 32768), x misses float32(k / 65535) by one ulp exactly when the true quotient lies more than about 0.2 ulp from x's float. The misses come in runs of the low byte, with a threshold that alternates with the parity of x's last mantissa bit and narrows as the leading ones of k grow. That is the signature of a value rounded on a finer grid and then rounded again, ties to even: y is the float32 subtraction 1 - z of a z that lies below 0.5.
2. The result is z = F(65535 - k), the fetch of the inverted 16-bit code.

The model is therefore: c = k when `ao_invert` equals `global_invert`, else 65535 - k, and the output is I(I(F(c))) in every set, with I(v) = float32(1 - v) and F the measured fetch. It equals Painter on all 65 534 codes, and on every compared texel of all 36 calibration cases (24 were exact before; the 12 single-invert cases are now exact too). The candidate (`tools/parity/proc_generators/occlusion_candidate.py`) was committed in `ef7dafc7` before any new held-out golden was recorded. It refuses an AO texel that is not float32(k / 65535) of a 16-bit code.

## 3. The new held-out set

The knob cube's held-out set was spent on 2026-11-09. A new set was requested in `9981df21`: the Tunic v10 low mesh (`18-Tunica/Export/18-Tunica-v10.fbx`, SHA-256 `ad7ef061…`, garment, the recipe set's own mesh, outside the calibration set) at 1024 and 4096, with the same four sets, 8 cases.

- Recorded under the Assets3D Painter lock (seq 2368 to 2369), Legacy, Painter 12.2.0, r1 and r2 after save and reopen.
- Admitted, verified, and their inbox runs deleted.
- Pinned in `e59f9433`. The calibration list is byte for byte the 2026-11-09 one.
- The mesh is kept in the private store as an input, as the hat is.

Certification (`python -m tools.parity.proc_cert certify parity/manifests/phase3/proc-cert/generator__occlusion@2/batch.json --fitter tools.parity.proc_generators.occlusion_candidate:fit`):

- Outcome **exact**: calibration 36 of 36 and held-out 8 of 8, on every compared texel (decision 423 §1).
- Candidate `3f9ca11f…`, held-out pin `2d91b5b1…` spent on it in the ledger.
- Report `parity/reports/phase3/proc-cert/generator__occlusion@2/2d91b5b1c67e5698.json`.

## 4. What it does not cover

- AO inputs off the 16-bit code grid: Painter's AO bake is 16-bit, so none was recorded. The candidate and the native family refuse them.
- The AO generator's other parameters stay at Painter's defaults. They are not editable in the certified domain.
- The compared-texel rule is decision 423 §1, accepted in the root review of 2026-11-10.
- Every other generator stays a release gap (02 §3).

## 5. The spent set as regression cases (root review, 2026-11-10)

The model panel found one flaw in decision 424: the spent knob cube set had left the batch. Decision 222 §2 moves it to the calibration set as regression cases instead.

- `python -m tools.parity.proc_generators.batch occlusion` now appends its 4 cases to `calibration/cases.json` (`goldens.spent_held_out`), outside the unchanged 36-cell matrix. The held-out list keeps its pin `2d91b5b1…`.
- The candidate is unchanged (fingerprint `3f9ca11f…`, no fitted constants). Re-certified with the same command: outcome **exact**, calibration 40 of 40, held-out 8 of 8. The ledger is unchanged, and the report is rewritten in place.
- The native CPU lane equals Painter on all 48 cases (`tests/procedural/test_proc_generator_families.py::test_occlusion_v2_equals_painter_on_its_batch`, 2 passed with the record test).
