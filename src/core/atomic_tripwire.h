// Explicitly armed MVCC diagnostics shared by server.h and FlatStore's header-only resolver.
// State is process-lifetime storage outside footprint-locked request objects, configured before
// workers start. Debug-disabled configuration allocates nothing. Observation requires a separate
// DEBUG TRIPWIRE ARM: armed probes take a mutex and inspect pending versions. Disarmed call sites
// test a relaxed flag and perform no diagnostic RMW; enabling debug commands alone does not arm it.
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

// Each DEBUG TRIPWIRE row is a four-tuple. phase identifies its observation in the one-shot dump.
enum class AtomicTripwirePhase : uint32_t {
    PlainBegin = 1,
    PlainExecution = 2,
    ChainAnswer = 3,
    ParkedSmaller = 4,
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
    // An armed-only unmasked same-key walk classifies chain_smaller observations. masked_out
    // means a key-holding entry with a visible ticket at/below the cut was hidden by the
    // membership filter, so the read used an older version. visible_lost means the walk saw the
    // entry but selected the base version (a ranking defect). undecided counts matching foreign
    // groups whose tickets were unpublished at the read.
    uint64_t samekey_masked_out = 0;
    uint64_t samekey_visible_lost = 0;
    uint64_t samekey_undecided = 0;
    // The undecided class split by a bounded armed-only re-poll of the group's epoch.  A ticket
    // that RESOLVES at or below the reader's cut proves the read skipped a write its cut was
    // required to see (ticket drawn before the read, epoch store not yet visible) -- the
    // publication-race miss.  Resolving above the cut proves the skip was correct.  Unresolved
    // means the poll budget expired with the ticket still unpublished.
    uint64_t samekey_undecided_le_cut = 0;
    uint64_t samekey_undecided_gt_cut = 0;
    // consider() exclusions (armed only): a chain candidate rejected by the visibility test
    // !(epoch <= snapshot || own_committed).  reader_zero means the read carried no origin conn
    // (read context never set for that path); mismatch means it carried one different from the
    // entry's. The ring records the first exclusion using ChainAnswer and ParkedSmaller.
    uint64_t excluded_reader_zero = 0;
    uint64_t excluded_conn_mismatch = 0;
    // Collapse writes that could resurrect a deleted key (armed only): an absent physical slot or
    // boundary-parked slot overwritten with a non-null winner.  other counts every remaining
    // collapse write for rate context.
    uint64_t collapse_undelete = 0;
    uint64_t collapse_write_other = 0;
};

namespace atomic_tripwire_detail {

// Non-owning identity for one command occurrence. Pointer values are keys only; callers must
// forget the scope before its addresses can be reused, and pair begin/execution with one slot.
struct ProbeKey {
    const void* scope = nullptr;     // transaction/scatter lifetime owner
    const void* fragment = nullptr;  // child command or scatter state
    uint64_t slot = 0;               // shard + key occurrence + wave

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

// Contract: owns diagnostic counts, the first captured ring, and pending probes. Worker/debug
// callers hold mu for every access to those fields; probes own values but not their identity
// pointers. Ring capture truncates at 64 rows. Probe allocation may fail without failing a
// command; dump allocation failures propagate. Configure/destruction require stopped workers.
struct State {
    static constexpr size_t kRingRows = 64;
    std::mutex mu;
    AtomicTripwireCounts counts;
    std::array<AtomicTripwireRow, kRingRows> ring{};
    size_t ring_size = 0;
    bool captured = false;
    std::unordered_map<ProbeKey, Probe, ProbeKeyHash> probes;
};

// Configured during Server::init(), before workers exist, and stable while they run. Inline
// storage gives the FlatStore resolver and debug handlers the same state within each namespace.
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

// Startup-only: allocate optional state with nothrow new, or destroy it while workers are absent.
// Allocation failure leaves diagnostics unavailable; configure(true) does not arm observations.
inline void atomic_tripwire_configure(bool enabled) {
    if (enabled) {
        if (!atomic_tripwire_detail::state)
            atomic_tripwire_detail::state.reset(new (std::nothrow) atomic_tripwire_detail::State());
    } else {
        atomic_tripwire_detail::state.reset();
        atomic_tripwire_detail::armed.store(false, std::memory_order_relaxed);
    }
}

inline bool atomic_tripwire_enabled() {
    return atomic_tripwire_detail::armed.load(std::memory_order_relaxed) &&
           atomic_tripwire_detail::state != nullptr;
}

// Debug callers enable/disable observation; false means no state is available. Both transitions
// clear pending probes under mu so disarmed probes do not remain indefinitely. The relaxed flag
// controls sampling, not object lifetime. A strict boundary against probes already in flight is
// not established by this function; the flag store occurs after releasing mu.
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
inline void atomic_tripwire_plain_execution(const void* scope, const void* fragment, uint64_t slot,
                                            uint64_t key_hash, uint64_t cut, uint64_t ticket,
                                            bool needs_version, bool plain_path) {
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
        if (it->first.scope == scope)
            it = state->probes.erase(it);
        else
            ++it;
    }
}

inline void atomic_tripwire_chain_smaller(uint64_t key_hash, uint64_t cut, uint64_t answer_ticket,
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

enum class AtomicTripwireSamekey : uint32_t {
    MaskedOut = 0,
    VisibleLost = 1,
    Undecided = 2,
    UndecidedLeCut = 3,
    UndecidedGtCut = 4,
};

// An armed collapse observation: was_null && !now_null means cleanup replaced an absent key
// with a value, which can expose deletion resurrection. Other writes supply comparison counts.
inline void atomic_tripwire_collapse_write(uint64_t key_hash, bool was_null, bool now_null,
                                           uint64_t winner_epoch) {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return;
    std::lock_guard<std::mutex> lock(state->mu);
    if (was_null && !now_null) {
        state->counts.collapse_undelete++;
        const AtomicTripwireRow rows[] = {
            {key_hash, winner_epoch, 0, AtomicTripwirePhase::ChainAnswer},
        };
        atomic_tripwire_detail::capture_locked(*state, rows, std::size(rows));
    } else {
        state->counts.collapse_write_other++;
    }
}

// A consider() exclusion by the visibility filter, with the geometry the filter judged.  The two
// counters split by whether the read carried an origin connection at all; the ring latches the
// first occurrence as a (cut, epoch) pair plus a (reader, owner) conn-id pair.
inline void atomic_tripwire_excluded(uint64_t key_hash, uint64_t snapshot, uint64_t epoch,
                                     uint64_t reader_conn, uint64_t owner_conn) {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return;
    std::lock_guard<std::mutex> lock(state->mu);
    if (reader_conn == 0)
        state->counts.excluded_reader_zero++;
    else
        state->counts.excluded_conn_mismatch++;
    const AtomicTripwireRow rows[] = {
        {key_hash, snapshot, epoch, AtomicTripwirePhase::ChainAnswer},
        {reader_conn, owner_conn, epoch, AtomicTripwirePhase::ParkedSmaller},
    };
    atomic_tripwire_detail::capture_locked(*state, rows, std::size(rows));
}

inline void atomic_tripwire_samekey(AtomicTripwireSamekey kind) {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return;
    std::lock_guard<std::mutex> lock(state->mu);
    switch (kind) {
        case AtomicTripwireSamekey::MaskedOut:
            state->counts.samekey_masked_out++;
            break;
        case AtomicTripwireSamekey::VisibleLost:
            state->counts.samekey_visible_lost++;
            break;
        case AtomicTripwireSamekey::Undecided:
            state->counts.samekey_undecided++;
            break;
        case AtomicTripwireSamekey::UndecidedLeCut:
            state->counts.samekey_undecided_le_cut++;
            break;
        case AtomicTripwireSamekey::UndecidedGtCut:
            state->counts.samekey_undecided_gt_cut++;
            break;
    }
}

inline AtomicTripwireCounts atomic_tripwire_counts() {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return {};
    std::lock_guard<std::mutex> lock(state->mu);
    return state->counts;
}

// Debug readers copy the first captured rows under mu. Empty state produces an empty payload;
// otherwise each line is `<key-hash> <cut> <ticket> <phase>` (see AtomicTripwirePhase).
// Output allocation can throw; no resolver or command-state ownership is transferred.
inline std::string atomic_tripwire_dump() {
    auto* state = atomic_tripwire_detail::state.get();
    if (!state) return {};
    std::lock_guard<std::mutex> lock(state->mu);
    std::string out;
    out.reserve(state->ring_size * 80);
    for (size_t i = 0; i < state->ring_size; i++) {
        const AtomicTripwireRow& row = state->ring[i];
        char line[128];
        const int n =
            std::snprintf(line, sizeof(line), "%016" PRIx64 " %" PRIu64 " %" PRIu64 " %u\n",
                          row.key_hash, row.cut, row.ticket, static_cast<unsigned>(row.phase));
        if (n > 0) out.append(line, static_cast<size_t>(n));
    }
    return out;
}

}  // namespace tomo
