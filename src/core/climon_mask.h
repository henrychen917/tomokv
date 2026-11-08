// MONITOR/tracking destination membership and event-forwarding history, shared by Server and
// pubsub events. The two words cover IO ids 0..127. Membership atomics use relaxed ordering;
// they do not publish event payloads or implement NotifyMask's wake protocol.

#pragma once

#include <atomic>
#include <cstdint>

namespace tomo {

// Contract: A value mask owns two ordinary words; callers serialize add/contains on that value.
// set/load operate on caller-owned atomic words with relaxed RMW/load operations. IO ids must
// be below kBits; there is no bounds check, allocation or queue back-pressure. Reading both
// words does not establish a simultaneous snapshot of membership.
struct ClimonIoMask {
    static constexpr uint32_t kBits = 128;
    uint64_t words[2] = {};

    /* TOMO_TOOL_FUNCTION climon-mask-word */
    static constexpr uint32_t /* TOMO_TOOL_BIND word */ word(uint32_t /* TOMO_TOOL_BIND io */ io) {
        return io >> 6;
    }
    bool contains(uint32_t io) const { return (words[word(io)] >> (io & 63)) & 1; }
    void add(uint32_t io) { words[word(io)] |= uint64_t{1} << (io & 63); }
    explicit operator bool() const { return words[0] || words[1]; }

    // Server stores the low word in its main state and the high word in its cold tail.
    // Membership uses relaxed ordering; NotifyMask separately supplies the wake protocol.
    static void set(std::atomic<uint64_t>& low, std::atomic<uint64_t>& high, uint32_t io,
                    bool present) {
        auto& bits = word(io) ? high : low;
        const uint64_t bit = uint64_t{1} << (io & 63);
        if (present)
            bits.fetch_or(bit, std::memory_order_relaxed);
        else
            bits.fetch_and(~bit, std::memory_order_relaxed);
    }
    static ClimonIoMask load(const std::atomic<uint64_t>& low, const std::atomic<uint64_t>& high) {
        return {{low.load(std::memory_order_relaxed), high.load(std::memory_order_relaxed)}};
    }
};

}  // namespace tomo
