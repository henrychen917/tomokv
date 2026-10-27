// Three actual fused-loop rotations, with no listener, connection or worker.
// The GDB driver stops the loop at iteration three and counts only [2,3).
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <sched.h>
#include <unistd.h>
using namespace tomo;
uint64_t* scope_iterations=nullptr;
std::atomic<bool>* scope_stop=nullptr;
[[gnu::noinline]] void scope_begin(){asm volatile("" ::: "memory");}
[[gnu::noinline]] void scope_end(){asm volatile("" ::: "memory");}
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool v){if(!v)std::abort();}
    static void run(){
        Server server;cpu_set_t mask;CPU_ZERO(&mask);need(sched_getaffinity(0,sizeof(mask),&mask)==0);
        std::string domain,place;unsigned count=0;
        for(int cpu=0;cpu<CPU_SETSIZE && count<8;++cpu)if(CPU_ISSET(cpu,&mask)){
            if(count++){domain+='+';place+=',';}domain+=std::to_string(cpu);place+="ifid@"+std::to_string(cpu);
        }
        need(count==8 && server.topo_.declare(domain.c_str()));
        need(server.placement_.build_fused(server.topo_,place.c_str()));need(server.placement_.reserve_runtime_roles(8));
        Config cfg;cfg.databases=TOMO_SINGLE_DATABASE?1:16;cfg.shards=16;
        cfg.thread_mode=ThreadMode::Fused;cfg.read_local=0;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.save.clear();
        need(server.init(cfg));command_bind_server(&server);
        for(unsigned tid=0;tid<8;++tid)need(server.thread(tid).init_task_inbox_local_fused());
        auto& self=server.thread(0);FusedExLoop owner;IoLoop io;
        need(owner.init(&server,&self,true));need(io.init(&server,&self,"127.0.0.1",20199,-1,nullptr,true));
        owner.activate_fused();io.bind_fused_executor(&owner);self.set_ring(&io.ring_);self.set_wb_engine(&io.wb_);
        need(io.listen_fd_==-1 && self.clients().empty());
        scope_iterations=&self.sig().iterations;scope_stop=&self.stop_flag();
        static_assert(sizeof(std::atomic<bool>)==1);
        scope_begin();io.run_fused();scope_end();
        need(*scope_iterations==3 && self.stop_flag().load() && self.clients().empty());
#if __has_include("src/core/fused_owner_turn.inc")
        need(!fused_owner_bells[0].runnable.load() && exec1s_counters[0].extra_passes==0);
#endif
        io.shutdown_on_issuer();
        std::puts("PASS three idle production rotations; no extra pass or network listener");
    }
};
}
int main(int argc,char** argv){
    if(argc<2 || std::string(argv[1])!="IDLE")return 2;
    alarm(120); // Missing debugger control is a bounded failure, never a spin forever.
    if(!command_registry_init(false))return 1;
    CoreConcurrencyTest::run();
}
