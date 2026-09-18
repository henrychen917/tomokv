// Deterministic namespace boundary schedules. Socketpairs for admission only;
// no listeners, io_uring queues, worker loops, sleeps or timing-based arming.
#include "src/core/server.h"
#include <functional>
namespace tomo {
static std::function<void(Server&, Op&)> after_database_stamp;
static void boundary_test_stamp(Server& server, Op& op, uint8_t logical) {
    multidb_stamp(server, op, logical);
    if (after_database_stamp) after_database_stamp(server, op);
}
}
// Interpose only in this test TU: the real stamp runs, then the deterministic
// schedule can finish the other connection's swap before parsing continues.
#define multidb_stamp boundary_test_stamp
#include "src/core/io_loop.h"
#undef multidb_stamp
#include <array>
#include <cstdio>
#include <memory>
#include <string>

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool value, const char* why) {
        if (!value) { std::fprintf(stderr, "FAIL multidb boundary: %s\n", why); std::exit(1); }
    }
    template<bool Fused, bool ReadLocal> static void accept_during_boundary() {
        Server server;
        Config cfg; cfg.databases = 16; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.read_local = ReadLocal; cfg.atomic = 1;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = cfg.protected_mode = 0;
        require(server.prepare_boot(cfg) && server.init(cfg), "admission fixture initialization");
        require(server.nthreads() == 8, "exact eight-core admission fixture");
        command_bind_server(&server);
        IoLoop io; io.srv_ = &server; io.self_ = &server.thread(0);
        // The accept CQE handler's admission checks are shared by both transport
        // instantiations. Use epoll for socketpair reads so no uring is started.
        io.epoll_ = true;
        require(io.ep_.init(), "socketpair epoll set");
        ExLoopT<true> local;
        local.srv_ = &server; local.self_ = io.self_;
        io.fused_executor_ = &local;
        const auto parse = [&](Client* client) {
            (void)io.template parse_and_dispatch<false,
                Fused ? kGenthreadIfidBatchOps : 0, !Fused,
                false, false, false, !Fused && ReadLocal>(client);
        };
        const auto accepted = [&](int fd, bool direct, uint64_t generation) {
            if (direct) io.template admit_fd<true, Fused>(fd, UrKind::Accept);
            else {
                io_uring_cqe cqe{};
                cqe.res = fd; cqe.flags = IORING_CQE_F_MORE;
                cqe.user_data = ur_tag(UrKind::Accept, reinterpret_cast<void*>(generation));
                io.template on_accept<true, Fused>(&cqe, UrKind::Accept);
            }
        };
        Client initiator(-1);
        constexpr char request[] = "*3\r\n$6\r\nSWAPDB\r\n$1\r\n0\r\n$1\r\n1\r\n"
                                   "*3\r\n$6\r\nSWAPDB\r\n$1\r\n0\r\n$1\r\n1\r\n";
        unsigned windows = 0;
        for (const auto stage : {FlipStage::DatabaseIoDrain, FlipStage::DatabaseExDrain,
                                 FlipStage::DatabaseRun}) {
            for (bool direct : {false, true}) {
                require(!server.database_boundary_begin(initiator, 0, 0), "first swap holds boundary");
                // Force each exact accept window, including after IO has acknowledged
                // the drain. The execution/ack schedule is covered by run() below.
                server.flip_stage_.store(stage, std::memory_order_release);
                int sockets[2];
                require(::socketpair(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC,
                                     0, sockets) == 0, "admission socketpair");
                require(::send(sockets[1], request, sizeof(request) - 1, MSG_NOSIGNAL) ==
                            sizeof(request) - 1, "second swapper sends two commands before admission");
                accepted(sockets[0], direct, io.accept_generation_);
                char byte;
                const auto received = ::recv(sockets[1], &byte, 1, MSG_DONTWAIT);
                if (received != -1 || (errno != EAGAIN && errno != EWOULDBLOCK))
                    std::fprintf(stderr, "admission mode=%s read-local=%u stage=%u direct=%u recv=%zd errno=%d\n",
                                 Fused ? "1s" : "2s", ReadLocal, unsigned(stage), direct, received, errno);
                require(received == -1 && (errno == EAGAIN || errno == EWOULDBLOCK),
                        "SWAPDB must not close a newly accepted swapper");
                require(server.live_clients() == 1 && io.self_->clients().size() == 1,
                        "second swapper is owned and counted");
                Client* client = io.self_->clients().front();
                require(client->rlen() == sizeof(request) - 1 && !client->closing(),
                        "both swap frames reached the live connection");
                parse(client);
                require(client->flip_backpressure() && client->rpos() == 0 &&
                            client->rob().dispatch_id() == 0 && client->rob().quiesced(),
                        "admission cannot dispatch past another swap's execution boundary");
                require(multidb_io_drained(*io.self_) &&
                            server.databases().boundary_client.load() == &initiator,
                        "new unconsumed commands preserve the prior drain acknowledgement");
                require(server.databases().swap(0, 1), "first swap publishes");
                server.database_boundary_end(initiator, 0);
                // This is the active-loop retry once Idle releases flip backpressure.
                client->set_flip_backpressure(false);
                parse(client);
                require(server.flip_stage() == FlipStage::DatabaseIoDrain &&
                            server.databases().boundary_client.load() == client &&
                            client->rpos() == 0 && client->rob().quiesced(),
                        "surviving swapper starts its own boundary from the same frame");
                io.close_client(client);
                require(!client->dead(), "boundary reference holds the disconnect");
                (void)io.database_control_pass();
                require(!server.database_boundary_active(), "disconnect cancels the new boundary");
                io.close_client(client);
                io.reap_dead(); io.reap_dead();
                ::close(sockets[1]);
                require(server.live_clients() == 0 && io.self_->clients().empty() &&
                            io.active_.size() == 0 && io.dead_ready_.empty(),
                        "admission fixture releases the connection exactly once");
                ++windows;
            }
        }
        // Role conversion still rejects incoming descriptors, as do stale accept
        // completions. A broad removal of the admission fence must fail here.
        for (auto stage : {FlipStage::Planning, FlipStage::IoDrain, FlipStage::IoPrepare,
                           FlipStage::ExDrain, FlipStage::ClientPrepare, FlipStage::ClientCommit,
                           FlipStage::ClientInstall, FlipStage::RoleReady, FlipStage::ShardCommit,
                           FlipStage::ExInstall, FlipStage::Rollback, FlipStage::Idle}) {
            server.flip_stage_.store(stage, std::memory_order_release);
            for (bool direct : {false, true}) {
                if (stage == FlipStage::Idle && direct) continue;
                int sockets[2];
                require(::socketpair(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC,
                                     0, sockets) == 0, "role fence socketpair");
                accepted(sockets[0], direct, io.accept_generation_ + (stage == FlipStage::Idle));
                char byte;
                require(::recv(sockets[1], &byte, 1, MSG_DONTWAIT) == 0 && server.live_clients() == 0,
                        "role-transition/stale accept still closes without admission");
                ::close(sockets[1]);
            }
        }
        require(windows == 6, "every database-stage/accept-entry window armed");
        command_bind_server(nullptr);
        std::printf("PASS multidb accept boundary %s read-local=%u atomic=1: %u forced windows\n",
                    Fused ? "1s" : "2s", ReadLocal, windows);
    }
    template<bool Fused> static void stamp_at_boundary(
            Server& server, std::array<ExLoopT<Fused>, 8>& owners, IoLoop& io) {
        Client initiator(-1), writer(-1);
        writer.set_id(98); writer.set_ifid_thread(0);
        writer.set_wb_slot(server.thread(0).assign_wb_slot(&writer));
        server.thread(0).add_client(&writer);
        const std::string key = "stamp-boundary";
        const std::string frame = "*3\r\n$3\r\nSET\r\n$" + std::to_string(key.size()) +
                                  "\r\n" + key + "\r\n$5\r\nvalue\r\n";
        std::memcpy(writer.rbuf(), frame.data(), frame.size());
        writer.commit_read(frame.size());
        const auto find = [&](uint8_t logical) {
            Slice physical(key.data(), key.size(), server.databases().capture()[logical]);
            const auto hash = FlatStore::hash_key(physical);
            return server.shard(server.router().shard_of(hash)).store().find(hash, physical);
        };
        require(!find(0) && !find(1), "fresh key for stamp/publication window");
        require(!server.database_boundary_begin(initiator, 0, 0), "stamp fixture boundary starts");
        server.flip_stage_.store(FlipStage::DatabaseRun, std::memory_order_release);
        unsigned releases = 0, stamps = 0;
        const auto finish_swap = [&] {
            require(server.flip_stage() == FlipStage::DatabaseRun, "swap publication window armed");
            require(server.databases().swap(0, 1), "publish swap during parser schedule");
            server.database_boundary_end(initiator, 0);
            ++releases;
            // This read starts AFTER SWAPDB replies and BEFORE SET executes. It
            // forces the overlapping SET after the swap in every serial history.
            require(!find(1), "post-swap read precedes the pending SET");
        };
        after_database_stamp = [&](Server&, Op&) {
            ++stamps;
            if (server.database_boundary_active()) finish_swap();
        };
        const auto parse = [&] {
            (void)io.template parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(&writer);
        };
        parse();
        if (server.database_boundary_active()) {
            require(writer.flip_backpressure() && writer.rpos() == 0 && writer.rob().quiesced(),
                    "parser holds the new command until its map may be captured");
            finish_swap();
            writer.set_flip_backpressure(false);
            parse();
        }
        after_database_stamp = {};
        require(releases == 1 && stamps == 1 && writer.rob().dispatch_id() == 1 &&
                    writer.rpos() == writer.rlen(), "one map capture and one dispatch across the forced window");
        unsigned executed = 0;
        for (unsigned tid = 0; tid < 8; ++tid)
            server.thread(tid).drain_tasks_unmasked([&](const Task& task) {
                require(owners[tid].execute(task), "execute the delayed SET on its owner");
                ++executed;
            });
        require(executed == 1, "the pending SET actually executed");
        require(find(0) && !find(1),
                "SET must use the post-swap map after the intervening empty read");
        require(writer.rob().drain([](Op& op) {
            op_materialise_code(op);
            std::string reply;
            if (op.direct_len) reply.append(op.direct, op.direct_len);
            reply.append(op.reply.data(), op.reply.size());
            require(reply == "+OK\r\n", "pending SET reply");
        }) == 1, "one SET reply retired");
        server.thread(0).remove_client(&writer);
        server.thread(0).release_wb_slot(writer.wb_slot());
        writer.set_in_active(false); io.active_.erase(&writer);
        std::printf("PASS multidb stamp/publication boundary %s: one forced swap, one SET, intervening read\n",
                    Fused ? "1s" : "2s");
    }
    template<bool Fused> static void run() {
        Server server;
        Config cfg; cfg.databases = 16; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        require(server.prepare_boot(cfg) && server.init(cfg), "fixture initialization");
        require(server.nthreads() == 8, "exact eight-core fixture");
        command_bind_server(&server);
        std::array<ExLoopT<Fused>, 8> owners;
        std::array<IoLoop, 8> ios;
        for (unsigned tid = 0; tid < 8; ++tid) {
            auto& thread = server.thread(tid);
            require(Fused ? thread.init_task_inbox_local_fused() :
                thread.init_task_inbox_local(server.placement().ifid_threads(),
                                             server.placement().ex_threads()), "task lanes");
            auto& owner = owners[tid]; owner.srv_ = &server; owner.self_ = &thread;
            owner.fused_handoff_ring_ = &owner.ring_; owner.cached_now_ms_ = 1000;
            if constexpr (Fused) owner.fused_completion_ = [](void*, Client*) {};
            server.bind_owner_notify_pending(tid, &owner.notify_keyless_pending_);
            owner.refresh_live_config();
            ios[tid].srv_ = &server; ios[tid].self_ = &thread;
            if constexpr (Fused) ios[tid].fused_executor_ = &owner;
        }
        auto control = [&] {
            for (auto tid : server.placement().ifid_threads())
                (void)ios[tid].template flip_control_pass<false>();
            if constexpr (!Fused)
                for (auto tid : server.placement().ex_threads()) (void)owners[tid].flip_control_pass();
        };
        stamp_at_boundary<Fused>(server, owners, ios[0]);
        Client swapper(-1);
        swapper.set_id(99); swapper.set_ifid_thread(0);
        server.thread(0).add_client(&swapper);
        std::array<Client, 4> writers{Client(-1), Client(-1), Client(-1), Client(-1)};
        std::array<std::array<std::string, 16>, 4> keys, values;
        for (unsigned w = 0; w < writers.size(); ++w) {
            writers[w].set_id(w + 1); writers[w].set_ifid_thread(w);
            writers[w].set_wb_slot(server.thread(w).assign_wb_slot(&writers[w]));
            server.thread(w).add_client(&writers[w]);
            for (unsigned i = 0; i < 16; ++i) keys[w][i] = "boundary:" + std::to_string(w) + ":" + std::to_string(i);
        }
        unsigned witnessed = 0;
        for (unsigned round = 0; round < 32; ++round) {
            const auto map = server.databases().capture();
            std::array<uint64_t, 4> starts{};
            for (unsigned w = 0; w < writers.size(); ++w) {
                auto& c = writers[w]; starts[w] = c.rob().dispatch_id();
                for (unsigned i = 0; i < 16; ++i) {
                    values[w][i] = "epoch=" + std::to_string(map.epoch) + ":" + std::to_string(i);
                    for (bool write : {true, false}) {
                        Op* op = c.rob().acquire<false>(); require(op, "pipeline slot");
                        require(op->push_arg(Slice(write ? "SET" : "GET", 3)) &&
                            op->push_arg(Slice(keys[w][i])) &&
                            (!write || op->push_arg(Slice(values[w][i]))), "pipeline arguments");
                        op->spec = command_lookup(op->arg(0)); multidb_stamp(server, *op, w % 2);
                        op->hash = FlatStore::hash_key(op->key()); op->shard = server.router().shard_of(op->hash);
                        op->mark_no_borrow(); c.rob().publish();
                    }
                }
            }
            require(!server.database_boundary_begin(swapper, 0, swapper.rob().dispatch_id()), "starts with a drain");
            for (unsigned pass = 0; pass < 3; ++pass) control();
            require(server.flip_stage() == FlipStage::DatabaseIoDrain, "delayed stamped writes hold boundary");
            require(server.databases().capture().epoch == map.epoch, "no premature map publish");
            ++witnessed;
            // Interleave four pipelines; each connection keeps program order. Capture
            // every reply's actual parser generation, not the generation at retirement.
            for (unsigned index = 0; index < 32; ++index) {
                for (unsigned w = 0; w < writers.size(); ++w) {
                    auto& c = writers[w]; auto id = starts[w] + index; auto& op = c.rob().at(id);
                    require(op.physical_db == map[w % 2] && op.key().ns == map[w % 2],
                            "immutable physical identity from the captured map");
                    require(owners[server.worker_of_shard(op.shard)].execute(Task{&c, id, -1, nullptr}), "owner execution");
                    if (index % 2) {
                        const auto& value = values[w][index / 2];
                        const std::string wanted = "$" + std::to_string(value.size()) + "\r\n" + value + "\r\n";
                        require(std::string(op.reply.data(), op.reply.size()) == wanted, "GET has a serial predecessor in its epoch");
                    }
                }
                control();
                if (index != 31) require(server.flip_stage() == FlipStage::DatabaseIoDrain, "every old operation must execute");
            }
            for (unsigned pass = 0; pass < 16 && server.flip_stage() != FlipStage::DatabaseRun; ++pass) control();
            require(server.flip_stage() == FlipStage::DatabaseRun, "owners drained without waiting for replies to retire");
            for (auto& c : writers) require(!multidb_dispatch_allowed(server, c), "foreign dispatch stays fenced");
            require(multidb_dispatch_allowed(server, swapper), "only boundary initiator may dispatch");
            require(server.databases().swap(0, 1), "map publication");
            require(server.databases().capture().epoch == map.epoch + 1, "one new map generation");
            server.database_boundary_end(swapper, swapper.rob().dispatch_id());
            for (unsigned w = 0; w < writers.size(); ++w) {
                auto& c = writers[w]; require(c.rob().drain([](Op&) {}) == 32, "retire full pipeline");
                const auto after = server.databases().capture();
                for (unsigned i = 0; i < 16; ++i) {
                    Slice key(keys[w][i].data(), keys[w][i].size(), after[1 - w % 2]);
                    const auto hash = FlatStore::hash_key(key);
                    auto* object = server.shard(server.router().shard_of(hash)).store().find(hash, key);
                    require(object && object->key().key_eq(key), "old writes moved with their physical namespace");
                }
            }
        }
        require(witnessed == 32, "all delayed-writer windows armed");
        // Disconnect before publication releases the cold Client reference and the fence.
        require(!server.database_boundary_begin(swapper, 0, swapper.rob().dispatch_id()), "cancel boundary start");
        swapper.mark_closing(); control();
        require(!server.database_boundary_active() && swapper.safe_to_release(), "disconnect cancels unpublished boundary");
        for (unsigned w = 0; w < writers.size(); ++w) server.thread(w).remove_client(&writers[w]);
        server.thread(0).remove_client(&swapper);
        command_bind_server(nullptr);
        std::printf("PASS multidb serial boundary %s: 4 writers x p32 x 32 epochs; delayed windows=%u\n", Fused ? "1s" : "2s", witnessed);
    }
};
}
int main() {
    tomo::CoreConcurrencyTest::require(tomo::command_registry_init(false), "command registry");
    tomo::CoreConcurrencyTest::accept_during_boundary<false, false>();
    tomo::CoreConcurrencyTest::accept_during_boundary<false, true>();
    tomo::CoreConcurrencyTest::accept_during_boundary<true, false>();
    tomo::CoreConcurrencyTest::accept_during_boundary<true, true>();
    tomo::CoreConcurrencyTest::run<false>();
    tomo::CoreConcurrencyTest::run<true>();
}
