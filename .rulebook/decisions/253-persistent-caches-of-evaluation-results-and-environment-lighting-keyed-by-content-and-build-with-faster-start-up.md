# 253. Persistent caches of evaluation results and environment lighting, keyed by content and build, with faster start-up

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.14_compositor-core, phase2.2_preview-capture, phase2.8_mcp-server, phase1.22_pyapi-cli-capabilities

## Context

The owner: "we need a faster way of loading, like a cache". The load-cache profile (Wand: 13 layers, 14 masks, 2048², 168 revisions; RTX 4090 / 7950X3D, ReleaseSafe) found where the time goes:

- **The first CPU evaluation in every new process.** The Assets3D adapter starts one `UzPainter.exe run` per call, so every export and every capture evaluates the stack from scratch: 54.7 s on main, 9.9-14.3 s with B19 (decision 246, which reuses an evaluation inside one process only). The first MCP export after a restart pays the same.
- **Environment lighting**, recomputed on the CPU by every `painter_viewport` capture (a function-local cache): 0.97-1.27 s, 38% of a warm in-session capture.
- **Python bytecode**: none existed (1086 `.py`, 0 `.pyc`, `write_bytecode = 0`). The MCP SDK compiled from source on every supervisor start (794 ms; 476 ms with bytecode).
- **Supervisor start in sequence**: the worker launch (436 ms, mostly its GPU device) and only then the SDK import.
- **An unread integrity report**: `Session::Open` (facade, `run`, MCP `project_open`) built a standard `IntegrityReport` and discarded it, 88-186 ms of a 98-215 ms open at 168 revisions, growing with history, paid twice per adapter subcommand.
- Small or already cached: mesh import 8-11 ms, templates 3-7 ms, PSO 2-4 ms warm, DXIL kernels (existing disk cache, always a hit), bitmap decodes 80 ms each but inside the evaluation a result hit skips.

Hard rules: outputs byte-identical with and without the cache, tested; a corrupt entry or a version change detected and ignored (recomputed); bounded size with eviction; under the user cache folder; a way to disable (`--no-cache`) and to clear.

## Panel

The design went to the model panel (`cx/gpt-6-astra`, `kimi/kimi-k3`, `xai/grok-4.5`, one round) as claims C1-C11.

| Claim | GPT | Kimi | Grok | Outcome |
|---|---|---|---|---|
| C1. Persist output-level results (channel read-outs, the combined virtual normal), CPU evaluator only | PARTLY | PARTLY | PARTLY | kept, with the key audit below |
| C2. Fingerprint = module path + size + mtime, ucrtbase, CPUID | DISAGREE | PARTLY | DISAGREE | changed: content hashes |
| C3. Close the glTF external-buffer gap in the geometry-mask hash | PARTLY | AGREE | AGREE | widened to the whole import report |
| C4. One file per entry, checked header, temp + atomic replace, LRU by last-write time | PARTLY | PARTLY | PARTLY | kept, hazards closed below |
| C5. A warm hit need not read the project's bitmaps | DISAGREE | DISAGREE | DISAGREE | rejected |
| C6. Persistent environment lighting | PARTLY | AGREE | AGREE | kept |
| C7. Python bytecode through `pycache_prefix` at run time | PARTLY | AGREE | AGREE | changed: build time, checked-hash |
| C8. `Session::Open` builds no integrity report | PARTLY | PARTLY | AGREE | kept, priced |
| C9. Import the SDK while the worker starts | PARTLY | PARTLY | AGREE | kept, with guards |
| C10. `--no-cache`, `UZP_NO_CACHE`, `UZP_CACHE_DIR`, `cache info|clear`; library default off | PARTLY | AGREE | AGREE | kept |
| C11. No resident adapter server, no bitmap/mesh/PSO caches | PARTLY | AGREE | AGREE | kept |

What the panel changed:

- **C2.** Path, size and last-write time are metadata, not identity (a restore can keep all three). The fingerprint is now XXH64 of the *bytes* of the module holding the evaluator (`UzPainter.exe`, or a test binary) and of the loaded `ucrtbase.dll` (its `pow`, `acos`, `atan2`), the CPU's vendor, signature and feature words, XCR0 (the extended state the OS enables, which the CRT dispatches on) and the entry format version. Computed once per process, lazily (about 20 ms for the 16.8 MB executable). Every rebuild invalidates; orphans age out under the cap.
- **C5.** Unanimous: a warm success where a cold run fails with `missing_resource` makes the cache authoritative. A stored result is served only when every bitmap the stack reads is available: its bytes fetched from the store and hashed, exactly what a cold evaluation does before decoding (`IResourceProvider::Available`, once per bitmap per process), and, when a layer has a geometry mask, a geometry provider is given. Otherwise the evaluation runs and fails as it would.
- **C7.** A run-time `pycache_prefix` puts executable bytecode in a user-writable folder, validates by source timestamp, and has no cap. Instead `zig build painter` runs `python -I -m compileall -q -j 0 --invalidation-mode checked-hash` over `bin/python` and `bin/Lib/site-packages`: nothing is written at run time (`write_bytecode` stays 0, the install folder stays read-only), and the interpreter checks each `.pyc` against its source's hash on import. The files carry the build Python's tag (`cpython-313`); the build's Python must be 3.13 (it already is, for the capability manifest), whose magic number every 3.13 release shares; another version's files are never read.
- **C3.** GPT: every input of the derivation, not just the buffers. The geometry-mask hash now covers the mesh resource and its whole import report except `source` (name and size beside the hash): the stored external files by hash, the import settings (`units`, `merged_materials`), the objects and materials a mask selects by name and the geometry hashes the re-derivation is checked against. This also fixes a latent in-process stale hit after a reload that changed only a `.bin`.

### Inputs the panel asked about

- **OCIO configuration.** The evaluator reads no OCIO file: OCIO means Painter's substance config pinned by hash in the project (`kPainterOcioConfigSha256`, never read), the decode table is compiled in (fingerprint), and each bitmap's OCIO use is in its source hash (97f8302).
- **Thread count and reduction order.** The CPU evaluator on main is single-threaded; B19's threaded store gives the single-threaded result bit for bit and gives every worker the caller's MXCSR, which is in the key.
- **x87.** No `long double` in the evaluator or the preview; x64 code computes in SSE under MXCSR.
- **Other libraries.** Everything but the UCRT is linked into the executable, whose bytes are hashed.
- **Templates and profiles.** A template's base value enters the root hash as floats; profiles are compiled in.
- **Environment bytes.** The store verifies a blob's SHA-256 on every read, and the default environment is checked against `kDefaultEnvironmentSha256`.

## Decision

1. **Persistent evaluation results** (`src/evaluator/result_cache.{h,cpp}` over `src/render/disk_cache.{h,cpp}`). `CpuEvaluator` attaches the `eval` area to its tile cache; `EvaluateOn` and `EvaluateVirtualNormalOn` look up the disk before evaluating and store after a successful miss. Persisted: the read-out of a channel whose root list is isolated and not empty (every tile of `EvaluateChannel`, texels as read back) and the combined virtual normal (float32 x 3). Key: SHA-256 of a domain tag, the payload version, the build fingerprint, the caller's MXCSR control bits and the evaluator's own digest (read-out hash with profile, channel, format, tile format and grid; or the virtual normal's digest with the set size). The GPU evaluator never reads or writes it. An evaluator whose tile cache already holds the read-out (B19's kept evaluation) reads it there and neither loads nor stores.
2. **Persistent environment lighting** (`preview::LightingOf`, area `lighting`): the exact floats of `PrecomputeLighting` keyed by the environment's SHA-256, the five sampling constants, the fingerprint and MXCSR. A hit also skips the decode.
3. **Storage.** `%LOCALAPPDATA%\UzPainter\cache\<area>\<hex key>` (`UZP_CACHE_DIR` overrides the root). An entry is a 56-byte header (magic, version, the full key, payload size, XXH64 of the payload) and the raw payload. It is written to a unique `CREATE_NEW` temporary file and moved over its name in one atomic replace. A read opens the entry shared for reading and deletion, and treats any inconsistency (magic, version, key, a size other than the caller's, a short file, the checksum) as a miss: it deletes the file *through the handle it read*, so it never deletes an entry another process has just replaced, and the result is recomputed and stored again. A hit touches the entry's last-write time; after every write the least recently used entries are removed until the area fits its cap (eval 4 GiB, lighting 256 MiB); an entry larger than the cap is not written; temporary files older than an hour are removed. No cache operation throws: a failed write leaves the result returned. Accepted limits: the LRU is approximate (file times), concurrent writers can overshoot the cap transiently by one entry each, and XXH64 detects damage, not tampering: the folder belongs to the user, who can edit the project anyway.
4. **Switches.** The caches are on in `UzPainter.exe` and off in a library or test binary until it calls `EnableCaches`. `--no-cache` (any verb, anywhere before `--`, stripped before the verb parses) or `UZP_NO_CACHE=1` turns them off; `--no-cache` sets the variable so the MCP worker inherits it. `UzPainter.exe cache info` prints the root, whether the caches are on, and each area's entries and bytes; `cache clear` removes every entry and temporary file of the areas (files in use are skipped and counted; reparse points are never followed; other files are never touched). The existing DXIL kernel cache is unchanged and outside these switches. The test suite runs every `UzPainter.exe` with `UZP_NO_CACHE=1` (`tests/conftest.py`), so no test depends on what an earlier run stored; the cache tests turn the caches on under their own folder.
5. **Bytecode at build time** (C7 above).
6. **Overlapped supervisor start.** `_serve` imports `mcp_types`, `mcp.server.lowlevel` and (stdio) `mcp.server.stdio` on a thread while `Supervisor.start()` launches the worker; the import is awaited before serving and cancelled on a fatal start, which still exits with status 4. An import error surfaces where it did before.
7. **`Session::Open` builds no integrity report** (`OpenOptions::report = false`). Open still runs `quick_check` (B9) and verifies the current manifest; `inspect --verify`, the `export` CLI and the census keep their checks. The adapter's export goes through `run`, so it saves the scan too.
8. **Not done.** No resident adapter server (decisions 105 and 111 stand; the fixed cost per process is now about 0.15 s plus the GPU device for a capture). No caches for bitmap decodes, meshes or PSOs: small, or skipped on a result hit. The release of B19's kept evaluation at close (0.67-0.97 s) belongs to the B19 branch.

## Measurements

Measured on wt/loadcache (main 3f2186f plus this change) against the same commit without it (`loadcache-base`), both ReleaseSafe, one after the other on the shared RTX 4090 / 7950X3D (other agents' builds and Kaspersky running, so indicative). The real Wand through the adapter (one `UzPainter.exe run` per call) and through MCP; caches in a fresh folder per flow. Drivers and logs: the session scratchpad `load-cache\` (`wand_cache.py`, `mcp_cache.py`, `logs\`).

| Flow | Before | After, cold cache | After, warm cache | Bytes |
|---|---|---|---|---|
| Adapter export, 4 maps PNG16 passthrough (new process) | 54.2 / 58.0 s | 55.0 s | **2.49 s** | f5202163, 24171dfa, 9cd6593a, e893061d in every run, `--no-cache` (56.1 s) included |
| Adapter capture `painter_viewport` (new process) | 54.9 / 59.5 s | 64.2 s | **2.97 s** | f22b9da6 in every run, `--no-cache` (56.9 s) included |
| MCP spawn to initialize (5 runs each) | 1.52-1.62 s | 0.77-0.91 s | | |
| MCP `project_open` (168 revisions) | 0.12-0.16 s | 0.04 s | | |
| MCP first export after a restart | 36.3-55.8 s | 45.0-57.7 s | **1.87-2.03 s** | as above |
| MCP same export again in the session | 36.5-38.5 s | 2.5-2.8 s | 2.6 s | as above |
| `run` + `project.open` of the Wand | 161 ms (open 98 ms) | 82 ms (open 14 ms) | | |
| `run` importing the facade | 125 ms | 111 ms | | |

The Wand's `eval` area holds 29 MB after the export (four read-outs). The cold runs pay the evaluation as before; the writes add little that the noise shows (55.0 against 54.2-58.0 s; the cold capture's 64.2 s against 56.9 s uncached includes the 48 MiB virtual normal written and scanned by the antivirus on its first write). B19 (decision 246) is not merged here: it shortens the cold evaluation (9.9-14.3 s) and the repeat inside one process; the warm figures above do not evaluate at all, so they hold with it. The MCP capture in a warm session was not re-measured: the GPU was held by the viewport-shadows workflow's renders.

## Consequences

- A warm export or capture of an unchanged revision no longer evaluates the stack in a new process; its bytes are the uncached bytes (tests below and the Wand hashes above).
- The cache key is now a correctness contract across processes: a field that changes evaluation results must be in the subtree hashes, as it already had to be for the in-process tile cache and the GPU preview.
- A developer rebuild invalidates every entry; `cache clear` frees the space at once.
- Tests: `uzp-evaluator-tests persistent` (`tests/evaluator/test_persistent_results.py`), `uzp-preview-tests lighting-cache` (`tests/preview/test_preview_viewport.py`), and `tests/python/test_pyapi_cli.py` (`cache info|clear`, `--no-cache`, cold and warm exports in separate processes byte for byte, damaged entries recomputed).
