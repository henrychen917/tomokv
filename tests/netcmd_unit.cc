#include "netcmd_unit.h"
// Include the actual cold command implementation to exercise its anonymous notification helpers.
// The unit link omits the corresponding production object.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#pragma GCC diagnostic pop
#include <filesystem>

long netcmd_fail_after = -1;
size_t netcmd_fail_size = 0;
unsigned netcmd_allocations = 0, netcmd_failures = 0;
void* operator new(size_t size) {
    if (netcmd_fail_after >= 0 && (!netcmd_fail_size || netcmd_fail_size == size)) {
        ++netcmd_allocations;
        if (netcmd_fail_after-- == 0) { ++netcmd_failures; throw std::bad_alloc(); }
    }
    if (void* ptr = std::malloc(size ? size : 1)) return ptr;
    throw std::bad_alloc();
}
void operator delete(void* ptr) noexcept { std::free(ptr); }
void operator delete(void* ptr, size_t) noexcept { std::free(ptr); }
void* operator new[](size_t size) { return ::operator new(size); }
void operator delete[](void* ptr) noexcept { std::free(ptr); }
void operator delete[](void* ptr, size_t) noexcept { std::free(ptr); }

namespace tomo {
struct NetcmdRegression {
    // Preparation-only fixtures still satisfy the production sender's complete bind contract.
    // The Ring stays unopened; these cases must never submit or acquire a borrowed value.
    struct Sender {
        Ring ring;
        std::atomic<bool> limits{false};
        uint32_t now_s = 0;
        LoopSignals signals;
        void bind(WbEngine& wb) {
            wb.bind(&ring, nullptr,
                [](void*, int32_t, const char*) { check(false, "unexpected fixture borrow release"); },
                nullptr, [](void*, Client&, Op&) { check(false, "unexpected fixture special retire"); },
                &limits, nullptr, [](void*, Client&) { return false; }, &now_s, &signals);
        }
    };
    static void notify_oom() {
        Server server;
        auto chain = std::make_unique<PubSubNotificationChain>();
        chain->items.push_back(PubSubNotificationItem{"channel", "message"});
        fault(0);
        bool threw = false;
        try { (void)notify_reserve_chain(server, std::move(chain)); }
        catch (const std::bad_alloc&) { threw = true; }
        const auto failed = netcmd_failures; fault(-1);
        check(threw && failed == 1, "shared_ptr control block allocation failed");
        check(server.pubsub_inflight() == 0, "reservation released exactly once on failure");
        auto good = std::make_unique<PubSubNotificationChain>();
        good->items.push_back(PubSubNotificationItem{"channel", "message"});
        auto reserved = notify_reserve_chain(server, std::move(good));
        check(reserved && server.pubsub_inflight() == 1, "successful chain owns reservation");
        reserved.reset(); check(server.pubsub_inflight() == 0, "successful chain releases reservation");
    }

    static void notify_retry() {
        Server server;
        // The gate runs this serverless row without taskset. Automatic SMT placement requires
        // whole sibling pairs for BOTH roles; only one IO is a tracking destination below.
        Config cfg; cfg.even_ifid = 2; cfg.even_ex = 2; cfg.shards = 16;
        check(server.prepare_boot(cfg), "notification topology");
        server.threads_.resize(server.placement().total_threads());
        for (uint32_t i = 0; i < server.threads_.size(); ++i) {
            server.threads_[i] = std::make_unique<ThreadCtx>();
            server.threads_[i]->init(i, Role::Ifid, server.threads_.size(), 0, 0);
        }
        const uint32_t io = server.placement().ifid_threads().front();
        ThreadCtx& thread = server.thread(io);
        server.climon_tracking_io_mask_.store(uint64_t{1} << io);
        Ring ring; LoopSignals signals;
        uint32_t queued = 0;
        while (thread.post_client(0, nullptr, ring, signals)) ++queued;
        check(queued > 0, "producer marker lane filled");
        Shard shard; shard.init_private(&server, 0, TypeLimits{}, StreamLimits{});
        shard.notify_state_slot() = std::make_unique<NotifyShardState>();
        NotifyOut out; out.routes = NOTIFY_TRACKING; out.key = "expired";
        shard.notify_state_slot()->keyless.push_back(std::move(out));
        check(notify_ex_pass_entry(server, shard, 0, thread, ring, signals) == 0,
              "failed marker post is incomplete work");
        check(shard.notify_state_slot()->keyless.size() == 1, "keyless invalidation retained");
        std::deque<PubSubEvent*> events; thread.take_pubsub_events(events);
        check(events.empty(), "failed post enqueued no payload");
        check(thread.drain_clients([](Client*) {}) == queued, "producer lane drained");
        check(notify_ex_pass_entry(server, shard, 0, thread, ring, signals) == 1, "retry completes record");
        thread.take_pubsub_events(events);
        check(events.size() == 1 && events.front()->kind == PubSubEventKind::TrackingInvalidate &&
              events.front()->items.size() == 1 && events.front()->items.front().value == "expired",
              "exact invalidation delivered after retry");
        server.pubsub_event_retired(); delete events.front();
        thread.drain_clients([](Client*) {});
    }

    static void flush() {
        // Two IOs still prove the foreign delivery; an even EX count also admits SMT placement.
        Server server; Config cfg; cfg.even_ifid = 2; cfg.even_ex = 2; cfg.shards = 16;
        check(server.prepare_boot(cfg), "flush topology");
        const auto& ios = server.placement().ifid_threads();
        check(ios.size() == 2, "foreign tracking IO exists");
        server.threads_.resize(server.placement().total_threads());
        for (uint32_t i = 0; i < server.threads_.size(); ++i) {
            server.threads_[i] = std::make_unique<ThreadCtx>();
            server.threads_[i]->init(i, Role::Ifid, server.threads_.size(), 0, 0);
        }
        IoLoop loop; loop.srv_ = &server; loop.self_ = &server.thread(ios[0]);
        loop.climon_armed_cached_ = Server::kClimonTracking;
        server.climon_tracking_io_mask_.store(uint64_t{1} << ios[1]);
        Client writer(-1); writer.set_id(9); Op op; args(op, {"FLUSHALL"});
        check(!loop.climon_armed_gate(&writer, op), "FLUSH passed dispatch gate");
        std::deque<PubSubEvent*> events;
        server.thread(ios[1]).take_pubsub_events(events);
        check(events.empty(), "no flush invalidation before owner work was published");
        op.state.store(OpState::Done);
        loop.climon_flush_completed(op);
        server.thread(ios[1]).take_pubsub_events(events);
        check(events.size() == 1 && events.front()->kind == PubSubEventKind::TrackingFlush,
              "completed flush invalidates foreign tracking IO");
        delete events.front(); server.pubsub_event_retired();
        server.thread(ios[1]).drain_clients([](Client*) {});
    }

    static void output() {
        Sender sender;
        Client client(-1); WbEngine wb;
        sender.bind(wb);
        client.start_obuf_tracking();
        check(client.obuf_bytes() == 0, "tracked balance drained before disable");
        Op* op = client.rob().acquire(); check(op, "reply slot");
        op->reply.append("+PONG\r\n", 7); op->state.store(OpState::Done); client.rob().publish();
        bool allowed; wb.prepare(client, allowed);
        check(allowed && client.fill_buf().size() == 7, "disabled specialization staged reply");
        client.swap_buffers(); client.commit_write(7);
        check(client.write_drained(), "uncounted reply send completion did not underflow");

        Server server; ThreadCtx self; IoLoop loop;
        loop.srv_ = &server; loop.self_ = &self;
        sender.bind(loop.wb_);
        // Mirror Server::init's mailbox initialization without starting workers or opening rings.
        // cx-waits made raw live-field stores writer-only; IO reads the published snapshot.
        server.live_config_committed_ = server.capture_live_config(server.live_config_version_.load());
        server.live_config_mailboxes_ = std::make_unique<LiveConfigMailbox[]>(server.nthreads() + 1);
        server.live_config_mailboxes_[self.id()].init(server.live_config_committed_);
        ClientOutputBufferLimits limits{}; limits.normal.hard_bytes = 8;
        server.set_client_output_buffer_limits(limits);
        check(server.client_obuf_armed() &&
              server.client_limits_snapshot(self.id()).normal.hard_bytes == 8,
              "hard limit published to the IO config mailbox");
        Client held(-1); held.set_id(1);
        check(held.rob().acquire(), "held ordinary operation"); held.rob().publish();
        check(!held.blocked(), "ordinary operation, not blocking exception");
        check(loop.wb_.defer_oob(held, "012345678", 9), "push entered deferred queue");
        check(held.buffered_output_bytes() == 0 && loop.wb_.deferred_output_bytes(held) == 9,
              "limit bytes exist only in deferred storage");
        check(loop.client_obuf_check(&held, false), "hard limit fired before Done");
        check(held.closing(), "deferred output scheduled connection close");
        loop.wb_.teardown(held);
    }

    static void pubsub() {
        pubsub_timeout();
        for (auto kind : {IoLoop::PubSubPendingKind::Channels, IoLoop::PubSubPendingKind::Numsub,
                          IoLoop::PubSubPendingKind::Numpat, IoLoop::PubSubPendingKind::Modify}) {
            for (bool suppressed : {false, true}) {
                Sender sender;
                Server server; ThreadCtx self; IoLoop loop; Client client(-1); client.set_id(42);
                loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
                Op* op = client.rob().acquire(); check(op, "pending pubsub operation");
                if (suppressed) op->mark_reply_skip();
                client.rob().publish();
                auto& local = loop.pubsub_local_[client.id()]; local.client = &client;
                local.channels.insert("old"); local.pending = 1;
                auto& pending = loop.pubsub_pending_[client.id()];
                pending.kind = kind; pending.op_id = client.rob().flush_id(); pending.subscribe = true;
                if (kind == IoLoop::PubSubPendingKind::Modify) pending.items.push_back("new");
                server.pubsub_pending_started();
                const std::string message = "*3\r\n$7\r\nmessage\r\n$3\r\nold\r\n$4\r\ndata\r\n";
                loop.pubsub_emit(&client, message.data(), message.size(), true);
                check(!pending.deferred.empty(), "publication arrived while control was pending");
                loop.pubsub_finish_pending(client.id());
                check(loop.pubsub_pending_.empty(), "pending control completed");
                bool allowed;
                if (suppressed) loop.wb_.prepare_suppressing(client, allowed);
                else loop.wb_.prepare(client, allowed);
                const std::string reply(client.fill_buf().data(), client.fill_buf().size());
                std::string push = message; push[0] = '>';
                check(reply.find(push) != std::string::npos, "independent publication survives retirement");
                if (suppressed) check(reply == push, "only command reply was suppressed");
            }
        }
    }

    static void pubsub_timeout() {
        for (bool resp3 : {false, true}) {
            Sender sender;
            Server server; ThreadCtx self; IoLoop loop; Client client(-1);
            client.set_id(42); client.set_resp3(resp3);
            loop.srv_ = &server; loop.self_ = &self; sender.bind(loop.wb_);
            ClientOutputBufferLimits limits; limits.pubsub = {};
            server.set_client_output_buffer_limits(limits);
            check(!server.client_obuf_armed(), "idle timeout isolated from output-buffer limits");
            self.add_client(&client);

            // Drive the real SUBSCRIBE completion, including its protocol-independent
            // subscriber flag. No listener, ring or worker is started by this fixture.
            Op* op = client.rob().acquire(); check(op, "timeout SUBSCRIBE slot");
            args(*op, {"SUBSCRIBE", "idle"});
            if (resp3) op->mark_resp3();
            client.rob().publish();
            auto& local = loop.pubsub_local_[client.id()];
            local.client = &client; local.pending = 1;
            auto& pending = loop.pubsub_pending_[client.id()];
            pending.kind = IoLoop::PubSubPendingKind::Modify;
            pending.op_id = client.rob().flush_id(); pending.subscribe = true;
            pending.items.push_back("idle");
            server.pubsub_pending_started();
            loop.pubsub_finish_pending(client.id());
            const std::string ack = std::string(resp3 ? ">" : "*") +
                "3\r\n$9\r\nsubscribe\r\n$4\r\nidle\r\n:1\r\n";
            check(op->state.load() == OpState::Done &&
                  std::string(op->reply.data(), op->reply.size()) == ack &&
                  client.subscriber_mode() && local.channels.count("idle") == 1 &&
                  loop.pubsub_pending_.empty() && server.pubsub_pending() == 0,
                  "SUBSCRIBE completed and armed the subscriber exemption candidate");

            client.set_last_interaction_s(100);
            loop.cached_now_s_ = 106;
            server.set_timeout(0);
            check(loop.client_cron_pass() == 1 && !client.closing(), "timeout 0 keeps subscribers open");
            server.set_timeout(5);
            loop.cached_now_s_ = 105;
            check(loop.client_cron_pass() == 1 && !client.closing(), "exact idle timeout keeps subscribers open");
            loop.cached_now_s_ = 106;
            client.set_blocked(true);
            check(loop.client_cron_pass() == 1 && !client.closing(), "blocked subscribers remain exempt");
            client.set_blocked(false);
            check(loop.client_cron_pass() == 1, "idle subscriber visited by client cron");
            check(!client.closing(),
                  resp3 ? "idle RESP3 SUBSCRIBE client must remain exempt from timeout"
                        : "idle RESP2 SUBSCRIBE client must remain exempt from timeout");

            Client idle(-1); idle.set_id(43); idle.set_resp3(resp3);
            idle.set_last_interaction_s(100);
            // Model an outstanding receive to keep this stack-owned control alive after close.
            // No receive is submitted; the control has no subscription or blocking command.
            idle.set_recv_armed(true);
            self.add_client(&idle);
            check(loop.client_cron_pass() == 2, "subscriber and plain idle client visited by cron");
            check(!client.closing(), "subscriber stays open alongside the plain idle control");
            check(idle.closing(),
                  resp3 ? "plain idle RESP3 client must be closed after timeout"
                        : "plain idle RESP2 client must be closed after timeout");
        }
    }

    static void receive_segments() {
        SegmentQueue<4, 8> segments;
        segments.append_buf("abcdefghijk", 11, "lmnopqrs", 8);
        check(segments.size() == 3 && segments.byte_size() == 19, "two-piece aggregate split into representable segments");
        iovec iov[4]; bool borrow = false; uint32_t bytes = 0;
        const auto n = segments.build_iov(iov, 4, 64, borrow, bytes);
        std::string actual;
        for (uint32_t i = 0; i < n; ++i) {
            check(iov[i].iov_len <= 8, "segment length cap honored");
            actual.append(static_cast<const char*>(iov[i].iov_base), iov[i].iov_len);
        }
        check(bytes == 19 && actual == "abcdefghijklmnopqrs", "aggregate contents preserved");
        Client input(-1); size_t avail = 0;
        check(input.read_space(2 * 1024 * 1024, avail, true, 1024 * 1024) && avail >= 2 * 1024 * 1024,
              "whole command can exceed individual bulk limit");
        const auto before = input.rcap();
        input.commit_read(before - 1);
        check(!input.read_space(4096, avail, false, 1024 * 1024) && input.rcap() == before,
              "receive growth remains forbidden with outstanding argv slices");
        // Allocation reserves virtual space; no 600 MiB payload or benchmark is needed.
        Client large(-1);
        check(large.read_space(600ull * 1024 * 1024, avail, true) &&
              avail >= 600ull * 1024 * 1024, "default receive allowance has no one-bulk ceiling");
        check(large.read_space(600ull * 1024 * 1024, avail, true, 1024ull * 1024 * 1024) &&
              avail >= 600ull * 1024 * 1024, "raised bulk limit fits epoll receive geometry");
    }

    // Diagnostic for the still-open cross-family partial-mutation finding; deliberately absent
    // from the passing gate rows until a failure-atomic collection update is implemented.
    static void collection_oom() {
        Shard shard; TypeLimits limits; limits.hash.max_entries = 1;
        shard.init_private(nullptr, 0, limits, StreamLimits{}); shard.set_cached_now_ms(1000);
        check(execute(shard, {"HSET", "h", "a", "old-a", "b", "old-b"}) == ":2\r\n", "expanded hash seeded");
        auto* object = shard.store().find(FlatStore::hash_key(Slice("h", 1)), Slice("h", 1));
        check(CollectionRef(object).encoding() == CollectionEncoding::Hashtable, "expanded hash arm entered");
        check(execute(shard, {"HPEXPIRE", "h", "60000", "FIELDS", "1", "a"}) == "*1\r\n:1\r\n", "field TTL armed");
        const std::string replacement(256, 'x'); Op op;
        args(op, {"HSET", "h", "a", replacement.c_str(), "b", replacement.c_str()});
        fault(1, replacement.size() + 1); op.spec->handler(shard, op);
        const unsigned failures = netcmd_failures; fault(-1);
        check(failures == 1, "second replacement allocation failed");
        check(std::string(op.reply.data(), op.reply.size()).starts_with("-ERR"), "HSET reported allocation failure");
        check(execute(shard, {"HGET", "h", "a"}) == "$5\r\nold-a\r\n",
              "OPEN F05: failed multi-field HSET retained a changed prefix (and its old TTL)");
    }

    static void config() {
        test_config_bounds();
        acl_selectors();
        tracking_eviction();
        zero_copy("zc-all");
        Server server;
        const std::string password = "pass with spaces\n\r\t\"'\\tail";
        char directory[] = "build/netcmd-config-XXXXXX";
        check(::mkdtemp(directory), "private config directory");
        const std::string path = std::string(directory) + "/tomo.conf";
        server.cfg_.conf_path = path.c_str(); server.cfg_.requirepass = password.c_str();
        ConfigParseState state;
        check(parse_config_args({"--port", "6397", "--bind", "127.0.0.2",
                                 "--unixsocket", "build/unused-knob-matrix.sock",
                                 "--unixsocketperm", "0600", "--aof-load-truncated", "no",
                                 "--hll-sparse-max-bytes", "1kb"},
                                server.cfg_, state, 1, "conf") == kConfigParsed,
              "knob matrix startup values parsed without starting a server");
        // CONFIG SET reads its owner's committed live snapshot even for encoding-only updates.
        // Supply the same mailbox contract as init(), with one private shard and no workers/rings.
        server.live_config_version_.store(2);
        server.live_config_committed_ = server.capture_live_config(2);
        server.live_config_mailboxes_ = std::make_unique<LiveConfigMailbox[]>(1);
        server.live_config_mailboxes_[0].init(server.live_config_committed_);
        server.shards_.push_back(std::make_unique<Shard>());
        server.shards_[0]->init_private(&server, 0, server.cfg_.encodings.type_limits(),
                                       server.cfg_.stream_limits);
        command_bind_server(&server);
        test_config_rewrite();
        // Retain t01's null-sidecar INFO regression. O6 enables fused prefetch, but the
        // helper must still report explicit zeros in this fixture without allocating state.
        // Use an empty INFO fixture: the CONFIG fixture above has a private shard but no
        // placement map. Neither fixture starts workers, opens a ring, or listens on a socket.
        Server info_server;
        command_bind_server(&info_server);
        info_server.cfg_.thread_mode = ThreadMode::Fused;
        for (uint32_t reorder : {0u, 1u}) {
        info_server.cfg_.reorder = reorder;
        Shard shard;
        for (uint32_t overlap : {0u, 1u}) {
            info_server.cfg_.overlap = overlap;
            check(info_server.mode_schedule_stats() == nullptr, "handler fixture starts without a sidecar");
            const std::string info = execute(shard, {"INFO", "SERVER"});
            check(info.find("overlap_enabled:" + std::to_string(overlap) + "\r\n") != std::string::npos,
                  "optional schedule reporting follows overlap");
            if (overlap) {
                for (const char* field : {"schedule_stats_threads:0\r\n", "overlap_schedule:plain\r\n",
                         "overlap_passes:0\r\n", "overlap_interleaved_passes:0\r\n"})
                    check(info.find(field) != std::string::npos, "requested schedule reports explicit zeros without a sidecar");
            } else {
                check(info.find("schedule_stats_threads:") == std::string::npos &&
                      info.find("reorder_permuted_runs:") == std::string::npos,
                      "both requested knobs off preserve the existing INFO surface");
            }
            check(info.find("reorder:0\r\nreorder_retired:1\r\n") != std::string::npos,
                  "retired reorder always reports effective zero");
            for (const char* field : {"reorder_batches:", "reorder_multi_client_runs:",
                                     "reorder_permuted_runs:", "reorder_max_batch:"})
                check(info.find(field) == std::string::npos, "retired counters are absent");
            check(info_server.mode_schedule_stats() == nullptr, "INFO did not allocate schedule storage");
        }
        }
        command_bind_server(nullptr);
        std::filesystem::remove_all(directory);
    }

    static void acl_selectors() {
        const std::vector<std::vector<std::string>> selectors = {
            {"()"}, {"(+get ~safe:*)"}, {"(", "+get", "~safe:*", ")"}, {"("}, {"(+@all (~*))"}
        };
        char directory[] = "build/deadconf-acl-XXXXXX";
        check(::mkdtemp(directory), "private ACL fixture directory");
        const std::string path = std::string(directory) + "/users.acl";
        auto write_file = [&](const std::vector<std::string>& rules) {
            std::FILE* file = std::fopen(path.c_str(), "w"); check(file, "open ACL fixture");
            std::fputs("user default on nopass ~* &* +@all\nuser acl-file on nopass ~safe:* +get", file);
            for (const auto& rule : rules) std::fprintf(file, " %s", rule.c_str());
            check(std::fputs("\n", file) >= 0 && std::fclose(file) == 0, "write ACL fixture");
        };
        write_file({});
        Server server; Config cfg; cfg.aclfile = path.c_str();
        ThreadCtx self; self.init(0, Role::Ifid, 1, 0, 0);
        IoLoop loop; loop.srv_ = &server; loop.self_ = &self;
        Client admin(-1); admin.set_id(808);
        std::string error;
        acl_shutdown();
        check(acl_initialize(server, cfg, error), "valid root ACL file accepted");
        auto request = [&](std::vector<std::string> values) {
            Op op;
            for (const auto& value : values)
                check(op.push_arg(Slice(value.data(), value.size())), "ACL fixture argument");
            op.spec = command_lookup(op.cmd_name());
            acl_command_entry(loop, admin, op);
            return std::string(op.reply.data(), op.reply.size());
        };
        check(request({"ACL", "SETUSER", "acl-root", "on", "nopass", "~safe:*", "+get"}) == "+OK\r\n",
              "root ACL rules remain accepted");
        const auto before = request({"ACL", "GETUSER", "acl-root"});
        for (const auto& rules : selectors) {
            for (const char* name : {"acl-root", "acl-new"}) {
                std::vector<std::string> values = {"ACL", "SETUSER", name, "reset", "on", "nopass"};
                values.insert(values.end(), rules.begin(), rules.end());
                const auto reply = request(values);
                check(reply.starts_with("-ERR ") && reply.find("ACL selectors are not supported") != std::string::npos,
                      "ACL SETUSER rejects packed, split, empty and malformed selectors");
                check(request({"ACL", "GETUSER", "acl-root"}) == before, "failed selector leaves existing ACL intact");
                check(request({"ACL", "GETUSER", "acl-new"}) == "$-1\r\n", "failed selector creates no user");
            }
            write_file(rules);
            const auto reply = request({"ACL", "LOAD"});
            check(reply.starts_with("-") && reply.find("ACL selectors are not supported") != std::string::npos &&
                  reply.ends_with("no change to the previously active ACL rules was performed\r\n"),
                  "ACL LOAD rejects selectors");
            check(request({"ACL", "GETUSER", "acl-root"}) == before, "rejected ACL LOAD leaves live users intact");
        }
        acl_shutdown();
        for (const auto& rules : selectors) {
            Config boot;
            boot.acl_users = {{"acl-boot", "on", "nopass"}};
            boot.acl_users.front().insert(boot.acl_users.front().end(), rules.begin(), rules.end());
            error.clear();
            check(!acl_initialize(server, boot, error) && error.find("ACL selectors are not supported") != std::string::npos,
                  "inline boot ACL rejects selectors before startup");
            acl_shutdown();
            write_file(rules);
            error.clear();
            check(!acl_initialize(server, cfg, error) && error.find("ACL selectors are not supported") != std::string::npos,
                  "boot ACL file rejects selectors before startup");
            acl_shutdown();
        }
        std::filesystem::remove_all(directory);
    }


    static void tracking_eviction() {
        {
            // A post-SWAP GET carries a physical namespace, while invalidation
            // events carry raw key bytes. Exercise the actual membership filter
            // before either eviction run can populate it with false positives.
            Server server; server.cfg_.databases = 16;
            ThreadCtx self; self.init(0, Role::Ifid, 1, 0, 0);
            IoLoop loop; loop.srv_ = &server; loop.self_ = &self;
            loop.tracking_broadcast_flush();
            server.climon_set_tracking_io(0, true);
            Client client(-1); client.set_id(100); client.set_resp3(true);
            client.set_ifid_thread(0);
            auto& tracking = loop.climon_conn_get(&client); tracking.tracking_on = true;
            check(server.databases().swap(0, 1), "tracking map swapped");
            std::string key;
            bool armed = false;
            for (unsigned attempt = 0; attempt < 128; ++attempt) {
                key = "tracking:namespace:" + std::to_string(attempt);
                const auto raw = FlatStore::hash_key(Slice(key));
                const auto stamped = FlatStore::hash_key(Slice(key.data(), key.size(), 1));
                if ((raw & 63) != (stamped & 63)) { armed = true; break; }
            }
            check(armed, "raw and physical identities use distinct filter bits");
            Op op; args(op, {"GET", key.c_str()}); multidb_stamp(server, op, 0);
            check(op.key().ns == 1, "tracking read uses post-SWAP physical identity");
            loop.tracking_register_read(&client, tracking, op);
            loop.tracking_broadcast_keys({key}, 999);
            const std::string frame = ">2\r\n$10\r\ninvalidate\r\n*1\r\n$" +
                std::to_string(key.size()) + "\r\n" + key + "\r\n";
            check(std::string(client.fill_buf().data(), client.fill_buf().size()) == frame,
                  "raw invalidation reaches a physically stamped read");
            check(loop.climon_track_keys_.empty(), "post-SWAP invalidation retires registration");
        }
        for (bool collide : {false, true}) {
            Server server; server.cfg_.tracking_table_max_keys = 32;
            ThreadCtx self; self.init(0, Role::Ifid, 1, 0, 0);
            IoLoop loop; loop.srv_ = &server; loop.self_ = &self;
            loop.random_state_ = 0x123456789abcdefULL;
            loop.climon_track_keys_.reserve(32);
            Client a(-1), b(-1);
            a.set_id(101); b.set_id(102); a.set_resp3(true); b.set_resp3(true);
            a.set_ifid_thread(0); b.set_ifid_thread(0);
            auto& ast = loop.climon_conn_get(&a); ast.tracking_on = true;
            auto& bst = loop.climon_conn_get(&b); bst.tracking_on = true;
            uint32_t next_key = 0;
            std::vector<std::string> originals;
            for (unsigned turn = 0; turn < 32 + 4096; ++turn) {
                std::string key;
                do { key = "tracking:" + std::to_string(next_key++); }
                while (collide && loop.climon_track_keys_.bucket(key) != 0);
                std::vector<std::string> before;
                for (const auto& entry : loop.climon_track_keys_) before.push_back(entry.first);
                Op op; args(op, {"GET", key.c_str()});
                loop.tracking_register_read(&a, ast, op);
                loop.tracking_register_read(&b, bst, op);
                check(loop.climon_track_keys_.size() == std::min(turn + 1, 32u), "tracking table respects its bound");
                check(server.climon_tracking_keys() == loop.climon_track_keys_.size() &&
                      server.climon_tracking_items() == 2 * loop.climon_track_keys_.size(),
                      "tracking eviction preserves exact key and owner counts");
                if (turn < 32) {
                    originals.push_back(key);
                    check(a.fill_buf().empty() && b.fill_buf().empty(), "no eviction before the table is full");
                } else {
                    unsigned removed = 0;
                    for (const auto& old : before) {
                        if (loop.climon_track_keys_.contains(old)) continue;
                        ++removed;
                        const std::string frame = ">2\r\n$10\r\ninvalidate\r\n*1\r\n$" +
                            std::to_string(old.size()) + "\r\n" + old + "\r\n";
                        check(std::string(a.fill_buf().data(), a.fill_buf().size()) == frame &&
                              std::string(b.fill_buf().data(), b.fill_buf().size()) == frame,
                              "each evicted key invalidates every tracking owner exactly once");
                    }
                    check(removed == 1, "one actual eviction per full-table insertion");
                    a.fill_buf().clear(); b.fill_buf().clear();
                }
            }
            check(server.climon_invalidations() == 8192, "4096 evictions fired for both owners");
            for (const auto& key : originals)
                check(!loop.climon_track_keys_.contains(key),
                      "random eviction reaches the whole table, including a single collision bucket");
        }
    }


    static void zero_copy(const std::string& section) {
        if (section == "zc-all" || section == "zc-install") {
            Shard shard;
            shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
            check(shard.zc_min() == UINT32_MAX, "boot zero-copy off installs the disabled sentinel");
        }
        if (section == "zc-all" || section == "zc-live") {
            Server registry;
            command_bind_server(&registry); command_bind_server(nullptr);
            Shard shard;
            shard.init_private(nullptr, 0, TypeLimits{}, StreamLimits{});
            for (const char* text : {"256", "0", "1024", "0"}) {
                check(execute(shard, {"CONFIG", "SET", "zc-min", text}).empty(), "live zc update");
                check(shard.zc_min() == (std::strcmp(text, "0") ? std::stoul(text) : UINT32_MAX),
                      "live zero-copy off installs the disabled sentinel");
                const std::string wire = "*2\r\n$6\r\nzc-min\r\n$" + std::to_string(std::strlen(text)) +
                    "\r\n" + text + "\r\n";
                check(execute(shard, {"CONFIG", "GET", "zc-min"}) == wire,
                      "CONFIG GET retains the public zero spelling");
            }
        }
        if (section == "zc-install" || section == "zc-live") return;
        for (ThreadMode mode : {ThreadMode::Split, ThreadMode::Fused}) {
            Server server;
            Config cfg; cfg.even_ifid = 6; cfg.even_ex = 2; cfg.shards = 16;
            cfg.thread_mode = mode; cfg.key_lb = cfg.client_lb = 0;
            check(server.prepare_boot(cfg) && server.init(cfg), "serverless zero-copy topology");
            std::string keys[2];
            for (unsigned i = 0; (keys[0].empty() || keys[1].empty()) && i < 100000; ++i) {
                const auto key = "zc:" + std::to_string(i);
                const int sid = server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size())));
                if (sid < 2) keys[sid] = key;
            }
            check(!keys[0].empty() && !keys[1].empty(), "two distinct gather shards found");
            for (uint32_t cutover : {0u, 256u, 1024u}) {
                if (section == "zc-boundary" && !cutover) continue;
                if (section == "zc-off" && cutover) continue;
                for (uint32_t length : {0u, 1u, 255u, 256u, 257u, 1023u, 1024u, 1025u, 16384u}) {
                    const std::string value(length, 'v');
                    const bool borrow = cutover && length >= cutover;
                    for (int sid = 0; sid < 2; ++sid) {
                        Shard& shard = server.shard(sid);
                        shard.set_zc_min(cutover ? cutover : UINT32_MAX);
                        check(execute(shard, {"SET", keys[sid].c_str(), value.c_str()}) == "+OK\r\n", "seed zc value");
                        Op get; args(get, {"GET", keys[sid].c_str()});
                        get.spec->handler(shard, get);
                        check((get.zc_ptr != nullptr) == borrow, "GET cutover is inclusive and zero disables");
                        if (get.zc_ptr) { shard.store().unborrow(get.zc_ptr); get.zc_ptr = nullptr; }
                    }
                    Client client(-1); client.set_id(777);
                    Op op; args(op, {"MGET", keys[0].c_str(), keys[1].c_str()});
                    ScatterArenaPool pool; ScatterDispatch dispatch;
                    check(xshard_prepare(server, op, pool, 0, client.id(), dispatch) == ScatterPrepare::Ready,
                          "MGET gather prepared");
                    ScatterState& state = *dispatch.state;
                    check(state.nsub == 2, "MGET really spans two shards");
                    for (uint32_t i = 0; i < state.nsub; ++i) {
                        const int sid = state.groups[i].shard;
                        check(xshard_execute(Task{&client, 0, sid, &state}, server.shard(sid), op,
                                             server.worker_of_shard(sid)) == ScatterTaskResult::Complete,
                              "MGET owner gather completed");
                    }
                    for (uint32_t i = 0; i < state.key_count; ++i) {
                        auto& slot = state.values[i];
                        check((slot.kind == ValueKind::Borrow) == borrow,
                              "GET and MGET agree at the exact cutover and when disabled");
                        const char* data = slot.kind == ValueKind::Inline ? slot.small : slot.ptr;
                        check(slot.len == length && std::string(data, slot.len) == value, "gather bytes intact");
                    }
                    if (!borrow) {
                        // A disabled gather owns its bytes even after a later owner overwrite.
                        for (int sid = 0; sid < 2; ++sid)
                            check(execute(server.shard(sid), {"SET", keys[sid].c_str(), "replacement"}) == "+OK\r\n",
                                  "overwrite after copied gather");
                        assemble_mget(client, op, state, nullptr, nullptr, nullptr);
                        const std::string bulk = "$" + std::to_string(length) + "\r\n" + value + "\r\n";
                        check(std::string(op.reply.data(), op.reply.size()) == "*2\r\n" + bulk + bulk,
                              "copied MGET assembles the gathered snapshot");
                    }
                    for (uint32_t i = 0; i < state.key_count; ++i) {
                        auto& slot = state.values[i];
                        if (slot.kind == ValueKind::Borrow) {
                            server.shard(slot.shard).store().unborrow(slot.ptr);
                            slot.kind = ValueKind::Nil;
                        }
                    }
                    for (unsigned i = 0; state.owner_record_refs && i < state.owner_slots; ++i)
                        while (state.owner_record_refs[i].remaining) complete_owner_record_wave(state, i);
                    xshard_destroy(&state, pool, 0); pool.reap_deferred();
                    for (int sid = 0; sid < 2; ++sid)
                        check(server.shard(sid).store().outstanding_borrows() == 0, "gather released every borrow");
                }
            }
            if (section == "zc-all" || section == "zc-off") {
                const std::string value(2048, 'x');
                for (int sid = 0; sid < 2; ++sid) {
                    server.shard(sid).set_zc_min(UINT32_MAX);
                    check(execute(server.shard(sid), {"SET", keys[sid].c_str(), value.c_str()}) == "+OK\r\n",
                          "seed gather allocation-failure case");
                }
                Client client(-1); client.set_id(778);
                Op op; args(op, {"MGET", keys[0].c_str(), keys[1].c_str()});
                ScatterArenaPool pool; ScatterDispatch dispatch;
                check(xshard_prepare(server, op, pool, 0, client.id(), dispatch) == ScatterPrepare::Ready,
                      "prepare allocation-failure gather");
                auto& state = *dispatch.state;
                fault(1, value.size()); // the second large reply copy, after the first owner finished
                for (uint32_t i = 0; i < state.nsub; ++i) {
                    const int sid = state.groups[i].shard;
                    check(xshard_execute(Task{&client, 0, sid, &state}, server.shard(sid), op,
                                         server.worker_of_shard(sid)) == ScatterTaskResult::Complete,
                          "copy allocation failure terminates the owner task");
                }
                const auto failures = netcmd_failures; fault(-1);
                WorkError error = WorkError::None;
                check(failures == 1 && first_error(state, error) && error == WorkError::Oom,
                      "second owned-copy allocation really failed and reported OOM");
                xshard_destroy(&state, pool, 0); pool.reap_deferred();
                for (int sid = 0; sid < 2; ++sid)
                    check(server.shard(sid).store().outstanding_borrows() == 0, "OOM used no borrow fallback");
            }
        }
    }
};
}

int main(int argc, char** argv) {
    check(argc == 2 || (argc == 3 && std::string(argv[1]) == "config-bounds"),
          "one regression section (and optional config-bound name) required");
    check(tomo::command_registry_init(false), "command registry initialized");
    const std::string mode = argv[1];
    using R = tomo::NetcmdRegression;
    if (mode == "streams") test_stream_faults();
    else if (mode == "zpop") test_zpop_faults();
    else if (mode == "notify-oom") R::notify_oom();
    else if (mode == "notify-retry") R::notify_retry();
    else if (mode == "flush") R::flush();
    else if (mode == "output") R::output();
    else if (mode == "pubsub") R::pubsub();
    else if (mode == "pubsub-timeout") R::pubsub_timeout();
    else if (mode == "receive") R::receive_segments();
    else if (mode == "collection-oom") R::collection_oom();
    else if (mode == "config") R::config();
    else if (mode == "config-bounds") test_config_bounds(argc == 3 ? argv[2] : nullptr);
    else if (mode == "acl-selectors") R::acl_selectors();
    else if (mode == "tracking-eviction") R::tracking_eviction();
    else if (mode.starts_with("zc-")) R::zero_copy(mode);
    else check(false, "unknown regression section");
    std::printf("ok: netcmd %s\n", argv[1]);
}
