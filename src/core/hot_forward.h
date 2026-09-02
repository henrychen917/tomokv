// hot_forward.h -- bounded, opt-in snapshots for one hot GET key per physical shard.
//
// The shard owner is the only writer.  IO threads never touch KvObj or FlatStore memory: they
// copy one fully formatted positive GET reply from atomic words and accept it only across a stable
// even sequence.  Candidate and target identity below are deliberately plain owner-only state;
// the FLIP quiescence barrier transfers that state with shard-writer tenure.
#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <new>
#include <utility>

#include "../store/kvobj.h"
#include "signal.h"

namespace tomo {

class HotForward {
public:
    static constexpr uint32_t kKeyBytes = 256;
    static constexpr uint32_t kReplyBytes = 4096;
    static constexpr uint8_t kPromotionSamples = 16;

    HotForward() = default;
    HotForward(const HotForward&) = delete;
    HotForward& operator=(const HotForward&) = delete;

    // Boot-only.  The two allocations are transactional: a failure leaves this object disabled
    // and permits the caller to fail server initialization without a partially installed table.
    bool init(uint32_t nshards, uint32_t nthreads) noexcept {
        if (!nshards || !nthreads || slots_ || scratches_) return false;
        try {
            std::unique_ptr<Slot[]> slots(new (std::nothrow) Slot[nshards]);
            if (!slots) return false;
            std::unique_ptr<Scratch[]> scratches(new (std::nothrow) Scratch[nthreads]);
            if (!scratches) return false;
            slots_ = std::move(slots);
            scratches_ = std::move(scratches);
            nshards_ = nshards;
            nthreads_ = nthreads;
            return true;
        } catch (...) {
            return false;
        }
    }

    char* scratch(uint32_t tid) noexcept {
        return tid < nthreads_ ? scratches_[tid].bytes.data() : nullptr;
    }

    // One non-spinning attempt.  realtime_cache is parse-call-local; a value <= 0 means no
    // CLOCK_REALTIME sample has yet been taken.  The clock is sampled only after an exact, stable
    // active-key match, and only for a snapshot that actually carries a deadline.
    bool try_read(uint32_t sid, uint64_t hash, Slice key, int64_t& realtime_cache,
                  char* destination, uint32_t& reply_len) const noexcept {
        reply_len = 0;
        if (sid >= nshards_ || !destination) return false;
        const Slot& slot = slots_[sid];

        const uint64_t first = slot.shared.sequence.load(std::memory_order_acquire);
        if (__builtin_expect((first & 1u) != 0, true)) return false;

        const uint64_t published_hash = slot.shared.hash.load(std::memory_order_relaxed);
        const uint64_t lengths = slot.shared.lengths.load(std::memory_order_relaxed);
        const uint32_t published_key_len = static_cast<uint32_t>(lengths);
        const uint32_t published_reply_len = static_cast<uint32_t>(lengths >> 32);
        if (published_hash != hash || published_key_len != key.n || key.n > kKeyBytes ||
            !published_reply_len || published_reply_len > kReplyBytes) return false;
        if (!atomic_words_equal(slot.key, key.p, key.n)) return false;

        const uint64_t expire_bits = slot.shared.expire_at_ms.load(std::memory_order_relaxed);
        atomic_words_copy(slot.reply, destination, published_reply_len);
        std::atomic_thread_fence(std::memory_order_acquire);
        const uint64_t second = slot.shared.sequence.load(std::memory_order_relaxed);
        if (first != second || (second & 1u) != 0) return false;

        int64_t expire_at_ms;
        std::memcpy(&expire_at_ms, &expire_bits, sizeof(expire_at_ms));
        if (expire_at_ms >= 0) {
            if (realtime_cache <= 0) realtime_cache = now_realtime_ms();
            if (expire_at_ms <= realtime_cache) return false;
        }
        reply_len = published_reply_len;
        return true;
    }

    // Called only on ExLoop's existing key-sampling tick, after a successful ordinary GET.  A
    // matching invalid target is republished by that later sampled read; another exact key must
    // independently accumulate the full consecutive threshold before replacing the target.
    void sampled_get(uint32_t sid, uint64_t hash, Slice key, const KvObj* object) noexcept {
        if (sid >= nshards_) return;
        Slot& slot = slots_[sid];
        OwnerState& owner = slot.owner;
        if (key.n > kKeyBytes) {
            owner.candidate_samples = 0;
            return;
        }
        if (!publishable_object(key, object)) {
            owner.candidate_samples = 0;
            if (owner_key_equal(owner.has_target, owner.target_hash, owner.target_len,
                                owner.target_key, hash, key))
                make_odd(slot);
            return;
        }

        if (owner_key_equal(owner.has_target, owner.target_hash, owner.target_len,
                            owner.target_key, hash, key)) {
            owner.candidate_samples = 0;
            if (!owner.published) publish_snapshot(slot, hash, key, object);
            return;
        }

        if (owner_key_equal(owner.candidate_samples != 0, owner.candidate_hash,
                            owner.candidate_len, owner.candidate_key, hash, key)) {
            if (owner.candidate_samples < kPromotionSamples) owner.candidate_samples++;
        } else {
            owner.candidate_hash = hash;
            owner.candidate_len = key.n;
            if (key.n) std::memcpy(owner.candidate_key.data(), key.p, key.n);
            owner.candidate_samples = 1;
        }
        if (owner.candidate_samples < kPromotionSamples) return;

        owner.has_target = true;
        owner.target_hash = hash;
        owner.target_len = key.n;
        if (key.n) std::memcpy(owner.target_key.data(), key.p, key.n);
        owner.candidate_samples = 0;
        publish_snapshot(slot, hash, key, object);
    }

    // Owner-thread write publication.  A non-matching write is a plain predicted-false check.
    // For the matching target, null/non-String/unsupported/oversize state leaves the slot odd and
    // unavailable; a valid bounded String publishes its final positive GET reply.
    bool publish_target(uint32_t sid, uint64_t hash, Slice key,
                        const KvObj* object) noexcept {
        if (!targets(sid, hash, key)) return false;
        return publish_snapshot(slots_[sid], hash, key, object);
    }

    // Broad owner-thread mutation invalidation.  Target identity survives so a later sampled
    // ordinary GET can republish after pending epoch state has drained.
    void invalidate_shard(uint32_t sid) noexcept {
        if (sid >= nshards_) return;
        Slot& slot = slots_[sid];
        if (__builtin_expect(!slot.owner.has_target || !slot.owner.published, true)) return;
        make_odd(slot);
    }

    // Owner-thread-only plain checks.  They must not be called by IO threads; the sequence is the
    // sole cross-thread availability signal.
    bool targets(uint32_t sid, uint64_t hash, Slice key) const noexcept {
        if (sid >= nshards_) return false;
        const OwnerState& owner = slots_[sid].owner;
        if (__builtin_expect(!owner.has_target, true)) return false;
        return owner_key_equal(true, owner.target_hash, owner.target_len, owner.target_key,
                               hash, key);
    }

    bool active(uint32_t sid) const noexcept {
        return sid < nshards_ && slots_[sid].owner.has_target;
    }

private:
    static_assert(std::atomic<uint64_t>::is_always_lock_free,
                  "hot-forward requires always-lock-free 64-bit atomics");

    static constexpr size_t kKeyWords = kKeyBytes / sizeof(uint64_t);
    static constexpr size_t kReplyWords = kReplyBytes / sizeof(uint64_t);

    struct alignas(64) SharedHeader {
        std::atomic<uint64_t> sequence{1};       // odd means invalid or writer in progress
        std::atomic<uint64_t> hash{0};
        std::atomic<uint64_t> lengths{0};        // low 32: key, high 32: formatted reply
        std::atomic<uint64_t> expire_at_ms{UINT64_MAX}; // signed bits; -1 means persistent
    };

    struct alignas(64) OwnerState {
        bool has_target = false;
        bool published = false;
        uint8_t candidate_samples = 0;
        uint32_t target_len = 0;
        uint32_t candidate_len = 0;
        uint64_t target_hash = 0;
        uint64_t candidate_hash = 0;
        std::array<char, kKeyBytes> target_key{};
        std::array<char, kKeyBytes> candidate_key{};
    };

    struct alignas(64) Slot {
        SharedHeader shared;
        alignas(64) std::array<std::atomic<uint64_t>, kKeyWords> key;
        alignas(64) std::array<std::atomic<uint64_t>, kReplyWords> reply;
        OwnerState owner;

        Slot() noexcept {
            for (auto& word : key) word.store(0, std::memory_order_relaxed);
            for (auto& word : reply) word.store(0, std::memory_order_relaxed);
        }
    };

    struct alignas(64) Scratch {
        std::array<char, kReplyBytes> bytes{};
    };

    template <size_t N>
    static void atomic_words_store(std::array<std::atomic<uint64_t>, N>& destination,
                                   const char* source, uint32_t length) noexcept {
        size_t offset = 0;
        while (offset < length) {
            uint64_t word = 0;
            const size_t remaining = static_cast<size_t>(length) - offset;
            const size_t count = remaining < sizeof(word) ? remaining : sizeof(word);
            std::memcpy(&word, source + offset, count);
            destination[offset / sizeof(word)].store(word, std::memory_order_relaxed);
            offset += count;
        }
    }

    template <size_t N>
    static bool atomic_words_equal(const std::array<std::atomic<uint64_t>, N>& published,
                                   const char* expected, uint32_t length) noexcept {
        size_t offset = 0;
        while (offset < length) {
            uint64_t word = 0;
            const size_t remaining = static_cast<size_t>(length) - offset;
            const size_t count = remaining < sizeof(word) ? remaining : sizeof(word);
            std::memcpy(&word, expected + offset, count);
            if (published[offset / sizeof(word)].load(std::memory_order_relaxed) != word)
                return false;
            offset += count;
        }
        return true;
    }

    template <size_t N>
    static void atomic_words_copy(const std::array<std::atomic<uint64_t>, N>& source,
                                  char* destination, uint32_t length) noexcept {
        size_t offset = 0;
        while (offset < length) {
            const uint64_t word =
                source[offset / sizeof(word)].load(std::memory_order_relaxed);
            const size_t remaining = static_cast<size_t>(length) - offset;
            const size_t count = remaining < sizeof(word) ? remaining : sizeof(word);
            std::memcpy(destination + offset, &word, count);
            offset += count;
        }
    }

    static bool owner_key_equal(bool present, uint64_t published_hash, uint32_t published_len,
                                const std::array<char, kKeyBytes>& published_key, uint64_t hash,
                                Slice key) noexcept {
        return present && published_hash == hash && published_len == key.n &&
               (key.n == 0 || std::memcmp(published_key.data(), key.p, key.n) == 0);
    }

    static bool publishable_object(Slice key, const KvObj* object) noexcept {
        if (!object || static_cast<Type>(object->type) != Type::String || !(object->key() == key))
            return false;
        const Enc encoding = static_cast<Enc>(object->enc);
        return encoding == Enc::Raw || encoding == Enc::Int || encoding == Enc::Extern;
    }

    // Makes the slot unavailable before inspecting/copying the final owner-local object.  The
    // release even store in publish_snapshot is the sole successful publication point.
    static uint64_t make_odd(Slot& slot) noexcept {
        uint64_t version = slot.shared.sequence.load(std::memory_order_relaxed);
        if ((version & 1u) == 0) version++;
        slot.shared.sequence.store(version, std::memory_order_release);
        // Pair the odd marker ahead of every following relaxed payload store.  Without this
        // writer-side barrier, a weakly ordered machine could expose a new payload word while a
        // reader still observes the preceding even sequence at both checks.
        std::atomic_thread_fence(std::memory_order_release);
        slot.owner.published = false;
        return version;
    }

    static uint32_t format_reply(const KvObj* object, char (&formatted)[kReplyBytes]) noexcept {
        char integer[24];
        Slice value;
        if (object->is_int()) {
            value = Slice(integer, i64_to_dec(integer, object->int_value()));
        } else {
            value = object->str_value();
            if (value.n && !value.p) return 0;
        }

        char digits[20];
        const uint32_t digit_count = u64_to_dec(digits, value.n);
        const uint64_t total = 1ull + digit_count + 2ull + value.n + 2ull;
        if (total > kReplyBytes) return 0;

        char* cursor = formatted;
        *cursor++ = '$';
        std::memcpy(cursor, digits, digit_count);
        cursor += digit_count;
        *cursor++ = '\r';
        *cursor++ = '\n';
        if (value.n) {
            std::memcpy(cursor, value.p, value.n);
            cursor += value.n;
        }
        *cursor++ = '\r';
        *cursor++ = '\n';
        return static_cast<uint32_t>(cursor - formatted);
    }

    static bool publish_snapshot(Slot& slot, uint64_t hash, Slice key,
                                 const KvObj* object) noexcept {
        const uint64_t odd = make_odd(slot);
        if (key.n > kKeyBytes || !publishable_object(key, object)) return false;

        char formatted[kReplyBytes];
        const uint32_t reply_len = format_reply(object, formatted);
        if (!reply_len) return false;

        const int64_t expire_at_ms = object->expire_at_ms();
        uint64_t expire_bits;
        std::memcpy(&expire_bits, &expire_at_ms, sizeof(expire_bits));
        atomic_words_store(slot.key, key.p, key.n);
        atomic_words_store(slot.reply, formatted, reply_len);
        slot.shared.hash.store(hash, std::memory_order_relaxed);
        slot.shared.lengths.store((static_cast<uint64_t>(reply_len) << 32) | key.n,
                                  std::memory_order_relaxed);
        slot.shared.expire_at_ms.store(expire_bits, std::memory_order_relaxed);
        slot.shared.sequence.store(odd + 1, std::memory_order_release);
        slot.owner.published = true;
        return true;
    }

    std::unique_ptr<Slot[]> slots_;
    std::unique_ptr<Scratch[]> scratches_;
    uint32_t nshards_ = 0;
    uint32_t nthreads_ = 0;
};

}  // namespace tomo
