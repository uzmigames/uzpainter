// uzp-normal-bake.exe: the normal-convention fixture (P0-NORMAL) re-run with the production
// tangent frames (task phase1.5_mesh-tangents-certificate, item 3.6).
//
// Same command line, bake and outputs as the Phase 0 prototype `uzp-normal-prototype.exe`
// (`src/prototype/normal_prototype.cpp`, `parity/NORMAL-CONVENTION.md` §3), so that
// `tools/parity/normal_convention` reads its maps unchanged; what differs is where the frames come
// from. Both meshes are read by the production importer (`ImportMeshFile`), the low mesh's
// per-corner frames are its import's MikkTSpace frames (`src/mesh/tangents.h`), and every texel's
// frame, `inverse` transform and analytic round trip use `InterpolateFrame`, `ToTangentSpace` and
// `FromTangentSpace`. The texel walk, the ray cast, the 16-bit encoding, the DirectX conversion
// (green code 65535 - g) and the `projection` transform (a rejected candidate the study still
// compares) are the fixture's test harness, as in the prototype.
//
// Usage: uzp-normal-bake --low <low.obj> --high <high.obj> --size <px> --max-height <d>
//        --max-depth <d> --out-dir <dir> --name <prefix>

#include <spng.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "mesh/mesh_import.h"
#include "mesh/tangents.h"

namespace {

using namespace uzp;
using namespace uzp::mesh;
using namespace uzp::mesh::v3;

/// One triangle of a mesh, its corners' attributes in the triangle's order.
struct Face {
    const Triangle* triangle;
    std::array<Float3, 3> p;
    std::array<Float3, 3> n;
    std::array<Float2, 3> uv;
};

std::vector<Face> Faces(const TexturingMesh& mesh) {
    std::vector<Face> faces;
    for (const Object& object : mesh.objects) {
        for (const Triangle& t : object.triangles) {
            Face face{&t, {}, {}, {}};
            for (std::size_t i = 0; i < 3; ++i) {
                const Corner& c = mesh.corners[t.corners[i]];
                face.p[i] = mesh.positions[c.position];
                face.n[i] = c.normal;
                face.uv[i] = c.uv0;
            }
            faces.push_back(face);
        }
    }
    return faces;
}

struct Hit {
    std::size_t face;
    Float3 normal;  // interpolated high-poly normal, normalized
};

// Rays start on the cage, `max_height` along the direction, and travel back through the low
// surface down to `max_depth` below it; the first hit from the cage is used, and triangles seen
// from behind are ignored (the prototype's rule).
std::optional<Hit> CastRay(const std::vector<Face>& high, const Float3& origin, const Float3& direction,
                           double max_height, double max_depth) {
    std::optional<Hit> best;
    double best_t = -max_depth;
    for (std::size_t f = 0; f < high.size(); ++f) {
        const auto& p = high[f].p;
        const Float3 e1 = Sub(p[1], p[0]);
        const Float3 e2 = Sub(p[2], p[0]);
        if (Dot(Cross(e1, e2), direction) <= 0.0f) continue;
        // Moeller-Trumbore in double precision.
        const std::array<double, 3> d{direction.x, direction.y, direction.z};
        const std::array<double, 3> a{e1.x, e1.y, e1.z};
        const std::array<double, 3> b{e2.x, e2.y, e2.z};
        const std::array<double, 3> pv{d[1] * b[2] - d[2] * b[1], d[2] * b[0] - d[0] * b[2], d[0] * b[1] - d[1] * b[0]};
        const double det = a[0] * pv[0] + a[1] * pv[1] + a[2] * pv[2];
        if (std::abs(det) < 1e-18) continue;
        const std::array<double, 3> s{origin.x - p[0].x, origin.y - p[0].y, origin.z - p[0].z};
        const double u = (s[0] * pv[0] + s[1] * pv[1] + s[2] * pv[2]) / det;
        if (u < 0.0 || u > 1.0) continue;
        const std::array<double, 3> qv{s[1] * a[2] - s[2] * a[1], s[2] * a[0] - s[0] * a[2], s[0] * a[1] - s[1] * a[0]};
        const double v = (d[0] * qv[0] + d[1] * qv[1] + d[2] * qv[2]) / det;
        if (v < 0.0 || u + v > 1.0) continue;
        const double t = (b[0] * qv[0] + b[1] * qv[1] + b[2] * qv[2]) / det;
        if (t > max_height || t < -max_depth || t <= best_t) continue;
        best_t = t;
        const auto& n = high[f].n;
        const float w0 = static_cast<float>(1.0 - u - v);
        const Float3 normal =
            Add(Add(Scale(n[0], w0), Scale(n[1], static_cast<float>(u))), Scale(n[2], static_cast<float>(v)));
        best = Hit{f, Normalize(normal)};
    }
    return best;
}

constexpr std::array<core::TangentSpace, 2> kModes{core::TangentSpace::PerVertex, core::TangentSpace::PerFragment};
const char* ModeName(core::TangentSpace mode) { return mode == core::TangentSpace::PerVertex ? "PerVertex" : "PerFragment"; }
constexpr std::array<const char*, 2> kTransforms{"inverse", "projection"};

/// The `projection` candidate: dot products with the normalized frame vectors.
Float3 Projection(const Frame& f, const Float3& n) {
    return Normalize({Dot(n, Normalize(f.t)), Dot(n, Normalize(f.b)), Dot(n, Normalize(f.n))});
}
Float3 ProjectionBack(const Frame& f, const Float3& t) {
    return Normalize(Add(Add(Scale(Normalize(f.t), t.x), Scale(Normalize(f.b), t.y)), Scale(Normalize(f.n), t.z)));
}

std::uint16_t Encode(float x) {
    const float e = std::clamp(x * 0.5f + 0.5f, 0.0f, 1.0f);
    return static_cast<std::uint16_t>(std::floor(e * 65535.0f + 0.5f));
}
float Decode(std::uint16_t code) { return static_cast<float>(code) / 65535.0f * 2.0f - 1.0f; }

double AngleDegrees(const Float3& a, const Float3& b) {
    const double ax = a.x, ay = a.y, az = a.z, bx = b.x, by = b.y, bz = b.z;
    const double cx = ay * bz - az * by, cy = az * bx - ax * bz, cz = ax * by - ay * bx;
    return std::atan2(std::sqrt(cx * cx + cy * cy + cz * cz), ax * bx + ay * by + az * bz) * 180.0 /
           3.14159265358979323846;
}

bool WritePng(const std::filesystem::path& file, const std::vector<std::uint16_t>& rgb, std::uint32_t size,
              std::string& error) {
    std::unique_ptr<spng_ctx, decltype(&spng_ctx_free)> ctx(spng_ctx_new(SPNG_CTX_ENCODER), &spng_ctx_free);
    if (!ctx) {
        error = "spng encoder context not created";
        return false;
    }
    int rc = spng_set_option(ctx.get(), SPNG_ENCODE_TO_BUFFER, 1);
    spng_ihdr ihdr{};
    ihdr.width = size;
    ihdr.height = size;
    ihdr.bit_depth = 16;
    ihdr.color_type = SPNG_COLOR_TYPE_TRUECOLOR;
    if (rc == 0) rc = spng_set_ihdr(ctx.get(), &ihdr);
    if (rc == 0) {
        rc = spng_encode_image(ctx.get(), rgb.data(), rgb.size() * sizeof(std::uint16_t), SPNG_FMT_PNG,
                               SPNG_ENCODE_FINALIZE);
    }
    if (rc != 0) {
        error = std::string("spng_encode_image failed: ") + spng_strerror(rc);
        return false;
    }
    std::size_t bytes = 0;
    std::unique_ptr<void, decltype(&std::free)> png(spng_get_png_buffer(ctx.get(), &bytes, &rc), &std::free);
    if (!png) {
        error = std::string("spng_get_png_buffer failed: ") + spng_strerror(rc);
        return false;
    }
    std::ofstream out(file, std::ios::binary);
    out.write(static_cast<const char*>(png.get()), static_cast<std::streamsize>(bytes));
    out.close();
    if (!out) {
        error = "cannot write " + file.string();
        return false;
    }
    return true;
}

struct Options {
    std::filesystem::path low, high, out_dir;
    std::string name;
    std::uint32_t size = 0;
    double max_height = -1.0;
    double max_depth = -1.0;
};

std::optional<Options> ParseOptions(int argc, char** argv) {
    Options o;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string key = argv[i];
        const std::string value = argv[i + 1];
        if (key == "--low") o.low = value;
        else if (key == "--high") o.high = value;
        else if (key == "--out-dir") o.out_dir = value;
        else if (key == "--name") o.name = value;
        else if (key == "--size") o.size = static_cast<std::uint32_t>(std::strtoul(value.c_str(), nullptr, 10));
        else if (key == "--max-height") o.max_height = std::strtod(value.c_str(), nullptr);
        else if (key == "--max-depth") o.max_depth = std::strtod(value.c_str(), nullptr);
        else return std::nullopt;
    }
    if (argc % 2 == 0 || o.low.empty() || o.high.empty() || o.out_dir.empty() || o.name.empty() || o.size == 0 ||
        o.size > 8192 || o.max_height < 0.0 || o.max_depth < 0.0) {
        return std::nullopt;
    }
    return o;
}

int Bake(const Options& o) {
    const ImportResult low_import = ImportMeshFile(o.low, {});
    const ImportResult high_import = ImportMeshFile(o.high, {});
    if (low_import.mesh.flags.corners_without_uv != 0) {
        std::fprintf(stderr, "%s: the low mesh needs texture coordinates\n", o.low.string().c_str());
        return 1;
    }
    const TexturingMesh& low_mesh = low_import.mesh;
    const std::vector<Face> low = Faces(low_mesh);
    const std::vector<Face> high = Faces(high_import.mesh);

    const std::size_t n = o.size;
    const std::array<std::uint16_t, 3> flat{32768, 32768, 65535};
    std::vector<std::uint16_t> world(n * n * 3);
    std::vector<std::uint16_t> faces(n * n * 3, 0);
    std::array<std::array<std::vector<std::uint16_t>, 2>, 2> maps;
    for (auto& by_mode : maps) {
        for (auto& map : by_mode) map.assign(n * n * 3, 0);
    }
    for (std::size_t t = 0; t < n * n; ++t) {
        for (std::size_t c = 0; c < 3; ++c) {
            world[t * 3 + c] = flat[c];
            for (auto& by_mode : maps) {
                for (auto& map : by_mode) map[t * 3 + c] = flat[c];
            }
        }
    }
    std::vector<bool> written(n * n, false);
    std::size_t covered = 0;
    std::size_t hits = 0;
    std::array<std::array<double, 2>, 2> round_trip{};
    std::array<std::array<double, 2>, 2> round_trip_coded{};

    const double size = static_cast<double>(o.size);
    for (std::size_t f = 0; f < low.size(); ++f) {
        const auto& uv = low[f].uv;
        double min_u = 1e30, max_u = -1e30, min_v = 1e30, max_v = -1e30;
        for (const Float2& t : uv) {
            min_u = std::min(min_u, static_cast<double>(t.u));
            max_u = std::max(max_u, static_cast<double>(t.u));
            min_v = std::min(min_v, static_cast<double>(t.v));
            max_v = std::max(max_v, static_cast<double>(t.v));
        }
        const long c0 = std::max(0L, static_cast<long>(std::floor(min_u * size - 0.5)));
        const long c1 = std::min(static_cast<long>(n) - 1, static_cast<long>(std::ceil(max_u * size)));
        const long r0 = std::max(0L, static_cast<long>(std::floor((1.0 - max_v) * size - 0.5)));
        const long r1 = std::min(static_cast<long>(n) - 1, static_cast<long>(std::ceil((1.0 - min_v) * size)));
        const double ax = uv[0].u, ay = uv[0].v, bx = uv[1].u, by = uv[1].v, cx = uv[2].u, cy = uv[2].v;
        const double den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
        if (std::abs(den) < 1e-15) continue;
        for (long row = r0; row <= r1; ++row) {
            for (long col = c0; col <= c1; ++col) {
                const std::size_t texel = static_cast<std::size_t>(row) * n + static_cast<std::size_t>(col);
                if (written[texel]) continue;
                const double u = (static_cast<double>(col) + 0.5) / size;
                const double v = 1.0 - (static_cast<double>(row) + 0.5) / size;
                const double w0 = ((by - cy) * (u - cx) + (cx - bx) * (v - cy)) / den;
                const double w1 = ((cy - ay) * (u - cx) + (ax - cx) * (v - cy)) / den;
                const double w2 = 1.0 - w0 - w1;
                if (w0 < 0.0 || w1 < 0.0 || w2 < 0.0) continue;
                written[texel] = true;
                ++covered;
                faces[texel * 3] = static_cast<std::uint16_t>(f + 1);
                const std::array<float, 3> w{static_cast<float>(w0), static_cast<float>(w1), static_cast<float>(w2)};
                Float3 position{};
                Float3 normal{};
                for (std::size_t i = 0; i < 3; ++i) {
                    position = Add(position, Scale(low[f].p[i], w[i]));
                    normal = Add(normal, Scale(low[f].n[i], w[i]));
                }
                const std::optional<Hit> hit = CastRay(high, position, Normalize(normal), o.max_height, o.max_depth);
                if (!hit) {
                    for (std::size_t c = 0; c < 3; ++c) {
                        world[texel * 3 + c] = 0;
                        for (auto& by_mode : maps) {
                            for (auto& map : by_mode) map[texel * 3 + c] = 0;
                        }
                    }
                    continue;
                }
                ++hits;
                faces[texel * 3 + 1] = static_cast<std::uint16_t>(hit->face + 1);
                const std::array<float, 3> hn{hit->normal.x, hit->normal.y, hit->normal.z};
                for (std::size_t c = 0; c < 3; ++c) world[texel * 3 + c] = Encode(hn[c]);
                for (std::size_t m = 0; m < kModes.size(); ++m) {
                    const Frame frame = InterpolateFrame(low_mesh, *low[f].triangle, w, kModes[m]);
                    for (std::size_t k = 0; k < kTransforms.size(); ++k) {
                        const Float3 tangent = k == 0 ? ToTangentSpace(frame, hit->normal) : Projection(frame, hit->normal);
                        const std::array<float, 3> tc{tangent.x, tangent.y, tangent.z};
                        std::array<float, 3> decoded{};
                        for (std::size_t c = 0; c < 3; ++c) {
                            const std::uint16_t code = Encode(tc[c]);
                            maps[m][k][texel * 3 + c] = code;
                            decoded[c] = Decode(code);
                        }
                        const Float3 dn = Normalize({decoded[0], decoded[1], decoded[2]});
                        const Float3 back = k == 0 ? FromTangentSpace(frame, tangent) : ProjectionBack(frame, tangent);
                        const Float3 back_coded = k == 0 ? FromTangentSpace(frame, dn) : ProjectionBack(frame, dn);
                        round_trip[m][k] = std::max(round_trip[m][k], AngleDegrees(back, hit->normal));
                        round_trip_coded[m][k] = std::max(round_trip_coded[m][k], AngleDegrees(back_coded, hit->normal));
                    }
                }
            }
        }
    }

    std::error_code ec;
    std::filesystem::create_directories(o.out_dir, ec);
    const auto file = [&](const std::string& suffix) { return o.out_dir / (o.name + suffix); };
    std::string error;
    bool ok = WritePng(file("-world.png"), world, o.size, error) && WritePng(file("-faces.png"), faces, o.size, error);
    for (std::size_t m = 0; ok && m < kModes.size(); ++m) {
        for (std::size_t k = 0; ok && k < kTransforms.size(); ++k) {
            const std::string stem = std::string("-") + ModeName(kModes[m]) + "-" + kTransforms[k];
            std::vector<std::uint16_t> directx = maps[m][k];
            for (std::size_t t = 0; t < n * n; ++t) {
                const bool empty = faces[t * 3] != 0 && faces[t * 3 + 1] == 0;  // no hit
                if (!empty) directx[t * 3 + 1] = static_cast<std::uint16_t>(65535 - directx[t * 3 + 1]);
            }
            ok = WritePng(file(stem + "-opengl.png"), maps[m][k], o.size, error) &&
                 WritePng(file(stem + "-directx.png"), directx, o.size, error);
        }
    }
    if (!ok) {
        std::fprintf(stderr, "%s\n", error.c_str());
        return 1;
    }
    std::ofstream summary(file("-summary.json"));
    summary.precision(9);
    summary << "{\n  \"schema\": \"uzpainter/normal-prototype-summary/1\",\n"
            << "  \"size\": " << o.size << ",\n  \"low_triangles\": " << low.size()
            << ",\n  \"high_triangles\": " << high.size() << ",\n  \"covered_texels\": " << covered
            << ",\n  \"hit_texels\": " << hits << ",\n  \"max_height\": " << o.max_height
            << ",\n  \"max_depth\": " << o.max_depth << ",\n  \"round_trip_degrees\": {";
    for (std::size_t m = 0; m < kModes.size(); ++m) {
        for (std::size_t k = 0; k < kTransforms.size(); ++k) {
            summary << (m + k == 0 ? "\n" : ",\n") << "    \"" << ModeName(kModes[m]) << "-" << kTransforms[k]
                    << "\": {\"exact\": " << round_trip[m][k] << ", \"coded\": " << round_trip_coded[m][k] << "}";
        }
    }
    summary << "\n  }\n}\n";
    summary.close();
    if (!summary) {
        std::fprintf(stderr, "cannot write %s\n", file("-summary.json").string().c_str());
        return 1;
    }
    std::printf("%s: %zu covered texels, %zu hits\n", o.name.c_str(), covered, hits);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    const std::optional<Options> options = ParseOptions(argc, argv);
    if (!options) {
        std::fprintf(stderr,
                     "usage: uzp-normal-bake --low <low.obj> --high <high.obj> --size <px> --max-height <d> "
                     "--max-depth <d> --out-dir <dir> --name <prefix>\n");
        return 2;
    }
    try {
        return Bake(*options);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
}
