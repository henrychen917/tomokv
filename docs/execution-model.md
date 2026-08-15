# Thread-per-core execution model

## What it is

TomoKV splits the normal network command path between IO owners and EX workers. An IO owner accepts a connection, owns its parser and real client, routes non-stateful work through a ring of fake clients, and is the only side that drains those fakes back into the real client's output. EX workers consume per-IO SPSC queues, execute against worker DBs, build replies in the fake clients, and publish completion through per-client CDB bytes. (src/server.c:22977-23000, src/networking.c:503-545, src/server.c:8407-8645, src/server.c:21479-21665, src/server.c:4120-4383)

The design has at least one IO thread and one EX thread per configured topology node; a zero-EX execution mode is rejected at startup. (src/server.c:5717-5734, src/server.c:5840-5850)

“Thread-per-core” describes the intended placement, not an unconditional runtime guarantee: <code>tomokv-pin-mode float</code> leaves placement to the scheduler, an unavailable statically requested CPU causes that thread to float, affinity-setting failure is only warned, and non-Linux builds make the pin function a no-op. (src/server.c:22622-22625, src/server.c:22649-22686)

## Thread roles and identities

<code>iotid</code> is thread-local and starts at 0. The reserved identity namespace is 0 for the main IO owner, the remainder of the 0-through-<code>TOMO_IO_THREADS_MAX</code> region for IO slots, and <code>TOMO_IO_THREADS_MAX + 1 + worker_id</code> for EX slots; both IO and EX compile-time maxima are 128. Live boot IO IDs are 1 through <code>io_threads-1</code>, and convertible workers can activate growth IDs from <code>io_threads</code> through <code>io_threads+tm_ngrow_io-1</code>. (src/server.c:153, src/server.h:1486-1487, src/server.h:1517-1520, src/server.c:22966-22977, src/server.c:23032-23036)

| Running context | <code>iotid</code> | Work driven |
| --- | --- | --- |
| Main thread | 0 | Main event loop and IO-owner duties, including worker-reply drain and pending writes before polling. (src/server.c:153, src/server.c:22738-22745, src/server.c:4560-4571) |
| Poly thread in IO mode | Its fixed <code>polyThreadCtx.io_slot</code> | One <code>ioSlice</code>, which calls <code>aeProcessEventsIO</code> on that binding's event loop. (src/server.c:23265-23273, src/server.c:23086-23104, src/server.c:23424-23464) |
| Poly thread in EX mode | <code>TOMO_IO_THREADS_MAX + 1 + polyThreadCtx.ex_slot</code> | One <code>exSlice</code> on that binding's worker. (src/server.c:23364-23374, src/server.c:23465-23467) |

<code>polyThreadCtx</code> contains the optional <code>ex</code> and <code>io</code> bindings, fixed <code>io_slot</code> and <code>ex_slot</code> identities, thread-private <code>io_listening</code>, atomic <code>mode</code> and <code>target_mode</code>, and the pthread handle. The valid adopted roles are <code>TOMO_MODE_IO=1</code> and <code>TOMO_MODE_EX=2</code>; <code>TOMO_MODE_UNSET=-1</code> is the pre-adoption state. (src/server.h:2521-2525, src/server.h:3070-3080)

Spawned Tomo threads enter <code>polyThreadMain</code>. At a between-slices checkpoint they acquire-load <code>target_mode</code>, validate the corresponding binding and transition preconditions, assign the new mode's <code>iotid</code> before its first slice, and release-store the adopted <code>mode</code>; a refused target leaves the current role running. (src/server.c:23146-23181, src/server.c:23193-23222, src/server.c:23265-23273, src/server.c:23364-23373, src/server.c:23406-23420)

An EX-to-IO transition first drains the old EX binding until it has stayed quiet for 50 ms and asserts that the worker owns no buckets or private keys; only then does it take the IO identity and activate or rebind the IO listener. (src/server.c:23223-23324)

An IO-to-EX transition is accepted only after that IO slot has left the accept group, has no clients, and has no unexpellable inbox work; it then takes the EX identity and initializes the worker slice once. (src/server.c:23329-23373)

The real client's <code>tid</code> is set from the accepting owner's <code>iotid</code>, while <code>running_tid</code> is initialized to the upstream main-thread ID. Consequently, Tomo custom IO owners execute <code>processInputBuffer</code> locally instead of taking the legacy <code>running_tid != IOTHREAD_MAIN_THREAD_ID</code> handoff. (src/networking.c:503-545, src/networking.c:4617-4638)

The separate upstream pool in <code>iothread.c</code> starts only when <code>server.io_threads_num &gt; 1</code>, but Tomo startup rejects that configuration; Tomo's pool is sized by <code>server.io_threads</code>/<code>server.ex_threads</code> and uses poly threads instead. (src/iothread.c:857-887, src/server.c:5700-5715, src/server.c:22816-23045)

### Static and auto thread modes

Both <code>tomokv-thread-mode static</code> and <code>auto</code> enable the same poly-thread execution machinery. Static holds the boot IO/EX split; auto sets <code>server.thread_auto</code> and enables flip rebalancing so the controller may move the split. (src/server.h:1525-1531, src/server.c:5614-5625)

The configured <code>tomokv-thread-io</code> and <code>tomokv-thread-ex</code> values are per-node starting counts in both modes, and startup derives global counts, requires both roles to be positive, and checks the fixed IO/EX capacities. (src/config.c:3212-3244, src/server.c:5717-5776)

For auto mode on one topology node, startup may remap the provisioned pool to one main IO slot plus <code>pool-1</code> convertible worker slots, then realize the requested boot split by birthing a suffix of those workers in IO mode. Static mode does not use this symmetric remap. (src/server.c:5782-5831, src/server.c:22901-22915)

<code>initIOThreads</code> creates IO-born poly threads, their event loops and <code>SO_REUSEPORT</code> listeners, plus dormant IO bindings for convertible workers; <code>initExThreads</code> creates EX-born poly threads and applies the auto boot role where applicable. The main startup sequence calls <code>initIOThreads</code> after <code>initServer</code> and <code>initExThreads</code> after listener setup. (src/server.c:22816-22926, src/server.c:22931-23045, src/server.c:27656-27674)

## Pinning

<code>tomoResolvePinConfig</code> runs after the topology and role counts have been resolved. (src/server.c:5717-5780, src/server.c:5852-5855)

| <code>tomokv-pin-mode</code> | Implemented placement |
| --- | --- |
| <code>float</code> | Return without changing affinity. (src/server.c:22622-22625) |
| <code>ccd</code> | Start with round-robin placement in the process's allowed CPU set; if the machine has multiple detected L3 domains, prefer the topology order grouped by shared-L3 ID. (src/server.c:22395-22445, src/server.c:22635-22676) |
| <code>numa</code> | Start with the same allowed-set round robin; when the multiple-L3 gate is true, use the topology order grouped by NUMA-node ID. (src/server.c:22395-22445, src/server.c:22635-22676) |
| <code>static</code> | Use the role/node/index entry parsed from <code>tomokv-pin-io</code> or <code>tomokv-pin-ex</code>, provided that CPU is in the process's allowed set; otherwise warn and leave the thread floating. (src/server.c:22571-22617, src/server.c:22649-22663) |

Static pin specifications use whitespace- or semicolon-separated <code>nodeN=cpu-list</code> tokens; CPU lists accept comma-separated IDs and inclusive <code>lo-hi</code> ranges. Malformed tokens, repeated nodes, invalid ranges, or per-node lists exceeding the fixed bound are rejected. (src/server.c:22464-22565)

Static mode requires both role specifications and enough entries for every role on every configured node; supplying either specification with a non-static mode is fatal. (src/server.c:22571-22617)

Logical placement assigns a contiguous logical block per topology node, workers first and then IO slots. IO slot 0 is the main thread, and both spawned IO threads and EX threads are passed through the same role-aware pin function. (src/server.c:22718-22745, src/server.c:22920-22925, src/server.c:23025-23039)

Affinity is assigned at thread creation, not at a role-change checkpoint: IO-born threads use the IO map, while every EX-born thread uses the EX map even when the auto boot split starts it in IO mode. A later IO/EX conversion therefore retains that OS thread's original affinity. (src/server.c:22901-22925, src/server.c:23010-23039, src/server.c:23193-23420)

After an EX thread adopts its role, every non-float pin mode also makes a best-effort Linux <code>MPOL_PREFERRED</code> request for the NUMA node containing its current CPU; failures or an unknown node leave the default policy in place. (src/server.c:22698-22715, src/server.c:23364-23372)

## Core data structures

### Pending commands

<code>pendingCommandList</code> is a doubly linked queue with <code>head</code>, <code>tail</code>, total <code>len</code>, and <code>ready_len</code> for entries that are not incomplete. (src/server.h:1303-1308, src/networking.c:6768-6801)

<code>pendingCommand</code> contains the following exact fields. (src/server.h:4230-4250)

| Field group | Fields |
| --- | --- |
| Parsed argv | <code>argc</code>, <code>argv_len</code>, <code>argv</code>, <code>argv_len_sum</code>. (src/server.h:4231-4235) |
| Cached command metadata | <code>input_bytes</code>, <code>cmd</code>, <code>keys_result</code>, <code>reploff</code>. (src/server.h:4236-4239) |
| State and result | <code>flags</code>, <code>slot</code>, <code>read_error</code>, <code>argv_released_mask</code>. (src/server.h:4240-4246) |
| Links | <code>next</code>, <code>prev</code>. (src/server.h:4248-4250) |

The non-debug flag bits are <code>INCOMPLETE</code>, <code>PREPROCESSED</code>, <code>KEYS_RESULT_VALID</code>, and <code>KEYS_RESULT_ALLOCATED</code>. (src/server.h:4216-4227)

The worker can decrement DB-aliased argv references and mark indices below 64 in <code>argv_released_mask</code>; terminal IO-side pending-command cleanup uses that record instead of decrementing the same references again. (src/server.c:21651-21664, src/server.h:4243-4246)

### Real and fake clients

The execution core is exactly 320 bytes. A full client appends one <code>clientExecTail</code>; without request/response logging the tail is 840 bytes and the asserted full size is 1160 bytes. (src/server.h:1766-1773, src/server.h:1949-1959)

| Protocol responsibility | Fields |
| --- | --- |
| Identity and ownership | <code>isFake</code>, <code>tid</code>, <code>running_tid</code>, <code>parent</code>, <code>flags</code>, <code>conn</code>, <code>db</code>, and <code>user</code>. (src/server.h:1877-1891) |
| Command state | <code>cmd</code>, <code>argv</code>, <code>argc</code>, <code>argv_len</code>, <code>slot</code>, <code>pending_cmds</code>, and <code>current_pending_cmd</code>. (src/server.h:1888-1897, src/server.h:1927-1933) |
| Reply state | <code>reply</code>, <code>buf</code>, <code>reply_bytes</code>, <code>sentlen</code>, <code>bufpos</code>, and <code>buf_usable_size</code>. (src/server.h:1893-1896, src/server.h:1914-1921) |
| Dispatch state carried by a fake | <code>fake_slot</code>, <code>cdb</code>, <code>tomo_local_worker</code>, <code>CLIENT_EX_PENDING</code> in <code>flags</code>, and the <code>has_exec_tail</code> guard. (src/server.h:1923-1940, src/server.c:8494-8517) |

The lifecycle-relevant tail fields are the CDB pointer <code>reply_cdb</code>; the fixed fake pointer array <code>fakeClients</code>; parser state such as <code>querybuf</code>, <code>qb_pos</code>, <code>reqtype</code>, <code>multibulklen</code>, and <code>read_error</code>; the intrusive pending-EX and pending-write nodes; the uring sidecar pointer; and the ring counters <code>dispatchid</code>, <code>flushid</code>, <code>ring_size</code>, <code>ring_mask</code>, <code>ring_want_grow</code>, and <code>cs_barrier</code>. (src/server.h:1778-1869)

The fake and CDB arrays have a compile-time maximum of 32 ring slots. (src/server.h:1559, src/server.h:1639-1643, src/server.h:1783-1786)

A real client owns the fake ring and initializes all fake pointers to null and both sequence counters to zero. It separately allocates a cache-line-aligned array of CDB lines and relaxed-clears every ready byte. (src/networking.c:503-520, src/networking.c:629-644)

A full fake allocates the core plus tail, an output buffer, and a reply list. An express core fake allocates only the 320-byte core and sets <code>has_exec_tail=0</code>; promotion to a full fake is asserted to occur only while the slot has no command, pending argv, reply, EX-pending flag, or pinned snapshot. (src/networking.c:339-419, src/networking.c:422-442)

### Worker lanes and completion bus

Each <code>exQueue</code> has consumer-owned atomic <code>head</code>, non-atomic <code>cached_tail</code>, and atomic <code>retired</code>; producer-owned atomic <code>tail</code>, non-atomic <code>cached_head</code>, and non-atomic <code>staged_tail</code>; and a fixed <code>jobs[TOMO_EX_QUEUE_SIZE_MAX]</code> array. <code>head</code> and <code>tail</code> are separately cache-line aligned, and the maximum jobs array is 2048 entries. (src/server.h:2310-2324, src/server.h:2437-2477)

Each worker <code>exThread</code> contains <code>id</code>, pthread handle, DB pointer, atomic <code>q_top</code> and <code>q_summary[]</code> handoff summaries, <code>stamp_pending</code>, dense-sweep diagnostics, and a read-only runtime lane description: <code>nlanes</code>, heap <code>queues</code>, and heap <code>freeback</code>. (src/server.h:2527-2584)

<code>initExThreads</code> allocates one <code>exThread</code> per worker. Each worker gets <code>min(io_threads + num_workers + 1, TOMO_IO_THREADS_MAX + 1)</code> heap lanes in one contiguous queue/freeback block, and indices 0 through <code>io_threads + tm_ngrow_io</code> are initialized. (src/server.c:22816-22877)

A <code>cdbSlots</code> object is exactly one cache line containing 32 lock-free atomic bytes, one byte per fake-ring slot; it is an array of flags, not a bitmask. (src/server.h:1638-1649, src/server.h:1559)

The number of per-client CDB lines is resolved once: one per worker when multiple L3 domains are detected, otherwise one, capped by worker count and <code>NUM_CDB_MAX</code>. Worker-to-bus mapping uses bus 0 for a single bus, direct identity when possible, and worker ID modulo bus count otherwise. (src/server.c:6094-6107, src/server.c:3139-3147)

## Command lifecycle

### 1. Accept and socket read

Each boot IO thread other than the main thread has its own event loop, nonblocking <code>SO_REUSEPORT</code> listener, and accept handler; growth IO bindings pre-create an event loop and bound-but-not-listening socket for later role adoption. (src/server.c:22931-23008)

<code>createClient</code> installs <code>readQueryFromClient</code>, attaches the client to the connection, records <code>tid=iotid</code>, initializes parsing/reply state, and links the client to the current owner's lists. (src/networking.c:503-613)

With the epoll path, a readable callback enters <code>readQueryFromClient</code>. It refuses a read while <code>CLIENT_EX_PENDING</code> or IO reading is disabled, grows or borrows a query buffer, calls <code>connRead</code>, handles disconnect/EOF and query-buffer limits, then calls <code>processInputBuffer</code>. (src/networking.c:4794-4811, src/networking.c:4812-4893, src/networking.c:4920-4953)

With uring2, an accepted ordinary TCP client is attached only when it belongs to the current <code>iotid</code> and is not a master, slave, internal client, or RDB replication channel. Attachment removes the connection read handler, allocates a per-client receive buffer, and queues a one-shot receive. (src/networking.c:2133-2151, src/uring2.c:1502-1529)

A positive uring receive CQE copies its bytes from that per-client buffer into the client's SDS query buffer, queues the client for parsing, and rearms a one-shot receive when the client remains runnable. (src/uring2.c:757-825, src/networking.c:4718-4760)

### 2. Parse into <code>pendingCommand</code>

<code>processInputBuffer</code> limits unauthenticated lookahead to one and otherwise uses <code>server.lookahead</code>. It stops when the client is blocked/unblocked, already has a pending command, is a busy master, or is closing. (src/networking.c:4478-4516)

When no ready command is queued, the parser selects inline or RESP multibulk from the current first byte, acquires a pending-command object, and reuses the tail object for an incomplete multibulk command. It appends the parse result and counts it as ready only when <code>PENDING_CMD_FLAG_INCOMPLETE</code> is clear. (src/networking.c:4518-4577, src/networking.c:6768-6801)

For a complete parser result, <code>preprocessCommand</code> reuses or looks up the command, checks arity, extracts keys and a slot, records heap ownership of extracted key metadata, and converts a cross-slot result into <code>CLIENT_READ_CROSS_SLOT</code> with an invalid slot. (src/server.c:7692-7746)

The ready list head is copied into the legacy client execution fields: argc/argv, argv allocation length, input-byte count, replication offset, slot, looked-up command, read error, and <code>current_pending_cmd</code>. (src/networking.c:4594-4610)

The IO owner calls <code>processCommandAndResetClient</code>. If routing sets <code>CLIENT_PIPELINE_STALLED</code>, that wrapper deliberately skips <code>commandProcessed</code>, leaving the current pending-command head intact for retry. (src/networking.c:4345-4366, src/networking.c:4658-4676)

At the end of the parse pass, consumed query bytes are trimmed and <code>flushExQueues</code> eagerly publishes jobs staged by that connection's batch. (src/networking.c:4699-4715)

### 3. Validate and choose a route

<code>processCommand</code> performs command lookup/reuse and ordinary command validation before entering the Tomo route block. (src/server.c:7812-7852, src/server.c:8191-8205)

| Condition | Route and ordering action |
| --- | --- |
| Stateful command with no T6 worker | Require <code>dispatchid == flushid</code>, then execute <code>call(c, CMD_CALL_FULL)</code> on the real client. (src/server.c:8205-8213, src/server.c:8270-8277) |
| Command queued inside MULTI, excluding the transaction-control exceptions | Require an empty ring, queue it on the real client's transaction state, and reply <code>QUEUED</code> from the real client. (src/server.c:8251-8267) |
| T6 route resolves to cross-worker | Reject; EXEC also discards the queued transaction before returning CROSSSLOT. (src/server.c:8214-8229) |
| T6 route resolves to one worker | Use the ring head as one worker job, set <code>cs_barrier</code>, transfer transaction/script state where needed, and dispatch directly to that worker queue. (src/server.c:8507-8563) |
| <code>TOMO_R_EXPRESS</code> route bit | Resolve the owner worker, capture CDB and worker DB, set <code>CLIENT_EX_PENDING</code>, increment <code>replyWorking</code>, and call <code>exDispatchPush</code>. (src/server.c:8494-8506) |
| Cross-shard classifier returns a command specification | Drain this connection's reorder scratch if needed and fan out through <code>csDispatch</code>; the ring fake remains the group head. Ordinary groups increment <code>replyWorking</code>; admitted atomic writes increment a separate notifier-backed wait count. (src/server.c) |
| <code>canDispatchToWorker(fake)</code> | Resolve one owner, capture CDB and worker DB, set EX-pending, increment <code>replyWorking</code>, and dispatch. (src/server.c:8591-8604) |
| All other non-stateful commands | Execute <code>call(fake, CMD_CALL_FULL)</code> synchronously on the IO owner, but still mark EX-pending and release-publish CDB completion so this reply cannot overtake earlier ring entries. (src/server.c:8605-8640) |

Unsupported cross-shard multi-key forms carrying <code>TOMO_R_XGUARD</code> are rejected before any fake slot is taken, and a live <code>cs_barrier</code> stalls subsequent commands until the ring is empty. (src/server.c:8231-8248, src/server.c:8283-8303)

The exact special gates inside <code>canDispatchToWorker</code> are: OBJECT only in its three-argument key form; MEMORY only for the USAGE subcommand; SCAN when at least one worker exists; DEL and PFCOUNT only with argc 2; and SORT/SORT_RO only when no BY, GET, or STORE option appears. Commands not handled by those gates are accepted only by the explicit proc-identity list in the final return expression. (src/server.c:8677-8831)

<code>getWorkerForCommand</code> sends SCAN to the live owner encoded in a private-DICT cursor when valid, otherwise to the first live worker; RANDOMKEY chooses among live workers with weights based on owned bucket-range width for shared DBs or DB size for private DBs; OBJECT/MEMORY hash argv[2]; and the ordinary path hashes argv[1] with xxh64, masks it to a bucket, and reads <code>ex_bucket_table[bucket]</code>. (src/server.c:9451-9544)

### 4. Reserve a fake-ring slot and move execution state

The in-flight count is the unsigned difference <code>dispatchid - flushid</code>. Ring growth is applied only when the ring is empty; equality with <code>ring_size</code> sets <code>ring_want_grow</code> and <code>CLIENT_PIPELINE_STALLED</code> without consuming the pending command. (src/server.c:8304-8326)

The selected slot is <code>dispatchid &amp; ring_mask</code>. Slots are allocated lazily; a 320-byte core fake is eligible only for <code>TOMO_R_EXPRESS</code> GET with argc 2 or SET with argc 3, with request/response logging absent and relevant module callbacks absent. A non-core-eligible command promotes an existing core fake before use. (src/server.c:8407-8434)

The slim state move transfers argc/argv/cmd/slot/input accounting and the pending-command object, copies response/auth/connection/DB context, initializes fake output state, and clears the moved command fields on the real client. The full move additionally transfers <code>lookedcmd</code>, <code>realcmd</code>, replication offset, and read error. (src/server.c:20719-20816)

The first in-flight fake links the real client into <code>server.clients_pending_ex[iotid]</code>. After the selected route has synchronously completed or accepted the job, <code>processCommand</code> increments <code>dispatchid</code>. (src/server.c:8473-8476, src/server.c:8642-8645)

### 5. Stage, publish, and back-pressure the worker SPSC lane

There is a distinct queue lane for each IO-producer/worker pair. <code>exQueueFor</code> asserts that <code>iotid</code> is in the IO namespace, records the target worker in a thread-local dirty mask, and returns <code>worker.queues[iotid]</code>; worker identities cannot legally index this matrix as producers. (src/server.c:3882-3908)

On push, the IO producer reads its private <code>staged_tail</code>, computes the next masked index, and refreshes <code>cached_head</code> with an acquire load only if the cached value says the ring may be full. It writes <code>jobs[tail]</code> and advances only <code>staged_tail</code>; <code>tail</code> is not published there. (src/server.c:20936-20969)

<code>flushExQueues</code> walks only this producer's dirty workers, release-stores each changed <code>staged_tail</code> into the queue's atomic <code>tail</code>, then release-ORs this producer's lane bit into the worker handoff summary. It is called at parse-batch end and at the start of every worker-reply drain. (src/server.c:20859-20892, src/server.c:3445-3468, src/networking.c:4705-4713, src/server.c:4120-4128)

If <code>tomokv-reorder &gt; 0</code>, strict ordering is off, and the fake is an eligible ordinary non-cross command, <code>exDispatchPush</code> can first place it in the per-IO reorder scratch; crossing to an ineligible dispatch drains that scratch before the direct queue push. (src/server.c:3986-4022)

If the SPSC lane is full, <code>exDispatchDirect</code> publishes and advertises the staged tail, flushes other dirty lanes, pause-spins with periodic yield until the push succeeds, and immediately publishes and advertises that successful retry. It back-pressures the IO owner rather than dropping the fake. (src/server.c:3910-3961)

### 6. Pop and execute in <code>exSlice</code>

Worker slice initialization captures the worker's CDB index, producer-lane count, scan cursor, and idle-spin state. Each slice first drains that worker's freeback rings. (src/server.c:21720-21738, src/server.c:21777-21788)

The worker acquire-exchanges <code>q_top</code>/<code>q_summary</code> to clear and harvest advertised lanes before draining them. Strict-order mode and every 64th pass perform a dense scan; otherwise the worker rotates across advertised producer lanes. Every lane from which the normal path pops a nonzero batch is added to the release re-advertisement mask for the next pass. (src/server.h:1558, src/server.c:21908-21945, src/server.c:21953-21992, src/server.c:22266-22280)

For an ordinary lane, <code>exQueuePopBatch</code> relaxed-loads consumer-owned <code>head</code>, acquire-refreshes <code>tail</code> only when its cached tail says empty, copies up to <code>WORKER_POP_BATCH</code> jobs, and release-stores the new head. The compiled batch maximum is 16. (src/server.h:2329-2333, src/server.c:21024-21054)

The worker prefetches the batch, then executes it in queue order. It records parent and slot pairs rather than retaining fake pointers for completion publication. (src/server.c:22042-22073)

For an ordinary fake, <code>exExecFake</code> installs the fake in the worker's <code>current_client</code> and <code>executing_client</code> slots. T6 jobs use full <code>call</code> while holding the owner-worker lock; hash-field-expiration commands on shared node DBs hold every worker lock for that node; the ordinary keyed route invokes the command proc while holding its selected owner lock when argv[1] is declared as a key. (src/server.c:21479-21602)

Cross-shard sub-fakes execute under their owner-worker lock. The last sub is selected with an acquire-release pending decrement when there are siblings, and that last sub publishes the group head's CDB byte unless a later protocol stage owns completion. (src/server.c:22144-22205)

### 7. Build the reply and publish completion

Command reply helpers call <code>_prepareClientToWrite</code> and append bytes first to the fake's buffer and then, if needed, to its reply list. <code>CLIENT_EX_PENDING</code> makes preparation return success without placing that fake on a socket write queue. (src/networking.c:748-781, src/networking.c:933-989, src/networking.c:1067-1108)

After every ordinary command in a popped batch has executed, the worker release-stores 1 to each saved parent/CDB/slot ready byte. It then release-stores <code>retired=head</code> for the lane, so <code>retired == tail</code> denotes execution quiescence whereas <code>head == tail</code> only denotes that nothing remains to pop. (src/server.c:22242-22263, src/server.h:2448-2462)

For each armed completion stage, one completion path performs the 0-to-1 publication: the ordinary worker batch, the last cross-shard sub, or the IO owner for the synchronous fake fallback. The real client's IO owner is the sole 1-to-0 clearer; publication is a release store, readiness is an acquire load, and clear is a relaxed store. (src/server.c:22171-22199, src/server.c:22242-22252, src/server.c:3149-3168, src/server.c:8637-8640)

### 8. Drain the ready prefix on the IO owner

<code>handleWorkerReplies</code> first publishes every staged EX queue, then walks only <code>server.clients_pending_ex[iotid]</code>. (src/server.c:4120-4128)

For each real client it examines <code>slot = flushid &amp; ring_mask</code> and acquire-loads that fake's captured CDB byte. It stops at the first unready slot, so workers may finish out of order but replies retire only as the contiguous <code>flushid</code> prefix. (src/server.c:4215-4241)

For a ready ordinary fake, the drain clears <code>CLIENT_EX_PENDING</code> and calls <code>AddReplyFromClient</code>, which copies the fake's static buffer and joins its reply list into the real client. For a cross-shard group it calls the appropriate stage/reassembly path instead. (src/server.c:4256-4311, src/networking.c:1956-2000)

After splicing, it relaxed-clears the CDB byte, releases any read snapshot, calls <code>commandProcessed(fake)</code>, decrements the matching ordinary or atomic completion count, and increments <code>flushid</code>. The ready byte is cleared before the ring slot can be reused. (src/server.c)

A closing or connectionless real client uses the same acquire-ready, ordered-retirement protocol but omits reply splicing and socket writes; once its ring is empty it is removed from the pending-EX list. (src/server.c:4133-4212)

When <code>flushid == dispatchid</code>, the live client is removed from the pending-EX list. A pipeline stall is retried only when its matching predicate is true: one free slot for an ordinary full-ring stall, or a completely empty ring for <code>cs_barrier</code>. (src/server.c:4357-4383)

Both the custom IO before-sleep hook and the main before-sleep hook call <code>handleWorkerReplies</code> before processing pending socket writes. (src/server.c:4387-4417, src/server.c:4560-4570)

### 9. Write the real client's output

After at least one splice, an attached uring client is put on the pending-write queue. Other clients first call <code>writeToClient(real, 0)</code> immediately and join the pending-write queue only if bytes remain. (src/server.c:4344-4354)

For a non-replica, <code>writeToClient</code> uses <code>writev</code> when the reply list is nonempty or the buffer is encoded, otherwise <code>connWrite</code> sends the static buffer. Ordinary clients stop after the per-event write cap unless memory pressure disables that cap; errors, close-after-reply, and pending-output state are handled before return. (src/networking.c:3372-3402, src/networking.c:3462-3560)

The pending-write pass queues a uring send when the attached client has an eligible stable buffer prefix; otherwise it writes synchronously and installs a writable handler if output remains. A writable epoll callback attempts the same uring queue first and otherwise calls <code>writeToClient</code>. (src/networking.c:3563-3571, src/networking.c:3579-3628)

## IO backends

| Configuration | Implemented network path |
| --- | --- |
| <code>tomokv-io-uring=0</code> | No ring is initialized; event loops poll their native backend and invoke readable/writable callbacks, so accepted client reads reach <code>readQueryFromClient</code> and writes use the syscall path. (src/config.c:3245, src/uring2.c:1335-1338, src/ae.c:449-456, src/ae.c:484-535) |
| <code>tomokv-io-uring=1</code> or <code>2</code> | Both accepted nonzero values call the same uring2 backend; the runtime has no branch that distinguishes them. (src/config.c:3245, src/uring2.c:1335-1338, src/uring2.c:1768-1776) |

### Epoll path

On Linux, the native poller first attempts <code>epoll_pwait2</code> so sub-millisecond timeouts are preserved and falls back to <code>epoll_wait</code> after <code>ENOSYS</code>. It maps epoll readiness into AE readable/writable masks. (src/ae_epoll.c:91-132)

The main loop uses <code>aeProcessEvents</code>; custom IO slices use <code>aeProcessEventsIO</code>. Without uring hooks, each calls the native poller and then invokes the registered readable and writable callbacks. (src/ae.c:395-456, src/ae.c:484-535, src/ae.c:544-545, src/ae.c:695-727)

For custom IO slices, <code>replyWorking</code> is thread-local. Ordinary in-flight replies select bounded user polling, zero-timeout drain passes, and finally a 100-microsecond poll fallback. Atomic writes are excluded: their owner arms a cache-line-isolated completion edge before the normal CDB scan and may block indefinitely; an EX publisher which wins the arm posts the owner's existing event notifier. The main before-sleep path likewise allows an atomic-only pending list to sleep. (src/ae.c, src/server.c)

### uring2 path

Uring2 owns one ring state object per possible IO slot and enforces that ring entry, CQ reaping, and client attachment occur on that slot's issuer pthread. EX workers do not enter these rings; their network-facing handoff remains the SPSC/CDB protocol. (src/uring2.c:168-208, src/uring2.c:1087-1092, src/uring2.c:1218-1223, src/uring2.c:1502-1516)

Initialization requires an event-loop epoll FD, liburing 2.4 or newer, Linux kernel 5.8 or newer, required ring features and opcodes, and successful <code>DONTFORK</code> setup. Failure returns an error to callers that terminate startup or role adoption; there is no fallback to epoll after a nonzero uring setting was requested. (src/uring2.c:1335-1470, src/server.c:23040-23044, src/server.c:23268-23273)

Kernel 5.19 or newer enables <code>SUBMIT_ALL</code> and conditional <code>POLL_FIRST</code>; kernel 6.1 or newer additionally enables <code>DEFER_TASKRUN</code>, <code>COOP_TASKRUN</code>, <code>TASKRUN_FLAG</code>, and <code>SINGLE_ISSUER</code>. (src/uring2.c:1381-1395)

Uring2 does not eliminate epoll. It gets the existing event loop's epoll FD and keeps an uring <code>POLL_ADD</code> on it for listener and control-FD readiness; after that CQE, AE performs a nonblocking native poll and rearms the epoll poll operation. (src/uring2.c:581-595, src/uring2.c:1128-1136, src/uring2.c:1335-1449, src/ae.c:467-476)

Each receive is one-shot into the client's private <code>recv_buf</code>. A tagged callback slot validates the CQE generation, the CQ is advanced in batches of at most 128 before parser callbacks run, and parsing calls <code>processClientInputFromUring</code> on the owning event-loop thread. (src/uring2.c:102-112, src/uring2.c:685-721, src/uring2.c:997-1125)

The uring send path copies at most one <code>PROTO_REPLY_CHUNK_BYTES</code> prefix from the real client's static buffer into owner-private <code>send_scratch</code>, stages up to 512 SEND SQEs in a loop turn, and advances the logical client buffer only when the SEND CQE is applied. Partial or retryable results requeue the remaining immutable scratch prefix, and <code>writeToClient</code> refuses to overtake an active uring send. (src/uring2.c:30-33, src/uring2.c:487-526, src/uring2.c:638-682, src/uring2.c:845-960, src/networking.c:3462-3467)

## Invariants and memory ordering

1. **One IO producer per worker lane.** Only an IO identity may call <code>exQueueFor</code>, and it selects the lane by that producer's <code>iotid</code>; the worker is the sole consumer of all its lanes. (src/server.c:3882-3908, src/server.c:20820-20839)

2. **Publish data before availability.** The producer writes <code>jobs[]</code>, release-stores queue <code>tail</code>, and only then release-ORs the lane summary. The worker acquire-exchanges the summary and acquire-loads <code>tail</code> before reading jobs. (src/server.c:20859-20889, src/server.c:3445-3468, src/server.c:21920-21945, src/server.c:21024-21054)

3. **Publish capacity after dequeue.** The worker release-stores queue <code>head</code>; the producer acquire-refreshes that head only when its cached value says full. (src/server.c:20945-20958, src/server.c:21024-21054)

4. **Dequeued is not executed.** Queue <code>head</code> advances before the batch runs, while <code>retired</code> is release-stored only after the batch's commands and completion publications finish; quiescence tests must use <code>retired == tail</code>. (src/server.h:2448-2462, src/server.c:22248-22263)

5. **Completion publishes the reply.** Reply and fake-lifetime writes happen before the worker's release store to the CDB byte; the IO owner acquire-loads that same byte before reading or retiring the fake, then relaxed-clears it. (src/server.c:3149-3168, src/server.c:22242-22252, src/server.c:4236-4241, src/server.c:4334-4341)

6. **Slot reuse follows IO retirement.** <code>dispatchid</code> selects a slot, <code>flushid</code> advances only after CDB clear and <code>commandProcessed</code>, and a full ring stalls new dispatch. (src/server.c:8304-8326, src/server.c:8423-8434, src/server.c:4334-4341)

7. **Wire order is dispatch order.** The IO drain stops at the first unready <code>flushid</code> slot even if later slots are ready; only that ordered prefix is spliced into the real client's output. (src/server.c:4215-4241, src/server.c:4267-4311)

8. **Stateful client mutation does not overlap older fake work.** Stateful commands and MULTI queueing wait for <code>dispatchid == flushid</code>, and multi-hop cross-shard work holds <code>cs_barrier</code> until the ring is empty. (src/server.c:8210-8213, src/server.c:8251-8277, src/server.c:8295-8303)

9. **Tail access is explicit.** A core fake has <code>has_exec_tail=0</code>, and promotion asserts a quiescent slot before forming a full-tail object; tail-dependent dispatch checks guard on <code>has_exec_tail</code>. (src/networking.c:354-442, src/server.c:3910-3917, src/server.c:3990-3994)

10. **Role identity changes only between slices.** A poly thread changes <code>iotid</code> at its checkpoint after satisfying exit conditions and before executing the new role's first slice; successful <code>mode</code> publication is a release store. (src/server.c:23146-23181, src/server.c:23210-23222, src/server.c:23265-23273, src/server.c:23364-23373, src/server.c:23406-23420)

## Code/comment discrepancies

- The headers of <code>uring2.c</code> and <code>uring2.h</code>, plus the <code>redisServer.io_uring</code> field comment, still describe mode 1 as an older backend and mode 2 as the isolated uring2 backend. The configuration comment instead calls 1 canonical and 2 a compatibility spelling, while executable dispatch makes no distinction and routes every nonzero value to uring2. (src/uring2.c:1-12, src/uring2.h:1-7, src/server.h:3312-3315, src/config.c:3245, src/uring2.c:1335-1338, src/uring2.c:1768-1776)

- Comments on <code>appendClientInputFromUring</code> and <code>processClientInputFromUring</code> refer to a provided-buffer ring and to the reaper returning every BID before parsing. The live uring2 implementation instead allocates one heap receive buffer per attached client, submits that buffer directly to a one-shot <code>recv</code>, copies completed bytes into the query SDS, advances the CQ in the reaper, and only then invokes parser callbacks. (src/networking.c:4718-4721, src/networking.c:4763-4765, src/uring2.c:114-166, src/uring2.c:685-721, src/uring2.c:757-825, src/uring2.c:1087-1125)

- The sparse-scan comment says a lane is added to <code>residual</code> when a batch could not fully drain it or more work arrived. The actual condition is only <code>n != 0</code>, so every normally popped nonempty lane is re-advertised, including a lane that the batch just emptied. (src/server.c:21969-21990, src/server.c:22266-22280)

- The <code>canDispatchToWorker</code> prologue says TTL-setting and RNG-sampling commands are excluded, and a later note warns that SET with TTL options should not dispatch. The actual return expression includes SET, the single-key expiration family, SRANDMEMBER, SPOP, ZRANDMEMBER, and HRANDFIELD, so those comments do not describe the current whitelist. (src/server.c:8648-8673, src/server.c:8721-8729, src/server.c:8783-8807)

- The older pinning comment says the mapping is simple, deterministic, topology-blind, and places workers at their raw indices. The implementation immediately below detects shared-L3 or NUMA topology, builds grouped physical-core orders, respects the process allowed CPU set, and uses per-node worker-first logical indices. (src/server.c:22367-22379, src/server.c:22380-22445, src/server.c:22622-22687, src/server.c:22718-22745)

## File and line map

| File and range | Role in this model |
| --- | --- |
| <code>src/server.h:1628-1649</code> | CDB byte-array layout and cache-line/lock-free assertions. |
| <code>src/server.h:1775-1959</code> | <code>clientExecTail</code>, execution-core client fields, full/core allocation contract. |
| <code>src/server.h:2422-2477</code> | SPSC <code>exQueue</code> layout. |
| <code>src/server.h:2521-2584</code> | Role enum and <code>exThread</code> queue ownership. |
| <code>src/server.h:3070-3080</code> | Fixed poly-thread bindings, identities, and atomic modes. |
| <code>src/server.h:4216-4250</code> | <code>pendingCommand</code> flags and fields. |
| <code>src/networking.c:339-442</code> | Full/core fake allocation and quiescent promotion. |
| <code>src/networking.c:503-662</code> | Real-client initialization, CDB allocation, fake-ring setup. |
| <code>src/networking.c:4345-4715</code> | Pending-command activation, parser loop, command retry, eager queue flush. |
| <code>src/networking.c:4718-4953</code> | uring input bridge and epoll socket-read path. |
| <code>src/networking.c:1956-2000</code> | Fake-to-real reply splice. |
| <code>src/networking.c:3355-3628</code> | Socket write, uring queue selection, and pending writes. |
| <code>src/server.c:3139-3168</code> | Worker-to-CDB mapping and release/acquire/relaxed completion operations. |
| <code>src/server.c:3445-3468</code> | Post-tail sparse handoff advertisement. |
| <code>src/server.c:3882-4022</code> | IO-side queue selection, dispatch, reorder admission, and full-lane backpressure. |
| <code>src/server.c:4120-4385</code> | Ordered ready-prefix drain, retirement, writes, and parser wakeup. |
| <code>src/server.c:7692-7746</code> | Parse-time command/key/slot preprocessing. |
| <code>src/server.c:8191-8645</code> | Stateful gates, fake-ring admission, express/T6/cross/worker/inline routing. |
| <code>src/server.c:20719-21054</code> | Real-to-fake state transfer and SPSC push/pop protocol. |
| <code>src/server.c:21479-21665</code> | Ordinary and T6 fake execution on EX workers. |
| <code>src/server.c:21720-22364</code> | One worker slice, sparse lane scan, execution, CDB publication, retirement. |
| <code>src/server.c:22367-22745</code> | Topology discovery, pin parsing/resolution, affinity and NUMA preference. |
| <code>src/server.c:22816-23475</code> | IO/EX pool creation, role checkpoints, identity adoption, IO and EX slices. |
| <code>src/iothread.c:857-887</code> | Legacy upstream IO pool that valid Tomo configuration keeps inactive. |
| <code>src/ae.c:395-739</code> | Main/custom event-loop integration, uring hooks, and reply-drain wait policy. |
| <code>src/ae_epoll.c:91-145</code> | Linux epoll polling and pollable epoll FD. |
| <code>src/uring2.c:114-208</code> | Per-client and per-IO-owner uring state. |
| <code>src/uring2.c:581-825</code> | Epoll polling, SEND/RECV staging, and receive completion. |
| <code>src/uring2.c:985-1258</code> | CQ drain, parser callbacks, SQ submission, and wait. |
| <code>src/uring2.c:1335-1529</code> | Ring validation/setup and client attachment. |
| <code>src/uring2.c:1768-1776</code> | Nonzero runtime dispatch to uring2. |

## Mechanisms

- [SPSC dispatch ring](mechanisms/buffers/spsc-dispatch-ring.md)
- [CDB completion slots](mechanisms/buffers/cdb-completion-slots.md)
- [Pending-command pool](mechanisms/buffers/pending-command-pool.md)
- [Reply buffer](mechanisms/buffers/reply-buffer.md)
- [Fake-client ring](mechanisms/buffers/fake-client-ring.md)
- [Ring push/pop](mechanisms/communication/ring-push-pop.md)
- [CDB completion bus](mechanisms/communication/cdb-completion-bus.md)
- [Cross-node prefetch](mechanisms/prefetch/crossnode-prefetch.md)
- [Worker-side batch storage prefetch](mechanisms/prefetch/exprefetchbatch.md)
- [L3 footprint gate](mechanisms/prefetch/l3-footprint-gate.md)
- [Message-carrier prefetch](mechanisms/prefetch/message-carrier-prefetch.md)
- [Prefetch engagement counters](mechanisms/prefetch/prefetch-engagement-counters.md)
- [Worker lookup-prefetch stages](mechanisms/prefetch/prefetch-stages.md)


## processEventsWhileBlocked is main-only (2026-08-15)

`processEventsWhileBlocked()` drives `server.el` — main's loop, whose handlers (the `beforeSleep`
nodes==1 reclaim/resize trio, `serverCron`'s memory stats) are main-owned and assert `iotid == 0`.
A worker-executed blocked command (DEBUG RELOAD's `rdbLoad`) that reaches PEWB off-main must not
take over those duties: main is not blocked in that case and keeps driving its own loop, so the
function returns immediately off-main (the rule `script.c` already applied at its call site).
Load-time resize progress is unaffected — the blocked inserter self-drives the coordinator from its
insert-full wait loop (`tomoFlatResizeQuiesce`).
