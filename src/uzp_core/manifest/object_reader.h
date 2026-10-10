#pragma once

// Typed access to one JSON object of a manifest, with the JSON path of every error and the
// keys left unread (the unknown keys a struct keeps in `extra`). Internal to `src/uzp_core/`.

#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <variant>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/ids.h"

namespace uzp::core::manifest_detail {

[[noreturn]] inline void Fail(const std::string& path, const std::string& message) {
    throw ManifestError(path + ": " + message);
}

inline const json::Object& AsObject(const json::Value& value, const std::string& path) {
    if (!value.IsObject()) Fail(path, "expected an object");
    return std::get<json::Object>(value.data);
}

inline const json::Array& AsArray(const json::Value& value, const std::string& path) {
    if (!value.IsArray()) Fail(path, "expected an array");
    return std::get<json::Array>(value.data);
}

inline const std::string& AsString(const json::Value& value, const std::string& path) {
    if (!value.IsString()) Fail(path, "expected a string");
    return std::get<std::string>(value.data);
}

inline bool AsBool(const json::Value& value, const std::string& path) {
    if (!value.IsBool()) Fail(path, "expected a boolean");
    return std::get<bool>(value.data);
}

inline std::int64_t AsInt(const json::Value& value, const std::string& path) {
    if (!value.IsInt()) Fail(path, "expected an integer");
    return std::get<std::int64_t>(value.data);
}

inline double AsNumber(const json::Value& value, const std::string& path) {
    if (value.IsInt()) return static_cast<double>(std::get<std::int64_t>(value.data));
    if (!value.IsDouble()) Fail(path, "expected a number");
    return std::get<double>(value.data);
}

inline Id AsId(const json::Value& value, const std::string& path) {
    const std::int64_t id = AsInt(value, path);
    if (id < 0) Fail(path, "an id is not negative");
    return static_cast<Id>(id);
}

template <typename E>
E AsEnum(const json::Value& value, const std::string& path) {
    const std::string& name = AsString(value, path);
    const auto parsed = FromString<E>(name);
    if (!parsed) Fail(path, "unknown member '" + name + "'");
    return *parsed;
}

template <typename E>
E KeyEnum(const std::string& key, const std::string& path) {
    const auto parsed = FromString<E>(key);
    if (!parsed) Fail(path, "unknown member '" + key + "' as a key");
    return *parsed;
}

class ObjectReader {
public:
    ObjectReader(const json::Value& value, std::string path)
        : object_(AsObject(value, path)), path_(std::move(path)) {}

    const std::string& path() const { return path_; }
    std::string Path(std::string_view key) const { return path_ + "." + std::string(key); }

    /// The value of `key`, or nullptr when absent; marks the key as read.
    const json::Value* Get(std::string_view key) {
        const auto it = object_.find(key);
        if (it == object_.end()) return nullptr;
        read_.insert(std::string(key));
        return &it->second;
    }

    /// The value of `key`, or nullptr when absent or null.
    const json::Value* GetOptional(std::string_view key) {
        const json::Value* value = Get(key);
        return value == nullptr || value->IsNull() ? nullptr : value;
    }

    const json::Value& Need(std::string_view key) {
        const json::Value* value = Get(key);
        if (value == nullptr) Fail(path_, "missing key '" + std::string(key) + "'");
        return *value;
    }

    std::string String(std::string_view key) { return AsString(Need(key), Path(key)); }
    bool Bool(std::string_view key) { return AsBool(Need(key), Path(key)); }
    double Number(std::string_view key) { return AsNumber(Need(key), Path(key)); }
    std::int64_t Int(std::string_view key) { return AsInt(Need(key), Path(key)); }
    Id IdValue(std::string_view key) { return AsId(Need(key), Path(key)); }
    const json::Object& Object(std::string_view key) { return AsObject(Need(key), Path(key)); }
    const json::Array& Array(std::string_view key) { return AsArray(Need(key), Path(key)); }

    template <typename E>
    E Enum(std::string_view key) {
        return AsEnum<E>(Need(key), Path(key));
    }

    std::optional<std::string> OptionalString(std::string_view key) {
        const json::Value* value = GetOptional(key);
        if (value == nullptr) return std::nullopt;
        return AsString(*value, Path(key));
    }

    /// The keys not read so far, kept verbatim.
    json::Object Rest() const {
        json::Object rest;
        for (const auto& [key, value] : object_) {
            if (!read_.contains(key)) rest.emplace(key, value);
        }
        return rest;
    }

private:
    const json::Object& object_;
    std::string path_;
    std::set<std::string, std::less<>> read_;
};

}  // namespace uzp::core::manifest_detail
