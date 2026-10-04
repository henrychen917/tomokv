// Real WbEngine/Client/ROB paths, without a listener, worker, or kernel io_uring.
// Pending TLS output is a deliberately constructed memory-BIO flight. It tests
// ciphertext dispatch, not a handshake; live handshake/mode witnesses stay in tls.py.
#include <array>
#include <memory>
#include <string>
#include <sys/socket.h>
#include <unistd.h>
#include "src/net/wb.h"

namespace tlsserve_test {
using namespace tomo;

// Explicit-instantiation access keeps fixture plumbing out of production layouts.
struct SqAccess { using Type = io_uring Ring::*; friend Type member(SqAccess); };
template <SqAccess::Type P> struct SqMember {
    friend SqAccess::Type member(SqAccess) { return P; }
};
template struct SqMember<&Ring::r_>;
struct BioAccess { using Type = BIO* TlsConn::*; friend Type member(BioAccess); };
template <BioAccess::Type P> struct BioMember {
    friend BioAccess::Type member(BioAccess) { return P; }
};
template struct BioMember<&TlsConn::external_bio_>;

enum Transport { Plain, Ktls, Userspace };
inline unsigned cases = 0;
inline std::string context;
inline void require(bool okay, const char* assertion) {
    if (!okay) {
        std::fprintf(stderr, "FAIL tlsserve %s: %s\n", context.c_str(), assertion);
        std::exit(1);
    }
}
inline bool selected(const char* name) {
    const char* only = std::getenv("TLSERVE_CASE");
    return !only || std::strcmp(only, name) == 0;
}

inline std::string staged(Client& c, bool* borrowed = nullptr) {
    std::string bytes(c.send_buf().data() + c.wsent(), c.send_buf().size() - c.wsent());
    bool borrow = false;
    uint32_t count = 0;
    c.build_segment_iov(borrow, count);
    const msghdr* msg = c.send_msg();
    for (size_t i = 0; i < msg->msg_iovlen; ++i)
        bytes.append(static_cast<const char*>(msg->msg_iov[i].iov_base), msg->msg_iov[i].iov_len);
    bytes.append(c.fill_buf().data(), c.fill_buf().size());
    if (borrowed) *borrowed = borrow;
    return bytes;
}

struct Fixture {
    Ring ring;
    WbEngine wb;
    Client c{-1};
    TlsConn tls;
    BIO* writer = nullptr;
    std::atomic<bool> limits;
    LoopSignals signals;
    uint32_t now = 10, head = 0;
    std::array<io_uring_sqe, 8> sqes{};
    Transport transport;
    unsigned hooks = 0, releases = 0, limit_calls = 0;
    bool reject = false, tearing_down = false, push_in_hook = false;
    bool allowed = false;
    std::string payload, at_release, at_limit;
    static constexpr const char* push = "*1\r\n+PUSH\r\n";
    Fixture(Transport t, bool track) : limits(track), transport(t) {
        auto& raw = ring.*member(SqAccess{});
        raw.sq.khead = &head;
        raw.sq.ring_entries = sqes.size();
        raw.sq.ring_mask = sqes.size() - 1;
        raw.sq.sqes = sqes.data();
        // Begin in the opposite state: both start and stop must really run.
        if (!track) c.start_obuf_tracking();
        wb.bind(&ring, this, [](void* p, int32_t shard, const char* value) {
            auto& f = *static_cast<Fixture*>(p);
            ++f.releases;
            require(shard == 7 && value == f.payload.data() && f.releases == 1,
                    "release-identity-count");
            if (!f.tearing_down) {
                require(f.hooks == 1 && staged(f.c) == f.at_release &&
                        f.wb.stats().retired == 0 && f.wb.stats().direct == 0 &&
                        f.wb.stats().zc_releases == 1 && f.signals.tls_zc_suppressed == 1,
                        "release-order");
                std::fill(f.payload.begin(), f.payload.end(), 'X');
            }
        }, this, [](void* p, Client& c, Op& op) {
            auto& f = *static_cast<Fixture*>(p);
            ++f.hooks;
            require(op.zc_ptr == f.payload.data() && f.hooks == 1 &&
                    f.signals.tls_zc_suppressed == unsigned(f.transport != Plain),
                    "retire-before-stage");
            if (f.push_in_hook)
                require(f.wb.defer_oob(c, push, std::strlen(push)), "hook-oob-armed");
        }, &limits, this, [](void* p, Client& c) {
            auto& f = *static_cast<Fixture*>(p);
            ++f.limit_calls;
            if (f.reject)
                require(staged(c) == f.at_limit && f.wb.deferred_output_bytes(c) == 0 &&
                        c.rob().quiesced() && f.wb.stats().retired == 0 &&
                        f.wb.stats().serves == 1 && f.wb.migration_ready(c),
                        "limit-after-oob-before-accounting");
            return f.reject;
        }, &now, &signals);
    }
    ~Fixture() {
        tearing_down = true;
        c.set_send_inflight(false);
        wb.teardown(c);
        if (writer) BIO_free(writer);
    }
    Op& issue() {
        Op* op = c.rob().acquire();
        require(op != nullptr, "fixture-rob-acquire");
        c.rob().publish();
        op->state.store(OpState::Done, std::memory_order_release);
        return *op;
    }
    void ciphertext() {
        BIO* external = nullptr;
        require(BIO_new_bio_pair(&writer, 4096, &external, 4096) == 1, "fixture-bio-pair");
        tls.*member(BioAccess{}) = external;
        require(BIO_write(writer, "ciphertext", 10) == 10 && tls.output_pending(),
                "ciphertext-window-armed");
    }
    unsigned submitted() { return (ring.*member(SqAccess{})).sq.sqe_tail; }
    void accounting(unsigned retired, unsigned direct, unsigned serves = 1) {
        require(wb.stats().serves == serves && wb.stats().retired == retired &&
                wb.stats().direct == direct && wb.stats().serves_empty == unsigned(retired == 0),
                "serve-retire-direct-empty-counts");
        require(limit_calls == (limits ? serves : 0), "limit-callback-gating");
        require(c.obuf_bytes() == (limits ? c.buffered_output_bytes() : 0), "output-accounting");
    }
};

// Call 0/1 = serve (ClassifySend false/true); 2 = prepare with submit_allowed.
// The prepare API has Submit=false, ClassifySend=false.
template <Transport T, bool Ep, bool Coded, unsigned Call>
bool invoke(Fixture& f) {
    static_assert(Call <= 2);
    if constexpr (Call < 2) {
        if constexpr (T == Plain) return f.wb.serve<Ep, Call == 1, Coded>(f.c);
        if constexpr (T == Ktls) return f.wb.serve_ktls<Ep, Call == 1, Coded>(f.c);
        if constexpr (T == Userspace) return f.wb.serve_tls<Ep, Call == 1, Coded>(f.c, f.tls);
    } else if constexpr (Call == 2) {
        if constexpr (T == Plain) return f.wb.prepare<Ep, Coded>(f.c, f.allowed);
        if constexpr (T == Ktls) return f.wb.prepare_ktls<Ep, Coded>(f.c, f.allowed);
        if constexpr (T == Userspace) return f.wb.prepare_tls<Ep, Coded>(f.c, f.tls, f.allowed);

    }
}

template <bool Coded> void okay_reply(Op& op) {
    if constexpr (Coded) op.reply_code_ = static_cast<uint8_t>(ReplyCode::Ok);
    else op.reply.append("+OK\r\n", 5);
}

template <Transport T, bool Ep, bool Coded, unsigned Call>
void matrix() {
    for (bool track : {false, true}) {
        const std::string config = std::to_string(T) + "/" + std::to_string(track) + "/" +
            std::to_string(Ep) + "/" + std::to_string(Coded) + "/" + std::to_string(Call);
        const char* only_config = std::getenv("TLSERVE_CONFIG");
        if (only_config && config != only_config) continue;
        auto run = [&](const char* name, auto test) {
            if (!selected(name)) return;
            context = std::string(name) + " transport=" + std::to_string(T) +
                " track=" + std::to_string(track) + " ep=" + std::to_string(Ep) +
                " coded=" + std::to_string(Coded) + " call=" + std::to_string(Call);
            Fixture f(T, track);
            test(f);
            ++cases;
        };
        auto call = [](Fixture& f) { return invoke<T, Ep, Coded, Call>(f); };
        run("empty", [&](Fixture& f) {
            require(!call(f), "empty-progress");
            f.accounting(0, 0);
            if constexpr (Call == 2) require(f.allowed, "prepare-allows-submit");
        });
        run("direct-spill", [&](Fixture& f) {
            f.c.set_send_inflight(true);
            auto& op = f.issue();
            op.direct = f.c.reserve_fill(9);
            std::memcpy(op.direct, "+DIRECT\r\n", 9); op.direct_len = 9;
            std::string spill(4097, 's'); op.reply.append(spill.data(), spill.size());
            require(call(f) && staged(f.c) == "+DIRECT\r\n" + spill, "direct-spill-bytes");
            f.accounting(1, 1);
        });
        for (bool pending : {false, true}) run(pending ? "pending-code" : "coded-frontier", [&](Fixture& f) {
            f.c.set_send_inflight(true);
            if (pending) f.c.append_static_segment("+OLDER\r\n", 8);
            okay_reply<Coded>(f.issue());
            require(call(f) && staged(f.c) == (pending ? "+OLDER\r\n+OK\r\n" : "+OK\r\n"),
                    "coded-or-materialized-bytes");
            f.accounting(1, 0);
        });
        for (bool coded_borrow : {false, true}) run(coded_borrow ? "coded-borrow" : "borrow-oob", [&](Fixture& f) {
            f.c.set_send_inflight(true);
            f.c.append_fill("+OLDER\r\n", 8);
            auto& op = f.issue();
            if (coded_borrow) okay_reply<Coded>(op);
            else {
                op.direct = f.c.reserve_fill(7);
                std::memcpy(op.direct, "$8193\r\n", 7); op.direct_len = 7;
            }
            f.payload.assign(8193, 'b');
            op.zc_ptr = f.payload.data(); op.zc_len = f.payload.size(); op.zc_shard = 7;
            op.mark_no_borrow();
            okay_reply<Coded>(f.issue());
            const std::string prefix = std::string("+OLDER\r\n") +
                (coded_borrow ? "+OK\r\n" : "$8193\r\n") + f.payload;
            f.at_release = prefix + (T == Userspace ? "\r\n" : "");
            f.push_in_hook = true;
            bool borrowed = false;
            require(call(f), "borrow-progress");
            require(staged(f.c, &borrowed) == prefix + "\r\n+OK\r\n" + Fixture::push,
                    "borrow-crlf-oob-order");
            require(borrowed == (T == Plain) && f.releases == unsigned(T != Plain) &&
                    f.hooks == 1 && f.signals.tls_zc_suppressed == (T == Plain ? 0 : 2),
                    "borrow-policy-release-suppression");
            require(f.wb.deferred_output_bytes(f.c) == 0 && f.wb.migration_ready(f.c), "oob-fully-flushed");
            f.accounting(2, coded_borrow ? 0 : 1);
            f.tearing_down = true; f.c.set_send_inflight(false); f.wb.teardown(f.c);
            require(f.releases == 1 && f.wb.stats().zc_releases == 1, "borrow-released-once");
        });
        if constexpr (T != Userspace) run("pump-ready", [&](Fixture& f) {
            f.c.append_fill("+READY\r\n", 8);
            bool did = call(f);
            constexpr bool submit = Call < 2;
            require(f.wb.stats().sends_submitted == unsigned(submit) &&
                    f.submitted() == unsigned(submit && !Ep) &&
                    did == (submit && !Ep), "plain-pump-selection");
            if constexpr (submit && !Ep)
                require(f.sqes[0].user_data == ur_tag(UrKind::Send, &f.c) &&
                        f.sqes[0].len == 8 && f.c.send_inflight() &&
                        f.ring.send_pending() == (Call == 1), "plain-send-and-classification");
            require(staged(f.c) == "+READY\r\n", "plain-frontier-unchanged");
            f.accounting(0, 0);
        });
        run("oob-hole", [&](Fixture& f) {
            f.c.set_send_inflight(true);
            okay_reply<Coded>(f.issue());
            Op& second = f.issue(); okay_reply<Coded>(second);
            second.state.store(OpState::Issued);
            require(f.wb.defer_oob(f.c, Fixture::push, std::strlen(Fixture::push)), "oob-hole-armed");
            require(call(f) && staged(f.c) == "+OK\r\n" && f.c.rob().in_flight() == 1 &&
                    f.wb.deferred_output_bytes(f.c) == std::strlen(Fixture::push), "oob-held-at-hole");
            second.state.store(OpState::Done, std::memory_order_release);
            require(call(f) && staged(f.c) == std::string("+OK\r\n+OK\r\n") + Fixture::push &&
                    f.wb.deferred_output_bytes(f.c) == 0, "oob-flushed-after-frontier");
            f.accounting(2, 0, 2);
        });
        for (bool empty : {false, true}) run(empty ? "limit-empty" : "limit-reply", [&](Fixture& f) {
            f.reject = true;
            // An unarmed callback cannot refuse; hold its send only in that case.
            f.c.set_send_inflight(!track);
            if (!empty) {
                okay_reply<Coded>(f.issue());
                require(f.wb.defer_oob(f.c, Fixture::push, std::strlen(Fixture::push)), "limit-oob-armed");
                f.at_limit = std::string("+OK\r\n") + Fixture::push;
            }
            if constexpr (T == Userspace) f.ciphertext();
            require(call(f) == (track || !empty), "limit-progress");
            constexpr bool ep_plain_submit = Ep && T != Userspace && Call < 2;
            const unsigned unarmed_sends = !track && !empty && ep_plain_submit;
            require(!f.submitted() && f.wb.stats().sends_submitted == unarmed_sends,
                    "limit-prevents-pump");
            if constexpr (Call == 2) require(f.allowed == !track, "limit-submit-allowed");
            f.accounting(empty ? 0 : 1, 0);
        });
        if constexpr (T == Userspace) run("cipher-only", [&](Fixture& f) {
            f.ciphertext();
            require(f.c.nothing_to_write(), "cipher-only-no-plaintext");
            // An invalid fd is never submitted to a kernel ring. Epoll's send(-1)
            // deterministically returns EBADF, but its attempted pump is counted.
            bool did = call(f);
            constexpr bool submit = Call < 2;
            require(f.wb.stats().sends_submitted == unsigned(submit) &&
                    f.submitted() == unsigned(submit && !Ep) &&
                    did == (submit && !Ep), "cipher-only-pump-selection");
            if constexpr (submit && !Ep)
                require(f.sqes[0].user_data == ur_tag(UrKind::TlsSend, &f.c) &&
                        f.sqes[0].len == 10 && f.c.send_inflight() &&
                        f.ring.send_pending() == (Call == 1), "tls-send-and-classification");
            const char* cipher = nullptr;
            require(f.tls.peek_output(cipher) == 10 && std::string(cipher, 10) == "ciphertext" &&
                    f.c.nothing_to_write(), "cipher-frontier-unchanged");
            f.accounting(0, 0);
        });
    }
}

template <Transport T, bool Ep, bool Coded> void calls() {
    matrix<T, Ep, Coded, 0>(); matrix<T, Ep, Coded, 1>();
    matrix<T, Ep, Coded, 2>();
}
template <Transport T> void transport() {
    calls<T, false, false>(); calls<T, false, true>();
    calls<T, true, false>(); calls<T, true, true>();
}
inline void run() {
    cases = 0;
    transport<Plain>(); transport<Ktls>(); transport<Userspace>();
    require(cases != 0, "selected-state-entered");
    std::printf("PASS tlsserve: %u deterministic cases (three transports, both tracking states, "
                "coded/plain, uring/epoll, classified/unclassified serve, prepare API)\n", cases);
}
} // namespace tlsserve_test
