#include "procedural/seam.h"

#include "uzp_core/manifest/sha256.h"

#include <algorithm>
#include <charconv>
#include <cmath>

namespace uzp::procedural {

namespace {

/// The shortest text that reads back as `value` ("1" for 1.0, "0.1" for 0.1).
std::string Number(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value > 0 ? "inf" : "-inf";
    char buf[32];
    const auto [end, ec] = std::to_chars(buf, buf + sizeof(buf), value);
    return ec == std::errc{} ? std::string(buf, end) : std::string("?");
}

std::string Quote(std::string_view text) {
    std::string out = "\"";
    for (const char c : text) {
        if (c == '"' || c == '\\') out += '\\';
        out += c;
    }
    return out + "\"";
}

std::optional<double> AsNumber(const ParamValue& value) {
    if (const auto* i = std::get_if<int64_t>(&value)) return static_cast<double>(*i);
    if (const auto* d = std::get_if<double>(&value)) return *d;
    return std::nullopt;
}

std::string Text(const ParamValue& value) {
    if (const auto* s = std::get_if<std::string>(&value)) return Quote(*s);
    return Number(*AsNumber(value));
}

/// Numbers equal by value (1 == 1.0), strings by their characters; a number never equals a
/// string.
bool SameValue(const ParamValue& a, const ParamValue& b) {
    const std::optional<double> x = AsNumber(a);
    const std::optional<double> y = AsNumber(b);
    if (x && y) return *x == *y;
    if (x || y) return false;
    return std::get<std::string>(a) == std::get<std::string>(b);
}

template <class T, class F>
std::string List(const std::vector<T>& values, F text) {
    std::string out = "[";
    for (size_t i = 0; i < values.size(); ++i) out += (i ? ", " : "") + text(values[i]);
    return out + "]";
}

std::string U64(uint64_t value) { return std::to_string(value); }

/// The exact sign of the sum of `values` (Shewchuk's grow-expansion with zero elimination:
/// the sum is kept as non-overlapping components, so no rounding decides the sign).
int ExactSign(const std::vector<double>& values) {
    std::vector<double> expansion;
    for (const double b : values) {
        std::vector<double> next;
        double q = b;
        for (const double e : expansion) {
            const double s = q + e;
            const double bv = s - q;
            const double av = s - bv;
            const double low = (q - av) + (e - bv);
            q = s;
            if (low != 0.0) next.push_back(low);
        }
        next.push_back(q);
        expansion = std::move(next);
    }
    for (auto it = expansion.rbegin(); it != expansion.rend(); ++it) {
        if (*it != 0.0) return *it > 0.0 ? 1 : -1;
    }
    return 0;
}

/// Whether sum(coefficient x value) <= max exactly: each product split into its rounded value
/// and its exact error (a fused multiply-add), then the sign of the whole sum.
bool Satisfies(const LinearConstraint& constraint, const Params& params) {
    std::vector<double> terms;
    for (const auto& [name, coefficient] : constraint.coefficients) {
        const auto it = params.find(name);
        const std::optional<double> number =
            it == params.end() ? std::nullopt : AsNumber(it->second);
        if (!number) return false;
        const double value = *number;
        const double product = coefficient * value;
        terms.push_back(product);
        terms.push_back(std::fma(coefficient, value, -product));
    }
    terms.push_back(-constraint.max);
    return ExactSign(terms) <= 0;
}

std::string Describe(const LinearConstraint& constraint) {
    std::string out;
    for (const auto& [name, coefficient] : constraint.coefficients) {
        out += (out.empty() ? "" : " + ") + Number(coefficient) + " " + name;
    }
    return out + " <= " + Number(constraint.max);
}

UnsupportedProcedural Outside(const ProceduralRequest& request, std::string field,
                              std::string value, std::string certified) {
    return UnsupportedProcedural{AssetName(request), std::string(kOutsideDomain), std::move(field),
                                 std::move(value), std::move(certified)};
}

template <class T>
bool Contains(const std::vector<T>& values, const T& value) {
    return std::find(values.begin(), values.end(), value) != values.end();
}

std::optional<UnsupportedProcedural> CheckRaster(const ProceduralRequest& request,
                                                 const std::string& where, const RasterSpec& spec,
                                                 const RasterRule& rule) {
    if (!Contains(rule.resolutions, spec.resolution)) {
        return Outside(request, where + ".resolution", U64(spec.resolution),
                       List(rule.resolutions, [](uint32_t r) { return U64(r); }));
    }
    if (!Contains(rule.formats, spec.format)) {
        return Outside(request, where + ".format", Quote(FormatName(spec.format)),
                       List(rule.formats, [](ChannelFormat f) { return Quote(FormatName(f)); }));
    }
    if (!Contains(rule.colourSpaces, spec.colourSpace)) {
        return Outside(request, where + ".colour_space", Quote(spec.colourSpace),
                       List(rule.colourSpaces, [](const std::string& s) { return Quote(s); }));
    }
    if (!Contains(rule.channels, spec.channels)) {
        return Outside(request, where + ".channels", U64(spec.channels),
                       List(rule.channels, [](uint32_t c) { return U64(c); }));
    }
    return std::nullopt;
}

}  // namespace

std::string_view FormatName(ChannelFormat format) {
    switch (format) {
        case ChannelFormat::U8: return "u8";
        case ChannelFormat::U16: return "u16";
        case ChannelFormat::F16: return "f16";
        case ChannelFormat::F32: return "f32";
    }
    return "?";
}

std::string AssetName(const ProceduralRequest& request) {
    return core::FormatAssetUrl(request.asset);
}

std::string Signature(const ProceduralRequest& request) {
    const auto spec = [](const RasterSpec& s) {
        return "{\"channels\":" + U64(s.channels) + ",\"colour_space\":" + Quote(s.colourSpace) +
               ",\"format\":" + Quote(FormatName(s.format)) + ",\"resolution\":" +
               U64(s.resolution) + "}";
    };
    std::string out = "{\"asset\":" + Quote(AssetName(request)) + ",\"inputs\":{";
    bool first = true;
    for (const auto& [name, input] : request.inputs) {
        out += (first ? "" : ",") + Quote(name) + ":{\"sha256\":" + Quote(input.sha256) +
               ",\"spec\":" + spec(input.spec) + "}";
        first = false;
    }
    out += "},\"mesh\":[" + Quote(request.meshClass) + "," + U64(request.uvTiles) +
           "],\"output\":" + spec(request.output) + ",\"params\":{";
    first = true;
    for (const auto& [name, value] : request.params) {
        out += (first ? "" : ",") + Quote(name) + ":" + Text(value);
        first = false;
    }
    out += "},\"preset\":" + (request.preset ? Quote(*request.preset) : std::string("null")) +
           ",\"seed\":" + U64(request.seed) + "}";
    return out;
}

std::string SignatureHash(const ProceduralRequest& request) {
    return core::Sha256Hex(Signature(request));
}

ParityStatus ParityStatus::Unavailable(std::string reason) {
    ParityStatus status;
    status.kind = Kind::Unavailable;
    status.reason = std::move(reason);
    return status;
}

std::string_view KindName(ParityStatus::Kind kind) {
    switch (kind) {
        case ParityStatus::Kind::Exact: return "exact";
        case ParityStatus::Kind::Calibrated: return "calibrated";
        case ParityStatus::Kind::Unavailable: return "unavailable";
    }
    return "?";
}

UnsupportedProcedural Refuse(std::string asset, std::string_view reason) {
    return UnsupportedProcedural{std::move(asset), std::string(reason), {}, {}, {}};
}

std::string UnsupportedProcedural::Describe() const {
    std::string out = "UnsupportedProcedural{asset: " + asset + ", reason: " + reason;
    if (!field.empty()) {
        out += ", field: " + field + ", value: " + value + ", certified range: " + certified;
    }
    return out + "}";
}

std::optional<UnsupportedProcedural> CheckDomain(const ProceduralRequest& request,
                                                 const CertifiedDomain& domain) {
    // Parameters: every declared one present, no other, each inside its rule.
    for (const auto& [name, rule] : domain.parameters) {
        if (!request.params.contains(name)) {
            return Outside(request, "params." + name, "missing", "every declared parameter");
        }
    }
    for (const auto& [name, value] : request.params) {
        if (!domain.parameters.contains(name)) {
            return Outside(request, "params." + name, Text(value), "not a parameter");
        }
    }
    for (const auto& [name, rule] : domain.parameters) {
        if (!rule.range) continue;
        const ParamValue& value = request.params.at(name);
        const std::optional<double> number = AsNumber(value);
        const auto [low, high] = *rule.range;
        if (!number || !(low <= *number && *number <= high)) {
            return Outside(request, "params." + name, Text(value),
                           "[" + Number(low) + ", " + Number(high) + "]");
        }
    }
    for (const auto& [name, rule] : domain.parameters) {
        if (rule.range) continue;
        const ParamValue& value = request.params.at(name);
        const bool listed = std::any_of(rule.set.begin(), rule.set.end(),
                                        [&](const ParamValue& v) { return SameValue(v, value); });
        if (!listed) return Outside(request, "params." + name, Text(value), List(rule.set, Text));
    }
    for (const LinearConstraint& constraint : domain.constraints) {
        if (!Satisfies(constraint, request.params)) {
            std::string values = "{";
            for (const auto& [name, coefficient] : constraint.coefficients) {
                const auto it = request.params.find(name);
                values += (values.size() > 1 ? ", " : "") + name + ": " +
                          (it == request.params.end() ? std::string("missing") : Text(it->second));
            }
            return Outside(request, "params", values + "}", Describe(constraint));
        }
    }
    if (request.preset && !Contains(domain.presets, *request.preset)) {
        return Outside(request, "preset", Quote(*request.preset),
                       List(domain.presets, [](const std::string& s) { return Quote(s); }));
    }

    if (request.seed > 0xFFFFFFFFull) return Outside(request, "seed", U64(request.seed), "[0, 4294967295]");
    if (!domain.anySeed && !Contains(domain.seeds, request.seed)) {
        return Outside(request, "seed", U64(request.seed), List(domain.seeds, U64));
    }
    if (!Contains(domain.meshClasses, request.meshClass)) {
        return Outside(request, "mesh.class", Quote(request.meshClass),
                       List(domain.meshClasses, [](const std::string& s) { return Quote(s); }));
    }
    if (request.uvTiles != domain.uvTiles) {
        return Outside(request, "mesh.uv_tiles", U64(request.uvTiles), U64(domain.uvTiles));
    }

    for (const auto& [usage, rule] : domain.inputs) {
        if (!request.inputs.contains(usage)) {
            return Outside(request, "inputs." + usage, "missing", "a declared input");
        }
    }
    for (const auto& [usage, input] : request.inputs) {
        if (!domain.inputs.contains(usage)) {
            return Outside(request, "inputs." + usage, "present", "not an input of the domain");
        }
    }
    if (auto refusal = CheckRaster(request, "output", request.output, domain.output)) return refusal;
    for (const auto& [usage, input] : request.inputs) {
        if (auto refusal = CheckRaster(request, "inputs." + usage, input.spec, domain.inputs.at(usage))) {
            return refusal;
        }
    }

    const TileRect& tile = request.tile;
    const uint64_t right = uint64_t{tile.x} + tile.width;
    const uint64_t bottom = uint64_t{tile.y} + tile.height;
    const bool whole = tile.width == 0 && tile.height == 0 && tile.x == 0 && tile.y == 0;
    if (!whole && (tile.width == 0 || tile.height == 0 || right > request.output.resolution ||
                   bottom > request.output.resolution)) {
        return Outside(request, "tile",
                       "[" + U64(tile.x) + ", " + U64(tile.y) + ", " + U64(tile.width) + ", " +
                           U64(tile.height) + "]",
                       "a non-empty rectangle inside the " + U64(request.output.resolution) +
                           " texel output");
    }
    return std::nullopt;
}

std::expected<IProceduralBackend*, UnsupportedProcedural> ProceduralSeam::Select(
    const ProceduralRequest& request) const {
    if (m_snapshot != nullptr && m_snapshot->CanEvaluate(request)) return m_snapshot;
    if (m_hlsl != nullptr && m_hlsl->CanEvaluate(request)) return m_hlsl;
    if (m_hlsl != nullptr) {
        std::optional<UnsupportedProcedural> refusal = m_hlsl->Refusal(request);
        if (refusal && refusal->reason != kNoFamily) return Refused(*refusal);
    }
    return Refused(Refuse(AssetName(request), kNoBackend));
}

std::expected<RasterFuture, UnsupportedProcedural> ProceduralSeam::Evaluate(
    const ProceduralRequest& request, const InputImages& inputs) const {
    std::expected<IProceduralBackend*, UnsupportedProcedural> backend = Select(request);
    if (!backend) return Refused(backend.error());
    return (*backend)->Evaluate(request, inputs);
}

}  // namespace uzp::procedural
