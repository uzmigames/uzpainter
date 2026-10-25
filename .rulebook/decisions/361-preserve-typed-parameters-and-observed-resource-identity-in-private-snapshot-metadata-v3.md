# 361. Preserve typed parameters and observed resource identity in private snapshot metadata v3

**Status**: accepted
**Date**: 2026-10-25
**Related Tasks**: phase3.1_proc-backend-seam

## Context

Local coordinator technical decision under the owner's continuous implementation request. Real capture/replay over derived private project bab09b8b950dadfb4c719bf9030029b0a4f22a33abe818802250a257677d59e5 found integral float parameters returned as ints because bind-snapshot copies value-canonical signature parameters. Existing SourceSubstance.resource_id intentionally returns the UzPainter pin; task 3.2 explicitly asks for a coordinator decision. Licensing and clean-room policy sections 1.6 and 1.7 permit observed readbacks as private oracle/per-project migration data; CLR-06 governs internal aliases and shipped assets. This changes the documented getter contract only for newly observed private metadata. It is not an owner licensing amendment, parity exception, gate waiver, or pilot authorization. Independent local review approves the design; Grok reviewed public identity/immutability risks, not private data or implementation.

## Decision

Add closed optional source metadata schema /3 with typed_effective_parameters and observed_resource_id observations. Keep /1 and /2 closed and byte-compatible when new observations are absent; never enrich or replace an existing immutable entry for the same signature. typed_effective_parameters is the complete raw JSON parameter map observed through get_parameters, accepting only int64, finite double and string in the current domain, not bool/vector/color/object/array. Paired observed maps must be canonically identical preserving JSON numeric types and signed zero; their exact keys and ParamJson-encoded values must match the complete signature parameter map. Preserve raw observed JSON; never infer parameter types or a parameters/properties bijection. Bind uses the typed map when present, otherwise the existing signature map. SignatureJson/SignatureHash stay value-canonical and unchanged.
observed_resource_id is a complete private observation {url,context,name,version} from the documented ResourceID getters. Capture every part, do not reconstruct from a hash or infer missing parts. Paired complete identities must match canonically; url must equal the validated receipt source.resource and requested versioned resource, and its SHA-256 must identify the existing internal snapshot asset pin. SourceSubstance.resource_id may return that observed identity for the exact current admitted snapshot when present. The internal ProceduralRef.asset, metadata asset pin, evaluator requests and native resolution continue using UzPainter pins. A native observational ResourceID codec must return its recorded URL and parts without enabling external resolution, import, source binding, search or alias registration. Reject such use before mutation. Legacy absent observations preserve the prior getter and effect behavior. Fallback is only for legitimate absence, never corruption, foreign entries, invalid signatures or stale handles. Resolve current metadata on each getter; never borrow identity/types from another signature.
New captures use a new private fixture and the same bounded ownership/lock protocol; the existing /2 fixture remains unchanged. Update the explicit getter documentation and task note. Validate legacy bytes, typed integral-float roundtrip, strict field/type refusals, receipt/pin mismatch, immutable conflicting observations, current-signature behavior, observational-ID refusal paths, save/reopen and real typed source replay. Keep all recorded values/identities/pixels private, publishing only permitted hashes/counts. No capability promotion or 3.2 closure until actual exact compared evidence satisfies scope.

## Alternatives Considered

- Coerce signature integers into floats using Property descriptors: rejected; invents a parameter/property mapping and changes unobserved values.
- Normalize or exclude resource_id when declaring full parity: rejected; conceals a real difference.
- Append observations to existing /2 entries or use an unhashed side table: rejected; violates immutability and allows ambiguous provenance.
- Retain only the internal pin forever: preserves current behavior but cannot satisfy the observed SourceSubstance identity contract.

## Consequences

Corrects observable type loss and permits genuine ResourceID readback without inventing an alias or waiving comparison. Native ResourceID codec and call sites require explicit provenance-only handling. Existing /2 entries and fixture cannot be upgraded in place; a fresh bounded capture is required after implementation. Signature and old operation identities remain unchanged. G1, G2, owner amendment, real pilot admission, M8 and task-wide acceptance remain independent and open.
