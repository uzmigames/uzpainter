#pragma once

// Authored bake fixtures of the CPU baker feasibility slice (decision 302): small meshes generated
// deterministically from a few constants. No Painter data and no Assets3D file is involved.

#include <cmath>
#include <cstdint>
#include <numbers>
#include <string>

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

}  // namespace uzp::bake::fixtures
