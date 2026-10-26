// Differential authored traces; every token comes through real C1/C2 admission.
#include <fstream>
#include <iostream>
#include <iterator>
#include <type_traits>

#include "filter_gate_test_support.h"
#include "procedural/filter_gate_settings.h"
#include "procedural/filter_gate_trace.h"

static_assert(!std::is_default_constructible_v<uzp::procedural::ValidatedFilterTrace>);

namespace {
std::string Read(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    uzp::filter_gate_test::Require(bool(file), "authored trace fixture present");
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}
}

int RunFilterGateTraceCases(const std::filesystem::path& work) {
    using namespace uzp;
    using namespace uzp::filter_gate_test;
    const auto scenarios = std::get<json::Array>(json::Parse(Read(work / "trace-records.json")).data);
    const auto png = Read(work / "trace-panel.png");
    json::Array results;
    int checks = 0;
    for (const auto& scenario : scenarios) {
        const auto& input = std::get<json::Object>(scenario.data);
        const auto name = std::get<std::string>(input.at("name").data);
        Capture capture;
        capture.record = std::get<json::Object>(input.at("record").data);
        capture.record["environment"] = capture.environment;
        for (auto& [id, bytes] : capture.images) bytes = png;
        capture.Reference();
        auto admitted = AdmitAuthored(capture, work / (name + "-store"), work / (name + "-registry.json"));
        json::Object result{{"name", name}, {"accepted", false}, {"stage", "admission"}};
        if (admitted) {
            auto panels = procedural::CheckFilterSettingsPanels(*admitted);
            result["stage"] = "panels";
            if (panels) {
                auto trace = procedural::ValidateFilterTrace(*admitted, *panels);
                result["stage"] = "trace";
                if (trace) {
                    result["accepted"] = true;
                    result["rounds"] = trace->Rounds();
                    Require(trace->Contexts().size() == 5 && trace->InitialPaintUid() > 0, "five frames and initial Paint UID");
                    Require(trace->OriginalRecordSha256() == panels->OriginalRecordSha256(), "original record remains bound");
                    if (name == "baseline") {
                        Capture alternate = capture;
                        alternate.manifest_text = " \n" + json::WriteCanonical(alternate.manifest);
                        auto other = AdmitAuthored(alternate, work / "alternate-store", work / "alternate-registry.json");
                        Require(other.has_value(), "alternate raw manifest admits");
                        auto mixed = procedural::ValidateFilterTrace(*other, *panels);
                        Require(!mixed && mixed.error().detail == "F_SETTINGS_CAPTURE_BINDING", "full admission identity prevents mixed panels");
                        ++checks;
                    }
                }
            }
        }
        results.push_back(std::move(result));
        ++checks;
    }
    std::cout << "FILTER_GATE_TRACE: " << json::WriteCanonical(json::Object{{"checks", checks}, {"results", results}}) << '\n';
    return 0;
}
