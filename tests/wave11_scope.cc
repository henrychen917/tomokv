// wave11: warm EVAL/EVALSHA/FCALL with original wave10 owner/scatter scope.
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
  const bool scatter_case = command.starts_with("EXEC-scatter-");
  const bool scatter_cross = command == "EXEC-scatter-cross";
  if(scatter_case)for(unsigned k=0;;k++){
   std::string key="execfair-dispatch:"+std::to_string(k);Slice s(key.data(),key.size());
   if(key!=keys[0]&&server.router().shard_of(FlatStore::hash_key(s))==0){keys.push_back(key);break;}
  }
  const std::string value = (command == "INCR" || command.starts_with("EXEC") || (command.starts_with("EVAL") || command.starts_with("FCALL"))) ? "0" : std::string(64,'v');
  for(const auto& key:keys){
   Op op;op.reset();need(op.push_arg(Slice("SET")));need(op.push_arg({key.data(),uint32_t(key.size())}));need(op.push_arg({value.data(),uint32_t(value.size())}));
   op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));op.spec->handler(server.shard(server.router().shard_of(op.hash)),op);
   need(std::string(op.reply.data(),op.reply.size())=="+OK\r\n");
  }
  if(command.find("-single")!=std::string::npos) {
   for(unsigned k=0;;++k) {
    const std::string key="wave10-script-same:"+std::to_string(k);
    if(server.router().shard_of(FlatStore::hash_key(Slice(key)))!=0) continue;
    keys[1]=key;
    Op seed;seed.reset();seed.push_arg(Slice("SET"));seed.push_arg(Slice(keys[1]));seed.push_arg(Slice("0"));
    seed.spec=command_lookup(seed.arg(0));seed.hash=FlatStore::hash_key(seed.arg(1));
    seed.spec->handler(server.shard(0),seed);need(std::string(seed.reply.data(),seed.reply.size())=="+OK\r\n");
    break;
   }
  }
  const bool depth_case = command.starts_with("EXEC-depth-");
  const unsigned depth = depth_case ? std::stoul(command.substr(11)) : 0;
  if(depth_case){
   need(depth==0||depth==16||depth==64);
   auto& store=server.shard(0).store();
   const Slice key(keys[0].data(),keys[0].size());
   const auto hash=FlatStore::hash_key(key);
   need(store.atomic_pending_entries()==0);
   for(unsigned i=0;i<depth;++i){
    void* entry=nullptr;KvObj* object=kvobj_new_int(key,0);need(object);
    need(store.atomic_admit(key,object));
    need(store.atomic_prepare_plain(key,hash,0,entry));
    const auto ticket=server.atomic_commit_reserve();
    store.atomic_install_plain(hash,key,entry,object,ticket);
    server.atomic_commit_publish();store.atomic_clear_read_epoch();
   }
   need(store.atomic_pending_entries()==depth);
  }
  if((command.starts_with("EVAL") || command.starts_with("FCALL"))) {
   need(n==1); ScatterArenaPool pool; Ring ring;
   const bool header=command.ends_with("-header");
   const std::string body=header
       ? "return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}"
       : "return {redis.call('INCR',KEYS[1]),redis.call('INCR',KEYS[2])}";
   const std::string code=(header?"#!lua flags=no-writes\n":"")+body;
   std::string verb="EVAL",target=code;
   if(command.starts_with("EVALSHA")) {
    Op load;load.reset();load.push_arg(Slice("SCRIPT"));load.push_arg(Slice("LOAD"));load.push_arg(Slice(code));
    load.spec=command_lookup(load.arg(0));load.spec->handler(server.shard(0),load);
    need(load.reply.size()==47 && std::string(load.reply.data(),5)=="$40\r\n");
    verb="EVALSHA";target.assign(load.reply.data()+5,40);
   } else if(command.starts_with("FCALL")) {
    // FUNCTION always requires a shebang. The header leg changes only EVAL's
    // header; FCALL uses the corresponding allow-oom registration flag.
    const std::string library="#!lua name=scope\nredis.register_function{function_name='scope_fn',callback=function(KEYS,ARGV) "+body+
        " end"+(header?",flags={'no-writes'}":"")+"}";
    Op load;load.reset();load.push_arg(Slice("FUNCTION"));load.push_arg(Slice("LOAD"));load.push_arg(Slice(library));
    load.spec=command_lookup(load.arg(0));load.spec->handler(server.shard(0),load);
    need(std::string(load.reply.data(),load.reply.size())=="$5\r\nscope\r\n");
    verb="FCALL";target="scope_fn";
   }
   const std::vector<std::string> args{verb,target,"2",keys[0],keys[1]};
   for(unsigned activation=0;activation<2;++activation) {
    const auto id=client.rob().dispatch_id();auto* op=client.rob().template acquire<false>();need(op);
    for(const auto& arg:args)need(op->push_arg(Slice(arg)));
    op->spec=command_lookup(op->arg(0));op->state.store(OpState::Issued);
    // Match the ordinary command scopes: pre-parsed key/hash are fixture setup.
    // Keep the fixture's private hash clone outside the production census.
    if(command.find("-single")!=std::string::npos) { op->hash=FlatStore::hash_key(op->arg(3));op->shard=0; }
    if(activation)scope_begin();
    ScatterDispatch dispatch;
    const auto prepared=xshard_prepare(server,*op,pool,io,client.id(),dispatch,false,&client);
    if(command.find("-single")!=std::string::npos) {
     need(prepared==ScatterPrepare::NotScatter);
     need(command_prepare_script_route(server,*op));
     client.rob().publish();const Task task{&client,id,-1,nullptr};
     const auto owner=server.worker_of_shard(0);
     if constexpr(Fused)production_fused(&loops[owner],&task,1);
     else production_split(&loops[owner],&task,1);
    } else {
     need(prepared==ScatterPrepare::Ready && dispatch.nshards==2);
     op->attach_scatter_state(dispatch.state);client.atomic_group_started();client.rob().publish();
     bool final=false;
     auto execute=[&](const Task& task) {
      auto& shard=server.shard(task.shard);const auto owner=server.worker_of_shard(task.shard);
      need(!xshard_task_should_defer(server,shard,task,*op));
      need(xshard_execute(task,shard,*op,owner)==ScatterTaskResult::Complete);
      const auto done=Fused?xshard_complete_iofused(server,server.thread(owner),ring,task,*op)
                           :xshard_complete(server,server.thread(owner),ring,task,*op);
      need(done==ScatterFinish::Waiting||done==ScatterFinish::Final);
      if(done==ScatterFinish::Final){need(!final);final=true;}
     };
     std::vector<Task> initial;
     for(unsigned k=0;k<dispatch.nshards;++k)initial.push_back(Task{&client,id,xshard_dispatch_shard(dispatch,k),dispatch.state});
     for(const auto& task:initial)execute(task);
     for(unsigned pass=0;!final&&pass<64;++pass)
      for(unsigned tid=0;tid<8;++tid)server.thread(tid).drain_tasks(execute);
     need(final);op->state.store(OpState::Done);
     xshard_retire(server,server.thread(io),ring,client,*op,pool,io,nullptr,nullptr,nullptr);
    }
    if(activation)scope_end();
    const auto expected=header ? std::string("*2\r\n$1\r\n0\r\n$1\r\n0\r\n") : "*2\r\n:"+std::to_string(activation+1)+"\r\n:"+std::to_string(activation+1)+"\r\n";
    need(std::string(op->reply.data(),op->reply.size())==expected);
    need(client.rob().drain([](Op&){})==1);
    for(unsigned sid=0;sid<server.nshards();++sid)server.shard(sid).store().atomic_shutdown_release_records();
    pool.reap_deferred();
   }
  }else if(command=="READLOCAL-GET"){

   if constexpr(Fused){
    need(n<=32&&server.read_local_enabled());
    IoLoop reader;reader.srv_=&server;reader.self_=&server.thread(io);
    reader.fused_executor_=&loops[io];reader.refresh_notify_config();
    const std::string frame="*2\r\n$3\r\nGET\r\n$"+std::to_string(keys[0].size())+"\r\n"+keys[0]+"\r\n";
    std::string wire;for(unsigned i=0;i<n;i++)wire+=frame;
    need(wire.size()<=client.rcap());std::memcpy(client.rbuf(),wire.data(),wire.size());client.commit_read(wire.size());
    const auto hits=server.thread(io).read_local_stats().hits;
    scope_begin();
    production_local_parse(&reader,&client);
    need(production_local_drain(&loops[io],UINT32_MAX)==n);
    scope_end();
    need(client.rpos()==wire.size()&&server.thread(io).read_local_stats().hits==hits+n);
    const std::string expected="$64\r\n"+value+"\r\n";
    need(client.rob().drain([&](Op& op){
     std::string actual;if(op.direct_len)actual.assign(op.direct,op.direct_len);
     actual.append(op.reply.data(),op.reply.size());need(actual==expected);
    })==n);
    need(!loops[io].read_local_impl().lane_count&&!client.rob().has_pending_read_local());
   }else need(false);
  }else if(command.starts_with("EXEC")){
   std::string error; need(acl_initialize(server,cfg,error));
   std::vector<MultiExecState*> deferred;
   auto* carrier=client.rob().template acquire<false>();need(carrier);
   need(carrier->push_arg(Slice("EXEC")));carrier->spec=command_lookup(carrier->arg(0));
   auto local=[&](const char* verb,const std::string* key){
    Op op;op.reset();need(op.push_arg(Slice(verb,std::strlen(verb))));
    if(key)need(op.push_arg({key->data(),uint32_t(key->size())}));
    op.spec=command_lookup(op.arg(0));MultiExecState* unused=nullptr;
    need(multi_handle_io(server,client,op,io,unused)==MultiIoAction::LocalDone);
    need(std::string(op.reply.data(),op.reply.size())==(key?"+QUEUED\r\n":"+OK\r\n"));
   };
   scope_begin();
   local("MULTI",nullptr);
   for(unsigned i=0;i<n;i++){
    if(!scatter_case){local("INCR",&keys[command=="EXEC-cross"?i:0]);continue;}
    Op op;op.reset();need(op.push_arg(Slice("MSET")));
    const std::string next=std::to_string(i+1);
    for(unsigned index:{0u,scatter_cross?1u:8u}){
     need(op.push_arg({keys[index].data(),uint32_t(keys[index].size())}));
     need(op.push_arg({next.data(),uint32_t(next.size())}));
    }
    op.spec=command_lookup(op.arg(0));MultiExecState* unused=nullptr;
    need(multi_handle_io(server,client,op,io,unused)==MultiIoAction::LocalDone);
    need(std::string(op.reply.data(),op.reply.size())=="+QUEUED\r\n");
   }
   MultiExecState* state=nullptr;
   need(multi_handle_io(server,client,*carrier,io,state)==MultiIoAction::Dispatch&&state);
   carrier->attach_multi_state(state);client.atomic_group_started();multi_dispatch_started(client,state);
   std::vector<int32_t> remaining;
   for(unsigned i=0;i<multi_dispatch_count(state);i++)remaining.push_back(multi_dispatch_shard(state,i));
   if(scatter_case){
    need(remaining.size()==(scatter_cross?2u:1u));
    if(scatter_cross)need(server.worker_of_shard(remaining[0])!=server.worker_of_shard(remaining[1]));
   }
   for(unsigned pass=0;!remaining.empty()&&pass<128;pass++){
    for(size_t i=0;i<remaining.size();){
     const auto sid=remaining[i];const auto owner=server.worker_of_shard(sid);
     const auto result=multi_execute_task(server,multi_make_task(&client,0,sid,state),server.shard(sid),owner,0,nullptr);
     if(multi_task_retry(result))i++;else remaining.erase(remaining.begin()+i);
    }
   }
   need(remaining.empty());
#ifdef TOMO_LATENCY_SCAN_WITNESS
   // The real latency_multi_retire wrapper retires the carrier before its children.
   if(wave8b_tracking)latency_tracking_retire(io,*carrier);
#endif
   multi_retire(client,*carrier,deferred);
   // Logical retirement can defer destruction until owner records are reclaimed.
   // Include that production cleanup so the forget hook cannot escape the trace.
   if(depth_case) scope_end(); // Old history cleanup is not the measured EXEC.
   for(unsigned sid=0;sid<server.nshards();sid++)xshard_cleanup_shard_at(server.shard(sid),UINT64_MAX,UINT64_MAX,UINT32_MAX);
   multi_reap_deferred(deferred);need(deferred.empty());
   if(!depth_case) scope_end();
   std::string expected="*"+std::to_string(n)+"\r\n";
   for(unsigned i=0;i<n;i++)expected+=scatter_case?"+OK\r\n":":"+std::to_string(command=="EXEC-cross"?1:i+1)+"\r\n";
   need(std::string(carrier->reply.data(),carrier->reply.size())==expected);
   if(scatter_case)for(unsigned index:{0u,scatter_cross?1u:8u}){
    Op op;op.reset();need(op.push_arg(Slice("GET")));
    need(op.push_arg({keys[index].data(),uint32_t(keys[index].size())}));
    op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));
    op.spec->handler(server.shard(server.router().shard_of(op.hash)),op);
    need(std::string(op.reply.data(),op.reply.size())=="$1\r\n"+std::to_string(n)+"\r\n");
   }
#ifdef TOMO_LATENCY_SCAN_WITNESS
   need(wave8b_tracking ? wave8b_scans > 0 : wave8b_scans == 0);
   uint64_t samples = 0;
   for(const auto& row:collect())samples += row.second.calls;
   need(samples == (wave8b_tracking ? n + 1 : 0));
   std::printf("PASS wave8b mode=%s ns=%s atomic=%d children=%u tracking=%d slots=%llu samples=%llu\n",
       Fused?"1s":"2s",TOMO_SINGLE_DATABASE?"db0":"normal",int(atomic),n,int(wave8b_tracking),
       (unsigned long long)wave8b_scans,(unsigned long long)samples);
#endif
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
  if constexpr(Fused) if(cfg.read_local){
   for(unsigned tid=0;tid<8;tid++){
    loops[tid].read_local_impl().deferred.drain_shutdown();
    for(Shard* sh:server.thread(tid).shards())sh->store().configure_read_local(false,{});
   }
  }
  command_bind_server(nullptr);
  std::puts("PASS bounded production command scope");
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
