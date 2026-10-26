// server_tail.cc — the remaining non-clustered server surface.
//
// Everything here is cold. OBJECT and MEMORY reach a shard owner through the shared SubcmdRoute
// hook rather than by putting an argument-shape test anywhere near the dispatch path: their first
// argument decides whether a key exists at all, which is a routing question, not a handler
// question.
//
// Semantics were taken from the documented protocol and from byte-probing a vanilla redis 7.4
// binary and the Redis 7.4 reference source; the implementation is local.
#include "server_tail.h"
#include "cmdmeta.h"

#include "command.h"
#include "acl.h"
#include "acl_categories_generated.h"
#include "slowlog.h"
#include "hll.h"
#include "../base/alloc.h"
#include "../core/config.h"
#include "../core/server.h"
#include "../core/shard.h"
#include "../core/signal_doorbell.h"
#include "../core/thread.h"
#include "../core/version.h"
#include "../exec/op.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../store/eviction.h"
#include "../store/kvobj.h"
#include "../snapshot/snapshot.h"

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

#if defined(TOMO_JEMALLOC)
#include <jemalloc/jemalloc.h>
#endif

namespace tomo {

KvObj* object_read_no_touch(Shard& shard, uint64_t hash, Slice key);
namespace {

bool eq_icase(Slice s, const char* lit) {
    const size_t n = std::strlen(lit);
    if (s.n != n) return false;
    for (size_t i = 0; i < n; i++) {
        unsigned char a = static_cast<unsigned char>(s.p[i]);
        unsigned char b = static_cast<unsigned char>(lit[i]);
        if (a >= 'a' && a <= 'z') a -= 'a' - 'A';
        if (b >= 'a' && b <= 'z') b -= 'a' - 'A';
        if (a != b) return false;
    }
    return true;
}

bool parse_u64(Slice s, uint64_t& out) {
    if (!s.n) return false;
    uint64_t value = 0;
    for (uint32_t i = 0; i < s.n; i++) {
        const char ch = s.p[i];
        if (ch < '0' || ch > '9') return false;
        const uint64_t digit = static_cast<uint64_t>(ch - '0');
        if (value > (UINT64_MAX - digit) / 10) return false;
        value = value * 10 + digit;
    }
    out = value;
    return true;
}

bool parse_i64(Slice s, int64_t& out) {
    if (!s.n || s.n > 20) return false;
    uint32_t i = 0;
    bool negative = false;
    if (s.p[0] == '-') { negative = true; i = 1; }
    if (i >= s.n) return false;
    // Canonical decimal, as redis's string2ll: no leading '+', no leading zeroes, no negative
    // zero. "WAIT +5 1" and "WAIT 0 05" were accepted before this.
    if (s.p[i] == '0') {
        if (negative || i + 1 != s.n) return false;
        out = 0;
        return true;
    }
    if (s.p[i] < '1' || s.p[i] > '9') return false;
    uint64_t value = 0;
    for (; i < s.n; i++) {
        const char ch = s.p[i];
        if (ch < '0' || ch > '9') return false;
        const uint64_t digit = static_cast<uint64_t>(ch - '0');
        if (value > (UINT64_MAX - digit) / 10) return false;
        value = value * 10 + digit;
    }
    const uint64_t limit = negative ? (uint64_t{1} << 63) : (uint64_t{1} << 63) - 1;
    if (value > limit) return false;
    // INT64_MIN has no positive counterpart, so negating the cast of 2^63 is undefined (UBSAN
    // catches it on "WAIT -9223372036854775808 0"). Name the value instead of computing it.
    out = negative ? (value == (uint64_t{1} << 63) ? std::numeric_limits<int64_t>::min()
                                                   : -static_cast<int64_t>(value))
                   : static_cast<int64_t>(value);
    return true;
}

void reply_invalid_integer(Op& op) {
    reply_err(op.sink(), "ERR value is not an integer or out of range");
}

// Redis answers container HELP with an array of simple strings. Keeping the text in one table per
// command makes the reply length self-consistent, which is what redis-cli's pager relies on.
void reply_help(Op& op, const char* const* lines, size_t count) {
    auto sink = op.sink();
    reply_array_header(sink, count);
    for (size_t i = 0; i < count; i++) reply_simple(sink, lines[i]);
}

// ---------------------------------------------------------------------------------------------
// Scope A — parity surface.
// ---------------------------------------------------------------------------------------------

void cmd_time(Shard&, Op& op) {
    timespec ts{};
    ::clock_gettime(CLOCK_REALTIME, &ts);
    char seconds[24], micros[24];
    const uint32_t sn = u64_to_dec(seconds, static_cast<uint64_t>(ts.tv_sec));
    const uint32_t un = u64_to_dec(micros, static_cast<uint64_t>(ts.tv_nsec / 1000));
    auto sink = op.sink();
    reply_array_header(sink, 2);
    reply_bulk(sink, Slice(seconds, sn));
    reply_bulk(sink, Slice(micros, un));
}

// Redis ignores every LOLWUT argument it does not recognise, including a bare VERSION. The art is
// ours; the trailing version line is the part clients actually parse.
void cmd_lolwut(Shard&, Op& op) {
    static const char kArt[] =
        "        .-\"\"\"-.\n"
        "       / .===. \\\n"
        "       \\/ 6 6 \\/     tomokv\n"
        "       ( \\___/ )     two stages, one owner per shard\n"
        "  _ooo__\\_____/__ooo_\n"
        " /                  \\\n"
        "/  io  |  ex  |  io  \\\n"
        "'--------------------'\n";
    std::string body(kArt);
    body += "TomoKV ver. ";
    body += kTomoVersion;
    body += "\n";
    reply_bulk(op.sink(), Slice(body.data(), static_cast<uint32_t>(body.size())));
}

// Standalone only. The empty third element is redis's replica list.
void cmd_role(Shard&, Op& op) {
    auto sink = op.sink();
    reply_array_header(sink, 3);
    reply_bulk(sink, Slice("master", 6));
    reply_int(sink, 0);
    reply_array_header(sink, 0);
}

// MULTI executes WAIT without blocking. Standalone dispatch handles an Unsatisfied result before
// calling this handler and completes the published ROB slot from the IO-owned deadline list.
void cmd_wait(Shard&, Op& op) {
    uint64_t timeout_ms = 0;
    if (server_tail_prepare_wait(op, timeout_ms) == WaitCommandResult::Error) return;
    reply_int(op.sink(), 0);
}

// MULTI shares validation but cannot block. Ordinary WAITAOF uses WAIT's
// deferred connection timer, including an infinite deadline when timeout is zero.
// Local fsync acknowledgements remain explicitly unsupported.
void cmd_waitaof(Shard&, Op& op) {
    uint64_t timeout_ms = 0;
    if (server_tail_prepare_wait(op, timeout_ms) != WaitCommandResult::Error)
        server_tail_reply_wait(op);
}

void cmd_failover(Shard&, Op& op) {
    if (op.argc() == 2 && eq_icase(op.arg(1), "ABORT")) {
        reply_err(op.sink(), "ERR No failover in progress.");
        return;
    }
    if (op.argc() != 1) { reply_syntax(op.sink()); return; }
    reply_err(op.sink(), "ERR FAILOVER requires connected replicas.");
}

// DELIBERATE DEVIATION. Redis answers +OK and starts replicating. TomoKV has no replication at
// all, and silently accepting the command would leave a client believing it had a replica. An
// explicit error is the honest answer.
void cmd_replicaof(Shard&, Op& op) {
    reply_err(op.sink(), "ERR replication is not supported by tomokv");
}

void cmd_pfselftest(Shard&, Op& op) {
    const std::string error = hll::selftest();
    if (error.empty()) reply_ok(op.sink());
    else reply_err(op.sink(), error.c_str());
}

// SHUTDOWN. On success redis sends NO reply -- the connection simply closes as the process goes
// away -- so the only replies here are the refusals.
//
} // namespace

// Both command and signal requests land here on an IO owner. A required save must succeed
// before publishing any stop flags; Busy is a refusal, never permission to discard writes.
SnapshotManager::StartResult Server::shutdown(ShutdownSave save, ThreadCtx* writer, Ring* ring,
                                              std::string& error, bool force, bool from_signal) {
    std::unique_lock lock(shutdown_mu_, std::try_to_lock);
    if (!lock.owns_lock()) {
        error = "shutdown is already in progress";
        return SnapshotManager::StartResult::Busy;
    }
    // ABORT and the signal request's admission use the same mutex. A request
    // cancelled before admission must not proceed with a previously read policy.
    if (from_signal && !signal_shutdown_pending()) return SnapshotManager::StartResult::Started;
    const bool must_save = save == ShutdownSave::Save ||
        (save == ShutdownSave::Configured && save_schedule_armed());
    if (must_save) {
        if (!writer || !ring) {
            error = "shutdown save has no IO owner";
            return SnapshotManager::StartResult::Failed;
        }
        const auto cancelled = snapshot_.cancel_for_shutdown(*this, *writer, *ring, error);
        if (cancelled != SnapshotManager::StartResult::Started) {
            if (!force || cancelled == SnapshotManager::StartResult::Busy) return cancelled;
            finish_shutdown();
            return SnapshotManager::StartResult::Started;
        }
        const auto result = snapshot_.start(*this, *writer, *ring, true, error,
                                             nullptr, nullptr, nullptr, true);
        if (result != SnapshotManager::StartResult::Started) {
            set_shutdown_snapshot_active(false);
            if (force && result == SnapshotManager::StartResult::Failed) {
                std::fprintf(stderr, "Shutdown save failed: %s; FORCE permits exit\n", error.c_str());
                finish_shutdown();
                return SnapshotManager::StartResult::Started;
            }
            return result;
        }
        // Owners stay frozen from the cut through capture and enter ShutdownHeld
        // on the final-chunk pass. No post-cut command gets a Draining turn before
        // the writer publishes stop after the final fsync (or failure resumes service).
    } else {
        finish_shutdown();
    }
    return SnapshotManager::StartResult::Started;
}

void Server::set_shutdown_policy(bool interrupt, uint8_t flags) {
    std::atomic_ref<uint8_t>(interrupt ? cfg_.shutdown_on_sigint : cfg_.shutdown_on_sigterm)
        .store(flags, std::memory_order_relaxed);
}

bool Server::request_signal_shutdown(bool interrupt) {
    if (loading()) return false;
    static_assert(std::atomic_ref<uint8_t>::is_always_lock_free);
    const uint8_t flags = std::atomic_ref<uint8_t>(
        interrupt ? cfg_.shutdown_on_sigint : cfg_.shutdown_on_sigterm).load(std::memory_order_relaxed);
    if ((flags & ShutdownNoSaveFlag) || (!(flags & ShutdownSaveFlag) && !save_schedule_armed()))
        return false;
    uint64_t unset = 0;
    signal_shutdown_deadline_ns_.compare_exchange_strong(
        unset, now_ns() + kShutdownSaveWaitNs, std::memory_order_relaxed);
    uint8_t current = live_save_armed_.load(std::memory_order_relaxed);
    do {
        if (current & kSignalShutdown) return true;
    } while (!live_save_armed_.compare_exchange_weak(current,
        uint8_t(current | kSignalShutdown | (flags << 2)), std::memory_order_release));
    return true;
}

bool Server::abort_signal_shutdown() {
    std::unique_lock lock(shutdown_mu_, std::try_to_lock);
    if (!lock.owns_lock() || shutdown_snapshot_active() || shutting_down()) return false;
    const uint8_t old = live_save_armed_.fetch_and(uint8_t(~(kSignalShutdown | 0x3c)),
                                                 std::memory_order_acq_rel);
    if (!(old & kSignalShutdown)) return false;
    signal_shutdown_deadline_ns_.store(0, std::memory_order_relaxed);
    signal_doorbell_consume_request();
    return true;
}

void Server::finish_shutdown() {
    shutting_down().store(true, std::memory_order_relaxed);
    for (uint32_t i = 0; i < nthreads(); ++i)
        thread(i).stop_flag().store(true, std::memory_order_relaxed);
    signal_doorbell_notify();
}

uint32_t Server::shutdown_from_cron(ThreadCtx& writer, Ring& ring) {
    // This is a request, not the terminal edge. In particular a failed save leaves no readable
    // eventfd that could spin every epoll worker. finish_shutdown rings a new, sticky stop edge.
    signal_doorbell_consume_request();
    std::string error;
    const uint8_t flags = live_save_armed_.load(std::memory_order_acquire) >> 2;
    auto result = shutdown(flags & ShutdownSaveFlag ? ShutdownSave::Save : ShutdownSave::Configured,
                           &writer, &ring, error, flags & ShutdownForceFlag, true);
    if (result == SnapshotManager::StartResult::Busy) {
        if (now_ns() < signal_shutdown_deadline_ns_.load(std::memory_order_relaxed))
            return 0; // yield to the old snapshot/FLIP, retry at the next ordinary IO pass
        error = "shutdown timed out waiting for snapshot/placement; retry SHUTDOWN";
        result = SnapshotManager::StartResult::Failed;
    }
    live_save_armed_.fetch_and(uint8_t(~(kSignalShutdown | 0x3c)), std::memory_order_relaxed);
    signal_shutdown_deadline_ns_.store(0, std::memory_order_relaxed);
    if (result == SnapshotManager::StartResult::Failed)
        std::fprintf(stderr, "Errors trying to SHUTDOWN: %s; server remains running\n", error.c_str());
    return 1;
}

namespace {

void cmd_shutdown(Shard&, Op& op) {
    bool nosave = false, save = false, force = false, abort = false, now = false;
    for (uint32_t i = 1; i < op.argc(); i++) {
        if (eq_icase(op.arg(i), "NOSAVE")) nosave = true;
        else if (eq_icase(op.arg(i), "SAVE")) save = true;
        else if (eq_icase(op.arg(i), "NOW")) now = true;
        else if (eq_icase(op.arg(i), "FORCE")) force = true;
        else if (eq_icase(op.arg(i), "ABORT")) abort = true;
        else { reply_syntax(op.sink()); return; }
    }
    if (nosave && save) { reply_syntax(op.sink()); return; }
    if (abort) for (uint32_t i = 1; i < op.argc(); ++i)
        if (!eq_icase(op.arg(i), "ABORT")) { reply_syntax(op.sink()); return; }

    Server* server = command_server();
    if (!server) { reply_err(op.sink(), "ERR server is not bound"); return; }
    if (abort) {
        if (server->abort_signal_shutdown()) reply_ok(op.sink());
        else reply_err(op.sink(), "ERR No shutdown in progress.");
        return;
    }
    if (Client* client = command_local_client(); !now && client &&
        client->barrier_held_by(BarrierOwner::Exec)) {
        reply_err(op.sink(), "ERR SHUTDOWN without NOW or ABORT isn't allowed for DENY BLOCKING client");
        return;
    }

    const SnapshotIoContext context = snapshot_io_context();
    const auto choice = nosave ? Server::ShutdownSave::NoSave :
                        save ? Server::ShutdownSave::Save : Server::ShutdownSave::Configured;
    std::string error;
    if (server->shutdown(choice, context.thread, context.ring, error, force) !=
        SnapshotManager::StartResult::Started) {
        std::fprintf(stderr, "Errors trying to SHUTDOWN: %s; server remains running\n", error.c_str());
        reply_err(op.sink(), "ERR Errors trying to SHUTDOWN. Check logs.");
        return;
    }
    // Deliberately no reply: the client observes a closed connection, exactly like redis.
}

// ---------------------------------------------------------------------------------------------
// Scope C — OBJECT.
// ---------------------------------------------------------------------------------------------

// Redis-name encoding table. Our representations do not line up one-for-one with redis's, so this
// is a deliberate, stable mapping rather than a passthrough of internal names:
//
//   string   Enc::Int                              -> int
//   string   Enc::Raw    (value inline, <= 192B)   -> embstr
//   string   Enc::Extern (separate block,  > 192B) -> raw
//   hash     Compact / Hashtable                   -> listpack / hashtable
//   list     Compact / Deque                       -> listpack / quicklist
//   set      Compact+Integer / Compact+Generic     -> intset / listpack
//   set      Hashtable                             -> hashtable
//   zset     Compact / Btree                       -> listpack / skiplist
//   stream   any                                   -> stream
//
// The embstr/raw boundary is kEmbedThreshold (192), not redis's 44: the names describe the same
// distinction (value bytes inside the object block vs. a separate allocation) at our threshold.
const char* encoding_name(const KvObj* object) {
    const Type type = static_cast<Type>(object->type);
    if (type == Type::String) {
        if (object->is_int()) return "int";
        return static_cast<Enc>(object->enc) == Enc::Extern ? "raw" : "embstr";
    }
    if (type == Type::Stream) return "stream";
    const CollectionRef ref(const_cast<KvObj*>(object));
    const CollectionEncoding encoding = ref.encoding();
    if (type == Type::Set) {
        if (encoding != CollectionEncoding::Compact) return "hashtable";
        // SetVal::small_encoding, packed into aux0 bits 40..47 for the embedded form. Mirrors
        // t_set.cc's set_small_encoding, which is file-local there.
        const SetSmallEncoding small = ref.is_embedded()
            ? static_cast<SetSmallEncoding>((ref.aux0() >> 40) & 0xff)
            : ref.external_as<SetVal>()->small_encoding;
        return small == SetSmallEncoding::Integer ? "intset" : "listpack";
    }
    switch (encoding) {
        case CollectionEncoding::Compact:   return "listpack";
        case CollectionEncoding::Hashtable: return "hashtable";
        case CollectionEncoding::Deque:     return type == Type::List ? "quicklist" : "stream";
        case CollectionEncoding::Btree:     return "skiplist";
    }
    return "unknown";
}

const char* const kObjectHelp[] = {
    "OBJECT <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
    "ENCODING <key>",
    "    Return the kind of internal representation used in order to store the value",
    "    associated with a <key>.",
    "FREQ <key>",
    "    Return the access frequency index of the <key>. The returned integer is",
    "    proportional to the logarithm of the recent access frequency of the key.",
    "IDLETIME <key>",
    "    Return the idle time of the <key>, that is the approximated number of",
    "    seconds elapsed since the last access to the key.",
    "REFCOUNT <key>",
    "    Return the number of references of the value associated with the specified",
    "    <key>.",
    "HELP",
    "    Print this help.",
};

template <bool kNotify>
void cmd_object_impl(Shard& shard, Op& op) {
    int16_t first_key = 0;
    if (!command_validate_container_subcommand(op, *op.spec, first_key)) return;
    const Slice sub = op.arg(1);
    if (eq_icase(sub, "HELP")) {
        reply_help(op, kObjectHelp, sizeof(kObjectHelp) / sizeof(kObjectHelp[0]));
        return;
    }
    const bool encoding = eq_icase(sub, "ENCODING");
    const bool refcount = eq_icase(sub, "REFCOUNT");
    const bool idletime = eq_icase(sub, "IDLETIME");
    const bool freq     = eq_icase(sub, "FREQ");

    // Redis uses LOOKUP_NOTOUCH|LOOKUP_NONOTIFY for every OBJECT lookup.
    // Lazy expiry still has its physical event; a missing key has no keymiss.
    const uint64_t expired_before = shard.stats().expired;
    KvObj* object = object_read_no_touch(shard, op.hash, op.arg(2));
    if constexpr (kNotify) notify_overwrite_expiry(shard, expired_before, op.arg(2));
    if (!object) { reply_null(op.sink(), op.resp3()); return; }

    const MaxmemoryPolicy policy = shard.store().maxmemory_policy();
    const bool lfu = maxmemory_policy_is_lfu(policy);
    // Policy errors follow the key lookup, including its lazy-expiry effects.
    if (freq && !lfu) {
        reply_err(op.sink(),
                  "ERR An LFU maxmemory policy is not selected, access frequency not tracked. Please note that when switching between policies at runtime LRU and LFU data will take some time to adjust.");
        return;
    }
    if (idletime && lfu) {
        reply_err(op.sink(),
                  "ERR An LFU maxmemory policy is selected, idle time not tracked. Please note that when switching between policies at runtime LRU and LFU data will take some time to adjust.");
        return;
    }

    if (encoding) {
        const char* name = encoding_name(object);
        reply_bulk(op.sink(), Slice(name, static_cast<uint32_t>(std::strlen(name))));
        return;
    }
    if (refcount) {
        // Our model has no shared-object table: every value is owned by exactly one key, so the
        // refcount is always 1. Redis reports INT_MAX for its shared small integers; that
        // divergence is documented rather than faked.
        reply_int(op.sink(), 1);
        return;
    }
    if (freq) { reply_int(op.sink(), object->eviction_meta()); return; }
    reply_int(op.sink(), shard.store().object_idle_seconds(object));
}

void cmd_object(Shard& shard, Op& op) { cmd_object_impl<false>(shard, op); }
void cmd_object_notify(Shard& shard, Op& op) { cmd_object_impl<true>(shard, op); }

// ---------------------------------------------------------------------------------------------
// Scope C — MEMORY.
// ---------------------------------------------------------------------------------------------

const char* const kMemoryHelp[] = {
    "MEMORY <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
    "DOCTOR",
    "    Return memory problems reports.",
    "MALLOC-STATS",
    "    Return internal statistics report from the memory allocator.",
    "PURGE",
    "    Attempt to purge dirty pages for reclamation by the allocator.",
    "STATS",
    "    Return information about the memory usage of the server.",
    "USAGE <key> [SAMPLES <count>]",
    "    Return memory in bytes used by <key> and its value. TomoKV accounts a key exactly,",
    "    so SAMPLES is accepted and ignored.",
    "HELP",
    "    Print this help.",
};

struct JeStats {
    bool     available = false;
    uint64_t allocated = 0;
    uint64_t active = 0;
    uint64_t resident = 0;
    uint64_t mapped = 0;
};

JeStats read_je_stats() {
    JeStats stats;
#if defined(TOMO_JEMALLOC)
    uint64_t epoch = 1;
    size_t epoch_size = sizeof(epoch);
    if (mallctl("epoch", &epoch, &epoch_size, &epoch, sizeof(epoch)) != 0) return stats;
    size_t value = 0, size = sizeof(value);
    stats.available = true;
    size = sizeof(value); if (!mallctl("stats.allocated", &value, &size, nullptr, 0)) stats.allocated = value;
    size = sizeof(value); if (!mallctl("stats.active", &value, &size, nullptr, 0)) stats.active = value;
    size = sizeof(value); if (!mallctl("stats.resident", &value, &size, nullptr, 0)) stats.resident = value;
    size = sizeof(value); if (!mallctl("stats.mapped", &value, &size, nullptr, 0)) stats.mapped = value;
#endif
    return stats;
}

void reply_map_pair_int(Op::Sink& sink, const char* name, unsigned long long value) {
    reply_bulk(sink, Slice(name, static_cast<uint32_t>(std::strlen(name))));
    reply_int(sink, static_cast<long long>(value));
}

void reply_memory_stats(Op& op) {
    Server* server = command_server();
    const JeStats je = read_je_stats();
    uint64_t keys = 0, obj_bytes = 0, expires = 0;
    std::vector<std::pair<std::string, uint64_t>> per_shard;
    if (server) {
        for (uint32_t i = 0; i < server->nshards(); i++) {
            const Shard& shard = server->shard(static_cast<int32_t>(i));
            keys += shard.published_size();
            obj_bytes += shard.published_obj_bytes();
            expires += shard.published_expires();
            per_shard.emplace_back("shard." + std::to_string(i), shard.published_obj_bytes());
        }
    }
    const uint64_t slot_overhead = keys * FlatStore::kSlotOverheadPerKey;
    const uint64_t dataset = obj_bytes + slot_overhead;
    // Per-connection bytes are IO-thread-owned and are not aggregated across threads anywhere in
    // the tree; the live client count with the fixed Client footprint is the honest lower bound.
    const uint64_t clients = server ? server->live_clients() * sizeof(Client) : 0;

    auto sink = op.sink();
    const size_t rows = 8 + per_shard.size() + (je.available ? 6 : 0);
    reply_map_header(sink, rows, op.resp3());
    reply_map_pair_int(sink, "total.allocated", je.available ? je.allocated : dataset);
    reply_map_pair_int(sink, "dataset.bytes", dataset);
    reply_map_pair_int(sink, "keys.count", keys);
    reply_map_pair_int(sink, "keys.bytes-per-key", keys ? dataset / keys : 0);
    reply_map_pair_int(sink, "overhead.slots", slot_overhead);
    reply_map_pair_int(sink, "keys.with-expiry", expires);
    reply_map_pair_int(sink, "clients.normal", clients);
    reply_map_pair_int(sink, "shards.count", per_shard.size());
    for (const auto& entry : per_shard) {
        reply_bulk(sink, Slice(entry.first.data(), static_cast<uint32_t>(entry.first.size())));
        reply_int(sink, static_cast<long long>(entry.second));
    }
    if (je.available) {
        reply_map_pair_int(sink, "allocator.allocated", je.allocated);
        reply_map_pair_int(sink, "allocator.active", je.active);
        reply_map_pair_int(sink, "allocator.resident", je.resident);
        reply_map_pair_int(sink, "allocator.mapped", je.mapped);
        // Redis publishes these as doubles; the ratio is the number operators actually read.
        reply_bulk(sink, Slice("allocator-fragmentation.ratio", 29));
        reply_double(sink, je.allocated ? static_cast<double>(je.active) /
                                          static_cast<double>(je.allocated) : 0.0, op.resp3());
        reply_bulk(sink, Slice("allocator-fragmentation.bytes", 29));
        reply_int(sink, static_cast<long long>(je.active > je.allocated
                                               ? je.active - je.allocated : 0));
    }
}

void reply_memory_doctor(Op& op) {
    const JeStats je = read_je_stats();
    Server* server = command_server();
    uint64_t keys = 0, obj_bytes = 0;
    if (server)
        for (uint32_t i = 0; i < server->nshards(); i++) {
            keys += server->shard(static_cast<int32_t>(i)).published_size();
            obj_bytes += server->shard(static_cast<int32_t>(i)).published_obj_bytes();
        }
    std::string text;
    if (keys < 128) {
        text = "This instance is holding very little data, so there is nothing for the memory "
               "report to work with. Fill it and ask again.";
    } else {
        const double fragmentation = (je.available && je.allocated)
            ? static_cast<double>(je.active) / static_cast<double>(je.allocated) : 1.0;
        char line[256];
        std::snprintf(line, sizeof(line),
                      "%llu keys hold %llu accounted bytes across the shard owners; allocator "
                      "fragmentation ratio is %.2f.",
                      static_cast<unsigned long long>(keys),
                      static_cast<unsigned long long>(obj_bytes), fragmentation);
        text = line;
        if (fragmentation > 1.5)
            text += " That is high: MEMORY PURGE may return dirty pages to the operating system.";
        else
            text += " Nothing here looks wrong.";
    }
    reply_verbatim(op.sink(), Slice(text.data(), static_cast<uint32_t>(text.size())), "txt",
                   op.resp3());
}

#if defined(TOMO_JEMALLOC)
void je_stats_writer(void* context, const char* text) {
    static_cast<std::string*>(context)->append(text);
}
#endif

void reply_memory_malloc_stats(Op& op) {
    std::string text;
#if defined(TOMO_JEMALLOC)
    malloc_stats_print(je_stats_writer, &text, "");
#endif
    if (text.empty()) {
        text = "allocator is ";
        text += alloc_backend();
        text += "; no statistics interface is available in this build.\n";
    }
    reply_verbatim(op.sink(), Slice(text.data(), static_cast<uint32_t>(text.size())), "txt",
                   op.resp3());
}

void reply_memory_purge(Op& op) {
#if defined(TOMO_JEMALLOC)
    // Every executor binds its own arena (alloc.h bind_thread_arena), so there is no single index
    // to purge. MALLCTL_ARENAS_ALL is jemalloc's documented all-arenas selector.
    char name[64];
    std::snprintf(name, sizeof(name), "arena.%u.purge",
                  static_cast<unsigned>(MALLCTL_ARENAS_ALL));
    if (mallctl(name, nullptr, nullptr, nullptr, 0) != 0) {
        reply_err(op.sink(), "ERR allocator purge failed");
        return;
    }
#endif
    reply_ok(op.sink());
}

void cmd_memory(Shard& shard, Op& op) {
    int16_t first_key = 0;
    if (!command_validate_container_subcommand(op, *op.spec, first_key)) return;
    const Slice sub = op.arg(1);
    if (eq_icase(sub, "USAGE")) {
        if (op.argc() < 3) {
            reply_err(op.sink(), "ERR wrong number of arguments for 'memory|usage' command");
            return;
        }
        if (op.argc() > 3) {
            // SAMPLES is the only trailing option redis accepts; our accounting is exact, so the
            // count is validated and then ignored.
            uint64_t samples = 0;
            if (op.argc() != 5 || !eq_icase(op.arg(3), "SAMPLES") ||
                !parse_u64(op.arg(4), samples)) {
                reply_syntax(op.sink());
                return;
            }
        }
        // Resident, not readable: redis reads USAGE straight out of the dictionary with no expire
        // check, so a key that is past its deadline but not yet reaped still reports the bytes it
        // is still holding. Every other introspection form (OBJECT, TYPE, TTL) hides it.
        KvObj* object = shard.store().find_resident(op.hash, op.arg(2));
        if (!object) { reply_null(op.sink(), op.resp3()); return; }
        reply_int(op.sink(), static_cast<long long>(kvobj_size(object) +
                                                   FlatStore::kSlotOverheadPerKey));
        return;
    }
    if (eq_icase(sub, "STATS") && op.argc() == 2) { reply_memory_stats(op); return; }
    if (eq_icase(sub, "DOCTOR") && op.argc() == 2) { reply_memory_doctor(op); return; }
    if (eq_icase(sub, "PURGE") && op.argc() == 2) { reply_memory_purge(op); return; }
    if (eq_icase(sub, "MALLOC-STATS") && op.argc() == 2) { reply_memory_malloc_stats(op); return; }
    if (eq_icase(sub, "HELP") && op.argc() == 2) {
        reply_help(op, kMemoryHelp, sizeof(kMemoryHelp) / sizeof(kMemoryHelp[0]));
        return;
    }
}

// ---------------------------------------------------------------------------------------------
// Scope B — CONFIG completion.
// ---------------------------------------------------------------------------------------------

const char* const kConfigHelpText[] = {
    "CONFIG <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
    "GET <pattern>",
    "    Return parameters matching the glob-like <pattern> and their values.",
    "SET <directive> <value>",
    "    Set the configuration <directive> to <value>.",
    "RESETSTAT",
    "    Reset statistics reported by the INFO command.",
    "REWRITE",
    "    Rewrite the configuration file.",
    "HELP",
    "    Print this help.",
};

// CONFIG REWRITE replaces runtime-owned directives and preserves boot-only directives absent
// from the runtime table. Only names accepted by the boot parser are generated; the fixed
// aof-use-rdb-preamble declaration is not a configurable boot directive.
bool config_name_is_rewritable(const std::string& name) {
    static const char* const kNotBootParsed[] = {
        "aof-use-rdb-preamble",
    };
    for (const char* skip : kNotBootParsed)
        if (name == skip) return false;
    return true;
}

std::string config_quote(std::string_view value) {
    // Keep the existing spelling of simple scalars; quote only tokens whose bytes need escaping.
    if (!value.empty() && std::all_of(value.begin(), value.end(), [](unsigned char ch) {
            return ch > 32 && ch < 127 && ch != '\\' && ch != '"' && ch != '\'';
        })) return std::string(value);
    std::string out = "\"";
    constexpr char hex[] = "0123456789abcdef";
    for (unsigned char ch : value) {
        if (ch == '\\' || ch == '"') { out.push_back('\\'); out.push_back(ch); }
        else if (ch < 32 || ch >= 127) {
            out += "\\x";
            out.push_back(hex[ch >> 4]); out.push_back(hex[ch & 15]);
        } else out.push_back(ch);
    }
    out.push_back('"');
    return out;
}

bool config_rewrite(std::string& error) {
    Server* server = command_server();
    if (!server) { error = "server is not bound"; return false; }
    const char* path = server->cfg().conf_path;
    if (!path || !*path) return false;   // caller emits redis's "running without a config file"

    std::vector<std::pair<std::string, std::string>> items;
    command_config_snapshot(items);

    std::string body = "# Generated by tomokv CONFIG REWRITE.\n";
    // The runtime table covers live knobs. Preserve directives it does not own, including
    // repeatable inline ACL users and boot-only recovery/placement settings.
    std::ifstream original(path);
    if (!original) { error = "cannot read original config"; return false; }
    std::string line;
    while (std::getline(original, line)) {
        const size_t first = line.find_first_not_of(" \t\r");
        if (first == std::string::npos || line[first] == '#') continue;
        std::vector<std::string> words;
        if (!cfg_split_args(line.c_str(), words)) {
            error = "invalid original config line"; return false;
        }
        if (words.empty()) continue;
        // Encoding aliases belong to the same runtime directive as their canonical name.
        // Keeping an old alias would preserve a stale value beside the rewritten live value.
        const int encoding = EncodingConfig::find(Slice(words.front().data(), words.front().size()));
        const std::string_view name = encoding >= 0
            ? EncodingConfig::settings[encoding].name : std::string_view(words.front());
        const bool replaced = std::any_of(items.begin(), items.end(), [&](const auto& item) {
            return item.first == name;
        });
        if (!replaced) body += line + "\n";
    }
    if (original.bad()) { error = "cannot read original config"; return false; }
    for (const auto& item : items) {
        if (!config_name_is_rewritable(item.first)) continue;
        if (item.first == "save") {
            std::vector<SaveClause> clauses;
            if (!cfg_parse_save_schedule(item.second.data(), item.second.size(), clauses)) {
                error = "invalid save schedule in runtime table";
                return false;
            }
            if (clauses.empty()) body += "save \"\"\n";
            else for (const SaveClause& clause : clauses)
                body += "save " + std::to_string(clause.seconds) + " " +
                        std::to_string(clause.changes) + "\n";
            continue;
        }
        body += item.first;
        body.push_back(' ');
        // Output limits are a multi-token directive; every other value is one parser token.
        if (item.first == "client-output-buffer-limit" ||
            (item.first == "latency-tracking-info-percentiles" && !item.second.empty()))
            body += item.second;
        else body += config_quote(item.second);
        body.push_back('\n');
    }

    // Write-then-rename so a failure part way through cannot leave a truncated config behind.
    std::string temporary = std::string(path) + ".rewrite.XXXXXX";
    const int fd = ::mkstemp(temporary.data());
    if (fd < 0) { error = std::strerror(errno); return false; }
    FILE* file = ::fdopen(fd, "w");
    if (!file) {
        error = std::strerror(errno);
        ::close(fd); std::remove(temporary.c_str()); return false;
    }
    const size_t written = std::fwrite(body.data(), 1, body.size(), file);
    const bool flushed = std::fflush(file) == 0;
    const bool closed = std::fclose(file) == 0;
    if (written != body.size() || !flushed || !closed) {
        error = "short write";
        std::remove(temporary.c_str());
        return false;
    }
    if (std::rename(temporary.c_str(), path) != 0) {
        error = std::strerror(errno);
        std::remove(temporary.c_str());
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------------------------
// Scope B — COMMAND completion.
// ---------------------------------------------------------------------------------------------

const char* const kCommandHelp[] = {
    "COMMAND <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
    "(no subcommand)",
    "    Return details about all commands.",
    "COUNT",
    "    Return the total number of commands in this server.",
    "LIST",
    "    Return a list of all commands in this server.",
    "INFO [<command-name> ...]",
    "    Return details about multiple commands.",
    "DOCS [<command-name> ...]",
    "    Return documentation details about multiple commands.",
    "GETKEYS <full-command>",
    "    Return the keys from a full command.",
    "GETKEYSANDFLAGS <full-command>",
    "    Return the keys and the access flags from a full command.",
    "HELP",
    "    Print this help.",
};

bool command_getkeys(Op& op, bool with_flags) {
    if (op.argc() < 3) {
        reply_err(op.sink(), "ERR Unknown subcommand or wrong number of arguments for 'GETKEYS'. Try COMMAND HELP.");
        return true;
    }
    const CommandMetadata* metadata = command_metadata_resolve(op, 2);
    if (!metadata) { reply_err(op.sink(), "ERR Invalid command specified"); return true; }
    if (!command_metadata_arity_ok(*metadata, op.argc() - 2)) {
        reply_err(op.sink(), "ERR Invalid number of arguments specified for command");
        return true;
    }
    std::vector<CommandKeyMetadata> keys;
    const CommandMetadataKeysResult result =
        command_metadata_collect_keys(op, 2, *metadata, keys);
    if (result == CommandMetadataKeysResult::InvalidArguments) {
        reply_err(op.sink(), "ERR Invalid arguments specified for command");
        return true;
    }
    if (result == CommandMetadataKeysResult::NoKeyArguments) {
        reply_err(op.sink(), "ERR The command has no key arguments");
        return true;
    }
    auto sink = op.sink();
    reply_array_header(sink, keys.size());
    for (const CommandKeyMetadata& key : keys) {
        if (!with_flags) { reply_bulk(sink, op.arg(key.argument)); continue; }
        reply_array_header(sink, 2);
        reply_bulk(sink, op.arg(key.argument));
        reply_set_header(sink, static_cast<uint64_t>(__builtin_popcount(key.flags)), op.resp3());
        for (uint32_t index = 0; index < command_metadata_key_flag_count(); index++)
            if (key.flags & (uint16_t{1} << index))
                reply_simple(sink, command_metadata_key_flag_name(index));
    }
    return true;
}

bool command_list(Op& op) {
    bool filter_pattern = false, filter_module = false, filter_aclcat = false;
    Slice argument{};
    if (op.argc() == 4 && eq_icase(op.arg(2), "FILTERBY")) {
        reply_syntax(op.sink());
        return true;
    }
    if (op.argc() == 5 && eq_icase(op.arg(2), "FILTERBY")) {
        argument = op.arg(4);
        filter_pattern = eq_icase(op.arg(3), "PATTERN");
        filter_module = eq_icase(op.arg(3), "MODULE");
        filter_aclcat = eq_icase(op.arg(3), "ACLCAT");
        if (!filter_pattern && !filter_module && !filter_aclcat) {
            reply_syntax(op.sink());
            return true;
        }
    } else if (op.argc() != 2) {
        reply_syntax(op.sink());
        return true;
    }

    uint64_t category_bit = 0;
    if (filter_aclcat) {
        for (size_t i = 0; i < kAclCategoryCount; i++)
            if (argument.eq_icase(kAclCategories[i].name)) category_bit = kAclCategories[i].bit;
        // Redis treats an unknown category as a filter matching no commands.
    }

    std::vector<std::string> names;
    for (uint32_t i = 0; i < command_metadata_size(); i++) {
        const CommandMetadata* spec = command_metadata_at(i);
        if (filter_module) continue;                  // no module system: the answer is always none
        const Slice metadata_name = command_metadata_name(*spec);
        // DB0 needs this append call to retain PRE's SHUTDOWN inlining after removing the
        // error path. The multi-database build retains its original constructor spelling.
#if defined(TOMO_SINGLE_DATABASE) && TOMO_SINGLE_DATABASE
        std::string name;
        name.append(metadata_name.p, metadata_name.n);
#else
        std::string name(metadata_name.p, metadata_name.n);
#endif
        if (filter_pattern &&
            !command_glob_match(argument, Slice(name.data(),
                                                static_cast<uint32_t>(name.size())), true)) continue;
        if (filter_aclcat && !(command_metadata_categories(*spec) & category_bit)) continue;
        names.push_back(std::move(name));
    }
    auto sink = op.sink();
    reply_array_header(sink, names.size());
    for (const std::string& name : names)
        reply_bulk(sink, Slice(name.data(), static_cast<uint32_t>(name.size())));
    return true;
}

}  // namespace

WaitCommandResult server_tail_prepare_wait(Op& op, uint64_t& timeout_ms) {
    if (op.argc() == 4) {
        int64_t local = 0, replicas = 0, timeout = 0;
        if (!cfg_parse_integer(op.arg(1), local)) {
            reply_invalid_integer(op); return WaitCommandResult::Error;
        }
        if (local < 0 || local > 1) {
            reply_err(op.sink(), "ERR value is out of range, value must between 0 and 1");
            return WaitCommandResult::Error;
        }
        if (!cfg_parse_integer(op.arg(2), replicas)) {
            reply_invalid_integer(op); return WaitCommandResult::Error;
        }
        if (replicas < 0) {
            reply_err(op.sink(), "ERR value is out of range, must be positive");
            return WaitCommandResult::Error;
        }
        if (!cfg_parse_integer(op.arg(3), timeout)) {
            reply_err(op.sink(), "ERR timeout is not an integer or out of range");
            return WaitCommandResult::Error;
        }
        if (timeout < 0) {
            reply_err(op.sink(), "ERR timeout is negative"); return WaitCommandResult::Error;
        }
        timespec now{};
        ::clock_gettime(CLOCK_REALTIME, &now);
        const int64_t now_ms = static_cast<int64_t>(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
        if (timeout > INT64_MAX - now_ms) {
            reply_err(op.sink(), "ERR timeout is out of range"); return WaitCommandResult::Error;
        }
        Server* server = command_server();
        if (local) {
            reply_err(op.sink(), server && server->aof().configured() ?
                "ERR WAITAOF with numlocal > 0 is not implemented by tomokv: the local fsync wait needs the deferred-reply path, see NOTES-SERVERTAIL.md" :
                "ERR WAITAOF cannot be used when numlocal is set but appendonly is disabled.");
            return WaitCommandResult::Error;
        }
        timeout_ms = static_cast<uint64_t>(timeout);
        return replicas ? WaitCommandResult::Unsatisfied : WaitCommandResult::Immediate;
    }
    int64_t replicas = 0, timeout = 0;
    if (!parse_i64(op.arg(1), replicas)) {
        reply_invalid_integer(op);
        return WaitCommandResult::Error;
    }
    // The timeout has a positional error string rather than WAIT's generic integer spelling.
    if (!parse_i64(op.arg(2), timeout)) {
        reply_err(op.sink(), "ERR timeout is not an integer or out of range");
        return WaitCommandResult::Error;
    }
    if (timeout < 0) {
        reply_err(op.sink(), "ERR timeout is negative");
        return WaitCommandResult::Error;
    }
    // Redis rejects a timeout whose wall-clock deadline would overflow signed milliseconds.
    timespec now{};
    ::clock_gettime(CLOCK_REALTIME, &now);
    const int64_t now_ms = static_cast<int64_t>(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
    if (timeout > INT64_MAX - now_ms) {
        reply_err(op.sink(), "ERR timeout is out of range");
        return WaitCommandResult::Error;
    }
    timeout_ms = static_cast<uint64_t>(timeout);
    return replicas > 0 ? WaitCommandResult::Unsatisfied : WaitCommandResult::Immediate;
}

void server_tail_reply_wait(Op& op) {
    auto sink = op.sink();
    if (op.argc() == 4) {
        reply_array_header(sink, 2);
        reply_int(sink, 0);
    }
    reply_int(sink, 0);
}

bool server_tail_config_subcommand(Op& op) {
    if (eq_icase(op.arg(1), "HELP") && op.argc() == 2) {
        reply_help(op, kConfigHelpText, sizeof(kConfigHelpText) / sizeof(kConfigHelpText[0]));
        return true;
    }
    if (eq_icase(op.arg(1), "RESETSTAT") && op.argc() == 2) {
        command_config_resetstat();
        reply_ok(op.sink());
        return true;
    }
    if (eq_icase(op.arg(1), "REWRITE") && op.argc() == 2) {
        std::string error;
        Server* server = command_server();
        const char* path = server ? server->cfg().conf_path : nullptr;
        if (!path || !*path) {
            reply_err(op.sink(), "ERR The server is running without a config file");
            return true;
        }
        if (!config_rewrite(error)) {
            std::string message = "ERR Rewriting config file: ";
            message += error.empty() ? "unknown error" : error;
            reply_err(op.sink(), message.c_str());
            return true;
        }
        reply_ok(op.sink());
        return true;
    }
    return false;
}

bool server_tail_command_subcommand(Op& op) {
    if (op.argc() < 2) return false;
    if (eq_icase(op.arg(1), "HELP") && op.argc() == 2) {
        reply_help(op, kCommandHelp, sizeof(kCommandHelp) / sizeof(kCommandHelp[0]));
        return true;
    }
    if (eq_icase(op.arg(1), "LIST")) return command_list(op);
    if (eq_icase(op.arg(1), "GETKEYS")) return command_getkeys(op, false);
    if (eq_icase(op.arg(1), "GETKEYSANDFLAGS")) return command_getkeys(op, true);
    return false;
}

// -------------------------------------------------------------------------------------------
// SubcmdRoute resolution. Runs on the IO thread inside the existing special-route hook.
// -------------------------------------------------------------------------------------------
bool command_prepare_subcmd_route(Server& server, Op& op) {
    int16_t first_key = 0;
    if (!command_validate_container_subcommand(op, *op.spec, first_key)) return false;
    if (first_key > 0) {
        op.hash = FlatStore::hash_key(op.arg(static_cast<uint32_t>(first_key)));
        op.shard = server.router().shard_of(op.hash);
        return true;
    }
    // Keyless subcommands are thread-agnostic. Pin them to shard 0 so they travel the ordinary
    // owner path with no special case; keyed children never reach this arm because their generated
    // metadata carries the exact key position.
    op.hash = 0;
    op.shard = 0;
    return true;
}

static const CommandSpec kTable[] = {
    // name       min max flags                                                  handler       first last step
    {"TIME",        1,  1, CmdFlags::ConnLocal,                                  cmd_time,       0,  0, 0},
    {"LOLWUT",      1, -1, CmdFlags::ConnLocal,                                  cmd_lolwut,     0,  0, 0},
    {"ROLE",        1,  1, CmdFlags::ConnLocal,                                  cmd_role,       0,  0, 0},
    {"WAIT",        3,  3, CmdFlags::ConnLocal | CmdFlags::OrderedLocal |
                                CmdFlags::DeferredLocal,                           cmd_wait,       0,  0, 0},
    {"WAITAOF",     4,  4, CmdFlags::ConnLocal | CmdFlags::OrderedLocal | CmdFlags::DeferredLocal,                                  cmd_waitaof,    0,  0, 0},
    {"FAILOVER",    1,  2, CmdFlags::ConnLocal | CmdFlags::Admin,                cmd_failover,   0,  0, 0},
    {"REPLICAOF",   3,  3, CmdFlags::ConnLocal | CmdFlags::Admin,                cmd_replicaof,  0,  0, 0},
    {"SLAVEOF",     3,  3, CmdFlags::ConnLocal | CmdFlags::Admin,                cmd_replicaof,  0,  0, 0},
    {"PFSELFTEST",  1,  1, CmdFlags::ConnLocal | CmdFlags::Admin,                cmd_pfselftest, 0,  0, 0},
    {"SHUTDOWN",    1, -1, CmdFlags::ConnLocal | CmdFlags::Admin,                cmd_shutdown,   0,  0, 0},
    // Read-only SORT: same scatter lowering, same option grammar minus STORE.
    {"SORT_RO",     2, -1, CmdFlags::Readonly | CmdFlags::MultiShard,            cmd_xshard_only,1,  1, 1},
    {"OBJECT",      2,  3, CmdFlags::Readonly | CmdFlags::Admin |
                           CmdFlags::CursorShard | CmdFlags::SubcmdRoute,        cmd_object,     2,  2, 1,
                                                                                 cmd_object_notify},
    {"MEMORY",      2,  5, CmdFlags::Readonly | CmdFlags::Admin |
                           CmdFlags::CursorShard | CmdFlags::SubcmdRoute,        cmd_memory,     2,  2, 1},
};

CommandTable server_tail_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
