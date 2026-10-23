// Bounded serverless instruction fixture; production owner/scatter objects,
// no listening socket, worker thread, rate, or repeated measurement workload.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
using namespace tomo;
#if TOMO_SINGLE_DATABASE
#define NSM "8tomo_db0"
#else
#define NSM "4tomo"
#endif
extern "C" void production_split(void*, const Task*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb0EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
extern "C" void production_fused(void*, const Task*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb1EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
[[gnu::noinline]] void execfair_trace_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void execfair_trace_end(){asm volatile("" ::: "memory");}
namespace tomo {
struct CoreConcurrencyTest {
 static void need(bool v){if(!v)std::abort();}
 template<bool Fused> static void run(const std::string& command,unsigned n,bool atomic,int64_t slowlog){
  Server server;
  cpu_set_t mask;CPU_ZERO(&mask);need(sched_getaffinity(0,sizeof(mask),&mask)==0);
  std::string domain,place;unsigned count=0;
  for(int cpu=0;cpu<CPU_SETSIZE&&count<8;cpu++)if(CPU_ISSET(cpu,&mask)){
   if(count++){domain+='+';place+=',';}domain+=std::to_string(cpu);place+="ifid@"+std::to_string(cpu);
  }
  need(count==8&&server.topo_.declare(domain.c_str()));
  if constexpr(Fused)need(server.placement_.build_fused(server.topo_,place.c_str()));
  else need(server.placement_.build_even(server.topo_,6,2));
  need(server.placement_.reserve_runtime_roles(8));
  Config cfg;cfg.databases=1;cfg.shards=16;cfg.atomic=atomic;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;
  cfg.thread_mode=Fused?ThreadMode::Fused:ThreadMode::Split;cfg.read_local=0;cfg.save.clear();
  cfg.slowlog_log_slower_than=slowlog;cfg.latency_monitor_threshold=0;
  need(server.init(cfg));command_bind_server(&server);
  auto loops=std::make_unique<ExLoopT<Fused>[]>(8);
  for(unsigned tid=0;tid<8;tid++){
   auto& thread=server.thread(tid);
   need(Fused?thread.init_task_inbox_local_fused():thread.init_task_inbox_local(server.placement().ifid_threads(),server.placement().ex_threads()));
   auto& loop=loops[tid];loop.srv_=&server;loop.self_=&thread;loop.cached_now_ms_=1000;
   server.bind_owner_notify_pending(tid,&loop.notify_keyless_pending_);loop.refresh_live_config();
  }
  const unsigned io=Fused?7:0;
  Client client(-1);client.set_id(99101);client.set_ifid_thread(io);
  client.set_wb_slot(server.thread(io).assign_wb_slot(&client));
  std::vector<std::string> keys;
  for(unsigned sid=0;sid<8;sid++)for(unsigned k=0;;k++){
   std::string key="execfair-dispatch:"+std::to_string(k);Slice s(key.data(),key.size());
   if(server.router().shard_of(FlatStore::hash_key(s))==sid){keys.push_back(key);break;}
  }
  const std::string value = command == "INCR" ? "0" : std::string(64,'v');
  for(const auto& key:keys){
   Op op;op.reset();need(op.push_arg(Slice("SET")));need(op.push_arg({key.data(),uint32_t(key.size())}));need(op.push_arg({value.data(),uint32_t(value.size())}));
   op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));op.spec->handler(server.shard(server.router().shard_of(op.hash)),op);
   need(std::string(op.reply.data(),op.reply.size())=="+OK\r\n");
  }
  if(command=="GET"||command=="SET"||command=="INCR"){
   Task tasks[32];need(n<=32);
   for(unsigned i=0;i<n;i++){
    auto* op=client.rob().template acquire<false>();need(op);need(op->push_arg({command.data(),uint32_t(command.size())}));
    need(op->push_arg({keys[0].data(),uint32_t(keys[0].size())}));
    if(command=="SET")need(op->push_arg({value.data(),uint32_t(value.size())}));
    op->spec=command_lookup(op->arg(0));op->hash=FlatStore::hash_key(op->arg(1));op->shard=0;
    op->state.store(OpState::Issued,std::memory_order_relaxed);tasks[i]=Task{&client,client.rob().dispatch_id(),-1,nullptr};client.rob().publish();
   }
   auto& loop=loops[server.worker_of_shard(0)];
   execfair_trace_begin();
   if constexpr(Fused)production_fused(&loop,tasks,n);else production_split(&loop,tasks,n);
   execfair_trace_end();
   const std::string want=command=="SET"?"+OK\r\n":"$64\r\n"+value+"\r\n";
   unsigned completed = 0;
   need(client.rob().drain([&](Op& op){
    const std::string expected = command == "INCR" ? ":" + std::to_string(++completed) + "\r\n" : want;
    need(std::string(op.reply.data(),op.reply.size()) == expected);
   })==n);
  }else{
   need(command=="MGET"&&n<=8);
   auto ops=std::make_unique<Op[]>(n);ScatterArenaPool pool;Ring ring;
   for(unsigned i=0;i<n;i++){
    ops[i].reset();need(ops[i].push_arg(Slice("MGET")));
    for(const auto& key:keys)need(ops[i].push_arg({key.data(),uint32_t(key.size())}));
    ops[i].spec=command_lookup(ops[i].arg(0));
   }
   execfair_trace_begin();
   for(unsigned i=0;i<n;i++){
    auto& op=ops[i];ScatterDispatch dispatch;
    need(xshard_prepare(server,op,pool,io,client.id(),dispatch,false,&client)==ScatterPrepare::Ready);
    need(dispatch.nshards==8);op.attach_scatter_state(dispatch.state);
    for(unsigned k=0;k<dispatch.nshards;k++){
     const auto sid=xshard_dispatch_shard(dispatch,k);const auto owner=server.worker_of_shard(sid);auto& shard=server.shard(sid);
     const Task task{&client,i,sid,dispatch.state};need(!xshard_task_should_defer(server,shard,task,op));
     need(xshard_execute(task,shard,op,owner)==ScatterTaskResult::Complete);
     const auto done=Fused?xshard_complete_iofused(server,server.thread(owner),ring,task,op):xshard_complete(server,server.thread(owner),ring,task,op);
     need(done==(k+1==dispatch.nshards?ScatterFinish::Final:ScatterFinish::Waiting));
    }
    xshard_retire(server,server.thread(io),ring,client,op,pool,io,nullptr,nullptr,nullptr);
   }
   execfair_trace_end();
   std::string want="*8\r\n";for(unsigned i=0;i<8;i++)want+="$64\r\n"+value+"\r\n";
   for(unsigned i=0;i<n;i++)need(std::string(ops[i].reply.data(),ops[i].reply.size())==want);
  }
  command_bind_server(nullptr);
  std::puts("PASS bounded production command scope");
 }
};
}
int main(int argc,char**argv){
 if(argc!=4)return 2;
 if(!command_registry_init(false))return 3;
 if(std::string(argv[2])=="1s")CoreConcurrencyTest::run<true>(argv[1],std::stoul(argv[3]),true,-1);
 else CoreConcurrencyTest::run<false>(argv[1],std::stoul(argv[3]),true,-1);
}
