#include "src/core/server.h"
#include "src/cmd/xshard.h"
#include <cassert>
#include <cstdio>
#include <new>
#include <cstdlib>

static bool fail_next_allocation = false;
void* operator new(std::size_t size) {
    if (fail_next_allocation) {
        fail_next_allocation = false;
        throw std::bad_alloc();
    }
    if (void* p = std::malloc(size ? size : 1)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
using namespace tomo;
int main() {
    static_assert(sizeof(Op)==336 && sizeof(Client)==1984 && sizeof(ThreadCtx)==1408);
    static_assert(sizeof(Shard)==1440 && sizeof(FlatStore)==944 && sizeof(Rob<64>)==192);
    static_assert(sizeof(AtomicEntry)==144 && sizeof(Config)==624);
    PlainReadCuts refs;
    assert(refs.floor()==UINT64_MAX);
    refs.reserve_one(); refs.add(9); refs.add(9);
    refs.reserve_one(); refs.add(12);
    refs.release(9); assert(refs.floor()==10);
    refs.release(12); assert(refs.floor()==10);
    refs.release(9); assert(refs.floor()==UINT64_MAX);
    refs.add(7); refs.add((1ull<<32)+7); refs.add((1ull<<32)+8);
    refs.release(7); assert(refs.floor()==8);
    refs.release(8); assert(refs.floor()==8);
    refs.release(7); assert(refs.floor()==UINT64_MAX);
    assert(command_registry_init(false));
    Config cfg; cfg.databases=1; cfg.shards=16; cfg.even_ifid=6; cfg.even_ex=2;
    cfg.key_lb=cfg.client_lb=cfg.flip_auto=0; cfg.save.clear();
    Server server; assert(server.prepare_boot(cfg) && server.init(cfg));
    ScatterArenaPool pool;
    Op a,b,c;
    ScatterArenaPool oom;
    uint64_t refused_cut=server.atomic_snapshot();
    fail_next_allocation=true;
    assert(!oom.register_plain_read(server,a,refused_cut,0));
    assert(!fail_next_allocation && !a.read_cut_registered_);
    assert(server.atomic_read_floor()==UINT64_MAX);
    uint64_t cut=server.atomic_snapshot();
    assert(pool.register_plain_read(server,a,cut,0));
    assert(server.atomic_read_floor()==cut+1);
    assert(pool.register_plain_read(server,b,cut,0));
    std::atomic<uint64_t> epoch{0};
    server.atomic_commit_group(epoch);
    uint64_t newer=server.atomic_snapshot();
    assert(newer>cut);
    assert(pool.register_plain_read(server,c,newer,0));
    pool.unregister_plain_read(server,a,0);
    assert(server.atomic_read_floor()==cut+1);
    SnapshotCut scatter; scatter.snapshot=newer;
    assert(pool.register_snapshot(server,&scatter,0));
    scatter.snapshot_complete.store(true); server.note_atomic_snapshot_complete(0);
    pool.refresh_snapshot_floor(server,0);
    assert(server.atomic_read_floor()==cut+1);
    // A later GET must inherit the MGET's confirmed cut even within one parse pass.
    Op after_scatter;
    uint64_t same_pass=cut;
    assert(pool.register_plain_read(server,after_scatter,same_pass,0));
    assert(same_pass==newer && after_scatter.read_cut(newer)==newer);
    pool.unregister_plain_read(server,after_scatter,0);
    pool.unregister_snapshot(server,&scatter,0);
    assert(server.atomic_read_floor()==cut+1);
    pool.unregister_plain_read(server,b,0);
    assert(server.atomic_read_floor()==newer+1);
    pool.unregister_plain_read(server,c,0);
    assert(server.atomic_read_floor()==UINT64_MAX);
    uint64_t stale=cut;
    assert(pool.register_plain_read(server,a,stale,0));
    assert(stale==newer && a.read_cut(newer)==newer);
    assert(server.atomic_read_floor()==newer+1);
    pool.unregister_plain_read(server,a,0);
    assert(server.atomic_read_floor()==UINT64_MAX && !a.read_cut_registered_);
    puts("PASS: references, wrap, OOM rollback, mixed floors, scatter ordering, early completion, confirmation, layouts");
}
