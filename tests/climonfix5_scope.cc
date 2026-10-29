// Bounded serverless instruction fixture; production owner/scatter objects,
// no listening socket, worker thread, rate, or repeated measurement workload.
#include "src/core/io_loop.h"
#include "src/cmd/acl.h"
#include "src/cmd/scripting.h"
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
  std::string error;need(acl_initialize(server,cfg,error));
  const unsigned io=Fused?7:0;
  Client client(-1);client.set_id(99101);client.set_ifid_thread(io);
  client.set_wb_slot(server.thread(io).assign_wb_slot(&client));
  command_client_connected(&client,"127.0.0.1:20299","127.0.0.1:20200",false,1000);
  std::vector<std::string> keys;
  for(unsigned sid=0;sid<8;sid++)for(unsigned k=0;;k++){
   std::string key="execfair-dispatch:"+std::to_string(k);Slice s(key.data(),key.size());
   if(server.router().shard_of(FlatStore::hash_key(s))==sid){keys.push_back(key);break;}
  }
  const std::string value = "0";
  for(const auto& key:keys){
   Op op;op.reset();need(op.push_arg(Slice("SET")));need(op.push_arg({key.data(),uint32_t(key.size())}));need(op.push_arg({value.data(),uint32_t(value.size())}));
   op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));op.spec->handler(server.shard(server.router().shard_of(op.hash)),op);
   need(std::string(op.reply.data(),op.reply.size())=="+OK\r\n");
  }
  IoLoop reader;reader.srv_=&server;reader.self_=&server.thread(io);
  if constexpr(Fused)reader.fused_executor_=&loops[io];
  reader.refresh_notify_config();
  auto frame=[](const std::vector<std::string>& args){
   std::string s="*"+std::to_string(args.size())+"\r\n";
   for(const auto& a:args)s+="$"+std::to_string(a.size())+"\r\n"+a+"\r\n";
   return s;
  };
  std::vector<std::string> replies;
  auto drive=[&](const std::string& wire){
   need(client.rob().quiesced());client.reset_rbuf_at_quiescence();
   size_t available=0;need(client.read_space_impl<false>(wire.size(),available,true,1u<<20,0));
   need(available>=wire.size());std::memcpy(client.rbuf(),wire.data(),wire.size());client.commit_read(wire.size());
   std::vector<Task> pending;
   for(unsigned pass=0;pass<4096;pass++){
    if(!client.scatter_barrier()){
     if constexpr(Fused)production_local_parse(&reader,&client);else production_split_parse(&reader,&client);
    }
    for(unsigned tid=0;tid<8;tid++)server.thread(tid).drain_tasks([&](const Task& t){pending.push_back(t);});
    for(size_t i=0;i<pending.size();){
     const Task task=pending[i];auto& op=client.rob().at(task.op_id);
     const int sid=task.shard<0?op.shard:task.shard;
     auto& shard=server.shard(sid);const auto owner=server.worker_of_shard(sid);
     bool retry=false;
     if(multi_task_tagged(task)){
      auto result=multi_execute_task(server,task,shard,owner,0,nullptr);
      retry=multi_task_retry(result);
      if(result==MultiTaskResult::Final)op.state.store(OpState::Done);
     }else if(task.scatter){
      if(xshard_task_should_defer(server,shard,task,op))retry=true;
      else{
       auto result=xshard_execute(task,shard,op,owner);
       need(result==ScatterTaskResult::Complete);
       auto done=Fused?xshard_complete_iofused(server,server.thread(owner),reader.ring_,task,op)
                      :xshard_complete(server,server.thread(owner),reader.ring_,task,op);
       if(done==ScatterFinish::Final)op.state.store(OpState::Done);
       else need(done==ScatterFinish::Waiting);
      }
     }else{
      if constexpr(Fused)production_fused(&loops[owner],&task,1);
      else production_split(&loops[owner],&task,1);
     }
     if(retry)i++;else pending.erase(pending.begin()+i);
    }
    client.rob().drain([&](Op& op){
     if(op.has_multi_state())multi_retire_entry(reader,client,op);
     else if(op.has_scatter_state())xshard_retire(server,server.thread(io),reader.ring_,client,op,reader.scatter_pool_,io,nullptr,nullptr,nullptr);
     std::string reply;
     if(op.direct_len)reply.assign(op.direct,op.direct_len);
     reply.append(op.reply.data(),op.reply.size());
     if(op.reply_code_){
      char buf[64];const auto bytes=format_reply_code(buf,op.reply_code_,op.reply_ival_);reply.append(buf,bytes);
     }
     replies.push_back(reply);
    });
    if(client.rob().quiesced())client.barrier_release_quiesced();
    if(client.rpos()==wire.size()&&client.rob().quiesced()&&pending.empty())return;
   }
   need(false);
  };
  const bool cross=command.find("cross")!=std::string::npos;
  const bool header=command.find("header")!=std::string::npos;
  const bool exec=command.starts_with("EXEC");
  const bool aborted=command.find("abort")!=std::string::npos;
  const std::string key2=cross?keys[1]:keys[0];
  std::string unit;
  std::string expected;
  bool pre_header_rejected=false;
  if(exec){
   unit=frame({"MULTI"})+frame({"INCR",keys[0]})+frame({"INCR",key2})+frame({"EXEC"});
  }else if(command=="PING")unit=frame({"PING"});
  else if(command=="WATCH")unit=frame({"WATCH",keys[0]});
  else{
   const std::string body=header?"return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}":
       "return {redis.call('INCR',KEYS[1]),redis.call('INCR',KEYS[2])}";
   const std::string code=(header?"#!lua flags=no-writes\n":"")+body;
   if(command.starts_with("FCALL")){
    const std::string function="#!lua name=scope\nredis.register_function('scope',function(keys,args) "+
      std::string("return {redis.call('INCR',keys[1]),redis.call('INCR',keys[2])} end)");
    drive(frame({"FUNCTION","LOAD",function}));need(replies.back()=="$5\r\nscope\r\n");
    unit=frame({"FCALL","scope","2",keys[0],key2});
   }else{
    drive(frame({"SCRIPT","LOAD",code}));
    pre_header_rejected=header&&replies.back().starts_with("-ERR");
    if(command.starts_with("EVALSHA")&&!pre_header_rejected){
     need(replies.back().starts_with("$40\r\n"));
     unit=frame({"EVALSHA",replies.back().substr(5,40),"2",keys[0],key2});
    }else unit=frame({"EVAL",code,"2",keys[0],key2});
   }
   drive(unit); // warm interpreter and chunk outside the measured sequence
   if(!pre_header_rejected)need(replies.back().starts_with("*2\r\n"));
  }
  // Restore exact values after warmup, before arming WATCH.
  drive(frame({"SET",keys[0],"0"})+frame({"SET",key2,"0"}));replies.clear();
  scope_begin();
  if(aborted){
   for(unsigned i=0;i<n;i++){
    drive(frame({"WATCH",keys[0]}));
    // Deterministic owner-side WATCH invalidation, no racing worker or timer.
    client.set_watch_dirty();
    drive(unit);
   }
  }else{
   std::string wire;for(unsigned i=0;i<n;i++)wire+=unit;
   drive(wire);
  }
  scope_end();
  for(unsigned i=0;i<n;i++){
   if(exec){
    if(aborted)expected+="+OK\r\n";
    expected+="+OK\r\n+QUEUED\r\n+QUEUED\r\n";
    if(aborted)expected+="*-1\r\n";
    else expected+="*2\r\n:"+std::to_string(cross?i+1:2*i+1)+"\r\n:"+std::to_string(cross?i+1:2*i+2)+"\r\n";
   }else if(command=="PING")expected+="+PONG\r\n";
   else if(command=="WATCH")expected+="+OK\r\n";
   else if(header&&!pre_header_rejected)expected+="*2\r\n$1\r\n0\r\n$1\r\n0\r\n";
   else if(!header)expected+="*2\r\n:"+std::to_string(cross?i+1:2*i+1)+"\r\n:"+std::to_string(cross?i+1:2*i+2)+"\r\n";
  }
  std::string actual;for(const auto& r:replies)actual+=r;
  if(pre_header_rejected){need(replies.size()==n);for(auto& r:replies)need(r.starts_with("-ERR"));}
  else if(actual!=expected){std::fprintf(stderr,"expected [%s] actual [%s]\n",expected.c_str(),actual.c_str());need(false);}
  std::printf("PASS scope %s %s batch=%u header_rejected=%d replies=%zu\n",command.c_str(),Fused?"1s":"2s",n,int(pre_header_rejected),replies.size());
  std::fflush(stdout);std::_Exit(0);
 }
};
}
int main(int argc,char**argv){
 if(argc!=6)return 2;
 if(!command_registry_init(false))return 3;
 if(std::string(argv[2])=="1s")CoreConcurrencyTest::run<true>(argv[1],std::stoul(argv[3]),std::stoi(argv[4]),std::stoll(argv[5]));
 else CoreConcurrencyTest::run<false>(argv[1],std::stoul(argv[3]),std::stoi(argv[4]),std::stoll(argv[5]));
}
