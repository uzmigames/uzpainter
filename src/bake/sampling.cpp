#include "bake/sampling.h"

#include <cmath>
#include <numbers>

namespace uzp::bake {

std::uint64_t SplitMix64(std::uint64_t value) {
    value += 0x9E3779B97F4A7C15ull;
    value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9ull;
    value = (value ^ (value >> 27)) * 0x94D049BB133111EBull;
    return value ^ (value >> 31);
}

double RadicalInverse2(std::uint32_t index) {
    index = (index << 16) | (index >> 16);
    index = ((index & 0x00FF00FFu) << 8) | ((index & 0xFF00FF00u) >> 8);
    index = ((index & 0x0F0F0F0Fu) << 4) | ((index & 0xF0F0F0F0u) >> 4);
    index = ((index & 0x33333333u) << 2) | ((index & 0xCCCCCCCCu) >> 2);
    index = ((index & 0x55555555u) << 1) | ((index & 0xAAAAAAAAu) >> 1);
    return static_cast<double>(index) * 0x1p-32;
}

namespace {

/// x + offset wrapped into [0, 1), for x and offset in [0, 1).
double Rotate(double x, double offset) {
    const double sum = x + offset;
    return sum >= 1.0 ? sum - 1.0 : sum;
}

}  // namespace

Sample2 TexelSample(std::uint64_t texel_index, std::uint32_t sample_id, std::uint32_t sample_count) {
    const std::uint64_t hash = SplitMix64(texel_index);
    const double offset1 = static_cast<double>(hash >> 32) * 0x1p-32;
    const double offset2 = static_cast<double>(hash & 0xFFFFFFFFull) * 0x1p-32;
    const double h1 = static_cast<double>(sample_id) / static_cast<double>(sample_count);
    const double h2 = RadicalInverse2(sample_id);
    return {Rotate(h1, offset1), Rotate(h2, offset2)};
}

Vec3d HemisphereDirection(Distribution distribution, Sample2 sample, Vec3d n) {
    double radius = 0.0;
    double up = 0.0;
    if (distribution == Distribution::Cosine) {
        radius = std::sqrt(sample.u1);
        up = std::sqrt(1.0 - sample.u1);
    } else {
        up = sample.u1;
        radius = std::sqrt(1.0 - sample.u1 * sample.u1);
    }
    const double phi = 2.0 * std::numbers::pi * sample.u2;
    const double lx = radius * std::cos(phi);
    const double ly = radius * std::sin(phi);
    // Duff et al. 2017, listing 3.
    const double sign = std::copysign(1.0, n.z);
    const double a = -1.0 / (sign + n.z);
    const double b = n.x * n.y * a;
    const Vec3d t{1.0 + sign * n.x * n.x * a, sign * b, -sign * n.x};
    const Vec3d bt{b, sign + n.y * n.y * a, -n.y};
    return {lx * t.x + ly * bt.x + up * n.x, lx * t.y + ly * bt.y + up * n.y,
            lx * t.z + ly * bt.z + up * n.z};
}

}  // namespace uzp::bake
