// Eight finite same-shard EXECs through the linked production owner batch.
// Preparation is outside the scope; exact replies and final values are checked.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <sched.h>
using namespace tomo;
#if TOMO_SINGLE_DATABASE
#define EXEC1S_NSM "8tomo_db0"
#else
#define EXEC1S_NSM "4tomo"
#endif
extern "C" void production_split(void*,const Task*,unsigned)
    asm("_ZN" EXEC1S_NSM "7ExLoopTILb0EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
extern "C" void production_fused(void*,const Task*,unsigned)
    asm("_ZN" EXEC1S_NSM "7ExLoopTILb1EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
[[gnu::noinline]] void scope_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void scope_end(){asm volatile("" ::: "memory");}
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool v,const char* file=__builtin_FILE(),int line=__builtin_LINE()){
        if(!v){std::fprintf(stderr,"scope failure %s:%d\n",file,line);std::abort();}
    }
    template<bool Fused> static void run(){
        Server server;cpu_set_t mask;CPU_ZERO(&mask);need(sched_getaffinity(0,sizeof(mask),&mask)==0);
        std::string domain,place;unsigned count=0;
        for(int cpu=0;cpu<CPU_SETSIZE&&count<8;++cpu)if(CPU_ISSET(cpu,&mask)){
            if(count++){domain+='+';place+=',';}domain+=std::to_string(cpu);place+="ifid@"+std::to_string(cpu);
        }
        need(count==8&&server.topo_.declare(domain.c_str()));
        if constexpr(Fused)need(server.placement_.build_fused(server.topo_,place.c_str()));
        else need(server.placement_.build_even(server.topo_,6,2));
        need(server.placement_.reserve_runtime_roles(8));
        Config cfg;cfg.databases=TOMO_SINGLE_DATABASE?1:16;cfg.shards=16;
        cfg.thread_mode=Fused?ThreadMode::Fused:ThreadMode::Split;cfg.read_local=0;
        cfg.even_ifid=6;cfg.even_ex=2;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.save.clear();
        cfg.slowlog_log_slower_than=-1;cfg.latency_monitor_threshold=0;
        need(server.init(cfg));command_bind_server(&server);
        std::string error;need(acl_initialize(server,cfg,error));
        auto owners=std::make_unique<ExLoopT<Fused>[]>(8);
        for(unsigned tid=0;tid<8;++tid){
            auto& thread=server.thread(tid);
            need(Fused?thread.init_task_inbox_local_fused():thread.init_task_inbox_local(
                server.placement().ifid_threads(),server.placement().ex_threads()));
            auto& owner=owners[tid];owner.srv_=&server;owner.self_=&thread;
            owner.cached_now_ms_=now_realtime_ms();owner.refresh_live_config();
            server.bind_owner_notify_pending(tid,&owner.notify_keyless_pending_);
        }
        const unsigned io=Fused?7:server.placement().ifid_threads().front();
        auto loop=std::make_unique<IoLoop>();loop->srv_=&server;loop->self_=&server.thread(io);
        std::vector<std::string> keys;
        for(unsigned i=0;keys.size()<2;++i){
            auto key="exec1s-owner:"+std::to_string(i);
            if(server.router().shard_of(FlatStore::hash_key(Slice(key.data(),key.size())))==0)keys.push_back(key);
        }
        constexpr unsigned n=8;
        std::vector<std::unique_ptr<Client>> clients;
        std::vector<Op*> carriers;
        for(unsigned i=0;i<n;++i){
            auto client=std::make_unique<Client>(-1);client->set_id(992000+i);client->set_ifid_thread(io);
            client->set_wb_slot(server.thread(io).assign_wb_slot(client.get()));
            for(auto args:std::vector<std::vector<std::string>>{{"MULTI"},{"INCR",keys[0]},{"INCR",keys[1]},{"EXEC"}}){
                auto* op=client->rob().acquire();need(op);
                for(const auto& a:args)need(op->push_arg(Slice(a.data(),a.size())));
                op->spec=command_lookup(op->arg(0));need(op->spec);
                need(multi_dispatch_entry(*loop,*client,*op,0));
                if(args[0]=="EXEC"){need(op->has_multi_state());carriers.push_back(op);}
                else need(op->state.load()==OpState::Done);
            }
            client->retire_queued().store(true);
            clients.push_back(std::move(client));
        }
        std::vector<Task> tasks;
        for(unsigned tid=0;tid<8;++tid)server.thread(tid).drain_tasks_unmasked(
            [&](const Task& task){need(task.shard==0);tasks.push_back(task);});
        need(tasks.size()==n);
        auto& owner=owners[server.worker_of_shard(0)];
        scope_begin();
        if constexpr(Fused)production_fused(&owner,tasks.data(),tasks.size());
        else production_split(&owner,tasks.data(),tasks.size());
        scope_end();
        for(auto* op:carriers)need(op->state.load()==OpState::Done);
        for(unsigned sid=0;sid<server.nshards();++sid)server.shard(sid).store().atomic_shutdown_release_records();
        for(unsigned i=0;i<n;++i){
            auto& client=*clients[i];multi_retire_entry(*loop,client,*carriers[i]);
            need(client.rob().drain([&](Op& op){if(&op==carriers[i]){
                auto value=":"+std::to_string(i+1)+"\r\n";
                need(std::string(op.reply.data(),op.reply.size())=="*2\r\n"+value+value);
            }})==4);
            server.thread(io).release_wb_slot(client.wb_slot());
        }
        need(multi_owner_reap_entry(*loop)==0);
        for(const auto& key:keys){
            Op op;op.reset();need(op.push_arg(Slice("GET")));need(op.push_arg(Slice(key.data(),key.size())));
            op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));
            op.spec->handler(server.shard(0),op);need(std::string(op.reply.data(),op.reply.size())=="$1\r\n8\r\n");
        }
        std::puts("PASS eight linked same-shard EXECs and exact final values");
    }
};
}
int main(int argc,char** argv){
    if(argc<3||!command_registry_init(false))return 2;
    if(std::string(argv[2])=="1s")CoreConcurrencyTest::run<true>();
    else CoreConcurrencyTest::run<false>();
}
