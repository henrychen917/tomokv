// Serverless disassembly-path fixture: the linked production objects execute
// directly. No worker, listener, load generator, timing or rate instrument.
#include "src/core/server.h"
#include "src/net/conn.h"
#include "src/core/thread.h"
#include "src/cmd/command.h"
#include "src/cmd/xshard.h"
#include "src/net/uring.h"
#include <cstdio>
#include <string>
#include <vector>
using namespace tomo;
[[gnu::noinline]] void scatter_trace_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scatter_trace_end() { asm volatile("" ::: "memory"); }
static void require(bool value) { if (!value) std::abort(); }
int main(int argc, char** argv) {
    require(argc == 3);
    const bool fused = std::string(argv[2]) == "1s";
    const std::string command = argv[1];
    require(command_registry_init(false));
    Config cfg;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = 0; cfg.flip_auto = 0; cfg.atomic = 0;
    if (fused) { cfg.thread_mode = ThreadMode::Fused; cfg.even_ifid = cfg.even_ex = 0; }
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg));
    command_bind_server(&server);
    std::vector<std::string> args{"MGET"};
    for (uint32_t owner = 0; owner < 3; ++owner) {
        for (unsigned i = 0; i < 100000; ++i) {
            std::string key = "scatter-disassembly:" + std::to_string(i);
            const auto shard = server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size())));
            if (shard == owner) {
                args.push_back(key); break;
            }
        }
    }
    require(args.size() == 4);
    require(server.worker_of_shard(0) != server.worker_of_shard(1));
    const std::string a=args[1], b=args[2], c=args[3];
    if (command == "MSET" || command == "MSETNX") args={command,a,"v",b,"v"};
    else if (command == "SMOVE") args={command,a,b,"v"};
    else if (command == "LMOVE") args={command,a,b,"LEFT","RIGHT"};
    else if (command == "LMPOP") args={command,"2",a,b,"LEFT"};
    else if (command == "ZMPOP") args={command,"2",a,b,"MIN"};
    else if (command == "ZUNION" || command == "ZINTER" || command == "ZDIFF" || command == "ZINTERCARD") args={command,"2",a,b};
    else if (command == "ZUNIONSTORE" || command == "ZINTERSTORE" || command == "ZDIFFSTORE") args={command,c,"2",a,b};
    else if (command == "SINTERCARD") args={command,"2",a,b};
    else if (command == "SINTERSTORE" || command == "SUNIONSTORE" || command == "SDIFFSTORE" || command == "PFMERGE") args={command,c,a,b};
    else if (command == "BITOP") args={command,"AND",c,a,b};
    else if (command == "ZRANGESTORE") args={command,b,a,"0","-1"};
    else if (command == "SORT") args={command,a,"STORE",b};
    else if (command == "SORTDEREF") args={"SORT",a,"BY","w:*","GET","v:*"};
    else if (command == "GEORADIUS") args={command,a,"0","0","1","km","STORE",b};
    else if (command == "GEORADIUSBYMEMBER") args={command,a,"m","1","km","STORE",b};
    else if (command == "GEOSEARCHSTORE") args={command,b,a,"FROMMEMBER","m","BYRADIUS","1","km"};
    else if (command == "XREAD") args={command,"STREAMS",a,b,"0-0","0-0"};
    else if (command == "XREADGROUP") args={command,"GROUP","g","c","STREAMS",a,b,">",">"};
    else if (command == "KEYS") args={command,"*"};
    else if (command == "INFO") args={command,"keyspace"};
    else if (command == "DBSIZE" || command == "RANDOMKEY" || command == "FLUSHDB" || command == "FLUSHALL") args={command};
    else args={command,a,b};
    Client client(-1); client.set_id(777);
    Op op; op.reset();
    for (const auto& arg : args) require(op.push_arg(Slice(arg.data(), arg.size())));
    op.spec = command_lookup(op.arg(0));
    ScatterArenaPool pool;
    ScatterDispatch dispatch;
    Ring ring;
    scatter_trace_begin();
    require(xshard_prepare(server, op, pool, 0, client.id(), dispatch, false, &client) == ScatterPrepare::Ready);
    require(dispatch.nshards >= 1);
    xshard_abandon_unpublished(dispatch.state, pool, 0);
    scatter_trace_end();
    std::puts("PASS linked production ordinary scatter preparation");
}
