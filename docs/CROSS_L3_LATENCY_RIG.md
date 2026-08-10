# Cross-L3 delayed-visibility rig

`tomokv-sim-hop-ns` emulates the latency of an asynchronous message crossing an L3/CCD boundary.
It does not stall either producer. The model is delayed visibility:

- an IO producer stages its normal `client *` entries, stamps the newly published FIFO range once,
  release-publishes the existing tail, advertises the existing batched handoff, and returns;
- a worker pops only the visible FIFO prefix (up to `WORKER_POP_BATCH`). A delayed head stays in the
  ring as occupancy; the worker rotates to other producer lanes and feeds only visible entries to
  the existing prefetch state machine;
- a worker stamps a completion before the existing ready-byte release store; and
- an IO drain treats a ready-but-immature completion exactly like not-ready for that connection,
  then continues its outer pending-connection walk.

No sleep, pause loop, notification, or synchronous handoff is added at publication. Existing queue
and CDB acquire/release edges remain the memory-ordering mechanism; the invariant TSC only decides
when a consumer may first touch the published message. Per-lane and per-connection FIFO ordering is
unchanged.

## Off-state contract

The default is `0`. In that state the queue allocation remains `queues + freeback`, client CDBs
remain exactly `num_cdb * 64` bytes (plus their pre-existing alignment overhead), and no timestamp
sidecar is appended. `exQueue`, `cdbSlots`, and `client` do not gain timestamp fields or pointers.
The 11 notification/CDB protections in `./notifyguard.sh` remain the merge guard.

The build emits `redis-server` and its sibling `redis-server-sim`. Simulator hooks are compiled out
of the ordinary server and networking objects, so hop 0 has neither a timestamp allocation nor a hot
mode test. After immutable configuration is parsed—but before threads, clients, or server-side
allocations exist—an armed `redis-server` invocation `exec`s the sibling specialization with the
same PID and arguments. The coordinator always invokes `redis-server`; this selection is transparent.
Because a consumed stdin configuration cannot be replayed across that `exec`, armed measurements
must use a config file or command-line options.

Nonzero mode appends two private sidecars without changing protected message layouts:

- `[worker][producer lane][EX queue slot]` publish-TSC records (the last slot in a tail-published
  batch owns the TSC; earlier slots carry a compact reference to it, and that descriptor slot cannot
  be reused until the FIFO retires the whole batch); and
- `[client][CDB][pipeline slot]` completion publish TSCs.

The server refuses armed mode unless Linux reports `constant_tsc` and `nonstop_tsc`. At armed boot it
calibrates raw TSC ticks once against `CLOCK_MONOTONIC_RAW`; whole-microsecond server clocks are not
used for 50–400 ns deadlines. The intended multi-CCD target is one socket with synchronized TSCs.
For a multi-socket run, the coordinator must first establish that the platform keeps TSC offsets
synchronized across every IO/EX CPU pair; the CPUID flags alone do not prove that property.

## Coordinator sweep

Restart for each immutable hop value and hold the IO/EX split static:

```sh
for hop in 0 50 100 200 400; do
  ./src/redis-server --save '' --appendonly no \
    --tomokv-thread-mode static \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 \
    --tomokv-pipeline-depth 32 \
    --tomokv-key-lb 0 --tomokv-client-lb no \
    --tomokv-sim-hop-ns "$hop"
done
```

`harness/bench_hop_sweep.sh` is the coordinator-side wrapper. It never starts, stops, or reconfigures
a server: point it at the already-running cell and give it a wall-clock duration. The deterministic
`cload` loop uses fixed per-thread sequences and no time-, address-, or `rand()`-derived choice.

```sh
./harness/bench_hop_sweep.sh \
  --duration 30 --variant header-base --hops 100 \
  --server-pid "$SERVER_PID" --port 7800 \
  --threads 8 --pipeline 64 --command get
```

The wrapper attaches `perf stat` as a separate observer of `SERVER_PID`; pass `--no-perf` when the
coordinator attaches it instead. Workload and counter output stay separate so IPC
(`instructions/cycles`) and throughput can be joined by hop value and variant. Healthy workload
output has a positive operation rate and zero connect/protocol errors. Compare the baseline and
message-header-shrink branches at every hop, not only at zero: the difference between their curves
prices bytes/dependencies saved under the transfer latency expected on a multi-CCD target.

Expected server log when armed:

```text
tomokv cross-L3 visibility simulator armed: hop=100ns ticks=... tsc_hz=... (producer paths remain non-blocking; timestamp sidecars enabled)
```

Expected load-driver records are documented beside `bench_hop_sweep.sh` in `harness/README.md`.
