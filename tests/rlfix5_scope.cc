// RL5.1/RL5.2: finite schedules and command scopes linked to production objects.
// No listener, test hook, worker, timing loop, or substitute ordering mechanism.
#include "src/core/io_loop.h"
#include "src/cmd/acl.h"
#include <cstdio>
#include <memory>
#include <sched.h>
using namespace tomo;
#if TOMO_SINGLE_DATABASE
#define NSM "8tomo_db0"
#else
#define NSM "4tomo"
#endif
#define PARSER(name, args) extern "C" int name(void*, Client*) \
    asm("_ZN" NSM "6IoLoop18parse_and_dispatchI" args "EEENS0_14DispatchResultEPNS_6ClientE")
PARSER(parse_fused, "Lb0ELj32ELb0");
PARSER(parse_split, "Lb0ELj0ELb0");
PARSER(parse_local_split, "Lb0ELj32ELb1");
extern "C" void exec_split(void*, const Task*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb0EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
extern "C" void exec_fused(void*, const Task*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb1EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
extern "C" unsigned drain_local(void*, unsigned)
    asm("_ZN" NSM "7ExLoopTILb1EE30drain_local_reads_bounded_implILb0EEEjj");
[[gnu::noinline]] void scope_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scope_end() { asm volatile("" ::: "memory"); }

namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool ok, int line = __builtin_LINE()) {
        if (!ok) { std::fprintf(stderr, "FAIL rlfix5 fixture line %d\n", line); std::exit(1); }
    }
    static Slice slice(const std::string& s) { return {s.data(), uint32_t(s.size())}; }
    static std::string wire(std::initializer_list<std::string> args) {
        std::string out = "*" + std::to_string(args.size()) + "\r\n";
        for (const auto& s : args) out += "$" + std::to_string(s.size()) + "\r\n" + s + "\r\n";
        return out;
    }
    struct Fixture {
        Server server;
        std::unique_ptr<FusedExLoop[]> fused = std::make_unique<FusedExLoop[]>(8);
        std::unique_ptr<ExLoop[]> split = std::make_unique<ExLoop[]>(8);
        IoLoop io;
        bool one, local;
        unsigned reader, owner;
        std::string key;
        std::vector<std::unique_ptr<Client>> clients;
        Fixture(bool one_, bool local_, bool tracking) : one(one_), local(local_),
                reader(one ? 7 : 0), owner(one ? 0 : 6) {
            cpu_set_t allowed; CPU_ZERO(&allowed);
            need(sched_getaffinity(0, sizeof(allowed), &allowed) == 0);
            std::string domain; unsigned count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) if (CPU_ISSET(cpu, &allowed)) {
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            need(count == 8 && server.topo_.declare(domain.c_str()));
            need(one ? server.placement_.build_fused(server.topo_, nullptr)
                     : server.placement_.build_even(server.topo_, 6, 2));
            need(server.placement_.reserve_runtime_roles(8));
            Config cfg; cfg.shards = 16; cfg.databases = TOMO_SINGLE_DATABASE ? 1 : 16;
            cfg.atomic = 1; cfg.read_local = local; cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
            cfg.thread_mode = one ? ThreadMode::Fused : ThreadMode::Split;
            cfg.latency_tracking = tracking; cfg.slowlog_log_slower_than = -1;
            cfg.latency_monitor_threshold = 0; cfg.save.clear();
            need(server.init(cfg)); command_bind_server(&server);
            std::string error; need(acl_initialize(server, cfg, error));
            for (unsigned i = 0; i < 8; ++i) {
                auto& thread = server.thread(i);
                need(one ? thread.init_task_inbox_local_fused() : thread.init_task_inbox_local(
                    server.placement().ifid_threads(), server.placement().ex_threads()));
                auto init = [&](auto& loop) {
                    loop.srv_ = &server; loop.self_ = &thread; loop.cached_now_ms_ = 1000;
                    loop.refresh_live_config();
                };
                init(fused[i]); init(split[i]);
                server.bind_owner_notify_pending(i, one || local ? &fused[i].notify_keyless_pending_
                                                                : &split[i].notify_keyless_pending_);
                if (local) {
                    auto& loop = fused[i];
                    loop.read_local_.impl = std::make_unique<ReadLocalExImpl>();
                    auto& lane = loop.read_local_impl();
                    lane.lane = std::make_unique<ReadLocalExImpl::LaneEntry[]>(kInboxSlots);
                    lane.lane_fallbacks = std::make_unique<ReadLocalFallbackReason[]>(kInboxSlots);
                    need(lane.deferred.init(&server, &thread));
                    thread.bind_read_local_retire_sink(*lane.deferred.sink());
                    for (auto* shard : thread.shards())
                        shard->store().configure_read_local(true, *lane.deferred.sink());
                    loop.bind_fused_completion(nullptr, [](void*, Client*) {});
                }
            }
            io.srv_ = &server; io.self_ = &server.thread(reader);
            if (one || local) io.fused_executor_ = &fused[reader];
            io.refresh_notify_config();
            if (local) {
                server.thread(reader).set_read_local_lane_active(true);
                server.thread(reader).publish_read_local_tick(server.read_local_epoch());
                fused[reader].bind_read_local_demotion(&io,
                    [](void* p, Client* c, const uint64_t* ids, const ReadLocalFallbackReason* reasons,
                       uint32_t n, uint32_t& demoted) {
                        return static_cast<IoLoop*>(p)->fused_demote_local_read_batch(c, ids, reasons, n, demoted);
                    });
            }
            const int sid = server.thread(owner).shards().front()->id();
            for (unsigned n = 0; n < 100000; ++n) {
                key = "rlfix5:" + std::to_string(n);
                if (server.router().shard_of(FlatStore::hash_key(slice(key))) == sid) break;
            }
            need(server.worker_of_shard(server.router().shard_of(FlatStore::hash_key(slice(key)))) == owner);
        }
        ~Fixture() {
            for (auto& c : clients) server.thread(reader).release_wb_slot(c->wb_slot());
            if (local) for (unsigned i = 0; i < 8; ++i) {
                fused[i].read_local_impl().deferred.drain_shutdown();
                for (auto* s : server.thread(i).shards()) s->store().configure_read_local(false, {});
            }
            command_bind_server(nullptr);
        }
        Client& client() {
            clients.push_back(std::make_unique<Client>(-1)); auto& c = *clients.back();
            c.set_id(9000 + clients.size()); c.set_ifid_thread(reader);
            c.set_wb_slot(server.thread(reader).assign_wb_slot(&c));
            command_client_connected(&c, "127.0.0.1:21599", "127.0.0.1:21500", false, 1000);
            return c;
        }
        void tracking(bool on) { server.set_latency_tracking(on); io.refresh_notify_config(); }
        void input(Client& c, const std::string& text) {
            need(c.rpos() == c.rlen());
            // Published operations may still borrow their arguments. Append the next pass;
            // only a fully retired ROB permits reuse of the previous input storage.
            if (c.rob().in_flight() == 0) c.reset_rbuf_at_quiescence();
            size_t available = 0;
            need(c.read_space_impl<false>(text.size(), available, true, 1u << 20, 0));
            need(available >= text.size()); std::memcpy(c.rbuf() + c.rlen(), text.data(), text.size());
            c.commit_read(text.size());
        }
        void parse(Client& c) {
            if (one) parse_fused(&io, &c);
            else if (local) parse_local_split(&io, &c);
            else parse_split(&io, &c);
        }
        unsigned lane() { return local ? drain_local(&fused[reader], 1024) : 0; }
        unsigned owners() {
            unsigned count = 0;
            for (unsigned i = 0; i < 8; ++i) {
                Task tasks[64]; unsigned n = 0;
                server.thread(i).drain_tasks_unmasked([&](const Task& t) { need(n < 64); tasks[n++] = t; });
                if (!n) continue;
                count += n;
                if (one || local) exec_fused(&fused[i], tasks, n); else exec_split(&split[i], tasks, n);
            }
            return count;
        }
        std::vector<std::string> replies(Client& c) {
            std::vector<std::string> out;
            c.rob().drain([&](Op& op) {
                std::string s; if (op.direct_len) s.assign(op.direct, op.direct_len);
                s.append(op.reply.data(), op.reply.size());
                if (op.reply_code_) { char b[64]; s.append(b, format_reply_code(b, op.reply_code_, op.reply_ival_)); }
                out.push_back(s);
            });
            return out;
        }
        std::vector<std::string> finish(Client& c) {
            std::vector<std::string> all;
            for (unsigned n = 0; n < 128; ++n) {
                if (c.rpos() != c.rlen()) parse(c);
                lane(); owners();
                auto r = replies(c); all.insert(all.end(), r.begin(), r.end());
                if (c.rpos() == c.rlen() && c.rob().in_flight() == 0) return all;
            }
            need(false); return {};
        }
        void put(const std::string& value) {
            auto& c = client(); input(c, wire({"SET", key, value}));
            need(finish(c) == std::vector<std::string>{"+OK\r\n"});
        }
        void arm(Client& c) {
            input(c, wire({"GET", key})); parse(c);
            need(c.rob().has_pending_read_local()); need(lane() == 1); need(replies(c).size() == 1);
        }
    };
    static void witness(const std::string& name, bool one) {
        Fixture f(one, true, false); f.put("old"); auto& c = f.client(); f.arm(c);
        std::vector<std::string> expected;
        if (name == "monotonic") {
            auto& writer = f.client(); f.input(writer, wire({"SET", f.key, "new-value"})); f.parse(writer);
            need(writer.rob().in_flight() == 1); // Held owner task precedes the read in the producer FIFO.
            f.input(c, wire({"STRLEN", f.key}) + wire({"GET", f.key})); f.parse(c);
            f.lane(); f.owners(); expected = {":9\r\n", "$9\r\nnew-value\r\n"};
        } else if (name == "yes-no") {
            f.tracking(true); f.input(c, wire({"SET", f.key, "new-value"})); f.parse(c);
            need(c.rob().in_flight() == 1);
            f.tracking(false); f.input(c, wire({"GET", f.key})); f.parse(c);
            f.lane(); f.owners(); expected = {"+OK\r\n", "$9\r\nnew-value\r\n"};
        } else {
            need(name == "no-yes" || name == "mget-no-yes");
            const bool mget = name == "mget-no-yes";
            f.input(c, wire({mget ? "MGET" : "GET", f.key})); f.parse(c);
            need(c.rob().has_pending_read_local());
            if (mget) need(c.rob().local_mget_fence_pending());
            f.tracking(true); f.input(c, wire({"SET", f.key, "new-value"})); f.parse(c);
            f.owners(); f.lane();
            expected = {mget ? "*1\r\n$3\r\nold\r\n" : "$3\r\nold\r\n", "+OK\r\n"};
        }
        auto actual = f.finish(c);
        for (const auto& s : actual) std::printf("reply=%s", s.c_str());
        need(actual == expected);
        std::printf("PASS rlfix5 %s %s: window exercised\n", name.c_str(), one ? "1s" : "2s");
    }
    static void count(const std::string& command, bool one, unsigned batch, bool local, bool tracking) {
        Fixture f(one, local, tracking); f.put(command == "INCR" ? "0" : "old"); auto& c = f.client();
        if (local && !tracking) f.arm(c);
        std::string frame;
        if (command == "SET" || command == "MSET") frame = wire({command, f.key, "old"});
        else if (command == "GETRANGE") frame = wire({command, f.key, "0", "-1"});
        else if (command == "OBJECT") frame = wire({command, "ENCODING", f.key});
        else frame = wire({command, f.key});
        std::string text; for (unsigned i = 0; i < batch; ++i) text += frame;
        f.input(c, text);
        scope_begin();
        auto replies = f.finish(c);
        scope_end();
        need(replies.size() == batch);
        for (unsigned i = 0; i < batch; ++i) {
            const std::string want = command == "GET" || command == "GETRANGE" ? "$3\r\nold\r\n"
                : command == "MGET" ? "*1\r\n$3\r\nold\r\n"
                : command == "SET" || command == "MSET" ? "+OK\r\n"
                : command == "INCR" ? ":" + std::to_string(i + 1) + "\r\n"
                : command == "STRLEN" ? ":3\r\n" : command == "EXISTS" ? ":1\r\n"
                : command == "TYPE" ? "+string\r\n" : command == "TTL" ? ":-1\r\n" : "$6\r\nembstr\r\n";
            need(replies[i] == want);
        }
        std::printf("PASS scope %s %s p%u rl%d latency%d\n", command.c_str(), one ? "1s" : "2s", batch, local, tracking);
    }
};
}
int main(int argc, char** argv) {
    if (argc != 6 || !command_registry_init(false)) return 2;
    const std::string name = argv[1];
    if (name.starts_with("witness-")) CoreConcurrencyTest::witness(name.substr(8), std::string(argv[2]) == "1s");
    else CoreConcurrencyTest::count(name, std::string(argv[2]) == "1s", std::stoul(argv[3]),
                                   std::stoi(argv[4]), std::stoi(argv[5]));
}
