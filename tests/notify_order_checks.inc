// R1/S failure paths in the existing serverless notify-oom row. No sockets/rings.
static unsigned notify_expired_records(const tomo::NotifyBatch* batch) {
    if (!batch) return 0;
    unsigned count = 0;
    for (unsigned i = 0; i < batch->inline_size; ++i)
        count += batch->inline_records[i].event == tomo::NotifyEventId::Expired;
    for (const auto& record : batch->spill)
        count += record.event == tomo::NotifyEventId::Expired;
    return count;
}

// Compile these same assertions against PRE too. The fallback is exactly PRE's
// five discard sites, not a replacement implementation of the candidate rule.
template <typename Batch>
static void notify_test_discard(std::atomic<Batch*>& slot) {
    if constexpr (requires { notify_discard_speculative(slot); })
        notify_discard_speculative(slot);
    else
        tomo::notify_discard_batch(slot.exchange(nullptr));
}

static void check_notify_overwrite_metadata() {
    using namespace tomo;
    Server server;
    Shard shard;
    shard.init_private(&server, 0, TypeLimits{}, StreamLimits{});
    auto& store = shard.store();
    store.configure_maxmemory(true, 1u << 20, MaxmemoryPolicy::AllKeysLfu, 5);
    Op source;
    args(source, {"SET", "notifyorder:live-policy", "new"});
    KvObj* value = store.make_set_string(source.arg(1), Slice("old"), -1, false);
    check(value && store.insert(source.hash, value) == FlatStore::InsertResult::Inserted,
          "overwrite metadata fixture insertion");
    // LFU increments at counts 4 and 5 with probability one. A redundant
    // notifying lookup would count this single SET twice, advancing 4 -> 6.
    value->set_eviction_meta(4);
    shard.set_notify_mask(NOTIFY_TRACKING);
    notify_execute_enter(shard, source, source);
    source.spec->handler_notify(shard, source);
    KvObj* current = store.find_no_touch(source.hash, source.arg(1));
    check(current == value && current->str_value().sv() == "new" && current->eviction_meta() == 5,
          "one armed SET overwrite counts exactly one LFU access");
    check(std::string_view(source.reply.data(), source.reply.size()) == "+OK\r\n",
          "overwrite metadata fixture SET succeeded");
    notify_discard_batch(notify_take_batch(source));
    notify_execute_leave(shard);
}

static void check_notify_overwrite_expiry() {
    using namespace tomo;
    for (bool read_local : {false, true}) {
        KvBlockCache blocks;
        {
            Server server;
            Shard shard;
            shard.init_private(&server, 0, TypeLimits{}, StreamLimits{});
            auto& store = shard.store();
            if (read_local) {
                check(store.prepare_read_local(), "overwrite fixture read-local allocation");
                store.configure_read_local(true, {nullptr,
                    [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn reclaim) {
                        reclaim(owner, p, n);
                    }, &blocks});
            }
            Op source;
            args(source, {"SET", "notifyorder:overwrite-expiry", "replacement"});
            const Slice key = source.arg(1);
            store.set_cached_now_ms(100);
            KvObj* old = store.make_set_string(key, Slice("old"), 200, false);
            check(old && store.insert(source.hash, old) == FlatStore::InsertResult::Inserted,
                  "overwrite fixture live TTL value");

            // An undecided, unrelated group keeps the store's version resolver
            // armed. A notifying find cannot physically reap while it is live.
            const Slice held("notifyorder:held-version");
            const uint64_t held_hash = FlatStore::hash_key(held);
            std::atomic<uint64_t> epoch{0};
            std::atomic<uint32_t> refs{1};
            std::atomic<bool> aborted{false};
            void* group = store.atomic_prepare_group(nullptr, 0, 1, &epoch, &refs, &aborted,
                42, nullptr, atomic_membership_bit(held_hash), true, held.n);
            check(group, "overwrite fixture held group allocation");
            check(!store.atomic_install_group(group, held_hash, held, nullptr),
                  "overwrite fixture absent held key");
            store.atomic_finish_group_install(0, 0);
            store.atomic_publish_group(group);
            check(store.atomic_pending_entries() == 1, "overwrite fixture version window opened");
            store.set_cached_now_ms(201);
            shard.set_notify_mask(NOTIFY_TRACKING);
            notify_execute_enter(shard, source, source);
            source.spec->handler_notify(shard, source);
            NotifyBatch* batch = notify_take_batch(source);
            check(batch && notify_expired_records(batch) == 1,
                  "raw SET expires exactly once with a live unrelated atomic version");
            check(std::string_view(source.reply.data(), source.reply.size()) == "+OK\r\n",
                  "overwrite fixture SET succeeded");
            notify_discard_batch(batch);
            notify_execute_leave(shard);
            epoch.store(1);
            for (unsigned i = 0; i < 10000 && store.atomic_pending_entries(); ++i)
                store.atomic_sweep(UINT64_MAX, UINT64_MAX, 1);
            check(store.atomic_pending_entries() == 0 && refs.load() == 0,
                  "overwrite fixture held group cleanup");
        }
        blocks.release_all();
    }
}

static void check_notify_order_failures() {
    check_notify_overwrite_metadata();
    check_notify_overwrite_expiry();
    using namespace tomo;
    Server server;
    Shard shard;
    shard.init_private(&server, 0, TypeLimits{}, StreamLimits{});
    Op source;
    args(source, {"GET", "notifyorder:physical"});
    notify_execute_enter(shard, source, source);
    shard.set_notify_mask(NOTIFY_TRACKING | NOTIFY_SAVE);
    const Slice key = source.arg(1);

    // A batch allocation failure must fall back, without counting a drop or two
    // SAVE changes. The one-shot failure must actually fire.
    fault(0);
    notify_flat_emit(&shard, NOTIFY_EXPIRED, NotifyEventId::Expired, key);
    const unsigned failed = netcmd_failures;
    fault(-1);
    check(failed == 1, "physical batch allocation failure fired");
    check(shard.notify_state_slot() && shard.notify_state_slot()->keyless.size() == 1,
          "physical allocation failure retains keyless event");
    check(shard.save_changes() == 1 && server.notify_events_dropped() == 0 &&
          server.notify_events_fired() == 1, "physical fallback counts once");
    shard.notify_state_slot()->keyless.clear();

    // Nested commands can name a key which is not pinned in the carrier argv.
    // A failed owned-string copy must use the same fallback, without a partial
    // record or a dangling reference to the caller's storage.
    NotifyBatch* batch = notify_get_or_create_batch(source);
    check(batch, "physical copied-key batch");
    const Slice copied_key("notifyorder:owned-expired-key-beyond-small-string-storage");
    const auto copy_before = shard.save_changes();
    fault(0);
    notify_flat_emit(&shard, NOTIFY_EXPIRED, NotifyEventId::Expired, copied_key);
    const auto copy_failures = netcmd_failures;
    fault(-1);
    check(copy_failures == 1 && batch->total == 0 && notify_expired_records(batch) == 0,
          "physical owned-key allocation failure fired without a partial record");
    check(shard.notify_state_slot()->keyless.size() == 1 &&
          shard.notify_state_slot()->keyless.front().key == copied_key.sv() &&
          shard.save_changes() == copy_before + 1 && server.notify_events_dropped() == 0,
          "owned-key failure retains one stable keyless event and SAVE observation");
    shard.notify_state_slot()->keyless.clear();
    notify_discard_batch(notify_take_batch(source));

    batch = notify_get_or_create_batch(source);
    check(batch, "physical mixed batch");
    std::vector<std::string> surviving_keys;
    for (unsigned i = 0; i < 20; ++i) {
        std::string owned = "notifyorder:nested-key-with-owned-storage:" + std::to_string(i);
        Op nested;
        if (i % 2) args(nested, {"SET", owned.c_str(), "v"});
        else args(nested, {"GET", owned.c_str()});
        notify_execute_source(shard, nested);
        if (i % 2) notify_record(shard, nested, NOTIFY_GENERIC, NotifyEventId::Set, nested.arg(1));
        else {
            surviving_keys.push_back(owned);
            notify_flat_emit(&shard, NOTIFY_EXPIRED, NotifyEventId::Expired, nested.arg(1));
        }
        notify_execute_source(shard, source);
        std::fill(owned.begin(), owned.end(), '#');
        // Both the nested argv and its original string die here. The carrier
        // names none of these keys. Poisoning the still-live original ensures
        // a borrowed slice cannot pass because freed storage retained old bytes.
    }
    check(batch->total == 20 && notify_expired_records(batch) == 10, "inline and spill both hold physical effects");
    std::atomic<NotifyBatch*> slot{notify_take_batch(source)};
    fault(0);
    notify_test_discard(slot);
    const unsigned allocations = netcmd_allocations;
    fault(-1);
    batch = slot.exchange(nullptr);
    check(allocations == 0 && batch && batch->total == 10 && notify_expired_records(batch) == 10,
          "script retry preserves physical effects without allocating");
    for (unsigned i = 0; i < 10; ++i) {
        const auto& record = i < 8 ? batch->inline_records[i] : batch->spill[i - 8];
        check(record.event == NotifyEventId::Expired && record.sequence == 2*i &&
              record.key.sv() == surviving_keys[i],
              "physical compaction preserves sequence and key lifetime across spill");
    }
    notify_discard_batch(batch);

    // A full batch and a failed spill growth both retain Expired through keyless.
    for (unsigned count : {8u, kNotifyBatchCap}) {
        batch = notify_get_or_create_batch(source);
        for (unsigned i = 0; i < count; ++i)
            notify_record(shard, source, NOTIFY_GENERIC, NotifyEventId::Set, key);
        const auto before = shard.save_changes();
        if (count == 8) fault(0);
        notify_flat_emit(&shard, NOTIFY_EXPIRED, NotifyEventId::Expired, key);
        const auto failures = netcmd_failures;
        fault(-1);
        check(count != 8 || failures == 1, "physical spill allocation failure fired");
        check(batch->total == count && notify_expired_records(batch) == 0 &&
              shard.notify_state_slot()->keyless.size() == 1,
              "full/spill-failed batch falls back exactly once");
        check(shard.save_changes() == before + 1 && server.notify_events_dropped() == 0,
              "full/spill fallback does not double-observe SAVE or count a drop");
        shard.notify_state_slot()->keyless.clear();
        slot.store(notify_take_batch(source));
        notify_test_discard(slot);
        check(!slot.load(), "purely speculative batch still discarded");
    }
    shard.set_notify_mask(0);
    fault(0);
    notify_flat_emit(&shard, NOTIFY_EXPIRED, NotifyEventId::Expired, key);
    const auto off_allocations = netcmd_allocations;
    fault(-1);
    check(!off_allocations && !source.has_notify_state() && shard.notify_state_slot()->keyless.empty(),
          "disabled sink allocates nothing");
    notify_execute_leave(shard);
}
