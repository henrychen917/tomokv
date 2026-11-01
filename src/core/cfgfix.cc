// Configuration of process services. Ordinary commands never enter this file.
#include "cfgfix.h"
#include "config.h"
#include "server.h"

#include <atomic>
#include <fcntl.h>
#include <ctime>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <csignal>
#include <syslog.h>
#include <unistd.h>

namespace tomo {
namespace {
std::atomic<int32_t> load_delay{0};
std::atomic<const Server*> control_server{nullptr};
std::atomic<int> verbosity{2};
struct ExecutorControl { Server* server = nullptr; void* loop = nullptr; bool (*action)(void*, int) = nullptr; };
ExecutorControl executors[kMaxThreads];
struct LogState {
    int fd = -1;
    bool use_syslog = false;
    std::string ident;
    std::string pidfile;
    std::string notify_socket;
    FILE* saved_out = nullptr;
    FILE* saved_err = nullptr;
    FILE* out = nullptr;
    FILE* err = nullptr;
    ~LogState() {
        if (out) { std::fflush(out); stdout = saved_out; std::fclose(out); }
        if (err) { std::fflush(err); stderr = saved_err; std::fclose(err); }
        if (fd >= 0) ::close(fd);
        if (use_syslog) ::closelog();
        if (!pidfile.empty()) ::unlink(pidfile.c_str());
    }
};
LogState log_state;

bool notify_supervisor(const char* message) {
    if (log_state.notify_socket.empty()) return false;
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    const auto size = log_state.notify_socket.size();
    if (size >= sizeof(address.sun_path)) return false;
    std::memcpy(address.sun_path, log_state.notify_socket.c_str(), size + 1);
    if (address.sun_path[0] == '@') address.sun_path[0] = 0;
    const int fd = ::socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return false;
    const bool okay = ::sendto(fd, message, std::strlen(message), MSG_NOSIGNAL,
        reinterpret_cast<sockaddr*>(&address), offsetof(sockaddr_un, sun_path) + size + 1) >= 0;
    ::close(fd);
    return okay;
}

ssize_t write_log(void* cookie, const char* bytes, size_t size) {
    const bool error_stream = cookie != nullptr;
    // Existing diagnostics have no per-call severity metadata: stderr is
    // warning, stdout is notice. Keep their payloads unchanged.
    const int severity = error_stream ? 3 : 2;
    if (severity < verbosity.load(std::memory_order_relaxed)) return size;
    int fd = log_state.fd;
    if (fd < 0) fd = error_stream ? STDERR_FILENO : STDOUT_FILENO;
    size_t done = 0;
    while (done < size) {
        const auto n = ::write(fd, bytes + done, size - done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return done ? static_cast<ssize_t>(done) : -1;
        done += n;
    }
    if (log_state.use_syslog)
        ::syslog(error_stream ? LOG_WARNING : LOG_NOTICE, "%.*s", static_cast<int>(size), bytes);
    return size;
}
}

void cfgfix_register_executor(Server* server, uint32_t tid, void* loop, bool (*action)(void*, int)) {
    executors[tid] = {server, loop, action};
}
bool cfgfix_executor_control(Server& server, uint32_t tid, int action) {
    const auto& entry = executors[tid];
    return entry.server == &server && entry.action && entry.action(entry.loop, action);
}

bool cfgfix_control_busy(const Server& server) {
    return control_server.load(std::memory_order_acquire) == &server;
}
bool cfgfix_control_begin(Server& server) {
    std::lock_guard lock(server.shape_transition_mutex());
    if (server.flip_stage() != FlipStage::Idle || server.lb_stage() != LbStage::Idle ||
        server.snapshot().in_progress() ||
        server.signal_shutdown_pending() || server.shutting_down().load(std::memory_order_relaxed)) return false;
    const Server* empty = nullptr;
    return control_server.compare_exchange_strong(empty, &server, std::memory_order_acq_rel);
}
void cfgfix_control_end(Server& server) {
    const Server* expected = &server;
    if (!control_server.compare_exchange_strong(expected, nullptr)) std::abort();
}

void cfgfix_loglevel(const char* value) {
    static constexpr const char* names[] = {"debug", "verbose", "notice", "warning", "nothing"};
    for (unsigned i = 0; i < std::size(names); ++i)
        if (!std::strcmp(value, names[i])) { verbosity.store(i, std::memory_order_relaxed); return; }
    std::abort();
}

void cfgfix_key_load_delay(int32_t value) { load_delay.store(value, std::memory_order_relaxed); }
void cfgfix_delay_loaded_key() {
    const int32_t delay = load_delay.load(std::memory_order_relaxed);
    if (delay > 0) {
        timespec left{delay / 1000000, (delay % 1000000) * 1000L};
        while (::nanosleep(&left, &left) && errno == EINTR) {}
    }
}

bool cfgfix_process_boot(const Config& cfg) {
    auto value = [&](const char* name) {
        return cfg_process_value(cfg, cfg_process_find(Slice(name, std::strlen(name))));
    };
    std::string supervised = value("supervised");
    if (supervised == "auto") supervised = std::getenv("UPSTART_JOB") ? "upstart" :
        std::getenv("NOTIFY_SOCKET") ? "systemd" : "no";
    bool supervision_active = false;
    if (supervised == "upstart" && std::getenv("UPSTART_JOB")) {
        ::raise(SIGSTOP);
        ::unsetenv("UPSTART_JOB");
        supervision_active = true;
    } else if (supervised == "systemd" && std::getenv("NOTIFY_SOCKET")) {
        log_state.notify_socket = std::getenv("NOTIFY_SOCKET");
        supervision_active = notify_supervisor("STATUS=TomoKV is loading...\n");
    }
    const bool daemon = !std::strcmp(value("daemonize"), "yes") && !supervision_active;
    const char* logfile = value("logfile");
    if (*logfile) {
        log_state.fd = ::open(logfile, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
        if (log_state.fd < 0) { std::perror("Can't open the log file"); return false; }
    }
    if (daemon) {
        std::fflush(nullptr);
        const pid_t child = ::fork();
        if (child < 0) { std::perror("fork"); return false; }
        if (child > 0) ::_exit(0);
        if (::setsid() < 0) return false;
        const int null = ::open("/dev/null", O_RDWR);
        if (null < 0) return false;
        for (int fd = 0; fd < 3; ++fd)
            if (::dup2(null, fd) < 0) { ::close(null); return false; }
        if (null > 2) ::close(null);
    }
    log_state.pidfile = value("pidfile");
    if (daemon && log_state.pidfile.empty()) log_state.pidfile = "/var/run/redis.pid";
    if (!log_state.pidfile.empty()) {
        // Redis treats failure to create the pidfile as non-fatal.
        if (FILE* f = std::fopen(log_state.pidfile.c_str(), "w")) {
            std::fprintf(f, "%ld\n", static_cast<long>(::getpid())); std::fclose(f);
        } else log_state.pidfile.clear();
    }
    log_state.use_syslog = !std::strcmp(value("syslog-enabled"), "yes");
    if (log_state.use_syslog) {
        log_state.ident = value("syslog-ident");
        const char* facility = value("syslog-facility");
        const int selected = !std::strcmp(facility, "user") ? LOG_USER :
            LOG_LOCAL0 + (facility[5] - '0') * 8;
        ::openlog(log_state.ident.c_str(), LOG_PID | LOG_NDELAY, selected);
    }
    cfgfix_loglevel(value("loglevel"));
    cfgfix_key_load_delay(std::strtol(value("key-load-delay"), nullptr, 10));
    cookie_io_functions_t hooks{};
    hooks.write = write_log;
    log_state.saved_out = stdout; log_state.saved_err = stderr;
    log_state.out = ::fopencookie(nullptr, "w", hooks);
    log_state.err = ::fopencookie(&log_state, "w", hooks);
    if (!log_state.out || !log_state.err) return false;
    std::setvbuf(log_state.out, nullptr, _IOLBF, 0);
    std::setvbuf(log_state.err, nullptr, _IONBF, 0);
    std::fflush(stdout); std::fflush(stderr);
    stdout = log_state.out; stderr = log_state.err;
    return true;
}
void cfgfix_process_ready() {
    (void)notify_supervisor("READY=1\nSTATUS=Ready to accept connections\n");
}
}
