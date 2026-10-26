// AT4.12. Cold script admission and escalation, included after txn_group.inc.
#include <list>
namespace tomo {
struct ScriptWindow {
    std::list<Client*> fifo;
    std::unordered_map<Client*, std::list<Client*>::iterator> members;
};
namespace {
void script_window_refresh(Server& server, uint32_t io) {
    auto& lane = server.multi_retry_lane(io);
    const auto released = lane.script_releases.exchange(0, std::memory_order_acquire);
    if (released > (lane.script_admission & 127u)) std::abort();
    lane.script_admission -= released;
}

Client* script_window_head(Server& server, ScriptWindow& window) {
    // Only a per-client drain can make an enqueued head undispatchable.
    uint64_t paused = 0;
    if (server.lb_stage() == LbStage::ClientDrain) {
        auto record = server.lb_client_read();
        if (record) paused = server.lb_client_move().id;
    }
    for (Client* client : window.fifo)
        if (!client->closing() && !client->dead() && client->id() != paused)
            return client;
    return nullptr;
}

bool script_window_wait(Server& server, uint32_t io, Client& client) {
    auto& lane = server.multi_retry_lane(io);
    script_window_refresh(server, io);
    if (lane.script_admission < 4) return true;
    try {
        if (!lane.script_window) lane.script_window = std::make_shared<ScriptWindow>();
        auto& window = *lane.script_window;
        if (!window.members.contains(&client)) {
            window.fifo.push_back(&client);
            try { window.members.emplace(&client, std::prev(window.fifo.end())); }
            catch (...) { window.fifo.pop_back(); throw; }
            lane.script_admission |= 128u;
            server.note_script_window_wait();
        }
        return (lane.script_admission & 127u) < 4 &&
               script_window_head(server, window) == &client;
    } catch (const std::bad_alloc&) {
        // No slot, ROB entry or credit was taken. Retry the unconsumed frame.
        return false;
    }
}

void script_window_admit(ScatterState& state, Client* client) {
    auto& lane = state.server->multi_retry_lane(state.owner_io);
    if ((lane.script_admission & 127u) >= 4) std::abort();
    if (client) script_window_forget(*state.server, state.owner_io, *client);
    ++lane.script_admission;
    state.script_slot_live = true;
}

void script_window_release(ScatterState& state) {
    if (!state.script_slot_live) return;
    state.script_slot_live = false;
    auto& lane = state.server->multi_retry_lane(state.owner_io);
    if (lane.script_releases.fetch_add(1, std::memory_order_release) >= 4) std::abort();
}
} // namespace

void script_window_forget(Server& server, uint32_t io, Client& client) {
    auto& lane = server.multi_retry_lane(io);
    if (!lane.script_window) return;
    auto& window = *lane.script_window;
    const auto found = window.members.find(&client);
    if (found == window.members.end()) return;
    window.fifo.erase(found->second);
    window.members.erase(found);
    if (window.fifo.empty()) lane.script_admission &= 127u;
}

void script_window_resume(Server& server, ScatterArenaPool& pool, uint32_t io, Client& client) {
    auto& lane = server.multi_retry_lane(io);
    script_window_refresh(server, io);
    if (!server.atomic_can_admit(io)) return;
    if (lane.script_window && lane.script_window->members.contains(&client)) {
        if ((lane.script_admission & 127u) < 4 &&
            script_window_head(server, *lane.script_window) == &client)
            client.set_atomic_backpressure(false);
    } else if (pool.can_register_snapshot()) {
        client.set_atomic_backpressure(false);
    }
}
} // namespace tomo
