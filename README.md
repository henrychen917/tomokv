# TomoKV

TomoKV is a C++20 in-memory key-value server for Linux, built for research into
single-node database execution. It speaks the Redis RESP2/RESP3 protocol and
works with Redis clients. Shards have a single executor owner; networking and
execution can run on separate threads or together on each thread, with optional
local reads and runtime rebalancing.

## Status

**v1.0 — Redis 7.4 compatible within the supported surface.** TomoKV is a
research system. Compatibility does not include every Redis command, option,
configuration directive, or persistence format. See the
[compatibility guide](docs/redis-compatibility.md) for the boundaries.

## Features

- Strings, hashes, lists, sets, sorted sets, streams and consumer groups,
  bitmaps, HyperLogLog, and geospatial commands.
- Key and hash-field expiration, memory limits and eviction.
- Transactions with `MULTI`/`EXEC` and `WATCH`, Lua scripting and functions.
- Pub/sub, keyspace notifications, client tracking, ACLs, and TLS.
- Logical databases, native snapshots, and append-only persistence.
- Split (`2s`) and fused (`1s`) thread modes, io_uring or epoll networking,
  optional local reads, and key/client load balancing.

The scope is single node. Cluster management, replication, Sentinel, modules,
and cross-server migration are absent. Some related command names return a
standalone response or an explicit unsupported error.

## Build

Use GNU Make and GCC with C++20 support. The build uses GCC-specific optimization
parameters. Install development packages for **liburing**, **OpenSSL**, and
**jemalloc**, plus Python 3 for the assertion source map. POSIX threads are
required; Lua 5.1 is bundled under `third_party/lua`.

```sh
make -j16
```

The executable is `build/tomokv`. The default flags are
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, with per-object
optimization settings in the [Makefile](Makefile). Build on the target CPU or
supply suitable flags before distributing a binary.

The build uses system jemalloc when its headers are installed. For a custom
installation, set `JEDIR=/path/to/jemalloc`; to use the system allocator, rebuild
with `JE=0`. Use `make clean` before changing compiler or allocator flags.
`make asan` and `make tsan` build sanitizer variants. There is no install target.

## Run

Start a four-thread split server with the supplied configuration file:

```sh
./build/tomokv tomokv.conf --ratio 2:2 --shards 16 --atomic 1
redis-cli PING
```

The default listener is `127.0.0.1:6379`. Configuration-file directives use the
CLI option names without `--`; CLI arguments override the file. Options take
separate arguments, such as `--port 7000`.

| Option | Purpose |
| --- | --- |
| `--thread-mode 2s` / `1s` | Separate IO/executor roles or fused threads |
| `--ratio 2:2` | Initial IO/executor thread counts in split mode |
| `--shards 16` | Shard count; `-1` derives it from executor count |
| `--atomic 1` | Enable grouped MVCC for ordinary multi-shard commands |
| `--read-local 1` | Enable eligible local GET/MGET execution |
| `--net-io uring` / `epoll` | Network backend |
| `--bind 127.0.0.1 --port 6379` | TCP listener |
| `--maxmemory 1gb` | Data budget for eviction; not a process RSS limit |
| `--appendonly yes` | Enable native append-only persistence |

The process affinity mask must contain enough CPUs for the requested placement.
Fused mode uses all allowed CPUs unless `--place` selects a subset; at most 128
threads are supported. Split mode requires both IO and executor roles.
Snapshots are scheduled by default; `--save ""` disables the periodic schedule.
TomoKV snapshots and AOF files are not interchangeable with Redis persistence
files. See [tomokv.conf](tomokv.conf) and the
[configuration reference](docs/configuration.md) for defaults, placement,
authentication, TLS, persistence, and runtime mutability.

## Test

Run the serverless unit suite from the repository root:

```sh
make -j16 unit
python3 tests/docs_drift.py --self-test
```

Additional correctness batteries and publication gates are in [tests](tests).
The publication gate builds and starts servers and runs performance comparisons;
it requires a quiet, suitably provisioned machine and reference tools. Read the
[gate guide](docs/gates.md) before running it. Its documented `--dry-run` mode
prints the network test plan without starting workloads.

## Documentation

- [Architecture](docs/ARCHITECTURE.md), [data plane](docs/architecture/data-plane.md),
  and [control plane](docs/architecture/control-plane.md)
- [Configuration](docs/configuration.md) and [INFO fields](docs/info.md)
- [Redis compatibility](docs/redis-compatibility.md)
- [Testing and publication gates](docs/gates.md)
- [Source directory map](src/README.md)

## Benchmarks

Results and methodology will be published in the forthcoming TomoKV paper.

## License

The project license is to be decided. Bundled third-party code retains its own
license notices in [third_party](third_party).
