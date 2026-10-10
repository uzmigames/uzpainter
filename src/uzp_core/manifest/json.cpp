#include "uzp_core/manifest/json.h"

#include <charconv>
#include <cmath>
#include <cstdio>
#include <limits>
#include <system_error>

namespace uzp::core::json {

Value::Value(std::uint64_t i) {
    if (i > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
        throw std::out_of_range("JSON integer above the signed 64-bit range");
    }
    data = static_cast<std::int64_t>(i);
}

Value::Value(double d) {
    if (!std::isfinite(d)) throw std::domain_error("JSON numbers must be finite");
    data = d;
}

ParseError::ParseError(const std::string& message, std::size_t offset)
    : std::runtime_error(message + " at byte " + std::to_string(offset)), offset_(offset) {}

namespace {

constexpr int kMaxDepth = 512;

class Parser {
public:
    explicit Parser(std::string_view text) : text_(text) {}

    Value Document() {
        SkipSpace();
        Value value = ParseValue(0);
        SkipSpace();
        if (pos_ != text_.size()) Fail("unexpected data after the JSON value");
        return value;
    }

private:
    [[noreturn]] void Fail(const std::string& message) const { throw ParseError(message, pos_); }

    void SkipSpace() {
        while (pos_ < text_.size()) {
            const char c = text_[pos_];
            if (c != ' ' && c != '\t' && c != '\n' && c != '\r') break;
            ++pos_;
        }
    }

    bool Consume(std::string_view literal) {
        if (text_.substr(pos_, literal.size()) != literal) return false;
        pos_ += literal.size();
        return true;
    }

    Value ParseValue(int depth) {
        if (depth > kMaxDepth) Fail("nesting deeper than 512 levels");
        if (pos_ >= text_.size()) Fail("unexpected end of input");
        switch (text_[pos_]) {
            case '{': return ParseObject(depth);
            case '[': return ParseArray(depth);
            case '"': return Value(ParseString());
            case 't':
                if (Consume("true")) return Value(true);
                break;
            case 'f':
                if (Consume("false")) return Value(false);
                break;
            case 'n':
                if (Consume("null")) return Value(nullptr);
                break;
            default:
                if (text_[pos_] == '-' || (text_[pos_] >= '0' && text_[pos_] <= '9')) {
                    return ParseNumber();
                }
        }
        Fail("invalid JSON value");
    }

    Value ParseObject(int depth) {
        ++pos_;  // '{'
        Object object;
        SkipSpace();
        if (pos_ < text_.size() && text_[pos_] == '}') {
            ++pos_;
            return Value(std::move(object));
        }
        while (true) {
            SkipSpace();
            if (pos_ >= text_.size() || text_[pos_] != '"') Fail("expected an object key");
            const std::size_t key_offset = pos_;
            std::string key = ParseString();
            SkipSpace();
            if (pos_ >= text_.size() || text_[pos_] != ':') Fail("expected ':'");
            ++pos_;
            SkipSpace();
            Value value = ParseValue(depth + 1);
            if (!object.emplace(std::move(key), std::move(value)).second) {
                throw ParseError("duplicate object key", key_offset);
            }
            SkipSpace();
            if (pos_ >= text_.size()) Fail("unexpected end of input in an object");
            if (text_[pos_] == ',') {
                ++pos_;
                continue;
            }
            if (text_[pos_] == '}') {
                ++pos_;
                return Value(std::move(object));
            }
            Fail("expected ',' or '}'");
        }
    }

    Value ParseArray(int depth) {
        ++pos_;  // '['
        Array array;
        SkipSpace();
        if (pos_ < text_.size() && text_[pos_] == ']') {
            ++pos_;
            return Value(std::move(array));
        }
        while (true) {
            SkipSpace();
            array.push_back(ParseValue(depth + 1));
            SkipSpace();
            if (pos_ >= text_.size()) Fail("unexpected end of input in an array");
            if (text_[pos_] == ',') {
                ++pos_;
                continue;
            }
            if (text_[pos_] == ']') {
                ++pos_;
                return Value(std::move(array));
            }
            Fail("expected ',' or ']'");
        }
    }

    unsigned Hex4() {
        if (pos_ + 4 > text_.size()) Fail("truncated \\u escape");
        unsigned value = 0;
        for (int i = 0; i < 4; ++i) {
            const char c = text_[pos_++];
            value <<= 4;
            if (c >= '0' && c <= '9') value |= static_cast<unsigned>(c - '0');
            else if (c >= 'a' && c <= 'f') value |= static_cast<unsigned>(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') value |= static_cast<unsigned>(c - 'A' + 10);
            else Fail("invalid hex digit in \\u escape");
        }
        return value;
    }

    static void AppendUtf8(std::string& out, std::uint32_t cp) {
        if (cp < 0x80) {
            out += static_cast<char>(cp);
        } else if (cp < 0x800) {
            out += static_cast<char>(0xC0 | (cp >> 6));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        } else if (cp < 0x10000) {
            out += static_cast<char>(0xE0 | (cp >> 12));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        } else {
            out += static_cast<char>(0xF0 | (cp >> 18));
            out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
            out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (cp & 0x3F));
        }
    }

    /// Copies one raw UTF-8 sequence starting at `pos_`, rejecting malformed, overlong and
    /// surrogate encodings.
    void CopyUtf8(std::string& out) {
        const auto byte = [&](std::size_t i) { return static_cast<unsigned char>(text_[i]); };
        const unsigned char lead = byte(pos_);
        std::size_t length = 0;
        std::uint32_t cp = 0;
        if (lead >= 0xC2 && lead <= 0xDF) {
            length = 2;
            cp = lead & 0x1Fu;
        } else if (lead >= 0xE0 && lead <= 0xEF) {
            length = 3;
            cp = lead & 0x0Fu;
        } else if (lead >= 0xF0 && lead <= 0xF4) {
            length = 4;
            cp = lead & 0x07u;
        } else {
            Fail("invalid UTF-8 lead byte");
        }
        if (pos_ + length > text_.size()) Fail("truncated UTF-8 sequence");
        for (std::size_t i = 1; i < length; ++i) {
            const unsigned char c = byte(pos_ + i);
            if ((c & 0xC0) != 0x80) Fail("invalid UTF-8 continuation byte");
            cp = (cp << 6) | (c & 0x3Fu);
        }
        if ((length == 3 && cp < 0x800) || (length == 4 && (cp < 0x10000 || cp > 0x10FFFF)) ||
            (cp >= 0xD800 && cp <= 0xDFFF)) {
            Fail("invalid UTF-8 code point");
        }
        out.append(text_.substr(pos_, length));
        pos_ += length;
    }

    std::string ParseString() {
        ++pos_;  // '"'
        std::string out;
        while (true) {
            if (pos_ >= text_.size()) Fail("unterminated string");
            const unsigned char c = static_cast<unsigned char>(text_[pos_]);
            if (c == '"') {
                ++pos_;
                return out;
            }
            if (c < 0x20) Fail("unescaped control character in a string");
            if (c >= 0x80) {
                CopyUtf8(out);
                continue;
            }
            if (c != '\\') {
                out += static_cast<char>(c);
                ++pos_;
                continue;
            }
            ++pos_;
            if (pos_ >= text_.size()) Fail("unterminated escape");
            const char e = text_[pos_++];
            switch (e) {
                case '"': out += '"'; break;
                case '\\': out += '\\'; break;
                case '/': out += '/'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'n': out += '\n'; break;
                case 'r': out += '\r'; break;
                case 't': out += '\t'; break;
                case 'u': {
                    std::uint32_t cp = Hex4();
                    if (cp >= 0xDC00 && cp <= 0xDFFF) Fail("lone low surrogate escape");
                    if (cp >= 0xD800 && cp <= 0xDBFF) {
                        if (!Consume("\\u")) Fail("lone high surrogate escape");
                        const std::uint32_t low = Hex4();
                        if (low < 0xDC00 || low > 0xDFFF) Fail("invalid surrogate pair");
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                    }
                    AppendUtf8(out, cp);
                    break;
                }
                default: Fail("invalid escape");
            }
        }
    }

    Value ParseNumber() {
        const std::size_t start = pos_;
        bool integral = true;
        if (text_[pos_] == '-') ++pos_;
        const auto digits = [&] {
            const std::size_t first = pos_;
            while (pos_ < text_.size() && text_[pos_] >= '0' && text_[pos_] <= '9') ++pos_;
            return pos_ - first;
        };
        if (pos_ < text_.size() && text_[pos_] == '0') {
            ++pos_;
        } else if (digits() == 0) {
            Fail("invalid number");
        }
        if (pos_ < text_.size() && text_[pos_] == '.') {
            integral = false;
            ++pos_;
            if (digits() == 0) Fail("invalid number fraction");
        }
        if (pos_ < text_.size() && (text_[pos_] == 'e' || text_[pos_] == 'E')) {
            integral = false;
            ++pos_;
            if (pos_ < text_.size() && (text_[pos_] == '+' || text_[pos_] == '-')) ++pos_;
            if (digits() == 0) Fail("invalid number exponent");
        }
        const char* first = text_.data() + start;
        const char* last = text_.data() + pos_;
        if (integral) {
            std::int64_t value = 0;
            const auto [ptr, ec] = std::from_chars(first, last, value);
            if (ec != std::errc() || ptr != last) {
                throw ParseError("integer outside the signed 64-bit range", start);
            }
            return Value(value);
        }
        double value = 0.0;
        const auto [ptr, ec] = std::from_chars(first, last, value);
        if (ec != std::errc() || ptr != last || !std::isfinite(value)) {
            throw ParseError("number outside the double range", start);
        }
        return Value(value);
    }

    std::string_view text_;
    std::size_t pos_ = 0;
};

void WriteString(std::string& out, const std::string& text) {
    out += '"';
    for (const char ch : text) {
        const unsigned char c = static_cast<unsigned char>(ch);
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += ch;
                }
        }
    }
    out += '"';
}

void Write(std::string& out, const Value& value) {
    struct Visitor {
        std::string& out;
        void operator()(std::nullptr_t) const { out += "null"; }
        void operator()(bool b) const { out += b ? "true" : "false"; }
        void operator()(std::int64_t i) const { out += std::to_string(i); }
        void operator()(double d) const { out += FormatDouble(d); }
        void operator()(const std::string& s) const { WriteString(out, s); }
        void operator()(const Array& a) const {
            out += '[';
            for (std::size_t i = 0; i < a.size(); ++i) {
                if (i != 0) out += ',';
                Write(out, a[i]);
            }
            out += ']';
        }
        void operator()(const Object& o) const {
            out += '{';
            bool first = true;
            for (const auto& [key, member] : o) {
                if (!first) out += ',';
                first = false;
                WriteString(out, key);
                out += ':';
                Write(out, member);
            }
            out += '}';
        }
    };
    std::visit(Visitor{out}, value.data);
}

}  // namespace

Value Parse(std::string_view text) { return Parser(text).Document(); }

std::string WriteCanonical(const Value& value) {
    std::string out;
    Write(out, value);
    return out;
}

std::string FormatDouble(double value) {
    if (!std::isfinite(value)) throw std::domain_error("JSON numbers must be finite");
    // Shortest round-trip digits in scientific form: "d[.ddd]e(+|-)xx".
    char buf[64];
    const auto result = std::to_chars(buf, buf + sizeof(buf), std::fabs(value),
                                      std::chars_format::scientific);
    const std::string_view sci(buf, static_cast<std::size_t>(result.ptr - buf));
    const std::size_t e_pos = sci.find('e');
    std::string digits;
    for (const char c : sci.substr(0, e_pos)) {
        if (c != '.') digits += c;
    }
    int exponent = 0;
    const std::string_view exp_text = sci.substr(e_pos + 1);
    std::from_chars(exp_text.data() + (exp_text.front() == '+' ? 1 : 0),
                    exp_text.data() + exp_text.size(), exponent);
    const int n = static_cast<int>(digits.size());
    std::string out = std::signbit(value) ? "-" : "";
    if (exponent >= -4 && exponent < 16) {
        const int point = exponent + 1;  // digits before the decimal point
        if (point <= 0) {
            out += "0." + std::string(static_cast<std::size_t>(-point), '0') + digits;
        } else if (point >= n) {
            out += digits + std::string(static_cast<std::size_t>(point - n), '0') + ".0";
        } else {
            out += digits.substr(0, static_cast<std::size_t>(point)) + "." +
                   digits.substr(static_cast<std::size_t>(point));
        }
        return out;
    }
    out += digits.substr(0, 1);
    if (n > 1) out += "." + digits.substr(1);
    char exp_buf[8];
    std::snprintf(exp_buf, sizeof(exp_buf), "e%c%02d", exponent < 0 ? '-' : '+',
                  exponent < 0 ? -exponent : exponent);
    return out + exp_buf;
}

}  // namespace uzp::core::json
