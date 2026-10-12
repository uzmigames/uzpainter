#pragma once

// The hand-over between the thread that evaluates and the preview thread (task
// phase2.1_preview-viewport-window item 2.4; docs/architecture/07-preview-and-render-parity.md §6):
// the publisher stores the last evaluation, the reader takes the newest one when it wants a frame.
//
// A wait-free triple buffer: three slots, one owned by the publisher (back), one by the reader
// (front) and one in the middle, exchanged with a single atomic index. `Publish` writes the back
// slot and swaps it with the middle; `Take` swaps the front slot with the middle when the middle
// holds a newer value. Neither side ever waits for the other, holds a lock or allocates inside the
// exchange, so a stalled, slow or closed reader never delays the publisher. A value is dropped
// only when a newer one replaces it before the reader looked.

#include <array>
#include <atomic>
#include <cstdint>
#include <optional>
#include <utility>

namespace uzp::preview {

template <class T>
class Latest {
public:
    Latest() = default;
    Latest(const Latest&) = delete;
    Latest& operator=(const Latest&) = delete;

    /// Publisher side (one thread): makes `value` the newest value.
    void Publish(T value) {
        m_slots[m_back] = std::move(value);
        const uint32_t previous = m_middle.exchange(m_back | kFresh, std::memory_order_acq_rel);
        m_back = previous & kIndex;
        m_published.fetch_add(1, std::memory_order_relaxed);
    }

    /// Reader side (one thread): the newest value published since the last `Take`, if any. The
    /// value moves out; the reader keeps it as long as it likes.
    std::optional<T> Take() {
        if ((m_middle.load(std::memory_order_acquire) & kFresh) == 0) return std::nullopt;
        const uint32_t previous = m_middle.exchange(m_front, std::memory_order_acq_rel);
        m_front = previous & kIndex;
        std::optional<T> value(std::move(m_slots[m_front]));
        m_slots[m_front] = T{};
        return value;
    }

    /// The number of values published so far.
    [[nodiscard]] uint64_t Published() const { return m_published.load(std::memory_order_relaxed); }

private:
    static constexpr uint32_t kIndex = 3u;
    static constexpr uint32_t kFresh = 4u;

    std::array<T, 3> m_slots{};
    uint32_t m_back = 0;                   // publisher only
    uint32_t m_front = 1;                  // reader only
    std::atomic<uint32_t> m_middle{2};     // index | kFresh when not yet taken
    std::atomic<uint64_t> m_published{0};
};

}  // namespace uzp::preview
