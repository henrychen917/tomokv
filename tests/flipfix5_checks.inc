// Included in CoreConcurrencyTest (lane flipfix5): a FLIP control pass acts on the stage it
// loaded at the top of the pass, and the thread can be held before its acknowledgement test
// (measured live: 70-250 us on io_uring executors). Meanwhile the sampled FLIP can finish and the
// next one begin. The pre-flipfix5 test, !flip_acked(tid, stage), compared that OLD stage with
// the NEW epoch, found no token and replayed the stage body outside its quiesce: ExInstall
// re-masked an inbox that resumed IO dispatch was refilling and aborted (all_quiesced() false).
//
// On the gate's state-only 6:2 fixture a test hook runs between the stage load and the first
// stage test and performs exactly that hold: the coordinator finishes the sampled FLIP and admits
// the next one (the same stores as flip_finish_active() and flip_begin()), and optionally resumed
// dispatch posts an ordinary SET to the executor. The "planted" selections restore the
// pre-flipfix5 live-epoch test (test_live_epoch_ack_test_) and must fail: the silent forms with a
// FAIL line naming the replay, the posted-task form by aborting in the re-mask.

    inline static Fixture<false>* ff5_fixture = nullptr;
    inline static uint32_t ff5_target = UINT32_MAX;
    inline static FlipStage ff5_trigger = FlipStage::Idle;
    inline static uint32_t ff5_fired = 0;
    inline static Client* ff5_client = nullptr;
    inline static std::string ff5_key;
    inline static uint64_t ff5_posted_id = UINT64_MAX;

    // flip_finish_active() of the sampled FLIP, then flip_begin()'s admission stores in order:
    // Planning, acknowledgement reset, epoch increment, IoDrain.
    static void ff5_next_flip(Server& server) {
        server.flip_finish_active();
        FlipStage expected = FlipStage::Idle;
        require(server.flip_stage_.compare_exchange_strong(expected, FlipStage::Planning,
                                                           std::memory_order_acq_rel),
                "the next FLIP is admitted from Idle");
        for (uint32_t tid = 0; tid < kMaxThreads; tid++)
            server.flip_ack_[tid].store(0, std::memory_order_relaxed);
        server.flip_epoch_.fetch_add(1, std::memory_order_acq_rel);
        server.flip_stage_.store(FlipStage::IoDrain, std::memory_order_release);
    }

    static void ff5_after_sample(uint32_t tid, FlipStage stage) {
        if (tid != ff5_target || stage != ff5_trigger || ff5_fired++) return;
        auto& f = *ff5_fixture;
        ff5_next_flip(f.server);
        if (ff5_client) {
            // Dispatch resumes between the two FLIPs: an ordinary SET reaches this executor's
            // inbox on the IO producer's lane.
            Op& op = prepare(*ff5_client, {Slice("SET"), slice(ff5_key), Slice("resumed")},
                             f.server);
            require(f.server.worker_of_shard(op.shard) == tid, "resumed SET routes to the held executor");
            ff5_posted_id = ff5_client->rob().dispatch_id();
            ff5_client->rob().publish();
            require(f.server.thread(tid).post_task_quiet(
                        f.io_id, Task{ff5_client, ff5_posted_id, -1, nullptr},
                        f.server.thread(f.io_id).sig()),
                    "resumed dispatch posts to the executor");
        }
    }

    // The planted posted-task control aborts inside the re-mask, exactly as PRE did. Catch that
    // SIGABRT here: print a fixed witness and exit 134 without a core dump.
    static void ff5_planted_abort(int) {
        static const char witness[] = "ABORT flipfix5 planted: stale ExInstall re-mask met a live lane\n";
        (void)!write(2, witness, sizeof(witness) - 1);
        _exit(134);
    }

    // Executor control pass. `trigger` is ExInstall (the abort site) or DatabaseExDrain (the
    // database boundary reuses the same stage machine and acknowledgement words). `inside` holds
    // the thread inside Server::flip_stage_owed() after its epoch/stage validation instead of
    // between the pass's stage load and the test: a token read there would already be the next
    // FLIP's cleared token (the first flipfix5 candidate did exactly that and aborted live).
    static void flipfix5_ex(FlipStage trigger, bool planted, bool post_task, bool inside = false,
                            bool late_token = false) {
        if (planted && post_task) {
            struct sigaction action{};
            action.sa_handler = ff5_planted_abort;
            sigemptyset(&action.sa_mask);
            require(sigaction(SIGABRT, &action, nullptr) == 0, "install the planted abort witness");
        }
        Fixture<false> f;
        const uint32_t ex = f.source;
        auto& loop = f.loops[ex];
        Client client(-1);
        f.client(client);
        const std::string key = f.key(f.sid());
        require(command(f, client, {Slice("SET"), slice(key), Slice("old")}) == "+OK\r\n",
                "seed traffic through the executor");
        ExLoop::test_live_epoch_ack_test_ = planted;
        f.server.flip_epoch_.store(1, std::memory_order_release);
        f.server.flip_stage_.store(trigger, std::memory_order_release);
        require(loop.flip_control_pass() == 1 && f.server.flip_acked(ex, trigger),
                "the executor acknowledges the sampled stage once");
        require(f.server.flip_stale_stage_refusals() == 0, "no stale sample before the hold");

        ff5_fixture = &f;
        ff5_target = ex;
        ff5_trigger = trigger;
        ff5_fired = 0;
        ff5_client = post_task ? &client : nullptr;
        ff5_key = key;
        if (inside) Server::test_flip_owed_validated_ = ff5_after_sample;
        else ExLoop::test_after_stage_sample_ = ff5_after_sample;
        Server::test_flip_owed_late_token_ = late_token;
        (void)loop.flip_control_pass();
        Server::test_flip_owed_validated_ = nullptr;
        Server::test_flip_owed_late_token_ = false;
        ExLoop::test_after_stage_sample_ = nullptr;
        ExLoop::test_live_epoch_ack_test_ = false;
        ff5_fixture = nullptr;
        ff5_client = nullptr;

        require(ff5_fired == 1, "the hold window opened inside the control pass");
        require(f.server.flip_epoch() == 2 && f.server.flip_stage() == FlipStage::IoDrain,
                "the sampled FLIP finished and the next one is in IoDrain");
        require(!f.server.flip_acked(ex, trigger),
                trigger == FlipStage::ExInstall
                    ? "stale ExInstall sample replayed: re-masked the inbox and acknowledged the next FLIP"
                    : "stale DatabaseExDrain sample replayed: acknowledged the next epoch");
        // Held at the top of the pass, the sample is stale and refused (counted once). Held after
        // the validation, it was a live, already acknowledged sample: nothing is owed or counted.
        require(f.server.flip_stale_stage_refusals() == (inside ? 0u : 1u),
                "the refused stale sample is counted exactly once");
        if (post_task) {
            require(f.server.thread(ex).any_ex_inbound() && !f.server.thread(ex).ex_inbound_quiesced(),
                    "the resumed task is still queued on its lane");
            require(loop.drain_tasks(true) == 1, "the executor runs the resumed task normally");
            std::string reply;
            require(client.rob().drain([&](Op& done) {
                        reply.assign(done.reply.data(), done.reply.size());
                    }) == 1 && reply == "+OK\r\n",
                    "resumed SET completes");
            require(command(f, client, {Slice("GET"), slice(key)}) == "$7\r\nresumed\r\n",
                    "the resumed SET is visible");
        }
        require(f.server.thread(ex).ex_inbound_quiesced(), "inbox quiesced after the hold");
        f.server.flip_stage_.store(FlipStage::Idle, std::memory_order_release);
        std::printf("ARMED flipfix5 %s: %s sample held %sacross FLIP 1 -> 2%s; refused\n",
                    planted || late_token ? "planted" : "post",
                    trigger == FlipStage::ExInstall ? "ExInstall" : "DatabaseExDrain",
                    inside ? "after its validation " : "",
                    post_task ? " with a resumed SET queued" : "");
        std::fflush(stdout);
    }

    // IO control pass: a non-coordinator IO held after sampling RoleReady, the last stage it
    // acknowledges. The pre-flipfix5 test replayed the RoleReady body in the next FLIP's IoDrain
    // (re-homing pub/sub for the wrong epoch) and stamped a RoleReady token into that FLIP.
    static void flipfix5_io(bool planted) {
        Fixture<false> f;
        IoLoop io;
        const uint32_t tid = f.server.placement().ifid_threads().back();
        require(tid != f.io_id && f.server.thread(tid).role() == Role::Ifid, "a second IO thread");
        io.srv_ = &f.server;
        io.self_ = &f.server.thread(tid);
        IoLoop::test_live_epoch_ack_test_ = planted;
        f.server.flip_epoch_.store(1, std::memory_order_release);
        f.server.flip_stage_.store(FlipStage::RoleReady, std::memory_order_release);
        (void)io.flip_control_pass<false>();
        require(f.server.flip_acked(tid, FlipStage::RoleReady) && io.flip_pubsub_rehome_epoch_ == 1,
                "the IO acknowledges RoleReady of FLIP 1 once");
        ff5_fixture = &f;
        ff5_target = tid;
        ff5_trigger = FlipStage::RoleReady;
        ff5_fired = 0;
        ff5_client = nullptr;
        IoLoop::test_after_stage_sample_ = ff5_after_sample;
        (void)io.flip_control_pass<false>();
        IoLoop::test_after_stage_sample_ = nullptr;
        IoLoop::test_live_epoch_ack_test_ = false;
        ff5_fixture = nullptr;
        require(ff5_fired == 1, "the hold window opened inside the IO control pass");
        require(f.server.flip_epoch() == 2 && f.server.flip_stage() == FlipStage::IoDrain,
                "the next FLIP is in IoDrain");
        require(!f.server.flip_acked(tid, FlipStage::RoleReady) && io.flip_pubsub_rehome_epoch_ == 1,
                "stale RoleReady sample replayed: re-homed pub/sub and acknowledged the next FLIP");
        require(f.server.flip_stale_stage_refusals() == 1, "the refused IO sample is counted");
        // The live stage still runs normally: this IO now acknowledges FLIP 2's IoDrain.
        for (int pass = 0; pass < 64 && !f.server.flip_acked(tid, FlipStage::IoDrain); pass++)
            (void)io.flip_control_pass<false>();
        require(f.server.flip_acked(tid, FlipStage::IoDrain), "the live IoDrain is still served");
        f.server.flip_stage_.store(FlipStage::Idle, std::memory_order_release);
        (void)io.flip_control_pass<false>();
        std::printf("ARMED flipfix5 %s: RoleReady sample held across FLIP 1 -> 2; refused\n",
                    planted ? "planted" : "post");
        std::fflush(stdout);
    }

    static void flipfix5_all() {
        flipfix5_ex(FlipStage::ExInstall, false, false);
        flipfix5_ex(FlipStage::ExInstall, false, true);
        flipfix5_ex(FlipStage::ExInstall, false, true, true);
        flipfix5_ex(FlipStage::DatabaseExDrain, false, false);
        flipfix5_io(false);
    }
