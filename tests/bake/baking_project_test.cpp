#include "../no_error_dialogs.h"
#include "bake/baking_project.h"
#include "store/project_store.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

namespace {
using namespace uzp::bake;
using namespace uzp::core;
using MeshMapUsage = uzp::bake::MeshMapUsage;
using uzp::store::ProjectStore;

#define CHECK(x) do { if (!(x)) throw std::runtime_error("line " + std::to_string(__LINE__) + ": " #x); } while (false)

template <typename F> void Refuses(F&& call) {
    bool caught = false;
    try { call(); } catch (const ValueError&) { caught = true; }
    CHECK(caught);
}

Project Fixture() {
    Project project;
    project.versions.app_version = "0.0.0";
    project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    for (const char* name : {"a", "b", "c"}) {
        TextureSet set;
        set.id = project.AllocateId();
        set.name = set.original_name = set.material_id = name;
        set.uv_tiles = {UVTile{project.AllocateId(), 1001, {}}};
        Stack stack;
        stack.id = project.AllocateId();
        stack.channels[ChannelType::BaseColor] = Channel{ChannelFormat::sRGB8, "", {}};
        set.stacks.push_back(stack);
        set.bake_settings.extra["extension"] = json::Object{{"retained", name}};
        project.texture_sets.push_back(set);
    }
    return project;
}

DocumentState State(Project project = Fixture()) {
    DocumentState state;
    state.project_uuid = "6f1c2a3e-0000-4000-8000-0000000000bc";
    state.project = std::move(project);
    return state;
}

MutationRequest Request(const char* key, std::int64_t revision) {
    return {"bake_configure", json::Object{{"key", key}}, key, revision};
}

void Configure(BakingSession& session) {
    const auto a = session.parameters("a");
    BakingParameters::set({{a.common().at("OutputSize"), std::pair<std::int64_t, std::int64_t>{10, 11}},
                           {a.common().at("HipolySuffix"), std::string("_hi")},
                           {a.baker(MeshMapUsage::AO).at("GroundPlane"), true}});
    session.set_linked_group({"a", "c"}, "a", MeshMapUsage::AO);
}

void CheckConfigured(const BakingSession& session) {
    CHECK((session.get_link_group_common_parameters() == std::vector<std::string>{"a", "b", "c"}));
    CHECK((session.get_link_group(MeshMapUsage::AO) == std::vector<std::string>{"a", "c"}));
    const auto b = ToBakeSettings(session.parameters("b"));
    CHECK((b.common.at("OutputSize") == json::Value(json::Array{std::int64_t{10}, std::int64_t{11}})));
    CHECK(b.detail.at("HipolySuffix") == json::Value("_hi"));
    CHECK(std::get<bool>(session.parameters("c").baker(MeshMapUsage::AO).at("GroundPlane").value()));
}

void Roundtrip(const std::filesystem::path& directory) {
    const auto path = directory / "baking.uzp";
    const auto initial = State();
    {
        auto store = ProjectStore::Create(path, initial);
        Document document(initial);
        store->Attach(document);
        const auto outcome = store->Submit(document, Request("configure", 0), [](Edit& edit) {
            EditBakingSession(edit, Configure);
        });
        CHECK(outcome.result->status == ResultStatus::committed);
        CHECK(outcome.result->changes.modified.size() == 3);
        CHECK(document.revision() == 1);
        CheckConfigured(LoadBakingSession(*document.snapshot().project));
        store->Save(document);
        store->Close();
    }
    auto reopened = ProjectStore::Open(path);
    Document document(std::move(reopened.state));
    reopened.store->Attach(document);
    CHECK(!document.NeedsSaving());
    CheckConfigured(LoadBakingSession(*document.snapshot().project));
    const auto before = *document.snapshot().project;
    for (std::size_t i = 0; i < before.texture_sets.size(); ++i)
        CHECK(before.texture_sets[i].bake_settings.extra.at("extension") ==
              initial.project.texture_sets[i].bake_settings.extra.at("extension"));
    // Rename/reorder changes names and query order, never persistent group membership.
    auto changed = before;
    changed.texture_sets[0].name = "renamed";
    std::reverse(changed.texture_sets.begin(), changed.texture_sets.end());
    const auto renamed = LoadBakingSession(changed);
    CHECK((renamed.get_link_group(MeshMapUsage::AO) == std::vector<std::string>{"c", "renamed"}));
    StoreBakingSession(renamed, changed);
    CHECK(changed.texture_sets[0].bake_settings.extra.at("linked_groups") ==
          before.texture_sets[2].bake_settings.extra.at("linked_groups"));
    const auto renamedPath = directory / "renamed.uzp";
    {
        const auto state = State(changed);
        auto store = ProjectStore::Create(renamedPath, state);
        Document renamedDocument(state);
        store->Attach(renamedDocument);
        store->Save(renamedDocument);
        store->Close();
    }
    {
        auto opened = ProjectStore::Open(renamedPath);
        const auto durable = LoadBakingSession(opened.state.project);
        CHECK((durable.get_link_group(MeshMapUsage::AO) == std::vector<std::string>{"c", "renamed"}));
        CHECK(std::get<bool>(durable.parameters("renamed").baker(MeshMapUsage::AO).at("GroundPlane").value()));
        opened.store->Close();
    }
    const auto unlink = reopened.store->Submit(document, Request("unlink", 1), [](Edit& edit) {
        EditBakingSession(edit, [](BakingSession& session) {
            session.unlink_all_common_parameters();
            session.unlink_all(MeshMapUsage::AO);
            BakingParameters::set({{session.parameters("b").common().at("HipolySuffix"), std::string("_b")}});
        });
    });
    CHECK(unlink.result->status == ResultStatus::committed);
    reopened.store->Save(document);
    reopened.store->Close();
    auto again = ProjectStore::Open(path);
    const auto unlinked = LoadBakingSession(again.state.project);
    CHECK(unlinked.get_link_group_common_parameters().empty());
    CHECK(unlinked.get_link_group(MeshMapUsage::AO).empty());
    CHECK(ToBakeSettings(unlinked.parameters("a")).detail.at("HipolySuffix") == json::Value("_hi"));
    CHECK(ToBakeSettings(unlinked.parameters("b")).detail.at("HipolySuffix") == json::Value("_b"));
    auto resaved = again.state.project;
    StoreBakingSession(unlinked, resaved);
    CHECK(resaved == again.state.project);
    again.store->Close();
}

void Transactions() {
    Document document(State());
    const Project legacy = *document.snapshot().project;
    const auto noop = ExecuteBakingSession(document, Request("noop", 0), [](BakingSession&) {});
    CHECK(noop.result->status == ResultStatus::no_op);
    CHECK(*document.snapshot().project == legacy && document.revision() == 0);
    int calls = 0;
    const auto configure = [&](BakingSession& session) { ++calls; Configure(session); };
    const auto success = ExecuteBakingSession(document, Request("set", 0), configure);
    CHECK(success.result->status == ResultStatus::committed && calls == 1);
    const auto replay = ExecuteBakingSession(document, Request("set", 0), configure);
    CHECK(replay.decision.admission == Admission::stored_outcome && calls == 1);
    const auto stale = ExecuteBakingSession(document, Request("stale", 0), configure);
    CHECK(stale.decision.admission == Admission::stale_revision && calls == 1);
    auto conflict_request = Request("set", 1);
    conflict_request.arguments["different"] = true;
    const auto conflict = ExecuteBakingSession(document, conflict_request, configure);
    CHECK(conflict.decision.admission == Admission::idempotency_conflict && calls == 1);
    const auto saved = document.snapshot();
    const auto operations = document.operations();
    const auto failed = ExecuteBakingSession(document, Request("invalid", 1), [](BakingSession& session) {
        session.unlink_all_common_parameters();
        BakingParameters::set({{session.parameters("a").common().at("DilationWidth"), std::int64_t{3}},
                               {session.parameters("b").common().at("IgnoreBackface"), std::int64_t{1}}});
    });
    CHECK(failed.result->status == ResultStatus::failed);
    CHECK(document.snapshot().project == saved.project && document.revision() == saved.revision);
    document.SetCommitSink([](const Snapshot&, const OperationRecord&) { throw std::runtime_error("sink fault"); });
    const auto sink = ExecuteBakingSession(document, Request("sink", 1), [](BakingSession& session) {
        session.unlink_all(MeshMapUsage::AO);
    });
    CHECK(sink.result->status == ResultStatus::failed);
    CHECK(document.snapshot().project == saved.project && document.operations() == operations);
    CheckConfigured(LoadBakingSession(*document.snapshot().project));
}

void Invalid() {
    Project project = Fixture();
    auto session = LoadBakingSession(project);
    Configure(session);
    StoreBakingSession(session, project);
    const Project valid = project;
    auto reject = [&](const std::function<void(Project&)>& corrupt) {
        Project bad = valid;
        corrupt(bad);
        const Project before = bad;
        Refuses([&] { (void)LoadBakingSession(bad); });
        CHECK(bad == before);
    };
    reject([](Project& p) { p.texture_sets[0].bake_settings.extra.erase("linked_groups"); });
    reject([](Project& p) { p.texture_sets[0].bake_settings.common["OutputSize"] = true; });
    reject([](Project& p) { p.texture_sets[0].bake_settings.detail["HipolySuffix"] = "conflict"; });
    reject([](Project& p) { p.texture_sets[2].bake_settings.per_baker["AO"]["GroundPlane"] = false; });
    for (const json::Value& common : {json::Value(true), json::Value(json::Array{std::int64_t{999}}),
                                     json::Value(json::Array{std::int64_t{1}, std::int64_t{1}}),
                                     json::Value(json::Array{std::int64_t{1}}),
                                     json::Value(json::Array{"1", "4"})}) {
        reject([&](Project& p) {
            for (auto& set : p.texture_sets)
                set.bake_settings.extra["linked_groups"] = json::Object{{"common", common}, {"per_baker", json::Object{}}};
        });
    }
    reject([](Project& p) {
        for (auto& set : p.texture_sets)
            set.bake_settings.extra["linked_groups"] = json::Object{{"common", json::Array{}},
                {"per_baker", json::Object{}}, {"unknown", true}};
    });
    reject([](Project& p) {
        for (auto& set : p.texture_sets)
            set.bake_settings.extra["linked_groups"] = json::Object{{"common", json::Array{}},
                {"per_baker", json::Object{{"Normal", json::Array{std::int64_t{1}, std::int64_t{4}}}}}};
    });
    Project legacy = Fixture();
    legacy.texture_sets[0].bake_settings.common["DilationWidth"] = std::int64_t{2};
    Refuses([&] { (void)LoadBakingSession(legacy); });
    BakingSession wrong({"a", "b"});
    Refuses([&] { StoreBakingSession(wrong, project); });
    CHECK(project == valid);
    Project unsupported = valid;
    unsupported.texture_sets[0].bake_settings.common["Unknown"] = true;
    const Project untouched = unsupported;
    Refuses([&] { StoreBakingSession(session, unsupported); });
    CHECK(unsupported == untouched);
    // Fresh loads do not alias either earlier sessions or the document.
    auto second = LoadBakingSession(project);
    second.unlink_all_common_parameters();
    BakingParameters::set({{second.parameters("a").common().at("DilationWidth"), std::int64_t{9}}});
    CheckConfigured(session);
    CHECK(project == valid);
}

// The model's metadata and defaults as the authored table lays them out
// (`tools.bake.bake_defaults.check_model` compares the two; decision 323).
json::Value Plain(const PropertySpec& spec, const PropertyValue& value) {
    if (const auto* b = std::get_if<bool>(&value)) return *b;
    if (const auto* i = std::get_if<std::int64_t>(&value)) return *i;
    if (const auto* d = std::get_if<double>(&value)) return *d;
    if (const auto* s = std::get_if<std::string>(&value)) return *s;
    if (const auto* p = std::get_if<std::pair<std::int64_t, std::int64_t>>(&value)) return json::Array{p->first, p->second};
    if (const auto* f = std::get_if<std::pair<double, double>>(&value)) return json::Array{f->first, f->second};
    const std::string& label = std::get<EnumLabel>(value).label;
    for (const auto& [known, integer] : spec.enum_values) {
        if (known == label) return std::int64_t{integer};
    }
    throw std::runtime_error("no enum value " + label);
}

json::Array Dump(const std::map<std::string, Property>& properties) {
    json::Array out;
    for (const auto& [key, property] : properties) {
        const PropertySpec& spec = property.spec();
        json::Object entry{{"short_name", property.short_name()},  {"name", property.name()},
                           {"label", property.label()},            {"widget_type", property.widget_type()},
                           {"type", PropertyTypeName(property.type())}};
        if (property.type() == PropertyType::Enum) {
            json::Object values;
            for (const auto& [label, integer] : property.enum_values()) {
                CHECK(property.enum_value(label) == integer);
                values[label] = std::int64_t{integer};
            }
            entry["enum_values"] = std::move(values);
        }
        json::Object range;
        if (spec.minimum) range["min"] = Plain(spec, *spec.minimum);
        if (spec.maximum) range["max"] = Plain(spec, *spec.maximum);
        if (!range.empty()) entry["range"] = std::move(range);
        try {
            entry["default"] = Plain(spec, property.value());
        } catch (const NotYetSupported&) {
            entry["default"] = nullptr;
        }
        out.push_back(std::move(entry));
    }
    return out;
}

void Catalog(const std::filesystem::path& out) {
    const BakingParameters parameters("catalog");
    json::Object bakers;
    for (int u = 0; u <= static_cast<int>(MeshMapUsage::Opacity); ++u) {
        const auto usage = static_cast<MeshMapUsage>(u);
        bakers[UsageName(usage)] = Dump(parameters.baker(usage));
    }
    const TextureSetBakeState& state = DefaultTextureSetState();
    json::Array enabled;
    for (const std::string& baker : state.enabled_bakers) enabled.push_back(baker);
    const json::Object dump{{"common", Dump(parameters.common())},
                            {"bakers", std::move(bakers)},
                            {"texture_set_state", json::Object{{"curvature_method", state.curvature_method},
                                                               {"enabled_bakers", std::move(enabled)},
                                                               {"textureset_enabled", state.textureset_enabled}}}};
    std::ofstream file(out, std::ios::binary);
    file << json::WriteCanonical(dump);
    CHECK(file.good());
}
}  // namespace

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    try {
        const std::string name = argv[1];
        if (name == "roundtrip") Roundtrip(argv[2]);
        else if (name == "transactions") Transactions();
        else if (name == "invalid") Invalid();
        else if (name == "catalog") Catalog(argv[2]);
        else return 2;
        std::printf("PASS %s\n", name.c_str());
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
