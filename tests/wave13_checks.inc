// Integration boundaries absent from the isolated wave11-based lanes.
static void wave13_flush_unpublished(unsigned databases, unsigned atomic) {
    Fixture f(false, 8, 16, databases, 6, false, -1, atomic);
    command_bind_server(&f.server);
    std::string error;
    require(acl_initialize(f.server, f.server.cfg(), error), "wave13 default ACL");
    for (const char* name : {"FLUSHALL", "FLUSHDB"}) {
        const auto request =
            std::string("*1\r\n$") + std::to_string(std::strlen(name)) + "\r\n" + name + "\r\n";
        Client client(-1);
        f.client(client);
        require(request.size() < client.rcap(), "wave13 frame fits receive buffer");
        std::memcpy(client.rbuf(), request.data(), request.size());
        client.commit_read(request.size());
        for (auto tid : {f.source, f.destination}) {
            auto& owner = f.server.thread(tid);
            const auto capacity = owner.task_free_slots(f.io_id);
            require(capacity != 0, "wave13 fresh owner lane");
            for (unsigned i = 0; i < capacity; ++i)
                require(owner.post_task_quiet(f.io_id, Task{}, f.io.self_->sig()),
                        "wave13 fill real owner lane");
            require(owner.task_free_slots(f.io_id) == 0, "wave13 FLUSH refusal armed");
            f.io.flip_pass_begin();
            f.io.parse_and_dispatch<false>(&client);
            require(client.rpos() == 0 && client.rob().in_flight() == 0 &&
                        !client.has_atomic_group_io() && !f.server.atomic_work_active() &&
                        !client.flip_session_pending(),
                    "FLUSH leaves no persistent unpublished unit");
            for (auto demand : f.io.dispatch_needed_)
                require(demand == 0, "FLUSH capacity exit clears all owner demand");
            require(owner.drain_tasks_unmasked([](Task task) {
                require(task.client == nullptr, "no FLUSH fragment escaped refusal");
            }) == capacity,
                    "restore actual lane capacity");
            require(f.server.flip_begin(5, 3, 0, error), "FLIP after FLUSH refusal admitted");
            require(!f.io.flip_session_drain_refused() && !f.server.flip_failed(error),
                    "abandoned FLUSH cannot hold S2 admission across FLIP");
            f.server.flip_refuse_active();
        }
        f.io.self_->release_wb_slot(client.wb_slot());
    }
    acl_shutdown();
    command_bind_server(nullptr);
    std::printf("ARMED wave13 FLUSH unpublished db%u atomic%u both capacity exits\n", databases,
                atomic);
}
