// MONITOR/tracking destinations, including the forwarding history carried by an event.
#pragma once

#include <atomic>
#include <cstdint>

namespace tomo {

struct ClimonIoMask {
    static constexpr uint32_t kBits = 128;
    uint64_t words[2] = {};

    static constexpr uint32_t word(uint32_t io) { return io >> 6; }
    bool contains(uint32_t io) const { return (words[word(io)] >> (io & 63)) & 1; }
    void add(uint32_t io) { words[word(io)] |= uint64_t{1} << (io & 63); }
    explicit operator bool() const { return words[0] || words[1]; }

    // The low word stays at its established Server offset; the high word is cold tail storage.
    // These are membership bits, not NotifyMask's wake protocol: retain relaxed ordering.
    static void set(std::atomic<uint64_t>& low, std::atomic<uint64_t>& high,
                    uint32_t io, bool present) {
        auto& bits = word(io) ? high : low;
        const uint64_t bit = uint64_t{1} << (io & 63);
        if (present) bits.fetch_or(bit, std::memory_order_relaxed);
        else bits.fetch_and(~bit, std::memory_order_relaxed);
    }
    static ClimonIoMask load(const std::atomic<uint64_t>& low,
                            const std::atomic<uint64_t>& high) {
        return {{low.load(std::memory_order_relaxed), high.load(std::memory_order_relaxed)}};
    }
};

}  // namespace tomo
