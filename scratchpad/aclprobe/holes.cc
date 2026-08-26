#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <sys/socket.h>
#include <sys/uio.h>

#include "src/net/conn.h"

#define TOMO_CLIENT_FIELDS                                                                    \
    int fd_;                                                                                  \
    uint32_t rlen_;                                                                           \
    uint32_t rpos_;                                                                           \
    uint32_t last_interaction_s_;                                                             \
    char* rbuf_;                                                                              \
    size_t rcap_;                                                                             \
    uint32_t fill_;                                                                           \
    uint32_t wsent_;                                                                          \
    bool recv_armed_;                                                                         \
    bool send_inflight_;                                                                      \
    bool segmented_send_;                                                                     \
    uint32_t send_requested_;                                                                 \
    bool serve_pending_;                                                                      \
    bool in_active_;                                                                          \
    bool closing_;                                                                            \
    bool dead_;                                                                               \
    bool scatter_barrier_;                                                                    \
    bool atomic_backpressure_;                                                                \
    bool subscriber_mode_;                                                                    \
    bool blocked_;                                                                            \
    uint64_t id_;                                                                             \
    uint32_t ifid_thread_;                                                                    \
    tomo::Session session_;                                                                   \
    tomo::Rob<tomo::kRobWindow> rob_;                                                         \
    tomo::SmallBuf<tomo::kWbufInline> buf_[2];                                                \
    tomo::SegmentQueue<8> segments_;                                                          \
    iovec send_iov_[16];                                                                      \
    msghdr send_msg_;                                                                         \
    alignas(64) std::atomic<bool> retire_queued_;                                              \
    std::atomic<uint32_t> wb_slot_;                                                           \
    uint32_t atomic_groups_io_;                                                               \
    tomo::MultiSession* multi_session_;                                                       \
    std::atomic<uint64_t> watch_generation_;                                                  \
    std::atomic<uint32_t> watched_refs_;                                                      \
    std::atomic<bool> watch_dirty_;                                                           \
    uint64_t obuf_bytes_;                                                                     \
    uint32_t obuf_soft_since_s_;                                                              \
    bool obuf_tracking_;                                                                      \
    bool authenticated_

struct ClientMirror {
    TOMO_CLIENT_FIELDS;
    uint32_t acl_user_idx_;
};

static_assert(sizeof(ClientMirror) == sizeof(tomo::Client), "mirror is not declaration-faithful");

int main() {
    std::printf("sizeof(Client)=%zu alignof(Client)=%zu\n", sizeof(tomo::Client),
                alignof(tomo::Client));
    std::printf("sizeof(Op)=%zu\n", sizeof(tomo::Op));
    std::printf("sizeof(ClientMirror)=%zu (faithful=%s)\n", sizeof(ClientMirror),
                sizeof(ClientMirror) == sizeof(tomo::Client) ? "yes" : "no");
    std::printf("rpos end=%zu rbuf=%zu gap=%zu\n",
                offsetof(ClientMirror, rpos_) + sizeof(ClientMirror::rpos_),
                offsetof(ClientMirror, rbuf_),
                offsetof(ClientMirror, rbuf_) -
                    (offsetof(ClientMirror, rpos_) + sizeof(ClientMirror::rpos_)));
    std::printf("watch_dirty end=%zu obuf_bytes=%zu soft_since=%zu tracking=%zu auth=%zu\n",
                offsetof(ClientMirror, watch_dirty_) + sizeof(ClientMirror::watch_dirty_),
                offsetof(ClientMirror, obuf_bytes_), offsetof(ClientMirror, obuf_soft_since_s_),
                offsetof(ClientMirror, obuf_tracking_), offsetof(ClientMirror, authenticated_));
    std::printf("acl_user_idx=%zu end=%zu sizeof=%zu slack=%zu\n",
                offsetof(ClientMirror, acl_user_idx_),
                offsetof(ClientMirror, acl_user_idx_) + sizeof(ClientMirror::acl_user_idx_),
                sizeof(ClientMirror), sizeof(ClientMirror) -
                    (offsetof(ClientMirror, acl_user_idx_) + sizeof(ClientMirror::acl_user_idx_)));
}

#undef TOMO_CLIENT_FIELDS
