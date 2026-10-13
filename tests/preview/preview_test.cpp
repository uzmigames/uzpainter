// Native tests of the preview viewport (src/preview/, rulebook task phase2.1_preview-viewport-window).
// Built by `zig build preview-tests` and driven by tests/preview/test_preview_viewport.py.
//
// Usage: uzp-preview-tests <case> <work-dir> [args]
//   display              the pinned display configuration, the unsupported ones and the display table
//   environment          decoding, the direction mapping and the IBL precomputation (CPU)
//   lighting-cache <work-dir>
//                        the persistent environment lighting (decision 253): stored cold, served warm
//                        without decoding, damaged entries and other MXCSR bits not served (CPU)
//   latest               the wait-free hand-over buffer, with a stalled reader
//   viewport-unsupported an unsupported display configuration fails before any GPU work (DX12)
//   viewport-golden <goldens.json> [--bless]
//                        the sphere, plane and bevelled-cube fixtures rendered twice: byte-identical,
//                        display codes equal to the CPU table, and equal to the stored golden of this
//                        (kernel, adapter, driver) key; `--bless` records the key's golden instead (DX12)
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` and `INFO` lines. Exit code 0 when every check
// passed, 1 when one failed, 2 on a usage error, 77 when the case needs a DX12 adapter and there
// is none.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "mesh/mesh_import.h"
#include "preview/display_transform.h"
#include "preview/environment.h"
#include "preview/latest.h"
#include "preview/viewport.h"
#include "render/engine_thread.h"
#include "render/disk_cache.h"
#include "render/kernel_cache.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"

#include "log.h"

#include <windows.h>

#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <numbers>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include <xmmintrin.h>

namespace {

using namespace uzp::preview;
namespace fs = std::filesystem;
namespace json = uzp::core::json;
using uzp::render::Engine;
using uzp::render::EngineContext;
using uzp::render::EngineOptions;
using uzp::render::Result;

constexpr int kExitSkip = 77;
int g_failures = 0;

void Check(bool ok, std::string_view name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %.*s\n", static_cast<int>(name.size()), name.data());
    } else {
        std::printf("FAIL %.*s: %s\n", static_cast<int>(name.size()), name.data(), detail.c_str());
        ++g_failures;
    }
    std::fflush(stdout);
}

void Info(const std::string& text) {
    std::printf("INFO %s\n", text.c_str());
    std::fflush(stdout);
}

int Finish() { return g_failures == 0 ? 0 : 1; }

fs::path RepoRoot() {
    // tests/preview/preview_test.cpp -> the repository root, from the source location.
    return fs::path(__FILE__).parent_path().parent_path().parent_path();
}

// ── display ──────────────────────────────────────────────────────────────────────────────────

int RunDisplay() {
    Check(!UnsupportedConfiguration(PinnedConfiguration()), "the pinned configuration (OCIO, substance config, "
                                                            "Default - sRGB) is supported");
    struct Case {
        const char* name;
        DisplayConfiguration config;
        const char* names;
    };
    const DisplayConfiguration pinned = PinnedConfiguration();
    auto with = [&](auto change) {
        DisplayConfiguration c = pinned;
        change(c);
        return c;
    };
    const Case cases[] = {
        {"Legacy Linear", with([](DisplayConfiguration& c) { c = {"", "", "Linear", "Default - sRGB"}; }),
         "Legacy colour management with tone mapping Linear"},
        {"Legacy ACES", with([](DisplayConfiguration& c) { c = {"legacy", "", "ACES", "Default - sRGB"}; }),
         "Legacy colour management with tone mapping ACES"},
        {"ACE mode", with([](DisplayConfiguration& c) { c.mode = "ace"; }), "ACE colour management"},
        {"an unknown mode", with([](DisplayConfiguration& c) { c.mode = "aces-cg"; }), "the colour-management mode"},
        {"OCIO without a config hash", with([](DisplayConfiguration& c) { c.configHash.clear(); }),
         "an OCIO project without a config hash"},
        {"another OCIO config", with([](DisplayConfiguration& c) { c.configHash = std::string(64, 'a'); }),
         "the OCIO config sha256"},
        {"another OCIO view", with([](DisplayConfiguration& c) { c.view = "ACES 1.0 - SDR Video"; }),
         "the OCIO view 'ACES 1.0 - SDR Video'"},
    };
    for (const Case& c : cases) {
        const std::optional<std::string> error = UnsupportedConfiguration(c.config);
        Check(error && error->starts_with("unsupported_configuration: ") && error->find("decision 038") != std::string::npos &&
                  error->find(c.names) != std::string::npos,
              std::string(c.name) + " is unsupported, naming what differs and decision 038", error.value_or("accepted"));
        const std::string label = DisplayLabel(c.config);
        Check(label.starts_with(c.names) && label.find(": not displayed") != std::string::npos &&
                  label.find("decision 038") != std::string::npos,
              std::string("the preview panel labels ") + c.name + " as not displayed (decision 038)", label);
    }
    Check(DisplayLabel(pinned) == "OCIO, Painter's substance config, Default - sRGB (decision 042)",
          "the preview panel labels the pinned configuration", DisplayLabel(pinned));

    // Binary16 conversions: every pattern round-trips; ties go to even.
    bool roundTrip = true;
    for (uint32_t bits = 0; bits < 65536; ++bits) {
        const float value = HalfToFloat(static_cast<uint16_t>(bits));
        if (std::isnan(value)) continue;
        if (FloatToHalf(value) != bits) roundTrip = false;
    }
    Check(roundTrip, "every binary16 pattern round-trips through float32");
    Check(FloatToHalf(1.0f + 0x1p-11f) == 0x3C00 && FloatToHalf(1.0f + 3 * 0x1p-11f) == 0x3C02 &&
              FloatToHalf(65520.0f) == 0x7C00 && FloatToHalf(0x1p-25f) == 0x0000 && FloatToHalf(0x1.8p-25f) == 0x0001,
          "float32 to binary16 rounds to nearest, ties to even, with overflow and subnormals");

    // The display table: the calibrated model of parity/semantics/iray.json `display-encoding`.
    const std::vector<uint16_t>& table = DisplayTable();
    bool exact = true;
    bool monotone = true;
    uint16_t previous = 0;
    for (uint32_t bits = 0; bits <= 0x3C00; ++bits) {  // +0 .. 1.0, ascending values
        const double linear = HalfToFloat(static_cast<uint16_t>(bits));
        if (table[bits] != static_cast<uint16_t>(std::lround(65535.0 * SrgbEncode(linear)))) exact = false;
        if (table[bits] < previous) monotone = false;
        previous = table[bits];
    }
    Check(exact, "codes of [0, 1] are round(65535 encode(L)) with the IEC 61966-2-1 encoding");
    Check(monotone, "codes are monotone over [0, 1]");
    Check(table[0x3C00] == 65535 && table[0x7C00] == 65535 && table[0x4000] == 65535, "1, 2 and +inf give 65535");
    Check(table[0x0000] == 0 && table[0x8000] == 0 && table[0xBC00] == 0 && table[0xFC00] == 0,
          "+0, -0, -1 and -inf give 0");
    Check(table[0x7E00] == 0 && table[0xFE00] == 0 && table[0x7C01] == 0, "NaN gives 0");
    Check(DisplayCode8(DisplayCode(0.1f)) == 89, "linear 0.1 (the standard's clear colour) displays as 8-bit 89",
          std::to_string(DisplayCode8(DisplayCode(0.1f))));
    Check(DisplayCode(0.8f) == table[FloatToHalf(0.8f)], "DisplayCode looks the binary16 rounding up");
    return Finish();
}

// ── environment ──────────────────────────────────────────────────────────────────────────────

std::string Bytes(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    std::ostringstream text;
    text << in.rdbuf();
    return text.str();
}

/// A Radiance HDR of `w` x 1 texels, run-length encoded when `rle`.
std::string MakeHdr(uint32_t w, bool rle) {
    std::string out = "#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X " + std::to_string(w) + "\n";
    // Texel x: mantissas (128, 64, 32) with exponent 129 + (x % 2): values 1, 0.5, 0.25 (x2 when odd).
    if (!rle) {
        for (uint32_t x = 0; x < w; ++x) {
            out += static_cast<char>(128);
            out += static_cast<char>(64);
            out += static_cast<char>(32);
            out += static_cast<char>(129 + (x % 2));
        }
        return out;
    }
    out += static_cast<char>(2);
    out += static_cast<char>(2);
    out += static_cast<char>(w >> 8);
    out += static_cast<char>(w & 255);
    for (int c = 0; c < 3; ++c) {
        out += static_cast<char>(128 + w);  // one run
        out += static_cast<char>(c == 0 ? 128 : (c == 1 ? 64 : 32));
    }
    out += static_cast<char>(w);  // literal exponents
    for (uint32_t x = 0; x < w; ++x) out += static_cast<char>(129 + (x % 2));
    return out;
}

int RunEnvironment() {
    for (const bool rle : {false, true}) {
        const std::expected<EnvironmentImage, std::string> hdr = DecodeEnvironment(MakeHdr(8, rle));
        bool values = hdr.has_value() && hdr->width == 8 && hdr->height == 1;
        for (uint32_t x = 0; values && x < 8; ++x) {
            const float scale = x % 2 ? 2.0f : 1.0f;
            values = hdr->rgb[x * 3] == 1.0f * scale && hdr->rgb[x * 3 + 1] == 0.5f * scale &&
                     hdr->rgb[x * 3 + 2] == 0.25f * scale;
        }
        Check(values, rle ? "a run-length encoded Radiance HDR decodes" : "a flat Radiance HDR decodes",
              hdr ? "wrong texels" : hdr.error());
    }
    Check(!DecodeEnvironment("not an image"), "an unknown encoding is refused");
    const std::expected<EnvironmentImage, std::string> sky =
        DecodeEnvironment(Bytes(RepoRoot() / "parity/fixtures/render-procedure/sky-patch.exr"));
    Check(sky && sky->width == 2 * sky->height, "the authored sky-patch.exr decodes as a 2:1 latitude-longitude image",
          sky ? std::to_string(sky->width) + " x " + std::to_string(sky->height) : sky.error());

    // The direction mapping round-trips with the sampler: a one-hot texel is found in its direction.
    EnvironmentImage probe = UniformEnvironment(0.0f, 0.0f, 0.0f, 64, 32);
    probe.rgb[(size_t{9} * 64 + 21) * 3] = 1.0f;
    const std::array<double, 3> d = DirectionOf((21 + 0.5) / 64, (9 + 0.5) / 32);
    Check(SampleDirection(probe, d)[0] == 1.0f, "a texel centre's direction samples that texel");
    const std::array<double, 3> rotated = DirectionOf((21 + 0.5) / 64 - 0.25, (9 + 0.5) / 32);
    Check(SampleDirection(probe, rotated, 90.0)[0] == 1.0f, "a rotation of 90 degrees shifts u by a quarter turn");
    Check(std::abs(DirectionOf(0.25, 0.5)[2] - 1.0) < 1e-12 && std::abs(DirectionOf(0.5, 0.0)[1] - 1.0) < 1e-12,
          "u = 1/4 looks along +Z and row 0 is +Y (iray.json environment-mapping)");

    // A uniform environment: irradiance pi L everywhere, every prefiltered level L.
    const EnvironmentLighting uniform = PrecomputeLighting(UniformEnvironment(0.5f, 0.25f, 1.0f));
    double worst = 0.0;
    for (const std::array<double, 3>& n : {std::array<double, 3>{0, 1, 0}, {1, 0, 0}, {0, 0, -1}, {0.6, -0.8, 0}}) {
        const std::array<float, 3> e = Irradiance(uniform, n);
        worst = std::max({worst, std::abs(e[0] / (0.5 * std::numbers::pi) - 1.0), std::abs(e[1] / (0.25 * std::numbers::pi) - 1.0),
                          std::abs(e[2] / (1.0 * std::numbers::pi) - 1.0)});
    }
    Check(worst < 2e-3, "the SH irradiance of a uniform environment is pi L in every direction",
          "relative error " + std::to_string(worst));
    bool flat = true;
    for (const RadianceLevel& level : uniform.radiance) {
        for (size_t i = 0; i < level.rgb.size(); i += 3) {
            if (std::abs(level.rgb[i] - 0.5f) > 1e-6f || std::abs(level.rgb[i + 2] - 1.0f) > 1e-6f) flat = false;
        }
    }
    Check(flat && uniform.radiance.size() == kRadianceLevels && uniform.radiance.back().width == kRadianceWidth >> 5,
          "every prefiltered level of a uniform environment is that radiance");
    bool bounded = true;
    std::string worstEntry;
    for (uint32_t row = 0; row < kBrdfTableSize; ++row) {
        for (uint32_t col = 0; col < kBrdfTableSize; ++col) {
            const std::array<float, 3> e = BrdfEntry(uniform, col, row);
            if (!(e[0] >= 0.0f && e[1] >= 0.0f && e[0] + e[1] <= 1.0f + 1e-4f && e[2] > 0.0f && e[2] < 2.0f)) {
                bounded = false;
                worstEntry = "row " + std::to_string(row) + " col " + std::to_string(col) + ": " + std::to_string(e[0]) +
                             " " + std::to_string(e[1]) + " " + std::to_string(e[2]);
            }
        }
    }
    Check(bounded, "the albedo table's A + B lies in [0, 1] (Monte-Carlo estimate, within 1e-4) and Burley's D in (0, 2)", worstEntry);
    bool mirror = true;
    for (uint32_t col = 0; col < kBrdfTableSize; ++col) {
        const std::array<float, 3> e = BrdfEntry(uniform, col, 0);
        if (std::abs(e[0] + e[1] - 1.0f) > 1e-5f) mirror = false;
    }
    Check(mirror, "a mirror (roughness 0) reflects everything: A + B = 1");
    const std::array<float, 3> rough = BrdfEntry(uniform, kBrdfTableSize - 1, kBrdfTableSize - 1);
    Check(rough[0] + rough[1] < 0.95f, "a rough lobe at normal incidence loses energy to single scattering");

    // Deterministic.
    const EnvironmentLighting a = PrecomputeLighting(*sky);
    const EnvironmentLighting b = PrecomputeLighting(*sky);
    bool same = a.sh == b.sh && a.brdf == b.brdf;
    for (size_t l = 0; same && l < kRadianceLevels; ++l) same = a.radiance[l].rgb == b.radiance[l].rgb;
    Check(same, "the precomputation is repeatable bit for bit");
    return Finish();
}

// ── latest ───────────────────────────────────────────────────────────────────────────────────

int RunLatest() {
    {
        Latest<int> latest;
        Check(!latest.Take(), "nothing is taken before a publish");
        latest.Publish(1);
        latest.Publish(2);
        const std::optional<int> taken = latest.Take();
        Check(taken == 2 && !latest.Take(), "the reader takes the newest value once");
        latest.Publish(3);
        Check(latest.Take() == 3 && latest.Published() == 3, "a later publish is taken next");
    }
    {
        // A reader stalled while holding its value never delays the publisher.
        Latest<std::shared_ptr<const int>> latest;
        std::mutex mutex;
        std::condition_variable cv;
        bool holding = false;
        bool release = false;
        std::thread reader([&] {
            latest.Publish(std::make_shared<const int>(-1));  // reader-side setup is not needed
        });
        reader.join();
        std::shared_ptr<const int> held;
        std::thread stalled([&] {
            held = *latest.Take();
            std::unique_lock lock(mutex);
            holding = true;
            cv.notify_all();
            cv.wait(lock, [&] { return release; });
        });
        {
            std::unique_lock lock(mutex);
            cv.wait(lock, [&] { return holding; });
        }
        const auto start = std::chrono::steady_clock::now();
        for (int i = 0; i < 100000; ++i) latest.Publish(std::make_shared<const int>(i));
        const auto elapsed = std::chrono::steady_clock::now() - start;
        Check(latest.Published() == 100001, "100000 publishes complete while the reader is stalled");
        Info("100000 publishes with a stalled reader took " +
             std::to_string(std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count()) + " ms");
        {
            std::lock_guard lock(mutex);
            release = true;
        }
        cv.notify_all();
        stalled.join();
        const std::optional<std::shared_ptr<const int>> last = latest.Take();
        Check(held && *held == -1 && last && **last == 99999, "after the stall the reader takes the newest value");
    }
    {
        // Concurrent: the reader only ever sees increasing values.
        Latest<int> latest;
        std::atomic<bool> done{false};
        bool increasing = true;
        int seen = -1;
        std::thread reader([&] {
            while (!done) {
                if (std::optional<int> v = latest.Take()) {
                    if (*v <= seen) increasing = false;
                    seen = *v;
                }
            }
            if (std::optional<int> v = latest.Take()) {
                if (*v <= seen) increasing = false;
                seen = *v;
            }
        });
        for (int i = 0; i < 1000000; ++i) latest.Publish(i);
        done = true;
        reader.join();
        Check(increasing && seen == 999999, "concurrent publishes are taken in order and the last one arrives",
              "last " + std::to_string(seen));
    }
    return Finish();
}

// ── GPU cases ────────────────────────────────────────────────────────────────────────────────

EngineOptions TestOptions(const fs::path& dir) {
    EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    return options;
}

bool NoAdapter(const Engine& engine) {
    if (!engine.DeviceError()) return false;
    std::printf("SKIP no DX12 device: %s\n", engine.DeviceError()->Describe().c_str());
    return true;
}

std::shared_ptr<const uzp::mesh::TexturingMesh> LoadMesh(const fs::path& relative) {
    uzp::mesh::ImportResult result = uzp::mesh::ImportMeshFile(RepoRoot() / relative, {});
    return std::make_shared<const uzp::mesh::TexturingMesh>(std::move(result.mesh));
}

int RunViewportUnsupported(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    ViewportScene scene;
    scene.mesh = LoadMesh("parity/fixtures/render-procedure/sphere.obj");
    scene.lighting = std::make_shared<const EnvironmentLighting>(PrecomputeLighting(UniformEnvironment(1, 1, 1)));
    const OrbitCamera camera = FitCamera(*scene.mesh);
    const std::pair<const char*, DisplayConfiguration> configs[] = {
        {"Legacy Linear", {"legacy", "", "Linear", "Default - sRGB"}},
        {"Legacy ACES", {"legacy", "", "ACES", "Default - sRGB"}},
        {"ACE mode", {"ace", "", "", "Default - sRGB"}},
        {"another OCIO view", {"ocio", std::string(kSubstanceConfigSha256), "", "Un-tone-mapped"}},
    };
    for (const auto& [name, config] : configs) {
        scene.display = config;
        auto snapshot = std::make_shared<const int>(0);
        uint64_t before = 0;
        uint64_t after = 0;
        Result<ViewportImage> image =
            engine
                .Submit(snapshot,
                        [&](EngineContext& context, const int&) {
                            before = context.Device().Queue().LastSubmitted();
                            Result<ViewportImage> rendered = RenderViewport(context, scene, camera, 64, 64);
                            after = context.Device().Queue().LastSubmitted();
                            return rendered;
                        })
                .get();
        const std::string reason = image ? std::string("rendered") : image.error().reason;
        Check(!image && reason.find("unsupported_configuration") != std::string::npos &&
                  reason.find("decision 038") != std::string::npos && before == after,
              std::string(name) + " fails before rendering (no submission) naming decision 038", reason);
    }
    return Finish();
}

std::string Hex64(uint64_t value) {
    char buf[24];
    std::snprintf(buf, sizeof(buf), "%016llx", static_cast<unsigned long long>(value));
    return buf;
}

std::string HashOf(const std::vector<uint16_t>& values) {
    return uzp::core::Sha256Hex(std::string_view(reinterpret_cast<const char*>(values.data()), values.size() * 2));
}

struct Fixture {
    std::string name;
    std::shared_ptr<const uzp::mesh::TexturingMesh> mesh;
    MaterialInputs material;
    double rotation = 0.0;
    double yaw = 0.0;
    double pitch = 0.0;
};

std::vector<Fixture> Fixtures() {
    std::vector<Fixture> fixtures;
    {
        Fixture f{"sphere", LoadMesh("parity/fixtures/render-procedure/sphere.obj"), {}, 0.0, 0.0, 0.0};
        f.material.roughnessValue = 0.5f;
        fixtures.push_back(std::move(f));
    }
    {
        // A checkered base colour and a tilted normal map exercise the map sampling and the
        // MikkTSpace frame.
        Fixture f{"plane", LoadMesh("parity/fixtures/iray-references/plane.obj"), {}, 45.0, 25.0, 35.0};
        MaterialMap base{8, 8, 3, {}};
        MaterialMap normal{8, 8, 3, {}};
        for (uint32_t y = 0; y < 8; ++y) {
            for (uint32_t x = 0; x < 8; ++x) {
                const float v = (x + y) % 2 ? 0.8f : 0.2f;
                base.values.insert(base.values.end(), {v, v * 0.9f, v * 0.7f});
                normal.values.insert(normal.values.end(), {x < 4 ? 0.65f : 0.35f, 0.5f, 0.9f});
            }
        }
        f.material.baseColor = std::move(base);
        f.material.normal = std::move(normal);
        f.material.roughnessValue = 0.35f;
        fixtures.push_back(std::move(f));
    }
    {
        Fixture f{"bevelled-cube", LoadMesh("parity/fixtures/iray-references/bevelled-cube.obj"), {}, 90.0, 30.0, 25.0};
        f.material.baseColorValue = {0.95f, 0.64f, 0.54f};
        f.material.metalnessValue = 1.0f;
        f.material.roughnessValue = 0.2f;
        fixtures.push_back(std::move(f));
    }
    return fixtures;
}

int RunViewportGolden(const fs::path& dir, const fs::path& goldens, bool bless) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Result<uzp::render::CapabilityReport> caps = engine.Capabilities();
    const std::string adapter = caps ? caps->adapter : "unknown";
    const std::string driver = DriverVersion(engine.Options().device.adapterIndex);
    Result<std::unique_ptr<uzp::render::DxcKernelCompiler>> compiler =
        uzp::render::DxcKernelCompiler::Load(uzp::render::DefaultDxcompilerPath());
    if (!compiler) {
        Check(false, "DXC loads", compiler.error().Describe());
        return Finish();
    }
    const std::string kernel = Hex64(ViewportKernelKey(uzp::render::KernelTarget::Dxil, (*compiler)->Version()));
    Info("key: kernel " + kernel + ", adapter " + adapter + ", driver " + driver);

    const std::expected<EnvironmentImage, std::string> sky =
        DecodeEnvironment(Bytes(RepoRoot() / "parity/fixtures/render-procedure/sky-patch.exr"));
    if (!sky) {
        Check(false, "the environment decodes", sky.error());
        return Finish();
    }
    const auto lighting = std::make_shared<const EnvironmentLighting>(PrecomputeLighting(*sky));
    const std::vector<uint16_t>& table = DisplayTable();

    json::Object results;
    constexpr uint32_t kSize = 256;
    for (const Fixture& fixture : Fixtures()) {
        ViewportScene scene;
        scene.mesh = fixture.mesh;
        scene.materials = {fixture.material};
        scene.lighting = lighting;
        scene.environmentRotationDegrees = fixture.rotation;
        OrbitCamera camera = FitCamera(*scene.mesh);
        camera.yawDegrees = fixture.yaw;
        camera.pitchDegrees = fixture.pitch;
        std::vector<ViewportImage> renders;
        for (int run = 0; run < 2; ++run) {
            Result<ViewportImage> image = engine
                                              .Submit(std::make_shared<const int>(run),
                                                      [&](EngineContext& context, const int&) {
                                                          return RenderViewport(context, scene, camera, kSize, kSize);
                                                      })
                                              .get();
            if (!image) {
                Check(false, fixture.name + " renders", image.error().Describe());
                return Finish();
            }
            renders.push_back(std::move(*image));
        }
        const ViewportImage& image = renders[0];
        Check(image.display == renders[1].display && image.linear == renders[1].linear,
              fixture.name + ": two renders are byte-identical");
        bool shared = true;
        size_t hits = 0;
        const uint16_t background = FloatToHalf(0.1f);
        for (size_t i = 0; i < image.linear.size(); ++i) {
            if (i % 4 == 3) {
                if (image.linear[i] != 0x3C00 || image.display[i] != 65535) shared = false;
                continue;
            }
            if (image.display[i] != table[image.linear[i]]) shared = false;
            if (i % 4 == 0 && image.linear[i] != background) ++hits;
        }
        Check(shared, fixture.name + ": every display code is the CPU table's code of its linear binary16 value");
        Check(image.linear[0] == background && image.display[0] == DisplayCode(0.1f),
              fixture.name + ": the corner shows the clear colour 0.1");
        Check(hits > kSize * kSize / 20, fixture.name + ": the fixture covers part of the frame",
              std::to_string(hits) + " pixels differ from the clear colour");
        const size_t centre = (size_t{kSize / 2} * kSize + kSize / 2) * 4;
        Check(image.linear[centre] != background, fixture.name + ": the centre pixel shows the fixture");
        results[fixture.name] =
            json::Object{{"display_sha256", HashOf(image.display)}, {"linear_sha256", HashOf(image.linear)}};
        Info(fixture.name + " display " + HashOf(image.display) + " linear " + HashOf(image.linear));
        std::ofstream(dir / (fixture.name + ".display.rgba16"), std::ios::binary)
            .write(reinterpret_cast<const char*>(image.display.data()),
                   static_cast<std::streamsize>(image.display.size() * 2));
        std::ofstream(dir / (fixture.name + ".linear.rgba16"), std::ios::binary)
            .write(reinterpret_cast<const char*>(image.linear.data()),
                   static_cast<std::streamsize>(image.linear.size() * 2));
    }

    // The goldens file: {"schema", "entries": [{"kernel", "adapter", "driver", "size", "fixtures"}]}.
    json::Object file{{"schema", "uzpainter/preview/viewport-goldens/1"}, {"entries", json::Array{}}};
    if (fs::exists(goldens)) file = std::get<json::Object>(json::Parse(Bytes(goldens)).data);
    json::Array& entries = std::get<json::Array>(file["entries"].data);
    json::Object* match = nullptr;
    for (json::Value& entry : entries) {
        json::Object& e = std::get<json::Object>(entry.data);
        if (e["kernel"] == json::Value(kernel) && e["adapter"] == json::Value(adapter) && e["driver"] == json::Value(driver)) {
            match = &e;
        }
    }
    if (bless) {
        json::Object entry{{"kernel", kernel},
                           {"adapter", adapter},
                           {"driver", driver},
                           {"size", static_cast<std::int64_t>(kSize)},
                           {"fixtures", results}};
        if (match) {
            *match = std::move(entry);
        } else {
            entries.push_back(std::move(entry));
        }
        std::ofstream(goldens, std::ios::binary) << json::WriteCanonical(json::Value(file)) << "\n";
        Info("blessed " + goldens.string());
        return Finish();
    }
    if (!match) {
        Check(false, "the goldens hold this (kernel, adapter, driver) key",
              "no entry for kernel " + kernel + ", adapter " + adapter + ", driver " + driver +
                  "; run with --bless on the owner's machine to record it");
        return Finish();
    }
    const json::Object& stored = std::get<json::Object>((*match)["fixtures"].data);
    for (const auto& [name, value] : results) {
        const auto it = stored.find(name);
        Check(it != stored.end() && it->second == value, name + ": equals the stored regression golden",
              it == stored.end() ? "missing" : json::WriteCanonical(it->second) + " != " + json::WriteCanonical(value));
    }
    return Finish();
}

/// Every float of two lightings has the same bits.
bool SameLighting(const EnvironmentLighting& a, const EnvironmentLighting& b) {
    auto bits = [](std::span<const float> x, std::span<const float> y) {
        return x.size() == y.size() && std::memcmp(x.data(), y.data(), x.size() * sizeof(float)) == 0;
    };
    if (!bits(a.sh, b.sh) || !bits(a.brdf, b.brdf) || a.radiance.size() != b.radiance.size()) return false;
    for (size_t l = 0; l < a.radiance.size(); ++l) {
        const RadianceLevel& x = a.radiance[l];
        const RadianceLevel& y = b.radiance[l];
        if (x.width != y.width || x.height != y.height || std::bit_cast<uint32_t>(x.roughness) != std::bit_cast<uint32_t>(y.roughness) ||
            !bits(x.rgb, y.rgb)) {
            return false;
        }
    }
    return true;
}

/// `lighting-cache <work-dir>`: the persistent environment lighting (`LightingOf`, decision 253).
/// Cold, the file is decoded and precomputed bit for bit and stored; warm, the stored lighting is
/// served without the file being decoded (garbage bytes in its place); a damaged entry and other
/// MXCSR control bits are not served.
int RunLightingCache(const fs::path& dir) {
    const std::string bytes = Bytes(RepoRoot() / "parity/fixtures/render-procedure/sky-patch.exr");
    const std::string sha256 = uzp::core::Sha256Hex(bytes);
    const fs::path root = dir / "cache";
    std::error_code ec;
    fs::remove_all(root, ec);
    const std::expected<EnvironmentImage, std::string> image = DecodeEnvironment(bytes);
    if (!image) {
        Check(false, "sky-patch.exr decodes", image.error());
        return Finish();
    }
    const EnvironmentLighting reference = PrecomputeLighting(*image);
    constexpr std::string_view kGarbage = "not an environment file";

    uzp::render::DisableCaches();
    const std::expected<EnvironmentLighting, std::string> off = LightingOf(sha256, bytes);
    Check(off && SameLighting(*off, reference) && !fs::exists(root),
          "without the caches the lighting is precomputed and nothing is stored");
    uzp::render::EnableCaches(root);
    const fs::path entry = [&] {
        const std::expected<EnvironmentLighting, std::string> cold = LightingOf(sha256, bytes);
        Check(cold && SameLighting(*cold, reference), "cold: the lighting is precomputed bit for bit");
        std::vector<fs::path> files;
        for (fs::directory_iterator it(root / "lighting", ec), end; !ec && it != end; it.increment(ec)) {
            files.push_back(it->path());
        }
        Check(files.size() == 1, "cold: one entry is stored in the lighting area", std::to_string(files.size()));
        return files.empty() ? fs::path() : files.front();
    }();
    const std::expected<EnvironmentLighting, std::string> warm = LightingOf(sha256, kGarbage);
    Check(warm && SameLighting(*warm, reference),
          "warm: the stored lighting is served bit for bit without decoding the environment file",
          warm ? std::string() : warm.error());

    {
        std::string stored;
        {
            std::ifstream in(entry, std::ios::binary);
            stored.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
        }
        stored.back() = static_cast<char>(~stored.back());
        std::ofstream(entry, std::ios::binary | std::ios::trunc).write(stored.data(), static_cast<std::streamsize>(stored.size()));
    }
    const std::expected<EnvironmentLighting, std::string> damaged = LightingOf(sha256, kGarbage);
    const std::expected<EnvironmentLighting, std::string> rebuilt = LightingOf(sha256, bytes);
    const std::expected<EnvironmentLighting, std::string> served = LightingOf(sha256, kGarbage);
    Check(!damaged && rebuilt && SameLighting(*rebuilt, reference) && served && SameLighting(*served, reference),
          "a damaged entry is not served (the file is decoded again), then recomputed bit for bit, stored and served");

    const unsigned int saved = _mm_getcsr();
    _mm_setcsr(saved | 0x8040u);  // flush-to-zero and denormals-are-zero
    const std::expected<EnvironmentLighting, std::string> flushed = LightingOf(sha256, kGarbage);
    _mm_setcsr(saved);
    Check(!flushed, "under other MXCSR control bits the stored lighting is not served");
    uzp::render::DisableCaches();
    return Finish();
}

}  // namespace

int main(int argc, char** argv) {
    const std::string_view mode = argc > 1 ? argv[1] : "";
    if (mode == "display") return RunDisplay();
    if (mode == "environment") return RunEnvironment();
    if (mode == "latest") return RunLatest();
    if (argc < 3) {
        std::fprintf(stderr,
                     "usage: uzp-preview-tests display | environment | latest | lighting-cache <work-dir> | viewport-unsupported <work-dir> | "
                     "viewport-golden <work-dir> <goldens.json> [--bless]\n");
        return 2;
    }
    const fs::path dir = argv[2];
    std::error_code ec;
    fs::create_directories(dir, ec);
    uz::LogInit((dir / ("preview-tests-" + std::string(mode) + ".log")).string().c_str());
    uz::LogSuppressConsole();
    int code = 2;
    if (mode == "viewport-unsupported") {
        code = RunViewportUnsupported(dir);
    } else if (mode == "lighting-cache") {
        code = RunLightingCache(dir);
    } else if (mode == "viewport-golden" && argc >= 4) {
        code = RunViewportGolden(dir, argv[3], argc >= 5 && std::string_view(argv[4]) == "--bless");
    } else {
        std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    }
    uz::LogShutdown();
    return code;
}
