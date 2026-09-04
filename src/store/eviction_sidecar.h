// eviction_sidecar.h -- owner-local maxmemory metadata parallel to FlatStore slots.
//
// FlatStore owns this object through a nullable pointer.  A null pointer is the complete disabled
// representation: no state object and no byte arrays are allocated while maxmemory is zero.
// Foreign readers never receive this pointer.  The shard owner is therefore the only reader or
// writer of these bytes, and ordinary (non-atomic) loads and stores are sufficient.
//
// The third array is a transaction slot.  Snapshot preparation retains it until the cut; table
// growth uses it only until the corresponding slot-word allocation succeeds.  A topology change
// then mirrors FlatStore without another fallible operation:
//
//   prepare_table(new_capacity)
//   move_table(0, 1)
//   install_prepared(0)
//
// A failed slot-word allocation calls free_prepared() and leaves both live arrays untouched.
#pragma once

#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <new>
#include <utility>

namespace tomo {

class EvictionSidecar {
public:
    // Allocations returned by this callback must be zero-filled and compatible with std::free.
    using Allocator = void* (*)(size_t count, size_t width);

    EvictionSidecar() noexcept = default;
    ~EvictionSidecar() noexcept {
        std::free(meta_[0]);
        std::free(meta_[1]);
        std::free(prepared_meta_);
    }
    EvictionSidecar(const EvictionSidecar&) = delete;
    EvictionSidecar& operator=(const EvictionSidecar&) = delete;
    EvictionSidecar(EvictionSidecar&&) = delete;
    EvictionSidecar& operator=(EvictionSidecar&&) = delete;

    // Construct a complete unpublished image.  Allocation is transactional: on failure all
    // arrays and the state object are released and the caller receives nullptr.
    static EvictionSidecar* allocate(uint32_t table0_capacity,
                                     uint32_t table1_capacity = 0,
                                     uint32_t prepared_capacity = 0,
                                     Allocator allocator = default_allocator) {
        if (!allocator) return nullptr;
        auto* result = new (std::nothrow) EvictionSidecar;
        if (!result) return nullptr;

        result->meta_[0] = allocate_meta(table0_capacity, allocator);
        if (table0_capacity && !result->meta_[0]) {
            delete result;
            return nullptr;
        }
        result->capacity_[0] = table0_capacity;

        result->meta_[1] = allocate_meta(table1_capacity, allocator);
        if (table1_capacity && !result->meta_[1]) {
            delete result;
            return nullptr;
        }
        result->capacity_[1] = table1_capacity;

        result->prepared_meta_ = allocate_meta(prepared_capacity, allocator);
        if (prepared_capacity && !result->prepared_meta_) {
            delete result;
            return nullptr;
        }
        result->prepared_capacity_ = prepared_capacity;
        return result;
    }

    // Publish a newly allocated sidecar only after its complete topology exists.  Repeated calls
    // are harmless, which lets a live maxmemory refresh retry a previously failed first arm.
    static bool arm(EvictionSidecar*& sidecar, uint32_t table0_capacity,
                    uint32_t table1_capacity = 0, uint32_t prepared_capacity = 0,
                    Allocator allocator = default_allocator) {
        if (sidecar) return true;
        EvictionSidecar* fresh =
            allocate(table0_capacity, table1_capacity, prepared_capacity, allocator);
        if (!fresh) return false;
        sidecar = fresh;
        return true;
    }

    // Reverse the maxmemory arm edge.  Nulling before destruction also makes accidental owner-side
    // reuse conspicuous; no foreign reader can race this operation.
    static void disarm(EvictionSidecar*& sidecar) noexcept {
        EvictionSidecar* old = std::exchange(sidecar, nullptr);
        delete old;
    }

    // Allocate the metadata half of a future table without disturbing either live table.  There
    // may be only one prepared topology operation at a time, matching FlatStore's resize/snapshot
    // exclusion.  calloc preserves demand-zero behaviour for large sparse tables.
    bool prepare_table(uint32_t capacity, Allocator allocator = default_allocator) {
        if (!capacity || !allocator || prepared_meta_) return false;
        uint8_t* fresh = allocate_meta(capacity, allocator);
        if (!fresh) return false;
        prepared_meta_ = fresh;
        prepared_capacity_ = capacity;
        return true;
    }

    bool has_prepared() const noexcept { return prepared_meta_ != nullptr; }
    uint32_t prepared_capacity() const noexcept { return prepared_capacity_; }
    uint8_t* prepared_data() noexcept { return prepared_meta_; }
    const uint8_t* prepared_data() const noexcept { return prepared_meta_; }

    // Install cannot fail.  Its destination must already have been vacated in the slot-word
    // topology too; requiring an empty destination prevents an unnoticed metadata leak or skew.
    void install_prepared(unsigned table) noexcept {
        assert(valid_table(table));
        assert(meta_[table] == nullptr && capacity_[table] == 0);
        assert(prepared_meta_ != nullptr && prepared_capacity_ != 0);
        meta_[table] = std::exchange(prepared_meta_, nullptr);
        capacity_[table] = std::exchange(prepared_capacity_, 0);
    }

    void free_prepared() noexcept {
        std::free(std::exchange(prepared_meta_, nullptr));
        prepared_capacity_ = 0;
    }

    // Transfer ownership of a complete parallel array.  FlatStore uses this when current table 0
    // is demoted to old table 1 for either incremental rehash or a snapshot cut.
    void move_table(unsigned from, unsigned to) noexcept {
        assert(valid_table(from) && valid_table(to) && from != to);
        assert(meta_[to] == nullptr && capacity_[to] == 0);
        meta_[to] = std::exchange(meta_[from], nullptr);
        capacity_[to] = std::exchange(capacity_[from], 0);
    }

    void free_table(unsigned table) noexcept {
        assert(valid_table(table));
        std::free(std::exchange(meta_[table], nullptr));
        capacity_[table] = 0;
    }

    // Used by FlatStore's allocation-failure FLUSH fallback, which retains table 0 but returns all
    // of its slots to EMPTY.  The metadata array must follow that retained topology exactly.
    void clear_table(unsigned table) noexcept {
        assert(valid_table(table));
        if (meta_[table]) std::memset(meta_[table], 0, capacity_[table]);
    }

    void free_all_tables() noexcept {
        free_table(0);
        free_table(1);
        free_prepared();
        sample_cursor_ = 0;
    }

    uint32_t capacity(unsigned table) const noexcept {
        assert(valid_table(table));
        return capacity_[table];
    }
    uint8_t* data(unsigned table) noexcept {
        assert(valid_table(table));
        return meta_[table];
    }
    const uint8_t* data(unsigned table) const noexcept {
        assert(valid_table(table));
        return meta_[table];
    }

    uint8_t meta(unsigned table, uint32_t slot) const noexcept {
        assert_slot(table, slot);
        return meta_[table][slot];
    }
    void set_meta(unsigned table, uint32_t slot, uint8_t value) noexcept {
        assert_slot(table, slot);
        meta_[table][slot] = value;
    }
    void clear_meta(unsigned table, uint32_t slot) noexcept {
        set_meta(table, slot, 0);
    }

    // Rehash can take a byte before probing for its destination.  Clearing the source mirrors the
    // old slot becoming a tombstone; the returned byte can then initialize the destination slot.
    uint8_t take_meta(unsigned table, uint32_t slot) noexcept {
        assert_slot(table, slot);
        return std::exchange(meta_[table][slot], uint8_t{0});
    }
    void move_meta(unsigned from_table, uint32_t from_slot,
                   unsigned to_table, uint32_t to_slot) noexcept {
        assert_slot(from_table, from_slot);
        assert_slot(to_table, to_slot);
        meta_[to_table][to_slot] =
            std::exchange(meta_[from_table][from_slot], uint8_t{0});
    }

    uint64_t& sample_cursor() noexcept { return sample_cursor_; }
    uint64_t sample_cursor() const noexcept { return sample_cursor_; }
    void reset_sample_cursor() noexcept { sample_cursor_ = 0; }

    size_t array_bytes() const noexcept {
        return static_cast<size_t>(capacity_[0]) + capacity_[1] + prepared_capacity_;
    }
    size_t memory_bytes() const noexcept {
        return sizeof(EvictionSidecar) + array_bytes();
    }

private:
    static void* default_allocator(size_t count, size_t width) {
        return std::calloc(count, width);
    }

    static uint8_t* allocate_meta(uint32_t capacity, Allocator allocator) noexcept {
        if (!capacity) return nullptr;
        // The public allocation API reports failure with nullptr/bool and promises transactional
        // rollback.  A custom fault allocator is not declared noexcept, so translate its exception
        // as well; otherwise allocate() leaks the partially constructed sidecar and prepare_table()
        // unexpectedly escapes instead of leaving the live arrays untouched.
        try {
            return static_cast<uint8_t*>(allocator(capacity, sizeof(uint8_t)));
        } catch (...) {
            return nullptr;
        }
    }

    static constexpr bool valid_table(unsigned table) noexcept { return table < 2; }

    void assert_slot(unsigned table, uint32_t slot) const noexcept {
        assert(valid_table(table));
        assert(meta_[table] != nullptr);
        assert(slot < capacity_[table]);
        (void)table;
        (void)slot;
    }

    uint8_t* meta_[2] = {nullptr, nullptr};
    uint8_t* prepared_meta_ = nullptr;
    uint32_t capacity_[2] = {0, 0};
    uint32_t prepared_capacity_ = 0;
    uint64_t sample_cursor_ = 0;
};

}  // namespace tomo
