# 167. Painter batch B admits 11 goldens: the renamed ramps fix the void padding probes, and bitmaps on non-sRGB8 channels refuse sRGB

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.15_compositor-colour-fits

## Context

Decision 166 re-authored the ten padding probes that decision 160 voided, as `-v2` on ramp files named `uv-ramp-n<N>.exr`. It also replaced the refused `srgb-bitmap-variants` with `srgb-bitmap-variants-v2`, in which s4 attempts `set_color_space(sRGB)` on each user channel. All eleven were recorded on 2026-10-12, 21:27-21:29, in one Painter `12.1.5+js-api.1.1.20` session:

- Legacy colour management (no `OCIO`, no `PAINTER_ACE_CONFIG`) and the documented API only;
- under the Assets3D Painter lock, on throwaway projects only.

Painter was open for under two minutes and closed normally, and the lock was released. No recording crashed or was refused.

## Decision

All eleven goldens recorded `r1` (same session) and `r2` (after save and reopen). They were admitted with `python -m tools.parity.store record --run` and joined `recording_requests.ADMITTED`, and their requests were deleted. `store verify` of the envelope's `tier0/` and `python -m tools.parity.tier0_semantics check` pass. Every same-session export repeat is identical.

| Golden | golden-record SHA-256 (prefix) | r1 = r2 | Status |
|---|---|---|---|
| `srgb-bitmap-variants-v2` | `6b39d103255a3d8b` | 426 of 432 exports; s5 BaseColor differs | valid |
| `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}-v2` (nine) | `e7f9f11e`, `aa75838d`, `948a948e`, `b474be90`, `23f80b3d`, `54fa9ddf`, `c0fd32d6`, `ad883480`, `47083cc0` (r1-p0 ... r15-p75) | infinite padding yes, passthrough no | valid |
| `export-padding-tie-2048-v2` | `8c7931f1c563ceb1` | infinite padding yes, passthrough no | valid |

The regenerated `parity/reports/phase0/tier0-stability.md` (no fits run) classifies all eleven as unstable, which makes them "not admitted (§4)" as exact goldens. The padding probes are unstable through their passthrough exports, and `srgb-bitmap-variants-v2` through s5. That leaves 164 goldens: 112 stable and 52 unstable.

**The cause of decision 160's void probes is confirmed.** It was the file name. With `uv-ramp-n1024.exr` and `uv-ramp-n2048.exr`:

- the resource is named `uv-ramp-n1024` and `uv-ramp-n2048` in the readback;
- the projection capture returns UV, BilinearHQ, Repeat, scale 1;
- User0 is RGB32F in the template capture of both recordings;
- no User0 export is uniform.

The infinite-padding export equals the authored ramp bit for bit on the covered texels:

| Probe | Texels equal to the ramp | Share of the map |
|---|---|---|
| r1 | 131072 | 12.5% |
| r2 | 81920 | 7.8% |
| r15 | 212992 | 20.3% |
| tie-2048 | 196608 | 4.7% |

The `r1` passthrough export equals the ramp on every texel. The `r2` passthrough export equals the infinite one, as with `export-padding-tie-512` (decision 160). None of the ten probes is void under decision 129.

For r1 the p0 and p25 infinite exports are byte-identical, while p75 differs. For r2 and r15 all three phases differ.

**The answer for decision 145's user channels.** Painter refused `SourceBitmap.set_color_space(sRGB)` with `ValueError: Invalid colorspace 'standard sRGB'`, in both recordings, on:

- User1 (RGB8), User2 (L8), User3 (RGB16), User4 (L16), User5 (RGB16F) and User7 (RGB32F), which are steps 34-44;
- the s5 mask fill effect's source, which is step 51.

Those bitmaps keep the `Data` space, and Painter offers only `Raw`, `Data` and `DataSigned` for them. On the sRGB8 channels (BaseColor, Emissive), the offered spaces are `Raw`, `Working`, `sRGB`, Legacy `Linear` and Legacy `sRGB`. s0-s3 hold `sRGB`, and s6-s8 hold `Working`, Legacy `Linear` and Legacy `sRGB` as requested.

So an sRGB bitmap colour space is available only on sRGB8 channels. Elsewhere the bitmap is read as `Data`.

**s5 is unstable across save and reopen.** Its BaseColor exports (a uniform under a black mask whose fill effect's source is grey A) differ between `r1` and `r2` at PNG 16, PNG 8 and OpenEXR 32f. Each recording's same-session repeats are identical. Every other export of the golden is identical in `r1` and `r2`.

## Alternatives Considered

- **Stop after the first padding probe if the ramp was still missing.** That check was built into the run. `export-padding-ramp-r1-p0-v2` was checked before the others were recorded, and its User0 export was not uniform.

## Consequences

### Positive
- phase1.25 item 2.7 has its nine P-ramp goldens and P-tie at 2048.
- phase1.15 item 2.2 has the recording decision 145 §3 asked for. The refusals on the user channels are its answer for those channels.

### Negative
- s5's masked BaseColor is unstable across save and reopen, so it is not an exact golden there. The fit owner reads it per recording.

## Follow-ups
- Fit owners: phase1.25 item 2.7 (P-ramp, P-tie) and phase1.15 item 2.2 (sRGB variants).
