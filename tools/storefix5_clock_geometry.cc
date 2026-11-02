// Serverless allocation geometry control for post-freeze alternatives. This is
// not an implementation of a shared/multi-writer clock, nor a timing benchmark.
#include "src/store/object_idle.h"
#include "src/store/kvobj.h"
#include <cassert>
#include <cstdio>
#include <memory>
#include <thread>
#include <vector>

using namespace tomo;
struct Allocation { void* header; void* value; size_t request; unsigned shard; };

int main() {
    constexpr unsigned owners = 8, keys = 50000, key_length = 16;
    assert(good_size_matches_allocator());
    std::puts("source,shards,owners,keys,value_bytes,per_shard_B_per_key,per_owner_B_per_key,process_B_per_key,stamp_class_delta_B_per_key");
    for (unsigned shards : {16u, 128u}) for (bool parser : {false, true})
    for (unsigned value_length : {2u, 100u, 180u, 1000u}) {
        std::vector<Allocation> allocations(keys);
        std::vector<std::thread> workers;
        for (unsigned owner = 0; owner < owners; ++owner) workers.emplace_back([&, owner] {
            assert(bind_thread_arena());
            const Enc enc = value_length <= kEmbedThreshold ? Enc::Raw : Enc::Extern;
            const size_t request = kvobj_alloc_size(key_length, value_length, false, enc);
            for (unsigned i = owner; i < keys; i += owners) {
                const unsigned shard = parser ? (i / owners) % shards
                    : owner + ((i / owners) % (shards / owners)) * owners;
                void* header = alloc_raw(good_size(request));
                void* value = enc == Enc::Extern ? alloc_raw(good_size(value_length)) : nullptr;
                assert(header && (enc != Enc::Extern || value));
                allocations[i] = {header, value, request, shard};
            }
        });
        for (auto& worker : workers) worker.join();
        auto clock_bytes = [&](unsigned count) {
            auto clocks = std::make_unique<ObjectIdleClock[]>(count);
            size_t bytes = count * sizeof(ObjectIdleClock);
            for (const auto& a : allocations) {
                const unsigned tree = count == 1 ? 0 : a.shard % count;
                assert(clocks[tree].install(a.header, 1, bytes));
            }
            size_t walked = 0;
            for (unsigned i = 0; i < count; ++i) walked += clocks[i].allocated_bytes();
            assert(bytes == walked); // read-only traversal agrees with allocations
            return bytes;
        };
        const auto per_shard = clock_bytes(shards);
        const auto per_owner = clock_bytes(owners);
        const auto process = clock_bytes(1);
        size_t stamp = 0;
        for (const auto& a : allocations) {
            stamp += good_size(a.request + sizeof(uint32_t)) - good_size(a.request);
            free_sized(a.header, good_size(a.request));
            if (a.value) free_sized(a.value, good_size(value_length));
        }
        std::printf("%s,%u,%u,%u,%u,%.5f,%.5f,%.5f,%.5f\n",
                    parser ? "parser" : "owner", shards, owners, keys, value_length,
                    double(per_shard)/keys, double(per_owner)/keys,
                    double(process)/keys, double(stamp)/keys);
    }
}
