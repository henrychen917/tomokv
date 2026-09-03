// foreign_read_safety.h -- per-shard fail-closed publication for foreign local reads.
//
// One shard owner writes these cells. Foreign IO/fused readers perform one acquire load for the
// queried key and never follow a pointer into owner state. Fingerprint collisions are deliberately
// false-positive: a wildcard cell sends the read to the owner until the complete bucket drains.
#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>

namespace tomo {

class alignas(64) ForeignReadSafety {
public:
    static constexpr uint32_t kCellCount = 4096;
    static constexpr uint32_t kCellMask = kCellCount - 1;
    static constexpr uint32_t kCountBits = 31;
    static constexpr uint32_t kFingerprintBits = 32;
    static constexpr uint64_t kCountMask = (uint64_t{1} << kCountBits) - 1;
    static constexpr uint64_t kFingerprintMask =
        ((uint64_t{1} << kFingerprintBits) - 1) << kCountBits;
    static constexpr uint64_t kWildcardBit = uint64_t{1} << 63;

    static uint64_t mixed_hash(uint64_t hash) {
        hash ^= hash >> 33;
        hash *= 0xff51afd7ed558ccdULL;
        hash ^= hash >> 33;
        hash *= 0xc4ceb9fe1a85ec53ULL;
        hash ^= hash >> 33;
        return hash;
    }

    static uint32_t cell_index(uint64_t hash) {
        return static_cast<uint32_t>(mixed_hash(hash)) & kCellMask;
    }

    static uint32_t fingerprint(uint64_t hash) {
        uint32_t result = static_cast<uint32_t>(mixed_hash(hash) >> 12);
        return result ? result : 1;
    }

    bool might_contain(uint64_t hash) const {
        const uint64_t cell = cells_[cell_index(hash)].load(std::memory_order_acquire);
        if (!cell) return false;
        return (cell & kWildcardBit) != 0 || cell_fingerprint(cell) == fingerprint(hash);
    }

    template <typename HashAt>
    void add_span(uint32_t count, HashAt&& hash_at) {
        if (!count) return;
        uint64_t total = unsafe_total_refs_.load(std::memory_order_relaxed);
        if (total == std::numeric_limits<uint64_t>::max() ||
            count > std::numeric_limits<uint64_t>::max() - total) {
            poison_permanently();
            return;
        }
        // Publish the exact drain witness before publishing individual cells. The caller performs
        // no physical mutation until this complete function has returned.
        unsafe_total_refs_.store(total + count, std::memory_order_relaxed);
        for (uint32_t i = 0; i < count; i++) add_hash(hash_at(i));
    }

    template <typename HashAt>
    void close_span(uint32_t count, HashAt&& hash_at) {
        if (!count) return;
        if (poison_refs_.load(std::memory_order_relaxed) ==
            std::numeric_limits<uint64_t>::max()) return;
        for (uint32_t i = 0; i < count; i++) close_hash(hash_at(i));

        const uint64_t total = unsafe_total_refs_.load(std::memory_order_relaxed);
        if (total < count) std::abort();
        const uint64_t remaining = total - count;
        unsafe_total_refs_.store(remaining, std::memory_order_relaxed);
        rebuild_saturated_if_drained(remaining);
    }

    // Fail-closed scope for a mutation whose complete key set cannot be enumerated before its first
    // physical change. The first opener contributes one wildcard reference to every cell; nesting
    // is owner-only bookkeeping and the last close removes that one contribution after raw state is
    // safe again.
    void poison_open() {
        uint64_t refs = poison_refs_.load(std::memory_order_relaxed);
        if (refs == std::numeric_limits<uint64_t>::max()) return;
        if (refs != 0) {
            if (refs == std::numeric_limits<uint64_t>::max() - 1) {
                poison_permanently();
                return;
            }
            poison_refs_.store(refs + 1, std::memory_order_relaxed);
            return;
        }
        poison_refs_.store(1, std::memory_order_relaxed);
        for (uint32_t i = 0; i < kCellCount; i++) add_cell(i, 1, true);
    }

    void poison_close() {
        uint64_t refs = poison_refs_.load(std::memory_order_relaxed);
        if (!refs) std::abort();
        if (refs == std::numeric_limits<uint64_t>::max()) return;
        if (refs > 1) {
            poison_refs_.store(refs - 1, std::memory_order_relaxed);
            return;
        }
        // The representation is already safe when this walk begins, so sequential release clears
        // cannot expose an unsafe key.
        for (uint32_t i = 0; i < kCellCount; i++) close_cell(i);
        poison_refs_.store(0, std::memory_order_relaxed);
        rebuild_saturated_if_drained(
            unsafe_total_refs_.load(std::memory_order_relaxed));
    }

    uint64_t unsafe_total_refs() const {
        return unsafe_total_refs_.load(std::memory_order_relaxed);
    }
    uint64_t saturated_cells() const {
        return saturated_cells_.load(std::memory_order_relaxed);
    }
    uint64_t poison_refs() const {
        return poison_refs_.load(std::memory_order_relaxed);
    }
    bool permanently_poisoned() const {
        return poison_refs_.load(std::memory_order_relaxed) ==
               std::numeric_limits<uint64_t>::max();
    }
    void fail_closed_permanently() { poison_permanently(); }

    uint64_t occupied_cells() const {
        uint64_t result = 0;
        for (const auto& cell : cells_)
            result += cell.load(std::memory_order_relaxed) != 0;
        return result;
    }

    uint64_t wildcard_cells() const {
        uint64_t result = 0;
        for (const auto& cell : cells_)
            result += (cell.load(std::memory_order_relaxed) & kWildcardBit) != 0;
        return result;
    }

#ifdef TOMO_FOREIGN_READ_SAFETY_TEST
    void test_set_cell(uint64_t hash, uint64_t count, bool wildcard = false) {
        if (!count || count > kCountMask) std::abort();
        const uint32_t index = cell_index(hash);
        cells_[index].store(pack(count, fingerprint(hash), wildcard),
                            std::memory_order_relaxed);
        saturated_cells_.store(count == kCountMask ? 1 : 0,
                               std::memory_order_relaxed);
    }
    void test_set_unsafe_total_refs(uint64_t refs) {
        unsafe_total_refs_.store(refs, std::memory_order_relaxed);
    }
    uint64_t test_cell(uint64_t hash) const {
        return cells_[cell_index(hash)].load(std::memory_order_relaxed);
    }
#endif

private:
    static uint64_t cell_count(uint64_t cell) { return cell & kCountMask; }
    static uint32_t cell_fingerprint(uint64_t cell) {
        return static_cast<uint32_t>((cell & kFingerprintMask) >> kCountBits);
    }
    static uint64_t pack(uint64_t count, uint32_t fingerprint, bool wildcard) {
        return count | (static_cast<uint64_t>(fingerprint) << kCountBits) |
               (wildcard ? kWildcardBit : 0);
    }

    void add_hash(uint64_t hash) {
        add_cell(cell_index(hash), fingerprint(hash), false);
    }

    void add_cell(uint32_t index, uint32_t fingerprint, bool force_wildcard) {
        const uint64_t old = cells_[index].load(std::memory_order_relaxed);
        if (!old) {
            cells_[index].store(pack(1, fingerprint, force_wildcard),
                                std::memory_order_release);
            return;
        }
        const uint64_t count = cell_count(old);
        if (count == kCountMask) return;  // already saturated and permanently positive until drain
        const uint64_t next = count + 1;
        const bool wildcard = force_wildcard || (old & kWildcardBit) != 0 ||
                              cell_fingerprint(old) != fingerprint;
        if (next == kCountMask) {
            cells_[index].store(pack(kCountMask, cell_fingerprint(old), true),
                                std::memory_order_release);
            saturated_cells_.store(
                saturated_cells_.load(std::memory_order_relaxed) + 1,
                std::memory_order_relaxed);
            return;
        }
        cells_[index].store(pack(next, cell_fingerprint(old), wildcard),
                            std::memory_order_release);
    }

    void close_hash(uint64_t hash) { close_cell(cell_index(hash)); }

    void close_cell(uint32_t index) {
        const uint64_t old = cells_[index].load(std::memory_order_relaxed);
        const uint64_t count = cell_count(old);
        if (!count) std::abort();
        if (count == kCountMask) return;  // saturation lost the exact high count
        if (count == 1) {
            cells_[index].store(0, std::memory_order_release);
            return;
        }
        cells_[index].store(pack(count - 1, cell_fingerprint(old),
                                 (old & kWildcardBit) != 0),
                            std::memory_order_release);
    }

    void rebuild_saturated_if_drained(uint64_t unsafe_refs) {
        if (unsafe_refs != 0 || poison_refs_.load(std::memory_order_relaxed) != 0 ||
            saturated_cells_.load(std::memory_order_relaxed) == 0) return;
        for (auto& cell : cells_) cell.store(0, std::memory_order_release);
        saturated_cells_.store(0, std::memory_order_relaxed);
    }

    void poison_permanently() {
        poison_refs_.store(std::numeric_limits<uint64_t>::max(),
                           std::memory_order_relaxed);
        unsafe_total_refs_.store(std::numeric_limits<uint64_t>::max(),
                                 std::memory_order_relaxed);
        for (auto& cell : cells_)
            cell.store(pack(kCountMask, 1, true), std::memory_order_release);
        saturated_cells_.store(kCellCount, std::memory_order_relaxed);
    }

    std::array<std::atomic<uint64_t>, kCellCount> cells_{};
    // These are exact owner-side lifecycle witnesses. They are atomic only so INFO may sample them
    // from another fused thread without creating a data race; updates remain sole-writer stores.
    std::atomic<uint64_t> unsafe_total_refs_{0};
    std::atomic<uint64_t> saturated_cells_{0};
    std::atomic<uint64_t> poison_refs_{0};
};

static_assert(ForeignReadSafety::kCellCount == 4096);
static_assert(sizeof(std::atomic<uint64_t>) == sizeof(uint64_t));
static_assert(std::atomic<uint64_t>::is_always_lock_free,
              "foreign-read filter cells must remain read-pure lock-free loads");

}  // namespace tomo
