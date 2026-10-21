// C3: hold Client reclamation after the real close_client socket-release fence.
// The synthetic TLS sidecar has completed a bidirectional handshake; no socket,
// SSL engine, executor or listener runs in this deterministic lifetime witness.
#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <openssl/ssl.h>
#define private public
#include "src/net/tls.h"
#undef private
#define TOMO_CORE_CONCURRENCY_EMBED
#define TOMO_CORE_CONCURRENCY_TEST
#include "core_concurrency_unit.cc"
#undef TOMO_CORE_CONCURRENCY_EMBED

namespace tomo {
struct LbPlannerTest {
    template<bool Fused> static void run() {
        CoreConcurrencyTest::Fixture<Fused> f;
        auto* client = new Client(-1);
        f.client(*client);
        f.server.client_accepted();
        auto tls = std::make_unique<TlsConn>();
        tls->state_ = TlsConn::State::Ktls;
        tls->ktls_engaged_ = true;
        tls->shutdown_started_ = true;
        f.io.tls_slots_.push_back(std::move(tls));
        client->set_tls_slot(0);
        auto& sig = f.server.thread(f.io_id).sig();
        sig.tls_accepts = sig.tls_ktls_active = 1;
        client->mark_closing();
        f.io.close_client(client);
        CoreConcurrencyTest::require(client->dead() && f.server.live_clients() == 0 &&
            f.io.dead_next_.size() == 1, "socket released, Client still deferred (window required)");
        std::fprintf(stderr, "mode=%s live=%llu ktls=%llu tls_closed=%llu retained=%zu\n",
            Fused ? "1s" : "2s", (unsigned long long)f.server.live_clients(),
            (unsigned long long)sig.tls_ktls_active,
            (unsigned long long)sig.tls_connections_freed, f.io.dead_next_.size());
        CoreConcurrencyTest::require(sig.tls_ktls_active == 0 && sig.tls_connections_freed == 1,
            "TLS gauges must reflect socket release before deferred Client reclamation");
        f.io.reap_dead();
        f.io.reap_dead();
        CoreConcurrencyTest::require(sig.tls_ktls_active == 0 && sig.tls_connections_freed == 1 &&
            f.io.dead_next_.empty() && f.io.dead_ready_.empty(), "reaping must not double-count");
    }
};
}

int main() {
    tomo::CoreConcurrencyTest::require(tomo::command_registry_init(false), "registry");
    tomo::LbPlannerTest::run<false>();
    tomo::LbPlannerTest::run<true>();
    std::puts("PASS kTLS socket lifetime accounting");
}
