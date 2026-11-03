# 394. Every native artifact compiles a stamp keyed on the files under its source and include roots

**Status**: accepted
**Date**: 2026-11-03
**Related Tasks**: phase2.10_pilot-tunic-recovery

## Context

On 2026-11-03 the Tunic state test ran a stale `UzPainter.exe`. `src/evaluator/ocio_srgb_table.inc` had grown from 449 to 498 entries, but a probe found 0 of the 49 new entries in the executable. The table is a header-only input: `src/evaluator/sources.cpp` pulls it in with `#include`, not `#embed`, so decision 147's digest define does not cover it.

What the cache shows (Zig 0.15.2; manifests bound to their outputs by recomputing the output directory as SipHash128(1,3) over the manifest name digest and the recorded file digests, `std/Build/Cache.zig`):

- **`UzPainter.exe`, `h/7f34aa76…`** (written 00:57:48Z, output `o/78538698…/UzPainter.exe`, SHA-256 `5469083119e8…`). It lists 1,976 inputs: the 203 C sources with their content hashes, the Zig runtime, and the depfile headers of exactly `plan.cpp` and `padding.cpp`, the two objects recompiled at 00:57:12. It lists `sources.cpp` but not the table. The previous full manifest of the same executable, `h/68dbe13f…` (11-02 19:10Z, after a full compile), had 2,768 inputs, among them the old table: 793 headers are missing from the newer one. The executable links `sources.obj` `904c7540…`, built from the old table.
- **`uzp-export-tests.exe`, `h/ea7c18f0…`** has no table line either and links `sources.obj` `0dcef515…` (old table).
- **`uzp-pyapi-tests.exe`, `h/d23db41e…`** lists the new table and links `35b17933…` (new table). It was fresh only because its last link predated the `plan`/`padding` edits, so its entry missed and every object was checked.
- **Object manifests are truthful.** Each `sources.obj` manifest records the table hash its object was built from.

Mechanism (INFERRED: the compiler source that writes executable and library manifests is not shipped, and no compiler code backs this): after a relink, Zig rewrites the whole-entry manifest of an executable with its C sources and the depfile headers of only the objects it recompiled in that run. Reused objects contribute only their source path. A later edit to a header that only reused objects include therefore changes no input of the entry. The old binary is served, and no object is checked. Static libraries are assumed to behave the same way, which has not been proven separately.

This is not decision 041's race: no file changed during a compile, and every object entry is correct. Zig 0.15.2 has no hook that adds a file to a Compile step's cache key. `dependOn` only orders steps, and `addWatchInput` only drives `--watch`.

## Decision

`native_input_key.zig` (repository root, listed in `build.zig.zon`) gives every executable and library one generated C stamp. `build()` calls `stampAll` in one deferred block, after `embed_inputs.check()`. The order is written out, not left to defer order.

- **Graph.** Every Compile step reachable from `b.top_level_steps` through `Step.dependencies`, plus every `.other_step` link object of every module in each compile's `root_module.getGraph()`. The module edges are wired only after `build()` returns, so the link objects are chased as `Compile.getCompileDependencies` does. Today that is 30 executables and 6 static libraries. The count is checked, not hard-coded.
- **Roots.** Each include directory (`.path`, `.path_system`, `.path_after`), each C source root, and each compiled source's directory. `build.zig` widens them: `src/…` becomes `src/`, `tests/…` becomes `tests/`, and `thirdparty/<pkg>/…` becomes `thirdparty/<pkg>/`. This covers `../` includes that stay inside a package. Explicit files are added beside the roots: the `#embed` targets of every source passed to `EmbedInputs.add` (for example `assets/defaults/baking.json` and `parity/…`), the Win32 manifest, and object files (`python313.lib`). An executable's digest does not include the roots of the libraries it links. A library change reaches the executable through the library's own output.
- **Inputs.** Every regular file under the roots, whatever its extension (`.c`, `.cpp`, `.md` and `.py` included), skipping only cache directories (`__pycache__`, `.zig-cache`, `zig-cache`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and the cache and install directories when they lie inside the build root). There is no include scanner, and old manifests are never a source.
- **Digest.** SHA-256 over `uzp-native-input-key-v1\0`, then, for each input in byte order of its build-root relative `/` path, deduplicated: the path, a zero byte and the file's SHA-256. A root or file missing on disk enters as `missing:<path>` and a zero byte, so it neither fails the build nor drops out silently. Each file is read once per configure, and the reads are shared across artifacts.
- **Stamp.** `<artifact>-native-inputs.c` from `b.addWriteFiles()`, holding `/* UzPainter native input key v1: <hex> */` and `typedef int uzp_native_input_key;`. It is added to the artifact's root module as C with `-std=c11`. It has no symbol and no run-time effect. No existing object's flags change.
- **Phases.** Collect every artifact's roots and files, then compute every digest, and only then attach any stamp. A stamp is never an input of a digest.
- **Refusals (configuration fails, decision 394 named in the message):**
  - a generated, `cwd_relative` or dependency-owned LazyPath;
  - a root that is the build root itself, or that lies in `.zig-cache`, `zig-cache`, `zig-out`, the cache root or the install prefix;
  - include directories other than `.path`, `.path_system` and `.path_after`, except the installed-header tree that `linkLibrary` adds, which is accepted only while the library installs no headers;
  - assembly and `.rc` link objects, library paths, rpaths, frameworks, linker or version scripts, libc files, a Zig root source file, and a Compile kind other than executable or library;
  - two compiles sharing a root module;
  - symbolic links under a root;
  - per-source flags that name a path. The prefixes refused are `-I`, `-i…`, `-F`, `-B`, `-L`, `--…`, `@`, `-Xclang`, `-Xpreprocessor`, `-Wp,`, `-fmodule…`, `-fprebuilt-module-path`, `-fprofile…`, `-fembed…` and the sanitizer list flags. This is a list of common path flags, not a parser: a path flag outside it is not covered;
  - an inventory file that lies under a root or is an input.
- **Inventory.** `-Dnative-input-inventory=<file>` writes each artifact's digest, roots and inputs. It is used only to check coverage.

## Alternatives Considered

- Digest only `#include "*.inc"` targets through `EmbedInputs` (the first plan). Rejected: it leaves the other 793 headers of `7f34aa76` exposed.
- Remove the stale executable entries after each header-only edit. Rejected as the durable fix: it is a manual coordinator rule that has to be repeated after every edit, and it needs owner approval each time.
- One digest flag on every object. Rejected: any header edit would recompile every object.

## Consequences

- **Cost.** Every configure walks and hashes the roots. The previous front measured 1,821 files and 130.1 MB with package-root widening, about 0.69 s with warm file caches, read-only. The first plan without package widening measured 1,716 files, 64.6 MB and 0.39 s. A cold configure costs more. Any edit under `src/`, `tests/` or a used third-party package changes the digest of every artifact that reads it, so each such artifact recompiles only its stamp plus the objects that really depend on the edit, then relinks. Unchanged builds stay full cache hits.
- **Rollout.** Every key changes once. Every object is checked, and only the objects whose recorded inputs differ recompile: `sources.cpp` in the variants built from the old table. Everything relinks once. The stale entries `7f34aa76` (`UzPainter.exe`) and `ea7c18f0` (`uzp-export-tests.exe`) become unreachable without a purge, because the stamp path is part of every new key. Nothing is deleted.
- **Residual risks.**
  - Toolchain headers (Zig 0.15.2's libc, libc++ and MinGW-w64 headers, compiler_rt) are not hashed. They are pinned compiler inputs that change only with a Zig upgrade, which `build.zig` refuses.
  - Decision 041's edits-during-build race still applies: a header saved while a compile runs is hashed after that compile. The rule of one `zig build` at a time and no native edits during a build stays.
  - Path-bearing flags outside the refused list, and includes that leave a package root through `..`, would not be keyed. An audit found none today.
  - The library behaviour is inferred, not proven, so libraries are stamped as well.
- **Coverage check.** The in-repo paths of the 10 full historical manifests are compared with each artifact's inventory. These are UzPainter `68dbe13f` (647 paths), pyapi `0f874365` (529), export-tests `0e237afc` (259), evaluator-tests `96b651a3` (197), `uzp_store` `1ff900d3` (66), `uzp_texture` `c9139cc3` (13), `uzp_mesh` `45018c3a` (42), `uzp_core` `4b295394` (28), `uzp_gltf` `458dd680` (10) and `uzrendercore` `b5657fb3` (128). Every in-repo path lies under `src/`, `tests/`, a used `thirdparty/<pkg>/`, or is one of the `#embed` targets under `assets/` and `parity/`. The per-artifact comparison runs on the inventory in the validation window.
- **Validation (2026-11-03).** In serialized runs with the native inputs frozen (three separate pytest invocations: key, embed, then the two production tests):
  - `zig build -l -Dnative-input-inventory=…` configured cleanly and listed 36 artifacts (30 executables, 6 libraries).
  - `python -m tools.native_input_coverage <inventory>` found every in-repo path of all 10 pinned manifests among its artifact's inputs (0 gaps).
  - `tests/vendoring/test_native_input_key.py` passed (26 cases), and the rewritten `tests/vendoring/test_embed_inputs.py` passed (4).
  - The `painter` build then produced a new `UzPainter.exe` (`c4bc3666…`, no longer `54690831…`) that holds all 49 table entries the stale build lacked. The real Tunic state and recipe tests passed on it.
  - An immediate unchanged `zig build painter` into the same prefix compiled nothing, added no output-cache directory and left the executable byte-identical.
  - `python -m tools.native_input_coverage verify <inventory>` recomputed all 36 digests from the current bytes and found them equal to the configure-time ones, with no root gaining or losing a file.
- **Proof.** `tests/vendoring/test_native_input_key.py` builds an authored fixture (`tests/vendoring/native_input_key_fixture/`, a two-unit static library and an executable with separate roots) with a copy of the helper in pytest's `tmp_path`, CPU only. It checks that a header-only edit recompiles only the stamp and the dependent source, that unchanged objects keep their path and hash, that the run output updates, and that unchanged builds are hits.
