// Serverless cost of the exact production helper, using a public-only header copy.
// No Server::init, ring init, socket, command handler, or load generator runs.
#include "clock-access.h"
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <vector>

struct Counters {
    int cycles, instructions;
    Counters() {
        perf_event_attr a{};
        a.type=PERF_TYPE_HARDWARE; a.size=sizeof(a); a.disabled=1;
        a.exclude_kernel=1; a.exclude_hv=1;
        a.config=PERF_COUNT_HW_CPU_CYCLES;
        cycles=syscall(SYS_perf_event_open,&a,0,-1,-1,0);
        a.config=PERF_COUNT_HW_INSTRUCTIONS;
        instructions=syscall(SYS_perf_event_open,&a,0,-1,cycles,0);
        if (cycles<0 || instructions<0) { perror("perf_event_open"); std::exit(1); }
    }
    ~Counters() { close(cycles); close(instructions); }
    void start() {
        ioctl(cycles,PERF_EVENT_IOC_RESET,PERF_IOC_FLAG_GROUP);
        ioctl(cycles,PERF_EVENT_IOC_ENABLE,PERF_IOC_FLAG_GROUP);
    }
    std::pair<double,double> stop() {
        ioctl(cycles,PERF_EVENT_IOC_DISABLE,PERF_IOC_FLAG_GROUP);
        uint64_t c=0,i=0;
        if (read(cycles,&c,8)!=8 || read(instructions,&i,8)!=8) std::abort();
        return {double(c),double(i)};
    }
};
template<bool Fused, bool Refresh>
__attribute__((noinline)) void loop(tomo::ExLoopT<Fused>& ex, unsigned batches) {
    for (unsigned b=0;b<batches;++b) {
        if constexpr (Refresh) ex.refresh_command_clock();
        asm volatile("" : "+m"(ex.cached_now_ms_) : : "memory");
    }
}
double median(std::vector<double> values) {
    std::sort(values.begin(),values.end()); return values[values.size()/2];
}
template<bool Fused> void measure(Counters& counter, bool lru, unsigned batch) {
    tomo::ExLoopT<Fused> ex;
    ex.maxmemory_enabled_=lru;
    constexpr unsigned n=1000000;
    loop<Fused,true>(ex,10000);
    std::vector<double> cycles,instructions;
    for (unsigned rep=0;rep<21;++rep) {
        std::pair<double,double> pre,post;
        for (unsigned arm=0;arm<2;++arm) {
            const bool refresh=(arm^(rep&1))!=0;
            counter.start();
            if (refresh) loop<Fused,true>(ex,n); else loop<Fused,false>(ex,n);
            auto value=counter.stop();
            if (refresh) post=value; else pre=value;
        }
        cycles.push_back((post.first-pre.first)/n);
        instructions.push_back((post.second-pre.second)/n);
    }
    if(ex.cached_now_ms_<=0) std::abort();
    if(lru && ex.cached_lru_clock_!=((uint64_t(ex.cached_now_ms_/1000)>>tomo::kLruClockShift)&0x1f)) std::abort();
    printf("{\"mode\":\"%s\",\"batch\":%u,\"maxmemory\":%u,\"batches_per_arm\":%u,\"pairs\":21,"
           "\"cycles_per_batch\":%.4f,\"instructions_per_batch\":%.4f,"
           "\"cycles_per_op\":%.4f,\"instructions_per_op\":%.4f,\"cycle_samples\":[",
           Fused?"1s":"2s",batch,lru,n,median(cycles),median(instructions),median(cycles)/batch,median(instructions)/batch);
    for(unsigned i=0;i<cycles.size();++i) printf("%s%.4f",i?",":"",cycles[i]);
    puts("]}");
}
int main() {
    Counters counter;
    for(bool lru : {false,true}) for(unsigned batch : {1u,32u}) {
        measure<false>(counter,lru,batch); measure<true>(counter,lru,batch);
    }
}
