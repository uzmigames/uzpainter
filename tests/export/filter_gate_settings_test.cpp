// Authored settings evidence through the real C1/C2/C3 boundaries; no private
// oracle.
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>

#include "filter_gate_test_support.h"
#include "procedural/filter_gate_settings.h"
#include "procedural/filter_gate_trace.h"

namespace {
using namespace uzp;
using namespace uzp::filter_gate_test;

std::string Read(const fs::path &path) {
    std::ifstream file(path, std::ios::binary);
    Require(bool(file), "authored fixture is present");
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

json::Object &PanelAt(Capture &c, std::size_t index = 0) {
    for (auto &r : Arr(c.record, "recordings"))
        for (auto &output : Arr(Obj(r), "outputs")) {
            auto &o = Obj(output);
            if (std::get<std::string>(o.at("kind").data) == "settings_panel_readback") {
                if (index-- == 0)
                    return Obj(o, "values");
            }
        }
    throw std::runtime_error("authored panel missing");
}

void Image(Capture &c, const std::string &bytes) {
    for (auto &[id, data] : c.images)
        data = bytes;
    for (auto &r : Arr(c.record, "recordings"))
        for (auto &output : Arr(Obj(r), "outputs")) {
            auto &o = Obj(output);
            if (std::get<std::string>(o.at("kind").data) == "settings_panel_evidence") {
                auto &blob = Obj(o, "blob");
                blob["sha256"] = core::Sha256Hex(bytes);
                blob["size_bytes"] = static_cast<std::uint64_t>(bytes.size());
            }
        }
}

void MeshPaths(Capture &c, const std::string &imported, const std::string &panel_path) {
    for (auto &r : Arr(c.record, "recordings")) {
        json::Array frame;
        for (auto &value : Arr(Obj(r), "outputs")) {
            auto &output = Obj(value);
            const auto &id = std::get<std::string>(output.at("output_id").data);
            if (id.starts_with("context/")) {
                if (output.at("call") == json::Value("substance_painter.project.last_imported_mesh_path"))
                    output["value"] = imported;
                frame.push_back(value);
            } else if (output.at("kind") == json::Value("settings_panel_readback")) {
                auto &panel = Obj(output, "values");
                Obj(panel, "mesh_import")["resolved_path"] = panel_path;
                auto &binding = Obj(panel, "binding");
                binding["context_after_outputs"] = frame;
                binding["context_before_sha256"] = core::Sha256Hex(json::WriteCanonical(frame));
                binding["context_after_sha256"] = binding["context_before_sha256"];
                frame.clear();
            }
        }
    }
}
} // namespace

int RunFilterGateSettingsCases(const std::filesystem::path &work) {
    using namespace uzp;
    using namespace uzp::filter_gate_test;
    Capture base;
    base.record = std::get<json::Object>(json::Parse(Read(work / "settings-record.json")).data);
    base.record["environment"] = base.environment;
    Image(base, Read(work / "settings-valid.png"));
    base.Reference();
    int checks = 0;
    const auto admit = [&](Capture c) {
        c.Reference();
        auto admitted = AdmitAuthored(c, work / ("store-" + std::to_string(checks)),
                                      work / ("registry-" + std::to_string(checks) + ".json"));
        Require(admitted.has_value(), admitted ? "" : admitted.error().detail);
        return *admitted;
    };
    auto original = admit(base);
    auto panels = procedural::CheckFilterSettingsPanels(original);
    Require(panels.has_value(), panels ? "" : panels.error().detail);
    ++checks;
    auto trace = procedural::ValidateFilterTrace(original, *panels);
    Require(trace.has_value(), trace ? "" : trace.error().detail);
    ++checks;
    auto settings = procedural::DeriveFilterSettings(original, *panels, *trace);
    Require(settings && settings->TangentSpace() == "PerVertex" && settings->Workflow() == "Default" &&
                settings->EffectiveCmPerUnit() == 1 &&
                settings->ProvenanceBasis() == "unitless-obj-internal-centimetres-v1",
            "derive target settings");
    ++checks;
    Require(json::WriteCanonical(panels->StrippedRecord().at("key")) ==
                    json::WriteCanonical(original.Record().at("key")) &&
                json::WriteCanonical(panels->StrippedRecord().at("golden_id")) ==
                    json::WriteCanonical(original.Record().at("golden_id")),
            "preserve original key and golden");
    ++checks;
    std::size_t removed = 0;
    const auto &old_rounds = std::get<json::Array>(original.Record().at("recordings").data);
    const auto &new_rounds = std::get<json::Array>(panels->StrippedRecord().at("recordings").data);
    for (std::size_t i = 0; i < 2; ++i)
        removed +=
            std::get<json::Array>(std::get<json::Object>(old_rounds[i].data).at("outputs").data).size() -
            std::get<json::Array>(std::get<json::Object>(new_rounds[i].data).at("outputs").data).size();
    Require(removed == 15, "remove exactly fifteen settings slots");
    ++checks;
    Require(panels->OriginalRecordSha256() == core::Sha256Hex(json::WriteCanonical(base.record)),
            "retain raw original record hash");
    ++checks;
    for (const auto &[readback, panel_path] : std::vector<std::pair<std::string, std::string>>{
             {"c:/authored-input/./PLANE.OBJ", "C:\\authored-input\\plane.obj"},
             {"C:/STRASSE/plane.obj", "c:/Stra\xc3\x9f"
                                      "e/PLANE.OBJ"},
             {"\\\\SERVER\\share\\PLANE.OBJ", "//server/share/plane.obj"},
             {"1:/plane.obj", "1:/plane.obj"},
             {"//../share/plane.obj", "//../share/plane.obj"},
             {"C:/..obj", "C:/..obj"},
             {"//?/UNC/server/share/plane.obj", "//?/UNC/server/share/plane.obj"},
             {"\xc3\x9f:/plane.obj", "\xc3\x9f:/plane.obj"}}) {
        Capture c = base;
        MeshPaths(c, readback, panel_path);
        auto capture = admit(c);
        Require(procedural::CheckFilterSettingsPanels(capture).has_value(),
                "Windows path normalization and full Unicode casefold");
        ++checks;
    }
    const auto refuses = [&](std::string_view name, const std::function<void(Capture &)> &mutate) {
        Capture c = base;
        mutate(c);
        auto capture = admit(c);
        auto result = procedural::CheckFilterSettingsPanels(capture);
        Require(!result && result.error().reason == procedural::kFilterCaptureInvalid, std::string(name));
        ++checks;
    };
    refuses("panel fields closed", [](Capture &c) { PanelAt(c)["extra"] = true; });
    refuses("before after identity", [](Capture &c) { Obj(Obj(PanelAt(c), "binding"), "after")["pid"] = 1; });
    refuses("boolean PID", [](Capture &c) { Obj(Obj(PanelAt(c), "binding"), "before")["pid"] = true; });
    refuses("context hash",
            [](Capture &c) { Obj(PanelAt(c), "binding")["context_before_sha256"] = std::string(64, '0'); });
    refuses("wrong mesh", [](Capture &c) {
        Obj(Obj(PanelAt(c), "mesh_import"), "before")["sha256"] = std::string(64, '0');
    });
    refuses("mesh parent traversal",
            [](Capture &c) { Obj(PanelAt(c), "mesh_import")["resolved_path"] = "C:\\root\\..\\plane.obj"; });
    refuses("relative mesh",
            [](Capture &c) { Obj(PanelAt(c), "mesh_import")["resolved_path"] = "plane.obj"; });
    refuses("lowercase extension without stem",
            [](Capture &c) { Obj(PanelAt(c), "mesh_import")["resolved_path"] = "C:/.obj"; });
    refuses("uppercase extension without stem",
            [](Capture &c) { Obj(PanelAt(c), "mesh_import")["resolved_path"] = "C:/.OBJ"; });
    refuses("dialog owner",
            [](Capture &c) { Obj(Obj(Obj(PanelAt(c), "ui"), "configuration"), "dialog")["pid"] = 1; });
    refuses("duplicate selector before visibility", [](Capture &c) {
        auto &values = Arr(Obj(Obj(PanelAt(c), "ui"), "configuration"), "values");
        auto copy = values[0];
        Obj(copy)["visible"] = false;
        values.push_back(copy);
    });
    refuses("boolean target", [](Capture &c) {
        auto &values = Arr(Obj(Obj(PanelAt(c), "ui"), "configuration"), "values");
        Obj(values[0])["toggle"] = false;
    });
    refuses("unavailable target", [](Capture &c) {
        auto &values = Arr(Obj(Obj(PanelAt(c), "ui"), "configuration"), "values");
        Obj(values[0])["toggle"] = json::Object{{"unavailable", "authored"}};
    });
    refuses("incomplete tree", [](Capture &c) {
        auto &tree = Arr(Obj(Obj(PanelAt(c), "ui"), "configuration"), "tree");
        Obj(tree[0])["children_error"] = "authored";
    });
    refuses("image dialog binding", [](Capture &c) { Obj(Arr(PanelAt(c), "images")[0])["hwnd"] = 1; });
    refuses("panel session drift", [](Capture &c) {
        for (auto side : {"before", "after"})
            Obj(Obj(PanelAt(c, 4), "binding"), side)["started"] = "other";
    });
    refuses("image ref join", [](Capture &c) {
        for (auto &r : Arr(c.record, "recordings"))
            for (auto &v : Arr(Obj(r), "outputs")) {
                auto &o = Obj(v);
                if (o.at("kind") == json::Value("settings_panel_evidence")) {
                    Obj(o, "blob")["sha256"] = std::string(64, '0');
                    return;
                }
            }
    });
    for (auto file : {"truncated", "ancillary-crc", "trailing", "missing-adler", "over-width", "over-height",
                      "chunk-limit", "ancillary-limit", "idat-trailing", "extra-scanline", "invalid-filter",
                      "missing-scanline"}) {
        const auto bytes = Read(work / (std::string("settings-") + file + ".png"));
        Require(procedural::ValidateFilterSettingsImage(bytes).has_value(), file);
        ++checks;
    }
    for (auto file : {"valid", "width-edge", "height-edge", "decoded-edge", "chunk-edge", "empty-idat",
                      "split-idat", "adam7-one", "adam7-small", "adam7-palette", "adam7-gray", "gray-four",
                      "rgba-sixteen", "rgb-eight", "gray-alpha", "adam7-sixteen"}) {
        const auto bytes = Read(work / (std::string("settings-") + file + ".png"));
        Require(!procedural::ValidateFilterSettingsImage(bytes).has_value(), file);
        ++checks;
    }
    {
        Capture other = base;
        // Same record bytes, different manifest serialization: admission identities
        // must not mix.
        other.Reference();
        other.manifest_text = " \n" + json::WriteCanonical(other.manifest);
        auto capture = admit(other);
        auto mixed = procedural::DeriveFilterSettings(capture, *panels, *trace);
        Require(!mixed, "different admission manifest cannot reuse settings/trace");
        ++checks;
    }
    std::cout << "FILTER_GATE_SETTINGS: " << json::WriteCanonical(json::Object{{"checks", checks}}) << "\n";
    return 0;
}
