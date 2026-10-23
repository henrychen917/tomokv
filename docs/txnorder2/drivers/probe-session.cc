// Trace only the ordinary-command MULTI-session bypass in production objects.
#include "src/core/server.h"
#include "src/net/conn.h"
#include "src/core/thread.h"
#include "src/cmd/command.h"
#include "src/cmd/multi.h"
#include <cstdio>
#include <string>
#include <vector>
using namespace tomo;
[[gnu::noinline]] void scatter_trace_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void scatter_trace_end(){asm volatile("" ::: "memory");}
static void require(bool x){if(!x)std::abort();}
static void args(Op& op,std::vector<std::string> values){op.reset();for(auto& s:values)require(op.push_arg({s.data(),static_cast<uint32_t>(s.size())}));op.spec=command_lookup(op.arg(0));}
int main(int argc,char** argv){
 require(argc==3);require(command_registry_init(false));Config cfg;cfg.databases=1;cfg.shards=16;
 cfg.even_ifid=6;cfg.even_ex=2;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.atomic=0;
 cfg.thread_mode=std::string(argv[2])=="1s"?ThreadMode::Fused:ThreadMode::Split;
 Server server;require(server.prepare_boot(cfg)&&server.init(cfg));command_bind_server(&server);
 Client client(-1);client.set_id(778);MultiExecState* state=nullptr;
 for(auto name:{"MULTI","DISCARD"}){Op op;args(op,{name});require(multi_handle_io(server,client,op,0,state)==MultiIoAction::LocalDone);}
 require(client.multi_session()&&!multi_session_active(client));
 std::string name=argv[1];std::vector<std::string> values{name,"key"};
 if(name=="SET")values.push_back("v");
 if(name=="MGET")values.push_back("other");
 if(name=="MSET")values.insert(values.end(),{"v","other","v"});
 Op op;args(op,values);scatter_trace_begin();
 auto result=multi_handle_io(server,client,op,0,state);
 scatter_trace_end();require(result==MultiIoAction::NotHandled&&!state);
 std::puts("PASS linked production inactive-session ordinary-command bypass");
}
