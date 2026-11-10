"""Recording requests of the grunge goldens (`tools.parity.proc_grunges`)."""

from __future__ import annotations

import pytest

from tools.parity.proc_generators.requests import MAX_CASES, SEED_PARAMETER
from tools.parity.proc_grunges.goldens import ASSETS, REFUSED, SEEDED_FIRST, goldens, recorded
from tools.parity.proc_grunges.requests import GRUNGE_URLS, Golden, GrungeCase, manifest
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import job_from_manifest


def test_a_request_is_a_recorder_job_with_one_mask_source_per_case() -> None:
    golden = Golden(
        "probe", "mixed", 1024, (GrungeCase("a", "rock", seed=1), GrungeCase("b", "linen"))
    )
    document = manifest(golden)
    job_from_manifest(document)  # the recorder's own offline check
    steps = document["instruction_sequence"]["steps"]
    sources = [s["args"] for s in steps if s["call"] == ps.SET_EFFECT_SOURCE]
    assert [s["resource"] for s in sources] == [GRUNGE_URLS["rock"], GRUNGE_URLS["linen"]]
    assert all(s["channel"] is None for s in sources)
    seeds = [s["args"] for s in steps if s["call"] == ps.SET_PARAMETERS]
    assert [(s["parameter"], s["value"]) for s in seeds] == [(SEED_PARAMETER, 1)]
    assert not any("bake" in s["call"] for s in steps)
    export = steps[-1]["args"]
    assert export["maps"] == ["documentMap/user0:L", "documentMap/user1:L"]


def test_the_recorded_diagnostic_goldens_cover_every_inventoried_grunge() -> None:
    cases = [(g.resolution, c.asset, c.seed) for g in recorded() for c in g.cases]
    unseeded = set(ASSETS[:4]) - set(SEEDED_FIRST)
    assert unseeded == {"dirt-large"}
    for asset in GRUNGE_URLS:
        found = {(r, s) for r, a, s in cases if a == asset}
        if asset in unseeded:
            assert found == {(1024, None), (2048, None)}
        else:
            assert {(1024, 1), (1024, 2), (2048, 1)} <= found
    assert len(GRUNGE_URLS) == 17
    assert {g.name for g in goldens()} >= REFUSED
    for golden in goldens():
        job_from_manifest(manifest(golden))


@pytest.mark.parametrize(
    "bad",
    [
        Golden("probe", "x", 1024),
        Golden(
            "probe", "x", 1024, tuple(GrungeCase(f"c{k}", "rock") for k in range(MAX_CASES + 1))
        ),
        Golden("probe", "x", 1024, (GrungeCase("a", "rock"), GrungeCase("a", "rock"))),
        Golden("probe", "x", 1024, (GrungeCase("a", "teapot"),)),
        Golden("probe", "x", 1024, (GrungeCase("a", "rock", ((SEED_PARAMETER, 2),)),)),
        Golden("probe", "x", 3000, (GrungeCase("a", "rock"),)),
    ],
)
def test_malformed_goldens_are_refused(bad: Golden) -> None:
    with pytest.raises(ValueError):
        manifest(bad)
