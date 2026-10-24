// AT4.8: bounded, serverless retired-instruction witness. No worker or socket starts.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <cstdio>

using namespace tomo;
static void need(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL %s\n", why); std::exit(1); }
}
struct Counter {
    int fd;
    Counter() {
        perf_event_attr a{}; a.size = sizeof(a); a.type = PERF_TYPE_HARDWARE;
        a.config = PERF_COUNT_HW_INSTRUCTIONS; a.disabled = 1;
        a.exclude_kernel = a.exclude_hv = 1;
        fd = syscall(SYS_perf_event_open, &a, 0, -1, -1, 0);
        need(fd >= 0, "perf_event_open instructions:u");
    }
    ~Counter() { close(fd); }
    template<class F> uint64_t count(F fn) {
        need(ioctl(fd, PERF_EVENT_IOC_RESET, 0) == 0, "reset counter");
        need(ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) == 0, "enable counter");
        fn();
        need(ioctl(fd, PERF_EVENT_IOC_DISABLE, 0) == 0, "disable counter");
        uint64_t n = 0; need(read(fd, &n, sizeof(n)) == sizeof(n), "read counter");
        return n;
    }
};
struct Request {
    Op op;
    std::vector<std::string> args;
    Request(std::vector<std::string> a) : args(std::move(a)) {
        op.reset();
        for (const auto& s : args) need(op.push_arg(Slice(s.data(), s.size())), "arguments");
        op.spec = command_lookup(op.arg(0)); need(op.spec, "command");
        op.hash = FlatStore::hash_key(op.key()); op.shard = 0;
    }
};
int main(int argc, char** argv) {
    const bool check = argc == 2 && std::string(argv[1]) == "--check";
    need(command_registry_init(false), "registry");
    Counter counter;
    double first[3]{};
    std::puts("blocked_keys,LPUSH_instructions,XADD_instructions,BLPOP_registration_instructions");
    for (unsigned n : {1u, 100u, 10000u}) {
        Config cfg; cfg.databases = 1; cfg.shards = 16;
        cfg.even_ifid = 6; cfg.even_ex = 2; cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        Server server;
        need(server.prepare_boot(cfg) && server.init(cfg), "16 shards, split 6:2");
        command_bind_server(&server);
        Shard& shard = server.shard(0); shard.set_cached_now_ms(now_realtime_ms(), 0);
        ThreadCtx self; Ring ring;
        blocking_bind_executor(&server, &self, &ring);
        auto* registry = blocking_registry_get(shard, true);
        uint64_t serial = 0;
        auto key = [&] {
            for (;;) {
                std::string k = "blockfix:" + std::to_string(serial++);
                if (server.router().shard_of(FlatStore::hash_key(Slice(k.data(), k.size()))) == 0)
                    return k;
            }
        };
        auto state = [&] {
            auto* s = new BlockingState; s->server = &server;
            BlockingKey k; k.key = key(); k.hash = FlatStore::hash_key(Slice(k.key.data(), k.key.size()));
            k.shard = 0; s->keys.push_back(std::move(k));
            s->phase.store(BlockingPhase::Parked); return s;
        };
        for (unsigned i = 0; i < n; ++i) {
            auto* s = state(); need(registry->add(shard, *s, 0), "seed waiter");
            blocking_state_release(s);
        }
        constexpr unsigned repeats = 64;
        double counts[3]{};
        for (unsigned kind = 0; kind < 2; ++kind) {
            const std::string target = key();
            std::vector<std::unique_ptr<Request>> commands;
            for (unsigned i = 0; i < repeats; ++i) {
                std::vector<std::string> args = kind == 0
                    ? std::vector<std::string>{"LPUSH", target, "v"}
                    : std::vector<std::string>{"XADD", target, std::to_string(i+1)+"-0", "f", "v"};
                commands.push_back(std::make_unique<Request>(std::move(args)));
            }
            counts[kind] = double(counter.count([&] {
                for (auto& r : commands) r->op.spec->handler(shard, r->op);
            })) / repeats;
            for (auto& r : commands) need(r->op.reply.size() && r->op.reply.data()[0] != '-', "write reply");
        }
        std::vector<BlockingState*> registrations;
        for (unsigned i = 0; i < repeats; ++i) registrations.push_back(state());
        counts[2] = double(counter.count([&] {
            for (auto* s : registrations) need(registry->add(shard, *s, 0), "register waiter");
        })) / repeats;
        for (auto* s : registrations) blocking_state_release(s);
        std::printf("%u,%.2f,%.2f,%.2f\n", n, counts[0], counts[1], counts[2]);
        for (unsigned k = 0; k < 3; ++k) {
            if (n == 1) first[k] = counts[k];
            if (check) need(counts[k] < first[k] * 4, "unrelated blocked keys must not cause linear work");
        }
        blocking_bind_executor(nullptr, nullptr, nullptr);
    }
}
