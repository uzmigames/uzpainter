"""Render feasibility prototype (task `phase0.8_render-reference-fits` items 2.1-2.3, 3.1 and
3.3; decision 050): sampler, environment sampling, BSDF energy, transport, display encoding.

These tests use synthetic scenes only (no Painter output, no environment file)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from tools.parity.render_fits import bsdf, display, environment, render, sampler, scene
from tools.parity.render_fits.fixtures import srgb8, srgb_to_linear, unorm8

CAMERA = scene.Camera((0.0, 0.0, 60.0), 40.0, 1200, 1200)
CENTRE = [600 * 1200 + 600, 520 * 1200 + 610, 680 * 1200 + 560, 600 * 1200 + 700]


def write_sphere(path: Path, radius: float = 10.0, rings: int = 16, segments: int = 32) -> Path:
    lines = []
    for i in range(rings + 1):
        theta = math.pi * i / rings
        for j in range(segments + 1):
            phi = 2 * math.pi * j / segments
            x = radius * math.sin(theta) * math.cos(phi)
            y = radius * math.cos(theta)
            z = radius * math.sin(theta) * math.sin(phi)
            lines.append(f"v {x} {y} {z}")
            lines.append(f"vt {j / segments} {1 - i / rings}")
            lines.append(f"vn {x / radius} {y / radius} {z / radius}")
    for i in range(rings):
        for j in range(segments):
            a = i * (segments + 1) + j + 1
            b, c, d = a + segments + 1, a + segments + 2, a + 1
            for tri in ((a, b, c), (a, c, d)):
                lines.append("f " + " ".join(f"{k}/{k}/{k}" for k in tri))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_bowl(path: Path, radius: float = 12.0, rings: int = 6, segments: int = 16) -> Path:
    """The back half of a sphere seen from the camera: a concave bowl opening toward +Z."""
    lines = []
    for i in range(rings + 1):
        theta = math.pi / 2 * i / rings  # 0 at the bowl's bottom (-Z) to the rim
        for j in range(segments + 1):
            phi = 2 * math.pi * j / segments
            x = radius * math.sin(theta) * math.cos(phi)
            y = radius * math.sin(theta) * math.sin(phi)
            z = -radius * math.cos(theta)
            lines.append(f"v {x} {y} {z}")
            lines.append(f"vt {j / segments} {i / rings}")
            lines.append(f"vn {-x / radius} {-y / radius} {-z / radius}")
    for i in range(rings):
        for j in range(segments):
            a = i * (segments + 1) + j + 1
            b, c, d = a + segments + 1, a + segments + 2, a + 1
            for tri in ((a, c, b), (a, d, c)):
                lines.append("f " + " ".join(f"{k}/{k}/{k}" for k in tri))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def furnace(
    mesh: scene.Mesh,
    base: float,
    metal: float,
    rough: float,
    variant: bsdf.Variant,
    spp: int,
    seed: int,
    max_depth: int = 8,
) -> np.ndarray:
    fixture = render.Fixture(
        mesh, CAMERA, environment.constant(1.0), (base, base, base), metal, rough, (0.0, 0.0, 0.0)
    )
    settings = render.Settings(variant=variant, max_depth=max_depth, rr_depth=3)
    return render.render(fixture, np.asarray(CENTRE, dtype=np.int64), spp, seed, settings)


# --- sampler (item 2.1) ---------------------------------------------------------------------


def test_byte_tables_reproduce_the_bitwise_sobol_product() -> None:
    index = np.arange(0, 1 << 16, 7, dtype=np.uint32) * np.uint32(40503)
    for dim in range(4):
        expected = np.zeros_like(index)
        for bit in range(32):
            mask = ((index >> np.uint32(bit)) & np.uint32(1)).astype(bool)
            expected[mask] ^= sampler.DIRECTIONS[dim, bit]
        assert np.array_equal(sampler.sobol(index, dim), expected)


def test_scrambled_pairs_stay_a_0_2_sequence() -> None:
    seeds = sampler.pixel_seeds(np.arange(4, dtype=np.int64), 7)
    points = np.stack([sampler.samples(i, seeds, 3, 2) for i in range(256)])
    for pixel in range(4):
        for kx in range(9):
            cells = np.floor(points[:, pixel, 0] * 2**kx) * 2 ** (8 - kx) + np.floor(
                points[:, pixel, 1] * 2 ** (8 - kx)
            )
            assert len(np.unique(cells)) == 256


def test_samples_depend_only_on_seed_pixel_index_and_set() -> None:
    seeds = sampler.pixel_seeds(np.array([5, 9], dtype=np.int64), 11)
    first = sampler.samples(17, seeds, 2, 2)
    assert np.array_equal(first, sampler.samples(17, seeds, 2, 2))
    assert not np.array_equal(first, sampler.samples(17, seeds, 3, 2))
    other = sampler.pixel_seeds(np.array([5, 9], dtype=np.int64), 12)
    assert not np.array_equal(first, sampler.samples(17, other, 2, 2))


# --- environment (items 2.1, 2.3) -------------------------------------------------------------


def test_environment_mapping_round_trips_and_rotates() -> None:
    rng = np.random.default_rng(3)
    texels = rng.random((16, 32, 3)) + 0.1
    env = environment.Environment(texels, rotation=37.0)
    u = rng.random(100)
    v = rng.random(100) * 0.98 + 0.01
    back_u, back_v = env.uv(env.direction(u, v))
    assert np.allclose(np.mod(back_u - u + 0.5, 1.0) - 0.5, 0.0, atol=1e-12)
    assert np.allclose(back_v, v, atol=1e-12)
    up = env.direction(np.array([0.3]), np.array([0.0]))
    assert np.allclose(up, [[0.0, 1.0, 0.0]], atol=1e-12)


def test_environment_sampling_density_matches_its_samples() -> None:
    rng = np.random.default_rng(5)
    texels = np.ones((32, 64, 3)) * 0.2
    texels[5:8, 10:14] = 50.0
    env = environment.Environment(texels)
    directions, pdf = env.sample(rng.random((200_000, 2)))
    assert np.allclose(env.pdf(directions), pdf, rtol=1e-6)
    # E[1/pdf] over the sampled directions is the sphere's solid angle.
    assert np.mean(1.0 / pdf) == pytest.approx(4 * math.pi, rel=0.02)
    # The bright patch receives the share of samples its weight asks for.
    lum = texels @ environment.LUMINANCE
    weight = lum * np.sin((np.arange(32) + 0.5) / 32 * math.pi)[:, None]
    u, v = env.uv(directions)
    in_patch = (v * 32 >= 5) & (v * 32 < 8) & (u * 64 >= 10) & (u * 64 < 14)
    assert in_patch.mean() == pytest.approx(weight[5:8, 10:14].sum() / weight.sum(), rel=0.02)


# --- BSDF (item 2.2) ------------------------------------------------------------------------------


@pytest.mark.parametrize("multiscatter", ["turquin", "kulla_conty", "tint"])
def test_compensated_white_metal_conserves_energy(multiscatter: str) -> None:
    rng = np.random.default_rng(1)
    count = 400_000
    variant = bsdf.Variant(multiscatter=multiscatter)
    for mu in (0.9, 0.4):
        wo = np.tile([math.sqrt(1 - mu * mu), 0.0, mu], (count, 1))
        u = rng.random((count, 2))
        z = u[:, 0]
        r = np.sqrt(1 - z * z)
        wi = np.stack([r * np.cos(2 * math.pi * u[:, 1]), r * np.sin(2 * math.pi * u[:, 1]), z], 1)
        material = bsdf.Material(np.ones((count, 3)), np.ones(count), np.full(count, 0.8))
        f = bsdf.evaluate(material, wo, wi, variant)[:, 0]
        assert (f * z).mean() * 2 * math.pi == pytest.approx(1.0, abs=0.01)


def test_importance_sampling_matches_uniform_integration() -> None:
    rng = np.random.default_rng(2)
    count = 400_000
    variant = bsdf.Variant(layering="albedo_oi_raw", dielectric_multiscatter="tint_f0")
    material = bsdf.Material(
        np.tile([0.6, 0.03, 0.01], (count, 1)), np.full(count, 0.0), np.full(count, 0.5)
    )
    mu = 0.6
    wo = np.tile([math.sqrt(1 - mu * mu), 0.0, mu], (count, 1))
    wi = bsdf.sample(material, wo, rng.random((count, 3)), variant)
    pdf = bsdf.pdf(material, wo, wi, variant)
    f = bsdf.evaluate(material, wo, wi, variant)
    safe = np.where(pdf > 0, pdf, 1.0)[:, None]
    weight = np.where((pdf > 0)[:, None], f * np.clip(wi[:, 2:3], 0, None) / safe, 0.0)
    u = rng.random((count, 2))
    z = u[:, 0]
    r = np.sqrt(1 - z * z)
    uni = np.stack([r * np.cos(2 * math.pi * u[:, 1]), r * np.sin(2 * math.pi * u[:, 1]), z], 1)
    reference = (bsdf.evaluate(material, wo, uni, variant) * z[:, None]).mean(0) * 2 * math.pi
    assert np.allclose(weight.mean(0), reference, rtol=0.02, atol=2e-4)


# --- transport: white furnace (item 3.1) -----------------------------------------------------


def test_white_furnace_convex_sphere_returns_the_environment(tmp_path: Path) -> None:
    """A white, energy-conserving material under a uniform unit environment reflects 1."""
    mesh = scene.load_obj(write_sphere(tmp_path / "sphere.obj"))
    assert mesh.convex
    runs = []
    for seed in (1, 2, 3, 4):
        metal = furnace(mesh, 1.0, 1.0, 0.6, bsdf.Variant(multiscatter="tint"), 256, seed)
        dielectric = furnace(
            mesh,
            1.0,
            0.0,
            0.6,
            bsdf.Variant(layering="albedo_o", dielectric_multiscatter="kulla_conty"),
            256,
            seed,
        )
        runs.append(np.concatenate([metal[:, 0], dielectric[:, 0]]))
    values = np.array(runs)
    error = values.std(axis=0, ddof=1) / math.sqrt(len(runs))
    assert np.all(np.abs(values.mean(axis=0) - 1.0) < 4 * error + 0.004)


def test_multiple_bounces_close_the_furnace_in_a_concave_bowl(tmp_path: Path) -> None:
    """Inside a concave bowl a white Lambert-like material needs its interreflections: one
    vertex loses energy, the path loop with Russian roulette restores it."""
    mesh = scene.load_obj(write_bowl(tmp_path / "bowl.obj"))
    # Its facets' empty side is the outside: rays toward the inside are traced.
    assert set(np.unique(mesh.empty_side).tolist()) <= {1, -1}
    variant = bsdf.Variant(layering="albedo_o", dielectric_multiscatter="kulla_conty")
    deep = np.array(
        [furnace(mesh, 1.0, 0.0, 1.0, variant, 64, s, max_depth=24)[:, 0] for s in (1, 2, 3)]
    )
    single = furnace(mesh, 1.0, 0.0, 1.0, variant, 64, 1, max_depth=1)[:, 0]
    assert np.all(single < 0.9)
    assert np.abs(deep.mean() - 1.0) < 0.05


# --- repeatability (item 3.3) ------------------------------------------------------------------


def test_same_seed_and_samples_give_identical_bytes(tmp_path: Path) -> None:
    mesh = scene.load_obj(write_sphere(tmp_path / "sphere.obj"))
    first = furnace(mesh, 0.5, 0.0, 0.5, bsdf.Variant(), 16, 9)
    second = furnace(mesh, 0.5, 0.0, 0.5, bsdf.Variant(), 16, 9)
    assert first.tobytes() == second.tobytes()
    assert furnace(mesh, 0.5, 0.0, 0.5, bsdf.Variant(), 16, 10).tobytes() != first.tobytes()


def test_a_longer_render_nests_the_shorter_one(tmp_path: Path) -> None:
    mesh = scene.load_obj(write_sphere(tmp_path / "sphere.obj"))
    fixture = render.Fixture(
        mesh, CAMERA, environment.constant(1.0), (0.4, 0.4, 0.4), 0.0, 0.5, (0.0, 0.0, 0.0)
    )
    pixels = np.asarray(CENTRE, dtype=np.int64)
    settings = render.Settings()
    short = render.render(fixture, pixels, 8, 3, settings)
    rest = render.render(fixture, pixels, 8, 3, settings, first_sample=8)
    long = render.render(fixture, pixels, 16, 3, settings)
    assert np.allclose((short + rest) / 2, long, rtol=1e-12, atol=1e-15)


# --- display and channels (item 2.3) -----------------------------------------------------------


def test_display_codes_lie_on_the_binary16_lattice() -> None:
    rng = np.random.default_rng(4)
    codes = display.to_codes(rng.random((1000, 3)) * 1.2)
    lattice = display.lattice()
    assert np.isin(codes.astype(np.int64), lattice).all()
    stats = display.lattice_statistics([codes, np.minimum(codes + 1.0, 65535.0)])
    assert stats["max_distance_codes"] <= 1
    assert stats["samples"] == 6000


def test_channel_quantisation_rules() -> None:
    assert unorm8(0.5) == 127 / 255
    assert unorm8(0.1) == 25 / 255
    assert unorm8(0.9) == 229 / 255
    assert unorm8(1.0) == 1.0
    assert srgb8(0.5) == pytest.approx(srgb_to_linear(128 / 255))
    assert srgb8(0.9) == pytest.approx(srgb_to_linear(230 / 255))
