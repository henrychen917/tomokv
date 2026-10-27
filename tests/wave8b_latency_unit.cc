// Instrument the actual histogram implementation, linked to production EXEC.
// The counter is absent from release objects; no sampling clock or load loop.
#define TOMO_LATENCY_SCAN_WITNESS
#include "src/cmd/latency_tracking.cc"
#define main wave8b_scope_main
#include "wave8b_scope.cc"
#undef main

static void transitions() {
    Server server;
    command_bind_server(&server);
    auto enabled = [&](bool value) {
        server.set_latency_tracking(value);
        if (!value) latency_tracking_discard_pending();
        latency_tracking_bind(value);
    };
    Op parent, child;
    parent.reset(); child.reset();
    for (auto* op : {&parent, &child}) {
        CoreConcurrencyTest::need(op->push_arg(Slice("INCR")) && op->push_arg(Slice("wave8b")));
        op->spec = command_lookup(op->arg(0));
    }
    latency_tracking_reset();
    enabled(true);
    const auto old = latency_tracking_start();
    latency_tracking_part(0, parent, old);
    latency_tracking_script_part(0, parent, child, old);
    CoreConcurrencyTest::need(!store(0).pending.empty() && !store(0).script_children.empty());
    enabled(false);
    CoreConcurrencyTest::need(store(0).pending.empty() && store(0).script_children.empty());
    enabled(true);
    // These scopes straddle no/yes. They must never resurrect discarded state.
    latency_tracking_part(0, parent, old);
    latency_tracking_script_part(0, parent, child, old);
    latency_tracking_finish(0, child, old);
    // The callback is delayed across no/yes after measuring a short duration.
    // Reconstructing now-duration would incorrectly turn this into a fresh sample.
    record_tracked(0, 0, child, 1, 0, SlowlogArm{-1, 0, true}, true, old);
    CoreConcurrencyTest::need(store(0).pending.empty() && store(0).script_children.empty());
    CoreConcurrencyTest::need(collect().empty());
    const auto fresh = latency_tracking_start();
    latency_tracking_part(0, parent, fresh);
    latency_tracking_retry(parent, child);
    CoreConcurrencyTest::need(!store(0).pending.contains(&parent) && store(0).pending.contains(&child));
    latency_tracking_retire(0, child);
    uint64_t samples = 0;
    for (const auto& row : collect()) samples += row.second.calls;
    CoreConcurrencyTest::need(samples == 1);
    latency_tracking_retire(0, child);
    uint64_t again = 0;
    for (const auto& row : collect()) again += row.second.calls;
    CoreConcurrencyTest::need(again == samples);
    enabled(false);
    latency_scan_slots = 0;
    Client client(-1);
    latency_tracking_retire(0, child);
    latency_tracking_forget(child);
    latency_tracking_forget_client(client);
    latency_tracking_retry(parent, child);
    latency_tracking_script_begin(parent);
    latency_tracking_part(0, parent, fresh);
    latency_tracking_script_part(0, parent, child, fresh);
    latency_tracking_record(0, child, 1000);
    CoreConcurrencyTest::need(latency_scan_slots == 0);
    command_bind_server(nullptr);
    std::puts("PASS stale slices, script children, retry transfer and disabled hooks with populated stores");
}

int main() {
    CoreConcurrencyTest::need(command_registry_init(false));
    for (bool tracking : {false, true, false, true}) {
        wave8b_tracking = tracking;
        for (bool atomic : {false, true}) for (const char* shape : {"EXEC-single", "EXEC-cross"}) {
            latency_tracking_reset();
            CoreConcurrencyTest::run<false>(shape, 4, atomic, -1);
            latency_tracking_reset();
            CoreConcurrencyTest::run<true>(shape, 4, atomic, -1);
        }
    }
    transitions();
}
