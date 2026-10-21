// Reuse the production hand-off fixtures; no listener, ring, or worker starts.
#define TOMO_CORE_CONCURRENCY_EMBED
#define TOMO_CORE_CONCURRENCY_TEST
#include "core_concurrency_unit.cc"
#undef TOMO_CORE_CONCURRENCY_EMBED

namespace tomo {
struct LbPlannerTest {
    using Core = CoreConcurrencyTest;
    template<bool Fused, bool Shadow>
    static void run(bool flip) {
        Core::Fixture<Fused> f;
        Client client(-1);
        f.client(client);
        const uint32_t destination = Fused ? 0 : 1;
        IoLoop target;
        target.srv_ = &f.server;
        target.self_ = &f.server.thread(destination);
        if constexpr (Fused) {
            f.io.fused_executor_ = &f.loops[f.io_id];
            target.fused_executor_ = &f.loops[destination];
        }
        command_client_connected(&client, "unit", "unit", false, 1);
        f.io.climon_track_client(&client);
        f.server.thread(f.io_id).add_client(&client);
        auto parse = [&](IoLoop& io) {
            if constexpr (Shadow)
                return io.r7_parse_and_dispatch<false, kGenthreadIfidBatchOps>(&client);
            else return io.parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(&client);
        };
        constexpr char prefix[] = "*2\r\n$4\r\nPING\r\n$4\r\npong\r";
        std::memcpy(client.rbuf(), prefix, sizeof(prefix)-1);
        client.commit_read(sizeof(prefix)-1);
        Core::require(parse(f.io) == IoLoop::DispatchResult::NeedInput,
                      "production parser must enter partial multibulk");
        Core::require(client.multibulk_pending() && client.multibulk_frontier().completed == 1,
                      "one completed argument actually saved before migration");
        client.rbuf()[4] = '!'; // Replay control, independent of elapsed time.
        std::string error;
        Core::require(f.io.client_transfer_ready(&client, destination, error), error.c_str());
        const auto flip_before = f.server.flip_clients_transferred_.load();
        if (flip) {
            Core::require(f.io.prepare_client_transfer(&client, destination, error), error.c_str());
            Core::require(f.io.client_transfers_prepared(), "FLIP partial client actually prepared");
            Core::require(client.ifid_thread() == f.io_id, "prepare retains source ownership");
            Core::require(f.io.template commit_client_transfer<false>(&client), "FLIP commit partial frame");
            Core::require(f.server.flip_clients_transferred_.load() == flip_before + 1,
                          "FLIP transfer counter witnesses commit");
        } else {
            Core::require(f.io.request_client_transfer(&client, destination, error), error.c_str());
        }
        Core::require(client.ifid_thread() == destination && client.multibulk_pending(),
                      "frontier crosses real single ownership edge");
        unsigned installed = 0;
        f.server.thread(destination).drain_client_transfers_unmasked([&](const ClientTransfer& transfer) {
            Core::require(transfer.client == &client, "correct Client transferred");
            Core::require(command_client_migration_install(transfer.catalog), "install migrated catalog");
            Core::require(target.client_routing_install(transfer.routing, &client, transfer.source),
                          "install migrated routing");
            ++installed;
        });
        Core::require(installed == 1, "migration inbox consumed exactly once");
        client.reset_rbuf_at_quiescence();
        client.rbuf()[client.rlen()] = '\n'; client.commit_read(1);
        Core::require(parse(target) == IoLoop::DispatchResult::Progress, "destination resumes frame");
        // PING is ConnLocal; the destination's production parser executes it.
        unsigned replies = client.rob().drain([](Op& op) {
            op_materialise_code(op);
            if (std::string(op.reply.data(), op.reply.size()) != "$4\r\npong\r\n")
                std::fprintf(stderr, "migration reply: %.*s\n", int(op.reply.size()), op.reply.data());
            Core::require(std::string(op.reply.data(), op.reply.size()) == "$4\r\npong\r\n",
                          "one exact reply after migration, no header replay");
        });
        Core::require(replies == 1 && !client.multibulk_pending(), "consume clears migrated frontier");
        command_client_disconnected(&client);
        f.server.thread(f.io_id).clients().clear();
        std::printf("PASS respresume migration: %s %s %s\n", Fused ? "1s" : "2s",
                    Shadow ? "R7" : "ordinary", flip ? "FLIP prepare/commit" : "client-LB handoff");
    }
};
}
int main() {
    tomo::CoreConcurrencyTest::require(tomo::command_registry_init(false), "initialize command registry");
    for (bool flip : {false, true}) {
        tomo::LbPlannerTest::run<false, false>(flip);
        tomo::LbPlannerTest::run<true, false>(flip);
        tomo::LbPlannerTest::run<true, true>(flip);
    }
}
