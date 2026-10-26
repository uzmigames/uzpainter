#include "procedural/filter_gate_settings.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <memory>
#include <regex>
#include <span>

#include "procedural/filter_gate_trace.h"
#include "spng.h"
#include "uzp_core/manifest/sha256.h"
#include "zlib.h"

namespace uzp::procedural {
namespace {
using core::json::Array;
using core::json::Object;
using core::json::Value;
constexpr std::string_view kPlane = "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe";
constexpr std::array<std::string_view, 5> kBoundaries{"after-create", "after-setup6", "pre16-r1",
                                                      "after-reopen", "pre16-r2"};
constexpr std::string_view kPrefix = "QApplication.ProjectSettingsDialog.scroll_area.qt_scrollarea_viewport."
                                     "scroll_area_content.advanced_settings_section.content.";
struct Failure {
    std::string code;
};
void Require(bool ok, std::string_view code) {
    if (!ok)
        throw Failure{"F_SETTINGS_" + std::string(code)};
}
const Object &Obj(const Value &v) {
    Require(v.IsObject(), "OBJECT");
    return std::get<Object>(v.data);
}
const Array &Arr(const Value &v) {
    Require(v.IsArray(), "ARRAY");
    return std::get<Array>(v.data);
}
const Value &At(const Object &o, std::string_view k) {
    auto i = o.find(k);
    Require(i != o.end(), "FIELD");
    return i->second;
}
const std::string &Str(const Value &v) {
    Require(v.IsString(), "STRING");
    return std::get<std::string>(v.data);
}
bool Eq(const Value &a, const Value &b) {
    return core::json::WriteCanonical(a) == core::json::WriteCanonical(b);
}
bool Text(const Value &v) {
    return v.IsString() && !Str(v).empty() && Str(v).find('\0') == std::string::npos;
}
bool Positive(const Value &v) { return v.IsInt() && std::get<std::int64_t>(v.data) > 0; }
const Object &Closed(const Value &v, std::initializer_list<std::string_view> keys) {
    const auto &o = Obj(v);
    Require(o.size() == keys.size(), "FIELDS");
    for (auto k : keys)
        Require(o.contains(k), "FIELDS");
    return o;
}
std::string Hash(const Value &v) { return core::Sha256Hex(core::json::WriteCanonical(v)); }
std::string Condition(std::string_view boundary) {
    return boundary == "after-reopen" || boundary == "pre16-r2" ? "after_save_reopen" : "same_session";
}
std::string Path(const Value &v) {
    Require(Text(v), "MESH_PATH");
    std::string path = Str(v);
    std::replace(path.begin(), path.end(), '/', '\\');
    std::string root;
    std::size_t pos = 0;
    if (path.starts_with("\\\\")) {
        std::string prefix = path.substr(0, 8);
        for (char &c : prefix)
            c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        const std::size_t start = prefix == "\\\\?\\UNC\\" ? 8 : 2;
        const auto server_end = path.find('\\', start);
        Require(server_end != std::string::npos, "MESH_PATH");
        const auto share_end = path.find('\\', server_end + 1);
        // A mesh must have a filename after its UNC anchor; a bare share has no suffix.
        Require(share_end != std::string::npos, "MESH_PATH");
        root = path.substr(0, share_end + 1);
        pos = share_end + 1;
    } else {
        const auto lead = static_cast<unsigned char>(path[0]);
        const std::size_t first = lead < 0x80 ? 1 : lead < 0xe0 ? 2 : lead < 0xf0 ? 3 : 4;
        Require(path[0] != '\\' && path.size() > first + 1 && path[first] == ':' && path[first + 1] == '\\',
                "MESH_PATH");
        root = path.substr(0, first + 2);
        pos = first + 2;
    }
    std::string result = root;
    while (pos < path.size()) {
        auto end = path.find('\\', pos);
        if (end == std::string::npos)
            end = path.size();
        auto part = path.substr(pos, end - pos);
        Require(part != "..", "MESH_PATH");
        if (!part.empty() && part != ".") {
            if (result.back() != '\\')
                result += '\\';
            result += part;
        }
        pos = end + 1;
    }
    return result;
}
// Unicode 15.1.0 full case folding, matching the recorder Python runtime.
// Generated from chr(cp).casefold() for cp in range(0x110000): adjacent
// single-codepoint mappings share delta/stride; multi-codepoint mappings stay
// explicit.
std::u32string Fold(std::string_view s) {
    struct Range {
        char32_t first, last, step;
        std::int32_t delta;
    };
    static constexpr Range ranges[]{
        {0x41, 0x5a, 1, 32},         {0xb5, 0xb5, 1, 775},        {0xc0, 0xd6, 1, 32},
        {0xd8, 0xde, 1, 32},         {0x100, 0x12e, 2, 1},        {0x132, 0x136, 2, 1},
        {0x139, 0x147, 2, 1},        {0x14a, 0x176, 2, 1},        {0x178, 0x178, 1, -121},
        {0x179, 0x17d, 2, 1},        {0x17f, 0x17f, 1, -268},     {0x181, 0x181, 1, 210},
        {0x182, 0x184, 2, 1},        {0x186, 0x186, 1, 206},      {0x187, 0x187, 1, 1},
        {0x189, 0x18a, 1, 205},      {0x18b, 0x18b, 1, 1},        {0x18e, 0x18e, 1, 79},
        {0x18f, 0x18f, 1, 202},      {0x190, 0x190, 1, 203},      {0x191, 0x191, 1, 1},
        {0x193, 0x193, 1, 205},      {0x194, 0x194, 1, 207},      {0x196, 0x196, 1, 211},
        {0x197, 0x197, 1, 209},      {0x198, 0x198, 1, 1},        {0x19c, 0x19c, 1, 211},
        {0x19d, 0x19d, 1, 213},      {0x19f, 0x19f, 1, 214},      {0x1a0, 0x1a4, 2, 1},
        {0x1a6, 0x1a6, 1, 218},      {0x1a7, 0x1a7, 1, 1},        {0x1a9, 0x1a9, 1, 218},
        {0x1ac, 0x1ac, 1, 1},        {0x1ae, 0x1ae, 1, 218},      {0x1af, 0x1af, 1, 1},
        {0x1b1, 0x1b2, 1, 217},      {0x1b3, 0x1b5, 2, 1},        {0x1b7, 0x1b7, 1, 219},
        {0x1b8, 0x1b8, 1, 1},        {0x1bc, 0x1bc, 1, 1},        {0x1c4, 0x1c4, 1, 2},
        {0x1c5, 0x1c5, 1, 1},        {0x1c7, 0x1c7, 1, 2},        {0x1c8, 0x1c8, 1, 1},
        {0x1ca, 0x1ca, 1, 2},        {0x1cb, 0x1db, 2, 1},        {0x1de, 0x1ee, 2, 1},
        {0x1f1, 0x1f1, 1, 2},        {0x1f2, 0x1f4, 2, 1},        {0x1f6, 0x1f6, 1, -97},
        {0x1f7, 0x1f7, 1, -56},      {0x1f8, 0x21e, 2, 1},        {0x220, 0x220, 1, -130},
        {0x222, 0x232, 2, 1},        {0x23a, 0x23a, 1, 10795},    {0x23b, 0x23b, 1, 1},
        {0x23d, 0x23d, 1, -163},     {0x23e, 0x23e, 1, 10792},    {0x241, 0x241, 1, 1},
        {0x243, 0x243, 1, -195},     {0x244, 0x244, 1, 69},       {0x245, 0x245, 1, 71},
        {0x246, 0x24e, 2, 1},        {0x345, 0x345, 1, 116},      {0x370, 0x372, 2, 1},
        {0x376, 0x376, 1, 1},        {0x37f, 0x37f, 1, 116},      {0x386, 0x386, 1, 38},
        {0x388, 0x38a, 1, 37},       {0x38c, 0x38c, 1, 64},       {0x38e, 0x38f, 1, 63},
        {0x391, 0x3a1, 1, 32},       {0x3a3, 0x3ab, 1, 32},       {0x3c2, 0x3c2, 1, 1},
        {0x3cf, 0x3cf, 1, 8},        {0x3d0, 0x3d0, 1, -30},      {0x3d1, 0x3d1, 1, -25},
        {0x3d5, 0x3d5, 1, -15},      {0x3d6, 0x3d6, 1, -22},      {0x3d8, 0x3ee, 2, 1},
        {0x3f0, 0x3f0, 1, -54},      {0x3f1, 0x3f1, 1, -48},      {0x3f4, 0x3f4, 1, -60},
        {0x3f5, 0x3f5, 1, -64},      {0x3f7, 0x3f7, 1, 1},        {0x3f9, 0x3f9, 1, -7},
        {0x3fa, 0x3fa, 1, 1},        {0x3fd, 0x3ff, 1, -130},     {0x400, 0x40f, 1, 80},
        {0x410, 0x42f, 1, 32},       {0x460, 0x480, 2, 1},        {0x48a, 0x4be, 2, 1},
        {0x4c0, 0x4c0, 1, 15},       {0x4c1, 0x4cd, 2, 1},        {0x4d0, 0x52e, 2, 1},
        {0x531, 0x556, 1, 48},       {0x10a0, 0x10c5, 1, 7264},   {0x10c7, 0x10c7, 1, 7264},
        {0x10cd, 0x10cd, 1, 7264},   {0x13f8, 0x13fd, 1, -8},     {0x1c80, 0x1c80, 1, -6222},
        {0x1c81, 0x1c81, 1, -6221},  {0x1c82, 0x1c82, 1, -6212},  {0x1c83, 0x1c84, 1, -6210},
        {0x1c85, 0x1c85, 1, -6211},  {0x1c86, 0x1c86, 1, -6204},  {0x1c87, 0x1c87, 1, -6180},
        {0x1c88, 0x1c88, 1, 35267},  {0x1c90, 0x1cba, 1, -3008},  {0x1cbd, 0x1cbf, 1, -3008},
        {0x1e00, 0x1e94, 2, 1},      {0x1e9b, 0x1e9b, 1, -58},    {0x1ea0, 0x1efe, 2, 1},
        {0x1f08, 0x1f0f, 1, -8},     {0x1f18, 0x1f1d, 1, -8},     {0x1f28, 0x1f2f, 1, -8},
        {0x1f38, 0x1f3f, 1, -8},     {0x1f48, 0x1f4d, 1, -8},     {0x1f59, 0x1f5f, 2, -8},
        {0x1f68, 0x1f6f, 1, -8},     {0x1fb8, 0x1fb9, 1, -8},     {0x1fba, 0x1fbb, 1, -74},
        {0x1fbe, 0x1fbe, 1, -7173},  {0x1fc8, 0x1fcb, 1, -86},    {0x1fd8, 0x1fd9, 1, -8},
        {0x1fda, 0x1fdb, 1, -100},   {0x1fe8, 0x1fe9, 1, -8},     {0x1fea, 0x1feb, 1, -112},
        {0x1fec, 0x1fec, 1, -7},     {0x1ff8, 0x1ff9, 1, -128},   {0x1ffa, 0x1ffb, 1, -126},
        {0x2126, 0x2126, 1, -7517},  {0x212a, 0x212a, 1, -8383},  {0x212b, 0x212b, 1, -8262},
        {0x2132, 0x2132, 1, 28},     {0x2160, 0x216f, 1, 16},     {0x2183, 0x2183, 1, 1},
        {0x24b6, 0x24cf, 1, 26},     {0x2c00, 0x2c2f, 1, 48},     {0x2c60, 0x2c60, 1, 1},
        {0x2c62, 0x2c62, 1, -10743}, {0x2c63, 0x2c63, 1, -3814},  {0x2c64, 0x2c64, 1, -10727},
        {0x2c67, 0x2c6b, 2, 1},      {0x2c6d, 0x2c6d, 1, -10780}, {0x2c6e, 0x2c6e, 1, -10749},
        {0x2c6f, 0x2c6f, 1, -10783}, {0x2c70, 0x2c70, 1, -10782}, {0x2c72, 0x2c72, 1, 1},
        {0x2c75, 0x2c75, 1, 1},      {0x2c7e, 0x2c7f, 1, -10815}, {0x2c80, 0x2ce2, 2, 1},
        {0x2ceb, 0x2ced, 2, 1},      {0x2cf2, 0x2cf2, 1, 1},      {0xa640, 0xa66c, 2, 1},
        {0xa680, 0xa69a, 2, 1},      {0xa722, 0xa72e, 2, 1},      {0xa732, 0xa76e, 2, 1},
        {0xa779, 0xa77b, 2, 1},      {0xa77d, 0xa77d, 1, -35332}, {0xa77e, 0xa786, 2, 1},
        {0xa78b, 0xa78b, 1, 1},      {0xa78d, 0xa78d, 1, -42280}, {0xa790, 0xa792, 2, 1},
        {0xa796, 0xa7a8, 2, 1},      {0xa7aa, 0xa7aa, 1, -42308}, {0xa7ab, 0xa7ab, 1, -42319},
        {0xa7ac, 0xa7ac, 1, -42315}, {0xa7ad, 0xa7ad, 1, -42305}, {0xa7ae, 0xa7ae, 1, -42308},
        {0xa7b0, 0xa7b0, 1, -42258}, {0xa7b1, 0xa7b1, 1, -42282}, {0xa7b2, 0xa7b2, 1, -42261},
        {0xa7b3, 0xa7b3, 1, 928},    {0xa7b4, 0xa7c2, 2, 1},      {0xa7c4, 0xa7c4, 1, -48},
        {0xa7c5, 0xa7c5, 1, -42307}, {0xa7c6, 0xa7c6, 1, -35384}, {0xa7c7, 0xa7c9, 2, 1},
        {0xa7d0, 0xa7d0, 1, 1},      {0xa7d6, 0xa7d8, 2, 1},      {0xa7f5, 0xa7f5, 1, 1},
        {0xab70, 0xabbf, 1, -38864}, {0xff21, 0xff3a, 1, 32},     {0x10400, 0x10427, 1, 40},
        {0x104b0, 0x104d3, 1, 40},   {0x10570, 0x1057a, 1, 39},   {0x1057c, 0x1058a, 1, 39},
        {0x1058c, 0x10592, 1, 39},   {0x10594, 0x10595, 1, 39},   {0x10c80, 0x10cb2, 1, 64},
        {0x118a0, 0x118bf, 1, 32},   {0x16e40, 0x16e5f, 1, 32},   {0x1e900, 0x1e921, 1, 34},
    };
    struct Expansion {
        char32_t from;
        std::u32string_view to;
    };
    static constexpr Expansion expansions[]{
        {0xdf, U"\U00000073\U00000073"},
        {0x130, U"\U00000069\U00000307"},
        {0x149, U"\U000002bc\U0000006e"},
        {0x1f0, U"\U0000006a\U0000030c"},
        {0x390, U"\U000003b9\U00000308\U00000301"},
        {0x3b0, U"\U000003c5\U00000308\U00000301"},
        {0x587, U"\U00000565\U00000582"},
        {0x1e96, U"\U00000068\U00000331"},
        {0x1e97, U"\U00000074\U00000308"},
        {0x1e98, U"\U00000077\U0000030a"},
        {0x1e99, U"\U00000079\U0000030a"},
        {0x1e9a, U"\U00000061\U000002be"},
        {0x1e9e, U"\U00000073\U00000073"},
        {0x1f50, U"\U000003c5\U00000313"},
        {0x1f52, U"\U000003c5\U00000313\U00000300"},
        {0x1f54, U"\U000003c5\U00000313\U00000301"},
        {0x1f56, U"\U000003c5\U00000313\U00000342"},
        {0x1f80, U"\U00001f00\U000003b9"},
        {0x1f81, U"\U00001f01\U000003b9"},
        {0x1f82, U"\U00001f02\U000003b9"},
        {0x1f83, U"\U00001f03\U000003b9"},
        {0x1f84, U"\U00001f04\U000003b9"},
        {0x1f85, U"\U00001f05\U000003b9"},
        {0x1f86, U"\U00001f06\U000003b9"},
        {0x1f87, U"\U00001f07\U000003b9"},
        {0x1f88, U"\U00001f00\U000003b9"},
        {0x1f89, U"\U00001f01\U000003b9"},
        {0x1f8a, U"\U00001f02\U000003b9"},
        {0x1f8b, U"\U00001f03\U000003b9"},
        {0x1f8c, U"\U00001f04\U000003b9"},
        {0x1f8d, U"\U00001f05\U000003b9"},
        {0x1f8e, U"\U00001f06\U000003b9"},
        {0x1f8f, U"\U00001f07\U000003b9"},
        {0x1f90, U"\U00001f20\U000003b9"},
        {0x1f91, U"\U00001f21\U000003b9"},
        {0x1f92, U"\U00001f22\U000003b9"},
        {0x1f93, U"\U00001f23\U000003b9"},
        {0x1f94, U"\U00001f24\U000003b9"},
        {0x1f95, U"\U00001f25\U000003b9"},
        {0x1f96, U"\U00001f26\U000003b9"},
        {0x1f97, U"\U00001f27\U000003b9"},
        {0x1f98, U"\U00001f20\U000003b9"},
        {0x1f99, U"\U00001f21\U000003b9"},
        {0x1f9a, U"\U00001f22\U000003b9"},
        {0x1f9b, U"\U00001f23\U000003b9"},
        {0x1f9c, U"\U00001f24\U000003b9"},
        {0x1f9d, U"\U00001f25\U000003b9"},
        {0x1f9e, U"\U00001f26\U000003b9"},
        {0x1f9f, U"\U00001f27\U000003b9"},
        {0x1fa0, U"\U00001f60\U000003b9"},
        {0x1fa1, U"\U00001f61\U000003b9"},
        {0x1fa2, U"\U00001f62\U000003b9"},
        {0x1fa3, U"\U00001f63\U000003b9"},
        {0x1fa4, U"\U00001f64\U000003b9"},
        {0x1fa5, U"\U00001f65\U000003b9"},
        {0x1fa6, U"\U00001f66\U000003b9"},
        {0x1fa7, U"\U00001f67\U000003b9"},
        {0x1fa8, U"\U00001f60\U000003b9"},
        {0x1fa9, U"\U00001f61\U000003b9"},
        {0x1faa, U"\U00001f62\U000003b9"},
        {0x1fab, U"\U00001f63\U000003b9"},
        {0x1fac, U"\U00001f64\U000003b9"},
        {0x1fad, U"\U00001f65\U000003b9"},
        {0x1fae, U"\U00001f66\U000003b9"},
        {0x1faf, U"\U00001f67\U000003b9"},
        {0x1fb2, U"\U00001f70\U000003b9"},
        {0x1fb3, U"\U000003b1\U000003b9"},
        {0x1fb4, U"\U000003ac\U000003b9"},
        {0x1fb6, U"\U000003b1\U00000342"},
        {0x1fb7, U"\U000003b1\U00000342\U000003b9"},
        {0x1fbc, U"\U000003b1\U000003b9"},
        {0x1fc2, U"\U00001f74\U000003b9"},
        {0x1fc3, U"\U000003b7\U000003b9"},
        {0x1fc4, U"\U000003ae\U000003b9"},
        {0x1fc6, U"\U000003b7\U00000342"},
        {0x1fc7, U"\U000003b7\U00000342\U000003b9"},
        {0x1fcc, U"\U000003b7\U000003b9"},
        {0x1fd2, U"\U000003b9\U00000308\U00000300"},
        {0x1fd3, U"\U000003b9\U00000308\U00000301"},
        {0x1fd6, U"\U000003b9\U00000342"},
        {0x1fd7, U"\U000003b9\U00000308\U00000342"},
        {0x1fe2, U"\U000003c5\U00000308\U00000300"},
        {0x1fe3, U"\U000003c5\U00000308\U00000301"},
        {0x1fe4, U"\U000003c1\U00000313"},
        {0x1fe6, U"\U000003c5\U00000342"},
        {0x1fe7, U"\U000003c5\U00000308\U00000342"},
        {0x1ff2, U"\U00001f7c\U000003b9"},
        {0x1ff3, U"\U000003c9\U000003b9"},
        {0x1ff4, U"\U000003ce\U000003b9"},
        {0x1ff6, U"\U000003c9\U00000342"},
        {0x1ff7, U"\U000003c9\U00000342\U000003b9"},
        {0x1ffc, U"\U000003c9\U000003b9"},
        {0xfb00, U"\U00000066\U00000066"},
        {0xfb01, U"\U00000066\U00000069"},
        {0xfb02, U"\U00000066\U0000006c"},
        {0xfb03, U"\U00000066\U00000066\U00000069"},
        {0xfb04, U"\U00000066\U00000066\U0000006c"},
        {0xfb05, U"\U00000073\U00000074"},
        {0xfb06, U"\U00000073\U00000074"},
        {0xfb13, U"\U00000574\U00000576"},
        {0xfb14, U"\U00000574\U00000565"},
        {0xfb15, U"\U00000574\U0000056b"},
        {0xfb16, U"\U0000057e\U00000576"},
        {0xfb17, U"\U00000574\U0000056d"},
    };
    std::u32string result;
    for (std::size_t i = 0; i < s.size();) {
        const auto lead = static_cast<unsigned char>(s[i++]);
        char32_t cp = lead;
        unsigned remaining = 0;
        if (lead >= 0xc0 && lead < 0xe0) {
            cp = lead & 31;
            remaining = 1;
        } else if (lead >= 0xe0 && lead < 0xf0) {
            cp = lead & 15;
            remaining = 2;
        } else if (lead >= 0xf0) {
            cp = lead & 7;
            remaining = 3;
        }
        Require(i + remaining <= s.size(), "MESH_PATH");
        while (remaining--) {
            auto c = static_cast<unsigned char>(s[i++]);
            Require((c & 0xc0) == 0x80, "MESH_PATH");
            cp = (cp << 6) | (c & 63);
        }
        bool expanded = false;
        for (const auto &e : expansions)
            if (cp == e.from) {
                result += e.to;
                expanded = true;
                break;
            }
        if (expanded)
            continue;
        for (const auto &r : ranges)
            if (cp >= r.first && cp <= r.last && (cp - r.first) % r.step == 0) {
                cp = static_cast<char32_t>(static_cast<std::int64_t>(cp) + r.delta);
                break;
            }
        result += cp;
    }
    return result;
}
bool PathEq(const Value &a, const Value &b) { return Fold(Path(a)) == Fold(Path(b)); }
const Object &Identity(const Value &v) {
    const auto &o = Closed(v, {"session_id", "pid", "started", "project_uuid", "main_hwnd"});
    for (auto k : {"session_id", "started", "project_uuid"})
        Require(Text(At(o, k)), "IDENTITY_VALUE");
    Require(Positive(At(o, "pid")) && Positive(At(o, "main_hwnd")), "IDENTITY_VALUE");
    return o;
}
const Value &Getter(const Array &rows, std::string_view name) {
    const Value *found = nullptr;
    for (const auto &v : rows) {
        const auto &o = Obj(v);
        if (Eq(At(o, "call"), "substance_painter.project." + std::string(name)) &&
            Eq(At(o, "args"), Object{{"selector", Object{}}, {"parameters", Object{}}})) {
            Require(!found && !o.contains("raised"), "PROJECT_GETTER");
            found = &At(o, "value");
        }
    }
    Require(found != nullptr, "PROJECT_GETTER");
    return *found;
}
void Pattern(const Value &v) {
    if (v.IsObject())
        Require(Text(At(Closed(v, {"unavailable"}), "unavailable")), "PATTERN_UNAVAILABLE");
    else
        Require(v.IsString() || v.IsInt() || v.IsBool(), "PATTERN_VALUE");
}
const Object &Snapshot(const Value &v, bool physical, const Object &identity) {
    const auto &s = physical ? Closed(v, {"tree", "values", "dialog", "expanded_by_click"})
                             : Closed(v, {"tree", "values", "dialog"});
    if (physical)
        Require(At(s, "expanded_by_click").IsBool(), "EXPANSION_STATE");
    const auto &d = Closed(At(s, "dialog"), {"hwnd", "pid"});
    Require(Positive(At(d, "hwnd")) && !Eq(At(d, "hwnd"), At(identity, "main_hwnd")) &&
                Eq(At(d, "pid"), At(identity, "pid")),
            "DIALOG_IDENTITY");
    const auto &tree = Arr(At(s, "tree"));
    Require(!tree.empty(), "TREE_MISSING");
    for (const auto &row : tree) {
        const auto &o =
            Closed(row, {"control_type", "automation_id", "class_name", "text", "enabled", "box"});
        for (auto k : {"control_type", "automation_id", "class_name", "text"})
            Require(At(o, k).IsString(), "TREE_VALUE");
        const auto &box = Arr(At(o, "box"));
        Require(At(o, "enabled").IsBool() && box.size() == 4, "TREE_VALUE");
        for (const auto &n : box)
            Require(n.IsInt(), "TREE_VALUE");
    }
    const auto &values = Arr(At(s, "values"));
    Require(!values.empty(), "VALUES_MISSING");
    for (const auto &row : values) {
        const auto &o = Closed(row, {"label", "type", "automation_id", "enabled", "value", "toggle",
                                     "selected", "visible", "process_id"});
        for (auto k : {"label", "type", "automation_id"})
            Require(At(o, k).IsString(), "ROW_VALUE");
        Require(At(o, "enabled").IsBool() && At(o, "visible").IsBool() && Positive(At(o, "process_id")),
                "ROW_VALUE");
        for (auto k : {"value", "toggle", "selected"})
            Pattern(At(o, k));
    }
    return s;
}
void Target(const Object &s, int which, const Value &pid) {
    constexpr std::array<std::string_view, 4> suffix{
        "perFragBinormalCheckBox", "useUvTilesGroupBox",
        "physical_size_section.content.PhysicalSizeSettings.useMeshInternalUnit",
        "physical_size_section.content.PhysicalSizeSettings.useCustomUnit"};
    constexpr std::array<std::string_view, 4> label{
        "Compute tangent space per fragment", "Use UV Tile workflow",
        "Use mesh file's internal unit scale (recommended)", "Custom unit scale"};
    std::string id = std::string(kPrefix) + std::string(suffix[which]);
    const Object *row = nullptr;
    const Object *node = nullptr;
    for (const auto &v : Arr(At(s, "values")))
        if (Eq(At(Obj(v), "automation_id"), id)) {
            Require(!row, "SELECTOR_AMBIGUOUS");
            row = &Obj(v);
        }
    for (const auto &v : Arr(At(s, "tree")))
        if (Eq(At(Obj(v), "automation_id"), id)) {
            Require(!node, "SELECTOR_AMBIGUOUS");
            node = &Obj(v);
        }
    Require(row && node, "SELECTOR_AMBIGUOUS");
    Value kind = which < 2 ? "CheckBox" : "RadioButton";
    Require(Eq(At(*row, "type"), kind) && Eq(At(*node, "control_type"), kind) &&
                Eq(At(*row, "label"), label[which]) && Eq(At(*node, "text"), label[which]) &&
                Eq(At(*row, "enabled"), At(*node, "enabled")) && Eq(At(*row, "visible"), true) &&
                Eq(At(*row, "process_id"), pid),
            "SELECTOR_IDENTITY");
    Require(Eq(At(*row, which < 2 ? "toggle" : "selected"), which == 2 ? 1 : 0), "NON_TARGET_STATE");
}
void Panel(const Value &value, const Array &outputs) {
    const auto &p =
        Closed(value, {"schema", "boundary", "condition", "binding", "mesh_import", "ui", "images"});
    const auto &boundary = Str(At(p, "boundary"));
    Require(std::find(kBoundaries.begin(), kBoundaries.end(), boundary) != kBoundaries.end(), "BOUNDARY");
    Require(Eq(At(p, "schema"), "uzpainter/parity/settings-panel-readback/1") &&
                Eq(At(p, "condition"), Condition(boundary)),
            "SCHEMA");
    const auto &b = Closed(At(p, "binding"), {"before", "after", "context_before_sha256",
                                              "context_after_sha256", "context_after_outputs"});
    const auto &identity = Identity(At(b, "before"));
    Identity(At(b, "after"));
    Require(Eq(At(b, "before"), At(b, "after")), "IDENTITY_CHANGED");
    Object frame{{"schema", "uzpainter/parity/filter-context-readback/1"},
                 {"boundary", boundary},
                 {"condition", At(p, "condition")},
                 {"outputs", outputs}};
    if (auto failure = ValidateFilterContextFrame(frame))
        throw Failure{failure->detail};
    frame["outputs"] = At(b, "context_after_outputs");
    if (auto failure = ValidateFilterContextFrame(frame))
        throw Failure{failure->detail};
    Require(Eq(At(b, "context_before_sha256"), Hash(outputs)) &&
                Eq(At(b, "context_after_sha256"), Hash(At(b, "context_after_outputs"))) &&
                Eq(outputs, At(b, "context_after_outputs")),
            "CONTEXT_CHANGED");
    Require(Eq(Getter(outputs, "get_uuid"), At(identity, "project_uuid")), "PROJECT_UUID");
    Require(Getter(outputs, "needs_saving").IsBool(), "NEEDS_SAVING");
    const auto &mesh = Closed(At(p, "mesh_import"), {"input_id", "resolved_path", "before", "after"});
    Require(Eq(At(mesh, "input_id"), "plane"), "MESH_INPUT");
    auto path = Path(At(mesh, "resolved_path"));
    auto suffix = path.size() >= 4 ? path.substr(path.size() - 4) : std::string{};
    for (char &c : suffix)
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    Require(suffix == ".obj" && path.substr(path.find_last_of('\\') + 1).size() > 4, "MESH_FORMAT");
    for (auto side : {"before", "after"}) {
        const auto &pin = Closed(At(mesh, side), {"sha256", "size_bytes"});
        Require(Eq(At(pin, "sha256"), kPlane) && Positive(At(pin, "size_bytes")), "MESH_PIN");
    }
    Require(Eq(At(mesh, "before"), At(mesh, "after")), "MESH_CHANGED");
    Require(PathEq(Getter(outputs, "last_imported_mesh_path"), At(mesh, "resolved_path")), "IMPORTED_PATH");
    const auto &ui = Closed(At(p, "ui"), {"configuration", "physical_size"});
    const auto &config = Snapshot(At(ui, "configuration"), false, identity);
    const auto &physical = Snapshot(At(ui, "physical_size"), true, identity);
    Require(Eq(At(config, "dialog"), At(physical, "dialog")), "DIALOG_CHANGED");
    for (int i = 0; i < 2; ++i)
        Target(config, i, At(identity, "pid"));
    for (int i = 0; i < 4; ++i)
        Target(physical, i, At(identity, "pid"));
    const auto &images = Arr(At(p, "images"));
    Require(images.size() == 2, "IMAGES_MISSING");
    for (std::size_t i = 0; i < 2; ++i) {
        const auto &image = Closed(images[i], {"output_id", "hwnd", "pid"});
        Require(Eq(At(image, "output_id"),
                   "settings/" + boundary + (i == 0 ? "/configuration-image" : "/physical-size-image")) &&
                    Eq(Object{{"hwnd", At(image, "hwnd")}, {"pid", At(image, "pid")}}, At(config, "dialog")),
                "IMAGE_BINDING");
    }
}
void Sequence(const Array &panels) {
    Require(panels.size() == 5, "BOUNDARY_SEQUENCE");
    for (std::size_t i = 0; i < 5; ++i) {
        const auto &p = Obj(panels[i]);
        Require(Eq(At(p, "boundary"), kBoundaries[i]), "BOUNDARY_SEQUENCE");
        Require(Eq(At(Obj(At(p, "binding")), "before"), At(Obj(At(Obj(panels[0]), "binding")), "before")),
                "SESSION_CHANGED");
        Require(Eq(At(p, "mesh_import"), At(Obj(panels[0]), "mesh_import")), "IMPORT_CHANGED");
    }
}
std::uint32_t U32(std::string_view s, std::size_t i) {
    return (std::uint32_t(static_cast<unsigned char>(s[i])) << 24) |
           (std::uint32_t(static_cast<unsigned char>(s[i + 1])) << 16) |
           (std::uint32_t(static_cast<unsigned char>(s[i + 2])) << 8) | static_cast<unsigned char>(s[i + 3]);
}
void Png(std::string_view bytes) {
    constexpr std::size_t chunk_limit = 64 * 1024 * 1024, decoded_limit = 256 * 1024 * 1024;
    Require(bytes.size() >= 8 && bytes.substr(0, 8) == std::string_view("\x89PNG\r\n\x1a\n", 8),
            "PNG_DECODE");
    std::size_t pos = 8, ancillary = 0;
    bool ended = false;
    std::vector<std::string_view> idat;
    while (pos < bytes.size()) {
        Require(bytes.size() - pos >= 12, "PNG_DECODE");
        auto len = U32(bytes, pos);
        Require(len <= chunk_limit && len <= bytes.size() - pos - 12, "PNG_DECODE");
        auto type = bytes.substr(pos + 4, 4);
        auto data = bytes.substr(pos + 8, len);
        Require(pos != 8 || (type == "IHDR" && len == 13), "PNG_DECODE");
        auto crc = crc32(0, reinterpret_cast<const Bytef *>(bytes.data() + pos + 4), len + 4);
        Require(crc == U32(bytes, pos + 8 + len), "PNG_DECODE");
        if (static_cast<unsigned char>(type[0]) & 32) {
            Require(len <= chunk_limit - ancillary, "PNG_DECODE");
            ancillary += len;
        }
        if (type == "IDAT")
            idat.push_back(data);
        pos += len + 12;
        if (type == "IEND") {
            Require(len == 0 && pos == bytes.size(), "PNG_DECODE");
            ended = true;
            break;
        }
    }
    Require(ended && !idat.empty(), "PNG_DECODE");
    std::unique_ptr<spng_ctx, decltype(&spng_ctx_free)> ctx(spng_ctx_new(0), &spng_ctx_free);
    Require(bool(ctx), "PNG_DECODE");
    Require(!spng_set_image_limits(ctx.get(), 8192, 8192) &&
                !spng_set_chunk_limits(ctx.get(), chunk_limit, chunk_limit) &&
                !spng_set_crc_action(ctx.get(), SPNG_CRC_ERROR, SPNG_CRC_ERROR) &&
                !spng_set_png_buffer(ctx.get(), bytes.data(), bytes.size()),
            "PNG_DECODE");
    spng_ihdr ihdr{};
    Require(!spng_get_ihdr(ctx.get(), &ihdr), "PNG_DECODE");
    constexpr std::array<unsigned, 7> channels{1, 0, 3, 1, 2, 0, 4};
    Require(ihdr.color_type < channels.size(), "PNG_DECODE");
    const std::uint64_t bits = channels[ihdr.color_type] * ihdr.bit_depth;
    std::uint64_t expected_raw = 0;
    if (!ihdr.interlace_method)
        expected_raw = (1 + (ihdr.width * bits + 7) / 8) * ihdr.height;
    else {
        constexpr std::array<unsigned, 7> x{0, 4, 0, 2, 0, 1, 0}, y{0, 0, 4, 0, 2, 0, 1};
        constexpr std::array<unsigned, 7> dx{8, 8, 4, 4, 2, 2, 1}, dy{8, 8, 8, 4, 4, 2, 2};
        for (std::size_t i = 0; i < 7; ++i)
            if (ihdr.width > x[i] && ihdr.height > y[i]) {
                const auto w = (ihdr.width - x[i] + dx[i] - 1) / dx[i],
                           h = (ihdr.height - y[i] + dy[i] - 1) / dy[i];
                expected_raw += (1 + (w * bits + 7) / 8) * h;
            }
    }
    std::size_t size = 0;
    Require(!spng_decoded_image_size(ctx.get(), SPNG_FMT_RGBA8, &size) && size > 0 && size <= decoded_limit,
            "PNG_DECODE");
    std::vector<unsigned char> decoded(size);
    Require(!spng_decode_image(ctx.get(), decoded.data(), size, SPNG_FMT_RGBA8, 0) &&
                !spng_decode_chunks(ctx.get()),
            "PNG_DECODE");
    // libspng's last scanline can finish before inflate observes the stream
    // trailer.
    z_stream stream{};
    Require(inflateInit(&stream) == Z_OK, "PNG_DECODE");
    struct End {
        z_stream *s;
        ~End() { inflateEnd(s); }
    } end{&stream};
    std::array<unsigned char, 65536> scratch{};
    bool stream_end = false;
    std::size_t total = 0;
    for (auto block : idat) {
        Require(!stream_end || block.empty(), "PNG_DECODE");
        if (block.empty())
            continue;
        stream.next_in = reinterpret_cast<Bytef *>(const_cast<char *>(block.data()));
        stream.avail_in = static_cast<uInt>(block.size());
        while (!stream_end) {
            stream.next_out = scratch.data();
            stream.avail_out = static_cast<uInt>(scratch.size());
            auto previous = stream.avail_in;
            int result = inflate(&stream, Z_NO_FLUSH);
            total += scratch.size() - stream.avail_out;
            if (result == Z_BUF_ERROR && !stream.avail_in && stream.avail_out == scratch.size())
                break;
            Require(total <= expected_raw, "PNG_DECODE");
            Require(result == Z_OK || result == Z_STREAM_END, "PNG_DECODE");
            stream_end = result == Z_STREAM_END;
            Require(stream_end || previous != stream.avail_in || stream.avail_out < scratch.size(),
                    "PNG_DECODE");
            if (!stream.avail_in && stream.avail_out)
                break;
        }
        Require(!stream_end || stream.avail_in == 0, "PNG_DECODE");
    }
    Require(stream_end && total == expected_raw, "PNG_DECODE");
}
std::string RecordHash(const AdmittedFilterCapture &capture) {
    const AdmittedRef *record = nullptr;
    for (const auto &ref : capture.Refs())
        if (ref.record_id == "golden-record" && ref.kind == "private_oracle_record") {
            Require(!record, "REFERENCES");
            record = &ref;
        }
    Require(record != nullptr, "REFERENCES");
    return record->sha256;
}
ImportRefusal Refusal(const Failure &f) { return {std::string(kFilterCaptureInvalid), f.code}; }
} // namespace

std::optional<ImportRefusal> ValidateFilterSettingsImage(std::string_view bytes) {
    try {
        Png(bytes);
        return std::nullopt;
    } catch (const Failure &f) {
        return Refusal(f);
    }
}

std::expected<CheckedSettingsPanels, ImportRefusal>
CheckFilterSettingsPanels(const AdmittedFilterCapture &capture) {
    try {
        CheckedSettingsPanels checked;
        checked.admission_identity_ = capture.Identity();
        checked.original_record_sha256_ = RecordHash(capture);
        checked.stripped_record_ = capture.Record();
        auto &recordings = std::get<Array>(checked.stripped_record_.at("recordings").data);
        const std::regex context("context/([a-z0-9-]+)/[0-9]{4}-[A-Za-z_][A-Za-z0-9_]*");
        for (auto &recording : recordings) {
            auto &r = std::get<Object>(recording.data);
            const auto outputs = Arr(At(r, "outputs"));
            Array kept;
            for (std::size_t i = 0; i < outputs.size();) {
                const auto &o = Obj(outputs[i]);
                const auto &id = Str(At(o, "output_id"));
                std::smatch match;
                if (!std::regex_match(id, match, context)) {
                    Require(!id.starts_with("settings/") &&
                                (!o.contains("kind") || (!Eq(At(o, "kind"), "settings_panel_readback") &&
                                                         !Eq(At(o, "kind"), "settings_panel_evidence"))),
                            "UNEXPECTED_SLOT");
                    kept.push_back(outputs[i++]);
                    continue;
                }
                std::string boundary = match[1];
                Array leaves;
                while (i < outputs.size()) {
                    const auto &next = Str(At(Obj(outputs[i]), "output_id"));
                    if (!std::regex_match(next, match, context) || match[1] != boundary)
                        break;
                    leaves.push_back(outputs[i]);
                    kept.push_back(outputs[i++]);
                }
                Require(outputs.size() - i >= 3, "SLOTS_MISSING");
                const auto &slot = Closed(outputs[i], {"output_id", "kind", "panel", "values"});
                Require(Eq(At(slot, "output_id"), "settings/" + boundary + "/panel") &&
                            Eq(At(slot, "kind"), "settings_panel_readback") &&
                            Eq(At(slot, "panel"), "Project Configuration"),
                        "SLOT_IDENTITY");
                const auto &panel = At(slot, "values");
                Panel(panel, leaves);
                const auto &p = Obj(panel);
                Require(
                    Eq(At(p, "boundary"), boundary) && Eq(At(p, "condition"), At(r, "condition")) &&
                        Eq(At(Obj(At(Obj(At(p, "binding")), "before")), "session_id"), At(r, "session_id")),
                    "RECORDING_BINDING");
                for (std::size_t j = 0; j < 2; ++j) {
                    const auto &shot = Closed(outputs[i + j + 1], {"output_id", "kind", "panel", "blob"});
                    const auto &blob = Closed(At(shot, "blob"), {"sha256", "size_bytes", "media_type"});
                    const auto &image = Obj(Arr(At(p, "images"))[j]);
                    Require(Eq(At(shot, "output_id"), At(image, "output_id")) &&
                                Eq(At(shot, "kind"), "settings_panel_evidence") &&
                                Eq(At(shot, "panel"), "Project Configuration") &&
                                Eq(At(blob, "media_type"), "image/png") && Positive(At(blob, "size_bytes")),
                            "PNG_BINDING");
                    auto imageid = Str(At(r, "recording_id")) + "-" + Str(At(image, "output_id"));
                    std::replace(imageid.begin(), imageid.end(), '/', '-');
                    const AdmittedRef *ref = nullptr;
                    for (const auto &candidate : capture.Refs())
                        if (candidate.record_id == imageid) {
                            Require(!ref, "REFERENCES");
                            ref = &candidate;
                        }
                    Require(ref && Eq(At(blob, "sha256"), ref->sha256) &&
                                Eq(At(blob, "size_bytes"), ref->size_bytes),
                            "PNG_BINDING");
                    const auto *bytes = capture.Image(imageid);
                    Require(bytes != nullptr, "IMAGE_BYTES");
                    Png(*bytes);
                }
                checked.panels_.push_back(panel);
                i += 3;
            }
            r["outputs"] = std::move(kept);
        }
        Sequence(checked.panels_);
        return checked;
    } catch (const Failure &f) {
        return std::expected<CheckedSettingsPanels, ImportRefusal>(std::unexpect, Refusal(f));
    }
}

std::expected<ValidatedFilterSettings, ImportRefusal>
DeriveFilterSettings(const AdmittedFilterCapture &capture, const CheckedSettingsPanels &panels,
                     const ValidatedFilterTrace &trace) {
    try {
        const auto identity = capture.Identity();
        const auto hash = RecordHash(capture);
        Require(Eq(identity, panels.AdmissionIdentity()) && Eq(identity, trace.AdmissionIdentity()) &&
                    hash == panels.OriginalRecordSha256() && hash == trace.OriginalRecordSha256(),
                "CONTEXT_EVIDENCE");
        Require(core::Sha256Hex(capture.PlaneBytes()) == kPlane, "MESH_BYTES");
        const auto &frames = trace.Contexts();
        Require(frames.size() == 5 && panels.Panels().size() == 5, "CONTEXT_EVIDENCE");
        for (std::size_t i = 0; i < 5; ++i) {
            const auto &frame = Obj(frames[i]);
            const auto &p = Obj(panels.Panels()[i]);
            Panel(p, Arr(At(frame, "outputs")));
            Require(Eq(At(p, "boundary"), At(frame, "boundary")) &&
                        Eq(At(p, "condition"), At(frame, "condition")),
                    "CONTEXT_BOUNDARY");
            const auto &pin = Obj(At(Obj(At(p, "mesh_import")), "before"));
            Require(Eq(At(pin, "size_bytes"), static_cast<std::uint64_t>(capture.PlaneBytes().size())),
                    "MESH_SIZE");
        }
        Sequence(panels.Panels());
        ValidatedFilterSettings result;
        result.admission_identity_ = identity;
        result.original_record_sha256_ = hash;
        return result;
    } catch (const Failure &f) {
        return std::expected<ValidatedFilterSettings, ImportRefusal>(std::unexpect, Refusal(f));
    }
}
} // namespace uzp::procedural
