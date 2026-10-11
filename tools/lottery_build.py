#!/usr/bin/env python3
"""Insert nonblocking observations in an isolated DEBUG witness build.

Like racefix_build.py, this never edits production source. Every anchor must
match exactly once (explicit counts for shared bodies), or the build refuses.
Ordinary all/ASAN/production-unit builds do not include lottery_hooks.h.
"""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def prepare(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / 'build'):
        raise ValueError('witness source must stay inside this worktree/build')
    output.mkdir(parents=True, exist_ok=True)
    for name in ('src', 'third_party'):
        shutil.copytree(ROOT / name, output / name, dirs_exist_ok=True)
    (output / 'tests').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'tests/lottery_hooks.h', output / 'tests/lottery_hooks.h')
    shutil.copy2(ROOT / 'Makefile', output / 'Makefile')
    changes = []

    def patch(path, old, new, count=1):
        file = output / path
        text = file.read_text()
        if text.count(old) != count:
            raise ValueError(f'{path}: expected {count} anchors, found {text.count(old)}: {old[:80]}')
        file.write_text(text.replace(old, new))
        changes.append(dict(path=path, anchor=old, replacement=new, count=count))

    def after(path, anchor, code, count=1):
        patch(path, anchor, anchor + '\n' + code, count)

    # Namespace-isolated trace state, compiled only in the copied tree.
    after('Makefile', 'CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread',
          'override CXXFLAGS += -include tests/lottery_hooks.h')
    after('src/cmd/t_server.cc', 'void cmd_debug_impl(Shard& shard, Op& op) {', '''
    if (op.arg(1).eq_icase("lottery")) {
        if (op.argc() == 5 && op.arg(2).eq_icase("arm")) {
            std::string mask(op.arg(3).p, op.arg(3).n), path(op.arg(4).p, op.arg(4).n);
            char* end = nullptr;
            const auto value = std::strtoull(mask.c_str(), &end, 10);
            if (end && !*end && lottery::start(value, path)) reply_ok(op.sink());
            else reply_err(op.sink(), "ERR lottery arm failed");
        } else if (op.argc() == 3 && op.arg(2).eq_icase("stop")) {
            if (lottery::stop()) reply_ok(op.sink());
            else reply_err(op.sink(), "ERR lottery incomplete trace");
        } else if (op.argc() == 3 && op.arg(2).eq_icase("config")) {
            lottery::event(lottery::bit(1), "config_check", 0,
                g_server->live_config_snapshot(g_thread->id()).version, g_server->nthreads());
            reply_ok(op.sink());
        } else if (op.argc() == 4 && op.arg(2).eq_icase("mark")) {
            std::string name(op.arg(3).p, op.arg(3).n);
            if (name.find_first_not_of("abcdefghijklmnopqrstuvwxyz_0123456789") != std::string::npos)
                reply_err(op.sink(), "ERR lottery marker");
            else { lottery::event(~uint64_t{0}, name.c_str()); reply_ok(op.sink()); }
        } else reply_err(op.sink(), "ERR lottery syntax");
        return;
    }''')
    after('src/core/ex_loop.h', '        live_config_version_ = snapshot.version;',
          '        lottery::event(lottery::bit(1), "config_ex", self_->id(), snapshot.version);')
    after('src/core/io_loop.h', '        notify_config_version_ = snapshot.version;',
          '        lottery::event(lottery::bit(1), "config_io", self_->id(), snapshot.version);')

    # W2/W16: boundaries carry operation identity and actual key hashes. The W16
    # begin is AFTER the last owner joins; end is BEFORE epoch publication.
    after('src/cmd/multi.inc', '                    assemble_ownerless_replies(state);', '''
                    if (lottery::enabled(lottery::bit(2)|lottery::bit(16))) {
                        lottery::event(lottery::bit(2)|lottery::bit(16), "write_new",
                            lottery::ptr(&state.epoch));
                        for (const auto& key : state.write_keys)
                            lottery::event(lottery::bit(2)|lottery::bit(16), "exec_key",
                                lottery::ptr(&state.epoch), key.hash, state.origin_conn_id, key.shard);
                        lottery::event(lottery::bit(2)|lottery::bit(16), "exec_installed",
                            lottery::ptr(&state.epoch), state.shards.size(), state.write_keys.size(),
                            state.origin_conn_id);
                    }''')
    after('src/core/server.h', '        store_tickets(first);',
          '        lottery::event(lottery::bit(2), "commit", 0, first, tickets);')
    patch('src/core/server.h', '            epoch.store(ticket, std::memory_order_release);', '''
            lottery::event(lottery::bit(2)|lottery::bit(9)|lottery::bit(16), "exec_decision",
                           lottery::ptr(&epoch), ticket);
            epoch.store(ticket, std::memory_order_release);''')
    after('src/store/flatstore_atomic.inc',
          '            if (owner.group_epoch && epoch == 0 && !own_committed) {', '''
                lottery::event(lottery::bit(16), "foreign_undecided",
                    lottery::ptr(owner.group_epoch), hash, snapshot, atomic_read_origin_conn_id_,
                    owner.origin_conn_id);''')
    after('src/cmd/scatter_engine.inc', '    dispatch.state = state;', '''
    if (!(op.spec->flags & (CmdFlags::Write|CmdFlags::SnapshotWrite)))
        lottery::event(lottery::bit(2), "read_new", lottery::ptr(state), state->nsub,
                       state->snapshot, state->origin_conn_id);''')
    after('src/cmd/scatter_engine.inc', '    ShardGroup& group = *group_for(state, shard.id());', '''
    const bool lottery_read = !(op.spec->flags & (CmdFlags::Write|CmdFlags::SnapshotWrite));
    lottery::Scope lottery_fragment(lottery_read ? lottery::bit(2) : 0,
        "read_begin", "read_end", lottery::ptr(&state), shard.id(), state.nsub,
        state.snapshot, state.origin_conn_id);
    if (lottery_read && lottery::enabled(lottery::bit(2)))
        for (uint32_t i=0; i<group.count; ++i)
            lottery::event(lottery::bit(2), "read_key", lottery::ptr(&state),
                          state.keys[state.key_order[group.begin+i]].hash, shard.id());''')
    after('src/cmd/multi.inc', '    const bool read_kind = command.kind == MultiCommandKind::Mget ||\n                           command.kind == MultiCommandKind::Exists;', '''
    lottery::Scope lottery_fragment(read_kind ? lottery::bit(2) : 0,
        "read_begin", "read_end", lottery::ptr(&command), shard.id(),
        command.participants.size(), multi_read_cut(state), state.origin_conn_id);
    if (read_kind && lottery::enabled(lottery::bit(2)))
        for (size_t i=0; i<command.key_args.size(); ++i)
            if (command.key_shards[i] == shard.id())
                lottery::event(lottery::bit(2), "read_key", lottery::ptr(&command),
                    FlatStore::hash_key(op.arg(command.key_args[i])), shard.id());''')
    after('src/cmd/multi.inc', '    op.attach_multi_state(dispatch);', '''
    if (lottery::enabled(lottery::bit(2)))
        for (const auto& command : dispatch->commands) {
            lottery::event(lottery::bit(2), "read_new", lottery::ptr(command.get()),
                           command->participants.size(), dispatch->snapshot, dispatch->origin_conn_id);
            if (command->scatter)
                lottery::event(lottery::bit(2), "read_new", lottery::ptr(command->scatter),
                    command->scatter->nsub, dispatch->snapshot, dispatch->origin_conn_id);
        }''')
    # Existing counters prove RYOW dispatch holds; the trace adds exact pinned
    # read lifetime around FLUSH. No delay is added to either path.
    after('src/cmd/scatter_engine.inc', 'void xshard_destroy(ScatterState* state, ScatterArenaPool& pool, uint32_t owner_io) {',
          '    lottery::event(lottery::bit(2), "read_drop", lottery::ptr(state));')
    after('src/cmd/t_server.cc', 'void cmd_flush(Shard& sh, Op& op) {',
          '    lottery::event(lottery::bit(2), "flush", sh.id());')

    # W4: compare the actual pinned cut, live deadline, and current wall time
    # at lookup. Real clock is diagnostic only; it never feeds the command.
    after('src/store/flatstore.h', '        if (!o->has_ttl_slot()) return o;\n        const int64_t at = deadline(h, o);', '''
        if (at >= 0 && at > cached_now_ms_)
            lottery::event(lottery::bit(4), "expiry_lookup", h, cached_now_ms_, at);''')

    # W6: phase-one selected element, a source push, and phase-two removal,
    # matched by the source key. Separate left/right edge evidence.
    after('src/cmd/scatter_engine.inc', '                    xshard_peek_list(object, state.from_left, result->bulk);', '''
                lottery::event(lottery::bit(6), "move_selected", lottery::ptr(&state),
                    key.hash, state.from_left, state.origin_conn_id);''')
    after('src/cmd/scatter_engine.inc', '        if (state.phase == 2) {', '''
            if (is_element_mover(state.kind))
                lottery::event(lottery::bit(6), "move_remove", lottery::ptr(&state));''')
    after('src/cmd/t_list.cc',
          'void push_generic(Shard& shard, Op& op, bool left, bool only_existing) {', '''
    lottery::Scope lottery_push(lottery::bit(6), "push_begin", "push_end",
                                FlatStore::hash_key(op.arg(1)), left);''')

    # W5/W7 lifecycle witnesses include exact client and deadline identities.
    after('src/cmd/blocking.inc', '                        blocking_reply_timeout(op, state.kind);', '''
                        lottery::event(lottery::bit(5), "block_timeout", state.client->id(),
                            state.op_id, state.deadline_ms, now_ms);''')
    after('src/core/io_loop.h', '        srv_->blocking_client_parked();', '''
        lottery::event(lottery::bit(7), "timer_start", client->id(),
                       uint64_t(kind), self_->id(), deadline_ms);''')
    after('src/core/io_loop.h', '            const DeferredTimer timer = deferred_timers_[i];', '''
            lottery::event(lottery::bit(7), "timer_visit", timer.client->id(),
                           uint64_t(timer.kind), self_->id(), timer.deadline_ms);''', count=2)
    after('src/core/io_loop.h', '            if (timer.client != client) {\n                i++;\n                continue;\n            }', '''
            lottery::event(lottery::bit(7), "timer_cancel", client->id(),
                           uint64_t(timer.kind), self_->id(), timer.deadline_ms);''')
    after('src/cmd/t_server.cc', 'void cmd_ping(Shard&, Op& op) {', '''
    if (g_client && g_thread)
        lottery::event(lottery::bit(7), "ping", g_client->id(), g_thread->id());''')
    after('src/core/io_loop.h', '        srv_->note_client_output_buffer_limit_disconnect();', '''
        lottery::event(lottery::bit(5), "obuf_close", c->id(), used,
            limit.hard_bytes, c->obuf_soft_since_s(), cached_now_s_);''')
    after('src/core/io_loop.h', '            bool closed = false;', '''
            if (timeout && (c->blocked() || c->subscriber_mode()) &&
                cached_now_s_ - c->last_interaction_s() > timeout)
                lottery::event(lottery::bit(5), "cron_exempt", c->id(), timeout,
                    c->last_interaction_s(), cached_now_s_);''')
    after('src/core/io_loop.h', '                cached_now_s_ - c->last_interaction_s() > timeout) {', '''
                lottery::event(lottery::bit(5), "idle_close", c->id(), timeout,
                    c->last_interaction_s(), cached_now_s_);''')

    # W10 and TLS parser stage: received, parsed Incomplete on THIS client.
    for file in ('src/core/io_loop.h', 'src/core/reorder.cc'):
        after(file, 'if (pr == ParseResult::Incomplete) {', '''
                lottery::event(lottery::bit(10)|lottery::bit(12), "parser_partial",
                    c->id(), self_->id(), c->is_tls(), conn.rlen()-conn.rpos());''')
    after('src/core/io_loop.h', '    void release_tls(Client* c) {\n        if (!c->is_tls()) return;',
          '        lottery::event(lottery::bit(12), "tls_retire", c->id());')
    after('src/core/io_loop.h', '    void on_tls_recv(Client* c, int res) {', '''
        if (res > 0) lottery::event(lottery::bit(12), "tls_input", c->id(), res);''')
    after('src/core/io_loop.h', '            if (result == TlsOp::WantRead || result == TlsOp::WantWrite) {', '''
                lottery::event(lottery::bit(12), "tls_handshake_wait", c->id(), uint64_t(result));''')
    after('src/core/io_loop.h', '            if (result.op == TlsOp::WantRead) {',
          '                lottery::event(lottery::bit(12), "tls_record_wait", c->id());')

    # W8/W9 already have exact preimage/apply-drain counters. W14 admission
    # is observed while holding the existing placement/snapshot mutex.
    after('src/snapshot/snapshot.cc', '        server.set_shutdown_snapshot_active(shutdown);',
          '        lottery::event(lottery::bit(14), "save_admitted", epoch_.load());')
    after('src/snapshot/snapshot.cc', '            error = "placement transition is in progress";',
          '            lottery::event(lottery::bit(14), "save_placement_busy");')
    after('src/snapshot/snapshot.cc', '            error = "Background save already in progress";',
          '            lottery::event(lottery::bit(14), "save_snapshot_busy");')

    after('src/cmd/t_stream.cc', '        if (id_zero(result)) result.seq = 1;', '''
        lottery::event(lottery::bit(15), "stream_clock", shard.id(), now,
                       header.last_id.ms, result.ms, result.seq);''')
    # Trace producer event identity and consumer completion (including forwards).
    # Used with test-side before/after markers on negative tracking drains.
    after('src/cmd/tracking.cc', 'void IoLoop::tracking_handle_event(PubSubEvent& event) {', '''
    lottery::Scope lottery_delivery(lottery::bit(13), "tracking_begin", "tracking_end",
        lottery::ptr(&event), self_->id(), uint64_t(event.kind), event.caller_id);''')

    after('src/cmd/scatter_engine.inc', '    dispatch.state = state;', '''
    if (state->atomic_group)
        lottery::event(lottery::bit(9), "apply_group", lottery::ptr(&state->epoch),
                       state->key_count);
    if (state->atomic_group && lottery::enabled(lottery::bit(2)))
    {
        lottery::event(lottery::bit(2), "write_new", lottery::ptr(&state->epoch));
        for (uint32_t i=0; i<state->key_count; ++i)
            lottery::event(lottery::bit(2), "exec_key", lottery::ptr(&state->epoch),
                state->keys[i].hash, state->origin_conn_id, state->keys[i].shard);
    }''')
    after('src/cmd/multi.inc', '    op.attach_multi_state(dispatch);', '''
    lottery::event(lottery::bit(9), "apply_group", lottery::ptr(&dispatch->epoch),
                   dispatch->write_keys.size());''')
    after('src/store/flatstore_atomic.inc', '        entry->count = index + 1;', '''
        lottery::event(lottery::bit(9), "apply_key", lottery::ptr(entry->group_epoch), hash);''')
    after('src/store/flatstore_atomic.inc', '        value = nullptr;\n        atomic_link_entry(*entry);', '''
        if (entry->group_epoch)
            lottery::event(lottery::bit(9), "apply_key", lottery::ptr(entry->group_epoch), hash);''', count=2)
    after('src/snapshot/snapshot.cc', '    const uint64_t queued = server.atomic_apply_inflight();',
          '    lottery::event(lottery::bit(9), "snapshot_drain", 0, queued);')
    patch('src/cmd/scatter_engine.inc',
          '                state->epoch.store(ticket + stored, std::memory_order_release);', '''
                lottery::event(lottery::bit(2)|lottery::bit(9), "exec_decision",
                               lottery::ptr(&state->epoch), ticket + stored);
                state->epoch.store(ticket + stored, std::memory_order_release);''')
    patch('src/cmd/atomics_glue.inc', '    if (own_undecided) return true;', '''
    if (own_undecided) {
        lottery::event(lottery::bit(2), "ryow_defer", origin_conn_id, op.hash, task.op_id);
        return true;
    }''')
    after('src/store/flatstore.h',
          '    bool deadline_elapsed(uint64_t h, const KvObj* object, int64_t now_ms) const {\n        const int64_t at = deadline(h, object);', '''
        if (at >= 0 && at > now_ms)
            lottery::event(lottery::bit(4), "expiry_lookup", h, now_ms, at);''')
    after('src/core/pubsub.inc', '    void pubsub_post(uint32_t target_io, PubSubEvent* event) {', '''
        if (event->kind == PubSubEventKind::TrackingInvalidate ||
            event->kind == PubSubEventKind::TrackingFlush ||
            event->kind == PubSubEventKind::TrackingDeliver)
            lottery::event(lottery::bit(13), "tracking_post", lottery::ptr(event), target_io);''')
    after('src/cmd/tracking.cc',
          'void IoLoop::tracking_emit_invalidation(Client* target, bool redirected, Slice key, bool flush) {',
          '    lottery::event(lottery::bit(13), "tracking_emit", target->id());')
    # These are observations of admitted executor work at the FLIP request.
    # They do not turn the row's separate saturation claim into a rate proof.
    after('src/core/ex_loop.h', '    bool execute(const Task& t) {', '''
        lottery::Scope lottery_work(t.client ? lottery::bit(11) : 0,
            "work_begin", "work_end", lottery::ptr(&t), self_->id());''')
    after('src/core/server.h', '        const uint32_t live_io = role_count(Role::Ifid);',
          '        lottery::event(lottery::bit(11), "flip_begin", flip_completed());')
    after('src/core/server.h', '        flip_last_transfers_.store(transfers, std::memory_order_relaxed);',
          '        lottery::event(lottery::bit(11), "flip_end", flip_completed());')
    after('src/net/tls.cc', '    const int result = SSL_accept(ssl_);', '''
    lottery::event(lottery::bit(12), "ssl_handshake", lottery::ptr(this),
                   BIO_number_read(SSL_get_rbio(ssl_)), result == 1,
                   result <= 0 && SSL_get_error(ssl_, result) == SSL_ERROR_WANT_READ);''')
    after('src/net/tls.cc', '    const int result = SSL_read(ssl_, dst, offer);', '''
    lottery::event(lottery::bit(12), "ssl_read", lottery::ptr(this),
                   BIO_number_read(SSL_get_rbio(ssl_)), result > 0);''')
    after('src/core/io_loop.h', '        if (tls->ktls()) return true;\n\n        if (tls->handshaking() && tls->fd_handshake()) {', '''
            lottery::event(lottery::bit(12), "tls_identity", c->id(), lottery::ptr(tls));''')
    after('src/core/io_loop.h', '        if (tls->handshaking()) {\n            const TlsOp result = tls->handshake();', '''
            lottery::event(lottery::bit(12), "tls_identity", c->id(), lottery::ptr(tls));''')
    after('src/cmd/t_server.cc', '    if (eq_icase(subcommand, "lbsignals") && op.argc() == 2) {',
          '        lottery::event(lottery::bit(10), "lbsignals");')

    (output / 'lottery-patches.json').write_text(json.dumps(changes, indent=2) + '\n')
    return changes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(f'{len(prepare(args.output))} reviewed witness anchors')
