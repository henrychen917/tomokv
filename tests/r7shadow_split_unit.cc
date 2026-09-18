// Production parser/inbox/handler workload; no listener, workers or io_uring setup.
// A separate process per raw knob makes allocation traces comparable from fresh state.
#define main engagement_main
#include "reorder_engagement_unit.cc"
#undef main

namespace {
using T = tomo::CoreConcurrencyTest;
template <bool ReadLocal>
void split(int32_t requested, uint32_t overlap, const std::string& leak) {
    using namespace tomo;
    r7_witness::track_heap = true;
    T::run<ReadLocal>(ThreadMode::Split, overlap, requested, true);
    T::shadow_pipes<ReadLocal>(ThreadMode::Split, overlap, requested);
    T::Fixture<ReadLocal> f(ThreadMode::Split, overlap, requested);
    auto& server = f.server;
    T::require(server.cfg().reorder == 0, "split init retained the raw request");
    // The ordinary existing signal beat must not observe the R7 policy.
    for (uint32_t i = 0; i < kGenthreadExBatchOps; ++i)
        T::require(server.thread(f.owner).sample_depth(1000 + 100 * i), "split signal beat missing");
    // Directed counterfactuals: execute the real forbidden mechanism, not the hook.
    if (leak == "parse") {
        Client client(-1);
        r7::ShadowDispatch dispatch(client);
    } else if (leak == "policy") {
        ModeScheduleStats stats;
        r7::PolicyScope scope(stats);
    } else if (leak == "sample") {
        (void)r7::InboxProbe::sample(server.thread(f.owner));
    } else if (leak == "allocation") {
        // Allocate and free it before inspection: a null final pointer is insufficient.
        auto* p = new ModeScheduleStats[server.nthreads()];
        asm volatile("" : : "r"(p) : "memory");
        delete[] p;
    }
    r7_witness::track_heap = false;
    T::require(r7_witness::paths == 0, "reorder-specific path executed in split mode");
    T::require(r7_witness::allocations == 0, "reorder-specific allocation in split mode");
    const auto* stats = server.mode_schedule_stats();
    T::require((stats != nullptr) == (overlap != 0), "split schedule allocation depends on reorder");
    if (stats) for (uint32_t i = 0; i < server.nthreads(); ++i) {
        T::require(!stats[i].reorder_policy && !stats[i].reorder_auto.load() &&
                       !stats[i].reorder_batches.load() && !stats[i].reorder_multi_client_runs.load() &&
                       !stats[i].reorder_permuted_runs.load() && !stats[i].reorder_max_batch.load(),
                   "split retained reorder state inside overlap storage");
    }
    command_bind_server(&server);
    Op op;
    T::require(op.push_arg(Slice("INFO")) && op.push_arg(Slice("SERVER")), "INFO arguments");
    command_lookup(Slice("INFO"))->handler(*server.thread(f.owner).shards().front(), op);
    const std::string info(op.reply.data(), op.reply.size());
    T::require(info.find("reorder:0\r\nreorder_retired:1\r\n") != std::string::npos,
               "split INFO does not report retired FIFO");
    for (const char* field : {"reorder_batches:", "reorder_multi_client_runs:", "reorder_permuted_runs:",
                             "reorder_max_batch:", "reorder_shadow:", "reorder_auto_"})
        T::require(info.find(field) == std::string::npos, "split INFO exposes reorder state");
    T::require(r7_witness::paths == 0, "split INFO traversed reorder state");
    command_bind_server(nullptr);
    // Only deterministic witness fields enter the cross-process comparison.
    std::printf("WITNESS paths=%llu reorder_allocations=%llu heap_calls=%llu heap_bytes=%llu heap_trace=%llu\n",
        (unsigned long long)r7_witness::paths, (unsigned long long)r7_witness::allocations,
        (unsigned long long)r7_witness::heap_calls, (unsigned long long)r7_witness::heap_bytes,
        (unsigned long long)r7_witness::heap_trace);
}
}

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "positive") {
        T::require(tomo::command_registry_init(false), "command registry");
        T::run<true>(tomo::ThreadMode::Fused, 0, 1, true);
        T::shadow_pipes<true>(tomo::ThreadMode::Fused, 0, 1);
        T::require(r7_witness::paths > 0 && r7_witness::allocations > 0,
                   "instrumented production R7 object did not count positive control");
        std::puts("PASS fused path/allocation positive control");
        return 0;
    }
    T::require(argc == 4 || argc == 5, "usage: split-unit requested overlap read-local [leak]");
    T::require(tomo::command_registry_init(false), "command registry");
    const int32_t requested = std::stoi(argv[1]);
    const uint32_t overlap = std::stoul(argv[2]);
    const std::string leak = argc == 5 ? argv[4] : "";
    if (std::stoi(argv[3])) split<true>(requested, overlap, leak);
    else split<false>(requested, overlap, leak);
}
