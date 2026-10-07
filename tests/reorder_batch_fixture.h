// Serverless single-admission fixture for the real production queue implementations.
// Production drains submit/finish directly; this adapter copies emitted tasks back for
// the units' exact permutation and membership oracles.
#pragma once
#include "src/core/reorder.h"

namespace tomo::r7::test {
template <size_t BatchOps, bool Shadow = false>
ReorderResult schedule_test_batch(Task (&tasks)[BatchOps], uint32_t n) {
    if (__builtin_expect(n > BatchOps, false)) std::abort();
    std::conditional_t<Shadow, ShadowReorderQueues<BatchOps>, ExReorderQueues<BatchOps>> queues;
    uint32_t count = 0;
    ReorderResult result;
    auto emit = [&](const Task* selected, uint32_t size, ReorderResult witness) {
        result.multi_client_runs += witness.multi_client_runs;
        result.permuted_runs += witness.permuted_runs;
        if (__builtin_expect(size > n - count, false)) std::abort();
        // submit() has admitted every source entry in this output prefix before calling us.
        // A queued emission can therefore replace it now without touching an unscanned suffix
        // or barrier. Bypassed spans already occupy their final position and need no Task copy.
        if (selected != tasks + count)
            for (uint32_t i = 0; i < size; i++) tasks[count + i] = selected[i];
        count += size;
    };
    queues.submit(tasks, n, emit);
    queues.finish(emit);
    if (count != n) std::abort();
    return result;
}

}  // namespace tomo::r7::test
