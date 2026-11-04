// parkwake: tests/wave14_parser_scope.cc with its eight-CPU topology declared on CPUs 48-55 (this
// lane may use CPUs 32-63 only). CPU ids are placement metadata; the measured parse path is unchanged.
// Finite linked-production owner fixture. No socket, server, EXEC or rate.
// Optional two-owner runs use one Server and disjoint shards/clients on 0/8.
#include "src/core/io_loop.h"
#include "src/cmd/acl.h"
#include <barrier>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <sched.h>
#include <thread>
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
extern "C" int production_fused_parse(void*, Client*)
    asm("_ZN" NSM "6IoLoop18parse_and_dispatchILb0ELj32ELb0EEENS0_14DispatchResultEPNS_6ClientE");
extern "C" int production_split_parse(void*, Client*)
    asm("_ZN" NSM "6IoLoop18parse_and_dispatchILb0ELj0ELb0EEENS0_14DispatchResultEPNS_6ClientE");
extern "C" unsigned production_local_drain(void*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb1EE30drain_local_reads_bounded_implILb0EEEjj");
struct Region { const char* name; const void* address; size_t size; };
Region scope_regions[40]{};
unsigned scope_region_count = 0;
[[gnu::noinline]] void scope_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scope_end() { asm volatile("" ::: "memory"); }
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool v, int line=__builtin_LINE()) {
        if (!v) { std::fprintf(stderr,"fixture failed at %d\n",line); std::abort(); }
    }
    static unsigned env(const char* name, unsigned fallback) {
        const char* value=std::getenv(name); return value ? std::stoul(value) : fallback;
    }
    template<bool Fused> static void run(std::string command,unsigned batch,bool local) {
        const unsigned workers=env("EXECFIFO3_THREADS",1), turns=env("EXECFIFO3_TURNS",1);
        const bool parse=command.starts_with("PARSE-");
        if(parse)command.erase(0,6);
        need(!parse||workers==1);
        need((workers==1||workers==2)&&batch>0&&batch<=32&&turns>0&&turns<=65536);
        need(!local||Fused);
        Server server;
        need(server.topo_.declare("48+49+50+51+52+53+54+55"));
        need(Fused?server.placement_.build_fused(server.topo_,
             "ifid@48,ifid@49,ifid@50,ifid@51,ifid@52,ifid@53,ifid@54,ifid@55")
             :server.placement_.build_even(server.topo_,6,2));
        need(server.placement_.reserve_runtime_roles(8));
        Config cfg;cfg.databases=TOMO_SINGLE_DATABASE?1:16;cfg.shards=16;
        cfg.atomic=1;cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.save.clear();
        cfg.thread_mode=Fused?ThreadMode::Fused:ThreadMode::Split;cfg.read_local=local;
        cfg.slowlog_log_slower_than=-1;cfg.latency_monitor_threshold=0;
        need(server.init(cfg));command_bind_server(&server);
        std::string error;need(acl_initialize(server,cfg,error));
        auto loops=std::make_unique<ExLoopT<Fused>[]>(8);
        auto region=[&](const char* name,const void* address,size_t size) {
            need(scope_region_count<std::size(scope_regions));
            scope_regions[scope_region_count++]={name,address,size};
        };
        region("Server",&server,sizeof(server));
        for(unsigned tid=0;tid<8;++tid) {
            auto& thread=server.thread(tid);
            need(Fused?thread.init_task_inbox_local_fused():thread.init_task_inbox_local(
                server.placement().ifid_threads(),server.placement().ex_threads()));
            auto& loop=loops[tid];loop.srv_=&server;loop.self_=&thread;loop.cached_now_ms_=1000;
            server.bind_owner_notify_pending(tid,&loop.notify_keyless_pending_);
            if constexpr(Fused) if(local) {
                loop.read_local_.impl=std::make_unique<ReadLocalExImpl>();
                loop.read_local_.impl->lane=std::make_unique<ReadLocalExImpl::LaneEntry[]>(kInboxSlots);
                loop.read_local_.impl->lane_fallbacks=std::make_unique<ReadLocalFallbackReason[]>(kInboxSlots);
                need(loop.read_local_.impl->deferred.init(&server,&thread));
                thread.bind_read_local_retire_sink(*loop.read_local_.impl->deferred.sink());
                for(Shard* shard:thread.shards())
                    shard->store().configure_read_local(true,*loop.read_local_.impl->deferred.sink());
            }
            loop.refresh_live_config();
        }
        const unsigned io=Fused?7:0;
        IoLoop reader;reader.srv_=&server;reader.self_=&server.thread(io);
        if constexpr(Fused)reader.fused_executor_=&loops[io];
        reader.refresh_notify_config();
        if constexpr(Fused) if(parse&&local&&command=="GET") {
            server.thread(io).publish_read_local_tick(server.read_local_epoch());
            server.thread(io).set_read_local_lane_active(true);
            loops[io].bind_fused_completion(nullptr,[](void*,Client*){});
        }
        region("IoLoop",&reader,sizeof(reader));
        region("IoThread",&server.thread(io),sizeof(ThreadCtx));
        std::unique_ptr<Client> clients[2];std::string keys[2];int32_t shards[2]{};
        const std::string value=command=="INCR"?"0":std::string(64,'v');
        for(unsigned w=0;w<workers;++w) {
            const unsigned owner=Fused?w:6+w;
            shards[w]=server.thread(owner).shards().front()->id();
            for(unsigned k=0;;++k) {
                keys[w]="execfifo3:"+std::to_string(k);Slice key(keys[w].data(),keys[w].size());
                if(server.router().shard_of(FlatStore::hash_key(key))==shards[w])break;
            }
            auto& c=clients[w]=std::make_unique<Client>(-1);
            c->set_id(99101+w);c->set_ifid_thread(io);
            c->set_wb_slot(server.thread(io).assign_wb_slot(c.get()));
            if(parse)command_client_connected(c.get(),"127.0.0.1:20699","127.0.0.1:20600",false,1000);
            auto& shard=server.shard(shards[w]);need(!shard.has_watches());
            need(shard.store().read_local_enabled()==local);
            region(w?"Shard1":"Shard0",&shard,sizeof(shard));
            region(w?"Owner1":"Owner0",&loops[owner],sizeof(loops[owner]));
            region(w?"Thread1":"Thread0",&server.thread(owner),sizeof(ThreadCtx));
            region(w?"Client1":"Client0",c.get(),sizeof(Client));
            Op op;op.reset();need(op.push_arg(Slice("SET")));
            need(op.push_arg(Slice(keys[w].data(),keys[w].size())));
            need(op.push_arg(Slice(value.data(),value.size())));
            op.spec=command_lookup(op.arg(0));op.hash=FlatStore::hash_key(op.arg(1));
            op.spec->handler(shard,op);need(std::string(op.reply.data(),op.reply.size())=="+OK\r\n");
        }
        std::barrier start(workers);
        auto work=[&](unsigned w) {
            cpu_set_t mask;CPU_ZERO(&mask);CPU_SET(w?56:48,&mask);
            need(sched_setaffinity(0,sizeof(mask),&mask)==0);
            auto& client=*clients[w];auto& shard=server.shard(shards[w]);
            auto& loop=loops[server.worker_of_shard(shards[w])];
            uint64_t completed=0;start.arrive_and_wait();
            for(unsigned turn=0;turn<turns;++turn) {
                Task tasks[32];
                if(parse) {
                    std::string frame="*"+std::to_string(command=="SET"||command=="MSET"?3:2)+"\r\n";
                    for(const auto& arg:std::vector<std::string>{command,keys[w]})
                        frame+="$"+std::to_string(arg.size())+"\r\n"+arg+"\r\n";
                    if(command=="SET"||command=="MSET")frame+="$"+std::to_string(value.size())+"\r\n"+value+"\r\n";
                    std::string wire;for(unsigned i=0;i<batch;++i)wire+=frame;
                    client.reset_rbuf_at_quiescence();size_t available=0;
                    need(client.read_space_impl<false>(wire.size(),available,true,1u<<20,0));
                    need(available>=wire.size());std::memcpy(client.rbuf(),wire.data(),wire.size());
                    client.commit_read(wire.size());
                    scope_begin();
                    if constexpr(Fused)production_fused_parse(&reader,&client);
                    else production_split_parse(&reader,&client);
                    scope_end();
                    need(client.rpos()==wire.size());unsigned count=0;
                    server.thread(server.worker_of_shard(shards[w])).drain_tasks_unmasked([&](const Task& task) {
                        need(count<batch);tasks[count++]=task;
                    });
                    if constexpr(Fused) {
                        if(local&&command=="GET") {
                            need(count==0);need(production_local_drain(&loops[io],batch)==batch);
                        } else need(count==batch);
                    } else need(count==batch);
                } else for(unsigned i=0;i<batch;++i) {
                    auto* op=client.rob().template acquire<false>();need(op);
                    need(op->push_arg(Slice(command.data(),command.size())));
                    need(op->push_arg(Slice(keys[w].data(),keys[w].size())));
                    if(command=="SET"||command=="MSET")need(op->push_arg(Slice(value.data(),value.size())));
                    op->spec=command_lookup(op->arg(0));need(op->spec);
                    op->hash=FlatStore::hash_key(op->arg(1));op->shard=shards[w];
                    op->state.store(OpState::Issued,std::memory_order_relaxed);
                    tasks[i]={&client,client.rob().dispatch_id(),-1,nullptr};client.rob().publish();
                }
                // In a traced run there is exactly one turn and one owner.
                if(!parse)scope_begin();
                if constexpr(Fused) {
                    if(!(parse&&local&&command=="GET"))production_fused(&loop,tasks,batch);
                } else production_split(&loop,tasks,batch);
                if(!parse)scope_end();
                need(client.rob().drain([&](Op& op) {
                    const std::string want=command=="INCR"?":"+std::to_string(++completed)+"\r\n"
                        :(command=="SET"||command=="MSET")?"+OK\r\n"
                        :(command=="MGET"?"*1\r\n":"")+std::string("$64\r\n")+value+"\r\n";
                    std::string reply;if(op.direct_len)reply.assign(op.direct,op.direct_len);
                    reply.append(op.reply.data(),op.reply.size());
                    if(op.reply_code_) { char buf[64];reply.append(buf,format_reply_code(buf,op.reply_code_,op.reply_ival_)); }
                    need(reply==want);
                })==batch);
                need(!shard.has_watches());
                if constexpr(Fused) if(local) loop.read_local_.impl->deferred.drain_shutdown();
            }
        };
        if(workers==1)work(0);
        else { std::thread second(work,1);work(0);second.join(); }
        for(unsigned w=0;w<workers;++w)server.thread(io).release_wb_slot(clients[w]->wb_slot());
        command_bind_server(nullptr);
        std::printf("PASS finite %s owners=%u turns=%u batch=%u read_local=%d\n",
                    command.c_str(),workers,turns,batch,local);
    }
};
}
int main(int argc,char** argv) {
    if(argc!=6||!command_registry_init(false))return 2;
    if(std::string(argv[2])=="1s")CoreConcurrencyTest::run<true>(argv[1],std::stoul(argv[3]),std::stoi(argv[5])==1);
    else CoreConcurrencyTest::run<false>(argv[1],std::stoul(argv[3]),false);
}
