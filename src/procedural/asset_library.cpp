#include "procedural/asset_library.h"

#include "render/kernel_cache.h"

#include "uzp_core/document/nodes.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <regex>
#include <set>
#include <sstream>
#include <tuple>

namespace uzp::procedural {

namespace json = core::json;
namespace fs = std::filesystem;

namespace {

// Zig's libc++ also declares the pre-C++17 `std::unexpected()`, so the bare name is ambiguous
// (seam.h `Refused`): the error types are named through `std::expected`.
using SearchError = std::expected<void, SearchRefusal>::unexpected_type;
using LoadFailure = std::expected<void, std::string>::unexpected_type;
using ResolveError = std::expected<void, UnsupportedProcedural>::unexpected_type;

/// A refusal of the library load: the file and the reason.
struct LoadError {
    std::string message;
};

[[noreturn]] void Fail(const fs::path& file, const std::string& reason) {
    throw LoadError{file.generic_string() + ": " + reason};
}

const json::Value* Member(const json::Object& object, std::string_view key) {
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &it->second;
}

const json::Object& ObjectOf(const json::Value& value, const fs::path& file, const std::string& where) {
    if (!value.IsObject()) Fail(file, where + " is not an object");
    return std::get<json::Object>(value.data);
}

const json::Array& ArrayOf(const json::Value& value, const fs::path& file, const std::string& where) {
    if (!value.IsArray()) Fail(file, where + " is not a list");
    return std::get<json::Array>(value.data);
}

const std::string& StringOf(const json::Value& value, const fs::path& file, const std::string& where) {
    if (!value.IsString() || std::get<std::string>(value.data).empty()) {
        Fail(file, where + " is not a non-empty string");
    }
    return std::get<std::string>(value.data);
}

const json::Value& Required(const json::Object& object, std::string_view key, const fs::path& file,
                            const std::string& where) {
    const json::Value* value = Member(object, key);
    if (value == nullptr) Fail(file, where + " has no " + std::string(key));
    return *value;
}

/// Refuses a member outside `allowed`: a record carries only what the schema names.
void OnlyKeys(const json::Object& object, std::initializer_list<std::string_view> allowed,
              const fs::path& file, const std::string& where) {
    for (const auto& [key, value] : object) {
        if (std::find(allowed.begin(), allowed.end(), key) == allowed.end()) {
            Fail(file, where + " has an unknown member " + key);
        }
    }
}

json::Value ReadJson(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream) Fail(file, "cannot be read");
    std::ostringstream text;
    text << stream.rdbuf();
    try {
        return json::Parse(text.str());
    } catch (const json::ParseError& error) {
        Fail(file, std::string("is not JSON: ") + error.what());
    }
}

/// Library defaults and explicit domain sets use the same typed values as project requests.
std::optional<ParamValue> ParamOf(const json::Value& value) {
    const auto parsed = ParamFromJson(value);
    if (parsed) return *parsed;
    return std::nullopt;
}

double NumberOf(const json::Value& value) {
    return value.IsInt() ? static_cast<double>(std::get<int64_t>(value.data)) : std::get<double>(value.data);
}

std::optional<ChannelFormat> FormatOf(std::string_view name) {
    if (name == "u8") return ChannelFormat::U8;
    if (name == "u16") return ChannelFormat::U16;
    if (name == "f16") return ChannelFormat::F16;
    if (name == "f32") return ChannelFormat::F32;
    return std::nullopt;
}

/// A domain problem (`ParseDomain` reports it as text).
struct DomainError {
    std::string message;
};

[[noreturn]] void Bad(const std::string& message) { throw DomainError{message}; }

const json::Object& DomainObject(const json::Value& value, const std::string& where) {
    if (!value.IsObject()) Bad(where + ": not an object");
    return std::get<json::Object>(value.data);
}

const json::Array& DomainArray(const json::Object& object, std::string_view key, const std::string& where) {
    const json::Value* value = Member(object, key);
    if (value == nullptr || !value->IsArray()) Bad(where + "." + std::string(key) + ": not a list");
    return std::get<json::Array>(value->data);
}

uint32_t Positive(const json::Value& value, const std::string& where, uint32_t max) {
    if (!value.IsInt() || std::get<int64_t>(value.data) < 1 || std::get<int64_t>(value.data) > max) {
        Bad(where + ": an integer in [1, " + std::to_string(max) + "]");
    }
    return static_cast<uint32_t>(std::get<int64_t>(value.data));
}

RasterRule RuleOf(const json::Value& value, const std::string& where) {
    const json::Object& object = DomainObject(value, where);
    RasterRule rule;
    for (const json::Value& r : DomainArray(object, "resolutions", where)) {
        rule.resolutions.push_back(Positive(r, where + ".resolutions", 1u << 16));
    }
    for (const json::Value& f : DomainArray(object, "formats", where)) {
        const std::optional<ChannelFormat> format = f.IsString() ? FormatOf(std::get<std::string>(f.data)) : std::nullopt;
        if (!format) Bad(where + ".formats: u8, u16, f16 or f32");
        rule.formats.push_back(*format);
    }
    for (const json::Value& s : DomainArray(object, "colour_spaces", where)) {
        if (!s.IsString() || std::get<std::string>(s.data).empty()) Bad(where + ".colour_spaces: names");
        rule.colourSpaces.push_back(std::get<std::string>(s.data));
    }
    for (const json::Value& c : DomainArray(object, "channels", where)) {
        rule.channels.push_back(Positive(c, where + ".channels", 4));
    }
    return rule;
}

CertifiedDomain DomainOf(const json::Value& document) {
    const json::Object& object = DomainObject(document, "domain");
    CertifiedDomain domain;
    const json::Value* parameters = Member(object, "parameters");
    if (parameters == nullptr) Bad("domain.parameters: missing");
    for (const auto& [name, rule] : DomainObject(*parameters, "domain.parameters")) {
        const json::Object& entry = DomainObject(rule, "domain.parameters." + name);
        if (entry.size() != 1) Bad("domain.parameters." + name + ": one of range or set");
        ParamRule parsed;
        if (const json::Value* range = Member(entry, "range")) {
            if (!range->IsArray() || std::get<json::Array>(range->data).size() != 2) {
                Bad("domain " + name + ": range [low, high]");
            }
            const json::Array& ends = std::get<json::Array>(range->data);
            if (!ends[0].IsNumber() || !ends[1].IsNumber() || !(NumberOf(ends[0]) < NumberOf(ends[1]))) {
                Bad("domain " + name + ": range [low, high] with low < high");
            }
            parsed.range = std::pair{NumberOf(ends[0]), NumberOf(ends[1])};
        } else if (const json::Value* set = Member(entry, "set")) {
            if (!set->IsArray() || std::get<json::Array>(set->data).empty()) Bad("domain " + name + ": a set");
            for (const json::Value& v : std::get<json::Array>(set->data)) {
                const std::optional<ParamValue> value = ParamOf(v);
                if (!value) Bad("domain " + name + ": invalid typed parameter in set");
                parsed.set.push_back(*value);
            }
        } else {
            Bad("domain.parameters." + name + ": one of range or set");
        }
        domain.parameters[name] = std::move(parsed);
    }
    if (const json::Value* constraints = Member(object, "constraints")) {
        if (!constraints->IsArray()) Bad("domain.constraints: not a list");
        for (const json::Value& c : std::get<json::Array>(constraints->data)) {
            const json::Object& entry = DomainObject(c, "domain constraint");
            const json::Value* coefficients = Member(entry, "coefficients");
            const json::Value* max = Member(entry, "max");
            if (coefficients == nullptr || !coefficients->IsObject() || max == nullptr || !max->IsNumber()) {
                Bad("domain constraint: coefficients over ranged parameters and a max");
            }
            LinearConstraint constraint;
            for (const auto& [name, coefficient] : std::get<json::Object>(coefficients->data)) {
                const auto it = domain.parameters.find(name);
                if (it == domain.parameters.end() || !it->second.range || !coefficient.IsNumber()) {
                    Bad("domain constraint: coefficients over ranged parameters and a max");
                }
                constraint.coefficients[name] = NumberOf(coefficient);
            }
            constraint.max = NumberOf(*max);
            domain.constraints.push_back(std::move(constraint));
        }
    }
    if (const json::Value* presets = Member(object, "presets")) {
        if (!presets->IsArray()) Bad("domain.presets: not a list");
        for (const json::Value& p : std::get<json::Array>(presets->data)) {
            if (!p.IsString()) Bad("domain.presets: names");
            domain.presets.push_back(std::get<std::string>(p.data));
        }
    }
    const json::Value* seeds = Member(object, "seeds");
    if (seeds == nullptr) Bad("domain.seeds: missing");
    const json::Object& seedPolicy = DomainObject(*seeds, "domain.seeds");
    const json::Value* policy = Member(seedPolicy, "policy");
    if (policy != nullptr && *policy == json::Value("any_u32")) {
        domain.anySeed = true;
    } else if (policy != nullptr && *policy == json::Value("listed")) {
        domain.anySeed = false;
        for (const json::Value& s : DomainArray(seedPolicy, "seeds", "domain.seeds")) {
            if (!s.IsInt() || std::get<int64_t>(s.data) < 0 || std::get<int64_t>(s.data) > 0xFFFFFFFFll) {
                Bad("domain.seeds.seeds: 32-bit unsigned integers");
            }
            domain.seeds.push_back(static_cast<uint64_t>(std::get<int64_t>(s.data)));
        }
        if (domain.seeds.empty()) Bad("domain.seeds.seeds: at least one listed seed");
    } else {
        Bad("domain.seeds.policy: any_u32 or listed");
    }
    const json::Value* geometry = Member(object, "geometry");
    if (geometry == nullptr) Bad("domain.geometry: missing");
    const json::Object& geo = DomainObject(*geometry, "domain.geometry");
    const json::Array& classes = DomainArray(geo, "mesh_classes", "domain.geometry");
    if (classes.empty()) Bad("domain.geometry.mesh_classes: at least one mesh class");
    for (const json::Value& c : classes) {
        if (!c.IsString() || std::get<std::string>(c.data).empty()) Bad("domain.geometry.mesh_classes: names");
        domain.meshClasses.push_back(std::get<std::string>(c.data));
    }
    const json::Value* tiles = Member(geo, "uv_tiles");
    if (tiles == nullptr || *tiles != json::Value(1)) Bad("domain.geometry.uv_tiles: a single UV tile");
    domain.uvTiles = 1;
    if (const json::Value* inputs = Member(geo, "inputs")) {
        for (const auto& [usage, rule] : DomainObject(*inputs, "domain.geometry.inputs")) {
            domain.inputs[usage] = RuleOf(rule, "domain input " + usage);
        }
    }
    const json::Value* output = Member(object, "output");
    if (output == nullptr) Bad("domain.output: missing");
    domain.output = RuleOf(*output, "domain.output");
    return domain;
}

ParityStatus StatusOf(const json::Value& value, const fs::path& file) {
    const json::Object& parity = ObjectOf(value, file, "parity");
    OnlyKeys(parity, {"status", "residuals", "reason", "report"}, file, "parity");
    const std::string& kind = StringOf(Required(parity, "status", file, "parity"), file, "parity.status");
    ParityStatus status;
    const json::Value* residuals = Member(parity, "residuals");
    if (kind == "exact") {
        status.kind = ParityStatus::Kind::Exact;
        if (residuals != nullptr) Fail(file, "an exact status has no residuals");
    } else if (kind == "calibrated") {
        status.kind = ParityStatus::Kind::Calibrated;
        if (residuals == nullptr || ArrayOf(*residuals, file, "parity.residuals").empty()) {
            Fail(file, "a calibrated status needs its residuals, one per unit");
        }
        for (const json::Value& r : std::get<json::Array>(residuals->data)) {
            const json::Object& entry = ObjectOf(r, file, "parity residual");
            OnlyKeys(entry, {"unit", "max", "sum", "count", "p99"}, file, "parity residual");
            Residual residual;
            residual.unit = StringOf(Required(entry, "unit", file, "parity residual"), file, "residual unit");
            static const std::set<std::string> kUnits{"code_u8", "code_u16", "ulp_f16", "ulp_f32"};
            if (!kUnits.contains(residual.unit)) Fail(file, "residual unit " + residual.unit + " is not a harness unit");
            for (auto [key, target] : {std::pair{"max", &residual.max}, std::pair{"sum", &residual.sum},
                                       std::pair{"count", &residual.count}, std::pair{"p99", &residual.p99}}) {
                const json::Value& n = Required(entry, key, file, "parity residual");
                if (!n.IsInt() || std::get<int64_t>(n.data) < 0) Fail(file, std::string("residual ") + key + ": a count");
                *target = static_cast<uint64_t>(std::get<int64_t>(n.data));
            }
            if (residual.max == 0) Fail(file, "a calibrated residual is non-zero");
            status.residuals.push_back(std::move(residual));
        }
    } else if (kind == "unavailable") {
        status.kind = ParityStatus::Kind::Unavailable;
        if (residuals != nullptr) Fail(file, "an unavailable status has no residuals");
        status.reason = StringOf(Required(parity, "reason", file, "parity"), file, "parity.reason");
    } else {
        Fail(file, "parity.status is exact, calibrated or unavailable");
    }
    return status;
}

AssetRecord RecordOf(const fs::path& file) {
    AssetRecord record;
    record.file = file;
    record.json = ReadJson(file);
    const json::Object& object = ObjectOf(record.json, file, "the record");
    OnlyKeys(object, {"schema", "asset", "name", "usage", "author", "license", "sources", "defaults",
                      "domain", "outputs", "physical_size_cm", "corpus", "parity"},
             file, "the record");
    if (Required(object, "schema", file, "the record") != json::Value(kRecordSchema)) {
        Fail(file, "schema is not " + std::string(kRecordSchema));
    }
    try {
        record.asset = core::ParseAssetUrl(StringOf(Required(object, "asset", file, "the record"), file, "asset"));
    } catch (const core::ValueError& error) {
        Fail(file, error.what());
    }
    if (ObservationRefusal(record.asset)) Fail(file, std::string(kObservationNotExecutable));
    record.name = StringOf(Required(object, "name", file, "the record"), file, "name");
    record.usage = StringOf(Required(object, "usage", file, "the record"), file, "usage");
    const std::vector<std::string>& usages = AssetUsages();
    if (std::find(usages.begin(), usages.end(), record.usage) == usages.end()) {
        Fail(file, "usage " + record.usage + " is not a procedural resource.Usage member");
    }
    record.author = StringOf(Required(object, "author", file, "the record"), file, "author");
    record.license = StringOf(Required(object, "license", file, "the record"), file, "license");
    if (record.license != "Apache-2.0") Fail(file, "license is not Apache-2.0 (decision 002)");

    // Clean room (decision 006): public literature and approved public documentation only.
    const json::Array& sources = ArrayOf(Required(object, "sources", file, "the record"), file, "sources");
    if (sources.empty()) Fail(file, "a record cites at least one public source");
    static const std::regex kApproved("^A-[A-Z0-9-]+$");
    for (const json::Value& s : sources) {
        const json::Object& entry = ObjectOf(s, file, "a source");
        OnlyKeys(entry, {"kind", "citation", "id"}, file, "a source");
        ProvenanceSource source;
        source.kind = StringOf(Required(entry, "kind", file, "a source"), file, "source kind");
        source.citation = StringOf(Required(entry, "citation", file, "a source"), file, "source citation");
        if (source.kind == "approved-source") {
            source.approvedSourceId = StringOf(Required(entry, "id", file, "an approved source"), file, "source id");
            if (!std::regex_match(source.approvedSourceId, kApproved)) {
                Fail(file, "approved source id " + source.approvedSourceId + " is not an A- id of docs/approved-sources.md");
            }
        } else if (source.kind != "paper" && source.kind != "book" && source.kind != "standard") {
            Fail(file, "source kind " + source.kind + " is not paper, book, standard or approved-source");
        } else if (Member(entry, "id") != nullptr) {
            Fail(file, "only an approved source carries an id");
        }
        record.sources.push_back(std::move(source));
    }

    try {
        record.domain = DomainOf(Required(object, "domain", file, "the record"));
    } catch (const DomainError& error) {
        Fail(file, error.message);
    }
    const json::Object& defaults = ObjectOf(Required(object, "defaults", file, "the record"), file, "defaults");
    for (const auto& [name, value] : defaults) {
        const std::optional<ParamValue> parsed = ParamOf(value);
        if (!parsed) Fail(file, "default " + name + " is not a typed parameter value");
        if (!record.domain.parameters.contains(name)) Fail(file, "default " + name + " is not a declared parameter");
        record.defaults[name] = *parsed;
    }
    for (const auto& [name, rule] : record.domain.parameters) {
        if (!record.defaults.contains(name)) Fail(file, "parameter " + name + " has no default");
    }

    // A multi-output asset (a material, phase3.2_proc-material-families): its outputs, each
    // inside the domain's output rule, and its physical size.
    if (const json::Value* outputs = Member(object, "outputs")) {
        const json::Array& list = ArrayOf(*outputs, file, "outputs");
        if (list.empty()) Fail(file, "outputs lists at least one output");
        const RasterRule& rule = record.domain.output;
        for (const json::Value& o : list) {
            const json::Object& entry = ObjectOf(o, file, "an output");
            OnlyKeys(entry, {"id", "channel", "channels", "colour_space"}, file, "an output");
            AssetOutput output;
            output.id = StringOf(Required(entry, "id", file, "an output"), file, "output id");
            const std::string where = "output " + output.id;
            output.channel = StringOf(Required(entry, "channel", file, where), file, where + " channel");
            if (!core::FromString<core::ChannelType>(output.channel)) {
                Fail(file, where + ": channel " + output.channel + " is not a ChannelType");
            }
            const json::Value& channels = Required(entry, "channels", file, where);
            if (!channels.IsInt() || std::get<int64_t>(channels.data) < 1 || std::get<int64_t>(channels.data) > 4) {
                Fail(file, where + ": channels is an integer in [1, 4]");
            }
            output.channels = static_cast<uint32_t>(std::get<int64_t>(channels.data));
            if (std::find(rule.channels.begin(), rule.channels.end(), output.channels) == rule.channels.end()) {
                Fail(file, where + ": channels is not one of the domain's output channels");
            }
            output.colourSpace = StringOf(Required(entry, "colour_space", file, where), file, where + " colour_space");
            if (std::find(rule.colourSpaces.begin(), rule.colourSpaces.end(), output.colourSpace) ==
                rule.colourSpaces.end()) {
                Fail(file, where + ": colour_space is not one of the domain's output colour spaces");
            }
            for (const AssetOutput& other : record.outputs) {
                if (other.id == output.id) Fail(file, where + " is listed twice");
                if (other.channel == output.channel) Fail(file, where + ": channel " + output.channel + " is fed twice");
            }
            record.outputs.push_back(std::move(output));
        }
    }
    if (const json::Value* size = Member(object, "physical_size_cm")) {
        const json::Array& sides = ArrayOf(*size, file, "physical_size_cm");
        if (sides.size() != 2) Fail(file, "physical_size_cm is [width, height] in centimetres");
        std::array<double, 2> cm{};
        for (size_t i = 0; i < 2; ++i) {
            if (!sides[i].IsNumber() || !std::isfinite(NumberOf(sides[i])) || !(NumberOf(sides[i]) > 0.0)) {
                Fail(file, "physical_size_cm holds two finite positive centimetre values");
            }
            cm[i] = NumberOf(sides[i]);
        }
        record.physicalSizeCm = cm;
    }

    const json::Object& corpus = ObjectOf(Required(object, "corpus", file, "the record"), file, "corpus");
    OnlyKeys(corpus, {"calibration", "held_out"}, file, "corpus");
    record.status = StatusOf(Required(object, "parity", file, "the record"), file);
    const json::Value* calibration = Member(corpus, "calibration");
    const json::Value* heldOut = Member(corpus, "held_out");
    if (record.status.kind != ParityStatus::Kind::Unavailable) {
        if (calibration == nullptr || heldOut == nullptr) {
            Fail(file, "an exact or calibrated status names its calibration and held-out corpus ids");
        }
        record.status.corpusIds = {StringOf(*calibration, file, "corpus.calibration"),
                                   StringOf(*heldOut, file, "corpus.held_out")};
        const json::Value* report = Member(std::get<json::Object>(object.at("parity").data), "report");
        if (report == nullptr) Fail(file, "an exact or calibrated status names the report that gives it");
        record.report = StringOf(*report, file, "parity.report");
    }
    return record;
}

std::vector<AssetAlias> AliasesOf(const fs::path& file) {
    const json::Value document = ReadJson(file);
    const json::Object& object = ObjectOf(document, file, "the alias table");
    OnlyKeys(object, {"schema", "aliases"}, file, "the alias table");
    if (Required(object, "schema", file, "the alias table") != json::Value(kAliasSchema)) {
        Fail(file, "schema is not " + std::string(kAliasSchema));
    }
    std::vector<AssetAlias> aliases;
    for (const json::Value& a : ArrayOf(Required(object, "aliases", file, "the alias table"), file, "aliases")) {
        const json::Object& entry = ObjectOf(a, file, "an alias");
        OnlyKeys(entry, {"shelf", "usage", "painter_name", "asset"}, file, "an alias");
        AssetAlias alias;
        alias.shelf = StringOf(Required(entry, "shelf", file, "an alias"), file, "alias shelf");
        alias.usage = StringOf(Required(entry, "usage", file, "an alias"), file, "alias usage");
        alias.painterName = StringOf(Required(entry, "painter_name", file, "an alias"), file, "alias painter_name");
        try {
            alias.asset = core::ParseAssetUrl(StringOf(Required(entry, "asset", file, "an alias"), file, "alias asset"));
        } catch (const core::ValueError& error) {
            Fail(file, error.what());
        }
        if (ObservationRefusal(alias.asset)) Fail(file, std::string(kObservationNotExecutable));
        if (alias.shelf == kLibraryShelf) Fail(file, "an alias names a Painter shelf, not " + std::string(kLibraryShelf));
        aliases.push_back(std::move(alias));
    }
    return aliases;
}

std::string Lower(std::string_view text) {
    std::string out(text);
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return out;
}

/// The query form of a usage: lower case, no underscore (`SMART_MATERIAL` -> `smartmaterial`).
std::string QueryUsage(std::string_view usage) {
    std::string out;
    for (const char c : Lower(usage)) {
        if (c != '_') out += c;
    }
    return out;
}

SearchRefusal Gap(const std::string& message) {
    return SearchRefusal{SearchRefusal::Kind::NotYetSupported,
                         "resource.search: " + message + " (phase3.3_procedural-families; decision 324)",
                         {}};
}

/// One term of a query: its key (s, u, n), its unescaped value and whether it ended with an
/// unescaped `=` (an exact name).
struct Term {
    char key = 0;
    std::string value;
    bool exact = false;
    std::string text;
};

std::expected<std::vector<Term>, SearchRefusal> Terms(std::string_view query) {
    std::vector<Term> terms;
    std::string raw;
    std::string value;
    bool escapedLast = false;
    bool any = false;
    const auto flush = [&]() -> std::optional<SearchRefusal> {
        if (!any) return std::nullopt;
        Term term;
        term.text = raw;
        if (raw.size() < 2 || raw[1] != ':' || (raw[0] != 's' && raw[0] != 'u' && raw[0] != 'n')) {
            return Gap("the query term \"" + raw + "\" is not s:, u: or n:; Painter's query grammar beyond "
                       "these terms is unrecorded");
        }
        term.key = raw[0];
        term.value = value.substr(2);
        if (!term.value.empty() && term.value.back() == '=' && !escapedLast) {
            term.exact = true;
            term.value.pop_back();
        }
        if (term.value.empty()) return Gap("the query term \"" + raw + "\" has no value");
        terms.push_back(std::move(term));
        raw.clear();
        value.clear();
        any = false;
        return std::nullopt;
    };
    for (size_t i = 0; i < query.size(); ++i) {
        const char c = query[i];
        if (c == '\\' && i + 1 < query.size()) {
            raw += c;
            raw += query[i + 1];
            value += query[++i];
            escapedLast = true;
            any = true;
            continue;
        }
        if (c == ' ' || c == '\t') {
            if (auto refusal = flush()) return SearchError(*refusal);
            continue;
        }
        raw += c;
        value += c;
        escapedLast = false;
        any = true;
    }
    if (auto refusal = flush()) return SearchError(*refusal);
    return terms;
}

}  // namespace

const std::vector<std::string>& AssetUsages() {
    static const std::vector<std::string> kUsages{"BASE_MATERIAL", "FILTER", "GENERATOR",
                                                  "PROCEDURAL", "SMART_MASK", "SMART_MATERIAL"};
    return kUsages;
}

std::expected<CertifiedDomain, std::string> ParseDomain(const json::Value& document) {
    try {
        return DomainOf(document);
    } catch (const DomainError& error) {
        return LoadFailure(error.message);
    }
}

std::expected<AssetLibrary, std::string> AssetLibrary::Load(const fs::path& root) {
    try {
        const fs::path index = root / "library.json";
        const json::Value document = ReadJson(index);
        const json::Object& object = ObjectOf(document, index, "the library");
        OnlyKeys(object, {"schema", "records", "aliases"}, index, "the library");
        if (Required(object, "schema", index, "the library") != json::Value(kLibrarySchema)) {
            Fail(index, "schema is not " + std::string(kLibrarySchema));
        }
        AssetLibrary library;
        std::set<std::string> urls;
        for (const json::Value& path : ArrayOf(Required(object, "records", index, "the library"), index, "records")) {
            const std::string& relative = StringOf(path, index, "a record path");
            if (fs::path(relative).is_absolute() || relative.find("..") != std::string::npos) {
                Fail(index, "record path " + relative + " is not inside the library");
            }
            AssetRecord record = RecordOf(root / relative);
            if (!urls.insert(core::FormatAssetUrl(record.asset)).second) {
                Fail(record.file, core::FormatAssetUrl(record.asset) + " is pinned by two records");
            }
            library.m_records.push_back(std::move(record));
        }
        const std::string& aliasPath = StringOf(Required(object, "aliases", index, "the library"), index, "aliases");
        if (fs::path(aliasPath).is_absolute() || aliasPath.find("..") != std::string::npos) {
            Fail(index, "alias path " + aliasPath + " is not inside the library");
        }
        const fs::path aliasFile = root / aliasPath;
        library.m_aliases = AliasesOf(aliasFile);
        std::set<std::tuple<std::string, std::string, std::string>> keys;
        for (const AssetAlias& alias : library.m_aliases) {
            const AssetRecord* record = library.Find(alias.asset);
            const std::string url = core::FormatAssetUrl(alias.asset);
            if (record == nullptr) Fail(aliasFile, "alias " + alias.painterName + " names " + url + ", which the library does not hold");
            if (record->usage != alias.usage) {
                Fail(aliasFile, "alias " + alias.painterName + " is a " + alias.usage + ", " + url + " a " + record->usage);
            }
            if (record->status.kind != ParityStatus::Kind::Exact) {
                Fail(aliasFile, "alias " + alias.painterName + " names " + url + ", whose parity status is " +
                                    std::string(KindName(record->status.kind)) +
                                    ": only a certified (exact) asset may answer a Painter name");
            }
            if (!keys.insert({alias.shelf, alias.usage, alias.painterName}).second) {
                Fail(aliasFile, "alias " + alias.shelf + "/" + alias.usage + "/" + alias.painterName + " is listed twice");
            }
        }
        // Shipped assets carry UzPainter names, never a Painter name of the alias table.
        for (const AssetRecord& record : library.m_records) {
            for (const AssetAlias& alias : library.m_aliases) {
                if (Lower(record.name) == Lower(alias.painterName)) {
                    Fail(record.file, "name " + record.name + " is a Painter asset name (an alias); a record carries a UzPainter name");
                }
            }
        }
        std::sort(library.m_records.begin(), library.m_records.end(), [](const AssetRecord& a, const AssetRecord& b) {
            return core::FormatAssetUrl(a.asset) < core::FormatAssetUrl(b.asset);
        });
        return library;
    } catch (const LoadError& error) {
        return LoadFailure(error.message);
    }
}

const AssetRecord* AssetLibrary::Find(const core::AssetUrl& asset) const {
    if (ObservationRefusal(asset)) return nullptr;
    for (const AssetRecord& record : m_records) {
        if (record.asset == asset) return &record;
    }
    return nullptr;
}

std::expected<const AssetRecord*, UnsupportedProcedural> AssetLibrary::Resolve(const core::AssetUrl& asset) const {
    if (std::optional<UnsupportedProcedural> reserved = ObservationRefusal(asset)) return ResolveError(std::move(*reserved));
    if (const AssetRecord* record = Find(asset)) return record;
    std::string held;
    for (const AssetRecord& record : m_records) {
        if (record.asset.family == asset.family && record.asset.id == asset.id) {
            held += (held.empty() ? "" : ", ") + record.asset.version;
        }
    }
    UnsupportedProcedural refusal = Refuse(core::FormatAssetUrl(asset), kNotInLibrary);
    refusal.field = "version";
    refusal.value = asset.version;
    refusal.certified = "[" + held + "]";
    return ResolveError(std::move(refusal));
}

std::expected<std::vector<const AssetRecord*>, SearchRefusal> AssetLibrary::Search(std::string_view query) const {
    std::expected<std::vector<Term>, SearchRefusal> terms = Terms(query);
    if (!terms) return SearchError(terms.error());
    std::optional<std::string> shelf, usage, name;
    for (const Term& term : *terms) {
        std::optional<std::string>& slot = term.key == 's' ? shelf : term.key == 'u' ? usage : name;
        if (slot) return SearchError(Gap("the query repeats the " + std::string(1, term.key) + ": term"));
        if (term.key == 'n' && !term.exact) {
            return SearchError(Gap("the name term \"" + term.text + "\" is not exact (n:<name>=); Painter's "
                                       "partial name matching is unrecorded"));
        }
        if (term.key != 'n' && term.exact) {
            return SearchError(Gap("the query term \"" + term.text + "\" ends with = outside a name term"));
        }
        slot = term.value;
    }
    if (usage) {
        const std::vector<std::string>& usages = AssetUsages();
        const auto known = std::find_if(usages.begin(), usages.end(),
                                        [&](const std::string& u) { return QueryUsage(u) == *usage; });
        if (known == usages.end()) {
            return SearchError(Gap("the usage u:" + *usage + " is not a procedural usage of the asset library"));
        }
        usage = *known;
    }
    std::vector<const AssetRecord*> found;
    if (shelf && *shelf == kLibraryShelf) {
        for (const AssetRecord& record : m_records) {
            if ((!usage || record.usage == *usage) && (!name || record.name == *name)) found.push_back(&record);
        }
        return found;
    }
    // Painter's library: only an exact Painter name is answered, through the alias table.
    if (!name) {
        return SearchError(Gap("listing " + (shelf ? "the shelf " + *shelf : std::string("every shelf")) +
                                   " without an exact name: UzPainter holds no Adobe content (decision 006), so "
                                   "Painter's listing cannot be reproduced"));
    }
    for (const AssetAlias& alias : m_aliases) {
        if (alias.painterName == *name && (!shelf || alias.shelf == *shelf) && (!usage || alias.usage == *usage)) {
            found.push_back(Find(alias.asset));
        }
    }
    if (found.empty()) {
        SearchRefusal refusal;
        refusal.kind = SearchRefusal::Kind::UnsupportedProcedural;
        refusal.procedural = Refuse((shelf ? *shelf + "/" : std::string()) + (usage ? QueryUsage(*usage) + "/" : std::string()) + *name,
                                    kNoCertifiedFamily);
        refusal.message = "resource.search: " + refusal.procedural.Describe() +
                          ": the asset library holds no certified family for this Painter name, and no "
                          "other asset is substituted (phase3.3_procedural-families)";
        return SearchError(std::move(refusal));
    }
    std::sort(found.begin(), found.end());
    found.erase(std::unique(found.begin(), found.end()), found.end());
    return found;
}

std::vector<std::string> PinnedAssets(const core::Project& project) {
    std::set<std::string> pins;
    const auto source = [&](const std::optional<core::Source>& s) {
        if (!s) return;
        if (const auto* procedural = std::get_if<core::ProceduralSource>(&s->value)) pins.insert(procedural->ref.asset);
    };
    const auto fill = [&](const std::optional<core::FillContent>& content) {
        if (!content) return;
        for (const auto& [channel, s] : content->sources) source(s);
        source(content->mono_source);
        source(content->material_source);
    };
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (visit.layer != nullptr) {
            fill(visit.layer->fill);
            if (visit.layer->preset_ref) pins.insert(visit.layer->preset_ref->asset);
        }
        if (visit.effect != nullptr) {
            fill(visit.effect->fill);
            if (visit.effect->procedural) pins.insert(visit.effect->procedural->asset);
            if (visit.effect->preset_ref) pins.insert(visit.effect->preset_ref->asset);
        }
    });
    return {pins.begin(), pins.end()};
}

std::optional<UnsupportedProcedural> CheckPins(const core::Project& project, const AssetLibrary& library) {
    for (const std::string& pin : PinnedAssets(project)) {
        core::AssetUrl url;
        try {
            url = core::ParseAssetUrl(pin);
        } catch (const core::ValueError&) {
            return Refuse(pin, "not a pinned asset URL (uzasset://<family>/<id>@<version>)");
        }
        std::expected<const AssetRecord*, UnsupportedProcedural> resolved = library.Resolve(url);
        if (!resolved) return resolved.error();
    }
    return std::nullopt;
}

fs::path DefaultLibraryRoot() {
    if (const wchar_t* overridden = _wgetenv(L"UZP_ASSET_LIBRARY"); overridden != nullptr && *overridden != L'\0') {
        return fs::path(overridden);
    }
    return render::DefaultDxcompilerPath().parent_path() / "assets" / "procedural";
}

const std::expected<AssetLibrary, std::string>& ShippedLibrary() {
    static const std::expected<AssetLibrary, std::string> library = AssetLibrary::Load(DefaultLibraryRoot());
    return library;
}

}  // namespace uzp::procedural
