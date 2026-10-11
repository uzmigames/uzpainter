"""The admitted Iray reference fixtures as prototype scenes (decision 046; task item 2.3).

Each golden of `tools/parity/render_procedure/references.FIXTURES` becomes a `render.Fixture`:

- Mesh: the committed UzmiGames OBJ; camera on +Z at 60 units, field of view 40 degrees,
  1200 x 1200 (decision 046).
- Environment: `v2` reads Studio White Soft from Painter's installed starter assets and
  `ref_match` the Assets3D HDRI; both are checked against the SHA-256 the pipeline names before
  use and are never copied (07 §7). Rotation is the preset's per-view value.
- Clear colour: `v2` 89,89,89 and `ref_match` 141,142,148 (sRGB8), decoded to linear.
- Material channels as Painter stores them (Tier 0 semantics, `colour-transfer.json` and
  `quantisation-profile.json`): BaseColor is an sRGB8 channel (code = the sRGB value times 255
  rounded half up, the tie rule fitted on the mirror sphere), BaseMetalness and
  SpecularRoughness are L8 channels written with the UNORM rule (truncate to 12 fractional
  bits, nearest, ties down). The decoded values feed the BSDF.
- The qualification sphere (`QUALIFICATION`, decision 068): the template-default material read
  back in an OCIO project (`phase0/template-default-material/ocio-sphere`). Its BaseColor is not
  on the sRGB8 lattice (the empty stack exports 59396 of 65535 at 16 bits, the sRGB encoding of
  linear 0.8), so the scene takes the export's linear value (`QUALIFICATION_BASE`); metalness
  is L8 code 0 and roughness L8 code 76. Normal (127/255, 127/255, 1) and Height 0 are the same
  empty channels every other fixture has: the interpolated normal is kept, as for them.
- Perturbations: the Normal bitmap is decoded as a tangent-space normal (2c/255 - 1); the
  Height bitmap is stored as 2t - 1 (`bitmap-height-signed`) and applied as bump with a fitted
  strength. Emission and opacity are ignored, as the default shader does (emission luminance 0,
  alpha test and blending off; decision 042).
"""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tools.parity.recorder.capture import decode_png
from tools.parity.recorder.iray_probe import REF_MATCH_HDRI_SHA256
from tools.parity.render_fits.environment import Environment, read_exr
from tools.parity.render_fits.render import Fixture, Texture
from tools.parity.render_fits.scene import Camera, Mesh, load_obj
from tools.parity.render_procedure import references as refs
from tools.parity.schemas import REPO_ROOT

STUDIO_WHITE_SOFT_SHA256 = "c2bb3294099b130bfa0f4bdae677efac544ba97ad3afd579a2563333e748c2c3"
PAINTER_DIR = Path(r"C:\Program Files\Adobe\Adobe Substance 3D Painter")
STUDIO_WHITE_SOFT_PATH = "resources/starter_assets/environments/Studio/Studio White Soft.exr"
ASSETS3D_DIR = Path(r"E:\UzmiGames\Assets3D")
REF_MATCH_PATH = "Pipeline/render/HDRI/" + refs.REF_MATCH_HDRI_NAME
V2_CLEAR = (89, 89, 89)
REF_MATCH_CLEAR = (141, 142, 148)
SIZE = 1200
MESH_PATHS = {
    "sphere": REPO_ROOT / refs.SPHERE_PATH,
    "plane": refs.FIXTURE_DIR / "plane.obj",
    "bevelled-cube": refs.FIXTURE_DIR / "bevelled-cube.obj",
    **{
        f"{mesh}-yaw-{label}": refs.FIXTURE_DIR / f"{mesh}-yaw-{label}.obj"
        for mesh in ("plane", "bevelled-cube")
        for _, label in refs.TURNS
    },
}


class FixtureError(Exception):
    """An environment file is missing or is not the one the pipeline names."""


def srgb_to_linear(c: float) -> float:
    """IEC 61966-2-1 decoding."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb8(value: float) -> float:
    """The sRGB8 code of an sRGB value (half up), decoded to linear."""
    code = math.floor(value * 255.0 + 0.5)
    return srgb_to_linear(code / 255.0)


def unorm8(value: float) -> float:
    """The L8 UNORM write rule: truncate to 12 fractional bits, nearest code, ties down."""
    j = math.floor(float(np.float32(value)) * 4096.0)
    code = (j * 255 + 2047) // 4096
    return code / 255.0


# Template-default material of an OCIO project, read back (decision 068): BaseColor 59396 of
# 65535 at PNG 16 (sRGB-encoded), BaseMetalness L8 code 0, SpecularRoughness L8 code 76.
QUALIFICATION_EXPORT_CODE = 59396
QUALIFICATION = refs.Fixture(
    "qualification-sphere",
    "sphere",
    (QUALIFICATION_EXPORT_CODE / 65535.0,) * 3,
    0.0,
    76 / 255.0,
    role="template default material (qualification job)",
)


def qualification_base() -> tuple[float, float, float]:
    """The read-back BaseColor as a linear colour (not on the sRGB8 lattice)."""
    value = srgb_to_linear(QUALIFICATION_EXPORT_CODE / 65535.0)
    return value, value, value


def environment_path(preset: str) -> tuple[Path, str]:
    if preset == "v2":
        root = Path(os.environ.get("UZP_PAINTER_DIR", str(PAINTER_DIR)))
        return root / STUDIO_WHITE_SOFT_PATH, STUDIO_WHITE_SOFT_SHA256
    root = Path(os.environ.get("UZP_ASSETS3D_DIR", str(ASSETS3D_DIR)))
    return root / REF_MATCH_PATH, REF_MATCH_HDRI_SHA256


_ENVIRONMENTS: dict[str, Environment] = {}
_MESHES: dict[str, Mesh] = {}


def environment(preset: str, rotation: float) -> Environment:
    if preset not in _ENVIRONMENTS:
        path, digest = environment_path(preset)
        if not path.is_file():
            raise FixtureError(f"{preset}: environment file {path} is missing")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise FixtureError(f"{preset}: {path} hashes {actual}, the pipeline names {digest}")
        _ENVIRONMENTS[preset] = Environment(read_exr(path))
    return replace(_ENVIRONMENTS[preset], rotation=rotation)


def mesh(name: str) -> Mesh:
    if name not in _MESHES:
        _MESHES[name] = load_obj(MESH_PATHS[name])
    return _MESHES[name]


def bitmap(name: str) -> npt.NDArray[np.float64]:
    """A committed fixture bitmap as UNORM values (H, W, C); IHDR byte 24 is the bit depth."""
    path = refs.FIXTURE_DIR / name
    image = decode_png(path)
    pixels = np.asarray(image.pixels, dtype=np.float64).reshape(image.height, image.width, -1)
    bit_depth = path.read_bytes()[24]
    result: npt.NDArray[np.float64] = pixels / float((1 << bit_depth) - 1)
    return result


def clear_colour(preset: str) -> tuple[float, float, float]:
    codes = V2_CLEAR if preset == "v2" else REF_MATCH_CLEAR
    r, g, b = (srgb_to_linear(c / 255.0) for c in codes)
    return r, g, b


def scene_fixture(fixture: refs.Fixture, bump_strength: float = 0.0) -> Fixture:
    """The prototype scene of one reference golden."""
    r, g, b = (srgb8(c) for c in fixture.base_srgb)
    result = Fixture(
        mesh=mesh(fixture.mesh),
        camera=Camera((0.0, 0.0, refs.CAMERA_DISTANCE), refs.FIELD_OF_VIEW, SIZE, SIZE),
        environment=environment(fixture.preset, fixture.rotation),
        base_color=(r, g, b),
        metalness=unorm8(fixture.metalness),
        roughness=unorm8(fixture.roughness),
        background=clear_colour(fixture.preset),
    )
    perturbation = fixture.perturbation
    if perturbation is not None and perturbation.channel == "Normal" and perturbation.bitmap:
        result.normal_map = Texture(bitmap(perturbation.bitmap) * 2.0 - 1.0)
    if perturbation is not None and perturbation.channel == "Height" and perturbation.bitmap:
        result.height_map = Texture(bitmap(perturbation.bitmap)[:, :, :1] * 2.0 - 1.0)
        result.bump_strength = bump_strength
    return result


def by_name(name: str) -> refs.Fixture:
    for fixture in (*refs.FIXTURES, QUALIFICATION):
        if fixture.name == name:
            return fixture
    raise KeyError(name)
