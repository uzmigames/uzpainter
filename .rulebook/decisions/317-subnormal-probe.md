# 317. Painter's handling of subnormal float32 values is measured as a black box by one Tier 0 request, `blend-subnormal-f32`, before the CPU reference or the GPU paths change; designed, recording pending

**Status**: accepted (the request); recording pending
**Date**: 2026-10-20
**Related Tasks**: phase3.1_vulkan-compute-parity, phase1.14_compositor-core

## Context

Decision 313's Vulkan sweep found that the GPU flushes subnormal float32 operands, on DX12 and Vulkan alike, where the CPU reference keeps them. On 172 of 240 blend combinations with subnormal float32 operands, the GPU differs from the CPU. For example, a Normal blend at opacity 1 gives 0x00000001 on the CPU and 0x00000000 on the GPU. The RTX 4090 reports `shaderDenormPreserveFloat32 = false`. The finding was reported to the owner and not waived. There are two candidate fixes:

- **(a)** the CPU reference flushes subnormals (FTZ, flush to zero, on results; DAZ, denormals are zero, on operands);
- **(b)** the CPU reference stays as it is, and GPU evaluation is refused wherever subnormal operands occur.

Acceptance is equality with Painter (decision 001), so the choice depends on what Painter itself does with subnormal float32 values. No golden contains a subnormal value. Painter is a GPU application: it renders with Vulkan (`src/evaluator/hwmath.h`), and the recording GPU's reciprocal, square root and arcsine, which the evaluator reproduces from measured tables, treat subnormal inputs as zero. That makes flushing a likely outcome, but it is not evidence about Painter's blend path, its bitmap read or its export.

Two facts limit how far decision 313's numbers reach:

- Its subnormal operands are all non-negative. In `SubnormalImage` (`tests/evaluator/evaluator_test.cpp`), the sign `(k >> 7) & 0x80000000u` of a 32-bit `k` is always 0. Fixed afterwards to `(k << 7) & 0x80000000u` (bit 24 of `k`), so both signs occur; the re-run sweep still reports 172 of 240 and names the modes: Color, ColorBurn, ColorDodge, Darken, Difference, Exclusion, HardLight, InverseSubtract, Lighten, LinearDodge, LinearLight, Multiply, Normal, NormalMapCombine, NormalMapDetail, NormalMapInverseDetail, Overlay, PinLight, Replace, Saturation, Screen, SoftLight, Subtract, Tint, Value, VividLight.
- Its 240 combinations are L32F and RGB32F, each with and without coverage, over 30 modes at opacities 1 and 0.7. Decision 313 does not say which modes the 172 are.

The coordinator's brief asked for one small Tier 0 semantics request: at most 256 px, under 1 minute of Painter time, reusing the tier0 semantics machinery and its EXR fixture writer.

## Decision

### 1. The request: `tier0/semantics/blend-subnormal-f32`

- One Legacy golden at 256 px on the 4x2 plane grid (`grid4x2`: eight texture sets, each a full 0..1 UV square, so every texel is covered).
- Built by `recording_requests.blend_subnormal`. Its two bitmaps come from `request_fixtures.subnormal_bits` and are written by `exr_float_rgb`, the writer the UV ramps and kernel codes use:
  - `parity/fixtures/tier0-semantics/bitmaps/subnormal-acc.exr`, the lower layer;
  - `parity/fixtures/tier0-semantics/bitmaps/subnormal-src.exr`, the upper layer.
  - Both are scanline OpenEXR with B, G, R as FLOAT and ZIP compression. Every bit pattern survives the file, including subnormals and −0. The OpenEXR library decodes them bit for bit, and the test's own decoder checks the same.
- The request file is `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/tier0/semantics/blend-subnormal-f32.json`, with `private_records` empty.
- It records like every Legacy probe, in a session with no `OCIO` (`parity/RECORDER.md` §11.4): `python -m tools.parity.recorder record "$req/tier0/semantics/blend-subnormal-f32.json"`.

### 2. The bitmaps: one role per component

| Component | Lower layer (acc) | Upper layer (src) | What it measures |
|---|---|---|---|
| R | per 16 x 16 texel block (bx, by): V[by] | V[bx] | every ordered pair of the 16 values V, one pair per block, uniform inside the block |
| G | per texel: decision 313's class x mod 3 | class y mod 3 | decision 313's operand distribution: class 0 a subnormal, class 1 a normal in [FLT_MIN, 2 FLT_MIN), class 2 a value k/2^24 in [0, 1). Non-negative, as in decision 313. Every pair of classes occurs. |
| B | block i = 16 by + bx: i/256 | (256 − i)/256 | normal values that locate the block and check that the path is exact on normal float32 values |

The 16 values V are:

- +0 and −0;
- the subnormals 2^-149 (0x00000001), 3·2^-149, 2^-127 and the largest subnormal (0x007FFFFF), and −2^-149 and minus the largest subnormal;
- FLT_MIN (0x00800000, the smallest normal value), FLT_MIN + 1 ulp, 1.5·FLT_MIN and −FLT_MIN;
- 0.25, 0.5, 1 and −0.25.

Three kinds of R pair separate the hypotheses:

- **Read.** A subnormal operand, through the controls (§3).
- **DAZ.** The exact result is normal but depends on a subnormal operand. Example: LinearDodge of acc FLT_MIN and src 2^-149 gives exactly 0x00800001; if the operand is read as zero, it gives 0x00800000.
- **FTZ.** Every operand is normal but the exact result is subnormal. Examples: Multiply of FLT_MIN and 0.5; Subtract or Difference of FLT_MIN + 1 ulp and FLT_MIN (2^-149); Normal at 0.7 of FLT_MIN over +0.

The negative entries also show the sign of a flushed zero.

### 3. The stack, the slots and the controls

- Every set adds User0-User7 as RGB32F.
- Per set, a lower fill holds the lower bitmap in Normal at opacity 1. An upper fill above it holds the upper bitmap. Both use `Nearest` filtering at scale 1, so sampling adds no arithmetic: a bilinear weight of 1 against 0 would itself pass the value through a multiply.
- The 64 (set, channel) slots run in order s0 User0..User7, s1 User0, and so on (`subnormal_slots`):

| Slots | Role |
|---|---|
| s0 User0, s7 User6 | **upper-only control**: the upper fill alone, Normal at opacity 1 on the empty stack (the lower fill is not active on that channel) |
| s0 User1, s7 User7 | **lower-only control**: the lower fill alone (the upper fill is not active on that channel) |
| s0 User2 .. s7 User5 | the 30 blend modes, every mode of `corpus.BLEND_FAMILIES` except Disable, in that order, each at opacity 1 then 0.7: the upper fill's mode and opacity over the lower fill |

- **No-stack control.** The upper bitmap is also bound as the Normal mesh map of every set. Its `meshMap/normal_base` export goes from import to export with no layer stack in between.
- Altogether these measure every mode and both opacities of decision 313's RGB32F combinations without coverage.

### 4. The export

- One export step: User0-User7 and `meshMap/normal_base`, as OpenEXR 32f with `passthrough` padding and no dithering. That is 72 files of 256 px.
- The step is not repeated within the session: the recorder's r1 and r2 already record the request twice.
- The expected Painter time is well under 1 minute. This is an estimate, not a measurement: the request has 433 API steps and 144 files of 256 px over r1 and r2. Decision 272's six 512 px probes took 30 s of recording in total.

### 5. Reading the record (CPU only, after the recording)

- Per slot and per component, compare Painter's bits with the CPU reference (`CpuTileStore`) under four flush models:
  - **IEEE**: the reference as it is, with gradual underflow;
  - **DAZ**: subnormal float32 operands read as zero of their sign;
  - **FTZ**: subnormal float32 results flushed to zero of their sign;
  - **FTZ+DAZ**.
- The controls are read directly against the bitmaps.
- The record is **void**, and must be reported, in any of these cases:
  - a template capture shows a user channel that is not RGB32F;
  - a step is refused;
  - an R block or a B block is not uniform inside its 16 x 16 texels;
  - a texel whose operands and IEEE result are all normal differs from the IEEE reference (those are decision 313's established parity, so a difference there means the path or the reading is wrong, not the flush).
- The no-stack control alone is void, and the rest stands, if `normal_base` is not exact on the B values, for example because Painter stores mesh maps at 16 bits.

### 6. What each outcome implies

| Outcome | Controls (upper-only, lower-only, normal_base) | DAZ pairs | FTZ pairs | CPU reference | GPU paths (DX12, Vulkan) |
|---|---|---|---|---|---|
| **P: preserved** | keep subnormals | operand seen (0x00800001) | subnormal result kept | unchanged: IEEE | They differ wherever a float32 operand or result is subnormal. A refusal keyed on the input bitmaps is not enough, because the FTZ pairs show that normal operands produce subnormals. So the fix is fix (b) plus a preserving GPU mode where one exists: DXC `-denorm preserve` on DX12 (SM 6.2+, to be qualified); none on this Vulkan device (`shaderDenormPreserveFloat32 = false`). Otherwise float32 GPU evaluation is refused (NotYetSupported naming `phase3.1_vulkan-compute-parity`). |
| **R: flushed on read** | the stack controls and normal_base flush subnormal inputs | operand read as zero | subnormal result kept | flush float32 subnormals where a bitmap texel is read (the sign as observed), and keep gradual underflow in the blend arithmetic | Equal on subnormal inputs (DAZ). They still differ on produced subnormals (FTZ), so the remedy is the same as in P. |
| **A: flushed by arithmetic only** | normal_base keeps subnormals; the stack controls flush them or keep them (the bottom layer's Normal at 1 over the base is itself arithmetic) | read as zero, or seen | flushed, or kept | fix (a), limited to the observed flags: FTZ+DAZ, or FTZ only, or DAZ only, on every float32 blend operation, with the sign of the zero as observed; copies stay untouched | Under FTZ+DAZ, unchanged: decision 313 measured DX12 = Vulkan, and the record is compared with the GPU kernels bit for bit before this is claimed. Under one flag only, they differ on the other flag, so the remedy is as in P. |
| **O: flushed at output** | every subnormal output is zero, normal_base included | operand seen | flushed | flush subnormal results where the channel is stored or exported, never in the arithmetic | The final store must flush the same way. Whether the GPU's per-operation FTZ matches that is checked against the record; where it does not, the remedy is as in P. |
| **M: mixed** | per mode or per opacity (for example, Normal at 1 kept as a copy while 0.7 flushes) | per mode | per mode | the flags of each mode, as measured | Equal per mode only where the GPU's flags match; other modes are refused on the GPU by name. |

- The sign of a flushed zero is part of every outcome. NVIDIA's FTZ keeps the sign (−2^-149 becomes −0). If Painter gives +0, the GPU differs on the negative entries even under outcome A.
- **Scope.**
  - The request measures RGB32F without coverage. Decision 313's L32F and coverage combinations are not recorded. An L channel would need a grey reading of the colour EXR, whose own arithmetic would confound the read (decision 048), and coverage needs masks.
  - The outcome carries over to them on the assumption that Painter's flush is a property of its float32 arithmetic, not of the channel count or the coverage.
  - After the fix, decision 313's sweep is re-run with the evaluator's new flags. It must then equal the CPU on all 240 combinations, or the remaining differences must be refused by name.

## Alternatives Considered

- **Choosing fix (a) or (b) now**, on the expectation that a Vulkan application flushes: rejected. Acceptance is Painter's output, and the read, the arithmetic and the export can each flush or keep subnormals independently.
- **One texture set per mode on a larger grid:** rejected. Per-channel modes on the upper fill give 64 slots on eight sets in one request.
- **Default (bilinear) filtering:** rejected. Its weights add a multiply on every sample, which would mix up the read and the arithmetic.
- **A mask for opacity 0.7:** rejected. Mask precision (`tier0/mask/precision`) would add quantisation. The layer's opacity is an exact control.

## Consequences

- New: `tools/parity/tier0_semantics/request_fixtures.py` (the `SUBNORMAL_*` constants, `subnormal_bits`, `subnormal_bitmap`); `recording_requests.py` (`subnormal_generator`, `SUBNORMAL_MODES`, `SUBNORMAL_MAPS`, `subnormal_slots`, `blend_subnormal`, last in `later_goldens`); the two bitmaps and the request file; two tests in `tests/parity/test_recording_requests.py`; and a paragraph in `parity/RECORDER.md` §11.4.
- No product code changes. Until the recording is read, decision 313's divergence stays open and unwaived, and its sweep keeps printing the `KNOWN` line.
- Decision 313's subnormal operands are non-negative only. This is a fact about that sweep's coverage; this decision does not change that test.
- No model panel was run. The request is a measurement; it chooses no fix.
