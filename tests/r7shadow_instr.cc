// Serverless instruction accounting for production dispatch/queue templates.
// No clocks, throughput measurement, sockets, worker threads or server boot.
// Compile this SAME file against PRE and POST headers; fixture setup is outside
// every counted interval. Report user instructions per submitted ordinary task.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "src/core/reorder.h"

namespace tomo { void multi_session_destroy(MultiSession* p) { if (p) std::abort(); } }
namespace {
using namespace tomo;
using namespace tomo::r7;
void require(bool value) { if (!value) std::abort(); }
void unused(Shard&, Op&) { std::abort(); }
constexpr CommandSpec spec(const char* name, CommandLengthClass length) {
    CommandSpec s(name, 2, 2, CmdFlags::Readonly, unused, 1, 1, 1, unused);
    s.length_class = static_cast<uint8_t>(length);
    return s;
}
constexpr auto short_op = spec("GET", CommandLengthClass::Point);
constexpr auto long_op = spec("BITCOUNT", CommandLengthClass::Long);
struct Pipe {
    Client client{-1};
    ShadowDispatch dispatch{client};
    Task add(bool is_long, uint32_t label) {
        auto& rob = client.rob();
        auto* op = rob.acquire();
        require(op);
        op->spec = is_long ? &long_op : &short_op;
        op->state.store(OpState::Issued, std::memory_order_release);
        Task task(&client, rob.dispatch_id(), -1, nullptr);
        task.enqueue_us_low = label;
        dispatch.stamp(task);
        rob.publish();
        return task;
    }
};
struct Instructions {
    int fd;
    Instructions() {
        perf_event_attr attr{};
        attr.type = PERF_TYPE_HARDWARE;
        attr.size = sizeof(attr);
        attr.config = PERF_COUNT_HW_INSTRUCTIONS;
        attr.disabled = 1;
        attr.exclude_kernel = attr.exclude_hv = 1;
        attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
        fd = syscall(SYS_perf_event_open, &attr, 0, -1, -1, 0);
        if (fd < 0) { std::perror("instruction counter (no substitute or guessed count)"); std::exit(1); }
    }
    ~Instructions() { close(fd); }
    template<class Fn> void count(const char* name, uint64_t ops, Fn fn) {
        require(ioctl(fd, PERF_EVENT_IOC_RESET, 0) == 0);
        require(ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) == 0);
        fn();
        require(ioctl(fd, PERF_EVENT_IOC_DISABLE, 0) == 0);
        struct { uint64_t instructions, enabled, running; } value{};
        require(read(fd, &value, sizeof(value)) == sizeof(value));
        require(value.instructions && value.running == value.enabled); // no scaling/multiplexing
        std::printf("%s,%llu,%llu,%.6f\n", name, (unsigned long long)ops,
                    (unsigned long long)value.instructions, double(value.instructions) / ops);
    }
};
volatile uint64_t sink;
constexpr uint32_t Repeats = 256;
__attribute__((noinline)) uint64_t dispatch_pass(Pipe& pipe, const Task* source) {
    // Half a live ROB predates this parse pass, half is the new 32-command wave.
    // Source metadata is prepared before counting; stamp() sees real ROB slots.
    ShadowDispatch dispatch(pipe.client, kRobWindow / 2);
    uint64_t result = 0;
    for (uint32_t i = 0; i < kRobWindow / 2; ++i) {
        Task task = source[i];
        dispatch.stamp(task);
        result += static_cast<uint32_t>(task.shard);
    }
    return result;
}
void dispatch_cost(Instructions& counter, bool preceding_long) {
    Pipe pipe;
    std::array<Task, kRobWindow / 2> tasks;
    for (uint32_t i = 0; i < kRobWindow; ++i) {
        auto task = pipe.add(preceding_long && i == kRobWindow / 2 - 1, i);
        if (i >= kRobWindow / 2) { task.shard = -1; tasks[i - kRobWindow / 2] = task; }
    }
    counter.count(preceding_long ? "dispatch_after_long" : "dispatch_uniform_short",
                  Repeats * tasks.size(), [&] {
        uint64_t result = 0;
        for (uint32_t r = 0; r < Repeats; ++r) result += dispatch_pass(pipe, tasks.data());
        sink = result;
    });
}
template<size_t B>
__attribute__((noinline)) void queue_pass(const std::vector<Task>& tasks) {
    ShadowReorderQueues<B> q;
    uint64_t count = 0, checksum = 0;
    auto emit = [&](const Task* selected, uint32_t n, ReorderResult) {
        count += n;
        for (uint32_t i = 0; i < n; ++i) checksum += selected[i].enqueue_us_low;
    };
    for (size_t i = 0; i < tasks.size(); i += B) q.submit(tasks.data() + i, B, emit);
    q.finish(emit);
    require(count == tasks.size() && checksum == count * (count - 1) / 2);
    sink = checksum;
}
template<size_t B>
void queue_cost(Instructions& counter, uint32_t batches, const char* name) {
    std::vector<std::unique_ptr<Pipe>> pipes;
    std::vector<Task> tasks;
    for (uint32_t i = 0; i < batches * B; ++i) {
        pipes.push_back(std::make_unique<Pipe>());
        if (i % B == 0) pipes.back()->add(true, UINT32_MAX); // unfinished foreign Long
        tasks.push_back(pipes.back()->add(i % B == 1, i));
    }
    counter.count(name, Repeats * tasks.size(), [&] {
        for (uint32_t r = 0; r < Repeats; ++r) queue_pass<B>(tasks);
    });
}
} // namespace
int main() {
    Instructions counter;
    std::puts("case,ops,instructions,instr_per_op");
    dispatch_cost(counter, false);
    dispatch_cost(counter, true);
    queue_cost<kGenthreadExBatchOps>(counter, 2, "queue_2_gathers_B32");
    queue_cost<kGenthreadExBatchOps>(counter, 48, "queue_48_gathers_B32");
    queue_cost<kGenthreadPipelineExBatchOps>(counter, 48, "queue_48_gathers_B128");
}
