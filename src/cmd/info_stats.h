#pragma once

#include <cstdint>
#include <cstddef>

namespace tomo {
class Op;

// Called only by error producers. prior is a staged script reply, when one exists.
void command_note_error(Op& op, const char* prior = nullptr, size_t prior_size = 0);
class RejectedReplyScope {
public:
    explicit RejectedReplyScope(const Op& op);
    ~RejectedReplyScope();
    static bool contains(const Op& op);
private:
    const Op* previous_;
};

// INFO-only process state. The request paths supply already-existing per-IO counters; sampling,
// division, locking and the memory high-water mark all stay on the cold introspection path.
uint64_t info_stats_sample_ops(uint64_t operations);
uint64_t info_stats_observe_memory(uint64_t used_memory);
void info_stats_reset(uint64_t operations, uint64_t used_memory);

}  // namespace tomo
