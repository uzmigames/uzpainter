# Direct supporting-plane padding diagnostic

Date: 2026-10-23. Status: diagnostic only; no production policy accepted.
Task: phase1.25_pilot-wand, item 2.7. Decision: 358.

## Hypothesis and domain

The current reference develops the far chart through individual physical hinges.
The alternative rotates that chart rigidly around the intersection of a source
supporting plane and the query triangle tau's supporting plane. The correct
source candidate is J, the far-side triangle adjacent to the crossed seam,
rather than K, the triangle owning the far tap. Off-plane chart points retain
their offsets under the same rigid rotation (decision 342).

The generic J/tau diagnostic requires distinct charts, a unique shortest face
path, exactly one chart crossing from the far chart to tau's chart, and tau
different from the seam's own-side triangle. The conservative diagnostic adds
at least two internal tau-chart hinges whose actual 3D edge vectors are exactly
parallel (zero cross product, no fitted tolerance). Degenerate parallel or
antiparallel plane normals retain the existing frame. Rotation uses the existing
fold threshold; all triangle pairs in the 27 cached probes have zero gate
disagreements between normalized-double and recorded-float32 cosine evaluation.
That finite check is not a universal proof of arithmetic equivalence.

## Results

Counts are differing ring coordinates against recorded Painter values, with
fixed/new sets measured against the current decision-358 reference. All 27
kernel probes have a common baseline of 2,941.

| Candidate | Remaining | Fixed | New | Disposition |
| --- | ---: | ---: | ---: | --- |
| Broad K/tau, at least two internal tau hinges | 2,686 | 257 | 2 | Rejected |
| Conservative J/tau, parallel internal hinges | 2,713 | 228 | 0 | Unaccepted |
| Generic J/tau | 1,438 | 1,504 | 1 | Rejected |

Broad K/tau regresses cube from 336 to 338. Conservative J/tau changes only
hinge-far (395 to 301) and hinge-single (677 to 543). Generic J/tau changes cube
(336 to 331; five fixed), hinge-far (395 to seven; 389 fixed, one new),
hinge-single (677 to 22; 655 fixed), and hinge-vary (961 to 506; 455 fixed).
Every other probe remains unchanged under each respective policy.

| Probe/control | Baseline | Conservative J/tau | Generic J/tau |
| --- | ---: | ---: | ---: |
| Tau-prism ring, 2,640 texels | 227 | 134 | 39 |
| Tau-prism mixed controls, 96 texels | 96 | 3 | 3 |
| Tau-prism single-far controls, 80 texels | 0 | 0 | 0 |
| Wand Normal EXR | 85 | 85 | 83 |
| Wand Normal PNG | 49 | 49 | 47 |

Tau-prism scores repeat across all four globally identical infinite exports.
Neither J/tau candidate adds tau-prism or Wand differences. Conservative Wand
residual sets are identical to baseline; generic fixes two in each format.
Forward scoring recomputes tap ordering; the inverse diagnostic's recovered
ordering is not injected into these scores.

The conservative restriction was formulated after the broad candidate's cube
regression. These 27 probes are reused regression evidence, not pristine unseen
validation. In particular, the at-least-two-hinges cutoff lacks independent
causal justification. Zero new residuals does not authorize its promotion.

## Remaining discrimination

Generic J/tau's single new hinge-far residual is on an authored slender triangle.
Support and ordering match baseline; existing quantization and FMA reproduce
the observed value under inferred weights. Only the first quantization bin
differs by one. Raw/box-normalized geometry, float32 point and distance
arithmetic, double geometry normals, split/fused float32 Rodrigues and plane
intersection arithmetic, optional normal renormalization, and measured GPU
trigonometry did not resolve it. No coordinate-specific fallback or exception
was introduced.

On tau-prism discovery data alone, box-normalized float32 points increase
inferred-bin agreement from 93 to 95 of 96 mixed controls. This variant has
neither corpus validation nor production acceptance. Earlier inverse bounds
explain only 19 of 96 mixed controls with arbitrary physical hinge masks and
own-triangle metrics; allowing alternate query anchors raises that bound to
46, still insufficient. These are diagnostic bounds, not executable policies.

Sixteen authored mathematical controls pass: plane mapping, rotation direction,
translation, distance preservation, inverse rotation, off-plane rigid-chart
preservation, and parallel/antiparallel fallback. Their double-roundoff checks
are not Painter comparison tolerances. No native or production code changed;
exact equality, task checkboxes and refusals 245/259 remain unchanged.

The smallest next causal control is a fresh authored 2-by-2 set: one versus two
internal tau hinges, crossed with regular versus slender tau triangles, keeping
endpoint supporting planes and comparable UV/distance conditions fixed. Add
rigid duplicates with bounding-box anchors to separate geometric policy from
normalized-coordinate arithmetic. Freeze both candidates' domain predicates
and predictions before capture. Use 24 source components, reserving 12 for
verification, selected two/four-tap controls, repeated infinite exports and
save/reopen, and verify covered-source invariance. A skew-axis extension is a
follow-up only if this first set cannot distinguish the hypotheses. No new
recording is claimed here.

## Evidence identities

Public evidence contains aggregates and hashes only. Coordinates, weights,
decoded pixels and detailed diagnostic output remain outside the repository.
Scratch source identities pin this experiment, not a shipped implementation.

| Artifact | SHA-256 |
| --- | --- |
| Tau-prism golden record | `aa0154c4c7c3a2c8b842f088e2bfc6c43979c59ce87308c9eb7ab248f6633a25` |
| Oracle environment | `d4c261535d9af09b11158ec61076a3b5fd181661d179ddba2329122fba43b4a1` |
| Private conservative summary | `2ec5a215f6ff96750564ee3c842cb5d02030c924e21bc734785bf8d40f5ffd17` |
| Private generic rejected summary | `366491ea45e8dc3948b4c5f4c7376ab85a37467f405d37ef201091b35c47a9fa` |
| `tests/export/padding_reference.py` | `c36795882a04c6ee6ff956f4280e4e58a5e605451039dc4f3b0df732e82e546a` |
| Scratch `direct_plane.py` | `592e55695aa22d80cb11bb6dc98283b1d0a57a240d581cba686d3fe667a45da5` |
| Scratch `direct_prism.py` | `4b9eff71a82cdf76ea06809f54b569eb82171d23b7b2f41cbf2beb8057998e4b` |
| Scratch `direct_prism_corpus.py` | `27d8889f5188e1fbc7a66b7780ac3f3367ff59849d553542a03d10cf5ef7dd08` |
| Scratch `direct_wand.py` | `4bae5cbe90e1657d10927d98397eeac0e5c13e78bf9c1c0d52b051ffbbbdda64` |
| Scratch `direct_seam_frame.py` | `28119f768f1d880d0593f568739c9942fb0a4204b5878856b539bc6e809d4e34` |
| Scratch `direct_seam_corpus.py` | `71303772a0b2533cd37cfb4ee46ce6d61b919c47f7772956a8c7c5ada9b5ce63` |
| Scratch `direct_seam_wand.py` | `9390565e7004979ab4db8724656ab26d4eaa9c8b694039407dc75afb66ff9e88` |
