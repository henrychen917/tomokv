// atomic_tripwire.h -- explicitly-armed, process-cold MVCC resolver diagnostics.
//
// The state deliberately lives outside Server, Shard, FlatStore, Task, Op, ScatterState and
// AtomicEntry.  --enable-debug-command=no allocates nothing, and none of the footprint-locked
// request/MVCC objects grows.  Allocation alone does NOT arm the probes: observation starts only
// at DEBUG TRIPWIRE ARM, because the armed cost (a shared mutex plus a pending-list walk on every
// atomic read) is a per-op tax that must never ride along with debug-enabled boots -- it once cost
// 9x on atomic multi-key throughput while every harness ran debug-enabled.  A disarmed server --
// debug-enabled or not -- sees one predicted-false flag test at the call sites and no atomic RMWs.
#pragma once

#include <array>
#include <atomic>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <unordered_map>

namespace tomo {

// DEBUG TRIPWIRE rows are intentionally the requested four-tuple.  `phase` makes the rows of the
// one-shot dump self-describing without adding another field to the wire format.
enum class AtomicTripwirePhase : uint32_t {
    PlainBegin       = 1,
    PlainExecution   = 2,
    ChainAnswer      = 3,
    ParkedSmaller    = 4,
};

struct AtomicTripwireRow {
    uint64_t key_hash = 0;
    uint64_t cut = 0;
    uint64_t ticket = 0;
    AtomicTripwirePhase phase = AtomicTripwirePhase::PlainBegin;
};

struct AtomicTripwireCounts {
    uint64_t plain_path_changes = 0;
    uint64_t chain_smaller_tickets = 0;
};

namespace atomic_tripwire_detail {

struct ProbeKey {
    const void* scope = nullptr;       // transaction/scatter lifetime owner
    const void* fragment = nullptr;    // child command or scatter state
    uint64_t slot = 0;                 // shard + key occurrence + wave

    bool operator==(const ProbeKey& other) const {
        return scope == other.scope && fragment == other.fragment && slot == other.slot;
    }
};

struct ProbeKeyHash {
    size_t operator()(const ProbeKey& key) const {
        uint64_t value = static_cast<uint64_t>(reinterpret_cast<uintptr_t>(key.scope));
        value ^= static_cast<uint64_t>(reinterpret_cast<uintptr_t>(key.fragment)) +
                 0x9e3779b97f4a7c15ull + (value << 6) + (value >> 2);
        value ^= key.slot + 0x9e3779b97f4a7c15ull + (value << 6) + (value >> 2);
        value ^= value >> 30;
        value *= 0xbf58476d1ce4e5b9ull;
        value ^= value >> 27;
        value *= 0x94d049bb133111ebull;
        return static_cast<size_t>(value ^ (value >> 31));
    }
};

struct Probe {
    uint64_t key_hash = 0;
    uint64_t cut = 0;
    uint64_t ticket = 0;
    bool needs_version = false;
};

struct State {
    static constexpr size_t kRingRows = 64;
    std::mutex mu;
    AtomicTripwireCounts counts;
    std::array<AtomicTripwireRow, kRingRows> ring{};
    size_t ring_size = 0;
    bool captured = false;
    std::unordered_map<ProbeKey, Probe, ProbeKeyHash> probes;
};

// Written once during Server::init(), before worker threads exist, and never replaced while the
// server runs.  Inline storage keeps the header usable by the header-only FlatStore resolver
// without adding a translation unit or build-system edge.
inline std::unique_ptr<State> state;

// Runtime observation switch.  The pointer above is fixed at init so workers may read it without
// synchronization; this flag is the part a DEBUG command may flip while they run.
inline std::atomic<bool> armed{false};

inline void capture_locked(State& s, const AtomicTripwireRow* rows, size_t count) {
    if (s.captured) return;
    s.captured = true;
    s.ring_size = count < State::kRingRows ? count : State::kRingRows;
    for (size_t i = 0; i < s.ring_size; i++) s.ring[i] = rows[i];
}

}  // namespace atomic_tripwire_detail

inline void atomic_tripwire_configure(bool enabled) {
    if (enabled) {
        if (!atomic_tripwire_detail::state)
            atomic_tripwire_detail::state.reset(
                new (std::nothrow) atomic_tripwire_detail::State());
    } else {
        atomic_tripwire_detail::state.reset();
        atomic_tripwire_detail::armed.store(false, std::memory_order_relaxed);
    }
}

inline bool atomic_tripwire_enabled() {
    return atomic_tripwire_detail::armed.load(std::memory_order_relaxed) &&
           atomic_tripwire_detail::state != nullptr;
}

// Flip observation on or off at runtime; false means there is no state to arm (debug disabled).
// Both transitions drop pending begin-probes: a probe recorded under one arming session must not
// pair with an execution observed in a later one, and disarming mid-flight would otherwise strand
// entries whose consuming call sites have stopped firing.
inline bool atomic_tripwire_arm(bool on) {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return false;
    {
        std::lock_guard<std::mutex> lock(state->mu);
        state->probes.clear();
    }
    atomic_tripwire_detail::armed.store(on, std::memory_order_relaxed);
    return true;
}

// Idempotent across task retries: the first owner observation is the fragment-begin answer and is
// never refreshed.  That is the point of the probe -- a retry must not erase the interval it is
// supposed to observe.
inline void atomic_tripwire_plain_begin(const void* scope, const void* fragment, uint64_t slot,
                                        uint64_t key_hash, uint64_t cut, uint64_t ticket,
                                        bool needs_version) {
    auto* state = atomic_tripwire_detail::state.get();
    // "Plain-path read" is defined at fragment begin. Retain true answers too so a retry cannot
    // replace the first verdict with a later false one; execution filters those out. In particular,
    // routine true->false cleanup while a task waits behind a dependency is not a resolver alarm.
    // The unstable population is a fragment that began plain (false) but reaches execution after
    // the answer became true.
    if (!state) return;
    std::lock_guard<std::mutex> lock(state->mu);
    try {
        state->probes.try_emplace(
            atomic_tripwire_detail::ProbeKey{scope, fragment, slot},
            atomic_tripwire_detail::Probe{key_hash, cut, ticket, needs_version});
    } catch (const std::bad_alloc&) {
        // Diagnostics may lose a sample under memory pressure; command execution must not fail.
    }
}

// Called immediately before a read that has selected FlatStore's plain (non-chain) arm.  Probes
// are consumed even when unchanged, so pointer reuse after a completed command cannot inherit an
// old begin verdict.
inline void atomic_tripwire_plain_execution(const void* scope, const void* fragment,
                                            uint64_t slot, uint64_t key_hash, uint64_t cut,
                                            uint64_t ticket, bool needs_version,
                                            bool plain_path) {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return;
    std::lock_guard<std::mutex> lock(state->mu);
    const atomic_tripwire_detail::ProbeKey probe_key{scope, fragment, slot};
    auto found = state->probes.find(probe_key);
    if (found == state->probes.end()) return;
    const atomic_tripwire_detail::Probe begin = found->second;
    state->probes.erase(found);
    if (!plain_path || begin.needs_version || !needs_version) return;

    state->counts.plain_path_changes++;
    const AtomicTripwireRow rows[] = {
        {begin.key_hash, begin.cut, begin.ticket, AtomicTripwirePhase::PlainBegin},
        {key_hash, cut, ticket, AtomicTripwirePhase::PlainExecution},
    };
    atomic_tripwire_detail::capture_locked(*state, rows, std::size(rows));
}

inline void atomic_tripwire_forget_scope(const void* scope) {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return;
    std::lock_guard<std::mutex> lock(state->mu);
    for (auto it = state->probes.begin(); it != state->probes.end();) {
        if (it->first.scope == scope) it = state->probes.erase(it);
        else ++it;
    }
}

inline void atomic_tripwire_chain_smaller(uint64_t key_hash, uint64_t cut,
                                          uint64_t answer_ticket,
                                          uint64_t smaller_ticket) {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return;
    std::lock_guard<std::mutex> lock(state->mu);
    state->counts.chain_smaller_tickets++;
    const AtomicTripwireRow rows[] = {
        {key_hash, cut, answer_ticket, AtomicTripwirePhase::ChainAnswer},
        {key_hash, cut, smaller_ticket, AtomicTripwirePhase::ParkedSmaller},
    };
    atomic_tripwire_detail::capture_locked(*state, rows, std::size(rows));
}

inline AtomicTripwireCounts atomic_tripwire_counts() {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return {};
    std::lock_guard<std::mutex> lock(state->mu);
    return state->counts;
}

// Empty state deliberately formats as an empty bulk/verbatim payload: a clean acceptance run can
// assert DEBUG TRIPWIRE == b"" without parsing a header.  Once latched, each line is exactly
// `<key-hash> <cut> <ticket> <phase>`; phase values are documented by AtomicTripwirePhase above.
inline std::string atomic_tripwire_dump() {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return {};
    std::lock_guard<std::mutex> lock(state->mu);
    std::string out;
    out.reserve(state->ring_size * 80);
    for (size_t i = 0; i < state->ring_size; i++) {
        const AtomicTripwireRow& row = state->ring[i];
        char line[128];
        const int n = std::snprintf(
            line, sizeof(line), "%016" PRIx64 " %" PRIu64 " %" PRIu64 " %u\n",
            row.key_hash, row.cut, row.ticket, static_cast<unsigned>(row.phase));
        if (n > 0) out.append(line, static_cast<size_t>(n));
    }
    return out;
}

}  // namespace tomo
