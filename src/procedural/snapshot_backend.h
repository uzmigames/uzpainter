#pragma once

// `SnapshotBackend` (docs/architecture/05-procedural-content.md §2, §4; decisions 006, 222, 327):
// frozen per-project snapshots behind `IProceduralBackend`. A snapshot is a raster the user's
// own Painter produced for the user's own project, stored in that project's `.uzp` as a raster
// plane with its exact signature (`SignatureJson`) in the manifest (store/snapshots.h).
//
// It serves a request only when the request's signature is exactly a stored one: every field of
// 05 §4 (asset id and version, effective parameters, preset, seed, output id, resolution, channel
// format, colour space, channels, image inputs by hash, mesh class, UV tiles and the project
// settings that affect evaluation). Otherwise it is `unavailable`, and the seam tries the
// certified families or raises `UnsupportedProcedural`. Nothing is resampled, interpolated or
// extrapolated: a tile is a copy of the stored texels.
//
// A snapshot is migration data only: `Status` is `unavailable` for every asset, it never counts
// as calibration or held-out evidence and never widens a certified editable domain (decision
// 222). A changed parameter changes the signature, so the edit is served by another backend or
// refused (admission.h).

#include "procedural/seam.h"

#include "store/project_store.h"
#include "uzp_core/types/project.h"

#include <expected>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace uzp::procedural {

/// Why a snapshot backend does not serve a request whose signature it does not hold.
inline constexpr std::string_view kNoSnapshot = "no snapshot with this signature";
/// Why the snapshot of a request's signature gives no `image_outputs`.
inline constexpr std::string_view kNoImageOutputs = "the snapshot's recording observed no image outputs";
/// `SnapshotBackend::Status` of every asset.
inline constexpr std::string_view kSnapshotStatus =
    "snapshots are exact-signature migration data and certify no asset";

/// The stored raster of one snapshot: its output spec and its texels, row-major from the top row,
/// `channels` samples per texel in the format's little-endian encoding (1, 2, 2 or 4 bytes for
/// u8, u16, f16, f32), exactly as recorded.
struct SnapshotRaster {
    RasterSpec spec;
    std::string bytes;

    bool operator==(const SnapshotRaster&) const = default;
};

/// The plane format of an output spec: `L8`/`RGB8`, `L16`/`RGB16`, `L16F`/`RGB16F` or
/// `L32F`/`RGB32F` for 1 or 3 channels of u8, u16, f16 or f32; empty for another channel count.
[[nodiscard]] std::optional<core::ChannelFormat> SnapshotPlaneFormat(const RasterSpec& spec);

class SnapshotBackend final : public IProceduralBackend {
public:
    SnapshotBackend() = default;

    /// The snapshots `project` (a revision of the project `store` holds) records, read through
    /// their plane bindings (verified against their chunk roots). Refused, naming the entry: a
    /// malformed entry, one stored under another hash than its signature's, one recorded for
    /// another project, and a plane whose format or size is not the signature's output.
    [[nodiscard]] static std::expected<SnapshotBackend, std::string> Load(store::ProjectStore& store,
                                                                         const core::Project& project);

    /// Adds a snapshot (`Load` and tests), with its recorded `image_outputs` when known.
    void Add(const ProceduralRequest& request, SnapshotRaster raster,
             std::optional<std::vector<std::string>> imageOutputs = std::nullopt);

    [[nodiscard]] std::string_view Name() const override { return "snapshot"; }
    /// `unavailable` for every asset (`kSnapshotStatus`): a snapshot certifies nothing.
    [[nodiscard]] ParityStatus Status(const core::AssetUrl& asset) const override;
    /// True only for a stored signature and a tile inside the output.
    [[nodiscard]] bool CanEvaluate(const ProceduralRequest& request) const override;
    /// `kNoSnapshot`, naming the first field where the request's signature differs from the
    /// closest stored signature of the same asset id (the field is empty when the project holds no
    /// snapshot of that asset); a tile outside the output names `tile`.
    [[nodiscard]] std::optional<UnsupportedProcedural> Refusal(
        const ProceduralRequest& request) const override;
    /// The stored texels as float32 values (u8 and u16 codes divided by 255 and 65535, f16 widened
    /// exactly), cropped to the request's tile; `request_failed` for a request it cannot serve.
    RasterFuture Evaluate(const ProceduralRequest& request, const InputImages& inputs) override;

    /// The stored raster of the request's exact signature, byte for byte, or the refusal.
    [[nodiscard]] std::expected<const SnapshotRaster*, UnsupportedProcedural> Stored(
        const ProceduralRequest& request) const;
    /// A copy of the `image_outputs` the snapshot of the request's exact signature recorded
    /// (store/snapshots.h `source_metadata`); the refusal when no snapshot has that signature, or
    /// `kNoImageOutputs` when its recording observed none. No other snapshot is consulted.
    [[nodiscard]] std::expected<std::vector<std::string>, UnsupportedProcedural> ImageOutputs(
        const ProceduralRequest& request) const;

    [[nodiscard]] size_t size() const { return m_snapshots.size(); }

private:
    struct Entry {
        core::json::Value signature;
        SnapshotRaster raster;
        std::optional<std::vector<std::string>> imageOutputs;
    };
    std::map<std::string, Entry> m_snapshots;  ///< By signature SHA-256.
};

/// Records `bytes` (laid out as `SnapshotRaster::bytes` for `request.output`) as the snapshot of
/// `request` in the transaction's working copy (`ProjectStore::RecordSnapshot`): a new plane in
/// `SnapshotPlaneFormat(request.output)` and the request's signature in the manifest. Call it
/// from the transaction's call; returns the plane id. Throws `core::ValueError` for a request
/// that names a tile (a snapshot is a whole texture), an output of 2 or 4 channels, bytes of
/// another size, and what `RecordSnapshot` throws. `imageOutputs`, when given, is stored as the
/// entry's `source_metadata`.
core::Id RecordSnapshot(store::ProjectStore& store, core::Edit& edit, const ProceduralRequest& request,
                        std::string bytes,
                        const std::optional<std::vector<std::string>>& imageOutputs = std::nullopt);

}  // namespace uzp::procedural
