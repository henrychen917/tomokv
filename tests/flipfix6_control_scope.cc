// flipfix6: bounded serverless instruction fixture for the FLIP control passes themselves.
// Production ExLoopT<false>/IoLoop control-pass bodies are called through their linked symbols on
// the gate's state-only 6:2 fixture; no listener, worker thread, rate or repeated workload.
// argv[1] selects one stage state; scope_begin/scope_end bracket exactly one control pass.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <string>
#include <sched.h>
using namespace tomo;
#if TOMO_SINGLE_DATABASE
#define NSM "8tomo_db0"
#else
#define NSM "4tomo"
#endif
extern "C" uint32_t production_ex_flip(void*) asm("_ZN" NSM "7ExLoopTILb0EE17flip_control_passEv");
extern "C" uint32_t production_io_flip(void*) asm("_ZN" NSM "6IoLoop17flip_control_passILb0EEEjv");
[[gnu::noinline]] void scope_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void scope_end(){asm volatile("" ::: "memory");}
namespace tomo {
struct CoreConcurrencyTest {
 static void need(bool v, const char* what){if(!v){std::fprintf(stderr,"fixture: %s\n",what);std::abort();}}
 static int run(const std::string& cell){
  Server server;
  cpu_set_t mask;CPU_ZERO(&mask);need(sched_getaffinity(0,sizeof(mask),&mask)==0,"affinity");
  std::string domain;unsigned count=0;
  for(int cpu=0;cpu<CPU_SETSIZE&&count<8;cpu++)if(CPU_ISSET(cpu,&mask)){
   if(count++)domain+='+';domain+=std::to_string(cpu);
  }
  need(count==8&&server.topo_.declare(domain.c_str()),"eight CPUs");
  need(server.placement_.build_even(server.topo_,6,2),"6:2 placement");
  need(server.placement_.reserve_runtime_roles(8),"roles");
  Config cfg;cfg.databases=TOMO_SINGLE_DATABASE?1:16;cfg.shards=16;cfg.atomic=1;
  cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.thread_mode=ThreadMode::Split;cfg.read_local=0;cfg.save.clear();
  need(server.init(cfg),"init");command_bind_server(&server);
  auto loops=std::make_unique<ExLoopT<false>[]>(8);
  for(unsigned tid=0;tid<8;tid++){
   auto& thread=server.thread(tid);
   need(thread.init_task_inbox_local(server.placement().ifid_threads(),server.placement().ex_threads()),"inbox");
   auto& loop=loops[tid];loop.srv_=&server;loop.self_=&thread;loop.cached_now_ms_=1000;
   server.bind_owner_notify_pending(tid,&loop.notify_keyless_pending_);loop.refresh_live_config();
  }
  const uint32_t ex=server.placement().ex_threads().front();
  uint32_t io_tid=server.placement().ifid_threads().back();  // a non-coordinator IO
  IoLoop io;io.srv_=&server;io.self_=&server.thread(io_tid);
  const bool io_cell=cell.rfind("io-",0)==0;
  FlipStage stage=FlipStage::Idle;bool acked=false;
  const bool prepare_cell=cell=="io-clientprepare-empty"||cell=="io-clientprepare-session";
  Client client(-1);std::string error;
  std::unique_ptr<IoLoop[]> targets;
  if(prepare_cell){
   need(server.flip_begin(5,3,0,error),"begin real FLIP");
   for(unsigned tid=1;tid<6;tid++)if(server.flip_candidate_target(tid)==Role::Ex)io_tid=tid;
   io.self_=&server.thread(io_tid);
   client.set_id(42);client.set_ifid_thread(io_tid);
   client.set_wb_slot(server.thread(io_tid).assign_wb_slot(&client));
   server.thread(io_tid).add_client(&client);server.client_accepted();
   command_client_connected(&client,"127.0.0.1:1","127.0.0.1:2",false,1);
   command_client_directory_add(&client,io_tid);
   if(cell=="io-clientprepare-session"){
    for(const char* verb:{"MULTI","DISCARD"}){
     Op op;op.reset();need(op.push_arg(Slice(verb,uint32_t(std::strlen(verb)))),"session arg");
     op.spec=command_lookup(op.arg(0));MultiExecState* pending=nullptr;
     need(multi_handle_io(server,client,op,io_tid,pending)==MultiIoAction::LocalDone,"session setup");
    }
   }
   for(auto tid:server.placement().ifid_threads())server.flip_ack(tid,FlipStage::IoDrain);
   need(server.flip_build_client_plan(nullptr,error),"plan one actual connection transfer");
   need(server.flip_source_clients(io_tid)==1,"source planned");
   if(cell=="io-clientprepare-session"){
    std::string refused;
    need(!io.client_transfer_ready(&client,server.flip_client_destination(io_tid,0),refused),"LB still refuses session");
    need(refused=="connection ROB, reply, borrow, or owner-local protocol state is busy","LB session clause");
    std::puts("PASS LB session connection declined");
   }
   targets=std::make_unique<IoLoop[]>(8);
   for(auto tid:server.placement().ifid_threads()){
    targets[tid].srv_=&server;targets[tid].self_=&server.thread(tid);
    need(targets[tid].prepare_client_transfer_capacity(server.flip_incoming_clients(tid)),"target capacity");
   }
  }
  if(prepare_cell){stage=FlipStage::ClientPrepare;}
  else if(cell=="ex-idle"||cell=="io-idle"){}
  else if(cell=="ex-exinstall-owed"){stage=FlipStage::ExInstall;}
  else if(cell=="ex-exinstall-acked"){stage=FlipStage::ExInstall;acked=true;}
  else if(cell=="ex-exdrain-owed"){stage=FlipStage::ExDrain;}
  else if(cell=="ex-exdrain-acked"){stage=FlipStage::ExDrain;acked=true;}
  else if(cell=="io-iodrain-owed"){stage=FlipStage::IoDrain;}
  else if(cell=="io-iodrain-acked"){stage=FlipStage::IoDrain;acked=true;}
  else if(cell=="io-roleready-owed"){stage=FlipStage::RoleReady;}
  else if(cell=="io-roleready-acked"){stage=FlipStage::RoleReady;acked=true;}
  else return 2;
  if(stage!=FlipStage::Idle){
   server.flip_epoch_.store(1,std::memory_order_release);
   server.flip_stage_.store(stage,std::memory_order_release);
  }
  io.flip_stage_snapshot_=stage;  // what flip_pass_begin() latched for this IO pass
  const uint32_t tid=io_cell?io_tid:ex;
  auto pass=[&]{return io_cell?production_io_flip(&io):production_ex_flip(&loops[ex]);};
  if(acked){(void)pass();need(server.flip_acked(tid,stage),"unscoped acknowledgement");}
  scope_begin();
  const uint32_t work=pass();
  scope_end();
  if(stage==FlipStage::Idle)need(work==0,"idle pass reports no work");
  else if(prepare_cell){
   // PRE session readiness refuses; POST carries it. Record either branch, but
   // an empty-session-free connection must be prepared on both arms.
   if(cell=="io-clientprepare-empty")need(server.flip_acked(tid,stage),"empty ClientPrepare acknowledged");
   std::printf("ClientPrepare acknowledged=%u migrations=%zu\n",server.flip_acked(tid,stage),io.client_migrations_.size());
   client.mark_closing(); // no socket/ring to re-arm during fixture teardown
   io.cancel_prepared_client_transfers_impl<false>();
   command_client_disconnected(&client);
   server.thread(io_tid).remove_client(&client);server.client_released();
  }else need(server.flip_acked(tid,stage),"stage acknowledged after the pass");
  if(io_cell&&stage!=FlipStage::Idle){server.flip_stage_.store(FlipStage::Idle,std::memory_order_release);io.flip_stage_snapshot_=FlipStage::Idle;}
  server.flip_stage_.store(FlipStage::Idle,std::memory_order_release);
  command_bind_server(nullptr);
  std::printf("PASS flipfix6 control scope %s work=%u\n",cell.c_str(),work);
  return 0;
 }
};
}
int main(int argc,char**argv){
 if(argc<2)return 2;
 if(!command_registry_init(false))return 3;
 return CoreConcurrencyTest::run(argv[1]);
}
