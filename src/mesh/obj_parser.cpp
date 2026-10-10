#include "mesh/obj_parser.h"

#include <charconv>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <system_error>
#include <vector>

#include "mesh/import_error.h"
#include "mesh/mesh_builder.h"

namespace uzp::mesh {

namespace {

constexpr std::string_view kDefaultName = "default";

bool IsSpace(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\v' || c == '\f'; }

std::string_view Trim(std::string_view s) {
    while (!s.empty() && IsSpace(s.front())) s.remove_prefix(1);
    while (!s.empty() && IsSpace(s.back())) s.remove_suffix(1);
    return s;
}

std::vector<std::string_view> Tokens(std::string_view s) {
    std::vector<std::string_view> tokens;
    std::size_t i = 0;
    while (i < s.size()) {
        while (i < s.size() && IsSpace(s[i])) ++i;
        const std::size_t start = i;
        while (i < s.size() && !IsSpace(s[i])) ++i;
        if (i > start) tokens.push_back(s.substr(start, i - start));
    }
    return tokens;
}

class Parser {
public:
    explicit Parser(TexturingMesh& mesh) : mesh_(mesh), builder_(mesh) {}

    void Run(std::string_view text) {
        std::size_t pos = 0;
        while (pos <= text.size()) {
            std::size_t end = text.find('\n', pos);
            if (end == std::string_view::npos) end = text.size();
            ++line_;
            Statement(text.substr(pos, end - pos));
            pos = end + 1;
        }
        builder_.Finish();
        if (!libraries_.empty()) mesh_.flags.format_details["mtllib"] = std::move(libraries_);
    }

private:
    [[noreturn]] void Fail(const std::string& message) const {
        throw ImportError(ImportErrorKind::parse_error,
                          "OBJ line " + std::to_string(line_) + ": " + message,
                          {{"line", static_cast<std::int64_t>(line_)}});
    }

    double Number(std::string_view token) const {
        double value = 0.0;
        const char* first = token.data();
        const char* last = token.data() + token.size();
        if (!token.empty() && *first == '+') ++first;
        const auto [ptr, ec] = std::from_chars(first, last, value);
        if (ec != std::errc() || ptr != last) Fail("'" + std::string(token) + "' is not a number");
        return value;
    }

    /// The 0-based element of a 1-based or negative (relative) OBJ index into `count` elements.
    std::uint32_t Index(std::string_view token, std::size_t count, const char* what) const {
        std::int64_t value = 0;
        const auto [ptr, ec] = std::from_chars(token.data(), token.data() + token.size(), value);
        if (ec != std::errc() || ptr != token.data() + token.size() || value == 0) {
            Fail("'" + std::string(token) + "' is not a valid " + what + " index");
        }
        const std::int64_t resolved = value > 0 ? value - 1 : static_cast<std::int64_t>(count) + value;
        if (resolved < 0 || resolved >= static_cast<std::int64_t>(count)) {
            Fail(std::string(what) + " index " + std::string(token) + " is out of range (" +
                 std::to_string(count) + " defined)");
        }
        return static_cast<std::uint32_t>(resolved);
    }

    void Statement(std::string_view line) {
        const std::size_t hash = line.find('#');
        if (hash != std::string_view::npos) line = line.substr(0, hash);
        line = Trim(line);
        if (line.empty()) return;
        std::size_t split = 0;
        while (split < line.size() && !IsSpace(line[split])) ++split;
        const std::string_view keyword = line.substr(0, split);
        const std::string_view rest = Trim(line.substr(split));
        if (keyword == "v") {
            const auto t = Tokens(rest);
            if (t.size() < 3) Fail("a vertex needs x, y and z");
            mesh_.positions.push_back(Float3{static_cast<float>(Number(t[0])), static_cast<float>(Number(t[1])),
                                             static_cast<float>(Number(t[2]))});
        } else if (keyword == "vt") {
            const auto t = Tokens(rest);
            if (t.empty()) Fail("a texture vertex needs u");
            uvs_.push_back(Float2{static_cast<float>(Number(t[0])),
                                  t.size() > 1 ? static_cast<float>(Number(t[1])) : 0.0f});
        } else if (keyword == "vn") {
            const auto t = Tokens(rest);
            if (t.size() < 3) Fail("a normal needs x, y and z");
            normals_.push_back(Float3{static_cast<float>(Number(t[0])), static_cast<float>(Number(t[1])),
                                      static_cast<float>(Number(t[2]))});
        } else if (keyword == "f") {
            Face(Tokens(rest));
        } else if (keyword == "o" || keyword == "g") {
            const std::string name = rest.empty() ? std::string(kDefaultName) : std::string(rest);
            if (!has_object_ || mesh_.objects.empty() || mesh_.objects.back().name != name) {
                builder_.BeginObject(name);
                has_object_ = true;
            }
        } else if (keyword == "usemtl") {
            if (rest.empty()) Fail("usemtl needs a material name");
            material_ = MaterialId(std::string(rest));
        } else if (keyword == "mtllib") {
            for (std::string_view name : Tokens(rest)) libraries_.push_back(std::string(name));
        } else if (keyword == "l" || keyword == "p") {
            ++mesh_.flags.skipped_non_surface_elements;
        }
    }

    std::uint32_t MaterialId(const std::string& name) {
        const auto [it, inserted] = material_order_.try_emplace(name, material_order_.size());
        (void)inserted;
        return builder_.Material(it->second, it->second, name);
    }

    void Face(const std::vector<std::string_view>& refs) {
        if (refs.size() < 3) Fail("a face needs at least three corners");
        if (!has_object_) {
            builder_.BeginObject(std::string(kDefaultName));
            has_object_ = true;
        }
        if (!material_) material_ = MaterialId(std::string(kDefaultName));
        corners_.clear();
        for (std::string_view ref : refs) {
            Corner corner;
            corner.material = *material_;
            const std::size_t s1 = ref.find('/');
            corner.position = Index(ref.substr(0, s1), mesh_.positions.size(), "vertex");
            bool has_uv = false;
            bool has_normal = false;
            if (s1 != std::string_view::npos) {
                const std::string_view tail = ref.substr(s1 + 1);
                const std::size_t s2 = tail.find('/');
                const std::string_view uv = tail.substr(0, s2);
                if (!uv.empty()) {
                    corner.uv0 = uvs_[Index(uv, uvs_.size(), "texture vertex")];
                    has_uv = true;
                }
                if (s2 != std::string_view::npos) {
                    const std::string_view normal = tail.substr(s2 + 1);
                    if (normal.empty() || normal.find('/') != std::string_view::npos) {
                        Fail("'" + std::string(ref) + "' is not a face reference");
                    }
                    corner.normal = normals_[Index(normal, normals_.size(), "normal")];
                    has_normal = true;
                }
            }
            if (!has_uv) ++mesh_.flags.corners_without_uv;
            if (!has_normal) ++mesh_.flags.corners_without_normal;
            corners_.push_back(corner);
        }
        builder_.AddPolygon(corners_);
    }

    TexturingMesh& mesh_;
    MeshBuilder builder_;
    std::vector<Float2> uvs_;
    std::vector<Float3> normals_;
    std::vector<Corner> corners_;
    std::map<std::string, std::uint64_t> material_order_;
    std::optional<std::uint32_t> material_;
    core::json::Array libraries_;
    bool has_object_ = false;
    std::size_t line_ = 0;
};

}  // namespace

void ParseObj(std::string_view text, TexturingMesh& mesh) {
    Parser(mesh).Run(text);
    mesh.units = Units{"unspecified", 0.0, 1.0, "file"};
}

}  // namespace uzp::mesh
