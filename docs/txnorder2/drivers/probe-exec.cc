// One bounded EXEC through linked production objects; no worker/listener/rate.
#include "src/core/server.h"
#include "src/net/conn.h"
#include "src/core/thread.h"
#include "src/cmd/command.h"
#include "src/cmd/multi.h"
#include "src/cmd/xshard.h"
#include "src/cmd/acl.h"
#include <cstdio>
#include <string>
#include <vector>
using namespace tomo;
[[gnu::noinline]] void scatter_trace_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void scatter_trace_end(){asm volatile("" ::: "memory");}
static void require(bool v){if(!v)std::abort();}
static Slice slice(const std::string& s){return {s.data(),static_cast<uint32_t>(s.size())};}
static void args(Op& op,const std::vector<std::string>& a){op.reset();for(auto& s:a)require(op.push_arg(slice(s)));op.spec=command_lookup(op.arg(0));}
int main(int argc,char** argv){
 require(argc==3);const bool cross=std::string(argv[1])=="cross";
 const bool fused=std::string(argv[2])=="1s";
 require(command_registry_init(false));Config cfg;cfg.databases=1;
 cfg.shards=16;cfg.even_ifid=6;cfg.even_ex=2;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.atomic=1;
 cfg.thread_mode=fused?ThreadMode::Fused:ThreadMode::Split;
 cfg.read_local=fused;Server server;require(server.prepare_boot(cfg)&&server.init(cfg));
 command_bind_server(&server);std::string error;require(acl_initialize(server,cfg,error));
 std::vector<std::string> keys;
 for(unsigned sid:{0u,cross?1u:0u})for(unsigned i=keys.size();i<100000;++i){
  auto key="exec-count:"+std::to_string(i);
  if(server.router().shard_of(FlatStore::hash_key(slice(key)))==sid && (keys.empty() || key!=keys[0])){keys.push_back(key);break;}}
 require(keys.size()==2);Client client(-1);client.set_id(777);
 for(auto& key:keys){Op seed;args(seed,{"SET",key,"0"});seed.hash=FlatStore::hash_key(seed.arg(1));seed.spec->handler(server.shard(server.router().shard_of(seed.hash)),seed);}
 for(auto a:std::vector<std::vector<std::string>>{{"MULTI"},{"INCR",keys[0]},{"INCR",keys[1]}}){
  Op op;args(op,a);MultiExecState* unused=nullptr;require(multi_handle_io(server,client,op,0,unused)==MultiIoAction::LocalDone);}
 Op* op=client.rob().acquire();require(op);args(*op,{"EXEC"});MultiExecState* state=nullptr;
 std::vector<MultiExecState*> deferred;
 scatter_trace_begin();
 require(multi_handle_io(server,client,*op,0,state)==MultiIoAction::Dispatch&&state);
 op->attach_multi_state(state);multi_dispatch_started(client,state);client.atomic_group_started();
 auto count=multi_dispatch_count(state);std::vector<bool> done(count,false);bool final=false;
 for(unsigned round=0;round<64&&!final;++round)for(unsigned i=0;i<count;++i){
  if(done[i])continue;auto sid=multi_dispatch_shard(state,i);auto owner=server.worker_of_shard(sid);
  auto result=multi_execute_task(server,multi_make_task(&client,0,sid,state),server.shard(sid),owner,0,nullptr);
  done[i]=result!=MultiTaskResult::Retry;final|=result==MultiTaskResult::Final;
 }
 require(final);multi_retire(client,*op,deferred);
 scatter_trace_end();
 require(std::string(op->reply.data(),op->reply.size())=="*2\r\n:1\r\n:1\r\n");
 std::puts("PASS linked production EXEC: two INCRs, exact reply, bounded owner turns");
 // Live private record references are intentionally left to process exit; no
 // production object is modified to make the fixture a cleanup benchmark.
 std::fflush(stdout);std::_Exit(0);
}
