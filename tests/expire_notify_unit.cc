// A script reservation without version records leaves find() on physical expiry.
// No worker, socket, wall-clock delay or synthetic notification path is involved.
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "src/store/flatstore.h"

using namespace tomo;

static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL expiry notification: %s\n", why); std::_Exit(1); }
}

int main() {
    FlatStore store{64};
    const Slice key("expires"), reserved("script-reservation");
    const uint64_t hash = FlatStore::hash_key(key), pin_hash = FlatStore::hash_key(reserved);
    uint64_t expired = 0;
    store.bind_expired_counter(&expired);
    store.set_cached_now_ms(1000);
    KvObj* value = kvobj_new_string(key, Slice("live"), 2000);
    require(value && store.insert(hash, value) == FlatStore::InsertResult::Inserted, "insert live key");
    require(store.atomic_script_pin(pin_hash, reserved), "install real script reservation");
    require(store.atomic_has_records() && store.atomic_pending_entries() == 0,
            "reservation exists without a version record (required window)");
    std::vector<NotifyEventId> events;
    FlatNotifySink sink{&events, [](void*, uint32_t) { return true; },
        [](void* context, uint32_t, NotifyEventId event, Slice) {
            static_cast<std::vector<NotifyEventId>*>(context)->push_back(event);
        }};
    require(store.find_notify(hash, key, &sink) == value && events.empty(), "live arm emits nothing");
    store.set_cached_now_ms(2001);
    require(!store.find_notify(hash, key, &sink) && expired == 1 &&
            !store.find_resident(hash, key), "physical expiry really removed the key");
    require(events == std::vector<NotifyEventId>{NotifyEventId::Expired, NotifyEventId::Keymiss},
            "reservation-only physical expiry emits expired then keymiss");
    require(!store.find_notify(hash, key, &sink) && expired == 1 && events.size() == 3 &&
            events.back() == NotifyEventId::Keymiss, "later miss never repeats expiry");
    store.atomic_script_unpin(pin_hash, reserved);
    require(!store.atomic_has_records(), "reservation released");
    std::puts("PASS reservation-only physical expiry notification");
}
