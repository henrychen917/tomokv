---
name: thredis-asan-repro-recipe
description: How to ASAN-build and stress-test THredis to catch heap bugs (the project is on this Linux box)
metadata: 
  node_type: memory
  type: reference
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis lives at `/home/henry/Projects/THredis-stable` on the Linux laptop (not a git repo; moved from a Windows dev box via zip). 16 cores. `memtier_benchmark` at `/usr/bin`. THredis-specific code marked `//ee451`, mostly in `server.c`, `networking.c`, `dict.c`/`.h`, `server.h`. Source-only backup at `/home/henry/Projects/_thredis_src_backup`.

**ASAN build** (forces libc malloc, halts on first error): from repo root `make distclean && make -j16 SANITIZER=address`. Incremental after edits: `make -j16 SANITIZER=address`. Note: the default/native build already uses `malloc=libc` here, so glibc itself reports "smallbin double linked list corrupted" on corruption even without ASAN.

**Run** (config matching the crashing setup — 6 IO + 4 workers, pipeline 32; directives: `myiothreads`, `myworkerthreads`, `myiothreadpipelinedepth`, `myworkerthreadqueuedepth`, all power-of-two except threads count): `ASAN_OPTIONS="detect_leaks=0:abort_on_error=0:halt_on_error=1" ./src/redis-server /tmp/thredis.conf`. Start it as a harness background task (a plain `nohup ... &` in a Bash tool call does NOT persist). **Foreground `sleep` is blocked in this sandbox (exit 144)** — poll readiness with a `redis-cli ping` retry loop instead.

**Repro that reliably caught the UAF:** populate ~1M keys all-SET, then a loop of many short (8s) `--ratio=1:1 --pipeline=32` memtier runs (back-to-back connection teardown = "between benches"). The bug surfaced during the FIRST populate. Most aggressive race trigger: small keyspace (256–5000 keys) + write-heavy ratio + `--reconnect-interval` (maximizes same-key→same-worker overwrites contending with IO-thread retirement).
