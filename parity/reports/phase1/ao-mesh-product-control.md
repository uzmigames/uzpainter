# AO mesh-storage and product control

Date: 2026-10-23. Status: authored and CPU-validated; capture pending.
Owner: `phase3.2_unreal-ue56-packed-preset` item 2.10, decision 131.

The scalar precomposed-source capture preserves both exported operands but still
leaves two residual texels under the float32-product/fixed12 diagnostic. This
control separates the mesh input path from a precomputed product without using
any recorded values to author its inputs. The production refusal remains.

## Construction

`tools/parity/tier0_semantics/ao_operand_control.py` defines the full 256-by-256
code-pair grid. Let `a = f32(x/255)` and
`c = f32(f32(f32(y/255)-1) * 0.5 + 1)`, with the multiply/add fused. The dyadic
expression is evaluated exactly in float64 before its final float32 rounding.
Let `p = f32(a*c)`, with one correctly rounded multiplication.

| Set | AO mesh input | AO L32F layer |
| --- | --- | --- |
| s0 | Existing grey-a PNG16, code x*257 | Scalar precomposed Y/FLOAT c, opacity 1 |
| s1 | Authored Y/FLOAT a | Same source and settings as s0 |
| s2 | Authored Y/FLOAT p | No layer, empty base expected to be 1 |
| s3 | Same mesh as s2 | Explicit Raw white fill, opacity 1 |

The product enters through the mesh to avoid a layer blend's subtraction and
addition at values below 0.5. All sets use the same full-UV geometry and resolution;
s0/s1 use Nearest, identity UV and RepeatNone. AO_Mixed, channel and mesh export
twice as PNG8 and twice as EXR32F, passthrough, with dithering disabled. The recorder
repeats the complete exports after Full save/close/reopen.

## Frozen comparisons

Check each immediate repeat and reopened recording separately before comparing
AO_Mixed. The s0/s1 EXR channel and mesh operands must be bit-identical. Their
comparison distinguishes format/import/sampling paths; equality of exported
operands does not establish equality of hidden intermediates or isolate only
normalization.

For s2/s3, channel exports must be exactly 1, and mesh exports must equal both
authored p and `f32(mesh_s1_EXR * channel_s1_EXR)` bit for bit. An EXR mesh import
that quantizes the product fails this precondition; its virtual result then
cannot identify multiplication or output quantization. Do not repair the input
or reinterpret a failed precondition after observing the recording.

Conditional on those checks, a float32 product of exported operands followed by
one common quantizer predicts identical AO_Mixed in all four sets. The existing
diagnostic quantizer, `j=floor(p*4096); code=(j*255+2047)>>12`, yields the same
65,536-byte row-major uint8 prediction for each set. Its hash is frozen below;
268 authored products lie exactly on fixed12 boundaries. Agreement with this
control alone does not establish a general operator or resolve earlier L16
save/reopen differences. Score every texel and retain all failed comparisons.

| Artifact | SHA-256 |
| --- | --- |
| Authored mesh a, Y/FLOAT EXR | `f4ce3fe428bd313dce7169eb84d8b565428aa6dd100232213ab1949a05c2e200` |
| Authored mesh p, Y/FLOAT EXR | `c15bc094abab6ed5d9c8b29b3688877245801b532611d06f596d9df1f64772a1` |
| Conditional diagnostic prediction, uint8 row-major | `816dd547a054cb453d601556db7f36ca7e8fa257931582963026542c1022134c` |

Validation: all 58 authored-control, scalar-control and recording-request tests
pass (`scripts/tmp/commits/ao-mesh-control.xml`). Independent struct-based scalar
arithmetic checks every input pair; tests also verify mesh assignments, empty
versus explicit-white layers, repeats, save/reopen declaration, fixture hashes
and generated request. Ruff, mypy and the generated-catalog check pass. No new
Painter capture, admission, implementation acceptance or task completion is claimed.

The next capture shares a 60-minute live-recording budget with the endpoint-plane
and R-322 controls, after the full suite releases the GPU; initial CPU analysis
has a separate 30-minute budget. The private ledger records elapsed times. Stop
on timeout, changed identity, failed preconditions or completed repeats/reopen.
The exact operand/product checks and prediction above remain frozen; a failed
control is reported before another experiment is selected.

CPU verifier: `python -m tools.parity.fit.ao_operand_control`. The raw private
record must match the current envelope, unique identities and the frozen protocol
hash `2961757c5df30fd45fdf084bb33bd8837800b8633b9e70376ee60bbe26c5969d`.
The published mesh/product EXR hashes are checked independently. Both recordings
must expose four 256px AO L32F sets and all 96 exports. The report retains every
operand/product precondition, repeat/reopen comparison and prediction residual,
using hashes and counts only. Twenty-eight CPU checks, Ruff and mypy pass;
missing oracle data remains unavailable rather than a pass.

## Bounded capture outcome (2026-10-23 local / 2026-10-24 UTC)

The four-control batch completed in 118.067 seconds. Initial CPU analysis of all
three control families took 4.885 seconds, once, without retry or fitting. Both
budgets were respected. This AO capture was admitted under the current Painter
12.2.0 envelope; its private record SHA-256 is
`18413b900363f8304cb2e38e8f0585820521614328c043e2f7ab9055a027cd5b`.

All 32 operand/product preconditions and all 96 repeat/reopen stability checks
pass. All 16 frozen PNG predictions fail with two differing samples each;
16 of 24 cross-set comparisons also fail with two differing samples each.
The verifier exits 1. Exact exported operands therefore do not validate the
frozen common-quantizer prediction. No inputs, predictions or production
refusals changed after observation; AO_Mixed remains unavailable.

The private batch-analysis summary SHA-256 is
`265a22d60713317f709b52ff593c8612dcb9bb07674c6964de8a13b12920856f`.
Only counts and identities are published; pixel values remain private.
