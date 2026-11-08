// Exercise every partial clock allocation boundary, including an unreclaimed
// previous generation. Serverless; the production FlatStore owns all charges.
#define main store_regression_original_main
#include "store_regression.cc"
#undef main

namespace {
bool observe_allocations = false;
size_t fail_at = 0, calls = 0, live_allocations = 0;
void* tracked[128]{};
void release_tracked(void* pointer) {
    for (void*& p : tracked)
        if (p == pointer && p) {
            p = nullptr;
            --live_allocations;
            break;
        }
}
}
void* operator new(size_t bytes, const std::nothrow_t&) noexcept {
    if (observe_allocations && ++calls == fail_at) return nullptr;
    void* pointer = std::malloc(bytes);
    if (observe_allocations && pointer) {
        auto slot = std::find(std::begin(tracked), std::end(tracked), nullptr);
        require(slot != std::end(tracked), "bounded allocation inventory");
        *slot = pointer;
        ++live_allocations;
    }
    return pointer;
}
void operator delete(void* pointer) noexcept {
    release_tracked(pointer);
    std::free(pointer);
}
void operator delete(void* pointer, size_t) noexcept {
    release_tracked(pointer);
    std::free(pointer);
}

int main() {
    struct Retire {
        void* owner;
        void* payload;
        size_t bytes;
        ReadLocalRetireSink::ReclaimFn reclaim;
    };
    for (bool readers : {false, true})
        for (size_t failure = 1; failure <= 6; ++failure) {
            std::vector<Retire> retired;
            KvBlockCache blocks;
            FlatStore store;
            require(store.prepare_read_local(), "clock slot prepared");
            if (readers)
                store.configure_read_local(
                    true, {&retired,
                           [](void* context, void* owner, void* payload, size_t bytes,
                              ReadLocalRetireSink::ReclaimFn reclaim) {
                               static_cast<std::vector<Retire>*>(context)->push_back(
                                   {owner, payload, bytes, reclaim});
                           },
                           &blocks});
            put(store, "clock-key");
            const size_t baseline = store.object_bytes();
            // Hold the old clock's QSBR charge across a failed replacement enable.
            require(store.configure_object_idle(true), "initial clock");
            const size_t charged = store.object_bytes();
            require(store.configure_object_idle(false), "retire initial clock");
            require(store.object_bytes() == (readers ? charged : baseline), "retirement charge");
            const size_t before = store.object_bytes();
            calls = 0;
            fail_at = failure;
            observe_allocations = true;
            const bool enabled =
                store.configure_maxmemory(true, 1 << 20, MaxmemoryPolicy::NoEviction, 1);
            observe_allocations = false;
            require(calls == failure && !enabled, "allocation failure must fire");
            require(live_allocations == 0, "every partial clock allocation freed");
            require(store.object_idle_slot()->load() == nullptr, "failed clock never published");
            require(store.object_bytes() == before, "failed clock never charged");
            require(store.object_idle_seconds(
                        store.find(hash("clock-key"), Slice("clock-key", 9))) == 0,
                    "failed clock degrades OBJECT IDLETIME");
            for (const auto& r : retired) r.reclaim(r.owner, r.payload, r.bytes);
            retired.clear();
            require(store.object_bytes() == baseline, "old grace removes exactly old charge");
            require(store.configure_object_idle(true), "fresh enable after failure");
            auto* clock = store.object_idle_slot()->load();
            require(store.object_bytes() == baseline + clock->allocated_bytes(),
                    "live charge exact");
            require(store.configure_object_idle(false), "disable after recovery");
            for (const auto& r : retired) r.reclaim(r.owner, r.payload, r.bytes);
            require(store.object_bytes() == baseline, "recovered clock charge removed");
            blocks.release_all();
        }
    std::puts("PASS twelve clock allocation/grace schedules");
}
