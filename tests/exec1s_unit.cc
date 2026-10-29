// Directed, bounded production paths. No server, traffic generator, or rate.
#include <cstddef>
thread_local std::size_t exec1s_allocated = 0;
#define TOMO_EXEC1S_ALLOCATIONS
#define TOMO_EXEC1S_DEBUG
#define main atomic_survivors_fixture_main
#include "tests/atomic_survivors_unit.cc"
#undef main

namespace tomo {
struct CoreConcurrencyTest {
    static void incoming(Server& server) {
        for (uint32_t tid=0;tid<server.nthreads();++tid)
            require(server.thread(tid).init_task_inbox_local_fused(),"fused fixture inbox");
        auto& self=server.thread(0);
        FusedExLoop owner;
        require(owner.init(&server,&self,true),"dormant fused owner initialized");
        owner.activate_fused();
        Ring peer;peer.track_owned_completions();require(peer.init(32),"incoming peer ring");
        bool idle=false;
        for (unsigned i=0;i<32;++i) if (!owner.fused_baseline_pass()) { idle=true;break; }
        require(idle && !owner.ring().completion_service_needed(),"zero-progress owner window opened");
        require(peer.msg_to(owner.ring(),ur_tag(UrKind::Wake,nullptr)),"idle owner wake queued");
        for (unsigned i=0;i<1000 && !owner.ring().completion_service_needed();++i)
            require(peer.submit_and_reap()>=0,"idle owner wake submitted");
        require(owner.ring().completion_service_needed() && !owner.ring().sq_ready() &&
                !owner.ring().owned_completions(),"incoming-only owner service armed");
        auto before=exec1s_ring_counters[1].enters;
        require(owner.fused_baseline_pass()>0 && exec1s_ring_counters[1].enters>before,
                "idle fused pass services incoming task work");
        for (unsigned i=0;i<32;++i) {
            owner.fused_baseline_pass();
            if (!owner.ring().completion_service_needed() && !io_uring_cq_ready(owner.ring().raw()))break;
        }
        require(!owner.ring().completion_service_needed() && !io_uring_cq_ready(owner.ring().raw()),
                "idle fused owner drains incoming wake");
        for (unsigned i=0;i<1000 && peer.owned_completions();++i) {
            require(peer.submit_and_reap()>=0,"peer completion enter");
            peer.for_each_cqe([](io_uring_cqe* c){require(c->res>=0,"idle owner wake succeeded");});
        }
        require(!peer.owned_completions(),"peer completion balanced");
    }
    static void reclaim(Server& server, Shard& shard) {
#ifdef TOMO_EXEC1S_NO_RECLAIM
        // Throwaway falsifier: remove the exact production cleanup call below.
        (void)server; (void)shard;
        return;
#endif
        ExLoop loop;
        loop.srv_ = &server;
        loop.self_ = &server.thread(server.worker_of_shard(shard.id()));
        loop.reclaim_multi_prefix(shard);
    }
    static void execute_without_batch(Server& server, const Task& task) {
        ExLoop loop;
        loop.srv_=&server;
        loop.self_=&server.thread(server.worker_of_shard(task.shard));
        loop.cached_now_ms_=now_realtime_ms();
        require(loop.execute(task),"standalone owner task progressed");
    }
};
}
namespace {
void group_count(FlatStore& store, unsigned expected) {
    const auto* pending=FlatStoreRegressionTest::pending(store);
    require(pending != nullptr,"group count checked before sidecar destruction");
    require(pending->live == expected && pending->group_records == uint8_t(expected),
            "ordinary unlink maintains the modulo group count");
    require(store.atomic_may_have_blind_records() == (expected != 0),
            "ordinary unlink maintains the blind-scan guard");
}
void ring_check() {
    Ring uninitialized;
    require(!uninitialized.completion_service_needed(), "uninitialized ring owes no completion service");
    { Ring::RegisteredFd registration(&uninitialized); }
    Ring sender, target;
    sender.track_owned_completions();
    target.track_owned_completions();
    require(sender.init(32) && target.init(32), "two real uring instances");
    {
        Ring::RegisteredFd registered(&sender);
        require(sender.raw()->enter_ring_fd != sender.raw()->ring_fd, "registered issuer fd witnessed");
        require(!sender.completion_service_needed(), "idle EX ring has no enter work");
        require(sender.msg_to(target, ur_tag(UrKind::Wake, nullptr)), "msg_ring queued");
        require(sender.owned_completions() == 1 && sender.completion_service_needed(), "owed wake tracked");
        unsigned sent = 0, received = 0, incoming_service = 0;
        for (unsigned i = 0; i < 1000 && (!sent || !received); ++i) {
            // Never enter an idle target speculatively. Its incoming task-work
            // signal must suffice even with no SQEs or owned completions.
            require(sender.submit_and_reap() >= 0, "issuer enter succeeds");
            require(!target.sq_ready() && !target.owned_completions(), "incoming target has no owned submit work");
            if (target.completion_service_needed()) {
                ++incoming_service;
                require(target.submit_and_reap() >= 0, "incoming task-work enter succeeds");
            }
            sender.for_each_cqe([&](io_uring_cqe* c) { require(c->res >= 0, "outgoing wake succeeded"); ++sent; });
            target.for_each_cqe([&](io_uring_cqe* c) { require(ur_kind(c->user_data)==UrKind::Wake, "incoming wake tag"); ++received; });
        }
        require(sent == 1 && received == 1 && sender.owned_completions() == 0, "wake CQEs balanced exactly once");
        require(!target.deferred() || incoming_service, "deferred incoming task-work signal witnessed");
        require(!target.completion_service_needed(), "drained incoming ring returns to idle");
        for (auto kind : {UrKind::AofIo, UrKind::SnapshotIo}) {
            auto* sqe = sender.sqe(); require(sqe, "persistence CQE slot");
            io_uring_prep_nop(sqe); sqe->user_data=ur_tag(kind, nullptr);
            sender.note_owned_completion();
        }
        for (unsigned i=0; i<1000 && sender.owned_completions(); ++i) {
            require(sender.submit_and_reap() >= 0, "persistence-tag enter");
            sender.for_each_cqe_filtered([](io_uring_cqe*) { return false; });
        }
        require(sender.owned_completions()==0, "filtered persistence CQEs clear owed count");
        unsigned replayed=0;
        sender.for_each_cqe([&](io_uring_cqe*) { ++replayed; });
        require(replayed==2 && sender.owned_completions()==0, "deferred CQEs replay without double decrement");
        require(!*sender.raw()->cq.koverflow && !*target.raw()->cq.koverflow, "no CQ overflow");
        // A deliberately full incoming CQ must retain its service indication
        // after the task-work flag clears, until the overflow backlog is reaped.
        require(target.raw()->features & IORING_FEAT_NODROP, "overflow fixture requires retained CQEs");
        const unsigned burst = 3 * target.raw()->cq.ring_entries;
        for (unsigned i=0; i<burst; ++i) {
            require(sender.msg_to(target,ur_tag(UrKind::Wake,nullptr)), "overflow wake queued");
            require(sender.submit_and_reap()>=0,"overflow issuer enters");
            sender.for_each_cqe([](io_uring_cqe* c) { require(c->res>=0,"overflow wake submitted"); });
        }
        require(target.completion_service_needed(), "incoming burst signals service");
        for (unsigned i=0; i<1000 && !(IO_URING_READ_ONCE(*target.raw()->sq.kflags) & IORING_SQ_CQ_OVERFLOW); ++i) {
            require(target.completion_service_needed(), "incoming burst remains signalled");
            require(target.submit_and_reap()>=0,"incoming burst enters");
        }
        require(IO_URING_READ_ONCE(*target.raw()->sq.kflags) & IORING_SQ_CQ_OVERFLOW,
                "retained CQ overflow window opened");
        received=0;
        for (unsigned i=0; i<1000 && received<burst; ++i) {
            target.for_each_cqe([&](io_uring_cqe* c) {
                require(ur_kind(c->user_data)==UrKind::Wake,"overflow wake tag"); ++received;
            });
            if (target.completion_service_needed()) require(target.submit_and_reap()>=0,"overflow backlog enters");
        }
        require(received==burst && !target.completion_service_needed(), "incoming overflow fully drained once");
    }
    require(sender.raw()->enter_ring_fd == sender.raw()->ring_fd, "same issuer unregisters before teardown");
}

void client_counts(Server& server) {
    std::vector<std::unique_ptr<Client>> clients;
    const auto& ios=server.placement().ifid_threads();
    require(!ios.empty(), "client-serving threads");
    for(unsigned i=0;i<64;++i) {
        auto c=std::make_unique<Client>(-1);c->set_ifid_thread(ios[i%ios.size()]);
        server.thread(c->ifid_thread()).add_client(c.get());clients.push_back(std::move(c));
    }
    uint64_t live=0,published=0;
    for(auto tid:ios) { live+=exec1s_counters[tid].clients_live;published+=server.thread(tid).client_count(); }
    require(live==64 && published==64,"new client counters conserve 64 actual clients");
    for(auto& c:clients) require(server.thread(c->ifid_thread()).remove_client(c.get()),"client removed once");
    for(auto tid:ios) require(exec1s_counters[tid].clients_live==0,"client live counter drains to zero");
}

void participants(Server& server) {
    Client client(-1); client.set_id(900001);
    const auto a=key_on(server, server.nshards()-1, "exec1s-slot:");
    const auto b=key_on(server, server.nshards()/2, "exec1s-slot:");
    std::vector<MultiQueuedCommand> queue(2);
    Request one({"INCR",a}), two({"INCR",b});
    require(queued_copy(one.op,queue[0]) && queued_copy(two.op,queue[1]), "queue classification");
    // Warm classification separately; count only the per-EXEC state/preparation.
    const auto before=exec1s_allocated;
    auto* state=allocate_state(server,client,0,MultiStateKind::Execute);
    require(state && prepare_commands(server,*state,queue), "sparse participants prepared");
    const auto allocated=exec1s_allocated-before;
    require(state->shards.size()==2 && state->claims.size()==2 && state->shard_commands.size()==2,
            "owner vectors sized by participants");
    require(state->slot(server.nshards()-1)==0 && state->slot(server.nshards()/2)==1,
            "sparse physical shards mapped to stable slots");
    require(state->claims[0].size()==1 && state->claims[1].size()==1, "both exact claims retained");
    std::printf("allocation shards=%u participants=2 bytes=%zu\n",server.nshards(),allocated);
    destroy_multi_state(state);
    // Discovery preserves command order before adding WATCH-only participants.
    const auto watched=key_on(server,2,"exec1s-watch-order:");
    state=allocate_state(server,client,0,MultiStateKind::Execute);
    require(state,"watched map allocated");
    state->watched.push_back({watched,FlatStore::hash_key(Slice(watched)),2});
    std::vector<MultiQueuedCommand> watched_queue(1);
    require(queued_copy(one.op,watched_queue[0]) && prepare_commands(server,*state,watched_queue),
            "watched command participants prepared");
    require(state->shards.size()==2 && state->shards[0]==int32_t(server.nshards()-1) &&
            state->shards[1]==2,"command participants precede WATCH-only participants");
    destroy_multi_state(state);
    // The registry's LMPOP key range includes option tokens, while the lowering
    // dispatches only exact keys. Those historical claim shards still need
    // storage, without becoming extra execution participants.
    const auto left=key_on(server,0,"exec1s-lmpop-a:"), right=key_on(server,1,"exec1s-lmpop-b:");
    Request pop({"LMPOP","2",left,right,"LEFT"});
    std::vector<MultiQueuedCommand> pop_queue(1);
    require(queued_copy(pop.op,pop_queue[0]),"lowered pop queued");
    state=allocate_state(server,client,0,MultiStateKind::Execute);
    require(state && prepare_commands(server,*state,pop_queue),"lowered pop claim slots prepared");
    require(state->shards.size()==2 && state->commands[0]->kind==MultiCommandKind::Xshard,
            "claim-only shards do not expand execution participants");
    for(auto sid:state->commands[0]->key_shards)
        require(state->slot(sid)<state->claims.size(),"all metadata claim slots exist");
    destroy_multi_state(state);
    state=allocate_state(server,client,0,MultiStateKind::Execute);
    require(state, "full map allocated");
    for (unsigned sid=0;sid<server.nshards();++sid) add_state_shard(*state,sid);
    for (unsigned sid=0;sid<server.nshards();++sid) add_state_shard(*state,sid);
    require(state->shards.size()==server.nshards(), "all slots including 255 are unique");
    for (unsigned sid=0;sid<server.nshards();++sid)
        require(state->slot(sid)==sid,"full map identity");
    destroy_multi_state(state);
}

void reuse_check(Server& server) {
    const auto name = key_on(server, 0, "exec1sd-reuse:");
    auto& store = server.shard(0).store();
    const Slice key = slice(name);
    const auto hash = FlatStore::hash_key(key);
    for (unsigned depth : {0u, 16u, 64u}) {
        require(store.atomic_live_records() == 0, "fresh reuse history");
        for (unsigned i = 0; i < depth; ++i) {
            void* entry = nullptr; KvObj* value = nullptr;
            require(store.atomic_prepare_plain(key, hash, 0, entry), "old version prepared");
            store.atomic_install_plain(hash, key, entry, value, 1);
        }
        MultiExecState parent; parent.server = &server; parent.decision.owner = &parent;
        std::atomic<bool> aborted{false};
        uint32_t owner_refs = 0;
        require(store.atomic_live_records() == depth, "requested history really installed");
        const auto check = [&](bool expected, unsigned maximum) {
            auto& counter = exec1s_counters[0]; const auto before = counter.record_visits;
            bool actual;
            { Exec1sVisitScope scope(0);
              actual = store.atomic_reuses_transaction(hash, key, &parent.decision.epoch, &aborted); }
            require(actual == expected, "newest ownership controls reuse");
            // The constructed prefix has exactly this length. Requiring the
            // positive count also rejects a missing/disabled visit witness.
            require(counter.record_visits - before == maximum, "reuse visits the exact newest prefix");
            bool oracle = false;
            store.atomic_visit_unit_records(hash, key, false, [&](AtomicEntry& e) {
                oracle = e.plain() && e.group_epoch == &parent.decision.epoch && e.group_aborted == &aborted;
            });
            require(actual == oracle, "reuse equals complete oldest-to-newest oracle");
        };
        check(false, depth ? 1 : 0);
        void* entry = nullptr; KvObj* value = nullptr;
        require(store.atomic_prepare_transaction(key, hash, 991, &parent.decision.epoch,
            &parent.record_refs, &aborted, &owner_refs, entry), "parent layer prepared");
        // The production parent pre-counts one reference per installing owner;
        // the store consumes that reference when its last owner record leaves.
        parent.record_refs.store(1);
        store.atomic_install_transaction(hash, key, entry, value); ++owner_refs;
        require(parent.record_refs.load() == 1 && owner_refs == 1, "parent lifetime really armed");
        check(true, 1);
        // An unrelated newest record must not hide a reusable private layer.
        const auto other_name = key_on(server, 0, "exec1sd-other:");
        const Slice other = slice(other_name); const auto other_hash = FlatStore::hash_key(other);
        require(store.atomic_prepare_plain(other, other_hash, 0, entry), "unrelated layer prepared");
        store.atomic_install_plain(other_hash, other, entry, value, 2);
        check(true, 2);
        // A newer foreign record forbids reuse even though the parent still exists.
        require(store.atomic_prepare_plain(key, hash, 0, entry), "newer foreign layer prepared");
        store.atomic_install_plain(hash, key, entry, value, 3);
        check(false, 1);
        parent.decision.epoch.store(1);
        store.atomic_shutdown_release_records();
        require(parent.record_refs.load() == 0 && owner_refs == 0, "reuse fixture releases parent lifetime");
    }
}


void blind_group_check(Server& server) {
    server.set_atomic_enabled(true);
    const auto a=key_on(server,0,"exec1s-blind-a:"), b=key_on(server,1,"exec1s-blind-b:");
    auto witnessed = [&] {
        auto& shard=server.shard(0);
        require(shard.store().atomic_live_records()>0 && shard.store().atomic_may_have_blind_records(),
                "live group record actually linked");
        const auto tid=server.worker_of_shard(0);
        const auto before=exec1s_counters[tid].blind_clear;
        std::vector<TxnClaim> claims; // Empty is enough to test the O(1) exit's guard.
        require(txn_blind_scan(shard,claims)==TxnBlind::Clear,"no unrelated claim blocks");
        require(exec1s_counters[tid].blind_clear==before,"live group forbids zero-group fast exit");
    };
    auto cancel = [&](ScatterRun& run, MultiExecState* parent = nullptr) {
        if(parent) parent->decision.aborted.store(true);
        run.state->aborted.store(true);
        for(unsigned i=0;i<run.state->owner_slots;++i)
            while(run.state->owner_record_refs[i].remaining)
                complete_owner_record_wave(*run.state,i);
        // Ordinary reclamation, while both the scatter and pending sidecar
        // remain alive. Shutdown would destroy the counter we need to inspect.
        for(unsigned sid=0;sid<server.nshards();++sid)
            xshard_cleanup_shard_at(server.shard(sid),UINT64_MAX,UINT64_MAX,256);
    };
    {
        MultiExecState parent; parent.server=&server; parent.decision.owner=&parent;
        ScatterRun run(server,{"MSET",a,"m",b,"m"});
        run.state->multi_child=true; run.state->multi_parent=&parent;
        for(unsigned i=0;i<run.state->nsub;++i) {
            const int sid=run.state->groups[i].shard;
            require(xshard_execute(Task{&run.client,0,sid,run.state},server.shard(sid),
                    run.request.op,server.worker_of_shard(sid))==ScatterTaskResult::Complete,
                    "actual atomic MSET candidate installed");
        }
        require(run.state->epoch.load()==0,"MSET group remains undecided");
        witnessed();
        cancel(run,&parent);
        group_count(server.shard(0).store(),0);
    }
    {
        ScatterRun run(server,{"EVAL","redis.call('SET',KEYS[1],'s'); return redis.call('GET',KEYS[2])","2",a,b});
        run.phase(ScriptPhase::Pin); run.state->script_cut=server.atomic_snapshot();
        run.phase(ScriptPhase::Read); run.phase(ScriptPhase::Run);
        run.state->script_ticket=server.atomic_commit_reserve();
        run.phase(ScriptPhase::Validate);
        require(!run.state->script_conflict.load(),"script validates");
        run.state->script_apply_after_unpin=true; run.phase(ScriptPhase::Unpin);
        run.phase(ScriptPhase::Apply);
        require(!run.state->aborted.load(),"script installed its candidate");
        witnessed(); server.atomic_commit_publish();
        cancel(run);
        group_count(server.shard(0).store(),0);
    }
    {
        // A zero byte count at exactly 256 live groups must NOT select the
        // no-group exit. Keep actual undecided MSET children linked until the
        // observation, then cancel and reclaim one prefix record at a time.
        std::vector<std::unique_ptr<MultiExecState>> parents;
        std::vector<std::unique_ptr<ScatterRun>> groups;
        for(unsigned n=0;n<256;++n) {
            auto parent=std::make_unique<MultiExecState>();
            parent->server=&server;parent->decision.owner=parent.get();
            const auto xp="exec1s-wrap-a:"+std::to_string(n)+":";
            const auto yp="exec1s-wrap-b:"+std::to_string(n)+":";
            const auto x=key_on(server,0,xp.c_str());
            const auto y=key_on(server,1,yp.c_str());
            auto run=std::make_unique<ScatterRun>(server,std::vector<std::string>{"MSET",x,"m",y,"m"});
            run->state->multi_child=true;run->state->multi_parent=parent.get();
            for(unsigned i=0;i<run->state->nsub;++i) {
                const int sid=run->state->groups[i].shard;
                require(xshard_execute(Task{&run->client,0,sid,run->state},server.shard(sid),
                        run->request.op,server.worker_of_shard(sid))==ScatterTaskResult::Complete,
                        "wrap fixture installs actual undecided groups");
            }
            parents.push_back(std::move(parent));groups.push_back(std::move(run));
        }
        require(server.shard(0).store().atomic_live_records()==256,"counter wrap window actually opened");
        witnessed();
        group_count(server.shard(0).store(),256);
        for(unsigned n=0;n<groups.size();++n) {
            cancel(*groups[n],parents[n].get());
            for(unsigned sid=0;sid<2;++sid)
                group_count(server.shard(sid).store(),255-n);
            if(n!=255) witnessed();
        }
        const auto tid=server.worker_of_shard(0);
        const auto before=exec1s_counters[tid].blind_clear;
        std::vector<TxnClaim> claims;
        require(txn_blind_scan(server.shard(0),claims)==TxnBlind::Clear &&
                exec1s_counters[tid].blind_clear==before+1,
                "zero-group exit resumes before sidecar destruction");
    }
}

void reclaim_check(Server& server, bool pinned) {
    const auto a=key_on(server,0,"exec1s-reclaim-a:"), b=key_on(server,0,"exec1s-reclaim-b:");
    require(local(server,{"SET",a,"0"})=="+OK\r\n" && local(server,{"SET",b,"0"})=="+OK\r\n", "predecessors seeded");
    const auto cut=server.atomic_snapshot();
    if (pinned) server.publish_atomic_read_floor(0,cut);
    std::vector<std::unique_ptr<Client>> clients;
    std::vector<MultiExecState*> states;
    const auto tid=server.worker_of_shard(0);
    const auto before=exec1s_counters[tid];
    for (unsigned n=1;n<=64;++n) {
        auto client=std::make_unique<Client>(-1); client->set_id(910000+n);
        require(multi_io(server,*client,{"MULTI"})=="+OK\r\n", "MULTI accepted");
        require(multi_io(server,*client,{"INCR",a})=="+QUEUED\r\n" &&
                multi_io(server,*client,{"INCR",b})=="+QUEUED\r\n", "two writes queued");
        Request request({"EXEC"}); MultiExecState* state=nullptr;
        require(multi_handle_io(server,*client,request.op,0,state)==MultiIoAction::Dispatch && state,
                "real EXEC participant discovery");
        state->now_cut_ms=now_realtime_ms(); initialize_multi_owner_record_refs(*state);
        multi_dispatch_started(*client,state);
        auto* carrier=client->rob().acquire(); require(carrier,"carrier"); carrier->spec=request.op.spec;
        const auto task=multi_make_task(client.get(),0,0,state);
        MultiTaskResult result;
        { Exec1sVisitScope visits(tid); result=multi_execute_task(server,task,server.shard(0),tid,0,nullptr); }
        require(result==MultiTaskResult::Final,"one-shard EXEC completed without retry");
        CoreConcurrencyTest::reclaim(server,server.shard(0));
        set_state_reply(*state,request.op);
        require(request.reply()=="*2\r\n:"+std::to_string(n)+"\r\n:"+std::to_string(n)+"\r\n", "exact RYOW result");
        if (!pinned) require(server.shard(0).store().atomic_live_records()<8,"decided prefix stays below threshold");
        states.push_back(state); clients.push_back(std::move(client));
    }
    auto& store=server.shard(0).store();
    if (pinned) {
        require(store.atomic_live_records()>=64,"registered old reader really retained records");
        server.publish_atomic_read_floor(0,UINT64_MAX);
        for (unsigned i=0;i<32 && store.atomic_live_records()>=8;++i) CoreConcurrencyTest::reclaim(server,server.shard(0));
    }
    require(exec1s_counters[tid].eager_collapses>before.eager_collapses,"eager collapse fired");
    require(exec1s_counters[tid].blind_clear>before.blind_clear,"zero-group O(1) scan fired");
    require(exec1s_counters[tid].record_visits>before.record_visits,"debug walks observed");
    require(local(server,{"GET",a})=="$2\r\n64\r\n" && local(server,{"GET",b})=="$2\r\n64\r\n","latest value survived eager reclamation");
    std::printf("reclaim pinned=%u collapses=%llu visits=%llu\n",pinned,
        (unsigned long long)(exec1s_counters[tid].eager_collapses-before.eager_collapses),
        (unsigned long long)(exec1s_counters[tid].record_visits-before.record_visits));
    release_records(server);
    for(auto* state:states) destroy_multi_state(state);
}

void publication_check(Server& server) {
    const auto key=key_on(server,0,"exec1s-publish:");
    require(local(server,{"SET",key,"value"})=="+OK\r\n","publication predecessor");
    auto& shard=server.shard(0);
    shard.publish_size();
    require(shard.published_size()==1 && shard.published_expires()==0,"zero-expiry baseline published");
    Client client(-1);client.set_id(920001);
    require(multi_io(server,client,{"MULTI"})=="+OK\r\n" &&
            multi_io(server,client,{"EXPIRE",key,"60"})=="+QUEUED\r\n","expiry transaction queued");
    Request request({"EXEC"});MultiExecState* state=nullptr;
    require(multi_handle_io(server,client,request.op,0,state)==MultiIoAction::Dispatch && state,
            "expiry transaction prepared");
    state->now_cut_ms=now_realtime_ms();initialize_multi_owner_record_refs(*state);
    multi_dispatch_started(client,state);
    auto* carrier=client.rob().acquire();require(carrier,"publication carrier");carrier->spec=request.op.spec;
    // No actual IO thread consumes this fixture's Done. Keep notification on
    // the already-queued path, while executing the real owner wrapper.
    client.retire_queued().store(true);
    CoreConcurrencyTest::execute_without_batch(server,multi_make_task(&client,0,0,state));
    require(carrier->state.load()==OpState::Done,"expiry EXEC completed outside a task batch");
    require(shard.store().size()==1 && shard.store().expire_count()==1,
            "expiry changed without a key-count change");
    require(shard.published_size()==1 && shard.published_expires()==1,
            "standalone transaction task publishes non-size statistics");
    release_records(server);destroy_multi_state(state);
}
}
int main(int argc,char** argv) {
    require(argc>=4,"case mode atomic [shards]");
    const std::string name=argv[1];
    if(name=="ring") { ring_check(); std::puts("PASS exec1s ring"); return 0; }
    require(command_registry_init(false),"registry");
    Config cfg; cfg.databases=1; cfg.shards=argc>4?std::atoi(argv[4]):16;
    cfg.even_ifid=6; cfg.even_ex=2; cfg.key_lb=cfg.client_lb=cfg.flip_auto=0; cfg.save.clear();
    cfg.thread_mode=std::string(argv[2])=="1s"?ThreadMode::Fused:ThreadMode::Split; cfg.atomic=std::atoi(argv[3]);
    if(name=="incoming") { cfg.thread_mode=ThreadMode::Fused; cfg.read_local=0; }
    Server server; require(server.prepare_boot(cfg)&&server.init(cfg),"production topology"); command_bind_server(&server);
    std::string error;require(acl_initialize(server,cfg,error),"ACL");
    if(name=="incoming") CoreConcurrencyTest::incoming(server);
    else if(name=="participants") { client_counts(server); participants(server); }
    else if(name=="reclaim") { reclaim_check(server,false); blind_group_check(server); }
    else if(name=="floor") reclaim_check(server,true);
    else if(name=="publication") publication_check(server);
    else if(name=="reuse") reuse_check(server);
    else require(false,"known case");
    release_records(server); std::printf("PASS exec1s %s\n",name.c_str());
}
