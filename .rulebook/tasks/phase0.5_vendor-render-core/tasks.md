## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0_owner-decisions

## 2. Children
- [ ] 2.1 Child accepted: phase0.1_vendor-core-copy (commit selection, export, `LICENSE`, `ORIGIN.md`, `MANIFEST.json`, `NOTICE` entry)
- [ ] 2.2 Child accepted: phase0.2_vendor-thirdparty (third-party libraries from their own upstreams)
- [ ] 2.3 Child accepted: phase0.3_vendor-modifications (UZP-MOD-001…006, `MODIFICATIONS.md`, static-library target)
- [ ] 2.4 Child accepted: phase0.4_vendor-check (CI vendoring check)

## 3. Integration tests
- [ ] 3.1 Clean build of the vendored static library with UzPainter's `build.zig` on a machine without any UzEngine checkout or artifact
- [ ] 3.2 Build inspection: no include path, library path or build step refers outside the UzPainter repository; no `runtime.lib`, no submodule entry, no pin or patch-queue file
- [ ] 3.3 Vendoring check green on the integrated tree

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-VENDOR): builds standalone in UzPainter's own build; no `runtime.lib`, no submodule, no engine path, no pin or patch queue

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
