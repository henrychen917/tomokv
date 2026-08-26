// climon.cc -- cold implementation of IO-owned CLIENT LIST/KILL scatter.

#include "../core/io_loop.h"

namespace tomo {

bool IoLoop::climon_parse_i64(Slice value, int64_t& out) {
    if (!value.n) return false;
    uint32_t pos = 0;
    bool negative = false;
    if (value.p[pos] == '-') { negative = true; if (++pos == value.n) return false; }
    uint64_t magnitude = 0;
    const uint64_t limit = negative ? uint64_t{INT64_MAX} + 1 : uint64_t{INT64_MAX};
    for (; pos < value.n; pos++) {
        const char ch = value.p[pos];
        if (ch < '0' || ch > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(ch - '0');
        if (magnitude > (limit - digit) / 10) return false;
        magnitude = magnitude * 10 + digit;
    }
    if (negative) {
        out = magnitude == uint64_t{INT64_MAX} + 1
            ? INT64_MIN : -static_cast<int64_t>(magnitude);
    } else {
        out = static_cast<int64_t>(magnitude);
    }
    return true;
}

std::string IoLoop::climon_string(Slice value) {
    return std::string(value.p, value.n);
}

bool IoLoop::climon_parse_client_type(Slice value, ClientTypeFilter& type) {
    if (value.eq_icase("normal")) type = ClientTypeFilter::Normal;
    else if (value.eq_icase("master")) type = ClientTypeFilter::Master;
    else if (value.eq_icase("replica") || value.eq_icase("slave"))
        type = ClientTypeFilter::Replica;
    else if (value.eq_icase("pubsub")) type = ClientTypeFilter::Pubsub;
    else return false;
    return true;
}

void IoLoop::climon_copy_client_filter(PubSubEvent& target, const PubSubEvent& source) {
    target.client_filter_mask = source.client_filter_mask;
    target.client_type = source.client_type;
    target.client_id = source.client_id;
    target.client_max_age = source.client_max_age;
    target.caller_id = source.caller_id;
    target.client_skipme = source.client_skipme;
    target.client_old_form = source.client_old_form;
    target.client_addr = source.client_addr;
    target.client_laddr = source.client_laddr;
    target.client_user = source.client_user;
    target.items = source.items;
}

IoLoop::ClimonStartResult IoLoop::climon_begin_client_scatter(
        Client* client, const PubSubEvent& filter, ClimonPendingKind kind) {
    const auto& ios = srv_->placement().ifid_threads();
    std::vector<PubSubEvent*> events;
    events.reserve(ios.size());
    for (uint32_t io : ios) {
        PubSubEvent* event = pubsub_new_event(
            kind == ClimonPendingKind::ClientList
                ? PubSubEventKind::ClientListRequest
                : PubSubEventKind::ClientKillRequest);
        event->target_io = io;
        climon_copy_client_filter(*event, filter);
        events.push_back(event);
    }

    ClimonPending pending;
    pending.kind = kind;
    pending.client = client;
    pending.op_id = client->rob().dispatch_id();
    pending.remaining = static_cast<uint32_t>(events.size());
    pending.old_form = filter.client_old_form;
    if (!climon_pending_.emplace(client->id(), std::move(pending)).second) std::abort();

    srv_->client_scatter_started();
    client->rob().publish();
    client->set_scatter_barrier(true);
    for (PubSubEvent* event : events) {
        event->origin_io = self_->id();
        event->conn_id = client->id();
        event->op_id = client->rob().dispatch_id() - 1;
        pubsub_post(event->target_io, event);
    }
    pubsub_drain_events();
    return ClimonStartResult::Async;
}

IoLoop::ClimonStartResult IoLoop::climon_start_client_list(Client* client, Op& op) {
    PubSubEvent filter;
    filter.caller_id = client->id();
    if (op.argc() == 2) {
        // No filter.
    } else if (op.argc() == 4 && op.arg(2).eq_icase("type")) {
        if (!climon_parse_client_type(op.arg(3), filter.client_type)) {
            std::string error = "ERR Unknown client type '";
            error.append(op.arg(3).p, op.arg(3).n);
            error.push_back('\'');
            reply_err(op.sink(), error.c_str());
            return ClimonStartResult::Sync;
        }
        filter.client_filter_mask |= ClientFilterType;
    } else if (op.argc() > 3 && op.arg(2).eq_icase("id")) {
        filter.client_filter_mask |= ClientFilterIdList;
        for (uint32_t arg = 3; arg < op.argc(); arg++) {
            int64_t id = 0;
            if (!climon_parse_i64(op.arg(arg), id)) {
                reply_err(op.sink(), "ERR Invalid client ID");
                return ClimonStartResult::Sync;
            }
            if (id >= 0)
                filter.items.push_back(PubSubEventItem{
                    0, false, static_cast<uint64_t>(id), {}});
        }
    } else {
        reply_syntax(op.sink());
        return ClimonStartResult::Sync;
    }
    return climon_begin_client_scatter(client, filter, ClimonPendingKind::ClientList);
}

IoLoop::ClimonStartResult IoLoop::climon_start_client_kill(Client* client, Op& op) {
    if (op.argc() == 2) {
        reply_err(op.sink(), "ERR wrong number of arguments for 'client|kill' command");
        return ClimonStartResult::Sync;
    }
    PubSubEvent filter;
    filter.caller_id = client->id();
    filter.client_skipme = true;
    if (op.argc() == 3) {
        filter.client_old_form = true;
        filter.client_skipme = false;
        filter.client_filter_mask = ClientFilterAddr;
        filter.client_addr = climon_string(op.arg(2));
    } else {
        for (uint32_t arg = 2; arg < op.argc();) {
            if (arg + 1 >= op.argc()) {
                reply_syntax(op.sink());
                return ClimonStartResult::Sync;
            }
            const Slice option = op.arg(arg);
            const Slice value = op.arg(arg + 1);
            if (option.eq_icase("id")) {
                int64_t id = 0;
                if (!climon_parse_i64(value, id) || id <= 0) {
                    reply_err(op.sink(), "ERR client-id should be greater than 0");
                    return ClimonStartResult::Sync;
                }
                filter.client_filter_mask |= ClientFilterId;
                filter.client_id = static_cast<uint64_t>(id);
            } else if (option.eq_icase("maxage")) {
                int64_t age = 0;
                if (!climon_parse_i64(value, age)) {
                    reply_err(op.sink(), "ERR maxage is not an integer or out of range");
                    return ClimonStartResult::Sync;
                }
                if (age <= 0) {
                    reply_err(op.sink(), "ERR maxage should be greater than 0");
                    return ClimonStartResult::Sync;
                }
                filter.client_filter_mask |= ClientFilterMaxAge;
                filter.client_max_age = static_cast<uint64_t>(age);
            } else if (option.eq_icase("type")) {
                if (!climon_parse_client_type(value, filter.client_type)) {
                    std::string error = "ERR Unknown client type '";
                    error.append(value.p, value.n);
                    error.push_back('\'');
                    reply_err(op.sink(), error.c_str());
                    return ClimonStartResult::Sync;
                }
                filter.client_filter_mask |= ClientFilterType;
            } else if (option.eq_icase("addr")) {
                filter.client_filter_mask |= ClientFilterAddr;
                filter.client_addr = climon_string(value);
            } else if (option.eq_icase("laddr")) {
                filter.client_filter_mask |= ClientFilterLaddr;
                filter.client_laddr = climon_string(value);
            } else if (option.eq_icase("user")) {
                uint32_t user_index = 0;
                if (!acl_find_user(value, user_index)) {
                    std::string error = "ERR No such user '";
                    error.append(value.p, value.n);
                    error.push_back('\'');
                    reply_err(op.sink(), error.c_str());
                    return ClimonStartResult::Sync;
                }
                (void)user_index;
                filter.client_filter_mask |= ClientFilterUser;
                filter.client_user = climon_string(value);
            } else if (option.eq_icase("skipme")) {
                if (value.eq_icase("yes")) filter.client_skipme = true;
                else if (value.eq_icase("no")) filter.client_skipme = false;
                else {
                    reply_syntax(op.sink());
                    return ClimonStartResult::Sync;
                }
            } else {
                reply_syntax(op.sink());
                return ClimonStartResult::Sync;
            }
            arg += 2;
        }
    }
    return climon_begin_client_scatter(client, filter, ClimonPendingKind::ClientKill);
}

IoLoop::ClimonStartResult IoLoop::climon_start_client_command(Client* client, Op& op) {
    if (op.arg(1).eq_icase("list")) return climon_start_client_list(client, op);
    if (op.arg(1).eq_icase("kill")) return climon_start_client_kill(client, op);

    // Ordinary CLIENT subcommands stay owner-local. Keeping this fallback in the cold object
    // prevents LIST/KILL support from changing parse_and_dispatch's code placement.
    command_set_local_context(client, self_);
    snapshot_bind_io(self_, &ring_);
    op.spec->handler(srv_->shard(0), op);
    snapshot_bind_io(nullptr, nullptr);
    command_set_local_context(nullptr, nullptr);
    return ClimonStartResult::Sync;
}

void IoLoop::climon_handle_client_request(PubSubEvent& event) {
    srv_->client_scatter_io_replied();
    // CLIENT traffic is cold and needs a current age/MAXAGE snapshot even when timeout and
    // output-buffer cron are disabled. Each owner samples once for its entire local pass.
    cached_now_ms_ = now_ns() / 1000000ull;
    cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
    const bool list = event.kind == PubSubEventKind::ClientListRequest;
    PubSubEvent* result = pubsub_new_event(
        list ? PubSubEventKind::ClientListResult : PubSubEventKind::ClientKillResult);
    result->conn_id = event.conn_id;
    result->op_id = event.op_id;
    std::vector<Client*> victims;
    for (Client* candidate : self_->clients()) {
        if (!candidate || !command_client_filter_match(*candidate, event, cached_now_ms_))
            continue;
        if (list) result->message += command_client_info_line(*candidate, cached_now_ms_);
        else victims.push_back(candidate);
    }
    if (!list) {
        result->count = victims.size();
        for (Client* victim : victims) {
            if (victim->id() == event.caller_id) {
                victim->mark_closing();
                mark_active(victim);
            } else {
                close_client(victim);
            }
        }
    }
    pubsub_post(event.origin_io, result);
}

void IoLoop::climon_finish_client_pending(uint64_t conn_id) {
    auto found = climon_pending_.find(conn_id);
    if (found == climon_pending_.end()) return;
    ClimonPending& pending = found->second;
    Client* client = pending.client;
    if (!client || client->dead()) { climon_pending_.erase(found); return; }
    Op& op = client->rob().at(pending.op_id);
    if (pending.kind == ClimonPendingKind::ClientList) {
        reply_verbatim(op.sink(), Slice(pending.body.data(), pending.body.size()),
                       "txt", op.resp3());
    } else if (pending.kind == ClimonPendingKind::ClientKill) {
        if (pending.old_form) {
            if (pending.count) reply_ok(op.sink());
            else reply_err(op.sink(), "ERR No such client");
        } else {
            reply_int(op.sink(), static_cast<long long>(pending.count));
        }
    }
    op.state.store(OpState::Done, std::memory_order_release);
    enqueue_serve(client);
    mark_active(client);
    climon_pending_.erase(found);
}

void IoLoop::climon_handle_client_result(PubSubEvent& event) {
    auto found = climon_pending_.find(event.conn_id);
    if (found == climon_pending_.end() || found->second.op_id != event.op_id) return;
    ClimonPending& pending = found->second;
    if (event.kind == PubSubEventKind::ClientListResult) pending.body += event.message;
    else if (event.kind == PubSubEventKind::ClientKillResult) pending.count += event.count;
    if (!pending.remaining) std::abort();
    if (--pending.remaining == 0) climon_finish_client_pending(event.conn_id);
}

bool IoLoop::climon_handle_event(PubSubEvent& event) {
    switch (event.kind) {
        case PubSubEventKind::ClientListRequest:
        case PubSubEventKind::ClientKillRequest:
            climon_handle_client_request(event);
            return true;
        case PubSubEventKind::ClientListResult:
        case PubSubEventKind::ClientKillResult:
            climon_handle_client_result(event);
            return true;
        default:
            return false;
    }
}

}  // namespace tomo
