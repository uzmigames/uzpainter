"""Layered BSDF of the default `open-pbr` instance, with the variants the fits choose between
(07 §3.3; decision 042: every optional open-pbr feature is off, so only the base layer acts).

Every formula has a public source (`parity/semantics/iray.json` repeats the provenance with the
fitted constants and residuals):

- Microfacet lobe: GGX / Trowbridge-Reitz distribution (Walter et al. 2007, P-WALTER) with the
  height-correlated Smith masking-shadowing G2 = 1 / (1 + Lambda(o) + Lambda(i)) and
  Lambda = (-1 + sqrt(1 + alpha^2 tan^2 theta)) / 2 (Heitz 2014, P-HEITZ); sampled by the
  distribution of visible normals (Heitz 2018, P-HEITZ). Roughness mapping alpha = r^2
  (OpenPBR `specular_roughness`, S-OPENPBR) or alpha = r (variant).
- Fresnel: the exact unpolarised dielectric Fresnel for `specular_ior` 1.5 (S-OPENPBR, PBRT 4th
  ed. §9.3, P-PBRT) or Schlick 1994 with F0 = ((n - 1) / (n + 1))^2 (P-SCHLICK, variant); the
  metal uses Schlick with F0 = base colour, which is OpenPBR's F82-tint conductor Fresnel when
  `specular_color` is white (S-OPENPBR).
- Diffuse: Lambert (OpenPBR's diffuse at `base_diffuse_roughness` 0, S-OPENPBR) or Burley 2012
  (P-BURLEY2012, variant).
- Dielectric layering of the specular lobe over the diffuse lobe (S-OPENPBR "albedo scaling";
  MDL `df::fresnel_layer`, N-MDL-SPEC):
    `albedo_o`:  f = f_s + (1 - E_s(mu_o)) f_d
    `albedo_oi`: f = f_s + (1 - E_s(mu_o)) (1 - E_s(mu_i)) / (1 - E_s,avg) f_d
    `albedo_oi_raw`: f = f_s + (1 - E_s(mu_o)) (1 - E_s(mu_i)) f_d (one transmission through
                 the interface each way, PBRT 4th ed. §14.3 layered view, without the
                 renormalisation)
    `fresnel_mix`: f = f_s + (1 - F(o . h)) f_d (glTF 2.0 Appendix B, S-GLTF)
    `none`:      f = f_s + f_d
  where E_s(mu) is the specular lobe's directional albedo (with its Fresnel), tabulated by
  numerical integration.
- Multiple-scattering energy compensation of the microfacet lobes (S-OPENPBR asks for energy
  preservation of the microfacet lobes; MDL's microfacet BSDFs offer `multiscatter_tint`,
  N-MDL-SPEC), two published forms, E1(mu) being the lobe's albedo with F = 1:
    `turquin`:     f_ms = f_ss (1 + F0 (1 - E1(mu_o)) / E1(mu_o))       (Turquin 2019, P-TURQUIN)
    `kulla_conty`: f_ms = f_ss + F_ms (1 - E1(mu_o)) (1 - E1(mu_i)) / (pi (1 - E1_avg)),
                   F_ms = F_avg^2 E1_avg / (1 - F_avg (1 - E1_avg))     (Kulla and Conty 2017,
                   P-KULLA), F_avg the cosine-weighted average Fresnel.
    `tint`:        as `kulla_conty` with F_ms replaced by a tint: the metal's F0 (its base
                   colour) or the dielectric's F_avg (MDL `multiscatter_tint`, N-MDL-SPEC);
    `tint_f0`:     the same with the dielectric's F0 as the tint.
- Metal / dielectric mix by `base_metalness` m: f = m f_metal + (1 - m) f_dielectric (S-OPENPBR).

Directions are in the local shading frame (z = shading normal); `wo` points to the viewer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
LAYERINGS = ("albedo_o", "albedo_oi", "albedo_oi_raw", "fresnel_mix", "none")
MULTISCATTER = ("none", "turquin", "kulla_conty", "tint", "tint_f0")
ALBEDO_TABLE = 64


@dataclass(frozen=True)
class Variant:
    """The lobe choices a fit compares (07 §3.3: decided by calibration, not by names)."""

    roughness_map: str = "squared"  # "squared": alpha = r^2; "linear": alpha = r
    dielectric_fresnel: str = "exact"  # "exact" or "schlick"
    diffuse: str = "lambert"  # "lambert" or "burley"
    layering: str = "albedo_o"
    multiscatter: str = "none"  # metal lobe: "none", "turquin", "kulla_conty" or "tint"
    dielectric_multiscatter: str = "none"  # dielectric specular lobe, same choices
    ior: float = 1.5

    def alpha(self, roughness: F64) -> F64:
        r = np.clip(roughness, 0.0, 1.0)
        a = r * r if self.roughness_map == "squared" else r
        result: F64 = np.maximum(a, 1e-4)
        return result


@dataclass
class Material:
    base_color: F64  # (N, 3) linear
    metalness: F64  # (N,)
    roughness: F64  # (N,)


def ggx_d(cos_h: F64, alpha: F64) -> F64:
    a2 = alpha * alpha
    c2 = cos_h * cos_h
    denom = c2 * (a2 - 1.0) + 1.0
    result: F64 = np.where(cos_h > 0, a2 / (math.pi * denom * denom), 0.0)
    return result


def smith_lambda(cos_t: F64, alpha: F64) -> F64:
    c2 = np.clip(cos_t * cos_t, 1e-12, 1.0)
    tan2 = (1.0 - c2) / c2
    result: F64 = (-1.0 + np.sqrt(1.0 + alpha * alpha * tan2)) / 2.0
    return result


def g2(cos_o: F64, cos_i: F64, alpha: F64) -> F64:
    result: F64 = 1.0 / (1.0 + smith_lambda(cos_o, alpha) + smith_lambda(cos_i, alpha))
    return result


def g1(cos_o: F64, alpha: F64) -> F64:
    result: F64 = 1.0 / (1.0 + smith_lambda(cos_o, alpha))
    return result


def fresnel_dielectric(cos_i: F64, eta: float) -> F64:
    """Unpolarised Fresnel reflectance from outside (n = 1) into eta."""
    c = np.clip(cos_i, 0.0, 1.0)
    sin2_t = (1.0 - c * c) / (eta * eta)
    cos_t = np.sqrt(np.maximum(1.0 - sin2_t, 0.0))
    r_par = (eta * c - cos_t) / (eta * c + cos_t)
    r_perp = (c - eta * cos_t) / (c + eta * cos_t)
    result: F64 = np.where(sin2_t >= 1.0, 1.0, 0.5 * (r_par * r_par + r_perp * r_perp))
    return result


def schlick(cos_i: F64, f0: F64) -> F64:
    m = np.clip(1.0 - cos_i, 0.0, 1.0)
    m5 = (m * m) * (m * m) * m
    result: F64 = f0 + (1.0 - f0) * m5
    return result


def dielectric_f(cos_h: F64, variant: Variant) -> F64:
    if variant.dielectric_fresnel == "exact":
        return fresnel_dielectric(cos_h, variant.ior)
    f0 = ((variant.ior - 1.0) / (variant.ior + 1.0)) ** 2
    return schlick(cos_h, np.full_like(cos_h, f0))


def sample_vndf(wo: F64, alpha: F64, u: F64) -> F64:
    """Heitz 2018 listing: visible microfacet normal for `wo` (local frame), isotropic alpha."""
    vh = np.stack([alpha * wo[:, 0], alpha * wo[:, 1], wo[:, 2]], axis=1)
    vh /= np.linalg.norm(vh, axis=1, keepdims=True)
    lensq = vh[:, 0] ** 2 + vh[:, 1] ** 2
    inv = np.where(lensq > 0, 1.0 / np.sqrt(np.maximum(lensq, 1e-30)), 0.0)
    t1 = np.where(
        (lensq > 0)[:, None],
        np.stack([-vh[:, 1] * inv, vh[:, 0] * inv, np.zeros_like(lensq)], axis=1),
        np.array([1.0, 0.0, 0.0]),
    )
    t2 = np.cross(vh, t1)
    r = np.sqrt(u[:, 0])
    phi = 2.0 * math.pi * u[:, 1]
    p1 = r * np.cos(phi)
    p2 = r * np.sin(phi)
    s = 0.5 * (1.0 + vh[:, 2])
    p2 = (1.0 - s) * np.sqrt(np.maximum(1.0 - p1 * p1, 0.0)) + s * p2
    p3 = np.sqrt(np.maximum(1.0 - p1 * p1 - p2 * p2, 0.0))
    nh = t1 * p1[:, None] + t2 * p2[:, None] + vh * p3[:, None]
    h = np.stack([alpha * nh[:, 0], alpha * nh[:, 1], np.maximum(nh[:, 2], 0.0)], axis=1)
    result: F64 = h / np.linalg.norm(h, axis=1, keepdims=True)
    return result


def reflect(w: F64, h: F64) -> F64:
    result: F64 = 2.0 * np.sum(w * h, axis=1, keepdims=True) * h - w
    return result


def specular_core(wo: F64, wi: F64, alpha: F64) -> tuple[F64, F64, F64]:
    """D G2 / (4 cos_o cos_i), the half vector's cosine with wo, and the VNDF pdf."""
    cos_o = wo[:, 2]
    cos_i = wi[:, 2]
    h = wo + wi
    h /= np.maximum(np.linalg.norm(h, axis=1, keepdims=True), 1e-30)
    cos_h = h[:, 2]
    oh = np.clip(np.sum(wo * h, axis=1), 0.0, 1.0)
    d = ggx_d(cos_h, alpha)
    valid = (cos_o > 0) & (cos_i > 0)
    core = np.where(
        valid, d * g2(cos_o, cos_i, alpha) / (4.0 * np.maximum(cos_o * cos_i, 1e-30)), 0
    )
    pdf = np.where(valid, g1(cos_o, alpha) * d / (4.0 * np.maximum(cos_o, 1e-30)), 0.0)
    return core, oh, pdf


@lru_cache(maxsize=256)
def albedo_table(alpha: float, fresnel: str, ior: float) -> tuple[F64, float]:
    """Directional albedo E(mu) of the specular lobe on ALBEDO_TABLE cosines, and its
    cosine-weighted average, by a 128 x 128 stratified VNDF quadrature (deterministic)."""
    mus = (np.arange(ALBEDO_TABLE) + 0.5) / ALBEDO_TABLE
    grid = (np.arange(128) + 0.5) / 128
    u = np.stack(np.meshgrid(grid, grid, indexing="ij"), axis=-1).reshape(-1, 2)
    variant = Variant(dielectric_fresnel=fresnel, ior=ior)
    values = np.empty(ALBEDO_TABLE)
    for k, mu in enumerate(mus):
        wo = np.tile([math.sqrt(1.0 - mu * mu), 0.0, mu], (len(u), 1))
        a = np.full(len(u), alpha)
        h = sample_vndf(wo, a, u)
        wi = reflect(wo, h)
        cos_i = wi[:, 2]
        oh = np.clip(np.sum(wo * h, axis=1), 0.0, 1.0)
        f = np.ones_like(oh) if fresnel == "one" else dielectric_f(oh, variant)
        # Estimator f G2 / G1 for VNDF sampling (Heitz 2018 §2).
        weight = np.where(cos_i > 0, f * g2(wo[:, 2], cos_i, a) / g1(wo[:, 2], a), 0.0)
        values[k] = weight.mean()
    average = float(2.0 * np.sum(values * mus) / ALBEDO_TABLE)
    return values, average


@lru_cache(maxsize=8)
def average_dielectric_fresnel(fresnel: str, ior: float) -> float:
    """F_avg = 2 int_0^1 F(mu) mu dmu (midpoint rule, 4096 cosines)."""
    mu = (np.arange(4096) + 0.5) / 4096
    f = dielectric_f(mu, Variant(dielectric_fresnel=fresnel, ior=ior))
    return float(2.0 * np.mean(f * mu))


def albedo_lookup(table: F64, mu: F64) -> F64:
    x = np.clip(mu, 0.0, 1.0) * ALBEDO_TABLE - 0.5
    result: F64 = np.interp(x, np.arange(ALBEDO_TABLE), table)
    return result


def per_alpha(alpha: F64, mu: F64, fresnel: str, ior: float) -> tuple[F64, F64]:
    """E(mu) and E_avg for each point, grouping the (few) distinct alphas of a fixture."""
    e = np.empty_like(mu)
    avg = np.empty_like(mu)
    for value in np.unique(alpha):
        pick = alpha == value
        table, average = albedo_table(float(value), fresnel, ior)
        e[pick] = albedo_lookup(table, mu[pick])
        avg[pick] = average
    return e, avg


def diffuse_term(material: Material, wo: F64, wi: F64, variant: Variant) -> F64:
    base = material.base_color / math.pi
    if variant.diffuse == "lambert":
        return np.where((wi[:, 2] > 0)[:, None], base, 0.0)
    h = wo + wi
    h /= np.maximum(np.linalg.norm(h, axis=1, keepdims=True), 1e-30)
    cos_d = np.clip(np.sum(wi * h, axis=1), 0.0, 1.0)
    fd90 = 0.5 + 2.0 * material.roughness * cos_d * cos_d
    fo = 1.0 + (fd90 - 1.0) * (1.0 - np.clip(wo[:, 2], 0, 1)) ** 5
    fi = 1.0 + (fd90 - 1.0) * (1.0 - np.clip(wi[:, 2], 0, 1)) ** 5
    return np.where((wi[:, 2] > 0)[:, None], base * (fo * fi)[:, None], 0.0)


def compensated(
    single: F64, f0: F64, f_avg: F64, wo: F64, wi: F64, alpha: F64, variant: Variant, mode: str
) -> F64:
    """The microfacet lobe with multiple-scattering compensation `mode` (N, 3)."""
    if mode == "none":
        return single
    mu_o = np.clip(wo[:, 2], 0.0, 1.0)
    e1_o, e1_avg = per_alpha(alpha, mu_o, "one", variant.ior)
    if mode == "turquin":
        factor = 1.0 + f0 * ((1.0 - e1_o) / np.maximum(e1_o, 1e-6))[:, None]
        result: F64 = single * factor
        return result
    mu_i = np.clip(wi[:, 2], 0.0, 1.0)
    e1_i, _ = per_alpha(alpha, mu_i, "one", variant.ior)
    if mode == "tint":
        f_ms = f0 if f0.shape[1] == 3 else f_avg
    elif mode == "tint_f0":
        f_ms = f0
    else:
        f_ms = f_avg * f_avg * e1_avg[:, None] / (1.0 - f_avg * (1.0 - e1_avg[:, None]))
    lobe = (1.0 - e1_o) * (1.0 - e1_i) / (math.pi * np.maximum(1.0 - e1_avg, 1e-6))
    lobe = np.where((wi[:, 2] > 0) & (wo[:, 2] > 0), lobe, 0.0)
    result = single + f_ms * lobe[:, None]
    return result


def dielectric_specular_albedo(alpha: F64, mu: F64, variant: Variant) -> tuple[F64, F64]:
    """E_s(mu) of the compensated dielectric specular lobe and its cosine-weighted average."""
    fresnel = "exact" if variant.dielectric_fresnel == "exact" else "schlick"
    e, avg = per_alpha(alpha, mu, fresnel, variant.ior)
    mode = variant.dielectric_multiscatter
    if mode == "none":
        return e, avg
    f0 = ((variant.ior - 1.0) / (variant.ior + 1.0)) ** 2
    e1, e1_avg = per_alpha(alpha, mu, "one", variant.ior)
    if mode == "turquin":
        scale = 1.0 + f0 * (1.0 - e1) / np.maximum(e1, 1e-6)
        # Average of E_s scale over cosines, by the same tables (64 cosines).
        grid = (np.arange(ALBEDO_TABLE) + 0.5) / ALBEDO_TABLE
        avg_c = np.empty_like(avg)
        for value in np.unique(alpha):
            pick = alpha == value
            table_f, _ = albedo_table(float(value), fresnel, variant.ior)
            table_1, _ = albedo_table(float(value), "one", variant.ior)
            comp = table_f * (1.0 + f0 * (1.0 - table_1) / np.maximum(table_1, 1e-6))
            avg_c[pick] = float(2.0 * np.sum(comp * grid) / ALBEDO_TABLE)
        result: F64 = e * scale
        return result, avg_c
    f_avg = average_dielectric_fresnel(fresnel, variant.ior)
    if mode == "tint":
        f_ms = np.full_like(e1, f_avg)
    elif mode == "tint_f0":
        f_ms = np.full_like(e1, f0)
    else:
        f_ms = f_avg * f_avg * e1_avg / (1.0 - f_avg * (1.0 - e1_avg))
    return e + f_ms * (1.0 - e1), avg + f_ms * (1.0 - e1_avg)


def evaluate(material: Material, wo: F64, wi: F64, variant: Variant) -> F64:
    """f(wo, wi) (N, 3), without the cosine."""
    alpha = variant.alpha(material.roughness)
    core, oh, _ = specular_core(wo, wi, alpha)
    m = material.metalness[:, None]
    f0_metal = material.base_color
    f_metal = schlick(oh[:, None], f0_metal) * core[:, None]
    f_metal = compensated(
        f_metal,
        f0_metal,
        f0_metal + (1.0 - f0_metal) / 21.0,
        wo,
        wi,
        alpha,
        variant,
        variant.multiscatter,
    )
    fresnel = "exact" if variant.dielectric_fresnel == "exact" else "schlick"
    f0_d = np.full((len(oh), 1), ((variant.ior - 1.0) / (variant.ior + 1.0)) ** 2)
    f_spec = (dielectric_f(oh, variant) * core)[:, None]
    favg_d = np.full_like(f0_d, average_dielectric_fresnel(fresnel, variant.ior))
    f_spec = compensated(
        f_spec, f0_d, favg_d, wo, wi, alpha, variant, variant.dielectric_multiscatter
    )
    f_diff = diffuse_term(material, wo, wi, variant)
    if variant.layering == "none":
        scale = np.ones_like(oh)
    elif variant.layering == "fresnel_mix":
        scale = 1.0 - dielectric_f(oh, variant)
    else:
        e_o, avg = dielectric_specular_albedo(alpha, np.clip(wo[:, 2], 0, 1), variant)
        scale = 1.0 - e_o
        if variant.layering in ("albedo_oi", "albedo_oi_raw"):
            e_i, _ = dielectric_specular_albedo(alpha, np.clip(wi[:, 2], 0, 1), variant)
            scale = scale * (1.0 - e_i)
            if variant.layering == "albedo_oi":
                scale = scale / np.maximum(1.0 - avg, 1e-6)
    f_dielectric = f_spec + scale[:, None] * f_diff
    result: F64 = m * f_metal + (1.0 - m) * f_dielectric
    return result


def specular_probability(material: Material) -> F64:
    """Lobe selection: the metal always samples the microfacet lobe, the dielectric half."""
    result: F64 = np.clip(material.metalness + (1.0 - material.metalness) * 0.5, 0.05, 1.0)
    return result


def pdf(material: Material, wo: F64, wi: F64, variant: Variant) -> F64:
    alpha = variant.alpha(material.roughness)
    _, _, spec_pdf = specular_core(wo, wi, alpha)
    p = specular_probability(material)
    cos_pdf = np.where(wi[:, 2] > 0, wi[:, 2] / math.pi, 0.0)
    result: F64 = p * spec_pdf + (1.0 - p) * cos_pdf
    return result


def sample(material: Material, wo: F64, u: F64, variant: Variant) -> F64:
    """Directions wi for uniform triples u (N, 3): u[:, 0] picks the lobe."""
    alpha = variant.alpha(material.roughness)
    p = specular_probability(material)
    h = sample_vndf(wo, alpha, u[:, 1:3])
    spec = reflect(wo, h)
    r = np.sqrt(u[:, 1])
    phi = 2.0 * math.pi * u[:, 2]
    cosine = np.stack(
        [r * np.cos(phi), r * np.sin(phi), np.sqrt(np.maximum(1.0 - u[:, 1], 0.0))], axis=1
    )
    result: F64 = np.where((u[:, 0] < p)[:, None], spec, cosine)
    return result
