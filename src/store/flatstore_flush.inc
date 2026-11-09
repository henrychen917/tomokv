// FlatStore's cold namespace-range MVCC declarations. Included by flatstore_atomic.inc
// inside FlatStore; definitions compile in src/store/flush.cc (both database namespaces).
// Range entries retain their group lifetime while logical clear and physical reclamation
// are separate phases. Callers hold shard ownership, or run after workers join at shutdown;
// atomic_flush_ready checks the registered scatter/transaction snapshot floor and cleanup
// cutoff before reclaiming a committed range. Plain-read cuts are unregistered and do not
// constrain that floor; aborted ranges bypass these bounds.
AtomicEntry* atomic_install_flush(ScatterState* group, int ns, std::atomic<uint64_t>* epoch,
                                  std::atomic<bool>* aborted, std::atomic<uint32_t>* refs,
                                  uint64_t origin, uint32_t shard);
void atomic_flush_release(AtomicEntry* entry);
bool atomic_flush_ready(AtomicEntry* range, uint64_t floor, uint64_t cutoff);
bool atomic_flush_has_post(const AtomicEntry& range) const;
bool atomic_flush_erase(AtomicEntry& range);
uint64_t atomic_flush_resolved_size(uint64_t snapshot);
AtomicResolved atomic_resolve_range(uint64_t hash, Slice key, uint64_t snapshot,
                                    bool count_predecessor);
