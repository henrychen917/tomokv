// Serverless layout/allocation checks for the cross-thread line-sharing audit.
#include <cassert>
#include <cstddef>
#include <cstdio>
#include "src/core/thread.h"
#include "src/net/conn.h"

static bool separate(size_t base, size_t first, size_t last, size_t peer_first, size_t peer_last) {
    return (base + last) / 64 < (base + peer_first) / 64 ||
           (base + peer_last) / 64 < (base + first) / 64;
}

int main() {
    using namespace tomo;
    static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
    static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
    for (size_t base = 0; base < 64; ++base) {
        assert(separate(base, RobLayoutLock::io_first, RobLayoutLock::io_last,
                        RobLayoutLock::frontier_first, RobLayoutLock::frontier_last));
        assert(separate(base, OpLayoutLock::reply_first, OpLayoutLock::reply_last,
                        OpLayoutLock::completion_first, OpLayoutLock::completion_last));
        assert(separate(base, OpLayoutLock::reply_first, OpLayoutLock::reply_last,
                        OpLayoutLock::parse_first, OpLayoutLock::parse_last));
        assert(separate(base, ThreadCtxLayoutLock::task_notify,
                        ThreadCtxLayoutLock::task_notify + sizeof(NotifyMask) - 1,
                        ThreadCtxLayoutLock::parked, ThreadCtxLayoutLock::parked_last));
        assert(separate(base, ThreadCtxLayoutLock::task_notify, ThreadCtxLayoutLock::notify_last,
                        ThreadCtxLayoutLock::nchan, ThreadCtxLayoutLock::nchan_last));
        assert(separate(base, FlatStoreLayoutLock::reader_first, FlatStoreLayoutLock::reader_last,
                        FlatStoreLayoutLock::owner_first, FlatStoreLayoutLock::owner_last));
        assert(separate(base, FlatStoreLayoutLock::reader_first, FlatStoreLayoutLock::reader_last,
                        FlatStoreLayoutLock::atomic_owner_first, FlatStoreLayoutLock::atomic_owner_last));
    }
    for (size_t base = 0; base < sizeof(Client) * 2; base += alignof(Client)) {
        assert(separate(base, ClientRobLayoutLock::io_first, ClientRobLayoutLock::io_last,
                        ClientRobLayoutLock::chunks_first, ClientRobLayoutLock::chunks_last));
        assert(separate(base, ClientRobLayoutLock::io_first, ClientRobLayoutLock::io_last,
                        ClientRobLayoutLock::frontier_first, ClientRobLayoutLock::frontier_last));
        assert(separate(base, ClientRobLayoutLock::chunks_first, ClientRobLayoutLock::chunks_last,
                        ClientRobLayoutLock::frontier_first, ClientRobLayoutLock::frontier_last));
        assert(separate(base, ClientRobLayoutLock::frontier_first, ClientRobLayoutLock::frontier_last,
                        ClientRobLayoutLock::buffers, sizeof(Client) - 1));
    }
    std::puts("cache layout: PASS (size locks and every base residue)");
}
