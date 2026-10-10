#pragma once

// SHA-256 (FIPS 180-4), used for manifest digests and resource keys.

#include <array>
#include <cstdint>
#include <string>
#include <string_view>

namespace uzp::core {

class Sha256 {
public:
    Sha256();
    void Update(std::string_view bytes);
    std::array<std::uint8_t, 32> Finish();

private:
    void Block(const std::uint8_t* block);

    std::array<std::uint32_t, 8> state_;
    std::array<std::uint8_t, 64> buffer_{};
    std::size_t buffered_ = 0;
    std::uint64_t length_ = 0;
};

/// Lower-case hexadecimal SHA-256 of `bytes`.
std::string Sha256Hex(std::string_view bytes);

/// True for 64 lower-case hexadecimal characters (the form every stored hash uses).
bool IsSha256Hex(std::string_view text);

}  // namespace uzp::core
