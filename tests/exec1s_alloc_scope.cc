// Same bounded IO preparation scope can be compiled against PRE or POST.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <cstdio>
thread_local size_t allocated_bytes=0;
thread_local bool count_allocations=false;
__attribute__((noinline)) void* operator new(size_t n) {
    if(count_allocations) allocated_bytes+=n;
    if(void* p=std::malloc(n?n:1)) return p;
    throw std::bad_alloc();
}
void* operator new[](size_t n) { return ::operator new(n); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p,size_t) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete[](void* p,size_t) noexcept { std::free(p); }
void* operator new(size_t n,const std::nothrow_t&) noexcept {
    try{return ::operator new(n);}catch(...){return nullptr;}
}
void* operator new[](size_t n,const std::nothrow_t&) noexcept {return ::operator new(n,std::nothrow);}
void operator delete(void* p,const std::nothrow_t&) noexcept {std::free(p);}
void operator delete[](void* p,const std::nothrow_t&) noexcept {std::free(p);}
using namespace tomo;
static void need(bool p){if(!p)std::abort();}
int main(int argc,char** argv) {
    need(argc==3 && command_registry_init(false));
    Config cfg;cfg.databases=1;cfg.shards=std::atoi(argv[2]);cfg.even_ifid=6;cfg.even_ex=2;
    cfg.thread_mode=std::string(argv[1])=="1s"?ThreadMode::Fused:ThreadMode::Split;
    cfg.key_lb=cfg.client_lb=cfg.flip_auto=0;cfg.save.clear();
    Server server;need(server.prepare_boot(cfg)&&server.init(cfg));need(server.nthreads()==8);command_bind_server(&server);
    std::string acl_error;need(acl_initialize(server,cfg,acl_error));
    Client client(-1);client.set_id(991991);
    std::vector<std::string> keys;
    for(unsigned target:{cfg.shards-1,cfg.shards/2}) for(unsigned i=0;;++i) {
        std::string k="exec1s-alloc:"+std::to_string(i);Slice key(k.data(),k.size());
        if(server.router().shard_of(FlatStore::hash_key(key))==target){keys.push_back(k);break;}
    }
    std::vector<MultiQueuedCommand> queue(2);
    for(unsigned i=0;i<2;++i) {
        Op op;op.reset();need(op.push_arg(Slice("INCR")));need(op.push_arg(Slice(keys[i].data(),keys[i].size())));
        op.spec=command_lookup(op.arg(0));need(queued_copy(op,queue[i]));
    }
    count_allocations=true;
    auto* state=allocate_state(server,client,0,MultiStateKind::Execute);need(state);
    const size_t initial=allocated_bytes;
    need(prepare_commands(server,*state,queue));
    need(state->shards.size()==2 && state->commands.size()==2);
    for(const auto& c:state->commands) need(c->kind==MultiCommandKind::Local);
    count_allocations=false;
    std::printf("{\"mode\":\"%s\",\"shards\":%u,\"threads\":%u,\"participants\":%zu,\"allocate_state_bytes\":%zu,\"prepare_total_bytes\":%zu}\n",
        argv[1],cfg.shards,server.nthreads(),state->shards.size(),initial,allocated_bytes);
    destroy_multi_state(state);
}
