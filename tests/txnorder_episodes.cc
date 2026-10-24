// A' owner-turn regressions. Every age comparison is relative to an observed
// writer stamp. This includes production xshard/multi/claim code, not a model.
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main
#include <array>
#include <sys/wait.h>
#include <map>
#include <functional>

namespace {
struct EpisodeUnit {
    Server& server;
    Client client{-1};
    std::unique_ptr<MultiExecState> exec;
    ScatterState group;
    TxnGroupAttempt attempt;
    bool is_group;
    std::array<bool, 2> placed{}, attempted{};
    bool done = false;
    bool validate = false;
    std::string watched;
    EpisodeUnit(Server& s, bool g = false) : server(s), is_group(g) {
        client.set_id(g ? 992 : 991);
        exec.reset(allocate_state(server, client, 0, MultiStateKind::Execute));
        require(exec != nullptr, "episode state allocated");
        group.server = &server;
        group.watch_refs.store(ScatterState::kGroupAttemptRef);
        group.group_attempt_storage = &attempt;
        attempt.arrived.resize(server.nshards());
        attempt.place_blockers = std::make_unique<TxnPlaceBlocker[]>(server.nshards());
    }
    auto& phase() { return is_group ? attempt.phase : exec->decision.phase; }
    auto& epoch() { return is_group ? group.epoch : exec->decision.epoch; }
    auto& aborted() { return is_group ? group.aborted : exec->decision.aborted; }
    const void* token() { return is_group ? static_cast<void*>(&group) : exec.get(); }
    void age(uint64_t age) { attempt.age_ns = exec->decision.age_ns = age; }
    void claim(int sid, const std::string& key, TxnClaimMode mode) {
        txn_add_claim(exec->claims[sid], slice(key), mode);
    }
    bool place(int sid) {
        attempted[sid] = true;
        Shard::WatchReservation r{token(), &epoch(), &aborted(),
            is_group ? &group.watch_refs : &exec->watch_refs, &client, 0, false, true};
        r.unit_kind = is_group ? 2 : 1;
        if (!server.shard(sid).watch_place_unit(exec->claims[sid], r)) return false;
        require(!aborted().load(), "fixture never hides a wound");
        placed[sid] = true;
        if (is_group) attempt.arrived[sid] |= 4;
        if (validate && sid == 1)
            require(server.shard(sid).watch_validate_and_reserve(slice(watched), &client, 0,
                token(), &epoch(), &aborted(), &exec->watch_refs, false, exec.get()),
                "WATCH validation follows successful placement in the same turn");
        return true;
    }
    void finish() {
        phase().store(TxnPhase::Executing);
        exec->execution_noted[0] |= 8; exec->execution_noted[1] |= 8;
        epoch().store(server.atomic_commit());
        for (int sid : {0, 1}) server.shard(sid).watch_finish_unit(exec->claims[sid], token());
        done = true;
    }
    ~EpisodeUnit() {
        aborted().store(true);
        for (int sid : {0, 1}) server.shard(sid).watch_finish_unit(exec->claims[sid], token());
    }
};

struct EpisodeSchedule {
    Server& server;
    int shape;
    std::string a, b, c;
    EpisodeUnit u, v, h;
    Request writer;
    Request flush{{"FLUSHDB"}};
    ScatterState scatter;
    ShardGroup fragment{};
    Client writer_client{-1};
    uint64_t stamp = 0;
    bool writer_done = false;
    std::string order;
    EpisodeSchedule(Server& s, int r)
        : server(s), shape(r),
          a(key_on(s, 0, "episode-a-")), b(key_on(s, 1, "episode-b-")),
          c(key_on(s, 1, "episode-c-")), u(s), v(s, r == 4 || r == 5), h(s),
          writer(r == 5 || r == 6 ? std::vector<std::string>{"SET", b, "1"}
                                 : std::vector<std::string>{"MSET", b, "1", c, "1"}) {
        if (r != 5 && r != 6) writer.op.mark_local_xshard();
        writer.op.hash = FlatStore::hash_key(slice(b));
        fragment.shard = 1; scatter.groups = &fragment; scatter.nsub = 1;
        scatter.server = &s; scatter.kind = Kind::AllShards;
        u.claim(0, a, TxnClaimMode::Write);
        u.claim(1, r == 5 || r == 6 ? b : c,
                   r == 5 || r == 6 ? TxnClaimMode::Read : TxnClaimMode::Write);
        v.claim(0, a, TxnClaimMode::Write); v.claim(1, b, TxnClaimMode::Read);
        v.validate = !v.is_group; v.watched = b;
        u.age(now_ns()); v.age(now_ns());
        if (r != 3 && r != 4) require(u.place(0), "U holds a before writer episode");
        if (r >= 5) {
            require(v.place(1), "V/G holds read or validation before writer episode");
        } else {
            h.claim(1, c, TxnClaimMode::Write);
            require(h.place(1), "H holds c");
            h.phase().store(TxnPhase::Executing); h.exec->execution_noted[1] |= 8;
        }
        require(!poll_writer(), "writer is genuinely blocked");
        const Op* marked = r == 7 ? &flush.op : &writer.op;
        stamp = s.shard(1).watch_writer_stamp(r == 7 ? Slice{} : slice(r >= 5 ? b : c),
                                             marked, r == 7);
        require(stamp > 3, "observed nonzero stamp");
        u.age(r == 3 || r == 4 ? stamp + 1 : stamp - 2);
        v.age(r == 1 || r == 3 || r == 4 ? stamp + 2 : stamp - 1);
        if (r == 3 || r == 4) require(u.place(0), "U holds a after episode");
        if (r < 5) v.place(1); // PRE can validate b; A' must queue the later V/G.
        require(!v.place(0), "V/G waits on U at a");
        if (r >= 5) h.done = true;
        require(!v.aborted().load() && !u.aborted().load(), "no wound in initial schedule");
    }
    bool poll_writer() {
        if (shape == 7) return txn_scatter_write_ready(Task{&writer_client, 0, 1, &scatter},
                                                       server.shard(1), flush.op);
        return multi_plain_write_ready(server.shard(1), writer.op);
    }
    void poll(int actor) {
        if (actor == 0 || actor == 1) {
            auto& unit = actor ? v : u;
            if (unit.done) return;
            // Independent fragments: revisit both shards without discarding any
            // previously placed claim. Success never masks a wound.
            for (int sid : {1, 0}) if (!unit.placed[sid]) unit.place(sid);
            if (unit.placed[0] && unit.placed[1]) {
                unit.finish(); order += actor ? 'V' : 'U';
            }
        } else if (actor == (shape == 7 ? 4 : 2) && !writer_done && poll_writer()) {
            writer_done = true; order += shape == 7 ? 'F' : 'W';
        } else if (actor == 3 && !h.done) h.finish();
    }
    bool complete() const { return u.done && v.done && writer_done; }
    ~EpisodeSchedule() {
        u.aborted().store(true); v.aborted().store(true); h.aborted().store(true);
        for (int sid : {0,1}) {
            server.shard(sid).watch_finish_unit(u.exec->claims[sid], u.token());
            server.shard(sid).watch_finish_unit(v.exec->claims[sid], v.token());
            server.shard(sid).watch_finish_unit(h.exec->claims[sid], h.token());
        }
        require(poll_writer(), "fixture cleanup releases every writer mark");
    }
};

void cycle(Server& server, int r, const std::array<int,5>& polls) {
    const auto violations = server.txn_counter(TxnCounter::OrderViolations);
    const auto wounds = server.txn_counter(TxnCounter::Wounds);
    EpisodeSchedule schedule(server, r);
    for (unsigned round = 0; round < 64 && !schedule.complete(); ++round)
        for (int actor : polls) schedule.poll(actor);
    require(server.txn_counter(TxnCounter::OrderViolations) == violations &&
            server.txn_counter(TxnCounter::Wounds) == wounds, "no invariant violation or wound");
#ifdef TXN_EPISODE_PRE
    require(!schedule.complete(), "PRE must reproduce the 64-turn cycle");
#elif defined(TXN_EPISODE_RANK_ONLY)
    require(schedule.complete() == (r != 3 && r != 4), "per-key rank leaves exactly R3/R4 cycles");
#else
    require(schedule.complete(), "A' completes the schedule within 64 fair owner rounds");
    if (r == 2 || r >= 5) require(schedule.order == (r == 7 ? "UVF" : "UVW"),
                                 "older unit, validator/group, then writer");
#endif
    std::printf("R%d owner schedule: complete=%u order=%s (bound 64 fair rounds)\n",
                r,schedule.complete(),schedule.order.c_str());
}

// Replay every reachable owner-turn state, then reject a recurrent component
// in which all five actors can keep polling without reaching completion. Unlike
// repeating one permutation, this covers changing poll orders between rounds.
void exhaustive(Server& server, int shape) {
    using Path = std::vector<int>;
    const auto signature = [](const EpisodeSchedule& s) {
        std::string key;
        for (const auto* u : {&s.u, &s.v, &s.h}) {
            for (bool b : u->placed) key += b ? '1' : '0';
            for (bool b : u->attempted) key += b ? '1' : '0';
            key += u->done ? '1' : '0';
        }
        key += s.writer_done ? '1' : '0';
        return key;
    };
    std::vector<Path> paths(1);
    std::vector<std::array<int,5>> edges;
    std::vector<bool> terminal;
    std::map<std::string,int> ids;
    { EpisodeSchedule s(server,shape); ids.emplace(signature(s),0); }
    for (size_t node=0;node<paths.size();++node) {
        std::array<int,5> next{}; bool complete=false;
        for (int actor=0;actor<5;++actor) {
            EpisodeSchedule s(server,shape);
            for (int previous : paths[node]) s.poll(previous);
            complete=s.complete();
            const auto violations=server.txn_counter(TxnCounter::OrderViolations);
            s.poll(actor);
            require(server.txn_counter(TxnCounter::OrderViolations)==violations,
                    "exhaustive owner step preserves invariant I");
            const auto [it,inserted]=ids.emplace(signature(s),paths.size());
            next[actor]=it->second;
            if (inserted) { auto path=paths[node];path.push_back(actor);paths.push_back(std::move(path)); }
        }
        edges.push_back(next);terminal.push_back(complete);
        require(paths.size()<10000,"finite owner-state exploration bound");
    }
    std::vector<int> index(paths.size(),-1), low(paths.size()), stack, component(paths.size(),-1);
    std::vector<bool> onstack(paths.size()); int serial=0, components=0;
    std::function<void(int)> visit = [&](int v) {
        index[v]=low[v]=serial++;stack.push_back(v);onstack[v]=true;
        for(int w:edges[v]) {
            if(index[w]<0) { visit(w);low[v]=std::min(low[v],low[w]); }
            else if(onstack[w]) low[v]=std::min(low[v],index[w]);
        }
        if(low[v]!=index[v]) return;
        for(;;) { int w=stack.back();stack.pop_back();onstack[w]=false;component[w]=components;if(w==v)break; }
        ++components;
    };
    visit(0);
    bool fair_cycle=false;
    for(int c=0;c<components;++c) {
        unsigned actors=0;bool done=false;
        for(size_t n=0;n<paths.size();++n) if(component[n]==c) {
            done|=terminal[n];
            for(int actor=0;actor<5;++actor) if(component[edges[n][actor]]==c) actors|=1u<<actor;
        }
        fair_cycle|=!done && actors==31;
    }
#ifdef TXN_EPISODE_PRE
    require(fair_cycle,"PRE exhaustive search finds the cycle");
#elif defined(TXN_EPISODE_RANK_ONLY)
    require(fair_cycle==(shape==3||shape==4),"rank-only exhaustive cycles are R3/R4");
#else
    require(!fair_cycle,"no reachable fair nonterminating component");
#endif
    std::printf("R%d exhaustive: %zu owner states, %zu transitions, fair cycle=%u\n",
                shape,paths.size(),paths.size()*5,fair_cycle);
}

void controls(Server& server, const std::string& name) {
    const auto b = key_on(server,1,"episode-b-"), c = key_on(server,1,"episode-c-");
    Shard& shard = server.shard(1);
    EpisodeUnit holder(server);
    holder.claim(1,b,TxnClaimMode::Read); holder.validate = true; holder.watched=b;
    require(holder.place(1), "validation placed");
    Request writer({"MSET",b,"1",c,"1"}); writer.op.mark_local_xshard();
    writer.op.hash = FlatStore::hash_key(slice(b));
    require(!multi_plain_write_ready(shard,writer.op), "blocked episode opened");
    const auto s1=shard.watch_writer_stamp(slice(b),&writer.op);
#if defined(TXN_EPISODE_PRE) || defined(TXN_EPISODE_RANK_ONLY)
    require(s1,"PRE blocked-key mark observed");
#else
    require(s1 && shard.watch_writer_stamp(slice(c),&writer.op)==s1, "complete common-stamp set");
#endif
    if (name=="R8") {
        holder.phase().store(TxnPhase::Executing);
        require(!(holder.exec->execution_noted[1]&8), "CAS before held shard started");
        require(!multi_plain_write_ready(shard,writer.op), "D10 writer waits before started bit");
        // Three proposed handshake controls, with their exact bad interleavings.
        const bool started_only_allows = !(holder.exec->execution_noted[1]&8);
        require(started_only_allows, "started-only control violates D10");
        std::atomic<TxnPhase> phase{TxnPhase::Placing}; std::atomic<bool> dirty{false};
        const bool read_clean=!dirty.load(); dirty.store(true);
        const bool writer_passes=phase.load()==TxnPhase::Placing;
        TxnPhase old=TxnPhase::Placing;
        require(read_clean && writer_passes && phase.compare_exchange_strong(old,TxnPhase::Executing),
                "read-dirty-before-CAS control commits over the intervening write");
        dirty.store(true); // speculative writer, before testing phase
        const bool writer_waits=phase.load()==TxnPhase::Executing;
        require(dirty.load() && writer_waits, "Dekker dirty flag yields null before any write");
        std::puts("R8 negative controls: started-only, read-before-CAS, Dekker all falsified");
    } else if (name=="R9") {
        holder.finish();
        require(multi_plain_write_ready(shard,writer.op), "first gate pass");
        require(!shard.watch_writer_stamp(slice(b),&writer.op) &&
                !shard.watch_writer_stamp(slice(c),&writer.op), "gate pass removes complete episode");
        ScatterRun predecessor(server,{"MSET",b,"predecessor",
            key_on(server,0,"episode-own-"),"predecessor"},!server.atomic_enabled());
        // At atomic=0 use the forced child path that EXEC itself uses; the
        // default bare MSET intentionally has no undecided group in that mode.
        require(predecessor.state->atomic_write && !predecessor.state->group_attempt(),
                "own undecided predecessor is a real blind group");
        require(xshard_execute(Task{&predecessor.client,0,1,predecessor.state},shard,
                predecessor.request.op,server.worker_of_shard(1))==ScatterTaskResult::Complete,
                "blind predecessor installed on this owner before its other fragment");
        require(xshard_task_should_defer(server,shard,Task{&predecessor.client,0,1,nullptr},writer.op),
                "writer passes claims then parks on own undecided group");
        require(!shard.watch_writer_stamp(slice(b),&writer.op) &&
                !shard.watch_writer_stamp(slice(c),&writer.op),"program-order park keeps no old marks");
        EpisodeUnit second(server);
        second.claim(1,c,TxnClaimMode::Write); require(second.place(1),"second holder");
        second.phase().store(TxnPhase::Executing); second.exec->execution_noted[1]|=8;
        require(!multi_plain_write_ready(shard,writer.op),"writer blocked again");
        const auto s2=shard.watch_writer_stamp(slice(b),&writer.op);
        require(s2>s1+1 && shard.watch_writer_stamp(slice(c),&writer.op)==s2,"episode re-stamped once");
        EpisodeUnit between(server); between.age(s1+1);
        between.claim(1,b,TxnClaimMode::Write);
        require(between.place(1),"unit between stamps passes the new episode");
        between.finish(); second.finish();
    } else if (name=="R10") {
#if defined(TXN_EPISODE_PRE) || defined(TXN_EPISODE_RANK_ONLY)
        EpisodeUnit first(server);first.age(s1+1);first.claim(1,c,TxnClaimMode::Write);
        require(first.place(1),"PRE lets one later unit enter the initially unmarked key");
        first.phase().store(TxnPhase::Executing);first.exec->execution_noted[1]|=8;
        require(!multi_plain_write_ready(shard,writer.op),"PRE extends its persistent blocked-key marks");
        const auto both=shard.watch_writer_stamp(slice(c),&writer.op);
        require(both,"second blocked key is now marked too");
        first.finish();
        for(int turn=0;turn<32;++turn) {
            EpisodeUnit later(server);later.age(both+1);
            later.claim(1,turn%2 ? b:c,TxnClaimMode::Write);
            require(!later.place(1),"PRE is bounded once both blocked-key marks exist");
        }
        std::puts("R10 PRE bounded: one initial overtaker, then 32 later placements blocked");
#else
        for (int turn=0;turn<32;++turn) {
            EpisodeUnit younger(server); younger.age(s1+1);
            younger.claim(1,turn%2 ? b:c,TxnClaimMode::Write);
            require(!younger.place(1),"later units cannot overtake on either writer key");
        }
#endif
    } else if (name=="invariant") {
#ifndef TXN_EPISODE_PRE
        const auto before=server.txn_counter(TxnCounter::OrderViolations);
        // Deliberately bypass placement to falsify the checker itself.
        holder.age(s1+1); shard.watch_writer_check(slice(b),false,s1);
        const auto after=server.txn_counter(TxnCounter::OrderViolations);
        require(after==before+1,"invariant-I falsifier detects a younger placing validator");
#endif
    } else if (name=="retirement") {
#ifdef TOMO_TXNORDER_DEBUG
        Rob<64> rob;
        Op* op=rob.acquire(); require(op != nullptr,"retirement fixture ROB slot");
        rob.publish();
        require(shard.watch_writer_mark(slice(c),op,false,now_ns()),"deliberately leaked mark");
        op->state.store(OpState::Done);
        const pid_t child=fork();
        require(child>=0,"fork negative retirement control");
        if (!child) { rob.drain([](Op&){}); _exit(0); }
        int status=0; require(waitpid(child,&status,0)==child,"wait retirement falsifier");
        require(WIFSIGNALED(status)&&WTERMSIG(status)==SIGABRT,"leak aborts at real ROB retirement");
        shard.watch_writer_unmark(slice(c),op);
        require(rob.drain([](Op&){})==1,"unmarked slot retires normally");
#else
        require(false,"retirement falsifier requires TOMO_TXNORDER_DEBUG build");
#endif
    } else if (name=="failure") {
#ifndef TXN_EPISODE_PRE
        shard.watch_writer_forget(&writer.op);
        require(shard.watch_writer_mark(slice(b),&writer.op,false,s1),"first stale mark");
        require(shard.watch_writer_mark(slice(c),&writer.op,false,s1+1),"second stale mark");
        require(!multi_plain_write_ready(shard,writer.op),"mismatched stamp remains blocked");
        require(!shard.watch_writer_stamp(slice(b),&writer.op) &&
                !shard.watch_writer_stamp(slice(c),&writer.op),"mismatch removes all marks");
        require(!multi_plain_write_ready(shard,writer.op),"retry opens a fresh complete episode");
        const auto s2=shard.watch_writer_stamp(slice(b),&writer.op);
        require(s2>s1 && shard.watch_writer_stamp(slice(c),&writer.op)==s2,"fresh complete stamp");
        shard.watch_writer_forget(&writer.op);
        allocation_failed=false; fail_new_after=0;
        require(!multi_plain_write_ready(shard,writer.op),"allocation failure stays blocked");
        fail_new_after=-1;
        require(allocation_failed,"mark allocation failure was exercised");
        require(!shard.watch_writer_stamp(slice(b),&writer.op) &&
                !shard.watch_writer_stamp(slice(c),&writer.op),"allocation failure removes partial episode");
        require(!multi_plain_write_ready(shard,writer.op),"allocation recovery re-arms");
#endif
    } else require(false,"known episode control");
    holder.finish();
    require(multi_plain_write_ready(shard,writer.op),"control marks retire");
}
}

int main(int argc,char** argv) {
    require(argc==2 || argc==4,"R-family case [1s|2s atomic]");
    require(command_registry_init(false),"command registry");
    Config cfg; cfg.databases=1; cfg.shards=16; cfg.even_ifid=6; cfg.even_ex=2;
    cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.atomic=argc==4 ? std::atoi(argv[3]) : 1;
    cfg.thread_mode=argc==4 && std::string(argv[2])=="1s" ? ThreadMode::Fused : ThreadMode::Split;
    Server server; require(server.prepare_boot(cfg)&&server.init(cfg),"owner-only boot");
    command_bind_server(&server);
    const std::string name=argv[1];
    if (name=="R12") {
        for(int shape=1;shape<=7;++shape) exhaustive(server,shape);
    } else if (name=="R11") txnorder_checks(server,"txnorder_placement");
    else if(name.size()==2 && name[0]=='R' && name[1]>='1' && name[1]<='7')
        cycle(server,name[1]-'0',{0,1,2,3,4});
    else controls(server,name);
    release_records(server);
    std::printf("PASS %s\n",name.c_str());
}
