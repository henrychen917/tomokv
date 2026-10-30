// The production group counter must never write the read-local discriminator.
// TSAN is necessary: the old overlapping write preserves the byte's value.
#include "src/store/atomic_mvcc.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <thread>
#include <fcntl.h>
#include <sys/wait.h>
#include <unistd.h>

static void require(bool value, const char* reason) {
    if (!value) { std::fprintf(stderr,"FAIL exec1s word: %s\n",reason); std::exit(1); }
}
__attribute__((noipa)) static bool foreign_shape(const tomo::AtomicPendingState& state) {
    return state.read_local_extended;
}
__attribute__((noipa)) static void publish(tomo::AtomicPendingState& state, bool broken) {
    if (!broken) { state.finish_group_install(); return; }
    // Exact old overlap, retained only in this throwaway control process.
    uint32_t word;
    auto* at = reinterpret_cast<char*>(&state) + offsetof(tomo::AtomicPendingState,read_local_extended);
    std::memcpy(&word,at,sizeof(word)); word += 0xff00u;
    std::memcpy(at,&word,sizeof(word));
}
static bool exercise_attempt(bool broken) {
    tomo::AtomicPendingState state{};
    reinterpret_cast<unsigned char*>(&state)[offsetof(tomo::AtomicPendingState,group_records)+1]=0;
    state.read_local_extended=true;
    state.cleanup_fast=0x123456789abcdef0ull;
    std::atomic<bool> ready{false},start{false},done{false};
    std::atomic<unsigned> observed{0};
    std::thread reader([&] {
        ready.store(true,std::memory_order_release);
        while(!start.load(std::memory_order_acquire)) std::this_thread::yield();
        while(!done.load(std::memory_order_relaxed)) {
            require(foreign_shape(state),"immutable reader discriminator changed");
            observed.fetch_add(1,std::memory_order_relaxed);
        }
    });
    while(!ready.load(std::memory_order_acquire)) std::this_thread::yield();
    start.store(true,std::memory_order_release);
    for(unsigned n=0;n<100000;++n) {
        state.group_installing=true;
        publish(state,broken);
        if (!(n&255u)) std::this_thread::yield();
    }
    done.store(true,std::memory_order_relaxed);
    reader.join();
    require(state.group_records==static_cast<uint8_t>(100000),"group count wraps modulo 256");
    require(!state.group_installing && state.read_local_extended,"install flag and immutable shape");
    require(state.cleanup_fast==0x123456789abcdef0ull,"adjacent owner counter unchanged");
    return observed.load()>0;
}
static void exercise(bool broken) {
    for(unsigned attempt=0;attempt<3;++attempt) if(exercise_attempt(broken)) return;
    require(false,"concurrent reader window never opened on three fresh states");
}
int main(int argc,char** argv) {
    require(argc==3 && std::string(argv[1])=="word","word and negative-control log path");
    // Fork before creating threads. The child inherits the working TSAN mapping;
    // its intentional report stays separate from the passing production leg.
    const auto child=fork(); require(child>=0,"control fork");
    if (!child) {
        const int fd=open(argv[2],O_WRONLY|O_CREAT|O_TRUNC,0600);
        require(fd>=0 && dup2(fd,STDERR_FILENO)>=0,"control log"); close(fd);
        exercise(true); _exit(0);
    }
    int status=0; require(waitpid(child,&status,0)==child,"control joined");
    std::ifstream input(argv[2]);
    const std::string report((std::istreambuf_iterator<char>(input)),{});
    require(WIFEXITED(status) && WEXITSTATUS(status)==66 &&
            report.find("ThreadSanitizer: data race")!=std::string::npos,
            "old wide update must fail with a data-race report");
    exercise(false);
    std::puts("PASS exec1s word (concurrent reader, byte wrap, wide-write control)");
}
