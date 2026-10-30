// Linked production MULTI IO entry: includes preparation and dispatch, no server.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
#if TOMO_SINGLE_DATABASE
#define EXEC1S_NSM "8tomo_db0"
#else
#define EXEC1S_NSM "4tomo"
#endif
// Call the body selected by the production link, never an inlined fixture copy.
extern "C" bool production_wb_defer(tomo::Client&, const tomo::wb_rule::Settings&)
    asm("_ZN" EXEC1S_NSM "7wb_rule5deferINS_6ClientEEEbRT_RKNS0_8SettingsE");
[[gnu::noinline]] void scope_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void scope_end(){asm volatile("" ::: "memory");}
namespace tomo {
struct CoreConcurrencyTest {
    [[gnu::noinline]] static void need(bool v, const char* file=__builtin_FILE(), int line=__builtin_LINE()){if(!v){std::fprintf(stderr,"scope failure %s:%d\n",file,line);std::abort();}}
    static void run(bool fused,unsigned nshards,bool wb,bool expect_hold){
        Config cfg;cfg.databases=TOMO_SINGLE_DATABASE?1:16;cfg.shards=nshards;
        cfg.even_ifid=6;cfg.even_ex=2;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;
        cfg.thread_mode=fused?ThreadMode::Fused:ThreadMode::Split;cfg.read_local=0;cfg.save.clear();
        Server server;
        cpu_set_t mask;CPU_ZERO(&mask);need(sched_getaffinity(0,sizeof(mask),&mask)==0);
        std::string domain,place;unsigned count=0;
        for(int cpu=0;cpu<CPU_SETSIZE&&count<8;++cpu) if(CPU_ISSET(cpu,&mask)) {
            if(count++){domain+='+';place+=',';}domain+=std::to_string(cpu);place+="ifid@"+std::to_string(cpu);
        }
        need(count==8&&server.topo_.declare(domain.c_str()));
        need(fused?server.placement_.build_fused(server.topo_,place.c_str()):server.placement_.build_even(server.topo_,6,2));
        need(server.placement_.reserve_runtime_roles(8));
        need(server.init(cfg));command_bind_server(&server);
        std::string error;need(acl_initialize(server,cfg,error));
        for(unsigned tid=0;tid<server.nthreads();++tid){
            auto& t=server.thread(tid);
            need(fused?t.init_task_inbox_local_fused():t.init_task_inbox_local(
                server.placement().ifid_threads(),server.placement().ex_threads()));
        }
        const unsigned io=server.placement().ifid_threads().front();
        auto loop=std::make_unique<IoLoop>();loop->srv_=&server;loop->self_=&server.thread(io);
        Client client(-1);client.set_id(991991);client.set_ifid_thread(io);
        client.set_wb_slot(server.thread(io).assign_wb_slot(&client));
        std::vector<std::string> keys;
        for(unsigned target:{nshards-1,nshards/2}) for(unsigned i=0;;++i){
            std::string key="exec1s-io:"+std::to_string(i);Slice s(key.data(),key.size());
            if(server.router().shard_of(FlatStore::hash_key(s))==target){keys.push_back(key);break;}
        }
        auto prepare=[&](std::vector<std::string> args){
            Op* op=client.rob().acquire();need(op);
            for(const auto& a:args)need(op->push_arg(Slice(a.data(),a.size())));
            // Own the slices until MULTI copies them or dispatch consumes EXEC.
            op->spec=command_lookup(op->arg(0));need(op->spec);
            return std::pair{op,std::move(args)};
        };
        for(auto args:std::vector<std::vector<std::string>>{{"MULTI"},{"INCR",keys[0]},{"INCR",keys[1]}}){
            auto [op,owned]=prepare(std::move(args));need(multi_dispatch_entry(*loop,client,*op,0));
            need(op->state.load()==OpState::Done);
        }
        auto [op,owned]=prepare({"EXEC"});
        if (!wb) scope_begin();
        need(multi_dispatch_entry(*loop,client,*op,0));
        if (!wb) scope_end();
        need(op->has_multi_state());
        if (wb) {
            need(client.rob().in_flight()==4 && op->state.load()!=OpState::Done);
            client.wb_deferrals()=wb_rule::kCompleteVisits;
            const wb_rule::Settings settings{};
            scope_begin();
            const bool held=production_wb_defer(client,settings);
            scope_end();
            need(held==expect_hold && client.wb_deferrals()==wb_rule::kCompleteVisits);
        }
        auto* state=static_cast<MultiExecState*>(op->multi_state());
        need(multi_dispatch_count(state)==2);
        std::vector<Task> tasks;
        for(unsigned tid=0;tid<server.nthreads();++tid)
            server.thread(tid).drain_tasks_unmasked([&](const Task& task){tasks.push_back(task);});
        need(tasks.size()==2);
        std::vector<bool> done(2,false);
        for(unsigned pass=0;pass<64 && !(done[0]&&done[1]);++pass) for(unsigned i=0;i<2;++i){
            if(done[i])continue;auto& task=tasks[i];
            const auto result=multi_execute_task(server,task,server.shard(task.shard),
                server.worker_of_shard(task.shard),0,nullptr);
            done[i]=!multi_task_retry(result);
        }
        need(done[0]&&done[1]);
        for(unsigned sid=0;sid<server.nshards();++sid)server.shard(sid).store().atomic_shutdown_release_records();
        op->state.store(OpState::Done);
        multi_retire_entry(*loop,client,*op);
        need(client.rob().drain([&](Op& row){
            if(row.spec==command_lookup(Slice("EXEC")))
                need(std::string(row.reply.data(),row.reply.size())=="*2\r\n:1\r\n:1\r\n");
        })==4);
        need(multi_owner_reap_entry(*loop)==0);
        server.thread(io).release_wb_slot(client.wb_slot());
        std::puts("PASS linked EXEC IO preparation and dispatch");
    }
};
}
int main(int argc,char** argv){
    tomo::CoreConcurrencyTest::need(argc>=3&&tomo::command_registry_init(false));
    const bool fused=std::string(argv[2])=="1s";
    tomo::CoreConcurrencyTest::run(fused,fused?64:16,std::string(argv[1])=="WB",
                                  argc>5 && std::string(argv[5])=="1");
}
