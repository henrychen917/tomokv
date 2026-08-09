# Cross-role cache interference: measurement and partitioning plan

## Bottom line

The 7700X evidence starts with a strong **no-cache-headroom** prior. Per-worker throughput is about
2.0 Mops/s in every split, increasing the dataset from 243 MiB to 5.14 GiB (21x) costs only 3.5%,
and group prefetch is neutral even when its residency gate is 97.8% open at 8M x 32 B. A high LLC
occupancy or a large miss count by itself does not overturn that. The required evidence is a
*paired throughput/latency improvement* accompanied by a role-local shift away from DRAM-filled
demand loads or memory-backed stalls. “No such shift and no gain above the noise floor” is a useful
result: stop spending implementation budget on LLC partitioning.

The highest-value risk is different. The 7700X has one shared L3, while either 24-core target has
128 MiB of L3 in four independent 32 MiB CCD caches (the advertised 152 MiB total cache is 24 MiB
of private L2 plus 128 MiB of L3). A one-CCD result cannot price cross-CCD queue, command, and reply
transfers. Worse, the current default `tomokv-nodes=1` can put the global EX block on early CCDs and
the global IO block on later CCDs. That placement can turn every handoff into a cross-CCD handoff.

There is also an immediate measurement confound on this host: logical CPUs 0 and 8 are SMT siblings,
as are 1/9 through 7/15. The server on 0-7 and local load generator on 8-15 therefore share each
core's execution engine, 32 KiB L1d, and 1 MiB L2 as well as the L3. This is not server/load-generator
isolation. AMD's `de_no_dispatch_per_slot.smt_contention` event must be recorded, and a clean CAT
experiment should use a remote load generator. Reserving CAT ways for the local generator controls
its L3 allocations, but cannot remove its SMT contention.

Official product data lists both the [9965WX](https://ir.amd.com/news-events/press-releases/detail/1253/amd-introduces-new-radeon-graphics-cards-and-ryzen-threadripper-processors-at-computex-2025)
and [7965WX](https://ir.amd.com/news-events/press-releases/detail/1162/amd-introduces-new-amd-ryzen-threadripper-7000-series-processors-and-ryzen-threadripper-pro-7000-wx-series-processors-for-the-ultimate-workstation)
as 24-core parts with 152 MiB total cache. The four-CCD inference should still be verified from the
actual machine's `cache/index*/id` and `shared_cpu_list`; CPU numbering and NPS mode must never be
hard-coded.

## Ranked proposals

| Rank | Proposal and mechanism | Estimated size / likely effect | Confirmation or refutation | Cost if it does not help |
|---:|---|---|---|---|
| 1 | **Make the target topology an explicit per-CCD pool.** Put at least one IO and one EX role on every CCD, bind each EX shard's memory locally, and flip roles only in place within the thread's home CCD. | The 24-core SKUs infer as 4 x 6 active cores, each sharing 32 MiB. At 2 Mops/s a worker has about 500 ns/op, or roughly 2,500 cycles at 5 GHz. One 100-200-cycle remote cache transfer is 4-8% of that budget; a command and reply transfer make an 8-16% *remote-versus-local upper estimate*. With the current global hash, balanced placement only makes about 1/4 of uniform dispatches local, so its first-order expected gain is nearer 2-4%. True node-local routing has a larger estimated 6-12% opportunity. | On the target, compare balanced-per-CCD placement against deliberate IO/EX CCD segregation at the same role counts. Record throughput, tail latency, and `near_cache`/`far_cache` fills per op. Also count owner-CCD-equals-IO-CCD in software before changing routing. | At least one IO per CCD consumes four cores globally; if locality is worthless, a globally smaller IO pool could have left more EX cores. Per-CCD minima also reduce the controller's freedom. This is why the first target run must sweep 1/5 through 5/1 per CCD rather than ship 2/4 by belief. |
| 2 | **Attribute core PMU data to the current IO and EX roles without resctrl.** The included naming patch publishes `tomo-io-NNN` / `tomo-ex-NNN` at the role checkpoint; attach counting PMUs by TID. | Patch size is one helper and one call at role adoption. It makes one thread-name syscall at birth and at a rare flip, with zero steady request-path work. Six-event groups fit the Zen 4 programmable counters without multiplexing. | The dataset and IO-footprint sweeps below must show the focal role's DRAM fills/op, memory-backed backend fraction, and cycles/op move with the other role's footprint. If only total accesses move, the roles merely coexist. | Two counting passes per cell and measurement time. Expected counting overhead is below 0.5%, but verify with an uninstrumented bracket and require 100% event running time. The patch remains useful for `top`, perf, and resctrl even if cache interference is absent. |
| 3 | **Use resctrl first as a role monitor, then as a CAT perturbation.** Give IO and EX separate RMIDs/CLOSIDs, read LLC occupancy and MBM, then sweep disjoint way masks. | On the expected 16-way, 32 MiB L3, one way is about 2 MiB. The plausible IO active footprint is much smaller than its allocated footprint: 200 connections allocate about 3.125 MiB of 16 KiB real reply buffers; four IO roles normally share four 16 KiB reusable query buffers; and a fully populated 32-slot ring adds about 6.25 MiB of 1 KiB fake buffers, before substantial client/fake metadata. Only touched lines matter, so CQM—not allocation arithmetic—decides whether 4, 6, or 8 IO ways are credible. | A disjoint mask must improve paired throughput by more than 3%, with a confidence interval above zero, no material p99 regression, and a causal fall in DRAM fills/MBM or memory stalls. Reverse the winning mask's way position. The half- and quarter-cache overlap controls establish whether capacity is load-bearing. | Requires root, CLOS/RMID lifecycle, warmup after each mask, and static roles. A mask that does not help can only remove replacement freedom; expect flat-to-negative throughput on this 7700X. |
| 4 | **Do not ship a fixed production IO/EX CAT split unless rank 3 wins on both machine classes.** CAT is an experimental scalpel here, not the optimization. | uTPS's hot-set-only TREE result was 1.08x; its 1.22-1.54x results came mainly from separating network buffers from index/data. This fork already separates those by thread, while its local evidence says overhead dominates. A static 4/12 split would cap IO at about 8 MiB and EX at 24 MiB on each CCD regardless of workload. | It would need repeatable wins in GET and SET, p1 and p32, small and large datasets, plus a safe policy for runtime flips. A single Zipfian/TREE win is insufficient for this FLAT/DICT dual engine. | Workload-dependent capacity cliffs, root-only deployment, and a flipped thread retaining the wrong CLOSID unless an external privileged agent moves it. **Expected value is negative today; do not implement runtime CAT.** |

## 1. Per-role measurement without resctrl

### TID attribution

Creation order is not a sound interface. In this tree the base IO pthreads are created first,
background BIO threads are created later, and EX pthreads are created after that. Linux TIDs tend
to increase with creation order but that is not a contract, other libraries can create threads,
and a runtime flip invalidates the birth-role interpretation anyway.

The source change in `src/server.c` instead uses the existing portable thread-title wrapper. On
Linux it becomes `pthread_setname_np`, which uses `PR_SET_NAME`. A successful role checkpoint sets:

- `tomo-io-NNN`, where `NNN` is the active IO slot; or
- `tomo-ex-NNN`, where `NNN` is the active EX slot.

The rename happens before the release-store that publishes the new role. The process leader is the
fixed IO0 endpoint and deliberately remains named `redis-server`; its TID is the server PID. This
preserves normal process discovery while making every polymorphic pthread attributable through
`/proc/PID/task/TID/comm`.

Use `--tomokv-thread-mode static` for all cache experiments. A perf attachment follows a TID, not a
role name; if auto mode flips a thread after attachment, the run has mixed roles and is invalid.

```bash
PID=12345

for task in /proc/$PID/task/*; do
    tid=${task##*/}
    printf '%s\t%s\n' "$tid" "$(<"$task/comm")"
done | sort -n

IO_TIDS=$(
    {
        printf '%s\n' "$PID"
        for task in /proc/$PID/task/*; do
            [[ $(<"$task/comm") == tomo-io-* ]] && printf '%s\n' "${task##*/}"
        done
    } | sort -nu | paste -sd, -
)
EX_TIDS=$(
    for task in /proc/$PID/task/*; do
        [[ $(<"$task/comm") == tomo-ex-* ]] && printf '%s\n' "${task##*/}"
    done | sort -nu | paste -sd, -
)

printf 'IO=%s\nEX=%s\n' "$IO_TIDS" "$EX_TIDS"
```

### Exact Zen 4 perf passes

Use named PMU events because this box's installed perf maps them to the following AMD encodings:

| Event | Encoding | Why it is here |
|---|---|---|
| `l2_cache_req_stat.ls_rd_blk_c` | `event=0x64,umask=0x08` | Demand data-cache request missed private L2 and had to look beyond it. |
| `ls_dmnd_fills_from_sys.local_ccx` | `event=0x43,umask=0x02` | Demand fill from this CCX's L3 or another L2. On the one-CCD 7700X this is the closest per-TID “served inside the shared cache complex” signal, but it is not a pure L3-hit counter. |
| `ls_dmnd_fills_from_sys.near_cache` | `event=0x43,umask=0x04` | Fill from another CCX cache in the same NUMA node. It should be approximately zero on this one-CCD host and becomes a cross-CCD signal under NPS1 on the target. |
| `ls_dmnd_fills_from_sys.far_cache` | `event=0x43,umask=0x10` | Fill from another CCX cache in a different NUMA node. Use with `near_cache` when comparing target NPS modes. |
| `ls_dmnd_fills_from_sys.dram_io_near` | `event=0x43,umask=0x08` | Demand fill from local DRAM/MMIO: the most useful role-local consequence of an LLC miss here. |
| `ls_dmnd_fills_from_sys.dram_io_far` | `event=0x43,umask=0x40` | Remote-NUMA DRAM fill; a sanity zero here and a target/NPS diagnostic later. |
| `de_no_dispatch_per_slot.backend_stalls` | `event=0x1a0,umask=0x1e` | Unused dispatch slots attributed to backend stalls. |
| `ex_no_retire.load_not_complete` | `event=0xd6,umask=0xa2` | No-retire cycles with the oldest op waiting for load data. |
| `ex_no_retire.not_complete` | `event=0xd6,umask=0x02` | Denominator used by AMD's memory-backend metric. |
| `de_no_dispatch_per_slot.smt_contention` | `event=0x1a0,umask=0x60` | Slots lost because the load-generator sibling got the SMT dispatch cycle. This is mandatory with CPUs 0-7 versus 8-15. |
| `ls_not_halted_cyc` | `event=0x76` | AMD's denominator for total dispatch slots (`6 * ls_not_halted_cyc`). |

Confirm aliases on any different perf installation with `perf list --details EVENT`. Do not use the
generic `cache-misses` label as the causal metric; its model mapping is less explicit than the fill
source events above.

Run each six-counter pass for IO and EX concurrently so the roles see the same workload interval.
The braces form a hardware group: perf should fail or report poor running time rather than silently
multiplex a causal ratio. The software counters do not consume core PMU slots.

```bash
SECONDS_PER_PASS=60
CACHE_EVENTS='{instructions,l2_cache_req_stat.ls_rd_blk_c,ls_dmnd_fills_from_sys.local_ccx,ls_dmnd_fills_from_sys.near_cache,ls_dmnd_fills_from_sys.dram_io_near,ls_dmnd_fills_from_sys.dram_io_far}'
TARGET_CACHE_EVENTS='{instructions,ls_dmnd_fills_from_sys.local_ccx,ls_dmnd_fills_from_sys.near_cache,ls_dmnd_fills_from_sys.far_cache,ls_dmnd_fills_from_sys.dram_io_near,ls_dmnd_fills_from_sys.dram_io_far}'
STALL_EVENTS='{instructions,ls_not_halted_cyc,de_no_dispatch_per_slot.backend_stalls,ex_no_retire.load_not_complete,ex_no_retire.not_complete,de_no_dispatch_per_slot.smt_contention}'

run_pair() {
    label=$1
    events=$2
    perf stat --no-inherit --no-big-num -x, -I 1000 \
        -e task-clock,context-switches,cpu-migrations -e "$events" \
        -t "$IO_TIDS" -o "perf.${label}.io.csv" -- sleep "$SECONDS_PER_PASS" &
    io_perf=$!
    perf stat --no-inherit --no-big-num -x, -I 1000 \
        -e task-clock,context-switches,cpu-migrations -e "$events" \
        -t "$EX_TIDS" -o "perf.${label}.ex.csv" -- sleep "$SECONDS_PER_PASS" &
    ex_perf=$!
    wait "$io_perf" "$ex_perf"
}

run_pair cache "$CACHE_EVENTS"
run_pair stall "$STALL_EVENTS"

# On a multi-CCD target, use this source pass as well (or instead of CACHE_EVENTS).
# run_pair target-source "$TARGET_CACHE_EVENTS"
```

The `target-source` line is for the later multi-CCD run; do not add it to every 7700X cell merely
to collect expected zeros. Keeping each pass to six hardware events avoids multiplexing.

Record the load generator's completed operations and p50/p99 for the exact interval. For point
GET/SET, normalize each role by completed operations as well as by instructions:

- L2-miss requests/op;
- `local_ccx` fills/op;
- `near_cache` / `far_cache` fills/op on the target source pass;
- near- and far-DRAM fills/op;
- CPI = `ls_not_halted_cyc / instructions`;
- backend-bound fraction = `backend_stalls / (6 * ls_not_halted_cyc)`;
- AMD memory-backend estimate = backend-bound fraction x
  `load_not_complete / not_complete`; and
- SMT lost-slot fraction = `smt_contention / (6 * ls_not_halted_cyc)`.

The fork's process-wide instructions/op is polluted by EX idle spinning. That does not make the PMU
pass useless: `task-clock`, the role-local values, per-op fill rates, and changes between matched
cells remain interpretable. Do not compare raw totals from intervals with different completed-op
counts.

### What interference looks like

| Observation in a focal role when the other role's footprint grows | Interpretation |
|---|---|
| L2 misses/op flat, but `local_ccx` share falls, DRAM fills/op rise, memory-backend fraction and cycles/op rise, and throughput falls | Capacity interference is plausible. The same demand is increasingly served outside the CCD cache. |
| Total L2/LLC traffic rises, but source fractions, DRAM fills/op, memory-backend fraction, and focal-role cycles/op stay flat | Mere coexistence. More cache activity is not lost throughput. |
| DRAM fills rise but backend/cycles and throughput do not | The core overlaps the misses; there is still no performance headroom for CAT to recover. |
| Throughput changes while fill sources do not, and instructions/op or SMT contention changes | Overhead, role starvation, engine change, or local load-generator contention—not LLC residency. |
| `near_cache`/`far_cache` rises on the target when IO and owner EX are separated | Cross-CCD coherence/transfer cost. CAT cannot fix this; placement/routing can. |

### Non-resctrl experiment matrix

Use interleaved A/B/A cells, fixed clocks/power policy, static roles, and the same achieved offered
load. Five paired observations is the minimum useful set on the documented +/-2% exclusive-host
noise floor.

1. **EX-footprint sweep, fixed IO shape:** keep 4 IO / 4 EX, connections, pipeline, value size,
   key distribution, and request rate fixed; compare 2M x 32 B, 8M x 32 B, and the existing 21x
   dataset endpoint. This is already unfavorable to the cache hypothesis: 21x costs only 3.5%.
   The missing evidence is whether IO's DRAM fills/op or memory-backend fraction moves at all.
2. **IO-footprint sweep, fixed EX work:** keep dataset, commands, role count, and completed rate
   fixed with load-generator rate limiting; vary connection count while keeping aggregate
   concurrency controlled. The allocation scale is 16 KiB of real reply buffer per connection,
   one reusable 16 KiB query buffer per IO thread in the common path, plus up to 32 KiB of 1 KiB
   fake buffers per connection at a fully occupied p32 ring. A rise in EX
   DRAM fills/op with otherwise stable EX instructions/op is evidence that IO buffers evict EX
   data. A throughput change caused only by more sockets/epoll work is not.
3. **Static split sweep as supporting evidence only:** use io2/ex6 through io6/ex2, avoiding ex1
   because ex1 selects DICT while ex>=2 selects FLATSTORE. This sweep changes per-worker shard
   size and role capacity simultaneously, so it can locate a useful operating point but cannot by
   itself prove cache interference.
4. **Remote-versus-local load generator bracket:** repeat one cell with a remote generator before
   trusting a 2-4% effect. If the local run has a material SMT lost-slot fraction, it is measuring
   sibling contention as part of the result.

Stop the no-resctrl branch if the focal-role source mix and memory-backend fraction remain stable
and no paired throughput effect clears 3%. That is the “there is no headroom” result.

## 2. resctrl monitoring and L3 partitioning

Linux resctrl gives two capabilities that perf does not:

- an RMID-scoped snapshot of `llc_occupancy` and cumulative `mbm_total_bytes` /
  `mbm_local_bytes` for each role; and
- a CLOSID-scoped L3 allocation mask for new cache fills.

The CPUID feature names map to resctrl files as follows: `cqm_occup_llc` becomes
`llc_occupancy`, `cqm_mbm_total` becomes `mbm_total_bytes`, and `cqm_mbm_local` becomes
`mbm_local_bytes`, under each group's per-L3 `mon_data` directory.

Occupancy is not a hit rate. Cache lines retain their old RMID/CLOS attribution until replacement,
and changing a CAT mask does not flush them. Wait until both occupancy and throughput settle after
every assignment/mask change. Compute MBM as byte deltas divided by the exact interval, not from
the cumulative value. CAT restricts where a CLOS may allocate a replacement line; it does not
forbid a hit on a line allocated under another CLOS. Disjoint masks isolate replacement pressure,
not the intentional sharing or coherence of queue/command/reply lines. These semantics are documented by the
[kernel resctrl interface](https://docs.kernel.org/filesystems/resctrl.html).

### Runnable harness and exact setup

`harness/cache_role_resctrl.sh` discovers the names installed by the source patch, treats the
server PID as IO0, moves IO and EX TIDs into separate CTRL_MON groups, optionally isolates a local
load generator, generates schemata for every discovered L3 domain, and prints all CQM/MBM files.
It does not start or stop a server or benchmark.

```bash
# Mount without CDP: the experiment partitions unified L3 ways, not code/data ways.
sudo ./harness/cache_role_resctrl.sh mount

PID=12345
LOADGEN_PID=23456       # omit this argument when the generator is remote
./harness/cache_role_resctrl.sh show-tids "$PID"
sudo ./harness/cache_role_resctrl.sh setup "$PID" "$LOADGEN_PID"
./harness/cache_role_resctrl.sh info

# Monitoring-only baseline: both roles retain the full L3 mask.
sudo ./harness/cache_role_resctrl.sh apply shared
./harness/cache_role_resctrl.sh sample 60 1 > cqm.shared.tsv
```

The equivalent primitive operations, shown explicitly, are:

```bash
sudo mount -t resctrl resctrl /sys/fs/resctrl
sudo mkdir /sys/fs/resctrl/tomo_io /sys/fs/resctrl/tomo_ex

# Repeat each write for every TID in the lists produced above.
printf '%s\n' "$ONE_IO_TID" | sudo tee /sys/fs/resctrl/tomo_io/tasks >/dev/null
printf '%s\n' "$ONE_EX_TID" | sudo tee /sys/fs/resctrl/tomo_ex/tasks >/dev/null

cat /sys/fs/resctrl/info/L3/cbm_mask
cat /sys/fs/resctrl/info/L3/min_cbm_bits
cat /sys/fs/resctrl/info/L3_MON/mon_features
cat /sys/fs/resctrl/tomo_io/schemata
cat /sys/fs/resctrl/tomo_ex/schemata

for file in /sys/fs/resctrl/tomo_{io,ex}/mon_data/mon_L3_*/{llc_occupancy,mbm_total_bytes,mbm_local_bytes}; do
    printf '%s=' "$file"
    cat "$file"
done
```

Cleanup returns surviving TIDs to the root group and removes only the four harness groups:

```bash
sudo ./harness/cache_role_resctrl.sh reset
sudo umount /sys/fs/resctrl       # optional, only after every resctrl user is done
```

### Specific 32 MiB way-split experiment

The expected `cbm_mask=ffff` is 16 ways, about 2 MiB per way. The script reads the real mask and
`min_cbm_bits` and refuses invalid arithmetic. With a **remote** load generator, run:

| Cell | IO mask / capacity | EX mask / capacity | What it tests |
|---|---|---|---|
| Shared control | `ffff` / 32 MiB | `ffff` / 32 MiB | Natural coexistence and the primary baseline. |
| Shared half-cache positive control | `00ff` / 16 MiB | `00ff` / 16 MiB | Pure capacity contraction without isolation. A neutral result says the active set fits or latency is hidden at 16 MiB; continue to the quarter-cache control before stopping. |
| Shared quarter-cache positive control | `000f` / 8 MiB | `000f` / 8 MiB | Strong capacity squeeze. If both overlap controls are neutral, a disjoint CAT sweep has no credible capacity mechanism to recover. |
| 2 / 14 | `0003` / 4 MiB | `fffc` / 28 MiB | Stress test for a very small IO active set; likely too small for broad connection mixes. |
| **4 / 12** | `000f` / 8 MiB | `fff0` / 24 MiB | First uTPS-shaped test: modest protected network/command footprint, most ways for index/data. Highest expected value of the disjoint cells. |
| 6 / 10 | `003f` / 12 MiB | `ffc0` / 20 MiB | Tests whether IO's active set exceeds the roughly 9.4 MiB counted-buffer estimate (metadata is additional). |
| 8 / 8 | `00ff` / 16 MiB | `ff00` / 16 MiB | Neutral midpoint; not assumed fair merely because a 4/4 thread split is equal. |
| 10 / 6 | `03ff` / 20 MiB | `fc00` / 12 MiB | IO-heavy capacity hypothesis. |
| 12 / 4 | `0fff` / 24 MiB | `f000` / 8 MiB | EX-capacity stress. |
| 14 / 2 | `3fff` / 28 MiB | `c000` / 4 MiB | Endpoint/positive stress, not a plausible shipping split. |

Commands for representative cells are:

```bash
sudo ./harness/cache_role_resctrl.sh apply overlap 8 low
sudo ./harness/cache_role_resctrl.sh apply overlap 4 low
sudo ./harness/cache_role_resctrl.sh apply split 4 12 io-low
sudo ./harness/cache_role_resctrl.sh apply split 6 10 io-low
sudo ./harness/cache_role_resctrl.sh apply split 8 8 io-low

# If 4/12 wins, put IO in the high four ways and EX in the low twelve.
# A real capacity result must survive this way-position reversal.
sudo ./harness/cache_role_resctrl.sh apply split 4 12 io-high
```

Run shared -> overlap-8 -> shared -> overlap-4 -> shared first. If a capacity control binds, run
shared -> 4/12 -> shared -> 8/8 -> shared. Only sweep all endpoints if one disjoint cell moves both
performance and the causal counters. Each mask needs at least 15 seconds of unscored turnover and
then an occupancy-stability check; CAT only constrains new allocations.

With the **local** SMT load generator, a full-mask loadgen can allocate into and evict both role
partitions, defeating exclusivity. Prefer a remote generator. If that is impossible, reserve one
way consistently and compare against a same-capacity shared-role control:

```bash
# IO and EX overlap on the upper 15 ways; loadgen/AUX use the low one.
sudo ./harness/cache_role_resctrl.sh apply shared 1

# Capacity controls remain disjoint from the local generator's reserved way.
sudo ./harness/cache_role_resctrl.sh apply overlap 8 high 1
sudo ./harness/cache_role_resctrl.sh apply overlap 4 high 1

# Fifteen server ways: 3+12, 5+10, 7+8, ...; the fourth argument reserves one.
sudo ./harness/cache_role_resctrl.sh apply split 3 12 io-low 1
sudo ./harness/cache_role_resctrl.sh apply split 5 10 io-low 1
sudo ./harness/cache_role_resctrl.sh apply split 7 8 io-low 1
```

If `min_cbm_bits` is two, reserve two ways and split the remaining fourteen as 2/12, 4/10, 6/8,
8/6, 10/4, and 12/2. A narrow load-generator mask is valid only if its achieved load, CPU time,
and latency show it is not the bottleneck. No CAT mask repairs the simultaneous SMT contention.

### Decision rule

For each scored mask, take at least five interleaved paired windows and pre-register throughput as
the primary result. Keep a partition only when all of the following hold:

1. paired median throughput improves by **more than 3%** over the capacity-matched shared control
   and the paired 95% confidence interval excludes zero;
2. p99 latency does not regress by more than 3%;
3. the constrained role's DRAM fills/op, MBM rate, or AMD memory-backend fraction improves in the
   direction predicted by less eviction; and
4. the effect repeats with the winning mask moved to the opposite way positions and in at least
   GET/SET p32 plus one p1 cell.

If full/full equals or beats every disjoint split, or a “win” has no cache/memory mechanism, reject
the cache-interference hypothesis. If both the shared-half and shared-quarter positive controls are
neutral, state the stronger result: this workload has no measurable LLC-capacity headroom on this
host.

## 3. Multi-CCD topology forecast and required code model

### What the current code already gets right

- `buildSmartCoreOrder()` discovers shared-L3 domains and puts each domain's CPUs consecutively.
- With an explicitly correct multi-node configuration, `tomoLogicalCore()` places a node's EX and
  IO roles in one contiguous per-node core block.
- A converted EX/IO pthread stays on its original core. The per-node flip actuators choose a worker
  from the same logical node, and resharding refuses cross-node moves.
- Worker allocation calls `exBindNumaLocal()` after affinity is set, so its shard prefers the
  CPU's actual NUMA node.

Those are useful pieces, but they do not yet constitute an automatic CCD policy.

### Four current gaps that matter on the target

1. **`tomokv-nodes=1` remains the default and topology identity is flattened.** `ccd` pin mode
   orders CPUs by L3, but `tomoLogicalCore()` still assigns workers first and IO threads second.
   With a one-hardware-thread-per-core cpuset, a 16 EX / 8 IO example on four six-core CCDs puts
   workers on CCD0, CCD1, and most of CCD2; IO then fills the rest of CCD2 and CCD3. “CCD-aware
   ordering” has silently become role segregation. The server should auto-resolve or reject a node
   count that disagrees with the discovered L3 domains.
2. **Multi-node auto mode is not a symmetric role pool.** The code generalizes the fully convertible
   one-node pool only under `server.topo_nodes == 1`. In multi-node mode the base IO-born contexts
   have `ctx->ex == NULL`, so they can never become EX; `io_per_node` is a floor, not merely the
   requested starting split. This prevents the stated controller semantics on the target.
3. **Every IO thread routes through the global bucket table.** `getWorkerForKey()` selects from
   `server.ex_bucket_table[]` across all workers. For uniformly distributed keys and four CCDs, an
   IO thread co-located with one CCD's workers is local only about 25% of the time. Existing design
   notes correctly say that no whole-connection placement can fix this when a connection's keys
   span all buckets. Pinning roles per CCD prevents the pathological 0%-local layout; it does not
   produce 100% locality.
4. **The smart order enumerates logical CPUs, not physical cores.** With all 48 target hardware
   threads allowed and conventional first-sibling-then-second-sibling CPU numbering, a CCD
   contributes its six cores and then their six SMT siblings before the next CCD is emitted. A
   24-thread server can therefore double-place six physical cores and leave later CCDs unused. A
   one-sibling cpuset prevents this for the experiment; production code must de-duplicate by
   `(package_id, core_id)` before applying the CCD order.

### Pinning policy for the first target run

1. Discover L3 IDs, shared CPU lists, core IDs, SMT siblings, and NUMA nodes from sysfs. The expected
   geometry is four CCDs with six enabled physical cores each, but abort on a mismatch.
2. Use one hardware thread per physical core for the server. Put the load generator on a remote
   host; do not repeat the 0-7 versus sibling-8-15 layout at 24 cores. Move NIC IRQs away from server
   CPUs or record their placement.
3. Start in static mode with four logical nodes, six cores per node, and a balanced role mix on
   every CCD. `io2/ex4` per CCD (8 IO, 16 EX globally) is a reasonable *first measurement*, not a
   default conclusion:

   ```text
   --tomokv-nodes 4
   --tomokv-cores-per-node 6
   --tomokv-thread-io 2
   --tomokv-thread-ex 4
   --tomokv-thread-mode static
   --tomokv-pin-mode ccd
   ```

4. Verify the actual startup log and `/proc/PID/task/*/{comm,status}` mapping. Each CCD must contain
   both roles, each TID must have a one-CPU affinity, and no two server TIDs should be SMT siblings.
5. Sweep the per-CCD split 1/5, 2/4, 3/3, 4/2, 5/1. Compare the best balanced cell with a deliberate
   role-segregated static pin map at identical global counts. The segregated arm is the positive
   control for cross-CCD handoff cost.
6. Repeat the best cells under the intended NPS modes. `pin-mode ccd` should continue to define the
   cache domain; NUMA mode changes whether a cross-CCD source is classified as near or far and how
   the eight memory channels are exposed. Use MBM plus `near_cache`, `far_cache`, `dram_io_near`,
   and `dram_io_far`, not the NUMA label alone.

### Flip-controller policy

A role is a state of a fixed physical execution context. Its home CCD is immutable:

```text
CCD c:  io_live[c] + ex_live[c] == physical_server_cores[c]
        io_live[c] >= 1
        ex_live[c] >= 1
```

An EX->IO or IO->EX flip changes the mode, queues, and listener binding at the existing safe
checkpoint; it must not call `pthread_setaffinity_np`, change `home_ccd`, or move shard memory. A
controller may choose a different thread **within the same CCD**. Moving a thread to another CCD
would discard its warm private caches, make its existing queue/reply relationships remote, and
separate its NUMA allocation policy from its CPU. If global pressure says “CCD0 needs one more IO
and CCD1 needs one more EX,” perform two independent in-place flips, one in each CCD; do not swap
the pthreads across CCDs.

For a fully flexible four-CCD, six-core pool, provision per CCD:

- one fixed IO endpoint;
- one fixed EX endpoint; and
- four contexts with both an IO and EX binding.

The requested 2/4 boot split then starts one convertible context as IO and three as EX on each CCD,
but can reach 1/5 through 5/1 later. This is the multi-CCD generalization of the existing one-node
symmetric pool. It requires per-node live prefixes and dormant IO-slot assignment; a single global
“highest worker converts first” mapping is insufficient.

Do **not** combine auto flips with the resctrl CAT experiment. A TID remains in its old resctrl
control group after its role name changes, and unprivileged server code should not gain authority
to rewrite resctrl. Measure CAT with static roles. If CAT ever earns a production design, a small
privileged control agent would have to move the TID's CLOSID at the role checkpoint and handle the
old-line warmout; that complexity is part of CAT's cost.

### Code changes needed to express CCD-aware assignment

In order, without changing the request hot path prematurely:

1. **Preserve topology instead of only sorting it.** Build `l3_domain[]` records containing cache
   ID, allowed physical-core CPUs, SMT siblings, and NUMA node. Select one logical CPU per core.
   Validate that `topo_nodes`, `cores_per_node`, and the allowed cpuset can represent the detected
   domains. Under `pin-mode ccd`, auto-fill `tomokv-nodes` from this table or fail loudly when an
   explicit value disagrees.
2. **Stamp immutable homes.** Add `home_l3_id`, `home_node`, and `home_cpu` to `polyThreadCtx` and
   the IO/EX bindings. Derive `tmNodeOfIoSlot()` from the context for every convertible slot rather
   than from a global slot arithmetic fallback. Assert at each role checkpoint that the running
   CPU belongs to `home_l3_id`.
3. **Generalize the symmetric pool per CCD.** Provision one fixed IO plus `cores_per_node-1` worker
   identities on every CCD; make all but the node's fixed EX endpoint IO-capable; apply the boot
   split independently to each node; initialize bucket ownership only over each node's live EX
   prefix. Keep flip accounting and the one-migration-at-a-time gate per node or explicitly
   serialize it as today.
4. **Instrument locality before redesigning routing.** At dispatch, the IO home and selected
   worker home are already known. Add relaxed per-IO counters for local-CCD and cross-CCD commands,
   and equivalent reply bytes. Expected size is two 64-bit counters per IO slot (about 2 KiB at the
   compiled 128-slot maximum before cache-line padding) and two relaxed increments per command.
   Measure that overhead behind a diagnostic gate; do not leave it unconditional if it costs more
   than the signal is worth.
5. **Choose an explicit locality contract.** The current arbitrary Redis connection cannot be made
   fully local merely by pinning, because its keys may target all CCDs. Near-100% locality requires
   one of:
   - shard-aware clients connecting to a per-CCD endpoint/port based on the key's bucket;
   - a declared key-affinity contract per connection, with client migration driven by measured
     owner-CCD majority; or
   - an IO-to-IO handoff to an owner-CCD coordinator, accepting that the socket/reply still crosses
     a CCD boundary.

   The first option has the cleanest data path but changes deployment/API expectations. The second
   helps only affinity-rich workloads. The third adds another queue hop and cannot eliminate the
   return transfer. Never remap the same key to a different same-CCD worker based on which IO thread
   received it; that would violate single-writer ownership.

### Size forecast and why the conclusion can invert

At the reference 200 connections, obvious IO buffer allocations are roughly 9.4 MiB server-wide
(3.125 MiB of real reply buffers plus up to 6.25 MiB of fake payload buffers at a full 32-slot
ring), plus one normally reusable 16 KiB query buffer per IO thread and substantial client/fake
metadata. That is about 2.35 MiB of the two counted buffer classes per CCD when connections are
balanced four ways. The actively touched portion can be far smaller. The 8M x 32 B dataset is
about 785 MiB, or roughly 196 MiB per CCD before imbalance—well
beyond a 32 MiB CCD L3. These estimates favor trying 4 IO ways / 12 EX ways, but the existing flat
prefetch result says the miss latency is probably overlapped and the buffer allocation size is not
residency. CQM and the paired CAT perturbation decide; arithmetic does not.

Cross-CCD placement is different from capacity. Even when a line is resident, a command object,
queue publication line, or reply line owned by another CCD must traverse the fabric. The current
overhead-bound result therefore makes topology *more* important, not less: extra coherence hops add
to the dominant per-command overhead, while more LLC capacity may still have nothing to recover.
Conversely, dividing each target CCD's 32 MiB into fixed role masks can hurt more than on the shared
7700X because no role can borrow unused ways from another CCD or role.

The procurement gate should therefore be a borrowed/rented four-CCD AMD run, not a software-delay
emulation on the 7700X. Require the balanced-versus-segregated placement result, source-specific
fills, and local-dispatch fraction before treating either Threadripper as a performance purchase.
Correctness/topology-table work can be completed on this host; the performance conclusion cannot.

## Recommended execution order

1. Land/use the thread names and take the two role-perf passes on the existing 2M and 8M cells.
2. If role-local DRAM/memory-stall evidence is absent, record “no LLC-capacity headroom” and skip
   the full CAT sweep.
3. When root is available, run resctrl shared monitoring and the half-/quarter-cache positive
   controls. Run 4/12 and 8/8 only if a control moves a causal metric.
4. Before purchase, run the four-CCD balanced-versus-segregated topology experiment remotely or on
   a loaner. This result is independent of whether CAT paid on the 7700X.
5. Generalize the per-CCD symmetric flip pool only after the static topology map and local/remote
   dispatch census are correct. Do not add production CAT or shard-aware routing without their own
   measured win.
