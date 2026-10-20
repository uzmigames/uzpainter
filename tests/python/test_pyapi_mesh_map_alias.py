"""`resource.update_layer_stack_resource` with two names of the same bytes bound as mesh maps
(task phase1.24_python-api-facade item 4.1; decision 336 and its amendment).

The expectations come from the golden `tier0/api-probes/p22b-mesh-map-alias-update` (identical
bytes imported as `old` and `alias`, AO bound to `old` and Thickness to `alias`: `update(old,
old)` returns `[]`; `update(old, new)` returns `[old]`, AO then binds `new` and Thickness keeps
`alias`, in the session and after save and reopen), from P22-A `phase1-mesh-map-update` (a fill
bound to the replaced resource binds the new one), and from the documented facade contract
(python/FACADE.md: any edit call marks the project unsaved; a native `Transaction` that raises
commits nothing). No Painter value is in this file.
"""

from __future__ import annotations

from tests.python.conftest import Run

SETUP = """
OLD = IMAGES + "/mask-left-half.png"
old = resource.import_project_resource(OLD, resource.Usage.TEXTURE, "old").identifier()
alias = resource.import_project_resource(OLD, resource.Usage.TEXTURE, "alias").identifier()
new = resource.import_project_resource(
    IMAGES + "/ao-white.png", resource.Usage.TEXTURE, "new"
).identifier()
texture_set = ts.all_texture_sets()[0]
texture_set.set_mesh_map_resource(ts.MeshMapUsage.AO, old)
texture_set.set_mesh_map_resource(ts.MeshMapUsage.Thickness, alias)

def bound():
    texture_set = ts.all_texture_sets()[0]
    return [texture_set.get_mesh_map_resource(u).name
            for u in (ts.MeshMapUsage.AO, ts.MeshMapUsage.Thickness)]
"""


def test_two_names_of_the_same_bytes_are_two_resources(facade: Run) -> None:
    """Golden s3-s4 and s10-s11: one version, two names, and each mesh map reads the name it was
    bound with."""
    report = facade(
        "stack = create()\n"
        + SETUP
        + """
assert old.version == alias.version and old.name != alias.name
assert new.version != old.version
assert old != alias
result = bound()
"""
    )
    assert report["status"] == "ok", report
    assert report["result"] == ["old", "alias"]


def test_replacing_a_resource_by_itself_replaces_nothing(facade: Run) -> None:
    """Golden s8: `update(old, old)` returns `[]`. No binding and no native revision changes;
    the call is an edit call, which marks the project unsaved (FACADE.md `needs_saving()`)."""
    report = facade(
        "stack = create()\n"
        + SETUP
        + """
project.save_as(os.path.join(WORK, "alias.spp"))
saved = project.needs_saving()
revision = uzpainter.project.revision()
returned = resource.update_layer_stack_resource(old, old)
result = {"saved": saved, "returned": returned, "bound": bound(),
          "revision_unchanged": uzpainter.project.revision() == revision,
          "needs_saving": project.needs_saving()}
"""
    )
    assert report["status"] == "ok", report
    assert report["result"] == {
        "saved": False,
        "returned": [],
        "bound": ["old", "alias"],
        "revision_unchanged": True,
        "needs_saving": True,
    }


def test_update_rebinds_the_named_mesh_map_and_fill_and_keeps_the_alias(facade: Run) -> None:
    """Golden s9-s11 with P22-A s9-s11: AO and the fill bound to `old` bind `new`, Thickness keeps
    `alias`; `[old]` is returned, once; all three persist through save and reopen."""
    report = facade(
        "stack = create()\n"
        + SETUP
        + """
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor}
fill.set_source(CT.BaseColor, old)
uid = fill.uid()
returned = resource.update_layer_stack_resource(old, new)

def state():
    source = ls.get_node_by_uid(uid).get_source(CT.BaseColor).resource_id
    return {"bound": bound(), "fill": [source.name, source.version == new.version]}

session = state()
path = os.path.join(WORK, "alias.spp")
project.save_as(path)
project.close()
project.open(path)
result = {"returned": [[r.name, r.version == old.version] for r in returned],
          "session": session, "reopened": state()}
"""
    )
    assert report["status"] == "ok", report
    after = {"bound": ["new", "alias"], "fill": ["new", True]}
    assert report["result"] == {
        "returned": [["old", True]],
        "session": after,
        "reopened": after,
    }


def test_an_aborted_outer_transaction_restores_every_binding(facade: Run) -> None:
    """Inside an open native `Transaction` the facade's mesh-map rebind and the native layer-stack
    rebind join it; when the block raises, nothing is committed: AO, Thickness, the fill and the
    revision are as before (the `Transaction` contract, test_pyapi_native.py)."""
    report = facade(
        "stack = create()\n"
        + SETUP
        + """
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor}
fill.set_source(CT.BaseColor, old)

def fill_name():
    return ls.get_node_by_uid(fill.uid()).get_source(CT.BaseColor).resource_id.name

revision = uzpainter.project.revision()
inside = None
try:
    with uzpainter.Transaction("outer"):
        resource.update_layer_stack_resource(old, new)
        inside = bound() + [fill_name()]
        raise KeyError("abort")
except KeyError:
    pass
result = {"inside": inside, "after": bound() + [fill_name()],
          "revision_unchanged": uzpainter.project.revision() == revision}
"""
    )
    assert report["status"] == "ok", report
    assert report["result"] == {
        "inside": ["new", "alias", "new"],
        "after": ["old", "alias", "old"],
        "revision_unchanged": True,
    }
