// Native tests of the material family (src/procedural/materials.h, rulebook task
// phase3.2_proc-material-families, decision 334). Built by `zig build proc-material-tests` and
// driven by tests/procedural/test_proc_material_families.py.
//
// Usage: uzp-proc-material-tests <case> <work-dir> <shipped-library>
//   library   the shipped library loads natively with every material's outputs and physical
//             size, the loader refuses a malformed output or physical size, and `assets list
//             --parity` prints both (CPU; item 2.6)
//   families  every material registers from its record; every output evaluates on the CPU lane
//             inside [0, 1] with its channels; a tile equals the whole texture's texels; every
//             declared parameter changes an output; every output is reachable through
//             `output_mapping` and equals the output evaluated directly; the seam refuses every
//             uncertified output (CPU; items 2.2, 2.3)
//   tiling    every material's texture continued past its border is the texture itself, bit for
//             bit, at several tilings and resolutions (CPU)
//   physical  the same material on one mesh imported in two unit scales repeats by its physical
//             size under the project unit rule, MaterialPhysicalSize and CustomPhysicalSize, and
//             every receipt records the effective units (CPU; item 2.4, test 3.2 our half)
//   domain    a parameter, a seed, a mesh-map input, a resolution and a format just outside each
//             material's domain are refused before mutation, naming the field, with nothing
//             clamped; inside it the uncertified material is refused as such; an admitted
//             material source commits the reference as given (CPU; test 3.4)
//   kernels   every output's kernel passes compiled to DXIL and SPIR-V (CPU, needs
//             dxcompiler.dll)
//   gpu       every output of every material on DX12 equal to its CPU reference bit for bit, whole
//             and by a border tile; the same request twice gives identical bytes; two seeds
//             differ (GPU; test 3.3)
//
// The shipped library is the repository's `assets/procedural/`. No case compares against a
// Painter output: the materials are not certified.
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` / `INFO` lines.
// Exit code 0 when every check passed, 1 when one failed, 2 on a usage error, 77 when the case
// needs a DX12 hardware adapter and there is none.

#include "procedural/asset_library.h"
#include "procedural/cli.h"
#include "procedural/hlsl_backend.h"
#include "procedural/materials.h"
#include "procedural/seam.h"

#include "mesh/mesh_import.h"
#include "render/engine_thread.h"
#include "render/kernel_cache.h"

#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/project.h"

#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <future>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>
#include "../no_error_dialogs.h"

namespace {

using namespace uzp::procedural;
namespace fs = std::filesystem;
namespace render = uzp::render;
namespace core = uzp::core;
namespace json = uzp::core::json;

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

int Finish() { return g_failures == 0 ? 0 : 1; }

uint32_t Bits(float value) { return std::bit_cast<uint32_t>(value); }

std::string Hex(uint32_t value) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "%08X", value);
    return buf;
}

/// The first value where two rasters differ bit for bit, or empty.
std::string FirstDifference(const Raster& a, const Raster& b) {
    if (a.width != b.width || a.height != b.height || a.channels != b.channels ||
        a.texels.size() != b.texels.size()) {
        return "shapes differ: " + std::to_string(a.width) + "x" + std::to_string(a.height) + "x" +
               std::to_string(a.channels) + " against " + std::to_string(b.width) + "x" +
               std::to_string(b.height) + "x" + std::to_string(b.channels);
    }
    size_t count = 0;
    std::string first;
    for (size_t i = 0; i < a.texels.size(); ++i) {
        if (Bits(a.texels[i]) == Bits(b.texels[i])) continue;
        if (count++ == 0) {
            const size_t texel = i / a.channels;
            first = "texel (" + std::to_string(texel % a.width) + ", " + std::to_string(texel / a.width) +
                    ") channel " + std::to_string(i % a.channels) + ": " + Hex(Bits(a.texels[i])) + " against " +
                    Hex(Bits(b.texels[i]));
        }
    }
    return count == 0 ? std::string() : std::to_string(count) + " values differ, first at " + first;
}

size_t Differing(const Raster& a, const Raster& b) {
    size_t count = 0;
    for (size_t i = 0; i < a.texels.size() && i < b.texels.size(); ++i) {
        if (Bits(a.texels[i]) != Bits(b.texels[i])) ++count;
    }
    return count + (a.texels.size() > b.texels.size() ? a.texels.size() - b.texels.size()
                                                      : b.texels.size() - a.texels.size());
}

std::string Url(std::string_view id) { return "uzasset://material/" + std::string(id) + "@1"; }

struct Fixture {
    AssetLibrary library;
    std::vector<const AssetRecord*> records;  ///< In `MaterialAssetIds()` order.
};

std::optional<Fixture> LoadFixture(const fs::path& shipped) {
    auto loaded = AssetLibrary::Load(shipped);
    Check(loaded.has_value(), "the shipped library loads", loaded ? "" : loaded.error());
    if (!loaded) return std::nullopt;
    Fixture fixture{std::move(*loaded), {}};
    for (const std::string_view id : MaterialAssetIds()) {
        const AssetRecord* record = fixture.library.Find(core::ParseAssetUrl(Url(id)));
        if (record == nullptr) {
            Check(false, "the shipped library holds every material", "no record of " + Url(id));
            return std::nullopt;
        }
        fixture.records.push_back(record);
    }
    return fixture;
}

const AssetOutput& OutputOf(const AssetRecord& record, std::string_view id) {
    for (const AssetOutput& output : record.outputs) {
        if (output.id == id) return output;
    }
    return record.outputs.front();
}

/// A request inside the record's domain for output `output`: its defaults, the `sphere` class, a
/// float32 output at `resolution` with the output's channels and colour space, and `seed`.
ProceduralRequest Request(const AssetRecord& record, std::string_view output, uint32_t resolution, uint64_t seed) {
    const AssetOutput& spec = OutputOf(record, output);
    ProceduralRequest request;
    request.asset = record.asset;
    request.params = record.defaults;
    request.meshClass = "sphere";
    request.output = RasterSpec{resolution, ChannelFormat::F32, spec.colourSpace, spec.channels};
    request.seed = seed;
    request.outputId = std::string(output);
    return request;
}

double NumberOf(const ParamValue& value) {
    if (const auto* d = std::get_if<double>(&value)) return *d;
    if (const auto* i = std::get_if<int64_t>(&value)) return static_cast<double>(*i);
    return 0.0;
}

/// A request with one parameter changed (an integer or a number, as the record's default).
ProceduralRequest With(ProceduralRequest request, const std::string& name, double value) {
    if (std::holds_alternative<int64_t>(request.params.at(name)) && value == static_cast<double>(int64_t(value))) {
        request.params[name] = static_cast<int64_t>(value);
    } else {
        request.params[name] = value;
    }
    return request;
}

/// The tile used by the CPU checks.
constexpr TileRect kProbe{448, 448, 96, 96};

// ── library (item 2.6) ───────────────────────────────────────────────────────

std::string ReadText(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream text;
    text << stream.rdbuf();
    return text.str();
}

void WriteText(const fs::path& path, const std::string& text) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream << text;
}

int RunLibrary(const fs::path& dir, const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    std::printf("LOADED %zu\n", fixture->library.records().size());
    bool declared = true;
    std::string detail;
    for (const AssetRecord* record : fixture->records) {
        const std::string name = core::FormatAssetUrl(record->asset);
        if (record->outputs.size() != MaterialOutputIds().size() || !record->physicalSizeCm ||
            record->status.kind != ParityStatus::Kind::Unavailable || record->usage != "BASE_MATERIAL") {
            declared = false;
            detail += name + "; ";
            continue;
        }
        for (size_t i = 0; i < record->outputs.size(); ++i) {
            declared = declared && record->outputs[i].id == MaterialOutputIds()[i];
        }
        const std::map<std::string, std::string> mapping = DefaultOutputMapping(*record);
        declared = declared && mapping.size() == 6 && mapping.at("BaseColor") == "basecolor" &&
                   mapping.at("Normal") == "normal" && mapping.at("AO") == "ambient_occlusion";
    }
    Check(declared,
          "every material loads natively with its six outputs, its physical size and an unavailable status", detail);

    // The loader refuses a malformed output or physical size, naming the file and the reason.
    const fs::path source = shipped / "records" / "material.felt@1.json";
    const json::Value original = json::Parse(ReadText(source));
    struct Broken {
        std::string what;
        std::string reason;
        std::function<void(json::Object&)> change;
    };
    const auto output = [](json::Object& record) -> json::Object& {
        return std::get<json::Object>(std::get<json::Array>(record.at("outputs").data).front().data);
    };
    const std::vector<Broken> broken = {
        {"an output with an unknown member", "an output has an unknown member texture",
         [&](json::Object& r) { output(r)["texture"] = json::Value("x.png"); }},
        {"an output channel that is not a ChannelType", "channel Colour is not a ChannelType",
         [&](json::Object& r) { output(r)["channel"] = json::Value("Colour"); }},
        {"an output with channels outside the domain", "channels is not one of the domain's output channels",
         [&](json::Object& r) { output(r)["channels"] = json::Value(int64_t{4}); }},
        {"an output colour space outside the domain", "colour_space is not one of the domain's output colour spaces",
         [&](json::Object& r) { output(r)["colour_space"] = json::Value("acescg"); }},
        {"an output listed twice", "output normal is listed twice",
         [&](json::Object& r) {
             json::Array& list = std::get<json::Array>(r.at("outputs").data);
             json::Value copy = list[1];
             std::get<json::Object>(copy.data)["channel"] = json::Value("User0");
             list.push_back(copy);
         }},
        {"two outputs that feed one channel", "channel BaseColor is fed twice",
         [&](json::Object& r) {
             std::get<json::Object>(std::get<json::Array>(r.at("outputs").data)[1].data)["channel"] =
                 json::Value("BaseColor");
         }},
        {"an empty outputs list", "outputs lists at least one output",
         [&](json::Object& r) { r["outputs"] = json::Array{}; }},
        {"a negative physical size", "physical_size_cm holds two finite positive centimetre values",
         [&](json::Object& r) { r["physical_size_cm"] = json::Array{json::Value(-1.0), json::Value(50.0)}; }},
        {"a physical size of one value", "physical_size_cm is [width, height] in centimetres",
         [&](json::Object& r) { r["physical_size_cm"] = json::Array{json::Value(50.0)}; }},
    };
    for (const Broken& b : broken) {
        const fs::path root = dir / "broken-library";
        fs::remove_all(root);
        fs::create_directories(root / "records");
        json::Value record = original;
        b.change(std::get<json::Object>(record.data));
        WriteText(root / "records" / "material.felt@1.json", json::WriteCanonical(record));
        WriteText(root / "aliases.json", R"({"schema": "uzpainter/asset-aliases/1", "aliases": []})");
        WriteText(root / "library.json",
                  R"({"schema": "uzpainter/asset-library/1", "records": ["records/material.felt@1.json"], )"
                  R"("aliases": "aliases.json"})");
        const auto loaded = AssetLibrary::Load(root);
        Check(!loaded && loaded.error().find(b.reason) != std::string::npos &&
                  loaded.error().find("material.felt@1.json") != std::string::npos,
              "the loader refuses " + b.what, loaded ? "loaded" : loaded.error());
    }

    // `assets list --parity` prints each material's outputs and physical size beside its domain.
    const fs::path listing = dir / "assets-list.txt";
    std::FILE* out = std::fopen(listing.string().c_str(), "wb");
    const int status = RunAssetsCommand({"assets", "list", "--parity", "--library", shipped.string()}, out, stderr);
    std::fclose(out);
    std::string text = ReadText(listing);
    bool listed = status == 0 && text.rfind("UZP_JSON:", 0) == 0;
    if (listed) {
        const json::Value document = json::Parse(text.substr(9));
        size_t materials = 0;
        for (const json::Value& entry : std::get<json::Array>(std::get<json::Object>(document.data).at("assets").data)) {
            const json::Object& asset = std::get<json::Object>(entry.data);
            if (std::get<std::string>(asset.at("asset").data).rfind("uzasset://material/", 0) != 0) continue;
            ++materials;
            listed = listed && asset.contains("outputs") && asset.contains("physical_size_cm") &&
                     asset.contains("domain") &&
                     std::get<json::Array>(asset.at("outputs").data).size() == MaterialOutputIds().size();
        }
        size_t records = 0;
        for (const AssetRecord& record : fixture->library.records()) records += record.asset.family == kMaterialFamily;
        listed = listed && materials == records && materials >= MaterialAssetIds().size();
    }
    Check(listed, "assets list --parity prints every material's outputs and physical size", text.substr(0, 200));
    return Finish();
}

// ── families (items 2.2, 2.3) ────────────────────────────────────────────────

struct Stats {
    float min = 0.0f;
    float max = 0.0f;
};

Stats StatsOf(const Raster& raster) {
    Stats s;
    if (raster.texels.empty()) return s;
    s.min = s.max = raster.texels.front();
    for (const float v : raster.texels) {
        if (v < s.min) s.min = v;
        if (v > s.max) s.max = v;
    }
    return s;
}

int RunFamilies(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    const std::expected<void, std::string> registered = RegisterMaterialFamilies(hlsl, fixture->library);
    Check(registered.has_value(), "every material registers from its library record",
          registered ? "" : registered.error());
    if (!registered) return Finish();
    ProceduralSeam seam(nullptr, &hlsl);
    bool ranges = true;
    bool varies = true;
    bool dielectric = true;
    bool unitNormals = true;
    bool occlusion = true;
    bool tiles = true;
    bool params = true;
    bool mapped = true;
    bool refused = true;
    std::string detail;
    for (const AssetRecord* record : fixture->records) {
        const std::string name = core::FormatAssetUrl(record->asset);
        for (const std::string_view output : MaterialOutputIds()) {
            const std::string what = name + " " + std::string(output);
            ProceduralRequest request = Request(*record, output, 1024, 7);
            request.tile = kProbe;
            const render::Result<Raster> base = hlsl.EvaluateReference(request, {});
            const uint32_t channels = OutputOf(*record, output).channels;
            if (!base || base->channels != channels ||
                base->texels.size() != size_t{kProbe.width} * kProbe.height * channels) {
                ranges = false;
                detail += what + ": " + (base ? "wrong shape" : base.error().Describe()) + "; ";
                continue;
            }
            const Stats stats = StatsOf(*base);
            std::printf("INFO %s: min %.4f max %.4f\n", what.c_str(), stats.min, stats.max);
            if (stats.min < 0.0f || stats.max > 1.0f) {
                ranges = false;
                detail += what + " leaves [0, 1]; ";
            }
            if (output == "metallic") {
                dielectric = dielectric && stats.min == 0.0f && stats.max == 0.0f;
            } else if (!(stats.max > stats.min)) {
                varies = false;
                detail += what + " is constant; ";
            }
            if (output == "normal") {
                for (size_t t = 0; t < base->texels.size(); t += 3) {
                    const double x = 2.0 * base->texels[t] - 1.0;
                    const double y = 2.0 * base->texels[t + 1] - 1.0;
                    const double z = 2.0 * base->texels[t + 2] - 1.0;
                    if (std::fabs(x * x + y * y + z * z - 1.0) > 1e-5 || z <= 0.0) unitNormals = false;
                }
                // No relief, no tilt: the flat normal (0, 0, 1).
                const render::Result<Raster> flat = hlsl.EvaluateReference(With(request, "normal_intensity", 0), {});
                for (size_t t = 0; flat && t < flat->texels.size(); t += 3) {
                    unitNormals = unitNormals && flat->texels[t] == 0.5f && flat->texels[t + 1] == 0.5f &&
                                  std::fabs(flat->texels[t + 2] - 1.0f) <= 6e-8f;
                }
                unitNormals = unitNormals && flat.has_value();
            }
            if (output == "ambient_occlusion") {
                const float lowest = static_cast<float>(1.0 - NumberOf(request.params.at("ao_intensity")));
                occlusion = occlusion && stats.min >= lowest - 1e-6f && stats.max == 1.0f;
            }
            // A tile equals the same texels of the whole texture (for the two-pass outputs too).
            if (output == "height" || output == "normal" || output == "ambient_occlusion" || output == "basecolor") {
                ProceduralRequest whole = request;
                whole.tile = {};
                const render::Result<Raster> all = hlsl.EvaluateReference(whole, {});
                bool same = all.has_value();
                for (uint32_t y = 0; same && y < kProbe.height; ++y) {
                    for (uint32_t x = 0; same && x < kProbe.width; ++x) {
                        for (uint32_t c = 0; same && c < channels; ++c) {
                            same = Bits(base->texels[(size_t{y} * kProbe.width + x) * channels + c]) ==
                                   Bits(all->texels[((size_t{kProbe.y} + y) * 1024 + kProbe.x + x) * channels + c]);
                        }
                    }
                }
                if (!same) {
                    tiles = false;
                    detail += what + ": a tile differs from the texture's texels; ";
                }
            }
            // The seam serves no uncertified output.
            ProceduralRequest inside = request;
            inside.tile = {};
            const auto selected = seam.Select(inside);
            if (selected || selected.error().reason != kNotCertified) {
                refused = false;
                detail += what + ": " + (selected ? std::string("served") : selected.error().Describe()) + "; ";
            }
        }
        // Every declared parameter changes an output somewhere (no parameter is ignored).
        for (const auto& [param, rule] : record->domain.parameters) {
            double other = 0.0;
            const double current = NumberOf(record->defaults.at(param));
            if (rule.range) {
                other = current == rule.range->second ? rule.range->first : rule.range->second;
            } else {
                other = NumberOf(rule.set.front()) == current ? NumberOf(rule.set.back()) : NumberOf(rule.set.front());
            }
            bool changes = false;
            for (const std::string_view output : {"basecolor", "roughness", "normal", "ambient_occlusion"}) {
                ProceduralRequest request = Request(*record, output, 1024, 7);
                request.tile = kProbe;
                const render::Result<Raster> a = hlsl.EvaluateReference(request, {});
                const render::Result<Raster> b = hlsl.EvaluateReference(With(request, param, other), {});
                if (a && b && Differing(*a, *b) > 0) {
                    changes = true;
                    break;
                }
            }
            if (!changes) {
                params = false;
                detail += name + ": " + param + " changes nothing; ";
            }
        }
        // Every output is reachable through output_mapping: the default mapping gives one
        // request per channel, with the output's spec, equal to the output evaluated directly.
        core::ProceduralRef ref;
        ref.asset = name;
        for (const auto& [channel, output] : DefaultOutputMapping(*record)) ref.output_mapping[channel] = output;
        UseContext context;
        context.meshClass = "sphere";
        context.output = RasterSpec{1024, ChannelFormat::F32, "linear", 1};
        context.seed = 7;
        context.tile = kProbe;
        const auto requests = MaterialRequests(ref, context, fixture->library);
        if (!requests || requests->size() != MaterialOutputIds().size()) {
            mapped = false;
            detail += name + ": " + (requests ? std::string("wrong count") : requests.error().Describe()) + "; ";
        } else {
            for (const MaterialChannelRequest& channel : *requests) {
                const std::string& outputId = channel.request.outputId;
                const AssetOutput& spec = OutputOf(*record, outputId);
                ProceduralRequest direct = Request(*record, outputId, 1024, 7);
                direct.tile = kProbe;
                const render::Result<Raster> viaMapping = hlsl.EvaluateReference(channel.request, {});
                const render::Result<Raster> viaOutput = hlsl.EvaluateReference(direct, {});
                const bool ok = std::string(core::ToString(channel.channel)) == spec.channel &&
                                channel.request.output.channels == spec.channels &&
                                channel.request.output.colourSpace == spec.colourSpace && viaMapping && viaOutput &&
                                FirstDifference(*viaMapping, *viaOutput).empty();
                if (!ok) {
                    mapped = false;
                    detail += name + " " + outputId + " through output_mapping; ";
                }
            }
        }
        // A channel mapped to an output the record does not list is refused, naming it.
        core::ProceduralRef unknown = ref;
        unknown.output_mapping = {{"BaseColor", "albedo"}};
        const auto bad = MaterialRequests(unknown, context, fixture->library);
        mapped = mapped && !bad && bad.error().reason == kOutsideDomain &&
                 bad.error().field == "output_mapping.BaseColor" && bad.error().value == "\"albedo\"";
        core::ProceduralRef empty = ref;
        empty.output_mapping.clear();
        mapped = mapped && !MaterialRequests(empty, context, fixture->library).has_value();
        core::ProceduralRef notChannel = ref;
        notChannel.output_mapping = {{"Colour", "basecolor"}};
        mapped = mapped && !MaterialRequests(notChannel, context, fixture->library).has_value();
    }
    Check(ranges, "every output of every material evaluates on the CPU lane inside [0, 1] with its channels", detail);
    Check(varies, "no output but metallic is constant at the defaults", detail);
    Check(dielectric, "the metallic output of every material is 0");
    Check(unitNormals, "every normal output is a unit vector facing out, and (0, 0, 1) without relief");
    Check(occlusion, "every occlusion output lies in [1 - ao_intensity, 1] and is 1 on open surfaces");
    Check(tiles, "a tile of every output equals the same texels of the whole texture", detail);
    Check(params, "every declared parameter of every material changes an output", detail);
    Check(mapped,
          "every output of every material is reachable through output_mapping, and an unknown output, an empty "
          "mapping or a key that is not a channel is refused",
          detail);
    Check(refused, "the seam refuses every uncertified material output inside its domain (family not certified)",
          detail);

    // The family's own refusals.
    ProceduralRequest foreign = Request(*fixture->records.front(), "height", 1024, 0);
    foreign.asset = core::ParseAssetUrl("uzasset://filter/sharpen@1");
    Check(!MaterialWords(foreign).has_value(), "MaterialWords refuses an asset outside the family");
    ProceduralRequest missing = Request(*fixture->records.front(), "height", 1024, 0);
    missing.params.erase("roughness");
    Check(!MaterialWords(missing).has_value(), "MaterialWords refuses a request without a declared parameter");
    Check(!hlsl.EvaluateReference(missing, {}).has_value(),
          "the CPU lane refuses a request outside the domain before evaluating it");
    ProceduralRequest noOutput = Request(*fixture->records.front(), "height", 1024, 0);
    noOutput.outputId.clear();
    const auto joint = hlsl.Refusal(noOutput);
    Check(joint && joint->reason == kOutsideDomain && joint->field == "output.id" &&
              !hlsl.EvaluateReference(noOutput, {}).has_value(),
          "a material request that names no output is refused (output.id)", joint ? joint->Describe() : "admitted");
    ProceduralRequest wrongChannels = Request(*fixture->records.front(), "basecolor", 1024, 0);
    wrongChannels.output.channels = 1;
    const auto channelsRefusal = hlsl.Refusal(wrongChannels);
    Check(channelsRefusal && channelsRefusal->field == "output.channels",
          "a basecolor request with one channel is refused (output.channels)",
          channelsRefusal ? channelsRefusal->Describe() : "admitted");
    ProceduralRequest wrongSpace = Request(*fixture->records.front(), "height", 1024, 0);
    wrongSpace.output.colourSpace = "srgb";
    const auto spaceRefusal = hlsl.Refusal(wrongSpace);
    Check(spaceRefusal && spaceRefusal->field == "output.colour_space",
          "an sRGB height request is refused (output.colour_space)", spaceRefusal ? spaceRefusal->Describe() : "admitted");
    return Finish();
}

// ── tiling ───────────────────────────────────────────────────────────────────

int RunTiling(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    struct Variant {
        std::string what;
        uint32_t resolution;
        double tiling;  ///< 0: the default.
    };
    const std::vector<Variant> variants = {
        {"defaults at 1024", 1024, 0}, {"tiling 1 at 1024", 1024, 1}, {"tiling 3 at 2048", 2048, 3},
        {"tiling 32 at 4096", 4096, 32}, {"tiling 7 at 4096", 4096, 7},
    };
    bool periodic = true;
    std::string detail;
    size_t compared = 0;
    for (const AssetRecord* record : fixture->records) {
        const std::string name = core::FormatAssetUrl(record->asset);
        for (const Variant& variant : variants) {
            ProceduralRequest request = Request(*record, "height", variant.resolution, 1234);
            if (variant.tiling != 0) request = With(request, "tiling", variant.tiling);
            const auto words = MaterialWords(request, true);
            if (!words) {
                periodic = false;
                detail += name + ": " + words.error() + "; ";
                continue;
            }
            const int32_t r = static_cast<int32_t>(variant.resolution);
            const auto same = [&](int32_t x0, int32_t y0, int32_t x1, int32_t y1) {
                const std::array<float, 4> a = MaterialTexel(*words, x0, y0, 1234);
                const std::array<float, 4> b = MaterialTexel(*words, x1, y1, 1234);
                ++compared;
                return Bits(a[0]) == Bits(b[0]) && Bits(a[1]) == Bits(b[1]);
            };
            bool ok = true;
            for (int32_t k = 0; ok && k < r; k += 7) {
                ok = same(-1, k, r - 1, k) && same(r, k, 0, k) && same(k, -1, k, r - 1) && same(k, r, k, 0) &&
                     same(k + r, k + 2 * r, k, k);
            }
            if (!ok) {
                periodic = false;
                detail += name + " " + variant.what + "; ";
            }
        }
    }
    std::printf("INFO %zu texel pairs compared\n", compared);
    Check(periodic,
          "every material wraps seamlessly: its fields continued one tile past each border are the texture itself, "
          "bit for bit",
          detail);
    return Finish();
}

// ── physical (item 2.4, test 3.2 our half) ───────────────────────────────────

/// A 1 x 1 file-unit plane in the xy plane, UVs over the whole tile, as an OBJ (no unit).
constexpr std::string_view kPlaneObj = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
                                       "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\n"
                                       "f 1/1/1 2/2/1 3/3/1\nf 1/1/1 3/3/1 4/4/1\n";

bool Near(double a, double b) { return std::fabs(a - b) <= 1e-12 * std::fabs(b); }

int RunPhysical(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    // The same mesh in two unit scales: the OBJ's own unit (one centimetre per file unit, the
    // file states none) and `mesh_unit_scale` 100 (a file authored in metres).
    struct Scaled {
        std::string what;
        std::optional<double> meshUnitScale;
        double cm;  ///< The centimetres per file unit the rule gives.
        std::string from;
    };
    const std::vector<Scaled> scales = {{"the file unit", std::nullopt, 1.0, "file"},
                                        {"mesh_unit_scale 100", 100.0, 100.0, "mesh_unit_scale"}};
    std::vector<core::MeshReference> meshes;
    for (const Scaled& s : scales) {
        uzp::mesh::ImportSettings settings;
        settings.mesh_unit_scale = s.meshUnitScale;
        try {
            const uzp::mesh::ImportResult result = uzp::mesh::ImportMesh(kPlaneObj, "plane.obj", settings);
            meshes.push_back(core::MeshReference{result.sha256, result.report, {}, {}});
        } catch (const std::exception& error) {
            Check(false, "the plane imports with " + s.what, error.what());
            return Finish();
        }
    }
    core::TextureSet set;
    set.name = set.original_name = set.material_id = "default";

    const AssetRecord& felt = *fixture->records.front();
    const std::array<double, 2> size = *felt.physicalSizeCm;
    core::UVTransformation material;
    material.scale_mode = core::ScaleMode::MaterialPhysicalSize;
    core::UVTransformation custom;
    custom.scale_mode = core::ScaleMode::CustomPhysicalSize;
    custom.scale = {25.0, 10.0};
    bool rule = true;
    bool recorded = true;
    std::string detail;
    std::vector<json::Object> receipts;
    for (size_t m = 0; m < meshes.size(); ++m) {
        const Scaled& s = scales[m];
        for (const core::UVTransformation& transformation : {material, custom}) {
            const auto scale = EvaluatePhysicalScale(transformation, &felt, meshes[m], set);
            if (!scale) {
                rule = false;
                detail += s.what + ": " + scale.error() + "; ";
                continue;
            }
            const std::array<double, 2> cm =
                transformation.scale_mode == core::ScaleMode::MaterialPhysicalSize ? size : custom.scale;
            std::printf("INFO %s, %s: %s\n", s.what.c_str(), std::string(core::ToString(transformation.scale_mode)).c_str(),
                        json::WriteCanonical(scale->ToJson()).c_str());
            // One UV unit of the plane spans one file unit, s.cm centimetres; the texture repeats
            // (cm per UV) / size times per UV unit and (cm per file unit) / size per file unit.
            rule = rule && scale->physicalSizeCm == cm && Near(scale->cmPerFileUnit, s.cm) &&
                   Near(scale->cmPerUv, s.cm) && Near(scale->uvScale[0], s.cm / cm[0]) &&
                   Near(scale->uvScale[1], s.cm / cm[1]) && Near(scale->texturesPerFileUnit[0], s.cm / cm[0]) &&
                   Near(scale->texturesPerFileUnit[1], s.cm / cm[1]);
            recorded = recorded && scale->unitsFrom == s.from && scale->requestedMeshUnitScale == s.meshUnitScale &&
                       scale->unitsSource == "unspecified" && scale->textureSet == "default" &&
                       scale->sizeFrom == (transformation.scale_mode == core::ScaleMode::MaterialPhysicalSize
                                               ? "material"
                                               : "custom");
            receipts.push_back(scale->ToJson());
        }
    }
    Check(rule,
          "the same material on one mesh in two unit scales repeats by (centimetres per UV or file unit) / its "
          "physical size, MaterialPhysicalSize and CustomPhysicalSize alike",
          detail);
    // The receipts record the effective units, and they differ as the rule says.
    const auto units = [](const json::Object& receipt) { return std::get<json::Object>(receipt.at("units").data); };
    recorded = recorded && receipts.size() == 4 && units(receipts[0]).at("from") == json::Value("file") &&
               units(receipts[2]).at("from") == json::Value("mesh_unit_scale") &&
               units(receipts[0]).at("requested_mesh_unit_scale") == json::Value(nullptr) &&
               units(receipts[2]).at("requested_mesh_unit_scale") == json::Value(100.0) &&
               units(receipts[0]).at("scale_to_internal") != units(receipts[2]).at("scale_to_internal") &&
               receipts[0].at("physical_size_cm") == receipts[2].at("physical_size_cm") &&
               receipts[0].at("uv") != receipts[2].at("uv");
    Check(recorded,
          "every physical-size receipt records the effective units (source, from, requested scale, centimetres per "
          "file unit) and the size it used, and the two unit scales record different units");

    // Refusals: no physical size, a non-physical mode, an invalid custom size, a set the
    // certificate does not know, a mesh without units.
    core::UVTransformation factors;
    Check(!EvaluatePhysicalScale(factors, &felt, meshes[0], set).has_value(),
          "the Factors scale mode is refused as not a physical size");
    for (const double bad : {0.0, -5.0, std::nan("")}) {
        core::UVTransformation invalid = custom;
        invalid.scale = {bad, 10.0};
        Check(!EvaluatePhysicalScale(invalid, &felt, meshes[0], set).has_value(),
              "a CustomPhysicalSize scale of " + std::to_string(bad) + " cm is refused");
    }
    const AssetRecord* grunge = fixture->library.Find(core::ParseAssetUrl("uzasset://grunge/rock@1"));
    Check(grunge != nullptr && !EvaluatePhysicalScale(material, grunge, meshes[0], set).has_value() &&
              !EvaluatePhysicalScale(material, nullptr, meshes[0], set).has_value(),
          "MaterialPhysicalSize is refused for an asset without a physical size");
    core::TextureSet other = set;
    other.material_id = "missing";
    Check(!EvaluatePhysicalScale(material, &felt, meshes[0], other).has_value(),
          "a texture set the mesh certificate does not know is refused");
    Check(!EvaluatePhysicalScale(material, &felt, core::MeshReference{}, set).has_value(),
          "a mesh without an import report is refused");
    return Finish();
}

// ── domain (test 3.4) ────────────────────────────────────────────────────────

/// A project with one fill layer in a stack holding the six channels the materials feed; `fill`
/// receives the layer's uid.
core::Project MaterialProject(core::Id& fill) {
    core::Project project;
    project.versions.app_version = "0.0.0";
    project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    core::TextureSet set;
    set.id = project.AllocateId();
    set.name = set.original_name = set.material_id = "set";
    set.uv_tiles = {core::UVTile{project.AllocateId(), 1001, {}}};
    core::Stack stack;
    stack.id = project.AllocateId();
    stack.channels[core::ChannelType::BaseColor] = core::Channel{core::ChannelFormat::sRGB8, "", {}};
    stack.channels[core::ChannelType::Normal] = core::Channel{core::ChannelFormat::RGB16F, "", {}};
    for (const core::ChannelType mono : {core::ChannelType::Roughness, core::ChannelType::Metallic,
                                         core::ChannelType::Height, core::ChannelType::AO}) {
        stack.channels[mono] = core::Channel{core::ChannelFormat::L16, "", {}};
    }
    core::Layer layer;
    layer.uid = project.AllocateId();
    layer.kind = core::LayerKind::fill;
    layer.name = "fill";
    layer.fill = core::FillContent{};
    fill = layer.uid;
    stack.root_layers.push_back(layer);
    set.stacks.push_back(stack);
    project.texture_sets.push_back(set);
    return project;
}

/// A snapshot backend that admits every request: a stand-in for a project snapshot with the
/// request's exact signature, so that an admitted edit reaches its transaction.
class AdmitAll final : public IProceduralBackend {
public:
    std::string_view Name() const override { return "snapshot"; }
    ParityStatus Status(const core::AssetUrl&) const override { return ParityStatus::Unavailable("test"); }
    bool CanEvaluate(const ProceduralRequest&) const override { return true; }
    std::optional<UnsupportedProcedural> Refusal(const ProceduralRequest&) const override { return std::nullopt; }
    RasterFuture Evaluate(const ProceduralRequest&, const InputImages&) override {
        std::promise<render::Result<Raster>> promise;
        promise.set_value(render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "not evaluated"));
        return promise.get_future();
    }
};

int RunDomain(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterMaterialFamilies(hlsl, fixture->library)) return Finish();
    ProceduralSeam seam(nullptr, &hlsl);

    core::Id fill = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-00000000a334";
    initial.project = MaterialProject(fill);
    core::Document document(initial);
    const core::Project before = *document.snapshot().project;
    int keys = 0;
    int submits = 0;
    const SubmitEdit submit = [&](const std::function<void(core::Edit&)>& call) {
        ++submits;
        const std::string key = "material-" + std::to_string(++keys);
        return core::Execute(document,
                             core::MutationRequest{"procedural_set", json::Object{{"key", key}}, key, document.revision()},
                             call);
    };

    struct Case {
        std::string what;
        std::string field;
        std::string value;
        std::function<void(core::ProceduralRef&, UseContext&)> change;
    };
    const auto param = [](std::string name, json::Value value) {
        return [name, value](core::ProceduralRef& ref, UseContext&) { ref.params[name] = value; };
    };
    const double aboveOne = std::nextafter(1.0, 2.0);
    const double belowZero = std::nextafter(0.0, -1.0);
    const std::string hash(64, 'a');
    for (const AssetRecord* record : fixture->records) {
        const std::string name = core::FormatAssetUrl(record->asset);
        // Each material's own parameters: the last ranged one of its record, just past its top.
        std::string own;
        double top = 0.0;
        for (const auto& [p, rule] : record->domain.parameters) {
            if (rule.range && !p.starts_with("color") && !p.starts_with("rough") && p != "normal_intensity" &&
                p != "ao_intensity") {
                own = p;
                top = rule.range->second;
            }
        }
        const std::vector<Case> cases = {
            {"a parameter one ulp above its range", "params.color_variation", "", param("color_variation", aboveOne)},
            {"a parameter one ulp below its range", "params.roughness", "", param("roughness", belowZero)},
            {"the material's own parameter one ulp above its range", "params." + own, "",
             param(own, std::nextafter(top, top + 1.0))},
            {"a normal intensity above 4", "params.normal_intensity", "", param("normal_intensity", 4.000001)},
            {"a tiling of 33 repeats", "params.tiling", "33", param("tiling", int64_t{33})},
            {"a tiling of 0 repeats", "params.tiling", "0", param("tiling", int64_t{0})},
            {"a fractional tiling", "params.tiling", "2.5", param("tiling", 2.5)},
            {"an undeclared parameter", "params.scale", "", param("scale", 3.0)},
            {"a seed outside 32 bits", "seed", "4294967296",
             [](core::ProceduralRef&, UseContext& context) { context.seed = 0x100000000ull; }},
            {"a mesh class the domain does not declare", "mesh.class", "\"vehicle\"",
             [](core::ProceduralRef&, UseContext& context) { context.meshClass = "vehicle"; }},
            {"two UV tiles", "mesh.uv_tiles", "2", [](core::ProceduralRef&, UseContext& context) { context.uvTiles = 2; }},
            {"a mesh-map input, which no material reads", "inputs.AO", "present",
             [hash](core::ProceduralRef& ref, UseContext& context) {
                 ref.image_inputs["AO"] = core::ResourceBinding{hash, std::nullopt, {}};
                 context.inputs["AO"] = RasterSpec{1024, ChannelFormat::U16, "raw", 1};
             }},
            {"an output resolution of 512", "output.resolution", "512",
             [](core::ProceduralRef&, UseContext& context) { context.output.resolution = 512; }},
            {"an output resolution of 8192", "output.resolution", "8192",
             [](core::ProceduralRef&, UseContext& context) { context.output.resolution = 8192; }},
            {"an output in half floats", "output.format", "\"f16\"",
             [](core::ProceduralRef&, UseContext& context) { context.output.format = ChannelFormat::F16; }},
        };
        const auto baseline = [&]() {
            core::ProceduralRef ref;
            ref.asset = name;
            ref.output_mapping = DefaultOutputMapping(*record);
            UseContext context;
            context.meshClass = "sphere";
            context.output = RasterSpec{1024, ChannelFormat::F32, "linear", 1};
            context.seed = 42;
            return std::pair{ref, context};
        };
        for (const Case& c : cases) {
            auto [ref, context] = baseline();
            c.change(ref, context);
            const int submitted = submits;
            const auto refused = SetMaterialSource(fill, ref, context, fixture->library, seam, submit);
            const bool named = !refused && refused.error().reason == kOutsideDomain &&
                               refused.error().field == c.field && (c.value.empty() || refused.error().value == c.value);
            Check(named && submits == submitted && document.revision() == 0 && *document.snapshot().project == before,
                  "outside the domain, refused before mutation with nothing clamped: " + name + ", " + c.what,
                  refused ? "admitted" : refused.error().Describe());
            // The candidate lane refuses every channel's request: nothing is evaluated in its place.
            const auto requests = MaterialRequests(ref, context, fixture->library);
            bool none = requests.has_value() && !requests->empty();
            for (const MaterialChannelRequest& channel : requests ? *requests : std::vector<MaterialChannelRequest>{}) {
                none = none && !hlsl.EvaluateReference(channel.request, {}).has_value();
            }
            Check(none, "the candidate lane evaluates nothing: " + name + ", " + c.what);
        }
        // An output the record does not list is refused before mutation too.
        {
            auto [ref, context] = baseline();
            ref.output_mapping["BaseColor"] = "albedo";
            const auto refused = SetMaterialSource(fill, ref, context, fixture->library, seam, submit);
            Check(!refused && refused.error().reason == kOutsideDomain &&
                      refused.error().field == "output_mapping.BaseColor" && submits == 0 && document.revision() == 0,
                  "an output the material does not have is refused before mutation: " + name,
                  refused ? "admitted" : refused.error().Describe());
        }
        // Inside the domain the uncertified material is still refused before mutation.
        {
            auto [ref, context] = baseline();
            const auto refused = SetMaterialSource(fill, ref, context, fixture->library, seam, submit);
            Check(!refused && refused.error().reason == kNotCertified && submits == 0 && document.revision() == 0,
                  "inside the domain the uncertified material is refused before mutation (family not certified): " +
                      name,
                  refused ? "admitted" : refused.error().Describe());
        }
    }
    // An admitted edit (a snapshot with the exact signature) commits the reference as given, as
    // the layer's material source.
    {
        AdmitAll snapshots;
        ProceduralSeam admitting(&snapshots, &hlsl);
        const AssetRecord& felt = *fixture->records.front();
        core::ProceduralRef ref;
        ref.asset = core::FormatAssetUrl(felt.asset);
        ref.output_mapping = DefaultOutputMapping(felt);
        ref.params["tiling"] = json::Value(int64_t{6});
        UseContext context;
        context.meshClass = "sphere";
        context.output = RasterSpec{1024, ChannelFormat::F32, "linear", 1};
        const auto committed = SetMaterialSource(fill, ref, context, fixture->library, admitting, submit);
        const core::Project now = *document.snapshot().project;
        const core::Layer* layer = core::FindLayer(now, fill);
        const bool stored = layer != nullptr && layer->fill && layer->fill->source_mode == core::SourceMode::Material &&
                            layer->fill->material_source &&
                            std::get_if<core::ProceduralSource>(&layer->fill->material_source->value) != nullptr &&
                            std::get<core::ProceduralSource>(layer->fill->material_source->value).ref == ref;
        Check(committed && committed->result && committed->result->status == core::ResultStatus::committed &&
                  submits == 1 && document.revision() == 1 && stored,
              "an admitted material source commits the reference as given, every channel mapped",
              committed ? (committed->result ? committed->result->error : "not executed") : committed.error().Describe());
    }
    return Finish();
}

// ── kernels ──────────────────────────────────────────────────────────────────

int RunKernels(const fs::path& dir, const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    render::Result<std::unique_ptr<render::DxcKernelCompiler>> compiler =
        render::DxcKernelCompiler::Load(render::DefaultDxcompilerPath());
    Check(compiler.has_value(), "DXC loads", compiler ? "" : compiler.error().Describe());
    if (!compiler) return Finish();
    render::KernelCache cache(**compiler, dir / "kernel-cache");
    HlslBackend hlsl(nullptr);
    if (!RegisterMaterialFamilies(hlsl, fixture->library)) return Finish();
    bool planned = true;
    bool compiled = true;
    std::string detail;
    for (const AssetRecord* record : fixture->records) {
        for (const std::string_view output : MaterialOutputIds()) {
            auto kernels = hlsl.Kernels(Request(*record, output, 1024, 0));
            const size_t passes = output == "normal" || output == "ambient_occlusion" ? 2 : 1;
            if (!kernels || kernels->size() != passes) {
                planned = false;
                detail += core::FormatAssetUrl(record->asset) + " " + std::string(output) +
                          (kernels ? "" : ": " + kernels.error().Describe()) + "; ";
                continue;
            }
            for (const render::KernelSource& kernel : *kernels) {
                for (const render::KernelTarget target : {render::KernelTarget::Dxil, render::KernelTarget::Spirv}) {
                    render::Result<render::CompiledKernel> compiledKernel = cache.Get(kernel, target);
                    if (!compiledKernel || compiledKernel->bytecode.empty()) {
                        compiled = false;
                        detail += kernel.name + " (" + std::string(render::KernelTargetName(target)) + "): " +
                                  (compiledKernel ? "empty" : compiledKernel.error().Describe()) + "; ";
                    }
                }
            }
        }
    }
    Check(planned, "one pass planned for every single-pass output and two for the normal and the occlusion", detail);
    Check(compiled, "every material kernel compiles to DXIL and SPIR-V", detail);
    return Finish();
}

// ── gpu (test 3.3; DX12) ─────────────────────────────────────────────────────

render::Result<Raster> Get(RasterFuture& future) {
    if (future.wait_for(std::chrono::seconds(300)) != std::future_status::ready) {
        return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "no result within 300 s");
    }
    return future.get();
}

bool SameBytes(const render::Result<Raster>& a, const render::Result<Raster>& b) {
    return a && b && a->width == b->width && a->height == b->height && a->channels == b->channels &&
           a->texels.size() == b->texels.size() &&
           std::memcmp(a->texels.data(), b->texels.data(), a->texels.size() * sizeof(float)) == 0;
}

int RunGpu(const fs::path& dir, const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    render::EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    render::Engine engine(options);
    if (engine.DeviceError()) {
        std::printf("SKIP no DX12 device: %s\n", engine.DeviceError()->Describe().c_str());
        return kExitSkip;
    }
    HlslBackend hlsl(&engine);
    if (!RegisterMaterialFamilies(hlsl, fixture->library)) return Finish();
    for (const AssetRecord* record : fixture->records) {
        for (const std::string_view output : MaterialOutputIds()) {
            const std::string name = core::FormatAssetUrl(record->asset) + " " + std::string(output);
            ProceduralRequest request = With(Request(*record, output, 1024, 33410), "tiling", 3);
            request = With(request, "color_variation", 0.75);
            const render::Result<Raster> reference = hlsl.EvaluateReference(request, {});
            RasterFuture first = hlsl.EvaluateCandidate(request, {});
            const render::Result<Raster> gpu = Get(first);
            Check(reference && gpu && FirstDifference(*gpu, *reference).empty(),
                  "DX12 equals the CPU reference bit for bit over the whole 1024 texture: " + name,
                  !reference ? reference.error().Describe()
                             : (!gpu ? gpu.error().Describe() : FirstDifference(*gpu, *reference)));
            // 3.3: the same request twice gives identical bytes on DX12.
            RasterFuture second = hlsl.EvaluateCandidate(request, {});
            const render::Result<Raster> again = Get(second);
            Check(SameBytes(gpu, again), "two DX12 runs give identical bytes: " + name);
            if (output != "metallic") {
                ProceduralRequest otherSeed = request;
                otherSeed.seed = 33411;
                RasterFuture otherFuture = hlsl.EvaluateCandidate(otherSeed, {});
                const render::Result<Raster> other = Get(otherFuture);
                const size_t changed = gpu && other ? Differing(*gpu, *other) : 0;
                Check(changed > 0, "two seeds give two different textures on DX12: " + name,
                      std::to_string(changed) + " values differ");
            }
            // A tile at the border, where the two-pass outputs read across the wrap.
            ProceduralRequest corner = request;
            corner.tile = TileRect{1017, 0, 7, 33};
            const render::Result<Raster> tileReference = hlsl.EvaluateReference(corner, {});
            RasterFuture tileFuture = hlsl.EvaluateCandidate(corner, {});
            const render::Result<Raster> tile = Get(tileFuture);
            Check(tileReference && tile && FirstDifference(*tile, *tileReference).empty(),
                  "a DX12 tile at the border equals the CPU tile: " + name,
                  !tileReference ? tileReference.error().Describe()
                                 : (!tile ? tile.error().Describe() : FirstDifference(*tile, *tileReference)));
        }
    }
    return Finish();
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr, "usage: uzp-proc-material-tests library | families | tiling | physical | domain | "
                             "kernels | gpu <work-dir> "
                             "<shipped-library>\n");
        return 2;
    }
    const std::string_view mode = argv[1];
    const fs::path dir = argv[2];
    const fs::path shipped = argv[3];
    if (mode == "library") return RunLibrary(dir, shipped);
    if (mode == "families") return RunFamilies(shipped);
    if (mode == "tiling") return RunTiling(shipped);
    if (mode == "physical") return RunPhysical(shipped);
    if (mode == "domain") return RunDomain(shipped);
    if (mode == "kernels") return RunKernels(dir, shipped);
    if (mode == "gpu") return RunGpu(dir, shipped);
    std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    return 2;
}
