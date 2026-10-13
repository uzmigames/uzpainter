# 160. Painter batch A admits 14 goldens; the 1024 and 2048 padding probes are void and srgb-bitmap-variants is refused

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.15_compositor-colour-fits

## Context

Decisions 156 and 157 queued 15 Legacy requests (`parity/RECORDER.md` §11.4): `srgb-bitmap-variants` (decision 145), the three inferred template bases (decision 126, phase1.25 item 2.6) and the P-tie and P-ramp padding probes (decision 129, item 2.7). They were recorded on 2026-10-12, 20:55-21:07, in one Painter `12.1.5+js-api.1.1.20` session: Legacy colour management (no `OCIO`, no `PAINTER_ACE_CONFIG`), documented API only, under the Assets3D Painter lock, throwaway projects only. Painter was open for 11 minutes and closed normally, and the lock was released. No recording crashed.

## Decision

Fourteen goldens recorded `r1` (same session) and `r2` (after save and reopen). They were admitted with `python -m tools.parity.store record --run`, joined `recording_requests.ADMITTED`, and their requests were deleted. `store verify` of the envelope's `tier0/` and `python -m tools.parity.tier0_semantics check` pass. Every same-session export repeat is identical.

| Golden | golden-record SHA-256 (prefix) | r1 = r2 | Status |
|---|---|---|---|
| `export-template-base-unreal-engine` | `3cd058dbd32342c4` | yes | valid. BaseColor only; PNG 16 code 48107, as decision 126 recorded |
| `export-template-base-openpbr-anisotropy` | `ef8fc950fdcf90e3` | yes | valid. BaseColor only; PNG 16 code 59397 |
| `export-template-base-pbr-specular-glossiness` | `094ff0ecbe625a9d` | yes | valid. Specular only; PNG 16 code 14330 |
| `export-padding-tie-512` | `02e43d6a71fd17ca` | infinite padding yes, passthrough no | valid. User0 RGB32F; the ramp is present |
| `export-padding-tie-2048` | `17a6935df3aa88f9` | yes | **void** (decision 129) |
| `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}` (nine) | `9cbb706a`, `439e002c`, `45e07a7d`, `b80e319f`, `e62242d7`, `9433f290`, `591f9156`, `20b7eeb3`, `ea9e8b72` (r1-p0 ... r15-p75) | yes | **void** (decision 129) |

In each template base, Painter skipped the map the template lacks, as decision 157 allowed. Their EXR values are 0.49804, 0.8 and 0.039216.

**Void probes.** In tie-2048 and in all nine P-ramp goldens, every User0 export is uniform (1.0, 1.0, 1.0) in both recordings, at infinite padding and at passthrough. The template capture shows User0 as RGB32F, but the passthrough User0 differs from the ramp on every covered texel. Decision 129 rules that such a record is void. The admitted records stay in the store as they are, because store records are write-once. They are not fit targets, and item 2.7 still has no P-ramp data, nor a P-tie at 2048.

Every void golden shares two symptoms. The fill's projection capture (`projection/s9`) raised `AttributeError: 'NoneType' object has no attribute 'uv_transformation'`, where tie-512 returned a UV projection. And Painter named the imported ramp resource `uv-ramp` for `uv-ramp-1024.exr` and `uv-ramp-2048.exr`, but `uv-ramp-512` for `uv-ramp-512.exr`.

The likely cause, not yet verified, is the file names. Painter seems to read a four-digit suffix from 1001 up as a UDIM tile number, so the bitmap never reaches the 0-1 tile. A re-recording needs new request names, because the store refuses a second golden record under the same id. Rename the ramp fixtures to a suffix Painter cannot take for a tile number, for example `uv-ramp-n1024.exr`.

**Refused: `srgb-bitmap-variants`.** Painter refused state step 33 (`FillLayerNode.set_source` on User1, an RGB8 channel, bitmap `field-a`, `color_space: sRGB`) with `ValueError: Invalid colorspace 'standard sRGB'`. A refused state step refuses the whole golden, so nothing was written. One diagnostic re-run, which added only a print of the failing step, located the step. Steps 15-29 had already applied the same `sRGB` bitmap colour space on sRGB8 channels (BaseColor, Emissive) without error. The request stays under `requests/`. Its fix follows §11.3: a new request name, with the User channel variants moved to a colour space those channels accept, or to the attempted `set_color_space` step of decision 156, whose refusal is recorded as an observation.

## Alternatives Considered

- **Leave the void probes' requests unadmitted.** Rejected. The store already holds their records, and a request under the same name could never be admitted. Admitting them and recording here that they are void keeps the corpus honest.
- **Retry the refused golden.** Rejected. The refusal is deterministic, because it comes from a state step.

## Consequences

### Positive
- phase1.25 item 2.6 has its three inferred template bases recorded, and item 2.7 has P-tie at 512.

### Negative
- Item 2.7 still waits for P-ramp (nine goldens) and P-tie 2048 under new names. Decision 145 still waits for `srgb-bitmap-variants`.

## Follow-ups
- Re-author the void probes under new names with renamed ramp fixtures. Check the resource name in the readback before admission.
- Re-author `srgb-bitmap-variants` under a new name.
- Regenerate `parity/reports/phase0/tier0-stability.md` with the next fit run.
