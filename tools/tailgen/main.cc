#include "config.h"
#include "connection.h"
#include "histogram.h"
#include "outstanding.h"
#include "report.h"

#include <atomic>
#include <condition_variable>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <netdb.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/epoll.h>
#include <sys/resource.h>
#include <thread>

namespace tailgen {
namespace {

constexpr const char* usage = R"(tailgen: smooth open-loop RESP load generator
Usage: tailgen [options]
  --rate N                 total offered commands/s (10000)
  --duration SECONDS       measurement send window (20)
  --warmup SECONDS         preceding unmeasured arrivals (3; 0 disables)
  --threads T              pinned workers (1)
  --conns C                connections PER THREAD (1)
  --cores LIST             e.g. 84-111 or 112,114-127 (process affinity)
  --host HOST --port PORT  target (127.0.0.1:6379)
  --spacing poisson|fixed  arrival process (poisson)
  --seed N                 deterministic schedule/workload seed (1)
  --mix MIX                weighted commands (GET:8,BITCOUNT:2)
                           commands: GET, SET <bytes>, BITCOUNT, PING
  --short-keys PATTERN     'memtier-{1..2000000}' (or numeric key count)
  --long-keys PATTERN      'blocker:memtier-{1..2048}' (or numeric count)
  --max-outstanding N      witness threshold per connection (64; 0 disables)
  --help                  show help without connecting

GET/SET/PING are short; BITCOUNT is long. Existing keys must be populated.
JSON goes to stdout, diagnostics to stderr. Errors exit nonzero without JSON.
See tools/tailgen/README.md for window, drain, and saturation semantics.
)";

struct Address { sockaddr_storage storage{}; socklen_t length; int family, protocol; };
std::vector<Address> resolve(const Config& config) {
    addrinfo hints{}, *raw = nullptr;
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    const int error = getaddrinfo(config.host.c_str(), config.port.c_str(), &hints, &raw);
    if (error) throw std::runtime_error(std::string("getaddrinfo: ") + gai_strerror(error));
    std::unique_ptr<addrinfo, decltype(&freeaddrinfo)> addresses(raw, freeaddrinfo);
    std::vector<Address> out;
    for (const addrinfo* a = raw; a; a = a->ai_next) {
        if (a->ai_addrlen > sizeof(sockaddr_storage)) continue;
        Address address{};
        address.length = a->ai_addrlen;
        address.family = a->ai_family;
        address.protocol = a->ai_protocol;
        std::memcpy(&address.storage, a->ai_addr, a->ai_addrlen);
        out.push_back(address);
    }
    if (out.empty()) throw std::runtime_error("host resolved to no usable TCP addresses");
    return out;
}

File connect_to(const std::vector<Address>& addresses, const std::atomic<bool>& cancelled) {
    int last_error = ECONNREFUSED;
    for (const auto& address : addresses) {
        if (cancelled.load(std::memory_order_relaxed)) throw std::runtime_error("cancelled during connect");
        File fd(socket(address.family, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, address.protocol));
        if (fd.get() < 0) { last_error = errno; continue; }
        int one = 1;
        if (setsockopt(fd.get(), IPPROTO_TCP, TCP_NODELAY, &one, sizeof one))
            throw std::system_error(errno, std::generic_category(), "TCP_NODELAY");
        if (!connect(fd.get(), reinterpret_cast<const sockaddr*>(&address.storage), address.length)) return fd;
        if (errno != EINPROGRESS) { last_error = errno; continue; }
        const uint64_t timeout = now_ns() + 5'000'000'000ULL;
        pollfd event{fd.get(), POLLOUT, 0};
        while (now_ns() < timeout && !cancelled.load(std::memory_order_relaxed)) {
            const int ready = poll(&event, 1, 50);
            if (ready < 0) { if (errno == EINTR) continue; last_error = errno; break; }
            if (!ready) { last_error = ETIMEDOUT; continue; }
            socklen_t length = sizeof last_error;
            if (getsockopt(fd.get(), SOL_SOCKET, SO_ERROR, &last_error, &length)) last_error = errno;
            if (!last_error) return fd;
            break;
        }
    }
    throw std::system_error(last_error, std::generic_category(), "connect");
}

struct Result {
    Histogram short_latency, long_latency, lateness;
    std::vector<Interval> over_intervals;
    uint64_t maximum = 0, pending_at_end = 0, queued_at_end = 0, queued_max = 0;
    uint64_t completed_in_window = 0, omitted_arrivals = 0, send_gap_max = 0;
    double drain_seconds = 0;
    std::string error;
};

struct Start {
    std::mutex mutex;
    std::condition_variable condition;
    size_t ready = 0;
    bool go = false;
    uint64_t time = 0;
    std::atomic<bool> cancelled{false};
};

class Worker {
public:
    Worker(const Config& config, const Workload& workload, size_t index, Result& result, Start& start,
           const std::vector<Address>& addresses)
        : config_(config), workload_(workload), index_(index), result_(result), start_(start),
          epoll_(epoll_create1(EPOLL_CLOEXEC)) {
        if (epoll_.get() < 0) throw std::system_error(errno, std::generic_category(), "epoll_create1");
        cpu_set_t mask;
        CPU_ZERO(&mask);
        CPU_SET(config.core(index), &mask);
        const int error = pthread_setaffinity_np(pthread_self(), sizeof mask, &mask);
        if (error) throw std::system_error(error, std::generic_category(), "pthread_setaffinity_np");
        connections_.reserve(config.conns);
        for (size_t i = 0; i < config.conns; ++i) {
            connections_.emplace_back(connect_to(addresses, start.cancelled));
            watch(i, EPOLL_CTL_ADD);
        }
    }

    void run() {
        uint64_t origin;
        {
            std::unique_lock lock(start_.mutex);
            ++start_.ready;
            start_.condition.notify_all();
            start_.condition.wait(lock, [&] { return start_.go || start_.cancelled.load(); });
            if (start_.cancelled.load()) return;
            origin = start_.time;
        }
        begin_ = origin + config_.warmup_ns();
        end_ = begin_ + config_.duration_ns();
        outstanding_ = std::make_unique<Outstanding>(config_.conns, config_.max_outstanding, begin_, end_);
        Arrivals arrivals(config_.rate, config_.threads, index_, config_.spacing, config_.seed);
        Random choices(config_.seed ^ (0xd1b54a32d192ed03ULL * (index_ + 1)));
        uint64_t deadline = origin + arrivals.next_offset_ns(), previous_send = 0;
        size_t next_connection = 0;
        std::string command;
        command.reserve(256);

        while (deadline < end_) {
            const CommandClass kind = workload_.render(choices, command);
            wait_until(deadline);
            const uint64_t sent = now_ns();
            outstanding_->advance(sent);
            if (sent >= end_) break;
            const bool measured = sent >= begin_;
            Connection& connection = connections_[next_connection];
            const bool was_writable = connection.wants_write();
            outstanding_->add(next_connection, sent);
            connection.submit(command, {sent, kind, measured});
            if (was_writable != connection.wants_write()) watch(next_connection, EPOLL_CTL_MOD);
            result_.queued_max = std::max<uint64_t>(result_.queued_max, connection.queued_bytes());
            if (measured) {
                result_.lateness.record(sent - deadline);
                if (previous_send) result_.send_gap_max = std::max(result_.send_gap_max, sent - previous_send);
            }
            previous_send = sent;
            next_connection = (next_connection + 1) % connections_.size();
            deadline = origin + arrivals.next_offset_ns();
            // Even when behind schedule, give replies one bounded service turn
            // per arrival. There is no refill tick, batching, or outstanding cap.
            service(deadline);
        }
        wait_until(end_);
        outstanding_->advance(now_ns());
        result_.pending_at_end = outstanding_->total();
        for (const auto& connection : connections_) result_.queued_at_end += connection.queued_bytes();
        const uint64_t drain_deadline = end_ + Histogram::max_ns;
        while (outstanding_->total()) {
            if (now_ns() >= drain_deadline)
                throw std::runtime_error("100 s drain timeout; outstanding=" + std::to_string(outstanding_->total()));
            service(drain_deadline, 10); // readiness wakes immediately; no arrivals during drain
        }
        result_.drain_seconds = static_cast<double>(now_ns() - end_) / 1e9;
        result_.maximum = outstanding_->maximum();
        result_.over_intervals = outstanding_->finish();
        // Count truncation only AFTER draining, so RNG replay cannot delay replies.
        while (deadline < end_) {
            if (deadline >= begin_) ++result_.omitted_arrivals;
            deadline = origin + arrivals.next_offset_ns();
        }
    }

private:
    void check_cancelled() const {
        if (start_.cancelled.load(std::memory_order_relaxed)) throw std::runtime_error("cancelled after another worker failed");
    }
    void wait_until(uint64_t deadline) {
        uint64_t now = now_ns();
        while (now < deadline) {
            check_cancelled();
            // Slice only long idle waits to make cancellation responsive. Each
            // slice still sleeps to its absolute deadline minus the spin margin.
            const uint64_t next = std::min(deadline, now + uint64_t{50'000'000});
            now = pace_until(next, [&](uint64_t until) { return service(until); });
        }
        check_cancelled();
    }
    void watch(size_t index, int operation) {
        epoll_event event{};
        event.events = EPOLLIN | EPOLLRDHUP | (connections_[index].wants_write() ? uint32_t{EPOLLOUT} : 0);
        event.data.u32 = static_cast<uint32_t>(index);
        if (epoll_ctl(epoll_.get(), operation, connections_[index].fd(), &event))
            throw std::system_error(errno, std::generic_category(), "epoll_ctl");
    }
    bool service(uint64_t deadline, int timeout_ms = 0) {
        check_cancelled();
        outstanding_->advance(now_ns());
        if (event_index_ == event_count_) {
            event_index_ = 0;
            event_count_ = epoll_wait(epoll_.get(), events_, 32, timeout_ms);
            if (event_count_ < 0) {
                event_count_ = 0;
                if (errno != EINTR) throw std::system_error(errno, std::generic_category(), "epoll_wait");
                return false;
            }
        }
        int serviced = 0;
        while (event_index_ < event_count_) {
            if (serviced++ && now_ns() >= deadline) break;
            // Keep the unprocessed suffix across calls. Discarding it could
            // repeatedly service only the first ready connection under load.
            const epoll_event event = events_[event_index_++];
            const size_t index = event.data.u32;
            Connection& connection = connections_[index];
            const uint32_t flags = event.events;
            if (flags & (EPOLLIN | EPOLLHUP | EPOLLRDHUP | EPOLLERR)) {
                connection.read_ready([&](Request request, uint64_t completed, bool error, std::string_view message) {
                    outstanding_->complete(index, completed);
                    if (error) throw std::runtime_error("server error reply: " + std::string(message));
                    if (completed >= begin_ && completed < end_) ++result_.completed_in_window;
                    if (request.measured)
                        (request.kind == CommandClass::short_op ? result_.short_latency : result_.long_latency)
                            .record(completed - request.sent_ns);
                });
            }
            if (flags & EPOLLOUT) {
                connection.write_ready();
                if (!connection.wants_write()) watch(index, EPOLL_CTL_MOD);
            }
        }
        return outstanding_->total() == 0;
    }
    const Config& config_;
    const Workload& workload_;
    size_t index_;
    Result& result_;
    Start& start_;
    File epoll_;
    std::vector<Connection> connections_;
    std::unique_ptr<Outstanding> outstanding_;
    epoll_event events_[32]{};
    int event_index_ = 0, event_count_ = 0;
    uint64_t begin_ = 0, end_ = 0;
};

void human_histogram(const char* name, const Histogram& histogram) {
    std::cerr << name << ": count=" << histogram.count() << " mean=" << histogram.mean_ms()
              << " p50=" << histogram.percentile_ms(50000) << " p90=" << histogram.percentile_ms(90000)
              << " p99=" << histogram.percentile_ms(99000) << " p99.9=" << histogram.percentile_ms(99900)
              << " p99.99=" << histogram.percentile_ms(99990) << " max=" << histogram.max_ms() << " ms\n";
}
void report(const Config& config, const std::vector<std::unique_ptr<Result>>& results) {
    Histogram short_latency, long_latency, lateness;
    std::vector<Interval> intervals;
    uint64_t maximum = 0, pending = 0, queued = 0, queued_max = 0, completions = 0, omitted = 0, gap = 0;
    double drain_seconds = 0;
    for (const auto& result : results) {
        short_latency.merge(result->short_latency);
        long_latency.merge(result->long_latency);
        lateness.merge(result->lateness);
        intervals.insert(intervals.end(), result->over_intervals.begin(), result->over_intervals.end());
        maximum = std::max(maximum, result->maximum);
        pending += result->pending_at_end;
        queued += result->queued_at_end;
        queued_max = std::max(queued_max, result->queued_max);
        completions += result->completed_in_window;
        omitted += result->omitted_arrivals;
        gap = std::max(gap, result->send_gap_max);
        drain_seconds = std::max(drain_seconds, result->drain_seconds);
    }
    Histogram combined = short_latency;
    combined.merge(long_latency);
    const double window = static_cast<double>(config.duration_ns()) / 1e9;
    const double rate = static_cast<double>(combined.count()) / window;
    const double fraction = static_cast<double>(union_ns(std::move(intervals))) / config.duration_ns();
    std::cerr << std::fixed << std::setprecision(6)
              << "window=" << window << " s, warmup=" << config.warmup << " s (excluded), drain=" << drain_seconds << " s\n"
              << "achieved cohort rate=" << rate << " ops/s, offered=" << config.rate
              << ", window reply rate=" << static_cast<double>(completions) / window << " ops/s\n";
    human_histogram("short", short_latency);
    human_histogram("long", long_latency);
    human_histogram("combined", combined);
    std::cerr << "outstanding_max=" << maximum << " per connection, any-connection over " << config.max_outstanding
              << " fraction=" << fraction << ", pending at window end=" << pending << '\n'
              << "unsent bytes at window end=" << queued << ", max queued bytes per connection=" << queued_max << '\n'
              << "pacing lag: mean=" << lateness.mean_ms() * 1000 << " us, p99.9=" << lateness.percentile_ms(99900) * 1000
              << " us, max=" << lateness.max_ms() * 1000 << " us; max worker send gap=" << static_cast<double>(gap) / 1000
              << " us; scheduled arrivals omitted at window end=" << omitted << '\n';
    if (!config.max_outstanding) std::cerr << "saturation time witness disabled (--max-outstanding 0)\n";
    if (omitted || lateness.max_ms() > 2 || queued_max)
        std::cerr << "generator pressure observed: inspect pacing lag, omitted arrivals and queued bytes before judging server tails\n";

    write_json(std::cout, short_latency, long_latency, config.duration_ns(), maximum, fraction);
}

int run(int argc, char** argv) {
    const Config config = parse_config(argc, argv);
    if (config.help) { std::cerr << usage; return 0; }
    rlimit files{};
    if (getrlimit(RLIMIT_NOFILE, &files)) throw std::system_error(errno, std::generic_category(), "getrlimit");
    if (config.threads * (config.conns + 1) + 16 > files.rlim_cur)
        throw std::invalid_argument("RLIMIT_NOFILE is too small for threads * conns (raise ulimit -n)");
    const Workload workload(config.mix, config.short_keys, config.long_keys);
    const auto addresses = resolve(config);
    std::cerr << "tailgen " << config.host << ':' << config.port << ", threads=" << config.threads
              << ", conns/thread=" << config.conns << ", total conns=" << config.threads * config.conns
              << ", spacing=" << (config.spacing == Spacing::poisson ? "poisson" : "fixed")
              << ", seed=" << config.seed << ", mix=" << config.mix << "\nworker cores:";
    for (size_t i = 0; i < config.threads; ++i) std::cerr << ' ' << config.core(i);
    std::cerr << '\n';
    Start start;
    std::vector<std::unique_ptr<Result>> results;
    for (size_t i = 0; i < config.threads; ++i) results.push_back(std::make_unique<Result>());
    std::vector<std::thread> threads;
    threads.reserve(config.threads);
    try {
        for (size_t i = 0; i < config.threads; ++i) threads.emplace_back([&, i] {
            try { Worker(config, workload, i, *results[i], start, addresses).run(); }
            catch (const std::exception& error) {
                results[i]->error = error.what();
                std::lock_guard lock(start.mutex);
                start.cancelled.store(true);
                start.condition.notify_all();
            }
        });
        std::unique_lock lock(start.mutex);
        start.condition.wait(lock, [&] { return start.ready == config.threads || start.cancelled.load(); });
        start.time = now_ns() + 10'000'000; // all connections established before the common origin
        start.go = true;
        start.condition.notify_all();
    } catch (...) {
        { std::lock_guard lock(start.mutex); start.cancelled.store(true); start.condition.notify_all(); }
        for (auto& thread : threads) thread.join();
        throw;
    }
    for (auto& thread : threads) thread.join();
    if (start.cancelled.load()) {
        for (size_t i = 0; i < results.size(); ++i)
            if (!results[i]->error.empty()) std::cerr << "worker " << i << ": " << results[i]->error << '\n';
        return 1;
    }
    report(config, results);
    return 0;
}
} // namespace
} // namespace tailgen

int main(int argc, char** argv) {
    try { return tailgen::run(argc, argv); }
    catch (const std::exception& error) { std::cerr << "tailgen: " << error.what() << '\n'; return 1; }
}
