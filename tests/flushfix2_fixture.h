#pragma once
// Included after xshard.cc by serverless fixtures with no IO continuation loop.
// Drive the real FLUSH completion, shared decision and owner collapse; never
// substitute a physical clear or let generic promotion consume a range.
inline tomo::MultiChildFinish flushfix2_fixture_complete(tomo::Server& server, tomo::Client& client,
                                                         tomo::ScatterState& state, tomo::Op& op,
                                                         uint32_t owner, uint32_t shard) {
    using namespace tomo;
    if (state.kind != Kind::Flush) return xshard_multi_child_complete(state, op, owner);
    Ring ring;
    const auto finish = flush_complete(server, server.thread(owner), ring,
                                       Task{&client, 0, static_cast<int>(shard), &state}, op);
    if (finish == ScatterFinish::Waiting) return MultiChildFinish::Waiting;
    if (finish == ScatterFinish::CommitQueued) {
        if (!state.group_attempt() || state.phase != 1 || state.aborted.load()) std::abort();
        server.atomic_commit_batch(1, [&](uint64_t ticket) { txn_group_decide(state, ticket); });
        state.phase = 2;
        state.pending.store(state.nsub, std::memory_order_release);
        return MultiChildFinish::PhaseAdvanced;
    }
    if (finish != ScatterFinish::Final || state.phase != 2 || state.record_refs.load())
        std::abort();
    return MultiChildFinish::Final;
}
