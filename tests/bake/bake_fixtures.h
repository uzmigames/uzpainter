#pragma once

// Authored bake fixtures of the CPU baker (decisions 302 and 306): small meshes generated
// deterministically from a few constants. No Painter data and no Assets3D file is involved.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <numbers>
#include <string>
#include <utility>
#include <vector>

#include "bake/bake_request.h"

namespace uzp::bake::fixtures {

/// Appends a quad (a, b, c, d counter-clockwise from its front) as two triangles.
inline void AddQuad(BakeMesh& mesh, Float3 a, Float3 b, Float3 c, Float3 d, Float3 normal,
                    Float2 ua, Float2 ub, Float2 uc, Float2 ud) {
    const auto base = static_cast<std::uint32_t>(mesh.positions.size());
    for (const Float3& p : {a, b, c, d}) {
        mesh.positions.push_back(p);
        mesh.normals.push_back(normal);
    }
    for (const Float2& uv : {ua, ub, uc, ud}) mesh.uvs.push_back(uv);
    for (std::uint32_t i : {0u, 1u, 2u, 0u, 2u, 3u}) mesh.indices.push_back(base + i);
}

/// The square [x0, x1] x [y0, y1] at height z, its front facing +z (or -z when `flipped`), UVs
/// mapping x0..x1 to u0..u1 and y0..y1 to v0..v1.
inline BakeMesh Plane(std::string name, float x0, float x1, float y0, float y1, float z,
                      bool flipped = false, Float2 uv0 = {0.25f, 0.25f},
                      Float2 uv1 = {0.75f, 0.75f}) {
    BakeMesh mesh;
    mesh.name = std::move(name);
    const Float3 a{x0, y0, z}, b{x1, y0, z}, c{x1, y1, z}, d{x0, y1, z};
    const Float2 ua{uv0.x, uv0.y}, ub{uv1.x, uv0.y}, uc{uv1.x, uv1.y}, ud{uv0.x, uv1.y};
    if (flipped) {
        AddQuad(mesh, a, d, c, b, {0.0f, 0.0f, -1.0f}, ua, ud, uc, ub);
    } else {
        AddQuad(mesh, a, b, c, d, {0.0f, 0.0f, 1.0f}, ua, ub, uc, ud);
    }
    return mesh;
}

/// The axis-aligned cube [-h, h]³, its six faces facing inward (or outward), no UVs used.
inline BakeMesh Box(std::string name, float h, bool inward) {
    BakeMesh mesh;
    mesh.name = std::move(name);
    const Float2 z2{0.0f, 0.0f};
    // Each face: four corners counter-clockwise seen from outside, and its outward normal.
    struct Face {
        Float3 a, b, c, d, n;
    };
    const Face faces[6] = {
        {{h, -h, -h}, {h, h, -h}, {h, h, h}, {h, -h, h}, {1, 0, 0}},
        {{-h, h, -h}, {-h, -h, -h}, {-h, -h, h}, {-h, h, h}, {-1, 0, 0}},
        {{h, h, -h}, {-h, h, -h}, {-h, h, h}, {h, h, h}, {0, 1, 0}},
        {{-h, -h, -h}, {h, -h, -h}, {h, -h, h}, {-h, -h, h}, {0, -1, 0}},
        {{-h, -h, h}, {h, -h, h}, {h, h, h}, {-h, h, h}, {0, 0, 1}},
        {{-h, h, -h}, {h, h, -h}, {h, -h, -h}, {-h, -h, -h}, {0, 0, -1}},
    };
    for (const Face& f : faces) {
        if (inward) {
            AddQuad(mesh, f.a, f.d, f.c, f.b, {-f.n.x, -f.n.y, -f.n.z}, z2, z2, z2, z2);
        } else {
            AddQuad(mesh, f.a, f.b, f.c, f.d, f.n, z2, z2, z2, z2);
        }
    }
    return mesh;
}

/// A ground grid ([-2, 2]², `cells` x `cells` quads, UVs in [0.01, 0.49] x [0.01, 0.99]) and a
/// latitude-longitude sphere of radius 0.5 resting on it (smooth normals, UVs in
/// [0.51, 0.99] x [0.01, 0.99]), as one mesh: the determinism scene, baked low as high.
inline BakeMesh SphereOnGround(std::uint32_t cells = 8, std::uint32_t stacks = 24,
                               std::uint32_t slices = 48) {
    BakeMesh mesh;
    mesh.name = "sphere_on_ground";
    const double size = 4.0;
    for (std::uint32_t j = 0; j < cells; ++j) {
        for (std::uint32_t i = 0; i < cells; ++i) {
            const auto x = [&](std::uint32_t k) { return static_cast<float>(-2.0 + size * k / cells); };
            const auto u = [&](std::uint32_t k) { return static_cast<float>(0.01 + 0.48 * k / cells); };
            const auto v = [&](std::uint32_t k) { return static_cast<float>(0.01 + 0.98 * k / cells); };
            AddQuad(mesh, {x(i), x(j), 0.0f}, {x(i + 1), x(j), 0.0f}, {x(i + 1), x(j + 1), 0.0f},
                    {x(i), x(j + 1), 0.0f}, {0.0f, 0.0f, 1.0f}, {u(i), v(j)}, {u(i + 1), v(j)},
                    {u(i + 1), v(j + 1)}, {u(i), v(j + 1)});
        }
    }
    const double radius = 0.5;
    const double cz = 0.5;
    const auto base = static_cast<std::uint32_t>(mesh.positions.size());
    const std::uint32_t columns = slices + 1;
    for (std::uint32_t i = 0; i <= stacks; ++i) {
        const double theta = std::numbers::pi * i / stacks;
        for (std::uint32_t j = 0; j <= slices; ++j) {
            const double phi = 2.0 * std::numbers::pi * j / slices;
            const double nx = std::sin(theta) * std::cos(phi);
            const double ny = std::sin(theta) * std::sin(phi);
            const double nz = std::cos(theta);
            mesh.positions.push_back({static_cast<float>(radius * nx), static_cast<float>(radius * ny),
                                      static_cast<float>(cz + radius * nz)});
            mesh.normals.push_back({static_cast<float>(nx), static_cast<float>(ny), static_cast<float>(nz)});
            mesh.uvs.push_back({static_cast<float>(0.51 + 0.48 * j / slices),
                                static_cast<float>(0.99 - 0.98 * i / stacks)});
        }
    }
    for (std::uint32_t i = 0; i < stacks; ++i) {
        for (std::uint32_t j = 0; j < slices; ++j) {
            const std::uint32_t a = base + i * columns + j;
            const std::uint32_t b = a + columns;
            const std::uint32_t c = b + 1;
            const std::uint32_t d = a + 1;
            // The pole rows keep only their non-degenerate triangle.
            if (i != stacks - 1) {
                for (std::uint32_t k : {a, b, c}) mesh.indices.push_back(k);
            }
            if (i != 0) {
                for (std::uint32_t k : {a, c, d}) mesh.indices.push_back(k);
            }
        }
    }
    return mesh;
}

// ── The bevelled cube with highs (decision 306) ──────────────────────────────────────────────

/// Atlas of the bevelled-cube fixture: 128 x 64 texels, 4 x 2 cells of 32 x 32, each island the
/// cell inset by 4 texels (24 x 24 texels, edges on texel boundaries).
inline constexpr std::uint32_t kAtlasWidthLog2 = 7;
inline constexpr std::uint32_t kAtlasHeightLog2 = 6;
inline constexpr std::uint32_t kCell = 32;
inline constexpr std::uint32_t kInset = 4;
inline constexpr std::uint32_t kIsland = 24;

/// The UV rectangle of atlas cell `cell` (column `cell % 4`, row `cell / 4` from the top).
inline void IslandUv(std::uint32_t cell, Float2& uv0, Float2& uv1) {
    const float x0 = static_cast<float>((cell % 4) * kCell + kInset);
    const float y0 = static_cast<float>((cell / 4) * kCell + kInset);  // top texel row
    uv0 = {x0 / 128.0f, 1.0f - (y0 + kIsland) / 64.0f};
    uv1 = {(x0 + kIsland) / 128.0f, 1.0f - y0 / 64.0f};
}

/// The faces of the cube [-1, 1]^3: corners counter-clockwise seen from outside, outward normal.
struct CubeFace {
    Float3 a, b, c, d, n;
};
inline constexpr CubeFace kCubeFaces[6] = {
    {{1, -1, -1}, {1, 1, -1}, {1, 1, 1}, {1, -1, 1}, {1, 0, 0}},
    {{-1, 1, -1}, {-1, -1, -1}, {-1, -1, 1}, {-1, 1, 1}, {-1, 0, 0}},
    {{1, 1, -1}, {-1, 1, -1}, {-1, 1, 1}, {1, 1, 1}, {0, 1, 0}},
    {{-1, -1, -1}, {1, -1, -1}, {1, -1, 1}, {-1, -1, 1}, {0, -1, 0}},
    {{-1, -1, 1}, {1, -1, 1}, {1, 1, 1}, {-1, 1, 1}, {0, 0, 1}},
    {{-1, 1, -1}, {1, 1, -1}, {1, -1, -1}, {-1, -1, -1}, {0, 0, -1}},
};
/// The cube face pointing up (+z), in atlas cell 4.
inline constexpr std::uint32_t kTopFace = 4;

/// The low cube [-1, 1]^3 scaled by `scale`, flat normals, face f in atlas cell f.
inline BakeMesh LowCube(std::string name, float scale = 1.0f) {
    BakeMesh mesh;
    mesh.name = std::move(name);
    for (std::uint32_t f = 0; f < 6; ++f) {
        const CubeFace& face = kCubeFaces[f];
        const auto s = [&](Float3 p) { return Float3{p.x * scale, p.y * scale, p.z * scale}; };
        Float2 uv0, uv1;
        IslandUv(f, uv0, uv1);
        AddQuad(mesh, s(face.a), s(face.b), s(face.c), s(face.d), face.n, uv0, {uv1.x, uv0.y}, uv1,
                {uv0.x, uv1.y});
    }
    return mesh;
}

/// The cube [-1, 1]^3 with every edge chamfered by `b`: the convex hull of the permutations of
/// (+-1, +-(1 - b), +-(1 - b)); 6 faces, 12 edge quads and 8 corner triangles, wound outward,
/// flat normals, no UVs.
inline BakeMesh ChamferedCube(std::string name, double b) {
    using P = std::array<double, 3>;
    BakeMesh mesh;
    mesh.name = std::move(name);
    const double m = 1.0 - b;
    const auto point = [](int axis, double va, double vb, double vc) {
        P p{};
        p[static_cast<std::size_t>(axis)] = va;
        p[static_cast<std::size_t>((axis + 1) % 3)] = vb;
        p[static_cast<std::size_t>((axis + 2) % 3)] = vc;
        return p;
    };
    const auto add = [&](std::vector<P> poly) {
        // Wind outward: the hull contains the origin, so the normal points away from it.
        const P e1{poly[1][0] - poly[0][0], poly[1][1] - poly[0][1], poly[1][2] - poly[0][2]};
        const P e2{poly[2][0] - poly[0][0], poly[2][1] - poly[0][1], poly[2][2] - poly[0][2]};
        P n{e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]};
        if (n[0] * poly[0][0] + n[1] * poly[0][1] + n[2] * poly[0][2] < 0.0) {
            std::reverse(poly.begin(), poly.end());
            n = {-n[0], -n[1], -n[2]};
        }
        const double length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
        const Float3 normal{static_cast<float>(n[0] / length), static_cast<float>(n[1] / length),
                            static_cast<float>(n[2] / length)};
        const auto base = static_cast<std::uint32_t>(mesh.positions.size());
        for (const P& p : poly) {
            mesh.positions.push_back({static_cast<float>(p[0]), static_cast<float>(p[1]), static_cast<float>(p[2])});
            mesh.normals.push_back(normal);
        }
        for (std::uint32_t i = 1; i + 1 < poly.size(); ++i) {
            for (std::uint32_t k : {0u, i, i + 1}) mesh.indices.push_back(base + k);
        }
    };
    for (int axis = 0; axis < 3; ++axis) {
        for (double s : {-1.0, 1.0}) {
            // The face at coordinate s on `axis`.
            add({point(axis, s, -m, -m), point(axis, s, m, -m), point(axis, s, m, m), point(axis, s, -m, m)});
            // The edge between this face and the face at sc on the next axis, along the third.
            for (double sc : {-1.0, 1.0}) {
                add({point(axis, s, sc * m, -m), point(axis, s * m, sc, -m), point(axis, s * m, sc, m),
                     point(axis, s, sc * m, m)});
            }
        }
    }
    for (double sx : {-1.0, 1.0}) {
        for (double sy : {-1.0, 1.0}) {
            for (double sz : {-1.0, 1.0}) add({P{sx, sy * m, sz * m}, P{sx * m, sy, sz * m}, P{sx * m, sy * m, sz}});
        }
    }
    return mesh;
}

/// One mesh holding the triangles of `parts`.
inline BakeMesh Merge(std::string name, std::initializer_list<BakeMesh> parts) {
    BakeMesh mesh;
    mesh.name = std::move(name);
    for (const BakeMesh& part : parts) {
        const auto base = static_cast<std::uint32_t>(mesh.positions.size());
        mesh.positions.insert(mesh.positions.end(), part.positions.begin(), part.positions.end());
        mesh.normals.insert(mesh.normals.end(), part.normals.begin(), part.normals.end());
        mesh.uvs.insert(mesh.uvs.end(), part.uvs.begin(), part.uvs.end());
        for (std::uint32_t i : part.indices) mesh.indices.push_back(base + i);
    }
    return mesh;
}

/// The knob low part: the plane [-0.5, 0.5]^2 at z = 3 facing up, in atlas cell 6.
inline BakeMesh KnobLow(std::string name) {
    Float2 uv0, uv1;
    IslandUv(6, uv0, uv1);
    return Plane(std::move(name), -0.5f, 0.5f, -0.5f, 0.5f, 3.0f, false, uv0, uv1);
}

/// The knob's high mesh: its surface at z = 3 facing up under a cover at z = 3.02 facing down.
inline BakeMesh KnobHigh(std::string name) {
    return Merge(std::move(name),
                 {Plane("surface", -1, 1, -1, 1, 3.0f), Plane("cover", -1, 1, -1, 1, 3.02f, true)});
}

/// A decoy high mesh over the cube's top face: [-1.5, 1.5]^2 at z = 1.02 facing down.
inline BakeMesh Decoy(std::string name) { return Plane(std::move(name), -1.5f, 1.5f, -1.5f, 1.5f, 1.02f, true); }

}  // namespace uzp::bake::fixtures
