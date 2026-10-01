// Included inside the existing physical-schedule witness's CoreConcurrencyTest.
// Real Phase2/ROB/WB, synthetic SQ, no listener or execution thread.
static unsigned wb_waits(Client& c) {
#if WBHYBRID2_DELAY
    return c.wb_deferrals();
#else
    (void)c; return 0;
#endif
}
static bool wb_can_wait(unsigned waits) {
#if WBHYBRID2_DELAY
    return waits < WBHYBRID2_DELAY;
#else
    (void)waits; return true;
#endif
}
template <bool Fused, bool Local = false> static void wbland_policies(bool r7) {
    for (unsigned depth : {2u, 4u, 5u, 8u, 16u, 17u, 32u, 64u}) for (int policy : {0, 1}) {
        Fixture<Fused, Local> f(policy);
        std::vector<std::unique_ptr<Client>> clients;
        std::array<bool, 96> queued; queued.fill(true);
        std::array<unsigned, 96> waits{};
        for (unsigned i = 0; i < queued.size(); ++i) {
            auto c = std::make_unique<Client>(-1); f.client(*c, i+1);
            fill(*c, depth, i%depth+1); f.io.enqueue_serve(c.get()); clients.push_back(std::move(c));
        }
        unsigned total_served = 0;
        for (unsigned pass = 0; pass < 4; ++pass) {
            phase(f, r7);
            unsigned pending = 0;
            for (unsigned i = 0; i < clients.size(); ++i) {
                Client& c = *clients[i];
                const unsigned prefix = i%depth+1;
                const bool complete = depth <= WBHYBRID2_SMALL && wb_can_wait(waits[i]);
                const unsigned need = complete ? depth : depth/2 + depth%2;
                if (queued[i] && (policy == 0 || prefix >= need)) {
                    queued[i] = false; waits[i] = 0; ++total_served;
                } else if (queued[i] && complete && WBHYBRID2_DELAY) ++waits[i];
                require(c.serve_pending() == queued[i], "bounded physical visit decision");
                require(c.rob().in_flight() == (queued[i] ? depth : depth-prefix),
                        "bounded physical visit retires exact prefix");
                require(wb_waits(c) == waits[i], "physical serve resets and deferral saturates");
                pending += queued[i];
            }
            require(f.io.pending_serve_.size() == pending, "captured FIFO count");
            unsigned previous = 0;
            for (Client* c : f.io.pending_serve_) {
                require(c->id() > previous, "FIFO rotations preserve deferred relative order");
                previous = c->id();
            }
            require(f.io.wb_.stats().serves == total_served, "one visit per captured client");
        }
        // Complete remaining work and empty the FIFO before giving the SAME
        // connections a new short pipe. Old sends may still be outstanding.
        for (auto& c : clients) {
            for (unsigned i = 0; i < c->rob().in_flight(); ++i)
                c->rob().at(c->rob().flush_id()+i).state.store(OpState::Done, std::memory_order_release);
            f.io.enqueue_serve(c.get());
        }
        phase(f, r7);
        require(f.io.pending_serve_.empty(), "complete pipes leave FIFO");
        for (auto& c : clients) {
            require(c->rob().in_flight() == 0 && wb_waits(*c) == 0, "completion resets count");
            fill(*c, 8, 4); f.io.enqueue_serve(c.get());
        }
        phase(f, r7);
        for (auto& c : clients) {
            const bool complete = policy && WBHYBRID2_SMALL;
            require(c->rob().in_flight() == (complete ? 8u : 4u),
                    "served connection completes again next pipe");
            require(wb_waits(*c) == unsigned(complete && WBHYBRID2_DELAY), "new pipe wait count");
        }
    }
    // Dead entries bypass defer() but must clear a nonzero wait count, and closing
    // live entries must still drain. Exercise the physical envelope, including R7.
    Fixture<Fused, Local> f;
    Client dead(-1), closing(-1); f.client(dead, 1); f.client(closing, 2);
#if WBHYBRID2_DELAY
    dead.wb_deferrals() = closing.wb_deferrals() = WBHYBRID2_DELAY;
#endif
    dead.mark_dead(); closing.mark_closing(); fill(closing, 1, 1);
    f.io.enqueue_serve(&dead); f.io.enqueue_serve(&closing); phase(f, r7);
    require(f.io.pending_serve_.empty() && !dead.serve_pending() && !closing.serve_pending(), "dead/closing pins released");
    require(wb_waits(dead) == 0 && wb_waits(closing) == 0 && closing.rob().in_flight() == 0,
            "dead and closing exits reset physical counter");
}
