// Bounded serverless instruction fixture; production owner/scatter objects,
// no listening socket, worker thread, rate, or repeated measurement workload.
#include "src/core/io_loop.h"
#include "src/cmd/acl.h"
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
extern "C" int production_local_parse(void*, Client*)
    asm("_ZN" NSM "6IoLoop21r7_parse_and_dispatchILb0ELj32ELb0EEENS0_14DispatchResultEPNS_6ClientE");
extern "C" int production_split_parse(void*, Client*)
    asm("_ZN" NSM "6IoLoop18parse_and_dispatchILb0ELj0ELb0EEENS0_14DispatchResultEPNS_6ClientE");
extern "C" unsigned production_local_drain(void*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb1EE30drain_local_reads_bounded_implILb0EEEjj");
#ifdef TOMO_LATENCY_SCAN_WITNESS
bool wave8b_tracking = false;
uint64_t wave8b_scans = 0;
#endif
[[gnu::noinline]] void scope_begin(){
#ifdef TOMO_LATENCY_SCAN_WITNESS
 tomo::latency_scan_slots = 0;
#endif
 asm volatile("" ::: "memory");
}
[[gnu::noinline]] void scope_end(){
 asm volatile("" ::: "memory");
#ifdef TOMO_LATENCY_SCAN_WITNESS
 wave8b_scans = tomo::latency_scan_slots;
#endif
}
namespace tomo {
struct CoreConcurrencyTest {
 static void need(bool v,unsigned line=__builtin_LINE()){if(!v){std::fprintf(stderr,"scope assertion line %u\n",line);std::abort();}}
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
  Config cfg;cfg.databases=TOMO_SINGLE_DATABASE?1:16;cfg.shards=16;cfg.atomic=atomic;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;
  cfg.thread_mode=Fused?ThreadMode::Fused:ThreadMode::Split;cfg.read_local=(command=="READLOCAL-GET");cfg.latency_tracking=false;cfg.save.clear();
  cfg.slowlog_log_slower_than=slowlog;cfg.latency_monitor_threshold=0;
#ifdef TOMO_LATENCY_SCAN_WITNESS
  cfg.latency_tracking = wave8b_tracking;
#endif
  need(server.init(cfg));command_bind_server(&server);
  auto loops=std::make_unique<ExLoopT<Fused>[]>(8);
  for(unsigned tid=0;tid<8;tid++){
   auto& thread=server.thread(tid);
   need(Fused?thread.init_task_inbox_local_fused():thread.init_task_inbox_local(server.placement().ifid_threads(),server.placement().ex_threads()));
   auto& loop=loops[tid];loop.srv_=&server;loop.self_=&thread;loop.cached_now_ms_=1000;
   if constexpr(Fused) if(cfg.read_local){
    loop.read_local_.impl=std::make_unique<ReadLocalExImpl>();
    loop.read_local_impl().lane=std::make_unique<ReadLocalExImpl::LaneEntry[]>(kInboxSlots);
    loop.read_local_impl().lane_fallbacks=std::make_unique<ReadLocalFallbackReason[]>(kInboxSlots);
    auto& deferred=loop.read_local_impl().deferred;need(deferred.init(&server,&thread));
    for(Shard* sh:thread.shards()){need(sh->store().prepare_read_local());sh->store().configure_read_local(true,*deferred.sink());}
    thread.publish_read_local_tick(server.read_local_epoch());
    thread.bind_read_local_retire_sink(*deferred.sink());thread.set_read_local_lane_active(true);
    loop.bind_fused_completion(nullptr,[](void*,Client*){});
   }
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
  const std::string value = (command == "INCR" || command.starts_with("EXEC")) ? "0" : std::string(64,'v');
  for(const auto& key:keys){
   Op op;op.reset();need(op.push_arg(Slice("SET")));need(op.push_arg({key.data(),uint32_t(key.size())}));need(op.push_arg({value.data(),uint32_t(value.size())}));
   op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));op.spec->handler(server.shard(server.router().shard_of(op.hash)),op);
   need(std::string(op.reply.data(),op.reply.size())=="+OK\r\n");
  }
  need(n<=32);
  IoLoop reader;reader.srv_=&server;reader.self_=&server.thread(io);
  if constexpr(Fused)reader.fused_executor_=&loops[io];
  reader.refresh_notify_config();
  std::vector<std::string> args{command};
  if(command=="MGET" || command=="MSET"){
   for(const auto& key:keys){args.push_back(key);if(command=="MSET")args.push_back(value);}
  }else{args.push_back(keys[0]);if(command=="SET")args.push_back(value);}
  std::string frame="*"+std::to_string(args.size())+"\r\n";
  for(const auto& arg:args)frame+="$"+std::to_string(arg.size())+"\r\n"+arg+"\r\n";
  std::string wire;for(unsigned i=0;i<n;i++)wire+=frame;
  size_t available=0;need(client.read_space_impl<false>(wire.size(),available,true,1u<<20,0));
  need(available>=wire.size());std::memcpy(client.rbuf(),wire.data(),wire.size());client.commit_read(wire.size());
  scope_begin();
  if constexpr(Fused)production_local_parse(&reader,&client);else production_split_parse(&reader,&client);
  scope_end();
  need(client.rpos()==wire.size() && client.rob().dispatch_id()==n);
  for(unsigned i=0;i<n;i++){
   const auto& op=client.rob().at(i);need(op.argc()==args.size());
   for(unsigned a=0;a<args.size();a++)need(std::string(op.arg(a).p,op.arg(a).n)==args[a]);
   need(op.spec==command_lookup(op.arg(0)));
  }
  // Dispatch-only fixture: the separately counted owner/scatter fixture checks
  // replies and data. No worker runs here; exit without destructing queued tasks.
  std::puts("PASS bounded production parse scope");std::fflush(stdout);std::_Exit(0);
 }
};
}
int main(int argc,char**argv){
 if(argc!=6)return 2;
 if(!command_registry_init(false))return 3;
 if(std::string(argv[2])=="1s")CoreConcurrencyTest::run<true>(argv[1],std::stoul(argv[3]),std::stoi(argv[4]),std::stoll(argv[5]));
 else CoreConcurrencyTest::run<false>(argv[1],std::stoul(argv[3]),std::stoi(argv[4]),std::stoll(argv[5]));
 return 0;
}
