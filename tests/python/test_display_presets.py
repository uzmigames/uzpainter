"""Display presets, environments, cameras and the pinned display API (task
phase2.1_preview-display-presets, items 3.1-3.5; decisions 038, 042 and 132;
`src/python/display.h`).

Each script runs in `uzp-pyapi-tests.exe` (conftest.py). CPU only: every lane runs these. The
comparison with the pipeline standard reads `Render-Comparison-Standard.json` where the Assets3D
checkout is (`UZP_RENDER_STANDARD`, else its path on the owner's machine) and checks its SHA-256
first.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.python.conftest import REPO_ROOT, Run

ENVIRONMENTS = REPO_ROOT / "assets" / "environments"
SHIPPED = ENVIRONMENTS / "studio-small-09.exr"
PROVENANCE_SCHEMA = REPO_ROOT / "src" / "python" / "environment-provenance.schema.json"
STANDARD = Path(
    os.environ.get(
        "UZP_RENDER_STANDARD",
        r"E:\UzmiGames\Assets3D\Pipeline\render\Render-Comparison-Standard.json",
    )
)
STANDARD_SHA256 = "2ec4281f7a1414c836eb59aec4fa895db0706c2fc9c4e19433325939a6525be5"
DECISION = "(decision 038)"


def ok(report: dict[str, Any]) -> Any:
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"]


def with_shipped(body: str) -> str:
    return f"SHIPPED = {SHIPPED.as_posix()!r}\n" + body


# ── 3.1 Preset round trip and the standard's values ─────────────────────────────────────────────

ROUND_TRIP = """
from uzpainter.render import display as rd
create()
env = resource.import_project_resource(SHIPPED, resource.Usage.ENVIRONMENT, "studio")
fresh = rd.preset()
fresh_default = rd.state()["environment_default"]
preset = rd.presets()[1]
preset["environment"]["sha256"] = env.identifier().version
preset["environment"]["rotation"] = 180.0
preset["cameras"] = [{"position": [0.5, 1.25, 60.0], "rotation": [-10.0, 180.0, 0.0],
                      "projection_type": "Perspective", "field_of_view": 40.0, "focal_length": 50.0,
                      "focus_distance": 60.0, "aperture": 0.0, "orthographic_height": 12.5}]
preset["seed"] = 7
applied = rd.apply_preset(preset).status
first = json.dumps(rd.preset(), sort_keys=True)
project.save_as(WORK + "/presets.uzp")
project.close()
project.create(PLANE, project.Settings(default_texture_resolution=256))
resource.import_project_resource(SHIPPED, resource.Usage.ENVIRONMENT, "studio")
rd.apply_preset(json.loads(first))
loaded = json.dumps(rd.preset(), sort_keys=True)
project.close()
project.open(WORK + "/presets.uzp")
reopened = json.dumps(rd.preset(), sort_keys=True)
result = {"fresh": fresh, "fresh_default": fresh_default, "applied": applied, "first": first,
          "loaded": loaded,
          "reopened": reopened, "presets": rd.presets(), "state": rd.state()}
"""


def test_preset_round_trip_is_lossless(run: Run) -> None:
    """3.1: serialise, load into a new project, serialise again: identical, and identical after
    save and reopen. A new project starts on the `common` preset with no environment."""
    result = ok(run(with_shipped(ROUND_TRIP)))
    assert result["applied"] == "committed"
    assert result["first"] == result["loaded"] == result["reopened"]
    first = json.loads(result["first"])
    assert first["name"] == "ref_match" and first["seed"] == 7
    assert first["environment"]["rotation"] == 180.0 and len(first["cameras"]) == 1
    fresh = result["fresh"]
    common = dict(result["presets"][0])
    assert common["name"] == "common"
    common["environment"] = {**common["environment"], "sha256": None}
    assert fresh == common
    # The shipped environment is not the standard's: the state is a non-parity preview.
    assert result["state"]["parity"] is False
    # A project that names no environment renders lit by the installation's default (decision
    # 212); one that names an environment does not.
    assert result["fresh_default"] is True and result["state"]["environment_default"] is False


def standard_presets() -> dict[str, dict[str, Any]]:
    """The two presets as `Render-Comparison-Standard.json` defines them."""
    if not STANDARD.is_file():
        pytest.skip(f"{STANDARD} is not on this machine (set UZP_RENDER_STANDARD)")
    data = STANDARD.read_bytes()
    assert hashlib.sha256(data).hexdigest() == STANDARD_SHA256, (
        "the standard changed: decision 038 re-opens"
    )
    s = json.loads(data)
    painter, contract = s["painter"], s["painter"]["render_contract"]
    iray = s["painter"]["iray_settings"]["sliders"]
    assert iray["minSamples"] == iray["maxSamples"]

    def preset(
        name: str, block: str, version: int, sha: str, lighting: dict[str, Any], rgb: Any
    ) -> dict[str, Any]:
        sliders, checks = lighting["sliders"], lighting["checks"]
        assert lighting["combos"]["environment_mode"] == "Infinite sphere"
        return {
            "schema": "uzpainter/display-preset/1",
            "name": name,
            "standard": {
                "source": "U-A3D-RENDERSTD-2",
                "sha256": STANDARD_SHA256,
                "block": block,
                "version": version,
            },
            "environment": {
                "sha256": sha,
                "exposure": sliders["pbrExposure"],
                "rotation": sliders["envRotation"],
                "opacity": sliders["cubemapOpacity"],
                "blur": sliders["envBlur"],
                "dome": "infinite_sphere",
                "color_space": contract["environment_color_space"],
                "shadows": checks["shadows"],
            },
            "background": {"clear_color": checks["use_clear_color"], "srgb8": rgb},
            "ground": {
                "enabled": lighting["ground_enabled"],
                "visible_below": checks["ground_visible_below"],
            },
            "display": {
                "mode": "ocio" if contract["color_management_enabled"] else "legacy",
                "config": "substance",
                "config_sha256": "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4",
                "view": painter["display_transform"],
                "color_lut": None,
                "post_effects": contract["post_effects"],
            },
            "cameras": [],
            "samples": int(iray["minSamples"]),
            "seed": 0,
        }

    ref = s["presets"]["ref_match"]
    assert ref["painter"]["display_transform"] == painter["display_transform"]
    return {
        "common": preset(
            "common",
            "painter (v2 common block)",
            s["version"],
            s["blender"]["environment"]["sha256"],
            painter["lighting"],
            contract["background_expected_srgb8"],
        ),
        "ref_match": preset(
            "ref_match",
            "presets.ref_match",
            ref["version"],
            ref["blender"]["environment"]["sha256"],
            ref["painter"]["lighting"],
            ref["painter"]["lighting"]["clear_color_srgb8"],
        ),
    }


def test_presets_equal_the_pipeline_standard(run: Run) -> None:
    """3.1: `common` and `ref_match` hold the standard's values."""
    expected = standard_presets()
    result = ok(run("from uzpainter.render import display as rd\nresult = rd.presets()"))
    assert {p["name"]: p for p in result} == expected


# ── 3.2 Missing environment ─────────────────────────────────────────────────────────────────────

MISSING = """
from uzpainter.render import display as rd
from uzpainter import display as d
create()
CHECKER = IMAGES + "/checker-16.png"
texture = resource.import_project_resource(CHECKER, resource.Usage.TEXTURE, "tex")
before = (project.revision(), rd.preset())
preset = rd.presets()[1]
missing = raises(rd.apply_preset, preset)
preset["environment"]["sha256"] = texture.identifier().version
not_environment = raises(rd.apply_preset, preset)
as_environment = raises(d.set_environment_resource, texture.identifier())
not_exr = raises(resource.import_project_resource, CHECKER, resource.Usage.ENVIRONMENT, "e")
after = (project.revision(), rd.preset())
result = {"missing": missing, "not_environment": not_environment, "as_environment": as_environment,
          "not_exr": not_exr, "unchanged": before == after,
          "environment": d.get_environment_resource()}
"""


def test_missing_environment_fails_without_substitute(run: Run) -> None:
    """3.2: a preset naming an environment the project does not store raises
    `ResourceNotFoundError`; nothing changes and no other environment is used."""
    result = ok(run(MISSING))
    assert result["missing"].startswith("ResourceNotFoundError: ")
    assert "77eeed8de580113581d50258e0ab3dd055aa29fa7d5ab614f2599ce036e0841d" in result["missing"]
    assert "no substitute" in result["missing"]
    assert result["not_environment"].startswith("ResourceNotFoundError: ")
    assert result["as_environment"].startswith("ResourceNotFoundError: ")
    assert (
        result["not_exr"]
        == "ValueError: cannot import checker-16.png as an environment: not an OpenEXR file"
    )
    assert result["unchanged"] and result["environment"] is None


# ── 3.3 Camera conversion ───────────────────────────────────────────────────────────────────────


def rotation(order: str, angles: list[float]) -> list[list[float]]:
    """The product of the axis rotations of `angles` (degrees) in `order`, e.g. "xyz" = Rx@Ry@Rz."""

    def axis(name: str, degrees: float) -> list[list[float]]:
        s, c = math.sin(math.radians(degrees)), math.cos(math.radians(degrees))
        matrices: dict[str, list[list[float]]] = {
            "x": [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]],
            "y": [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]],
            "z": [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]],
        }
        return matrices[name]

    def mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for name, degrees in zip(order, angles, strict=True):
        m = mul(m, axis(name, degrees))
    return m


BASIS = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]  # the contract's (x, y, z) -> (x, -z, y)


def camera(position: list[float], rot: list[float], **lens: Any) -> dict[str, Any]:
    return {
        "position": position,
        "rotation": rot,
        "projection_type": lens.get("projection_type", "Perspective"),
        "field_of_view": lens.get("field_of_view", 40.0),
        "focal_length": lens.get("focal_length", 50.0),
        "focus_distance": lens.get("focus_distance", 60.0),
        "aperture": 0.0,
        "orthographic_height": lens.get("orthographic_height", 10.0),
    }


# Painter cameras on the axes (decision 046's fixture camera is the first): yaw about Painter's
# up axis (Y) becomes yaw about Blender's up axis (Z) after the 90 degree tilt of the basis. The
# last column is the rotation the way back returns: the canonical Euler angles of the same matrix
# (Y in [-90, 90]), so the back view's yaw 180 returns as (180, 0, 180).
KNOWN = [
    (
        camera([0.0, 0.0, 60.0], [0.0, 0.0, 0.0]),
        [0.0, -60.0, 0.0],
        [90.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ),
    (
        camera([60.0, 0.0, 0.0], [0.0, 90.0, 0.0]),
        [60.0, 0.0, 0.0],
        [90.0, 0.0, 90.0],
        [0.0, 90.0, 0.0],
    ),
    (
        camera([0.0, 0.0, -60.0], [0.0, 180.0, 0.0]),
        [0.0, 60.0, 0.0],
        [90.0, 0.0, 180.0],
        [180.0, 0.0, 180.0],
    ),
    (
        camera([-60.0, 0.0, 0.0], [0.0, -90.0, 0.0]),
        [-60.0, 0.0, 0.0],
        [90.0, 0.0, -90.0],
        [0.0, -90.0, 0.0],
    ),
    (
        camera([0.0, 60.0, 0.0], [-90.0, 0.0, 0.0]),
        [0.0, 0.0, 60.0],
        [0.0, 0.0, 0.0],
        [-90.0, 0.0, 0.0],
    ),
]

GENERAL = camera(
    [1.5, -2.25, 30.125],
    [-17.5, 33.25, 8.75],
    field_of_view=27.5,
    focal_length=71.0,
    focus_distance=12.0,
    orthographic_height=3.5,
)
ORTHO_BLENDER = {
    "location": [0.0, -40.0, 1.0],
    "rotation_euler_degrees": [90.0, 0.0, 0.0],
    "type": "ORTHO",
    "angle_degrees": 40.0,
    "lens_mm": 50.0,
    "ortho_scale": 2.5,
    "focus_distance": 40.0,
    "aperture_radius": 0.0,
}

CAMERAS = """
from uzpainter import display as d
known = __KNOWN__
general = __GENERAL__
blender_ortho = __ORTHO__
to_blender = [d.camera_to_blender(c) for c, _, _, _ in known]
back = [d.camera_from_blender(b) for b in to_blender]
general_blender = d.camera_to_blender(general)
general_back = d.camera_from_blender(general_blender)
ortho_painter = d.camera_from_blender(blender_ortho)
ortho_again = d.camera_to_blender(ortho_painter)
create()
cam = d.Camera.get_default_camera()
unset = [raises(lambda: cam.position), raises(setattr, cam, "position", [0.0, 0.0, 1.0])]
d.set_camera(general)
cam.position = [1.0, 2.0, 3.0]
cam.rotation = [0.0, 45.0, 0.0]
cam.projection_type = d.CameraProjectionType.Orthographic
coupled = [raises(setattr, cam, "field_of_view", 30.0), raises(setattr, cam, "focal_length", 35.0)]
aperture = raises(setattr, cam, "aperture", 0.5)
out_of_range = raises(d.set_camera, dict(general, field_of_view=2.0))
result = {"to_blender": to_blender, "back": back, "general_blender": general_blender,
          "general_back": general_back, "ortho_painter": ortho_painter, "ortho_again": ortho_again,
          "unset": unset, "coupled": coupled, "aperture": aperture, "out_of_range": out_of_range,
          "stored": d.camera(), "projection": cam.projection_type.name, "fov": cam.field_of_view}
"""


def test_camera_conversion_round_trips_and_follows_the_contract(run: Run) -> None:
    """3.3: Painter's camera to Blender's convention and back, on known cameras (exact) and a
    general one (the rotation matrices agree with the contract; the round trip returns the same
    canonical Euler angles up to float64 rounding of the trigonometry)."""
    body = (
        CAMERAS.replace("__KNOWN__", repr(KNOWN))
        .replace("__GENERAL__", repr(GENERAL))
        .replace("__ORTHO__", repr(ORTHO_BLENDER))
    )
    result = ok(run(body))
    for (painter, location, euler, canonical), blender, back in zip(
        KNOWN, result["to_blender"], result["back"], strict=True
    ):
        assert blender["location"] == location and blender["rotation_euler_degrees"] == euler, (
            blender
        )
        assert blender["type"] == "PERSP" and blender["angle_degrees"] == painter["field_of_view"]
        assert blender["lens_mm"] == painter["focal_length"] and blender["aperture_radius"] == 0.0
        # Exact: every sine and cosine is 0 or +-1.
        assert back == dict(painter, rotation=canonical), back
    # The general camera: R_blender = B @ Rx @ Ry @ Rz (the contract) as Blender's Rz @ Ry @ Rx.
    blender = result["general_blender"]
    want = rotation("xyz", GENERAL["rotation"])
    want = [[sum(BASIS[i][k] * want[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    euler = blender["rotation_euler_degrees"]
    got = rotation("zyx", [euler[2], euler[1], euler[0]])
    assert max(abs(got[i][j] - want[i][j]) for i in range(3) for j in range(3)) < 1e-12
    x, y, z = GENERAL["position"]
    assert blender["location"] == [x, -z, y]
    back = result["general_back"]
    assert (
        max(abs(a - b) for a, b in zip(back["rotation"], GENERAL["rotation"], strict=True)) < 1e-9
    )
    assert {k: v for k, v in back.items() if k != "rotation"} == {
        k: v for k, v in GENERAL.items() if k != "rotation"
    }
    # Blender -> Painter -> Blender: unchanged (orthographic, scene off the origin).
    assert result["ortho_painter"]["projection_type"] == "Orthographic"
    assert result["ortho_painter"]["position"] == [0.0, 1.0, 40.0]
    assert result["ortho_again"] == ORTHO_BLENDER
    # Painter's Camera properties: no default camera, coupled lens setters, pinned aperture.
    assert all(u.startswith("NotYetSupported: ") and "decision 132" in u for u in result["unset"])
    assert all(c.startswith("NotYetSupported: ") and "sensor size" in c for c in result["coupled"])
    assert (
        result["aperture"].startswith("UnsupportedInUzPainter: ") and DECISION in result["aperture"]
    )
    assert result["out_of_range"] == "ValueError: field_of_view 2.0 is outside 3..179 degrees"
    stored = result["stored"]
    assert stored["position"] == [1.0, 2.0, 3.0] and stored["rotation"] == [0.0, 45.0, 0.0]
    assert result["projection"] == "Orthographic" and result["fov"] == GENERAL["field_of_view"]


# ── 3.4 Tone mapping and values outside the fixed pipeline ─────────────────────────────────────

OUTSIDE = """
from uzpainter.render import display as rd, shader
from uzpainter import display as d
create()
before = (project.revision(), rd.preset(), shader.parameters())
refused = {
    "exposure": raises(rd.set_exposure, 1.0),
    "opacity": raises(rd.set_opacity, 0.5),
    "blur": raises(rd.set_blur, 0.1),
    "rotation": raises(rd.set_rotation, 90.0),
    "shadows": raises(rd.set_shadows, True),
    "background": raises(rd.set_background, [141, 142, 148]),
    "lut": raises(d.set_color_lut_resource, resource.ResourceID("project", "sepia")),
    "lut_import": raises(resource.import_project_resource, IMAGES + "/checker-16.png",
                         resource.Usage.COLOR_LUT),
    "shader_value": raises(shader.set_parameters, {"double_sided": True}),
    "shader_unknown": raises(shader.set_parameters, {"emissive_intensity": 1.0}),
    "get_tone_mapping": raises(d.get_tone_mapping),
    "set_tone_mapping": raises(d.set_tone_mapping, d.ToneMappingFunction.ACES),
    "preset_exposure": raises(rd.apply_preset, dict(rd.presets()[0], environment=dict(
        rd.presets()[0]["environment"], sha256=None, exposure=1.0))),
}
accepted = [rd.set_exposure(0.0).status, rd.set_opacity(0).status, rd.set_rotation(0.0).status,
            rd.set_shadows(False).status, rd.set_background([89, 89, 89]).status,
            d.set_color_lut_resource(None).status,
            shader.set_parameters({"specular_ior": 1.5}).status,
            d.get_color_lut_resource()]
after = (project.revision(), rd.preset(), shader.parameters())
result = {"refused": refused, "accepted": accepted, "unchanged": before == after}
"""


def test_values_outside_the_fixed_pipeline_are_refused_and_change_nothing(run: Run) -> None:
    """3.4: a display, colour-LUT, tone-mapping or shader value outside the fixed pipeline raises
    the unsupported-value error naming the setting, the accepted values and decision 038, and
    leaves the state unchanged; the pipeline's own values are accepted (no change)."""
    result = ok(run(OUTSIDE))
    refused = result["refused"]
    for key, error in refused.items():
        assert error is not None and error.startswith("UnsupportedInUzPainter: "), (key, error)
        assert "decision 038" in error, (key, error)
    assert refused["exposure"].endswith(
        "environment exposure 1.0 is outside the fixed render pipeline; "
        "accepted: 0.0 (decision 038)"
    )
    assert "accepted: [89,89,89]" in refused["background"]
    assert "accepted: None (no colour LUT)" in refused["lut"]
    assert "accepted: false (open-pbr default)" in refused["shader_value"]
    assert (
        "Legacy" in refused["get_tone_mapping"] and "accepted: none" in refused["set_tone_mapping"]
    )
    assert "environment.exposure 1.0" in refused["preset_exposure"]
    assert result["accepted"] == ["no_op"] * 7 + [None]
    assert result["unchanged"]


OCIO = """
import hashlib

OCIO_CONFIG = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

manifest = {
    "schema": "uzpainter/manifest/1",
    "versions": {"format_version": "1.0.0", "app_version": "0.0.0",
                 "evaluator_profile": "painter-12.1-layerq-linear",
                 "compat_profile": "painter-12.1-api-0.3.7",
                 "painter_reference": {"build": "", "recorded_from": ""}},
    "next_id": 1,
    "settings": {"normal_map_format": "OpenGL", "tangent_space": "PerVertex", "workflow": "Default",
                 "default_resolution": {"width": 1024, "height": 1024}, "mesh_unit_scale": 1.0,
                 "color_management": {"mode": "ocio", "working_space": "ACEScg", "io_rules": [],
                                      "config_hash": OCIO_CONFIG},
                 "import_cameras": False, "auto_unwrap": False},
    "mesh": None, "texture_sets": [], "resources": {},
    "display": {"environment": {"resource": None, "rotation": 0.0, "exposure": 0.0, "opacity": 0.0,
                                "blur": 0.0},
                "color_lut": None, "tone_mapping": "Linear",
                "shader": {"id": "", "hash": "", "parameters": {}},
                "cameras": [], "background": {}, "shadows": False, "post_effects": {}},
    "export_defaults": {}, "metadata": {},
}
bundle = os.path.join(WORK, "ocio")
os.makedirs(bundle)
text = canonical(manifest).encode("utf-8")
with open(os.path.join(bundle, "manifest.json"), "wb") as f:
    f.write(text)
with open(os.path.join(bundle, "bundle.json"), "w", encoding="utf-8") as f:
    json.dump({"schema": "uzpainter/bundle/1",
               "project_uuid": "00000000-0000-4000-8000-000000000132",
               "revision": 1, "manifest_sha256": hashlib.sha256(text).hexdigest(), "resources": [],
               "planes": []}, f)
project.open(bundle)
from uzpainter import display as d
before = project.revision()
result = {"mode": cm.get_color_management()["mode"], "get": raises(d.get_tone_mapping),
          "set": raises(d.set_tone_mapping, d.ToneMappingFunction.Linear),
          "unchanged": project.revision() == before}
"""


def test_tone_mapping_raises_runtime_error_on_a_colour_managed_project(run: Run) -> None:
    """3.4: on an OCIO project `get_tone_mapping` and `set_tone_mapping` raise `RuntimeError`, as
    Painter documents. The project is a bundle whose manifest declares OCIO (decision 132); the
    creation path of decision 207 needs Painter's installed config, which this test does not."""
    result = ok(run(OCIO))
    assert result["mode"] == "ocio" and result["unchanged"]
    for key in ("get", "set"):
        assert result[key].startswith("RuntimeError: The project is color managed"), result[key]


FACADE = """
from substance_painter import display
create()
env = resource.import_project_resource(SHIPPED, resource.Usage.ENVIRONMENT, "studio")
none_before = display.get_environment_resource()
display.set_environment_resource(env.identifier())
got = display.get_environment_resource()
result = {
    "none_before": none_before,
    "url": got.url(), "same": got == env.identifier(),
    "type": raises(display.set_environment_resource, "studio"),
    "lut": display.get_color_lut_resource(),
    "lut_none": display.set_color_lut_resource(None),
    "lut_set": raises(display.set_color_lut_resource, resource.ResourceID.from_project("sepia")),
    "tone": raises(display.get_tone_mapping),
    "enums": [m.name for m in (display.ToneMappingFunction.Linear, display.ToneMappingFunction.ACES,
              display.CameraProjectionType.Perspective, display.CameraProjectionType.Orthographic)],
    "camera": raises(lambda: display.Camera.get_default_camera().position),
}
"""


def test_facade_display_symbols(facade: Run) -> None:
    """3.4 and decision 042: the documented `substance_painter.display` symbols over the native
    calls, with Painter-shaped resource ids."""
    result = ok(facade(with_shipped(FACADE)))
    assert result["none_before"] is None and result["same"]
    assert result["url"].startswith("resource://project0/studio?version=") and result[
        "url"
    ].endswith(".image")
    assert result["type"] == "TypeError: new_env_map must be a resource.ResourceID"
    assert result["lut"] is None and result["lut_none"] is None
    assert (
        result["lut_set"].startswith("UnsupportedInUzPainter: ") and DECISION in result["lut_set"]
    )
    assert result["tone"].startswith("UnsupportedInUzPainter: ")
    assert result["enums"] == ["Linear", "ACES", "Perspective", "Orthographic"]
    assert result["camera"].startswith("NotYetSupported: ")


# ── 3.5 Shipped environments ────────────────────────────────────────────────────────────────────


def exr_size(data: bytes) -> tuple[int, int]:
    """The data window of a single-part OpenEXR file (its header attributes)."""
    assert data[:4] == b"\x76\x2f\x31\x01", "not an OpenEXR file"
    at = 8
    while data[at] != 0:
        name_end = data.index(b"\0", at)
        type_end = data.index(b"\0", name_end + 1)
        (size,) = struct.unpack_from("<i", data, type_end + 1)
        value = type_end + 5
        if data[at:name_end] == b"dataWindow":
            x0, y0, x1, y1 = struct.unpack_from("<4i", data, value)
            return x1 - x0 + 1, y1 - y0 + 1
        at = value + size
    raise AssertionError("no dataWindow")


def test_shipped_environments_have_valid_provenance() -> None:
    """3.5: every shipped environment has `<name>.provenance.json`, valid under the schema, whose
    hash, size and dimensions are the file's; nothing else is in the folder."""
    validator = Draft202012Validator(json.loads(PROVENANCE_SCHEMA.read_text(encoding="utf-8")))
    images = sorted(ENVIRONMENTS.glob("*.exr"))
    assert images, "no shipped environment"
    expected = {p.name for p in images} | {p.stem + ".provenance.json" for p in images}
    assert {p.name for p in ENVIRONMENTS.iterdir()} == expected
    for image in images:
        record = json.loads(
            (ENVIRONMENTS / (image.stem + ".provenance.json")).read_text(encoding="utf-8")
        )
        errors = [e.message for e in validator.iter_errors(record)]
        assert errors == [], (image.name, errors)
        data = image.read_bytes()
        assert record["asset"] == image.stem and record["file"] == image.name
        assert record["sha256"] == hashlib.sha256(data).hexdigest() and record["bytes"] == len(data)
        assert (
            hashlib.md5(data).hexdigest() == record["source"]["md5"]
        )  # the source publishes MD5 checksums
        width, height = exr_size(data)
        assert [width, height] == [
            record["image"]["width"],
            record["image"]["height"],
        ] and width == 2 * height
