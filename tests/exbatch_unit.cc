// EX1/EX3/EX6: real owner objects and command metadata, no listener, ring or workers.
#include "src/core/server.h"
#include "src/cmd/cmdmeta.h"
#include <cstdio>
#include <cstdlib>
#include <new>
#include <string>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {
bool count_allocations = false;
size_t allocations = 0;
int fail_after = -1;
bool dump_wire = false;
void check(bool yes, const char* why) {
    if (!yes) { std::fprintf(stderr, "FAIL exbatch: %s\n", why); std::exit(1); }
}
}
void* operator new(size_t n) {
    if (fail_after == 0) throw std::bad_alloc();
    if (fail_after > 0) --fail_after;
    if (count_allocations) ++allocations;
    if (void* p = std::malloc(n ? n : 1)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void* operator new[](size_t n) { return ::operator new(n); }
void operator delete[](void* p) noexcept { ::operator delete(p); }
void operator delete[](void* p, size_t) noexcept { ::operator delete(p); }

using namespace tomo;
namespace {
Slice slice(const std::string& s) { return {s.data(), static_cast<uint32_t>(s.size())}; }
struct Request {
    std::vector<std::string> args;
    Op op;
    explicit Request(std::vector<std::string> a) : args(std::move(a)) {
        op.reset();
        for (const auto& s : args) check(op.push_arg(slice(s)), "argument allocation");
        op.spec = command_lookup(op.arg(0));
    }
};
void put(Shard& sh, Slice key, int64_t deadline = -1) {
    auto* object = kvobj_new_string(key, Slice("value"), deadline);
    check(object != nullptr, "value allocation");
    check(sh.store().insert(FlatStore::hash_key(key), object) == FlatStore::InsertResult::Inserted,
          "insert new key");
}
void gauges(const Shard& sh) {
    check(sh.published_size() == sh.store().size(), "published size includes every changed shard");
    check(sh.published_obj_bytes() == sh.store().object_bytes(), "published object bytes exact");
    check(sh.published_expires() == sh.store().expire_count(), "published expiry count exact");
    check(sh.published_evicted() == sh.stats().evicted, "published eviction count exact");
}
// Intentionally outline the same production entry for ELF/static receipts.
__attribute__((noinline)) void publish(Shard& sh) { sh.publish_size(); }
__attribute__((noinline)) bool watches(const Shard& sh) { return sh.has_watches(); }

void publication() {
    const long page = sysconf(_SC_PAGESIZE);
    check(page >= long(sizeof(Shard)), "one mapped page holds a shard");
    void* memory = mmap(nullptr, page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    check(memory != MAP_FAILED, "map publication fixture");
    Shard* sh = new(memory) Shard;
    sh->set_cached_now_ms(1000);
    put(*sh, Slice("plain")); put(*sh, Slice("ttl"), 100000);
    sh->stats().evicted = 7;
    publish(*sh); gauges(*sh);
    const pid_t child = fork();
    check(child >= 0, "fork publication witness");
    if (child == 0) {
        rlimit limit{0, 0}; setrlimit(RLIMIT_CORE, &limit);
        if (mprotect(memory, page, PROT_READ)) std::_Exit(2);
        for (unsigned i = 0; i < 64; ++i) publish(*sh);
        std::_Exit(0);
    }
    int status = 0;
    check(waitpid(child, &status, 0) == child, "wait publication witness");
    check(WIFEXITED(status) && WEXITSTATUS(status) == 0,
          "unchanged publication must issue zero stores (read-only page)");
    check(sh->store().erase(FlatStore::hash_key(Slice("ttl")), Slice("ttl")), "delete TTL key");
    sh->stats().evicted = 3; // Includes counter reset/decrease, not only monotonic changes.
    publish(*sh); gauges(*sh);
    sh->~Shard(); munmap(memory, page);
    Shard first, last;
    put(first, Slice("first")); put(last, Slice("last"));
    for (Shard* owned : {&first, &last}) publish(*owned);
    gauges(first); gauges(last);
    std::puts("PASS exbatch publication: zero unchanged stores; all four gauges; non-last shard");
}

void watch_lifecycle() {
    Client a(-1), b(-1);
    Shard sh;
    sh.set_cached_now_ms(1000);
    const Slice key("watched");
    const std::string owned = database_owned_key(key);
    auto ga = a.next_watch_generation(), gb = b.next_watch_generation();
    check(!watches(sh), "empty WATCH gate");
    check(sh.watch_add(key, &a, ga) && watches(sh), "WATCH add arms gate");
    check(sh.watch_add(key, &a, ga), "duplicate WATCH");
    check(sh.watch_add(key, &b, gb), "second WATCH");
    sh.watch_remove(key, &a, ga);
    check(watches(sh), "remaining watcher keeps gate armed");
    sh.watch_write_committed(key);
    check(b.watch_dirty(), "armed write dirties watcher");
    sh.watch_remove(key, &b, gb);
    check(!watches(sh), "last UNWATCH clears gate");

    a.clear_watch_dirty();
    check(sh.watch_add(key, &a, ga), "arm EXEC validation");
    std::atomic<uint64_t> epoch{0};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    int token = 0, other = 0;
    check(sh.watch_validate_and_reserve(key, &a, ga, &token, &epoch, &aborted, &refs, true),
          "EXEC reserves watched key");
    sh.watch_remove(key, &a, ga);
    check(watches(sh) && refs == 1, "reservation alone keeps gate armed");
    check(!sh.watch_write_ready(key) && sh.stats().watch_reservation_waits > 0,
          "undecided blocking reservation observed");
    epoch = 1;
    check(sh.watch_write_ready(key) && refs == 0 && !watches(sh),
          "commit finalizes last reservation and clears gate");

    check(sh.watch_add(key, &a, ga), "arm nonblocking writers");
    a.clear_watch_dirty(); epoch = 0;
    sh.watch_reserve_write(key, &b, gb, &token, &epoch, &aborted, &refs);
    sh.watch_reserve_write(key, &b, gb, &other, &epoch, &aborted, &refs);
    check(refs == 2 && sh.stats().watch_reservation_coexist > 0, "coexisting reservations armed");
    sh.watch_validate_and_reserve(key, &a, ga, &sh, &epoch, &aborted, &refs, true);
    check(a.watch_dirty() && sh.stats().watch_reservation_precommit_aborts > 0,
          "conflicting EXEC observes pending writer");
    aborted = true;
    check(sh.watch_finalize_reservation(owned) && refs == 0 && watches(sh),
          "abort finalization retains remaining watcher");
    a.next_watch_generation();
    sh.watch_prune_stale(owned);
    check(!watches(sh), "stale last watcher pruning clears gate");

    ga = a.watch_generation(); a.clear_watch_dirty();
    put(sh, key);
    check(sh.watch_add(key, &a, ga, 0), "arm database swap");
    check(sh.watch_database_swap(0, 1, 0, 1) && a.watch_dirty() && watches(sh),
          "database swap preserves gate and dirties matching watch");
    sh.watch_remove(key, &a, ga);
    check(!watches(sh), "swap watcher cleanup");
    std::puts("PASS exbatch watch: add/remove/reserve/finalize/prune/swap; all reservation counters");
}

void watch_loads() {
    const long page = sysconf(_SC_PAGESIZE);
    void* memory = mmap(nullptr, page * 2, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    check(memory != MAP_FAILED, "map cold WATCH fixture");
    // Header remains accessible; the maps at 1216/1272 are wholly on page two.
    auto* sh = new(static_cast<char*>(memory) + page - 1200) Shard;
    const pid_t child = fork();
    check(child >= 0, "fork WATCH load witness");
    if (child == 0) {
        rlimit limit{0, 0}; setrlimit(RLIMIT_CORE, &limit);
        if (mprotect(static_cast<char*>(memory) + page, page, PROT_NONE)) std::_Exit(2);
        for (unsigned i = 0; i < 64; ++i) if (watches(*sh)) std::_Exit(3);
        std::_Exit(0);
    }
    int status = 0;
    check(waitpid(child, &status, 0) == child, "wait WATCH load witness");
    check(WIFEXITED(status) && WEXITSTATUS(status) == 0,
          "unarmed WATCH gate must not read either cold map (inaccessible page)");
    sh->~Shard(); munmap(memory, page * 2);
    std::puts("PASS exbatch watch-loads: cold map page inaccessible");
}

void watch_oom() {
    unsigned failures = 0, successes = 0;
    for (bool reservation : {false, true}) {
        for (int budget = 0; budget < 8; ++budget) {
            Client client(-1); Shard sh;
            const auto generation = client.next_watch_generation();
            const Slice key("oom-watch");
            const auto owned = database_owned_key(key);
            std::atomic<uint64_t> epoch{1}; std::atomic<uint32_t> refs{0};
            bool added = false;
            fail_after = budget;
            try {
                if (reservation) {
                    Shard::WatchReservation item;
                    item.epoch = &epoch; item.refs = &refs;
                    added = sh.watch_append_reservation(owned, item);
                } else added = sh.watch_add(key, &client, generation);
            } catch (const std::bad_alloc&) {}
            fail_after = -1;
            check(watches(sh) == added, "allocation failure preserves WATCH cache truth");
            if (added) ++successes; else ++failures;
            if (reservation) check(sh.watch_finalize_reservation(owned), "retire OOM reservation fixture");
            else sh.watch_remove(key, &client, generation);
            check(!watches(sh) && refs == 0, "OOM fixture leaves empty registries");
        }
    }
    check(failures > 0 && successes > 0, "allocation failure window and successful arm both observed");
    std::printf("PASS exbatch watch-oom: %u failed allocations, %u successful arms\n", failures, successes);
}

const CommandMetadata* linear(Slice name) {
    for (uint32_t i = 0; i < command_metadata_size(); ++i) {
        const auto* row = command_metadata_at(i);
        const auto candidate = command_metadata_name(*row);
        if (name.eq_icase(std::string_view(candidate.p, candidate.n))) return row;
    }
    return nullptr;
}
const CommandMetadata* legacy_resolve(Op& op, uint32_t argument) {
    if (argument >= op.argc()) return nullptr;
    const auto* parent = linear(op.arg(argument));
    if (argument + 1 < op.argc()) {
        std::string qualified(op.arg(argument).p, op.arg(argument).n);
        qualified += '|'; qualified.append(op.arg(argument + 1).p, op.arg(argument + 1).n);
        if (const auto* child = linear(slice(qualified))) return child;
        if (parent) {
            const auto prefix = command_metadata_name(*parent);
            for (uint32_t i = 0; i < command_metadata_size(); ++i) {
                const auto name = command_metadata_name(*command_metadata_at(i));
                if (name.n > prefix.n && !std::memcmp(name.p, prefix.p, prefix.n) &&
                    name.p[prefix.n] == '|') return nullptr;
            }
        }
    }
    return parent;
}
uint64_t wire_hash = 1469598103934665603ull;
void hash_wire(const Op& op) {
    if (dump_wire) {
        const uint64_t length = op.reply.size();
        check(std::fwrite(&length, sizeof(length), 1, stdout) == 1, "wire length output");
        check(std::fwrite(op.reply.data(), 1, length, stdout) == length, "wire bytes output");
    }
    for (size_t i = 0; i < op.reply.size(); ++i) {
        wire_hash ^= static_cast<unsigned char>(op.reply.data()[i]); wire_hash *= 1099511628211ull;
    }
}
void metadata(bool allocation_check) {
    for (uint32_t i = 0; i < command_metadata_size(); ++i) {
        const auto* row = command_metadata_at(i);
        const auto name = command_metadata_name(*row);
        std::string spelling(name.p, name.n);
        for (char& c : spelling) if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
        check(command_metadata_lookup(slice(spelling)) == row, "all rows resolve case-insensitively");
        for (auto arg : {std::string("unknown-child"), std::string(4096, 'x')}) {
            Request req({spelling, arg});
            check(command_metadata_resolve(req.op, 0) == legacy_resolve(req.op, 0),
                  "unknown/long argument preserves parent and container behavior");
        }
        const auto pipe = spelling.find('|');
        if (pipe != std::string::npos) {
            Request direct({spelling.substr(0, pipe), spelling.substr(pipe + 1), "key"});
            Request nested({"COMMAND", "GETKEYS", spelling.substr(0, pipe), spelling.substr(pipe + 1), "key"});
            check(command_metadata_resolve(direct.op, 0) == row, "every child including orphan parents");
            direct.op.spec = nullptr; // Parser arity validation precedes spec assignment.
            check(command_metadata_resolve(direct.op, 0) == row, "parser resolves before spec assignment");
            check(command_metadata_resolve(nested.op, 2) == row, "nested COMMAND GETKEYS resolver");
        }
        for (bool resp3 : {false, true}) {
            Request req({"COMMAND", "INFO", spelling});
            if (resp3) req.op.mark_resp3();
            command_metadata_reply_info(req.op, row); hash_wire(req.op);
        }
    }
    for (std::string spelling : {std::string(), std::string("\0get", 4),
                                 std::string("get\0", 4), std::string("\xff", 1)}) {
        check(command_metadata_lookup(slice(spelling)) == linear(slice(spelling)), "binary/empty lookup");
    }
    for (auto args : {std::vector<std::string>{"OBJECT", "ENCODING", "k"},
                     {"XGROUP", "CREATECONSUMER", "k", "g", "c"},
                     {"XINFO", "STREAM", "k"}, {"HSET", std::string(1024, 'k'), "f", "v"},
                     {"ZADD", std::string(1024, 'z'), "1", "m"}}) {
        Request req(args);
        const auto* expected = legacy_resolve(req.op, 0);
        allocations = 0; count_allocations = true;
        const auto* actual = command_metadata_resolve(req.op, 0);
        count_allocations = false;
        check(actual == expected, "indexed resolver agrees with frozen algorithm");
        if (allocation_check) check(allocations == 0, "dispatch metadata resolution must allocate nothing");
    }
    // The allocator detector itself must see the legacy qualified-name allocation.
    Request long_child({"XGROUP", "CREATECONSUMER", "k", "g", "c"});
    allocations = 0; count_allocations = true;
    const auto* observed = legacy_resolve(long_child.op, 0);
    count_allocations = false;
    check(observed && allocations > 0, "legacy allocation control must fire");
    std::printf("PASS exbatch metadata: %u rows; wire=%016llx; allocation control=%zu\n",
                command_metadata_size(), static_cast<unsigned long long>(wire_hash), allocations);
}
}
int main(int argc, char** argv) {
    check(argc == 2, "select publication, watch, metadata, or wire");
    check(command_registry_init(false), "command registry");
    const std::string selection(argv[1]);
    if (selection == "publication") publication();
    else if (selection == "watch") { watch_lifecycle(); watch_oom(); }
    else if (selection == "watch-loads") watch_loads();
    else if (selection == "metadata" || selection == "wire") {
        dump_wire = selection == "wire";
        metadata(selection == "metadata");
    }
    else check(false, "unknown selection");
    std::printf("layouts Op=%zu Client=%zu ThreadCtx=%zu Shard=%zu FlatStore=%zu Rob=%zu AtomicEntry=%zu Config=%zu\n",
        sizeof(Op), sizeof(Client), sizeof(ThreadCtx), sizeof(Shard), sizeof(FlatStore),
        sizeof(Rob<64>), sizeof(AtomicEntry), sizeof(Config));
}
