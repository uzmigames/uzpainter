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
//   viewport-spirv       compile/inspect the three Vulkan shader variants without a GPU
//   viewport-backend <work-dir> dx12|vulkan
//                        qualified native-test device only: repeated fixture captures and CPU
//                        visibility checks, with backend/adapter/driver in backend-report.json
//   viewport-unsupported an unsupported display configuration fails before any GPU work (DX12)
//   viewport-normal-fade a normal map tilted past the viewer's horizon shades continuously (DX12)
//   viewport-golden <goldens.json> [--bless]
//                        the sphere, plane, bevelled-cube and cube-on-plane fixtures rendered twice:
//                        byte-identical, display codes equal to the CPU table, and equal to the stored
//                        golden of this (kernel, adapter, driver) key; `--bless` records the key's
//                        golden instead (DX12)
//   viewport-visibility  the self-occlusion of decision 251: the closed box, the traversal against
//                        every triangle, the thin gap, the shared edges, the shadow geometry predicts,
//                        per-channel ratios, no self-shadowing on flat and convex surfaces, the
//                        estimator against a high-count render, the BVH cache (DX12)
//   viewport-occlusion   the AO mesh map's cone of decision 257: an AO of 1 changes no pixel, a normal
//                        map alone darkens nothing, an AO of 0 gives exactly 0, the cone's calibration
//                        against 1024-ray renders, grazing against normal light, the specular occlusion
//                        over roughness and view, mirrored and scaled UVs, and the overlap with the
//                        BVH's occlusion (reported) (DX12)
//   viewport-occlusion-time <mesh> <environment>
//                        times renders of a mesh without and with an AO map at the window's default size
//                        and at 1700 x 1250 (DX12)
//   viewport-ladder <mesh> <environment> [<report.json>]
//                        measures the visibility ray counts (8, 4) to (256, 128), doubling, on a mesh at
//                        the preview window's default view (660 x 600) and at 1700 x 1250: render times,
//                        the BVH build time and the RMSE against a (1024, 1024) render (DX12)
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
#include "preview/visibility.h"
#include "render/engine_thread.h"
#include "render/disk_cache.h"
#include "render/kernel_cache.h"
#include "render/vulkan_backend.h"
#include "render/vulkan_kernels.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"

#include "log.h"

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <numbers>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <tuple>
#include <vector>

#include <xmmintrin.h>
#include "../no_error_dialogs.h"

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

    // The importance distribution of the visibility rays (decision 251).
    const auto cdfValid = [](const std::vector<float>& cdf, size_t offset, size_t size) {
        if (cdf[offset] != 0.0f || cdf[offset + size - 1] != 1.0f) return false;
        for (size_t i = 1; i < size; ++i) {
            if (cdf[offset + i] < cdf[offset + i - 1]) return false;
        }
        return true;
    };
    const ImportanceDistribution& skyImportance = PrecomputeLighting(*sky).importance;
    bool cdfs = skyImportance.width == kRadianceWidth && skyImportance.height == kRadianceWidth / 2 &&
                skyImportance.marginalCdf.size() == skyImportance.height + 1 &&
                skyImportance.conditionalCdf.size() == size_t{skyImportance.height} * (skyImportance.width + 1) &&
                cdfValid(skyImportance.marginalCdf, 0, skyImportance.height + 1);
    for (uint32_t y = 0; cdfs && y < skyImportance.height; ++y) {
        cdfs = cdfValid(skyImportance.conditionalCdf, size_t{y} * (skyImportance.width + 1), skyImportance.width + 1);
    }
    Check(cdfs, "the importance distribution's marginal and conditional CDFs rise from 0 to 1");
    // One bright texel of a 64 x 32 image covers an 8 x 8 block of the level-0 radiance; its mass
    // is its light times sin(theta) over that of the whole image, row by row (in double).
    EnvironmentImage spot = UniformEnvironment(0.01f, 0.01f, 0.01f, 64, 32);
    for (int c = 0; c < 3; ++c) spot.rgb[(size_t{9} * 64 + 21) * 3 + static_cast<size_t>(c)] = 1000.0f;
    const ImportanceDistribution& spotImportance = PrecomputeLighting(spot).importance;
    double spotMass = 0.0;
    double spotLight = 0.0;
    double allLight = 0.0;
    for (uint32_t y = 0; y < spotImportance.height; ++y) {
        const double sinTheta = std::sin(std::numbers::pi * (y + 0.5) / spotImportance.height);
        const bool spotRow = y >= 9 * 8 && y < 10 * 8;
        allLight += sinTheta * (spotRow ? (spotImportance.width - 8) * 0.01 + 8 * 1000.0 : spotImportance.width * 0.01);
        if (!spotRow) continue;
        spotLight += sinTheta * 8 * 1000.0;
        const double row = static_cast<double>(spotImportance.marginalCdf[y + 1]) - spotImportance.marginalCdf[y];
        const size_t base = size_t{y} * (spotImportance.width + 1);
        spotMass += row * (static_cast<double>(spotImportance.conditionalCdf[base + 22 * 8]) -
                           spotImportance.conditionalCdf[base + 21 * 8]);
    }
    Check(std::abs(spotMass - spotLight / allLight) < 1e-5,
          "a bright texel holds the importance distribution's mass in proportion to its light",
          std::to_string(spotMass) + " vs " + std::to_string(spotLight / allLight));
    const ImportanceDistribution& dark = PrecomputeLighting(UniformEnvironment(0.0f, 0.0f, 0.0f)).importance;
    double worstUniform = 0.0;
    double sinSum = 0.0;
    for (uint32_t y = 0; y < dark.height; ++y) sinSum += std::sin(std::numbers::pi * (y + 0.5) / dark.height);
    for (uint32_t y = 0; y < dark.height; ++y) {
        const double expected = std::sin(std::numbers::pi * (y + 0.5) / dark.height) / sinSum;
        worstUniform = std::max(worstUniform, std::abs(static_cast<double>(dark.marginalCdf[y + 1]) - dark.marginalCdf[y] - expected));
        const size_t base = size_t{y} * (dark.width + 1);
        for (uint32_t x = 0; x < dark.width; ++x) {
            worstUniform = std::max(worstUniform, std::abs(static_cast<double>(dark.conditionalCdf[base + x + 1]) -
                                                           dark.conditionalCdf[base + x] - 1.0 / dark.width));
        }
    }
    Check(worstUniform < 1e-6, "an environment without light gets the uniform distribution over the sphere",
          std::to_string(worstUniform));

    // Deterministic.
    const EnvironmentLighting a = PrecomputeLighting(*sky);
    const EnvironmentLighting b = PrecomputeLighting(*sky);
    bool same = a.sh == b.sh && a.brdf == b.brdf && a.importance.marginalCdf == b.importance.marginalCdf &&
                a.importance.conditionalCdf == b.importance.conditionalCdf;
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

using P3 = std::array<float, 3>;

using UV3 = std::array<uzp::mesh::Float2, 3>;
/// The corner UVs of a triangle without its own: (0, 0), (1, 0), (0, 1).
constexpr UV3 kTriangleUvs{{{0.0f, 0.0f}, {1.0f, 0.0f}, {0.0f, 1.0f}}};

/// A mesh authored in code: one object, flat corner normals, the tangent frame of each triangle's
/// own UVs (the tangent along dP/du, the sign of dP/dv against cross(normal, tangent), as
/// MikkTSpace gives a flat triangle; none for a zero-area UV triangle), one material per
/// `material` index used.
class MeshBuilder {
public:
    // An overload, not a default argument: the bundled clang folds a const local initialised
    // through a reference parameter to the value of its constexpr default argument (decision 258's
    // tests measured the tangent of `kTriangleUvs` for every triangle).
    void Triangle(const P3& a, const P3& b, const P3& c, uint32_t material) { Triangle(a, b, c, material, kTriangleUvs); }
    void Triangle(const P3& a, const P3& b, const P3& c, uint32_t material, const UV3& uvs) {
        const P3 e1{b[0] - a[0], b[1] - a[1], b[2] - a[2]};
        const P3 e2{c[0] - a[0], c[1] - a[1], c[2] - a[2]};
        const uzp::mesh::Float3 normal{e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2],
                                       e1[0] * e2[1] - e1[1] * e2[0]};
        std::array<float, 4> tangent{};
        const double du1 = uvs[1].u - uvs[0].u;
        const double dv1 = uvs[1].v - uvs[0].v;
        const double du2 = uvs[2].u - uvs[0].u;
        const double dv2 = uvs[2].v - uvs[0].v;
        const double area = du1 * dv2 - du2 * dv1;
        if (area != 0.0) {
            std::array<double, 3> pu{};
            std::array<double, 3> pv{};
            for (size_t k = 0; k < 3; ++k) {
                pu[k] = (e1[k] * dv2 - e2[k] * dv1) / area;
                pv[k] = (e2[k] * du1 - e1[k] * du2) / area;
            }
            const double length = std::sqrt(pu[0] * pu[0] + pu[1] * pu[1] + pu[2] * pu[2]);
            const std::array<double, 3> b{normal.y * pu[2] - normal.z * pu[1], normal.z * pu[0] - normal.x * pu[2],
                                          normal.x * pu[1] - normal.y * pu[0]};
            tangent = {static_cast<float>(pu[0] / length), static_cast<float>(pu[1] / length),
                       static_cast<float>(pu[2] / length), b[0] * pv[0] + b[1] * pv[1] + b[2] * pv[2] < 0.0 ? -1.0f : 1.0f};
        }
        uzp::mesh::Triangle triangle;
        const std::array<const P3*, 3> corners{&a, &b, &c};
        for (size_t k = 0; k < 3; ++k) {
            m_mesh.positions.push_back({(*corners[k])[0], (*corners[k])[1], (*corners[k])[2]});
            uzp::mesh::Corner corner;
            corner.position = static_cast<uint32_t>(m_mesh.positions.size() - 1);
            corner.normal = normal;
            corner.uv0 = uvs[k];
            corner.tangent = tangent;
            corner.material = material;
            m_mesh.corners.push_back(corner);
            triangle.corners[k] = static_cast<uint32_t>(m_mesh.corners.size() - 1);
        }
        m_mesh.objects[0].triangles.push_back(triangle);
        while (m_mesh.materials.size() <= material) {
            m_mesh.materials.push_back({"m" + std::to_string(m_mesh.materials.size()),
                                        static_cast<uint32_t>(m_mesh.materials.size())});
        }
    }
    /// The quad a, b, c, d as the triangles (a, b, c) and (a, c, d).
    void Quad(const P3& a, const P3& b, const P3& c, const P3& d, uint32_t material) {
        Triangle(a, b, c, material);
        Triangle(a, c, d, material);
    }
    /// The quad with the corner UVs ua, ub, uc, ud.
    void QuadUv(const P3& a, const P3& b, const P3& c, const P3& d, uint32_t material,
                const std::array<uzp::mesh::Float2, 4>& uv) {
        Triangle(a, b, c, material, {uv[0], uv[1], uv[2]});
        Triangle(a, c, d, material, {uv[0], uv[2], uv[3]});
    }
    /// The six faces of the box from `lo` to `hi`, two triangles each.
    void Box(const P3& lo, const P3& hi, uint32_t material) {
        const auto at = [&](int x, int y, int z) { return P3{x ? hi[0] : lo[0], y ? hi[1] : lo[1], z ? hi[2] : lo[2]}; };
        Quad(at(0, 0, 0), at(0, 1, 0), at(1, 1, 0), at(1, 0, 0), material);  // -z
        Quad(at(0, 0, 1), at(1, 0, 1), at(1, 1, 1), at(0, 1, 1), material);  // +z
        Quad(at(0, 0, 0), at(0, 0, 1), at(0, 1, 1), at(0, 1, 0), material);  // -x
        Quad(at(1, 0, 0), at(1, 1, 0), at(1, 1, 1), at(1, 0, 1), material);  // +x
        Quad(at(0, 0, 0), at(1, 0, 0), at(1, 0, 1), at(0, 0, 1), material);  // -y
        Quad(at(0, 1, 0), at(0, 1, 1), at(1, 1, 1), at(1, 1, 0), material);  // +y
    }
    std::shared_ptr<const uzp::mesh::TexturingMesh> Build() {
        return std::make_shared<const uzp::mesh::TexturingMesh>(m_mesh);
    }

private:
    uzp::mesh::TexturingMesh m_mesh = [] {
        uzp::mesh::TexturingMesh mesh;
        mesh.objects.push_back({"fixture", uzp::mesh::kIdentity, {}});
        return mesh;
    }();
};

/// The concave fixture of decision 251: a 1.5-unit cube (texture set 1) resting on a 6 x 6 plane
/// (texture set 0) at y = 0.
std::shared_ptr<const uzp::mesh::TexturingMesh> CubeOnPlane() {
    MeshBuilder builder;
    builder.Quad({-3.0f, 0.0f, -3.0f}, {-3.0f, 0.0f, 3.0f}, {3.0f, 0.0f, 3.0f}, {3.0f, 0.0f, -3.0f}, 0);
    builder.Box({-0.75f, 0.0f, -0.75f}, {0.75f, 1.5f, 0.75f}, 1);
    return builder.Build();
}

struct Fixture {
    std::string name;
    std::shared_ptr<const uzp::mesh::TexturingMesh> mesh;
    MaterialInputs material;
    double rotation = 0.0;
    double yaw = 0.0;
    double pitch = 0.0;
    /// A second texture set's material, when the fixture has one.
    std::optional<MaterialInputs> second{};
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
    {
        // Concave (decision 251): the cube shadows the plane, another texture set.
        Fixture f{"cube-on-plane", CubeOnPlane(), {}, 30.0, 35.0, 30.0};
        f.material.roughnessValue = 0.5f;
        MaterialInputs cube;
        cube.baseColorValue = {0.9f, 0.3f, 0.2f};
        cube.roughnessValue = 0.4f;
        f.second = cube;
        fixtures.push_back(std::move(f));
    }
    return fixtures;
}

// The tilted plane under a uniform environment with a normal map whose tilt along the bitangent
// sweeps from -80 to +80 degrees across u: on one side the perturbed normal turns past the
// viewer's horizon. Fading the shading normal toward the interpolated one as its mirror reflection
// sinks toward the tangent plane (decision 256) keeps the shade a continuous function of the tilt
// there: the centre row's mean linear value varies with the tilt and no two neighbouring pixels
// differ by more than 0.02. The rule it replaces (a hard switch to the interpolated normal wherever
// the perturbed one faces away) jumped by 0.224 at the horizon: the thin dark lines along the Wand
// gem's lower edge.
int RunViewportNormalFade(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    ViewportScene scene;
    scene.mesh = LoadMesh("parity/fixtures/iray-references/plane.obj");
    MaterialInputs material;
    MaterialMap normal{256, 1, 3, {}};
    for (uint32_t x = 0; x < normal.width; ++x) {
        const double a = (-80.0 + 160.0 * (x + 0.5) / normal.width) * std::numbers::pi / 180.0;
        normal.values.insert(normal.values.end(),
                             {0.5f, static_cast<float>(0.5 + 0.5 * std::sin(a)), static_cast<float>(0.5 + 0.5 * std::cos(a))});
    }
    material.normal = std::move(normal);
    material.baseColorValue = {0.5f, 0.5f, 0.5f};
    material.roughnessValue = 0.2f;
    scene.materials = {material};
    scene.lighting = std::make_shared<const EnvironmentLighting>(PrecomputeLighting(UniformEnvironment(1, 1, 1)));
    const OrbitCamera camera = FitCamera(*scene.mesh);
    constexpr uint32_t kSize = 256;
    Result<ViewportImage> image =
        engine
            .Submit(std::make_shared<const int>(0),
                    [&](EngineContext& context, const int&) { return RenderViewport(context, scene, camera, kSize, kSize); })
            .get();
    if (!image) {
        Check(false, "the plane renders", image.error().Describe());
        return Finish();
    }
    const uint16_t background = FloatToHalf(0.1f);
    std::vector<double> row;
    for (uint32_t x = 0; x < kSize; ++x) {
        const size_t i = (size_t{kSize / 2} * kSize + x) * 4;
        if (image->linear[i] == background) continue;
        row.push_back((HalfToFloat(image->linear[i]) + HalfToFloat(image->linear[i + 1]) + HalfToFloat(image->linear[i + 2])) / 3.0);
    }
    // The map wraps at u = 0 and 1 (the plane's ends): those columns are left out.
    constexpr size_t kTrim = 8;
    bool finite = true;
    double low = 1e30;
    double high = -1e30;
    double step = 0.0;
    for (size_t k = kTrim; k + kTrim < row.size(); ++k) {
        finite = finite && std::isfinite(row[k]);
        low = std::min(low, row[k]);
        high = std::max(high, row[k]);
        if (k > kTrim) step = std::max(step, std::abs(row[k] - row[k - 1]));
    }
    Info("centre row: " + std::to_string(row.size()) + " hits, range [" + std::to_string(low) + ", " +
         std::to_string(high) + "], largest step " + std::to_string(step));
    Check(row.size() > kSize / 2 && finite, "the plane covers the centre row with finite colours",
          std::to_string(row.size()) + " hits");
    Check(high - low > 0.01 && step <= 0.02,
          "the shade is continuous where the perturbed normal turns past the horizon",
          "largest step " + std::to_string(step) + " of range " + std::to_string(high - low));
    return Finish();
}

int RunViewportSpirv(const fs::path& dir) {
    namespace render = uzp::render;
    auto compiler = render::DxcKernelCompiler::Load(render::DefaultDxcompilerPath());
    if (!compiler) {
        Check(false, "DXC loads", compiler.error().Describe());
        return Finish();
    }
    render::KernelCache cache(**compiler, dir / "kernel-cache");
    for (std::string_view entry : {"main", "display", "probe"}) {
        const auto source = ViewportShaderSource(render::KernelTarget::Spirv, entry);
        auto compiled = cache.Get(source, render::KernelTarget::Spirv);
        const std::string label = "Vulkan viewport " + std::string(entry);
        Check(compiled.has_value(), label + " compiles to SPIR-V", compiled ? "" : compiled.error().Describe());
        if (!compiled) continue;
        const render::SpirvFacts facts = render::InspectSpirv(compiled->bytecode);
        std::vector<uint32_t> words(compiled->bytecode.size() / 4);
        std::memcpy(words.data(), compiled->bytecode.data(), compiled->bytecode.size());
        size_t pushConstants = 0;
        for (size_t at = 5; at < words.size();) {
            const uint32_t count = words[at] >> 16;
            if (!count || at + count > words.size()) break;
            if ((words[at] & 0xffffu) == 59u && count >= 4 && words[at + 3] == 9u) ++pushConstants;
            at += count;
        }
        bool slots = pushConstants == 1;
        for (uint32_t set : facts.descriptorSets) slots &= set == 0;
        for (uint32_t binding : facts.bindings) slots &= binding < 16 || binding == 48 || (binding >= 64 && binding < 80);
        Check(slots, label + " uses fixed slots and push constants");
        size_t images = 0;
        for (uint32_t format : facts.imageFormats) {
            if (format == 0) continue;
            ++images;
            Check(format == (entry == "display" ? 10u : 2u), label + " declares its storage image format");
        }
        Check(images == 1, label + " writes one storage image");
        for (uint32_t capability : facts.capabilities) {
            Check(capability == render::kSpirvCapabilityShader ||
                      capability == render::kSpirvCapabilityStorageImageExtendedFormats ||
                      capability == render::kSpirvCapabilitySignedZeroInfNanPreserve || capability == 10 || capability == 11,
                  label + " needs only qualified capabilities", std::to_string(capability));
        }
    }
    return Finish();
}

bool CpuOccluded(const std::vector<float>& corners, const VisibilityRay& ray);
std::vector<VisibilityRay> RandomRays(const std::vector<float>& corners, size_t count, uint32_t seed);

int RunViewportBackend(const fs::path& dir, std::string_view backend) {
    namespace render = uzp::render;
    const auto selected = render::ParseBackend(backend);
    if (!selected) return 2;
    EngineOptions options = TestOptions(dir);
    options.device.backend = *selected;
    if (*selected == render::Backend::Vulkan) {
        options.createDevice = [&]() -> Result<std::unique_ptr<render::IDevice>> {
            const auto survey = render::SurveyVulkan();
            auto device = render::CreateQualifiedVulkanDevice(survey, render::QualifyVulkan(survey, 0), {});
            if (!device) return render::Unexpected(device.error());
            return std::unique_ptr<render::IDevice>(std::move(*device));
        };
    }
    Engine engine(std::move(options));
    if (engine.DeviceError()) {
        Info(engine.DeviceError()->Describe());
        return kExitSkip;
    }
    auto caps = engine.Capabilities();
    if (!caps) {
        Check(false, "backend capabilities", caps.error().Describe());
        return Finish();
    }
    auto compiler = render::DxcKernelCompiler::Load(render::DefaultDxcompilerPath());
    if (!compiler) {
        Check(false, "DXC loads", compiler.error().Describe());
        return Finish();
    }
    const auto target = *selected == render::Backend::Vulkan ? render::KernelTarget::Spirv : render::KernelTarget::Dxil;
    const auto sky = DecodeEnvironment(Bytes(RepoRoot() / "parity/fixtures/render-procedure/sky-patch.exr"));
    if (!sky) {
        Check(false, "the environment decodes", sky.error());
        return Finish();
    }
    const auto lighting = std::make_shared<const EnvironmentLighting>(PrecomputeLighting(*sky));
    json::Object results;
    constexpr uint32_t size = 256;
    for (const Fixture& fixture : Fixtures()) {
        ViewportScene scene;
        scene.mesh = fixture.mesh;
        scene.materials = {fixture.material};
        if (fixture.second) scene.materials.push_back(*fixture.second);
        scene.lighting = lighting;
        scene.environmentRotationDegrees = fixture.rotation;
        auto camera = FitCamera(*scene.mesh);
        camera.yawDegrees = fixture.yaw;
        camera.pitchDegrees = fixture.pitch;
        std::optional<ViewportImage> first;
        const auto rendered = engine.Submit(std::make_shared<const int>(0), [&](EngineContext& context, const int&) -> Result<void> {
            ResidentInputs resident;
            for (int repeat = 0; repeat < 2; ++repeat) {
                auto image = RenderViewport(context, scene, camera, size, size, &resident);
                if (!image) return render::Unexpected(image.error());
                if (!first) first = std::move(*image);
                else Check(first->linear == image->linear && first->display == image->display,
                           fixture.name + ": cold and resident renders are byte-identical");
            }
            Check(resident.Builds() == 1, fixture.name + ": resident inputs reused");
            return {};
        }).get();
        Check(rendered.has_value(), fixture.name + " renders", rendered ? "" : rendered.error().Describe());
        if (!rendered || !first) return Finish();
        bool display = true;
        for (size_t i = 0; i < first->linear.size(); ++i) {
            display &= first->display[i] == (i % 4 == 3 ? 65535 : DisplayTable()[first->linear[i]]);
        }
        Check(display, fixture.name + ": every display code equals the CPU table");
        results[fixture.name] = json::Object{{"linear_sha256", HashOf(first->linear)}, {"display_sha256", HashOf(first->display)}};
        for (const auto& [suffix, values] : {std::pair{"linear", &first->linear}, std::pair{"display", &first->display}}) {
            std::ofstream stream(dir / (fixture.name + "." + suffix + ".rgba16"), std::ios::binary);
            stream.write(reinterpret_cast<const char*>(values->data()), static_cast<std::streamsize>(values->size() * 2));
        }
    }
    const auto probeMesh = CubeOnPlane();
    const auto corners = WorldCorners(*probeMesh);
    const auto rays = RandomRays(corners, 4096, 310);
    auto hits = engine.Submit(std::make_shared<const int>(0), [&](EngineContext& context, const int&) {
        return TraceVisibility(context, *probeMesh, rays);
    }).get();
    Check(hits.has_value(), "visibility probe renders", hits ? "" : hits.error().Describe());
    if (!hits) return Finish();
    bool reference = hits->bvh.size() == rays.size() && hits->linear.size() == rays.size();
    if (reference) {
        for (size_t i = 0; i < rays.size(); ++i) {
            reference &= hits->bvh[i] == hits->linear[i] && (hits->bvh[i] != 0) == CpuOccluded(corners, rays[i]);
        }
    }
    Check(reference, "visibility probe equals CPU and linear traversal");
    std::ofstream(dir / "backend-report.json", std::ios::binary) << json::WriteCanonical(json::Object{
        {"schema", "uzpainter/preview/backend-diagnostic/1"}, {"backend", backend}, {"adapter", caps->adapter},
        {"driver", caps->driver}, {"kernel", Hex64(ViewportKernelKey(target, (*compiler)->Version()))},
        {"size", static_cast<int64_t>(size)}, {"fixtures", results}, {"acceptance", false},
        {"probe_rays", static_cast<int64_t>(rays.size())}, {"probe_matches_cpu", reference}}) << "\n";
    return Finish();
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
        if (fixture.second) scene.materials.push_back(*fixture.second);
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
    if (a.importance.width != b.importance.width || a.importance.height != b.importance.height ||
        !bits(a.importance.marginalCdf, b.importance.marginalCdf) ||
        !bits(a.importance.conditionalCdf, b.importance.conditionalCdf)) {
        return false;
    }
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

// ── viewport-visibility (decision 251) ───────────────────────────────────────────────────────

std::shared_ptr<const EnvironmentLighting> SharedLighting(const EnvironmentImage& image) {
    return std::make_shared<const EnvironmentLighting>(PrecomputeLighting(image));
}

/// One render inside one engine request; a failure is a failed check named `what`.
std::optional<ViewportImage> Render(Engine& engine, const ViewportScene& scene, const CameraPose& pose, uint32_t width,
                                    uint32_t height, const std::string& what, ResidentInputs* resident = nullptr) {
    Result<ViewportImage> image = engine
                                      .Submit(std::make_shared<const int>(0),
                                              [&](EngineContext& context, const int&) {
                                                  return RenderViewport(context, scene, pose, width, height, resident);
                                              })
                                      .get();
    if (!image) {
        Check(false, what + " renders", image.error().Describe());
        return std::nullopt;
    }
    return std::move(*image);
}

float Linear(const ViewportImage& image, size_t pixel, size_t channel) {
    return HalfToFloat(image.linear[pixel * 4 + channel]);
}

/// The 64 x 32 environment of the shadow checks: a grey sky of 0.02 and a sun, texel (21, 9) at
/// 300 (37 degrees above the horizon, towards -x and +z), which gives most of a floor's light.
EnvironmentImage SunEnvironment() {
    EnvironmentImage image = UniformEnvironment(0.02f, 0.02f, 0.02f, 64, 32);
    for (size_t c = 0; c < 3; ++c) image.rgb[(size_t{9} * 64 + 21) * 3 + c] = 300.0f;
    return image;
}

using D3 = std::array<double, 3>;

D3 Along(const D3& o, const D3& d, double t) { return {o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t}; }

/// The entry distance of the ray (o, d) into the box [lo, hi] beyond `from`, or +infinity.
double BoxEntry(const D3& o, const D3& d, const D3& lo, const D3& hi, double from = 0.0) {
    double enter = from;
    double leave = std::numeric_limits<double>::infinity();
    for (int a = 0; a < 3; ++a) {
        if (d[a] == 0.0) {
            if (o[a] < lo[a] || o[a] > hi[a]) return std::numeric_limits<double>::infinity();
            continue;
        }
        const double t0 = (lo[a] - o[a]) / d[a];
        const double t1 = (hi[a] - o[a]) / d[a];
        enter = std::max(enter, std::min(t0, t1));
        leave = std::min(leave, std::max(t0, t1));
    }
    return enter <= leave ? enter : std::numeric_limits<double>::infinity();
}

/// The centre ray of pixel (x, y), as the kernel casts it (perspective).
std::pair<D3, D3> PixelRay(const CameraPose& pose, uint32_t x, uint32_t y, uint32_t width, uint32_t height) {
    const double tanHalf = std::tan(pose.fovDegrees * std::numbers::pi / 360.0);
    const double aspect = static_cast<double>(width) / height;
    const double sx = ((x + 0.5) / width * 2.0 - 1.0) * tanHalf * aspect;
    const double sy = (1.0 - (y + 0.5) / height * 2.0) * tanHalf;
    D3 d{};
    for (int a = 0; a < 3; ++a) d[a] = pose.forward[a] + pose.right[a] * sx + pose.up[a] * sy;
    const double length = std::sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
    for (double& v : d) v /= length;
    return {pose.eye, d};
}

/// The CPU reference of the kernel's `Blocks` for a ray whose largest direction component is
/// exactly +-1: the same float operations in the same order (this file is compiled without
/// contraction), so its decisions equal the GPU's bit for bit.
struct CpuRay {
    P3 origin;
    int kx = 0;
    int ky = 0;
    int kz = 0;
    float shearX = 0.0f;
    float shearY = 0.0f;
    float shearZ = 0.0f;
};

CpuRay MakeCpuRay(const P3& origin, const P3& dir) {
    CpuRay r{origin};
    const P3 a{std::abs(dir[0]), std::abs(dir[1]), std::abs(dir[2])};
    r.kz = a[0] > a[1] ? (a[0] > a[2] ? 0 : 2) : (a[1] > a[2] ? 1 : 2);
    r.kx = r.kz == 2 ? 0 : r.kz + 1;
    r.ky = r.kx == 2 ? 0 : r.kx + 1;
    r.shearX = dir[static_cast<size_t>(r.kx)] / dir[static_cast<size_t>(r.kz)];
    r.shearY = dir[static_cast<size_t>(r.ky)] / dir[static_cast<size_t>(r.kz)];
    r.shearZ = 1.0f / dir[static_cast<size_t>(r.kz)];
    return r;
}

bool CpuBlocks(const CpuRay& r, const float* corners) {
    std::array<P3, 3> rel{};
    for (size_t k = 0; k < 3; ++k) {
        for (size_t a = 0; a < 3; ++a) rel[k][a] = corners[k * 3 + a] - r.origin[a];
    }
    const auto kx = static_cast<size_t>(r.kx);
    const auto ky = static_cast<size_t>(r.ky);
    const auto kz = static_cast<size_t>(r.kz);
    std::array<float, 3> x{};
    std::array<float, 3> y{};
    std::array<float, 3> z{};
    for (size_t k = 0; k < 3; ++k) {
        const float sx = r.shearX * rel[k][kz];
        x[k] = rel[k][kx] - sx;
        const float sy = r.shearY * rel[k][kz];
        y[k] = rel[k][ky] - sy;
        z[k] = r.shearZ * rel[k][kz];
    }
    const float a0 = x[1] * y[2];
    const float b0 = y[1] * x[2];
    const float f0 = a0 - b0;
    const float a1 = x[2] * y[0];
    const float b1 = y[2] * x[0];
    const float f1 = a1 - b1;
    const float a2 = x[0] * y[1];
    const float b2 = y[0] * x[1];
    const float f2 = a2 - b2;
    if ((f0 < 0.0f || f1 < 0.0f || f2 < 0.0f) && (f0 > 0.0f || f1 > 0.0f || f2 > 0.0f)) return false;
    if (f0 == 0.0f && f1 == 0.0f && f2 == 0.0f) return false;
    const float det01 = f0 + f1;
    const float det = det01 + f2;
    const float t0 = f0 * z[0];
    const float t1 = f1 * z[1];
    const float t2 = f2 * z[2];
    const float t01 = t0 + t1;
    const float t = t01 + t2;
    return det > 0.0f ? t > 0.0f : t < 0.0f;
}

/// Whether some triangle other than `self` blocks the ray, testing every triangle.
bool CpuOccluded(const std::vector<float>& corners, const VisibilityRay& ray) {
    const CpuRay r = MakeCpuRay(ray.point, ray.direction);
    for (size_t t = 0; t < corners.size() / 9; ++t) {
        if (t == ray.self) continue;
        if (CpuBlocks(r, &corners[t * 9])) return true;
    }
    return false;
}

/// The traced visibility of `rays` against `mesh`, or none (a failed check).
std::optional<VisibilityHits> Trace(Engine& engine, const std::shared_ptr<const uzp::mesh::TexturingMesh>& mesh,
                                    const std::vector<VisibilityRay>& rays, const std::string& what) {
    Result<VisibilityHits> hits = engine
                                      .Submit(std::make_shared<const int>(0),
                                              [&](EngineContext& context, const int&) {
                                                  return TraceVisibility(context, *mesh, rays);
                                              })
                                      .get();
    if (!hits) {
        Check(false, what + ": the rays are traced", hits.error().Describe());
        return std::nullopt;
    }
    return std::move(*hits);
}

std::string RayText(const VisibilityRay& ray) {
    char text[256];
    std::snprintf(text, sizeof(text), "point (%.9g, %.9g, %.9g) normal (%g, %g, %g) direction (%.9g, %.9g, %.9g) self %u",
                  ray.point[0], ray.point[1], ray.point[2], ray.normal[0], ray.normal[1], ray.normal[2], ray.direction[0],
                  ray.direction[1], ray.direction[2], ray.self);
    return text;
}

/// The BVH holds every triangle once, its boxes bound their children and triangles, and its depth
/// is within `cap`; an empty string, or what is wrong.
std::string BvhProblem(const VisibilityBvh& bvh, const std::vector<float>& corners, uint32_t cap) {
    const size_t triangles = corners.size() / 9;
    if (triangles == 0) return bvh.nodes.empty() ? "" : "nodes without triangles";
    if (bvh.depth > cap) return "depth " + std::to_string(bvh.depth) + " beyond the cap";
    std::vector<uint32_t> seen(triangles, 0);
    const auto f = [&](size_t word) { return std::bit_cast<float>(bvh.nodes[word]); };
    const size_t nodes = bvh.nodes.size() / kBvhNodeWords;
    for (size_t n = 0; n < nodes; ++n) {
        const size_t base = n * kBvhNodeWords;
        const auto inside = [&](float v, size_t axis) { return v >= f(base + axis) && v <= f(base + 4 + axis); };
        const uint32_t first = bvh.nodes[base + 3];
        const uint32_t count = bvh.nodes[base + 7];
        if (count == 0) {
            if (first + 1 >= nodes) return "node " + std::to_string(n) + " names children out of range";
            for (const uint32_t child : {first, first + 1}) {
                for (size_t a = 0; a < 3; ++a) {
                    if (!inside(f(child * kBvhNodeWords + a), a) || !inside(f(child * kBvhNodeWords + 4 + a), a)) {
                        return "node " + std::to_string(n) + " does not bound child " + std::to_string(child);
                    }
                }
            }
            continue;
        }
        for (uint32_t j = first; j < first + count; ++j) {
            const size_t o = size_t{j} * kOccluderWords;
            if (o + kOccluderWords > bvh.occluders.size()) return "a leaf names occluders out of range";
            const uint32_t t = bvh.occluders[o + 3];
            if (t >= triangles) return "an occluder names triangle " + std::to_string(t);
            ++seen[t];
            for (size_t k = 0; k < 3; ++k) {
                for (size_t a = 0; a < 3; ++a) {
                    const float v = std::bit_cast<float>(bvh.occluders[o + k * 4 + a]);
                    if (v != corners[t * 9 + k * 3 + a]) return "occluder " + std::to_string(j) + " is not its triangle";
                    if (!inside(v, a)) return "leaf " + std::to_string(n) + " does not bound triangle " + std::to_string(t);
                }
            }
        }
    }
    for (size_t t = 0; t < triangles; ++t) {
        if (seen[t] != 1) return "triangle " + std::to_string(t) + " is in " + std::to_string(seen[t]) + " leaves";
    }
    return "";
}

/// Rays from a deterministic generator around the bounds of `corners`: origins on a 2^-12 grid
/// inside the bounds grown by a fifth, directions with one component exactly +-1 and the others
/// on a 2^-9 grid in [-1, 1] (so the CPU reference shears exactly as the GPU), every fourth ray
/// skipping a triangle.
std::vector<VisibilityRay> RandomRays(const std::vector<float>& corners, size_t count, uint32_t seed) {
    P3 lo{std::numeric_limits<float>::max(), std::numeric_limits<float>::max(), std::numeric_limits<float>::max()};
    P3 hi{-lo[0], -lo[1], -lo[2]};
    for (size_t i = 0; i < corners.size(); ++i) {
        lo[i % 3] = std::min(lo[i % 3], corners[i]);
        hi[i % 3] = std::max(hi[i % 3], corners[i]);
    }
    uint64_t state = 0x9E3779B97F4A7C15ull ^ seed;
    const auto next = [&] {
        state = state * 6364136223846793005ull + 1442695040888963407ull;
        return static_cast<uint32_t>(state >> 33);
    };
    const auto unit = [&] { return static_cast<double>(next() % 4097) / 4096.0; };
    std::vector<VisibilityRay> rays(count);
    const size_t triangles = corners.size() / 9;
    for (size_t i = 0; i < count; ++i) {
        VisibilityRay& ray = rays[i];
        for (size_t a = 0; a < 3; ++a) {
            const double margin = (static_cast<double>(hi[a]) - lo[a]) * 0.2 + 0.01;
            const double v = lo[a] - margin + unit() * ((static_cast<double>(hi[a]) - lo[a]) + 2.0 * margin);
            ray.point[a] = static_cast<float>(std::round(v * 4096.0) / 4096.0);
        }
        const size_t major = next() % 3;
        for (size_t a = 0; a < 3; ++a) {
            ray.direction[a] = a == major ? (next() % 2 ? 1.0f : -1.0f)
                                          : static_cast<float>(static_cast<int>(next() % 1025) - 512) / 512.0f;
        }
        if (i % 4 == 3 && triangles > 0) ray.self = next() % static_cast<uint32_t>(triangles);
    }
    return rays;
}

/// Material slots of the ratio renders: the base colour does not change a ratio.
MaterialInputs Rough(float roughness) {
    MaterialInputs m;
    m.roughnessValue = roughness;
    return m;
}

/// `Rough(roughness)` with a 2 x 2 normal map whose every texel is the encoded (x, y, z): a
/// uniformly tilted normal, which does not curve (no cavity, decision 258).
MaterialInputs UniformNormal(float roughness, float x, float y, float z) {
    MaterialInputs m = Rough(roughness);
    m.normal = MaterialMap{2, 2, 3, {}};
    for (int i = 0; i < 4; ++i) m.normal->values.insert(m.normal->values.end(), {x, y, z});
    return m;
}

int RunViewportVisibility(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    const auto uniform = SharedLighting(UniformEnvironment(1.0f, 1.0f, 1.0f));
    const auto sun = SharedLighting(SunEnvironment());
    const std::expected<EnvironmentImage, std::string> studioImage =
        DecodeEnvironment(Bytes(RepoRoot() / "assets/environments/studio-small-09.exr"));
    if (!studioImage) {
        Check(false, "the shipped environment decodes", studioImage.error());
        return Finish();
    }
    const auto studio = SharedLighting(*studioImage);

    // 1. A camera inside a closed box under a constant environment: every visibility ray of every
    // pixel is valid (its weight and radiance are positive) and blocked, so both ratios are 0 and
    // the pixel is exactly 0; the ratio-1 fallback of an empty sum would light it.
    {
        MeshBuilder builder;
        builder.Box({-1.0f, -1.0f, -1.0f}, {1.0f, 1.0f, 1.0f}, 0);
        ViewportScene scene;
        scene.mesh = builder.Build();
        scene.materials = {Rough(0.5f)};
        scene.lighting = uniform;
        CameraPose pose;
        pose.eye = {0.1, -0.2, 0.15};
        pose.fovDegrees = 100.0;
        if (const std::optional<ViewportImage> image = Render(engine, scene, pose, 64, 64, "the closed box")) {
            size_t lit = 0;
            for (size_t i = 0; i < size_t{64} * 64; ++i) {
                for (size_t c = 0; c < 3; ++c) {
                    if (image->linear[i * 4 + c] != 0 || image->display[i * 4 + c] != 0) ++lit;
                }
            }
            Check(lit == 0, "closed box: every pixel renders exactly 0 (every visibility ray valid and blocked)",
                  std::to_string(lit) + " channels are not 0");
        }
        scene.diffuseRays = 0;
        scene.specularRays = 0;
        if (const std::optional<ViewportImage> image = Render(engine, scene, pose, 64, 64, "the closed box, no rays")) {
            bool all = true;
            for (size_t i = 0; i < size_t{64} * 64; ++i) all = all && Linear(*image, i, 1) > 0.0f;
            Check(all, "closed box without visibility rays: every pixel is lit (the 0 comes from the rays)");
        }
    }

    // 2. The traversal against every triangle: the BVH's visibility of each ray equals a CPU cast
    // against all triangles (and the kernel's own linear test), on the concave fixture, the
    // sphere, the closed box and a BVH whose depth cap is reached.
    {
        MeshBuilder box;
        box.Box({-1.0f, -1.0f, -1.0f}, {1.0f, 1.0f, 1.0f}, 0);
        const std::pair<const char*, std::shared_ptr<const uzp::mesh::TexturingMesh>> meshes[] = {
            {"cube-on-plane", CubeOnPlane()},
            {"sphere", LoadMesh("parity/fixtures/render-procedure/sphere.obj")},
            {"closed box", box.Build()},
        };
        uint32_t seed = 1;
        for (const auto& [name, mesh] : meshes) {
            const std::vector<float> corners = WorldCorners(*mesh);
            const VisibilityBvh bvh = BuildVisibilityBvh(corners);
            const std::string problem = BvhProblem(bvh, corners, kBvhMaxDepth);
            Check(problem.empty(),
                  std::string(name) + ": the BVH holds every triangle once, bounds its contents and is within the depth cap",
                  problem);
            Info(std::string(name) + ": " + std::to_string(corners.size() / 9) + " triangles, " +
                 std::to_string(bvh.nodes.size() / kBvhNodeWords) + " nodes, depth " + std::to_string(bvh.depth));
            const std::vector<VisibilityRay> rays = RandomRays(corners, 20000, seed++);
            const std::optional<VisibilityHits> hits = Trace(engine, mesh, rays, name);
            if (!hits) continue;
            size_t blocked = 0;
            std::string mismatch;
            for (size_t i = 0; i < rays.size(); ++i) {
                const bool cpu = CpuOccluded(corners, rays[i]);
                blocked += cpu ? 1 : 0;
                if (mismatch.empty() && (hits->bvh[i] != (cpu ? 1 : 0) || hits->linear[i] != (cpu ? 1 : 0))) {
                    mismatch = "ray " + std::to_string(i) + " " + RayText(rays[i]) + ": CPU " + std::to_string(cpu) +
                               ", BVH " + std::to_string(hits->bvh[i]) + ", every triangle " + std::to_string(hits->linear[i]);
                }
            }
            Check(mismatch.empty() && blocked > rays.size() / 10 && blocked < rays.size() * 9 / 10,
                  std::string(name) + ": the BVH's visibility of every ray equals a CPU cast against every triangle",
                  mismatch.empty() ? std::to_string(blocked) + " of " + std::to_string(rays.size()) + " blocked" : mismatch);
        }
        // The depth cap: a cap of 2 makes leaves of whatever remains at depth 2.
        const std::vector<float> corners = WorldCorners(*LoadMesh("parity/fixtures/render-procedure/sphere.obj"));
        const VisibilityBvh capped = BuildVisibilityBvh(corners, 2);
        const std::string problem = BvhProblem(capped, corners, 2);
        Check(problem.empty() && capped.depth == 2,
              "a depth cap makes leaves at the cap that still hold every triangle once",
              problem.empty() ? "depth " + std::to_string(capped.depth) : problem);
    }

    // 3. A thin gap: an occluder twice the origin offset above the surface blocks; one at half of
    // it lies behind the moved origin and leaks (the documented limit of the offset). The offset
    // is 256 units in the last place at y = 1 (2^-15) and 2^-16 within 1/32 of zero.
    for (const auto& [y0, offset] : {std::pair<float, float>{1.0f, 0x1p-15f}, std::pair<float, float>{0.0f, 0x1p-16f}}) {
        for (const float factor : {2.0f, 0.5f}) {
            const float y1 = y0 + factor * offset;
            MeshBuilder builder;
            builder.Quad({-1.0f, y0, -1.0f}, {-1.0f, y0, 1.0f}, {1.0f, y0, 1.0f}, {1.0f, y0, -1.0f}, 0);
            builder.Quad({-1.0f, y1, -1.0f}, {1.0f, y1, -1.0f}, {1.0f, y1, 1.0f}, {-1.0f, y1, 1.0f}, 0);
            const auto mesh = builder.Build();
            std::vector<VisibilityRay> rays;
            for (int i = 0; i < 8; ++i) {
                for (const P3& d : {P3{0.0f, 1.0f, 0.0f}, P3{0.25f, 1.0f, -0.25f}, P3{-0.5f, 1.0f, 0.125f}}) {
                    VisibilityRay ray;
                    ray.point = {-0.7f + 0.2f * static_cast<float>(i), y0, 0.3f - 0.1f * static_cast<float>(i)};
                    ray.normal = {0.0f, 1.0f, 0.0f};
                    ray.direction = d;
                    rays.push_back(ray);
                }
            }
            const std::string what = "y " + std::to_string(y0) + ", gap " + std::to_string(factor) + " x the offset";
            const std::optional<VisibilityHits> hits = Trace(engine, mesh, rays, what);
            if (!hits) continue;
            size_t blocked = 0;
            for (size_t i = 0; i < rays.size(); ++i) blocked += hits->bvh[i] && hits->linear[i] ? 1 : 0;
            if (factor > 1.0f) {
                Check(blocked == rays.size(),
                      "at y = " + std::string(y0 == 0.0f ? "0" : "1") + " an occluder twice the origin offset above blocks",
                      std::to_string(blocked) + " of " + std::to_string(rays.size()) + " blocked");
            } else {
                Check(blocked == 0,
                      "at y = " + std::string(y0 == 0.0f ? "0" : "1") +
                          " an occluder at half the origin offset leaks (documented)",
                      std::to_string(blocked) + " of " + std::to_string(rays.size()) + " blocked");
            }
        }
    }

    // 4. Watertight: rays through the shared diagonal of every face, through every box edge and
    // through every corner of a closed box are blocked, through the BVH and every triangle.
    {
        MeshBuilder builder;
        builder.Box({-1.0f, -1.0f, -1.0f}, {1.0f, 1.0f, 1.0f}, 0);
        const auto mesh = builder.Build();
        std::vector<VisibilityRay> rays;
        const float ts[] = {-0.75f, -0.3f, 0.0f, 0.4f, 0.875f};
        for (size_t axis = 0; axis < 3; ++axis) {
            for (const float side : {-1.0f, 1.0f}) {
                const size_t u = (axis + 1) % 3;
                const size_t v = (axis + 2) % 3;
                for (const float t : ts) {
                    for (const float flip : {1.0f, -1.0f}) {  // both diagonals: one is shared by the face's triangles
                        VisibilityRay ray;
                        ray.point[axis] = 3.0f * side;
                        ray.point[u] = t;
                        ray.point[v] = t * flip;
                        ray.direction[axis] = -side;
                        rays.push_back(ray);
                    }
                    // Along a box edge: the ray grazes the face it runs along and meets the edge.
                    VisibilityRay edge;
                    edge.point[axis] = 3.0f * side;
                    edge.point[u] = 1.0f;
                    edge.point[v] = t;
                    edge.direction[axis] = -side;
                    rays.push_back(edge);
                }
            }
        }
        for (int corner = 0; corner < 8; ++corner) {
            VisibilityRay ray;
            for (size_t a = 0; a < 3; ++a) {
                const float s = (corner >> a) & 1 ? 1.0f : -1.0f;
                ray.point[a] = 3.0f * s;
                ray.direction[a] = -s;
            }
            rays.push_back(ray);
        }
        if (const std::optional<VisibilityHits> hits = Trace(engine, mesh, rays, "the box's shared edges")) {
            std::string missed;
            for (size_t i = 0; i < rays.size(); ++i) {
                if ((!hits->bvh[i] || !hits->linear[i]) && missed.empty()) missed = RayText(rays[i]);
            }
            Check(missed.empty(), "every ray through a shared edge or corner of a closed box is blocked (watertight)", missed);
        }
    }

    // 5. The cube (texture set 1) shadows the plane (texture set 0) where the geometry predicts,
    // under a sun that gives most of the light: the diffuse ratio is low where every direction of
    // the sun's texel is hidden by the cube (umbra) and high where none is; the umbra is darker.
    {
        ViewportScene scene;
        scene.mesh = CubeOnPlane();
        scene.materials = {Rough(0.5f), Rough(0.4f)};
        scene.lighting = sun;
        scene.background = {-1.0f, -1.0f, -1.0f};
        OrbitCamera camera;
        camera.distance = 10.0;
        camera.pitchDegrees = 80.0;
        camera.yawDegrees = 20.0;
        const CameraPose pose = PoseOf(camera);
        constexpr uint32_t kSize = 192;
        scene.output = ViewportOutput::DiffuseVisibility;
        const std::optional<ViewportImage> ratios = Render(engine, scene, pose, kSize, kSize, "the sun's shadow (ratio)");
        scene.output = ViewportOutput::Colour;
        const std::optional<ViewportImage> colours = Render(engine, scene, pose, kSize, kSize, "the sun's shadow (colour)");
        if (ratios && colours) {
            const D3 cubeLo{-0.75, 0.0, -0.75};
            const D3 cubeHi{0.75, 1.5, 0.75};
            std::vector<D3> sunDirections;
            for (const double du : {-1.0, 0.0, 1.0}) {
                for (const double dv : {-1.0, 0.0, 1.0}) {
                    // The sun's texel, grown by one level-0 texel for the bilinear lookups.
                    const double u = (21.5 + du * (0.5 + 1.0 / 8.0)) / 64.0;
                    const double v = (9.5 + dv * (0.5 + 1.0 / 8.0)) / 32.0;
                    sunDirections.push_back(DirectionOf(u, v));
                }
            }
            double umbraMax = 0.0;
            double litMin = 1.0;
            double umbraColour = 0.0;
            double litColour = 0.0;
            size_t umbra = 0;
            size_t lit = 0;
            for (uint32_t y = 0; y < kSize; ++y) {
                for (uint32_t x = 0; x < kSize; ++x) {
                    const auto [o, d] = PixelRay(pose, x, y, kSize, kSize);
                    if (!(d[1] < 0.0)) continue;
                    const double tPlane = -o[1] / d[1];
                    const D3 p = Along(o, d, tPlane);
                    if (std::abs(p[0]) > 2.9 || std::abs(p[2]) > 2.9) continue;
                    if (BoxEntry(o, d, cubeLo, cubeHi) < tPlane) continue;  // the camera sees the cube
                    int hidden = 0;
                    for (const D3& s : sunDirections) hidden += BoxEntry(p, s, cubeLo, cubeHi, 1e-9) < 1e30 ? 1 : 0;
                    const size_t i = size_t{y} * kSize + x;
                    const double ratio = (Linear(*ratios, i, 0) + Linear(*ratios, i, 1) + Linear(*ratios, i, 2)) / 3.0;
                    const double colour = Linear(*colours, i, 1);
                    if (hidden == static_cast<int>(sunDirections.size())) {
                        ++umbra;
                        umbraMax = std::max(umbraMax, ratio);
                        umbraColour += colour;
                    } else if (hidden == 0) {
                        ++lit;
                        litMin = std::min(litMin, ratio);
                        litColour += colour;
                    }
                }
            }
            Info("sun shadow: " + std::to_string(umbra) + " umbra pixels (largest diffuse ratio " + std::to_string(umbraMax) +
                 "), " + std::to_string(lit) + " lit pixels (smallest " + std::to_string(litMin) + ")");
            Check(umbra > 200 && lit > 2000 && umbraMax < 0.3 && litMin > 0.7,
                  "the cube (texture set 1) shadows the plane (texture set 0) where geometry predicts: the diffuse "
                  "ratio is below 0.3 in the umbra and above 0.7 where the sun is in view",
                  "umbra " + std::to_string(umbra) + " max " + std::to_string(umbraMax) + ", lit " + std::to_string(lit) +
                      " min " + std::to_string(litMin));
            const double umbraMean = umbra ? umbraColour / umbra : 0.0;
            const double litMean = lit ? litColour / lit : 0.0;
            Check(umbra > 0 && lit > 0 && umbraMean < 0.5 * litMean,
                  "an occluded point is darker: the umbra's mean colour is below half the lit plane's",
                  std::to_string(umbraMean) + " vs " + std::to_string(litMean));
        }
    }

    // 6. Per-channel ratios: red light comes only from +x, blue only from -x; beside a wall at
    // x = 0.5 that hides +x, the floor's red ratio falls while its blue ratio stays near 1.
    {
        EnvironmentImage twoColour = UniformEnvironment(0.0f, 0.0f, 0.0f, 64, 32);
        for (uint32_t y = 0; y < 32; ++y) {
            for (uint32_t x = 0; x < 64; ++x) {
                const bool red = DirectionOf((x + 0.5) / 64, (y + 0.5) / 32)[0] > 0.0;
                float* texel = &twoColour.rgb[(size_t{y} * 64 + x) * 3];
                texel[0] = red ? 1.0f : 0.0f;
                texel[2] = red ? 0.0f : 1.0f;
            }
        }
        MeshBuilder builder;
        builder.Quad({-3.0f, 0.0f, -3.0f}, {-3.0f, 0.0f, 3.0f}, {0.5f, 0.0f, 3.0f}, {0.5f, 0.0f, -3.0f}, 0);
        builder.Quad({0.5f, 0.0f, -3.0f}, {0.5f, 0.0f, 3.0f}, {0.5f, 3.0f, 3.0f}, {0.5f, 3.0f, -3.0f}, 0);
        ViewportScene scene;
        scene.mesh = builder.Build();
        scene.materials = {Rough(0.5f)};
        scene.lighting = SharedLighting(twoColour);
        scene.background = {-1.0f, -1.0f, -1.0f};
        scene.output = ViewportOutput::DiffuseVisibility;
        OrbitCamera camera;
        camera.target = {-0.5, 0.0, 0.0};
        camera.distance = 6.0;
        camera.pitchDegrees = 70.0;
        camera.yawDegrees = -90.0;
        const CameraPose pose = PoseOf(camera);
        constexpr uint32_t kSize = 128;
        if (const std::optional<ViewportImage> image = Render(engine, scene, pose, kSize, kSize, "the two-colour wall")) {
            double redSum = 0.0;
            size_t beside = 0;
            double blueMin = 1.0;
            size_t floor = 0;
            for (uint32_t y = 0; y < kSize; ++y) {
                for (uint32_t x = 0; x < kSize; ++x) {
                    const auto [o, d] = PixelRay(pose, x, y, kSize, kSize);
                    if (!(d[1] < 0.0)) continue;
                    const D3 p = Along(o, d, -o[1] / d[1]);
                    if (p[0] > 0.49 || p[0] < -2.9 || std::abs(p[2]) > 2.9) continue;
                    const size_t i = size_t{y} * kSize + x;
                    ++floor;
                    blueMin = std::min(blueMin, static_cast<double>(Linear(*image, i, 2)));
                    if (p[0] > 0.0 && std::abs(p[2]) < 2.0) {
                        ++beside;
                        redSum += Linear(*image, i, 0);
                    }
                }
            }
            const double redMean = beside ? redSum / beside : 1.0;
            Info("two-colour wall: " + std::to_string(floor) + " floor pixels, smallest blue ratio " + std::to_string(blueMin) +
                 "; " + std::to_string(beside) + " beside the wall, mean red ratio " + std::to_string(redMean));
            Check(beside > 100 && redMean < 0.5 && blueMin > 0.98,
                  "a two-colour environment gives per-channel ratios: beside a wall that hides the red half, the red "
                  "ratio falls below 0.5 while the blue one stays above 0.98",
                  "red " + std::to_string(redMean) + ", blue " + std::to_string(blueMin));
        }
    }

    // 7. No self-shadowing on flat and convex surfaces: on the plane (with and without a uniformly
    // tilted normal map, which has no cavity, decision 258) and on the sphere every diffuse and
    // specular ratio is exactly 1, at grazing and steep views, under the sun and the shipped
    // environment.
    {
        const std::vector<Fixture> fixtures = Fixtures();
        std::vector<std::pair<std::string, std::pair<std::shared_ptr<const uzp::mesh::TexturingMesh>, MaterialInputs>>> cases = {
            {"plane", {fixtures[1].mesh, Rough(0.35f)}},
            {"normal-mapped plane", {fixtures[1].mesh, UniformNormal(0.35f, 0.65f, 0.5f, 0.9f)}},
            {"sphere", {fixtures[0].mesh, Rough(0.5f)}},
        };
        std::string problem;
        size_t pixels = 0;
        for (const auto& [name, input] : cases) {
            for (const auto& lighting : {sun, studio}) {
                for (const double pitch : {8.0, 35.0, 70.0}) {
                    for (const double yaw : {0.0, 120.0}) {
                        ViewportScene scene;
                        scene.mesh = input.first;
                        scene.materials = {input.second};
                        scene.lighting = lighting;
                        scene.background = {-1.0f, -1.0f, -1.0f};
                        OrbitCamera camera = FitCamera(*scene.mesh);
                        camera.pitchDegrees = pitch;
                        camera.yawDegrees = yaw;
                        for (const ViewportOutput output : {ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
                            scene.output = output;
                            const std::optional<ViewportImage> image = Render(engine, scene, PoseOf(camera), 96, 96, name);
                            if (!image) continue;
                            for (size_t i = 0; i < size_t{96} * 96; ++i) {
                                if (image->linear[i * 4] == FloatToHalf(-1.0f)) continue;
                                ++pixels;
                                for (size_t c = 0; c < 3; ++c) {
                                    if (image->linear[i * 4 + c] != FloatToHalf(1.0f) && problem.empty()) {
                                        problem = name + " pitch " + std::to_string(pitch) + " yaw " + std::to_string(yaw) +
                                                  ": pixel " + std::to_string(i) + " ratio " + std::to_string(Linear(*image, i, c));
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        Check(problem.empty() && pixels > 10000,
              "no self-shadowing: on a plane (with and without a uniformly tilted normal map) and on the sphere every "
              "diffuse and specular ratio is exactly 1 at grazing and steep views",
              problem.empty() ? std::to_string(pixels) + " pixels" : problem);
    }

    // 8. The estimator against a high-count render of the same estimator (1024 rays of each kind),
    // over the concave fixture's pixels the reference shows occluded:
    // - it converges: four times the rays at least nearly halve the RMSE (Monte-Carlo rate, 0.6);
    // - the RMSE at the shipped count N is within 0.5 / sqrt(N), the largest standard deviation of
    //   a ratio in [0, 1] estimated from N equally weighted rays. Both terms mix their own lobe's
    //   directions with environment-importance ones, so no bright light rests on one heavy ray.
    {
        ViewportScene scene;
        scene.mesh = CubeOnPlane();
        scene.materials = {Rough(0.5f), Rough(0.3f)};
        scene.lighting = studio;
        scene.background = {-1.0f, -1.0f, -1.0f};
        OrbitCamera camera = FitCamera(*scene.mesh);
        camera.yawDegrees = 35.0;
        camera.pitchDegrees = 30.0;
        constexpr uint32_t kSize = 128;
        for (const ViewportOutput output : {ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
            const bool diffuse = output == ViewportOutput::DiffuseVisibility;
            const uint32_t rays = diffuse ? kDiffuseVisibilityRays : kSpecularVisibilityRays;
            const auto renderWith = [&](uint32_t count, const char* what) {
                scene.output = output;
                scene.diffuseRays = diffuse ? count : kDiffuseVisibilityRays;
                scene.specularRays = diffuse ? kSpecularVisibilityRays : count;
                return Render(engine, scene, PoseOf(camera), kSize, kSize, what);
            };
            const std::optional<ViewportImage> low = renderWith(rays, "the estimator");
            const std::optional<ViewportImage> four = renderWith(rays * 4, "the estimator at four times the rays");
            const std::optional<ViewportImage> high = renderWith(1024, "the reference");
            if (!low || !four || !high) continue;
            double squared = 0.0;
            double fourSquared = 0.0;
            size_t pixels = 0;
            size_t occluded = 0;
            for (size_t i = 0; i < size_t{kSize} * kSize; ++i) {
                if (high->linear[i * 4] == FloatToHalf(-1.0f)) continue;
                for (size_t c = 0; c < 3; ++c) {
                    ++pixels;
                    if (!(Linear(*high, i, c) < 0.999f)) continue;
                    const double e = static_cast<double>(Linear(*low, i, c)) - Linear(*high, i, c);
                    const double e4 = static_cast<double>(Linear(*four, i, c)) - Linear(*high, i, c);
                    squared += e * e;
                    fourSquared += e4 * e4;
                    ++occluded;
                }
            }
            const double rmse = occluded ? std::sqrt(squared / occluded) : 0.0;
            const double fourRmse = occluded ? std::sqrt(fourSquared / occluded) : 0.0;
            const double tolerance = 0.5 / std::sqrt(static_cast<double>(rays));
            const std::string name = diffuse ? "diffuse" : "specular";
            Info(name + " ratio over " + std::to_string(occluded / 3) + " occluded of " + std::to_string(pixels / 3) +
                 " pixels, RMSE against 1024 rays: " + std::to_string(fourRmse) + " at " + std::to_string(rays * 4) +
                 " rays, " + std::to_string(rmse) + " at " + std::to_string(rays) + " (tolerance " +
                 std::to_string(tolerance) + ")");
            Check(pixels > 3000 && occluded > 300 && fourRmse <= 0.6 * rmse,
                  "the " + name + " ratio converges: four times the rays at least nearly halve its RMSE against a "
                  "1024-ray render of the same estimator",
                  std::to_string(fourRmse) + " > 0.6 x " + std::to_string(rmse));
            Check(pixels > 3000 && occluded > 300 && rmse <= tolerance,
                  "the " + name + " ratio's RMSE against a 1024-ray render of the same estimator is within 0.5 / "
                  "sqrt(N) on the occluded pixels",
                  std::to_string(rmse) + " > " + std::to_string(tolerance));
        }
    }

    // 9. The BVH is built once per geometry: a new mesh object of the same geometry reuses it.
    {
        ViewportScene scene;
        scene.mesh = CubeOnPlane();
        scene.materials = {Rough(0.5f), Rough(0.4f)};
        scene.lighting = sun;
        const CameraPose pose = PoseOf(FitCamera(*scene.mesh));
        static_cast<void>(Render(engine, scene, pose, 32, 32, "the cache's first render"));
        const uint64_t before = VisibilityBvhBuilds();
        scene.mesh = CubeOnPlane();
        static_cast<void>(Render(engine, scene, pose, 32, 32, "the cache's second render"));
        const uint64_t same = VisibilityBvhBuilds();
        MeshBuilder other;
        other.Box({-2.0f, -2.0f, -2.0f}, {2.0f, 2.0f, 2.0f}, 0);
        scene.mesh = other.Build();
        scene.materials = {Rough(0.5f)};
        static_cast<void>(Render(engine, scene, pose, 32, 32, "the cache's other geometry"));
        Check(same == before && VisibilityBvhBuilds() == same + 1,
              "a new mesh object of the same geometry reuses its BVH; another geometry builds one",
              std::to_string(before) + " " + std::to_string(same) + " " + std::to_string(VisibilityBvhBuilds()));
    }
    return Finish();
}

// ── viewport-occlusion (decision 257) ────────────────────────────────────────────────────────

/// A constant `size` x `size` occlusion map of `value`.
MaterialMap ConstantMap(float value, uint32_t size = 4) {
    return MaterialMap{size, size, 1, std::vector<float>(size_t{size} * size, value)};
}

/// The open plane y = 0 from -3 to 3, facing +y, as texture set `material`: u = (x + 3) / 6 and
/// v = (z + 3) / 6, scaled by `scale`, u mirrored when `mirrored`.
void OpenPlane(MeshBuilder& builder, uint32_t material, float scale = 1.0f, bool mirrored = false) {
    const auto uv = [&](float x, float z) {
        const float u = (x + 3.0f) / 6.0f;
        return uzp::mesh::Float2{(mirrored ? 1.0f - u : u) * scale, (z + 3.0f) / 6.0f * scale};
    };
    builder.QuadUv({-3.0f, 0.0f, -3.0f}, {-3.0f, 0.0f, 3.0f}, {3.0f, 0.0f, 3.0f}, {3.0f, 0.0f, -3.0f}, material,
                   {uv(-3.0f, -3.0f), uv(-3.0f, 3.0f), uv(3.0f, 3.0f), uv(3.0f, -3.0f)});
}

/// The u, v of a point of `OpenPlane`.
std::pair<double, double> PlaneUv(const D3& p, double scale = 1.0, bool mirrored = false) {
    const double u = (p[0] + 3.0) / 6.0;
    return {(mirrored ? 1.0 - u : u) * scale, (p[2] + 3.0) / 6.0 * scale};
}

/// An orthographic view of the plane y = 0 from `degrees` off its normal, towards +x.
CameraPose PlaneView(double degrees, double height = 4.0) {
    const double a = degrees * std::numbers::pi / 180.0;
    CameraPose pose;
    pose.orthographic = true;
    pose.orthographicHeight = height;
    pose.eye = {5.0 * std::sin(a), 5.0 * std::cos(a), 0.0};
    pose.forward = {-std::sin(a), -std::cos(a), 0.0};
    pose.right = {0.0, 0.0, 1.0};
    pose.up = {std::cos(a), -std::sin(a), 0.0};
    return pose;
}

/// The mean, the extremes and the count of the channel-mean values of the pixels that hit
/// something (the clear colour is -1).
struct HitStats {
    double mean = 0.0;
    double low = 0.0;
    double high = 0.0;
    size_t pixels = 0;
};

HitStats StatsOf(const ViewportImage& image) {
    HitStats s;
    double sum = 0.0;
    double low = std::numeric_limits<double>::max();
    double high = -low;
    for (size_t i = 0; i < size_t{image.width} * image.height; ++i) {
        if (image.linear[i * 4] == FloatToHalf(-1.0f)) continue;
        const double v = (Linear(image, i, 0) + Linear(image, i, 1) + Linear(image, i, 2)) / 3.0;
        sum += v;
        low = std::min(low, v);
        high = std::max(high, v);
        ++s.pixels;
    }
    if (s.pixels > 0) {
        s.mean = sum / static_cast<double>(s.pixels);
        s.low = low;
        s.high = high;
    }
    return s;
}

/// The RMSE between two renders over the pixels both hit, every channel.
double Rmse(const ViewportImage& a, const ViewportImage& b) {
    double squared = 0.0;
    size_t samples = 0;
    for (size_t i = 0; i < size_t{a.width} * a.height; ++i) {
        if (a.linear[i * 4] == FloatToHalf(-1.0f) || b.linear[i * 4] == FloatToHalf(-1.0f)) continue;
        for (size_t c = 0; c < 3; ++c) {
            const double e = static_cast<double>(Linear(a, i, c)) - Linear(b, i, c);
            squared += e * e;
            ++samples;
        }
    }
    return samples ? std::sqrt(squared / static_cast<double>(samples)) : 0.0;
}

std::string Fixed(double v, int digits = 4) {
    char text[64];
    std::snprintf(text, sizeof(text), "%.*f", digits, v);
    return text;
}

/// The AO bake of the open plane of `CubeOnUvPlane` (the test's own, UzmiGames-authored): per
/// texel, the fraction of 32 x 32 stratified cosine-weighted directions (Malley's method) from the
/// texel's point that leave without entering the cube.
MaterialMap BakeCubeAo(uint32_t size) {
    MaterialMap map{size, size, 1, {}};
    const D3 lo{-0.75, 0.0, -0.75};
    const D3 hi{0.75, 1.5, 0.75};
    for (uint32_t r = 0; r < size; ++r) {
        for (uint32_t c = 0; c < size; ++c) {
            const double u = (c + 0.5) / size;
            const double v = 1.0 - (r + 0.5) / size;
            const D3 p{-3.0 + 6.0 * u, 0.0, -3.0 + 6.0 * v};
            int open = 0;
            for (int i = 0; i < 32; ++i) {
                for (int j = 0; j < 32; ++j) {
                    const double x1 = (i + 0.5) / 32.0;
                    const double phi = 2.0 * std::numbers::pi * (j + 0.5) / 32.0;
                    const D3 d{std::sqrt(x1) * std::cos(phi), std::sqrt(1.0 - x1), std::sqrt(x1) * std::sin(phi)};
                    if (!(BoxEntry(p, d, lo, hi, 1e-9) < 1e30)) ++open;
                }
            }
            map.values.push_back(static_cast<float>(open / 1024.0));
        }
    }
    return map;
}

/// The concave fixture with a UV-mapped plane: the 1.5-unit cube (texture set 1) on `OpenPlane`
/// (texture set 0).
std::shared_ptr<const uzp::mesh::TexturingMesh> CubeOnUvPlane() {
    MeshBuilder builder;
    OpenPlane(builder, 0);
    builder.Box({-0.75f, 0.0f, -0.75f}, {0.75f, 1.5f, 0.75f}, 1);
    return builder.Build();
}

int RunViewportOcclusion(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    const auto uniform = SharedLighting(UniformEnvironment(1.0f, 1.0f, 1.0f));
    const auto sun = SharedLighting(SunEnvironment());
    const std::expected<EnvironmentImage, std::string> studioImage =
        DecodeEnvironment(Bytes(RepoRoot() / "assets/environments/studio-small-09.exr"));
    if (!studioImage) {
        Check(false, "the shipped environment decodes", studioImage.error());
        return Finish();
    }
    const auto studio = SharedLighting(*studioImage);
    MeshBuilder openPlane;
    OpenPlane(openPlane, 0);
    const auto plane = openPlane.Build();
    const auto ratioScene = [&](const std::shared_ptr<const uzp::mesh::TexturingMesh>& mesh,
                                std::vector<MaterialInputs> materials,
                                const std::shared_ptr<const EnvironmentLighting>& lighting, ViewportOutput output) {
        ViewportScene scene;
        scene.mesh = mesh;
        scene.materials = std::move(materials);
        scene.lighting = lighting;
        scene.background = {-1.0f, -1.0f, -1.0f};
        scene.output = output;
        return scene;
    };

    // 1. Negative control: an AO map of exactly 1 takes the early return, so every fixture of the
    // goldens and the concave one render bit for bit as without an AO map, colour and ratios.
    {
        std::string problem;
        size_t compared = 0;
        const std::shared_ptr<const EnvironmentLighting> lightings[] = {sun, studio};
        for (const Fixture& fixture : Fixtures()) {
            for (const auto& lighting : lightings) {
                for (const ViewportOutput output :
                     {ViewportOutput::Colour, ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
                    ViewportScene scene;
                    scene.mesh = fixture.mesh;
                    scene.materials = {fixture.material};
                    if (fixture.second) scene.materials.push_back(*fixture.second);
                    scene.lighting = lighting;
                    scene.environmentRotationDegrees = fixture.rotation;
                    scene.output = output;
                    OrbitCamera camera = FitCamera(*scene.mesh);
                    camera.yawDegrees = fixture.yaw;
                    camera.pitchDegrees = fixture.pitch;
                    const std::optional<ViewportImage> without = Render(engine, scene, PoseOf(camera), 96, 96, fixture.name);
                    for (MaterialInputs& m : scene.materials) m.occlusion = ConstantMap(1.0f, 8);
                    const std::optional<ViewportImage> with = Render(engine, scene, PoseOf(camera), 96, 96, fixture.name);
                    if (!without || !with) continue;
                    ++compared;
                    if ((without->linear != with->linear || without->display != with->display) && problem.empty()) {
                        problem = fixture.name + " output " + std::to_string(static_cast<int>(output));
                    }
                }
            }
        }
        Check(problem.empty() && compared == 24,
              "an AO map of 1 leaves every pixel of the pass without one bit for bit (colour and both ratios, the "
              "golden fixtures and the concave one)",
              problem.empty() ? std::to_string(compared) + " compared" : problem);
    }

    // 2. No micro-shadow from a normal map that does not curve: with an AO map of 1, a flat and a
    // uniformly tilted normal map on the open plane keep every diffuse and specular ratio exactly 1
    // (the AO weight reads only the AO map, and the cavity of decision 258 is 1 where the normal map
    // does not curve).
    {
        const std::vector<Fixture> fixtures = Fixtures();
        const MaterialInputs flat = UniformNormal(0.35f, 0.5f, 0.5f, 1.0f);
        const MaterialInputs tilted = UniformNormal(0.35f, 0.65f, 0.5f, 0.9f);
        std::string problem;
        size_t pixels = 0;
        for (MaterialInputs m : {flat, tilted}) {
            m.occlusion = ConstantMap(1.0f);
            for (const auto& lighting : {sun, studio}) {
                for (const double pitch : {8.0, 35.0, 70.0}) {
                    for (const ViewportOutput output : {ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
                        const ViewportScene scene = ratioScene(fixtures[1].mesh, {m}, lighting, output);
                        OrbitCamera camera = FitCamera(*scene.mesh);
                        camera.pitchDegrees = pitch;
                        camera.yawDegrees = 30.0;
                        const std::optional<ViewportImage> image = Render(engine, scene, PoseOf(camera), 96, 96, "the normal-mapped plane");
                        if (!image) continue;
                        for (size_t i = 0; i < size_t{96} * 96; ++i) {
                            if (image->linear[i * 4] == FloatToHalf(-1.0f)) continue;
                            ++pixels;
                            for (size_t c = 0; c < 3; ++c) {
                                if (image->linear[i * 4 + c] != FloatToHalf(1.0f) && problem.empty()) {
                                    problem = "pitch " + std::to_string(pitch) + " pixel " + std::to_string(i) + " ratio " +
                                              std::to_string(Linear(*image, i, c));
                                }
                            }
                        }
                    }
                }
            }
        }
        Check(problem.empty() && pixels > 10000,
              "no micro-shadow without AO or curvature: with an AO map of 1, a flat and a uniformly tilted normal map "
              "keep every diffuse and specular ratio exactly 1",
              problem.empty() ? std::to_string(pixels) + " pixels" : problem);
    }

    // 3. Fully occluded: an AO map of 0 removes every ray, so on the open plane under a uniform
    // environment (every denominator valid) both ratios and the colour are exactly 0.
    {
        MaterialInputs dielectric = Rough(0.4f);
        dielectric.occlusion = ConstantMap(0.0f);
        MaterialInputs metal = dielectric;
        metal.metalnessValue = 1.0f;
        metal.baseColorValue = {0.9f, 0.6f, 0.5f};
        std::string problem;
        size_t pixels = 0;
        for (const MaterialInputs& m : {dielectric, metal}) {
            for (const double view : {0.0, 40.0, 75.0}) {
                for (const ViewportOutput output :
                     {ViewportOutput::Colour, ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
                    const ViewportScene scene = ratioScene(plane, {m}, uniform, output);
                    const std::optional<ViewportImage> image = Render(engine, scene, PlaneView(view), 64, 64, "the plane at a = 0");
                    if (!image) continue;
                    for (size_t i = 0; i < size_t{64} * 64; ++i) {
                        if (image->linear[i * 4] == FloatToHalf(-1.0f)) continue;
                        ++pixels;
                        for (size_t c = 0; c < 3; ++c) {
                            if ((image->linear[i * 4 + c] != 0 || image->display[i * 4 + c] != 0) && problem.empty()) {
                                problem = "view " + std::to_string(view) + " output " + std::to_string(static_cast<int>(output)) +
                                          " pixel " + std::to_string(i) + " value " + std::to_string(Linear(*image, i, c));
                            }
                        }
                    }
                }
            }
        }
        Check(problem.empty() && pixels > 10000,
              "an AO map of 0 gives exactly 0: both ratios and the colour (dielectric and metal, three views)",
              problem.empty() ? std::to_string(pixels) + " pixels" : problem);
    }

    // 4. Calibration: on the open plane under a uniform environment the AO weight's cosine-weighted
    // mean is a, so a 1024-ray render's diffuse ratio is a (mean within 0.01; the largest pixel
    // error is reported), and the shipped 128 rays stay within decision 251's 0.5 / sqrt(N) of it.
    // A grazing view (82 degrees, inside decision 256's fade band) gives the same: the weight's
    // axis is the faded shading normal.
    for (const float a : {0.25f, 0.5f, 0.75f}) {
        MaterialInputs m = Rough(0.5f);
        m.occlusion = ConstantMap(a);
        ViewportScene scene = ratioScene(plane, {m}, uniform, ViewportOutput::DiffuseVisibility);
        scene.diffuseRays = 1024;
        const std::optional<ViewportImage> reference = Render(engine, scene, PlaneView(30.0), 96, 96, "the 1024-ray reference");
        scene.diffuseRays = kDiffuseVisibilityRays;
        const std::optional<ViewportImage> shipped = Render(engine, scene, PlaneView(30.0), 96, 96, "the shipped rays");
        const std::optional<ViewportImage> grazing = Render(engine, scene, PlaneView(82.0, 1.0), 96, 96, "the grazing view");
        if (!reference || !shipped || !grazing) continue;
        double largest = 0.0;
        for (size_t i = 0; i < size_t{96} * 96; ++i) {
            if (reference->linear[i * 4] == FloatToHalf(-1.0f)) continue;
            largest = std::max(largest, std::abs(static_cast<double>(Linear(*reference, i, 1)) - a));
        }
        const HitStats ref = StatsOf(*reference);
        const HitStats graze = StatsOf(*grazing);
        const double rmse = Rmse(*shipped, *reference);
        const double bound = 0.5 / std::sqrt(static_cast<double>(kDiffuseVisibilityRays));
        Info("a = " + Fixed(a, 2) + ": 1024-ray diffuse ratio mean " + Fixed(ref.mean) + " (largest pixel error " +
             Fixed(largest) + "), 128-ray RMSE " + Fixed(rmse) + " (bound " + Fixed(bound) + "), grazing view mean " +
             Fixed(graze.mean) + " over " + std::to_string(graze.pixels) + " pixels");
        Check(ref.pixels > 5000 && std::abs(ref.mean - a) <= 0.01,
              "a = " + Fixed(a, 2) + ": a 1024-ray render's diffuse ratio is a within 0.01 on the open plane (the AO "
              "weight's cosine-weighted mean)",
              Fixed(ref.mean));
        Check(rmse <= bound, "a = " + Fixed(a, 2) + ": the 128-ray diffuse ratio is within 0.5 / sqrt(128) of the 1024-ray one",
              Fixed(rmse));
        Check(graze.pixels > 1000 && std::abs(graze.mean - a) <= 0.01 && graze.low >= 0.0 && graze.high <= 1.0,
              "a = " + Fixed(a, 2) + ": at a grazing view the diffuse ratio is still a within 0.01", Fixed(graze.mean));
    }

    // 5. Directional: with a = 0.3 (k = 14 / 3), light within 25 degrees of the normal keeps most of
    // its weight and light from 65 to 85 degrees off it, a grazing band, almost none; without an AO
    // map both are kept whole. The 1024-ray diffuse ratio of each is that of the weight mu^k over
    // the environment's lit texels, sum L mu^(k + 1) dOmega / sum L mu dOmega, within 0.03 (the
    // texels' bilinear edges blur the regions).
    {
        EnvironmentImage zenith = UniformEnvironment(0.0f, 0.0f, 0.0f, 64, 32);
        EnvironmentImage band = zenith;
        constexpr double kExponent = 2.0 * (1.0 - 0.3) / 0.3;
        double zenithSeen = 0.0;
        double zenithTotal = 0.0;
        double bandSeen = 0.0;
        double bandTotal = 0.0;
        for (uint32_t y = 0; y < 32; ++y) {
            for (uint32_t x = 0; x < 64; ++x) {
                const double cosine = DirectionOf((x + 0.5) / 64.0, (y + 0.5) / 32.0)[1];
                const double degrees = std::acos(std::clamp(cosine, -1.0, 1.0)) * 180.0 / std::numbers::pi;
                const bool inZenith = degrees < 25.0;
                const bool inBand = degrees > 65.0 && degrees < 85.0;
                for (size_t c = 0; c < 3; ++c) {
                    zenith.rgb[(size_t{y} * 64 + x) * 3 + c] = inZenith ? 10.0f : 0.0f;
                    band.rgb[(size_t{y} * 64 + x) * 3 + c] = inBand ? 10.0f : 0.0f;
                }
                // Texel solid angle of the equirectangular map: proportional to the sine of the polar angle.
                const double weight = cosine * std::sqrt(std::max(0.0, 1.0 - cosine * cosine));
                if (inZenith) {
                    zenithSeen += weight * std::pow(cosine, kExponent);
                    zenithTotal += weight;
                }
                if (inBand) {
                    bandSeen += weight * std::pow(cosine, kExponent);
                    bandTotal += weight;
                }
            }
        }
        const double zenithExpected = zenithSeen / zenithTotal;
        const double bandExpected = bandSeen / bandTotal;
        const auto zenithLight = SharedLighting(zenith);
        const auto bandLight = SharedLighting(band);
        MaterialInputs m = Rough(0.5f);
        m.occlusion = ConstantMap(0.3f);
        const auto diffuse = [&](const MaterialInputs& material, const std::shared_ptr<const EnvironmentLighting>& light) {
            ViewportScene scene = ratioScene(plane, {material}, light, ViewportOutput::DiffuseVisibility);
            scene.diffuseRays = 1024;
            return scene;
        };
        const std::optional<ViewportImage> kept = Render(engine, diffuse(m, zenithLight), PlaneView(30.0), 64, 64, "light along the normal");
        const std::optional<ViewportImage> removed = Render(engine, diffuse(m, bandLight), PlaneView(30.0), 64, 64, "grazing light");
        const std::optional<ViewportImage> open =
            Render(engine, diffuse(Rough(0.5f), bandLight), PlaneView(30.0), 64, 64, "grazing light without AO");
        if (kept && removed && open) {
            const HitStats k = StatsOf(*kept);
            const HitStats r = StatsOf(*removed);
            const HitStats o = StatsOf(*open);
            Info("a = 0.3: light within 25 degrees keeps a diffuse ratio of " + Fixed(k.mean) + " (expected " +
                 Fixed(zenithExpected) + ", lowest " + Fixed(k.low) + "); the 65-85 degree band keeps " + Fixed(r.mean) +
                 " (expected " + Fixed(bandExpected) + ", highest " + Fixed(r.high) + "); without AO " + Fixed(o.mean));
            Check(k.pixels > 2000 && std::abs(k.mean - zenithExpected) <= 0.03 && std::abs(r.mean - bandExpected) <= 0.03 &&
                      k.mean > 0.75 && r.high < 0.05 && o.low == 1.0,
                  "a = 0.3 keeps most light along the normal and almost no grazing light (micro-shadows), as mu^k over "
                  "the lit texels; without AO both are kept",
                  "near " + Fixed(k.mean) + ", grazing " + Fixed(r.mean) + ", open " + Fixed(o.low));
        }
    }

    // 6. Specular occlusion: on a metal plane with a = 0.5 under a uniform environment, the 1024-ray
    // specular ratio falls with roughness (a wider lobe reaches further from the normal) and with
    // the view angle (the mirror direction moves away from it); the shipped 64 rays are within
    // 0.5 / sqrt(64) of it.
    {
        MaterialInputs metal;
        metal.metalnessValue = 1.0f;
        metal.baseColorValue = {1.0f, 1.0f, 1.0f};
        metal.occlusion = ConstantMap(0.5f);
        const auto ratio = [&](float roughness, double view, uint32_t rays) {
            MaterialInputs m = metal;
            m.roughnessValue = roughness;
            ViewportScene scene = ratioScene(plane, {m}, uniform, ViewportOutput::SpecularVisibility);
            scene.specularRays = rays;
            return Render(engine, scene, PlaneView(view), 64, 64, "the metal plane");
        };
        std::string rough;
        std::string views;
        std::vector<double> byRoughness;
        std::vector<double> byView;
        double worstRmse = 0.0;
        for (const float r : {0.1f, 0.3f, 0.5f, 0.7f, 0.9f}) {
            const std::optional<ViewportImage> high = ratio(r, 20.0, 1024);
            const std::optional<ViewportImage> low = ratio(r, 20.0, kSpecularVisibilityRays);
            if (!high || !low) continue;
            byRoughness.push_back(StatsOf(*high).mean);
            worstRmse = std::max(worstRmse, Rmse(*low, *high));
            rough += " " + Fixed(byRoughness.back(), 3);
        }
        for (const double v : {0.0, 20.0, 40.0, 60.0, 75.0}) {
            const std::optional<ViewportImage> high = ratio(0.3f, v, 1024);
            const std::optional<ViewportImage> low = ratio(0.3f, v, kSpecularVisibilityRays);
            if (!high || !low) continue;
            byView.push_back(StatsOf(*high).mean);
            worstRmse = std::max(worstRmse, Rmse(*low, *high));
            views += " " + Fixed(byView.back(), 3);
        }
        const auto falls = [](const std::vector<double>& values) {
            if (values.size() < 5) return false;
            for (size_t i = 1; i < values.size(); ++i) {
                if (values[i] > values[i - 1] + 0.002) return false;
            }
            return values.front() - values.back() > 0.1;
        };
        const double bound = 0.5 / std::sqrt(static_cast<double>(kSpecularVisibilityRays));
        Info("metal, a = 0.5: specular ratio over roughness 0.1-0.9 at 20 degrees:" + rough + "; over views 0-75 degrees at "
             "roughness 0.3:" + views + "; largest " + std::to_string(kSpecularVisibilityRays) + "-ray RMSE " + Fixed(worstRmse) + " (bound " + Fixed(bound) + ")");
        Check(falls(byRoughness), "the specular occlusion falls with roughness on a metal plane (1024 rays)", rough);
        Check(falls(byView), "the specular occlusion falls with the view angle on a metal plane (1024 rays)", views);
        Check(worstRmse <= bound, "the shipped specular ratio with an AO map (64 rays) is within 0.5 / sqrt(64) of the 1024-ray one",
              Fixed(worstRmse));
    }

    // 7. Mirrored and scaled UVs: a 2 x 2-block checker AO map of 0 and 1 on a plane whose u is
    // mirrored and whose UVs are scaled by 2 (so the map wraps) gives exactly 1 or 0 wherever the
    // four texels of the bilinear lookup, computed on the CPU from the hit point, agree.
    {
        MeshBuilder builder;
        OpenPlane(builder, 0, 2.0f, true);
        MaterialInputs m = Rough(0.5f);
        MaterialMap checker{8, 8, 1, {}};
        for (uint32_t r = 0; r < 8; ++r) {
            for (uint32_t c = 0; c < 8; ++c) checker.values.push_back(((c / 2 + r / 2) % 2) == 0 ? 1.0f : 0.0f);
        }
        m.occlusion = checker;
        OrbitCamera camera;
        camera.distance = 9.0;
        camera.pitchDegrees = 60.0;
        camera.yawDegrees = 30.0;
        const CameraPose pose = PoseOf(camera);
        constexpr uint32_t kSize = 128;
        const std::optional<ViewportImage> image =
            Render(engine, ratioScene(builder.Build(), {m}, uniform, ViewportOutput::DiffuseVisibility), pose, kSize, kSize, "the mirrored plane");
        if (image) {
            size_t ones = 0;
            size_t zeros = 0;
            std::string problem;
            for (uint32_t y = 0; y < kSize; ++y) {
                for (uint32_t x = 0; x < kSize; ++x) {
                    const auto [o, d] = PixelRay(pose, x, y, kSize, kSize);
                    if (!(d[1] < 0.0)) continue;
                    const D3 p = Along(o, d, -o[1] / d[1]);
                    if (std::abs(p[0]) > 2.95 || std::abs(p[2]) > 2.95) continue;
                    const auto [u, v] = PlaneUv(p, 2.0, true);
                    const double fx = u * 8.0 - 0.5;
                    const double fy = (1.0 - v) * 8.0 - 0.5;
                    const double tx = fx - std::floor(fx);
                    const double ty = fy - std::floor(fy);
                    if (tx < 0.02 || tx > 0.98 || ty < 0.02 || ty > 0.98) continue;
                    const auto wrap = [](int i) { return static_cast<uint32_t>(((i % 8) + 8) % 8); };
                    const int x0 = static_cast<int>(std::floor(fx));
                    const int y0 = static_cast<int>(std::floor(fy));
                    const float t00 = checker.values[wrap(y0) * 8 + wrap(x0)];
                    const float t01 = checker.values[wrap(y0) * 8 + wrap(x0 + 1)];
                    const float t10 = checker.values[wrap(y0 + 1) * 8 + wrap(x0)];
                    const float t11 = checker.values[wrap(y0 + 1) * 8 + wrap(x0 + 1)];
                    if (t00 != t01 || t00 != t10 || t00 != t11) continue;
                    const size_t i = size_t{y} * kSize + x;
                    const uint16_t expected = FloatToHalf(t00);
                    (t00 == 1.0f ? ones : zeros) += 1;
                    for (size_t c = 0; c < 3; ++c) {
                        if (image->linear[i * 4 + c] != expected && problem.empty()) {
                            problem = "pixel (" + std::to_string(x) + ", " + std::to_string(y) + ") uv (" + Fixed(u) + ", " +
                                      Fixed(v) + ") expects " + Fixed(t00, 0) + ", got " + Fixed(Linear(*image, i, c));
                        }
                    }
                }
            }
            Check(problem.empty() && ones > 300 && zeros > 300,
                  "mirrored and scaled UVs sample the AO map as the CPU does: exactly 1 and 0 where the lookup's texels agree",
                  problem.empty() ? std::to_string(ones) + " ones, " + std::to_string(zeros) + " zeros" : problem);
        }
    }

    // 8. Overlap, reported and not a pass condition: the AO weight and the BVH meet per ray, so with
    // both a pixel's ratio is at most each one alone (checked); how much darker it gets than the
    // darker of the two is the declared double darkening (reported). Fixtures: the concave fixture
    // with its own AO bake (64 x 64), the cube with a constant a = 0.5 (a one-sided blocker), and a
    // square floating 2 above the plane with a = 0.5 (a blocker near the normal, where the weight is
    // close to 1).
    {
        MeshBuilder floating;
        OpenPlane(floating, 0);
        floating.Quad({-0.5f, 2.0f, -0.5f}, {0.5f, 2.0f, -0.5f}, {0.5f, 2.0f, 0.5f}, {-0.5f, 2.0f, 0.5f}, 1);
        const MaterialMap bake = BakeCubeAo(64);
        struct Case {
            std::string name;
            std::shared_ptr<const uzp::mesh::TexturingMesh> blocked;
            MaterialMap map;
            D3 lo;
            D3 hi;
        };
        const Case cases[] = {
            {"the concave fixture with its own AO bake", CubeOnUvPlane(), bake, {-0.75, 0.0, -0.75}, {0.75, 1.5, 0.75}},
            {"the cube with a = 0.5 (one-sided)", CubeOnUvPlane(), ConstantMap(0.5f), {-0.75, 0.0, -0.75}, {0.75, 1.5, 0.75}},
            {"a square above with a = 0.5 (disjoint)", floating.Build(), ConstantMap(0.5f), {-0.5, 2.0, -0.5}, {0.5, 2.0, 0.5}},
        };
        OrbitCamera camera;
        camera.distance = 10.0;
        camera.pitchDegrees = 50.0;
        camera.yawDegrees = 20.0;
        const CameraPose pose = PoseOf(camera);
        constexpr uint32_t kSize = 128;
        std::string problem;
        size_t checked = 0;
        for (const Case& c : cases) {
            MaterialInputs withMap = Rough(0.5f);
            withMap.occlusion = c.map;
            const std::optional<ViewportImage> bvh = Render(
                engine, ratioScene(c.blocked, {Rough(0.5f), Rough(0.5f)}, uniform, ViewportOutput::DiffuseVisibility), pose, kSize, kSize, c.name);
            const std::optional<ViewportImage> weight =
                Render(engine, ratioScene(plane, {withMap}, uniform, ViewportOutput::DiffuseVisibility), pose, kSize, kSize, c.name);
            const std::optional<ViewportImage> both = Render(
                engine, ratioScene(c.blocked, {withMap, Rough(0.5f)}, uniform, ViewportOutput::DiffuseVisibility), pose, kSize, kSize, c.name);
            if (!bvh || !weight || !both) continue;
            double sumBvh = 0.0;
            double sumCone = 0.0;
            double sumBoth = 0.0;
            double excess = 0.0;
            size_t pixels = 0;
            for (uint32_t y = 0; y < kSize; ++y) {
                for (uint32_t x = 0; x < kSize; ++x) {
                    const auto [o, d] = PixelRay(pose, x, y, kSize, kSize);
                    if (!(d[1] < 0.0)) continue;
                    const double tPlane = -o[1] / d[1];
                    const D3 p = Along(o, d, tPlane);
                    // The plane near the blocker, where the camera sees the plane.
                    if (std::abs(p[0]) > 2.0 || std::abs(p[2]) > 2.0) continue;
                    if (BoxEntry(o, d, c.lo, c.hi) < tPlane) continue;
                    if (p[0] >= c.lo[0] && p[0] <= c.hi[0] && p[2] >= c.lo[2] && p[2] <= c.hi[2] && c.lo[1] == 0.0) continue;
                    const size_t i = size_t{y} * kSize + x;
                    ++pixels;
                    for (size_t ch = 0; ch < 3; ++ch) {
                        const float b = Linear(*bvh, i, ch);
                        const float k = Linear(*weight, i, ch);
                        const float w = Linear(*both, i, ch);
                        ++checked;
                        if ((w > b || w > k) && problem.empty()) {
                            problem = c.name + ": pixel (" + std::to_string(x) + ", " + std::to_string(y) + ") both " + Fixed(w) +
                                      ", BVH " + Fixed(b) + ", AO weight " + Fixed(k);
                        }
                        if (ch == 1) {
                            sumBvh += b;
                            sumCone += k;
                            sumBoth += w;
                            excess += std::min(b, k) - w;
                        }
                    }
                }
            }
            const double n = pixels ? static_cast<double>(pixels) : 1.0;
            Info("overlap, " + c.name + ": " + std::to_string(pixels) + " plane pixels near the blocker, mean diffuse ratio "
                 "BVH only " + Fixed(sumBvh / n) + ", AO weight only " + Fixed(sumCone / n) + ", both " + Fixed(sumBoth / n) +
                 "; darker than the darker of the two by " + Fixed(excess / n) + " on average (the declared double darkening)");
        }
        Check(problem.empty() && checked > 3000,
              "the AO weight and the BVH meet per ray: with both, every ratio is at most each one alone (the overlap sizes "
              "are reported)",
              problem.empty() ? std::to_string(checked) + " values" : problem);
    }

    // 9. Never brighter: the AO weight only lowers a ray's share, so with the concave fixture's own
    // bake every pixel of the colour and of both ratios is at most that of the same
    // render without the AO map (the same rays, the same denominators).
    {
        const MaterialMap bake = BakeCubeAo(64);
        MaterialInputs withMap = Rough(0.35f);
        withMap.occlusion = bake;
        MaterialInputs metalWithMap = withMap;
        metalWithMap.metalnessValue = 1.0f;
        OrbitCamera camera;
        camera.distance = 10.0;
        camera.pitchDegrees = 35.0;
        camera.yawDegrees = 20.0;
        std::string problem;
        size_t compared = 0;
        size_t darker = 0;
        for (const MaterialInputs& m : {withMap, metalWithMap}) {
            for (const ViewportOutput output :
                 {ViewportOutput::Colour, ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
                MaterialInputs without = m;
                without.occlusion.reset();
                const std::optional<ViewportImage> a =
                    Render(engine, ratioScene(CubeOnUvPlane(), {m, Rough(0.5f)}, studio, output), PoseOf(camera), 96, 96, "with the bake");
                const std::optional<ViewportImage> b = Render(
                    engine, ratioScene(CubeOnUvPlane(), {without, Rough(0.5f)}, studio, output), PoseOf(camera), 96, 96, "without it");
                if (!a || !b) continue;
                for (size_t i = 0; i < size_t{96} * 96; ++i) {
                    if (a->linear[i * 4] == FloatToHalf(-1.0f)) continue;
                    for (size_t c = 0; c < 3; ++c) {
                        ++compared;
                        const float x = Linear(*a, i, c);
                        const float y = Linear(*b, i, c);
                        if (x < y) ++darker;
                        if ((x > y || a->display[i * 4 + c] > b->display[i * 4 + c]) && problem.empty()) {
                            problem = "output " + std::to_string(static_cast<int>(output)) + " pixel " + std::to_string(i) +
                                      " with " + Fixed(x) + ", without " + Fixed(y);
                        }
                    }
                }
            }
        }
        Check(problem.empty() && compared > 50000 && darker > 1000,
              "an AO map never brightens a pixel: colour and both ratios are at most those without it (studio light, "
              "dielectric and metal)",
              problem.empty() ? std::to_string(compared) + " values, " + std::to_string(darker) + " darker" : problem);
    }

    // 10. Resident inputs (decision 257): the renders of one scene with resident inputs give the
    // bytes of renders without them; the second render reuses the first one's buffers; after
    // `Invalidate`, a changed AO map shows.
    {
        MaterialInputs half = Rough(0.4f);
        half.occlusion = ConstantMap(0.5f, 16);
        ViewportScene scene = ratioScene(CubeOnUvPlane(), {half, Rough(0.5f)}, studio, ViewportOutput::Colour);
        OrbitCamera camera;
        camera.distance = 10.0;
        camera.pitchDegrees = 40.0;
        camera.yawDegrees = 25.0;
        OrbitCamera turned = camera;
        turned.yawDegrees = 60.0;
        ResidentInputs resident;
        const std::optional<ViewportImage> first = Render(engine, scene, PoseOf(camera), 80, 80, "the first resident render", &resident);
        const std::optional<ViewportImage> second = Render(engine, scene, PoseOf(turned), 80, 80, "the second resident render", &resident);
        const std::optional<ViewportImage> plainFirst = Render(engine, scene, PoseOf(camera), 80, 80, "the first plain render");
        const std::optional<ViewportImage> plainSecond = Render(engine, scene, PoseOf(turned), 80, 80, "the second plain render");
        const bool reused = resident.Builds() == 1 && resident.Reuses() == 1;
        scene.materials[0].occlusion = ConstantMap(0.2f, 16);
        resident.Invalidate();
        const std::optional<ViewportImage> changed = Render(engine, scene, PoseOf(camera), 80, 80, "the changed resident render", &resident);
        const std::optional<ViewportImage> plainChanged = Render(engine, scene, PoseOf(camera), 80, 80, "the changed plain render");
        static_cast<void>(engine
                              .Submit(std::make_shared<const int>(0),
                                      [&](EngineContext&, const int&) -> Result<bool> {
                                          resident.Release();
                                          return true;
                                      })
                              .get());
        if (first && second && plainFirst && plainSecond && changed && plainChanged) {
            Check(first->linear == plainFirst->linear && first->display == plainFirst->display &&
                      second->linear == plainSecond->linear && second->display == plainSecond->display && reused,
                  "resident inputs give the bytes of a render without them, and a second render of the scene reuses them",
                  std::to_string(resident.Builds()) + " builds, " + std::to_string(resident.Reuses()) + " reuses");
            Check(changed->linear == plainChanged->linear && changed->linear != first->linear && resident.Builds() == 2,
                  "after Invalidate, the next resident render rebuilds its inputs and shows the changed AO map",
                  std::to_string(resident.Builds()) + " builds");
        }
    }
    return Finish();
}

// ── viewport-cavity (decision 258) ───────────────────────────────────────────────────────────

/// The cavity fixtures' plane: y = 0, 1 cm square at the Wand's scale (a mesh without a unit, so
/// its unit is read as the metre).
constexpr double kPlaneSide = 0.01;

/// An affine UV layout of the plane y = 0: (u, v) = A (x, z) + o, A in 1 / scene unit.
struct UvLayout {
    double a00 = 1.0 / kPlaneSide;
    double a01 = 0.0;
    double a10 = 0.0;
    double a11 = 1.0 / kPlaneSide;
    double o0 = 0.5;
    double o1 = 0.5;

    [[nodiscard]] uzp::mesh::Float2 Uv(double x, double z) const {
        return {static_cast<float>(a00 * x + a01 * z + o0), static_cast<float>(a10 * x + a11 * z + o1)};
    }
    [[nodiscard]] double Det() const { return a00 * a11 - a01 * a10; }
    /// The point (x, z) of (u, v).
    [[nodiscard]] std::pair<double, double> Point(double u, double v) const {
        const double du = u - o0;
        const double dv = v - o1;
        return {(a11 * du - a01 * dv) / Det(), (-a10 * du + a00 * dv) / Det()};
    }
};

/// A part of the plane: the rectangle [x0, x1] x [z0, z1] with its layout; the normal map's texels
/// with u in [uFrom, uTo) are those of this part's layout (extended past its rectangle).
struct PlanePart {
    double x0, x1, z0, z1;
    UvLayout layout;
    double uFrom = 0.0;
    double uTo = 1.0;
};

/// A height profile of x alone (UzmiGames-authored): its slope h'(x) and Laplacian h''(x).
struct Profile {
    std::function<double(double)> slope;
    std::function<double(double)> laplacian;
};

/// h = A cos(k x) with peak slope A k: concave where cos(k x) < 0.
Profile Sinusoid(double wavelength, double peakSlope) {
    const double k = 2.0 * std::numbers::pi / wavelength;
    const double a = peakSlope / k;
    return {[=](double x) { return -a * k * std::sin(k * x); }, [=](double x) { return -a * k * k * std::cos(k * x); }};
}

/// A cylindrical trough of radius r along z, centred at x = 0, out to |x| = edge (flat beyond).
Profile Trough(double r, double edge) {
    return {[=](double x) { return std::abs(x) < edge ? x / std::sqrt(r * r - x * x) : 0.0; },
            [=](double x) { return std::abs(x) < edge ? r * r / std::pow(r * r - x * x, 1.5) : 0.0; }};
}

/// h = -x^2 / (2 r) everywhere: a convex ridge, h'' = -1 / r.
Profile Ridge(double r) {
    return {[=](double x) { return -x / r; }, [=](double) { return -1.0 / r; }};
}

/// The plane's parts as a mesh, texture set 0.
std::shared_ptr<const uzp::mesh::TexturingMesh> CavityPlane(const std::vector<PlanePart>& parts) {
    MeshBuilder builder;
    for (const PlanePart& p : parts) {
        const UvLayout& l = p.layout;
        builder.QuadUv({static_cast<float>(p.x0), 0.0f, static_cast<float>(p.z0)},
                       {static_cast<float>(p.x0), 0.0f, static_cast<float>(p.z1)},
                       {static_cast<float>(p.x1), 0.0f, static_cast<float>(p.z1)},
                       {static_cast<float>(p.x1), 0.0f, static_cast<float>(p.z0)}, 0,
                       {l.Uv(p.x0, p.z0), l.Uv(p.x0, p.z1), l.Uv(p.x1, p.z1), l.Uv(p.x1, p.z0)});
    }
    return builder.Build();
}

/// The OpenGL tangent-space normal map of `profile` on the parts' layouts, `size` x `size`, float:
/// per texel the world normal normalize(-h'(x), 1, 0) of its point, in the frame MeshBuilder gives
/// the layout (T along dP/du, B = sign cross(N, T), N = +y).
MaterialMap GrooveNormalMap(uint32_t size, const std::vector<PlanePart>& parts, const Profile& profile) {
    MaterialMap map{size, size, 3, {}};
    map.values.reserve(size_t{size} * size * 3);
    for (uint32_t r = 0; r < size; ++r) {
        for (uint32_t c = 0; c < size; ++c) {
            const double u = (c + 0.5) / size;
            const double v = 1.0 - (r + 0.5) / size;
            const PlanePart* part = &parts.front();
            for (const PlanePart& p : parts) {
                if (u >= p.uFrom && u < p.uTo) part = &p;
            }
            const UvLayout& l = part->layout;
            const double x = l.Point(u, v).first;
            const double s = profile.slope(x);
            const double length = std::sqrt(1.0 + s * s);
            const D3 n{-s / length, 1.0 / length, 0.0};
            // dP/du and dP/dv of the layout, in (x, 0, z).
            const D3 pu{l.a11 / l.Det(), 0.0, -l.a10 / l.Det()};
            const D3 pv{-l.a01 / l.Det(), 0.0, l.a00 / l.Det()};
            const double tl = std::sqrt(pu[0] * pu[0] + pu[2] * pu[2]);
            const D3 t{pu[0] / tl, 0.0, pu[2] / tl};
            const D3 nt{t[2], 0.0, -t[0]};  // cross(+y, t)
            const double sign = nt[0] * pv[0] + nt[2] * pv[2] < 0.0 ? -1.0 : 1.0;
            const D3 b{sign * nt[0], 0.0, sign * nt[2]};
            const double tx = n[0] * t[0] + n[2] * t[2];
            const double ty = n[0] * b[0] + n[2] * b[2];
            map.values.insert(map.values.end(), {static_cast<float>(0.5 + 0.5 * tx), static_cast<float>(0.5 + 0.5 * ty),
                                                 static_cast<float>(0.5 + 0.5 * n[1])});
        }
    }
    return map;
}

/// The whole plane under one layout.
std::vector<PlanePart> WholePlane(const UvLayout& layout = {}) {
    return {{-kPlaneSide / 2, kPlaneSide / 2, -kPlaneSide / 2, kPlaneSide / 2, layout}};
}

/// A top-down orthographic view of the plane's centre, `extent` wide and high, from `height`.
CameraPose TopView(double extent, double height = 0.05) {
    CameraPose pose;
    pose.orthographic = true;
    pose.orthographicHeight = extent;
    pose.eye = {0.0, height, 0.0};
    pose.forward = {0.0, -1.0, 0.0};
    pose.right = {0.0, 0.0, 1.0};
    pose.up = {1.0, 0.0, 0.0};
    return pose;
}

/// A perspective view of the plane's centre from `degrees` off its normal (towards +x), at
/// `distance`.
CameraPose ObliqueView(double degrees, double distance, double fov = 30.0) {
    const double a = degrees * std::numbers::pi / 180.0;
    CameraPose pose;
    pose.fovDegrees = fov;
    pose.eye = {distance * std::sin(a), distance * std::cos(a), 0.0};
    pose.forward = {-std::sin(a), -std::cos(a), 0.0};
    pose.right = {0.0, 0.0, 1.0};
    pose.up = {std::cos(a), -std::sin(a), 0.0};
    pose.nearPlane = distance * 1e-6;
    return pose;
}

/// Where pixel (x, y)'s centre ray meets y = 0, as (x, z), for both projections.
std::optional<std::pair<double, double>> PlaneHit(const CameraPose& pose, uint32_t x, uint32_t y, uint32_t width,
                                                  uint32_t height) {
    D3 o = pose.eye;
    D3 d = pose.forward;
    if (pose.orthographic) {
        const double half = pose.orthographicHeight / 2.0;
        const double sx = ((x + 0.5) / width * 2.0 - 1.0) * half * width / height;
        const double sy = (1.0 - (y + 0.5) / height * 2.0) * half;
        for (int a = 0; a < 3; ++a) o[a] += pose.right[a] * sx + pose.up[a] * sy;
    } else {
        std::tie(o, d) = PixelRay(pose, x, y, width, height);
    }
    if (!(d[1] < 0.0)) return std::nullopt;
    const D3 p = Along(o, d, -o[1] / d[1]);
    return std::pair{p[0], p[2]};
}

/// a_cav as the pass forms it (decision 258) from the closed-form Laplacian of `profile` at pixel
/// (x, y): the footprint h per axis from the next pixels' hits on the plane (at least 1 texel of
/// the `mapSize` map), n = min(ceil(h), 3) points per axis spread over h - g with g = max(1, h / n),
/// each point's x from the layout of the part whose texels hold its u (as GrooveNormalMap writes
/// them), and the mean of 1 / (1 + r max(0, h''(x))) over them.
std::optional<double> FootprintCavity(const CameraPose& pose, uint32_t x, uint32_t y, uint32_t size,
                                      const std::vector<PlanePart>& parts, uint32_t mapSize, const Profile& profile,
                                      double radius) {
    const auto at = PlaneHit(pose, x, y, size, size);
    const auto nextX = PlaneHit(pose, x + 1, y, size, size);
    const auto nextY = PlaneHit(pose, x, y + 1, size, size);
    if (!at || !nextX || !nextY) return std::nullopt;
    const PlanePart* hitPart = &parts.front();
    for (const PlanePart& p : parts) {
        if (at->first >= p.x0 && at->first <= p.x1 && at->second >= p.z0 && at->second <= p.z1) hitPart = &p;
    }
    const UvLayout& l = hitPart->layout;
    const uzp::mesh::Float2 uv = l.Uv(at->first, at->second);
    const uzp::mesh::Float2 ux = l.Uv(nextX->first, nextX->second);
    const uzp::mesh::Float2 uy = l.Uv(nextY->first, nextY->second);
    const double w = mapSize;
    const double hu = std::max(1.0, w * std::max(std::abs(double{ux.u} - uv.u), std::abs(double{uy.u} - uv.u)));
    const double hv = std::max(1.0, w * std::max(std::abs(double{ux.v} - uv.v), std::abs(double{uy.v} - uv.v)));
    const auto points = [](double h) {
        const int n = std::min(static_cast<int>(std::ceil(h)), 3);
        const double g = std::max(1.0, h / n);
        const double spread = n > 1 ? (h - g) / (n - 1) : 0.0;
        std::vector<double> offsets;
        for (int i = 0; i < n; ++i) offsets.push_back((i - 0.5 * (n - 1)) * spread);
        return offsets;
    };
    double sum = 0.0;
    size_t count = 0;
    for (const double ov : points(hv)) {
        for (const double ou : points(hu)) {
            const double u = uv.u + ou / w;
            const double v = uv.v + ov / w;
            const double wrapped = u - std::floor(u);
            const PlanePart* part = &parts.front();
            for (const PlanePart& p : parts) {
                if (wrapped >= p.uFrom && wrapped < p.uTo) part = &p;
            }
            const double laplacian = profile.laplacian(part->layout.Point(u, v).first);
            sum += 1.0 / (1.0 + radius * std::max(0.0, laplacian));
            ++count;
        }
    }
    return sum / static_cast<double>(count);
}

/// A cavity render's per-pixel values (decision 258's output mode), -1 where the pixel shows the
/// clear colour.
struct CavityValues {
    std::vector<double> cavity;
    std::vector<double> kappa;
    std::vector<double> traced;
};

CavityValues CavityOf(const ViewportImage& image) {
    CavityValues v;
    for (size_t i = 0; i < size_t{image.width} * image.height; ++i) {
        const bool hit = image.linear[i * 4 + 2] != FloatToHalf(-1.0f);
        v.cavity.push_back(hit ? Linear(image, i, 0) : -1.0);
        v.kappa.push_back(hit ? Linear(image, i, 1) : -1.0);
        v.traced.push_back(hit ? Linear(image, i, 2) : -1.0);
    }
    return v;
}

/// The result of one analytic comparison: whether it held, the largest error as a fraction of
/// its bound, and the hits compared.
struct Analytic {
    bool ok = false;
    double worst = 0.0;
    size_t checked = 0;
};

int RunViewportCavity(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    const auto sun = SharedLighting(SunEnvironment());
    const std::expected<EnvironmentImage, std::string> studioImage =
        DecodeEnvironment(Bytes(RepoRoot() / "assets/environments/studio-small-09.exr"));
    if (!studioImage) {
        Check(false, "the shipped environment decodes", studioImage.error());
        return Finish();
    }
    const auto studio = SharedLighting(*studioImage);
    const double radius = kCavityRadiusMetres;
    const auto scene = [&](const std::shared_ptr<const uzp::mesh::TexturingMesh>& mesh, MaterialInputs material,
                           const std::shared_ptr<const EnvironmentLighting>& lighting, ViewportOutput output,
                           bool cavity = true) {
        ViewportScene s;
        s.mesh = mesh;
        s.materials = {std::move(material)};
        s.lighting = lighting;
        s.background = {-1.0f, -1.0f, -1.0f};
        s.output = output;
        s.cavity = cavity;
        return s;
    };
    const auto withNormal = [](const MaterialMap& normal, float roughness = 0.4f) {
        MaterialInputs m = Rough(roughness);
        m.normal = normal;
        return m;
    };
    // The views of the analytic checks: top-down over the plane's central 8 mm (a footprint of 2
    // texels of a 512 map) and oblique in perspective.
    constexpr uint32_t kSize = 200;
    const std::pair<std::string, CameraPose> views[] = {{"top view", TopView(0.008)},
                                                        {"oblique view", ObliqueView(35.0, 0.011)}};

    // 1. Neutral without a normal map: on the golden fixtures that bind none the cavity is never
    // computed (the third channel of the cavity output is 0 on every hit, a_cav 1, kappa 0), and
    // on the plane fixture, which binds one, it is computed on every hit.
    {
        std::string problem;
        size_t hits = 0;
        for (const Fixture& fixture : Fixtures()) {
            ViewportScene s;
            s.mesh = fixture.mesh;
            s.materials = {fixture.material};
            if (fixture.second) s.materials.push_back(*fixture.second);
            s.lighting = sun;
            s.background = {-1.0f, -1.0f, -1.0f};
            s.output = ViewportOutput::Cavity;
            OrbitCamera camera = FitCamera(*s.mesh);
            camera.yawDegrees = fixture.yaw;
            camera.pitchDegrees = fixture.pitch;
            const std::optional<ViewportImage> image = Render(engine, s, PoseOf(camera), 96, 96, fixture.name);
            if (!image) continue;
            const bool mapped = fixture.material.normal.has_value();
            const CavityValues v = CavityOf(*image);
            for (size_t i = 0; i < v.traced.size(); ++i) {
                if (v.traced[i] < 0.0) continue;
                ++hits;
                if (v.traced[i] != (mapped ? 1.0 : 0.0) && problem.empty()) {
                    problem = fixture.name + " pixel " + std::to_string(i) + " traced " + Fixed(v.traced[i], 0);
                }
                if (!mapped && (v.cavity[i] != 1.0 || v.kappa[i] != 0.0) && problem.empty()) {
                    problem = fixture.name + " pixel " + std::to_string(i) + " a_cav " + Fixed(v.cavity[i]);
                }
            }
        }
        Check(problem.empty() && hits > 5000,
              "without a normal map the cavity is not computed (the golden fixtures without one), and with one it is",
              problem.empty() ? std::to_string(hits) + " hits" : problem);
    }

    // 2. Neutral where the normal map does not curve: a flat, a uniformly tilted and a convex
    // (ridge) normal map give a_cav exactly 1 on every hit (the views keep every tap on the
    // ridge's convex region, away from its wrap), and the colour and both ratios equal those of
    // the pass with the cavity off bit for bit (both views, sun and studio light, dielectric and
    // metal).
    {
        const auto parts = WholePlane();
        const auto plane = CavityPlane(parts);
        std::vector<std::pair<std::string, MaterialInputs>> materials = {
            {"flat", UniformNormal(0.4f, 0.5f, 0.5f, 1.0f)},
            {"tilted", UniformNormal(0.4f, 0.7f, 0.35f, 0.9f)},
            {"ridge", withNormal(GrooveNormalMap(256, parts, Ridge(0.004)))},
        };
        MaterialInputs metalRidge = materials[2].second;
        metalRidge.metalnessValue = 1.0f;
        metalRidge.baseColorValue = {0.9f, 0.6f, 0.5f};
        materials.push_back({"metal ridge", metalRidge});
        std::string problem;
        size_t compared = 0;
        for (const auto& [name, m] : materials) {
            for (const auto& [viewName, pose] : views) {
                if (const std::optional<ViewportImage> cav =
                        Render(engine, scene(plane, m, sun, ViewportOutput::Cavity), pose, 96, 96, name)) {
                    const CavityValues v = CavityOf(*cav);
                    for (size_t i = 0; i < v.cavity.size(); ++i) {
                        if (v.cavity[i] >= 0.0 && v.cavity[i] != 1.0 && problem.empty()) {
                            problem = name + ", " + viewName + ": pixel " + std::to_string(i) + " a_cav " + Fixed(v.cavity[i]) +
                                      " kappa " + Fixed(v.kappa[i], 1);
                        }
                    }
                }
                for (const auto& lighting : {sun, studio}) {
                    for (const ViewportOutput output :
                         {ViewportOutput::Colour, ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
                        const std::optional<ViewportImage> on = Render(engine, scene(plane, m, lighting, output), pose, 96, 96, name);
                        const std::optional<ViewportImage> off =
                            Render(engine, scene(plane, m, lighting, output, false), pose, 96, 96, name);
                        if (!on || !off) continue;
                        ++compared;
                        if ((on->linear != off->linear || on->display != off->display) && problem.empty()) {
                            problem = name + ", " + viewName + ", output " + std::to_string(static_cast<int>(output)) +
                                      ": differs from the pass with the cavity off";
                        }
                    }
                }
            }
        }
        Check(problem.empty() && compared == 48,
              "a flat, a uniformly tilted and a convex normal map give a_cav exactly 1 and the bytes of the pass with "
              "the cavity off (colour and both ratios, dielectric and metal)",
              problem.empty() ? std::to_string(compared) + " renders compared" : problem);
    }

    // 3-5. Analytic curvature: kappa against the closed-form Laplacian h''(x) at the hit point, on
    // a sinusoidal groove (peak slope 1), a cylindrical groove whose walls reach n.z = 0.44 (slope
    // 2.06, the steep case) and a sinusoid of peak slope 5 (n.z down to 0.2) that the clamp at
    // n.z = 0.3 limits. Bounds: the sinusoid within 1 % of its peak Laplacian A k^2 (central
    // differences over a footprint of 1-3 texels and bilinear taps, both second order), the steep
    // sinusoid within 2 % of its own (the normal changes faster per texel); the cylinder within 3 %
    // of h''(x) where every tap lies inside it. a_cav is the mean of 1 / (1 + r max(0, h'')) over
    // the footprint's points (FootprintCavity) within r times the kappa bound plus the binary16
    // rounding of the output (0.002).
    const double wavelength = 0.0025;  // the 1 cm plane holds 4 periods, so the map tiles seamlessly
    const Profile sinusoid = Sinusoid(wavelength, 1.0);
    const double peak = 2.0 * std::numbers::pi / wavelength;  // A k^2 with A k = 1
    const auto analytic = [&](const std::string& what, const std::vector<PlanePart>& parts, uint32_t mapSize,
                              const Profile& profile, const std::function<std::optional<double>(double)>& bound,
                              std::vector<std::vector<double>>* cavities = nullptr) {
        Analytic result;
        const auto plane = CavityPlane(parts);
        const MaterialInputs m = withNormal(GrooveNormalMap(mapSize, parts, profile));
        double worstMapping = 0.0;
        std::string where;
        std::string mappingWhere;
        for (const auto& [viewName, pose] : views) {
            const std::optional<ViewportImage> image = Render(engine, scene(plane, m, sun, ViewportOutput::Cavity), pose, kSize, kSize, what);
            if (!image) return result;
            const CavityValues v = CavityOf(*image);
            if (cavities) cavities->push_back(v.cavity);
            for (uint32_t y = 0; y < kSize; ++y) {
                for (uint32_t x = 0; x < kSize; ++x) {
                    const size_t i = size_t{y} * kSize + x;
                    const auto at = PlaneHit(pose, x, y, kSize, kSize);
                    if (!at || v.traced[i] != 1.0) continue;
                    const std::optional<double> allowed = bound(at->first);
                    if (!allowed) continue;
                    const double expected = profile.laplacian(at->first);
                    const double error = std::abs(v.kappa[i] - expected);
                    ++result.checked;
                    if (error / *allowed > result.worst) {
                        result.worst = error / *allowed;
                        where = viewName + " x = " + Fixed(at->first * 1000.0, 3) + " mm: kappa " + Fixed(v.kappa[i], 1) +
                                ", h'' " + Fixed(expected, 1);
                    }
                    const std::optional<double> mapped = FootprintCavity(pose, x, y, kSize, parts, mapSize, profile, radius);
                    if (!mapped) continue;
                    const double mappingError = std::abs(v.cavity[i] - *mapped) / (radius * *allowed + 2e-3);
                    if (mappingError > worstMapping) {
                        worstMapping = mappingError;
                        mappingWhere = viewName + " x = " + Fixed(at->first * 1000.0, 3) + " mm: a_cav " + Fixed(v.cavity[i]) +
                                       ", expected " + Fixed(*mapped);
                    }
                }
            }
        }
        Info(what + ": " + std::to_string(result.checked) + " hits, largest error " + Fixed(result.worst, 3) +
             " of the bound (" + where + "); a_cav against the footprint's mean of 1 / (1 + r max(0, h'')): " +
             Fixed(worstMapping, 3) + " of its bound (" + mappingWhere + ")");
        result.ok = result.worst <= 1.0 && worstMapping <= 1.0;
        return result;
    };
    const auto sinusoidBound = [&](double) { return std::optional<double>{0.01 * peak}; };
    std::vector<std::vector<double>> base;
    {
        const Analytic a = analytic("sinusoid, 512 map", WholePlane(), 512, sinusoid, sinusoidBound, &base);
        double darkest = 1.0;
        for (const auto& c : base) {
            for (double value : c) {
                if (value >= 0.0) darkest = std::min(darkest, value);
            }
        }
        const double expectedDarkest = 1.0 / (1.0 + radius * peak);
        Check(a.ok && a.checked > 50000 && std::abs(darkest - expectedDarkest) < 0.01,
              "a sinusoidal groove: kappa is the closed-form Laplacian within 1 % of its peak, and a_cav darkens the "
              "groove as 1 / (1 + r kappa) with r = 0.25 mm",
              Fixed(a.worst, 3) + " of the bound, darkest " + Fixed(darkest, 4) + " (closed form " + Fixed(expectedDarkest, 4) + ")");
    }
    {
        const double r = 0.0025;
        const double edge = 0.9 * r;
        const double tap = 4.0 * kPlaneSide / 512.0;
        const Analytic a = analytic("cylindrical groove", WholePlane(), 512, Trough(r, edge), [&](double x) {
            // Every tap inside the trough.
            if (std::abs(x) > edge - tap) return std::optional<double>{};
            return std::optional<double>{0.03 * r * r / std::pow(r * r - x * x, 1.5)};
        });
        // The walls are steep: n.z = 1 / sqrt(1 + h'^2) < 0.5 where |x| > 0.866 r.
        Check(a.ok && a.checked > 20000,
              "a cylindrical groove with steep walls (n.z down to 0.44): kappa is the closed-form Laplacian within 3 %",
              Fixed(a.worst, 3) + " of the bound over " + std::to_string(a.checked) + " hits");
    }
    {
        const Profile steep = Sinusoid(wavelength, 5.0);
        const double steepPeak = 5.0 * 2.0 * std::numbers::pi / wavelength;
        const double clampSlope = std::sqrt(1.0 - 0.09) / 0.3;  // the clamped slope's largest value, 3.18
        const double tap = 4.0 * kPlaneSide / 512.0;
        const auto slopes = [&](double x) {
            const double a = std::abs(steep.slope(x - tap));
            const double b = std::abs(steep.slope(x));
            const double c = std::abs(steep.slope(x + tap));
            return std::pair{std::min({a, b, c}), std::max({a, b, c})};
        };
        // Where the slope stays below 2.5 across the taps, kappa is the closed form h''; where it
        // exceeds the clamp across them, the slope is t.x / 0.3 and kappa its derivative
        // h'' / (0.3 (1 + h'^2)^1.5) (checked below); between, neither is asserted.
        const Analytic a = analytic("clamped sinusoid", WholePlane(), 512, steep, [&](double x) {
            return slopes(x).second < 2.5 ? std::optional<double>{0.02 * steepPeak} : std::optional<double>{};
        });
        const auto plane = CavityPlane(WholePlane());
        const MaterialInputs m = withNormal(GrooveNormalMap(512, WholePlane(), steep));
        double clampedWorst = 0.0;
        double clampedLargest = 0.0;
        double unclamped = 0.0;
        size_t clamped = 0;
        if (const std::optional<ViewportImage> image =
                Render(engine, scene(plane, m, sun, ViewportOutput::Cavity), views[0].second, kSize, kSize, "the clamp")) {
            const CavityValues v = CavityOf(*image);
            for (uint32_t y = 0; y < kSize; ++y) {
                for (uint32_t x = 0; x < kSize; ++x) {
                    const auto at = PlaneHit(views[0].second, x, y, kSize, kSize);
                    if (!at || slopes(at->first).first <= clampSlope + 0.5) continue;
                    ++clamped;
                    const double s = steep.slope(at->first);
                    const double expected = steep.laplacian(at->first) / (0.3 * std::pow(1.0 + s * s, 1.5));
                    const double kappa = v.kappa[size_t{y} * kSize + x];
                    clampedWorst = std::max(clampedWorst, std::abs(kappa - expected));
                    clampedLargest = std::max(clampedLargest, std::abs(kappa));
                    unclamped = std::max(unclamped, std::abs(steep.laplacian(at->first)));
                }
            }
        }
        Info("clamp: " + std::to_string(clamped) + " hits where every tap's slope exceeds 3.68: largest |kappa| " +
             Fixed(clampedLargest, 1) + ", largest error against the clamped closed form " + Fixed(clampedWorst, 1) +
             " (the unclamped Laplacian there reaches " + Fixed(unclamped, 1) + ")");
        Check(a.ok && a.checked > 5000 && clamped > 1000 && clampedWorst <= 0.01 * steepPeak && unclamped > 0.3 * steepPeak &&
                  clampedLargest < 0.1 * unclamped,
              "the slope clamp at n.z = 0.3: on a sinusoid of peak slope 5, kappa is the clamped slope's derivative where "
              "the clamp holds every tap (within 1 % of the peak) and the closed form (within 2 %) where the slope stays "
              "below 2.5",
              Fixed(clampedWorst, 1) + " where clamped, " + Fixed(a.worst, 3) + " of the bound elsewhere");
    }

    // 6. Invariance: the same sinusoidal groove under other UV layouts gives kappa within the
    // bound of check 3 and a_cav within 0.01 of the base layout's on every hit: half the map's
    // resolution, twice the texel density (the map tiles twice), u mirrored, the layout rotated by
    // 30 degrees, sheared (u along x + 0.6 z), and two islands meeting along z = 0, the second
    // mirrored, turned and squeezed, whose texels outside each island continue its own layout (as
    // padding does).
    {
        const double c30 = std::cos(std::numbers::pi / 6.0);
        const double s30 = std::sin(std::numbers::pi / 6.0);
        const double fit = 1.0 / (c30 + s30);
        UvLayout twice;
        twice.a00 = twice.a11 = 2.0 / kPlaneSide;
        twice.o0 = twice.o1 = 0.0;
        UvLayout mirrored;
        mirrored.a00 = -1.0 / kPlaneSide;
        UvLayout rotated;
        rotated.a00 = fit * c30 / kPlaneSide;
        rotated.a01 = -fit * s30 / kPlaneSide;
        rotated.a10 = fit * s30 / kPlaneSide;
        rotated.a11 = fit * c30 / kPlaneSide;
        UvLayout sheared;
        sheared.a00 = 0.625 / kPlaneSide;
        sheared.a01 = 0.6 * 0.625 / kPlaneSide;
        sheared.a11 = 0.625 / kPlaneSide;
        const double half = kPlaneSide / 2.0;
        UvLayout islandA;  // z < 0: u = 0.02 + 0.45 (x + L/2) / L, v = 0.05 + 0.9 (z + L/2) / (L/2)
        islandA.a00 = 0.45 / kPlaneSide;
        islandA.o0 = 0.245;
        islandA.a11 = 1.8 / kPlaneSide;
        islandA.o1 = 0.95;
        UvLayout islandB;  // z >= 0: u = 0.53 + 0.9 z / L, v = 0.5 + 0.9 x / L (mirrored and turned)
        islandB.a00 = 0.0;
        islandB.a01 = 0.9 / kPlaneSide;
        islandB.o0 = 0.53;
        islandB.a10 = 0.9 / kPlaneSide;
        islandB.a11 = 0.0;
        islandB.o1 = 0.5;
        const std::vector<PlanePart> seam = {{-half, half, -half, 0.0, islandA, 0.0, 0.5},
                                             {-half, half, 0.0, half, islandB, 0.5, 1.0}};
        struct Layout {
            std::string name;
            std::vector<PlanePart> parts;
            uint32_t size;
            bool seam;
        };
        const Layout layouts[] = {
            {"half the resolution (256 map)", WholePlane(), 256, false},
            {"twice the texel density (the map tiles twice)", WholePlane(twice), 512, false},
            {"u mirrored", WholePlane(mirrored), 512, false},
            {"rotated 30 degrees", WholePlane(rotated), 512, false},
            {"sheared", WholePlane(sheared), 512, false},
            {"two islands across a seam, one mirrored", seam, 512, true},
        };
        std::string problem;
        double worstShift = 0.0;
        double seamShift = 0.0;
        size_t seamPixels = 0;
        for (const Layout& layout : layouts) {
            std::vector<std::vector<double>> other;
            const Analytic a = analytic("sinusoid, " + layout.name, layout.parts, layout.size, sinusoid, sinusoidBound, &other);
            double shift = 0.0;
            for (size_t view = 0; view < std::min(base.size(), other.size()); ++view) {
                for (size_t i = 0; i < base[view].size(); ++i) {
                    if (base[view][i] < 0.0 || other[view][i] < 0.0) continue;
                    const double d = std::abs(base[view][i] - other[view][i]);
                    shift = std::max(shift, d);
                    if (layout.seam) {
                        const auto at = PlaneHit(views[view].second, static_cast<uint32_t>(i % kSize),
                                                 static_cast<uint32_t>(i / kSize), kSize, kSize);
                        if (at && std::abs(at->second) < 0.0002) {
                            seamShift = std::max(seamShift, d);
                            ++seamPixels;
                        }
                    }
                }
            }
            worstShift = std::max(worstShift, shift);
            Info(layout.name + ": a_cav within " + Fixed(shift, 4) + " of the base layout's");
            if ((!a.ok || a.checked < 50000 || other.size() != base.size() || shift > 0.01) && problem.empty()) {
                problem = layout.name + ": " + Fixed(a.worst, 3) + " of the kappa bound, a_cav shift " + Fixed(shift, 4);
            }
        }
        Info("seam: on " + std::to_string(seamPixels) + " hits within 0.2 mm of z = 0, a_cav within " + Fixed(seamShift, 4) +
             " of the base layout's");
        Check(!base.empty() && problem.empty() && seamPixels > 500,
              "the cavity does not change with the map's resolution, the texel density, mirrored, rotated or sheared UVs, "
              "or across a UV seam: kappa within the bound and a_cav within 0.01",
              problem.empty() ? "largest a_cav shift " + Fixed(worstShift, 4) : problem);
    }

    // 7. The radius is a world length: the same groove modelled in centimetres, in a file that
    // states its unit (the scene is then in centimetres), gives the a_cav of the mesh without a
    // unit read in metres.
    {
        uzp::mesh::TexturingMesh centimetres = *CavityPlane(WholePlane());
        for (auto& p : centimetres.positions) {
            p.x *= 100.0f;
            p.z *= 100.0f;
        }
        centimetres.units.source = "centimeter";
        centimetres.units.source_meters_per_unit = 0.01;
        centimetres.units.scale_to_internal = 1.0;
        const auto stated = std::make_shared<const uzp::mesh::TexturingMesh>(std::move(centimetres));
        const auto unstated = CavityPlane(WholePlane());
        const MaterialInputs m = withNormal(GrooveNormalMap(512, WholePlane(), sinusoid));
        const std::optional<ViewportImage> metres =
            Render(engine, scene(unstated, m, sun, ViewportOutput::Cavity), TopView(0.008), 96, 96, "the groove in metres");
        const std::optional<ViewportImage> cm =
            Render(engine, scene(stated, m, sun, ViewportOutput::Cavity), TopView(0.8, 5.0), 96, 96, "the groove in centimetres");
        if (metres && cm) {
            const CavityValues a = CavityOf(*metres);
            const CavityValues b = CavityOf(*cm);
            double shift = 0.0;
            double darkest = 1.0;
            for (size_t i = 0; i < a.cavity.size(); ++i) {
                shift = std::max(shift, std::abs(a.cavity[i] - b.cavity[i]));
                darkest = std::min(darkest, b.cavity[i]);
            }
            Check(SceneUnitKnown(*stated) && !SceneUnitKnown(*unstated) && shift <= 0.002 && darkest < 0.7,
                  "the radius is 0.25 mm in the world: a mesh that states centimetres gives the a_cav of the same groove "
                  "without a unit, read in metres",
                  "largest difference " + Fixed(shift, 4) + ", darkest " + Fixed(darkest, 3));
        }
    }

    // 8. Never brighter, and metal too: on the sinusoidal groove (dielectric and metal, both views,
    // studio light) the colour and both ratios are at most those of the pass with the cavity off,
    // and a metal's colour, all specular, is at most that pass's colour times a_cav (the specular
    // term keeps the darker of the weighted ratio and a_cav times the ratio without the cavity),
    // within the binary16 rounding of the three outputs (relative 2e-3).
    {
        const auto plane = CavityPlane(WholePlane());
        const MaterialInputs dielectric = withNormal(GrooveNormalMap(512, WholePlane(), sinusoid), 0.35f);
        MaterialInputs metal = dielectric;
        metal.metalnessValue = 1.0f;
        metal.baseColorValue = {0.9f, 0.6f, 0.5f};
        std::string problem;
        size_t compared = 0;
        size_t metalDarker = 0;
        double metalDarkest = 1.0;
        for (const MaterialInputs* m : std::initializer_list<const MaterialInputs*>{&dielectric, &metal}) {
            for (const auto& [viewName, pose] : views) {
                const std::optional<ViewportImage> cav = Render(engine, scene(plane, *m, studio, ViewportOutput::Cavity), pose, 96, 96, "a_cav");
                if (!cav) continue;
                const CavityValues v = CavityOf(*cav);
                for (const ViewportOutput output :
                     {ViewportOutput::Colour, ViewportOutput::DiffuseVisibility, ViewportOutput::SpecularVisibility}) {
                    const std::optional<ViewportImage> on = Render(engine, scene(plane, *m, studio, output), pose, 96, 96, "with the cavity");
                    const std::optional<ViewportImage> off =
                        Render(engine, scene(plane, *m, studio, output, false), pose, 96, 96, "without it");
                    if (!on || !off) continue;
                    const std::string where = viewName + " output " + std::to_string(static_cast<int>(output));
                    for (size_t i = 0; i < size_t{96} * 96; ++i) {
                        if (on->linear[i * 4] == FloatToHalf(-1.0f) || v.cavity[i] < 0.0) continue;
                        for (size_t c = 0; c < 3; ++c) {
                            ++compared;
                            const double a = Linear(*on, i, c);
                            const double b = Linear(*off, i, c);
                            const bool metalColour = m == &metal && output == ViewportOutput::Colour;
                            if (metalColour && a < b) {
                                ++metalDarker;
                                metalDarkest = std::min(metalDarkest, a / b);
                            }
                            if ((a > b || on->display[i * 4 + c] > off->display[i * 4 + c] ||
                                 (metalColour && a > b * v.cavity[i] + 2e-3 * b + 1e-7)) &&
                                problem.empty()) {
                                problem = where + " pixel " + std::to_string(i) + ": with " + Fixed(a, 6) + ", without " +
                                          Fixed(b, 6) + ", a_cav " + Fixed(v.cavity[i], 4);
                            }
                        }
                    }
                }
            }
        }
        Info("metal: " + std::to_string(metalDarker) + " values darker with the cavity, the darkest at " +
             Fixed(metalDarkest, 3) + " of the pass without it");
        Check(problem.empty() && compared > 50000 && metalDarker > 5000 && metalDarkest < 0.7,
              "the cavity never brightens a pixel (colour and both ratios at most those with it off) and darkens a metal's "
              "colour at least by a_cav within the binary16 rounding (studio light)",
              problem.empty() ? std::to_string(compared) + " values" : problem);
    }

    // 9. Minification: the groove tiled over a 10 cm plane seen from far away at a grazing angle,
    // where a pixel spans up to tens of texels. The high-pass energy of a_cav (the RMS of a_cav
    // minus its 3 x 3 mean) in the 128 x 128 render stays within twice, plus 0.005, that of the
    // same view rendered at 8 x 8 times the pixels and box-filtered down (a supersampled
    // reference): the footprint spacing keeps the cavity from aliasing into speckle.
    {
        UvLayout tiled;
        tiled.o0 = tiled.o1 = 0.0;
        const double big = 0.1;
        const std::vector<PlanePart> wide = {{-big / 2, big / 2, -big / 2, big / 2, tiled}};
        const auto plane = CavityPlane(wide);
        const MaterialInputs m = withNormal(GrooveNormalMap(512, WholePlane(tiled), sinusoid));
        const CameraPose distant = ObliqueView(70.0, 0.12, 30.0);
        constexpr uint32_t kSmall = 128;
        constexpr uint32_t kSuper = 8;
        const std::optional<ViewportImage> low = Render(engine, scene(plane, m, sun, ViewportOutput::Cavity), distant, kSmall, kSmall, "the far groove");
        const std::optional<ViewportImage> high = Render(engine, scene(plane, m, sun, ViewportOutput::Cavity), distant,
                                                         kSmall * kSuper, kSmall * kSuper, "the supersampled far groove");
        if (low && high) {
            const CavityValues lv = CavityOf(*low);
            const CavityValues hv = CavityOf(*high);
            std::vector<double> reference(size_t{kSmall} * kSmall, -1.0);
            for (uint32_t y = 0; y < kSmall; ++y) {
                for (uint32_t x = 0; x < kSmall; ++x) {
                    double sum = 0.0;
                    bool all = true;
                    for (uint32_t j = 0; j < kSuper; ++j) {
                        for (uint32_t i = 0; i < kSuper; ++i) {
                            const double a = hv.cavity[size_t{y * kSuper + j} * kSmall * kSuper + x * kSuper + i];
                            all = all && a >= 0.0;
                            sum += a;
                        }
                    }
                    if (all) reference[size_t{y} * kSmall + x] = sum / (kSuper * kSuper);
                }
            }
            const auto highPass = [&](const std::vector<double>& image) {
                double squared = 0.0;
                size_t count = 0;
                for (uint32_t y = 1; y + 1 < kSmall; ++y) {
                    for (uint32_t x = 1; x + 1 < kSmall; ++x) {
                        double sum = 0.0;
                        bool all = true;
                        for (uint32_t j = y - 1; j <= y + 1; ++j) {
                            for (uint32_t i = x - 1; i <= x + 1; ++i) {
                                const double a = image[size_t{j} * kSmall + i];
                                all = all && a >= 0.0 && reference[size_t{j} * kSmall + i] >= 0.0 && lv.cavity[size_t{j} * kSmall + i] >= 0.0;
                                sum += a;
                            }
                        }
                        if (!all) continue;
                        const double e = image[size_t{y} * kSmall + x] - sum / 9.0;
                        squared += e * e;
                        ++count;
                    }
                }
                return std::pair{count ? std::sqrt(squared / static_cast<double>(count)) : 0.0, count};
            };
            const auto [lowEnergy, lowCount] = highPass(lv.cavity);
            const auto [refEnergy, refCount] = highPass(reference);
            // The mean darkening 1 - a_cav over the hits of both renders.
            const auto darkening = [&](const std::vector<double>& image) {
                double sum = 0.0;
                size_t count = 0;
                for (size_t i = 0; i < image.size(); ++i) {
                    if (image[i] < 0.0 || reference[i] < 0.0 || lv.cavity[i] < 0.0) continue;
                    sum += 1.0 - image[i];
                    ++count;
                }
                return count ? sum / static_cast<double>(count) : 0.0;
            };
            const double lowDarkening = darkening(lv.cavity);
            const double refDarkening = darkening(reference);
            Info("minification: high-pass RMS of a_cav " + Fixed(lowEnergy, 4) + " against " + Fixed(refEnergy, 4) +
                 " supersampled, mean darkening " + Fixed(lowDarkening, 4) + " against " + Fixed(refDarkening, 4) + ", over " +
                 std::to_string(lowCount) + " pixels");
            Check(lowCount > 3000 && lowCount == refCount && lowEnergy <= 2.0 * refEnergy + 0.005,
                  "minified, the cavity's high-pass energy stays within twice (plus 0.005) that of a supersampled reference",
                  Fixed(lowEnergy, 4) + " against " + Fixed(refEnergy, 4));
            // The footprint is covered by at most 3 x 3 curvature points, so at the far pixels
            // (about 75 texels along the grazing axis) their spacing reaches 25 texels of the
            // groove's 128-texel period and the central differences keep about
            // sin(k g) / (k g) = 0.77 of the curvature: the bound is three quarters.
            Check(lowCount > 3000 && lowEnergy >= 0.75 * refEnergy && lowDarkening >= 0.75 * refDarkening && refDarkening > 0.01,
                  "minified, the cavity keeps at least three quarters of a supersampled reference's high-pass energy and "
                  "mean darkening (a crease and its convex shoulders in one footprint do not cancel)",
                  Fixed(lowEnergy / std::max(refEnergy, 1e-12), 3) + " of the energy, " +
                      Fixed(lowDarkening / std::max(refDarkening, 1e-12), 3) + " of the darkening");
        }
    }
    return Finish();
}

// ── viewport-occlusion-time (decision 257: the AO map's cost) ─────────────────────────────────

int RunViewportOcclusionTime(const fs::path& dir, const fs::path& meshPath, const fs::path& environmentPath) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    uzp::mesh::ImportResult imported = uzp::mesh::ImportMeshFile(meshPath, {});
    const auto mesh = std::make_shared<const uzp::mesh::TexturingMesh>(std::move(imported.mesh));
    const std::expected<EnvironmentImage, std::string> environment = DecodeEnvironment(Bytes(environmentPath));
    if (!environment) {
        Check(false, "the environment decodes", environment.error());
        return Finish();
    }
    ViewportScene scene;
    scene.mesh = mesh;
    scene.lighting = SharedLighting(*environment);
    const CameraPose pose = PoseOf(FitCamera(*mesh));
    const std::pair<uint32_t, uint32_t> sizes[] = {{660, 600}, {1700, 1250}};
    // The Wand's maps at 2048 x 2048: base colour, metalness, roughness and normal, then the AO map.
    constexpr uint32_t kSide = 2048;
    const auto constant = [](uint32_t components, std::vector<float> value) {
        MaterialMap map{kSide, kSide, components, {}};
        map.values.reserve(size_t{kSide} * kSide * components);
        for (size_t i = 0; i < size_t{kSide} * kSide; ++i) map.values.insert(map.values.end(), value.begin(), value.end());
        return map;
    };
    MaterialInputs wandMaps;
    wandMaps.baseColor = constant(3, {0.4f, 0.3f, 0.2f});
    wandMaps.metalness = constant(1, {0.0f});
    wandMaps.roughness = constant(1, {0.5f});
    wandMaps.normal = constant(3, {0.5f, 0.5f, 1.0f});
    MaterialInputs wandWithAo = wandMaps;
    wandWithAo.occlusion = constant(1, {0.5f});
    struct Row {
        const char* name;
        const MaterialInputs* material;
        bool cavity = true;
    };
    const MaterialInputs none;
    // The normal map is flat: the cavity (decision 258) runs its taps (four per point, up to 3 x 3 points over the footprint) on every hit and gives 1.
    const Row rows[] = {{"no maps", &none},
                        {"four 2048 x 2048 maps, the cavity off", &wandMaps, false},
                        {"four 2048 x 2048 maps", &wandMaps},
                        {"four maps and a 2048 x 2048 AO map of 0.5", &wandWithAo}};
    double windowResident = 0.0;
    double windowP95 = 0.0;
    for (const auto& [width, height] : sizes) {
        for (const Row& row : rows) {
            scene.materials.assign(std::max<size_t>(1, mesh->materials.size()), *row.material);
            scene.cavity = row.cavity;
            // Every render uploads every input (a capture), then one scene rendered again and again
            // from resident inputs (the window between revisions); the first resident render builds them.
            std::vector<double> plain;
            std::vector<double> resident;
            double build = 0.0;
            for (int run = 0; run < 4; ++run) {
                const auto start = std::chrono::steady_clock::now();
                if (!Render(engine, scene, pose, width, height, "the timed render")) return Finish();
                const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
                if (run > 0) plain.push_back(ms);  // the first run also compiles the kernel
            }
            ResidentInputs inputs;
            for (int run = 0; run < 21; ++run) {
                const auto start = std::chrono::steady_clock::now();
                if (!Render(engine, scene, pose, width, height, "the timed resident render", &inputs)) return Finish();
                const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
                if (run == 0) {
                    build = ms;
                } else {
                    resident.push_back(ms);
                }
            }
            static_cast<void>(engine
                                  .Submit(std::make_shared<const int>(0),
                                          [&](EngineContext&, const int&) -> Result<bool> {
                                              inputs.Release();
                                              return true;
                                          })
                                  .get());
            std::sort(plain.begin(), plain.end());
            std::sort(resident.begin(), resident.end());
            // The median and the 95th percentile (the 19th of 20) of the resident renders.
            const double median = (resident[9] + resident[10]) / 2.0;
            const double p95 = resident[18];
            Info(std::to_string(width) + " x " + std::to_string(height) + ", rays (" + std::to_string(kDiffuseVisibilityRays) +
                 ", " + std::to_string(kSpecularVisibilityRays) + "), " + row.name + ": " + Fixed(plain[1], 1) +
                 " ms uploading every input (median of 3), " + Fixed(build, 1) + " ms building the resident inputs, " +
                 Fixed(median, 1) + " ms from them (median of 20, p95 " + Fixed(p95, 1) + " ms)");
            if (width == 660 && row.material == &wandWithAo) {
                windowResident = median;
                windowP95 = p95;
            }
        }
    }
    Check(windowResident > 0.0 && windowP95 < 200.0,
          "at the window's default size, with the Wand's five 2048 x 2048 maps and the cavity, a render from resident "
          "inputs fits the 200 ms period (p95 of 20)",
          "median " + Fixed(windowResident, 1) + " ms, p95 " + Fixed(windowP95, 1) + " ms");
    return Finish();
}

// ── viewport-ladder (decision 251: the counts are chosen by measurement) ──────────────────────

int RunViewportLadder(const fs::path& dir, const fs::path& meshPath, const fs::path& environmentPath,
                      const fs::path& reportPath) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    uzp::mesh::ImportResult imported = uzp::mesh::ImportMeshFile(meshPath, {});
    const auto mesh = std::make_shared<const uzp::mesh::TexturingMesh>(std::move(imported.mesh));
    const std::expected<EnvironmentImage, std::string> environment = DecodeEnvironment(Bytes(environmentPath));
    if (!environment) {
        Check(false, "the environment decodes", environment.error());
        return Finish();
    }
    ViewportScene scene;
    scene.mesh = mesh;
    scene.materials.resize(mesh->materials.size());
    scene.lighting = SharedLighting(*environment);
    const CameraPose pose = PoseOf(FitCamera(*mesh));

    const std::vector<float> corners = WorldCorners(*mesh);
    std::vector<double> builds;
    for (int run = 0; run < 5; ++run) {
        const auto start = std::chrono::steady_clock::now();
        const VisibilityBvh bvh = BuildVisibilityBvh(corners);
        builds.push_back(std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count());
        static_cast<void>(bvh);
    }
    std::sort(builds.begin(), builds.end());
    Info("mesh " + meshPath.filename().string() + ": " + std::to_string(corners.size() / 9) + " triangles; BVH build " +
         std::to_string(builds[2]) + " ms (median of 5)");
    json::Array rows;
    const std::pair<uint32_t, uint32_t> sizes[] = {{660, 600}, {1700, 1250}};
    const std::pair<uint32_t, uint32_t> counts[] = {{0, 0}, {8, 4}, {16, 8}, {32, 16}, {64, 32}, {128, 64}, {256, 128}};
    for (const auto& [width, height] : sizes) {
        scene.diffuseRays = 1024;
        scene.specularRays = 1024;
        const std::optional<ViewportImage> reference = Render(engine, scene, pose, width, height, "the reference");
        if (!reference) return Finish();
        for (const auto& [diffuse, specular] : counts) {
            scene.diffuseRays = diffuse;
            scene.specularRays = specular;
            std::vector<double> times;
            std::optional<ViewportImage> image;
            for (int run = 0; run < 4; ++run) {
                const auto start = std::chrono::steady_clock::now();
                image = Render(engine, scene, pose, width, height, "the ladder");
                const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
                if (run > 0) times.push_back(ms);  // the first run also compiles the kernel
                if (!image) return Finish();
            }
            std::sort(times.begin(), times.end());
            double squared = 0.0;
            double sum = 0.0;
            size_t samples = 0;
            for (size_t i = 0; i < size_t{width} * height; ++i) {
                if (reference->linear[i * 4] == image->linear[i * 4] && reference->linear[i * 4] == FloatToHalf(0.1f)) continue;
                for (size_t c = 0; c < 3; ++c) {
                    const double e = static_cast<double>(Linear(*image, i, c)) - Linear(*reference, i, c);
                    squared += e * e;
                    sum += Linear(*reference, i, c);
                    ++samples;
                }
            }
            const double rmse = samples ? std::sqrt(squared / samples) : 0.0;
            const double mean = samples ? sum / samples : 0.0;
            Info(std::to_string(width) + " x " + std::to_string(height) + " (" + std::to_string(diffuse) + ", " +
                 std::to_string(specular) + "): " + std::to_string(times[1]) + " ms (median of 3), RMSE " +
                 std::to_string(rmse) + " against (1024, 1024), mean " + std::to_string(mean));
            rows.push_back(json::Object{{"size", json::Array{static_cast<std::int64_t>(width), static_cast<std::int64_t>(height)}},
                                        {"diffuse_rays", static_cast<std::int64_t>(diffuse)},
                                        {"specular_rays", static_cast<std::int64_t>(specular)},
                                        {"milliseconds", times[1]},
                                        {"rmse", rmse},
                                        {"mean", mean}});
        }
    }
    if (!reportPath.empty()) {
        const json::Object report{{"mesh", meshPath.filename().string()},
                                  {"triangles", static_cast<std::int64_t>(corners.size() / 9)},
                                  {"bvh_build_milliseconds", builds[2]},
                                  {"rows", rows}};
        std::ofstream(reportPath, std::ios::binary) << json::WriteCanonical(json::Value(report)) << "\n";
    }
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
                     "viewport-normal-fade <work-dir> | viewport-golden <work-dir> <goldens.json> [--bless] | viewport-visibility <work-dir> | "
                     "viewport-occlusion <work-dir> | viewport-cavity <work-dir> | viewport-occlusion-time <work-dir> <mesh> <environment> | viewport-ladder <work-dir> <mesh> <environment> [<report.json>]\n");
        return 2;
    }
    const fs::path dir = argv[2];
    std::error_code ec;
    fs::create_directories(dir, ec);
    uz::LogInit((dir / ("preview-tests-" + std::string(mode) + ".log")).string().c_str());
    uz::LogSuppressConsole();
    int code = 2;
    if (mode == "viewport-spirv") {
        code = RunViewportSpirv(dir);
    } else if (mode == "viewport-backend" && argc == 4) {
        code = RunViewportBackend(dir, argv[3]);
    } else if (mode == "viewport-unsupported") {
        code = RunViewportUnsupported(dir);
    } else if (mode == "lighting-cache") {
        code = RunLightingCache(dir);
    } else if (mode == "viewport-normal-fade") {
        code = RunViewportNormalFade(dir);
    } else if (mode == "viewport-golden" && argc >= 4) {
        code = RunViewportGolden(dir, argv[3], argc >= 5 && std::string_view(argv[4]) == "--bless");
    } else if (mode == "viewport-visibility") {
        code = RunViewportVisibility(dir);
    } else if (mode == "viewport-occlusion") {
        code = RunViewportOcclusion(dir);
    } else if (mode == "viewport-cavity") {
        code = RunViewportCavity(dir);
    } else if (mode == "viewport-occlusion-time" && argc >= 5) {
        code = RunViewportOcclusionTime(dir, argv[3], argv[4]);
    } else if (mode == "viewport-ladder" && argc >= 5) {
        code = RunViewportLadder(dir, argv[3], argv[4], argc >= 6 ? fs::path(argv[5]) : fs::path());
    } else {
        std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    }
    uz::LogShutdown();
    return code;
}
