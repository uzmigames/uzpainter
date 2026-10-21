// CPU tests of the `painter_iray` path tracer's sampling foundations (src/render/pathtracer/,
// rulebook task phase3.4_path-tracer-transport items 2.4, 2.6 (CPU distribution and density),
// 2.8, 3.2 (sampling density part) and 3.3). Built by `zig build pathtracer-tests` and driven by
// tests/render/test_pathtracer_sampler.py. No GPU: every case runs on the CPU.
//
// Every expectation is deterministic: fixed seeds, exact values derived by hand in the comments
// (the Sobol direction numbers from the Joe-Kuo recurrence, the first eight points, texel
// probabilities, the analytic irradiance of a piecewise-constant environment), exact
// stratification properties, or a bound stated beside the check. A statistical check states its
// bound and prints the measured value in an `INFO` line.
//
// Usage: uzp-pathtracer-tests <case>
//   sobol        Owen-scrambled Sobol: direction numbers, first points, nested scrambling,
//                1D and (0,2) stratification, seeds
//   sobol-dump   one `VALUES <json>` line of sample bits for the comparison with the Phase 0
//                prototype (tools/parity/render_fits/sampler.py)
//   lambert      the Lambert lobe behind the BSDF interface
//   environment  the piecewise-constant 2D environment distribution and its densities
//   env-mis      one-bounce irradiance of a single bright patch with environment sampling,
//                Lambert sampling and their power-heuristic combination, against the analytic
//                value
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` lines and `INFO` lines. Exit code 0 when
// every check passed, 1 when one failed, 2 on a usage error.

#include "../no_error_dialogs.h"

#include "render/pathtracer/bsdf.h"
#include "render/pathtracer/environment_distribution.h"
#include "render/pathtracer/sobol.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <iterator>
#include <set>
#include <string>
#include <vector>

namespace pt = uzp::render::pathtracer;

namespace {

int g_failures = 0;
constexpr double kPi = 3.14159265358979323846;

void Check(bool ok, const std::string& name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %s\n", name.c_str());
    } else {
        ++g_failures;
        std::printf("FAIL %s: %s\n", name.c_str(), detail.c_str());
    }
}

std::string Hex(uint32_t v) {
    char buffer[16];
    std::snprintf(buffer, sizeof buffer, "0x%08X", v);
    return buffer;
}

// ── sobol ───────────────────────────────────────────────────────────────────────────────────

void CaseSobol() {
    // Direction numbers v_i = m_i / 2^i from the Joe-Kuo recurrence
    // m_i = 2 a_1 m_(i-1) ^ 4 a_2 m_(i-2) ^ ... ^ 2^s m_(i-s) ^ m_(i-s), derived by hand:
    //   x + 1        (s 1):        m = 1, 3, 5, 15
    //   x^2 + x + 1  (s 2, a_1 1): m = 1, 3, 3, 9
    //   x^3 + x + 1  (s 3, a_2 1): m = 1, 3, 1, 5
    // and the van der Corput sequence for component 0 (m_i = 1).
    const uint32_t m[4][4] = {{1, 1, 1, 1}, {1, 3, 5, 15}, {1, 3, 3, 9}, {1, 3, 1, 5}};
    bool directions = true;
    std::string detail;
    for (uint32_t c = 0; c < 4; ++c) {
        for (uint32_t i = 0; i < 4; ++i) {
            const uint32_t expected = m[c][i] << (31 - i);
            if (pt::SobolDirection(c, i) != expected) {
                directions = false;
                detail = "component " + std::to_string(c) + " bit " + std::to_string(i) + ": " +
                         Hex(pt::SobolDirection(c, i)) + " != " + Hex(expected);
            }
        }
    }
    Check(directions, "Sobol direction numbers match the hand-derived m_i of components 0-3",
          detail);

    // Points 0-7 in eighths, the XOR of the directions above selected by the index bits.
    const uint32_t eighths[4][8] = {
        {0, 4, 2, 6, 1, 5, 3, 7},
        {0, 4, 6, 2, 5, 1, 3, 7},
        {0, 4, 6, 2, 3, 7, 5, 1},
        {0, 4, 6, 2, 1, 5, 7, 3},
    };
    bool first_points = true;
    for (uint32_t c = 0; c < 4; ++c) {
        for (uint32_t i = 0; i < 8; ++i) {
            if (pt::Sobol(i, c) != eighths[c][i] << 29) {
                first_points = false;
                detail = "component " + std::to_string(c) + " index " + std::to_string(i) +
                         ": " + Hex(pt::Sobol(i, c));
            }
        }
    }
    Check(first_points, "unscrambled Sobol points 0-7 equal the hand-derived eighths", detail);

    Check(pt::ReverseBits(1u) == 0x80000000u && pt::ReverseBits(0x0000F00Du) == 0xB00F0000u &&
              pt::ReverseBits(pt::ReverseBits(0x12345678u)) == 0x12345678u,
          "ReverseBits reverses the bit order");
    // hash_combine(0, 0) = 0 ^ (0 + 0x9E3779B9 + 0 + 0) and hash_combine(1, 2) =
    // 1 ^ (2 + 0x9E3779B9 + 64 + 0) = 1 ^ 0x9E3779FB.
    Check(pt::HashCombine(0, 0) == 0x9E3779B9u && pt::HashCombine(1, 2) == 0x9E3779FAu,
          "HashCombine follows Burley 2020's seed ^ (v + 0x9E3779B9 + (seed << 6) + (seed >> 2))");
    // The permutation of 0 under seed 0 is 0 (every product of 0 is 0).
    Check(pt::LaineKarrasPermutation(0, 0) == 0, "Laine-Karras permutation of 0 under seed 0");

    // Nested (Owen) scrambling: values sharing their top k bits keep sharing them, and the
    // scramble is a bijection on every aligned block of 2^m values (checked for m = 12).
    bool nested = true;
    for (uint32_t seed : {0u, 7u, 0xDEADBEEFu}) {
        for (uint32_t k = 1; k < 32 && nested; ++k) {
            const uint32_t base = 0xA5C3F00Fu;
            const uint32_t mask = ~0u << (32 - k);
            const uint32_t other = (base & mask) | (~base & ~mask);
            const uint32_t a = pt::NestedUniformScramble(base, seed);
            const uint32_t b = pt::NestedUniformScramble(other, seed);
            if ((a & mask) != (b & mask)) {
                nested = false;
                detail = "seed " + Hex(seed) + " k " + std::to_string(k);
            }
        }
        std::set<uint32_t> low;
        const uint32_t block = 0x7u << 12;
        uint32_t top = 0;
        for (uint32_t i = 0; i < 4096; ++i) {
            const uint32_t s = pt::NestedUniformScramble(block + i, seed);
            if (i == 0) top = s >> 12;
            if ((s >> 12) != top) nested = false;
            low.insert(s & 0xFFFu);
        }
        if (low.size() != 4096) {
            nested = false;
            detail = "block of 4096 not a bijection under seed " + Hex(seed);
        }
    }
    Check(nested, "Owen scrambling keeps shared top bits and permutes aligned blocks", detail);

    // 1D stratification: for every aligned block of 2^m sample indices, the values of one
    // dimension put exactly one value in each interval of width 2^-m.
    bool strat1d = true;
    for (uint32_t render_seed : {0u, 7u, 0xDEADBEEFu}) {
        for (uint32_t pixel : {0u, 1u, 4097u}) {
            const uint32_t ps = pt::PixelSeed(pixel, render_seed);
            for (uint32_t dim = 0; dim < 16 && strat1d; ++dim) {
                for (uint32_t mbits = 0; mbits <= 12 && strat1d; ++mbits) {
                    const uint32_t n = 1u << mbits;
                    for (uint32_t block : {0u, 3u}) {
                        std::vector<uint8_t> seen(n, 0);
                        for (uint32_t i = 0; i < n; ++i) {
                            const uint32_t bits = pt::SampleBits(ps, block * n + i, dim);
                            const uint32_t cell = mbits == 0 ? 0 : bits >> (32 - mbits);
                            if (seen[cell]++ != 0) {
                                strat1d = false;
                                detail = "seed " + Hex(render_seed) + " pixel " +
                                         std::to_string(pixel) + " dim " + std::to_string(dim) +
                                         " n " + std::to_string(n);
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
    Check(strat1d,
          "every dimension 0-15 is stratified: one value per 2^-m interval in each aligned block "
          "of 2^m indices (m 0-12, three seeds, three pixels)",
          detail);

    // (0,2) stratification of components 0 and 1 of a set: 2^m points put one point in every
    // elementary box 2^-kx x 2^-(m-kx).
    bool strat2d = true;
    for (uint32_t render_seed : {7u, 0xDEADBEEFu}) {
        const uint32_t ps = pt::PixelSeed(12345u, render_seed);
        for (uint32_t set = 0; set < 4; ++set) {
            for (uint32_t mbits = 1; mbits <= 10; ++mbits) {
                const uint32_t n = 1u << mbits;
                for (uint32_t kx = 0; kx <= mbits; ++kx) {
                    std::vector<uint8_t> seen(n, 0);
                    for (uint32_t i = 0; i < n; ++i) {
                        const uint32_t a = pt::SampleBits(ps, i, set * 4 + 0);
                        const uint32_t b = pt::SampleBits(ps, i, set * 4 + 1);
                        const uint32_t cx = kx == 0 ? 0 : a >> (32 - kx);
                        const uint32_t ky = mbits - kx;
                        const uint32_t cy = ky == 0 ? 0 : b >> (32 - ky);
                        if (seen[(cx << ky) | cy]++ != 0) strat2d = false;
                    }
                }
            }
        }
    }
    Check(strat2d,
          "components 0 and 1 of sets 0-3 form a (0,2)-sequence: one point per elementary box "
          "for 2^1 to 2^10 points",
          "an elementary box holds two points");

    // Seeds: the same seed reproduces the sequence; another render seed, pixel or set changes
    // it. Counted over 256 indices x 8 dimensions; every one of the 2048 values must differ
    // except by a chance collision of 32-bit values (bound: at most 2).
    const uint32_t ps = pt::PixelSeed(42u, 1234u);
    const uint32_t ps_again = pt::PixelSeed(42u, 1234u);
    const uint32_t ps_seed = pt::PixelSeed(42u, 1235u);
    const uint32_t ps_pixel = pt::PixelSeed(43u, 1234u);
    uint32_t same = 0;
    uint32_t equal_seed = 0;
    uint32_t equal_pixel = 0;
    uint32_t equal_set = 0;
    for (uint32_t i = 0; i < 256; ++i) {
        for (uint32_t dim = 0; dim < 8; ++dim) {
            const uint32_t v = pt::SampleBits(ps, i, dim);
            same += v == pt::SampleBits(ps_again, i, dim);
            equal_seed += v == pt::SampleBits(ps_seed, i, dim);
            equal_pixel += v == pt::SampleBits(ps_pixel, i, dim);
            equal_set += v == pt::SampleBits(ps, i, dim + 4);
        }
    }
    std::printf("INFO equal values of 2048: other seed %u, other pixel %u, other set %u\n",
                equal_seed, equal_pixel, equal_set);
    Check(same == 2048, "the same seed and pixel reproduce every value");
    Check(equal_seed <= 2, "another render seed changes the sequence",
          std::to_string(equal_seed) + " equal values");
    Check(equal_pixel <= 2, "another pixel changes the sequence",
          std::to_string(equal_pixel) + " equal values");
    Check(equal_set <= 2, "another 4D set changes the sequence",
          std::to_string(equal_set) + " equal values");

    // Floats: the top 24 bits times 2^-24, in [0, 1).
    Check(pt::FixedToFloat(0xFFFFFFFFu) == 16777215.0f / 16777216.0f &&
              pt::FixedToFloat(0x80000000u) == 0.5f && pt::FixedToFloat(0x000000FFu) == 0.0f,
          "FixedToFloat keeps the top 24 bits: below 1, 0.5 exact");
    bool floats = true;
    for (uint32_t i = 0; i < 4096; ++i) {
        const float f = pt::SampleFloat(ps, i, 5);
        if (!(f >= 0.0f && f < 1.0f) || f != pt::FixedToFloat(pt::SampleBits(ps, i, 5))) {
            floats = false;
        }
    }
    Check(floats, "SampleFloat lies in [0, 1) and equals FixedToFloat of SampleBits");
}

// ── sobol-dump ──────────────────────────────────────────────────────────────────────────────

void CaseSobolDump() {
    // The grid tests/render/test_pathtracer_sampler.py recomputes with the prototype.
    const uint32_t seeds[] = {0u, 7u, 0x9E3779B9u};
    const uint32_t pixels[] = {0u, 1u, 2u, 1023u, (1u << 20) + 5u};
    std::vector<uint32_t> indices;
    for (uint32_t i = 0; i < 64; ++i) indices.push_back(i);
    indices.push_back(1000u);
    indices.push_back(65535u);
    std::string json = "{\"seeds\":[";
    for (size_t s = 0; s < std::size(seeds); ++s) json += (s ? "," : "") + std::to_string(seeds[s]);
    json += "],\"pixels\":[";
    for (size_t p = 0; p < std::size(pixels); ++p) {
        json += (p ? "," : "") + std::to_string(pixels[p]);
    }
    json += "],\"indices\":[";
    for (size_t i = 0; i < indices.size(); ++i) json += (i ? "," : "") + std::to_string(indices[i]);
    json += "],\"dimensions\":12,\"pixel_seeds\":[";
    bool first_seed = true;
    for (uint32_t seed : seeds) {
        for (uint32_t pixel : pixels) {
            json += (first_seed ? "" : ",") + std::to_string(pt::PixelSeed(pixel, seed));
            first_seed = false;
        }
    }
    json += "],\"bits\":[";
    bool first = true;
    for (uint32_t seed : seeds) {
        for (uint32_t pixel : pixels) {
            const uint32_t ps = pt::PixelSeed(pixel, seed);
            for (uint32_t index : indices) {
                for (uint32_t dim = 0; dim < 12; ++dim) {
                    json += (first ? "" : ",") + std::to_string(pt::SampleBits(ps, index, dim));
                    first = false;
                }
            }
        }
    }
    json += "]}";
    std::printf("VALUES %s\n", json.c_str());
    Check(true, "sample bits dumped");
}

// ── lambert ─────────────────────────────────────────────────────────────────────────────────

double RelativeError(double value, double expected) {
    return std::fabs(value - expected) / std::max(std::fabs(expected), 1e-300);
}

void CaseLambert() {
    const pt::Rgb albedo{0.8f, 0.5f, 0.2f};
    const pt::LambertBsdf lobe(albedo);
    const pt::Vec3 up_wo{0.3f, -0.2f, 0.9327379f};
    const pt::Vec3 up_wi{-0.6f, 0.0f, 0.8f};
    const pt::Vec3 down_wi{0.0f, 0.6f, -0.8f};

    // f = R / pi in the hemisphere of wo (binary32 rounding: relative 2^-23 bound).
    const pt::Rgb f = lobe.Evaluate(up_wo, up_wi);
    Check(RelativeError(f.r, 0.8 / kPi) < 2.4e-7 && RelativeError(f.g, 0.5 / kPi) < 2.4e-7 &&
              RelativeError(f.b, 0.2 / kPi) < 2.4e-7,
          "Evaluate is albedo / pi in the hemisphere of wo");
    const pt::Rgb zero = lobe.Evaluate(up_wo, down_wi);
    Check(zero.r == 0.0f && zero.g == 0.0f && zero.b == 0.0f &&
              lobe.Pdf(up_wo, down_wi) == 0.0f,
          "Evaluate and Pdf are 0 across the surface");
    Check(RelativeError(lobe.Pdf(up_wo, up_wi), 0.8 / kPi) < 2.4e-7,
          "Pdf is cos(theta_i) / pi");
    const pt::Rgb swapped = lobe.Evaluate(up_wi, up_wo);
    Check(swapped.r == f.r && swapped.g == f.g && swapped.b == f.b,
          "f is reciprocal (Evaluate(wo, wi) = Evaluate(wi, wo))");

    // Concentric disk mapping, hand-computed points: the centre, the two axes at radius 1/2 and
    // the corner (0, 0) to the unit circle at 225 degrees.
    float x;
    float y;
    pt::SampleUniformDiskConcentric(0.5f, 0.5f, &x, &y);
    bool disk = x == 0.0f && y == 0.0f;
    pt::SampleUniformDiskConcentric(0.75f, 0.5f, &x, &y);
    disk = disk && std::fabs(x - 0.5f) < 1e-7f && std::fabs(y) < 1e-7f;
    pt::SampleUniformDiskConcentric(0.5f, 0.75f, &x, &y);
    disk = disk && std::fabs(x) < 1e-7f && std::fabs(y - 0.5f) < 1e-7f;
    pt::SampleUniformDiskConcentric(0.0f, 0.0f, &x, &y);
    disk = disk && std::fabs(x + 0.70710678f) < 1e-6f && std::fabs(y + 0.70710678f) < 1e-6f;
    Check(disk, "concentric disk mapping of the centre, the half axes and a corner");

    // Samples for wo above and below the surface: unit wi in the hemisphere of wo, pdf and f as
    // Pdf and Evaluate give them, and f cos / pdf = R (binary32: relative 1e-6 bound).
    const uint32_t ps = pt::PixelSeed(9u, 2026u);
    bool samples = true;
    double worst_weight = 0.0;
    std::string detail;
    for (const pt::Vec3 wo : {up_wo, pt::Vec3{0.0f, 0.0f, 1.0f}, pt::Vec3{0.1f, 0.7f, -0.7071068f}}) {
        for (uint32_t i = 0; i < 4096; ++i) {
            pt::BsdfSample s;
            if (!lobe.Sample(wo, pt::SampleFloat(ps, i, 0), pt::SampleFloat(ps, i, 1),
                             pt::SampleFloat(ps, i, 2), &s)) {
                samples = false;
                detail = "no sample at index " + std::to_string(i);
                continue;
            }
            const double length = std::sqrt(double(s.wi.x) * s.wi.x + double(s.wi.y) * s.wi.y +
                                            double(s.wi.z) * s.wi.z);
            const pt::Rgb fe = lobe.Evaluate(wo, s.wi);
            const double cos_i = std::fabs(s.wi.z);
            const double weight = s.f.r * cos_i / s.pdf;
            worst_weight = std::max(worst_weight, RelativeError(weight, albedo.r));
            if (std::fabs(length - 1.0) > 1e-6 || s.wi.z * wo.z <= 0.0f ||
                s.pdf != lobe.Pdf(wo, s.wi) || fe.r != s.f.r || fe.g != s.f.g || fe.b != s.f.b) {
                samples = false;
                detail = "index " + std::to_string(i);
            }
        }
    }
    std::printf("INFO worst relative error of f cos / pdf against R: %.3g\n", worst_weight);
    Check(samples, "Sample returns unit wi in the hemisphere of wo with Pdf and Evaluate", detail);
    Check(worst_weight < 1e-6, "f cos(theta_i) / pdf = albedo for every sample (white furnace)");
    pt::BsdfSample untouched;
    Check(!lobe.Sample(pt::Vec3{1.0f, 0.0f, 0.0f}, 0.5f, 0.3f, 0.6f, &untouched) &&
              untouched.pdf == 0.0f,
          "a grazing wo (z = 0) has no sample");

    // Distribution of 4096 samples for wo = +z: cos^2(theta) and phi are uniform under
    // cosine-weighted sampling. Chi-square over 16 equal bins of each, bound 30.58 (the
    // 0.01 quantile of chi-square with 15 degrees of freedom; deterministic, Sobol points).
    std::vector<double> cos2_bins(16, 0.0);
    std::vector<double> phi_bins(16, 0.0);
    const uint32_t n = 4096;
    for (uint32_t i = 0; i < n; ++i) {
        pt::BsdfSample s;
        lobe.Sample({0.0f, 0.0f, 1.0f}, 0.0f, pt::SampleFloat(ps, i, 4), pt::SampleFloat(ps, i, 5),
                    &s);
        const double c2 = double(s.wi.z) * s.wi.z;
        double phi = std::atan2(double(s.wi.y), double(s.wi.x));
        if (phi < 0.0) phi += 2.0 * kPi;
        cos2_bins[std::min<size_t>(15, size_t(c2 * 16.0))] += 1.0;
        phi_bins[std::min<size_t>(15, size_t(phi / (2.0 * kPi) * 16.0))] += 1.0;
    }
    auto chi2 = [](const std::vector<double>& bins) {
        const double expected = double(n) / double(bins.size());
        double sum = 0.0;
        for (double b : bins) sum += (b - expected) * (b - expected) / expected;
        return sum;
    };
    const double chi_cos = chi2(cos2_bins);
    const double chi_phi = chi2(phi_bins);
    std::printf("INFO chi-square (15 dof) of 4096 samples: cos^2 %.4f, phi %.4f\n", chi_cos,
                chi_phi);
    Check(chi_cos < 30.58 && chi_phi < 30.58,
          "sampled directions are cosine-distributed (chi-square below 30.58)");

    // The density integrates to 1 over the hemisphere: midpoint rule on 512 x 1024 cells of
    // (theta, phi), bound 1e-5 (the rule's error on cos sin is below 1e-5 at this size).
    double integral = 0.0;
    const int nt = 512;
    const int np = 1024;
    for (int t = 0; t < nt; ++t) {
        const double theta = (t + 0.5) * (kPi / 2.0) / nt;
        for (int p = 0; p < np; ++p) {
            const double phi = (p + 0.5) * 2.0 * kPi / np;
            const pt::Vec3 wi{float(std::sin(theta) * std::cos(phi)),
                              float(std::sin(theta) * std::sin(phi)), float(std::cos(theta))};
            integral += double(lobe.Pdf({0.0f, 0.0f, 1.0f}, wi)) * std::sin(theta) *
                        ((kPi / 2.0) / nt) * (2.0 * kPi / np);
        }
    }
    std::printf("INFO hemisphere integral of Pdf: %.9f\n", integral);
    Check(std::fabs(integral - 1.0) < 1e-5, "Pdf integrates to 1 over the hemisphere");
}

// ── environment ─────────────────────────────────────────────────────────────────────────────

std::vector<float> GreyMap(uint32_t width, uint32_t height, float value) {
    return std::vector<float>(size_t(width) * height * 3, value);
}

void SetTexel(std::vector<float>& map, uint32_t width, uint32_t row, uint32_t col, float value) {
    float* t = &map[(size_t(row) * width + col) * 3];
    t[0] = t[1] = t[2] = value;
}

double Distance(pt::DirectionD a, pt::DirectionD b) {
    return std::sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y) +
                     (a.z - b.z) * (a.z - b.z));
}

void CaseEnvironment() {
    std::string error;

    // Orientation of parity/semantics/iray.json `environment-mapping`, hand-evaluated:
    // v = 0 is +Y, v = 1 is -Y; at v = 1/2, u = 1/4 is +Z, u = 1/2 is -X, u = 0 is +X; a
    // rotation of 90 degrees moves +Z to u = 1/2.
    const double eps = 1e-12;
    Check(Distance(pt::UvToDirection(0.3, 0.0, 0.0), {0, 1, 0}) < eps &&
              Distance(pt::UvToDirection(0.3, 1.0, 0.0), {0, -1, 0}) < eps &&
              Distance(pt::UvToDirection(0.25, 0.5, 0.0), {0, 0, 1}) < eps &&
              Distance(pt::UvToDirection(0.5, 0.5, 0.0), {-1, 0, 0}) < eps &&
              Distance(pt::UvToDirection(0.0, 0.5, 0.0), {1, 0, 0}) < eps &&
              Distance(pt::UvToDirection(0.5, 0.5, 90.0), {0, 0, 1}) < eps,
          "texel coordinates map to the directions of the iray.json environment mapping");
    bool round_trip = true;
    const uint32_t ps = pt::PixelSeed(3u, 77u);
    for (uint32_t i = 0; i < 1024; ++i) {
        const double u = pt::SampleBits(ps, i, 0) * 0x1p-32;
        const double v = 0.01 + 0.98 * (pt::SampleBits(ps, i, 1) * 0x1p-32);
        double bu;
        double bv;
        pt::DirectionToUv(pt::UvToDirection(u, v, 37.0), 37.0, &bu, &bv);
        const double du = std::fabs(bu - u);
        if (std::min(du, 1.0 - du) > 1e-12 || std::fabs(bv - v) > 1e-12) round_trip = false;
    }
    Check(round_trip, "DirectionToUv inverts UvToDirection under a rotation (1e-12)");

    // Invalid maps fail before any table exists.
    auto zero = GreyMap(8, 4, 0.0f);
    auto nan_map = GreyMap(8, 4, 1.0f);
    nan_map[5] = std::nanf("");
    Check(!pt::EnvironmentDistribution::Build(8, 4, zero.data(), 0.0, &error) &&
              !pt::EnvironmentDistribution::Build(8, 4, nan_map.data(), 0.0, &error) &&
              !pt::EnvironmentDistribution::Build(0, 4, zero.data(), 0.0, &error),
          "an empty, black or non-finite map is refused", error);

    // 2 x 2 grey map with radiances 1, 3 (row 0) and 2, 6 (row 1): both rows have
    // sin(theta) = sin(pi/4), so texel probabilities are L / 12.
    std::vector<float> small = GreyMap(2, 2, 0.0f);
    SetTexel(small, 2, 0, 0, 1.0f);
    SetTexel(small, 2, 0, 1, 3.0f);
    SetTexel(small, 2, 1, 0, 2.0f);
    SetTexel(small, 2, 1, 1, 6.0f);
    auto dist_small = pt::EnvironmentDistribution::Build(2, 2, small.data(), 0.0, &error);
    const double expected_small[2][2] = {{1.0 / 12, 3.0 / 12}, {2.0 / 12, 6.0 / 12}};
    bool small_ok = dist_small.has_value();
    for (uint32_t r = 0; small_ok && r < 2; ++r) {
        for (uint32_t c = 0; c < 2; ++c) {
            small_ok = small_ok &&
                       RelativeError(dist_small->TexelProbability(r, c), expected_small[r][c]) <
                           1e-12;
        }
    }
    Check(small_ok, "texel probabilities of a 2 x 2 map are L / 12");

    // A single lit texel (row 5, column 11 of 16 x 8): every sample lands in it, with
    // pdf_uv = W H = 128 and pdf = 128 / (2 pi^2 sin(pi v)); every other texel has density 0.
    std::vector<float> one = GreyMap(16, 8, 0.0f);
    SetTexel(one, 16, 5, 11, 4.0f);
    auto dist_one = pt::EnvironmentDistribution::Build(16, 8, one.data(), 0.0, &error);
    bool one_ok = dist_one.has_value();
    for (uint32_t i = 0; one_ok && i < 4096; ++i) {
        const auto s = dist_one->Sample(pt::SampleBits(ps, i, 4) * 0x1p-32,
                                        pt::SampleBits(ps, i, 5) * 0x1p-32);
        const double pdf = 128.0 / (2.0 * kPi * kPi * std::sin(kPi * s.v));
        one_ok = s.row == 5 && s.column == 11 && s.u >= 11.0 / 16 && s.u < 12.0 / 16 &&
                 s.v >= 5.0 / 8 && s.v < 6.0 / 8 && s.pdf_uv == 128.0 &&
                 RelativeError(s.pdf_solid_angle, pdf) < 1e-14;
    }
    Check(one_ok && dist_one->PdfUv(0.1, 0.1) == 0.0 && dist_one->PdfUv(11.5 / 16, 5.5 / 8) == 128.0,
          "a single lit texel takes every sample with pdf_uv = W H", error);

    // A structured map (32 x 16, luminance 1 + (3 r + 7 c) mod 5, one bright patch 200):
    std::vector<float> map = GreyMap(32, 16, 0.0f);
    for (uint32_t r = 0; r < 16; ++r) {
        for (uint32_t c = 0; c < 32; ++c) SetTexel(map, 32, r, c, 1.0f + float((3 * r + 7 * c) % 5));
    }
    for (uint32_t r = 3; r < 5; ++r) {
        for (uint32_t c = 20; c < 24; ++c) SetTexel(map, 32, r, c, 200.0f);
    }
    auto dist = pt::EnvironmentDistribution::Build(32, 16, map.data(), 25.0, &error);
    if (!dist) {
        Check(false, "structured map builds", error);
        return;
    }

    // Pdf(direction) reproduces the density Sample returns. The round trip through the
    // direction keeps the texel (pdf_uv equal) unless the sample lies within 1e-9 texel of a
    // texel edge, and the solid-angle density agrees to 1e-9 + 4e-16 / sin^2(theta) relative:
    // acos(y) loses about 1e-16 / sin(theta) of theta near the poles, and the density divides
    // by sin(theta).
    uint32_t texel_changes = 0;
    uint32_t density_mismatches = 0;
    const uint32_t n = 1u << 16;
    std::vector<uint32_t> texel_counts(32 * 16, 0);
    std::vector<uint32_t> row_counts(16, 0);
    for (uint32_t i = 0; i < n; ++i) {
        const auto s = dist->Sample(pt::SampleBits(ps, i, 8) * 0x1p-32,
                                    pt::SampleBits(ps, i, 9) * 0x1p-32);
        ++texel_counts[s.row * 32 + s.column];
        ++row_counts[s.row];
        double bu;
        double bv;
        pt::DirectionToUv(s.direction, 25.0, &bu, &bv);
        const double fu = s.u * 32.0;
        const double fv = s.v * 16.0;
        const double edge =
            std::min(std::fabs(fu - std::round(fu)), std::fabs(fv - std::round(fv)));
        if (dist->PdfUv(bu, bv) != s.pdf_uv && edge > 1e-9) ++texel_changes;
        const double sin_theta = std::sin(kPi * s.v);
        if (s.pdf_solid_angle > 0.0 && edge > 1e-9 &&
            RelativeError(dist->Pdf(s.direction), s.pdf_solid_angle) >
                1e-9 + 4e-16 / (sin_theta * sin_theta)) {
            ++density_mismatches;
        }
    }
    std::printf("INFO 65536 samples: %u texel changes and %u density mismatches away from a "
                "texel edge\n",
                texel_changes, density_mismatches);
    Check(texel_changes == 0 && density_mismatches == 0,
          "Pdf(direction) equals the density of the sample that produced it");

    // The rows come from one stratified dimension by CDF inversion, so each row's count is
    // within 2 of N times its probability (an interval meets at most two partial strata).
    double worst_row = 0.0;
    for (uint32_t r = 0; r < 16; ++r) {
        double p = 0.0;
        for (uint32_t c = 0; c < 32; ++c) p += dist->TexelProbability(r, c);
        worst_row = std::max(worst_row, std::fabs(row_counts[r] - n * p));
    }
    // Texels: within 3 binomial standard deviations plus 1 (the bound an independent sampler
    // meets with probability 0.997 per texel; the Sobol points are deterministic).
    double worst_texel = 0.0;
    bool texels_ok = true;
    for (uint32_t r = 0; r < 16; ++r) {
        for (uint32_t c = 0; c < 32; ++c) {
            const double p = dist->TexelProbability(r, c);
            const double deviation = std::fabs(texel_counts[r * 32 + c] - n * p);
            const double bound = 3.0 * std::sqrt(n * p * (1.0 - p)) + 1.0;
            worst_texel = std::max(worst_texel, deviation / bound);
            if (deviation > bound) texels_ok = false;
        }
    }
    std::printf("INFO 65536 samples: worst row |count - N p| %.3f, worst texel deviation / bound %.3f\n",
                worst_row, worst_texel);
    Check(worst_row <= 2.0, "row counts are within 2 of N p");
    Check(texels_ok, "texel counts are within 3 sigma + 1 of N p");

    // The solid-angle density integrates to 1 over the sphere: midpoint rule on a grid of
    // 8 x 8 cells per texel aligned to the texel edges (in the rotated frame), so the
    // integrand pdf sin(theta) is constant on each cell up to rounding (bound 1e-9).
    double integral = 0.0;
    const int nv = 16 * 8;
    const int nu = 32 * 8;
    for (int a = 0; a < nv; ++a) {
        const double v = (a + 0.5) / nv;
        for (int b = 0; b < nu; ++b) {
            const double u = (b + 0.5) / nu;
            const pt::DirectionD d = pt::UvToDirection(u, v, 25.0);
            // d(omega) = 2 pi^2 sin(theta) du dv.
            integral += dist->Pdf(d) * 2.0 * kPi * kPi * std::sin(kPi * v) / (double(nu) * nv);
        }
    }
    std::printf("INFO sphere integral of Pdf: %.12f\n", integral);
    Check(std::fabs(integral - 1.0) < 1e-9, "Pdf integrates to 1 over the sphere");
}

// ── env-mis ─────────────────────────────────────────────────────────────────────────────────

struct Estimate {
    double mean = 0.0;
    double standard_error = 0.0;
};

struct Accumulator {
    double sum = 0.0;
    double sum_sq = 0.0;
    uint32_t n = 0;
    void Add(double x) {
        sum += x;
        sum_sq += x * x;
        ++n;
    }
    Estimate Result() const {
        const double mean = sum / n;
        const double variance = std::max(0.0, (sum_sq / n - mean * mean) * n / (n - 1.0));
        return {mean, std::sqrt(variance / n)};
    }
};

void CaseEnvMis() {
    // Fixture: a 64 x 32 grey environment of radiance 0.05 with one bright patch of radiance 50
    // (rows 6-9, columns 40-47, all above the horizon), a Lambert surface of albedo 0.8 with its
    // normal along +Y, looked at along the normal. Radiance is the value of the texel holding
    // the direction (piecewise constant, as the distribution).
    //
    // Analytic reflected radiance: Lo = (R / pi) E, E = sum over texels above the horizon of
    // L (2 pi / W) (sin^2 theta_1 - sin^2 theta_0) / 2, theta_k the texel's row edges (rows
    // 0-15 lie above the horizon: theta_1 <= pi / 2 at row 15).
    const uint32_t width = 64;
    const uint32_t height = 32;
    std::vector<float> map = GreyMap(width, height, 0.05f);
    for (uint32_t r = 6; r < 10; ++r) {
        for (uint32_t c = 40; c < 48; ++c) SetTexel(map, width, r, c, 50.0f);
    }
    std::string error;
    auto dist = pt::EnvironmentDistribution::Build(width, height, map.data(), 0.0, &error);
    if (!dist) {
        Check(false, "fixture map builds", error);
        return;
    }
    double irradiance = 0.0;
    for (uint32_t r = 0; r < height / 2; ++r) {
        const double t0 = kPi * r / height;
        const double t1 = kPi * (r + 1) / height;
        const double band = (std::sin(t1) * std::sin(t1) - std::sin(t0) * std::sin(t0)) / 2.0;
        for (uint32_t c = 0; c < width; ++c) {
            irradiance += double(map[(size_t(r) * width + c) * 3]) * (2.0 * kPi / width) * band;
        }
    }
    const float albedo = 0.8f;
    const double analytic = albedo / kPi * irradiance;
    auto radiance = [&](pt::DirectionD d) {
        double u;
        double v;
        pt::DirectionToUv(d, 0.0, &u, &v);
        const uint32_t row = std::min<uint32_t>(height - 1, uint32_t(v * height));
        const uint32_t col = std::min<uint32_t>(width - 1, uint32_t(u * width));
        return double(map[(size_t(row) * width + col) * 3]);
    };

    // The shading frame: local z is world +Y, local (x, y) world (x, z).
    const pt::LambertBsdf lobe({albedo, albedo, albedo});
    const pt::Vec3 wo{0.0f, 0.0f, 1.0f};
    Accumulator env_only;
    Accumulator bsdf_only;
    Accumulator mis;
    const uint32_t ps = pt::PixelSeed(0u, 20261021u);
    const uint32_t n = 1u << 16;
    for (uint32_t i = 0; i < n; ++i) {
        // Environment sample (set 0) and BSDF sample (set 1).
        const auto e = dist->Sample(pt::SampleBits(ps, i, 0) * 0x1p-32,
                                    pt::SampleBits(ps, i, 1) * 0x1p-32);
        double env_term = 0.0;
        double env_mis = 0.0;
        if (e.pdf_solid_angle > 0.0 && e.direction.y > 0.0) {
            const pt::Vec3 wi{float(e.direction.x), float(e.direction.z), float(e.direction.y)};
            const double f = lobe.Evaluate(wo, wi).r;
            const double p_b = lobe.Pdf(wo, wi);
            const double contribution = f * radiance(e.direction) * e.direction.y;
            env_term = contribution / e.pdf_solid_angle;
            const double p_e = e.pdf_solid_angle;
            env_mis = env_term * p_e * p_e / (p_e * p_e + p_b * p_b);
        }
        double bsdf_term = 0.0;
        double bsdf_mis = 0.0;
        pt::BsdfSample s;
        if (lobe.Sample(wo, pt::SampleFloat(ps, i, 4), pt::SampleFloat(ps, i, 5),
                        pt::SampleFloat(ps, i, 6), &s)) {
            const pt::DirectionD d{s.wi.x, s.wi.z, s.wi.y};
            const double length = std::sqrt(d.x * d.x + d.y * d.y + d.z * d.z);
            const pt::DirectionD unit{d.x / length, d.y / length, d.z / length};
            bsdf_term = s.f.r * radiance(unit) * std::fabs(s.wi.z) / s.pdf;
            const double p_b = s.pdf;
            const double p_e = dist->Pdf(unit);
            bsdf_mis = bsdf_term * p_b * p_b / (p_e * p_e + p_b * p_b);
        }
        env_only.Add(env_term);
        bsdf_only.Add(bsdf_term);
        mis.Add(env_mis + bsdf_mis);
    }
    // Unbiasedness: each estimator's mean lies within 4 standard errors of the analytic value
    // (deterministic for these Sobol points; the measured ratios are printed).
    const auto report = [&](const char* name, const Accumulator& acc) {
        const Estimate est = acc.Result();
        const double z = (est.mean - analytic) / est.standard_error;
        std::printf("INFO %s: mean %.9f analytic %.9f standard error %.3g (z %.3f)\n", name,
                    est.mean, analytic, est.standard_error, z);
        Check(std::fabs(z) <= 4.0,
              std::string(name) + " estimate of Lo is within 4 standard errors of the analytic "
                                  "value");
    };
    report("environment sampling", env_only);
    report("Lambert sampling", bsdf_only);
    report("power-heuristic MIS", mis);
    Check(mis.Result().standard_error < bsdf_only.Result().standard_error,
          "MIS has a lower standard error than Lambert sampling alone on the bright patch");
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: uzp-pathtracer-tests <case>\n");
        return 2;
    }
    const std::string name = argv[1];
    if (name == "sobol") {
        CaseSobol();
    } else if (name == "sobol-dump") {
        CaseSobolDump();
    } else if (name == "lambert") {
        CaseLambert();
    } else if (name == "environment") {
        CaseEnvironment();
    } else if (name == "env-mis") {
        CaseEnvMis();
    } else {
        std::fprintf(stderr, "unknown case %s\n", name.c_str());
        return 2;
    }
    return g_failures == 0 ? 0 : 1;
}
