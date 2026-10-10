// Included in CoreConcurrencyTest (lane flipfix): FLIP connection-set lifetime/order (IO4.4, IO4.1)
// and the fingerprint publication contract (CT4.3), on the gate's state-only 6:2 fixture. No
// socket, ring or worker: fd -1 connections exercise only ownership, lifetime and publication.
// Every selection is written against APIs that PRE also has, so the same rows are their own
// negative controls on the PRE tree (TSan report, ASan use-after-free, or a failed assertion).

    // One FLIP 5 3 from the fixture's 6:2 split, with `count` connections on the converting IO.
    struct FlipfixPlan {
        Fixture<false> f{false};
        IoLoop source;
        uint32_t converting = UINT32_MAX;
        std::vector<Client*> clients;
        explicit FlipfixPlan(uint32_t count) {
            std::string error;
            require(f.server.flip_begin(5, 3, f.io_id, error), "admit FLIP 5 3 from 6:2");
            for (uint32_t tid = 0; tid < f.server.nthreads(); tid++)
                if (f.server.flip_candidate_target(tid) == Role::Ex) converting = tid;
            require(converting < f.server.nthreads() && converting != f.io_id &&
                        f.server.thread(converting).role() == Role::Ifid,
                    "one non-coordinator IO converts");
            source.srv_ = &f.server;
            source.self_ = &f.server.thread(converting);
            for (uint32_t i = 0; i < count; i++) {
                Client* client = new Client(-1);
                client->set_id(100 + i);
                client->set_ifid_thread(converting);
                client->set_wb_slot(f.server.thread(converting).assign_wb_slot(client));
                f.server.thread(converting).add_client(client);
                f.server.client_accepted();
                clients.push_back(client);
            }
        }
        // The converting IO's own pass acknowledges IoDrain (the production predicate).
        void source_drain_ack() {
            for (int pass = 0; pass < 64 && !f.server.flip_acked(converting, FlipStage::IoDrain);
                 pass++)
                (void)source.flip_control_pass<false>();
            require(f.server.flip_acked(converting, FlipStage::IoDrain),
                    "converting IO acknowledged IoDrain");
        }
        // Coordinator side: acquire the source's acknowledgement, stand in for the idle IOs, plan.
        bool coordinator_plan(std::string& error) {
            while (!f.server.flip_acked(converting, FlipStage::IoDrain)) std::this_thread::yield();
            for (uint32_t tid = 0; tid < f.server.nthreads(); tid++)
                if (tid != converting && f.server.thread(tid).role() == Role::Ifid)
                    f.server.flip_ack(tid, FlipStage::IoDrain);
            return f.server.flip_build_client_plan(nullptr, error);
        }
        uint32_t surviving_quota() const {
            uint32_t total = 0;
            for (uint32_t tid = 0; tid < f.server.nthreads(); tid++)
                if (tid != converting && f.server.thread(tid).role() == Role::Ifid)
                    total += f.server.flip_client_quota(tid);
            return total;
        }
        // ClientPrepare on the converting source, then let the held closes finish and reap.
        void prepare_and_finish(const char* label) {
            f.server.flip_set_stage(FlipStage::ClientPrepare);
            for (int pass = 0; pass < 64 &&
                     !f.server.flip_acked(converting, FlipStage::ClientPrepare); pass++)
                (void)source.flip_control_pass<false>();
            require(f.server.flip_acked(converting, FlipStage::ClientPrepare),
                    "converting IO acknowledged ClientPrepare without its closed connections");
            require(f.server.thread(converting).client_count() == clients.size() &&
                        f.server.live_clients() == clients.size(),
                    "closes stayed held before removal through ClientPrepare");
            require(surviving_quota() == 0,
                    "every planned connection that closed was dropped from its destination quota");
            for (Client* client : clients) source.close_client(client);
            for (Client* client : clients)
                require(client->dead(), "a converting IO finishes its dropped closes after ClientPrepare");
            require(f.server.thread(converting).client_count() == 0 &&
                        f.server.live_clients() == 0,
                    "dropped connections leave the converting IO before ClientInstall");
            source.reap_dead();
            source.reap_dead();
            f.server.flip_refuse_active(); // state-only fixture never commits ownership
            std::printf("ARMED %s: %zu planned connections closed during FLIP 5 3, dropped and reaped\n",
                        label, clients.size());
            std::fflush(stdout);
        }
    };

    // IO4.4a: a close on the converting IO's thread after its IoDrain acknowledgement is unordered
    // with the coordinator's plan read of that IO's client vector (TSan selection).
    static void flipfix_plan_race() {
        FlipfixPlan plan(2);
        std::thread owner([&] {
            plan.source_drain_ack();
            plan.source.close_client(plan.clients[0]); // a peer FIN, unordered with the plan
        });
        std::string error;
        const bool planned = plan.coordinator_plan(error);
        owner.join();
        require(planned && error.empty(), "the plan saw a held close, not a half-removed one");
        require(plan.f.server.flip_source_clients(plan.converting) == 2,
                "both connections of the converting IO are planned");
        plan.source.close_client(plan.clients[1]);
        plan.prepare_and_finish("flipfix-plan-race");
    }

    // IO4.4b + IO4.1: both planned connections close AFTER planning and the source reaps twice
    // (two prologues: the corpse grace) before ClientPrepare reads its planned Client* (ASan).
    static void flipfix_plan_lifetime() {
        FlipfixPlan plan(2);
        plan.source_drain_ack();
        std::string error;
        require(plan.coordinator_plan(error) && error.empty(), "plan both connections");
        require(plan.f.server.flip_source_clients(plan.converting) == 2,
                "both connections of the converting IO are planned");
        for (Client* client : plan.clients) plan.source.close_client(client);
        plan.source.reap_dead();
        plan.source.reap_dead();
        plan.prepare_and_finish("flipfix-plan-lifetime");
    }

    // CT4.3: the owner publishes sampled windows while the monitor's reader consumes them.
    static void flipfix_fingerprint() {
        Fixture f(false);
        FlipController controller;
        require(controller.init(true, f.server.nthreads()), "initialize the flip controller");
        FlipFingerprintWriter& writer = f.server.thread(f.io_id).flip_fingerprint();
        writer.configure(1); // every pass sampled: one window per pass, no probabilistic arm
        constexpr uint64_t kPasses = 20000, kChunks = 20;
        std::atomic<bool> done{false};
        // RELAXED handshake: it guarantees the reader runs between the owner's chunks without
        // creating any happens-before edge between the owner's counter stores and the reader's
        // loads (an acquire/release handshake here would hide the PRE data race from TSan).
        std::atomic<uint64_t> reads{0};
        std::thread owner([&] {
            for (uint64_t pass = 0; pass < kPasses; pass++) {
                if (pass % (kPasses / kChunks) == 0) {
                    const uint64_t seen = reads.load(std::memory_order_relaxed);
                    while (reads.load(std::memory_order_relaxed) < seen + 2)
                        std::this_thread::yield();
                }
                require(writer.pass_sampled(), "W=1 samples every pass");
                writer.note_command(FlipFingerprintClass::Read, 1, 8);
                if (pass % 3 == 0) writer.note_command(FlipFingerprintClass::MultiWrite, 2, 16);
                require(writer.finish_parse_pass(), "a sampled pass publishes");
                writer.arm(pass);
            }
            done.store(true, std::memory_order_release);
        });
        uint64_t consumed = 0;
        while (!done.load(std::memory_order_acquire)) {
            (void)controller.sample_fingerprint(f.server);
            consumed += controller.fingerprint_sampled_this_tick_;
            reads.fetch_add(1, std::memory_order_relaxed);
        }
        owner.join();
        (void)controller.sample_fingerprint(f.server);
        const FlipFingerprintWindow& last = controller.fingerprint_last_[f.io_id];
        const uint64_t multi = (kPasses + 2) / 3;
        require(last.closed_windows == kPasses && last.commands == kPasses + multi &&
                    last.multikey_ops == multi && last.multikey_keys == 2 * multi &&
                    last.value_bytes == 8 * kPasses + 16 * multi,
                "the reader's cumulative copy matches every published window");
        require(consumed > 1, "the reader consumed windows while the owner published");
        std::printf("ARMED flipfix-fingerprint: %llu windows, %llu reads consumed new windows\n",
                    static_cast<unsigned long long>(kPasses),
                    static_cast<unsigned long long>(consumed));
        std::fflush(stdout);
    }
