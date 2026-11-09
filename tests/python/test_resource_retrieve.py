"""`substance_painter.resource.Resource.retrieve` outside its Tier 0 golden
(`resource-retrieve-cached-url`, compared in `test_pyapi_observed_host_tier0.py`): the usage of
the resource it returns, an unsaved import, and the identifiers the golden does not record, which
refuse before anything is read (task phase3.1_assets3d-cutover)."""

from tests.python.conftest import Run


def test_retrieve_returns_the_imported_resource_with_its_usage(facade: Run) -> None:
    report = facade(
        r"""
stack = create()
imported = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
url = imported.identifier().url()
found = resource.Resource.retrieve(resource.ResourceID.from_url(url))
assert [r.identifier() for r in found] == [imported.identifier()]
assert found[0].usages() == [resource.Usage.TEXTURE]
absent = resource.ResourceID.from_project(imported.identifier().name, "0" * 40 + ".image")
assert resource.Resource.retrieve(absent) == []
project.close()  # never saved: the cached URL now names nothing in the next project
create()
stale = raises(resource.Resource.retrieve, resource.ResourceID.from_url(url))
current = imported.identifier().name, imported.identifier().version
same_context = resource.ResourceID.from_project(*current)
result = {"stale": stale, "unsaved": resource.Resource.retrieve(same_context)}
"""
    )
    assert report["status"] == "ok", report.get("error", report)
    assert report["result"] == {"stale": "ValueError: invalid resource id", "unsaved": []}


def test_unrecorded_identifiers_refuse_before_anything_is_read(facade: Run) -> None:
    report = facade(
        r"""
no_project = raises(resource.Resource.retrieve, resource.ResourceID("project0", "a", "v.image"))
create()
imported = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
result = {
    "no_project": no_project,
    "unversioned": raises(
        resource.Resource.retrieve, resource.ResourceID.from_project(imported.identifier().name)
    ),
    "shelf_context": raises(
        resource.Resource.retrieve, resource.ResourceID("starter_assets", "a", "v")
    ),
    "not_an_identifier": raises(resource.Resource.retrieve, imported),
}
"""
    )
    assert report["status"] == "ok", report.get("error", report)
    result = report["result"]
    for key in ("no_project", "unversioned", "shelf_context"):
        assert result[key].startswith("NotYetSupported: Resource.retrieve of "), result
    assert result["not_an_identifier"].startswith("TypeError: "), result
