#include "src/core/server.h"
#include "src/cmd/xshard.h"
#include "src/net/wb.h"
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
    // A fresh pool cannot inherit the scatter's cut: this must advance after publication.
    ScatterArenaPool confirmation;
    uint64_t stale=cut;
    assert(confirmation.register_plain_read(server,a,stale,0));
    assert(stale==newer && a.read_cut(newer)==newer);
    assert(server.atomic_read_floor()==newer+1);
    confirmation.unregister_plain_read(server,a,0);
    assert(server.atomic_read_floor()==UINT64_MAX && !a.read_cut_registered_);
    // Real WB drains must release plain references even without zc_ptr or tracking.
    for (bool suppress : {false, true}) for (bool closing : {false, true}) {
        Client client(-1);
        if (closing) client.mark_closing();
        Op* op = client.rob().acquire<true>();
        assert(op);
        uint64_t live_cut=server.atomic_snapshot();
        assert(pool.register_plain_read(server,*op,live_cut,0));
        if (suppress) op->mark_reply_skip();
        reply_ok(op->sink());
        client.rob().publish();
        Ring ring;
        WbEngine wb;
        uint32_t now=0;
        LoopSignals signals;
        std::atomic<bool> limits{false};
        struct Context { Server& server; ScatterArenaPool& pool; } context{server,pool};
        wb.bind(&ring, nullptr, [](void*,int32_t,const char*) { std::abort(); }, &context,
                [](void* opaque, Client&, Op& done) {
                    auto& c=*static_cast<Context*>(opaque);
                    assert(done.read_cut_registered_);
                    c.pool.unregister_plain_read(c.server,done,0);
                }, &limits, nullptr, [](void*,Client&) { return false; }, &now, &signals);
        bool submit=false;
        wb.prepare<true,true>(client,submit);
        assert(server.atomic_read_floor()==live_cut+1 && !client.rob().quiesced());
        op->state.store(OpState::Done,std::memory_order_release);
        if (suppress) wb.prepare_suppressing(client,submit,false);
        else wb.prepare<true,true>(client,submit);
        assert(client.rob().quiesced() && !op->read_cut_registered_);
        assert(server.atomic_read_floor()==UINT64_MAX);
        if (suppress) assert(client.nothing_to_write());
    }
    puts("PASS: references, wrap, OOM rollback, mixed floors, scatter ordering, early completion, confirmation, WB/suppressed/closing retirement, layouts");
}
