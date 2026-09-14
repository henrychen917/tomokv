// Exercise R2's real boot binder and every registry variant without booting workers,
// a listener, or a Ring. Each process owns a fresh registry; arguments are 0/1 for
// reorder, TLS registry, fused mode, and read-local class prediction respectively.
#include "src/cmd/command.h"
#include "src/core/genthread.h"
#include "src/core/server.h"

#include <cstdio>
#include <cstdlib>
#include <vector>
#ifdef TOMO_JEMALLOC
#include <jemalloc/jemalloc.h>
#endif

namespace {
void require(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "reorder registry: FAIL: %s\n", message);
        std::exit(1);
    }
}
struct Saved {
    const tomo::CommandSpec* row;
    tomo::CommandSpec value;
};
}

int main(int argc, char** argv) {
    require(argc == 5, "expected four boolean arguments");
    bool options[4];
    for (unsigned i = 0; i < 4; i++) {
        require(argv[i + 1][0] >= '0' && argv[i + 1][0] <= '1' &&
                argv[i + 1][1] == '\0', "argument is not 0 or 1");
        options[i] = argv[i + 1][0] == '1';
    }
    const bool armed = options[0], tls = options[1], fused = options[2], local = options[3];
    require(tomo::command_registry_init(tls, fused, local), "registry init");
    std::vector<Saved> before;
    const uint32_t count = tomo::command_registry_size();
    require(count != 0, "empty registry");
    for (uint32_t id = 0; id < count; id++) {
        const auto* spec = tomo::command_registry_at(id);
        const auto* notify = tomo::command_notify_variant(spec);
        const auto* encrypted = tomo::command_tls_variant(spec);
        const auto* encrypted_notify = tomo::command_tls_variant(notify);
        require(spec && notify && encrypted && encrypted_notify, "missing variant");
        require(notify != spec && (!tls || (encrypted != spec && encrypted_notify != notify)),
                "variant witness did not open");
        for (const auto* row : {spec, notify, encrypted, encrypted_notify}) {
            require(!(row->flags & tomo::CmdFlags::ReorderClasses), "registry was already stamped");
            before.push_back({row, *row});
        }
    }
    // No topology or server init: the production binder uses only this boot config.
    // cfg() is const to runtime callers; this stack-owned fixture is still mutable.
    tomo::Server server;
    auto& cfg = const_cast<tomo::Config&>(server.cfg());
    cfg.reorder = armed;
    cfg.read_local = local;
    cfg.thread_mode = fused ? tomo::ThreadMode::Fused : tomo::ThreadMode::Split;
#ifdef TOMO_JEMALLOC
    // Obtain jemalloc's thread counter before the window, including its own
    // first-use setup. This counts allocations even if the binder frees them.
    uint64_t* allocated = nullptr;
    size_t counter_size = sizeof(allocated);
    require(mallctl("thread.allocatedp", &allocated, &counter_size, nullptr, 0) == 0 && allocated,
            "jemalloc allocation witness unavailable");
    const uint64_t before_witness = *static_cast<volatile uint64_t*>(allocated);
    void* witness = mallocx(1, 0);
    require(witness && *static_cast<volatile uint64_t*>(allocated) > before_witness,
            "jemalloc allocation counter did not observe the witness");
    dallocx(witness, 0);
    const uint64_t before_bind = *static_cast<volatile uint64_t*>(allocated);
#endif
    tomo::command_bind_server_selected(&server);
#ifdef TOMO_JEMALLOC
    require(*static_cast<volatile uint64_t*>(allocated) == before_bind,
            "boot binder allocated memory");
#endif
    unsigned cost_rows = 0, barriers = 0, classes = 0;
    for (const Saved& saved : before) {
        const auto& row = *saved.row;
        const auto& old = saved.value;
        const bool barrier = old.flags & tomo::CmdFlags::ReorderBarrier;
        const uint32_t expected = armed && !barrier
            ? tomo::CmdFlags::ReorderPoint << old.length_class : 0;
        require(row.flags == (old.flags | expected), "incorrect cost bits or altered public flags");
        require(row.length_class == old.length_class && row.id == old.id &&
                row.name == old.name && row.handler == old.handler &&
                row.handler_notify == old.handler_notify && row.min_arity == old.min_arity &&
                row.max_arity == old.max_arity && row.first_key == old.first_key &&
                row.last_key == old.last_key && row.key_step == old.key_step,
                "stamping changed registry semantics");
        if (barrier) barriers++;
        else { cost_rows++; classes |= 1u << old.length_class; }
    }
    require(cost_rows && barriers && classes == 7, "cost/barrier/class witnesses did not open");
    for (uint32_t id = 0; id < count; id++) {
        const auto* spec = tomo::command_registry_at(id);
        const tomo::Slice name(spec->name, static_cast<uint32_t>(std::strlen(spec->name)));
        require(tomo::command_lookup(name) == spec && tomo::command_lookup_registry(name) == spec,
                "hot or indexed lookup stopped naming the stamped row");
    }
    tomo::command_bind_server(nullptr);
    std::printf("reorder registry: PASS ro=%u tls=%u fused=%u rl=%u, %u rows, %zu variant checks\n",
                armed, tls, fused, local, count, before.size());
}
