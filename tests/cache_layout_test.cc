// Serverless layout/allocation checks for the cross-thread line-sharing audit.
#include <cassert>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <new>
#include "src/core/thread.h"
#include "src/net/conn.h"

namespace {
size_t aligned_new_calls = 0, aligned_delete_calls = 0;
size_t requested_alignment = 0, deleted_alignment = 0, requested_bytes = 0;
bool fail_aligned_allocation = false;
}

// The replacement pair observes the actual allocation contract. Pointer alignment alone would
// miss a broken unaligned new that merely happened to get a 64-aligned allocator size class.
void* operator new(size_t bytes, std::align_val_t alignment) {
    ++aligned_new_calls;
    requested_alignment = static_cast<size_t>(alignment);
    requested_bytes = bytes;
    if (fail_aligned_allocation) throw std::bad_alloc();
    void* ptr = nullptr;
    if (::posix_memalign(&ptr, requested_alignment, bytes) != 0) throw std::bad_alloc();
    return ptr;
}
void operator delete(void* ptr, std::align_val_t alignment) noexcept {
    ++aligned_delete_calls;
    deleted_alignment = static_cast<size_t>(alignment);
    std::free(ptr);
}

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
    // Drive the production class allocation/deallocation pair without constructing a server or
    // needing a Shard destructor stub. The ordinary unit fixtures cover actual Shard lifetimes.
    std::array<void*, 64> allocations{};
    for (void*& ptr : allocations) {
        ptr = Shard::operator new(sizeof(Shard));
        assert(requested_alignment == 64 && requested_bytes == sizeof(Shard));
        const uintptr_t base = reinterpret_cast<uintptr_t>(ptr);
        assert(base % 64 == 0);
        assert(separate(base, ShardLayoutLock::reader_first, ShardLayoutLock::reader_last,
                        ShardLayoutLock::owner_first, ShardLayoutLock::owner_last));
    }
    assert(aligned_new_calls == allocations.size());
    for (void* ptr : allocations) {
        Shard::operator delete(ptr);
        assert(deleted_alignment == 64);
    }
    assert(aligned_delete_calls == allocations.size());
    fail_aligned_allocation = true;
    bool threw = false;
    try { (void)Shard::operator new(sizeof(Shard)); }
    catch (const std::bad_alloc&) { threw = true; }
    assert(threw && aligned_new_calls == allocations.size() + 1);
    std::puts("cache layout: PASS (size locks, every base residue, aligned Shard new/delete + OOM)");
}
