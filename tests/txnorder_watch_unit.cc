// Deterministic owner-turn witnesses for async serves and read-only WATCH.
// The window is created by withholding the next owner turn, never by a sleep.
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main

namespace {
void served_watch(Server& server) {
    for (const char* verb : {"BLPOP","BRPOP","BLMPOP","BZPOPMIN","BZPOPMAX","BZMPOP"}) {
        Client watcher{-1}, consumer{-1};
        watcher.set_id(620); consumer.set_id(621);
        const auto key=key_on(server,0,verb);
        const bool zset=verb[1]=='Z';
        local(server,{"DEL",key});
        local(server,zset ? std::vector<std::string>{"ZADD",key,"1","v"}
                          : std::vector<std::string>{"LPUSH",key,"v"});
        auto& shard=server.shard(0);
        require(shard.watch_add(slice(key),&watcher,watcher.watch_generation()),"WATCH after producer");
        require(!watcher.watch_dirty(),"WATCH clean in real producer/serve window");
        require(local(server,{zset ? "ZCARD" : "LLEN",key})==":1\r\n","produced element still present");
        Op* op=consumer.rob().acquire(); require(op,"consumer slot");
        std::vector<std::string> args{verb,key,"0"};
        if (std::string(verb)=="BLMPOP") args={verb,"0","1",key,"LEFT"};
        if (std::string(verb)=="BZMPOP") args={verb,"0","1",key,"MIN"};
        for(const auto& arg:args) require(op->push_arg(slice(arg)),"serve argv");
        op->spec=command_lookup(op->arg(0));
        BlockingState state; state.server=&server; state.client=&consumer; state.op_id=0;
        state.selected=0; state.keys.push_back({0,key,FlatStore::hash_key(slice(key)),0});
        state.kind=std::string(verb)=="BLPOP" ? BlockingKind::Blpop :
                   std::string(verb)=="BRPOP" ? BlockingKind::Brpop :
                   std::string(verb)=="BLMPOP" ? BlockingKind::Blmpop :
                   std::string(verb)=="BZPOPMIN" ? BlockingKind::Bzpopmin :
                   std::string(verb)=="BZPOPMAX" ? BlockingKind::Bzpopmax : BlockingKind::Bzmpop;
        // Keep the completion publisher joined: the production direct serve
        // still runs, while no empty ring is asked to wake an IO worker.
        state.active_tasks.store(1);
        Ring ring;
        require(blocking_run_direct(state,shard,server.thread(server.worker_of_shard(0)),ring),
                "actual deferred serve executes");
        require(local(server,{zset ? "ZCARD" : "LLEN",key})==":0\r\n","serve removed element");
        require(watcher.watch_dirty(),"successful serve must dirty the watched key");
        shard.watch_remove(slice(key),&watcher,watcher.watch_generation());
        std::printf("PASS served %s: WATCH saw one, serve removed it and dirtied WATCH\n",verb);
    }
}

void same_owner_rename(Server& server) {
    const auto a=key_on(server,0,"rename-a-"), b=key_on(server,2,"rename-b-");
    require(server.worker_of_shard(0)==server.worker_of_shard(2),"two shards on one owner");
    require(local(server,{"SET",a,"value"})=="+OK\r\n","RENAME source seeded");
    Client client{-1};client.set_id(640);Request request({"RENAME",a,b});
    ScatterArenaPool pool;ScatterDispatch dispatch;
    require(xshard_prepare(server,request.op,pool,0,client.id(),dispatch)==ScatterPrepare::Ready,
            "bare atomic direct RENAME prepared");
    auto* state=dispatch.state;state->now_cut_ms=now_realtime_ms();
    require(state->atomic_direct && state->nsub==2,"two source/destination fragments");
    bool done[16]={};bool queued=false;Ring ring;
    for(unsigned round=0;round<64 && !queued;++round) {
        for(unsigned g=0;g<state->nsub;++g) {
            const int sid=state->groups[g].shard;if(done[sid])continue;
            Task task{&client,0,sid,state};auto& shard=server.shard(sid);
            if(xshard_task_should_defer(server,shard,task,request.op))continue;
            if(xshard_execute(task,shard,request.op,server.worker_of_shard(sid))!=ScatterTaskResult::Complete)continue;
            done[sid]=true;
            const auto result=xshard_complete(server,server.thread(server.worker_of_shard(sid)),ring,task,request.op);
            queued |= result==ScatterFinish::CommitQueued;
        }
    }
    require(done[0]&&done[2]&&queued&&state->pending.load()==0,
            "last owner must queue commit after both shards finish");
    state->epoch.store(server.atomic_commit());
    require(local(server,{"GET",a})=="$-1\r\n" &&
            local(server,{"GET",b})=="$5\r\nvalue\r\n","RENAME conservation");
    release_records(server);xshard_destroy(state,pool,0);pool.reap_deferred();
}

void readonly_watch(Server& server, bool handshake=false) {
    Client client{-1}; client.set_id(630);
    const auto a=key_on(server,0,"readonly-a-"),b=key_on(server,1,"readonly-b-");
    require(server.worker_of_shard(0)!=server.worker_of_shard(1),"two owners");
    local(server,{"SET",a,"a"}); local(server,{"SET",b,"old"});
    require(multi_io(server,client,{"WATCH",b})=="+OK\r\n","WATCH registered");
    require(multi_io(server,client,{"MULTI"})=="+OK\r\n","MULTI");
    if (handshake) {
        require(multi_io(server,client,{"SET",a,"one"})=="+QUEUED\r\n","write queued");
    } else {
        require(multi_io(server,client,{"GET",a})=="+QUEUED\r\n","first read queued");
        require(multi_io(server,client,{"GET",b})=="+QUEUED\r\n","late watched read queued");
    }
    Request request({"EXEC"}); MultiExecState* state=nullptr;
    require(multi_handle_io(server,client,request.op,0,state)==MultiIoAction::Dispatch && state,
            "EXEC prepared");
    state->now_cut_ms=now_realtime_ms(); state->snapshot=server.atomic_snapshot();
    initialize_multi_owner_record_refs(*state);
    multi_dispatch_started(client,state);
    auto* carrier=client.rob().acquire(); require(carrier,"EXEC carrier");
    carrier->spec=request.op.spec;
    for(unsigned round=0;round<16 && !state->watch_phase_done.load();++round)
        for(int sid:state->shards) execute_watch_phase(*state,server.shard(sid));
    require(state->read_only != handshake && state->decision.phase.load()==TxnPhase::Executing &&
            state->watch_phase_done.load(),"CAS passed before delayed shard read");
    require(!client.watch_dirty(),"WATCH clean at CAS");
    Request write({"SET",b,"new"}); write.op.hash=FlatStore::hash_key(slice(b));
    if (handshake) {
        require(!(state->execution_noted[1]&8),"real CAS-to-shard-start held window");
        require(!multi_plain_write_ready(server.shard(1),write.op),
                "D10 validation blocks writer in real EXEC CAS/start window");
    } else {
        require(multi_execute_task(server,multi_make_task(&client,0,0,state),server.shard(0),
                server.worker_of_shard(0),0,nullptr)==MultiTaskResult::Retry,"lead runs; late read held");
        require(!state->finalized.load() && !state->execution_joined[1],"held read window exists");
        local(server,{"SET",b,"new"},631);
        require(client.watch_dirty(),"foreign write committed after CAS");
    }
    std::vector<bool> done(server.nshards(),false);
    for(unsigned round=0;round<1000;++round) {
        bool all=true;
        for(int sid:state->shards) if(!done[sid]) {
            const auto result=multi_execute_task(server,multi_make_task(&client,0,sid,state),
                server.shard(sid),server.worker_of_shard(sid),0,nullptr);
            done[sid]=result!=MultiTaskResult::Retry; all &= done[sid];
        }
        if(all) break;
    }
    require(state->finalized.load(),"all reads joined");
    set_state_reply(*state,request.op);
    require(request.reply()==(handshake ? "*1\r\n+OK\r\n" : "*-1\r\n"),
            "EXEC final reply obeys held WATCH ordering");
    if(handshake) {
        require(local(server,{"GET",b})=="$3\r\nold\r\n","writer has not run before non-null EXEC");
        require(multi_plain_write_ready(server.shard(1),write.op),"writer resumes after EXEC");
    }
    release_records(server); destroy_multi_state(state);
}
}
int main(int argc,char** argv) {
    require(argc==3,"serve|readonly and 1s|2s");
    require(command_registry_init(false),"registry");
    Config cfg;cfg.databases=1;cfg.shards=16;cfg.even_ifid=6;cfg.even_ex=2;
    cfg.thread_mode=std::string(argv[2])=="1s" ? ThreadMode::Fused : ThreadMode::Split;
    cfg.read_local=cfg.thread_mode==ThreadMode::Fused;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.atomic=1;
    Server server;require(server.prepare_boot(cfg)&&server.init(cfg),"owner geometry");
    command_bind_server(&server);
    std::string error;require(acl_initialize(server,cfg,error),"default ACL");
    if(std::string(argv[1])=="serve") served_watch(server);
    else if(std::string(argv[1])=="readonly") readonly_watch(server);
    else if(std::string(argv[1])=="handshake") readonly_watch(server,true);
    else if(std::string(argv[1])=="rename") same_owner_rename(server);
    else require(false,"known WATCH regression");
    release_records(server);
    std::puts("PASS WATCH owner-turn regression");
}
