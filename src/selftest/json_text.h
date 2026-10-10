#pragma once

// JSON string literal of a UTF-8 text, shared by the `selftest` report (harness.cpp) and the probe
// reports (probe_report.cpp).

#include <cstdio>
#include <string>

namespace uzp::selftest {

inline std::string JsonString(const std::string& text) {
    std::string out = "\"";
    for (const unsigned char c : text) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    return out + "\"";
}

}  // namespace uzp::selftest
