"""Project readbacks use persisted mesh data; facade metadata writes discard native receipts."""

from __future__ import annotations

from tests.python.conftest import Run


def test_scene_bounds_survive_source_changes_and_reopen(facade: Run) -> None:
    report = facade(
        r'''
from pathlib import Path

box = project.BoundingBox([6.0, 0.0, 10.0], [5.0, 4.0, 2.0], 5.0)
assert box.dimensions == [6.0, 0.0, 10.0]
assert box.center == [5.0, 4.0, 2.0]
assert box.radius == 5.0

source = Path(WORK) / "bounds.obj"
source.write_text("""o bounds
v 2 4 -3
v 8 4 -3
v 2 4 7
vt 0 0
vt 1 0
vt 0 1
vn 0 1 0
usemtl bounds
f 1/1/1 2/2/1 3/3/1
""")
settings = project.Settings(default_texture_resolution=256, mesh_unit_scale=2.0)
project.create(str(source), settings=settings)
def bounds():
    box = project.get_scene_bounding_box()
    assert isinstance(box, project.BoundingBox)
    assert isinstance(box.center, list) and isinstance(box.dimensions, list)
    return [list(box.center), list(box.dimensions), box.radius]

# The recorded Painter getter ignores mesh_unit_scale, including after reopen.
expected = [[5.0, 4.0, 2.0], [6.0, 0.0, 10.0], 5.0]
assert bounds() == expected
source.write_text("not a mesh any more")
assert bounds() == expected
project.save_as(WORK + "/bounds.spp")
project.close()
project.open(WORK + "/bounds.spp")
assert bounds() == expected
project.close()
error = raises(project.get_scene_bounding_box)
assert error is not None and error.startswith("ProjectError:"), error
result = {"bounds": expected, "closed_error": error}
'''
    )
    assert report["status"] == "ok", report.get("error", report)


def test_metadata_set_returns_none_and_preserves_native_receipt(facade: Run) -> None:
    report = facade(
        r"""
import uzpainter

project.create(PLANE, settings=project.Settings(default_texture_resolution=256))
metadata = project.Metadata("readback-test")
value = {"nested": [1, True, None, "text"], "number": 1.25}
assert metadata.set("value", value) is None
assert metadata.get("value") == value
assert metadata.list() == ["value"]
assert metadata.get("absent") is None
native = uzpainter.project.Metadata("native-test").set("value", 7)
assert native.status == "committed"
project.save_as(WORK + "/metadata.spp")
project.close()
project.open(WORK + "/metadata.spp")
assert project.Metadata("readback-test").get("value") == value
project.close()
result = {"facade_return": None, "native_status": native.status}
"""
    )
    assert report["status"] == "ok", report.get("error", report)
