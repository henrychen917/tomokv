// expire_wheel.h -- optional owner-local exact key expiry.
//
// The wheel owns no KvObj and never dereferences one.  KvObj* is part of the node identity so an
// immutable replacement can coexist briefly with a stale timer without letting either timer act
// on the other object version.  Every mutating operation is for the shard owner only.
#pragma once

#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <new>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

#ifndef TOMO_EXPIRE_WHEEL
#define TOMO_EXPIRE_WHEEL 0
#endif

namespace tomo {

static_assert(TOMO_EXPIRE_WHEEL == 0 || TOMO_EXPIRE_WHEEL == 1,
              "TOMO_EXPIRE_WHEEL must be 0 (sampler) or 1 (hierarchical wheel)");

inline constexpr bool kExpireWheelEnabled = TOMO_EXPIRE_WHEEL == 1;

struct KvObj;

// Eleven six-bit levels at millisecond resolution cover every non-negative int64_t deadline.
// State is absent while there are no timers.  A level cascade and a due callback each cost one
// unit of advance()'s caller-supplied budget, including when many nodes share one bucket.
class ExpireWheel {
public:
    static constexpr uint8_t kLevels = 11;
    static constexpr uint8_t kSlotsPerLevel = 64;

    struct Item {
        uint64_t hash = 0;
        KvObj* object = nullptr;
        int64_t deadline_ms = -1;
    };

    enum class DueAction : uint8_t {
        Consume,     // Stale, persisted, or successfully erased: remove the timer.
        Retry,       // Keep its logical deadline but do not retry before wake_ms.
        Reschedule,  // The same object now has a new logical deadline.
    };

    struct DueDecision {
        DueAction action = DueAction::Consume;
        int64_t wake_ms = -1;

        static constexpr DueDecision consume() { return {}; }
        static constexpr DueDecision retry_at(int64_t wake) {
            return {DueAction::Retry, wake};
        }
        static constexpr DueDecision reschedule_at(int64_t deadline) {
            return {DueAction::Reschedule, deadline};
        }
    };

    struct AdvanceResult {
        uint32_t work = 0;       // Cascaded nodes plus due callbacks.
        uint32_t due = 0;        // Due callbacks only.
        bool pending = false;    // More wheel work has a boundary at or before now_ms.
        bool clock_regressed = false;
    };

    ExpireWheel() = default;
    ~ExpireWheel() { delete state_; }
    ExpireWheel(const ExpireWheel&) = delete;
    ExpireWheel& operator=(const ExpireWheel&) = delete;
    ExpireWheel(ExpireWheel&&) = delete;
    ExpireWheel& operator=(ExpireWheel&&) = delete;

    // Insert or move one exact object-version timer.  This is the only path that can allocate.
    // A failed new insertion leaves any existing timers intact.
    bool schedule(uint64_t hash, KvObj* object, int64_t deadline_ms, int64_t now_ms) {
        if (!object || deadline_ms < 0) return false;

        if (!state_) {
            try {
                state_ = new State(normalize(now_ms));
            } catch (const std::bad_alloc&) {
                return false;
            }
        }

        State& state = *state_;
        const Identity identity{hash, object};
        auto found = state.nodes.find(identity);
        if (found != state.nodes.end()) {
            Node& node = found->second;
            unlink(state, node);
            node.deadline_ms = deadline_ms;
            link(state, node, clamp_due(state, normalize(deadline_ms)));
            return true;
        }

        // The due node is detached while its callback runs.  An unrelated insertion must reserve
        // room for both itself and restoration of that detached node; otherwise the callback can
        // consume the one naturally spare map/vector slot and turn Retry into an allocating,
        // lossy operation.  Replacing the detached identity needs only its already-spare slot.
        if (state.callback_active && !(identity == state.callback_identity)) {
            try {
                state.nodes.reserve(state.nodes.size() + 2);
                state.random.reserve(state.random.size() + 2);
            } catch (const std::bad_alloc&) {
                return false;
            } catch (const std::length_error&) {
                return false;
            }
        }

        typename NodeMap::iterator inserted;
        try {
            auto result = state.nodes.try_emplace(identity);
            assert(result.second);
            inserted = result.first;
        } catch (const std::bad_alloc&) {
            release_empty_state();
            return false;
        } catch (const std::length_error&) {
            release_empty_state();
            return false;
        }

        Node& node = inserted->second;
        node.hash = hash;
        node.object = object;
        node.deadline_ms = deadline_ms;
        try {
            state.random.push_back(&node);
        } catch (const std::bad_alloc&) {
            state.nodes.erase(inserted);
            release_empty_state();
            return false;
        } catch (const std::length_error&) {
            state.nodes.erase(inserted);
            release_empty_state();
            return false;
        }
        node.random_index = state.random.size() - 1;
        link(state, node, clamp_due(state, normalize(deadline_ms)));
        return true;
    }

    bool reschedule(uint64_t hash, KvObj* object, int64_t deadline_ms, int64_t now_ms) {
        return schedule(hash, object, deadline_ms, now_ms);
    }

    bool cancel(uint64_t hash, KvObj* object) {
        if (!state_ || !object) return false;
        State& state = *state_;
        auto found = state.nodes.find(Identity{hash, object});
        if (found == state.nodes.end()) return false;
        Node& node = found->second;
        unlink(state, node);
        random_remove(state, node);
        state.nodes.erase(found);
        release_empty_state();
        return true;
    }

    // clear() is not a due-callback operation.  schedule()/cancel() of other identities are safe
    // inside a callback; scheduling the detached identity wins over its returned decision.
    void clear() {
        if (state_ && state_->callback_active) std::abort();
        delete state_;
        state_ = nullptr;
    }

    uint32_t size() const {
        return state_ ? static_cast<uint32_t>(state_->nodes.size()) : 0;
    }
    bool empty() const { return state_ == nullptr; }

    // A structural heap estimate; allocator bookkeeping and unordered_map implementation padding
    // are intentionally not guessed.  Empty wheels report zero dynamic bytes.
    size_t memory_bytes() const {
        if (!state_) return 0;
        return sizeof(State) + state_->nodes.bucket_count() * sizeof(void*) +
               state_->nodes.size() * (sizeof(typename NodeMap::value_type) + 2 * sizeof(void*)) +
               state_->random.capacity() * sizeof(Node*);
    }

    // O(1) volatile-candidate selection for the eviction path.  Entropy is supplied by the owner.
    bool random(uint64_t entropy, Item& out) const {
        if (!state_ || state_->random.empty()) return false;
        const size_t index = static_cast<size_t>(mix(entropy) % state_->random.size());
        const Node& node = *state_->random[index];
        out = {node.hash, node.object, node.deadline_ms};
        return true;
    }

    // The next wakeup may be a cascade boundary rather than a deadline.  -1 means no state.
    int64_t next_wakeup_ms() const {
        if (!state_) return -1;
        Bucket bucket;
        if (!next_bucket(*state_, bucket)) return -1;
        if (bucket.when > static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
            return std::numeric_limits<int64_t>::max();
        return static_cast<int64_t>(bucket.when);
    }

    bool has_work_at(int64_t now_ms) const {
        if (!state_ || now_ms < 0) return false;
        const uint64_t now = static_cast<uint64_t>(now_ms);
        if (now < state_->cursor_ms) return false;
        Bucket bucket;
        return next_bucket(*state_, bucket) && bucket.when <= now;
    }

    // callback(Item) returns DueDecision.  The node is absent from the identity map while callback
    // runs, so expiry code can validate the table's current pointer without a live wheel node being
    // mistaken for that current version.  Retry is forced strictly beyond the current wheel tick;
    // at INT64_MAX, same-tick work rotates to the bucket tail and ends the current pass.
    template <typename Callback>
    AdvanceResult advance(int64_t now_ms, uint32_t budget, Callback&& callback) {
        AdvanceResult result;
        if (!state_) return result;

        // A nested advance would clear the outer callback's single mutation guard and could let
        // cancel() release State while the outer frame still refers to it.
        if (state_->callback_active) std::abort();
        // Deadlines occupy the non-negative signed domain.  Unlike normalize(), treating a
        // negative observation as tick zero would fire a zero deadline before signed time reached
        // it and would disagree with has_work_at().
        if (now_ms < 0) {
            result.clock_regressed = true;
            return result;
        }

        const uint64_t now = static_cast<uint64_t>(now_ms);
        if (now < state_->cursor_ms) {
            result.clock_regressed = true;
            return result;
        }

        while (state_ && result.work < budget) {
            State& state = *state_;
            Bucket bucket;
            if (!next_bucket(state, bucket) || bucket.when > now) {
                state.cursor_ms = now;
                break;
            }
            state.cursor_ms = bucket.when;

            Node* node = bucket_head(state, bucket.level, bucket.slot);
            assert(node);
            unlink(state, *node);
            result.work++;

            if (bucket.level != 0 || node->ready_ms > state.cursor_ms) {
                link(state, *node, clamp_due(state, node->ready_ms));
                continue;
            }

            random_remove(state, *node);
            const Identity identity{node->hash, node->object};
            const Item item{node->hash, node->object, node->deadline_ms};
            auto extracted = state.nodes.extract(identity);
            if (extracted.empty()) std::abort();

            state.callback_identity = identity;
            state.callback_active = true;
            DueDecision decision;
            try {
                decision = callback(item);
            } catch (...) {
                state.callback_active = false;
                Node& held = extracted.mapped();
                held.ready_ms = retry_tick(state.cursor_ms, state.cursor_ms);
                restore(state, std::move(extracted), held.ready_ms,
                        held.ready_ms == state.cursor_ms);
                release_empty_state();
                throw;
            }
            state.callback_active = false;
            result.due++;

            // A callback may have installed the same identity directly.  In that case it is the
            // newer owner decision and the detached node is simply consumed.
            bool stop_at_same_tick = false;
            auto installed = state.nodes.find(identity);
            if (installed != state.nodes.end()) {
                Node& newer = installed->second;
                if (newer.ready_ms == state.cursor_ms) {
                    unlink(state, newer);
                    link(state, newer, newer.ready_ms, /*at_tail=*/true);
                    stop_at_same_tick = true;
                }
            } else {
                Node& held = extracted.mapped();
                if (decision.action == DueAction::Retry) {
                    const uint64_t wake = retry_tick(state.cursor_ms, normalize(decision.wake_ms));
                    stop_at_same_tick = wake == state.cursor_ms;
                    restore(state, std::move(extracted), wake, stop_at_same_tick);
                } else if (decision.action == DueAction::Reschedule && decision.wake_ms >= 0) {
                    held.deadline_ms = decision.wake_ms;
                    const uint64_t wake = clamp_due(state, normalize(decision.wake_ms));
                    stop_at_same_tick = wake == state.cursor_ms;
                    restore(state, std::move(extracted), wake, stop_at_same_tick);
                }
            }
            release_empty_state();
            // INT64_MAX has no later representable retry tick.  Put that node at the bucket tail
            // and end this pass, so repeated retries rotate fairly instead of consuming the whole
            // budget at the head and permanently starving its due peers.  A caller-requested
            // reschedule to an already-due tick gets the same bounded treatment.
            if (stop_at_same_tick) break;
        }

        if (state_) {
            Bucket bucket;
            result.pending = next_bucket(*state_, bucket) && bucket.when <= now;
            if (!result.pending && state_->cursor_ms < now) state_->cursor_ms = now;
        }
        return result;
    }

private:
    struct Identity {
        uint64_t hash;
        KvObj* object;

        bool operator==(const Identity& other) const noexcept {
            return hash == other.hash && object == other.object;
        }
    };

    static uint64_t mix(uint64_t value) {
        value ^= value >> 33;
        value *= 0xff51afd7ed558ccdULL;
        value ^= value >> 33;
        value *= 0xc4ceb9fe1a85ec53ULL;
        value ^= value >> 33;
        return value;
    }

    struct IdentityHash {
        size_t operator()(const Identity& identity) const noexcept {
            const uint64_t pointer = static_cast<uint64_t>(
                reinterpret_cast<uintptr_t>(identity.object));
            return static_cast<size_t>(mix(identity.hash ^ mix(pointer)));
        }
    };

    struct Node {
        uint64_t hash = 0;
        KvObj* object = nullptr;
        int64_t deadline_ms = -1;  // Logical TTL reported to the due callback.
        uint64_t ready_ms = 0;     // Physical wake tick; Retry may move only this value.
        Node* next = nullptr;
        Node* previous = nullptr;
        size_t random_index = std::numeric_limits<size_t>::max();
        uint8_t level = 0;
        uint8_t slot = 0;
    };

    using NodeMap = std::unordered_map<Identity, Node, IdentityHash>;

    struct State {
        explicit State(uint64_t now) : cursor_ms(now) {}

        std::array<Node*, static_cast<size_t>(kLevels) * kSlotsPerLevel> buckets{};
        std::array<uint64_t, kLevels> nonempty{};
        NodeMap nodes;
        std::vector<Node*> random;
        uint64_t cursor_ms = 0;
        Identity callback_identity{};
        bool callback_active = false;
    };

    struct Bucket {
        uint64_t when = 0;
        uint8_t level = 0;
        uint8_t slot = 0;
    };

    static uint64_t normalize(int64_t time_ms) {
        return time_ms < 0 ? uint64_t{0} : static_cast<uint64_t>(time_ms);
    }

    static uint64_t clamp_due(const State& state, uint64_t tick) {
        return tick < state.cursor_ms ? state.cursor_ms : tick;
    }

    static uint64_t retry_tick(uint64_t cursor, uint64_t requested) {
        if (requested > cursor) return requested;
        const uint64_t maximum = static_cast<uint64_t>(std::numeric_limits<int64_t>::max());
        return cursor < maximum ? cursor + 1 : cursor;
    }

    static uint8_t level_for(uint64_t delta) {
        for (uint8_t level = 0; level + 1 < kLevels; level++) {
            const unsigned upper_bit = static_cast<unsigned>(level + 1) * 6;
            if (delta < (uint64_t{1} << upper_bit)) return level;
        }
        return kLevels - 1;
    }

    static size_t bucket_index(uint8_t level, uint8_t slot) {
        return static_cast<size_t>(level) * kSlotsPerLevel + slot;
    }

    static Node*& bucket_head(State& state, uint8_t level, uint8_t slot) {
        return state.buckets[bucket_index(level, slot)];
    }

    static Node* bucket_head(const State& state, uint8_t level, uint8_t slot) {
        return state.buckets[bucket_index(level, slot)];
    }

    static void link(State& state, Node& node, uint64_t ready_ms, bool at_tail = false) {
        assert(!node.next && !node.previous);
        node.ready_ms = clamp_due(state, ready_ms);
        const uint64_t delta = node.ready_ms - state.cursor_ms;
        node.level = level_for(delta);
        node.slot = static_cast<uint8_t>((node.ready_ms >> (node.level * 6)) & 63u);

        Node*& head = bucket_head(state, node.level, node.slot);
        if (!head) {
            node.next = node.previous = &node;
            head = &node;
        } else {
            Node* tail = head->previous;
            node.next = head;
            node.previous = tail;
            tail->next = &node;
            head->previous = &node;
            if (!at_tail) head = &node;
        }
        state.nonempty[node.level] |= uint64_t{1} << node.slot;
    }

    static void unlink(State& state, Node& node) {
        assert(node.next && node.previous);
        Node*& head = bucket_head(state, node.level, node.slot);
        if (node.next == &node) {
            assert(head == &node);
            head = nullptr;
            state.nonempty[node.level] &= ~(uint64_t{1} << node.slot);
        } else {
            node.previous->next = node.next;
            node.next->previous = node.previous;
            if (head == &node) head = node.next;
        }
        node.next = nullptr;
        node.previous = nullptr;
    }

    static void random_remove(State& state, Node& node) {
        assert(node.random_index < state.random.size());
        Node* last = state.random.back();
        state.random[node.random_index] = last;
        last->random_index = node.random_index;
        state.random.pop_back();
        node.random_index = std::numeric_limits<size_t>::max();
    }

    // Return the first non-empty bucket boundary at or after cursor_ms.  On equal boundaries,
    // upper levels win so all cascade debt at that tick is exposed before level-zero due work.
    static bool next_bucket(const State& state, Bucket& out) {
        bool found = false;
        for (uint8_t level = 0; level < kLevels; level++) {
            const uint64_t mask = state.nonempty[level];
            if (!mask) continue;

            const unsigned shift = static_cast<unsigned>(level) * 6;
            const uint64_t unit = state.cursor_ms >> shift;
            const uint8_t current = static_cast<uint8_t>(unit & 63u);
            const uint64_t lower_mask = shift ? ((uint64_t{1} << shift) - 1) : 0;
            const bool aligned = (state.cursor_ms & lower_mask) == 0;
            const unsigned first = static_cast<unsigned>(current) + (aligned ? 0u : 1u);
            const uint64_t same_rotation =
                first < 64 ? mask & (~uint64_t{0} << first) : uint64_t{0};

            uint8_t slot;
            uint64_t target_unit;
            if (same_rotation) {
                slot = trailing_zeroes(same_rotation);
                target_unit = (unit & ~uint64_t{63}) + slot;
            } else {
                slot = trailing_zeroes(mask);
                const uint64_t maximum_unit = std::numeric_limits<uint64_t>::max() >> shift;
                const uint64_t base = unit & ~uint64_t{63};
                if (base > maximum_unit || maximum_unit - base < uint64_t{64} + slot)
                    continue;
                target_unit = base + uint64_t{64} + slot;
            }

            const uint64_t when = target_unit << shift;
            if (!found || when < out.when || (when == out.when && level > out.level)) {
                out = {when, level, slot};
                found = true;
            }
        }
        return found;
    }

    static uint8_t trailing_zeroes(uint64_t value) {
        assert(value);
#if defined(__GNUC__) || defined(__clang__)
        return static_cast<uint8_t>(__builtin_ctzll(value));
#else
        uint8_t count = 0;
        while ((value & 1u) == 0) { value >>= 1; count++; }
        return count;
#endif
    }

    static void restore(State& state, typename NodeMap::node_type&& extracted,
                        uint64_t ready_ms, bool at_tail = false) {
        auto restored = state.nodes.insert(std::move(extracted));
        if (!restored.inserted) return;  // A direct callback schedule owns this identity now.
        Node& node = restored.position->second;
        // Extraction reserved this element's vector slot. schedule() reserves one additional slot
        // for the detached node before accepting an unrelated callback insertion, so restoration
        // cannot allocate or lose the timer on allocation failure.
        assert(state.random.size() < state.random.capacity());
        state.random.push_back(&node);
        node.random_index = state.random.size() - 1;
        link(state, node, ready_ms, at_tail);
    }

    void release_empty_state() {
        if (!state_ || state_->callback_active || !state_->nodes.empty()) return;
        delete state_;
        state_ = nullptr;
    }

    State* state_ = nullptr;
    // ExpireIndex is 80 bytes in the locked FlatStore layout.  Keeping the selector alternative
    // the same size lets integration switch types without moving any following FlatStore field.
    std::array<std::byte, 72> layout_reserve_{};
};

static_assert(sizeof(void*) == 8, "ExpireWheel's locked inline footprint assumes 64-bit pointers");
static_assert(sizeof(ExpireWheel) == 80,
              "ExpireWheel must preserve ExpireIndex's FlatStore layout footprint");

}  // namespace tomo
