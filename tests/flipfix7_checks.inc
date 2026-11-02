// Serverless states at the exact production drain and deferred-serve boundary.
static void flipfix7_output(unsigned databases) {
    Fixture f(false, 8, 16, databases);
    Client client(-1);
    f.client(client);
    f.server.thread(f.io_id).add_client(&client);
    f.server.client_accepted();
    f.server.flip_stage_.store(FlipStage::IoDrain);
    require(f.io.flip_io_drained(), "empty initial IO drain");
    require(f.io.flip_output_hold() && client.serve_pending() && f.io.pending_serve_.empty(),
            "IoDrain ack holds the existing serve pin off the socket FIFO");
    client.append_fill("+late\r\n", 7);
    f.io.enqueue_serve(&client);
    require(f.io.pending_serve_.empty() && client.flip_held_output_idle(),
            "late owned output neither sends on source nor vetoes transfer");
    client.watch_ref();
    require(!client.flip_held_output_idle(), "held output does not waive a WATCH pin");
    client.watch_unref();
    client.set_send_inflight(true);
    require(!client.flip_held_output_idle(), "kernel pointer cannot move");
    f.server.flip_stage_.store(FlipStage::ClientInstall);
    require(f.io.flip_io_drained(), "ClientInstall ignores owned socket output and send");
    client.set_send_inflight(false);
    client.barrier_acquire(BarrierOwner::Exec);
    require(!f.io.flip_io_drained(), "post-commit still waits for executor barrier");
    client.barrier_release(BarrierOwner::Exec);
    const char borrowed[] = "borrowed";
    client.append_borrow_segment(borrowed, 8, f.sid());
    require(!f.io.flip_io_drained() && !client.flip_held_output_idle(),
            "borrowed storage is not socket-owned output");
    unsigned releases = 0;
    client.release_all_segments([&](int32_t sid, const char* ptr) {
        require(sid == f.sid() && ptr == borrowed, "exact borrow lifetime"); ++releases;
    });
    require(releases == 1, "borrow released exactly once");
    f.server.flip_stage_.store(FlipStage::Rollback);
    f.io.flip_output_release();
    require(f.io.pending_serve_.size() == 1 && client.serve_pending() &&
            f.io.flip_held_output_.empty(), "rollback resumes the same output frontier once");
    f.io.pending_serve_.clear(); client.set_serve_pending(false);
    f.server.flip_stage_.store(FlipStage::Idle);
    f.server.thread(f.io_id).remove_client(&client);
    f.server.thread(f.io_id).release_wb_slot(client.wb_slot());
    f.server.client_released();
    std::printf("ARMED flipfix7 owned-output db%u\n", databases);
}
