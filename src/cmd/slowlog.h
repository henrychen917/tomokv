// slowlog.h — the SLOWLOG + LATENCY recording hook.
//
// ZERO COST WHEN OFF IS THE WHOLE DESIGN. With slowlog-log-slower-than = -1 and
// latency-monitor-threshold = 0 the executor pays exactly one predicted-false branch PER BATCH --
// not per op -- and reads no clock at all. Everything below that gate is out of line.
//
// WHEN ARMED the executor times at BATCH granularity (two clock reads per <=32 ops) and escalates
// to per-op timing only after a batch overruns. A one-op batch is exact; a multi-op batch is
// screened by its per-op average and, if it overruns, arms exact timing for the next 64 batches.
// Unlike redis's per-command timing, a one-off slow op in that first multi-op batch is not logged.
#pragma once
#include <cstdint>
#include <memory>

namespace tomo {

class Op;
class Shard;
struct Config;
class Server;
class ThreadCtx;
class Ring;
class Client;
class IoLoop;
class ScatterArenaPool;
struct Task;
enum class ScatterTaskResult : uint8_t;

// Latched once per executor pass from the live-config seqlock; passed by value into the hook so
// the armed test is a register compare, not a memory load, inside the batch loop.
struct SlowlogArm {
    // Microseconds. Negative means the slow log is disabled. 0 means "log everything".
    int64_t  slowlog_us = -1;
    // Milliseconds. 0 means the latency monitor is disabled.
    uint32_t latency_ms = 0;
    bool latency_tracking = false; // existing padding; no SlowlogArm size change
    bool armed() const { return slowlog_us >= 0 || latency_ms != 0 || latency_tracking; }
};

// Redis truncation rules for a logged command: at most 32 arguments, at most 128 bytes each.
inline constexpr uint32_t kSlowlogMaxArgs = 32;
inline constexpr uint32_t kSlowlogMaxArgBytes = 128;

// A snapshot of one command's arguments, taken BEFORE completion publication.
//
// THIS IS A LIFETIME FIX, NOT AN OPTIMISATION. Op::argv are Slices into the connection's read
// buffer, which is pinned only until the op retires. execute() publishes OpState::Done, and the
// owning IO thread may then retire the op and call reset_rbuf_at_quiescence(), which memmoves and
// can even realloc that buffer. Reading argv from the executor after execute() returns is
// therefore a use-after-retire race. Exact timing now tests the threshold at completion,
// then copies only a slow operation's arguments while they are still pinned.
struct SlowlogIdentity;

struct SlowlogCapture {
    uint32_t total_argc = 0;                 // argc before truncation
    uint32_t captured = 0;                   // arguments actually stored
    uint32_t used = 0;                       // bytes consumed in `bytes`
    uint32_t off[kSlowlogMaxArgs] = {};
    uint32_t len[kSlowlogMaxArgs] = {};      // stored length, <= kSlowlogMaxArgBytes
    uint32_t full[kSlowlogMaxArgs] = {};     // original length, for the truncation marker
    char     bytes[kSlowlogMaxArgs * kSlowlogMaxArgBytes];
};

// One executor's recorder state. Lives at the cold tail of ExLoop.
struct SlowlogExState {
    // Batches remaining in per-op (exact attribution) mode. Set when a multi-op batch overruns.
    uint32_t escalate_batches = 0;
    SlowlogCapture capture; // retained footprint; exact completion uses a cold stack capture
};

// Exact timing owns this stack frame only until execution returns. Completion
// records before Done/AofWait can release argv or let a younger SETNAME run.
// Ordinary, untimed executor specializations never create or consult it.
struct SlowlogTiming {
    const Op* op = nullptr;
    uint64_t client_id = 0;
    uint64_t started = 0;
    int64_t now_ms = 0;
    SlowlogArm arm{};
    uint32_t thread_id = 0;
    bool completed = false;
    SlowlogTiming* previous = nullptr;

    SlowlogTiming() = default;
    SlowlogTiming(const Op* operation, uint64_t client, uint32_t thread,
                  uint64_t start, int64_t now, const SlowlogArm& setting);
    ~SlowlogTiming();
    SlowlogTiming(const SlowlogTiming&) = delete;
    SlowlogTiming& operator=(const SlowlogTiming&) = delete;
};

// Cold completion paths may finish a different client's blocked operation.
// Match the active operation, and record it at most once before publication.
void slowlog_complete(const Op& op);

// Copies pinned arguments (at most 32 of 128 bytes) and snapshots the identity under the
// directory shard lock. The returned shared reference keeps that version alive across Done;
// the caller retains it until recording finishes. Used only by armed per-op timing.
std::shared_ptr<const SlowlogIdentity> slowlog_capture(
    const Op& op, SlowlogCapture& out, uint64_t client_id);

// The executor-side recorder, fed from a capture rather than from the (possibly retired) op.
void slowlog_record_captured(uint32_t thread_id, const std::shared_ptr<const SlowlogIdentity>& identity,
                             const SlowlogCapture& capture,
                             uint64_t duration_ns, int64_t now_ms, const SlowlogArm& arm);

// Records one completed operation. `duration_ns` is the measured span; `exact` says whether it is
// this op's own time (batch of one, or escalated per-op timing) or the enclosing batch's time.
// Called only from the armed arm of the executor batch loop.
// Preserve the actual start for the bound histogram recorder: callback delay
// must not reconstruct an old span into a newer CONFIG tracking generation.
void slowlog_record(uint32_t thread_id, uint64_t client_id, const Op& op, uint64_t duration_ns,
                    int64_t now_ms, const SlowlogArm& arm, bool exact, uint64_t started);

// Chosen only at a committed configuration boundary. Replaces an existing call,
// rather than adding an off-state predicate to a command's execution path.
// constinit suppresses an implicit TLS initialization guard at every call site.
using SlowlogRecorder = decltype(&slowlog_record);
extern thread_local constinit __attribute__((tls_model("local-exec")))
    SlowlogRecorder slowlog_recorder;
void latency_tracking_bind(bool enabled, uint32_t* escalation = nullptr);
using LatencyScatterExecutor = ScatterTaskResult (*)(const Task&, Shard&, Op&, uint32_t);
extern thread_local constinit __attribute__((tls_model("local-exec")))
    LatencyScatterExecutor latency_xshard_execute;
extern thread_local constinit __attribute__((tls_model("local-exec")))
    LatencyScatterExecutor latency_watch_execute;

using LatencyScatterRetirer = void (*)(Server&, ThreadCtx&, Ring&, Client&, Op&,
    ScatterArenaPool&, uint32_t, void*, void (*)(void*, int32_t, const char*), void (*)(void*));
using LatencyBlockingRetirer = void (*)(Server&, Client&, Op&, ThreadCtx&);
using LatencyMultiRetirer = void (*)(IoLoop&, Client&, Op&);
extern thread_local constinit __attribute__((tls_model("local-exec")))
    LatencyScatterRetirer latency_xshard_retire;
extern thread_local constinit __attribute__((tls_model("local-exec")))
    LatencyBlockingRetirer latency_blocking_retire;
extern thread_local constinit __attribute__((tls_model("local-exec")))
    LatencyMultiRetirer latency_multi_retire;


// Resumable commands accumulate execution slices, never their parked interval.
// These helpers are reached only by the cold scatter/transaction/blocking paths.
void latency_tracking_part(uint32_t executor, const Op& op, uint64_t started);
void latency_tracking_retire(uint32_t executor, const Op& op);
void latency_tracking_retry(const Op& previous, const Op& next);
void latency_tracking_forget(const Op& op);
void latency_tracking_forget_client(Client& client);
void latency_tracking_discard_pending();
void latency_tracking_script_begin(const Op& parent);
void latency_tracking_script_part(uint32_t executor, const Op& parent,
                                  const Op& child, uint64_t started);
struct LatencyTrackingPart {
    uint32_t executor;
    const Op* op;
    uint64_t started;
    LatencyTrackingPart* previous;
    LatencyTrackingPart(uint32_t owner, const Op* command);
    ~LatencyTrackingPart();
    void finish();
};
void latency_tracking_pause(const Op& op);
uint64_t latency_tracking_start();
void latency_tracking_finish(uint32_t executor, const Op& op, uint64_t started);
struct LatencyTrackingScope {
    uint32_t executor;
    const Op& op;
    uint64_t started;
    LatencyTrackingScope(uint32_t owner, const Op& command)
        : executor(owner), op(command), started(latency_tracking_start()) {}
    ~LatencyTrackingScope() { latency_tracking_finish(executor, op, started); }
};
struct LatencyTrackingScriptCall {
    uint32_t executor;
    const Op& parent;
    const Op& child;
    uint64_t started;
    LatencyTrackingScriptCall(uint32_t owner, const Op& script, const Op& command)
        : executor(owner), parent(script), child(command), started(latency_tracking_start()) {}
    ~LatencyTrackingScriptCall() {
        latency_tracking_script_part(executor, parent, child, started);
    }
};

// How many batches stay in per-op timing after an overrun.
inline constexpr uint32_t kSlowlogEscalateBatches = 64;

// Boot seeding from the parsed config, and the live CONFIG SET path.
void slowlog_configure(const Config& config);
void slowlog_set_threshold(int64_t threshold);
void slowlog_set_max_len(uint64_t max_len);

// Mechanism counters. The vacuous-validation rule is load-bearing: a test that cannot see the
// recorder FIRE proves nothing, so these are published in INFO and asserted by tests/slowlog.py.
void slowlog_note_escalation();
void slowlog_note_batch_timed();
uint64_t slowlog_entries_recorded();
uint64_t slowlog_escalations();
uint64_t slowlog_batches_timed();
uint64_t latency_events_recorded();

// Addr/name directory. Connection lifecycle publishes immutable versions; armed recording
// retains a version in each entry, so later rename/disconnect cannot change SLOWLOG GET.
void slowlog_note_client(uint64_t client_id, const char* addr);
void slowlog_note_client_name(uint64_t client_id, const char* name, uint32_t name_len);
void slowlog_forget_client(uint64_t client_id);

// Shared by the cold outer-arity error path; writes the complete SLOWLOG/LATENCY reply.
bool slowlog_validate_container_subcommand(Op& op, bool slowlog);

}  // namespace tomo
