"""`resource.search` over the asset library and the `.sbsar` import refusal
(phase3.1_proc-backend-seam items 2.4 and 2.5, decision 324).

`search` answers only from UzPainter's asset library: the shipped library holds no certified asset
and no alias yet, so every Painter name is refused; with the synthetic fixture library
(`UZP_ASSET_LIBRARY`) a Painter name resolves through the alias table to the UzPainter asset, with
its UzPainter name and its provenance. Importing a `.sbsar` file raises `UnsupportedProcedural`
(reason "no runtime") before the file is read and before any mutation. CPU only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.python.conftest import Run

FIXTURE = Path(__file__).resolve().parents[1] / "procedural/fixtures/library"
SHIPPED_LIBRARY = Path(__file__).resolve().parents[2] / "assets/procedural"


def shipped_resource_ids() -> list[str]:
    """The ResourceID of every record of the shipped library, sorted."""
    library = json.loads((SHIPPED_LIBRARY / "library.json").read_text(encoding="utf-8"))
    ids = []
    for path in library["records"]:
        record = json.loads((SHIPPED_LIBRARY / path).read_text(encoding="utf-8"))
        family, rest = record["asset"].removeprefix("uzasset://").split("/", 1)
        asset_id, version = rest.split("@", 1)
        ids.append(f"resource://uzasset/{family}/{asset_id}?version={version}")
    return sorted(ids)


SHIPPED = """
def refusal(query):
    try:
        resource.search(query)
    except BaseException as error:
        return [type(error).__name__, getattr(error, "asset", None), getattr(error, "reason", None),
                str(error)]
    return None

shelf = resource.Shelves.add("scripted-shelf", WORK)
result = {
    "own": [r.identifier().url() for r in resource.search("s:uzpainter")],
    "painter": refusal(r"s:starterassets u:filter n:Blur="),
    "listing": refusal("u:generator"),
    "partial": refusal("n:Blur"),
    "user_shelf": refusal("s:scripted-shelf n:anything="),
    "none": refusal(None),
}
"""

FIXTURE_SCRIPT = """
found = resource.search(r"s:starterassets u:generator n:Synthetic\\ Edge\\ Probe=")
r = found[0]
filters = resource.search("s:uzpainter u:filter")
try:
    filters[0].usages()
    filter_usage = None
except BaseException as error:
    filter_usage = type(error).__name__ + ": " + str(error)
result = {
    "count": len(found),
    "url": r.identifier().url(),
    "asset": r.asset_url(),
    "name": r.gui_name(),
    "usages": [u.name for u in r.usages()],
    "status": r.parity_status(),
    "sources": [s["kind"] for s in r.provenance()["sources"]],
    "author": r.provenance()["author"],
    "own": sorted(x.asset_url() for x in resource.search("s:uzpainter")),
    "filter_usage": filter_usage,
}
"""

SBSAR = """
def refusal(call):
    before = uzpainter.project.revision()
    try:
        call()
    except BaseException as error:
        return [type(error).__name__, getattr(error, "asset", None),
                getattr(error, "reason", None), isinstance(error, uzpainter.NotYetSupported),
                uzpainter.project.revision() == before, str(error)]
    return None

create()
resources_before = len(resource.list_project_resources())
archive = os.path.join(WORK, "noise.sbsar")
with open(archive, "wb") as stream:
    stream.write(b"not a real archive")
result = {
    "facade_texture": refusal(
        lambda: resource.import_project_resource(archive, resource.Usage.TEXTURE)),
    "facade_generator": refusal(
        lambda: resource.import_project_resource(archive, resource.Usage.GENERATOR)),
    "facade_missing": refusal(
        lambda: resource.import_project_resource(os.path.join(WORK, "absent.SBSAR"),
                                                 resource.Usage.TEXTURE)),
    "native": refusal(lambda: uzpainter.resource.import_project_resource(
        archive, uzpainter.resource.Usage.SMART_MATERIAL)),
    "resources_unchanged": len(resource.list_project_resources()) == resources_before,
}
"""


def test_search_with_the_shipped_library_answers_no_painter_name(facade: Run) -> None:
    report = facade(SHIPPED)
    assert report["status"] == "ok", report
    result = report["result"]
    # The shipped records declare their domains before calibration and are not certified
    # (phase3.2_proc-filter-families and proc-grunge-families 2.6): listed on UzPainter's shelf,
    # never aliased.
    assert sorted(result["own"]) == shipped_resource_ids()
    assert "resource://uzasset/filter/sharpen?version=1" in result["own"]
    assert "resource://uzasset/grunge/rock?version=1" in result["own"]
    name, asset, reason, message = result["painter"]
    assert (name, asset, reason) == (
        "UnsupportedProcedural",
        "starterassets/filter/Blur",
        "no certified family",
    )
    assert "no other asset is substituted" in message
    for key in ("listing", "partial", "user_shelf"):
        assert result[key][0] == "NotYetSupported", result[key]
    assert "phase3.3_procedural-families" in result["listing"][3]
    assert "scripted-shelf" in result["user_shelf"][3]
    assert result["none"][0] == "TypeError"


def test_search_resolves_a_painter_name_through_the_alias_table(
    facade: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UZP_ASSET_LIBRARY", str(FIXTURE))
    report = facade(FIXTURE_SCRIPT)
    assert report["status"] == "ok", report
    result = report["result"]
    assert result["count"] == 1
    assert result["url"] == "resource://uzasset/test-generator/ridge?version=2"
    assert result["asset"] == "uzasset://test-generator/ridge@2"
    assert result["name"] == "Ridge (synthetic test probe)"
    assert result["usages"] == ["GENERATOR"]
    assert result["status"] == "exact"
    assert result["sources"] == ["paper", "approved-source"]
    assert result["author"].startswith("UzmiGames")
    assert result["own"] == [
        "uzasset://test-filter/soften@1",
        "uzasset://test-generator/ridge@1",
        "uzasset://test-generator/ridge@2",
    ]
    assert result["filter_usage"].startswith("NotYetSupported: resource.Usage.FILTER")


def test_sbsar_import_raises_no_runtime_before_mutation(facade: Run) -> None:
    report = facade(SBSAR)
    assert report["status"] == "ok", report
    result = report["result"]
    for key, asset in (
        ("facade_texture", "noise.sbsar"),
        ("facade_generator", "noise.sbsar"),
        ("facade_missing", "absent.SBSAR"),
        ("native", "noise.sbsar"),
    ):
        name, refused, reason, gap, unchanged, message = result[key]
        assert (name, refused, reason, gap, unchanged) == (
            "UnsupportedProcedural",
            asset,
            "no runtime",
            True,
            True,
        ), result[key]
        assert "UzPainter executes no .sbsar file" in message
    assert result["resources_unchanged"] is True
