"""The tangent-frame prototype against the analytic field (task 3.1) and the direction check on
its maps (task 3.3)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from tools.parity.normal_convention.fixtures import plane_tangent_normal
from tools.parity.normal_convention.prototype import FORMATS, MODES, TRANSFORMS, PrototypeBake
from tools.parity.normal_convention.study import direction, domains, pair_fields


def encode(values: npt.NDArray[np.float64]) -> npt.NDArray[np.int64]:
    """The prototype's encoding: nearest UNORM16 code of x / 2 + 1 / 2."""
    return np.floor(np.clip(values * 0.5 + 0.5, 0, 1) * 65535 + 0.5).astype(np.int64)


def test_prototype_reproduces_the_analytic_field(prototype_bakes: dict[str, PrototypeBake]) -> None:
    """Triangles, ray hits and the world-space normal equal the analytic field on the domain;
    on the plane-dome pair (constant frame) every tangent-space map equals the analytic tangent
    normal, code for code."""
    fields = pair_fields()
    for pair, bake in prototype_bakes.items():
        field = fields[pair]
        domain = field.domain
        assert np.array_equal(bake.low_face[domain], field.low_face[domain]), pair
        assert np.array_equal(bake.high_face[domain], field.high_face[domain]), pair
        hit = domains(field)["hit"]
        assert np.array_equal(bake.maps["world"][hit], encode(field.world_normal)[hit]), pair
        assert bake.summary["covered_texels"] == int((field.low_face >= 0).sum())
    plane = fields["plane-dome"]
    hit = domains(plane)["hit"]
    expected = encode(plane_tangent_normal(plane.world_normal))
    for mode in MODES:
        for transform in TRANSFORMS:
            codes = prototype_bakes["plane-dome"].maps[f"{mode}-{transform}-opengl"]
            assert np.array_equal(codes[hit], expected[hit]), (mode, transform)


def test_inverse_transform_round_trips(prototype_bakes: dict[str, PrototypeBake]) -> None:
    """The MikkTSpace sampler transform is the exact inverse of the shading transform in both
    frame modes: the decoded normal is the high-poly normal up to 16-bit quantisation."""
    for pair, bake in prototype_bakes.items():
        errors = bake.summary["round_trip_degrees"]
        for mode in MODES:
            assert errors[f"{mode}-inverse"]["exact"] < 1e-3, pair
            assert errors[f"{mode}-inverse"]["coded"] < 1e-2, pair


def test_frame_modes_differ_on_the_hemisphere(prototype_bakes: dict[str, PrototypeBake]) -> None:
    """The fixture discriminates: PerVertex and PerFragment maps differ on the hemisphere."""
    hit = domains(pair_fields()["hemisphere"])["hit"]
    maps = prototype_bakes["hemisphere"].maps
    for transform in TRANSFORMS:
        delta = np.abs(
            maps[f"PerVertex-{transform}-opengl"] - maps[f"PerFragment-{transform}-opengl"]
        )[hit]
        assert delta.mean() > 10, transform


def test_green_follows_plus_v_and_the_directx_conversion_flips_it(
    prototype_bakes: dict[str, PrototypeBake],
) -> None:
    """Task 3.3: texels leaning towards +v read green above 1/2 in the OpenGL map; the DirectX
    conversion flips green only (red, the control, is unchanged)."""
    plane = pair_fields()["plane-dome"]
    hit = domains(plane)["hit"]
    tangent = plane_tangent_normal(plane.world_normal)
    maps = prototype_bakes["plane-dome"].maps
    opengl = direction(maps["PerFragment-inverse-opengl"], tangent, hit)
    directx = direction(maps["PerFragment-inverse-directx"], tangent, hit)
    assert opengl["green_plus_v"] > 1000 and opengl["green_minus_v"] < -1000
    assert directx["green_plus_v"] < -1000 and directx["green_minus_v"] > 1000
    for key in ("red_plus_u", "red_minus_u"):
        assert opengl[key] == directx[key]
    assert opengl["red_plus_u"] > 1000 and opengl["red_minus_u"] < -1000
    for pair, bake in prototype_bakes.items():
        for mode in MODES:
            for transform in TRANSFORMS:
                gl, dx = (bake.maps[f"{mode}-{transform}-{f}"] for f in FORMATS)
                empty = (bake.low_face >= 0) & (bake.high_face < 0)
                assert np.array_equal(dx[..., 1][~empty], 65535 - gl[..., 1][~empty]), pair
                assert np.all(dx[empty] == 0) and np.all(gl[empty] == 0), pair
                assert np.array_equal(dx[..., [0, 2]], gl[..., [0, 2]]), pair
