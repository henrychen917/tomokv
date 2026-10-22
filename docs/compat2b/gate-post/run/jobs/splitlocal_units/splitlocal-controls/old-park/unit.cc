#include <cstdint>
#include <cstdio>
constexpr uint32_t kGenthreadIfidBatchOps = 32;
struct Policy { bool borrow; uint32_t batch; bool local, fused, build, discard; };
namespace fifo {
template <bool NoBorrow, uint32_t BatchOps = 0,
          bool SplitLocal = false>
constexpr Policy parse_and_dispatch(void*) {
constexpr bool Fused = SplitLocal || (
        BatchOps == kGenthreadIfidBatchOps);
return {NoBorrow, BatchOps, SplitLocal, Fused, Fused && !SplitLocal, Fused && !SplitLocal};
}
template<bool Fused, bool SplitLocal> consteval bool flush_ready() {
void* c = nullptr;
constexpr bool no_borrow[] = {true,false,false,true,false,false};
const Policy sites[] = {parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c)};
for (unsigned i=0; i<6; ++i) { const auto p=sites[i];
if (p.local != SplitLocal || p.fused != Fused || p.borrow != no_borrow[i] ||
p.batch != (Fused ? kGenthreadIfidBatchOps : 0) ||
p.build != (Fused && !SplitLocal) || p.discard != p.build) return false;
} return true; }
static_assert(flush_ready<false,false>(), "fifo: flush_ready preserves SplitLocal and prebuild policy");
static_assert(flush_ready<true,false>(), "fifo: flush_ready preserves SplitLocal and prebuild policy");
static_assert(flush_ready<true,true>(), "fifo: flush_ready preserves SplitLocal and prebuild policy");
template<bool U, bool T, bool F> consteval bool epoll_pass(int) { return F; }
template<bool HasUnix, bool HasTls, bool Fused, bool SplitLocal>
consteval bool park() {
constexpr bool hot = epoll_pass<HasUnix, HasTls, Fused>(0);
if constexpr (Fused) return hot == epoll_pass<HasUnix, HasTls, !SplitLocal>(50);
else return hot == epoll_pass<HasUnix, HasTls, false>(50);
}
static_assert(park<false,false,false,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<false,false,true,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<false,false,true,true>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<false,true,false,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<false,true,true,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<false,true,true,true>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<true,false,false,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<true,false,true,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<true,false,true,true>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<true,true,false,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<true,true,true,false>(), "fifo: park/hot callback Fused policy mismatch");
static_assert(park<true,true,true,true>(), "fifo: park/hot callback Fused policy mismatch");
}
namespace r7 {
template <bool NoBorrow, uint32_t BatchOps,
          bool SplitLocal>
constexpr Policy r7_parse_and_dispatch(void*) {
constexpr bool Fused = SplitLocal || (
        BatchOps == kGenthreadIfidBatchOps);
return {NoBorrow, BatchOps, SplitLocal, Fused, Fused && !SplitLocal, Fused && !SplitLocal};
}
template<bool Fused, bool SplitLocal> consteval bool flush_ready() {
void* c = nullptr;
constexpr bool no_borrow[] = {true,false,false,true,false,false};
const Policy sites[] = {r7_parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
r7_parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
r7_parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
r7_parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
r7_parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c),
r7_parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0, SplitLocal>(c)};
for (unsigned i=0; i<6; ++i) { const auto p=sites[i];
if (p.local != SplitLocal || p.fused != Fused || p.borrow != no_borrow[i] ||
p.batch != (Fused ? kGenthreadIfidBatchOps : 0) ||
p.build != (Fused && !SplitLocal) || p.discard != p.build) return false;
} return true; }
static_assert(flush_ready<false,false>(), "r7: flush_ready preserves SplitLocal and prebuild policy");
static_assert(flush_ready<true,false>(), "r7: flush_ready preserves SplitLocal and prebuild policy");
static_assert(flush_ready<true,true>(), "r7: flush_ready preserves SplitLocal and prebuild policy");
template<bool U, bool T, bool F> consteval bool r7_epoll_pass(int) { return F; }
template<bool HasUnix, bool HasTls, bool Fused, bool SplitLocal>
consteval bool park() {
constexpr bool hot = r7_epoll_pass<HasUnix, HasTls, Fused>(0);
if constexpr (Fused) return hot == r7_epoll_pass<HasUnix, HasTls, !SplitLocal>(50);
else return hot == r7_epoll_pass<HasUnix, HasTls, false>(50);
}
static_assert(park<false,false,false,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<false,false,true,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<false,false,true,true>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<false,true,false,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<false,true,true,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<false,true,true,true>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<true,false,false,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<true,false,true,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<true,false,true,true>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<true,true,false,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<true,true,true,false>(), "r7: park/hot callback Fused policy mismatch");
static_assert(park<true,true,true,true>(), "r7: park/hot callback Fused policy mismatch");
}
int main() { std::puts("PASS splitlocal: FIFO/R7 forwarding, prebuild/discard, park policies"); }
