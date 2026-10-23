#include "procedural/seam.h"

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <bit>
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
    if (const auto* i = std::get_if<int64_t>(&value)) return std::to_string(*i);
    if (const auto number = AsNumber(value)) return Number(*number);
    return core::json::WriteCanonical(ParamJson(value));
}

/// Numbers equal by value (1 == 1.0), strings by their characters; a number never equals a
/// string.
bool SameValue(const ParamValue& a, const ParamValue& b) {
    const std::optional<double> x = AsNumber(a);
    const std::optional<double> y = AsNumber(b);
    if (x && y) {
        if (std::isnan(*x) || std::isnan(*y)) return false;
        return ParamJson(a) == ParamJson(b);
    }
    if (x || y) return false;
    return ParamJson(a) == ParamJson(b);
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
std::optional<int> ExactSign(const std::vector<double>& values) {
    std::vector<double> expansion;
    for (const double b : values) {
        std::vector<double> next;
        double q = b;
        for (const double e : expansion) {
            const double s = q + e;
            const double bv = s - q;
            const double av = s - bv;
            const double low = (q - av) + (e - bv);
            if (!std::isfinite(s) || !std::isfinite(bv) || !std::isfinite(av) || !std::isfinite(low)) {
                return std::nullopt;
            }
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

/// A normalized Dekker product avoids overflow in splitting and runtime fma cancellation
/// errors. Refuse products with bits below binary64's smallest subnormal rather than lose them.
bool ProductTerms(double a, double b, std::vector<double>& terms) {
    if (!std::isfinite(a) || !std::isfinite(b)) return false;
    if (a == 0 || b == 0) return true;
    int ae = 0, be = 0;
    const double am = std::frexp(a, &ae), bm = std::frexp(b, &be);
    const auto lowest = [](double mantissa, int exponent) {
        const auto integer = static_cast<uint64_t>(std::ldexp(std::abs(mantissa), 53));
        return exponent - 53 + std::countr_zero(integer);
    };
    if (lowest(am, ae) + lowest(bm, be) < -1074) return false;
    constexpr double splitter = 134217729.0;
    const double ac = splitter * am, bc = splitter * bm;
    const double ah = ac - (ac - am), bh = bc - (bc - bm);
    const double al = am - ah, bl = bm - bh;
    const double product = am * bm;
    const double error1 = product - ah * bh;
    const double error2 = error1 - al * bh;
    const double error3 = error2 - ah * bl;
    const double error = al * bl - error3;
    const double high = std::ldexp(product, ae + be);
    const double low = std::ldexp(error, ae + be);
    if (!std::isfinite(high) || !std::isfinite(low)) return false;
    terms.push_back(high);
    terms.push_back(low);
    return true;
}

/// Missing result means the exact constraint cannot be established in this expansion range.
std::optional<bool> Satisfies(const LinearConstraint& constraint, const Params& params) {
    std::vector<double> terms;
    if (!std::isfinite(constraint.max)) return std::nullopt;
    for (const auto& [name, coefficient] : constraint.coefficients) {
        const auto it = params.find(name);
        if (it != params.end()) {
            if (const auto* integer = std::get_if<int64_t>(&it->second)) {
                // Each signed 32-bit part is exact in binary64, including INT64_MIN.
                constexpr int64_t base = int64_t{1} << 32;
                if (!ProductTerms(coefficient, static_cast<double>(*integer / base) * static_cast<double>(base), terms) ||
                    !ProductTerms(coefficient, static_cast<double>(*integer % base), terms)) return std::nullopt;
                continue;
            }
        }
        const std::optional<double> number =
            it == params.end() ? std::nullopt : AsNumber(it->second);
        if (!number) return false;
        if (!ProductTerms(coefficient, *number, terms)) return std::nullopt;
    }
    terms.push_back(-constraint.max);
    const auto sign = ExactSign(terms);
    return sign ? std::optional<bool>(*sign <= 0) : std::nullopt;
}

bool InRange(const ParamValue& value, double low, double high) {
    if (std::isnan(low) || std::isnan(high)) return false;
    if (const auto* integer = std::get_if<int64_t>(&value)) {
        constexpr double minimum = -0x1p63;
        constexpr double pastMaximum = 0x1p63;
        const bool above = low <= minimum ||
            (low < pastMaximum && *integer >= static_cast<int64_t>(std::ceil(low)));
        const bool below = high >= pastMaximum ||
            (high >= minimum && *integer <= static_cast<int64_t>(std::floor(high)));
        return above && below;
    }
    const auto* number = std::get_if<double>(&value);
    return number && low <= *number && *number <= high;
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

core::json::Value ParamJson(const ParamValue& parameter) {
    namespace json = core::json;
    const auto number = [](const ParamNumber& v) -> json::Value {
        if (const auto* i = std::get_if<int64_t>(&v)) return *i;
        const double d = std::get<double>(v);
        if (std::isnan(d)) return json::Object{{"non_finite", "nan"}};
        if (std::isinf(d)) return json::Object{{"non_finite", d > 0 ? "inf" : "-inf"}};
        // Numbers by value: an integral double inside the int64 range is that integer.
        if (std::trunc(d) == d && d >= -9223372036854775808.0 && d < 9223372036854775808.0) {
            return static_cast<int64_t>(d);
        }
        return d;
    };
    const auto component = [&](const ParamNumber& v) -> json::Value {
        if (const auto* d = std::get_if<double>(&v); d && !std::isfinite(*d)) {
            throw core::ValueError("procedural vector/color components must be finite numbers");
        }
        return number(v);
    };
    if (const auto* s = std::get_if<std::string>(&parameter)) return *s;
    if (const auto* i = std::get_if<int64_t>(&parameter)) return *i;
    if (const auto* d = std::get_if<double>(&parameter)) return number(*d);
    if (const auto* vector = std::get_if<ParamVector>(&parameter)) {
        if (vector->components.size() < 2 || vector->components.size() > 4) {
            throw core::ValueError("procedural vectors need 2 to 4 components");
        }
        json::Array values;
        for (const auto& v : vector->components) values.push_back(component(v));
        return values;
    }
    const auto& color = std::get<ParamColor>(parameter);
    if (color.working_space.empty()) throw core::ValueError("procedural colors need a working space");
    json::Array values;
    for (const auto& v : color.components) values.push_back(component(v));
    return json::Object{{"type", "color"}, {"working_space", color.working_space},
                        {"components", std::move(values)},
                        {"alpha", color.alpha ? component(*color.alpha) : json::Value()}};
}

std::expected<ParamValue, std::string> ParamFromJson(const core::json::Value& value) {
    namespace json = core::json;
    const auto number = [](const json::Value& v) -> std::optional<ParamNumber> {
        if (v.IsInt()) return std::get<int64_t>(v.data);
        if (v.IsDouble() && std::isfinite(std::get<double>(v.data))) return std::get<double>(v.data);
        return std::nullopt;
    };
    if (value.IsBool()) return ParamValue{int64_t{std::get<bool>(value.data) ? 1 : 0}};
    if (value.IsInt()) return ParamValue{std::get<int64_t>(value.data)};
    if (value.IsDouble() && std::isfinite(std::get<double>(value.data))) {
        return ParamValue{std::get<double>(value.data)};
    }
    if (value.IsString()) return ParamValue{std::get<std::string>(value.data)};
    if (value.IsArray()) {
        const auto& values = std::get<json::Array>(value.data);
        if (values.size() < 2 || values.size() > 4) return std::expected<ParamValue, std::string>(std::unexpect, "a vector needs 2 to 4 components");
        ParamVector vector;
        for (const auto& v : values) {
            const auto n = number(v);
            if (!n) return std::expected<ParamValue, std::string>(std::unexpect, "vector components must be finite numbers");
            vector.components.push_back(*n);
        }
        return ParamValue{std::move(vector)};
    }
    if (value.IsObject()) {
        const auto& object = std::get<json::Object>(value.data);
        if (object.size() != 4 || !object.contains("type") || !object.contains("working_space") ||
            !object.contains("components") || !object.contains("alpha")) {
            return std::expected<ParamValue, std::string>(std::unexpect, "a color needs exactly type, working_space, components and alpha");
        }
        if (object.at("type") != json::Value("color") || !object.at("working_space").IsString() ||
            std::get<std::string>(object.at("working_space").data).empty() || !object.at("components").IsArray()) {
            return std::expected<ParamValue, std::string>(std::unexpect, "a color needs type color, a nonempty working_space and three components");
        }
        const auto& values = std::get<json::Array>(object.at("components").data);
        if (values.size() != 3) return std::expected<ParamValue, std::string>(std::unexpect, "a color needs three components");
        ParamColor color;
        color.working_space = std::get<std::string>(object.at("working_space").data);
        for (size_t i = 0; i < 3; ++i) {
            const auto n = number(values[i]);
            if (!n) return std::expected<ParamValue, std::string>(std::unexpect, "color components must be finite numbers");
            color.components[i] = *n;
        }
        if (!object.at("alpha").IsNull()) {
            color.alpha = number(object.at("alpha"));
            if (!color.alpha) return std::expected<ParamValue, std::string>(std::unexpect, "color alpha must be null or a finite number");
        }
        return ParamValue{std::move(color)};
    }
    return std::expected<ParamValue, std::string>(std::unexpect, "a parameter must be a finite number, boolean, string, vector or tagged color");
}

core::json::Value SignatureJson(const ProceduralRequest& request) {
    namespace json = core::json;
    const auto params = [&](const Params& map) {
        json::Object out;
        for (const auto& [name, v] : map) out[name] = ParamJson(v);
        return out;
    };
    const auto spec = [](const RasterSpec& s, json::Object out) {
        out["resolution"] = int64_t{s.resolution};
        out["format"] = std::string(FormatName(s.format));
        out["colour_space"] = s.colourSpace;
        out["channels"] = int64_t{s.channels};
        return out;
    };
    json::Object inputs;
    for (const auto& [name, input] : request.inputs) {
        inputs[name] = spec(input.spec, json::Object{{"sha256", input.sha256}});
    }
    return json::Object{
        {"asset", "uzasset://" + request.asset.family + "/" + request.asset.id},
        {"version", request.asset.version},
        {"params", params(request.params)},
        {"preset", request.preset ? json::Value(*request.preset) : json::Value()},
        // A seed is 64-bit unsigned; the JSON integer is its two's-complement value.
        {"seed", static_cast<int64_t>(request.seed)},
        {"output", spec(request.output, json::Object{{"id", request.outputId}})},
        {"inputs", std::move(inputs)},
        {"mesh", json::Object{{"class", request.meshClass}, {"uv_tiles", int64_t{request.uvTiles}}}},
        {"settings", params(request.settings)},
    };
}

std::string Signature(const ProceduralRequest& request) {
    return core::json::WriteCanonical(SignatureJson(request));
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
        const auto [low, high] = *rule.range;
        if (!InRange(value, low, high)) {
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
        const auto satisfies = Satisfies(constraint, request.params);
        if (!satisfies || !*satisfies) {
            std::string values = "{";
            for (const auto& [name, coefficient] : constraint.coefficients) {
                const auto it = request.params.find(name);
                values += (values.size() > 1 ? ", " : "") + name + ": " +
                          (it == request.params.end() ? std::string("missing") : Text(it->second));
            }
            return Outside(request, "params", values + "}", Describe(constraint) +
                (satisfies ? "" : " (exact arithmetic unavailable: product underflow or expansion overflow)"));
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
