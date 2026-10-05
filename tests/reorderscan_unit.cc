// Serverless work-count witness over real Clients/ROBs and production R7 helpers.
// The reference is the PRE per-read ShadowDispatch back-scan. No timing oracle.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
static uint64_t visits = 0, constructions = 0;
#define TOMO_R7_SCAN_VISIT() (++visits)
#define TOMO_R7_SCAN_CONSTRUCT() (++constructions)
#include "src/core/reorder.h"

namespace tomo { void multi_session_destroy(MultiSession* p) { if (p) std::abort(); } }
namespace {
using namespace tomo;
using namespace tomo::r7;
void require(bool okay, const char* message) {
    if (!okay) { std::fprintf(stderr, "FAIL reorderscan: %s\n", message); std::exit(1); }
}
void unused(Shard&, Op&) { std::abort(); }
constexpr CommandSpec spec(const char* name, CommandLengthClass kind, uint32_t flags = CmdFlags::Readonly) {
    CommandSpec result(name, 2, 2, flags, unused, 1, 1, 1, unused);
    result.length_class = static_cast<uint8_t>(kind);
    return result;
}
constexpr auto point = spec("GET", CommandLengthClass::Point);
constexpr auto small = spec("MGET", CommandLengthClass::SmallMulti);
constexpr auto slow = spec("BITCOUNT", CommandLengthClass::Long);
constexpr auto barrier = spec("EXEC", CommandLengthClass::Long, CmdFlags::Transaction);
uint64_t append(Client& client, const CommandSpec& command) {
    auto& rob = client.rob();
    Op* op = rob.acquire();
    require(op, "fixture must open the requested ROB window");
    op->spec = &command;
    op->state.store(OpState::Issued, std::memory_order_release);
    const auto id = rob.dispatch_id();
    rob.publish();
    return id;
}
Task reference(Client& client, uint64_t id) {
    ShadowDispatch dispatch(client, id);
    Task result(&client, id, -1, nullptr);
    dispatch.stamp(result);
    return result;
}
void pure_short(uint32_t count) {
    Client client(-1);
    for (uint32_t i = 0; i < count; ++i) append(client, i % 2 ? small : point);
    visits = 0;
    std::vector<Task> before;
    for (uint32_t i = 0; i < count; ++i) before.push_back(reference(client, i));
    const auto pre = visits;
    visits = 0;
    ShadowDemotionDispatch dispatch(client, count - 1);
    for (uint32_t i = 0; i < count; ++i) {
#ifdef TOMO_REORDERSCAN_OLD_DEMOTION
        const auto after = reference(client, i);
#else
        const auto after = dispatch.task(&client, i);
#endif
        require(after.op_id == before[i].op_id && after.shard == before[i].shard,
                "demotion task or shadow changed");
    }
    require(pre == uint64_t{count} * (count - 1) / 2, "PRE quadratic window not armed");
    require(visits == count - 1, "POST must visit the prefix only once per commit");
    std::printf("PASS RO1 count=%u PRE=%llu POST=%llu slot visits/commit\n", count,
                (unsigned long long)pre, (unsigned long long)visits);
}
void mixed(uint64_t seed, uint32_t offset) {
    Client client(-1);
    auto& rob = client.rob();
    for (uint32_t i = 0; i < offset; ++i) {
        const auto id = append(client, point);
        rob.at(id).state.store(OpState::Done, std::memory_order_release);
        require(rob.drain([](Op&) {}) == 1, "advance to a real recycled ROB generation");
    }
    auto random = [&] { seed ^= seed << 13; seed ^= seed >> 7; seed ^= seed << 17; return seed; };
    std::vector<uint64_t> selected;
    for (uint32_t i = 0; i < 64; ++i) {
        const auto kind = random() % 5;
        const auto id = append(client, kind == 0 ? slow : kind == 1 ? barrier :
                                      kind == 2 ? small : point);
        if (kind >= 2 && (random() & 1)) selected.push_back(id);
        if (kind < 2 && (random() & 1)) rob.at(id).state.store(OpState::Done);
    }
    require(!selected.empty(), "mixed demotion must select reads");
    ShadowDemotionDispatch dispatch(client, selected.back());
    uint64_t post_visits = 0;
    for (const auto id : selected) {
        // Completion between demotions must reveal an older pending Long.
        const auto done = offset + random() % 64;
        if (rob.at(done).spec == &slow) rob.at(done).state.store(OpState::Done);
        const auto expected = reference(client, id);
        visits = 0;
        const auto actual = dispatch.task(&client, id);
        post_visits += visits;
        require(actual.client == expected.client && actual.op_id == expected.op_id &&
                    actual.shard == expected.shard && actual.scatter == expected.scatter,
                "older-prefix choice differs from PRE after completion/wrap");
    }
    require(post_visits <= selected.size() + 64, "repeated completion pruning is not linear");
}
}
int main() {
    for (const uint32_t count : {8u, 32u, 64u}) pure_short(count);
    for (uint64_t seed = 1; seed <= 1000; ++seed) mixed(seed, seed % 129);
    std::puts("PASS RO1 1000 mixed commits: exact tasks/order/shadows, Done and ROB wrap");
}
