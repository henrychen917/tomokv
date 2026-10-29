// rlfix4: bounded serverless instruction fixture; production owner/scatter objects,
// no listening socket, worker thread, rate, or repeated measurement workload.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
#include <source_location>
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
extern "C" int production_parse(void*,Client*)
    asm("_ZN" NSM "6IoLoop18parse_and_dispatchILb0ELj32ELb0EEENS0_14DispatchResultEPNS_6ClientE");
extern "C" int production_r7_parse(void*,Client*)
    asm("_ZN" NSM "6IoLoop21r7_parse_and_dispatchILb0ELj32ELb0EEENS0_14DispatchResultEPNS_6ClientE");
#ifdef TOMO_RLFIX4_ADMISSION
extern "C" int production_split_parse(void*,Client*)
    asm("_ZN" NSM "6IoLoop18parse_and_dispatchILb0ELj0ELb0EEENS0_14DispatchResultEPNS_6ClientE");
extern "C" int production_split_local_parse(void*,Client*)
    asm("_ZN" NSM "6IoLoop18parse_and_dispatchILb0ELj32ELb1EEENS0_14DispatchResultEPNS_6ClientE");
#endif
extern "C" unsigned production_local(void*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb1EE30drain_local_reads_bounded_implILb0EEEjj");
[[gnu::noinline]] void scope_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void scope_end(){asm volatile("" ::: "memory");}
namespace tomo {
struct CoreConcurrencyTest {
 static void need(bool v,std::source_location at=std::source_location::current()){if(!v){std::fprintf(stderr,"scope assertion line %u\n",at.line());std::abort();}}
 template<bool Fused> static void run(const std::string& command,unsigned n,bool atomic,int64_t slowlog,const std::string& route){
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
  cfg.thread_mode=Fused?ThreadMode::Fused:ThreadMode::Split;cfg.read_local=route!="owner0";cfg.save.clear();
  cfg.slowlog_log_slower_than=slowlog;cfg.latency_monitor_threshold=0;
  need(server.init(cfg));command_bind_server(&server);
  auto loops=std::make_unique<ExLoopT<Fused>[]>(8);
  for(unsigned tid=0;tid<8;tid++){
   auto& thread=server.thread(tid);
   need(Fused?thread.init_task_inbox_local_fused():thread.init_task_inbox_local(server.placement().ifid_threads(),server.placement().ex_threads()));
   auto& loop=loops[tid];loop.srv_=&server;loop.self_=&thread;loop.cached_now_ms_=1000;
   server.bind_owner_notify_pending(tid,&loop.notify_keyless_pending_);loop.refresh_live_config();
  }
  auto local_loops=std::make_unique<ExLoopT<true>[]>(8);
  if(cfg.read_local)for(unsigned tid=0;tid<8;tid++){
   auto init_lane=[&](ExLoopT<true>& loop){
    loop.srv_=&server;loop.self_=&server.thread(tid);loop.cached_now_ms_=1000;
    loop.read_local_.impl=std::make_unique<ReadLocalExImpl>();
    auto& lane=loop.read_local_impl();
    lane.lane=std::make_unique<ReadLocalExImpl::LaneEntry[]>(kInboxSlots);
    lane.lane_fallbacks=std::make_unique<ReadLocalFallbackReason[]>(kInboxSlots);
    need(lane.deferred.init(&server,loop.self_));
    loop.refresh_live_config();loop.bind_fused_completion(nullptr,[](void*,Client*){});
   };
   init_lane(local_loops[tid]);
   if constexpr(Fused)init_lane(loops[tid]);
   for(Shard* shard:server.thread(tid).shards())
    shard->store().configure_read_local(true,*local_loops[tid].read_local_impl().deferred.sink());
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
#ifdef TOMO_RLFIX4_ADMISSION
  {
   auto& reader=local_loops[io];auto& rob=client.rob();
   IoLoop parser;parser.srv_=&server;parser.self_=&server.thread(io);parser.fused_executor_=&reader;
   parser.refresh_notify_config();parser.flip_pass_begin();
   std::string wire;
   const unsigned nk=(command=="MGET"||command=="MSET")?8:1;
   const unsigned argc=1+nk*((command=="MSET"||command=="SET")?2:1);
   auto bulk=[&](const std::string& s){wire+="$"+std::to_string(s.size())+"\r\n"+s+"\r\n";};
   for(unsigned i=0;i<n;i++){
    wire+="*"+std::to_string(argc)+"\r\n";bulk(command);
    for(unsigned k=0;k<nk;k++){bulk(keys[k]);if(command=="MSET"||command=="SET")bulk(value);}
   }
   size_t avail=0;char* dest=client.read_space(wire.size(),avail,true);
   need(dest&&avail>=wire.size());std::memcpy(dest,wire.data(),wire.size());client.commit_read(wire.size());
   auto entry=Fused?production_parse:(cfg.read_local?production_split_local_parse:production_split_parse);
   unsigned passes=0,done=0;
   scope_begin();
   do {
    const auto before=client.rpos();entry(&parser,&client);
    need(client.rpos()>before&&++passes<=n);
    // MGET's real one-command cut fence is released by the production local
    // drain. Owner tasks remain queued: this scope measures admission, not EX.
    if(cfg.read_local&&(command=="GET"||command=="MGET"))done+=production_local(&reader,32);
   }while(client.rpos()!=client.rlen());
   scope_end();
   need(rob.dispatch_id()==n&&rob.in_flight()==n);
   const bool local=cfg.read_local&&(command=="GET"||command=="MGET");
   need(done==(local?n:0));
   for(unsigned i=0;i<n;i++){
    auto& op=rob.at(i);need(op.spec==command_lookup({command.data(),uint32_t(command.size())}));
    need(op.argc()==argc);need((op.state.load()==OpState::Done)==local);
    for(unsigned k=0;k<nk;k++){
     const Slice arg=op.arg(1+k*((command=="MSET"||command=="SET")?2:1));
     need(std::string(arg.p,arg.n)==keys[k]);
    }
    if(local){
     std::string expected=command=="MGET"?"*8\r\n":"";
     for(unsigned k=0;k<nk;k++)expected+="$64\r\n"+value+"\r\n";
     const std::string actual=(op.direct_len?std::string(op.direct,op.direct_len):std::string{})+
                              std::string(op.reply.data(),op.reply.size());
     need(actual==expected);
    }
   }
   std::printf("ADMISSION commands=%u keys=%u passes=%u local_completed=%u owner_pending=%u\n",n,nk,passes,done,n-done);
  }
#else
  if(route=="local"||route=="mix"||route=="parse"||route=="parsemix"||route=="r7parse"||route=="r7mix"){
   need(command=="GET"||command=="MGET");need(n==1||n==32);
   auto& reader=local_loops[io];auto& rob=client.rob();
   unsigned reads=0,writes=0;
   auto queue=[&](bool write){
    auto* op=rob.acquire_read_local();need(op);
    need(op->push_arg(write?Slice("SET"):Slice(command.data(),uint32_t(command.size()))));
    if(write){
     need(op->push_arg({keys[7].data(),uint32_t(keys[7].size())}));
     need(op->push_arg({value.data(),uint32_t(value.size())}));
    }else for(unsigned k=0;k<(command=="MGET"?8:1);k++)
     need(op->push_arg({keys[k].data(),uint32_t(keys[k].size())}));
    op->spec=command_lookup(op->arg(0));need(op->spec);
    op->hash=FlatStore::hash_key(op->arg(1));op->shard=server.router().shard_of(op->hash);
    op->state.store(OpState::Issued,std::memory_order_release);
    const auto id=rob.dispatch_id();
    if(write){rob.mark_current_write();need(rob.refine_current_write_hash(op->hash));op->mark_read_local_precise_write();++writes;}
    else{need(!rob.read_local_write_conflicts(op->hash,[&](const Op& write,uint64_t hash){return read_local_command_touches_hash(write,hash);}));op->mark_read_local();rob.mark_current_read_local_hash(id,op->hash);++reads;}
    rob.publish();
    if(!write)reader.enqueue_local_read(&client,id,command=="MGET"?8:1);
   };
   // Arm on a completed fresh GET before introducing precise pending writes.
   // This excludes the connection's one-shot arm transient from the steady scope.
   if(route=="mix"||route=="parsemix"||route=="r7mix"){
    need(command=="GET");queue(false);need(production_local(&reader,32)==1);
    need(rob.drain([](Op&){})==1);reads=0;
    if(n==1)queue(true);
   }
   const bool parsing=route=="parse"||route=="parsemix"||route=="r7parse"||route=="r7mix";
   const bool mixed=route=="parsemix"||route=="r7mix";
   auto parse_entry=route.starts_with("r7")?production_r7_parse:production_parse;
   IoLoop parser;parser.srv_=&server;parser.self_=&server.thread(io);parser.fused_executor_=&reader;
   parser.refresh_notify_config();
   // Production sets this once per IO pass. Avoid the standalone caller's live
   // FLIP fallback when counting steady command admission.
   parser.flip_pass_begin();
   std::string wire;
   if(parsing){
    need(Fused&&command=="GET");
    for(unsigned i=0;i<n;i++){
     const bool write=mixed&&i%10==9;
     const auto& key=keys[write?7:0];
     wire+=(write?"*3\r\n$3\r\nSET":"*2\r\n$3\r\nGET");
     wire+="\r\n$"+std::to_string(key.size())+"\r\n"+key+"\r\n";
     if(write){wire+="$64\r\n"+value+"\r\n";++writes;}else ++reads;
    }
    std::memcpy(client.rbuf(),wire.data(),wire.size());client.commit_read(wire.size());
   }else for(unsigned i=0;i<n;i++)queue(route=="mix"&&i%10==9);
   const auto hits=server.thread(io).read_local_stats().keyspace_hits;
   scope_begin();
   if(parsing)parse_entry(&parser,&client);
   const auto done=production_local(&reader,32);
   scope_end();
   if(parsing)need(client.rpos()==client.rlen());
   need(done==reads&&reader.read_local_impl().lane_count==0);
   need(server.thread(io).read_local_stats().keyspace_hits-hits==reads*(command=="MGET"?8:1));
   const std::string bulk="$64\r\n"+value+"\r\n";
   std::string expected=command=="MGET"?"*8\r\n":"";
   for(unsigned k=0;k<(command=="MGET"?8:1);k++)expected+=bulk;
   unsigned checked=0;
   for(auto id=rob.flush_id();id<rob.dispatch_id();id++){
    auto& op=rob.at(id);
    if(op.spec->flags&CmdFlags::Write){need(op.state.load()!=OpState::Done);op.state.store(OpState::Done);}
    else{need(op.state.load()==OpState::Done);need(std::string(op.direct_len?op.direct:op.reply.data(),op.direct_len?op.direct_len:op.reply.size())==expected);++checked;}
   }
   need(checked==reads);need(rob.drain([](Op&){})==reads+writes);
   std::printf("WITNESS reads=%u pending_writes=%u keys_per_read=%u\n",reads,writes,command=="MGET"?8:1);
  }else if(command=="GET"||command=="SET"||command=="INCR"){
   Task tasks[32];need(n<=32);
   for(unsigned i=0;i<n;i++){
    auto* op=client.rob().template acquire<false>();need(op);need(op->push_arg({command.data(),uint32_t(command.size())}));
    need(op->push_arg({keys[0].data(),uint32_t(keys[0].size())}));
    if(command=="SET")need(op->push_arg({value.data(),uint32_t(value.size())}));
    op->spec=command_lookup(op->arg(0));op->hash=FlatStore::hash_key(op->arg(1));op->shard=0;
    op->state.store(OpState::Issued,std::memory_order_relaxed);tasks[i]=Task{&client,client.rob().dispatch_id(),-1,nullptr};client.rob().publish();
   }
   auto& loop=loops[server.worker_of_shard(0)];
   scope_begin();
   if constexpr(Fused)production_fused(&loop,tasks,n);else production_split(&loop,tasks,n);
   scope_end();
   const std::string want=command=="SET"?"+OK\r\n":"$64\r\n"+value+"\r\n";
   unsigned completed = 0;
   need(client.rob().drain([&](Op& op){
    const std::string expected = command == "INCR" ? ":" + std::to_string(++completed) + "\r\n" : want;
    need(std::string(op.reply.data(),op.reply.size()) == expected);
   })==n);
  }else{
   need((command=="MGET"||command=="MSET")&&n<=32);
   Op* ops[32];uint32_t ids[32];ScatterArenaPool pool;Ring ring;
   const std::string updated(64,'w');
   for(unsigned i=0;i<n;i++){
    ids[i]=client.rob().dispatch_id();ops[i]=client.rob().template acquire<false>();need(ops[i]);
    need(ops[i]->push_arg({command.data(),uint32_t(command.size())}));
    for(const auto& key:keys){
     need(ops[i]->push_arg({key.data(),uint32_t(key.size())}));
     if(command=="MSET")need(ops[i]->push_arg({updated.data(),uint32_t(updated.size())}));
    }
    ops[i]->spec=command_lookup(ops[i]->arg(0));
    ops[i]->state.store(OpState::Issued,std::memory_order_relaxed);client.rob().publish();
   }
   if(command=="MSET"&&atomic)for(unsigned i=0;i<n;i++)client.atomic_group_started();
   scope_begin();
   for(unsigned i=0;i<n;i++){
    auto& op=*ops[i];ScatterDispatch dispatch;
    need(xshard_prepare(server,op,pool,io,client.id(),dispatch,false,&client)==ScatterPrepare::Ready);
    need(dispatch.nshards==8);op.attach_scatter_state(dispatch.state);
    for(unsigned k=0;k<dispatch.nshards;k++){
     const auto sid=xshard_dispatch_shard(dispatch,k);const auto owner=server.worker_of_shard(sid);auto& shard=server.shard(sid);
     const Task task{&client,ids[i],sid,dispatch.state};need(!xshard_task_should_defer(server,shard,task,op));
     need(xshard_execute(task,shard,op,owner)==ScatterTaskResult::Complete);
     const auto done=Fused?xshard_complete_iofused(server,server.thread(owner),ring,task,op):xshard_complete(server,server.thread(owner),ring,task,op);
     if(k+1<dispatch.nshards)need(done==ScatterFinish::Waiting);
     else if(done==ScatterFinish::CommitQueued){
      need(command=="MSET"&&atomic);
      xshard_queue_commit(server,server.thread(owner),task);
      xshard_flush_commits(server,server.thread(owner),ring,nullptr,[](void*,Client*){});
      need(op.state.load(std::memory_order_acquire)==OpState::Done);
     }else need(done==ScatterFinish::Final);
    }
    xshard_retire(server,server.thread(io),ring,client,op,pool,io,nullptr,nullptr,nullptr);
   }
   scope_end();
   std::string want="+OK\r\n";
   if(command=="MGET"){want="*8\r\n";for(unsigned i=0;i<8;i++)want+="$64\r\n"+value+"\r\n";}
   for(unsigned i=0;i<n;i++){
    need(std::string(ops[i]->reply.data(),ops[i]->reply.size())==want);
    ops[i]->state.store(OpState::Done,std::memory_order_release);
   }
   need(client.rob().drain([](Op&){})==n);
   if(command=="MSET")for(const auto& key:keys){
    Op op;op.reset();need(op.push_arg(Slice("GET")));need(op.push_arg({key.data(),uint32_t(key.size())}));
    op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));
    op.spec->handler(server.shard(server.router().shard_of(op.hash)),op);
    need(std::string(op.reply.data(),op.reply.size())=="$64\r\n"+updated+"\r\n");
   }
  }
#endif
  if(cfg.read_local)for(unsigned tid=0;tid<8;tid++){
   local_loops[tid].read_local_impl().deferred.drain_shutdown();
   if constexpr(Fused)loops[tid].read_local_impl().deferred.drain_shutdown();
   for(Shard* shard:server.thread(tid).shards())shard->store().configure_read_local(false,{});
  }
  command_bind_server(nullptr);
  std::puts("PASS bounded production command scope");
 }
};
}
int main(int argc,char**argv){
 if(argc!=7)return 2;
 if(!command_registry_init(false))return 3;
 if(std::string(argv[2])=="1s")CoreConcurrencyTest::run<true>(argv[1],std::stoul(argv[3]),std::stoi(argv[4]),std::stoll(argv[5]),argv[6]);
#ifndef TOMO_RLFIX4_LOCAL_HISTORY
 else CoreConcurrencyTest::run<false>(argv[1],std::stoul(argv[3]),std::stoi(argv[4]),std::stoll(argv[5]),argv[6]);
#else
 else return 2;
#endif
 return 0;
}
