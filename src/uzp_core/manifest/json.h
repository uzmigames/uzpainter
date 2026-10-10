#pragma once

// JSON values, a strict parser and the canonical writer of the project manifest
// (`docs/architecture/09-project-file-format.md` §1, §5; `03-project-model.md` §7).
//
// Canonical form: UTF-8, no insignificant whitespace, object keys sorted by their UTF-8 bytes
// (code-point order), integers in plain decimal, other numbers in the shortest round-trip form
// with Python's `repr` layout (`1.0`, `0.0001`, `1e-05`, `1e+16`), strings escaped only where
// JSON requires it (`\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t`, other controls as `\u00xx`). The
// bytes equal Python's `json.dumps(v, sort_keys=True, separators=(",", ":"),
// ensure_ascii=False)` (`tools/parity/recorder/job.py`, `canonical_json`), so tools written in
// either language compute the same SHA-256.
//
// The parser accepts RFC 8259 JSON and rejects duplicate object keys, invalid UTF-8, lone
// surrogate escapes, non-finite numbers and integers outside the signed 64-bit range: a
// manifest that parses has exactly one canonical form.

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace uzp::core::json {

struct Value;
using Array = std::vector<Value>;
using Object = std::map<std::string, Value, std::less<>>;

struct Value {
    std::variant<std::nullptr_t, bool, std::int64_t, double, std::string, Array, Object> data;

    Value() : data(nullptr) {}
    Value(std::nullptr_t) : data(nullptr) {}
    Value(bool b) : data(b) {}
    Value(int i) : data(static_cast<std::int64_t>(i)) {}
    Value(std::int64_t i) : data(i) {}
    Value(std::uint64_t i);  // throws std::out_of_range above INT64_MAX
    Value(double d);         // throws std::domain_error when not finite
    Value(const char* s) : data(std::string(s)) {}
    Value(std::string s) : data(std::move(s)) {}
    Value(std::string_view s) : data(std::string(s)) {}
    Value(Array a) : data(std::move(a)) {}
    Value(Object o) : data(std::move(o)) {}

    bool IsNull() const { return std::holds_alternative<std::nullptr_t>(data); }
    bool IsBool() const { return std::holds_alternative<bool>(data); }
    bool IsInt() const { return std::holds_alternative<std::int64_t>(data); }
    bool IsDouble() const { return std::holds_alternative<double>(data); }
    bool IsNumber() const { return IsInt() || IsDouble(); }
    bool IsString() const { return std::holds_alternative<std::string>(data); }
    bool IsArray() const { return std::holds_alternative<Array>(data); }
    bool IsObject() const { return std::holds_alternative<Object>(data); }

    bool operator==(const Value& other) const = default;
};

/// A syntax error, with the byte offset where parsing stopped.
class ParseError : public std::runtime_error {
public:
    ParseError(const std::string& message, std::size_t offset);
    std::size_t offset() const { return offset_; }

private:
    std::size_t offset_;
};

/// Parses one JSON text (surrounding whitespace allowed, nothing else after it).
Value Parse(std::string_view text);

/// The canonical serialisation described above.
std::string WriteCanonical(const Value& value);

/// The canonical text of a finite double (Python `repr` layout).
std::string FormatDouble(double value);

}  // namespace uzp::core::json
