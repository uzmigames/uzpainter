// uzp-normal-prototype.exe: the Phase 0 tangent-frame prototype of the normal-convention fixture
// (rulebook task phase0.9_normal-convention-fixture, docs/architecture/12-mesh-import.md §3).
//
// It bakes the tangent-space normal of a low/high OBJ pair the way a texture-space baker does:
// every texel centre inside a low-poly UV triangle is interpolated from the triangle's corners,
// a ray along the interpolated low-poly normal finds the high-poly triangle, and the high-poly
// normal there is expressed in the low-poly tangent frame. Per-corner frames come from
// Mikkelsen's reference mikktspace.c (thirdparty/mikktspace/, genTangSpaceDefault). Two frame
// modes are written:
//   PerVertex    vB = sum_i w_i * sign_i * cross(n_i, t_i)   (the bitangent interpolated)
//   PerFragment  vB = sign * cross(vN, vT)                    (rebuilt per texel)
// with vN = sum_i w_i n_i and vT = sum_i w_i t_i unnormalized, and two ways of expressing the
// normal n in a frame:
//   inverse      the exact inverse of the shading transform normalize(x vT + y vB + z vN), as
//                the comment of mikktspace.h prescribes for normal-map samplers
//   projection   normalize(dot(n, T), dot(n, B), dot(n, N)) with T, B, N normalized
// Outputs (16-bit RGB PNG, row 0 is v = 1, UNORM16 of x / 2 + 1 / 2 rounded to nearest):
//   <name>-world.png                           the high-poly normal in world space
//   <name>-<mode>-<transform>-opengl.png        tangent-space normal, green = +bitangent
//   <name>-<mode>-<transform>-directx.png       the DirectX conversion: green code 65535 - g
//                                              (texels without a hit stay 0)
//   <name>-faces.png                           R = low triangle + 1, G = high triangle + 1
//   <name>-summary.json                        counts and round-trip errors
// Texels outside the UV triangles hold the flat normal (32768, 32768, 65535) and face 0. Texels
// inside them whose ray hits nothing hold 0 in every channel, as Painter's bake leaves them
// before its dilation (parity/reports/phase0/normal-convention.md).

#include <mikktspace.h>
#include <spng.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace {

using Vec3 = std::array<float, 3>;
using Vec2 = std::array<float, 2>;

Vec3 Add(const Vec3& a, const Vec3& b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
Vec3 Sub(const Vec3& a, const Vec3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
Vec3 Scale(const Vec3& a, float s) { return {a[0] * s, a[1] * s, a[2] * s}; }
float Dot(const Vec3& a, const Vec3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
Vec3 Cross(const Vec3& a, const Vec3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
Vec3 Normalize(const Vec3& a) { return Scale(a, 1.0f / std::sqrt(Dot(a, a))); }

// A triangle mesh read from an OBJ file, attributes per corner (`f p/t/n` or `f p//n`).
struct Mesh {
    std::vector<std::array<Vec3, 3>> positions;
    std::vector<std::array<Vec3, 3>> normals;
    std::vector<std::array<Vec2, 3>> uvs;  // empty for a mesh without texture coordinates
    // Filled by mikktspace for the low mesh.
    std::vector<std::array<Vec3, 3>> tangents;
    std::vector<std::array<float, 3>> signs;
};

std::optional<Mesh> ReadObj(const std::filesystem::path& path, std::string& error) {
    std::ifstream in(path);
    if (!in) {
        error = "cannot read " + path.string();
        return std::nullopt;
    }
    std::vector<Vec3> v;
    std::vector<Vec3> vn;
    std::vector<Vec2> vt;
    Mesh mesh;
    bool allUv = true;
    std::string line;
    while (std::getline(in, line)) {
        std::istringstream words(line);
        std::string kind;
        words >> kind;
        if (kind == "v") {
            Vec3 p{};
            words >> p[0] >> p[1] >> p[2];
            v.push_back(p);
        } else if (kind == "vn") {
            Vec3 n{};
            words >> n[0] >> n[1] >> n[2];
            vn.push_back(n);
        } else if (kind == "vt") {
            Vec2 t{};
            words >> t[0] >> t[1];
            vt.push_back(t);
        } else if (kind == "f") {
            std::array<Vec3, 3> p{};
            std::array<Vec3, 3> n{};
            std::array<Vec2, 3> t{};
            std::string token;
            int corner = 0;
            while (words >> token) {
                if (corner == 3) {
                    error = path.string() + ": only triangles are supported";
                    return std::nullopt;
                }
                const size_t first = token.find('/');
                const size_t second = token.find('/', first + 1);
                if (first == std::string::npos || second == std::string::npos) {
                    error = path.string() + ": faces need normals (p/t/n or p//n): " + token;
                    return std::nullopt;
                }
                const long pi = std::strtol(token.substr(0, first).c_str(), nullptr, 10) - 1;
                const std::string ts = token.substr(first + 1, second - first - 1);
                const long ni = std::strtol(token.substr(second + 1).c_str(), nullptr, 10) - 1;
                if (pi < 0 || static_cast<size_t>(pi) >= v.size() || ni < 0 ||
                    static_cast<size_t>(ni) >= vn.size()) {
                    error = path.string() + ": index out of range: " + token;
                    return std::nullopt;
                }
                p[corner] = v[static_cast<size_t>(pi)];
                n[corner] = vn[static_cast<size_t>(ni)];
                if (ts.empty()) {
                    allUv = false;
                } else {
                    const long ti = std::strtol(ts.c_str(), nullptr, 10) - 1;
                    if (ti < 0 || static_cast<size_t>(ti) >= vt.size()) {
                        error = path.string() + ": texture index out of range: " + token;
                        return std::nullopt;
                    }
                    t[corner] = vt[static_cast<size_t>(ti)];
                }
                ++corner;
            }
            if (corner != 3) {
                error = path.string() + ": only triangles are supported";
                return std::nullopt;
            }
            mesh.positions.push_back(p);
            mesh.normals.push_back(n);
            mesh.uvs.push_back(t);
        }
    }
    if (!allUv) mesh.uvs.clear();
    if (mesh.positions.empty()) {
        error = path.string() + ": no triangles";
        return std::nullopt;
    }
    return mesh;
}

// ---- mikktspace callbacks -------------------------------------------------------------------

Mesh& MeshOf(const SMikkTSpaceContext* context) { return *static_cast<Mesh*>(context->m_pUserData); }
int NumFaces(const SMikkTSpaceContext* context) {
    return static_cast<int>(MeshOf(context).positions.size());
}
int NumVerticesOfFace(const SMikkTSpaceContext*, const int) { return 3; }
void GetPosition(const SMikkTSpaceContext* context, float out[], const int face, const int vert) {
    const Vec3& p = MeshOf(context).positions[static_cast<size_t>(face)][static_cast<size_t>(vert)];
    std::copy(p.begin(), p.end(), out);
}
void GetNormal(const SMikkTSpaceContext* context, float out[], const int face, const int vert) {
    const Vec3& n = MeshOf(context).normals[static_cast<size_t>(face)][static_cast<size_t>(vert)];
    std::copy(n.begin(), n.end(), out);
}
void GetTexCoord(const SMikkTSpaceContext* context, float out[], const int face, const int vert) {
    const Vec2& t = MeshOf(context).uvs[static_cast<size_t>(face)][static_cast<size_t>(vert)];
    std::copy(t.begin(), t.end(), out);
}
void SetTSpaceBasic(const SMikkTSpaceContext* context, const float tangent[], const float sign,
                    const int face, const int vert) {
    Mesh& mesh = MeshOf(context);
    mesh.tangents[static_cast<size_t>(face)][static_cast<size_t>(vert)] = {tangent[0], tangent[1],
                                                                           tangent[2]};
    mesh.signs[static_cast<size_t>(face)][static_cast<size_t>(vert)] = sign;
}

bool GenerateFrames(Mesh& mesh) {
    mesh.tangents.assign(mesh.positions.size(), {});
    mesh.signs.assign(mesh.positions.size(), {});
    SMikkTSpaceInterface callbacks{};
    callbacks.m_getNumFaces = NumFaces;
    callbacks.m_getNumVerticesOfFace = NumVerticesOfFace;
    callbacks.m_getPosition = GetPosition;
    callbacks.m_getNormal = GetNormal;
    callbacks.m_getTexCoord = GetTexCoord;
    callbacks.m_setTSpaceBasic = SetTSpaceBasic;
    SMikkTSpaceContext context{&callbacks, &mesh};
    return genTangSpaceDefault(&context) != 0;
}

// ---- ray cast against the high mesh ---------------------------------------------------------

struct Hit {
    size_t face;
    Vec3 normal;  // interpolated high-poly normal, normalized
};

// Rays start on the cage, `maxHeight` along the direction, and travel back through the low
// surface down to `maxDepth` below it; the first hit from the cage is used, and triangles seen
// from behind (geometric normal facing away from the cage) are ignored.
std::optional<Hit> CastRay(const Mesh& high, const Vec3& origin, const Vec3& direction,
                           double maxHeight, double maxDepth) {
    std::optional<Hit> best;
    double bestT = -maxDepth;
    for (size_t f = 0; f < high.positions.size(); ++f) {
        const auto& p = high.positions[f];
        const Vec3 e1 = Sub(p[1], p[0]);
        const Vec3 e2 = Sub(p[2], p[0]);
        if (Dot(Cross(e1, e2), direction) <= 0.0f) continue;  // backface seen from the cage
        // Moeller-Trumbore in double precision.
        const std::array<double, 3> d{direction[0], direction[1], direction[2]};
        const std::array<double, 3> a{e1[0], e1[1], e1[2]};
        const std::array<double, 3> b{e2[0], e2[1], e2[2]};
        const std::array<double, 3> pv{d[1] * b[2] - d[2] * b[1], d[2] * b[0] - d[0] * b[2],
                                       d[0] * b[1] - d[1] * b[0]};
        const double det = a[0] * pv[0] + a[1] * pv[1] + a[2] * pv[2];
        if (std::abs(det) < 1e-18) continue;
        const std::array<double, 3> s{origin[0] - p[0][0], origin[1] - p[0][1],
                                      origin[2] - p[0][2]};
        const double u = (s[0] * pv[0] + s[1] * pv[1] + s[2] * pv[2]) / det;
        if (u < 0.0 || u > 1.0) continue;
        const std::array<double, 3> qv{s[1] * a[2] - s[2] * a[1], s[2] * a[0] - s[0] * a[2],
                                       s[0] * a[1] - s[1] * a[0]};
        const double v = (d[0] * qv[0] + d[1] * qv[1] + d[2] * qv[2]) / det;
        if (v < 0.0 || u + v > 1.0) continue;
        const double t = (b[0] * qv[0] + b[1] * qv[1] + b[2] * qv[2]) / det;
        if (t > maxHeight || t < -maxDepth || t <= bestT) continue;
        bestT = t;
        const auto& n = high.normals[f];
        const float w0 = static_cast<float>(1.0 - u - v);
        const Vec3 normal = Add(Add(Scale(n[0], w0), Scale(n[1], static_cast<float>(u))),
                                Scale(n[2], static_cast<float>(v)));
        best = Hit{f, Normalize(normal)};
    }
    return best;
}

// ---- frames ---------------------------------------------------------------------------------

enum class Mode { PerVertex, PerFragment };
enum class Transform { Inverse, Projection };

constexpr std::array<Mode, 2> kModes{Mode::PerVertex, Mode::PerFragment};
constexpr std::array<Transform, 2> kTransforms{Transform::Inverse, Transform::Projection};
const char* Name(Mode mode) { return mode == Mode::PerVertex ? "PerVertex" : "PerFragment"; }
const char* Name(Transform t) { return t == Transform::Inverse ? "inverse" : "projection"; }

struct Frame {
    Vec3 t;  // unnormalized interpolated tangent
    Vec3 b;  // bitangent of the mode
    Vec3 n;  // unnormalized interpolated normal
};

Frame FrameAt(const Mesh& low, size_t face, const std::array<float, 3>& w, Mode mode) {
    Frame frame{};
    float sign = 0.0f;
    for (size_t i = 0; i < 3; ++i) {
        frame.t = Add(frame.t, Scale(low.tangents[face][i], w[i]));
        frame.n = Add(frame.n, Scale(low.normals[face][i], w[i]));
        sign += w[i] * low.signs[face][i];
        if (mode == Mode::PerVertex) {
            const Vec3 corner = Scale(Cross(low.normals[face][i], low.tangents[face][i]),
                                      low.signs[face][i]);
            frame.b = Add(frame.b, Scale(corner, w[i]));
        }
    }
    if (mode == Mode::PerFragment) frame.b = Scale(Cross(frame.n, frame.t), sign < 0 ? -1.0f : 1.0f);
    return frame;
}

Vec3 ToTangent(const Frame& f, const Vec3& n, Transform transform) {
    if (transform == Transform::Inverse) {
        const Vec3 row0 = Cross(f.b, f.n);
        const Vec3 row1 = Cross(f.n, f.t);
        const Vec3 row2 = Cross(f.t, f.b);
        const float sign = Dot(f.t, row0) < 0 ? -1.0f : 1.0f;
        return Normalize(Scale({Dot(n, row0), Dot(n, row1), Dot(n, row2)}, sign));
    }
    return Normalize({Dot(n, Normalize(f.t)), Dot(n, Normalize(f.b)), Dot(n, Normalize(f.n))});
}

Vec3 FromTangent(const Frame& f, const Vec3& t, Transform transform) {
    if (transform == Transform::Inverse) {
        return Normalize(Add(Add(Scale(f.t, t[0]), Scale(f.b, t[1])), Scale(f.n, t[2])));
    }
    return Normalize(Add(Add(Scale(Normalize(f.t), t[0]), Scale(Normalize(f.b), t[1])),
                         Scale(Normalize(f.n), t[2])));
}

uint16_t Encode(float x) {
    const float e = std::clamp(x * 0.5f + 0.5f, 0.0f, 1.0f);
    return static_cast<uint16_t>(std::floor(e * 65535.0f + 0.5f));
}
float Decode(uint16_t code) { return static_cast<float>(code) / 65535.0f * 2.0f - 1.0f; }

// The angle between two directions, atan2(|a x b|, a . b) in double precision (accurate for
// nearly equal vectors, unlike acos of the dot product).
double AngleDegrees(const Vec3& a, const Vec3& b) {
    const double ax = a[0], ay = a[1], az = a[2], bx = b[0], by = b[1], bz = b[2];
    const double cx = ay * bz - az * by, cy = az * bx - ax * bz, cz = ax * by - ay * bx;
    const double sine = std::sqrt(cx * cx + cy * cy + cz * cz);
    return std::atan2(sine, ax * bx + ay * by + az * bz) * 180.0 / 3.14159265358979323846;
}

// ---- output ---------------------------------------------------------------------------------

bool WritePng(const std::filesystem::path& file, const std::vector<uint16_t>& rgb, uint32_t size,
              std::string& error) {
    std::unique_ptr<spng_ctx, decltype(&spng_ctx_free)> ctx(spng_ctx_new(SPNG_CTX_ENCODER),
                                                           &spng_ctx_free);
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
    // SPNG_FMT_PNG takes host-endian 16-bit samples and writes them big-endian.
    if (rc == 0) {
        rc = spng_encode_image(ctx.get(), rgb.data(), rgb.size() * sizeof(uint16_t), SPNG_FMT_PNG,
                               SPNG_ENCODE_FINALIZE);
    }
    if (rc != 0) {
        error = std::string("spng_encode_image failed: ") + spng_strerror(rc);
        return false;
    }
    size_t bytes = 0;
    std::unique_ptr<void, decltype(&std::free)> png(spng_get_png_buffer(ctx.get(), &bytes, &rc),
                                                    &std::free);
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
    std::filesystem::path low;
    std::filesystem::path high;
    std::filesystem::path outDir;
    std::string name;
    uint32_t size = 0;
    double maxHeight = -1.0;
    double maxDepth = -1.0;
};

std::optional<Options> ParseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string key = argv[i];
        const std::string value = argv[i + 1];
        if (key == "--low") {
            options.low = value;
        } else if (key == "--high") {
            options.high = value;
        } else if (key == "--out-dir") {
            options.outDir = value;
        } else if (key == "--name") {
            options.name = value;
        } else if (key == "--size") {
            options.size = static_cast<uint32_t>(std::strtoul(value.c_str(), nullptr, 10));
        } else if (key == "--max-height") {
            options.maxHeight = std::strtod(value.c_str(), nullptr);
        } else if (key == "--max-depth") {
            options.maxDepth = std::strtod(value.c_str(), nullptr);
        } else {
            return std::nullopt;
        }
    }
    if (argc % 2 == 0 || options.low.empty() || options.high.empty() || options.outDir.empty() ||
        options.name.empty() || options.size == 0 || options.size > 8192 ||
        options.maxHeight < 0.0 || options.maxDepth < 0.0) {
        return std::nullopt;
    }
    return options;
}

constexpr int kExitOk = 0;
constexpr int kExitFailure = 1;
constexpr int kExitUsage = 2;

}  // namespace

int main(int argc, char** argv) {
    const std::optional<Options> parsed = ParseOptions(argc, argv);
    if (!parsed) {
        std::fprintf(stderr,
                     "usage: uzp-normal-prototype.exe --low <low.obj> --high <high.obj> --size <px> "
                     "--max-height <d> --max-depth <d> --out-dir <dir> --name <prefix>\n");
        return kExitUsage;
    }
    const Options& o = *parsed;
    std::string error;
    std::optional<Mesh> low = ReadObj(o.low, error);
    std::optional<Mesh> high = low ? ReadObj(o.high, error) : std::nullopt;
    if (!low || !high) {
        std::fprintf(stderr, "%s\n", error.c_str());
        return kExitFailure;
    }
    if (low->uvs.empty()) {
        std::fprintf(stderr, "%s: the low mesh needs texture coordinates\n", o.low.string().c_str());
        return kExitFailure;
    }
    if (!GenerateFrames(*low)) {
        std::fprintf(stderr, "mikktspace: genTangSpaceDefault failed\n");
        return kExitFailure;
    }

    const size_t n = static_cast<size_t>(o.size);
    const std::array<uint16_t, 3> flat{32768, 32768, 65535};
    std::vector<uint16_t> world(n * n * 3);
    std::vector<uint16_t> faces(n * n * 3, 0);
    std::array<std::array<std::vector<uint16_t>, 2>, 2> maps;
    for (auto& byMode : maps) {
        for (auto& map : byMode) map.assign(n * n * 3, 0);
    }
    for (size_t t = 0; t < n * n; ++t) {
        for (size_t c = 0; c < 3; ++c) {
            world[t * 3 + c] = flat[c];
            for (auto& byMode : maps) {
                for (auto& map : byMode) map[t * 3 + c] = flat[c];
            }
        }
    }
    std::vector<bool> written(n * n, false);
    size_t covered = 0;
    size_t hits = 0;
    std::array<std::array<double, 2>, 2> roundTrip{};      // before quantisation, degrees
    std::array<std::array<double, 2>, 2> roundTripCoded{};  // after decoding the codes

    const double size = static_cast<double>(o.size);
    for (size_t f = 0; f < low->positions.size(); ++f) {
        const auto& uv = low->uvs[f];
        double minU = 1e30, maxU = -1e30, minV = 1e30, maxV = -1e30;
        for (const Vec2& t : uv) {
            minU = std::min(minU, static_cast<double>(t[0]));
            maxU = std::max(maxU, static_cast<double>(t[0]));
            minV = std::min(minV, static_cast<double>(t[1]));
            maxV = std::max(maxV, static_cast<double>(t[1]));
        }
        const long c0 = std::max(0L, static_cast<long>(std::floor(minU * size - 0.5)));
        const long c1 = std::min(static_cast<long>(n) - 1, static_cast<long>(std::ceil(maxU * size)));
        const long r0 = std::max(0L, static_cast<long>(std::floor((1.0 - maxV) * size - 0.5)));
        const long r1 =
            std::min(static_cast<long>(n) - 1, static_cast<long>(std::ceil((1.0 - minV) * size)));
        const double ax = uv[0][0], ay = uv[0][1], bx = uv[1][0], by = uv[1][1];
        const double cx = uv[2][0], cy = uv[2][1];
        const double den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
        if (std::abs(den) < 1e-15) continue;
        for (long row = r0; row <= r1; ++row) {
            for (long col = c0; col <= c1; ++col) {
                const size_t texel = static_cast<size_t>(row) * n + static_cast<size_t>(col);
                if (written[texel]) continue;
                const double u = (static_cast<double>(col) + 0.5) / size;
                const double v = 1.0 - (static_cast<double>(row) + 0.5) / size;
                const double w0 = ((by - cy) * (u - cx) + (cx - bx) * (v - cy)) / den;
                const double w1 = ((cy - ay) * (u - cx) + (ax - cx) * (v - cy)) / den;
                const double w2 = 1.0 - w0 - w1;
                if (w0 < 0.0 || w1 < 0.0 || w2 < 0.0) continue;
                written[texel] = true;
                ++covered;
                faces[texel * 3] = static_cast<uint16_t>(f + 1);
                const std::array<float, 3> w{static_cast<float>(w0), static_cast<float>(w1),
                                             static_cast<float>(w2)};
                Vec3 position{};
                Vec3 normal{};
                for (size_t i = 0; i < 3; ++i) {
                    position = Add(position, Scale(low->positions[f][i], w[i]));
                    normal = Add(normal, Scale(low->normals[f][i], w[i]));
                }
                const std::optional<Hit> hit =
                    CastRay(*high, position, Normalize(normal), o.maxHeight, o.maxDepth);
                if (!hit) {
                    for (size_t c = 0; c < 3; ++c) {
                        world[texel * 3 + c] = 0;
                        for (auto& byMode : maps) {
                            for (auto& map : byMode) map[texel * 3 + c] = 0;
                        }
                    }
                    continue;
                }
                ++hits;
                faces[texel * 3 + 1] = static_cast<uint16_t>(hit->face + 1);
                for (size_t c = 0; c < 3; ++c) world[texel * 3 + c] = Encode(hit->normal[c]);
                for (size_t m = 0; m < kModes.size(); ++m) {
                    const Frame frame = FrameAt(*low, f, w, kModes[m]);
                    for (size_t k = 0; k < kTransforms.size(); ++k) {
                        const Vec3 tangent = ToTangent(frame, hit->normal, kTransforms[k]);
                        Vec3 decoded{};
                        for (size_t c = 0; c < 3; ++c) {
                            const uint16_t code = Encode(tangent[c]);
                            maps[m][k][texel * 3 + c] = code;
                            decoded[c] = Decode(code);
                        }
                        roundTrip[m][k] = std::max(
                            roundTrip[m][k],
                            AngleDegrees(FromTangent(frame, tangent, kTransforms[k]), hit->normal));
                        roundTripCoded[m][k] = std::max(
                            roundTripCoded[m][k],
                            AngleDegrees(FromTangent(frame, Normalize(decoded), kTransforms[k]),
                                         hit->normal));
                    }
                }
            }
        }
    }

    std::error_code ec;
    std::filesystem::create_directories(o.outDir, ec);
    const auto file = [&](const std::string& suffix) { return o.outDir / (o.name + suffix); };
    bool ok = WritePng(file("-world.png"), world, o.size, error) &&
              WritePng(file("-faces.png"), faces, o.size, error);
    for (size_t m = 0; ok && m < kModes.size(); ++m) {
        for (size_t k = 0; ok && k < kTransforms.size(); ++k) {
            const std::string stem = std::string("-") + Name(kModes[m]) + "-" + Name(kTransforms[k]);
            std::vector<uint16_t> directx = maps[m][k];
            for (size_t t = 0; t < n * n; ++t) {
                const bool empty = faces[t * 3] != 0 && faces[t * 3 + 1] == 0;  // no hit
                if (!empty) directx[t * 3 + 1] = 65535 - directx[t * 3 + 1];
            }
            ok = WritePng(file(stem + "-opengl.png"), maps[m][k], o.size, error) &&
                 WritePng(file(stem + "-directx.png"), directx, o.size, error);
        }
    }
    if (!ok) {
        std::fprintf(stderr, "%s\n", error.c_str());
        return kExitFailure;
    }

    std::ofstream summary(file("-summary.json"));
    summary.precision(9);
    summary << "{\n  \"schema\": \"uzpainter/normal-prototype-summary/1\",\n"
            << "  \"size\": " << o.size << ",\n  \"low_triangles\": " << low->positions.size()
            << ",\n  \"high_triangles\": " << high->positions.size()
            << ",\n  \"covered_texels\": " << covered << ",\n  \"hit_texels\": " << hits
            << ",\n  \"max_height\": " << o.maxHeight << ",\n  \"max_depth\": " << o.maxDepth
            << ",\n  \"round_trip_degrees\": {";
    for (size_t m = 0; m < kModes.size(); ++m) {
        for (size_t k = 0; k < kTransforms.size(); ++k) {
            summary << (m + k == 0 ? "\n" : ",\n") << "    \"" << Name(kModes[m]) << "-"
                    << Name(kTransforms[k]) << "\": {\"exact\": " << roundTrip[m][k]
                    << ", \"coded\": " << roundTripCoded[m][k] << "}";
        }
    }
    summary << "\n  }\n}\n";
    summary.close();
    if (!summary) {
        std::fprintf(stderr, "cannot write %s\n", file("-summary.json").string().c_str());
        return kExitFailure;
    }
    std::printf("%s: %zu covered texels, %zu hits\n", o.name.c_str(), covered, hits);
    return kExitOk;
}
