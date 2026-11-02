#pragma once
#include "thread.h"
#include "../net/conn.h"
#include <deque>
#include <list>
#include <map>
#include <memory>
#include <unordered_map>

namespace tomo {
// Owner-local indexes over parked tasks. Nothing is allocated before the first
// park. Empty tests and every following ExLoop field retain the deque layout.
// Tasks are removed from both indexes before execution/forwarding can release
// the ROB or hand the shard to another owner; no index is shared across owners.
class AtomicParkedTasks {
    using Fifo = std::list<Task>;
    using ByOp = std::multimap<uint64_t, Fifo::iterator>;
    struct Connection {
        ByOp tasks;
        ByOp::iterator poll;
        std::list<Client*>::iterator rotation;
    };
    struct State {
        Fifo fifo;
        std::unordered_map<Client*, Connection> connections;
        std::list<Client*> rotation;
    };
    std::unique_ptr<State> state_;
    uint64_t reserved_ = 0;
    uint64_t removed_ = 0;
    std::byte gap_[24]{};
    uint64_t added_ = 0;
    std::byte tail_[24]{};

    void remove(Fifo::iterator task) {
        auto found = state_->connections.find(task->client);
        auto& connection = found->second;
        auto it = connection.tasks.lower_bound(task->op_id);
        while (it->second != task) ++it;
        const bool polled = connection.poll == it;
        connection.tasks.erase(it);
        if (connection.tasks.empty()) {
            state_->rotation.erase(connection.rotation);
            state_->connections.erase(found);
        } else if (polled || connection.poll->first != connection.tasks.begin()->first) {
            connection.poll = connection.tasks.begin();
        }
        state_->fifo.erase(task);
        ++removed_;
    }
public:
    bool empty() const { return removed_ == added_; }
    size_t size() const { return added_ - removed_; }
    auto begin() { return state_ ? state_->fifo.begin() : Fifo::iterator{}; }
    auto end() { return state_ ? state_->fifo.end() : Fifo::iterator{}; }
    auto begin() const { return state_ ? state_->fifo.cbegin() : Fifo::const_iterator{}; }
    auto end() const { return state_ ? state_->fifo.cend() : Fifo::const_iterator{}; }
    auto erase(Fifo::iterator task) {
        auto next = std::next(task);
        remove(task);
        return next;
    }
    void push_back(const Task& task) {
        if (!state_) state_ = std::make_unique<State>();
        state_->fifo.push_back(task);
        auto [it, fresh] = state_->connections.try_emplace(task.client);
        auto& connection = it->second;
        if (fresh) {
            state_->rotation.push_back(task.client);
            connection.rotation = std::prev(state_->rotation.end());
        }
        connection.tasks.emplace(task.op_id, std::prev(state_->fifo.end()));
        if (fresh || task.op_id < connection.poll->first)
            connection.poll = connection.tasks.begin();
        ++added_;
    }
    const Task& front() const { return state_->fifo.front(); }
    void pop_front() { remove(state_->fifo.begin()); }
    size_t connections() const { return empty() ? 0 : state_->connections.size(); }
    const Task& oldest() const {
        return *state_->connections.at(state_->rotation.front()).poll->second;
    }
    // Rotate equal-op siblings too: a destination phase may need its source
    // fragment on this same owner. Younger operations are never polled first.
    void rotate_oldest() {
        auto& connection = state_->connections.at(state_->rotation.front());
        auto next = std::next(connection.poll);
        connection.poll = next == connection.tasks.end() ||
            next->first != connection.tasks.begin()->first ? connection.tasks.begin() : next;
        state_->rotation.splice(state_->rotation.end(), state_->rotation,
                                state_->rotation.begin());
    }
    void pop_oldest() {
        auto task = state_->connections.at(state_->rotation.front()).poll->second;
        rotate_oldest();
        remove(task);
    }
    template<class Fn>
    bool older(Client* client, uint64_t op_id, Fn&& match) const {
        if (empty()) return false;
        auto found = state_->connections.find(client);
        if (found == state_->connections.end()) return false;
        for (auto it = found->second.tasks.begin();
             it != found->second.tasks.end() && it->first < op_id; ++it)
            if (match(*it->second)) return true;
        return false;
    }
    bool promote_writer(const void* token, int32_t sid) {
        if (empty()) return false;
        for (auto it = state_->fifo.begin(); it != state_->fifo.end(); ++it) {
            if (!it->client) continue;
            auto& op = it->client->rob().at(it->op_id);
            if (&op != token || (it->shard >= 0 ? it->shard : op.shard) != sid) continue;
            auto& connection = state_->connections.at(it->client);
            state_->rotation.splice(state_->rotation.begin(), state_->rotation,
                                    connection.rotation);
            if (it == state_->fifo.begin()) return false;
            state_->fifo.splice(state_->fifo.begin(), state_->fifo, it);
            return true;
        }
        return false;
    }
};
static_assert(sizeof(AtomicParkedTasks) == sizeof(std::deque<Task>));
static_assert(alignof(AtomicParkedTasks) == alignof(std::deque<Task>));
} // namespace tomo
