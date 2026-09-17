// Deterministic namespace boundary schedule. No sockets, worker loops or clocks.
#include "src/core/io_loop.h"
#include <array>
#include <cstdio>
#include <memory>
#include <string>

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool value, const char* why) {
        if (!value) { std::fprintf(stderr, "FAIL multidb boundary: %s\n", why); std::exit(1); }
    }
    template<bool Fused> static void run() {
        Server server;
        Config cfg; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
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
                    require(op.database_epoch() == map.epoch, "recorded reply epoch");
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
    tomo::CoreConcurrencyTest::run<false>();
    tomo::CoreConcurrencyTest::run<true>();
}
