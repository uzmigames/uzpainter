"""The persistent evaluation results (decision 253; `src/evaluator/result_cache.h` over
`src/render/disk_cache.h`).

The native case `persistent` of `uzp-evaluator-tests.exe` (`tests/evaluator/evaluator_test.cpp`)
runs on the CPU anywhere, under a cache folder of its own: a fresh evaluator, as a new process
has, is served a stored read-out or virtual normal bit for bit and computes nothing; everything
that is not the stored result misses. The test across processes is in
`tests/python/test_pyapi_cli.py`.
"""

from __future__ import annotations

from pathlib import Path

from tests.evaluator.test_compositor_tile_dag import run_case


def test_persistent_results_are_served_bit_for_bit_and_only_for_their_inputs(
    evaluator_tests: Path, tmp_path: Path
) -> None:
    passed, _ = run_case(evaluator_tests, "persistent", str(tmp_path))
    assert {
        "with the caches off there is no persistent area",
        "with the caches on, the eval area lies under the root, capped at 4 GiB, keyed with the "
        "build fingerprint",
        "without the caches nothing is stored",
        "a cold evaluation computes each channel and stores its read-out",
        "a cold evaluation equals the evaluation without the caches bit for bit",
        "a fresh evaluator serves both channels from the stored read-outs and computes nothing",
        "the stored read-outs equal the evaluation without the caches, every tile and texel bit "
        "for bit",
        "an edited stack misses, is computed and stored under its own key, and is then served as "
        "computed",
        "under other MXCSR control bits the stored read-out is not served: a new key is computed "
        "and stored",
        "an evaluator whose tile cache holds the read-out reads it there, without reading or "
        "writing the disk",
        "with a bitmap missing, the stored read-out is not served and the evaluation fails with "
        "missing_resource exactly as without the cache",
        "a flipped payload byte (the checksum): a miss, recomputed bit for bit and stored again, "
        "then served",
        "a flipped key byte: a miss, recomputed bit for bit and stored again, then served",
        "another format version: a miss, recomputed bit for bit and stored again, then served",
        "a truncated entry: a miss, recomputed bit for bit and stored again, then served",
        "an empty entry: a miss, recomputed bit for bit and stored again, then served",
        "a combined virtual normal is stored cold and served to a fresh evaluator bit for bit, "
        "tag included",
        "with the Height bitmap missing, the stored virtual normal is not served: missing_resource",
        "a geometry-masked read-out's hash changes with the mesh's stored external files, "
        "geometry hashes, objects and import settings, not with its file name",
        "over its cap the area removes the least recently used entry (a hit counts as a use)",
        "an entry of another size than the caller's is inconsistent: a miss, removed",
        "an entry larger than the cap is not written",
        "eight threads writing and reading one key only ever read the whole entry",
    } <= passed
