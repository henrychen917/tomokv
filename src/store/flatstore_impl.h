// FlatStore's private storage, snapshot, read-local and reclamation helpers. Included by
// flatstore.h immediately after FlatStore, inside namespace tomo, in each using translation unit.
// Owner mutations release-publish armed slot/topology changes; foreign capture acquires and
// validates topology under a caller-provided QSBR lifetime. Retired allocations reach the
// owner's sink before reuse, while wire borrows can extend object lifetime beyond QSBR.
// Snapshot emission resumes at saved offsets under byte/chunk back-pressure. Capacity and
// retirement failures follow the declarations' contracts; helpers do not transfer shard ownership.
#pragma once

[[gnu::noinline]] inline KvObj* FlatStore::expire_found(int t, uint64_t h, Slice key) {
    if (snapshot_active_ && t == 1) return nullptr;
    if (client_pause_expiry_held()) return nullptr;
    // Logical expiry never needs reclamation. With a full armed ring, leave the object and
    // its deadline index resident for owner maintenance. Only the eventual physical delete
    // emits expiry/AOF/accounting effects; repeated reads cannot enqueue or wait for grace.
    if (!read_retirement_available()) return nullptr;
    (void)aof_.record_delete(key);
    erase_in(t, h, key);
    if (expired_counter_) (*expired_counter_)++;
    return nullptr;
}

inline bool FlatStore::insert_into(int t, uint64_t h, KvObj* o, bool fresh) {
    if (__builtin_expect(read_local_enabled_, false)) return insert_into_read_local(t, h, o, fresh);
    const uint16_t tag = tag_of(h);
    const Slice key = o->key();
    uint32_t i = slot_start(t, h);
    int32_t first_tomb = -1;
    for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
        const uint64_t w = tab_[t][i];
        if (w == 0) {
            if (first_tomb >= 0) {
                tab_[t][first_tomb] = make_word(tag, o);
                tombs_[t]--;
            } else {
                tab_[t][i] = make_word(tag, o);
            }
            live_[t]++;
            if (fresh) {
                if constexpr (!kSingleDatabase) storesize_replace(nullptr, o);
                obj_bytes_ += kvobj_size(o);
                (void)this->track_expire(h, o);
            }
            return true;
        }
        KvObj* cur = ptr_of(w);
        if (!cur) {
            if (first_tomb < 0) first_tomb = static_cast<int32_t>(i);
        }
        // Use key_mem_eq here to keep the byte comparison out of this register-heavy probe loop.
        // A full comparison follows a 15-bit tag match (replacement or collision); it compares
        // the same key bytes as key_eq. read_local_capture_in uses the same call-based policy.
        else if (tag_of_word(w) == tag && cur->key().key_mem_eq(key)) {
            if (fresh && deadline_elapsed(h, cur, cached_now_ms_) && expired_counter_)
                (*expired_counter_)++;
            if (fresh) {
                if constexpr (!kSingleDatabase) storesize_replace(cur, o);
                (void)this->track_expire(h, o);
            }
            retire_obj(cur, o);  // replace in place; live_ unchanged
            tab_[t][i] = make_word(tag, o);
            if (fresh) obj_bytes_ += kvobj_size(o);
            return true;
        }
        i = (i + 1) & mask_[t];
    }
    return false;  // unreachable while the load factor holds
}

inline void FlatStore::notify_emit(FlatNotifySink* sink, uint32_t cls, NotifyEventId event,
                                   Slice key) {
    if (sink && sink->enabled && sink->enabled(sink->context, cls) && sink->emit)
        sink->emit(sink->context, cls, event, key);
}

inline bool FlatStore::erase_in(int t, uint64_t h, Slice key, bool* was_expired,
                                const KvObj* replacement) {
    if (__builtin_expect(read_local_enabled_, false))
        return erase_in_read_local(t, h, key, was_expired, replacement);
    if (!tab_[t]) return false;
    const uint16_t tag = tag_of(h);
    uint32_t i = slot_start(t, h);
    for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
        const uint64_t w = tab_[t][i];
        if (w == 0) return false;
        KvObj* o = ptr_of(w);
        if (o && tag_of_word(w) == tag && o->key().key_eq(key)) {
            if (was_expired) {
                *was_expired = deadline_elapsed(h, o, cached_now_ms_);
            }
            if constexpr (!kSingleDatabase) storesize_replace(o, nullptr);
            untrack_expire(h);
            if (replacement)
                retire_obj(o, replacement);
            else
                retire_obj(o);
            tab_[t][i] = kTombBit;  // DEAD: non-zero, ptr == 0
            live_[t]--;
            tombs_[t]++;
            return true;
        }
        i = (i + 1) & mask_[t];
    }
    return false;
}

inline FlatStore::TtlResult FlatStore::rewrite_expire(uint64_t h, KvObj* old,
                                                      int64_t expire_at_ms) {
    if (__builtin_expect(read_local_enabled_, false))
        return rewrite_expire_read_local(h, old, expire_at_ms);
    KvObj* replacement = kvobj_reheader(old, expire_at_ms);
    if (!replacement) return TtlResult::Oom;
    if (maxmemory_enabled_) replacement->set_eviction_meta(old->eviction_meta());

    const bool moves_collection =
        static_cast<Type>(old->type) != Type::String && static_cast<Enc>(old->enc) == Enc::Extern;
    if (moves_collection) {
        old->flags &= static_cast<uint8_t>(~KvObjFlags::OwnsExtern);
        replacement->flags |= KvObjFlags::OwnsExtern;
    }
    const InsertResult inserted = insert(h, replacement);
    if (inserted != InsertResult::Inserted) {
        if (moves_collection) {
            old->flags |= KvObjFlags::OwnsExtern;
            replacement->flags &= static_cast<uint8_t>(~KvObjFlags::OwnsExtern);
        }
        kvobj_free(replacement);
        return inserted == InsertResult::MaxmemoryOom ? TtlResult::MaxmemoryOom : TtlResult::Oom;
    }
    return TtlResult::Updated;
}

inline FlatStore::OverwriteResult FlatStore::try_overwrite_read_local(uint64_t, Slice, Slice) {
    // Published values stay immutable for the whole grace period.
    return OverwriteResult::NotPossible;
}

inline bool FlatStore::snapshot_mark_read_local(int32_t shard_id, int64_t cut_ms) {
    if (!snapshot_prepared_ || snapshot_active_ || rehashing()) return false;
    ReadLocalTableGuard table_change(*this);
    read_local_topology_store(&tab_[1], tab_[0]);
    read_local_topology_store(&cap_[1], cap_[0]);
    read_local_topology_store(&mask_[1], mask_[0]);
    live_[1] = live_[0];
    tombs_[1] = tombs_[0];
    read_local_topology_store(&tab_[0], snapshot_new_tab_);
    read_local_topology_store(&cap_[0], snapshot_new_cap_);
    read_local_topology_store(&mask_[0], snapshot_new_cap_ - 1);
    live_[0] = tombs_[0] = 0;
    snapshot_new_tab_ = nullptr;
    snapshot_new_cap_ = 0;
    snapshot_prepared_ = false;
    rehash_pos_ = 0;
    snapshot_active_ = true;
    snapshot_shard_id_ = shard_id;
    snapshot_cut_ms_ = cut_ms;
    snapshot_pos_ = 0;
    snapshot_sequence_ = 0;
    snapshot_failed_ = false;
    snapshot_finished_ = false;
    snapshot_build_ = make_snapshot_chunk(SnapshotFrameBegin);
    snapshot_ready_.reset();
    snapshot_record_ = {};
    return snapshot_build_ != nullptr;
}

inline FlatStore::SnapshotWriteResult FlatStore::snapshot_prepare_write_read_local(uint64_t h,
                                                                                   Slice key) {
    if (!snapshot_active_) return SnapshotWriteResult::Ready;
    if (snapshot_failed_) return SnapshotWriteResult::Error;
    if (find_in(0, h, key)) return SnapshotWriteResult::Ready;
    uint32_t slot = 0;
    KvObj* object = find_slot_in(1, h, key, slot);
    if (!object || slot < snapshot_pos_ || (tab_[1][slot] & kTombBit))
        return SnapshotWriteResult::Ready;
    if (deadline_elapsed(h, object, snapshot_cut_ms_)) {
        read_local_slot_store(&tab_[1][slot], tab_[1][slot] | kTombBit);
        return SnapshotWriteResult::Ready;
    }
    if (snapshot_record_.active) return SnapshotWriteResult::Pending;
    if (!snapshot_start_record(object, slot, true)) return SnapshotWriteResult::Error;
    snapshot_preimages_++;
    return SnapshotWriteResult::Pending;
}

inline uint32_t FlatStore::snapshot_progress_read_local(uint32_t byte_budget,
                                                        uint32_t slot_budget) {
    if (!snapshot_active_ || snapshot_failed_ || snapshot_ready_) return 0;
    uint32_t work = 0;
    while (byte_budget && !snapshot_ready_ && !snapshot_failed_) {
        if (snapshot_record_.active) {
            const uint32_t before = byte_budget;
            snapshot_progress_record_read_local(byte_budget);
            work += before - byte_budget;
            if (snapshot_record_.active || snapshot_ready_) break;
            continue;
        }
        if (snapshot_pos_ >= cap_[1]) {
            snapshot_finish_stream();
            break;
        }
        if (!slot_budget) break;
        const uint32_t slot = snapshot_pos_;
        const uint64_t word = tab_[1][slot];
        KvObj* object = ptr_of(word);
        slot_budget--;
        work++;
        if (!object) {
            snapshot_pos_++;
            continue;
        }
        if (word & kTombBit) {
            read_local_slot_store(&tab_[1][slot], word & ~kTombBit);
            snapshot_pos_++;
            continue;
        }
        if (deadline_elapsed(hash_key(object->key()), object, snapshot_cut_ms_)) {
            snapshot_pos_++;
            continue;
        }
        if (!snapshot_start_record(object, slot, false)) break;
    }
    return work;
}

// Owner-side armed serializer continuation; keep the record's borrowed object stable.
// A ready chunk or exhausted budget pauses at saved offsets. Invalid state, hook failure or
// allocation failure sets snapshot_failed_. Completion release-stores the pre-image mark or
// advances the owner cursor, without taking ownership of the serialized object.
inline void FlatStore::snapshot_progress_record_read_local(uint32_t& budget) {
    SnapshotRecordState& state = snapshot_record_;
    const KvObj* object = state.value.object;
    if (!state.active || !object) {
        snapshot_failed_ = true;
        return;
    }

    if (state.header_offset < kSnapshotRecordHeader) {
        const uint32_t emitted_bytes =
            snapshot_emit(state.header + state.header_offset,
                          kSnapshotRecordHeader - state.header_offset, budget);
        state.header_offset += emitted_bytes;
        if (state.header_offset != kSnapshotRecordHeader || snapshot_ready_) return;
    }
    if (state.key_offset < object->klen()) {
        const uint32_t emitted_bytes =
            snapshot_emit(reinterpret_cast<const uint8_t*>(object->key_ptr()) + state.key_offset,
                          object->klen() - state.key_offset, budget);
        state.key_offset += emitted_bytes;
        if (state.key_offset != object->klen() || snapshot_ready_) return;
    }
    while (state.value.offset < state.value.total && budget && !snapshot_ready_) {
        if (!snapshot_build_) snapshot_build_ = make_snapshot_chunk(0);
        if (!snapshot_build_) return;
        const size_t room = kSnapshotChunkBytes - snapshot_build_->bytes.size();
        const size_t capacity = std::min<size_t>(room, budget);
        const size_t old_size = snapshot_build_->bytes.size();
        try {
            snapshot_build_->bytes.resize(old_size + capacity);
        } catch (const std::bad_alloc&) {
            snapshot_failed_ = true;
            return;
        }
        size_t written = 0;
        const SnapshotHookStatus status = state.hooks.read_save(
            state.value, snapshot_build_->bytes.data() + old_size, capacity, written);
        if (status != SnapshotHookStatus::Ok || written > capacity ||
            (written == 0 && state.value.offset < state.value.total)) {
            snapshot_build_->bytes.resize(old_size);
            snapshot_failed_ = true;
            return;
        }
        snapshot_build_->bytes.resize(old_size + written);
        budget -= static_cast<uint32_t>(written);
        if (snapshot_build_->bytes.size() == kSnapshotChunkBytes) snapshot_seal(0);
    }
    if (state.value.offset != state.value.total || snapshot_ready_) return;

    const bool preimage = state.preimage;
    const uint32_t slot = state.slot;
    snapshot_record_ = {};
    if (preimage) {
        read_local_slot_store(&tab_[1][slot], tab_[1][slot] | kTombBit);
    } else {
        snapshot_pos_++;
    }
}

inline FlatStore::TtlResult FlatStore::set_expire_read_local(uint64_t h, Slice key,
                                                             int64_t expire_at_ms) {
    KvObj* old = find(h, key);
    if (!old) return TtlResult::Missing;
    return rewrite_expire_read_local(h, old, expire_at_ms);
}

inline FlatStore::TtlResult FlatStore::set_expire_notify_read_local(uint64_t h, Slice key,
                                                                    int64_t expire_at_ms,
                                                                    FlatNotifySink* sink) {
    KvObj* old = find_notify(h, key, sink);
    if (!old) return TtlResult::Missing;
    return rewrite_expire_read_local(h, old, expire_at_ms);
}

inline FlatStore::InsertResult FlatStore::insert_read_local(uint64_t h, KvObj* o) {
    const bool capturing = rehashing() && snapshot_active_;
    if (rehashing()) {
        if (!capturing) rehash_step_read_local();
    } else {
        if (!maybe_start_grow()) return InsertResult::Failed;
    }
    if (static_cast<uint64_t>(live_[0]) + tombs_[0] + 1 >= cap_[0] && snapshot_prepared_ &&
        !find_in(0, h, o->key()))
        return InsertResult::Failed;
    if (capturing) {
        const bool exists = find_in(0, h, o->key()) || find_in(1, h, o->key());
        if (!exists && static_cast<uint64_t>(live_[0]) + tombs_[0] + live_[1] + 1 >= cap_[0])
            return InsertResult::Failed;
    }
    if (__builtin_expect(maxmemory_enabled_, false)) {
        if (!snapshot_active_ &&
            !make_room_for(o->key(), kvobj_size(o) + object_idle_allocation_bytes(o)))
            return InsertResult::MaxmemoryOom;
        if (!object_idle_install(h, o)) return InsertResult::Failed;
        if (!snapshot_active_) {
            if (o->eviction_meta() == 0) initialize_meta_read_local(o);
        }
    }
    const bool moves_from_old = rehashing() && find_in(1, h, o->key()) != nullptr;
    ReadLocalTableGuard table_move(*this, moves_from_old);
    if (rehashing()) {
        bool expired = false;
        if (erase_in_read_local(1, h, o->key(), &expired, o) && expired && expired_counter_)
            (*expired_counter_)++;
    }
    return insert_into_read_local(0, h, o, true) ? InsertResult::Inserted : InsertResult::Failed;
}

inline bool FlatStore::erase_read_local(uint64_t h, Slice key) {
    if (rehashing() && !snapshot_active_) rehash_step_read_local();
    bool expired = false;
    if (erase_in_read_local(0, h, key, &expired)) {
        maybe_start_shrink();
        if (expired && expired_counter_) (*expired_counter_)++;
        return !expired;
    }
    if (rehashing() && erase_in_read_local(1, h, key, &expired)) {
        maybe_start_shrink();
        if (expired && expired_counter_) (*expired_counter_)++;
        return !expired;
    }
    return false;
}

inline void FlatStore::clear_read_local() {
    uint64_t* fresh = allocate_table(clear_capacity());
    // A clear rewrites every answer without naming a key. Poison the per-key filter for its
    // duration so a multi-key local read straddling it sees every cell epoch move; the poison
    // opens before the first slot store and closes after the table bracket below.
    ForeignReadPoisonGuard broad_change(*this);
    ReadLocalTableGuard table_change(*this);
    expires_.clear();
    for (int t = 0; t < 2; t++) {
        if (!tab_[t]) continue;
        for (uint32_t i = 0; i < cap_[t]; i++) {
            if (KvObj* object = ptr_of(tab_[t][i])) {
                read_local_slot_store(&tab_[t][i], kTombBit);
                retire_obj_read_local(object);
            }
        }
        if (t == 0 && !fresh) {
            for (uint32_t i = 0; i < cap_[0]; i++) read_local_slot_store(&tab_[0][i], 0);
            live_[0] = tombs_[0] = 0;
            continue;
        }
        uint64_t* retired = tab_[t];
        read_local_topology_store(&tab_[t], static_cast<uint64_t*>(nullptr));
        read_local_topology_store(&cap_[t], uint32_t{0});
        read_local_topology_store(&mask_[t], uint32_t{0});
        live_[t] = tombs_[t] = 0;
        retire_table_read_local(retired);
    }
    field_expires_.clear();
    field_ttl_gate_ = 0;
    field_ttl_index_incomplete_ = false;
    rehash_pos_ = 0;
    // The keyspace this cache was serving has gone. Nothing is about to ask for those blocks,
    // and the per-put ceiling would refuse new ones anyway (obj_bytes_ is now 0), so hand them
    // straight back rather than holding them until the next write pressure.
    read_local_cache_release_all();
    // Both tables went to the object ring, so no resize owns the reservation now -- unless a
    // prepared snapshot does: mark publishes its post-cut table and the post-capture merge
    // hands the cut table to the owner FIFO with the record snapshot_prepare() reserved.
    if (!snapshot_prepared_) read_local_store_state_armed().resize_retirement.reset();
    if (fresh) install_empty_table_read_local(0, fresh, clear_capacity());
}

inline void FlatStore::clear_during_snapshot_read_local() {
    ForeignReadPoisonGuard broad_change(*this);
    ReadLocalTableGuard table_change(*this);
    expires_.clear();
    for (int t = 0; t < 2; t++) {
        if (!tab_[t]) continue;
        for (uint32_t i = 0; i < cap_[t]; i++) {
            if (KvObj* object = ptr_of(tab_[t][i])) {
                read_local_slot_store(&tab_[t][i], kTombBit);
                retire_obj_read_local(object);
                live_[t]--;
                tombs_[t]++;
            }
        }
    }
    field_expires_.clear();
    field_ttl_gate_ = 0;
    field_ttl_index_incomplete_ = false;
}

inline void FlatStore::initialize_meta_read_local(KvObj* o) {
    if (maxmemory_policy_is_lru(maxmemory_policy_)) {
        write_eviction_meta_read_local(o, lru_clock());
    } else if (maxmemory_policy_is_lfu(maxmemory_policy_)) {
        write_eviction_meta_read_local(o, 5);
    }
}

inline void FlatStore::touch_read_local(KvObj* o) {
    note_object_access(o, cached_now_ms_);
    if (maxmemory_policy_is_lru(maxmemory_policy_)) {
        write_eviction_meta_read_local(o, lru_clock());
        return;
    }
    if (!maxmemory_policy_is_lfu(maxmemory_policy_)) return;

    uint8_t count = o->eviction_meta();
    if (count == 0) count = 5;
    const uint32_t base = count > 5 ? static_cast<uint32_t>(count - 5) : 0;
    const uint32_t denominator = base * 10 + 1;
    if (count < 31 && next_random() % denominator == 0) count++;
    write_eviction_meta_read_local(o, count);
}

// Armed owner eviction sample: configure_maxmemory bounds samples to 1..64. ProtectKey
// excludes the incoming key; pending versions/intents are ineligible. Returns a borrowed
// resident pointer or nullptr, updating LFU metadata through relaxed-load/release-store.
// Sampling uses stack workspace; notification callbacks own any allocation/back-pressure.
template <bool ProtectKey>
inline KvObj* FlatStore::choose_victim_read_local(Slice protected_key) {
    KvObj* best = nullptr;
    KvObj* seen[64];
    uint32_t seen_count = 0;
    uint64_t best_score = 0;
    for (uint32_t i = 0; i < maxmemory_samples_; i++) {
        KvObj* candidate = maxmemory_policy_is_volatile(maxmemory_policy_)
                               ? random_volatile_candidate()
                               : random_allkeys_candidate();
        if (!candidate) continue;
        if constexpr (ProtectKey)
            if (candidate->key().key_eq(protected_key)) continue;
        if (atomic_needs_version(hash_key(candidate->key()), candidate->key())) continue;
        bool duplicate = false;
        for (uint32_t j = 0; j < seen_count; j++)
            if (seen[j] == candidate) {
                duplicate = true;
                break;
            }
        if (duplicate) continue;
        seen[seen_count++] = candidate;

        uint64_t score = 0;
        switch (maxmemory_policy_) {
            case MaxmemoryPolicy::AllKeysRandom:
            case MaxmemoryPolicy::VolatileRandom:
                score = next_random();
                break;
            case MaxmemoryPolicy::AllKeysLru:
            case MaxmemoryPolicy::VolatileLru: {
                const uint8_t age =
                    static_cast<uint8_t>((lru_clock() - candidate->eviction_meta()) & 0x1f);
                score = (static_cast<uint64_t>(age) << 56) | (next_random() & ((1ULL << 56) - 1));
                break;
            }
            case MaxmemoryPolicy::AllKeysLfu:
            case MaxmemoryPolicy::VolatileLfu: {
                uint8_t count = candidate->eviction_meta();
                if (count) write_eviction_meta_read_local(candidate, --count);
                score = (static_cast<uint64_t>(31 - count) << 56) |
                        (next_random() & ((1ULL << 56) - 1));
                break;
            }
            case MaxmemoryPolicy::VolatileTtl:
                score = std::numeric_limits<uint64_t>::max() -
                        static_cast<uint64_t>(deadline(hash_key(candidate->key()), candidate));
                break;
            case MaxmemoryPolicy::NoEviction:
                return nullptr;
        }
        if (!best || score > best_score) {
            best = candidate;
            best_score = score;
        }
    }
    if (best) {
        const bool expired = deadline_elapsed(hash_key(best->key()), best, cached_now_ms_);
        notify_flat_store_emit(this, expired ? NOTIFY_EXPIRED : NOTIFY_EVICTED,
                               expired ? NotifyEventId::Expired : NotifyEventId::Evicted,
                               best->key());
    }
    return best;
}

inline void FlatStore::install_empty_table_read_local(int t, uint64_t* table, uint32_t cap) {
    ReadLocalTableGuard table_change(*this);
    read_local_topology_store(&tab_[t], table);
    read_local_topology_store(&cap_[t], cap);
    read_local_topology_store(&mask_[t], cap - 1);
    live_[t] = 0;
    tombs_[t] = 0;
}

inline bool FlatStore::insert_into_read_local(int t, uint64_t h, KvObj* o, bool track_expire) {
    const uint16_t tag = tag_of(h);
    const Slice key = o->key();
    uint32_t i = slot_start(t, h);
    int32_t first_tomb = -1;
    for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
        const uint64_t w = tab_[t][i];
        if (w == 0) {
            if (first_tomb >= 0) {
                read_local_slot_store(&tab_[t][first_tomb], make_word(tag, o));
                tombs_[t]--;
            } else {
                read_local_slot_store(&tab_[t][i], make_word(tag, o));
            }
            live_[t]++;
            const size_t added_bytes = kvobj_capacity(o) + read_local_external_bytes(o);
            obj_bytes_ += added_bytes;
            if (track_expire) {
                if constexpr (!kSingleDatabase) storesize_replace(nullptr, o);
                (void)this->track_expire(h, o);
                if (o->expire_at_ms() < 0) {
                }
            }
            return true;
        }
        KvObj* cur = ptr_of(w);
        if (!cur) {
            if (first_tomb < 0) first_tomb = static_cast<int32_t>(i);
        }
        // Match insert_into's call-based byte comparison to limit probe-loop register pressure.
        else if (tag_of_word(w) == tag && cur->key().key_mem_eq(key)) {
            if (track_expire && deadline_elapsed(h, cur, cached_now_ms_) && expired_counter_)
                (*expired_counter_)++;
            // An acquiring reader that starts after the retirement stamp must no longer be
            // able to acquire the displaced pointer.
            if (track_expire) {
                if constexpr (!kSingleDatabase) storesize_replace(cur, o);
                (void)this->track_expire(h, o);
            }
            read_local_slot_store(&tab_[t][i], make_word(tag, o));
            retire_obj_read_local(cur, o);
            const size_t added_bytes = kvobj_capacity(o) + read_local_external_bytes(o);
            obj_bytes_ += added_bytes;
            if (track_expire && o->expire_at_ms() < 0) {
            }
            return true;
        }
        i = (i + 1) & mask_[t];
    }
    return false;
}

inline bool FlatStore::erase_in_read_local(int t, uint64_t h, Slice key, bool* was_expired,
                                           const KvObj* replacement) {
    if (!tab_[t]) return false;
    const uint16_t tag = tag_of(h);
    uint32_t i = slot_start(t, h);
    for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
        const uint64_t w = tab_[t][i];
        if (w == 0) return false;
        KvObj* o = ptr_of(w);
        if (o && tag_of_word(w) == tag && o->key().key_eq(key)) {
            if (was_expired) {
                *was_expired = deadline_elapsed(h, o, cached_now_ms_);
            }
            if constexpr (!kSingleDatabase) storesize_replace(o, nullptr);
            untrack_expire(h);
            read_local_slot_store(&tab_[t][i], kTombBit);
            retire_obj_read_local(o, replacement);
            live_[t]--;
            tombs_[t]++;
            return true;
        }
        i = (i + 1) & mask_[t];
    }
    return false;
}

inline FlatStore::TtlResult FlatStore::rewrite_expire_read_local(uint64_t h, KvObj* old,
                                                                 int64_t expire_at_ms) {
    KvObj* replacement = kvobj_reheader(old, expire_at_ms);
    if (!replacement) return TtlResult::Oom;
    if (maxmemory_enabled_) replacement->set_eviction_meta(old->eviction_meta());

    const bool moves_collection =
        static_cast<Type>(old->type) != Type::String && static_cast<Enc>(old->enc) == Enc::Extern;
    if (moves_collection) {
        write_object_flags_read_local(
            old, static_cast<uint8_t>(old->flags & static_cast<uint8_t>(~KvObjFlags::OwnsExtern)));
        write_object_flags_read_local(
            replacement, static_cast<uint8_t>(replacement->flags | KvObjFlags::OwnsExtern));
    }
    const InsertResult inserted = insert_read_local(h, replacement);
    if (inserted != InsertResult::Inserted) {
        if (moves_collection) {
            write_object_flags_read_local(
                old, static_cast<uint8_t>(old->flags | KvObjFlags::OwnsExtern));
            write_object_flags_read_local(
                replacement, static_cast<uint8_t>(replacement->flags &
                                                  static_cast<uint8_t>(~KvObjFlags::OwnsExtern)));
        }
        kvobj_free(replacement);
        return inserted == InsertResult::MaxmemoryOom ? TtlResult::MaxmemoryOom : TtlResult::Oom;
    }
    return TtlResult::Updated;
}

inline size_t FlatStore::read_local_external_bytes(const KvObj* object) {
    return static_cast<Enc>(object->enc) == Enc::Extern ? kvobj_external_bytes(object) : 0;
}

inline size_t FlatStore::retiring_external_bytes(const KvObj* object, const KvObj* replacement) {
    return static_cast<Enc>(object->enc) == Enc::Extern
               ? kvobj_external_bytes<true>(object, this, replacement)
               : 0;
}

inline void FlatStore::retire_obj_read_local(KvObj* object, const KvObj* replacement) {
    const size_t capacity = kvobj_capacity(object);
    const size_t bytes = capacity + retiring_external_bytes(object, replacement);
    obj_bytes_ -= bytes;
    read_local_store_state_armed().retire_sink.retire(this, object, capacity,
                                                      &FlatStore::read_local_reclaim_object);
}

inline bool FlatStore::start_rehash_read_local(uint32_t newcap) {
    if (rehashing()) return true;
    if (newcap < kMinCap) newcap = kMinCap;
    uint64_t* fresh = allocate_table(newcap);
    if (!fresh) return false;
    if (!prepare_resize_retirement()) {
        std::free(fresh);
        return false;
    }
    ReadLocalTableGuard table_change(*this);
    if (rehash_counter_) (*rehash_counter_)++;
    read_local_topology_store(&tab_[1], tab_[0]);
    read_local_topology_store(&cap_[1], cap_[0]);
    read_local_topology_store(&mask_[1], mask_[0]);
    live_[1] = live_[0];
    tombs_[1] = tombs_[0];
    install_empty_table_read_local(0, fresh, newcap);
    rehash_pos_ = 0;
    return true;
}

inline void FlatStore::rehash_step_read_local() {
    ReadLocalTableGuard table_change(*this);
    uint32_t budget = kRehashSlotsPerOp;
    while (budget && rehash_pos_ < cap_[1]) {
        const uint64_t w = tab_[1][rehash_pos_];
        if (KvObj* o = ptr_of(w)) {
            // Publish the destination before withdrawing the old slot. A refused insertion
            // must leave its source and accounting intact.
            if (!insert_into_read_local(0, hash_key(o->key()), o, false)) return;
            read_local_slot_store(&tab_[1][rehash_pos_], kTombBit);
            live_[1]--;
            tombs_[1]++;
            obj_bytes_ -= kvobj_size(o);
        }
        rehash_pos_++;
        budget--;
    }
    if (rehash_pos_ >= cap_[1]) {
        uint64_t* retired = tab_[1];
        read_local_topology_store(&tab_[1], static_cast<uint64_t*>(nullptr));
        read_local_topology_store(&cap_[1], uint32_t{0});
        read_local_topology_store(&mask_[1], uint32_t{0});
        live_[1] = 0;
        tombs_[1] = 0;
        rehash_pos_ = 0;
        auto& state = read_local_store_state_armed();
        if (state.retire_sink.defer_resize) {
            if (!state.resize_retirement) std::abort();
            state.retire_sink.defer_resize(state.retire_sink.context,
                                           state.resize_retirement.release(), retired);
        } else {
            retire_table_read_local(retired);  // synchronous serverless sink
        }
    }
}

inline bool FlatStore::prepare_resize_retirement() {
    auto& record = read_local_store_state_required().resize_retirement;
    if (!record) record.reset(new (std::nothrow) ResizeRetirement);
    return record != nullptr;
}

template <typename T>
inline void FlatStore::read_local_topology_store(T* location, T value) {
    if (!read_local_enabled_ || !read_local_store_state_required().table_mutation_depth)
        std::abort();
    __atomic_store_n(location, value, __ATOMIC_RELEASE);
}

inline void FlatStore::read_local_slot_store(uint64_t* location, uint64_t value) {
    __atomic_store_n(location, value, __ATOMIC_RELEASE);
}

inline uint64_t FlatStore::read_local_slot_load(const uint64_t* location) {
    return __atomic_load_n(location, __ATOMIC_ACQUIRE);
}

inline bool FlatStore::read_local_probe_sequence_equal(uint64_t first, uint64_t second) {
    // The pending bit is an independent owner-fallback indication. Per-key filter publication
    // may toggle it for an unrelated key without changing topology, so it is not part of the
    // one-attempt topology validation; a mismatch returns to owner execution.
    return ((first ^ second) & ~kReadLocalPendingBit) == 0;
}

inline bool FlatStore::read_local_snapshot_topology(uint64_t state,
                                                    ReadLocalTopology& topology) const {
    for (int table = 0; table < 2; table++) {
        topology.tables[table].slots = __atomic_load_n(&tab_[table], __ATOMIC_ACQUIRE);
        topology.tables[table].cap = __atomic_load_n(&cap_[table], __ATOMIC_ACQUIRE);
        topology.tables[table].mask = __atomic_load_n(&mask_[table], __ATOMIC_ACQUIRE);
    }
    // Validate before using a pointer/capacity pair. A final validation alone is too late: a
    // mixed grow/shrink snapshot could otherwise calculate an out-of-bounds slot first.
    return read_local_probe_sequence_equal(read_local_state_acquire(), state);
}

inline const KvObj* FlatStore::read_local_capture_in(const ReadLocalTable& table, uint64_t hash,
                                                     Slice key,
                                                     const uint64_t*& captured_slot) const {
    captured_slot = nullptr;
    if (!table.slots || !table.cap) return nullptr;
    const uint16_t tag = tag_of(hash);
    uint32_t slot = static_cast<uint32_t>(mix64(hash)) & table.mask;
    for (uint32_t probes = 0; probes <= table.cap; probes++) {
        captured_slot = table.slots + slot;
        const uint64_t word = read_local_slot_load(captured_slot);
        if (word == 0) return nullptr;
        const KvObj* object = ptr_of(word);
        if (object && tag_of_word(word) == tag) {
            const uint8_t flags = object->read_local_flags();
            // Use key_mem_eq as insert_into does: topology, cursor, mask and tag already occupy
            // registers, so a call avoids an inlined byte comparison adding spill pressure.
            // This capture walk is reached through the armed read-local API; the unarmed path
            // does not call it. key_eq and key_mem_eq compare the same key bytes.
            if (object->read_local_key(flags).key_mem_eq(key)) return object;
        }
        slot = (slot + 1) & table.mask;
    }
    return nullptr;
}

inline void FlatStore::read_local_prefetch_object(const KvObj* object) {
    __builtin_prefetch(object, 0, 1);
    if (static_cast<Type>(object->type) != Type::String) return;

    const uint8_t flags = object->read_local_flags();
    const char* value = object->read_local_key_ptr(flags) + object->read_local_klen(flags);
    if (object->encoding() != Enc::Extern) {
        __builtin_prefetch(value, 0, 1);
        return;
    }

    const void* external = nullptr;
    std::memcpy(&external, value, sizeof(external));
    if (external) __builtin_prefetch(external, 0, 1);
}

inline void FlatStore::write_eviction_meta_read_local(KvObj* object, uint8_t meta) {
    object->set_eviction_meta_atomic(meta);
}

inline void FlatStore::write_object_flags_read_local(KvObj* object, uint8_t flags) {
    object->store_flags_atomic(flags);
}

inline void FlatStore::read_local_reclaim_table(void*, void* payload, size_t) {
    std::free(payload);
}

inline void FlatStore::read_local_reclaim_object(void* owner, void* payload, size_t capacity) {
    FlatStore* store = static_cast<FlatStore*>(owner);
    KvObj* object = static_cast<KvObj*>(payload);
    if (!store->read_local_cache_put(object, capacity))
        store->destroy_retired_obj(object, capacity);
}

inline void FlatStore::read_local_reclaim_atomic_object(void* owner, void* payload,
                                                        size_t capacity) {
    FlatStore* store = static_cast<FlatStore*>(owner);
    KvObj* object = static_cast<KvObj*>(payload);
    if (store->atomic_recycle_value(object)) {
        return;
    }
    if (!store->read_local_cache_put(object, capacity))
        store->destroy_retired_obj(object, capacity);
}

inline void FlatStore::retire_table_read_local(uint64_t* table) {
    if (!table) return;
    read_local_store_state_required().retire_sink.retire(this, table, 0,
                                                         &FlatStore::read_local_reclaim_table);
}

inline void FlatStore::read_local_table_mutation_begin() {
    if (__builtin_expect(!read_local_enabled_, true)) return;
    ReadLocalStoreState& state = read_local_store_state_required();
    if (state.table_mutation_depth++ == 0)
        read_local_advance_generation(state.probe_sequence, false);
}

inline void FlatStore::read_local_table_mutation_end() {
    if (__builtin_expect(!read_local_enabled_, true)) return;
    ReadLocalStoreState& state = read_local_store_state_required();
    if (!state.table_mutation_depth) std::abort();
    if (--state.table_mutation_depth == 0)
        read_local_advance_generation(state.probe_sequence, true);
}

inline void FlatStore::read_local_advance_generation(std::atomic<uint64_t>& sequence, bool ending) {
    if (!ending) {
        const uint64_t previous = sequence.load(std::memory_order_relaxed);
        if (previous & kReadLocalTableMutationBit) std::abort();
        sequence.store(previous | kReadLocalTableMutationBit, std::memory_order_release);
        std::atomic_thread_fence(std::memory_order_acq_rel);
        return;
    }
    const uint64_t observed = sequence.load(std::memory_order_relaxed);
    if (!(observed & kReadLocalTableMutationBit)) std::abort();
    const uint64_t generation = observed >> kReadLocalGenerationShift;
    const uint64_t next = generation == kReadLocalGenerationMask ? generation : generation + 1;
    const uint64_t desired =
        (next << kReadLocalGenerationShift) | (observed & kReadLocalPendingBit);
    sequence.store(desired, std::memory_order_release);
}

inline void FlatStore::read_local_pending_publish(AtomicEntry& entry) {
    if (!read_local_enabled_) std::abort();
    if (entry.foreign_read_unsafe_published) std::abort();
    ReadLocalStoreState& state = read_local_store_state_required();
    state.foreign_reads.add_span(entry.capacity,
                                 [&](uint32_t index) { return atomic_entry_hash(entry, index); });
    foreign_read_pending_witness_open(state);
    entry.foreign_read_unsafe_published = true;
}

inline void FlatStore::read_local_pending_unpublish(AtomicEntry& entry) {
    if (__builtin_expect(!entry.foreign_read_unsafe_published, true)) return;
    ReadLocalStoreState& state = read_local_store_state_required();
    state.foreign_reads.close_span(entry.capacity,
                                   [&](uint32_t index) { return atomic_entry_hash(entry, index); });
    foreign_read_pending_witness_close(state);
    entry.foreign_read_unsafe_published = false;
}

inline void FlatStore::foreign_read_pending_witness_open(ReadLocalStoreState& state) {
    if (state.pending_count == UINT32_MAX) {
        state.foreign_reads.fail_closed_permanently();
        state.probe_sequence.fetch_or(kReadLocalPendingBit, std::memory_order_release);
        return;
    }
    if (state.pending_count++ != 0) return;
    const uint64_t previous =
        state.probe_sequence.fetch_or(kReadLocalPendingBit, std::memory_order_acq_rel);
    if ((previous & kReadLocalPendingBit) && !state.foreign_reads.permanently_poisoned())
        std::abort();
}

inline void FlatStore::foreign_read_pending_witness_close(ReadLocalStoreState& state) {
    if (!state.pending_count) {
        if (state.foreign_reads.permanently_poisoned()) return;
        std::abort();
    }
    state.pending_count--;
    if (state.pending_count != 0 || state.foreign_reads.permanently_poisoned()) return;
    const uint64_t previous =
        state.probe_sequence.fetch_and(~kReadLocalPendingBit, std::memory_order_release);
    if (!(previous & kReadLocalPendingBit)) std::abort();
}

inline void FlatStore::foreign_read_poison_open() {
    ReadLocalTableGuard publication(*this);
    ReadLocalStoreState& state = read_local_store_state_required();
    state.foreign_reads.poison_open();
    foreign_read_pending_witness_open(state);
}

inline void FlatStore::foreign_read_poison_close() {
    ReadLocalStoreState& state = read_local_store_state_required();
    state.foreign_reads.poison_close();
    foreign_read_pending_witness_close(state);
}

inline bool FlatStore::is_borrowed(const char* ptr) const { return borrow_find(ptr) != kNoBorrow; }

inline void FlatStore::free_retired_obj_now(KvObj* object, size_t capacity) {
    kvobj_free_with_capacity(object, capacity);
}

inline void FlatStore::destroy_retired_obj(KvObj* object, size_t capacity) {
    if (outstanding_borrows_ == 0) {
        free_retired_obj_now(object, capacity);
        return;
    }
    const char* ptr = (static_cast<Type>(object->type) == Type::String && !object->is_int())
                          ? object->str_data()
                          : nullptr;
    const uint32_t at = ptr ? borrow_find(ptr) : kNoBorrow;
    if (at != kNoBorrow) {
        borrows_[at].retired = object;
        pending_bytes_ += capacity + read_local_external_bytes(object);
        return;
    }
    free_retired_obj_now(object, capacity);
}

inline void FlatStore::retire_obj(KvObj* o) { retire_obj(o, nullptr); }

[[gnu::always_inline]] inline void FlatStore::retire_obj(KvObj* o, const KvObj* replacement) {
    const size_t capacity = kvobj_capacity(o);
    const size_t bytes = capacity + retiring_external_bytes(o, replacement);
    obj_bytes_ -= bytes;
    if (outstanding_borrows_ == 0) {
        kvobj_free_with_capacity(o, capacity);
        return;
    }
    const char* ptr =
        (static_cast<Type>(o->type) == Type::String && !o->is_int()) ? o->str_data() : nullptr;
    const uint32_t at = ptr ? borrow_find(ptr) : kNoBorrow;
    if (at != kNoBorrow) {
        borrows_[at].retired = o;
        pending_bytes_ += bytes;
        return;
    }
    kvobj_free_with_capacity(o, capacity);
}

inline bool FlatStore::maybe_start_grow() {
    if ((static_cast<uint64_t>(live_[0]) + tombs_[0] + 1) * 100 <
        static_cast<uint64_t>(cap_[0]) * kLoadPct)
        return true;
    if (snapshot_prepared_) return true;
    // Double only when the LIVE set alone justifies it. The trigger counts tombstones, so a
    // delete-heavy workload trips it with almost no live keys and doubling there would inflate
    // the table forever. Otherwise rehash at the same size, which costs the same walk and
    // reclaims every tombstone.
    const bool double_it =
        static_cast<uint64_t>(live_[0]) * 200 >= static_cast<uint64_t>(cap_[0]) * kLoadPct;
    uint64_t wanted = cap_[0];
    if (double_it) wanted *= uint64_t{2};
    if (wanted > UINT32_MAX) return false;
    return start_rehash(static_cast<uint32_t>(wanted));
}

inline void FlatStore::maybe_start_shrink() {
    if (rehashing() || cap_[0] <= kMinCap) return;
    // Hysteresis: grow triggers at kLoadPct and leaves the table at kLoadPct/2, so shrinking
    // only below kLoadPct/4 keeps the two far enough apart that a workload sitting near a
    // boundary cannot rebuild on every other operation.
    if (static_cast<uint64_t>(live_[0]) * 400 > static_cast<uint64_t>(cap_[0]) * kLoadPct) return;
    if (snapshot_prepared_) return;
    (void)start_rehash(cap_[0] / 2);  // shrinking is opportunistic; OOM keeps the old table
}

inline bool FlatStore::start_rehash(uint32_t newcap) {
    if (__builtin_expect(read_local_enabled_, false)) return start_rehash_read_local(newcap);
    if (rehashing()) return true;  // one at a time; finish before starting
    if (newcap < kMinCap) newcap = kMinCap;
    uint64_t* fresh = allocate_table(newcap);
    if (!fresh) return false;
    if (rehash_counter_) (*rehash_counter_)++;
    tab_[1] = tab_[0];
    cap_[1] = cap_[0];
    mask_[1] = mask_[0];
    live_[1] = live_[0];
    tombs_[1] = tombs_[0];
    install_empty_table(0, fresh, newcap);
    rehash_pos_ = 0;
    return true;
}

inline void FlatStore::rehash_step() {
    if (__builtin_expect(read_local_enabled_, false)) {
        rehash_step_read_local();
        return;
    }
    // The window's slot words share a cache line; the objects behind them do not, and every
    // move needs one (hash_key(o->key()) -- the hash is not stored). Warm them together so the
    // misses overlap instead of serializing, eight deep, inside one operation.
    const uint32_t end = std::min(rehash_pos_ + kRehashSlotsPerOp, cap_[1]);
    for (uint32_t i = rehash_pos_; i < end; i++)
        if (const KvObj* o = ptr_of(tab_[1][i])) __builtin_prefetch(o, 0, 1);
    while (rehash_pos_ < end) {
        const uint64_t w = tab_[1][rehash_pos_];
        if (KvObj* o = ptr_of(w)) {
            // Preserve the source if admission's capacity invariant is ever violated.
            if (!insert_into(0, hash_key(o->key()), o, false)) return;
            // TOMBSTONE, not EMPTY. Writing 0 here would terminate any probe run passing
            // through this slot, making every key that probed past it unreachable in the old
            // table for the rest of the rehash — a silent, transient, load-dependent miss.
            tab_[1][rehash_pos_] = kTombBit;
            live_[1]--;
            tombs_[1]++;
        }
        rehash_pos_++;
    }
    if (rehash_pos_ >= cap_[1]) {
        std::free(tab_[1]);
        tab_[1] = nullptr;
        cap_[1] = 0;
        mask_[1] = 0;
        live_[1] = 0;
        tombs_[1] = 0;
        rehash_pos_ = 0;
    }
}
