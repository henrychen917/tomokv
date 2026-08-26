#include <cstddef>
#include <cstdio>
#include "src/net/conn.h"

namespace tomo {

struct alignas(64) MirrorClient {
    int       fd_   = -1;
    uint32_t  rlen_ = 0;
    uint32_t  rpos_ = 0;
    uint32_t  last_interaction_s_ = 0;
    char*     rbuf_ = nullptr;
    size_t    rcap_ = 0;
    uint32_t  fill_  = 0;
    uint32_t  wsent_ = 0;
    bool      recv_armed_ = false;
    bool      send_inflight_ = false;
    bool      segmented_send_ = false;
    uint32_t  send_requested_ = 0;
    bool      serve_pending_ = false;
    bool      in_active_ = false;
    bool      closing_ = false;
    bool      dead_ = false;
    bool      scatter_barrier_ = false;
    bool      atomic_backpressure_ = false;
    bool      subscriber_mode_ = false;
    bool      blocked_ = false;
    uint64_t  id_ = 0;
    uint32_t  ifid_thread_ = 0;
    Session   session_;
    Rob<kRobWindow> rob_;
    SmallBuf<kWbufInline> buf_[2];
    SegmentQueue<8> segments_;
    iovec           send_iov_[16] = {};
    msghdr          send_msg_ = {};
    alignas(64) std::atomic<bool> retire_queued_{false};
    std::atomic<uint32_t> wb_slot_{UINT32_MAX};
    uint32_t atomic_groups_io_ = 0;
    MultiSession* multi_session_ = nullptr;
    std::atomic<uint64_t> watch_generation_{0};
    std::atomic<uint32_t> watched_refs_{0};
    std::atomic<bool> watch_dirty_{false};
    uint64_t obuf_bytes_ = 0;
    uint32_t obuf_soft_since_s_ = 0;
    bool obuf_tracking_ = false;
    bool authenticated_ = false;
    uint32_t acl_user_idx_ = 0;
    uint32_t tls_slot_ = UINT32_MAX;
};

#define SHOW(member) std::printf("%-24s %4zu..%4zu (%zu)\n", #member, \
    offsetof(MirrorClient, member), offsetof(MirrorClient, member) + \
    sizeof(((MirrorClient*)nullptr)->member), sizeof(((MirrorClient*)nullptr)->member))

}  // namespace tomo

int main() {
    using namespace tomo;
    std::printf("Client=%zu/%zu Mirror=%zu/%zu Op=%zu\n", sizeof(Client), alignof(Client),
                sizeof(MirrorClient), alignof(MirrorClient), sizeof(Op));
    SHOW(fd_); SHOW(rlen_); SHOW(rpos_); SHOW(last_interaction_s_); SHOW(rbuf_);
    SHOW(recv_armed_); SHOW(send_inflight_); SHOW(segmented_send_); SHOW(send_requested_);
    SHOW(serve_pending_); SHOW(in_active_); SHOW(closing_); SHOW(dead_); SHOW(scatter_barrier_);
    SHOW(atomic_backpressure_); SHOW(subscriber_mode_); SHOW(blocked_); SHOW(id_);
    SHOW(retire_queued_); SHOW(wb_slot_); SHOW(atomic_groups_io_); SHOW(multi_session_);
    SHOW(watch_generation_); SHOW(watched_refs_); SHOW(watch_dirty_); SHOW(obuf_bytes_);
    SHOW(obuf_soft_since_s_); SHOW(obuf_tracking_); SHOW(authenticated_); SHOW(acl_user_idx_);
    SHOW(tls_slot_);
}
