// Compile-only view of the actual production predicate; no listener or workload.
#include "src/net/conn.h"

extern "C" bool ntfix3_query_guard(const tomo::Client& client,
                                   uint64_t limit, uint64_t queued) {
    return client.query_buffer_exceeded(limit, queued);
}
