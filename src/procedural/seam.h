#pragma once

// The procedural backend seam (docs/architecture/05-procedural-content.md §2, §3, §6; decisions
// 006, 222): one request type, one backend interface, the parity status vocabulary, the
// certified editable domain and the seam that tries `SnapshotBackend` then `HlslBackend` per
// asset. A request that no backend can serve is refused with `UnsupportedProcedural{asset,
// reason}` before anything is evaluated: nothing is clamped, nothing is replaced by the nearest
// certified point and no similar asset is substituted. There is no Adobe runtime adapter behind
// this seam, and none is reserved (decision 002).
//
// The domain check mirrors `tools/parity/proc_cert/batch.py` `Domain.refusal` (decision 303):
// the same field names (`params.<name>`, `seed`, `inputs.<usage>.<property>`,
// `output.<property>`), the same order of checks and the same seed policies.

#include "render/backend.h"

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/resource_url.h"

#include <cstdint>
#include <expected>
#include <future>
#include <map>
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace uzp::procedural {

/// A parameter value. Booleans travel as integers, as Painter's documentation passes them
/// (`SourceSubstance.set_parameters`, 05 §7); numbers compare by value, so 1 equals 1.0.
using ParamValue = std::variant<int64_t, double, std::string>;
using Params = std::map<std::string, ParamValue>;

/// Stored channel formats, in the certification harness's vocabulary (decision 305).
enum class ChannelFormat : uint8_t { U8, U16, F16, F32 };

/// "u8", "u16", "f16" or "f32".
[[nodiscard]] std::string_view FormatName(ChannelFormat format);

/// A raster's checkable properties (an output, or an image input such as a mesh map).
struct RasterSpec {
    uint32_t resolution = 0;  ///< Square, in texels.
    ChannelFormat format = ChannelFormat::F32;
    std::string colourSpace;  ///< "linear", "srgb", "raw", ...
    uint32_t channels = 1;

    bool operator==(const RasterSpec&) const = default;
};

/// An image input (a mesh map by usage, an anchor, a bitmap): its properties and the SHA-256
/// of its bytes.
struct ImageInput {
    RasterSpec spec;
    std::string sha256;

    bool operator==(const ImageInput&) const = default;
};

/// The part of the texture a request evaluates; an empty rectangle is the whole texture.
struct TileRect {
    uint32_t x = 0;
    uint32_t y = 0;
    uint32_t width = 0;
    uint32_t height = 0;

    bool operator==(const TileRect&) const = default;
};

/// One evaluation of one pinned procedural asset (05 §2). `params` holds the effective
/// parameters, defaults included.
struct ProceduralRequest {
    core::AssetUrl asset;  ///< `uzasset://<family>/<id>@<version>`.
    Params params;
    std::optional<std::string> preset;
    std::map<std::string, ImageInput> inputs;  ///< By usage or input name.
    std::string meshClass;                     ///< The mesh class the geometry stands for.
    uint32_t uvTiles = 1;
    RasterSpec output;
    TileRect tile;
    uint64_t seed = 0;
    /// The asset output evaluated (`SourceSubstance.active_output`, 05 §7); empty for an asset
    /// with one output.
    std::string outputId;
    /// The project settings that affect evaluation (`EvaluationSettings`, admission.h), by name.
    Params settings;
};

/// `uzasset://<family>/<id>@<version>` of the request.
[[nodiscard]] std::string AssetName(const ProceduralRequest& request);

/// The request's exact signature (05 §4, decision 327) as a JSON object: `asset` (the asset id,
/// `uzasset://<family>/<id>`), `version`, `params` (the effective parameters, defaults
/// included), `preset`, `seed`, `output` {id, resolution, format, colour_space, channels},
/// `inputs` {name: {sha256, resolution, format, colour_space, channels}}, `mesh` {class,
/// uv_tiles} and `settings` (the project settings that affect evaluation). Numbers compare by
/// value: an integral double is written as an integer, so 1 and 1.0 give one signature; a
/// non-finite number is `{"non_finite": "nan" | "inf" | "-inf"}`. The tile is not part of it:
/// a tile is a part of the same texture.
[[nodiscard]] core::json::Value SignatureJson(const ProceduralRequest& request);
/// The canonical JSON text of `SignatureJson(request)` (MANIFEST.md §2).
[[nodiscard]] std::string Signature(const ProceduralRequest& request);
/// SHA-256 (lower-case hex) of `Signature(request)`.
[[nodiscard]] std::string SignatureHash(const ProceduralRequest& request);

// ── Parity status (05 §3, decisions 303 and 305) ─────────────────────────────

/// Residual statistics of one unit (`code_u8`, `code_u16`, `ulp_f16`, `ulp_f32`), pooled over
/// the compared cases: integer distances, an exact sum and a nearest-rank p99.
struct Residual {
    std::string unit;
    uint64_t max = 0;
    uint64_t sum = 0;
    uint64_t count = 0;
    uint64_t p99 = 0;

    [[nodiscard]] double Mean() const { return count == 0 ? 0.0 : double(sum) / double(count); }
    bool operator==(const Residual&) const = default;
};

struct ParityStatus {
    enum class Kind : uint8_t {
        /// Zero residual on every calibration and held-out case (decision 222).
        Exact,
        /// A non-zero residual: a candidate exception for the owner, never a pass (decision 017).
        Calibrated,
        /// Not certified.
        Unavailable,
    };
    Kind kind = Kind::Unavailable;
    std::vector<Residual> residuals;     ///< Calibrated only, one per unit.
    std::vector<std::string> corpusIds;  ///< The calibration and held-out corpus ids.
    std::string reason;                  ///< Unavailable: why.

    [[nodiscard]] static ParityStatus Unavailable(std::string reason);
    bool operator==(const ParityStatus&) const = default;
};

/// "exact", "calibrated" or "unavailable".
[[nodiscard]] std::string_view KindName(ParityStatus::Kind kind);

// ── The refusal ──────────────────────────────────────────────────────────────

/// `UnsupportedProcedural{asset, reason}` (05 §2, §6): raised before any mutation. A refusal
/// outside the certified domain also names the field, the value and the certified range.
struct UnsupportedProcedural {
    std::string asset;
    std::string reason;
    std::string field;
    std::string value;
    std::string certified;

    /// `UnsupportedProcedural{asset: ..., reason: ...[, field: ..., value: ..., certified range:
    /// ...]}`.
    [[nodiscard]] std::string Describe() const;
    bool operator==(const UnsupportedProcedural&) const = default;
};

/// A refusal without a field (`asset` and `reason` only).
[[nodiscard]] UnsupportedProcedural Refuse(std::string asset, std::string_view reason);

/// `std::unexpected<UnsupportedProcedural>`, named through `std::expected` (Zig's libc++ also
/// declares the pre-C++17 `std::unexpected()`, which makes the bare name ambiguous).
using Refused = std::expected<void, UnsupportedProcedural>::unexpected_type;

inline constexpr std::string_view kOutsideDomain = "outside certified domain";
inline constexpr std::string_view kNoBackend = "no snapshot and no certified family";
inline constexpr std::string_view kNotCertified = "family not certified";
/// The HLSL backend's reason for an asset it has no family for; the seam reports `kNoBackend`.
inline constexpr std::string_view kNoFamily = "no certified family";

// ── The certified editable domain (decision 222 §1) ──────────────────────────

/// One parameter of the domain: a closed numeric range, or an enumerated set.
struct ParamRule {
    std::optional<std::pair<double, double>> range;
    std::vector<ParamValue> set;
};

/// A joint constraint between ranged parameters: sum(coefficient x value) <= max, judged
/// exactly (no rounding of the sum).
struct LinearConstraint {
    std::map<std::string, double> coefficients;
    double max = 0.0;
};

/// The checkable properties an image input or the output must have.
struct RasterRule {
    std::vector<uint32_t> resolutions;
    std::vector<ChannelFormat> formats;
    std::vector<std::string> colourSpaces;
    std::vector<uint32_t> channels;
};

struct CertifiedDomain {
    std::map<std::string, ParamRule> parameters;
    std::vector<LinearConstraint> constraints;
    /// The presets the domain certifies; a request naming another one is refused.
    std::vector<std::string> presets;
    /// Seed policy: any 32-bit seed, or the listed ones.
    bool anySeed = true;
    std::vector<uint64_t> seeds;
    std::vector<std::string> meshClasses;
    uint32_t uvTiles = 1;
    std::map<std::string, RasterRule> inputs;
    RasterRule output;
};

/// The first field of `request` outside `domain`, or empty inside it. Nothing is clamped.
/// The order of checks is that of `proc_cert` `Domain.refusal`: parameters (missing, extra,
/// ranges, sets, constraints), preset, seed, mesh class, UV tiles, inputs (missing, extra), then
/// the output's and each input's resolution, format, colour space and channels; then the tile.
[[nodiscard]] std::optional<UnsupportedProcedural> CheckDomain(const ProceduralRequest& request,
                                                               const CertifiedDomain& domain);

/// Decoded rasters: rows top to bottom, `channels` float32 values per texel.
struct Raster {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 0;
    std::vector<float> texels;

    bool operator==(const Raster&) const = default;
};

/// The decoded image inputs of a request, by the names of `ProceduralRequest::inputs`.
using InputImages = std::map<std::string, Raster>;

using RasterFuture = std::future<render::Result<Raster>>;

// ── The backend interface (05 §2) ────────────────────────────────────────────

class IProceduralBackend {
public:
    virtual ~IProceduralBackend() = default;
    /// The backend's name in reports ("snapshot", "hlsl").
    [[nodiscard]] virtual std::string_view Name() const = 0;
    [[nodiscard]] virtual ParityStatus Status(const core::AssetUrl& asset) const = 0;
    /// Whether this backend serves `request` exactly as asked.
    [[nodiscard]] virtual bool CanEvaluate(const ProceduralRequest& request) const = 0;
    /// Why `CanEvaluate(request)` is false (empty when it is true).
    [[nodiscard]] virtual std::optional<UnsupportedProcedural> Refusal(
        const ProceduralRequest& request) const = 0;
    /// Evaluates a request this backend can serve; a missing or invalid image input fails the
    /// evaluation loudly (`request_failed`).
    virtual RasterFuture Evaluate(const ProceduralRequest& request, const InputImages& inputs) = 0;
};

/// The seam: per request, the snapshot backend first, then the HLSL backend.
class ProceduralSeam {
public:
    /// Either backend may be absent (null).
    ProceduralSeam(IProceduralBackend* snapshot, IProceduralBackend* hlsl)
        : m_snapshot(snapshot), m_hlsl(hlsl) {}

    /// The backend that serves `request`, or the refusal. Evaluates nothing.
    [[nodiscard]] std::expected<IProceduralBackend*, UnsupportedProcedural> Select(
        const ProceduralRequest& request) const;

    /// `Select`, then the selected backend's evaluation; a refusal evaluates nothing.
    std::expected<RasterFuture, UnsupportedProcedural> Evaluate(const ProceduralRequest& request,
                                                                const InputImages& inputs) const;

private:
    IProceduralBackend* m_snapshot;
    IProceduralBackend* m_hlsl;
};

}  // namespace uzp::procedural
