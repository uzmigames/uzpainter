#include "procedural/filter_gate_pins.h"

#include <stdexcept>
#include <string_view>

#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::procedural {
namespace {

using core::json::Array;
using core::json::Object;
using core::json::Value;

// The fixed request, the envelope registry and the gate's own sources, embedded at build time
// (decision 147: the build keys this object on these bytes).
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kRequest[] = {
#embed "../../parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/tier0/api-probes/filter-context-settings-a.json"
};
constexpr char kRegistry[] = {
#embed "../../parity/envelopes/registry.json"
};
constexpr char kPinsHeader[] = {
#embed "filter_gate_pins.h"
};
constexpr char kPinsSource[] = {
#embed "filter_gate_pins.cpp"
};
constexpr char kAdmissionHeader[] = {
#embed "filter_gate_admission.h"
};
constexpr char kAdmissionSource[] = {
#embed "filter_gate_admission.cpp"
};
constexpr char kSettingsHeader[] = {
#embed "filter_gate_settings.h"
};
constexpr char kSettingsSource[] = {
#embed "filter_gate_settings.cpp"
};
constexpr char kTraceHeader[] = {
#embed "filter_gate_trace.h"
};
constexpr char kTraceSource[] = {
#embed "filter_gate_trace.cpp"
};
constexpr char kDestinationHeader[] = {
#embed "filter_gate_destination.h"
};
constexpr char kDestinationSource[] = {
#embed "filter_gate_destination.cpp"
};
constexpr char kHostHeader[] = {
#embed "filter_gate_host.h"
};
constexpr char kHostSource[] = {
#embed "filter_gate_host.cpp"
};
constexpr char kImportHeader[] = {
#embed "filter_observation_import_v2.h"
};
constexpr char kImportSource[] = {
#embed "filter_observation_import_v2.cpp"
};
constexpr char kPayloadHeader[] = {
#embed "filter_gate_request.h"
};
constexpr char kPayloadSource[] = {
#embed "filter_gate_request.cpp"
};
constexpr char kCommandHeader[] = {
#embed "filter_import_cli.h"
};
constexpr char kCommandSource[] = {
#embed "filter_import_cli.cpp"
};
constexpr char kHostPolicy[] = {
#embed "../../parity/snapshot-producer-policy-v1.json"
};
#pragma clang diagnostic pop

// The approved envelope and the reviewed settings producer (decision 363; REV398 freeze).
constexpr std::string_view kEnvelopeId = "painter-12.2.0+js-api.1.1.20-env-a981b586eae7";
constexpr std::string_view kSettingsProducer = "uzp-recorder/1+src.89f3bbffae21361e";
constexpr std::string_view kProducerSourceRevision = "7c3f819cf420a1b9369882893f0950036186a491";
// Recipe A (`tools/parity/filter_context_contract.py` A_RECIPE_SHA256) and the plane input.
constexpr std::string_view kRecipeSha256 = "b7758f5b14fd4c5c06780f087dc23dee4269529c37cfc512334ebd389ed6a083";
constexpr std::string_view kPlaneSha256 = "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe";
constexpr std::string_view kGoldenId = "tier0/api-probes/filter-context-settings-a";

struct Drift {};

void Require(bool condition) {
    if (!condition) throw Drift{};
}

const Object& AsObject(const Value& value) {
    Require(value.IsObject());
    return std::get<Object>(value.data);
}

const Value& At(const Object& object, std::string_view key) {
    const auto found = object.find(key);
    Require(found != object.end());
    return found->second;
}

const std::string& StringAt(const Object& object, std::string_view key) {
    const Value& value = At(object, key);
    Require(value.IsString());
    return std::get<std::string>(value.data);
}

std::string Lf(std::string_view bytes) {
    std::string text;
    text.reserve(bytes.size());
    for (std::size_t i = 0; i < bytes.size(); ++i) {
        if (bytes[i] == '\r' && i + 1 < bytes.size() && bytes[i + 1] == '\n') continue;
        text += bytes[i];
    }
    return text;
}

}  // namespace

std::expected<FilterGatePins, ImportRefusal> CompiledFilterGatePins() {
    try {
        FilterGatePins pins;
        pins.request_bytes.assign(kRequest, sizeof(kRequest));
        const Object request = AsObject(core::json::Parse(pins.request_bytes));
        pins.golden_id = StringAt(request, "golden_id");
        Require(pins.golden_id == kGoldenId);
        pins.recipe_sha256 = core::Sha256Hex(core::json::WriteCanonical(At(request, "instruction_sequence")));
        Require(pins.recipe_sha256 == kRecipeSha256);
        const Value& inputs = At(request, "inputs");
        Require(inputs.IsArray() && std::get<Array>(inputs.data).size() == 1);
        const Object& plane = AsObject(std::get<Array>(inputs.data)[0]);
        Require(StringAt(plane, "input_id") == "plane" && StringAt(plane, "sha256") == kPlaneSha256);
        pins.plane_sha256 = std::string(kPlaneSha256);

        pins.registry_bytes.assign(kRegistry, sizeof(kRegistry));
        const Object registry = AsObject(core::json::Parse(pins.registry_bytes));
        Require(StringAt(registry, "current") == kEnvelopeId);
        const Value& envelopes = At(registry, "envelopes");
        Require(envelopes.IsArray());
        const Object* entry = nullptr;
        for (const Value& candidate : std::get<Array>(envelopes.data)) {
            const Object& object = AsObject(candidate);
            if (StringAt(object, "envelope_id") != kEnvelopeId) continue;
            Require(entry == nullptr);
            entry = &object;
        }
        Require(entry != nullptr && StringAt(*entry, "status") == "current");
        Require(core::json::WriteCanonical(At(*entry, "environment_known")) == "true");
        pins.envelope_id = std::string(kEnvelopeId);
        pins.painter_build = StringAt(*entry, "painter_build");
        pins.envelope_sha256 = StringAt(*entry, "envelope_sha256");
        Require(!pins.painter_build.empty() && core::IsSha256Hex(pins.envelope_sha256));
        const Value& equivalents = At(*entry, "equivalent_envelopes");
        Require(equivalents.IsArray());
        for (const Value& equivalent : std::get<Array>(equivalents.data)) {
            Require(equivalent.IsString() && core::IsSha256Hex(std::get<std::string>(equivalent.data)));
            pins.equivalent_envelopes.push_back(std::get<std::string>(equivalent.data));
        }
        pins.settings_producer = std::string(kSettingsProducer);
        pins.producer_source_revision = std::string(kProducerSourceRevision);
        return pins;
    } catch (const Drift&) {
    } catch (const std::exception&) {
    }
    return std::expected<FilterGatePins, ImportRefusal>(
        std::unexpect, ImportRefusal{"F_CAPTURE_INVALID", "F_SETTINGS_REGISTRY_DRIFT"});
}

std::string FilterGateCodeSha256() {
    std::string text;
    for (const std::string_view part :
         {std::string_view(kPinsHeader, sizeof(kPinsHeader)), std::string_view(kPinsSource, sizeof(kPinsSource)),
          std::string_view(kAdmissionHeader, sizeof(kAdmissionHeader)),
          std::string_view(kAdmissionSource, sizeof(kAdmissionSource)),
          std::string_view(kSettingsHeader, sizeof(kSettingsHeader)),
          std::string_view(kSettingsSource, sizeof(kSettingsSource)), std::string_view(kTraceHeader, sizeof(kTraceHeader)),
          std::string_view(kTraceSource, sizeof(kTraceSource)),
          std::string_view(kDestinationHeader, sizeof(kDestinationHeader)),
          std::string_view(kDestinationSource, sizeof(kDestinationSource)),
          std::string_view(kHostHeader, sizeof(kHostHeader)),
          std::string_view(kHostSource, sizeof(kHostSource)),
          std::string_view(kImportHeader, sizeof(kImportHeader)),
          std::string_view(kImportSource, sizeof(kImportSource)),
          std::string_view(kPayloadHeader, sizeof(kPayloadHeader)),
          std::string_view(kPayloadSource, sizeof(kPayloadSource)),
          std::string_view(kCommandHeader, sizeof(kCommandHeader)),
          std::string_view(kCommandSource, sizeof(kCommandSource)),
          std::string_view(kHostPolicy, sizeof(kHostPolicy)),
          std::string_view(kRequest, sizeof(kRequest)),
          std::string_view(kRegistry, sizeof(kRegistry))}) {
        const std::string normalized = Lf(part);
        text += core::Sha256Hex(normalized);
        text += '\n';
    }
    return core::Sha256Hex(text);
}

}  // namespace uzp::procedural
