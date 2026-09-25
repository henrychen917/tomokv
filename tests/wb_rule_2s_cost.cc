// One deterministic selection invocation, no clocks, PMU, server or workload.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <memory>
#include <string>
#include <vector>
#include "src/core/iopipe_pipeline.h"
#include "src/core/wb_rule.h"
using namespace tomo;
void tomo::multi_session_destroy(MultiSession* p) { if (p) std::abort(); }
struct SelectionLoop { std::deque<Client*> pending_serve_; };
struct SelectionBatch {
    std::array<Client*, kIoPipeWbBatchClients> clients;
    std::array<bool, kIoPipeWbBatchClients> submit_allowed;
    uint32_t count = 0;
};
// The same production template; includes FIFO pops/rotations, pin changes and
// scratch chunking, excludes AOF checks, retirement, formatting and SEND.
extern "C" __attribute__((noinline)) unsigned wb_rule_2s_cost_select(SelectionLoop* loop) {
    size_t left = SIZE_MAX;
    unsigned selected = 0;
    do {
        SelectionBatch batch;
        selected += wb_rule::Phase2::gather(*loop, batch, left);
    } while (left && !loop->pending_serve_.empty());
    return selected;
}
extern "C" __attribute__((noinline)) unsigned wb_rule_2s_cost_walk(Client** clients, size_t count) {
    unsigned selected = 0;
    for (size_t i = 0; i < count; ++i) selected += !wb_rule::defer(*clients[i]);
    return selected;
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string name = argv[1];
    const bool mget = name.find("mget") != std::string::npos;
    const bool select = name.find("select") != std::string::npos;
    const unsigned count = name.ends_with("128") ? 128 : 16;
    const unsigned depth = mget ? 8 : 32;
    SelectionLoop loop;
    std::vector<std::unique_ptr<Client>> owned;
    std::vector<Client*> clients;
    for (unsigned j = 0; j < count; ++j) {
        auto c = std::make_unique<Client>(-1);
        for (unsigned i = 0; i < depth; ++i) {
            Op* op = c->rob().acquire<false>(); if (!op) std::abort();
            if (mget) { op->zc_ptr = reinterpret_cast<const char*>(1); op->zc_shard = Op::kScatterStateMarker; op->zc_len = UINT32_MAX; }
            else op->reply.append("+OK\r\n", 5);
            c->rob().publish();
            op->state.store(mget || i < (j%4+1)*8 ? OpState::Done : OpState::Issued, std::memory_order_release);
        }
        c->set_serve_pending(true); clients.push_back(c.get()); loop.pending_serve_.push_back(c.get());
        owned.push_back(std::move(c));
    }
    const unsigned result = select ? wb_rule_2s_cost_select(&loop) : wb_rule_2s_cost_walk(clients.data(), clients.size());
    constexpr unsigned numerator = 1, denominator = 2; // test expectation, patched only in the 3/4 overlay
    const unsigned expected = mget ? count : count/4 * (numerator == 1 && denominator == 2 ? 3 : 2);
    if (result != expected) { std::fprintf(stderr,"FAIL cost selection %u != %u\n",result,expected); return 1; }
    std::printf("PASS wb-rule 2s cost %s selected=%u\n",argv[1],result);
}
