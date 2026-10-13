#include "export/padding.h"

#include "export/encode.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>

namespace uzp::exporter {

namespace {

[[noreturn]] void Unfitted(const PlannedFile& file, const std::string& what) {
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + what + " (" + std::string(kProcessingRecording) + ")");
}

// The ring's weights (decisions 176, 206): f = 0.4142245, a diagonal weighs f / (1 - f) against a
// side's 1. On a straight edge one diagonal is weakened by kAsymmetry so that the mean moves
// kEdgeShift texel: side 1, diagonals w and w r, w (1 - r) / (1 + w + w r) = kEdgeShift.
constexpr double kDiagonalFraction = 0.4142245;
constexpr double kDiagonalWeight = kDiagonalFraction / (1.0 - kDiagonalFraction);
constexpr double kEdgeShift = 24.875 * 0x1p-15;
constexpr double kAsymmetry =
    (kDiagonalWeight - kEdgeShift * (1.0 + kDiagonalWeight)) / (kDiagonalWeight * (1.0 + kEdgeShift));

// The 8-neighbours as (dy, dx), in the order their contributions are summed.
constexpr std::array<std::array<int, 2>, 8> kNeighbours{
    {{-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}}};
// The jump flood's offsets per step as (dy, dx), in the order they are tried (decision 197).
constexpr std::array<std::array<int, 2>, 8> kFloodOffsets{
    {{0, 1}, {0, -1}, {-1, 0}, {1, 0}, {-1, 1}, {1, -1}, {-1, -1}, {1, 1}}};

struct Neighbour {
    int dy = 0;
    int dx = 0;
    size_t texel = 0;
};

enum class Edge { none, horizontal, vertical };

// A straight edge: three covered neighbours in one row (or column) other than the texel's own,
// one on each side of it and one in line with it.
Edge StraightEdge(const std::vector<Neighbour>& neighbours) {
    if (neighbours.size() != 3) return Edge::none;
    const auto line = [&](auto key, auto across) {
        std::array<bool, 3> seen{};
        for (const Neighbour& n : neighbours) {
            if (key(n) != key(neighbours[0])) return false;
            seen[static_cast<size_t>(across(n) + 1)] = true;
        }
        return key(neighbours[0]) != 0 && seen[0] && seen[1] && seen[2];
    };
    const auto row = [](const Neighbour& n) { return n.dy; };
    const auto column = [](const Neighbour& n) { return n.dx; };
    if (line(row, column)) return Edge::horizontal;
    if (line(column, row)) return Edge::vertical;
    return Edge::none;
}

// The ring value of one texel into `out` (`channels` floats), from its covered neighbours.
void RingValue(const std::vector<float>& values, uint32_t channels, const std::vector<Neighbour>& neighbours,
               float* out) {
    const auto at = [&](size_t texel) { return values.data() + texel * channels; };
    const float* first = at(neighbours[0].texel);
    if (std::all_of(neighbours.begin(), neighbours.end(),
                    [&](const Neighbour& n) { return std::equal(first, first + channels, at(n.texel)); })) {
        std::copy(first, first + channels, out);
        return;
    }
    const Edge edge = StraightEdge(neighbours);
    std::array<double, 4> sum{};
    double weights = 0.0;
    for (const Neighbour& n : neighbours) {
        double w = (n.dy == 0 || n.dx == 0) ? 1.0 : kDiagonalWeight;
        if (edge == Edge::horizontal && n.dx == -1) w *= kAsymmetry;  // the mean moves toward +x
        if (edge == Edge::vertical && n.dy == 1) w *= kAsymmetry;     // the mean moves toward -row
        for (uint32_t c = 0; c < channels; ++c) sum[c] = sum[c] + w * static_cast<double>(at(n.texel)[c]);
        weights += w;
    }
    for (uint32_t c = 0; c < channels; ++c) {
        const float mean = static_cast<float>(sum[c] / weights);
        const float complement = 1.0f - mean;
        out[c] = 1.0f - complement;
    }
}

// `infinite` padding over incomplete coverage (padding.h): the ring, then the jump flood.
void InfinitePadding(const Coverage& coverage, uint32_t channels, std::vector<float>& values) {
    const int width = static_cast<int>(coverage.width);
    const int height = static_cast<int>(coverage.height);
    if (channels == 0 || channels > 4 || values.size() != size_t{coverage.width} * coverage.height * channels) {
        throw std::invalid_argument("export: infinite padding takes 1 to 4 values per texel");
    }
    const std::vector<uint8_t>& covered = coverage.covered;
    const auto index = [&](int y, int x) { return static_cast<size_t>(y) * coverage.width + static_cast<size_t>(x); };
    const auto copy = [&](size_t from, size_t to) {
        std::copy_n(values.begin() + static_cast<std::ptrdiff_t>(from * channels), channels,
                    values.begin() + static_cast<std::ptrdiff_t>(to * channels));
    };
    // 1. The ring, from the covered texels only.
    std::vector<uint8_t> seed(covered);
    std::vector<float> ring;
    std::vector<size_t> ringTexels;
    std::vector<Neighbour> neighbours;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (covered[index(y, x)] != 0) continue;
            neighbours.clear();
            for (const auto& [dy, dx] : kNeighbours) {
                const int yy = y + dy;
                const int xx = ((x + dx) % width + width) % width;
                if (yy >= 0 && yy < height && covered[index(yy, xx)] != 0) neighbours.push_back({dy, dx, index(yy, xx)});
            }
            if (neighbours.empty()) continue;
            ring.resize(ring.size() + channels);
            RingValue(values, channels, neighbours, ring.data() + ring.size() - channels);
            ringTexels.push_back(index(y, x));
        }
    }
    for (size_t i = 0; i < ringTexels.size(); ++i) {
        std::copy_n(ring.begin() + static_cast<std::ptrdiff_t>(i * channels), channels,
                    values.begin() + static_cast<std::ptrdiff_t>(ringTexels[i] * channels));
        seed[ringTexels[i]] = 1;
    }
    // 2. The jump flood over the covered and ring texels; each step reads the previous step's seeds.
    const size_t texels = size_t{coverage.width} * coverage.height;
    std::vector<int32_t> seedY(texels, -1);
    std::vector<int32_t> seedX(texels, -1);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (seed[index(y, x)] != 0) {
                seedY[index(y, x)] = y;
                seedX[index(y, x)] = x;
            }
        }
    }
    const auto distance = [](int32_t sy, int32_t sx, int y, int x) {
        if (sy < 0) return std::numeric_limits<int64_t>::max();
        const int64_t dy = sy - y;
        const int64_t dx = sx - x;
        return dy * dy + dx * dx;
    };
    std::vector<int32_t> nextY(texels);
    std::vector<int32_t> nextX(texels);
    for (int k = std::max(width, height) / 2; k >= 1; k /= 2) {
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const size_t t = index(y, x);
                int32_t bestY = seedY[t];
                int32_t bestX = seedX[t];
                int64_t best = distance(bestY, bestX, y, x);
                for (const auto& [dy, dx] : kFloodOffsets) {
                    const int yy = y + dy * k;
                    const int xx = x + dx * k;
                    if (yy < 0 || yy >= height || xx < 0 || xx >= width) continue;
                    const size_t from = index(yy, xx);
                    const int64_t d = distance(seedY[from], seedX[from], y, x);
                    if (d < best) {
                        best = d;
                        bestY = seedY[from];
                        bestX = seedX[from];
                    }
                }
                nextY[t] = bestY;
                nextX[t] = bestX;
            }
        }
        seedY.swap(nextY);
        seedX.swap(nextX);
    }
    for (size_t t = 0; t < texels; ++t) {
        if (seed[t] == 0 && seedY[t] >= 0) copy(index(seedY[t], seedX[t]), t);
    }
}

}  // namespace

bool Coverage::Complete() const {
    return std::all_of(covered.begin(), covered.end(), [](uint8_t c) { return c != 0; });
}

void CheckPadding(const PlannedFile& file, const Coverage& coverage) {
    if (file.layout == FileLayout::Statistics) return;
    if (coverage.width != file.width || coverage.height != file.height ||
        coverage.covered.size() != size_t{coverage.width} * coverage.height) {
        throw std::invalid_argument("export: the coverage of " + file.relativePath + " does not have its size");
    }
    if (coverage.Complete()) return;
    const Padding padding = file.parameters->paddingAlgorithm;
    if (padding == Padding::infinite) return;  // written under EXC-007 (decision 223)
    if (padding != Padding::passthrough) {
        Unfitted(file, "the padding \"" + std::string(PaddingName(padding)) +
                           "\" on a texture set whose UV islands do not cover the whole tile is not fitted");
    }
    if (file.layout == FileLayout::LA || file.layout == FileLayout::RGBA) {
        Unfitted(file, "an alpha layout (L+A, RGB+A) on a texture set whose UV islands do not cover the whole tile "
                       "is recorded under infinite and transparent padding only, and not fitted");
    }
    for (const PlannedChannel& channel : file.channels) {
        const SourceType type = channel.source.type;
        if (type == SourceType::meshMap || type == SourceType::virtualMap) {
            Unfitted(file, "the padding \"passthrough\" of a " + std::string(SourceTypeName(type)) +
                               " source outside the UV islands is not recorded");
        }
    }
}

bool ApplyPadding(const PlannedFile& file, const Coverage& coverage, uint32_t channels, std::vector<float>& stored) {
    CheckPadding(file, coverage);
    // Every other admitted case keeps the values: complete coverage, or `passthrough`.
    if (file.layout == FileLayout::Statistics || file.parameters->paddingAlgorithm != Padding::infinite ||
        coverage.Complete() || std::none_of(coverage.covered.begin(), coverage.covered.end(), [](uint8_t c) {
            return c != 0;
        })) {
        return false;
    }
    InfinitePadding(coverage, channels, stored);
    return true;
}

}  // namespace uzp::exporter
