// Deterministic serverless lifetime schedules. ALL linked implementation TUs
// use the same sanitizer and test-hook flags. No listener or ring is started.
#include "src/core/io_loop.h"
#include "src/core/ex_loop.h"
#include <condition_variable>
#include <chrono>
#include <thread>
#include <new>

using namespace tomo;
using Hooks = DatabaseMapTestHooks;
using Scope = Server::DatabaseWorkScope;

namespace {
thread_local int allocation_budget = -1;
thread_local size_t allocation_attempts = 0;
void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL mdbqsbr: %s\n", why); std::exit(1); }
}
void allocation() {
    if (allocation_budget < 0) return;
    ++allocation_attempts;
    if (!allocation_budget--) throw std::bad_alloc();
}
struct Event {
    std::mutex mutex;
    std::condition_variable cv;
    bool ready = false;
    void signal() { std::lock_guard lock(mutex); ready = true; cv.notify_all(); }
    void wait() {
        std::unique_lock lock(mutex);
        require(cv.wait_for(lock, std::chrono::seconds(5), [&] { return ready; }),
                "deterministic window opened before deadline");
    }
};
struct Fixture {
    Server server;
    DatabaseMap& map = server.databases();
    Fixture() {
        require(map.bind_workers(8), "allocate eight physical participants");
        Hooks::server = &server;
        require(map.swap(0, 1), "first nonidentity publication");
    }
    void ack(unsigned skip = UINT32_MAX) {
        for (unsigned tid = 1; tid < 8; ++tid)
            if (tid != skip) map.quiescent(server, tid);
        if (skip != 0) map.quiescent(server, 0);
    }
};
Fixture* current = nullptr;
const void* held = nullptr;
size_t held_deletions = 0, load_windows = 0;
void deletion(const void* p) { if (p == held) ++held_deletions; }
void remember(const void* p) { held = p; ++load_windows; }
void hold_setup(Fixture& f) {
    current = &f; held = nullptr; held_deletions = load_windows = 0;
    Hooks::deleting = deletion; Hooks::loaded = remember;
}
void hooks_clear() {
    Hooks::loaded = nullptr; Hooks::deleting = nullptr;
    Hooks::before_publish = nullptr; Hooks::loop_pass = nullptr;
}
void after_grace(Fixture& f) {
    f.ack();
    require(held_deletions == 1, "last-swap maintenance frees held version exactly once");
    require(DatabaseMapTest::backlog(f.map) == 0 && !f.map.reclamation_pending(),
            "last-swap queue drains to empty");
    const auto scans = Hooks::scans.load();
    f.ack();
    require(held_deletions == 1 && Hooks::scans == scans, "empty map performs no scan or double free");
}

void lifetime(bool publisher, bool nested) {
    Fixture f; hold_setup(f);
    const unsigned tid = publisher ? 0 : 1;
    {
        Scope outer(f.server, tid);
        DatabaseMap::Read read(f.map);
        require(load_windows == 1 && held, "reader paused after old pointer load");
        require(f.map.swap(0, 1), "retire held map");
        if (nested) {
            Scope inner(f.server, tid);
            f.map.quiescent(f.server, tid);
        }
        f.ack();
        if (publisher) DatabaseMapTest::maintenance(f.map, f.server);
        require(held_deletions == 0 && DatabaseMapTest::backlog(f.map) == 1,
                "held map not deleted before final dereference");
        require(read[0] == 1 && read[1] == 0 && read.epoch() == 1,
                "old immutable map remains readable");
        require(f.server.client_work_epoch(tid) & 1, "nested exit preserves outer epoch");
    }
    Hooks::loaded = nullptr;
    after_grace(f); hooks_clear();
}

void publish_during_copy(const void* p) {
    remember(p); Hooks::loaded = nullptr;
    require(current->map.swap(0, 1), "copy/scan window publishes after load");
    current->ack();
    require(held_deletions == 0, "capture/logical retains map through last dereference");
}
void copy_or_logical(bool logical) {
    Fixture f; hold_setup(f); Hooks::loaded = publish_during_copy;
    {
        Scope scope(f.server, 1);
        if (logical) require(f.map.logical(1) == 0, "logical scan uses loaded version");
        else {
            auto copy = f.map.capture();
            require(copy[0] == 1 && copy[1] == 0 && copy.epoch == 1,
                    "capture owns all bytes and epoch from loaded version");
        }
    }
    require(load_windows == 1, "copy/scan load window opened exactly once");
    after_grace(f); hooks_clear();
}

Event *enter_event, *loaded_event, *release_event;
void entry_loaded(const void* p) {
    remember(p); loaded_event->signal(); release_event->wait();
}
void before_publication() { enter_event->signal(); loaded_event->wait(); }
void entry() {
    Fixture f; hold_setup(f);
    Event enter, loaded, release;
    enter_event = &enter; loaded_event = &loaded; release_event = &release;
    Hooks::loaded = entry_loaded; Hooks::before_publish = before_publication;
    require(f.server.client_work_epoch(1) == 0, "participant even before publication window");
    std::thread reader([&] {
        enter.wait();
        Scope scope(f.server, 1);
        DatabaseMap::Read read(f.map);
        require(read[0] == 1 && read[1] == 0, "racing entrant finishes old map dereferences");
    });
    require(f.map.swap(0, 1), "publication follows even-sampled participant entry");
    require(load_windows == 1 && (f.server.client_work_epoch(1) & 1),
            "precise even-to-entry-before-publication window opened");
    f.ack(1);
    require(held_deletions == 0 && DatabaseMapTest::acknowledged(f.map, 1) == 0,
            "sampled-even participant still owes publication acknowledgement");
    release.signal(); reader.join();
    Hooks::loaded = nullptr; Hooks::before_publish = nullptr;
    after_grace(f); hooks_clear();
}

void park_or_role(bool role) {
    Fixture f; hold_setup(f);
    {
        Scope scope(f.server, 1);
        DatabaseMap::Read read(f.map);
        require(read[0] == 1, "pre-park/role reader loaded");
    }
    require(!(f.server.client_work_epoch(1) & 1), "park/role gap has an even epoch");
    require(f.map.swap(0, 1), "publish in park/role gap");
    f.ack(1);
    require(held_deletions == 0 && DatabaseMapTest::backlog(f.map) == 1,
            "parked/even/role-changing participant not silently exempted");
    Hooks::loaded = nullptr;
    {
        Scope resumed(f.server, 1);
        if (role) { Server::ClientWorkScope owner(f.server, 1); }
        require(DatabaseMapTest::acknowledged(f.map, 1) != 0,
                "resume/role entry acquires request before acknowledging");
        f.ack(1);
        require(held_deletions == 1, "resume allows grace while new scope is active");
        DatabaseMap::Read read(f.map);
        require(read[0] == 0 && read.epoch() == 2, "post-ack reader sees published map");
    }
    after_grace(f); hooks_clear();
}

void backlog() {
    Fixture f; hold_setup(f);
    {
        Scope held_scope(f.server, 1);
        DatabaseMap::Read read(f.map);
        Hooks::loaded = nullptr;
        for (unsigned i = 0; i < 160; ++i) {
            if (i & 1) {
                DatabaseMap::Map restore;
                if (i & 2) std::swap(restore[0], restore[1]);
                require(f.map.restore(restore.data()), "repeated restore publication");
            } else require(f.map.swap(0, 1), "repeated swap publication");
            f.ack(1);
        }
        require(DatabaseMapTest::backlog(f.map) == 160 && held_deletions == 0,
                "stalled participant retains every required version without budget eviction");
        require(read[0] == 1 && read.epoch() == 1, "oldest map survives 160 publications");
    }
    // There is always at least one active new reader throughout the drain.
    // No global-idle instant is needed; acknowledgements survive new odd scopes.
    Scope first(f.server, 2);
    {
        Scope second(f.server, 1);
        f.ack(1);
        require(DatabaseMapTest::backlog(f.map) == 0 && held_deletions == 1,
                "staggered active readers drain backlog without global idle or another write");
    }
    hooks_clear();
}

void failures() {
    Fixture f;
    const auto before = f.map.capture();
    std::unique_ptr<DatabaseMap::Map> prepared;
    for (int budget : {0, 1}) { // map allocation, then retirement queue allocation
        const auto live = Hooks::allocated.load() - Hooks::freed.load();
        allocation_budget = budget;
        const bool ok = f.map.prepare_publish(before, prepared);
        allocation_budget = -1;
        require(!ok && !prepared && Hooks::allocated - Hooks::freed == live,
                "failed prepare frees its map and leaves no prepared object");
        require(f.map.capture().epoch == before.epoch && DatabaseMapTest::backlog(f.map) == 0,
                "failed prepare preserves mapping and retirement queue");
    }
    allocation_budget = 0;
    const bool swap_ok = f.map.swap(0, 1);
    allocation_budget = -1;
    require(!swap_ok && f.map.capture().epoch == before.epoch, "map allocation failure leaves live map intact");
    auto next = before; std::swap(next[0], next[1]); ++next.epoch;
    require(f.map.prepare_publish(next, prepared), "successful prepare owns reserved capacity");
    // Refused transaction drops its prepared object; no commit/publication occurs.
    prepared.reset();
    require(f.map.capture().epoch == before.epoch && Hooks::allocated - Hooks::freed == 1,
            "refused prepared publication has no leak or partial commit");
    require(f.map.prepare_publish(next, prepared), "reprepare after refusal");
    allocation_attempts = 0; allocation_budget = 0;
    bool threw = false;
    try { f.map.publish_prepared(std::move(prepared)); }
    catch (const std::bad_alloc&) { threw = true; }
    allocation_budget = -1;
    require(!threw && allocation_attempts == 0, "prepared commit performs zero allocations under denial");
    require(f.map.capture()[0] == 0 && f.map.capture().epoch == next.epoch,
            "prepared commit publishes complete immutable map");
    f.ack();
    require(DatabaseMapTest::backlog(f.map) == 0, "prepared retirement reclaims without another writer");
    DatabaseMap::Map bad; bad[1] = bad[0];
    require(!f.map.restore(bad.data()) && f.map.capture().epoch == next.epoch,
            "invalid restore preserves committed map");
}

// A link wrapper refuses the real producer's journal admission at the exact
// record_database_map call. No unrelated persistence implementation is replaced.
bool refuse_journal = false;
void journal() {
    Fixture f; AofProducer producer;
    auto before = f.map.capture();
    const auto live = Hooks::allocated - Hooks::freed;
    refuse_journal = true;
    require(!f.map.swap(0, 1, &producer), "forced AOF refusal reached journal call");
    refuse_journal = false;
    require(f.map.capture() == before && f.map.capture().epoch == before.epoch &&
            DatabaseMapTest::backlog(f.map) == 0 && Hooks::allocated - Hooks::freed == live,
            "AOF refusal leaves old mapping live with no leak or partial publication");
}
} // namespace

void* operator new(size_t n) {
    allocation(); if (void* p = std::malloc(n ? n : 1)) return p; throw std::bad_alloc();
}
void* operator new[](size_t n) { return ::operator new(n); }
void* operator new(size_t n, std::align_val_t a) {
    allocation(); void* p = nullptr;
    if (!posix_memalign(&p, size_t(a), n ? n : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](size_t n, std::align_val_t a) { return ::operator new(n, a); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }
void operator delete(void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p, size_t, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t, std::align_val_t) noexcept { std::free(p); }

bool real_record(AofProducer*, const uint8_t*)
    asm("__real__ZN4tomo11AofProducer19record_database_mapEPKh");
bool wrap_record(AofProducer* p, const uint8_t* bytes)
    asm("__wrap__ZN4tomo11AofProducer19record_database_mapEPKh");
bool wrap_record(AofProducer* p, const uint8_t* bytes) {
    return refuse_journal ? false : real_record(p, bytes);
}

namespace tomo {
struct CoreConcurrencyTest {
    static void endpoints() {
        Fixture f; f.server.cfg_.databases = 16;
        for (const char* cmd : {"COPY", "MOVE"}) {
            // Use an owning argument frame and the production parser + stamper.
            const bool copy = std::strcmp(cmd, "COPY") == 0;
            const std::string frame = copy
                ? "*5\r\n$4\r\nCOPY\r\n$1\r\na\r\n$1\r\nb\r\n$2\r\nDB\r\n$1\r\n1\r\n"
                : "*3\r\n$4\r\nMOVE\r\n$1\r\na\r\n$1\r\n1\r\n";
            Op op; uint32_t at = 0; const char* error = nullptr;
            require(resp_parse(frame.data(), frame.size(), at, op, &error) == ParseResult::Ok,
                    "COPY/MOVE parser creates both endpoints");
            op.spec = command_lookup(op.cmd_name());
            auto before = f.map.capture();
            hold_setup(f); Hooks::loaded = publish_during_copy;
            {
                Scope scope(f.server, 1);
                multidb_stamp(f.server, op, 0);
                require(op.physical_db == before[0] && op.secondary_db == before[1] &&
                        op.physical_db != op.secondary_db,
                        "COPY/MOVE endpoints use one immutable version across forced swap");
            }
            require(load_windows == 1, "endpoint swap window opened once");
            after_grace(f); hooks_clear();
        }
    }
    static void loop_callback(Server& server, ThreadCtx& self, unsigned path) {
        require(server.client_work_epoch(self.id()) & 1,
                "ordinary IO/owner loop covers stamping with read-local off");
        const char frame[] = "*2\r\n$3\r\nGET\r\n$1\r\nk\r\n";
        Op op; uint32_t at = 0; const char* error = nullptr;
        require(resp_parse(frame, sizeof(frame) - 1, at, op, &error) == ParseResult::Ok,
                "loop parser loads actual command frame");
        op.spec = command_lookup(op.cmd_name());
        multidb_stamp(server, op, 0);
        require(op.physical_db == 1 && op.key().ns == 1,
                "loop stamping sees immutable map under physical participant scope");
        ++load_windows;
        require(path <= 2, "baseline/reorder/owner loop path identified");
        self.stop_flag().store(true);
    }
    static void coverage() {
        for (bool fused : {false, true}) for (bool reorder : {false, true})
        for (bool overlap : {false, true}) {
            Fixture f; f.server.cfg_.databases = 16; f.server.cfg_.read_local = 0;
            ThreadCtx self; self.init(1, Role::Ifid, 8, 0, 0);
            IoLoop io; io.srv_ = &f.server; io.self_ = &self;
            Hooks::loop_pass = loop_callback; load_windows = 0;
            // The test hook returns before transport/control work; no ring/listener.
            if (reorder && fused) {
                io.r7_run_loop<false, false, true, true, 0>();
            } else {
                if (fused) io.run_loop<false, false, true, true, 0>();
                else if (overlap) io.run_loop<false, false, true, false, 1>();
                else io.run_loop<false, false, true, false, 0>();
            }
            require(load_windows == 1 && !(f.server.client_work_epoch(1) & 1),
                    "IO loop exits its complete scope once");
            // Same physical participant changes role; no epoch/ack reset.
            self.set_role(Role::Ex); self.stop_flag().store(false);
            ExLoop owner; owner.srv_ = &f.server; owner.self_ = &self;
            owner.run();
            require(load_windows == 2 && !(f.server.client_work_epoch(1) & 1),
                    "IO-to-EX role tenure uses same participant and unwinds scope");
            hooks_clear();
        }
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    require(command_registry_init(false), "command registry");
    std::string selection = argc > 1 ? argv[1] : "all";
    if (argc == 3) Hooks::fault = static_cast<Hooks::Fault>(std::atoi(argv[2]));
    const auto run = [&](const char* name, auto fn) {
        if (selection != "all" && selection != name) return;
        const auto before = Hooks::allocated - Hooks::freed;
        fn();
        require(Hooks::allocated - Hooks::freed == before, "fixture destruction releases all map versions");
        std::printf("PASS mdbqsbr %s\n", name);
    };
    run("lifetime", [] { lifetime(false, false); });
    run("owner", [] { lifetime(true, false); });
    run("nested", [] { lifetime(false, true); });
    run("capture", [] { copy_or_logical(false); });
    run("logical", [] { copy_or_logical(true); });
    run("entry", entry);
    run("park", [] { park_or_role(false); });
    run("role", [] { park_or_role(true); });
    run("backlog", backlog);
    run("allocation", failures);
    run("journal", journal);
    run("endpoints", CoreConcurrencyTest::endpoints);
    run("coverage", CoreConcurrencyTest::coverage);
}
