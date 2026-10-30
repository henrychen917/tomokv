// Command-free instruction witness: calls only the production plain-writer gate.
// Compile against either source root; no TOMO_TXNORDER_DEBUG instrumentation.
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
[[gnu::noinline]] uint64_t cost_loop(Shard& shard, Op& op, uint64_t iterations) {
    uint64_t ready = 0;
    bool (*volatile gate)(Shard&, Op&) = &multi_plain_write_ready;
    for (uint64_t i=0;i<iterations;++i) {
        asm volatile("" ::: "memory");
        ready += gate(shard, op);
    }
    return ready;
}
int main(int argc, char** argv) {
    require(argc == 3, "case a|b|c|d iterations");
    require(command_registry_init(false), "commands");
    Config cfg; cfg.databases=1; cfg.shards=16; cfg.even_ifid=6; cfg.even_ex=2;
    cfg.key_lb=cfg.client_lb=cfg.flip_auto=0; cfg.save.clear();
    Server server; require(server.prepare_boot(cfg) && server.init(cfg), "serverless owners");
    command_bind_server(&server);
    auto& shard = server.shard(0);
    Client client{-1}; client.set_id(9001);
    const std::string hot="index-cost-hot", other="index-cost-other";
    Request writer({"SET",hot,"1"}); writer.op.hash=FlatStore::hash_key(slice(hot));
    std::vector<std::unique_ptr<MultiExecState>> states;
    std::atomic<uint64_t> epoch{0}; std::atomic<bool> aborted{false}; std::atomic<uint32_t> refs{0};
    int foreign=0;
    const char kind=argv[1][0]; require(kind>='a' && kind<='d', "known cost case");
    if (kind=='b' || kind=='d') {
        for (unsigned i=0,n=kind=='b'?1:64;i<n;++i) {
            auto* state=fixture_allocate_state(server,client,0,MultiStateKind::Execute);
            require(state,"cost state"); states.emplace_back(state);
            state->decision.age_ns=i+1;
            txn_add_claim(state->claims[0],slice(kind=='b'?other:hot),TxnClaimMode::Write);
            Shard::WatchReservation r{state,&state->decision.epoch,&state->decision.aborted,
                                     &state->watch_refs,&client,0,false,true};
            r.unit_kind=1;
            require(shard.watch_place_unit(state->claims[0],r)==(i==0),"cost registry shape");
            if (!i) { state->decision.phase.store(TxnPhase::Executing); state->execution_noted[0]|=8; }
        }
    } else if (kind=='c') {
        require(shard.watch_append_reservation(database_owned_key(slice(hot)),
            Shard::WatchReservation{&epoch,&epoch,&aborted,&refs,nullptr,0,false,false}),"nonblocking group write");
        require(shard.watch_writer_mark(slice(hot),&foreign,false,1),"foreign writer episode");
    }
    const bool expected=kind!='d';
    require(multi_plain_write_ready(shard,writer.op)==expected,"warm predicate");
    const uint64_t iterations=std::strtoull(argv[2],nullptr,10);
    perf_event_attr attr{}; attr.type=PERF_TYPE_HARDWARE; attr.size=sizeof(attr);
    attr.config=PERF_COUNT_HW_INSTRUCTIONS; attr.disabled=1; attr.exclude_kernel=1; attr.exclude_hv=1;
    const int fd=syscall(SYS_perf_event_open,&attr,0,-1,-1,0);
    require(fd>=0,"instructions:u event opened");
    require(ioctl(fd,PERF_EVENT_IOC_DISABLE,0)==0,"counter warm syscall");
    require(ioctl(fd,PERF_EVENT_IOC_RESET,0)==0,"counter reset");
    require(ioctl(fd,PERF_EVENT_IOC_ENABLE,0)==0,"counter enabled");
    const uint64_t ready=cost_loop(shard,writer.op,iterations);
    require(ioctl(fd,PERF_EVENT_IOC_DISABLE,0)==0,"counter disabled");
    uint64_t instructions=0;
    require(read(fd,&instructions,sizeof(instructions))==sizeof(instructions),"counter read");
    close(fd);
    std::printf("scoped instructions:u=%llu instructions/call=%.9f\n",
        (unsigned long long)instructions,double(instructions)/iterations);
    require(ready==(expected?iterations:0),"every measured predicate agrees");
    shard.watch_writer_forget(&writer.op); shard.watch_writer_forget(&foreign);
    aborted.store(true); shard.watch_finalize_reservation(database_owned_key(slice(hot)));
    for (auto& state:states) {
        state->decision.aborted.store(true);
        state->place_blockers[0].clear();
    }
    for (auto& state:states) shard.watch_finish_unit(state->claims[0],state.get());
    require(refs.load()==0,"cost group retired");
    std::printf("case=%c calls=%llu ready=%llu\n",kind,(unsigned long long)iterations,(unsigned long long)ready);
}
