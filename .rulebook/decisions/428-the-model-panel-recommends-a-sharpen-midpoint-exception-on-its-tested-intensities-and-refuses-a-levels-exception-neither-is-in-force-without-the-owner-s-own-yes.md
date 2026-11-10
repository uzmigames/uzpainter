# 428. The model panel recommends a Sharpen midpoint exception on its tested intensities and refuses a Levels exception; neither is in force without the owner's own yes

**Status**: accepted (panel consultation the owner asked for, 2026-11-10). The Levels refusal is in force. The Sharpen exception is a recommendation: it is entered in `parity/exceptions.json` only on the owner's own yes to the terms of §2 (decision 259 §6, `parity/CONTRACT.md` §5).
**Date**: 2026-11-10
**Related Tasks**: phase3.3_procedural-families

## Context

Decision 426 left two candidate exceptions for the owner: Sharpen (`filter/sharpen@2`, §2) and the Levels filter (`filter/levels@2`, §3). Asked about them, the owner answered (André, 2026-11-10, pt-BR, verbatim):

> "voce precisa conversar com as outras IAs c isso e aceitavel ou nao"

**The panel.** Two rounds through `python -m tools.model_panel --deadline 180`. Each model got only public reasoning and the aggregate statistics of decision 426 and `docs/analysis/proc-filter-families/02-calibration-2026-11-10.md`: no Painter value, texel or private record hash. Every reply came back `completed` with finish reason `stop`.

| Model (reply id) | R1 Sharpen | R1 Levels | R1 governance | R2 Sharpen | R2 domain | R2 spent held-out |
|---|---|---|---|---|---|---|
| `gpt-5.6-sol` | ACCEPT | REFUSE | ASK-OWNER | ACCEPT | tested intensities | narrowing only |
| `gpt-6-astra` | ACCEPT | REFUSE | ASK-OWNER | ACCEPT | tested intensities | narrowing only |
| `kimi-k3` | ACCEPT | REFUSE | ASK-OWNER | ACCEPT | tested intensities | narrowing only |
| `grok-4.5` | REFUSE | REFUSE | ASK-OWNER | ACCEPT | whole range [0, 4] | narrowing only |

- **Round 1.** Grok refused Sharpen because the route to exactness (measuring the GPU's float-to-UNORM16 write) is still open, the held-out set is spent and the tie-break is unreproduced. The three others accepted it on a per-texel midpoint scope, which can be computed from the input codes and the intensity alone.
- **Round 2** was run because the Sharpen votes conflicted and named different domains. Grok then accepted: the midpoint scope answers its concern. It alone wanted the whole intensity range. The majority keeps the tested intensities: the midpoint predicate says where an error may sit, not that an untested intensity has no other error.
- **Levels**, refused 4 to 0:
  - the regime (a gamma that is neither 1 nor a power of two, with clamp off) is sampled at one point, and one point does not bound a continuous range;
  - the mechanism is unidentified (an effective gamma of about 1.7000006);
  - no per-texel predicate isolates the affected texels;
  - the inspected cases are spent.
- **Governance**, 4 to 0: the owner's reply asks for a consultation. It is not his yes to an exception's terms, so the verdict goes back to him as a plain yes/no question. This matches decision 259 §6 and `parity/CONTRACT.md` §5: a delegation to a model panel is not owner approval. It is also the lesson of EXC-007.

## Decision

1. **Levels: refused.** The Levels filter stays a release gap under item 2.11, `filter.levels@1` `unavailable`, refused with `family not certified`. No exception is prepared. The route is unchanged:
   - sample clamp-off gammas that are neither 1 nor powers of two;
   - find the mechanism, or a per-texel predicate;
   - add the two spent cases as regression cases (decision 222 §2);
   - record a new held-out set and certify again.
2. **Sharpen: the panel recommends an exception, and its terms are fixed here.** These are the terms the owner is asked to approve:
   - **Domain.** `procedural_asset` `filter/sharpen@2`, on decision 426 §1's content (an L32F 16-bit bitmap fill) and the batch's declared geometry and resolutions.
   - **Intensities.** Only the tested set {0, 0.2, 0.25, 0.4, 0.63, 1, 2.71, 4}. Any other intensity is refused as outside the certified domain (decision 222 §3).
   - **Not covered.** Sharpen inside a mask stack, and channels other than L32F (decision 426 §6).
   - **Bound.** Absolute difference of at most one 16-bit code, and only on midpoint texels: those where intensity × (4k − (n + s + e + w)), on the input codes, is exactly a half-integer. That predicate is computed from the inputs, never from the difference. Every other texel is held to 0.
   - **Defect tests, each of which must fail:**
     - a 2-code error on a midpoint texel;
     - a 1-code error on a non-midpoint texel;
     - wrong midpoint detection;
     - a wrong wrap;
     - a wrong clamp;
     - any change at an exact intensity (0, 0.2, 0.4, 1, 4);
     - an intensity outside the set.
   - **Expiry.** The exception lapses when the float-to-UNORM16 write is measured (item 2.10). The candidate that follows needs a new held-out set, which narrows, confirms or revokes the exception. The spent held-out set blocks only that later step, not this exception (4 to 0).
3. **Not in force until the owner says yes.** No `parity/exceptions.json` entry is written, `filter/sharpen@2` stays `calibrated` and unserved, and `filter.sharpen@1` stays `unavailable`. On his yes:
   - the entry is written with the next unused `EXC-` id, `approved_by: owner`, and this decision, or the decision that records his yes;
   - the verdict gains the midpoint scope and its defect test;
   - the record serves only that domain.

   The question to put to him, in plain words (pt-BR):

   > "Sharpen: em alguns texels, só onde a conta cai exatamente no meio entre dois níveis de 16 bits, o UzPainter pode ficar 1 nível (1/65535) acima ou abaixo do Painter; todo o resto fica idêntico. Vale só para as intensidades testadas (0, 0.2, 0.25, 0.4, 0.63, 1, 2.71, 4); outras são recusadas. A exceção cai quando medirmos o arredondamento da GPU. Aprova? (Sim/Não)"

## Alternatives Considered

- **Record both exceptions as owner-approved on the delegation**, as the consultation request suggested. Rejected for three reasons: decision 259 §6, `parity/CONTRACT.md` §5, and the panel's 4-to-0 governance vote. EXC-007 was withdrawn for exactly that.
- **The whole Sharpen intensity range [0, 4]** (Grok's round-2 view). Not taken, by majority (3 to 1). It can be widened by a new version once a new held-out set covers interior intensities.
- **A Levels exception at the single recorded point** (gamma 1.7, output 0.05 to 0.9, no clamp). Not taken. Kimi called it "a fixture, not certification", and no model accepted it.

## Consequences

- Items 2.10 and 2.11 of `phase3.3_procedural-families` cite this decision.
- No register, record, native or capability-manifest change is made. Both filters stay release gaps until the owner says yes (Sharpen) or a new certification succeeds (both).
