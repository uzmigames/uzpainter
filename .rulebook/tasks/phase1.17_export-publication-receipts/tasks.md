## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core, phase1.15_export-plan-compiler, phase1.16_export-processing-encoders

## 2. Implementation
- [ ] 2.1 Implement generation directories with per-file flush and verification against the plan (size and SHA-256)
- [ ] 2.2 Implement the atomic durable `current.json` pointer update and `uzpainter export --recover`
- [ ] 2.3 Implement the fixed-name copy journal, the generation-pinning delivery adapter and the coordinated publication lock
- [ ] 2.4 Implement receipts with the ARC-11 header, per-file fields, normal tags, consumer gaps and the `exportacao` block, plus `receipt.schema.json`
- [ ] 2.5 Add test-only fault hooks between every publication step, excluded from release builds

## 3. Tests
- [ ] 3.1 Interrupt after each file, after the receipt and around the pointer rename: a consumer reading `current.json` sees the old or the new complete generation; `--recover` completes or discards the interrupted one
- [ ] 3.2 Interrupt each fixed-name copy, then immediately invoke a fixed-name test consumer through the delivery adapter and through the publication lock: it consumes one complete generation or fails before consumption
- [ ] 3.3 Staging names never appear in a receipt or in `current.json`
- [ ] 3.4 Receipt schema: every field present and valid; normal tags `combined`/`geometry_only` with relief round; the `exportacao` block complete
- [ ] 3.5 An encoder failure leaves the previous generation selected and the host process alive

## 4. Acceptance
- [ ] 4.1 Publication interruption and receipt tests green on the hosted CPU lane

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
