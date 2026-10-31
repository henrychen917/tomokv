// maxmemrace_stress.cc -- CONFIG SET maxmemory publication race stress (lane maxmemrace).
//
// One control connection toggles `CONFIG SET maxmemory` between a tight value and 0.  The moment
// it reads each +OK, the driver writes SETs on K other connections (other IO owners and, through
// key spread, every shard owner).  Redis 7.4 admits every command issued after the +OK under the
// new limit, so with a server that is over the tight limit:
//   * after the +OK of a lift to 0, no SET may be rejected with OOM          (lift violation);
//   * after the +OK of a tight value, no SET may be admitted (noeviction)    (tight violation);
//   * after the +OK of a lift to 0, no key may be evicted (allkeys-lru)      (eviction violation).
// The tight check is applied only where Redis is strict, under noeviction: with allkeys-lru Redis
// itself admits writes while an eviction is still running (EVICT_RUNNING).  Optional background threads pipeline owner-executed reads so
// that executor passes stay long.  The driver never retries or relaxes a check; every violation
// is counted and the first examples are printed with their cycle, connection and reply.
//
// Build: g++ -O2 -std=c++20 -pthread tests/maxmemrace_stress.cc -o build/maxmemrace/stress
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

struct Reply {
    char type = 0;            // + - : $ * (and '_' for null)
    std::string str;
    long long integer = 0;
    std::vector<Reply> elems;
    bool is_ok() const { return type == '+' && str == "OK"; }
    bool is_oom() const { return type == '-' && str.rfind("OOM ", 0) == 0; }
};

[[noreturn]] void die(const std::string& what) { throw std::runtime_error(what); }

class Conn {
public:
    explicit Conn(uint16_t port, int timeout_ms) : timeout_ms_(timeout_ms) {
        fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
        if (fd_ < 0) die("socket");
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (::connect(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0)
            die(std::string("connect: ") + std::strerror(errno));
        int one = 1;
        ::setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    }
    ~Conn() { if (fd_ >= 0) ::close(fd_); }
    Conn(const Conn&) = delete;
    Conn& operator=(const Conn&) = delete;

    void send(const std::string& bytes) {
        size_t off = 0;
        while (off < bytes.size()) {
            const ssize_t n = ::send(fd_, bytes.data() + off, bytes.size() - off, MSG_NOSIGNAL);
            if (n < 0) {
                if (errno == EINTR) continue;
                die(std::string("send: ") + std::strerror(errno));
            }
            off += static_cast<size_t>(n);
        }
    }

    Reply read() {
        for (;;) {
            size_t p = pos_;
            Reply r;
            if (parse(r, p)) {
                pos_ = p;
                if (pos_ > (1u << 20) || pos_ == buf_.size()) { buf_.erase(0, pos_); pos_ = 0; }
                return r;
            }
            fill();
        }
    }

private:
    void fill() {
        pollfd pfd{fd_, POLLIN, 0};
        for (;;) {
            const int rc = ::poll(&pfd, 1, timeout_ms_);
            if (rc < 0 && errno == EINTR) continue;
            if (rc == 0) die("reply timeout");
            if (rc < 0) die("poll");
            break;
        }
        char tmp[65536];
        const ssize_t n = ::recv(fd_, tmp, sizeof(tmp), 0);
        if (n == 0) die("server closed connection");
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN) return;
            die(std::string("recv: ") + std::strerror(errno));
        }
        buf_.append(tmp, static_cast<size_t>(n));
    }

    bool line(size_t& p, std::string& out) {
        const size_t e = buf_.find("\r\n", p);
        if (e == std::string::npos) return false;
        out.assign(buf_, p, e - p);
        p = e + 2;
        return true;
    }

    bool parse(Reply& r, size_t& p) {
        if (p >= buf_.size()) return false;
        const char t = buf_[p++];
        std::string l;
        if (!line(p, l)) return false;
        r.type = t;
        switch (t) {
            case '+': case '-': r.str = l; return true;
            case ':': r.integer = std::atoll(l.c_str()); return true;
            case '_': return true;
            case '$': {
                const long long n = std::atoll(l.c_str());
                if (n < 0) { r.type = '_'; return true; }
                if (buf_.size() < p + static_cast<size_t>(n) + 2) return false;
                r.str.assign(buf_, p, static_cast<size_t>(n));
                p += static_cast<size_t>(n) + 2;
                return true;
            }
            case '*': {
                const long long n = std::atoll(l.c_str());
                if (n < 0) { r.type = '_'; return true; }
                r.elems.resize(static_cast<size_t>(n));
                for (auto& e : r.elems)
                    if (!parse(e, p)) return false;
                return true;
            }
            default: die(std::string("unexpected RESP type byte ") + t);
        }
    }

    int fd_ = -1;
    int timeout_ms_;
    std::string buf_;
    size_t pos_ = 0;
};

std::string cmd(std::initializer_list<std::string> args) {
    std::string out = "*" + std::to_string(args.size()) + "\r\n";
    for (const auto& a : args) {
        out += "$" + std::to_string(a.size()) + "\r\n";
        out += a;
        out += "\r\n";
    }
    return out;
}

unsigned long long info_field(const std::string& info, const char* field) {
    const std::string needle = std::string(field) + ":";
    const size_t at = info.find(needle);
    if (at == std::string::npos) die(std::string("INFO lacks ") + field);
    return std::strtoull(info.c_str() + at + needle.size(), nullptr, 10);
}

struct Options {
    uint16_t port = 0;
    uint64_t toggles = 1000;
    std::string policy = "noeviction";
    std::string submit = "single";   // single | pipe
    uint32_t conns = 8;
    uint32_t per_conn = 4;           // SETs per connection per wave
    uint32_t bg_threads = 0;
    uint32_t bg_conns = 4;           // per background thread
    uint32_t bg_pipe = 64;
    std::string bg_mode = "light";   // light: STRLEN/EXISTS point reads; heavy: EXISTS of
                                     // bg_keys keys that all route to one shard
    uint32_t bg_keys = 256;
    int bg_shard = -1;               // heavy groups from this shard only (-1: every shard)
    std::string tight = "alt";       // one | near | alt
    uint32_t fill = 4096;
    uint32_t value_size = 64;
    uint32_t rotate = 32;            // key namespace rotation (bounds memory growth)
    int timeout_ms = 20000;
    uint32_t examples = 8;
    std::string label;
};

struct Counters {
    uint64_t cycles = 0;
    uint64_t lift_sets = 0, lift_ok = 0, lift_oom = 0, lift_other = 0;
    uint64_t tight_sets = 0, tight_strict_sets = 0, tight_ok = 0, tight_oom = 0, tight_other = 0;
    uint64_t tight_strict_admitted = 0;
    uint64_t evicted_after_lift = 0, eviction_checks = 0;
    uint64_t bg_replies = 0, bg_errors = 0;
    std::vector<std::string> lift_examples, tight_examples, evict_examples, other_examples;
};

void note(std::vector<std::string>& list, uint32_t cap, std::string text) {
    if (list.size() < cap) list.push_back(std::move(text));
}

std::string json_escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (static_cast<unsigned char>(c) < 0x20) {
            char buf[8]; std::snprintf(buf, sizeof(buf), "\\u%04x", c); out += buf;
        } else out += c;
    }
    return out;
}

std::string json_list(const std::vector<std::string>& v) {
    std::string out = "[";
    for (size_t i = 0; i < v.size(); i++) {
        if (i) out += ", ";
        out += "\"" + json_escape(v[i]) + "\"";
    }
    return out + "]";
}

void background(const Options& o, const std::vector<std::vector<std::string>>& groups,
                std::atomic<bool>& stop, std::atomic<uint64_t>& replies,
                std::atomic<uint64_t>& errors, uint32_t seed) {
    try {
        std::vector<std::unique_ptr<Conn>> conns;
        for (uint32_t i = 0; i < o.bg_conns; i++)
            conns.push_back(std::make_unique<Conn>(o.port, o.timeout_ms));
        // Heavy commands are prebuilt: each is one owner task (all keys on one shard) whose
        // cost does not depend on stored data, so eviction cannot make the load disappear.
        std::vector<std::string> heavy;
        for (const auto& keys : groups) {
            std::string c = "*" + std::to_string(keys.size() + 1) + "\r\n$6\r\nEXISTS\r\n";
            for (const auto& k : keys) c += "$" + std::to_string(k.size()) + "\r\n" + k + "\r\n";
            heavy.push_back(std::move(c));
        }
        std::mt19937 rng(seed);
        while (!stop.load(std::memory_order_relaxed)) {
            for (auto& c : conns) {
                std::string batch;
                for (uint32_t i = 0; i < o.bg_pipe; i++) {
                    if (!heavy.empty()) { batch += heavy[rng() % heavy.size()]; continue; }
                    const std::string key = "fill:" + std::to_string(rng() % o.fill);
                    // STRLEN/EXISTS are owner-executed in every geometry, unlike GET which the
                    // read-local lane can serve on the connection's own thread.
                    batch += (i & 1) ? cmd({"STRLEN", key}) : cmd({"EXISTS", key});
                }
                c->send(batch);
            }
            for (auto& c : conns)
                for (uint32_t i = 0; i < o.bg_pipe; i++) {
                    const Reply r = c->read();
                    if (r.type == '-') errors.fetch_add(1, std::memory_order_relaxed);
                    replies.fetch_add(1, std::memory_order_relaxed);
                }
        }
    } catch (const std::exception& e) {
        std::fprintf(stderr, "background thread: %s\n", e.what());
        errors.fetch_add(1000000, std::memory_order_relaxed);
    }
}

// One wave: every connection sends per_conn SETs (pipelined in one write, or one at a time),
// immediately after the caller observed a +OK.  Returns replies in connection-major order.
void wave(const Options& o, std::vector<std::unique_ptr<Conn>>& sets, const std::string& tag,
          uint64_t cycle, const std::string& value, std::vector<std::vector<Reply>>& out) {
    out.assign(sets.size(), {});
    const uint64_t slot = cycle % o.rotate;
    auto key = [&](size_t j, uint32_t m) {
        return tag + ":" + std::to_string(slot) + ":" + std::to_string(j) + ":" + std::to_string(m);
    };
    if (o.submit == "pipe") {
        for (size_t j = 0; j < sets.size(); j++) {
            std::string batch;
            for (uint32_t m = 0; m < o.per_conn; m++) batch += cmd({"SET", key(j, m), value});
            sets[j]->send(batch);
        }
        for (size_t j = 0; j < sets.size(); j++)
            for (uint32_t m = 0; m < o.per_conn; m++) out[j].push_back(sets[j]->read());
    } else {
        for (uint32_t m = 0; m < o.per_conn; m++) {
            for (size_t j = 0; j < sets.size(); j++) sets[j]->send(cmd({"SET", key(j, m), value}));
            for (size_t j = 0; j < sets.size(); j++) out[j].push_back(sets[j]->read());
        }
    }
}

int run(const Options& o) {
    Counters k;
    const auto started = std::chrono::steady_clock::now();
    Conn ctl(o.port, o.timeout_ms);
    auto expect_ok = [&](const std::string& c, const char* what) {
        ctl.send(c);
        const Reply r = ctl.read();
        if (!r.is_ok()) die(std::string(what) + " did not reply +OK: " + r.str);
    };
    expect_ok(cmd({"CONFIG", "SET", "maxmemory", "0"}), "setup CONFIG SET maxmemory 0");
    expect_ok(cmd({"CONFIG", "SET", "maxmemory-policy", o.policy}), "setup maxmemory-policy");
    expect_ok(cmd({"FLUSHALL"}), "setup FLUSHALL");
    const std::string value(o.value_size, 'v');
    for (uint32_t base = 0; base < o.fill; base += 256) {
        std::string batch;
        const uint32_t end = std::min(o.fill, base + 256);
        for (uint32_t i = base; i < end; i++) batch += cmd({"SET", "fill:" + std::to_string(i), value});
        ctl.send(batch);
        for (uint32_t i = base; i < end; i++)
            if (!ctl.read().is_ok()) die("fill SET failed");
    }
    ctl.send(cmd({"INFO", "memory"}));
    const Reply mem = ctl.read();
    const unsigned long long dataset = info_field(mem.str, "used_memory_dataset");
    const unsigned long long used = info_field(mem.str, "used_memory");
    // "near": half of the dataset, so every shard (or the whole Redis heap) is over the limit.
    const unsigned long long near = std::max<unsigned long long>(1, dataset / 2);

    std::vector<std::unique_ptr<Conn>> sets;
    for (uint32_t j = 0; j < o.conns; j++) sets.push_back(std::make_unique<Conn>(o.port, o.timeout_ms));

    // Heavy background groups: TomoKV names each key's shard (DEBUG SHARDS); a server
    // without that oracle (Redis) gets arbitrary groups, which is all a single thread needs.
    std::vector<std::vector<std::string>> groups;
    uint32_t geometry_shards = 0;
    if (o.bg_threads && o.bg_mode == "heavy") {
        std::vector<std::string> keys;
        for (uint32_t i = 0; i < 16384; i++) keys.push_back("bgk:" + std::to_string(i));
        std::vector<std::vector<std::string>> by_shard;
        bool oracle = true;
        for (size_t base = 0; base < keys.size() && oracle; base += 1024) {
            std::string c = "*" + std::to_string(2 + 1024) + "\r\n$5\r\nDEBUG\r\n$6\r\nSHARDS\r\n";
            for (size_t i = base; i < base + 1024; i++)
                c += "$" + std::to_string(keys[i].size()) + "\r\n" + keys[i] + "\r\n";
            ctl.send(c);
            const Reply r = ctl.read();
            if (r.type != '*') { oracle = false; break; }
            for (size_t i = 0; i < r.elems.size(); i++) {
                const auto sid = static_cast<size_t>(r.elems[i].elems.at(0).integer);
                if (by_shard.size() <= sid) by_shard.resize(sid + 1);
                by_shard[sid].push_back(keys[base + i]);
            }
        }
        if (!oracle) {
            by_shard.assign(16, {});
            for (size_t i = 0; i < keys.size(); i++) by_shard[i % 16].push_back(keys[i]);
        } else geometry_shards = static_cast<uint32_t>(by_shard.size());
        // --bg-shard 0 loads only the publishing owner (the owner of shard 0), whose own pass
        // always straddles the commit; with every shard loaded, a fused owner's share drains fast.
        for (size_t sid = 0; sid < by_shard.size(); sid++) {
            if (o.bg_shard >= 0 && sid != static_cast<size_t>(o.bg_shard)) continue;
            const auto& shard = by_shard[sid];
            for (size_t base = 0; base + o.bg_keys <= shard.size(); base += o.bg_keys)
                groups.emplace_back(shard.begin() + base, shard.begin() + base + o.bg_keys);
        }
        if (groups.empty()) die("heavy background: no full key group");
    }
    std::atomic<bool> stop{false};
    std::atomic<uint64_t> bg_replies{0}, bg_errors{0};
    std::vector<std::thread> bg;
    for (uint32_t t = 0; t < o.bg_threads; t++)
        bg.emplace_back(background, std::cref(o), std::cref(groups), std::ref(stop),
                        std::ref(bg_replies), std::ref(bg_errors), 1000u + t);

    std::vector<std::vector<Reply>> replies;
    const bool lru = o.policy != "noeviction";
    int rc = 0;
    try {
        for (uint64_t i = 0; i < o.toggles; i++) {
            const bool one = o.tight == "one" || (o.tight == "alt" && (i & 1) == 0);
            const std::string tight = one ? "1" : std::to_string(near);
            // ---- tight edge: admitted after its +OK only where Redis would also admit.
            ctl.send(cmd({"CONFIG", "SET", "maxmemory", tight}));
            Reply r = ctl.read();
            if (!r.is_ok()) die("CONFIG SET maxmemory " + tight + " replied " + r.str);
            wave(o, sets, "t", i, value, replies);
            // Strict only under noeviction: with an evicting policy Redis admits a write while
            // its eviction is still running (performEvictions() == EVICT_RUNNING), so an
            // admission after a tight +OK is legal there. Lifts stay strict for both policies.
            const bool strict = !lru;
            for (size_t j = 0; j < replies.size(); j++)
                for (size_t m = 0; m < replies[j].size(); m++) {
                    const Reply& x = replies[j][m];
                    k.tight_sets++;
                    if (strict) k.tight_strict_sets++;
                    if (x.is_ok()) {
                        k.tight_ok++;
                        if (strict) {
                            k.tight_strict_admitted++;
                            note(k.tight_examples, o.examples,
                                 "cycle " + std::to_string(i) + " conn " + std::to_string(j) +
                                 " set " + std::to_string(m) + " maxmemory " + tight +
                                 ": +OK after the tight +OK");
                        }
                    } else if (x.is_oom()) k.tight_oom++;
                    else {
                        k.tight_other++;
                        note(k.other_examples, o.examples, "tight cycle " + std::to_string(i) +
                             ": " + std::string(1, x.type) + x.str);
                    }
                }
            // ---- lift edge: every later SET is admitted; nothing is evicted afterwards.
            ctl.send(cmd({"CONFIG", "SET", "maxmemory", "0"}));
            r = ctl.read();
            if (!r.is_ok()) die("CONFIG SET maxmemory 0 replied " + r.str);
            if (lru) ctl.send(cmd({"INFO", "stats"}));       // concurrent with the wave
            wave(o, sets, "l", i, value, replies);
            unsigned long long e0 = 0;
            if (lru) e0 = info_field(ctl.read().str, "evicted_keys");
            for (size_t j = 0; j < replies.size(); j++)
                for (size_t m = 0; m < replies[j].size(); m++) {
                    const Reply& x = replies[j][m];
                    k.lift_sets++;
                    if (x.is_ok()) k.lift_ok++;
                    else if (x.is_oom()) {
                        k.lift_oom++;
                        note(k.lift_examples, o.examples,
                             "cycle " + std::to_string(i) + " conn " + std::to_string(j) +
                             " set " + std::to_string(m) + " after maxmemory " + tight +
                             "->0 +OK: " + x.str);
                    } else {
                        k.lift_other++;
                        note(k.other_examples, o.examples, "lift cycle " + std::to_string(i) +
                             ": " + std::string(1, x.type) + x.str);
                    }
                }
            if (lru) {
                ctl.send(cmd({"INFO", "stats"}));
                const unsigned long long e1 = info_field(ctl.read().str, "evicted_keys");
                k.eviction_checks++;
                if (e1 > e0) {
                    k.evicted_after_lift += e1 - e0;
                    note(k.evict_examples, o.examples,
                         "cycle " + std::to_string(i) + " maxmemory " + tight + "->0: evicted_keys " +
                         std::to_string(e0) + " -> " + std::to_string(e1) + " after the lift +OK");
                }
            }
            k.cycles++;
        }
    } catch (const std::exception& e) {
        std::fprintf(stderr, "driver aborted at cycle %llu: %s\n",
                     static_cast<unsigned long long>(k.cycles), e.what());
        note(k.other_examples, o.examples, std::string("ABORT: ") + e.what());
        rc = 3;
    }
    stop.store(true);
    for (auto& t : bg) t.join();
    k.bg_replies = bg_replies.load();
    k.bg_errors = bg_errors.load();
    try { expect_ok(cmd({"CONFIG", "SET", "maxmemory", "0"}), "final CONFIG SET maxmemory 0"); }
    catch (const std::exception& e) { if (!rc) rc = 3; note(k.other_examples, o.examples, e.what()); }
    const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    const uint64_t violations = k.lift_oom + k.tight_strict_admitted + k.evicted_after_lift;
    std::printf("{\"label\": \"%s\", \"port\": %u, \"toggles_requested\": %llu, \"cycles\": %llu, "
                "\"policy\": \"%s\", \"submit\": \"%s\", \"conns\": %u, \"per_conn\": %u, "
                "\"bg_threads\": %u, \"bg_conns\": %u, \"bg_pipe\": %u, \"bg_mode\": \"%s\", "
                "\"bg_keys\": %u, \"bg_shard\": %d, \"bg_groups\": %zu, \"geometry_shards\": %u, \"tight\": \"%s\", "
                "\"fill\": %u, \"used_memory_after_fill\": %llu, \"dataset_after_fill\": %llu, "
                "\"near_value\": %llu, "
                "\"lift_sets\": %llu, \"lift_ok\": %llu, \"lift_oom\": %llu, \"lift_other\": %llu, "
                "\"tight_sets\": %llu, \"tight_strict_sets\": %llu, \"tight_ok\": %llu, "
                "\"tight_oom\": %llu, \"tight_other\": %llu, \"tight_strict_admitted\": %llu, "
                "\"eviction_checks\": %llu, \"evicted_after_lift\": %llu, "
                "\"bg_replies\": %llu, \"bg_errors\": %llu, \"violations\": %llu, "
                "\"elapsed_s\": %.3f, \"lift_examples\": %s, \"tight_examples\": %s, "
                "\"evict_examples\": %s, \"other_examples\": %s, \"rc\": %d}\n",
                json_escape(o.label).c_str(), o.port,
                static_cast<unsigned long long>(o.toggles), static_cast<unsigned long long>(k.cycles),
                o.policy.c_str(), o.submit.c_str(), o.conns, o.per_conn, o.bg_threads, o.bg_conns,
                o.bg_pipe, o.bg_mode.c_str(), o.bg_keys, o.bg_shard, groups.size(), geometry_shards, o.tight.c_str(), o.fill, used, dataset, near,
                static_cast<unsigned long long>(k.lift_sets), static_cast<unsigned long long>(k.lift_ok),
                static_cast<unsigned long long>(k.lift_oom), static_cast<unsigned long long>(k.lift_other),
                static_cast<unsigned long long>(k.tight_sets),
                static_cast<unsigned long long>(k.tight_strict_sets),
                static_cast<unsigned long long>(k.tight_ok), static_cast<unsigned long long>(k.tight_oom),
                static_cast<unsigned long long>(k.tight_other),
                static_cast<unsigned long long>(k.tight_strict_admitted),
                static_cast<unsigned long long>(k.eviction_checks),
                static_cast<unsigned long long>(k.evicted_after_lift),
                static_cast<unsigned long long>(k.bg_replies), static_cast<unsigned long long>(k.bg_errors),
                static_cast<unsigned long long>(violations), elapsed,
                json_list(k.lift_examples).c_str(), json_list(k.tight_examples).c_str(),
                json_list(k.evict_examples).c_str(), json_list(k.other_examples).c_str(), rc);
    if (rc) return rc;
    if (k.lift_other || k.tight_other || k.bg_errors) return 4;
    return violations ? 1 : 0;
}

}  // namespace

int main(int argc, char** argv) {
    Options o;
    for (int i = 1; i < argc; i++) {
        const std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) { std::fprintf(stderr, "%s needs a value\n", a.c_str()); std::exit(2); }
            return argv[++i];
        };
        if (a == "--port") o.port = static_cast<uint16_t>(std::stoul(next()));
        else if (a == "--toggles") o.toggles = std::stoull(next());
        else if (a == "--policy") o.policy = next();
        else if (a == "--submit") o.submit = next();
        else if (a == "--conns") o.conns = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--per-conn") o.per_conn = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--bg-threads") o.bg_threads = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--bg-conns") o.bg_conns = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--bg-pipe") o.bg_pipe = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--bg-mode") o.bg_mode = next();
        else if (a == "--bg-keys") o.bg_keys = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--bg-shard") o.bg_shard = std::stoi(next());
        else if (a == "--tight") o.tight = next();
        else if (a == "--fill") o.fill = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--value-size") o.value_size = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--rotate") o.rotate = static_cast<uint32_t>(std::stoul(next()));
        else if (a == "--timeout-ms") o.timeout_ms = std::stoi(next());
        else if (a == "--label") o.label = next();
        else { std::fprintf(stderr, "unknown argument %s\n", a.c_str()); return 2; }
    }
    if (!o.port || (o.submit != "single" && o.submit != "pipe") ||
        (o.tight != "one" && o.tight != "near" && o.tight != "alt") || !o.conns || !o.per_conn ||
        !o.rotate || !o.fill || (o.bg_mode != "light" && o.bg_mode != "heavy") || !o.bg_keys) {
        std::fprintf(stderr, "usage: --port P [--toggles N] [--policy noeviction|allkeys-lru] "
                             "[--submit single|pipe] [--tight one|near|alt] ...\n");
        return 2;
    }
    try { return run(o); }
    catch (const std::exception& e) { std::fprintf(stderr, "setup failed: %s\n", e.what()); return 3; }
}
