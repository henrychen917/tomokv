#!/usr/bin/env python3
"""Insert temporary ablation switches into rob.h / io_loop.h.

  ablate.py apply   -- add #if TOMO_RLABL guards (from the pristine copies)
  ablate.py restore -- put the pristine copies back

Bits (compile with -DTOMO_RLABL=n):
  1  read_local_write_conflicts() always returns false   (no read-side probe, no demotions)
  2  mark_current_write()/refine_*() are no-ops          (no write generation at all)
  4  ReadLocalDemotionPlan::prepare() returns true       (no demotion planning on writes)
These break read-your-own-writes on purpose. Instrument only; never built into a shipped binary.
"""
import sys, os, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PRIS = os.path.join(HERE, "pristine")
FILES = ["src/net/rob.h", "src/core/io_loop.h"]

if not os.path.isdir(PRIS):
    os.makedirs(PRIS)
    for f in FILES:
        shutil.copyfile(os.path.join(ROOT, f), os.path.join(PRIS, os.path.basename(f)))
    print("seeded pristine/ from the working tree")

if sys.argv[1] == "restore":
    for f in FILES:
        shutil.copyfile(os.path.join(PRIS, os.path.basename(f)), os.path.join(ROOT, f))
    print("restored"); sys.exit(0)

for f in FILES:
    shutil.copyfile(os.path.join(PRIS, os.path.basename(f)), os.path.join(ROOT, f))

p = os.path.join(ROOT, "src/net/rob.h")
s = open(p).read()
old = """    __attribute__((always_inline)) bool read_local_write_conflicts(
            uint64_t hash, KeysetTouchesHash&& keyset_touches_hash) {
        if (!read_local_state_active()) return false;"""
new = """    __attribute__((always_inline)) bool read_local_write_conflicts(
            uint64_t hash, KeysetTouchesHash&& keyset_touches_hash) {
#if defined(TOMO_RLABL) && (TOMO_RLABL & 1)
        (void)hash; (void)keyset_touches_hash; return false;
#endif
        if (!read_local_state_active()) return false;"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """    void mark_current_write() {
        read_local_state_activate();"""
new = """    void mark_current_write() {
#if defined(TOMO_RLABL) && (TOMO_RLABL & 2)
        return;
#endif
        read_local_state_activate();"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """    bool refine_current_write_hash(uint64_t hash) {
        ReadLocalRobState& state = read_local_state_required();"""
new = """    bool refine_current_write_hash(uint64_t hash) {
#if defined(TOMO_RLABL) && (TOMO_RLABL & 2)
        (void)hash; return false;
#endif
        ReadLocalRobState& state = read_local_state_required();"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """    bool refine_current_write_keyset(uint64_t filter, uint32_t key_count) {
        ReadLocalRobState& state = read_local_state_required();"""
new = """    bool refine_current_write_keyset(uint64_t filter, uint32_t key_count) {
#if defined(TOMO_RLABL) && (TOMO_RLABL & 2)
        (void)filter; (void)key_count; return false;
#endif
        ReadLocalRobState& state = read_local_state_required();"""
assert s.count(old) == 1
s = s.replace(old, new)
open(p, "w").write(s)

p = os.path.join(ROOT, "src/core/io_loop.h")
s = open(p).read()
old = """            if (loop_ || !client) std::abort();
            if (reason == ReadLocalFallbackReason::None) std::abort();"""
new = """#if defined(TOMO_RLABL) && (TOMO_RLABL & 4)
            (void)loop; (void)client; (void)hash; (void)require_hash_match;
            (void)reserve_shard; (void)reason; (void)reserve_current_without_reads;
            (void)fallback_ids; (void)fallback_reasons; (void)fallback_count;
            (void)intersect_command; (void)intersect_filter_miss;
            return true;
#endif
            if (loop_ || !client) std::abort();
            if (reason == ReadLocalFallbackReason::None) std::abort();"""
assert s.count(old) == 1
s = s.replace(old, new)
open(p, "w").write(s)
print("applied")
