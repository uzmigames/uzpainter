"""Path-tracing integrator of the feasibility prototype (07 §3.2; P-KAJIYA, P-VEACH, P-PBRT).

Unidirectional path tracing from the camera. At every surface vertex: next-event estimation
toward the environment (sampled by its piecewise-constant importance distribution) and a BSDF
sample, combined by multiple importance sampling with the power heuristic (Veach 1997 §9.2,
P-VEACH; PBRT 4th ed. §13.4); Russian roulette after `rr_depth` bounces with survival
probability min(1, max throughput) (PBRT 4th ed. §13.1.4); at most `max_depth` surface
vertices. Samples come from Owen-scrambled Sobol (`sampler.py`) under a fixed seed, one 2D
dimension set per decision of a bounce. Pixel positions are drawn from the pixel filter
(filter importance sampling, PBRT 4th ed. §8.8.3): a box of one pixel or a truncated Gaussian.
Each pixel sums its samples in sample-index order in float64, without atomics, so a run is
repeatable for a given seed and sample count.

Below-facet directions: a smooth or perturbed shading normal can choose a direction under the
facet's plane. `below_facet` = "absorb" gives such a direction no contribution (the geometric
normal test); "trace" follows it as an ordinary ray (for a closed convex mesh it then meets the
mesh's inside, which receives no light; behind an open plane it reaches the environment).

The camera background is the preset's clear colour (environment opacity 0, decision 038): a
camera ray that misses the mesh returns the clear colour, linear, and is averaged with the
pixel's other samples.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from tools.parity.render_fits import bsdf, sampler
from tools.parity.render_fits.environment import Environment
from tools.parity.render_fits.scene import (
    Camera,
    Hits,
    Mesh,
    Surface,
    intersect,
    pixel_candidates,
    surface,
)

F64 = npt.NDArray[np.float64]
I64 = npt.NDArray[np.int64]
RAY_OFFSET = 1e-4


@dataclass(frozen=True)
class PixelFilter:
    kind: str = "box"  # "box" (one pixel) or "gaussian"
    sigma: float = 0.5  # pixels, gaussian only
    radius: float = 1.5  # pixels, gaussian truncation

    def support(self) -> float:
        return 0.5 if self.kind == "box" else self.radius

    def offsets(self, u: F64) -> F64:
        """Offsets from the pixel centre for uniform pairs (N, 2)."""
        if self.kind == "box":
            result: F64 = u - 0.5
            return result
        # Separable truncated Gaussian by inversion of its CDF (bisection, fixed 40 steps).
        bound = math.erf(self.radius / (self.sigma * math.sqrt(2.0)))
        target = (2.0 * u - 1.0) * bound
        low = np.full_like(u, -self.radius)
        high = np.full_like(u, self.radius)
        for _ in range(40):
            mid = 0.5 * (low + high)
            value = np.vectorize(math.erf)(mid / (self.sigma * math.sqrt(2.0)))
            below = value < target
            low = np.where(below, mid, low)
            high = np.where(below, high, mid)
        out: F64 = 0.5 * (low + high)
        return out


@dataclass
class Texture:
    """A bitmap sampled bilinearly in UV (row 0 is v = 1), repeating."""

    texels: F64  # (H, W, C)

    def sample(self, uv: F64) -> F64:
        height, width, _ = self.texels.shape
        fx = np.mod(uv[:, 0], 1.0) * width - 0.5
        fy = np.mod(1.0 - uv[:, 1], 1.0) * height - 0.5
        x0 = np.floor(fx).astype(np.int64)
        y0 = np.floor(fy).astype(np.int64)
        ax = (fx - x0)[:, None]
        ay = (fy - y0)[:, None]
        x1, y1 = np.mod(x0 + 1, width), np.mod(y0 + 1, height)
        x0, y0 = np.mod(x0, width), np.mod(y0, height)
        t = self.texels
        top = (1 - ax) * t[y0, x0] + ax * t[y0, x1]
        bottom = (1 - ax) * t[y1, x0] + ax * t[y1, x1]
        result: F64 = (1 - ay) * top + ay * bottom
        return result


@dataclass
class Fixture:
    mesh: Mesh
    camera: Camera
    environment: Environment
    base_color: tuple[float, float, float]  # linear
    metalness: float
    roughness: float
    background: tuple[float, float, float]  # linear clear colour
    normal_map: Texture | None = None  # tangent-space, decoded to [-1, 1]
    height_map: Texture | None = None  # stored height (Height channel values)
    bump_strength: float = 0.0  # height-derivative scale per texel of `height_map`

    def material(self, count: int) -> bsdf.Material:
        return bsdf.Material(
            np.tile(np.asarray(self.base_color, dtype=np.float64), (count, 1)),
            np.full(count, self.metalness),
            np.full(count, self.roughness),
        )


@dataclass(frozen=True)
class Settings:
    variant: bsdf.Variant = field(default_factory=bsdf.Variant)
    pixel_filter: PixelFilter = field(default_factory=PixelFilter)
    max_depth: int = 8
    rr_depth: int = 3
    below_facet: str = "absorb"  # "absorb" or "trace"
    environment_scale: float = 1.0


def shading_frame(fixture: Fixture, hit: Surface, wo: F64) -> F64:
    """Per-point orthonormal frame (N, 3, 3): rows tangent, bitangent, perturbed normal.

    Where the perturbed normal turns away from the viewer (wo below its hemisphere) the
    unperturbed interpolated normal is kept, so no point of a visible surface goes black."""
    n = hit.shading
    t = hit.tangent - n * np.sum(hit.tangent * n, axis=1, keepdims=True)
    length = np.linalg.norm(t, axis=1, keepdims=True)
    fallback = np.where(np.abs(n[:, :1]) < 0.9, [[1.0, 0.0, 0.0]], [[0.0, 1.0, 0.0]])
    t = np.where(length > 1e-9, t / np.maximum(length, 1e-12), fallback)
    t = t - n * np.sum(t * n, axis=1, keepdims=True)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    b = np.cross(n, t)
    perturbed = n
    local = np.zeros_like(n)
    local[:, 2] = 1.0
    if fixture.normal_map is not None:
        local = fixture.normal_map.sample(hit.uv)[:, :3]
    if fixture.height_map is not None and fixture.bump_strength != 0.0:
        height, width, _ = fixture.height_map.texels.shape
        du = np.stack([np.full(len(n), 1.0 / width), np.zeros(len(n))], axis=1)
        dv = np.stack([np.zeros(len(n)), np.full(len(n), 1.0 / height)], axis=1)
        h0 = fixture.height_map.sample(hit.uv)[:, 0]
        dx = h0 - fixture.height_map.sample(hit.uv - du)[:, 0]
        dy = h0 - fixture.height_map.sample(hit.uv - dv)[:, 0]
        k = fixture.bump_strength
        bump = np.stack([-k * dx, -k * dy, np.ones_like(dx)], axis=1)
        local = local + bump - np.array([0.0, 0.0, 1.0])
    if fixture.normal_map is not None or fixture.height_map is not None:
        perturbed = local[:, :1] * t + local[:, 1:2] * b + local[:, 2:3] * n
        perturbed /= np.linalg.norm(perturbed, axis=1, keepdims=True)
        away = np.sum(perturbed * wo, axis=1) <= 0.0
        perturbed = np.where(away[:, None], n, perturbed)
        t = t - perturbed * np.sum(t * perturbed, axis=1, keepdims=True)
        t /= np.linalg.norm(t, axis=1, keepdims=True)
        b = np.cross(perturbed, t)
    return np.stack([t, b, perturbed], axis=1)


def to_local(frame: F64, w: F64) -> F64:
    result: F64 = np.einsum("nij,nj->ni", frame, w)
    return result


def to_world(frame: F64, w: F64) -> F64:
    result: F64 = np.einsum("nji,nj->ni", frame, w)
    return result


def power_heuristic(a: F64, b: F64) -> F64:
    a2, b2 = a * a, b * b
    result: F64 = np.where(a2 + b2 > 0, a2 / np.maximum(a2 + b2, 1e-300), 0.0)
    return result


class Tracer:
    """Ray queries against one fixture mesh."""

    def __init__(self, fixture: Fixture, pixels: I64, pixel_filter: PixelFilter) -> None:
        self.fixture = fixture
        self.mesh = fixture.mesh
        self.candidates = pixel_candidates(
            fixture.mesh, fixture.camera, pixels, pixel_filter.support() + 0.5
        )
        self.all_triangles = np.arange(len(fixture.mesh.triangles), dtype=np.int64)

    def primary(self, rows: I64, origins: F64, directions: F64) -> Hits:
        return intersect(self.mesh, origins, directions, self.candidates[rows])

    def secondary(self, origins: F64, directions: F64, triangles: I64) -> Hits:
        """Rays leaving the given facets; a ray into a facet's empty side escapes exactly."""
        n = len(origins)
        hits = Hits(
            np.zeros(n, bool),
            np.full(n, -1, np.int64),
            np.full(n, np.inf),
            np.zeros(n),
            np.zeros(n),
        )
        side = self.mesh.empty_side[triangles]
        along = np.sum(directions * self.mesh.face_normals[triangles], axis=1)
        escapes = (side == 2) | ((side != 0) & (along * side > 0.0))
        test = ~escapes
        idx = np.nonzero(test)[0]
        for start in range(0, len(idx), 4096):
            part = idx[start : start + 4096]
            cand = np.broadcast_to(self.all_triangles, (len(part), len(self.all_triangles)))
            found = intersect(self.mesh, origins[part], directions[part], np.array(cand))
            hits.valid[part] = found.valid
            hits.triangle[part] = found.triangle
            hits.t[part] = found.t
            hits.b1[part] = found.b1
            hits.b2[part] = found.b2
        return hits


def render(
    fixture: Fixture,
    pixels: I64,
    samples: int,
    seed: int,
    settings: Settings,
    first_sample: int = 0,
    tracer: Tracer | None = None,
) -> F64:
    """Linear RGB of each pixel index (y * W + x): the mean of `samples` samples with indices
    first_sample .. first_sample + samples - 1 (so a longer render nests a shorter one)."""
    tracer = tracer or Tracer(fixture, pixels, settings.pixel_filter)
    camera = fixture.camera
    seeds = sampler.pixel_seeds(pixels, seed)
    px = (pixels % camera.width).astype(np.float64)
    py = (pixels // camera.width).astype(np.float64)
    total = np.zeros((len(pixels), 3))
    background = np.asarray(fixture.background, dtype=np.float64)
    rows_all = np.arange(len(pixels), dtype=np.int64)
    for index in range(first_sample, first_sample + samples):
        offset = settings.pixel_filter.offsets(sampler.samples(index, seeds, 0, 2))
        origins, directions = camera.rays(px + 0.5 + offset[:, 0], py + 0.5 + offset[:, 1])
        hits = tracer.primary(rows_all, origins, directions)
        value = np.zeros((len(pixels), 3))
        value[~hits.valid] = background
        live = np.nonzero(hits.valid)[0]
        value[live] = trace_paths(
            fixture,
            tracer,
            settings,
            seeds[live],
            index,
            origins[live],
            directions[live],
            Hits(hits.valid[live], hits.triangle[live], hits.t[live], hits.b1[live], hits.b2[live]),
        )
        total += value
    result: F64 = total / samples
    return result


def trace_paths(
    fixture: Fixture,
    tracer: Tracer,
    settings: Settings,
    seeds: npt.NDArray[np.uint32],
    index: int,
    origins: F64,
    directions: F64,
    hits: Hits,
) -> F64:
    """Radiance along camera rays that hit the mesh (one sample index)."""
    env = fixture.environment
    variant = settings.variant
    scale = settings.environment_scale
    n = len(origins)
    radiance = np.zeros((n, 3))
    throughput = np.ones((n, 3))
    alive = np.arange(n)
    ray_dir = directions
    current = hits
    for depth in range(settings.max_depth):
        if len(alive) == 0:
            break
        hit = surface(tracer.mesh, current, ray_dir)
        wo_world = -ray_dir
        frame = shading_frame(fixture, hit, wo_world)
        material = fixture.material(len(alive))
        wo = to_local(frame, wo_world)
        facing = wo[:, 2] > 0
        set_base = 1 + 4 * depth
        s = seeds[alive]
        # Next-event estimation toward the environment.
        light_dir, light_pdf = env.sample(sampler.samples(index, s, set_base, 2))
        wi = to_local(frame, light_dir)
        above = np.sum(light_dir * hit.geometric, axis=1) > 0
        origin = hit.position + hit.geometric * RAY_OFFSET
        blocked = np.zeros(len(alive), dtype=bool)
        test = np.nonzero(above & facing)[0]
        blocked[test] = tracer.secondary(origin[test], light_dir[test], hit.triangle[test]).valid
        f = bsdf.evaluate(material, wo, wi, variant)
        bsdf_pdf = bsdf.pdf(material, wo, wi, variant)
        weight = power_heuristic(light_pdf, bsdf_pdf)
        ok = facing & above & ~blocked & (wi[:, 2] > 0) & (light_pdf > 0)
        contribution = f * (wi[:, 2] * weight / np.maximum(light_pdf, 1e-300))[:, None]
        contribution *= env.radiance(light_dir) * scale
        radiance[alive] += np.where(ok[:, None], throughput[alive] * contribution, 0.0)
        # BSDF sample.
        u_lobe = sampler.samples(index, s, set_base + 1, 2)
        u_dir = sampler.samples(index, s, set_base + 2, 2)
        wi = bsdf.sample(material, wo, np.column_stack([u_lobe[:, 0], u_dir]), variant)
        f = bsdf.evaluate(material, wo, wi, variant)
        bsdf_pdf = bsdf.pdf(material, wo, wi, variant)
        new_dir = to_world(frame, wi)
        above = np.sum(new_dir * hit.geometric, axis=1) > 0
        good = facing & (wi[:, 2] > 0) & (bsdf_pdf > 0)
        if settings.below_facet == "absorb":
            good &= above
        beta = np.where(good[:, None], f * (wi[:, 2] / np.maximum(bsdf_pdf, 1e-300))[:, None], 0.0)
        side = np.where(above[:, None], hit.geometric, -hit.geometric)
        start = hit.position + side * RAY_OFFSET
        nxt = Hits(
            np.zeros(len(alive), bool),
            np.full(len(alive), -1, np.int64),
            np.full(len(alive), np.inf),
            np.zeros(len(alive)),
            np.zeros(len(alive)),
        )
        test = np.nonzero(good)[0]
        found = tracer.secondary(start[test], new_dir[test], hit.triangle[test])
        nxt.valid[test], nxt.triangle[test], nxt.t[test] = found.valid, found.triangle, found.t
        nxt.b1[test], nxt.b2[test] = found.b1, found.b2
        escaped = good & ~nxt.valid
        light_pdf = env.pdf(new_dir)
        weight = power_heuristic(bsdf_pdf, light_pdf)
        contribution = beta * (env.radiance(new_dir) * scale) * weight[:, None]
        radiance[alive] += np.where(escaped[:, None], throughput[alive] * contribution, 0.0)
        # Continue the paths that hit the mesh again.
        throughput[alive] *= beta
        cont = good & nxt.valid
        if depth + 1 >= settings.rr_depth:
            q = np.clip(throughput[alive].max(axis=1), 0.0, 1.0)
            u_rr = sampler.samples(index, s, set_base + 3, 2)[:, 0]
            survive = u_rr < q
            throughput[alive] /= np.maximum(q, 1e-12)[:, None]
            cont &= survive
        keep = np.nonzero(cont)[0]
        alive = alive[keep]
        ray_dir = new_dir[keep]
        current = Hits(nxt.valid[keep], nxt.triangle[keep], nxt.t[keep], nxt.b1[keep], nxt.b2[keep])
    return radiance
