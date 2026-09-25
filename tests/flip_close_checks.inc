// Included in CoreConcurrencyTest: actual close/drain/planner, no worker or socket.
    static void flip_close() {
        for (const uint32_t databases : {16u, 1u}) {
            Fixture f(false, 8, 16, databases);
            Client coordinator(-1);
            f.client(coordinator);
            f.server.thread(f.io_id).add_client(&coordinator);
            f.server.client_accepted();
            Client* closing = new Client(-1);
            f.client(*closing);
            closing->set_id(2);
            f.server.thread(f.io_id).add_client(closing);
            f.server.client_accepted();
            // DB16 holds even a peer IO's epoch for the whole pass. DB1 can
            // reach the same lifetime window with a post-Done executor tail.
            const uint32_t peer = databases == 16 ? 1 : f.source;
            std::optional<Server::DatabaseWorkScope> database_pass;
            std::optional<Server::ClientWorkScope> executor_tail;
            if (databases == 16) database_pass.emplace(f.server, peer);
            else executor_tail.emplace(f.server, peer);
            require(f.server.client_work_epoch(peer) & 1, "FLIP close peer epoch armed");
            closing->mark_closing(); // fd=-1: only state/lifetime machinery is exercised.
            f.io.close_client(closing);
            require(f.server.thread(f.io_id).client_count() == 1 &&
                        f.server.live_clients() == 2 && closing->in_active() && !closing->dead(),
                    "FLIP close window: detached client still live behind captured epoch");
            std::string error;
            require(f.server.flip_begin(3, 5, f.io_id, error), "admit actual FLIP at 16-shard 6:2 geometry");
            require(!f.server.flip_build_client_plan(&coordinator, error) &&
                        error == "ERR FLIP connection ownership count is not conserved",
                    "premature FLIP planner reproduces exact ownership-count refusal");
            std::printf("ARMED flip-close db%u: %s (owned=1 live=2)\n", databases, error.c_str());
            std::fflush(stdout);
            require(!f.io.flip_io_drained(), "FLIP drain must wait for detached closing client");
            require(!closing->dead() && f.server.live_clients() == 2,
                    "waiting for FLIP drain preserves client lifetime");
            database_pass.reset();
            executor_tail.reset();
            // A newer peer pass may already be active: the captured epoch alone
            // must finish. Never replace the lifetime fence with an idle snapshot.
            Server::ClientWorkScope newer(f.server, peer);
            f.io.close_client(closing);
            require(closing->dead() && f.server.live_clients() == 1,
                    "close completes after captured epoch despite newer active pass");
            require(!f.io.flip_io_drained(), "FLIP still waits for corpse/channel grace");
            f.io.reap_dead();
            f.io.reap_dead();
            require(f.io.flip_io_drained(), "FLIP drain opens after real close and corpse grace");
            error.clear();
            require(f.server.flip_build_client_plan(&coordinator, error) && error.empty(),
                    "same FLIP planner succeeds after close without weakening count law");
            f.server.flip_refuse_active(); // state-only fixture never commits ownership.
            f.server.thread(f.io_id).remove_client(&coordinator);
            f.server.thread(f.io_id).release_wb_slot(coordinator.wb_slot());
            f.server.client_released();
        }
    }
