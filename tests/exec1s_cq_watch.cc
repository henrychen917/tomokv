// Correctness-only LD_PRELOAD observer. Never use this in a rate arm.
// Sample every liburing submission/wait boundary and teardown, on its issuer.
// With DEFER_TASKRUN and one CQ consumer, retained overflow cannot be flushed
// after a userspace drain without passing another observed enter boundary.
#include <liburing.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <cstdio>
#include <cstdlib>
#include <sys/syscall.h>
#include <unistd.h>

namespace {
struct Row {
    io_uring* ring = nullptr;
    int fd = -1;
    unsigned flags = 0;
    unsigned long long samples = 0, overflow_samples = 0;
    unsigned dropped = 0;
};
struct Observations {
    // The coordinator tears down every worker's rings after joining them.
    Row rows[256];
    unsigned used = 0;
    ~Observations() {
        if (!used) return;
        // Main-thread ring teardown can outlive the final shutdown_report.
        // Preserve that production log contract: observer data has its own
        // per-process/per-thread file, never a trailing stderr record.
        const char* directory = std::getenv("EXEC1S_CQ_LOG_DIR");
        if (!directory || !*directory) std::abort();
        char path[4096];
        const int length = std::snprintf(path, sizeof(path), "%s/%ld-%ld.log", directory,
                                        long(::getpid()), long(::syscall(SYS_gettid)));
        if (length <= 0 || length >= int(sizeof(path))) std::abort();
        const int out = ::open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
        if (out < 0) std::abort();
        for (unsigned i=0;i<used;++i) {
            const auto& r=rows[i];char line[256];
            const int n=std::snprintf(line,sizeof(line),
                "EXEC1S_CQ {\"fd\":%d,\"deferred\":%u,\"taskrun_flag\":%u,"
                "\"samples\":%llu,\"overflow_samples\":%llu,\"dropped\":%u}\n",
                r.fd,!!(r.flags & IORING_SETUP_DEFER_TASKRUN),
                !!(r.flags & IORING_SETUP_TASKRUN_FLAG),r.samples,r.overflow_samples,r.dropped);
            if(n<=0 || n>=int(sizeof(line)) || ::write(out,line,n)!=n) std::abort();
        }
        if (::close(out)) std::abort();
    }
};
thread_local Observations observations;
void observe(io_uring* ring) {
    unsigned slot=0;
    while(slot<observations.used && (observations.rows[slot].ring!=ring ||
          observations.rows[slot].fd!=ring->ring_fd))++slot;
    if(slot==observations.used) {
        if(slot==256) std::abort();
        ++observations.used;
        observations.rows[slot].ring=ring;
        observations.rows[slot].fd=ring->ring_fd;
        observations.rows[slot].flags=ring->flags;
    }
    auto& row=observations.rows[slot];++row.samples;
    row.overflow_samples+=!!(IO_URING_READ_ONCE(*ring->sq.kflags) & IORING_SQ_CQ_OVERFLOW);
    const unsigned dropped=IO_URING_READ_ONCE(*ring->cq.koverflow);
    if(dropped>row.dropped)row.dropped=dropped;
}
template<class Function> Function next(const char* name) {
    auto fn=reinterpret_cast<Function>(dlsym(RTLD_NEXT,name));
    if(!fn)std::abort();
    return fn;
}
}
extern "C" int io_uring_submit(io_uring* ring) {
    static auto fn=next<decltype(&io_uring_submit)>("io_uring_submit");
    observe(ring);const int result=fn(ring);observe(ring);return result;
}
extern "C" int io_uring_submit_and_get_events(io_uring* ring) {
    static auto fn=next<decltype(&io_uring_submit_and_get_events)>("io_uring_submit_and_get_events");
    observe(ring);const int result=fn(ring);observe(ring);return result;
}
extern "C" int io_uring_submit_and_wait_timeout(io_uring* ring,io_uring_cqe** cqe,
        unsigned count,__kernel_timespec* time,sigset_t* mask) {
    static auto fn=next<decltype(&io_uring_submit_and_wait_timeout)>("io_uring_submit_and_wait_timeout");
    observe(ring);const int result=fn(ring,cqe,count,time,mask);observe(ring);return result;
}
extern "C" void io_uring_queue_exit(io_uring* ring) {
    static auto fn=next<decltype(&io_uring_queue_exit)>("io_uring_queue_exit");
    observe(ring);fn(ring);
}
