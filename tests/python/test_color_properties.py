"""Color property contracts recorded by phase1-color-srgb-value."""

from tests.python.conftest import Run


def test_color_properties_and_srgb_assignment(facade: Run) -> None:
    report = facade(
        r'''
create()
rgb = (1.0, 0.54902, 0.0)
expected = (1.0, 0.549019992351532, 0.0)
for space in (cm.GenericColorSpace.sRGB, cm.GenericColorSpace.Raw):
    color = cm.Color(*rgb, space)
    assert color.sRGB == expected, (space, color.sRGB)
    assert color.value == expected
color = cm.Color(*rgb)
assert color.value == rgb
assert raises(lambda: color.sRGB) == (
    "RuntimeError: color_space is undefined, no conversion can be done."
)
for space in (None, cm.GenericColorSpace.Working, cm.GenericColorSpace.Raw,
              cm.GenericColorSpace.sRGB):
    color = cm.Color(0.25, 0.5, 0.75, space)
    color.sRGB = (0.5, 0.5, 0.5)
    assert color.color_space is cm.GenericColorSpace.sRGB
    assert color.value_raw == (0.5, 0.5, 0.5)
    assert color.sRGB == (0.5, 0.5, 0.5)
    assert color.working == (0.21404114365577698,) * 3
project.close()
result = {"properties": "passed"}
'''
    )
    assert report["status"] == "ok", report.get("error", report)
