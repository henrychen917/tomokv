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
    served_watch(server);
    release_records(server);
}
